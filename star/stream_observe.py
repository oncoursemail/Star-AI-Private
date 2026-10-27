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

from collections import deque
from dataclasses import dataclass
import math

from .stream_budget import StreamTelemetry, advise_workload
from .frame_fingerprint import Region, difference_hash

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
    hud_hash: int | None = None  # optional separately cropped UI fingerprint

    def __post_init__(self) -> None:
        _ms(self.captured_ms, "captured_ms")
        if type(self.perceptual_hash) is not int or not 0 <= self.perceptual_hash < (1 << 64):
            raise ValueError("perceptual_hash must be a 64-bit unsigned integer")
        if type(self.hud_hash) is not int and self.hud_hash is not None:
            raise ValueError("hud_hash must be an unsigned 64-bit integer or None")
        if self.hud_hash is not None and not 0 <= self.hud_hash < (1 << 64):
            raise ValueError("hud_hash must be an unsigned 64-bit integer or None")
        if type(self.cue) is not str or self.cue not in _CUES:
            raise ValueError("unknown host-observed cue")

    @classmethod
    def from_pixels(
        cls, captured_ms: float, pixels: bytes | bytearray | memoryview, *,
        width: int, height: int, pixel_format: str = "BGRA",
        row_stride: int | None = None, cue: str = "none",
        game_region: Region | None = None, hud_region: Region | None = None,
    ) -> FrameCue:
        """Fingerprint approved host pixels. No recording, inference or capture.

        Crops are host-configured (not chosen by a viewer or AI); the HUD hash
        helps preserve UI changes when the gameplay scene stays nearly static.
        """
        _ms(captured_ms, "captured_ms")
        if type(cue) is not str or cue not in _CUES:
            raise ValueError("unknown host-observed cue")
        main = difference_hash(
            pixels, width=width, height=height, pixel_format=pixel_format,
            row_stride=row_stride, region=game_region,
        )
        hud = (difference_hash(
            pixels, width=width, height=height, pixel_format=pixel_format,
            row_stride=row_stride, region=hud_region,
        ) if hud_region is not None else None)
        return cls(captured_ms, main, cue, hud)


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
    a screen. Timeouts and revocation quarantine an active GPU worker until
    the trusted host confirms it actually stopped. Deadlines alone cannot free
    hardware. Successful and failed completed calls feed bounded latency
    feedback to reduce future sampling when inference is slow.
    """

    def __init__(self, *, calls_per_minute: int = 24, burst: int = 2,
                 novelty_bits: int = 8, hud_novelty_bits: int = 4,
                 refresh_ms: float = 6000.0,
                 ticket_timeout_ms: float = 5000.0,
                 frame_max_age_ms: float = 1500.0,
                 latency_safety_factor: float = 2.0) -> None:
        if type(calls_per_minute) is not int or not 1 <= calls_per_minute <= 120:
            raise ValueError("calls_per_minute must be 1..120")
        if type(burst) is not int or not 1 <= burst <= 8:
            raise ValueError("burst must be 1..8")
        if type(novelty_bits) is not int or not 1 <= novelty_bits <= 64:
            raise ValueError("novelty_bits must be 1..64")
        if type(hud_novelty_bits) is not int or not 1 <= hud_novelty_bits <= 64:
            raise ValueError("hud_novelty_bits must be 1..64")
        self.refresh_ms = _ms(refresh_ms, "refresh_ms")
        self.ticket_timeout_ms = _ms(ticket_timeout_ms, "ticket_timeout_ms")
        self.frame_max_age_ms = _ms(frame_max_age_ms, "frame_max_age_ms")
        self.latency_safety_factor = _ms(latency_safety_factor, "latency_safety_factor")
        if not 1.0 <= self.latency_safety_factor <= 8.0:
            raise ValueError("latency_safety_factor must be 1..8")
        if not 100 <= self.refresh_ms <= 120000 or not 100 <= self.ticket_timeout_ms <= 120000:
            raise ValueError("refresh and ticket timeout must be 100..120000 ms")
        if not 100 <= self.frame_max_age_ms <= 10000:
            raise ValueError("frame_max_age_ms must be 100..10000")
        self.calls_per_minute = calls_per_minute
        self.burst = burst
        self.novelty_bits = novelty_bits
        self.hud_novelty_bits = hud_novelty_bits
        self.enabled = False
        self._next_ticket = 0
        # Only the trusted worker host can clear this. Never reset it on
        # timeout, disable, or a session re-enable.
        self._quarantined_ticket: int | None = None
        self._reset()

    def _reset(self) -> None:
        self._clock_ms: float | None = None
        self._tokens = float(self.burst)
        self._pending: tuple[int, float, FrameCue, float] | None = None
        self._durations_ms: deque[float] = deque(maxlen=16)
        self._last_request_at: float | None = None
        self._last_success: tuple[float, int, int | None] | None = None
        self._stats = {"admitted": 0, "completed": 0, "failed": 0,
                       "expired": 0, "deferred": 0, "stop_confirmed": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner opt-in required for vision scheduling")
        if not self.enabled:
            if self._pending is not None or self._quarantined_ticket is not None:
                raise RuntimeError("confirm vision worker stopped before starting a new session")
            self._reset()
        self.enabled = True

    def disable(self) -> None:
        # Caller must stop the physical GPU worker. Revoking admission is not
        # evidence that an already-started inference process has terminated.
        if self._pending is not None:
            self._quarantined_ticket = self._pending[0]
        self.enabled = False
        self._reset()

    def acknowledge_worker_stopped(self, *, ticket: int, now_ms: float,
                                   worker_stopped: bool) -> bool:
        """Release a quarantined worker only after trusted host termination.

        An expired worker's output is NEVER accepted as a completed inference.
        A cancellation request is not a worker-stopped acknowledgement. This
        method does not perform physical process termination.
        """
        if type(ticket) is not int or ticket <= 0 or type(worker_stopped) is not bool:
            raise ValueError("valid ticket and explicit worker-stopped boolean required")
        self._advance(now_ms)
        if not worker_stopped or self._quarantined_ticket != ticket:
            return False
        self._quarantined_ticket = None
        self._stats["stop_confirmed"] += 1
        return True

    def _advance(self, now_ms: float) -> float:
        now = _ms(now_ms, "now_ms")
        if self._clock_ms is not None:
            if now < self._clock_ms:
                raise ValueError("session clock cannot move backwards")
            elapsed = now - self._clock_ms
            self._tokens = min(float(self.burst), self._tokens + elapsed * self.calls_per_minute / 60000.0)
        self._clock_ms = now
        if self._pending and now >= self._pending[1]:
            self._quarantined_ticket = self._pending[0]
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
        effective_fps = advice.sample_fps
        if effective_fps > 0 and self._durations_ms:
            # Host-reported duration is not a claimed model speedup. Slow
            # inference reduces the target observation request rate.
            durations = sorted(self._durations_ms)
            p90 = durations[math.ceil(0.9 * len(durations)) - 1]
            if p90 > 0:
                effective_fps = min(
                    effective_fps, 1000.0 / (self.latency_safety_factor * p90)
                )

        def defer(reason: str) -> ObservationDecision:
            self._stats["deferred"] += 1
            return ObservationDecision(False, reason, advice.profile, effective_fps)

        if not self.enabled or not capture_authorized:
            return defer("owner_consent_or_capture_permission_missing")
        if self._quarantined_ticket is not None:
            return defer("vision_worker_stop_unconfirmed")
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
        minimum_gap = 1000.0 / effective_fps
        if self._last_request_at is not None and now - self._last_request_at < minimum_gap:
            return defer("minimum_sampling_interval")
        if self._tokens < 1.0 - 1e-9:
            return defer("minute_budget_exhausted")
        if frame.cue == "none" and self._last_success is not None:
            last_time, last_hash, last_hud = self._last_success
            distance = (frame.perceptual_hash ^ last_hash).bit_count()
            if frame.hud_hash is None and last_hud is None:
                hud_is_similar = True
            elif frame.hud_hash is None or last_hud is None:
                # Uncomparable HUD scopes must never suppress observations.
                hud_is_similar = False
            else:
                hud_is_similar = (
                    (frame.hud_hash ^ last_hud).bit_count() < self.hud_novelty_bits
                )
            if (distance < self.novelty_bits and hud_is_similar
                    and now - last_time < self.refresh_ms):
                return defer("low_visual_novelty")
        self._tokens = max(0.0, self._tokens - 1)
        self._next_ticket += 1
        self._pending = (self._next_ticket, now + self.ticket_timeout_ms, frame, now)
        self._last_request_at = now
        self._stats["admitted"] += 1
        return ObservationDecision(True, "novel_or_periodic_frame", advice.profile,
                                   effective_fps,
                                   self._next_ticket)

    def complete(self, *, ticket: int, now_ms: float, succeeded: bool) -> bool:
        if type(ticket) is not int or ticket <= 0 or type(succeeded) is not bool:
            raise ValueError("ticket and explicit succeeded bool required")
        now = self._advance(now_ms)
        if not self.enabled or self._pending is None or self._pending[0] != ticket:
            return False
        _, _, frame, issued_ms = self._pending
        self._pending = None
        self._durations_ms.append(now - issued_ms)
        if succeeded:
            self._last_success = (now, frame.perceptual_hash, frame.hud_hash)
            self._stats["completed"] += 1
        else:
            self._stats["failed"] += 1
        return True

    def stats(self) -> dict[str, int | bool]:
        """No frames, prompts, personally identifying data or fingerprints."""
        return {**self._stats, "pending": self._pending is not None,
                "quarantined": self._quarantined_ticket is not None,
                "enabled": self.enabled}
