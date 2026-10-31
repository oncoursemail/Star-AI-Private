"""Bounded, opt-in host-VAD turn-taking hints for STAR's gaming VTuber.

The host supplies *preprocessed*, local-monotonic voice activity windows.
No microphone/audio, speaker identification, recording, network, TTS, or OBS
operation is performed. This gate cannot authenticate the host's VAD claims.

A short noise spike is not a barge-in. A confirmed, echo-cleared OWNER voice
requests an interruption from the host; guest voices only hold future speech.
No state here authorizes a tool call, broadcast or interruption by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock

MAX_CLOCK_MS = 1e13
_THRESHOLD = 0.75
_CONFIRM_MS = 120.0
_RECENT_MS = 250.0
_QUIET_MS = 350.0
_MAX_GAP_MS = 150.0


def _number(value: object, name: str, *, ceiling: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and numeric")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and numeric") from exc
    if not math.isfinite(number) or not 0 <= number <= ceiling:
        raise ValueError(f"{name} must be within 0..{ceiling}")
    return number


@dataclass(frozen=True)
class VoiceFrame:
    """One host-attested, short frame ending at at_ms, *not* raw PCM.

    'owner_probability' MUST be assigned by a trusted owner-authenticated
    input source, never by speaker similarity or a speech model's own claim.
    Echo-cleared requires a separate capture/playback echo-cancellation check.
    """
    at_ms: float
    duration_ms: float
    owner_probability: float
    guest_probability: float
    echo_cleared: bool

    def __post_init__(self) -> None:
        at = _number(self.at_ms, "at_ms", ceiling=MAX_CLOCK_MS)
        duration = _number(self.duration_ms, "duration_ms", ceiling=100)
        _number(self.owner_probability, "owner_probability", ceiling=1)
        _number(self.guest_probability, "guest_probability", ceiling=1)
        if duration < 10 or at < duration:
            raise ValueError("frame length must be 10..100 ms and within clock")
        if type(self.echo_cleared) is not bool:
            raise ValueError("echo_cleared must be boolean")


@dataclass(frozen=True)
class TurnAdvice:
    action: str  # speak | hold | yield_owner
    should_interrupt: bool
    reason: str

    def __post_init__(self) -> None:
        if self.action not in {"speak", "hold", "yield_owner"}:
            raise ValueError("unsupported turn action")
        if type(self.should_interrupt) is not bool:
            raise ValueError("should_interrupt must be boolean")
        if self.should_interrupt and self.action != "yield_owner":
            raise ValueError("only authenticated-owner yield may request interruption")
        if type(self.reason) is not str or not 1 <= len(self.reason) <= 80:
            raise ValueError("invalid bounded turn reason")

    @property
    def hold(self) -> bool:
        return self.action != "speak"


class TurnTakingGate:
    """A small deterministic turn-taking *advisor*, not a speech recognizer.

    Stale/no frames fail closed. The host must always stop actual playback,
    invalidate animation frames, and use StarStage.interrupt() after an
    authenticated owner barge-in; advice alone never moves the stage.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._enabled = False
        self._last: VoiceFrame | None = None
        self._owner_ms = 0.0
        self._guest_ms = 0.0
        self._owner_yield_counted = False
        self._last_voice_ms: float | None = None
        self._counts = {"accepted": 0, "rejected": 0, "owner_yields": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("turn-taking requires explicit host approval")
        with self._lock:
            self._reset()
            self._enabled = True

    def _reset(self) -> None:
        self._last = None
        self._owner_ms = self._guest_ms = 0.0
        self._owner_yield_counted = False
        self._last_voice_ms = None

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._reset()

    def observe(self, frame: VoiceFrame) -> bool:
        """Ingest monotonic, nonoverlapping VAD frames with gap-safe debounce."""
        if not isinstance(frame, VoiceFrame):
            raise TypeError("expected VoiceFrame")
        with self._lock:
            if not self._enabled:
                return False
            prev = self._last
            if prev is not None:
                gap = frame.at_ms - prev.at_ms
                if gap <= 0 or frame.at_ms - frame.duration_ms < prev.at_ms - 1e-6:
                    self._counts["rejected"] += 1
                    raise ValueError("overlapping or reversed voice frames")
                if gap > _MAX_GAP_MS:
                    self._owner_ms = self._guest_ms = 0.0
                    self._owner_yield_counted = False
            owner = (frame.echo_cleared and
                     frame.owner_probability >= _THRESHOLD and
                     frame.guest_probability < _THRESHOLD)
            guest = (frame.echo_cleared and
                     frame.guest_probability >= _THRESHOLD and
                     frame.owner_probability < _THRESHOLD)
            # Prevent simultaneous labels or playback echo from forging an owner
            # identity or a barge-in, but remain quiet on uncertain activity.
            if max(frame.owner_probability, frame.guest_probability) >= 0.50:
                self._last_voice_ms = frame.at_ms
            self._owner_ms = self._owner_ms + frame.duration_ms if owner else 0.0
            if not owner:
                # A new independently confirmed utterance is a new event.
                self._owner_yield_counted = False
            self._guest_ms = self._guest_ms + frame.duration_ms if guest else 0.0
            self._last = frame
            self._counts["accepted"] += 1
            return True

    def advise(self, *, now_ms: float, star_speaking: bool) -> TurnAdvice:
        """Recommend speech/silence, independent of actual stage operations."""
        now = _number(now_ms, "now_ms", ceiling=MAX_CLOCK_MS)
        if type(star_speaking) is not bool:
            raise ValueError("star_speaking must be boolean")
        with self._lock:
            frame = self._last
            if not self._enabled:
                return TurnAdvice("hold", False, "owner_opt_in_missing")
            if frame is None or now < frame.at_ms or now - frame.at_ms > _RECENT_MS:
                return TurnAdvice("hold", False, "vad_missing_or_stale")
            if not frame.echo_cleared:
                return TurnAdvice("hold", False, "echo_not_cleared")
            # A sustained owner-verified source is the only barge-in case.
            if self._owner_ms >= _CONFIRM_MS:
                if star_speaking and not self._owner_yield_counted:
                    # Polling the same frame repeatedly is not a new barge-in.
                    # Keep should_interrupt actionable until the host stops
                    # audio; only the *metric* is deduplicated here.
                    self._counts["owner_yields"] += 1
                    self._owner_yield_counted = True
                return TurnAdvice("yield_owner", star_speaking,
                                  "confirmed_authenticated_owner_voice")
            if self._guest_ms >= _CONFIRM_MS:
                return TurnAdvice("hold", False, "confirmed_guest_voice")
            if (self._last_voice_ms is not None and
                    now - self._last_voice_ms < _QUIET_MS):
                return TurnAdvice("hold", False, "speech_or_noise_hangover")
            return TurnAdvice("speak", False, "trusted_silence")

    def metrics(self) -> dict[str, int | bool]:
        """No audio, transcripts, speaker IDs, raw probabilities or timings."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled}


__all__ = ["VoiceFrame", "TurnAdvice", "TurnTakingGate"]
