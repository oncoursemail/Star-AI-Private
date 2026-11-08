"""Offline enforcement of matching real OBS stream network evidence."""

from dataclasses import replace

import pytest

from star.obs_stats_window import ObsLagWindow
from star.obs_stream_loss_window import ObsStreamLossSampler
from star.stream_load_governor import StreamLoadGovernor
from star.stream_load_host_bridge import HostLoadReceipt, StreamLoadHostBridge


def obs(ms):
    return ObsLagWindow(observed_ms=ms, render_lag_pct=0, output_lag_pct=0, window_ms=500)


def receipt(ms, loss):
    return HostLoadReceipt(
        observed_at_ms=ms,
        game_p95_frame_ms=14,
        game_target_fps=60,
        gpu_vram_used_mb=3000,
        gpu_vram_total_mb=8192,
        tts_first_audio_p95_ms=100,
        network_dropped_pct=loss,
        obs_connected=True,
        game_frame_count=60,
    )


def stream_window(ms, dropped=5):
    sampler = ObsStreamLossSampler()
    base = {
        "outputActive": True,
        "outputReconnecting": False,
        "outputDuration": 1000,
        "outputSkippedFrames": 0,
        "outputTotalFrames": 100,
    }
    assert sampler.ingest(base, host_ms=ms - 500, host_verified=True) is None
    return sampler.ingest(
        {**base, "outputDuration": 1500, "outputSkippedFrames": dropped, "outputTotalFrames": 145},
        host_ms=ms,
        host_verified=True,
    )


def ready():
    gov = StreamLoadGovernor()
    bridge = StreamLoadHostBridge(gov, require_verified_stream_network=True)
    bridge.arm(owner_approved=True, obs_session_id="verified-network")
    return gov, bridge


def test_matching_stream_loss_transitions_to_network_constrained():
    gov, bridge = ready()
    for ms in (1000, 1500, 2000):
        network = stream_window(ms)
        assert network is not None
        assert bridge.submit(
            obs=obs(ms),
            receipt=receipt(ms, network.network_dropped_pct),
            stream_network=network,
            now_ms=ms + 5,
            host_verified=True,
        )
    assert gov.recommend(now_s=2.005).reason == "network_loss"
    assert not gov.recommend(now_s=2.005).allow_optional_commentary


def test_missing_stream_network_evidence_fails_closed_even_with_numeric_zero():
    gov, bridge = ready()
    assert not bridge.submit(obs=obs(1000), receipt=receipt(1000, 0), now_ms=1010, host_verified=True)
    assert gov.recommend(now_s=1.01).profile == "disabled"
    assert not bridge.metrics()["armed"]


@pytest.mark.parametrize(
    "change",
    [
        lambda n: replace(n, network_dropped_pct=0),
        lambda n: replace(n, delivered_frames=10000),
        lambda n: replace(n, observed_ms=n.observed_ms + 500),
        lambda n: replace(n, window_ms=1200),
        lambda n: replace(n, dropped_frames=-1),
    ],
)
def test_false_stream_evidence_does_not_authorize_speech(change):
    gov, bridge = ready()
    network = stream_window(1000)
    assert network is not None
    assert not bridge.submit(
        obs=obs(1000),
        receipt=receipt(1000, network.network_dropped_pct),
        stream_network=change(network),
        now_ms=1010,
        host_verified=True,
    )
    assert gov.recommend(now_s=1.01).profile == "disabled"


def test_receipt_must_match_network_drop_fraction_exactly():
    gov, bridge = ready()
    network = stream_window(1000)
    assert network is not None
    assert not bridge.submit(
        obs=obs(1000), receipt=receipt(1000, 0), stream_network=network, now_ms=1010, host_verified=True
    )
    assert gov.recommend(now_s=1.01).profile == "disabled"


def test_offline_legacy_mode_keeps_old_behavior():
    gov = StreamLoadGovernor()
    bridge = StreamLoadHostBridge(gov)
    bridge.arm(owner_approved=True, obs_session_id="private-rehearsal")
    assert bridge.submit(obs=obs(1000), receipt=receipt(1000, 0), now_ms=1010, host_verified=True)


def test_stream_mode_configuration_rejects_truthy_non_boolean():
    with pytest.raises(ValueError):
        StreamLoadHostBridge(StreamLoadGovernor(), require_verified_stream_network=1)
