"""Deterministic synthetic tests: no game, OBS or GPU is accessed."""
from dataclasses import replace
import pytest
from star.stream_budget import StreamTelemetry
from star.stream_admission import StreamAdmissionGate, StreamHealthSample


def sample(at=1000.0, *, live=True, free=2500.0, fps=60.0,
           backlog=50.0, render=0.0, encode=0.0, verified=True):
    return StreamHealthSample(at, StreamTelemetry(live, True, free, 8192.0,
                                                 fps, backlog),
                              render, encode, verified)


def active():
    gate = StreamAdmissionGate()
    gate.enable(owner_approved=True)
    return gate


def test_opt_in_and_no_game_io_permissions():
    gate = StreamAdmissionGate()
    with pytest.raises(PermissionError):
        gate.enable()
    assert not gate.observe(sample())
    assert not gate.advise("speech", now_ms=1000).allowed
    gate.enable(owner_approved=True)
    assert gate.advise("speech", now_ms=1000).allowed
    assert not gate.advise("vision", now_ms=1000).allowed
    with pytest.raises(RuntimeError):
        gate.enable(owner_approved=True)


def test_live_admission_protects_gameplay_voice_and_heavy_jobs():
    gate = active()
    assert gate.observe(sample())
    assert gate.advise("gameplay", now_ms=1030).profile == "latency"
    voice = gate.advise("speech", now_ms=1030)
    assert voice.allowed and not voice.authorizes_execution
    vision = gate.advise("vision", now_ms=1030)
    assert vision.allowed and vision.sample_fps == 1.0
    for kind in ("training", "research", "render"):
        assert not gate.advise(kind, now_ms=1030).allowed


def test_obs_pressure_trips_on_one_sample_even_with_headroom():
    gate = active()
    assert gate.observe(sample(render=1.1))
    assert gate.metrics()["overload_trips"] == 1
    assert not gate.advise("vision", now_ms=1050).allowed
    assert gate.advise("speech", now_ms=1050).allowed


def test_encoder_lag_and_memory_pressure_each_trip():
    for bad in (dict(encode=4.0), dict(free=1100.0),
                dict(fps=30.0), dict(backlog=500.0)):
        gate = active()
        assert gate.observe(sample(**bad))
        assert not gate.advise("vision", now_ms=1010).allowed
        assert gate.metrics()["overloaded"]


def test_recovery_requires_spaced_healthy_samples_and_dwell():
    gate = active()
    gate.observe(sample(render=5.0))
    for at in (1100, 1200, 1300, 1800, 2200):
        assert gate.observe(sample(at))
        assert not gate.advise("vision", now_ms=at).allowed
    gate.observe(sample(2600))
    assert gate.advise("vision", now_ms=2600).allowed
    assert gate.metrics()["recoveries"] == 1


def test_new_bad_sample_resets_recovery_counter():
    gate = active()
    gate.observe(sample(render=2.0))
    gate.observe(sample(1400))
    gate.observe(sample(2000, encode=2.0))
    gate.observe(sample(2400))
    gate.observe(sample(2900))
    assert not gate.advise("vision", now_ms=2900).allowed
    gate.observe(sample(4000))
    assert gate.advise("vision", now_ms=4000).allowed


def test_rejected_and_replayed_samples_cannot_clear_overload():
    gate = active()
    gate.observe(sample(render=2.0))
    assert not gate.observe(sample(1000))
    assert not gate.observe(sample(1700, verified=False))
    assert gate.observe(sample(1800))
    assert not gate.advise("vision", now_ms=1800).allowed
    assert gate.metrics()["rejected"] == 2


def test_stale_sample_and_clock_reversal_fail_closed_for_background():
    gate = active()
    gate.observe(sample())
    assert not gate.advise("vision", now_ms=2600).allowed
    assert gate.advise("gameplay", now_ms=2600).allowed
    # A new telemetry observation can arrive later than a prior advice call.
    # Its *capture* timestamp can be older than that call but still fresh.
    assert gate.observe(sample(2400))
    assert not gate.advise("vision", now_ms=2599).allowed
    assert gate.advise("vision", now_ms=2600).allowed


def test_disable_reset_but_cannot_skip_owner_approval():
    gate = active()
    gate.observe(sample(render=3.0))
    gate.disable()
    assert not gate.advise("vision", now_ms=2000).allowed
    with pytest.raises(PermissionError):
        gate.enable()
    gate.enable(owner_approved=True)
    assert not gate.metrics()["overloaded"]
    assert gate.metrics()["accepted"] == 1
    assert gate.observe(sample(3000))
    assert gate.advise("vision", now_ms=3000).allowed


def test_offline_workloads_are_deferred_until_healthy():
    gate = active()
    gate.observe(sample(live=False))
    assert gate.advise("training", now_ms=1000).allowed
    assert gate.advise("vision", now_ms=1000).sample_fps == 4


@pytest.mark.parametrize("changes", [
    {"obs_render_lag_pct": float("nan")},
    {"obs_encode_lag_pct": 101},
    {"observed_ms": -1},
    {"observed_ms": True},
    {"host_verified": 1},
])
def test_bad_samples_rejected(changes):
    with pytest.raises(ValueError):
        replace(sample(), **changes)


def test_bad_controls_rejected():
    with pytest.raises(ValueError):
        StreamAdmissionGate(recovery_samples=True)
    with pytest.raises(ValueError):
        StreamAdmissionGate(max_sample_age_ms=200, min_sample_gap_ms=300)
    gate = active()
    with pytest.raises(ValueError):
        gate.advise("unknown", now_ms=1000)
    with pytest.raises(ValueError):
        gate.advise("vision", now_ms=float("inf"))
