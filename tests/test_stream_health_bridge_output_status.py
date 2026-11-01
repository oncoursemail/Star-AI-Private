"""OBS output-status provenance tests: no OBS, GPU, microphone or network I/O."""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_health_bridge import StreamHealthBridge


def stats(frames):
    return {
        "renderSkippedFrames": 0, "renderTotalFrames": frames,
        "outputSkippedFrames": 0, "outputTotalFrames": frames,
        "private_untrusted_extra": "viewer-not-stored",
    }


def status(active=True, reconnecting=False):
    return {"outputActive": active, "outputReconnecting": reconnecting}


def bridge():
    b = StreamHealthBridge()
    b.enable(owner_approved=True)
    return b


def host(b, at):
    return b.offer_host(
        StreamTelemetry(True, True, 2800, 8192, 60, 20),
        host_ms=at, host_verified=True,
    )


def window(b, first, last, frames=1000):
    assert b.offer_obs(stats(frames), host_ms=first, host_verified=True) is None
    return b.offer_obs(stats(frames + 100), host_ms=last, host_verified=True)


def test_preview_frame_counters_do_not_imply_actual_stream_output():
    b = bridge()
    assert window(b, 1000, 1500) is not None
    assert not host(b, 1510)  # OBS may render a preview when no stream is running.
    assert not b.advise("vision", now_ms=1520).allowed
    assert b.offer_stream_status(status(), host_ms=1550, host_verified=True)
    # Stream activation invalidates all prior preview samples.
    assert not host(b, 1560)
    assert window(b, 1600, 1900, 1100) is not None
    assert host(b, 1910)
    assert b.advise("vision", now_ms=1920).allowed


def test_stopped_and_reconnecting_outputs_invalidate_previous_admission():
    b = bridge()
    assert b.offer_stream_status(status(), host_ms=900, host_verified=True)
    assert window(b, 1000, 1500) is not None
    assert host(b, 1510)
    assert b.advise("vision", now_ms=1520).allowed
    assert not b.offer_stream_status(status(active=False), host_ms=1600,
                                     host_verified=True)
    assert not b.advise("vision", now_ms=1610).allowed
    assert b.offer_stream_status(status(), host_ms=1700, host_verified=True)
    assert window(b, 1800, 2100, 1100) is not None
    assert host(b, 2110)
    assert b.advise("vision", now_ms=2120).allowed
    assert not b.offer_stream_status(status(reconnecting=True), host_ms=2150,
                                     host_verified=True)
    assert not b.advise("vision", now_ms=2160).allowed
    assert b.offer_stream_status(status(), host_ms=2200, host_verified=True)
    assert window(b, 2300, 2600, 1200) is not None
    assert host(b, 2610)


def test_untrusted_and_replayed_status_cannot_replace_valid_evidence():
    b = bridge()
    assert b.offer_stream_status(status(), host_ms=900, host_verified=True)
    assert window(b, 1000, 1500) is not None
    assert host(b, 1510)
    assert not b.offer_stream_status(status(False), host_ms=1600)
    assert not b.offer_stream_status(status(False), host_ms=900,
                                     host_verified=True)
    assert b.advise("vision", now_ms=1610).allowed
    assert b.metrics()["output_verified"] == 1


@pytest.mark.parametrize("data", [
    {"outputActive": 1, "outputReconnecting": False},
    {"outputActive": True, "outputReconnecting": "false"},
    {"outputActive": True},
    {"outputActive": None, "outputReconnecting": False},
])
def test_malformed_trusted_output_status_invalidates_readiness(data):
    b = bridge()
    assert b.offer_stream_status(status(), host_ms=900, host_verified=True)
    assert window(b, 1000, 1500) is not None
    assert host(b, 1510)
    with pytest.raises(ValueError):
        b.offer_stream_status(data, host_ms=1600, host_verified=True)
    assert not b.advise("vision", now_ms=1610).allowed


def test_stale_status_denies_new_host_samples_and_existing_advice():
    b = bridge()
    assert b.offer_stream_status(status(), host_ms=900, host_verified=True)
    assert window(b, 1000, 1500) is not None
    assert host(b, 1510)
    assert b.advise("vision", now_ms=1850).allowed
    # Host's current OBS GetStats may continue even after status polling dies.
    assert b.offer_obs(stats(1200), host_ms=2000, host_verified=True) is not None
    assert not host(b, 2010)
    assert not b.advise("vision", now_ms=2020).allowed
    assert b.offer_stream_status(status(), host_ms=2025, host_verified=True)
    assert host(b, 2030)
    assert b.advise("vision", now_ms=2040).allowed


def test_future_status_and_new_obs_session_are_not_reused():
    b = bridge()
    assert b.offer_stream_status(status(), host_ms=2000, host_verified=True)
    assert window(b, 1000, 1500) is not None
    assert not host(b, 1510)
    b.obs_reset()
    assert not host(b, 2010)
    assert b.offer_stream_status(status(), host_ms=2100, host_verified=True)
    assert window(b, 2200, 2500) is not None
    assert host(b, 2510)
    assert b.advise("vision", now_ms=2520).allowed


def test_invalid_status_flags_do_not_authorize_anything():
    b = bridge()
    for value in (1, "true", None):
        with pytest.raises(ValueError):
            b.offer_stream_status(status(), host_ms=1000, host_verified=value)
    for value in (float("nan"), float("inf"), -1, True):
        with pytest.raises(ValueError):
            b.offer_stream_status(status(), host_ms=value, host_verified=True)
    assert not b.advise("vision", now_ms=1100).allowed
    assert b.metrics()["output_verified"] == 0
