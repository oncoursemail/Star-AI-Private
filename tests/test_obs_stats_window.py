"""OBS v5 GetStats fixtures; never connects to OBS or captures video."""
import pytest
from star.obs_stats_window import ObsLagWindow, ObsStatsWindow
from star.stream_admission import StreamAdmissionGate, StreamHealthSample
from star.stream_budget import StreamTelemetry


def counters(*, rskip=0, rtotal=1000, oskip=0, ototal=1000):
    return dict(renderSkippedFrames=rskip, renderTotalFrames=rtotal,
                outputSkippedFrames=oskip, outputTotalFrames=ototal,
                extra_untrusted_data="viewer-id-not-retained")


def test_two_samples_produce_interval_not_lifetime_percentages():
    s = ObsStatsWindow()
    assert s.ingest(counters(rskip=100, rtotal=1000), host_ms=1000,
                    host_verified=True) is None
    x = s.ingest(counters(rskip=102, rtotal=1100, oskip=3, ototal=1097),
                 host_ms=1500, host_verified=True)
    assert isinstance(x, ObsLagWindow)
    assert x.window_ms == 500
    assert x.render_lag_pct == pytest.approx(100 * 2 / 102)
    assert x.output_lag_pct == pytest.approx(100 * 3 / 100)
    assert s.metrics()["windows"] == 1


def test_obs_lag_feeds_existing_admission_advice():
    s, gate = ObsStatsWindow(), StreamAdmissionGate()
    gate.enable(owner_approved=True)
    assert s.ingest(counters(), host_ms=1000, host_verified=True) is None
    x = s.ingest(counters(rskip=3, rtotal=1097, ototal=1100), host_ms=1500,
                 host_verified=True)
    assert x is not None
    telemetry = StreamTelemetry(True, True, 2048, 8192, 60, 30)
    assert gate.observe(StreamHealthSample(x.observed_ms, telemetry,
                                         x.render_lag_pct, x.output_lag_pct,
                                         host_verified=True))
    assert not gate.advise("vision", now_ms=1510).allowed
    assert gate.advise("speech", now_ms=1510).allowed


def test_small_sampling_interval_is_debounced_without_losing_baseline():
    s = ObsStatsWindow()
    s.ingest(counters(), host_ms=1000, host_verified=True)
    assert s.ingest(counters(rtotal=1010, ototal=1010), host_ms=1100,
                    host_verified=True) is None
    x = s.ingest(counters(rtotal=1100, ototal=1100), host_ms=1500,
                 host_verified=True)
    assert x is not None and x.window_ms == 500


def test_reset_counter_restarts_baseline_not_negative_rate():
    s = ObsStatsWindow()
    s.ingest(counters(rskip=50), host_ms=1000, host_verified=True)
    assert s.ingest(counters(rskip=1), host_ms=1500,
                    host_verified=True) is None
    x = s.ingest(counters(rskip=2, rtotal=1100, ototal=1100),
                 host_ms=2000, host_verified=True)
    assert x is not None
    assert s.metrics()["resets"] == 1


def test_long_gap_restarts_baseline_and_no_wakeup_assumption():
    s = ObsStatsWindow()
    s.ingest(counters(), host_ms=1000, host_verified=True)
    assert s.ingest(counters(rtotal=1100, ototal=1100), host_ms=6500,
                    host_verified=True) is None
    x = s.ingest(counters(rtotal=1200, ototal=1200), host_ms=7000, host_verified=True)
    assert x is not None and x.render_lag_pct == 0


def test_no_output_frames_is_not_healthy_admission_evidence():
    s = ObsStatsWindow()
    s.ingest(counters(), host_ms=1000, host_verified=True)
    assert s.ingest(counters(), host_ms=1500, host_verified=True) is None


def test_unauthenticated_and_replayed_frames_cannot_update_baseline():
    s = ObsStatsWindow()
    assert s.ingest(counters(), host_ms=1000) is None
    assert s.ingest(counters(), host_ms=1000, host_verified=True) is None
    assert s.ingest(counters(rskip=20), host_ms=1000,
                    host_verified=True) is None
    assert s.ingest(counters(rskip=20), host_ms=1200, host_verified=False) is None
    x = s.ingest(counters(rskip=2, rtotal=1100, ototal=1100), host_ms=1500,
                 host_verified=True)
    assert x is not None
    assert x.render_lag_pct == pytest.approx(100 * 2 / 102)
    assert s.metrics()["rejected"] == 3


@pytest.mark.parametrize("value", [-1, True, 2**60, float("inf"),
                                    float("nan"), 1.5, "5"])
def test_malformed_counters_rejected(value):
    s = ObsStatsWindow()
    with pytest.raises(ValueError):
        s.ingest(counters(rskip=value), host_ms=1000, host_verified=True)


def test_rejected_counter_input_does_not_poison_valid_next_sample():
    s = ObsStatsWindow()
    with pytest.raises(ValueError):
        s.ingest(counters(rtotal=float("nan")), host_ms=1000,
                 host_verified=True)
    assert s.ingest(counters(), host_ms=1100, host_verified=True) is None
    assert s.ingest(counters(rtotal=1100, ototal=1100), host_ms=1600,
                    host_verified=True) is not None


def test_invalid_host_time_and_interval_controls():
    with pytest.raises(ValueError):
        ObsStatsWindow(min_window_ms=True)
    with pytest.raises(ValueError):
        ObsStatsWindow(min_window_ms=2000, max_window_ms=1000)
    s = ObsStatsWindow()
    with pytest.raises(ValueError):
        s.ingest(counters(), host_ms=float("nan"), host_verified=True)
    with pytest.raises(ValueError):
        s.ingest(counters(), host_ms=1000, host_verified=1)


def test_explicit_reset_requires_new_two_sample_window():
    s = ObsStatsWindow()
    s.ingest(counters(), host_ms=1000, host_verified=True)
    s.reset()
    assert s.ingest(counters(), host_ms=2500, host_verified=True) is None
    assert s.ingest(counters(rtotal=1100, ototal=1100), host_ms=3000,
                    host_verified=True) is not None
