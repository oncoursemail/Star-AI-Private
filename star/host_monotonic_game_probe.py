"""Local, opt-in host event clock for private gameplay-latency diagnostics.

Records event times by calling one process-local monotonic_ns clock itself,
rather than trusting a list of externally supplied timestamps. This does NOT
establish an independently trusted game host, prove that game input moved a
character, control games, make network calls, or publish OBS broadcasts.

An authorized application must call capture/decision_ready/action_submitted/
action_ack at the corresponding REAL host lifecycle boundaries. Acknowledgment
must be from the host, not a language-model assertion. Clock readings and
in-flight event details never leave memory through report APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic_ns
from typing import Callable, NoReturn

from .measured_game_latency import (
    LocalFrameTiming, PrivateLatencyReplay, prepare_private_latency_replay,
)

_MAX_NS = (1 << 63) - 1
_MAX_FRAMES = 256


@dataclass(slots=True)
class _PendingFrame:
    capture_ns: int
    decision_ready_ns: int | None = None
    action_submit_ns: int | None = None


class HostMonotonicGameProbe:
    """Single-use, local-only host recorder; all public methods are threadsafe.

    Host owns all callback sources. A user/model cannot prove successful game
    movement by supplying a callback name. Failures revoke the entire window:
    partially completed, reordered, or aborted frames must never disappear
    from a successful latency benchmark.

    The optional clock is only for deterministic testing; injection is not
    independently attested and must not be presented as hardware proof.
    """

    def __init__(
        self, *, owner_approved: bool = False,
        clock: Callable[[], int] | None = None,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("private host timing requires owner approval")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be a callable monotonic_ns source")
        self._clock = monotonic_ns if clock is None else clock
        self._lock = RLock()
        self._last_clock_ns: int | None = None
        self._started = 0
        self._next_ack = 1
        self._pending: dict[int, _PendingFrame] = {}
        self._completed: dict[int, LocalFrameTiming] = {}
        self._revoked = False
        self._finalized = False
        self._replay: PrivateLatencyReplay | None = None

    def _clear_and_revoke(self) -> None:
        self._revoked = True
        self._pending.clear()
        self._completed.clear()
        self._replay = None

    def _require_open(self) -> None:
        if self._revoked:
            raise RuntimeError("private timing window revoked")
        if self._finalized:
            raise RuntimeError("private timing window already finalized")

    def _fail(self, reason: str) -> NoReturn:
        self._clear_and_revoke()
        raise ValueError(reason)

    def _sample(self) -> int:
        try:
            now = self._clock()
        except Exception as exc:
            self._clear_and_revoke()
            raise RuntimeError("host monotonic clock failed") from exc
        if type(now) is not int or not 0 <= now <= _MAX_NS:
            self._fail("host clock must return a nonnegative int64 monotonic_ns")
        if self._last_clock_ns is not None and now < self._last_clock_ns:
            self._fail("host monotonic clock moved backward")
        self._last_clock_ns = now
        return now

    def capture(self) -> int:
        """Mark frame capture at host receipt; returns a local opaque sequence."""
        with self._lock:
            self._require_open()
            if self._started >= _MAX_FRAMES:
                self._fail("host timing window exceeded 256 frames")
            now = self._sample()
            self._started += 1
            self._pending[self._started] = _PendingFrame(now)
            return self._started

    def _get(self, sequence: int) -> _PendingFrame:
        if type(sequence) is not int or sequence not in self._pending:
            self._fail("unknown or already acknowledged frame")
        return self._pending[sequence]

    def decision_ready(self, sequence: int) -> None:
        """Mark completion of reasoning; this does not authorize input."""
        with self._lock:
            self._require_open()
            pending = self._get(sequence)
            if pending.decision_ready_ns is not None:
                self._fail("duplicate decision-ready event")
            pending.decision_ready_ns = self._sample()

    def action_submitted(self, sequence: int) -> None:
        """Mark actual host submission (never submits input itself)."""
        with self._lock:
            self._require_open()
            pending = self._get(sequence)
            if pending.decision_ready_ns is None or pending.action_submit_ns is not None:
                self._fail("submission requires one prior decision-ready event")
            pending.action_submit_ns = self._sample()

    def action_ack(self, sequence: int) -> None:
        """Mark observed host ACK (not proof of movement or game success)."""
        with self._lock:
            self._require_open()
            pending = self._get(sequence)
            ready_ns = pending.decision_ready_ns
            submitted_ns = pending.action_submit_ns
            if ready_ns is None or submitted_ns is None or sequence != self._next_ack:
                self._fail("ACK requires host submission and in-order completion")
            now = self._sample()
            # LocalFrameTiming independently validates intra-frame ordering
            # and rejects stalled/mixed-clock intervals over 30 seconds.
            try:
                timing = LocalFrameTiming(
                    sequence=sequence, capture_ns=pending.capture_ns,
                    decision_ready_ns=ready_ns,
                    action_submit_ns=submitted_ns, action_ack_ns=now,
                )
            except (ValueError, TypeError) as exc:
                self._clear_and_revoke()
                raise ValueError("invalid host frame timing") from exc
            self._completed[sequence] = timing
            del self._pending[sequence]
            self._next_ack += 1

    def abort(self) -> None:
        """Lost ACK, cancelled frame, game failure, or user stop: revoke window."""
        with self._lock:
            self._clear_and_revoke()

    def status(self) -> dict[str, int | bool]:
        """Counts only, including incomplete frames; no raw times or media."""
        with self._lock:
            return {
                "started_frames": self._started,
                "completed_frames": len(self._completed) if not self._finalized and not self._revoked
                                    else (self._started if self._finalized else 0),
                "pending_frames": len(self._pending),
                "revoked": self._revoked,
                "finalized": self._finalized,
                "independent_gameplay_proof": False,
                "timing_attested": False,
            }

    def finalize(self, *, tick_ns: int = 100_000_000) -> PrivateLatencyReplay:
        """Consume complete observations; reject any missing/cancelled frame."""
        with self._lock:
            self._require_open()
            if not self._started or self._pending or len(self._completed) != self._started:
                self._clear_and_revoke()
                raise ValueError("incomplete window cannot produce a success-only replay")
            captures = tuple(self._completed[n] for n in range(1, self._started + 1))
            try:
                replay = prepare_private_latency_replay(
                    captures, owner_approved=True, tick_ns=tick_ns,
                )
            except (ValueError, TypeError):
                self._clear_and_revoke()
                raise
            finally:
                # Destroy retained raw monotonic timestamps on finalization.
                self._completed.clear()
                self._pending.clear()
            self._finalized = True
            self._replay = replay
            return replay


__all__ = ["HostMonotonicGameProbe"]
