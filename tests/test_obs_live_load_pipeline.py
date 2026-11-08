"""Paired OBS -> live gaming governor: deterministic, entirely offline."""

import pytest

from star.obs_live_load_pipeline import ObsLiveLoadPipeline
from star.stream_load_governor import StreamLoadGovernor, StreamLoadSample
from star.stream_load_host_bridge import HostLoadReceipt


def data(n: int, *, dropped: int = 0, sent: int | None = None):
    t = 1000 + n * 500
    return (
        {
            "renderSkippedFrames": 0,
            "renderTotalFrames": 1000 + n * 60,
            "outputSkippedFrames": 0,
            "outputTotalFrames": 1000 + n * 60,
        },
        {
            "outputActive": True,
            "outputReconnecting": False,
            "outputDuration": t,
            "outputSkippedFrames": dropped,
            "outputTotalFrames": 100 + n * 50 if sent is None else sent,
        },
    )


def load(n: int, **kwargs):
    values = {
        "observed_at_ms": 1000 + n * 500,
        "game_p95_frame_ms": 14.0,
        "game_target_fps": 60.0,
        "gpu_vram_used_mb": 3500.0,
        "gpu_vram_total_mb": 8192.0,
        "tts_first_audio_p95_ms": 160.0,
        "network_dropped_pct": 0.0,
        "obs_connected": True,
        "game_frame_count": 90,
    }
    values.update(kwargs)
    return HostLoadReceipt(**values)


def send(pipeline, n, *, stats=None, stream=None, receipt=None, **overrides):
    a, b = data(n)
    values = dict(
        stats=a if stats is None else stats,
        stream_status=b if stream is None else stream,
        receipt=load(n) if receipt is None else receipt,
        stats_received_ms=1000 + 500 * n,
        stream_received_ms=1040 + 500 * n,
        now_ms=1060 + 500 * n,
        host_verified=True,
    )
    values.update(overrides)
    return pipeline.ingest(**values)


def ready():
    pipe = ObsLiveLoadPipeline()
    pipe.arm(owner_approved=True, obs_epoch="obs_pid_123_ws_01")
    return pipe


def warmed():
    pipe = ready()
    assert send(pipe, 0).status == "pending"
    for n in (1, 2, 3):
        assert send(pipe, n).status == "accepted"
    assert pipe.recommend(now_ms=2560).profile == "normal"
    assert pipe.recommend(now_ms=2560).allow_optional_commentary is True
    return pipe


def test_first_full_sequence_warms_from_aligned_observations():
    pipe = warmed()
    assert pipe.metrics() == {
        "accepted": 3,
        "pending": 1,
        "rejected": 0,
        "disarmed": 0,
        "armed": True,
    }
    assert not send(pipe, 4).authorizes_broadcast
    assert not send(pipe, 5).authorizes_game_input
    assert not send(pipe, 6).authorizes_playback


def test_verified_network_pressure_escalates_without_speaking():
    pipe = ready()
    assert send(pipe, 0).status == "pending"
    _, status = data(1, dropped=10)
    observed_loss = 100.0 * 10 / (50 + 10)
    result = send(
        pipe,
        1,
        stream=status,
        receipt=load(1, network_dropped_pct=observed_loss),
    )
    assert result.status == "accepted"
    advice = pipe.recommend(now_ms=1560)
    assert advice.profile == "critical"
    assert advice.reason == "network_loss"
    assert not advice.allow_optional_commentary
    assert not advice.allow_extra_gpu_inference


@pytest.mark.parametrize(
    "bad",
    [
        {"outputActive": False},
        {"outputReconnecting": True},
        {"outputSkippedFrames": "broken"},
        {"outputTotalFrames": 1},
        {"outputDuration": 10},
    ],
)
def test_invalid_observation_after_good_green_revokes_everything(bad):
    pipe = warmed()
    _, status = data(4)
    status.update(bad)
    assert send(pipe, 4, stream=status).status == "rejected"
    assert not pipe.metrics()["armed"]
    assert pipe.recommend(now_ms=3060).profile == "disabled"
    assert send(pipe, 5).status == "disabled"


def test_post_warm_no_frame_progress_cannot_preserve_green():
    pipe = warmed()
    original_stats, _ = data(3)
    result = send(pipe, 4, stats=original_stats)
    assert result.status == "rejected"
    assert pipe.recommend(now_ms=3060).profile == "disabled"


@pytest.mark.parametrize(
    "overrides",
    [
        {"now_ms": 4000},
        {"stream_received_ms": 3500},
        {"stats_received_ms": 2000},
        {"host_verified": False},
        {"now_ms": float("inf")},
    ],
)
def test_age_span_replay_and_unverified_host_fail_closed(overrides):
    pipe = warmed()
    assert send(pipe, 4, **overrides).status == "rejected"
    assert pipe.recommend(now_ms=3060).profile == "disabled"


def test_receipt_network_identity_and_clock_must_match():
    for incorrect in (
        {"network_dropped_pct": 1},
        {"observed_at_ms": 900},
        {"obs_connected": False, "network_dropped_pct": 1},
    ):
        pipe = ready()
        assert send(pipe, 0).status == "pending"
        assert send(pipe, 1, receipt=load(1, **incorrect)).status == "rejected"
        assert pipe.recommend(now_ms=1560).profile == "disabled"


def test_bad_receipt_or_missing_auth_revokes_even_before_first_pair():
    pipe = ready()
    assert send(pipe, 0, receipt=object()).status == "rejected"
    assert pipe.recommend(now_ms=1060).profile == "disabled"
    pipe.arm(owner_approved=True, obs_epoch="fresh")
    assert send(pipe, 0, host_verified=1).status == "rejected"


def test_epoch_restart_requires_new_pinned_identity():
    pipe = warmed()
    pipe.stop()
    with pytest.raises(RuntimeError):
        pipe.arm(owner_approved=True, obs_epoch="obs_pid_123_ws_01")
    pipe.arm(owner_approved=True, obs_epoch="obs_pid_123_ws_02")
    assert pipe.recommend(now_ms=3000).profile == "telemetry_stale"
    assert send(pipe, 0).status == "pending"
    assert send(pipe, 1).status == "accepted"
    assert pipe.recommend(now_ms=1560).profile != "normal"


def test_opt_in_parameter_bounds_and_strict_type():
    for configuration in (
        {"max_response_span_ms": True},
        {"max_age_ms": 10},
        {"max_response_span_ms": 1500},
        {"governor": object()},
    ):
        with pytest.raises((TypeError, ValueError)):
            ObsLiveLoadPipeline(**configuration)
    pipe = ObsLiveLoadPipeline()
    assert send(pipe, 0).status == "disabled"
    with pytest.raises(PermissionError):
        pipe.arm(obs_epoch="obs")
    with pytest.raises(ValueError):
        pipe.arm(owner_approved=True, obs_epoch="\n")
    assert pipe.metrics()["armed"] is False


def test_advice_only_uses_fresh_host_clock_and_no_identifiers_in_metrics():
    pipe = warmed()
    assert pipe.recommend(now_ms=10000).profile == "telemetry_stale"
    with pytest.raises(ValueError):
        pipe.recommend(now_ms=float("nan"))
    assert "obs_pid" not in str(pipe.metrics())


def test_previously_healthy_shared_governor_cannot_bypass_pipeline_opt_in():
    governor = StreamLoadGovernor()
    governor.enable(owner_approved=True)
    for i in range(3):
        assert governor.ingest(
            StreamLoadSample(
                sample_id=str(i),
                measured_at_s=float(i + 1),
                game_p95_frame_ms=14.0,
                game_target_fps=60,
                obs_render_missed_pct=0,
                obs_encode_skipped_pct=0,
                obs_network_dropped_pct=0,
                gpu_vram_used_mb=1000,
                gpu_vram_total_mb=8192,
                tts_first_audio_p95_ms=100,
            ),
            now_s=float(i + 1),
            host_verified=True,
        )
    assert governor.recommend(now_s=3).profile == "normal"
    pipeline = ObsLiveLoadPipeline(governor=governor)
    assert pipeline.recommend(now_ms=3000).profile == "disabled"
