"""Bounded, offline game-action evidence and conservative practice recommendations.

This is a *policy advisor*, not an input driver, RL trainer or proof authenticator.
Only a trusted host may submit independently observed episode outcomes. The
checksum associates an episode with evidence but does NOT authenticate it.
No I/O, network, model call, file persistence, or executable actions occur.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_Z95 = 1.959963984540054


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be an ASCII identifier of 1-64 characters")
    return value


@dataclass(frozen=True)
class Episode:
    """One host-verified outcome from one authorized game's action/goal pair.

    `seq` increases strictly in a game+session, even across different states.
    A host must map its own telemetry to success/safety; an LLM must not create
    this record from a screenshot, a chat message or its own prediction.
    """

    game: str
    session: str
    seq: int
    state: str
    action: str
    success: bool
    unsafe: bool
    elapsed_ms: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        for label in ("game", "session", "state", "action"):
            _id(getattr(self, label), label)
        if type(self.seq) is not int or not 1 <= self.seq <= 1_000_000_000:
            raise ValueError("seq must be a positive bounded integer")
        if type(self.elapsed_ms) is not int or not 0 <= self.elapsed_ms <= 600_000:
            raise ValueError("elapsed_ms must be a bounded nonnegative integer")
        if type(self.success) is not bool or type(self.unsafe) is not bool:
            raise ValueError("success and unsafe must be explicit booleans")
        if self.unsafe and self.success:
            raise ValueError("An unsafe episode cannot count as a safe success")
        if type(self.evidence_sha256) is not str or _SHA.fullmatch(self.evidence_sha256) is None:
            raise ValueError("Evidence checksum must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class ActionEvidence:
    action: str
    trials: int
    successes: int
    unsafe_observations: int
    success_lower_95: float
    mean_duration_ms: float | None


@dataclass(frozen=True)
class Advice:
    action: str | None
    reason: str
    evidence: ActionEvidence | None
    mode: str


def wilson_lower_95(successes: int, trials: int) -> float:
    """Conservative bound used for decisions, not a causal success guarantee."""
    if type(trials) is not int or type(successes) is not int or not 0 <= successes <= trials:
        raise ValueError("Invalid binomial counts")
    if trials == 0:
        return 0.0
    p = successes / trials
    z2 = _Z95 * _Z95
    return max(0.0, (p + z2 / (2 * trials) - _Z95 * sqrt(
        p * (1 - p) / trials + z2 / (4 * trials * trials)
    )) / (1 + z2 / trials))


class GameSkillMemory:
    """In-memory evidence ledger: fixed capacities, no hidden model calls.

    `advise(..., mode='play')` only suggests sufficiently verified actions;
    `mode='practice'` suggests experiments only for an explicitly approved
    isolated sandbox. All results are advisory data, never game controls.
    """

    def __init__(self, *, max_sessions: int = 256, max_episodes: int = 4096):
        if (type(max_sessions) is not int or not 1 <= max_sessions <= 1024
                or type(max_episodes) is not int or not 1 <= max_episodes <= 16384):
            raise ValueError("Memory capacities must be positive and bounded")
        self._max_sessions = max_sessions
        self._max_episodes = max_episodes
        self._seq: dict[tuple[str, str], int] = {}
        # [independent_sessions, sessions_all_successful, sessions_unsafe,
        #  duration_ms_of_successful_sessions]. Multiple attempts in one session
        # cannot create fake independent samples for Wilson confidence.
        self._counts: dict[tuple[str, str, str], list[int]] = {}
        self._session_outcomes: dict[tuple[str, str, str, str], tuple[bool, bool, int]] = {}
        self._total = 0

    def record(self, episode: Episode, *, trusted_host: bool = False) -> None:
        """Accept independently scored data via a privileged caller (NOT proof of origin)."""
        if trusted_host is not True:
            raise PermissionError("Only a trusted game host may record scored episodes")
        if type(episode) is not Episode:
            raise TypeError("Expected a validated Episode")
        session = (episode.game, episode.session)
        previous = self._seq.get(session)
        if previous is not None and episode.seq <= previous:
            raise ValueError("Replay or out-of-order episode rejected")
        if session not in self._seq and len(self._seq) >= self._max_sessions:
            raise OverflowError("Session evidence capacity reached; ask host to start a new ledger")
        if self._total >= self._max_episodes:
            raise OverflowError("Episode evidence capacity reached; ask host to rotate the ledger")
        key = (episode.game, episode.state, episode.action)
        per_session = (*key, episode.session)
        old = self._session_outcomes.get(per_session)
        counts = self._counts.setdefault(key, [0, 0, 0, 0])
        # A session is called successful only if every observed attempt was
        # successful, and unsafe if ANY observed attempt was unsafe. Duration
        # is the slowest successful attempt in that session (pessimistic).
        was_success = old[0] if old is not None else True
        was_unsafe = old[1] if old is not None else False
        success = was_success and episode.success
        unsafe = was_unsafe or episode.unsafe
        duration = max(old[2], episode.elapsed_ms) if old is not None else episode.elapsed_ms
        if old is not None:
            counts[1] -= int(old[0])
            counts[2] -= int(old[1])
            counts[3] -= old[2] if old[0] else 0
        else:
            counts[0] += 1
        counts[1] += int(success)
        counts[2] += int(unsafe)
        counts[3] += duration if success else 0
        self._session_outcomes[per_session] = (success, unsafe, duration)
        self._seq[session] = episode.seq
        self._total += 1

    def evidence(self, game: str, state: str, action: str) -> ActionEvidence:
        _id(game, "game")
        _id(state, "state")
        _id(action, "action")
        n, wins, unsafe, duration = self._counts.get((game, state, action), [0, 0, 0, 0])
        return ActionEvidence(action, n, wins, unsafe,
                              round(wilson_lower_95(wins, n), 6),
                              round(duration / wins, 2) if wins else None)

    def advise(self, game: str, state: str, actions: tuple[str, ...], *,
               mode: str = "play", min_trials: int = 16,
               minimum_lower: float = 0.5, sandbox_approved: bool = False) -> Advice:
        _id(game, "game")
        _id(state, "state")
        if type(actions) is not tuple or not 1 <= len(actions) <= 32:
            raise ValueError("Provide 1..32 distinct host-allowlisted actions")
        for action in actions:
            _id(action, "action")
        if len(actions) != len(set(actions)):
            raise ValueError("Duplicate host-allowlisted actions")
        if mode not in ("play", "practice"):
            raise ValueError("Unknown advice mode")
        if type(min_trials) is not int or not 3 <= min_trials <= 256:
            raise ValueError("Require at least 3, at most 256 independent trials")
        if type(minimum_lower) not in (int, float) or not 0.5 <= minimum_lower < 1:
            raise ValueError("Conservative success threshold must be >= 0.5 and < 1")
        evidence = [self.evidence(game, state, a) for a in actions]
        safe = [e for e in evidence if not e.unsafe_observations]
        if mode == "practice":
            if sandbox_approved is not True:
                return Advice(None, "sandbox_not_approved", None, mode)
            if not safe:
                return Advice(None, "all_actions_flagged_unsafe", None, mode)
            # Least-tried safe option first, then lexical stability. This is
            # an experiment proposal, not a claim that the option will work.
            candidate = min(safe, key=lambda e: (e.trials, e.action))
            return Advice(candidate.action, "sandbox_experiment_only", candidate, mode)
        eligible = [e for e in safe if e.trials >= min_trials
                    and e.success_lower_95 >= minimum_lower]
        if not eligible:
            return Advice(None, "insufficient_safe_evidence", None, mode)
        # Prefer stronger conservative evidence, then lower observed successful
        # latency. No latency value from unobserved/failed runs is fabricated.
        selected = min(eligible, key=lambda e: (-e.success_lower_95,
                         e.mean_duration_ms if e.mean_duration_ms is not None else float("inf"), e.action))
        return Advice(selected.action, "observed_safe_success", selected, mode)

    def summary(self) -> dict[str, int]:
        """Counts only; no chat, screenshots, prompts, or evidence payloads."""
        return {"sessions": len(self._seq), "episodes": self._total,
                "state_actions": len(self._counts)}
