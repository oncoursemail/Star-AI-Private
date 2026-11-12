"""Pure parser and epoch-safe sampler for OBS WebSocket GetStreamStatus.

The authenticated local WebSocket transport remains the host's responsibility.
This module never connects to OBS, reads credentials, changes stream state, or
runs in an audio/render callback.

Important protocol caveats:
- OBS may return outputCongestion: null when no network output is connected.
  None means unknown/unavailable, never zero congestion.
- outputDuration / outputTimecode are retained only as diagnostics. They are
  not used for elapsed time or throughput because Enhanced Broadcasting has
  produced reports where these values over-count wall-clock duration.
- Byte throughput uses the host's monotonic sample clock, not OBS duration.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping, cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\\Z")
_MAX_COUNTER = 9_007_199_254_740_991
_MAX_GAUGE = 1_000_000_000.0


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


def _epoch(value: object, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a bounded opaque epoch identifier")
    return value


@dataclass(frozen=True)
class ObsStreamStatusSnapshot:
    """Validated GetStreamStatus response with host-owned monotonic metadata."""

    obs_epoch: str
    stream_epoch: str
    sampled_at_ms: float
    output_active: bool
    output_reconnecting: bool
    output_bytes: int
    output_skipped_frames: int
    output_total_frames: int
    output_congestion: float | None = None
    reported_duration_ms: int | None = None
    reported_timecode: str | None = None

    def __post_init__(self) -> None:
        _epoch(self.obs_epoch, "obs_epoch")
        _epoch(self.stream_epoch, "stream_epoch")
        _number(self.sampled_at_ms, "sampled_at_ms", maximum=1e13)
        if type(self.output_active) is not bool:
            raise ValueError("output_active must be a Boolean")
        if type(self.output_reconnecting) is not bool:
            raise ValueError("output_reconnecting must be a Boolean")
        for name in ("output_bytes", "output_skipped_frames", "output_total_frames"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= _MAX_COUNTER:
                raise ValueError(f"{name} must be a safe nonnegative integer")
        if self.output_congestion is not None:
            _number(self.output_congestion, "output_congestion", maximum=1.0)
        if self.reported_duration_ms is not None:
            if type(self.reported_duration_ms) is not int or not 0 <= self.reported_duration_ms <= _MAX_COUNTER:
                raise ValueError("reported_duration_ms must be a safe nonnegative integer")
        if self.reported_timecode is not None:
            if type(self.reported_timecode) is not str or not 1 <= len(self.reported_timecode) <= 32:
                raise ValueError("reported_timecode must be a bounded string")


def parse_get_stream_status_response(
    response_data: Mapping[str, Any],
    *,
    obs_epoch: str,
    stream_epoch: str,
    sampled_at_ms: float,
) -> ObsStreamStatusSnapshot:
    """Parse allowlisted fields from the OBS GetStreamStatus responseData.

    outputCongestion is nullable/optional to tolerate OBS's observed null
    response when the output is not connected. Missing/unknown congestion is
    represented as None and is never coerced to 0.0.
    """
    if not isinstance(response_data, Mapping):
        raise ValueError("GetStreamStatus responseData must be an object")
    required = {
        "outputActive",
        "outputReconnecting",
        "outputBytes",
        "outputSkippedFrames",
        "outputTotalFrames",
    }
    if required - set(response_data):
        raise ValueError("GetStreamStatus responseData is missing required fields")
    active = response_data["outputActive"]
    reconnecting = response_data["outputReconnecting"]
    if type(active) is not bool or type(reconnecting) is not bool:
        raise ValueError("outputActive and outputReconnecting must be Booleans")

    congestion_value = response_data.get("outputCongestion")
    congestion = (
        None if congestion_value is None
        else _number(congestion_value, "outputCongestion", maximum=1.0)
    )
    duration_value = response_data.get("outputDuration")
    duration = None if duration_value is None else _counter(duration_value, "outputDuration")
    timecode_value = response_data.get("outputTimecode")
    if timecode_value is not None and (
        type(timecode_value) is not str or not 1 <= len(timecode_value) <= 32
    ):
        raise ValueError("outputTimecode must be a bounded string")

    return ObsStreamStatusSnapshot(
        obs_epoch=obs_epoch,
        stream_epoch=stream_epoch,
        sampled_at_ms=sampled_at_ms,
        output_active=active,
        output_reconnecting=reconnecting,
        output_bytes=_counter(response_data["outputBytes"], "outputBytes"),
        output_skipped_frames=_counter(
            response_data["outputSkippedFrames"], "outputSkippedFrames"
        ),
        output_total_frames=_counter(response_data["outputTotalFrames"], "outputTotalFrames"),
        output_congestion=congestion,
        reported_duration_ms=duration,
        reported_timecode=timecode_value,
    )


@dataclass(frozen=True)
class ObsStreamStatusInterval:
    """One output-status interval; missing evidence stays missing."""

    status: str
    output_active: bool | None = None
    output_reconnecting: bool | None = None
    output_congestion: float | None = None
    interval_ms: float | None = None
    bytes_delta: int | None = None
    observed_bytes_per_second: float | None = None
    skipped_frames_delta: int | None = None
    total_frames_delta: int | None = None
    reported_duration_ms: int | None = None
    reported_timecode: str | None = None
    reason: str = ""


class ObsStreamStatusWindow:
    """Calculate stream-output counter deltas within one monotonic epoch.

    A new OBS process epoch, stream epoch, or active/reconnecting state
    transition discards the cross-boundary interval. Inactive and reconnecting
    samples never produce throughput. The reported OBS duration/timecode never
    participates in elapsed-time or throughput calculations.
    """

    def __init__(self) -> None:
        self._previous: ObsStreamStatusSnapshot | None = None

    def reset(self) -> None:
        self._previous = None

    @staticmethod
    def _status(
        status: str,
        sample: ObsStreamStatusSnapshot,
        reason: str,
    ) -> ObsStreamStatusInterval:
        return ObsStreamStatusInterval(
            status=status,
            output_active=sample.output_active,
            output_reconnecting=sample.output_reconnecting,
            output_congestion=sample.output_congestion,
            reported_duration_ms=sample.reported_duration_ms,
            reported_timecode=sample.reported_timecode,
            reason=reason,
        )

    def push(self, sample: ObsStreamStatusSnapshot) -> ObsStreamStatusInterval:
        if type(sample) is not ObsStreamStatusSnapshot:
            raise TypeError("sample must be ObsStreamStatusSnapshot")
        previous = self._previous
        self._previous = sample
        if previous is None:
            return self._status("baseline", sample, "first sample establishes the baseline")
        if (sample.obs_epoch, sample.stream_epoch) != (previous.obs_epoch, previous.stream_epoch):
            return self._status(
                "epoch_changed", sample,
                "OBS process or stream session changed; interval baseline restarted",
            )
        elapsed = sample.sampled_at_ms - previous.sampled_at_ms
        if elapsed <= 0:
            self._previous = None
            return self._status(
                "invalid_interval", sample,
                "sample timestamps must increase on one monotonic host clock",
            )
        if (
            sample.output_active != previous.output_active
            or sample.output_reconnecting != previous.output_reconnecting
        ):
            return self._status(
                "state_changed", sample,
                "active/reconnecting state changed; cross-state interval discarded",
            )
        if not sample.output_active:
            return self._status("inactive", sample, "stream output is not active")
        if sample.output_reconnecting:
            return self._status("reconnecting", sample, "stream output is reconnecting")

        byte_delta = sample.output_bytes - previous.output_bytes
        skipped_delta = sample.output_skipped_frames - previous.output_skipped_frames
        total_delta = sample.output_total_frames - previous.output_total_frames
        if min(byte_delta, skipped_delta, total_delta) < 0:
            return self._status(
                "counter_reset", sample,
                "an output cumulative counter decreased; this interval is discarded",
            )

        return ObsStreamStatusInterval(
            status="ok",
            output_active=sample.output_active,
            output_reconnecting=sample.output_reconnecting,
            output_congestion=sample.output_congestion,
            interval_ms=round(elapsed, 3),
            bytes_delta=byte_delta,
            observed_bytes_per_second=round(byte_delta * 1000.0 / elapsed, 3),
            skipped_frames_delta=skipped_delta,
            total_frames_delta=total_delta,
            reported_duration_ms=sample.reported_duration_ms,
            reported_timecode=sample.reported_timecode,
        )


__all__ = [
    "ObsStreamStatusInterval",
    "ObsStreamStatusSnapshot",
    "ObsStreamStatusWindow",
    "parse_get_stream_status_response",
]
