"""Host-calibrated short-turn pacing for STAR's real-time gaming VTuber.

Only an actual, completed and independently witnessed audio playout can teach
the rate estimator. Speech is not generated here. Output is advisory prompt
guidance and cannot authorize TTS, game input, a broadcast or an avatar cue.

An optional owner-enabled host can pass this pacer into StarStage. New sessions
start cold; calibration never crosses a TTS route/device or gameplay regime.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from threading import RLock
from typing import cast

from .stream_director import SpeechIntent

# Natural, short reactions are more useful than long speeches during a game.
_LIMITS = {
    "owner_interrupt": 28,
    "game_danger": 8,
    "game_success": 16,
    "game_observation": 22,
    "viewer_question": 44,
    "viewer_comment": 14,
    "ambient": 14,
}
_MIN_WORDS = 4
# Defaults are conservative, NOT a claim about the user's actual speech engine.
_FALLBACK_SECONDS_PER_WORD = 0.52


def _second(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a host clock in seconds")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(result) or not 0 <= result <= 1e12:
        raise ValueError(f"invalid {field}")
    return result


@dataclass(frozen=True)
class PacingAdvice:
    status: str  # disabled | no_host_context | bounded | hold
    reason: str
    max_words: int | None = None
    measured_samples: int = 0
    authorizes_speech: bool = False
    authorizes_broadcast: bool = False
    calibration_scope: str = "none"  # intent | workload | cold_start | none


class StreamSpeechPacer:
    """Opt-in, bounded speech pacing calibrated from actual audible utterances.

    The host MUST report true first/last audible device timestamps (same clock
    as the current StreamDirector), not model token emission or TTS enqueue.
    Counts only utterances independently confirmed audible and completed.
    Statistics store no transcript, audio, viewer identity or prompt.
    """

    def __init__(
        self, *, required_samples: int = 8, history: int = 32, start_margin_s: float = 0.8, tail_margin_s: float = 0.35
    ) -> None:
        if (
            type(required_samples) is not int
            or not 5 <= required_samples <= 32
            or type(history) is not int
            or not required_samples <= history <= 64
        ):
            raise ValueError("invalid bounded sample requirements")
        self._start_margin = _second(start_margin_s, "start_margin_s")
        self._tail_margin = _second(tail_margin_s, "tail_margin_s")
        if not 0.2 <= self._start_margin <= 3 or not 0.1 <= self._tail_margin <= 2:
            raise ValueError("invalid speech timing margins")
        self._minimum = required_samples
        self._history = history
        self._lock = RLock()
        self._enabled = False
        self._route = ""
        # Key: (game_active, streaming_load, intent_kind). None is the
        # pooled workload fallback; named buckets are event-specific.
        self._samples: dict[tuple[bool, bool, str | None], deque[float]] = {}
        self._max_id = 0
        self._clock = -1.0
        self._counts = {"accepted": 0, "rejected": 0, "deferred": 0}

    def enable(self, *, owner_approved: bool = False, route_id: str) -> None:
        if owner_approved is not True:
            raise PermissionError("the owner must enable speech pacing")
        # A route identifies the exact voice model, runtime and output device;
        # host-owned, never copied from viewer text or model output.
        if (
            type(route_id) is not str
            or not 1 <= len(route_id) <= 64
            or not all(ch.isascii() and (ch.isalnum() or ch in "._-") for ch in route_id)
        ):
            raise ValueError("canonical host voice route required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable previous voice route before enabling")
            self._samples.clear()
            self._max_id = 0
            self._clock = -1.0
            self._route = route_id
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._route = ""
            self._samples.clear()
            self._max_id = 0
            self._clock = -1.0

    def observe_audible(
        self,
        *,
        route_id: str,
        sample_id: int,
        words_spoken: int,
        first_audible_s: float,
        finished_audible_s: float,
        now_s: float,
        game_active: bool,
        streaming_load: bool,
        intent_kind: str | None = None,
        host_confirmed: bool = False,
    ) -> bool:
        """Receive one *completed* independently witnessed voice sample.

        Replayed IDs, unreasonable speech rates and old/inverted timestamps
        cannot make STAR erroneously treat a fast model as calibrated.
        """
        if type(route_id) is not str or len(route_id) > 64:
            raise ValueError("invalid observed voice route ID")
        if type(sample_id) is not int or not 1 <= sample_id <= 2**63 - 1:
            raise ValueError("invalid host audio sample ID")
        if type(words_spoken) is not int or not 3 <= words_spoken <= 180:
            raise ValueError("actual spoken-word count must be 3..180")
        if intent_kind is not None and (
            type(intent_kind) is not str or intent_kind not in _LIMITS
        ):
            raise ValueError("intent_kind must match a known host stage kind")
        if any(
            type(flag) is not bool
            for flag in (
                game_active,
                streaming_load,
                host_confirmed,
            )
        ):
            raise ValueError("trusted host flags must be booleans")
        started = _second(first_audible_s, "first_audible_s")
        finished = _second(finished_audible_s, "finished_audible_s")
        now = _second(now_s, "now_s")
        duration = finished - started
        with self._lock:
            if not self._enabled or not host_confirmed or route_id != self._route:
                self._counts["rejected"] += 1
                return False
            if (
                now < self._clock
                or sample_id <= self._max_id
                or not 0 < duration <= 120
                or finished > now
                or now - finished > 10
            ):
                self._counts["rejected"] += 1
                return False
            seconds_per_word = duration / words_spoken
            if not 0.10 <= seconds_per_word <= 1.5:
                self._counts["rejected"] += 1
                return False
            self._clock = now
            self._max_id = sample_id
            # Every accepted sample contributes to a same-regime pooled
            # fallback. When the host binds the exact StagePlan.kind, it also
            # trains only that event's bucket; no text or viewer identity is
            # retained. Both histories are independently bounded.
            self._samples.setdefault(
                (game_active, streaming_load, None),
                deque(maxlen=self._history),
            ).append(seconds_per_word)
            if intent_kind is not None:
                self._samples.setdefault(
                    (game_active, streaming_load, intent_kind),
                    deque(maxlen=self._history),
                ).append(seconds_per_word)
            self._counts["accepted"] += 1
            return True

    def advise(
        self,
        intent: SpeechIntent,
        *,
        now_s: float,
        game_active: bool,
        streaming_load: bool,
        queued_audio_ms: float = 0,
        host_context_verified: bool = False,
    ) -> PacingAdvice:
        """Use current event deadline and observed playout to cap spoken length.

        This does not prove that the next model will meet its deadline: the
        host still must check speech/output freshness before any physical PCM.
        """
        if not isinstance(intent, SpeechIntent):
            raise TypeError("exact StreamDirector intent required")
        if intent.kind not in _LIMITS:
            raise ValueError("unknown stream speech kind")
        _second(intent.deadline_at, "intent.deadline_at")
        now = _second(now_s, "now_s")
        queued = _second(queued_audio_ms, "queued_audio_ms")
        if queued > 20_000:
            raise ValueError("audio backlog exceeds bounded host budget")
        if any(
            type(flag) is not bool
            for flag in (
                game_active,
                streaming_load,
                host_context_verified,
            )
        ):
            raise ValueError("trusted host context flags must be booleans")
        with self._lock:
            if not self._enabled:
                return PacingAdvice("disabled", "owner_opt_in_missing")
            if not host_context_verified:
                return PacingAdvice("no_host_context", "host_load_observation_missing")
            if now < self._clock:
                return PacingAdvice("hold", "host_clock_reversed")
            intent_samples = self._samples.get(
                (game_active, streaming_load, intent.kind), (),
            )
            workload_samples = self._samples.get(
                (game_active, streaming_load, None), (),
            )
            if len(intent_samples) >= self._minimum:
                observations = intent_samples
                calibration_scope = "intent"
            elif len(workload_samples) >= self._minimum:
                observations = workload_samples
                calibration_scope = "workload"
            else:
                # Partial samples are diagnostic only; do not call them a
                # calibrated p90 until the configured minimum is reached.
                observations = (
                    intent_samples
                    if len(intent_samples) > len(workload_samples)
                    else workload_samples
                )
                calibration_scope = "cold_start"
            enough = calibration_scope != "cold_start"
            if enough:
                ordered = sorted(observations)
                per_word = ordered[math.ceil(0.90 * len(ordered)) - 1]
            else:
                per_word = _FALLBACK_SECONDS_PER_WORD
            remaining = intent.deadline_at - now - self._start_margin - self._tail_margin - queued / 1000
            cap = min(_LIMITS[intent.kind], math.floor(remaining / per_word))
            if cap < _MIN_WORDS:
                self._counts["deferred"] += 1
                return PacingAdvice(
                    "hold",
                    "speech_cannot_fit_event_deadline",
                    measured_samples=len(observations),
                    calibration_scope=calibration_scope,
                )
            return PacingAdvice(
                "bounded",
                "host_playout_p90" if enough else "conservative_cold_start",
                max_words=cap,
                measured_samples=len(observations),
                calibration_scope=calibration_scope,
            )

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "accepted": self._counts["accepted"],
                "rejected": self._counts["rejected"],
                "deferred": self._counts["deferred"],
                "game_stream_samples": len(
                    self._samples.get((True, True, None), ()),
                ),
                "game_stream_calibrated_intents": sum(
                    len(self._samples.get((True, True, kind), ())) >= self._minimum
                    for kind in _LIMITS
                ),
            }


__all__ = ["PacingAdvice", "StreamSpeechPacer"]