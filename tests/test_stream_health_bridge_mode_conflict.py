"""Host/OBS contradictory-mode regression tests; no sockets or media I/O."""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_health_bridge import StreamHealthBridge


def _telemetry(*, live: bool) -> StreamTelemetry:
    return StreamTelemetry(live, True, 2500, 8192, 60, 20)


def _stats(total: int) -> dict[str, int]:
    return {
        "renderSkippedFrames": 0, "renderTotalFrames": total,
        "outputSkippedFrames": 0, "outputTotalFrames": total,
    }


def _status(bridge: StreamHealthBridge, at: int, *,
            active: bool, reconnecting: bool = False) -> bool:
    return bridge.offer_stream_status(
        {"outputActive": active, "outputReconnecting": reconnecting},
        host_ms=at, host_verified=True,
    )


def _host(bridge: StreamHealthBridge, at: int, *, live: bool) -> bool:
    return bridge.offer_host(_telemetry(live=live), host_ms=at,
                             host_verified=True)


def _ready_live() -> StreamHealthBridge:
    bridge = StreamHealthBridge()
    bridge.enable(owner_approved=True)
    assert _status(bridge, 900, active=True)
    assert bridge.offer_obs(_stats(1000), host_ms=1000,
                            host_verified=True) is None
    assert bridge.offer_obs(_stats(1100), host_ms=1500,
                            host_verified=True) is not None
    assert _host(bridge, 1510, live=True)
    assert bridge.advise("vision", now_ms=1520).allowed
    return bridge


def test_offline_host_snapshot_cannot_override_active_obs_output():
    bridge = _ready_live()
    assert not _host(bridge, 1600, live=False)
    assert not bridge.advise("training", now_ms=1610).allowed
    assert not bridge.advise("vision", now_ms=1610).allowed
    assert bridge.metrics()["output_mode_mismatch"] == 1
    assert bridge.metrics()["live"] is True


def test_offline_work_recovers_only_after_verified_output_stop():
    bridge = _ready_live()
    assert not _host(bridge, 1600, live=False)
    assert not _status(bridge, 1650, active=False)
    assert _host(bridge, 1700, live=False)
    offline = bridge.advise("training", now_ms=1710)
    assert offline.allowed and offline.profile == "offline"
    assert not offline.authorizes_execution


def test_obs_reconnection_and_reset_cannot_fake_offline_mode():
    bridge = _ready_live()
    assert not _status(bridge, 1600, active=True, reconnecting=True)
    assert not _host(bridge, 1610, live=False)
    bridge.obs_reset()
    assert not _host(bridge, 1620, live=False)
    assert not bridge.advise("render", now_ms=1630).allowed
    assert not _status(bridge, 1700, active=False)
    assert _host(bridge, 1710, live=False)
    assert bridge.advise("research", now_ms=1720).allowed


def test_even_inconsistent_reconnecting_flag_is_conservative():
    bridge = _ready_live()
    # OBS is attempting to reconnect even if an out-of-sync adapter says
    # outputActive=False. Only both flags False proves output stopped.
    assert not _status(bridge, 1600, active=False, reconnecting=True)
    assert not _host(bridge, 1610, live=False)
    assert not bridge.advise("training", now_ms=1620).allowed


@pytest.mark.parametrize("bad", [None, [], "not-an-object"])
def test_trusted_malformed_status_shape_invalidates_old_readiness(bad):
    bridge = _ready_live()
    with pytest.raises(TypeError):
        bridge.offer_stream_status(bad, host_ms=1600, host_verified=True)
    assert not bridge.advise("vision", now_ms=1610).allowed
    assert not _host(bridge, 1620, live=False)
    assert not bridge.advise("training", now_ms=1630).allowed
    assert bridge.metrics()["output_invalidated"] >= 1


def test_trusted_invalid_flags_cannot_unlock_offline_mode():
    bridge = _ready_live()
    with pytest.raises(ValueError):
        bridge.offer_stream_status(
            {"outputActive": False, "outputReconnecting": 0},
            host_ms=1600, host_verified=True,
        )
    assert not _host(bridge, 1610, live=False)
    assert not bridge.advise("training", now_ms=1620).allowed


def test_untrusted_malformed_status_does_not_replace_valid_attestation():
    bridge = _ready_live()
    assert not bridge.offer_stream_status(
        None, host_ms=1600, host_verified=False,
    )
    assert bridge.advise("vision", now_ms=1610).allowed
    assert bridge.metrics()["output_invalidated"] == 1  # initial activation
