"""Counterbalanced, owner-only offline A/B runner for STAR's local game vision.

This is the missing *execution* bridge from two already captured, authorized
RGB frames through two independent LocalLlamaComparisonWorker instances into
PairedVisionTraceHost. The workers see the exact same pixel snapshots. Neither
model receives truth, and truth may only be revealed after the entire cohort
has been frozen. No Windows capture, game input, OBS, narration, or training is
performed here.

IMPORTANT: A client timeout does not prove physical inference has stopped.
An ambiguous stop permanently poisons this runner and aborts the whole trace
cohort. The caller must independently confirm and clear each worker's
quarantine before constructing a new runner.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from threading import RLock
import time
from typing import Callable

from .stream_local_vlm import LocalLlamaComparisonWorker
from .stream_visual_perception import VisualPacket
from .stream_vision_trace_host import (
    HostFrameRef, PairedVisionTraceHost, VisionTraceTicket,
)
from .stream_windows_game_capture import CapturedVisionFrame, WorkerReport


class UncertainVisionStop(RuntimeError):
    """The model may still be processing: never claim GPU capacity is free."""


@dataclass(frozen=True)
class PairedVisionProbeResult:
    """No images, labels, model text or hidden truth are returned."""

    ticket: VisionTraceTicket
    first_variant: str
    baseline_status: str
    candidate_status: str


class PairedOfflineVisionRunner:
    """Serially run two models with balanced call order and immutable pixels.

    The caller MUST opt into a separately enabled PairedVisionTraceHost, then
    authorize this call for a private/offline game-window capture. Both workers
    are dedicated to this runner; they must not be shared with live streaming.
    Each test pair resets both workers, supplies a previous frame, and asks
    about the newer frame, without relying on prior cached visual state.

    Even the previous-frame priming step may fail: that failure is recorded as
    an error, not mistaken for a valid 'no change' prediction. A returned
    WorkerReport(stopped=False) is never silently converted to a timeout.
    """

    def __init__(
        self, *,
        traces: PairedVisionTraceHost,
        baseline: LocalLlamaComparisonWorker,
        candidate: LocalLlamaComparisonWorker,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        max_pair_gap_ms: int = 5000,
        max_capture_age_ms: int = 15000,
    ) -> None:
        if type(traces) is not PairedVisionTraceHost:
            raise TypeError("exact owner-owned PairedVisionTraceHost required")
        if (type(baseline) is not LocalLlamaComparisonWorker
                or type(candidate) is not LocalLlamaComparisonWorker
                or baseline is candidate):
            raise TypeError("two distinct local comparison workers required")
        if not callable(clock_ms):
            raise TypeError("trusted monotonic clock required")
        if (type(max_pair_gap_ms) is not int
                or not 300 <= max_pair_gap_ms <= 10000):
            raise ValueError("invalid maximum frame gap")
        if (type(max_capture_age_ms) is not int
                or not 100 <= max_capture_age_ms <= 30000):
            raise ValueError("invalid capture age")
        self._traces = traces
        self._workers = {"baseline": baseline, "candidate": candidate}
        self._clock_ms = clock_ms
        self._max_gap_ms = max_pair_gap_ms
        self._max_age_ms = max_capture_age_ms
        self._lock = RLock()
        self._poisoned = False
        self._last_clock = 0.0
        self._last_sequence = 0
        self._completed = 0

    def _clock(self) -> float:
        value = self._clock_ms()
        if type(value) not in (int, float):
            raise ValueError("host clock returned invalid value")
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 1e13:
            raise ValueError("host clock is not finite")
        if number < self._last_clock:
            raise ValueError("host clock went backwards")
        self._last_clock = number
        return number

    @staticmethod
    def _snapshot(frame: CapturedVisionFrame) -> bytearray:
        # Reuse the existing strict layout/geometry validator, before reading
        # even one RGB byte from an untrusted or malformed view.
        LocalLlamaComparisonWorker._validate_frame(frame)
        return bytearray(frame.rgb)

    @staticmethod
    def _status(report: WorkerReport) -> str:
        if type(report) is not WorkerReport:
            raise TypeError("local worker returned an invalid report")
        if not report.stopped:
            raise UncertainVisionStop(
                "local model termination ambiguous: preserve quarantine")
        if not report.succeeded:
            return "error"
        if report.perception is None:
            return "skipped"
        return "accepted"

    def _run_variant(
        self, worker: LocalLlamaComparisonWorker,
        previous: CapturedVisionFrame, current: CapturedVisionFrame,
    ) -> tuple[str, VisualPacket | None, float, float]:
        """Return only a stopped worker's bounded categorical observation."""
        started = self._clock()
        worker.enable(owner_approved=True, local_model_approved=True)
        # Never reuse a previous-reference frame between experiments.
        priming = worker(previous)
        priming_status = self._status(priming)
        if priming_status != "skipped":
            if priming_status == "accepted":
                raise RuntimeError("model generated a packet during priming")
            return "error", None, started, self._clock()
        result = worker(current)
        status = self._status(result)
        return status, result.perception if status == "accepted" else None, (
            started), self._clock()

    def run_pair(
        self, sequence: int, previous: CapturedVisionFrame,
        current: CapturedVisionFrame, *, owner_approved: bool = False,
        capture_approved: bool = False, model_approved: bool = False,
    ) -> PairedVisionProbeResult:
        """Evaluate two LOCAL models on the exact same approved pixel pair.

        Never infer permission from a model reply. The host must separately
        prove capture/window identity, offline session consent, focus, and
        worker termination. Sequence parity alternates evaluation order to
        reduce systematic warm-cache bias; it does not eliminate all bias.
        """
        if (owner_approved is not True or capture_approved is not True
                or model_approved is not True):
            raise PermissionError("owner, offline capture and local model consent required")
        if type(sequence) is not int or sequence <= 0:
            raise ValueError("positive host sequence required")
        with self._lock:
            if self._poisoned:
                raise UncertainVisionStop("runner poisoned: host must confirm model stop")
            if sequence <= self._last_sequence:
                raise ValueError("duplicate or replayed host sequence")
            before = after = None
            older_view = newer_view = None
            reserved = False
            try:
                before = self._snapshot(previous)
                after = self._snapshot(current)
                if (previous.width != current.width
                        or previous.height != current.height
                        or not 0 < current.captured_ms - previous.captured_ms
                        <= self._max_gap_ms):
                    raise ValueError("mismatched or nonconsecutive captured frames")
                now = self._clock()
                if (current.captured_ms > now
                        or now - current.captured_ms > self._max_age_ms):
                    raise ValueError("captured frame not fresh on host clock")
                # Digest the SNAPSHOT, not a mutable external RGB buffer.
                digest = hashlib.sha256(after).hexdigest()
                # A trace reservation is irreversible within this cohort.
                # If anything fails after this point, abort the cohort.
                ticket = self._traces.reserve(
                    HostFrameRef(sequence, digest, current.captured_ms),
                    capture_approved=True)
                reserved = True
                self._last_sequence = sequence
                older_view = memoryview(before).toreadonly()
                newer_view = memoryview(after).toreadonly()
                older = CapturedVisionFrame(
                    older_view, previous.width, previous.height,
                    previous.captured_ms)
                newer = CapturedVisionFrame(
                    newer_view, current.width, current.height,
                    current.captured_ms)
                order = ("baseline", "candidate") if sequence % 2 else (
                    "candidate", "baseline")
                statuses: dict[str, str] = {}
                for variant in order:
                    status, packet, started, finished = self._run_variant(
                        self._workers[variant], older, newer)
                    # Trace records only bounded labels and timings, never RGB.
                    self._traces.record_worker(
                        ticket, variant=variant, packet=packet, status=status,
                        started_ms=started, finished_ms=finished,
                        worker_stopped=True)
                    statuses[variant] = status
                    self._workers[variant].disable()
                self._completed += 1
                return PairedVisionProbeResult(
                    ticket, order[0], statuses["baseline"],
                    statuses["candidate"])
            except BaseException:
                # KeyboardInterrupt/SystemExit while network inference is active
                # are also uncertain stops; never leave a partial live cohort.
                # A failed run cannot be an apparently complete holdout.
                # Fail closed for all failures after reservation (including
                # an ambiguous still-running server inference).
                if reserved:
                    self._poisoned = True
                    self._traces.disable()
                raise
            finally:
                for worker in self._workers.values():
                    worker.disable()
                if older_view is not None:
                    older_view.release()
                if newer_view is not None:
                    newer_view.release()
                if before is not None:
                    before[:] = b"\x00" * len(before)
                if after is not None:
                    after[:] = b"\x00" * len(after)

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "completed_pairs": self._completed,
                "poisoned": self._poisoned,
                "last_sequence": self._last_sequence,
            }


__all__ = [
    "UncertainVisionStop", "PairedVisionProbeResult", "PairedOfflineVisionRunner",
]
