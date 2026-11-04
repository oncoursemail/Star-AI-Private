"""Fail-closed, read-only OBS WebSocket v5 evidence for offline STAR rehearsals.

This module *parses* independently fetched GetStats/GetStreamStatus/
GetRecordStatus responses. It never opens sockets or requests OBS actions.
The trusted host must own the authenticated OBS connection, issue the three
read-only requests, provide receipt times from one monotonic clock, and keep
request IDs out of model-visible context. Python objects are NOT cryptographic
attestation or proof that OBS was never live between samples.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Mapping, cast

from star.stream_rehearsal_recorder import StreamRehearsalRecorder

_TYPES = ("GetStats", "GetStreamStatus", "GetRecordStatus")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:\-]{0,95}\Z", re.ASCII)


@dataclass(frozen=True)
class ObsReadOnlyWitness:
    """Ephemeral authenticated-transport response; never serialize or log it."""

    at_monotonic_ms: float
    message: Mapping[str, object]


@dataclass(frozen=True)
class ObsCounters:
    """Numeric OBS render/encoder evidence, NOT game FPS or a live-stream metric."""

    at_monotonic_ms: float
    render_skipped_frames: int
    render_total_frames: int
    output_skipped_frames: int
    output_total_frames: int


def _number(value: object, *, upper: float = 1e13) -> float:
    if type(value) not in (int, float):
        raise ValueError("host timestamp must be a finite number")
    try:
        n = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid host timestamp") from exc
    if not math.isfinite(n) or not 0 <= n <= upper:
        raise ValueError("invalid host timestamp")
    return n


def _count(value: object) -> int:
    # obs-websocket protocol declares these fields as Number. Accept 42.0,
    # but never round an unintegral, boolean, infinite, or huge counter.
    n = _number(value, upper=1e12)
    if not n.is_integer():
        raise ValueError("OBS counter must be an exact integer")
    return int(n)


def _response(
    witness: ObsReadOnlyWitness, *, request_type: str, request_id: str,
) -> tuple[float, Mapping[str, object]]:
    if not isinstance(witness, ObsReadOnlyWitness):
        raise ValueError("OBS host witness missing")
    when = _number(witness.at_monotonic_ms)
    msg = witness.message
    if not isinstance(msg, Mapping) or type(msg.get("op")) is not int or msg["op"] != 7:
        raise ValueError("OBS request response opcode mismatch")
    data = msg.get("d")
    if not isinstance(data, Mapping):
        raise ValueError("OBS response data missing")
    if data.get("requestType") != request_type or data.get("requestId") != request_id:
        raise ValueError("OBS response correlation failed")
    status = data.get("requestStatus")
    if (not isinstance(status, Mapping)
            or status.get("result") is not True
            or type(status.get("code")) is not int
            or status.get("code") != 100):
        raise ValueError("OBS request did not succeed")
    body = data.get("responseData")
    if not isinstance(body, Mapping):
        raise ValueError("OBS response body missing")
    return when, body


class ObsReadOnlyEvidenceGate:
    """Opt-in OBS telemetry parser for a *nonbroadcast*, offline rehearsal.

    This must only be fed by a trusted authenticated read-only host adapter.
    It correlates three distinct successful v5 responses per sample, requires
    an inactive stream, checks timestamps/counter continuity and, by default,
    requires an inactive recording. In private-recording mode, the host
    instead verifies that OBS reports an active, unpaused local recording.
    The gate can also forward render-frame counters to a private recorder.
    A rejected triplet cannot advance the gate or the downstream recorder.
    """

    def __init__(
        self, *, owner_approved: bool = False,
        max_response_span_ms: float = 750.0,
        max_inter_sample_gap_ms: float = 10000.0,
        max_samples: int = 2000,
        require_private_recording: bool = False,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for offline OBS observation")
        if type(require_private_recording) is not bool:
            raise ValueError("private recording mode must be an explicit host boolean")
        span = _number(max_response_span_ms, upper=5000)
        if not 25 <= span <= 5000:
            raise ValueError("response span must be 25..5000 ms")
        gap = _number(max_inter_sample_gap_ms, upper=60000)
        if not 1000 <= gap <= 60000:
            raise ValueError("inter-sample gap must be 1000..60000 ms")
        if type(max_samples) is not int or not 2 <= max_samples <= 10000:
            raise ValueError("max_samples must be 2..10000")
        self._require_private_recording = require_private_recording
        self._span = span
        self._gap = gap
        self._limit = max_samples
        self._lock = RLock()
        self._last: ObsCounters | None = None
        self._count = 0
        self._render_skipped_delta = 0
        self._render_total_delta = 0
        self._output_skipped_delta = 0
        self._output_total_delta = 0
        self._seen_ids: set[str] = set()

    def accept(
        self, *, witnesses: Mapping[str, ObsReadOnlyWitness],
        expected_request_ids: Mapping[str, str],
        host_verified: bool = False,
        recorder: StreamRehearsalRecorder | None = None,
    ) -> ObsCounters:
        """Validate a single read-only OBS triplet and atomically advance state.

        If recorder is supplied, insert only the GetStats *render-thread*
        counters using the latest response receipt time; the recorder's game
        FPS must still come from independent actual game presentation events.
        """
        if host_verified is not True:
            raise PermissionError("authenticated trusted-host evidence required")
        if (not isinstance(witnesses, Mapping)
                or set(witnesses) != set(_TYPES)
                or not isinstance(expected_request_ids, Mapping)
                or set(expected_request_ids) != set(_TYPES)):
            raise ValueError("complete OBS triple required")
        ids = [expected_request_ids[k] for k in _TYPES]
        if any(type(t) is not str or _TOKEN.fullmatch(t) is None for t in ids):
            raise ValueError("invalid opaque OBS request correlator")
        if len(set(ids)) != len(_TYPES):
            raise ValueError("OBS request IDs must be distinct")
        parsed = [_response(witnesses[k], request_type=k, request_id=expected_request_ids[k])
                  for k in _TYPES]
        timestamps = [when for when, _ in parsed]
        if max(timestamps) - min(timestamps) > self._span:
            raise ValueError("OBS status evidence is stale relative to stats")

        stats, stream, recording = (item[1] for item in parsed)
        # A paused recording is still recording; do not infer safety from
        # paused, reconnecting, congestion, outputDuration or stream timecode.
        if stream.get("outputActive") is not False:
            raise PermissionError("stream state is active or not independently verified")
        if self._require_private_recording:
            # Host must start its own *private* OBS recording separately.
            # A paused recording is not evidence of actual media capture.
            if (recording.get("outputActive") is not True
                    or recording.get("outputPaused") is not False):
                raise PermissionError("private recording is not active and unpaused")
        elif recording.get("outputActive") is not False:
            raise PermissionError("record state is active or not independently verified")
        for key in (
            "renderSkippedFrames", "renderTotalFrames",
            "outputSkippedFrames", "outputTotalFrames",
        ):
            if key not in stats:
                raise ValueError("OBS metrics incomplete")
        rs, rt, os, ot = (
            _count(stats["renderSkippedFrames"]),
            _count(stats["renderTotalFrames"]),
            _count(stats["outputSkippedFrames"]),
            _count(stats["outputTotalFrames"]),
        )
        if rs > rt or os > ot or rt == 0:
            raise ValueError("OBS metrics impossible or no rendered frames")
        candidate = ObsCounters(max(timestamps), rs, rt, os, ot)
        with self._lock:
            if self._count >= self._limit:
                raise RuntimeError("OBS evidence window full")
            if any(request_id in self._seen_ids for request_id in ids):
                raise ValueError("replayed OBS response identifier")
            previous = self._last
            if previous is not None:
                if min(timestamps) <= previous.at_monotonic_ms:
                    raise ValueError("OBS responses overlap a previous observation")
                if candidate.at_monotonic_ms - previous.at_monotonic_ms > self._gap:
                    raise ValueError("OBS evidence sample gap is too long")
                drs = rs - previous.render_skipped_frames
                drt = rt - previous.render_total_frames
                dos = os - previous.output_skipped_frames
                dot = ot - previous.output_total_frames
                if drt <= 0 or not 0 <= drs <= drt or dot < 0 or not 0 <= dos <= dot:
                    raise ValueError("OBS counter reset or impossible delta")
            else:
                drs = drt = dos = dot = 0

            if recorder is not None:
                # Do not advance gate counters if downstream validation fails.
                recorder.record(
                    "obs_stats_sampled", at_ms=candidate.at_monotonic_ms,
                    host_verified=True, skipped_frames=rs, total_frames=rt,
                )
            self._last = candidate
            self._seen_ids.update(ids)
            self._count += 1
            self._render_skipped_delta += drs
            self._render_total_delta += drt
            self._output_skipped_delta += dos
            self._output_total_delta += dot
            return candidate

    def report(self) -> dict[str, object]:
        """Only aggregate counters. Excludes request IDs and raw OBS messages."""
        with self._lock:
            return {
                "sample_count": self._count,
                "render_skipped_fraction": (
                    round(self._render_skipped_delta / self._render_total_delta, 6)
                    if self._render_total_delta else None
                ),
                "output_skipped_fraction": (
                    round(self._output_skipped_delta / self._output_total_delta, 6)
                    if self._output_total_delta else None
                ),
                "nonbroadcast_verified_only_at_sample_times": self._count > 0,
                "private_recording_verified_only_at_sample_times": (
                    self._require_private_recording and self._count > 0
                ),
                "note": "read-only snapshots; not continuous capture proof, audio proof, game FPS or broadcast authorization",
            }


__all__ = ["ObsReadOnlyWitness", "ObsCounters", "ObsReadOnlyEvidenceGate"]
