"""Invalid OBS GetStats evidence must never be bridged into a healthy window.

Offline fixtures only; neither these tests nor the sampler connect to OBS.
"""

import pytest

from star.obs_stats_window import ObsStatsWindow


def stats(total=1000, *, skipped=0, output=1000, output_skipped=0):
    return {
        "renderTotalFrames": total,
        "renderSkippedFrames": skipped,
        "outputTotalFrames": output,
        "outputSkippedFrames": output_skipped,
    }


@pytest.mark.parametrize(
    ("damaged", "expect"),
    [
        ({**stats(), "renderTotalFrames": float("nan")}, ValueError),
        ({**stats(), "outputSkippedFrames": True}, ValueError),
        ({**stats(), "outputTotalFrames": "1100"}, ValueError),
        ({**stats(), "renderSkippedFrames": -1}, ValueError),
        ({**stats(), "renderTotalFrames": 2**60}, ValueError),
        ({**stats(), "outputTotalFrames": 1.5}, ValueError),
        ({"renderSkippedFrames": 0}, ValueError),
        (None, TypeError),
    ],
)
def test_invalid_middle_sample_revokes_continuity(damaged, expect):
    sampler = ObsStatsWindow()
    assert sampler.ingest(stats(), host_ms=1000, host_verified=True) is None
    with pytest.raises(expect):
        sampler.ingest(damaged, host_ms=1250, host_verified=True)
    # Would incorrectly report healthy without the middle-sample revocation.
    assert sampler.ingest(stats(1200, output=1200), host_ms=1500, host_verified=True) is None
    good = sampler.ingest(stats(1300, output=1300), host_ms=2000, host_verified=True)
    assert good is not None and good.window_ms == 500
    assert sampler.metrics()["rejected"] == 1
    assert sampler.metrics()["resets"] >= 1


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), -1, "1250", True])
def test_invalid_host_clock_revokes_prior_measurement(bad_time):
    sampler = ObsStatsWindow()
    assert sampler.ingest(stats(), host_ms=1000, host_verified=True) is None
    with pytest.raises(ValueError):
        sampler.ingest(stats(1020, output=1020), host_ms=bad_time, host_verified=True)
    assert sampler.ingest(stats(1100, output=1100), host_ms=1500, host_verified=True) is None
    assert sampler.ingest(stats(1200, output=1200), host_ms=2000, host_verified=True)


@pytest.mark.parametrize("auth", [False, 1, None])
def test_bad_authentication_disarms_old_counter_epoch(auth):
    sampler = ObsStatsWindow()
    assert sampler.ingest(stats(), host_ms=1000, host_verified=True) is None
    if auth is False:
        assert sampler.ingest(stats(1020, output=1020), host_ms=1250, host_verified=auth) is None
    else:
        with pytest.raises(ValueError):
            sampler.ingest(stats(1020, output=1020), host_ms=1250, host_verified=auth)
    assert sampler.ingest(stats(1100, output=1100), host_ms=1500, host_verified=True) is None
    assert sampler.ingest(stats(1200, output=1200), host_ms=2000, host_verified=True)
    assert sampler.metrics()["rejected"] == 1


def test_replayed_clock_destroys_continuity_until_two_fresh_samples():
    sampler = ObsStatsWindow()
    assert sampler.ingest(stats(), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(stats(1020, output=1020), host_ms=1000, host_verified=True) is None
    assert sampler.ingest(stats(1100, output=1100), host_ms=1500, host_verified=True) is None
    window = sampler.ingest(stats(1200, output=1200), host_ms=2000, host_verified=True)
    assert window is not None and window.window_ms == 500


def test_failed_future_host_clock_cannot_poison_valid_clock():
    sampler = ObsStatsWindow()
    assert sampler.ingest(stats(), host_ms=1000, host_verified=True) is None
    with pytest.raises(ValueError):
        sampler.ingest(stats(1100), host_ms=1e30, host_verified=True)
    # Revoke the old epoch instead of using untrusted future time as a watermark.
    assert sampler.ingest(stats(1100, output=1100), host_ms=1500, host_verified=True) is None
    assert sampler.ingest(stats(1200, output=1200), host_ms=2000, host_verified=True)
