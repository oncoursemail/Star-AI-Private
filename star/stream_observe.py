"""Opt-in, host-mediated novelty sampler for Star's live game observations.

A vision call costs memory, latency and FPS. This pure session-local admission
state machine avoids re-analyzing near-identical frames, protects the realtime
voice/game budget and creates expiring reservations. No images, chat, credentials
or actions are stored. This is NOT a vision model, capture source, permission
broker, game controller, or OBS integration.

The host, not the LLM or a viewer, must supply monotonic capture timestamps,
64-bit perceptual fingerprints, event cues, and authenticated owner consent.
Perceptual hashes are only a novelty *heuristic*, not evidence that a scene or
mechanic was understood or verified.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .stream_budget import StreamTelemetry, advise_workload

_CUES = frozenset({"none", "damage", "death", "win", "new_scene", "objective", "menu"})
_MAX_CLOCK_MS = 1e13


def _ms(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be a finite nonnegative monotonic millisecond value")
    try:
        val = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(val) or not 0 <= val <= _MAX_CLOCK_MS:
        raise ValueError(f"{label} must be a finite nonnegative monotonic millisecond value")
    return val


@dataclass(frozen=True)
class FrameCue:
    captured_ms: float
    perceptual_hash: int  # locally computed 64-bit pHash/dHash, not a crypto digest
    cue: str = "none"

    def __post_init__(self) -> None:
        _ms(self.captured_ms, "captured_ms")
        if type(self.perceptual_hash) is not int or not 0 <= self.perceptual_hash < (1 << 64):
            raise ValueError("perceptual_hash must be a 64-bit unsigned integer")
        if type(self.cue) is not str or self.cue not in _CUES:
            raise ValueError("unknown host-observed cue")


@dataclass(frozen=True)
class ObservationDecision:
    admitted: bool
    reason: str
    profile: str
    target_fps: float
    ticket: int | None = None


class ObservationGovernor:
    """Guard requests to a *separately owner-authorized* vision inference host.

    Enabling this object is an additional opt-in, never authorization to capture
    a screen. Tickets are consumed on success/failure; a timeout consumes its
    allotted budget so a stalled worker cannot trigger a GPU request storm.
    """

    def __init__(self, *, calls_per_minute: int = 24, burst: int = 2,
                 novelty_bits: int = 8, refresh_ms: float = 6000.0,
                 ticket_timeout_ms: float = 5000.0,
                 frame_max_age_ms: float = 1500.0) -> None:
        if type(calls_per_minute) is not int or not 1 <= calls_per_minute <= 120:
            raise ValueError("calls_per_minute must be 1..120")
        if type(burst) is not int or not 1 <= burst <= 8:
            raise ValueError("burst must be 1..8")
        if type(novelty_bits) is not int or not 1 <= novelty_bits <= 64:
            raise ValueError("novelty_bits must be 1..64")
        self.refresh_ms = _ms(refresh_ms, "refresh_ms")
        self.ticket_timeout_ms = _ms(ticket_timeout_ms, "ticket_timeout_ms")
        self.frame_max_age_ms = _ms(frame_max_age_ms, "frame_max_age_ms")
        if not 100 <= self.refresh_ms <= 120000 or not 100 <= self.ticket_timeout_ms <= 120000:
            raise ValueError("refresh and ticket timeout must be 100..120000 ms")
        if not 100 <= self.frame_max_age_ms <= 10000:
            raise ValueError("frame_max_age_ms must be 100..10000")
        self.calls_per_minute = calls_per_minute
        self.burst = burst
        self.novelty_bits = novelty_bits
        self.enabled = False
        self._next_ticket = 0
        self._reset()

    def _reset(self) -> None:
        self._clock_ms: float | None = None
        self._tokens = float(self.burst)
        self._pending: tuple[int, float, FrameCue] | None = None
        self._last_request_at: float | None = None
        self._last_success: tuple[float, int] | None = None
        self._stats = {"admitted": 0, "completed": 0, "failed": 0,
                       "expired": 0, "deferred": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner opt-in required for vision scheduling")
        if not self.enabled:
            self._reset()
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False
        self._reset()

    def _advance(self, now_ms: float) -> float:
        now = _ms(now_ms, "now_ms")
        if self._clock_ms is not None:
            if now < self._clock_ms:
                raise ValueError("session clock cannot move backwards")
            elapsed = now - self._clock_ms
            self._tokens = min(float(self.burst), self._tokens + elapsed * self.calls_per_minute / 60000.0)
        self._clock_ms = now
        if self._pending and now >= self._pending[1]:
            self._pending = None
            self._stats["expired"] += 1
        return now

    def consider(self, frame: FrameCue, telemetry: StreamTelemetry | None, *,
                 now_ms: float, capture_authorized: bool = False) -> ObservationDecision:
        if not isinstance(frame, FrameCue):
            raise TypeError("expected FrameCue")
        if type(capture_authorized) is not bool:
            raise ValueError("capture_authorized must be an explicit trusted-host bool")
        now = self._advance(now_ms)
        advice = advise_workload("vision", telemetry)

        def defer(reason: str) -> ObservationDecision:
            self._stats["deferred"] += 1
            return ObservationDecision(False, reason, advice.profile, advice.sample_fps)

        if not self.enabled or not capture_authorized:
            return defer("owner_consent_or_capture_permission_missing")
        if not advice.allowed:
            return defer("realtime_headroom_unavailable")
        # The older stream-budget advisor permits 4 Hz *offline* vision even
        # when the game is under pressure. Enforce a stricter safety floor for
        # this request governor; headroom matters even without an OBS stream.
        assert telemetry is not None  # vision advice cannot be allowed otherwise
        if (telemetry.free_vram_mib < 1024
                or (telemetry.game_active and telemetry.game_fps < 45)
                or telemetry.speech_backlog_ms > 350):
            return defer("insufficient_game_or_voice_headroom")
        if frame.captured_ms > now + 20 or now - frame.captured_ms > self.frame_max_age_ms:
            return defer("frame_stale_or_future_dated")
        if self._pending is not None:
            return defer("vision_request_already_in_flight")
        # The latest admitted query sets a min spacing, even if a model fails;
        # an urgent cue cannot flood inference or preempt an existing request.
        minimum_gap = 1000.0 / advice.sample_fps
        if self._last_request_at is not None and now - self._last_request_at < minimum_gap:
            return defer("minimum_sampling_interval")
        if self._tokens < 1.0 - 1e-9:
            return defer("minute_budget_exhausted")
        if frame.cue == "none" and self._last_success is not None:
            last_time, last_hash = self._last_success
            distance = (frame.perceptual_hash ^ last_hash).bit_count()
            if distance < self.novelty_bits and now - last_time < self.refresh_ms:
                return defer("low_visual_novelty")
        self._tokens = max(0.0, self._tokens - 1)
        self._next_ticket += 1
        self._pending = (self._next_ticket, now + self.ticket_timeout_ms, frame)
        self._last_request_at = now
        self._stats["admitted"] += 1
        return ObservationDecision(True, "novel_or_periodic_frame", advice.profile,
                                   advice.sample_fps, self._next_ticket)

    def complete(self, *, ticket: int, now_ms: float, succeeded: bool) -> bool:
        if type(ticket) is not int or ticket <= 0 or type(succeeded) is not bool:
            raise ValueError("ticket and explicit succeeded bool required")
        now = self._advance(now_ms)
        if not self.enabled or self._pending is None or self._pending[0] != ticket:
            return False
        _, _, frame = self._pending
        self._pending = None
        if succeeded:
            self._last_success = (now, frame.perceptual_hash)
            self._stats["completed"] += 1
        else:
            self._stats["failed"] += 1
        return True

    def stats(self) -> dict[str, int | bool]:
        """No frames, prompts, personally identifying data or fingerprints."""
        return {**self._stats, "pending": self._pending is not None,
                "enabled": self.enabled}
