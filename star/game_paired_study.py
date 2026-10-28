"""Preregistered, host-only, matched A/B game-mechanic experiments for STAR.

The existing mechanic probe lab can find associations from signed practice
aggregates; this separate study controls allocation *before* observing
outcomes. Each owner-curated scenario is attempted once with each action.
A secret-balanced AB/BA ordering reduces, but cannot eliminate, order effects.

No controls, gameplay, streams, neural training, claims of mastery or
holdout access. The host must independently reset the same scenario and
verify its initial state; an HMAC receipt proves signer provenance only.
The owner, not an AI model or chat participant, holds randomization keys.
No early stopping or per-trial outcome feedback is available to a planner.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math
import re
from threading import RLock, get_ident

from .gameplay_skill_bank import GameTrial, GameplaySkillBank
from .stream_budget import StreamTelemetry, advise_workload

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_UNIX = 10**11


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded symbolic identifier")
    return value


def _unix(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_UNIX:
        raise ValueError("trusted positive integer Unix time required")
    return value


def _p_one_sided(wins: int, losses: int) -> float:
    """Exact one-sided matched-pair discordance test; n <= 64 by design."""
    n = wins + losses
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (1 << n)


@dataclass(frozen=True)
class PairedStudyProtocol:
    """Curated *offline practice* pairs, frozen before any outcome is observed."""

    study_id: str
    game_id: str
    game_version: str
    objective_id: str
    baseline_action_id: str
    candidate_action_id: str
    scenario_ids: tuple[str, ...]
    registered_unix_s: int
    min_complete_pairs: int = 8
    minimum_lift: float = 0.10

    def __post_init__(self) -> None:
        for field in ("study_id", "game_id", "game_version", "objective_id",
                      "baseline_action_id", "candidate_action_id"):
            _id(getattr(self, field), field)
        if self.baseline_action_id == self.candidate_action_id:
            raise ValueError("two distinct predeclared actions required")
        if (type(self.scenario_ids) is not tuple
                or not 8 <= len(self.scenario_ids) <= 64
                or len(self.scenario_ids) % 2 != 0
                or any(type(x) is not str or _ID.fullmatch(x) is None
                       for x in self.scenario_ids)
                or len(set(self.scenario_ids)) != len(self.scenario_ids)):
            raise ValueError("require 8..64 unique paired scenarios, even count")
        if (type(self.min_complete_pairs) is not int
                or not 8 <= self.min_complete_pairs <= len(self.scenario_ids)):
            raise ValueError("invalid preregistered minimum complete pairs")
        if (type(self.minimum_lift) not in (int, float)
                or not math.isfinite(float(self.minimum_lift))
                or not 0.05 <= self.minimum_lift <= 0.40):
            raise ValueError("minimum_lift must be 0.05..0.40")
        _unix(self.registered_unix_s)


@dataclass(frozen=True)
class PairedReservation:
    """Symbolic host task; never permission to control a game or publish."""

    ticket: str
    situation_id: str
    action_id: str
    expected_run_id: str
    expires_unix_s: int
    authorized_to_play: bool = False
    authorized_to_broadcast: bool = False


@dataclass(frozen=True)
class PairedStudyReport:
    """OWNER-ONLY aggregate; exploratory, not causal proof or skill mastery."""

    status: str
    complete_pairs: int
    dropped_pairs: int
    candidate_wins: int
    baseline_wins: int
    ties: int
    paired_success_lift: float | None
    exact_one_sided_p: float | None
    authorized_to_play: bool = False
    authorized_to_promote: bool = False


class PairedGameStudy:
    """Session-local, one-flight randomized study with strict signed outcomes.

    A restart or disable irrevocably abandons this study. It is intentionally
    not resumed from untrusted agent memory; a persistent implementation would
    require transactional, signed preregistration and recovery.
    """

    def __init__(
        self, bank: GameplaySkillBank, protocol: PairedStudyProtocol, *,
        randomization_key: bytes, reservation_ttl_s: int = 180,
    ) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("independently signed gameplay bank required")
        if not isinstance(protocol, PairedStudyProtocol):
            raise TypeError("a frozen paired study protocol is required")
        if type(randomization_key) is not bytes or len(randomization_key) < 32:
            raise ValueError("host-only randomization key must have 32+ bytes")
        if type(reservation_ttl_s) is not int or not 30 <= reservation_ttl_s <= 600:
            raise ValueError("reservation_ttl_s must be 30..600")
        self._bank = bank
        self._protocol = protocol
        self._key = randomization_key
        self._ttl = reservation_ttl_s
        self._owner_thread = get_ident()
        self._lock = RLock()
        self._enabled = False
        self._aborted = False
        self._contaminated = False
        self._index = 0
        self._arm_index = 0
        self._pending: PairedReservation | None = None
        self._issued_at = 0
        self._last_clock: int | None = None
        self._recorded: dict[str, dict[str, tuple[str, str]]] = {
            scene: {} for scene in protocol.scenario_ids
        }
        self._dropped: set[str] = set()
        self._stats = dict(issued=0, signed=0, rejected=0, expired=0, deferred=0)

    def _thread(self) -> None:
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal the study to the gameplay ledger owner thread")

    def _time(self, now_unix_s: int) -> int:
        now = _unix(now_unix_s)
        if self._last_clock is not None and now < self._last_clock:
            raise ValueError("study clock moved backwards")
        self._last_clock = now
        return now

    def _digest(self, purpose: str, *parts: object) -> str:
        payload = ("\x00".join((purpose, self._protocol.study_id,
                              str(self._protocol.registered_unix_s),
                              *(str(p) for p in parts)))).encode("ascii")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def _actions(self, index: int) -> tuple[str, str]:
        # Each consecutive two scenarios contain one AB and one BA order.
        # The HMAC chooses which comes first; first-arm totals remain equal.
        bit = int(self._digest("order", index // 2)[:2], 16) & 1
        if index % 2:
            bit ^= 1
        a, b = (self._protocol.baseline_action_id,
                self._protocol.candidate_action_id)
        return (a, b) if bit == 0 else (b, a)

    def _check_contamination(self, now: int) -> None:
        """Any unassigned signed PRACTICE event invalidates inference.

        Never touch validation/holdout counts. A corrupted signature raises
        inside practice_evidence and is not silently converted to a trial.
        """
        p = self._protocol
        for scene in p.scenario_ids:
            rows = self._bank.practice_evidence(
                p.game_id, p.game_version, p.objective_id, scene, now_unix_s=now)
            expected = self._recorded[scene]
            actual = {r.action_id: r.trials for r in rows}
            if actual != {action: 1 for action in expected}:
                self._contaminated = True
                raise RuntimeError("study contaminated by external or stale practice evidence")

    def enable(self, *, owner_approved: bool = False, now_unix_s: int) -> None:
        if owner_approved is not True:
            raise PermissionError("a trusted host must explicitly opt into the study")
        with self._lock:
            self._thread()
            now = self._time(now_unix_s)
            if self._enabled or self._aborted or self._index or self._contaminated:
                raise RuntimeError("study cannot be restarted or re-registered")
            if now < self._protocol.registered_unix_s:
                raise ValueError("study must be registered before the first assignment")
            self._check_contamination(now)
            self._enabled = True

    def disable(self) -> None:
        """Abort permanently; never reuse a partly observed experiment."""
        with self._lock:
            self._thread()
            self._pending = None
            self._enabled = False
            self._aborted = True

    def _drop_scene(self, *, expired: bool = False) -> None:
        if self._index >= len(self._protocol.scenario_ids):
            return
        self._dropped.add(self._protocol.scenario_ids[self._index])
        self._pending = None
        self._arm_index = 0
        self._index += 1
        if expired:
            self._stats["expired"] += 1

    def next_assignment(
        self, *, now_unix_s: int, telemetry: StreamTelemetry | None,
    ) -> PairedReservation | None:
        """Admit one symbolic offline action only with suitable host telemetry."""
        with self._lock:
            self._thread()
            now = self._time(now_unix_s)
            if not self._enabled or self._aborted or self._contaminated:
                return None
            if (self._pending is not None
                    and now > self._pending.expires_unix_s):
                self._drop_scene(expired=True)
            if self._index >= len(self._protocol.scenario_ids):
                return None
            # Cheap resource preflight before consulting the signed ledger.
            # Even existing reservations must not be returned while LIVE.
            if (not isinstance(telemetry, StreamTelemetry)
                    or telemetry.live
                    or telemetry.speech_backlog_ms > 250
                    or (telemetry.game_active and telemetry.game_fps < 50)
                    or not advise_workload("training", telemetry).allowed):
                self._stats["deferred"] += 1
                return None
            # Reject an unassigned signed trial, including when the previous
            # reservation is still pending and someone tries to reuse it.
            self._check_contamination(now)
            if self._pending is not None:
                return self._pending
            scene = self._protocol.scenario_ids[self._index]
            action = self._actions(self._index)[self._arm_index]
            run_id = "cx_" + self._digest("run", scene, action)[:40]
            ticket = self._digest("ticket", scene, action, self._index)[:40]
            self._pending = PairedReservation(
                ticket, scene, action, run_id, now + self._ttl,
            )
            self._issued_at = now
            self._stats["issued"] += 1
            return self._pending

    def accept_signed_trial(
        self, ticket: str, trial: GameTrial, *, now_unix_s: int,
        initial_state_sha256: str, reset_verified: bool = False,
    ) -> bool:
        """Accept an EXACT bank-verified outcome, not a claimed successful run.

        The trusted host must attest identical initial state after resets.
        A digest match is necessary but not sufficient for game-state parity.
        """
        with self._lock:
            self._thread()
            now = self._time(now_unix_s)
            if (not self._enabled or self._aborted or self._contaminated
                    or self._pending is None):
                return False
            pending = self._pending
            if now > pending.expires_unix_s:
                self._drop_scene(expired=True)
                return False
            p = self._protocol
            if (type(ticket) is not str or not hmac.compare_digest(ticket, pending.ticket)
                    or not isinstance(trial, GameTrial)
                    or type(initial_state_sha256) is not str
                    or _SHA.fullmatch(initial_state_sha256) is None
                    or reset_verified is not True
                    or (trial.game_id, trial.game_version, trial.objective_id,
                        trial.situation_id, trial.action_id, trial.run_id,
                        trial.split) != (p.game_id, p.game_version, p.objective_id,
                                         pending.situation_id, pending.action_id,
                                         pending.expected_run_id, "practice")
                    or not self._issued_at <= trial.observed_unix_s <= now):
                self._stats["rejected"] += 1
                return False
            # Verify exact signed outcome, including success/failure and digest.
            if not self._bank.verify_practice_trial(trial, now_unix_s=now):
                self._stats["rejected"] += 1
                return False
            self._recorded[pending.situation_id][pending.action_id] = (
                trial.outcome, initial_state_sha256)
            self._pending = None
            self._stats["signed"] += 1
            self._arm_index += 1
            if self._arm_index == 2:
                one, two = self._actions(self._index)
                first = self._recorded[pending.situation_id][one]
                second = self._recorded[pending.situation_id][two]
                if first[1] != second[1]:
                    self._dropped.add(pending.situation_id)
                self._index += 1
                self._arm_index = 0
            return True

    def owner_report(self, *, now_unix_s: int,
                     owner_approved: bool = False) -> PairedStudyReport:
        """No interim result to prevent optional stopping or practice leakage."""
        if owner_approved is not True:
            raise PermissionError("only the trusted host can inspect study outcomes")
        with self._lock:
            self._thread()
            now = self._time(now_unix_s)
            if self._aborted:
                return PairedStudyReport("aborted", 0, len(self._dropped), 0, 0, 0, None, None)
            if self._contaminated:
                return PairedStudyReport("contaminated", 0, 0, 0, 0, 0, None, None)
            if not self._enabled or self._index < len(self._protocol.scenario_ids):
                return PairedStudyReport("preregistered_not_complete", 0, 0, 0, 0, 0, None, None)
            self._check_contamination(now)
            baseline, candidate = (self._protocol.baseline_action_id,
                                   self._protocol.candidate_action_id)
            wins = losses = ties = count = 0
            for scene in self._protocol.scenario_ids:
                if scene in self._dropped:
                    continue
                outcomes = self._recorded[scene]
                if set(outcomes) != {baseline, candidate}:
                    raise RuntimeError("incomplete pair was not marked missing")
                count += 1
                b = outcomes[baseline][0] == "success"
                c = outcomes[candidate][0] == "success"
                wins += int(c and not b)
                losses += int(b and not c)
                ties += int(b == c)
            p_value = _p_one_sided(wins, losses)
            lift = (wins - losses) / count if count else None
            status = "inconclusive"
            if self._dropped:
                status = "attrition_requires_independent_review"
            elif count < self._protocol.min_complete_pairs or wins + losses < 8:
                status = "insufficient_discordant_pairs"
            elif (p_value <= 0.025
                  and lift is not None
                  and lift >= self._protocol.minimum_lift):
                status = "exploratory_candidate_preferred"
            return PairedStudyReport(
                status, count, len(self._dropped), wins, losses, ties,
                round(lift, 5) if lift is not None else None, p_value,
            )

    def metrics(self) -> dict[str, int | bool]:
        """No actions, game IDs, receipts, trial outcomes, secrets or chat data."""
        with self._lock:
            return {**self._stats, "enabled": self._enabled,
                    "aborted": self._aborted, "contaminated": self._contaminated,
                    "pending": self._pending is not None,
                    "scenarios_total": len(self._protocol.scenario_ids),
                    "scenarios_completed": self._index,
                    "invalid_pairs": len(self._dropped)}


__all__ = ["PairedStudyProtocol", "PairedReservation", "PairedStudyReport",
           "PairedGameStudy"]
