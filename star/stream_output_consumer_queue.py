"""Bounded, epoch-checked consumer-side VTuber output queue.

An output epoch check at generation enqueue is insufficient: queued TTS
and rig payloads might be emitted after a trusted interruption revokes that
epoch. This trusted-host queue checks the SAME identity-only ticket again
at the final, fast native-output handoff. The two checks are serialized by
StreamOutputEpochFence against revocation.

Use only on a private host control worker, NEVER from the audio render
callback. A successful handoff acknowledges only that the backend accepted
a chunk, not audible playback, frame rendering, OBS state or a broadcast.
The native device still must flush on cancellation, verify silence, and
report a neutral avatar through NaturalTurnPhysicalHost.

No viewer/model/plugin API is exposed here. No payload leaves metrics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from .stream_output_epoch_fence import (
    OutputEpochTicket,
    OutputFenceResult,
    StreamOutputEpochFence,
    _ms,
)

# Hard per-chunk ceilings keep an accidental model output from indefinitely
# blocking the audio worker or retaining large speech buffers.
_KIND_MAX_BYTES = {"model_text": 8192, "tts_pcm": 262144, "avatar_motion": 8192}


@dataclass(frozen=True)
class ConsumerQueueResult:
    status: str  # accepted | rejected | fault | revoked | empty
    reason: str
    authorizes_game_input: bool = False
    authorizes_broadcast: bool = False


@dataclass(frozen=True, eq=False)
class _PendingChunk:
    ticket: OutputEpochTicket
    kind: str
    payload: bytes | str
    size: int


class StreamOutputConsumerQueue:
    """Owner-local, opt-in queue with a second check before device handoff.

    Queue capacity checks are actual encoded payload bytes, not a
    model-asserted size. The native callback must be nonblocking and accept
    ONLY a chunk for the epoch it is handed. Its return is not device proof.

    Lock ordering: NEVER hold this queue lock while entering the fence.
    The fence can call its cancellation hooks when budgets expire, and those
    hooks may need to clear this queue. The pop/revoke race is resolved by
    the second atomic fence check, not by holding two locks across a device.
    """

    def __init__(
        self,
        fence: StreamOutputEpochFence,
        *,
        max_pending: int = 64,
        max_buffered_bytes: int = 524288,
    ) -> None:
        if type(fence) is not StreamOutputEpochFence:
            raise TypeError("trusted exact StreamOutputEpochFence required")
        if type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("pending chunk bound must be 1..256")
        if type(max_buffered_bytes) is not int or not 8192 <= max_buffered_bytes <= 4_194_304:
            raise ValueError("buffered bytes bound must be 8192..4194304")
        self._fence = fence
        self._max_pending = max_pending
        self._max_bytes = max_buffered_bytes
        self._lock = RLock()
        self._pending: deque[_PendingChunk] = deque()
        self._bytes = 0
        self._closed = False
        self._queued = 0
        self._consumed = 0
        self._dropped = 0
        self._rejected = 0

    @staticmethod
    def _size(kind: str, payload: bytes | str) -> int:
        if type(kind) is not str or kind not in _KIND_MAX_BYTES:
            raise ValueError("invalid trusted output kind")
        if kind == "model_text":
            if type(payload) is not str or len(payload) > 8192:
                raise ValueError("bounded UTF-8 model text required")
            size = len(payload.encode("utf-8"))
        else:
            if type(payload) is not bytes:
                raise ValueError("immutable encoded native payload required")
            size = len(payload)
        if not 0 < size <= _KIND_MAX_BYTES[kind]:
            raise ValueError("chunk exceeds per-kind byte cap")
        return size

    def enqueue(
        self,
        ticket: OutputEpochTicket,
        *,
        kind: str,
        payload: bytes | str,
        now_ms: float,
    ) -> ConsumerQueueResult:
        """Validate lease and queue once, with backpressure on oversubscription."""
        size = self._size(kind, payload)
        now = _ms(now_ms)

        def put(epoch: str, checked_kind: str) -> bool:
            # The fence holds its lock throughout this fast callback.
            if epoch != ticket.epoch or checked_kind != kind:
                return False
            with self._lock:
                if self._closed or len(self._pending) >= self._max_pending or self._bytes + size > self._max_bytes:
                    return False
                self._pending.append(_PendingChunk(ticket, kind, payload, size))
                self._bytes += size
                self._queued += 1
                return True

        outcome = self._fence.dispatch(ticket, kind=kind, now_ms=now, submit=put)
        if outcome.status != "accepted":
            with self._lock:
                self._rejected += 1
        return ConsumerQueueResult(outcome.status, outcome.reason)

    def consume_one(
        self,
        *,
        now_ms: float,
        submit: Callable[[str, str, bytes | str], bool],
    ) -> ConsumerQueueResult:
        """A second atomic epoch check at the FINAL native enqueue boundary.

        Never call directly from the OS callback or from untrusted viewer
        content. submit MUST synchronously enqueue to an epoch-scoped
        native device/rig adapter without waiting for playback.
        """
        now = _ms(now_ms)
        if not callable(submit):
            raise TypeError("trusted nonblocking consumer callback required")
        with self._lock:
            if not self._pending:
                return ConsumerQueueResult("empty", "no_queued_output")
            chunk = self._pending.popleft()
            self._bytes -= chunk.size

        def handoff(epoch: str, kind: str) -> bool:
            return submit(epoch, kind, chunk.payload) is True

        outcome: OutputFenceResult = self._fence.dispatch(
            chunk.ticket,
            kind=chunk.kind,
            now_ms=now,
            submit=handoff,
        )
        if outcome.status != "accepted":
            # Release all other old buffers now; they cannot be delivered.
            self.discard_ticket(chunk.ticket)
        with self._lock:
            if outcome.status == "accepted":
                self._consumed += 1
            else:
                self._dropped += 1
        return ConsumerQueueResult(outcome.status, outcome.reason)

    def discard_ticket(self, ticket: OutputEpochTicket) -> int:
        """Proactively erase revoked epoch's pending chunks, never execute them."""
        with self._lock:
            keep: deque[_PendingChunk] = deque()
            dropped = 0
            while self._pending:
                item = self._pending.popleft()
                if item.ticket is ticket:
                    self._bytes -= item.size
                    dropped += 1
                else:
                    keep.append(item)
            self._pending = keep
            self._dropped += dropped
            return dropped

    def close(self) -> ConsumerQueueResult:
        """Owner shutdown clears buffers before disabling future output."""
        with self._lock:
            self._closed = True
            self._dropped += len(self._pending)
            self._pending.clear()
            self._bytes = 0
        # Do NOT hold queue lock across fence cancellation callbacks.
        result = self._fence.disable()
        return ConsumerQueueResult(result.status, result.reason)

    def metrics(self) -> dict[str, int | bool]:
        """Privacy-safe bounded counters: never payloads, tickets or text."""
        with self._lock:
            return {
                "pending": len(self._pending),
                "buffered_bytes": self._bytes,
                "queued": self._queued,
                "consumed": self._consumed,
                "dropped": self._dropped,
                "rejected": self._rejected,
                "closed": self._closed,
            }


__all__ = ["ConsumerQueueResult", "StreamOutputConsumerQueue"]
