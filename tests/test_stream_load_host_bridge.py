"""Offline-only host OBS/game load bridge tests; no hardware or network I/O."""

import pytest

from star.obs_stats_window import ObsLagWindow, ObsStatsWindow
from star.stream_load_governor import StreamLoadGovernor
from star.stream_load_host_bridge import HostLoadReceipt, StreamLoadHostBridge


def receipt(ms: float, **kwargs: object) -> HostLoadReceipt:
    values = dict(
        observed_at_ms=ms,
        game_p95_frame_ms=14.0,
        game_target_fps=60.0,
        gpu_vram_used_mb=4000.0,
        gpu_vram_total_mb=8192.0,
        tts_first_audio_p95_ms=240.0,
        network_dropped_pct=0.0,
        obs_connected=True,
        game_frame_count=75,
    )
    values.update(kwargs)
    return HostLoadReceipt(**values)


def obs(ms: float, *, render: float = 0.0, output: float = 0.0, duration: float = 500.0) -> ObsLagWindow:
    return ObsLagWindow(ms, render, output, duration)


def ready():
    gov = StreamLoadGovernor()
    bridge = StreamLoadHostBridge(gov)
    bridge.arm(owner_approved=True, obs_session_id="obs-1")
    return gov, bridge


def test_disabled_by_default_approval_and_per_session_rearm():
    gov = StreamLoadGovernor()
    bridge = StreamLoadHostBridge(gov)
    assert not bridge.submit(obs=obs(1000), receipt=receipt(1000), now_ms=1000, host_verified=True)
    with pytest.raises(PermissionError):
        bridge.arm(obs_session_id="obs-1")
    bridge.arm(owner_approved=True, obs_session_id="obs-1")
    with pytest.raises(RuntimeError):
        bridge.arm(owner_approved=True, obs_session_id="obs-1")
    bridge.stop()
    assert gov.recommend(now_s=2).profile == "disabled"
    with pytest.raises(RuntimeError):
        bridge.arm(owner_approved=True, obs_session_id="obs-1")
    bridge.arm(owner_approved=True, obs_session_id="obs-2")
    assert gov.recommend(now_s=2).profile == "telemetry_stale"


def test_three_real_obs_windows_warm_governor_to_normal():
    gov, bridge = ready()
    feed = ObsStatsWindow(min_window_ms=250)
    assert (
        feed.ingest(
            {"renderSkippedFrames": 0, "renderTotalFrames": 1000, "outputSkippedFrames": 0, "outputTotalFrames": 1000},
            host_ms=1000,
            host_verified=True,
        )
        is None
    )
    for idx in (1, 2, 3):
        frame = feed.ingest(
            {
                "renderSkippedFrames": 0,
                "renderTotalFrames": 1000 + idx * 30,
                "outputSkippedFrames": 0,
                "outputTotalFrames": 1000 + idx * 30,
            },
            host_ms=1000 + idx * 500,
            host_verified=True,
        )
        assert frame is not None
        assert bridge.submit(
            obs=frame, receipt=receipt(frame.observed_ms), now_ms=frame.observed_ms + 20, host_verified=True
        )
    advice = gov.recommend(now_s=2.52)
    assert advice.profile == "normal"
    assert advice.allow_optional_commentary
    assert bridge.metrics()["accepted"] == 3


def test_verified_obs_render_and_output_pressure_suppress_optional_speech():
    for what, kwargs, reason in (
        ("render", {"render": 4.5}, "obs_render_lag"),
        ("output", {"output": 3.0}, "obs_encoder_lag"),
    ):
        gov, bridge = ready()
        assert bridge.submit(obs=obs(1000, **kwargs), receipt=receipt(1000), now_ms=1020, host_verified=True), what
        advice = gov.recommend(now_s=1.02)
        assert advice.profile == "critical"
        assert advice.reason == reason
        assert not advice.allow_optional_commentary


def test_network_vram_game_and_speech_sensors_are_not_invented():
    for values, reason in (
        ({"network_dropped_pct": 5}, "network_loss"),
        ({"gpu_vram_used_mb": 8000}, "vram_near_capacity"),
        ({"game_p95_frame_ms": 35}, "game_frame_deadline"),
        ({"tts_first_audio_p95_ms": 1100}, "speech_latency"),
        ({"obs_connected": False}, "obs_disconnected"),
    ):
        gov, bridge = ready()
        assert bridge.submit(obs=obs(1000), receipt=receipt(1000, **values), now_ms=1010, host_verified=True)
        assert gov.recommend(now_s=1.01).reason == reason


@pytest.mark.parametrize(
    "bad",
    [
        {"game_p95_frame_ms": None},
        {"game_target_fps": False},
        {"gpu_vram_used_mb": -5},
        {"gpu_vram_total_mb": 0},
        {"tts_first_audio_p95_ms": float("nan")},
        {"network_dropped_pct": None},
        {"network_dropped_pct": -1},
        {"obs_connected": 1},
        {"game_frame_count": 0},
        {"observed_at_ms": float("inf")},
    ],
)
def test_missing_forged_or_invalid_sensor_values_cannot_become_healthy(bad):
    with pytest.raises(ValueError):
        receipt(1000, **bad)


@pytest.mark.parametrize(
    "event",
    [
        lambda: (obs(2000, render=float("nan")), receipt(2000), 2020, True),
        lambda: (obs(2000, duration=0), receipt(2000), 2020, True),
        lambda: (obs(2000, duration=10000), receipt(2000), 2020, True),
        lambda: (obs(2000), receipt(1400), 2020, True),
        lambda: (obs(2000), receipt(2000), 3000, True),
        lambda: (obs(2000), receipt(2000), 1950, True),
        lambda: (obs(2000), receipt(2000), 2020, False),
        lambda: (obs(2000), receipt(2000), 2020, 1),
    ],
)
def test_bad_input_immediately_revokes_existing_healthy_governor(event):
    gov, bridge = ready()
    for ms in (500, 1000, 1500):
        assert bridge.submit(obs=obs(ms), receipt=receipt(ms), now_ms=ms + 10, host_verified=True)
    assert gov.recommend(now_s=1.51).profile == "normal"
    sample, sample_receipt, now, valid = event()
    assert not bridge.submit(obs=sample, receipt=sample_receipt, now_ms=now, host_verified=valid)
    assert gov.recommend(now_s=1.51).profile == "disabled"
    assert not bridge.metrics()["armed"]


def test_replay_overlap_and_clock_reversal_fail_closed():
    gov, bridge = ready()
    assert bridge.submit(obs=obs(1000), receipt=receipt(1000), now_ms=1010, host_verified=True)
    assert not bridge.submit(obs=obs(1250, duration=500), receipt=receipt(1250), now_ms=1260, host_verified=True)
    assert gov.recommend(now_s=1.3).profile == "disabled"
    bridge.arm(owner_approved=True, obs_session_id="new-epoch")
    assert bridge.submit(obs=obs(2000), receipt=receipt(2000), now_ms=2010, host_verified=True)
    assert not bridge.submit(obs=obs(2000), receipt=receipt(2000), now_ms=2011, host_verified=True)


def test_forged_receipt_false_or_type_errors_disarm():
    gov, bridge = ready()
    assert not bridge.submit(obs=obs(1000), receipt=receipt(1000), now_ms=float("inf"), host_verified=True)
    assert gov.recommend(now_s=1).profile == "disabled"
    bridge.arm(owner_approved=True, obs_session_id="fresh")
    assert not bridge.submit(
        obs=obs(1000),
        receipt=object(),  # type: ignore[arg-type]
        now_ms=1010,
        host_verified=True,
    )


def test_metrics_are_aggregates_without_session_ids_or_chat_content():
    _, bridge = ready()
    assert bridge.submit(obs=obs(1000), receipt=receipt(1000), now_ms=1020, host_verified=True)
    stat = bridge.metrics()
    assert stat == {"accepted": 1, "rejected": 0, "sessions": 1, "disarmed": 0, "armed": True}
    assert "obs-1" not in str(stat)


def test_fresh_arm_cannot_inherit_existing_green_governor():
    from star.stream_load_governor import StreamLoadSample

    gov = StreamLoadGovernor()
    gov.enable(owner_approved=True)
    for index, stamp in enumerate((0.5, 1.0, 1.5), start=1):
        assert gov.ingest(
            StreamLoadSample(
                sample_id=f"old_{index}",
                measured_at_s=stamp,
                game_p95_frame_ms=12,
                game_target_fps=60,
                obs_render_missed_pct=0,
                obs_encode_skipped_pct=0,
                obs_network_dropped_pct=0,
                gpu_vram_used_mb=2000,
                gpu_vram_total_mb=8192,
                tts_first_audio_p95_ms=90,
            ),
            now_s=stamp,
            host_verified=True,
        )
    assert gov.recommend(now_s=1.51).profile == "normal"
    bridge = StreamLoadHostBridge(gov)
    bridge.arm(owner_approved=True, obs_session_id="next-obs-epoch")
    assert gov.recommend(now_s=1.51).profile == "telemetry_stale"
    assert not gov.recommend(now_s=1.51).allow_optional_commentary
