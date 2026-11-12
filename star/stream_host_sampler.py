"""Fail-closed assembly of trusted host observations into the stream QoS sample.

This module is the narrow join between independently collected Windows/OBS/
voice/game telemetry and the pure StreamLoadGovernor policy. It performs no
hardware I/O, network I/O, process control, or authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .stream_load_governor import StreamSample

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_CLOCK_MS = 10**12
_MAX_SEQ = 1_000_000_000


class TelemetryUnavailable(RuntimeError):
    """A required active-workload observation is absent, stale, or from another clock epoch."""


@dataclass(frozen=True)
class MetricObservation:
    """One typed-at-use value stamped by the host's shared monotonic clock."""

    value: object
    captured_ms: int
    clock_epoch: str


@dataclass(frozen=True)
class StreamHostInputs:
    """Inputs from the host collectors; None means unknown, never zero."""

    seq: int
    now_monotonic_ms: int
    clock_epoch: str
    streaming: MetricObservation | None
    gaming: MetricObservation | None
    vram_free_mb: MetricObservation | None
    game_fps_p10: MetricObservation | None = None
    voice_p95_ms: MetricObservation | None = None
    obs_dropped_pct: MetricObservation | None = None
    audio_underruns: MetricObservation | None = None


def _metadata(observation: MetricObservation | None, *, label: str, inputs: StreamHostInputs,
              max_age_ms: int) -> int:
    if observation is None:
        raise TelemetryUnavailable(f"{label} is unavailable")
    if not isinstance(observation, MetricObservation):
        raise TypeError(f"{label} must be MetricObservation")
    if type(observation.clock_epoch) is not str or not _ID.fullmatch(observation.clock_epoch):
        raise ValueError(f"{label} clock_epoch must be a bounded opaque identifier")
    if observation.clock_epoch != inputs.clock_epoch:
        raise TelemetryUnavailable(f"{label} belongs to another monotonic clock epoch")
    captured = observation.captured_ms
    if type(captured) is not int or not 0 <= captured <= _MAX_CLOCK_MS:
        raise ValueError(f"{label} captured_ms must be a bounded monotonic integer")
    if captured > inputs.now_monotonic_ms:
        raise ValueError(f"{label} is future-dated")
    if inputs.now_monotonic_ms - captured > max_age_ms:
        raise TelemetryUnavailable(f"{label} is stale")
    return captured


def _bool_value(observation: MetricObservation | None, *, label: str, inputs: StreamHostInputs,
                max_age_ms: int) -> tuple[bool, int]:
    captured = _metadata(observation, label=label, inputs=inputs, max_age_ms=max_age_ms)
    if type(observation.value) is not bool:
        raise ValueError(f"{label} must be an explicit boolean")
    return observation.value, captured


def _number_value(observation: MetricObservation | None, *, label: str, inputs: StreamHostInputs,
                  max_age_ms: int, maximum: float) -> tuple[float, int]:
    captured = _metadata(observation, label=label, inputs=inputs, max_age_ms=max_age_ms)
    value = observation.value
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    else:
        raise ValueError(f"{label} must be a finite number in range")
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f"{label} must be a finite number in range")
    return number, captured


def _integer_value(observation: MetricObservation | None, *, label: str, inputs: StreamHostInputs,
                   max_age_ms: int, maximum: int) -> tuple[int, int]:
    captured = _metadata(observation, label=label, inputs=inputs, max_age_ms=max_age_ms)
    value = observation.value
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    return value, captured


class StreamHostSampler:
    """Build ordered QoS samples without converting missing telemetry to healthy zeros.

    Required measurements:
      * stream and game state are always explicit;
      * VRAM free space is always measured;
      * while gaming, game FPS p10 is required;
      * while streaming, voice p95, OBS drop percentage, and audio underruns are required.

    Metrics for an inactive workload are encoded as zero only as an explicit
    not-applicable value after the corresponding state is known false. Missing
    measurements for an active workload raise TelemetryUnavailable, so callers
    must not feed the scheduler a fabricated healthy sample.
    """

    def __init__(self, *, max_age_ms: int = 3_000) -> None:
        if type(max_age_ms) is not int or not 100 <= max_age_ms <= 60_000:
            raise ValueError("max_age_ms must be in 100..60000")
        self.max_age_ms = max_age_ms
        self._clock_epoch: str | None = None
        self._last_seq = 0
        self._last_now_ms: int | None = None
        self._last_sample_ms: int | None = None

    def build(self, inputs: StreamHostInputs) -> StreamSample:
        if not isinstance(inputs, StreamHostInputs):
            raise TypeError("inputs must be StreamHostInputs")
        if type(inputs.seq) is not int or not 1 <= inputs.seq <= _MAX_SEQ:
            raise ValueError("seq must be a positive bounded integer")
        now = inputs.now_monotonic_ms
        if type(now) is not int or not 0 <= now <= _MAX_CLOCK_MS:
            raise ValueError("now_monotonic_ms must be a bounded monotonic integer")
        if type(inputs.clock_epoch) is not str or not _ID.fullmatch(inputs.clock_epoch):
            raise ValueError("clock_epoch must be a bounded opaque identifier")
        if self._clock_epoch is not None and inputs.clock_epoch != self._clock_epoch:
            raise TelemetryUnavailable("host clock epoch changed; rebuild the sampler and runtime")
        if self._last_now_ms is not None and now < self._last_now_ms:
            raise ValueError("host monotonic clock moved backwards")
        if inputs.seq <= self._last_seq:
            raise ValueError("sample sequence must increase")

        streaming, stream_at = _bool_value(
            inputs.streaming, label="streaming", inputs=inputs, max_age_ms=self.max_age_ms
        )
        gaming, game_state_at = _bool_value(
            inputs.gaming, label="gaming", inputs=inputs, max_age_ms=self.max_age_ms
        )
        vram_free_mb, vram_at = _integer_value(
            inputs.vram_free_mb, label="vram_free_mb", inputs=inputs,
            max_age_ms=self.max_age_ms, maximum=1_000_000
        )

        timestamps = [stream_at, game_state_at, vram_at]

        if gaming:
            if inputs.game_fps_p10 is None:
                raise TelemetryUnavailable("game_fps_p10 is required while gaming")
            game_fps_p10, captured = _number_value(
                inputs.game_fps_p10, label="game_fps_p10", inputs=inputs,
                max_age_ms=self.max_age_ms, maximum=500.0
            )
            timestamps.append(captured)
        else:
            game_fps_p10 = 0.0

        if streaming:
            if inputs.voice_p95_ms is None:
                raise TelemetryUnavailable("voice_p95_ms is required while streaming")
            if inputs.obs_dropped_pct is None:
                raise TelemetryUnavailable("obs_dropped_pct is required while streaming")
            if inputs.audio_underruns is None:
                raise TelemetryUnavailable("audio_underruns is required while streaming")
            voice_p95_ms, voice_at = _number_value(
                inputs.voice_p95_ms, label="voice_p95_ms", inputs=inputs,
                max_age_ms=self.max_age_ms, maximum=60_000.0
            )
            obs_dropped_pct, obs_at = _number_value(
                inputs.obs_dropped_pct, label="obs_dropped_pct", inputs=inputs,
                max_age_ms=self.max_age_ms, maximum=100.0
            )
            audio_underruns, audio_at = _integer_value(
                inputs.audio_underruns, label="audio_underruns", inputs=inputs,
                max_age_ms=self.max_age_ms, maximum=1_000_000
            )
            timestamps.extend((voice_at, obs_at, audio_at))
        else:
            voice_p95_ms = 0.0
            obs_dropped_pct = 0.0
            audio_underruns = 0

        sample = StreamSample(
            seq=inputs.seq,
            captured_ms=min(timestamps),
            streaming=streaming,
            gaming=gaming,
            game_fps_p10=game_fps_p10,
            voice_p95_ms=voice_p95_ms,
            obs_dropped_pct=obs_dropped_pct,
            vram_free_mb=vram_free_mb,
            audio_underruns=audio_underruns,
        )
        if self._last_sample_ms is not None and sample.captured_ms <= self._last_sample_ms:
            raise ValueError("assembled sample timestamp must increase")
        self._clock_epoch = inputs.clock_epoch
        self._last_seq = inputs.seq
        self._last_now_ms = now
        self._last_sample_ms = sample.captured_ms
        return sample
