"""Synthetic OBS/host join tests: no GPU, network, game or broadcast needed."""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_health_bridge import StreamHealthBridge


def obs(*, rskip=0, rtotal=1000, oskip=0, ototal=1000):
    return {
        "renderSkippedFrames": rskip, "renderTotalFrames": rtotal,
        "outputSkippedFrames": oskip, "outputTotalFrames": ototal,
        "not_recorded_viewer_data": "do-not-keep",
    }


def load(*, live=True, free=2500, fps=60, backlog=20):
    return StreamTelemetry(live, True, free, 8192, fps, backlog)


def active():
    bridge = StreamHealthBridge()
    bridge.enable(owner_approved=True)
    return bridge


def output(bridge, at_ms, *, active=True, reconnecting=False):
    return bridge.offer_stream_status(
        {"outputActive": active, "outputReconnecting": reconnecting},
        host_ms=at_ms, host_verified=True,
    )


def ready(bridge, *, lagged=False):
    assert output(bridge, 900)
    assert bridge.offer_obs(obs(), host_ms=1000, host_verified=True) is None
    w = bridge.offer_obs(
        obs(rskip=3 if lagged else 0, rtotal=1100, ototal=1100),
        host_ms=1500, host_verified=True,
    )
    assert w is not None
    assert bridge.offer_host(load(), host_ms=1510, host_verified=True)


def test_explicit_opt_in_and_advice_never_authorizes_work():
    bridge = StreamHealthBridge()
    with pytest.raises(PermissionError):
        bridge.enable()
    assert bridge.offer_obs(obs(), host_ms=1000, host_verified=True) is None
    assert not bridge.offer_host(load(), host_ms=1000, host_verified=True)
    assert not bridge.advise("vision", now_ms=1010).allowed
    bridge.enable(owner_approved=True)
    assert not bridge.advise("vision", now_ms=1010).allowed
    voice = bridge.advise("speech", now_ms=1010)
    assert voice.allowed and not voice.authorizes_execution
    with pytest.raises(RuntimeError):
        bridge.enable(owner_approved=True)


def test_live_measured_headroom_admits_only_bounded_vision():
    bridge = active()
    ready(bridge)
    good = bridge.advise("vision", now_ms=1520)
    assert good.allowed and good.sample_fps == 1.0
    assert not good.authorizes_execution
    for work in ("training", "research", "render"):
        assert not bridge.advise(work, now_ms=1520).allowed


def test_missing_obs_cannot_be_fake_healthy_zero_lag():
    bridge = active()
    assert not bridge.offer_host(load(), host_ms=1000, host_verified=True)
    assert not bridge.advise("vision", now_ms=1010).allowed
    assert bridge.advise("speech", now_ms=1010).allowed
    bridge.offer_obs(obs(), host_ms=1100, host_verified=True)
    assert not bridge.offer_host(load(), host_ms=1200, host_verified=True)
    assert not bridge.advise("vision", now_ms=1210).allowed


def test_no_output_frames_and_obs_reconnect_invalidate_admission():
    bridge = active()
    assert output(bridge, 900)
    bridge.offer_obs(obs(), host_ms=1000, host_verified=True)
    assert bridge.offer_obs(obs(), host_ms=1500, host_verified=True) is None
    assert not bridge.offer_host(load(), host_ms=1510, host_verified=True)
    assert output(bridge, 1950)
    bridge.offer_obs(obs(rtotal=1100, ototal=1100),
                     host_ms=2000, host_verified=True)
    assert bridge.offer_host(load(), host_ms=2010, host_verified=True)
    assert bridge.advise("vision", now_ms=2020).allowed
    bridge.obs_reset()
    assert not bridge.advise("vision", now_ms=2030).allowed
    assert bridge.advise("speech", now_ms=2030).allowed


def test_every_live_host_sample_needs_a_distinct_obs_window():
    bridge = active()
    ready(bridge)
    assert not bridge.offer_host(load(), host_ms=1600, host_verified=True)
    assert not bridge.advise("vision", now_ms=1610).allowed
    # Fresh OBS window and active output proof enable new admission.
    assert output(bridge, 1950)
    assert bridge.offer_obs(obs(rtotal=1200, ototal=1200),
                            host_ms=2000, host_verified=True) is not None
    assert bridge.offer_host(load(), host_ms=2010, host_verified=True)
    assert bridge.advise("vision", now_ms=2020).allowed


def test_obs_window_expiry_is_bounded_by_clock():
    bridge = active()
    ready(bridge)
    assert output(bridge, 2400)
    assert bridge.advise("vision", now_ms=2450).allowed
    assert not bridge.advise("vision", now_ms=2600).allowed
    assert not bridge.offer_host(load(), host_ms=2610, host_verified=True)


def test_bad_obs_metrics_trip_and_recover_only_from_distinct_spaced_windows():
    bridge = active()
    ready(bridge, lagged=True)
    assert not bridge.advise("vision", now_ms=1520).allowed
    for at, total in ((2000, 1200), (2700, 1300)):
        assert output(bridge, at - 100)
        assert bridge.offer_obs(
            obs(rskip=3, rtotal=total, ototal=total),
            host_ms=at, host_verified=True,
        ) is not None
        assert bridge.offer_host(load(), host_ms=at + 10, host_verified=True)
        assert not bridge.advise("vision", now_ms=at + 20).allowed
    assert output(bridge, 3600)
    assert bridge.offer_obs(obs(rskip=3, rtotal=1400, ototal=1400),
                            host_ms=3700, host_verified=True) is not None
    assert bridge.offer_host(load(), host_ms=3710, host_verified=True)
    assert bridge.advise("vision", now_ms=3720).allowed
    assert bridge.metrics()["overloaded"] is False


def test_live_transition_cannot_reuse_offline_headroom():
    bridge = active()
    assert bridge.offer_host(load(live=False), host_ms=1000,
                             host_verified=True)
    assert bridge.advise("vision", now_ms=1010).allowed
    assert not bridge.offer_host(load(live=True), host_ms=1100,
                                 host_verified=True)
    assert not bridge.advise("vision", now_ms=1110).allowed


def test_offline_admission_does_not_need_obs_counters():
    bridge = active()
    assert bridge.offer_host(load(live=False), host_ms=1000,
                             host_verified=True)
    result = bridge.advise("training", now_ms=1010)
    assert result.allowed and result.profile == "offline"


def test_unverified_and_repeated_host_samples_rejected():
    bridge = active()
    ready(bridge)
    assert not bridge.offer_host(load(), host_ms=1505, host_verified=True)
    assert not bridge.offer_host(load(), host_ms=1600, host_verified=False)
    assert not bridge.offer_host(load(), host_ms=1510, host_verified=True)
    assert bridge.metrics()["host_rejected"] == 3
    assert bridge.advise("vision", now_ms=1520).allowed


def test_unverified_obs_does_not_replace_last_trusted_window():
    bridge = active()
    ready(bridge)
    assert bridge.offer_obs(obs(rskip=999), host_ms=1700) is None
    assert bridge.advise("vision", now_ms=1710).allowed


def test_malformed_new_obs_invalidates_previous_readiness():
    bridge = active()
    ready(bridge)
    with pytest.raises(ValueError):
        bridge.offer_obs(obs(rskip=float("nan")), host_ms=2000,
                         host_verified=True)
    assert not bridge.advise("vision", now_ms=2010).allowed
    assert bridge.advise("gameplay", now_ms=2010).allowed



def test_malformed_verified_obs_requires_two_fresh_counter_samples():
    bridge = active()
    ready(bridge)
    with pytest.raises(ValueError):
        bridge.offer_obs(obs(rskip=float("nan")), host_ms=1700,
                         host_verified=True)
    assert output(bridge, 1900)
    # A valid next sample must establish a new OBS baseline, not join the
    # old one from before the invalid trusted measurement.
    assert bridge.offer_obs(obs(rtotal=1200, ototal=1200),
                            host_ms=2000, host_verified=True) is None
    assert not bridge.offer_host(load(), host_ms=2010, host_verified=True)
    assert not bridge.advise("vision", now_ms=2020).allowed
    assert output(bridge, 2400)
    assert bridge.offer_obs(obs(rtotal=1300, ototal=1300),
                            host_ms=2500, host_verified=True) is not None
    assert bridge.offer_host(load(), host_ms=2510, host_verified=True)
    assert bridge.advise("vision", now_ms=2520).allowed


def test_short_obs_interval_cannot_represent_a_new_complete_window():
    bridge = active()
    ready(bridge)
    assert bridge.offer_obs(obs(rtotal=1120, ototal=1120),
                            host_ms=1600, host_verified=True) is None
    assert not bridge.advise("vision", now_ms=1610).allowed
    assert not bridge.offer_host(load(), host_ms=1620, host_verified=True)


def test_new_session_cannot_inherit_old_obs_or_host_status():
    bridge = active()
    ready(bridge)
    bridge.disable()
    assert not bridge.advise("vision", now_ms=1520).allowed
    bridge.enable(owner_approved=True)
    assert not bridge.offer_host(load(), host_ms=2000, host_verified=True)
    assert not bridge.advise("vision", now_ms=2010).allowed


@pytest.mark.parametrize("value", [False, float("inf"), float("nan"), -1,
                                    "1000", 10**400])
def test_invalid_host_clock_rejected_without_readiness(value):
    bridge = active()
    ready(bridge)
    with pytest.raises(ValueError):
        bridge.offer_host(load(), host_ms=value, host_verified=True)
    assert bridge.advise("vision", now_ms=1520).allowed


def test_wrong_host_flags_or_unknown_workload_are_rejected():
    bridge = active()
    ready(bridge)
    with pytest.raises(ValueError):
        bridge.offer_host(load(), host_ms=2000, host_verified=1)
    with pytest.raises(TypeError):
        bridge.offer_host(None, host_ms=2000, host_verified=True)
    with pytest.raises(ValueError):
        bridge.advise("arbitrary_tool", now_ms=1520)


def test_metrics_exclude_obs_payloads_and_require_real_windows():
    bridge = active()
    ready(bridge)
    m = bridge.metrics()
    assert m["obs_windows"] == 1
    assert m["host_admitted"] == 1
    assert set(m) == {
        "obs_windows", "host_admitted", "host_rejected",
        "bridge_deferrals", "obs_invalidated", "output_verified",
        "output_invalidated", "output_mode_mismatch", "enabled", "live", "overloaded",
    }


@pytest.mark.parametrize("invalid", [True, 200, 1600, 1000.0])
def test_obs_age_configuration_is_strict(invalid):
    with pytest.raises(ValueError):
        StreamHealthBridge(max_obs_age_ms=invalid)
