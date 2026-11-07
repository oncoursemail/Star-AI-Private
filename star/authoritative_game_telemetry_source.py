"""Private engine-side producer for Star's authenticated game telemetry v1.

Deploy only INSIDE an independently trusted, owner-controlled game/test host.
This object is not a model tool, a Roblox client script, a network endpoint,
a Windows controller, or a proof that the engine-side facts are correct.
The reader must obtain authoritative live engine state, not image captions,
viewer messages, gameplay actions, or model-provided values.

Transport (including peer pinning, isolation and timeouts) is supplied by a
separate host; bytes returned here can be handed to the existing
AuthenticatedGameTelemetryBridge in a DIFFERENT trusted process. Never place
this key in model prompts, chat, logs, client code or a public repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import math
from threading import RLock
import time
from typing import Callable

from .game_state_transition_witness import GameStateSample
from .game_telemetry_source_bridge import (
    SignedEngineFrame, telemetry_mac_payload,
)
from .stream_moment_receipts import validate_receipt_key

_MAX_FRAMES = 4096
_MAX_PACKET_BYTES = 512
_ZERO_MAC = "0" * 64


class EngineSourceRevoked(RuntimeError):
    """Source continuity is not trustworthy; use a new owner-approved session."""


@dataclass(frozen=True)
class SourceMetrics:
    active: bool
    signed_frames: int
    revoked: bool
    # Intentionally no game state, secret, packet data, timestamps, or IDs.


class AuthoritativeGameTelemetrySource:
    """Emit authenticated, sequenced facts from a pinned private engine reader.

    Only the private reader callback can supply state. poll() accepts no
    model-supplied state argument. If a read fails, time reverses, the frame
    stalls/jumps, the session budget ends, or the round moves inconsistently,
    the source is irreversibly revoked. No resend: a transport failure must
    revoke the receiving bridge and require a fresh session on both sides.

    A synchronous callback cannot be forcibly stopped by Python. A production
    transport MUST run the game host behind a separate timeout/stop boundary.
    """

    def __init__(
        self, *, source_id: str, session_id: str, source_key: bytes,
        trusted_reader: Callable[[], GameStateSample],
        clock: Callable[[], float] = time.monotonic,
        max_gap_s: float = 1.0,
        max_read_ms: float = 150.0,
        max_frame_step: int = 240,
    ) -> None:
        # Reuse the receiver's exact canonical validators.
        SignedEngineFrame(source_id, session_id, 1, 0, 1, "playing", 0, _ZERO_MAC)
        if not callable(trusted_reader) or not callable(clock):
            raise TypeError("private engine reader and clock are required")
        if (type(max_gap_s) not in (int, float) or
                not math.isfinite(max_gap_s) or not 0.01 <= max_gap_s <= 10):
            raise ValueError("max_gap_s must be 0.01..10")
        if (type(max_read_ms) not in (int, float) or
                not math.isfinite(max_read_ms) or not 1 <= max_read_ms <= 1000):
            raise ValueError("max_read_ms must be 1..1000")
        if type(max_frame_step) is not int or not 1 <= max_frame_step <= 10_000:
            raise ValueError("max_frame_step must be 1..10000")
        self._source = source_id
        self._session = session_id
        self._key = validate_receipt_key(source_key)
        self._reader = trusted_reader
        self._clock = clock
        self._max_gap = float(max_gap_s)
        self._max_read = float(max_read_ms) / 1000
        self._max_step = max_frame_step
        self._lock = RLock()
        self._active = False
        self._ever_enabled = False
        self._revoked = False
        self._last_sample: GameStateSample | None = None
        self._last_at: float | None = None
        self._signed = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must approve private game telemetry")
        with self._lock:
            if self._active or self._ever_enabled or self._revoked:
                raise EngineSourceRevoked("source session already used")
            self._active = True
            self._ever_enabled = True

    def disable(self) -> None:
        with self._lock:
            self._active = False
            self._revoked = True
            self._last_sample = None
            self._last_at = None

    @staticmethod
    def _read_clock(clock: Callable[[], float]) -> float:
        number = clock()
        if type(number) not in (int, float):
            raise ValueError
        value = float(number)
        if not math.isfinite(value) or not 0 <= value <= 1e13:
            raise ValueError
        return value

    def _continuous(self, sample: GameStateSample, at: float) -> bool:
        old = self._last_sample
        if old is None:
            return sample.phase == "playing"
        previous_at = self._last_at
        assert previous_at is not None
        if (at <= previous_at or at - previous_at > self._max_gap or
                sample.frame <= old.frame or
                sample.frame - old.frame > self._max_step or
                sample.round_id < old.round_id or
                sample.round_id > old.round_id + 1):
            return False
        if sample.round_id > old.round_id:
            return sample.phase == "playing"
        if sample.checkpoint < old.checkpoint:
            return False
        if old.phase in ("won", "lost") and old.phase != sample.phase:
            return False
        return True

    def poll(self) -> bytes:
        """One bounded authenticated fact, never a gameplay command or victory."""
        with self._lock:
            if not self._active or self._revoked:
                raise EngineSourceRevoked("source session not enabled")
            try:
                if self._signed >= _MAX_FRAMES:
                    raise ValueError("session frame budget exhausted")
                before = self._read_clock(self._clock)
                sample = self._reader()
                after = self._read_clock(self._clock)
                if type(sample) is not GameStateSample:
                    raise ValueError("reader did not return authoritative state")
                if after < before or after - before > self._max_read:
                    raise ValueError("engine reader stalled or clock reversed")
                if not self._continuous(sample, after):
                    raise ValueError("authoritative game continuity lost")
                next_seq = self._signed + 1
                unsigned = SignedEngineFrame(
                    self._source, self._session, next_seq,
                    sample.frame, sample.round_id, sample.phase,
                    sample.checkpoint, _ZERO_MAC,
                )
                tag = hmac.new(
                    self._key, telemetry_mac_payload(unsigned), sha256
                ).hexdigest()
                packet = json.dumps(
                    {"v": 1, "source": self._source, "session": self._session,
                     "seq": next_seq, "frame": sample.frame,
                     "round": sample.round_id, "phase": sample.phase,
                     "checkpoint": sample.checkpoint, "mac": tag},
                    ensure_ascii=True, separators=(",", ":"),
                ).encode("ascii")
                if len(packet) > _MAX_PACKET_BYTES:
                    raise ValueError("packet size unexpectedly exceeded")
                self._signed = next_seq
                self._last_sample = sample
                self._last_at = after
                return packet
            except Exception:
                self._active = False
                self._revoked = True
                self._last_sample = None
                self._last_at = None
                raise EngineSourceRevoked(
                    "private engine observation failed: source revoked"
                ) from None

    def metrics(self) -> SourceMetrics:
        with self._lock:
            return SourceMetrics(self._active, self._signed, self._revoked)


__all__ = [
    "AuthoritativeGameTelemetrySource", "EngineSourceRevoked", "SourceMetrics",
]
