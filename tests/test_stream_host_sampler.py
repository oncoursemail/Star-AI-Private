from __future__ import annotations

import pytest

from star.stream_host_sampler import (
    MetricObservation,
    StreamHostInputs,
    StreamHostSampler,
    TelemetryUnavailable,
)


def obs(value, at=9_900, epoch="boot-1"):
    return MetricObservation(value=value, captured_ms=at, clock_epoch=epoch)


def inputs(**overrides):
    values = {
        "seq": 1,
        "now_monotonic_ms": 10_000,
        "clock_epoch": "boot-1",
        "streaming": obs(False),
        "gaming": obs(False),
        "vram_free_mb": obs(3_000),
    }
    values.update(overrides)
    return StreamHostInputs(**values)


def test_idle_sample_uses_zero_only_for_known_inactive_lanes():
    sample = StreamHostSampler().build(inputs())
    assert sample.streaming is False
    assert sample.gaming is False
    assert sample.game_fps_p10 == 0.0
    assert sample.voice_p95_ms == 0.0
    assert sample.obs_dropped_pct == 0.0
    assert sample.audio_underruns == 0
    assert sample.vram_free_mb == 3_000
    assert sample.captured_ms == 9_900


def test_streaming_requires_every_live_stream_measurement():
    data = inputs(
        streaming=obs(True),
        voice_p95_ms=obs(320.0, at=9_950),
        obs_dropped_pct=obs(0.2, at=9_960),
        audio_underruns=obs(0, at=9_970),
    )
    sample = StreamHostSampler().build(data)
    assert sample.streaming is True
    assert sample.voice_p95_ms == 320.0
    assert sample.obs_dropped_pct == 0.2
    assert sample.audio_underruns == 0
    assert sample.captured_ms == 9_900


def test_streaming_missing_metric_is_not_fabricated_as_zero():
    data = inputs(streaming=obs(True), voice_p95_ms=obs(100.0), obs_dropped_pct=obs(0.0))
    with pytest.raises(TelemetryUnavailable, match="audio_underruns"):
        StreamHostSampler().build(data)


def test_gaming_requires_real_fps_measurement():
    data = inputs(gaming=obs(True))
    with pytest.raises(TelemetryUnavailable, match="game_fps_p10"):
        StreamHostSampler().build(data)


def test_gaming_sample_uses_measured_fps():
    data = inputs(gaming=obs(True), game_fps_p10=obs(58.5, at=9_980))
    sample = StreamHostSampler().build(data)
    assert sample.gaming is True
    assert sample.game_fps_p10 == 58.5


def test_missing_vram_never_becomes_zero_or_free():
    data = inputs(vram_free_mb=None)
    with pytest.raises(TelemetryUnavailable, match="vram_free_mb is unavailable"):
        StreamHostSampler().build(data)


def test_stale_active_metric_fails_closed():
    data = inputs(
        streaming=obs(True),
        voice_p95_ms=obs(200.0, at=6_000),
        obs_dropped_pct=obs(0.0),
        audio_underruns=obs(0),
    )
    with pytest.raises(TelemetryUnavailable, match="stale"):
        StreamHostSampler(max_age_ms=3_000).build(data)


def test_future_dated_metric_is_rejected():
    data = inputs(vram_free_mb=obs(3_000, at=10_001))
    with pytest.raises(ValueError, match="future-dated"):
        StreamHostSampler().build(data)


def test_cross_epoch_observation_is_rejected():
    data = inputs(vram_free_mb=obs(3_000, epoch="other-boot"))
    with pytest.raises(TelemetryUnavailable, match="another monotonic clock epoch"):
        StreamHostSampler().build(data)


def test_clock_epoch_change_requires_new_runtime():
    sampler = StreamHostSampler()
    sampler.build(inputs())
    data = inputs(seq=2, clock_epoch="boot-2",
                  streaming=obs(False, epoch="boot-2"),
                  gaming=obs(False, epoch="boot-2"),
                  vram_free_mb=obs(3_000, epoch="boot-2"))
    with pytest.raises(TelemetryUnavailable, match="clock epoch changed"):
        sampler.build(data)


def test_duplicate_or_replayed_sequence_is_rejected():
    sampler = StreamHostSampler()
    sampler.build(inputs())
    with pytest.raises(ValueError, match="sequence must increase"):
        sampler.build(inputs(seq=1))


def test_failed_build_does_not_consume_sequence():
    sampler = StreamHostSampler()
    bad = inputs(streaming=obs(True))
    with pytest.raises(TelemetryUnavailable):
        sampler.build(bad)
    good = inputs()
    assert sampler.build(good).seq == 1


def test_bool_is_not_accepted_as_a_numeric_measurement():
    data = inputs(vram_free_mb=obs(True))
    with pytest.raises(ValueError, match="bounded nonnegative integer"):
        StreamHostSampler().build(data)


def test_inactive_optional_metric_is_ignored_but_active_state_is_explicit():
    data = inputs(game_fps_p10=None, voice_p95_ms=None, obs_dropped_pct=None, audio_underruns=None)
    sample = StreamHostSampler().build(data)
    assert sample.game_fps_p10 == 0.0
    assert sample.voice_p95_ms == 0.0


def test_missing_stream_state_is_not_assumed_idle():
    data = inputs(streaming=None)
    with pytest.raises(TelemetryUnavailable, match="streaming is unavailable"):
        StreamHostSampler().build(data)


def test_host_now_clock_must_not_regress():
    sampler = StreamHostSampler()
    sampler.build(inputs())
    data = inputs(seq=2, now_monotonic_ms=9_999,
                  streaming=obs(False, at=9_910),
                  gaming=obs(False, at=9_910),
                  vram_free_mb=obs(3_000, at=9_910))
    with pytest.raises(ValueError, match="clock moved backwards"):
        sampler.build(data)


def test_assembled_sample_timestamp_must_increase():
    sampler = StreamHostSampler()
    sampler.build(inputs())
    data = inputs(seq=2, now_monotonic_ms=10_100,
                  streaming=obs(False, at=9_800),
                  gaming=obs(False, at=9_800),
                  vram_free_mb=obs(3_000, at=9_800))
    with pytest.raises(ValueError, match="sample timestamp must increase"):
        sampler.build(data)



def test_extreme_integer_metric_is_rejected_without_overflow():
    data = inputs(gaming=obs(True), game_fps_p10=obs(10**1000))
    with pytest.raises(ValueError, match="finite number in range"):
        StreamHostSampler().build(data)
