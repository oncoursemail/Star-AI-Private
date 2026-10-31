"""Opt-in, offline observation-to-action age gate for Star's game agents.

A correct action can be unsafe after the environment has moved on. The trusted
game-input adapter MAY use this diagnostic immediately before dispatching an
action. It does not press keys, access games, authenticate the host, confer
permission to play, or demonstrate game mastery. No text, screenshots, player
identities, or action payloads are stored. The feature is OFF by default.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


def _time(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("time must be a finite nonnegative number")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("time must be a finite nonnegative number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("time must be a finite nonnegative number")
    return number


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical bounded identifier")
    return value


def _nearest_rank_ms(samples: deque[float], fraction: float) -> float | None:
    """Anonymous nearest-rank latency percentile over at most 64 accepted actions."""
    if not samples:
        return None
    values = sorted(samples)
    return round(values[math.ceil(fraction * len(values)) - 1], 3)


@dataclass(frozen=True)
class GameActionTiming:
    """Timing only; the host supplies the actual action outside this module."""

    session_id: str
    game_scope: str
    observation_seq: int
    observed_at_s: float
    decided_at_s: float
    host_observed: bool = False

    def __post_init__(self) -> None:
        _id(self.session_id, "session_id")
        _id(self.game_scope, "game_scope")
        if type(self.observation_seq) is not int or not 0 <= self.observation_seq < 2**63:
            raise ValueError("observation_seq must be a bounded nonnegative integer")
        observed = _time(self.observed_at_s)
        decided = _time(self.decided_at_s)
        if decided < observed:
            raise ValueError("decision cannot precede its observation")
        if type(self.host_observed) is not bool:
            raise ValueError("host_observed must be a strict boolean")


@dataclass(frozen=True)
class ActionAgeVerdict:
    """A host hint; NOT permission to inject game inputs."""

    fresh: bool
    reason: str
    observation_age_ms: float | None
    authorizes_game_input: bool = False


class GameActionFreshnessGate:
    """Reject late, replayed or cross-session observations at an input boundary.

    Calls share one monotonic host-clock domain. An authenticated host must
    supply trusted timestamps and independently enforce allowed-game policy.
    This layer deliberately does not infer provenance from chat/model claims.
    """

    def __init__(self, *, max_observation_age_ms: float = 250.0) -> None:
        max_age = _time(max_observation_age_ms)
        if not 1.0 <= max_age <= 5000.0:
            raise ValueError("max_observation_age_ms must be 1..5000")
        self._max_age_ms = max_age
        self._lock = RLock()
        self._enabled = False
        self._session = ""
        self._scope = ""
        self._last_sequence = -1
        self._last_observed_at: float | None = None
        self._last_now: float | None = None
        # PRE-dispatch timing only; never evidence of physical keypresses.
        self._capture_to_assessment_ms: deque[float] = deque(maxlen=64)
        self._capture_to_decision_ms: deque[float] = deque(maxlen=64)
        self._decision_to_assessment_ms: deque[float] = deque(maxlen=64)
        self._counts = {
            "allowed": 0, "stale": 0, "replayed": 0,
            "unverified": 0, "wrong_session": 0, "bad_clock": 0,
            "out_of_order_observation": 0,
        }

    def enable(self, *, owner_approved: bool = False,
               session_id: str, game_scope: str) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must enable gameplay freshness checks")
        session = _id(session_id, "session_id")
        scope = _id(game_scope, "game_scope")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before starting another game session")
            self._enabled = True
            self._session = session
            self._scope = scope
            self._last_sequence = -1
            self._last_observed_at = None
            self._last_now = None
            self._capture_to_assessment_ms.clear()
            self._capture_to_decision_ms.clear()
            self._decision_to_assessment_ms.clear()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._session = self._scope = ""
            self._last_sequence = -1
            self._last_observed_at = None
            self._last_now = None
            self._capture_to_assessment_ms.clear()
            self._capture_to_decision_ms.clear()
            self._decision_to_assessment_ms.clear()

    def assess(self, timing: GameActionTiming, *, now_s: float) -> ActionAgeVerdict:
        if not isinstance(timing, GameActionTiming):
            raise TypeError("assess requires GameActionTiming")
        now = _time(now_s)
        with self._lock:
            if not self._enabled:
                return ActionAgeVerdict(False, "disabled", None)
            if not timing.host_observed:
                self._counts["unverified"] += 1
                return ActionAgeVerdict(False, "unverified", None)
            if timing.session_id != self._session or timing.game_scope != self._scope:
                self._counts["wrong_session"] += 1
                return ActionAgeVerdict(False, "wrong_session", None)
            if (timing.decided_at_s > now or timing.observed_at_s > now
                    or (self._last_now is not None and now < self._last_now)):
                self._counts["bad_clock"] += 1
                return ActionAgeVerdict(False, "bad_clock", None)
            self._last_now = now
            if timing.observation_seq <= self._last_sequence:
                self._counts["replayed"] += 1
                return ActionAgeVerdict(False, "replayed", None)
            age_ms = (now - timing.observed_at_s) * 1000.0
            if not math.isfinite(age_ms) or age_ms > self._max_age_ms:
                self._counts["stale"] += 1
                return ActionAgeVerdict(False, "stale", None)
            # A larger queue sequence does not establish a newer capture.
            if (self._last_observed_at is not None
                    and timing.observed_at_s <= self._last_observed_at):
                self._counts["out_of_order_observation"] += 1
                return ActionAgeVerdict(False, "out_of_order_observation", None)
            self._last_sequence = timing.observation_seq
            self._last_observed_at = timing.observed_at_s
            self._capture_to_assessment_ms.append(age_ms)
            self._capture_to_decision_ms.append(
                (timing.decided_at_s - timing.observed_at_s) * 1000.0,
            )
            self._decision_to_assessment_ms.append(
                (now - timing.decided_at_s) * 1000.0,
            )
            self._counts["allowed"] += 1
            return ActionAgeVerdict(True, "fresh", round(age_ms, 3))

    def metrics(self) -> dict[str, int | bool | float | None]:
        """Accepted pre-dispatch age attribution, not physical input timestamps."""
        with self._lock:
            return {
                **self._counts,
                "enabled": self._enabled,
                "accepted_samples": len(self._capture_to_assessment_ms),
                "capture_to_assessment_p50_ms": _nearest_rank_ms(
                    self._capture_to_assessment_ms, 0.50,
                ),
                "capture_to_assessment_p95_ms": _nearest_rank_ms(
                    self._capture_to_assessment_ms, 0.95,
                ),
                "capture_to_decision_p50_ms": _nearest_rank_ms(
                    self._capture_to_decision_ms, 0.50,
                ),
                "capture_to_decision_p95_ms": _nearest_rank_ms(
                    self._capture_to_decision_ms, 0.95,
                ),
                "decision_to_assessment_p50_ms": _nearest_rank_ms(
                    self._decision_to_assessment_ms, 0.50,
                ),
                "decision_to_assessment_p95_ms": _nearest_rank_ms(
                    self._decision_to_assessment_ms, 0.95,
                ),
            }


__all__ = ["GameActionTiming", "ActionAgeVerdict", "GameActionFreshnessGate"]
