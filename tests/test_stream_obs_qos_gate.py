"""Offline synthetic checks only; no claim about real OBS/gaming performance."""
from dataclasses import replace

import pytest
import json

from star.stream_realtime_benchmark import RealtimeRun
from star.stream_obs_qos_gate import (
    ObsFrameWindow, ObsStatsCounters, compare_realtime_with_obs, read_obs_jsonl,
)


def run(pair, variant, *, ttfa=None, frame=16.7, finished=True):
    return RealtimeRun(
        pair, variant, "obby", "v2",
        float(ttfa if ttfa is not None else (650 if variant == "baseline" else 400)),
        (frame,) * 150, 5000.0, finished,
    )


def counters(rendered, render_dropped=0, output=0, output_dropped=0):
    return ObsStatsCounters(rendered, render_dropped, output, output_dropped)


def window(pair, variant, *, render_drop=0, output_drop=0,
           reconnect=False, active=True, duration=10_000,
           game="obby", version="v2"):
    return ObsFrameWindow(
        pair, variant, game, version, "session_" + variant,
        1000, 1000 + duration,
        counters(1000, 10, 1000, 10),
        counters(1600, 10 + render_drop, 1600, 10 + output_drop),
        active, reconnect,
    )


def cohort(n=24, *, candidate_render_drop=0, candidate_output_drop=0):
    runs, obs = [], []
    for i in range(n):
        pair = f"p{i:02d}"
        for variant in ("baseline", "candidate"):
            runs.append(run(pair, variant))
            obs.append(window(
                pair, variant,
                render_drop=candidate_render_drop if variant == "candidate" else 0,
                output_drop=candidate_output_drop if variant == "candidate" else 0,
            ))
    return runs, obs


def test_good_obs_plus_faster_voice_and_healthy_game_only_allows_manual_pilot():
    runs, windows = cohort()
    report = compare_realtime_with_obs(runs, windows)
    assert report.verdict == "eligible_for_manual_pilot"
    assert report.performance_verdict == "eligible_for_manual_pilot"
    assert report.paired_windows == 24
    assert report.candidate_render_skipped_pct == 0
    assert report.candidate_output_skipped_pct == 0
    assert report.candidate_reconnections == 0
    assert "network-loss guarantee" in report.note
    assert compare_realtime_with_obs(list(reversed(runs)), list(reversed(windows))) == report
    assert "p00" not in str(report)


@pytest.mark.parametrize("field", ["render", "output"])
def test_observable_stutter_vetoes_nominally_faster_tts(field):
    runs, windows = cohort(candidate_render_drop=7 if field == "render" else 0,
                           candidate_output_drop=7 if field == "output" else 0)
    report = compare_realtime_with_obs(runs, windows)
    assert report.performance_verdict == "eligible_for_manual_pilot"
    assert report.verdict == "regressed"
    assert getattr(report, f"candidate_{field}_skipped_pct") > 0.5


@pytest.mark.parametrize("field", ["render", "output"])
def test_single_bad_window_cannot_hide_in_good_average(field):
    runs, windows = cohort()
    index = len(windows) - 1
    windows[index] = window("p23", "candidate",
                            render_drop=9 if field == "render" else 0,
                            output_drop=9 if field == "output" else 0)
    report = compare_realtime_with_obs(runs, windows)
    assert report.verdict == "regressed"
    assert getattr(report, f"worst_candidate_{field}_pct") > 1


def test_candidate_reconnecting_stops_pilot_even_if_counters_look_good():
    runs, windows = cohort()
    windows[-1] = replace(windows[-1], reconnect_observed=True)
    report = compare_realtime_with_obs(runs, windows)
    assert report.verdict == "regressed"
    assert report.candidate_reconnections == 1
    windows[-1] = replace(windows[-1], reconnect_observed=False, stream_active=False)
    assert compare_realtime_with_obs(runs, windows).verdict == "regressed"


def test_baseline_reconnect_invalidates_comparison_not_a_candidate_failure():
    runs, windows = cohort()
    windows[0] = replace(windows[0], reconnect_observed=True)
    result = compare_realtime_with_obs(runs, windows)
    assert result.verdict == "inconclusive"
    assert result.candidate_render_skipped_pct is None


def test_audio_or_game_regression_never_passes_with_clean_obs():
    runs, windows = cohort()
    runs[-1] = replace(runs[-1], audio_finished=False)
    assert compare_realtime_with_obs(runs, windows).verdict == "regressed"
    runs, windows = cohort()
    runs = [replace(x, frame_times_ms=(30.0,) * 150)
            if x.variant == "candidate" else x for x in runs]
    assert compare_realtime_with_obs(runs, windows).verdict == "regressed"


def test_missing_obs_window_never_counts_as_clean_and_no_unpaired_promotions():
    runs, windows = cohort()
    result = compare_realtime_with_obs(runs, windows[:-1])
    assert result.verdict == "inconclusive"
    assert result.missing_windows == 1
    assert compare_realtime_with_obs(runs, []).verdict == "inconclusive"
    assert compare_realtime_with_obs([], []).verdict == "inconclusive"


def test_few_pairs_or_slower_voice_are_never_eligible():
    runs, windows = cohort(8)
    assert compare_realtime_with_obs(runs, windows).verdict == "inconclusive"
    runs, windows = cohort()
    runs = [replace(r, first_audio_ms=850) if r.variant == "candidate"
            else r for r in runs]
    assert compare_realtime_with_obs(runs, windows).verdict == "regressed"


def test_extra_duplicate_or_wrong_scope_windows_rejected():
    runs, windows = cohort()
    with pytest.raises(ValueError, match="duplicate"):
        compare_realtime_with_obs(runs, windows + [windows[-1]])
    with pytest.raises(ValueError, match="unmatched"):
        compare_realtime_with_obs(runs, windows + [window("stray", "baseline")])
    windows[-1] = replace(windows[-1], game_version="wrong")
    with pytest.raises(ValueError, match="scopes"):
        compare_realtime_with_obs(runs, windows)


def test_mismatched_exposure_is_not_a_fair_paired_run():
    runs, windows = cohort()
    windows[-1] = replace(windows[-1], end_ms=7000)
    with pytest.raises(ValueError, match="different exposure"):
        compare_realtime_with_obs(runs, windows)


def test_getstats_projects_only_four_fields_and_accepts_integral_json_numbers():
    source = {
        "renderTotalFrames": 6000.0, "renderSkippedFrames": 2.0,
        "outputTotalFrames": 5900.0, "outputSkippedFrames": 1.0,
        "cpuUsage": 50, "webSocketSessionIncomingMessages": "PRIVATE",
    }
    assert ObsStatsCounters.from_getstats(source) == counters(6000, 2, 5900, 1)
    source.pop("renderTotalFrames")
    with pytest.raises(ValueError, match="missing"):
        ObsStatsCounters.from_getstats(source)


@pytest.mark.parametrize("bad", [True, -1, 0.3, 1e100, float("nan"),
                                  float("inf"), "10", None])
def test_invalid_obs_counters_never_default_to_zero(bad):
    with pytest.raises(ValueError):
        counters(bad, 0, 100, 0)


def test_counters_must_be_consistent_and_restarts_detected():
    with pytest.raises(ValueError, match="exceed"):
        counters(10, 11, 100, 0)
    with pytest.raises(ValueError, match="backwards"):
        replace(window("p", "baseline"),
                after=counters(700, 0, 1500, 0))
    with pytest.raises(ValueError, match="too few frames"):
        replace(window("p", "baseline"),
                after=counters(1020, 10, 1600, 10))
    with pytest.raises(ValueError, match="invalid skip deltas"):
        replace(window("p", "baseline"),
                after=counters(1600, 700, 1600, 10))


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), 1e100, -10, "500"])
def test_invalid_times_and_thresholds_rejected(bad):
    if bad is not True:
        with pytest.raises(ValueError):
            replace(window("p", "baseline"), end_ms=bad)
    runs, windows = cohort()
    with pytest.raises(ValueError):
        compare_realtime_with_obs(runs, windows, max_render_skip_pct=bad)


def test_window_rejects_invalid_status_type_and_suspicious_very_short_window():
    with pytest.raises(ValueError, match="booleans"):
        replace(window("p", "candidate"), stream_active=1)
    with pytest.raises(ValueError, match="2 seconds"):
        replace(window("p", "candidate"), end_ms=1500)
    with pytest.raises(ValueError, match="short opaque"):
        replace(window("p", "candidate"), pair_id="../a")


def test_reject_nonmaterialized_or_unsupported_evidence():
    runs, windows = cohort()
    with pytest.raises(TypeError, match="materialized"):
        compare_realtime_with_obs(iter(runs), windows)
    with pytest.raises(TypeError, match="validated"):
        compare_realtime_with_obs(runs, [dict(pair_id="p00")])


def test_jsonl_loader_disallows_private_fields_and_oversized_metadata(tmp_path):
    path = tmp_path / "obs.jsonl"
    row = {
        "pair_id": "p0", "variant": "baseline", "game_id": "obby",
        "game_version": "v2", "session_id": "s1",
        "start_ms": 1000, "end_ms": 11000,
        "before": {
            "renderTotalFrames": 1000, "renderSkippedFrames": 0,
            "outputTotalFrames": 1000, "outputSkippedFrames": 0,
            "private_other_data": "must never reach the report",
        },
        "after": {
            "renderTotalFrames": 1600, "renderSkippedFrames": 2,
            "outputTotalFrames": 1600, "outputSkippedFrames": 1,
        },
        "stream_active": True, "reconnect_observed": False,
    }
    path.write_text(json.dumps(row) + "\n")
    decoded = read_obs_jsonl(path)
    assert len(decoded) == 1
    assert decoded[0].render_skipped == 2
    assert "must never" not in str(decoded)
    row["raw_audio"] = "SECRET"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="exactly"):
        read_obs_jsonl(path)
    path.write_text("x" * 2_000_001)
    with pytest.raises(ValueError, match="2 MB"):
        read_obs_jsonl(path)


def test_reconnect_or_skip_drift_cannot_be_hidden_below_absolute_limit():
    runs, windows = cohort()
    windows[-1] = window("p23", "candidate", render_drop=2)
    # Only one bad window: 2/600=0.333%, below the absolute 0.5%
    # and baseline 0%; cohort aggregate is tiny, so this is acceptable.
    assert compare_realtime_with_obs(runs, windows).verdict == "eligible_for_manual_pilot"
    windows = [window(w.pair_id, "candidate", render_drop=2)
               if w.variant == "candidate" else w for w in windows]
    # Persistent 0.333pp increase still matters despite good absolute rate.
    result = compare_realtime_with_obs(runs, windows)
    assert result.candidate_render_skipped_pct < 0.5
    assert result.render_skip_increase_pp > 0.2
    assert result.verdict == "regressed"
