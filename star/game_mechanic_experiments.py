"""Preregistered, matched-pair PRACTICE experiments for learning game mechanics.

STAR can compare two owner-curated game actions in comparable private-playtest
situations rather than accepting a model's hunch about why an action worked.
Each pair has a random execution order and TWO separately signed, bank-stored
outcomes. Missing pairs invalidate the experiment instead of being silently
discarded. A fixed sample size avoids repeated-significance-test peeking.

This is an OFFLINE advisory analysis, not a game controller, causal proof,
model-weight trainer, live-streaming fact, or permission to access game clients.
The trusted game host must reset comparable situations between actions and
independently witness/sign genuine outcomes. Never expose hidden holdout data.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import secrets
from threading import RLock, get_ident

from .gameplay_skill_bank import GameTrial, GameplaySkillBank
from .stream_budget import StreamTelemetry, advise_workload

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_TIME = 10**11


def _id(value: object, field: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{field} must be a short symbolic ID")
    return value


def _time(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_TIME:
        raise ValueError("trusted Unix time must be a positive integer")
    return value


def exact_mcnemar_p(candidate_only: int, baseline_only: int) -> float:
    """Exact two-sided conditional binomial test on discordant matched pairs.

    Descriptive p-value for a SINGLE pre-specified, fixed-size comparison.
    It is not a confidence of game-mechanic truth or a license to keep testing
    different hypotheses until one passes.
    """
    if (type(candidate_only) is not int or type(baseline_only) is not int
            or min(candidate_only, baseline_only) < 0
            or candidate_only + baseline_only > 128):
        raise ValueError("discordant counts must be nonnegative bounded integers")
    discordants = candidate_only + baseline_only
    if discordants == 0:
        return 1.0
    tail = sum(math.comb(discordants, k)
               for k in range(min(candidate_only, baseline_only) + 1))
    return min(1.0, 2 * tail / (2 ** discordants))


@dataclass(frozen=True)
class MechanicHypothesis:
    """Host preregisters ONE comparison, objective and fixed sample size."""

    hypothesis_id: str
    game_id: str
    game_version: str
    objective_id: str
    situation_id: str
    baseline_action: str
    candidate_action: str
    target_pairs: int = 24
    minimum_effect_bps: int = 1500

    def __post_init__(self) -> None:
        for field in ("hypothesis_id", "game_id", "game_version", "objective_id",
                      "situation_id", "baseline_action", "candidate_action"):
            _id(getattr(self, field), field)
        if self.baseline_action == self.candidate_action:
            raise ValueError("comparison actions must be distinct")
        if type(self.target_pairs) is not int or not 12 <= self.target_pairs <= 64:
            raise ValueError("preregister 12..64 pairs; no adaptive stopping")
        if (type(self.minimum_effect_bps) is not int
                or not 500 <= self.minimum_effect_bps <= 5000):
            raise ValueError("minimum practical effect must be 500..5000 bps")


@dataclass(frozen=True)
class MechanicPairTicket:
    """Host-only experiment assignment, NOT permission to press a game key."""

    session: int
    serial: int
    baseline_run_id: str
    candidate_run_id: str
    execution_order: tuple[str, str]
    issued_unix_s: int
    expires_unix_s: int
    authorized_to_play: bool = False


@dataclass(frozen=True)
class MechanicFinding:
    status: str  # off | collecting | invalid | candidate_advantage | baseline_advantage | inconclusive
    accepted_pairs: int
    target_pairs: int
    candidate_only: int = 0
    baseline_only: int = 0
    effect_bps: int | None = None
    exact_two_sided_p: float | None = None
    authorized_to_play: bool = False
    established_causal_mechanic: bool = False


class PairedMechanicLab:
    """One-shot matched comparison on the existing signed PRACTICE ledger.

    The model may propose a hypothesis for human review. Only the trusted
    host constructs this preregistration and randomly assigns actions.
    Reservations never dispatch to Studio. Outcomes must already exist in the
    independently signed GameplaySkillBank before submit_pair() is called.

    Incomplete/corrupted pairs invalidate the entire fixed-size experiment.
    Results are private diagnostics until separately reviewed. A signed event
    authenticates the observer, not the accuracy of the observation.
    """

    def __init__(self, bank: GameplaySkillBank, hypothesis: MechanicHypothesis,
                 *, reservation_seconds: int = 180) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("existing signed practice bank is required")
        if not isinstance(hypothesis, MechanicHypothesis):
            raise TypeError("host-registered hypothesis required")
        if (type(reservation_seconds) is not int
                or not 30 <= reservation_seconds <= 300):
            raise ValueError("pair timeout must be 30..300 seconds")
        self._bank = bank
        self._spec = hypothesis
        self._ttl = reservation_seconds
        self._owner_thread = get_ident()  # bank SQLite must be used on this thread
        self._lock = RLock()
        self._started = False
        self._enabled = False
        self._invalid = False
        self._epoch = 0
        self._serial = 0
        self._clock: int | None = None
        self._pending: MechanicPairTicket | None = None
        self._results: list[tuple[bool, bool]] = []
        self._seen_trials: set[str] = set()
        self._seen_witnesses: set[str] = set()
        self._counts = dict(reserved=0, accepted=0, rejected=0, deferred=0)

    def _thread(self) -> None:
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal gameplay ledger to its SQLite owner thread")

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner preregistration is required")
        self._thread()
        with self._lock:
            if self._started:
                raise RuntimeError("experiment is one-shot; preregister a new ID")
            self._started = True
            self._enabled = True
            self._epoch += 1

    def disable(self) -> None:
        self._thread()
        with self._lock:
            self._enabled = False
            self._pending = None
            # A partially collected experiment is never salvageable by restart.
            self._invalid = self._invalid or bool(self._results)
            self._epoch += 1

    def _advance(self, now_unix_s: int) -> int:
        now = _time(now_unix_s)
        if self._clock is not None and now < self._clock:
            self._invalid = True
            raise ValueError("experiment host clock reversed")
        self._clock = now
        if self._pending is not None and now > self._pending.expires_unix_s:
            self._invalid = True  # no silent dropping a bad/missing pair
            self._pending = None
        return now

    def reserve(self, *, now_unix_s: int,
                telemetry: StreamTelemetry | None) -> MechanicPairTicket | None:
        """Randomize next matched pair ONLY when offline compute is available."""
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("expected trusted host StreamTelemetry")
        self._thread()
        with self._lock:
            now = self._advance(now_unix_s)
            if (not self._enabled or self._invalid or self._pending is not None
                    or len(self._results) >= self._spec.target_pairs
                    or telemetry is None or telemetry.live
                    or (telemetry.game_active and telemetry.game_fps < 50)
                    or telemetry.speech_backlog_ms > 250
                    or not advise_workload("training", telemetry).allowed):
                self._counts["deferred"] += 1
                return None
            self._serial += 1
            # Unpredictable assignment order limits host/game-state drift.
            order = ("baseline", "candidate") if secrets.randbelow(2) == 0 else (
                "candidate", "baseline")
            ticket = MechanicPairTicket(
                session=self._epoch, serial=self._serial,
                baseline_run_id="mec_" + secrets.token_hex(12),
                candidate_run_id="mec_" + secrets.token_hex(12),
                execution_order=order, issued_unix_s=now,
                expires_unix_s=now + self._ttl,
            )
            self._pending = ticket
            self._counts["reserved"] += 1
            return ticket

    def submit_pair(self, ticket: MechanicPairTicket, *,
                    baseline: GameTrial, candidate: GameTrial,
                    now_unix_s: int) -> bool:
        """Consume both exact signed outcomes or invalidate the experiment.

        The trusted host must RESET to comparable game situations between the
        two attempts. The bank does not encode or verify that reset. Ordered
        observation timestamps help detect swapped/replayed assignments.
        """
        self._thread()
        with self._lock:
            now = self._advance(now_unix_s)
            if (not self._enabled or self._invalid or self._pending is None
                    or ticket is not self._pending):
                self._counts["rejected"] += 1
                return False
            self._pending = None  # no resubmitting after a failed pair
            spec = self._spec
            try:
                if not isinstance(baseline, GameTrial) or not isinstance(candidate, GameTrial):
                    raise ValueError("two signed GameTrial records required")
                expected_scope = (
                    spec.game_id, spec.game_version, spec.objective_id, spec.situation_id
                )
                for trial, action, run in (
                    (baseline, spec.baseline_action, ticket.baseline_run_id),
                    (candidate, spec.candidate_action, ticket.candidate_run_id),
                ):
                    if ((trial.game_id, trial.game_version,
                         trial.objective_id, trial.situation_id) != expected_scope
                            or trial.action_id != action or trial.run_id != run
                            or trial.split != "practice"
                            or not ticket.issued_unix_s <= trial.observed_unix_s <= now
                            or now > ticket.expires_unix_s
                            or trial.trial_id in self._seen_trials
                            or trial.evidence_sha256 in self._seen_witnesses
                            or not self._bank.verify_practice_trial(
                                trial, now_unix_s=now)):
                        raise ValueError("untrusted, missing or cross-run outcome")
                if (baseline.trial_id == candidate.trial_id
                        or baseline.evidence_sha256 == candidate.evidence_sha256):
                    raise ValueError("pair must contain independent evidence")
                first, second = (baseline, candidate) if ticket.execution_order[0] == "baseline" else (
                    candidate, baseline)
                if first.observed_unix_s >= second.observed_unix_s:
                    raise ValueError("outcomes contradict randomized trial order")
            except Exception:
                self._invalid = True
                self._counts["rejected"] += 1
                return False
            for trial in (baseline, candidate):
                self._seen_trials.add(trial.trial_id)
                self._seen_witnesses.add(trial.evidence_sha256)
            self._results.append((baseline.outcome == "success",
                                  candidate.outcome == "success"))
            self._counts["accepted"] += 1
            return True

    def report(self, *, now_unix_s: int) -> MechanicFinding:
        """Private owner-facing statistical finding; never a public victory."""
        self._thread()
        with self._lock:
            self._advance(now_unix_s)
            n = len(self._results)
            target = self._spec.target_pairs
            if self._invalid:
                return MechanicFinding("invalid", n, target)
            if not self._enabled:
                return MechanicFinding("off", n, target)
            if n < target:
                # Fixed-sample pre-registration: no interim outcomes or p-values.
                return MechanicFinding("collecting", n, target)
            candidate_only = sum(not b and c for b, c in self._results)
            baseline_only = sum(b and not c for b, c in self._results)
            delta_bps = round(10000 * (candidate_only - baseline_only) / n)
            p = exact_mcnemar_p(candidate_only, baseline_only)
            significant = (candidate_only + baseline_only >= 8 and p <= 0.05
                           and abs(delta_bps) >= self._spec.minimum_effect_bps)
            status = ("candidate_advantage" if candidate_only > baseline_only else
                      "baseline_advantage") if significant else "inconclusive"
            return MechanicFinding(status, n, target, candidate_only,
                                   baseline_only, delta_bps, p)

    def metrics(self) -> dict[str, int | bool]:
        self._thread()
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "invalid": self._invalid, "pairs": len(self._results),
                    "pending": self._pending is not None}


__all__ = [
    "MechanicHypothesis", "MechanicPairTicket", "MechanicFinding",
    "PairedMechanicLab", "exact_mcnemar_p",
]
