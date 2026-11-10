"""Bounded nonverbal active-listening cues for STAR's VTuber stage.

A trusted local conversation host may emit coarse incremental semantic intents
while a viewer is speaking. This module maps only a tiny allowlist of those
intents to subtle, short-lived rig adjustments. It stores no transcript, audio,
speaker identity, or inferred emotion, and it never creates speech or grants
output/broadcast permission.

The host must provide a fresh verified context on every rendered idle frame.
Owner speech, STAR speech, critical gameplay, stream pressure, reduced motion,
stale events, and rate limits suppress the cue.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math
import re
import secrets
from threading import RLock
from typing import cast

from .stream_motion import MotionFrame

_INTENTS = {"acknowledge", "considering", "clarifying"}
_ADDRESSING = frozenset({"star", "group", "other", "unknown"})
_SESSION_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_CLOCK_S = 1e12
_MIN_CONFIDENCE = 0.82
_MAX_EVENT_AGE_S = 0.25
_COOLDOWN_S = 1.15
_WINDOW_S = 60.0
_MAX_PER_WINDOW = 10
_DURATIONS = {
    "acknowledge": 0.48,
    "considering": 0.62,
    "clarifying": 0.46,
}


def _clock(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite monotonic timestamp")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite monotonic timestamp") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK_S:
        raise ValueError(f"{field} must be a finite monotonic timestamp")
    return result


def _unit(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number in [0, 1]")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number in [0, 1]") from exc
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"{field} must be a finite number in [0, 1]")
    return result


@dataclass(frozen=True)
class ListenerIntentSignal:
    """Content-free host event from incremental ASR/dialogue analysis.

    event_id is monotonic within one stage session. "acknowledge" means only
    that the utterance was received; it must not be used to imply agreement.
    The host must derive every flag and confidence value independently. Both the event and each rendered idle context must carry the current stage-session ID.
    """

    session_id: str
    event_id: int
    kind: str
    observed_at_s: float
    confidence: float
    addressing: str
    resolved_by_other: bool
    guest_speaking: bool
    owner_speaking: bool
    star_speaking: bool
    gameplay_critical: bool
    stream_pressure: bool
    host_verified: bool

    def __post_init__(self) -> None:
        if type(self.session_id) is not str or _SESSION_ID.fullmatch(self.session_id) is None:
            raise ValueError("session_id must be a 128-bit lowercase hex session token")
        if type(self.event_id) is not int or not 1 <= self.event_id <= 2**63 - 1:
            raise ValueError("event_id must be a positive signed 64-bit integer")
        if type(self.kind) is not str or self.kind not in _INTENTS:
            raise ValueError("unsupported listener intent")
        _clock(self.observed_at_s, "observed_at_s")
        _unit(self.confidence, "confidence")
        if type(self.addressing) is not str or self.addressing not in _ADDRESSING:
            raise ValueError("addressing must be star, group, other, or unknown")
        if type(self.resolved_by_other) is not bool:
            raise ValueError("resolved_by_other must be an explicit boolean")
        for name in (
            "guest_speaking", "owner_speaking", "star_speaking",
            "gameplay_critical", "stream_pressure", "host_verified",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an explicit boolean")


class StreamListenerBackchannel:
    """Owner-opted, rate-limited overlay for active-listening micro-cues."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._enabled = False
        self._session_id = ""
        self._last_event_id = 0
        self._last_clock = -1.0
        self._event_times: deque[float] = deque(maxlen=_MAX_PER_WINDOW)
        self._cue: tuple[str, float, float] | None = None
        self._counts = {
            "accepted": 0,
            "rejected": 0,
            "stale": 0,
            "duplicate": 0,
            "suppressed": 0,
            "rate_limited": 0,
            "expired": 0,
            "clock_reversed": 0,
            "session_mismatch": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> str:
        if owner_approved is not True:
            raise PermissionError("listener backchannels require owner approval")
        with self._lock:
            if self._enabled:
                raise RuntimeError("listener backchannels are already enabled")
            self._reset_locked()
            self._enabled = True
            self._session_id = secrets.token_hex(16)
            return self._session_id

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._reset_locked()
            self._session_id = ""

    def reset(self) -> None:
        """Clear session evidence and rotate the replay fence without changing opt-in."""
        with self._lock:
            self._reset_locked()
            if self._enabled:
                self._session_id = secrets.token_hex(16)

    @property
    def session_id(self) -> str:
        """Current stage-session replay fence; empty while the feature is disabled."""
        with self._lock:
            return self._session_id if self._enabled else ""

    def clear(self) -> None:
        """Cancel the current micro-cue without resetting replay protection."""
        with self._lock:
            self._cue = None

    def _reset_locked(self) -> None:
        self._last_event_id = 0
        self._last_clock = -1.0
        self._event_times.clear()
        self._cue = None

    def observe(self, signal: ListenerIntentSignal, *, now_s: float) -> bool:
        """Accept one fresh semantic event; no raw speech is ever retained."""
        if not isinstance(signal, ListenerIntentSignal):
            raise TypeError("ListenerIntentSignal required")
        now = _clock(now_s, "now_s")
        with self._lock:
            if not self._enabled:
                self._counts["rejected"] += 1
                return False
            if signal.session_id != self._session_id:
                self._counts["session_mismatch"] += 1
                return False
            if now < self._last_clock:
                self._cue = None
                self._counts["clock_reversed"] += 1
                return False
            self._last_clock = now
            if signal.event_id <= self._last_event_id:
                self._counts["duplicate"] += 1
                return False
            # Consume the sequence before evaluating content-free flags so a
            # rejected event cannot later be replayed with a refreshed clock.
            self._last_event_id = signal.event_id
            if not signal.host_verified:
                self._counts["rejected"] += 1
                return False
            age = now - signal.observed_at_s
            if age < 0 or age > _MAX_EVENT_AGE_S:
                self._counts["stale"] += 1
                return False
            if (
                signal.confidence < _MIN_CONFIDENCE
                or signal.addressing not in {"star", "group"}
                or signal.resolved_by_other
                or not signal.guest_speaking
                or signal.owner_speaking
                or signal.star_speaking
                or signal.gameplay_critical
                or signal.stream_pressure
            ):
                self._counts["suppressed"] += 1
                return False
            while self._event_times and now - self._event_times[0] >= _WINDOW_S:
                self._event_times.popleft()
            if (
                (self._event_times and now - self._event_times[-1] < _COOLDOWN_S)
                or len(self._event_times) >= _MAX_PER_WINDOW
            ):
                self._counts["rate_limited"] += 1
                return False
            self._event_times.append(now)
            self._cue = (signal.kind, now, signal.confidence)
            self._counts["accepted"] += 1
            return True

    def overlay(
        self,
        frame: MotionFrame,
        *,
        now_s: float,
        host_context_verified: bool,
        viewer_speaking: bool,
        owner_speaking: bool = False,
        gameplay_critical: bool = False,
        stream_pressure: bool = False,
        reduced_motion: bool = False,
        listener_context_session_id: str = "",
        listener_addressing: str = "unknown",
        listener_resolved_by_other: bool = False,
    ) -> MotionFrame:
        """Overlay a subtle cue only while the same safe context remains fresh."""
        if not isinstance(frame, MotionFrame):
            raise TypeError("base MotionFrame required")
        now = _clock(now_s, "now_s")
        flags = (
            host_context_verified, viewer_speaking, owner_speaking,
            gameplay_critical, stream_pressure, reduced_motion,
        )
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("listener overlay context flags must be booleans")
        if type(listener_context_session_id) is not str:
            raise ValueError("listener_context_session_id must be a string")
        if type(listener_addressing) is not str or listener_addressing not in _ADDRESSING:
            raise ValueError("listener_addressing must be star, group, other, or unknown")
        if type(listener_resolved_by_other) is not bool:
            raise ValueError("listener_resolved_by_other must be an explicit boolean")
        with self._lock:
            if not self._enabled:
                return frame
            if now < self._last_clock:
                self._cue = None
                self._counts["clock_reversed"] += 1
                return frame
            self._last_clock = now
            if (
                not host_context_verified
                or not viewer_speaking
                or owner_speaking
                or gameplay_critical
                or stream_pressure
                or reduced_motion
                or listener_context_session_id != self._session_id
                or listener_addressing not in {"star", "group"}
                or listener_resolved_by_other
            ):
                # A pause, safety change, or lost host witness cancels the cue;
                # it must never resume later as a stale gesture.
                self._cue = None
                return frame
            if self._cue is None:
                return frame
            kind, started, confidence = self._cue
            duration = _DURATIONS[kind]
            elapsed = now - started
            if elapsed < 0:
                self._cue = None
                self._counts["clock_reversed"] += 1
                return frame
            if elapsed >= duration:
                self._cue = None
                self._counts["expired"] += 1
                return frame
            envelope = math.sin(math.pi * elapsed / duration) * confidence
            if kind == "acknowledge":
                return replace(
                    frame,
                    head_y=max(-1.0, frame.head_y - 0.045 * envelope),
                    body_lean=min(1.0, frame.body_lean + 0.018 * envelope),
                )
            if kind == "considering":
                return replace(
                    frame,
                    head_x=min(1.0, frame.head_x + 0.038 * envelope),
                    brow_raise=min(1.0, frame.brow_raise + 0.025 * envelope),
                )
            return replace(
                frame,
                head_x=max(-1.0, frame.head_x - 0.032 * envelope),
                brow_raise=min(1.0, frame.brow_raise + 0.045 * envelope),
            )

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate counters only; no event IDs, content, or viewer identity."""
        with self._lock:
            return {"enabled": self._enabled, **self._counts}


__all__ = ["ListenerIntentSignal", "StreamListenerBackchannel"]
