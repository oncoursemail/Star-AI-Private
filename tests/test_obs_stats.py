import pytest

from star.obs_stats import (
    ObsStatsSnapshot,
    ObsStatsWindow,
    parse_get_stats_response,
)


def payload(**overrides):
    value = {
        "activeFps": 60.0,
        "averageFrameRenderTime": 5.0,
        "renderSkippedFrames": 2,
        "renderTotalFrames": 1000,
        "outputSkippedFrames": 1,
        "outputTotalFrames": 990,
        "cpuUsage": 12.5,
        "memoryUsage": 512.0,
        "webSocketSessionIncomingMessages": 12,
    }
    value.update(overrides)
    return value


def sample(
    *,
    at=1000.0,
    obs="obs-a",
    stream="stream-a",
    render_skipped=2,
    render_total=1000,
    output_skipped=1,
    output_total=990,
    fps=60.0,
):
    return parse_get_stats_response(
        payload(
            activeFps=fps,
            renderSkippedFrames=render_skipped,
            renderTotalFrames=render_total,
            outputSkippedFrames=output_skipped,
            outputTotalFrames=output_total,
        ),
        obs_epoch=obs,
        stream_epoch=stream,
        sampled_at_ms=at,
    )


def test_parser_reads_allowlisted_stats_and_ignores_unknown_fields():
    result = parse_get_stats_response(
        payload(secret="must not be copied"),
        obs_epoch="obs-1",
        stream_epoch="stream-1",
        sampled_at_ms=10.0,
    )
    assert result.active_fps == 60.0
    assert result.cpu_usage_percent == 12.5
    assert result.memory_usage_mib == 512.0
    assert not hasattr(result, "secret")


def test_parser_allows_absent_optional_cpu_and_memory():
    data = payload()
    data.pop("cpuUsage")
    data.pop("memoryUsage")
    result = parse_get_stats_response(
        data, obs_epoch="obs-1", stream_epoch="stream-1", sampled_at_ms=10.0
    )
    assert result.cpu_usage_percent is None
    assert result.memory_usage_mib is None


def test_parser_requires_core_get_stats_fields():
    data = payload()
    data.pop("renderTotalFrames")
    with pytest.raises(ValueError, match="missing required"):
        parse_get_stats_response(
            data, obs_epoch="obs-1", stream_epoch="stream-1", sampled_at_ms=10.0
        )


@pytest.mark.parametrize("value", [True, "60", float("nan"), float("inf"), -1, 1e20])
def test_parser_rejects_invalid_gauges(value):
    with pytest.raises(ValueError):
        parse_get_stats_response(
            payload(activeFps=value),
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
        )


@pytest.mark.parametrize("value", [True, 1.5, -1, float("nan"), 1e20])
def test_parser_rejects_invalid_counters(value):
    with pytest.raises(ValueError):
        parse_get_stats_response(
            payload(renderSkippedFrames=value),
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
        )


@pytest.mark.parametrize("field,value", [
    ("cpuUsage", 100.1),
    ("memoryUsage", -1),
])
def test_parser_validates_optional_fields(field, value):
    with pytest.raises(ValueError):
        parse_get_stats_response(
            payload(**{field: value}),
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
        )


@pytest.mark.parametrize("obs,stream", [("", "stream-1"), ("obs-1", "bad id")])
def test_parser_rejects_invalid_epoch_ids(obs, stream):
    with pytest.raises(ValueError, match="epoch identifier"):
        parse_get_stats_response(
            payload(), obs_epoch=obs, stream_epoch=stream, sampled_at_ms=10.0
        )


def test_snapshot_rejects_skips_exceeding_cumulative_total():
    with pytest.raises(ValueError, match="cannot exceed"):
        ObsStatsSnapshot(
            obs_epoch="obs-1",
            stream_epoch="stream-1",
            sampled_at_ms=10.0,
            active_fps=60.0,
            average_frame_render_time_ms=5.0,
            render_skipped_frames=11,
            render_total_frames=10,
            output_skipped_frames=0,
            output_total_frames=10,
        )


def test_first_sample_is_baseline_and_emits_no_fake_zero_rate():
    window = ObsStatsWindow()
    result = window.push(sample())
    assert result.status == "baseline"
    assert result.render_skip_rate is None
    assert result.output_skip_rate is None
    with pytest.raises(ValueError, match="valid OBS interval"):
        result.rehearsal_counts()


def test_valid_interval_keeps_render_and_output_channels_separate():
    window = ObsStatsWindow()
    window.push(sample())
    result = window.push(sample(
        at=2000.0,
        render_skipped=4,
        render_total=1200,
        output_skipped=3,
        output_total=1390,
        fps=59.9,
    ))
    assert result.status == "ok"
    assert result.interval_ms == 1000.0
    assert result.render_skipped_delta == 2
    assert result.render_total_delta == 200
    assert result.render_skip_rate == 0.01
    assert result.output_skipped_delta == 2
    assert result.output_total_delta == 400
    assert result.output_skip_rate == 0.005
    assert result.active_fps == 59.9
    assert result.rehearsal_counts() == {
        "obs_render_skipped_frames": 2,
        "obs_render_total_frames": 200,
        "obs_output_skipped_frames": 2,
        "obs_output_total_frames": 400,
    }


@pytest.mark.parametrize("obs,stream", [
    ("obs-b", "stream-a"),
    ("obs-a", "stream-b"),
])
def test_epoch_change_restarts_baseline(obs, stream):
    window = ObsStatsWindow()
    window.push(sample())
    changed = window.push(sample(at=2000.0, obs=obs, stream=stream))
    assert changed.status == "epoch_changed"
    assert changed.render_skip_rate is None
    assert window.push(sample(at=3000.0, obs=obs, stream=stream,
                              render_skipped=3, render_total=1100,
                              output_skipped=2, output_total=1090)).status == "ok"


def test_counter_rollback_discards_interval_and_rebaselines():
    window = ObsStatsWindow()
    window.push(sample())
    result = window.push(sample(at=2000.0, render_skipped=1, render_total=900,
                                output_skipped=1, output_total=900))
    assert result.status == "counter_reset"
    next_result = window.push(sample(at=3000.0, render_skipped=2, render_total=1000,
                                     output_skipped=2, output_total=1000))
    assert next_result.status == "ok"


def test_nonincreasing_clock_invalidates_baseline():
    window = ObsStatsWindow()
    window.push(sample(at=1000.0))
    assert window.push(sample(at=1000.0)).status == "invalid_interval"
    assert window.push(sample(at=2000.0)).status == "baseline"


def test_zero_frame_delta_is_not_reported_as_zero_error_rate():
    window = ObsStatsWindow()
    window.push(sample())
    result = window.push(sample(at=2000.0))
    assert result.status == "ok"
    assert result.render_skip_rate is None
    assert result.output_skip_rate is None


def test_inconsistent_interval_counter_deltas_are_rejected():
    window = ObsStatsWindow()
    window.push(sample(render_skipped=2, render_total=100))
    result = window.push(sample(at=2000.0, render_skipped=5, render_total=102))
    assert result.status == "inconsistent_counters"
    assert result.render_skip_rate is None


def test_reset_clears_previous_sample():
    window = ObsStatsWindow()
    window.push(sample())
    window.reset()
    assert window.push(sample(at=2000.0)).status == "baseline"


def test_sampler_rejects_wrong_sample_type():
    with pytest.raises(TypeError, match="ObsStatsSnapshot"):
        ObsStatsWindow().push({})  # type: ignore[arg-type]
