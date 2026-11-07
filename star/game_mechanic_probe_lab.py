"""STAR's evidence-gated *offline* mechanic comparison and active probes.

A small, owner-curated catalogue asks which of TWO symbolic actions might work
better in the exact same game/version/objective/situation. All evidence is
obtained from GameplaySkillBank's independently signed PRACTICE aggregates.
The lab uses ActivePracticePlanner to reserve a single next probe, so its
advice remains compatible with existing host-assigned run IDs and checks.

This is not causal inference: the data may be confounded by level seeds,
player skill, learning, or time. A promising practice result must pass a
separate independently held-out transfer evaluation. This module never
reads validation evidence, executes tools, controls games, publishes streams,
or authorizes actions. Its default state is OFF.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Sequence

from .active_practice import ActivePracticePlanner
from .gameplay_skill_bank import GameplaySkillBank, PracticeEvidence, wilson_lower
from .stream_budget import StreamTelemetry, advise_workload

_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _symbol(value: object, field: str) -> str:
    if type(value) is not str or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded symbolic ID")
    return value


def _timestamp(value: object) -> int:
    if type(value) is not int or not 0 < value <= 10**11:
        raise ValueError("now_unix_s must be a positive Unix integer")
    return value


def _bounds(successes: int, trials: int) -> tuple[float, float]:
    """Two-sided Wilson intervals, used as *practice* screening only."""
    if trials == 0:
        return 0.0, 1.0
    return (wilson_lower(successes, trials),
            1.0 - wilson_lower(trials - successes, trials))


@dataclass(frozen=True)
class MechanicHypothesis:
    experiment_id: str
    situation_id: str
    baseline_action_id: str
    candidate_action_id: str
    min_trials_per_arm: int = 12
    max_trials_per_arm: int = 36
    minimum_effect: float = 0.08

    def __post_init__(self) -> None:
        for field in ("experiment_id", "situation_id",
                      "baseline_action_id", "candidate_action_id"):
            _symbol(getattr(self, field), field)
        if self.baseline_action_id == self.candidate_action_id:
            raise ValueError("two different actions are required")
        if (type(self.min_trials_per_arm) is not int
                or not 8 <= self.min_trials_per_arm <= 32
                or type(self.max_trials_per_arm) is not int
                or not self.min_trials_per_arm <= self.max_trials_per_arm <= 128):
            raise ValueError("invalid bounded practice arm budgets")
        if (type(self.minimum_effect) not in (float, int)
                or not math.isfinite(float(self.minimum_effect))
                or not 0.02 <= float(self.minimum_effect) <= 0.25):
            raise ValueError("minimum_effect must be 0.02..0.25")


@dataclass(frozen=True)
class MechanicAdvice:
    status: str
    reason: str
    experiment_id: str | None = None
    action_id: str | None = None
    ticket: int | None = None
    expected_run_id: str | None = None
    baseline_trials: int = 0
    candidate_trials: int = 0
    baseline_successes: int = 0
    candidate_successes: int = 0
    provisional_preference: str | None = None
    authorized_to_play: bool = False


@dataclass(frozen=True)
class _Comparison:
    definition: MechanicHypothesis
    baseline: PracticeEvidence
    candidate: PracticeEvidence
    verdict: str | None

    @property
    def total(self) -> int:
        return self.baseline.trials + self.candidate.trials


class GameMechanicProbeLab:
    """Coordinated, signed-evidence offline comparison across curated pairs.

    The lab checks resource safety before consulting the ledger or reserving
    actions. Owner enabling this lab does not enable the ActivePracticePlanner:
    each must be independently approved by its trusted host. Only an existing
    authorised Studio runner can execute a returned action reservation.
    """

    def __init__(
        self, bank: GameplaySkillBank, planner: ActivePracticePlanner, *,
        game_id: str, game_version: str, objective_id: str,
        hypotheses: Sequence[MechanicHypothesis],
    ) -> None:
        if not isinstance(bank, GameplaySkillBank) or not isinstance(planner, ActivePracticePlanner):
            raise TypeError("existing signed practice bank and planner are required")
        if getattr(planner, "_bank", None) is not bank:
            raise ValueError("planner and lab must use the same signed evidence bank")
        self._scope = (_symbol(game_id, "game_id"),
                       _symbol(game_version, "game_version"),
                       _symbol(objective_id, "objective_id"))
        if (type(hypotheses) not in (tuple, list) or
                not 1 <= len(hypotheses) <= 32 or
                any(not isinstance(h, MechanicHypothesis) for h in hypotheses)):
            raise ValueError("supply 1..32 curated hypotheses")
        ids = [h.experiment_id for h in hypotheses]
        situations = [h.situation_id for h in hypotheses]
        # This prevents one arm's evidence from being reused in another
        # comparison with a changed hypothesis within one lab.
        if len(set(ids)) != len(ids) or len(set(situations)) != len(situations):
            raise ValueError("each hypothesis and situation must be unique")
        self._bank = bank
        self._planner = planner
        self._hypotheses = tuple(sorted(hypotheses, key=lambda h: h.experiment_id))
        self._lock = RLock()
        self._enabled = False
        self._clock_s: int | None = None
        self._pending_ticket: int | None = None
        self._pending_at: int | None = None
        self._stats = {"suggestions": 0, "accepted_signed": 0,
                       "rejected_unverified": 0, "deferred": 0, "screened": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted owner must explicitly enable offline experiments")
        with self._lock:
            if self._enabled:
                raise RuntimeError("already enabled")
            self._enabled = True
            self._clock_s = None

    def disable(self) -> None:
        """Stop offering work. Host must also cancel/disable shared planner."""
        with self._lock:
            self._enabled = False
            self._pending_ticket = None
            self._pending_at = None
            self._clock_s = None

    def _advance(self, now_unix_s: int) -> int:
        now = _timestamp(now_unix_s)
        if self._clock_s is not None and now < self._clock_s:
            raise ValueError("mechanic lab clock went backwards")
        self._clock_s = now
        return now

    def _compare(self, hypothesis: MechanicHypothesis, now: int) -> _Comparison:
        rows = self._bank.practice_evidence(
            *self._scope, hypothesis.situation_id, now_unix_s=now)
        evidence = {row.action_id: row for row in rows}
        b = evidence.get(hypothesis.baseline_action_id,
                         PracticeEvidence(hypothesis.baseline_action_id, 0, 0, 0))
        c = evidence.get(hypothesis.candidate_action_id,
                         PracticeEvidence(hypothesis.candidate_action_id, 0, 0, 0))
        verdict = None
        if min(b.trials, c.trials) >= hypothesis.min_trials_per_arm:
            b_low, b_high = _bounds(b.successes, b.trials)
            c_low, c_high = _bounds(c.successes, c.trials)
            margin = hypothesis.minimum_effect
            if c_low > b_high + margin:
                verdict = "provisional_candidate"
            elif b_low > c_high + margin:
                verdict = "retain_baseline"
        # The shared planner may have a LOWER per-arm cap than the
        # hypothesis (defaults: 24 versus 36). Never keep requesting actions
        # the planner cannot reserve; report a bounded inconclusive screen.
        effective_cap = min(
            hypothesis.max_trials_per_arm, self._planner.max_trials_per_action
        )
        if verdict is None and min(b.trials, c.trials) >= effective_cap:
            verdict = "inconclusive"
        return _Comparison(hypothesis, b, c, verdict)

    def suggest(
        self, *, now_unix_s: int, telemetry: StreamTelemetry | None,
    ) -> MechanicAdvice:
        """Suggest the next information-gathering OFFLINE practice reservation."""
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be a trusted StreamTelemetry or None")
        with self._lock:
            now = self._advance(now_unix_s)

            def defer(reason: str) -> MechanicAdvice:
                self._stats["deferred"] += 1
                return MechanicAdvice("deferred", reason)

            if not self._enabled:
                return defer("owner_opt_in_missing")
            if self._pending_ticket is not None:
                # Mirror the actual shared planner's configured TTL,
                # not the maximum POSSIBLE 600-second lifetime. Otherwise
                # default 90-second tickets would stall practice for 601s.
                # The planner itself expires the old ticket before reissuing.
                if (self._pending_at is None or
                        now - self._pending_at <= self._planner.reservation_seconds):
                    return defer("signed_practice_pending")
                self._pending_ticket = self._pending_at = None
            if telemetry is None:
                return defer("trusted_telemetry_missing")
            if telemetry.live:
                return defer("never_experiment_while_live")
            if telemetry.game_active and telemetry.game_fps < 50.0:
                return defer("game_fps_below_practice_floor")
            if telemetry.speech_backlog_ms > 250.0:
                return defer("speech_backlog_protection")
            if not advise_workload("training", telemetry).allowed:
                return defer("insufficient_offline_compute_headroom")

            comparisons = tuple(self._compare(h, now) for h in self._hypotheses)
            unfinished = [x for x in comparisons if x.verdict is None]
            if not unfinished:
                # Reporting a PRACTICE preference is not proving mastery.
                # No action is reserved when all experiments are screened.
                best = comparisons[0]
                self._stats["screened"] += 1
                return MechanicAdvice(
                    best.verdict or "inconclusive",
                    "signed_practice_only_independent_holdout_required",
                    experiment_id=best.definition.experiment_id,
                    baseline_trials=best.baseline.trials,
                    candidate_trials=best.candidate.trials,
                    baseline_successes=best.baseline.successes,
                    candidate_successes=best.candidate.successes,
                    provisional_preference=(
                        best.definition.candidate_action_id if best.verdict == "provisional_candidate"
                        else best.definition.baseline_action_id if best.verdict == "retain_baseline"
                        else None),
                )

            # Balance arms and explore every situation before oversampling
            # one. This is NOT randomized assignment or causal identification.
            selected = min(unfinished, key=lambda x: (
                min(x.baseline.trials, x.candidate.trials),
                x.total, x.definition.experiment_id))
            h = selected.definition
            effective_cap = min(
                h.max_trials_per_arm, self._planner.max_trials_per_action
            )
            if selected.baseline.trials >= effective_cap:
                arm = h.candidate_action_id
            elif selected.candidate.trials >= effective_cap:
                arm = h.baseline_action_id
            elif selected.baseline.trials <= selected.candidate.trials:
                arm = h.baseline_action_id
            else:
                arm = h.candidate_action_id
            reserve = self._planner.reserve(
                *self._scope, h.situation_id, (arm,),
                now_unix_s=now, telemetry=telemetry)
            if reserve.status != "practice_candidate":
                return defer("underlying_practice_planner_" + reserve.reason)
            if reserve.ticket is None or reserve.expected_run_id is None:
                return defer("underlying_practice_reservation_invalid")
            self._pending_ticket = reserve.ticket
            self._pending_at = now
            self._stats["suggestions"] += 1
            return MechanicAdvice(
                "practice_candidate", "balanced_probe_not_skill_mastery",
                h.experiment_id, arm, reserve.ticket, reserve.expected_run_id,
                selected.baseline.trials, selected.candidate.trials,
                selected.baseline.successes, selected.candidate.successes,
            )

    def finish(
        self, ticket: int, *, now_unix_s: int,
        host_reports_recorded: bool = False,
    ) -> bool:
        """Accept only the exact planner-reserved independently signed run."""
        if type(ticket) is not int or ticket < 1 or type(host_reports_recorded) is not bool:
            raise ValueError("valid ticket and explicit host receipt flag required")
        with self._lock:
            now = self._advance(now_unix_s)
            if not self._enabled or ticket != self._pending_ticket:
                return False
            # If no host receipt exists, the underlying planner itself
            # rejects this run; no fabricated win enters the evidence bank.
            verified = self._planner.finish(
                ticket, now_unix_s=now, host_reports_recorded=host_reports_recorded)
            self._pending_ticket = self._pending_at = None
            self._stats["accepted_signed" if verified else "rejected_unverified"] += 1
            return verified

    def metrics(self) -> dict[str, int | bool]:
        """Do not leak private trials, receipts, game IDs or player details."""
        with self._lock:
            return {**self._stats, "enabled": self._enabled,
                    "pending": self._pending_ticket is not None,
                    "hypotheses": len(self._hypotheses)}


__all__ = ["MechanicHypothesis", "MechanicAdvice", "GameMechanicProbeLab"]
