"""Offline OBS v5 stream drop interval evidence and fail-closed regression tests."""

import pytest

from star.obs_stream_loss_window import ObsStreamLossSampler


def status(*, active=True, reconnect=False, duration=1000, skipped=0, sent=100):
    return {
        "outputActive": active,
        "outputReconnecting": reconnect,
        "outputDuration": duration,
        "outputSkippedFrames": skipped,
        "outputTotalFrames": sent,
    }


def test_real_network_interval_not_lifetime_average():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(skipped=50, sent=900), host_ms=1000, host_verified=True) is None
    window = sampler.ingest(status(duration=1500, skipped=55, sent=945), host_ms=1500, host_verified=True)
    assert window is not None
    assert window.window_ms == 500
    assert window.dropped_frames == 5
    assert window.delivered_frames == 45
    assert window.network_dropped_pct == pytest.approx(10)
    assert sampler.metrics()["windows"] == 1


def test_zero_loss_needs_two_real_active_samples():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    good = sampler.ingest(status(duration=1500, sent=130), host_ms=1500, host_verified=True)
    assert good is not None and good.network_dropped_pct == 0
    assert good.delivered_frames == 30


def test_inactive_or_reconnecting_stream_never_yields_zero_network_loss():
    for bad in (status(active=False), status(reconnect=True)):
        sampler = ObsStreamLossSampler()
        assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
        assert sampler.ingest(bad, host_ms=1500, host_verified=True) is None
        assert sampler.ingest(status(duration=2000, sent=160), host_ms=2000, host_verified=True) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"outputActive": 1},
        {"outputActive": None},
        {"outputReconnecting": 0},
        {"outputSkippedFrames": -1},
        {"outputSkippedFrames": float("nan")},
        {"outputTotalFrames": 1.5},
        {"outputDuration": float("inf")},
    ],
)
def test_malformed_receipt_revokes_previous_baseline(bad):
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest({**status(duration=1500), **bad}, host_ms=1500, host_verified=True) is None
    assert sampler.ingest(status(duration=2000, sent=200), host_ms=2000, host_verified=True) is None
    assert sampler.metrics()["rejected"] == 1


def test_authentication_loss_revokes_baseline_and_restarts():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=1500), host_ms=1500, host_verified=False) is None
    assert sampler.ingest(status(duration=2000), host_ms=2000, host_verified=True) is None


def test_counter_rollback_rebases_without_reporting_healthy():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=1500, sent=90), host_ms=1500, host_verified=True) is None
    assert sampler.ingest(status(duration=2000, sent=125), host_ms=2000, host_verified=True) is not None


def test_stale_window_does_not_authorize_optional_work():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=8500, sent=1000), host_ms=8500, host_verified=True) is None
    assert sampler.ingest(status(duration=9000, sent=1030), host_ms=9000, host_verified=True) is not None


def test_replay_clock_reversal_requires_new_baseline():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=1300, sent=130), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=1500, sent=150), host_ms=1500, host_verified=True) is None


def test_duration_jump_or_reset_requires_new_baseline():
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=12000, sent=200), host_ms=1500, host_verified=True) is None
    assert sampler.ingest(status(duration=12500, sent=230), host_ms=2000, host_verified=True) is not None


def test_tiny_or_no_output_is_not_zero_loss_proof():
    sampler = ObsStreamLossSampler(min_attempted_frames=20)
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(status(duration=1500, sent=100), host_ms=1500, host_verified=True) is None
    assert sampler.ingest(status(duration=2000, sent=120), host_ms=2000, host_verified=True) is not None


def test_invalid_configuration_and_explicit_reset():
    for kwargs in (
        {"min_window_ms": 1},
        {"max_window_ms": 200},
        {"min_attempted_frames": 0},
        {"max_window_ms": 100000},
    ):
        with pytest.raises(ValueError):
            ObsStreamLossSampler(**kwargs)
    sampler = ObsStreamLossSampler()
    assert sampler.ingest(status(), host_ms=1000, host_verified=True) is None
    sampler.reset()
    assert sampler.ingest(status(duration=1500, sent=150), host_ms=1500, host_verified=True) is None
