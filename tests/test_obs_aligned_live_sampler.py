"""Offline, deterministic alignment of live OBS rendering and stream transport."""

import pytest

from star.obs_aligned_live_sampler import ObsAlignedLiveSampler, ObsAlignedLiveWindow


def stat(total=1000, skipped=0, out=1000, out_skipped=0):
    return {
        "renderSkippedFrames": skipped,
        "renderTotalFrames": total,
        "outputSkippedFrames": out_skipped,
        "outputTotalFrames": out,
    }


def stream(sent=100, skipped=0, duration=1000, active=True, reconnect=False):
    return {
        "outputActive": active,
        "outputReconnecting": reconnect,
        "outputDuration": duration,
        "outputSkippedFrames": skipped,
        "outputTotalFrames": sent,
    }


def submit(sampler, *, stats=None, network=None, t=1000, now=None, verified=True, delta=100):
    return sampler.ingest(
        stats=stat() if stats is None else stats,
        stream_status=stream() if network is None else network,
        stats_received_ms=t,
        stream_received_ms=t + delta,
        now_ms=t + delta + 50 if now is None else now,
        host_verified=verified,
    )


def arm():
    sampler = ObsAlignedLiveSampler()
    sampler.arm(owner_approved=True, obs_epoch="pid_1234_create_5678_ws_a")
    return sampler


def test_verified_intervals_join_only_after_two_responses():
    sampler = arm()
    assert submit(sampler) is None
    sample = submit(
        sampler,
        stats=stat(total=1100, skipped=3, out=1100, out_skipped=2),
        network=stream(sent=145, skipped=5, duration=1500),
        t=1500,
    )
    assert isinstance(sample, ObsAlignedLiveWindow)
    assert sample.render.window_ms == sample.network.window_ms == 500
    assert sample.render.render_lag_pct == pytest.approx(3)
    assert sample.render.output_lag_pct == pytest.approx(2)
    assert sample.network.network_dropped_pct == pytest.approx(10)
    assert not sample.authorizes_broadcast
    assert not sample.authorizes_game_input
    assert sampler.metrics()["accepted"] == 1


def test_untrusted_middle_observation_latches_disarmed():
    sampler = arm()
    assert submit(sampler) is None
    assert submit(sampler, t=1250, verified=False) is None
    assert sampler.metrics()["armed"] is False
    assert submit(sampler, stats=stat(total=1100), t=1500) is None
    with pytest.raises(RuntimeError):
        sampler.arm(owner_approved=True, obs_epoch="pid_1234_create_5678_ws_a")
    sampler.arm(owner_approved=True, obs_epoch="pid_1234_create_5678_ws_b")
    assert submit(sampler, stats=stat(total=1100), network=stream(sent=145, duration=1500), t=1500) is None
    assert (
        submit(
            sampler,
            stats=stat(total=1200, out=1100),
            network=stream(sent=175, duration=2000),
            t=2000,
        )
        is not None
    )


@pytest.mark.parametrize(
    ("status", "bad_stats"),
    [
        (stream(active=False), None),
        (stream(reconnect=True), None),
        ({**stream(), "outputTotalFrames": "100"}, None),
        (stream(sent=90, duration=1500), None),
        (stream(sent=125, duration=9000), None),
        (stream(sent=125, duration=1500), {**stat(), "outputTotalFrames": float("nan")}),
    ],
)
def test_invalid_observation_disarms_entire_host_epoch(status, bad_stats):
    sampler = arm()
    assert submit(sampler) is None
    assert (
        submit(
            sampler,
            network=status,
            stats=stat(total=1100, out=1100) if bad_stats is None else bad_stats,
            t=1500,
        )
        is None
    )
    assert sampler.metrics()["armed"] is False


@pytest.mark.parametrize("deltams", [251, 500, -300])
def test_clock_skew_between_two_obs_responses_revokes(deltams):
    sampler = arm()
    assert submit(sampler) is None
    assert (
        submit(
            sampler,
            stats=stat(total=1100, out=1100),
            network=stream(sent=145, duration=1500),
            t=1500,
            delta=deltams,
        )
        is None
    )
    assert not sampler.metrics()["armed"]


def test_old_obs_receipts_are_not_usable_as_current_performance():
    sampler = arm()
    assert submit(sampler) is None
    assert (
        submit(
            sampler,
            stats=stat(total=1100, out=1100),
            network=stream(sent=145, duration=1500),
            t=1500,
            now=10000,
        )
        is None
    )
    assert sampler.metrics()["armed"] is False


def test_counter_reset_in_only_one_source_revokes_both():
    sampler = arm()
    assert submit(sampler) is None
    assert submit(
        sampler,
        stats=stat(total=1100, out=1100),
        network=stream(sent=145, duration=1500),
        t=1500,
    )
    assert (
        submit(
            sampler,
            stats=stat(total=1200, out=1200),
            network=stream(sent=5, duration=2000),
            t=2000,
        )
        is None
    )
    assert not sampler.metrics()["armed"]


def test_invalid_configuration_and_unapproved_arm():
    for kw in ({"max_response_span_ms": True}, {"max_age_ms": 10}, {"max_response_span_ms": 1000}):
        with pytest.raises(ValueError):
            ObsAlignedLiveSampler(**kw)
    sampler = ObsAlignedLiveSampler()
    with pytest.raises(PermissionError):
        sampler.arm(obs_epoch="a")
    with pytest.raises(ValueError):
        sampler.arm(owner_approved=True, obs_epoch="invalid\\newline\\n")
    with pytest.raises(ValueError):
        sampler.arm(owner_approved=True, obs_epoch="")
    sampler.arm(owner_approved=True, obs_epoch="a")
    with pytest.raises(RuntimeError):
        sampler.arm(owner_approved=True, obs_epoch="b")
    sampler.stop()
    assert not sampler.metrics()["armed"]


def test_no_output_activity_never_proves_healthy():
    sampler = arm()
    assert submit(sampler) is None
    assert (
        submit(
            sampler,
            stats=stat(total=1100, out=1100),
            network=stream(sent=100, duration=1500),
            t=1500,
        )
        is None
    )
    assert sampler.metrics()["accepted"] == 0
