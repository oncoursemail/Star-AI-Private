"""Pure parser and epoch-safe interval sampler for OBS WebSocket GetStats.

The host owns the authenticated local WebSocket transport and supplies opaque
OBS-process and stream-session epochs. This module performs no network I/O,
stores no credentials, changes no OBS state, and never runs on a render/audio
callback. It emits only numeric observations suitable for private rehearsal
aggregation.

OBS render/output counters are cumulative. A stream-session baseline must be
captured on the first sample after each stream start; OBS-process restarts and
counter resets invalidate an interval rather than manufacturing a zero rate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping, cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_COUNTER = 9_007_199_254_740_991  # largest integer exactly representable by JSON/JS Number
_MAX_GAUGE = 1_000_000_000.0

_REQUIRED = frozenset({
    "activeFps",
    "averageFrameRenderTime",
    "renderSkippedFrames",
    "renderTotalFrames",
    "outputSkippedFrames",
    "outputTotalFrames",
})


def _number(value: object, name: str, *, maximum: float = _MAX_GAUGE) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a JSON number")
    try:
        result = float(cast(float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and nonnegative") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValueError(f"{name} is outside the supported range")
    return result


def _counter(value: object, name: str) -> int:
    number = _number(value, name, maximum=float(_MAX_COUNTER))
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer-valued counter")
    return int(number)


@dataclass(frozen=True)
class ObsStatsSnapshot:
    """Validated GetStats sample with host-owned monotonic time and epochs."""

    obs_epoch: str
    stream_epoch: str
    sampled_at_ms: float
    active_fps: float
    average_frame_render_time_ms: float
    render_skipped_frames: int
    render_total_frames: int
    output_skipped_frames: int
    output_total_frames: int
    cpu_usage_percent: float | None = None
    memory_usage_mib: float | None = None

    def __post_init__(self) -> None:
        for name in ("obs_epoch", "stream_epoch"):
            value = getattr(self, name)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"{name} must be a bounded opaque epoch identifier")
        _number(self.sampled_at_ms, "sampled_at_ms", maximum=1e13)
        _number(self.active_fps, "active_fps")
        _number(self.average_frame_render_time_ms, "average_frame_render_time_ms")
        for name in (
            "render_skipped_frames",
            "render_total_frames",
            "output_skipped_frames",
            "output_total_frames",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= _MAX_COUNTER:
                raise ValueError(f"{name} must be a safe nonnegative integer")
        if self.render_skipped_frames > self.render_total_frames:
            raise ValueError("render skipped frames cannot exceed render total frames")
        if self.output_skipped_frames > self.output_total_frames:
            raise ValueError("output skipped frames cannot exceed output total frames")
        if self.cpu_usage_percent is not None:
            cpu = _number(self.cpu_usage_percent, "cpu_usage_percent", maximum=100.0)
            if cpu > 100:
                raise ValueError("cpu_usage_percent must be in 0..100")
        if self.memory_usage_mib is not None:
            _number(self.memory_usage_mib, "memory_usage_mib")


def parse_get_stats_response(
    response_data: Mapping[str, Any],
    *,
    obs_epoch: str,
    stream_epoch: str,
    sampled_at_ms: float,
) -> ObsStatsSnapshot:
    """Parse only allowlisted fields from OBS GetStats responseData.

    Unknown fields are ignored, never copied into the returned object. The
    caller must use a new obs_epoch after OBS restarts and a new stream_epoch
    after each stream start. This function accepts responseData, not the
    surrounding obs-websocket RPC envelope.
    """
    if not isinstance(response_data, Mapping):
        raise ValueError("GetStats responseData must be an object")
    missing = _REQUIRED - set(response_data)
    if missing:
        raise ValueError("GetStats responseData is missing required fields")
    return ObsStatsSnapshot(
        obs_epoch=obs_epoch,
        stream_epoch=stream_epoch,
        sampled_at_ms=sampled_at_ms,
        active_fps=_number(response_data["activeFps"], "activeFps"),
        average_frame_render_time_ms=_number(
            response_data["averageFrameRenderTime"], "averageFrameRenderTime"
        ),
        render_skipped_frames=_counter(response_data["renderSkippedFrames"], "renderSkippedFrames"),
        render_total_frames=_counter(response_data["renderTotalFrames"], "renderTotalFrames"),
        output_skipped_frames=_counter(response_data["outputSkippedFrames"], "outputSkippedFrames"),
        output_total_frames=_counter(response_data["outputTotalFrames"], "outputTotalFrames"),
        cpu_usage_percent=(
            _number(response_data["cpuUsage"], "cpuUsage", maximum=100.0)
            if "cpuUsage" in response_data and response_data["cpuUsage"] is not None
            else None
        ),
        memory_usage_mib=(
            _number(response_data["memoryUsage"], "memoryUsage")
            if "memoryUsage" in response_data and response_data["memoryUsage"] is not None
            else None
        ),
    )


@dataclass(frozen=True)
class ObsStatsInterval:
    """One interval result; rates are None until a valid denominator exists."""

    status: str
    interval_ms: float | None = None
    render_skipped_delta: int | None = None
    render_total_delta: int | None = None
    render_skip_rate: float | None = None
    output_skipped_delta: int | None = None
    output_total_delta: int | None = None
    output_skip_rate: float | None = None
    active_fps: float | None = None
    average_frame_render_time_ms: float | None = None
    cpu_usage_percent: float | None = None
    memory_usage_mib: float | None = None
    reason: str = ""

    def rehearsal_counts(self) -> dict[str, int]:
        """Return the two separate count pairs expected by STAR's rehearsal gate."""
        if self.status != "ok" or any(value is None for value in (
            self.render_skipped_delta, self.render_total_delta,
            self.output_skipped_delta, self.output_total_delta,
        )):
            raise ValueError("only a valid OBS interval can contribute rehearsal counts")
        return {
            "obs_render_skipped_frames": cast(int, self.render_skipped_delta),
            "obs_render_total_frames": cast(int, self.render_total_delta),
            "obs_output_skipped_frames": cast(int, self.output_skipped_delta),
            "obs_output_total_frames": cast(int, self.output_total_delta),
        }


class ObsStatsWindow:
    """Calculate epoch-scoped counter deltas without crossing session boundaries.

    The first sample in each (OBS process, stream) epoch is a baseline. A new
    epoch, counter rollback, or non-increasing monotonic timestamp never yields
    a rate. The host should start a fresh stream_epoch on every stream start,
    even when OBS itself remains open between streams.
    """

    def __init__(self) -> None:
        self._previous: ObsStatsSnapshot | None = None

    def reset(self) -> None:
        self._previous = None

    def push(self, sample: ObsStatsSnapshot) -> ObsStatsInterval:
        if type(sample) is not ObsStatsSnapshot:
            raise TypeError("sample must be ObsStatsSnapshot")
        previous = self._previous
        self._previous = sample
        if previous is None:
            return ObsStatsInterval(status="baseline", reason="first sample establishes the baseline")
        if (sample.obs_epoch, sample.stream_epoch) != (previous.obs_epoch, previous.stream_epoch):
            return ObsStatsInterval(
                status="epoch_changed",
                reason="OBS process or stream session changed; interval baseline restarted",
            )
        elapsed = sample.sampled_at_ms - previous.sampled_at_ms
        if elapsed <= 0:
            self._previous = None
            return ObsStatsInterval(
                status="invalid_interval",
                reason="sample timestamps must increase on one monotonic host clock",
            )
        counter_names = (
            "render_skipped_frames",
            "render_total_frames",
            "output_skipped_frames",
            "output_total_frames",
        )
        deltas = {
            name: getattr(sample, name) - getattr(previous, name)
            for name in counter_names
        }
        if any(value < 0 for value in deltas.values()):
            return ObsStatsInterval(
                status="counter_reset",
                reason="an OBS cumulative counter decreased; this interval is discarded",
            )
        if deltas["render_skipped_frames"] > deltas["render_total_frames"]:
            return ObsStatsInterval(
                status="inconsistent_counters",
                reason="render skip delta exceeds render total delta",
            )
        if deltas["output_skipped_frames"] > deltas["output_total_frames"]:
            return ObsStatsInterval(
                status="inconsistent_counters",
                reason="output skip delta exceeds output total delta",
            )
        render_total = deltas["render_total_frames"]
        output_total = deltas["output_total_frames"]
        return ObsStatsInterval(
            status="ok",
            interval_ms=round(elapsed, 3),
            render_skipped_delta=deltas["render_skipped_frames"],
            render_total_delta=render_total,
            render_skip_rate=(
                round(deltas["render_skipped_frames"] / render_total, 8)
                if render_total > 0 else None
            ),
            output_skipped_delta=deltas["output_skipped_frames"],
            output_total_delta=output_total,
            output_skip_rate=(
                round(deltas["output_skipped_frames"] / output_total, 8)
                if output_total > 0 else None
            ),
            active_fps=sample.active_fps,
            average_frame_render_time_ms=sample.average_frame_render_time_ms,
            cpu_usage_percent=sample.cpu_usage_percent,
            memory_usage_mib=sample.memory_usage_mib,
        )


__all__ = [
    "ObsStatsInterval",
    "ObsStatsSnapshot",
    "ObsStatsWindow",
    "parse_get_stats_response",
]
