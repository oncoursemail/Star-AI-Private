import pytest

from star.obs_stream_status import (
    ObsStreamStatusSnapshot,
    ObsStreamStatusWindow,
    parse_get_stream_status_response,
)


def payload(**overrides):
    value = {
        "outputActive": True,
        "outputReconnecting": False,
        "outputTimecode": "00:00:10.000",
        "outputDuration": 10_000,
        "outputCongestion": 0.0,
        "outputBytes": 1_000_000,
        "outputSkippedFrames": 10,
        "outputTotalFrames": 1_000,
        "privateField": "must not be copied",
    }
    value.update(overrides)
    return value


def sample(
    *,
    at=1_000.0,
    obs="obs-a",
    stream="stream-a",
    active=True,
    reconnecting=False,
    bytes_sent=1_000_000,
    skipped=10,
    total=1_000,
    congestion=0.0,
    duration=10_000,
    timecode="00:00:10.000",
):
    return parse_get_stream_status_response(
        payload(
            outputActive=active,
            outputReconnecting=reconnecting,
            outputBytes=bytes_sent,
            outputSkippedFrames=skipped,
            outputTotalFrames=total,
            outputCongestion=congestion,
            outputDuration=duration,
            outputTimecode=timecode,
        ),
        obs_epoch=obs,
        stream_epoch=stream,
        sampled_at_ms=at,
    )


def test_parser_reads_allowlisted_fields_and_ignores_unknown_fields():
    result = parse_get_stream_status_response(
        payload(), obs_epoch="obs-1", stream_epoch="stream-1", sampled_at_ms=10.0
    )
    assert result.output_active is True
    assert result.output_congestion == 0.0
    assert result.output_bytes == 1_000_000
    assert not hasattr(result, "privateField")


def test_parser_accepts_null_congestion_without_coercing_it_to_zero():
    result = parse_get_stream_status_response(
        payload(outputCongestion=None),
        obs_epoch="obs-1",
        stream_epoch="stream-1",
        sampled_at_ms=10.0,
    )
    assert result.output_congestion is None


def test_parser_treats_missing_congestion_as_unknown():
    data = payload()
    data.pop("outputCongestion")
    result = parse_get_stream_status_response(
        data, obs_epoch="obs-1", stream_epoch="stream-1", sampled_at_ms=10.0
    )
    assert result.output_congestion is None


@pytest.mark.parametrize("value", [True, -0.01, 1.01, float("nan"), float("inf"), "0.5"])
def test_parser_rejects_invalid_congestion(value):
    with pytest.raises(ValueError):
        parse_get_stream_status_response(
            payload(outputCongestion=value),
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
        )


def test_parser_requires_core_fields():
    data = payload()
    data.pop("outputBytes")
    with pytest.raises(ValueError, match="missing required"):
        parse_get_stream_status_response(
            data, obs_epoch="obs-1", stream_epoch="stream-1", sampled_at_ms=10.0
        )


@pytest.mark.parametrize("field", ["outputActive", "outputReconnecting"])
@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_parser_rejects_non_boolean_state_fields(field, value):
    with pytest.raises(ValueError, match="Booleans"):
        parse_get_stream_status_response(
            payload(**{field: value}),
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
        )


@pytest.mark.parametrize("field,value", [
    ("outputBytes", True),
    ("outputBytes", -1),
    ("outputBytes", 1.5),
    ("outputSkippedFrames", float("nan")),
    ("outputTotalFrames", 2**54),
])
def test_parser_rejects_invalid_counters(field, value):
    with pytest.raises(ValueError):
        parse_get_stream_status_response(
            payload(**{field: value}),
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
        )


def test_parser_accepts_optional_duration_and_timecode_absence():
    data = payload()
    data.pop("outputDuration")
    data.pop("outputTimecode")
    result = parse_get_stream_status_response(
        data, obs_epoch="obs-1", stream_epoch="stream-1", sampled_at_ms=10.0
    )
    assert result.reported_duration_ms is None
    assert result.reported_timecode is None


def test_first_sample_is_baseline_and_has_no_throughput():
    result = ObsStreamStatusWindow().push(sample())
    assert result.status == "baseline"
    assert result.observed_bytes_per_second is None


def test_throughput_uses_monotonic_clock_not_obs_reported_duration():
    window = ObsStreamStatusWindow()
    window.push(sample(at=1_000.0, bytes_sent=1_000, duration=10_000))
    result = window.push(sample(
        at=2_000.0,
        bytes_sent=1_001_000,
        duration=99_999_999,
        timecode="99:99:99.999",
    ))
    assert result.status == "ok"
    assert result.interval_ms == 1_000.0
    assert result.bytes_delta == 1_000_000
    assert result.observed_bytes_per_second == 1_000_000.0
    assert result.reported_duration_ms == 99_999_999


def test_null_congestion_does_not_hide_valid_monotonic_throughput():
    window = ObsStreamStatusWindow()
    window.push(sample())
    result = window.push(sample(at=2_000.0, bytes_sent=1_250_000, congestion=None))
    assert result.status == "ok"
    assert result.output_congestion is None
    assert result.observed_bytes_per_second == 250_000.0


def test_inactive_output_never_reports_throughput():
    window = ObsStreamStatusWindow()
    window.push(sample(active=False, bytes_sent=0))
    result = window.push(sample(at=2_000.0, active=False, bytes_sent=10_000))
    assert result.status == "inactive"
    assert result.observed_bytes_per_second is None


def test_active_state_transition_discards_cross_state_interval():
    window = ObsStreamStatusWindow()
    window.push(sample(active=False, bytes_sent=0))
    changed = window.push(sample(at=2_000.0, active=True, bytes_sent=10_000))
    assert changed.status == "state_changed"
    assert changed.observed_bytes_per_second is None
    valid = window.push(sample(at=3_000.0, active=True, bytes_sent=20_000))
    assert valid.status == "ok"
    assert valid.observed_bytes_per_second == 10_000.0


def test_reconnecting_output_never_reports_throughput():
    window = ObsStreamStatusWindow()
    window.push(sample(reconnecting=False))
    changed = window.push(sample(at=2_000.0, reconnecting=True))
    assert changed.status == "state_changed"
    assert changed.observed_bytes_per_second is None
    waiting = window.push(sample(at=3_000.0, reconnecting=True))
    assert waiting.status == "reconnecting"
    assert waiting.observed_bytes_per_second is None


def test_reconnect_completion_requires_a_fresh_interval():
    window = ObsStreamStatusWindow()
    window.push(sample(reconnecting=True))
    changed = window.push(sample(at=2_000.0, reconnecting=False))
    assert changed.status == "state_changed"
    assert changed.observed_bytes_per_second is None
    valid = window.push(sample(at=3_000.0, reconnecting=False, bytes_sent=1_010_000))
    assert valid.status == "ok"


def test_epoch_change_discards_cross_session_interval():
    window = ObsStreamStatusWindow()
    window.push(sample())
    changed = window.push(sample(at=2_000.0, stream="stream-b"))
    assert changed.status == "epoch_changed"
    assert changed.observed_bytes_per_second is None


def test_obs_process_restart_discards_interval():
    window = ObsStreamStatusWindow()
    window.push(sample())
    changed = window.push(sample(at=2_000.0, obs="obs-b"))
    assert changed.status == "epoch_changed"


def test_counter_rollback_discards_interval_and_rebaselines():
    window = ObsStreamStatusWindow()
    window.push(sample())
    result = window.push(sample(at=2_000.0, bytes_sent=10))
    assert result.status == "counter_reset"
    next_result = window.push(sample(at=3_000.0, bytes_sent=20))
    assert next_result.status == "ok"
    assert next_result.bytes_delta == 10


def test_nonincreasing_monotonic_clock_invalidates_baseline():
    window = ObsStreamStatusWindow()
    window.push(sample(at=1_000.0))
    assert window.push(sample(at=1_000.0)).status == "invalid_interval"
    assert window.push(sample(at=2_000.0)).status == "baseline"


def test_zero_byte_delta_is_a_valid_zero_throughput_interval():
    window = ObsStreamStatusWindow()
    window.push(sample())
    result = window.push(sample(at=2_000.0, bytes_sent=1_000_000))
    assert result.status == "ok"
    assert result.observed_bytes_per_second == 0.0


def test_frame_counter_deltas_are_kept_separate_from_byte_throughput():
    window = ObsStreamStatusWindow()
    window.push(sample())
    result = window.push(sample(
        at=2_000.0,
        bytes_sent=1_500_000,
        skipped=15,
        total=1_400,
    ))
    assert result.status == "ok"
    assert result.skipped_frames_delta == 5
    assert result.total_frames_delta == 400
    assert result.observed_bytes_per_second == 500_000.0


def test_skipped_frames_are_not_assumed_to_be_bounded_by_delivered_frames():
    result = sample(skipped=2_000, total=1_000)
    assert result.output_skipped_frames == 2_000
    assert result.output_total_frames == 1_000


def test_sampler_rejects_wrong_snapshot_type():
    with pytest.raises(TypeError, match="ObsStreamStatusSnapshot"):
        ObsStreamStatusWindow().push({})  # type: ignore[arg-type]


def test_snapshot_rejects_invalid_epoch_and_timecode():
    with pytest.raises(ValueError, match="epoch identifier"):
        ObsStreamStatusSnapshot(
            obs_epoch="bad id",
            stream_epoch="stream-a",
            sampled_at_ms=1.0,
            output_active=True,
            output_reconnecting=False,
            output_bytes=0,
            output_skipped_frames=0,
            output_total_frames=0,
        )
    with pytest.raises(ValueError, match="Timecode"):
        parse_get_stream_status_response(
            payload(outputTimecode="x" * 33),
            obs_epoch="obs-a",
            stream_epoch="stream-a",
            sampled_at_ms=1.0,
        )
