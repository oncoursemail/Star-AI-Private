"""Synthetic fixtures validate an evaluator, NOT Star's real gaming performance."""
import json
import math

import pytest

from star.stream_realtime_benchmark import (
    RealtimeRun, compare_realtime, read_jsonl,
)


def row(pair, variant, *, ttfa=600.0, frame_ms=16.7, gpu=5000,
        finished=True, game="ObbyA", version="v1"):
    return RealtimeRun(
        pair, variant, game, version, ttfa, (frame_ms,) * 150,
        gpu, finished,
    )


def cohort(n=24, *, base=650, new=420, base_frames=16.7,
           new_frames=16.8, new_gpu=5400):
    result = []
    for i in range(n):
        jitter = (i % 5) * 9
        result.append(row(f"pair-{i}", "baseline", ttfa=base + jitter,
                          frame_ms=base_frames))
        result.append(row(f"pair-{i}", "candidate", ttfa=new + jitter,
                          frame_ms=new_frames, gpu=new_gpu))
    return result


def test_strict_paired_evidence_supports_only_manual_hardware_pilot():
    records = cohort()
    summary = compare_realtime(records)
    assert summary.complete_pairs == 24
    assert summary.incomplete_pairs == summary.failed_pairs == 0
    assert summary.verdict == "eligible_for_manual_pilot"
    assert summary.ttfa_mean_gain_ms == pytest.approx(230)
    assert summary.ttfa_gain_ci95_ms[0] > 30
    assert summary.fps_gain_ci95[0] > -3
    assert summary.scope == "ObbyA:v1"
    assert "host-measured" in summary.note
    # No identifying run IDs or dialogue can escape into a report.
    assert "pair-0" not in str(summary)
    assert compare_realtime(list(reversed(records))) == summary


def test_better_ttfa_does_not_justify_damaged_game_framerate():
    result = compare_realtime(cohort(new_frames=28))
    assert result.verdict == "regressed"
    assert result.fps_gain_ci95[1] < -3


def test_faster_game_does_not_justify_slow_speech():
    result = compare_realtime(cohort(base=450, new=700))
    assert result.verdict == "regressed"
    assert result.ttfa_gain_ci95_ms[1] < -30


def test_candidate_exceeding_gpu_budget_never_passes():
    summary = compare_realtime(cohort(new_gpu=7400))
    assert summary.verdict == "regressed"
    assert summary.candidate_gpu_peak_mib == 7400


def test_too_few_pairs_are_inconclusive_even_with_large_speedup():
    summary = compare_realtime(cohort(8))
    assert summary.verdict == "inconclusive"
    assert summary.complete_pairs == 8


def test_failed_candidate_speech_vetoes_experiment():
    records = cohort()
    records[-1] = row("pair-23", "candidate", ttfa=420, finished=False)
    assert compare_realtime(records).verdict == "regressed"
    assert compare_realtime(records).failed_pairs == 1


def test_unpaired_rows_never_promote_candidate():
    records = cohort()
    records.pop()
    result = compare_realtime(records)
    assert result.incomplete_pairs == 1
    assert result.verdict == "inconclusive"


def test_cannot_cherry_pick_duplicate_variants_or_mix_game_versions():
    records = cohort(10)
    with pytest.raises(ValueError, match="duplicate"):
        compare_realtime(records + [records[0]])
    with pytest.raises(ValueError, match="unrelated"):
        compare_realtime(records + [row("other", "baseline", version="v2")])


def test_empty_inconclusive_and_all_failed_never_piloted():
    assert compare_realtime([]).verdict == "inconclusive"
    assert compare_realtime([
        row("x", "baseline", finished=False),
        row("x", "candidate", finished=False),
    ]).verdict == "regressed"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -5, True, "500"])
def test_untrusted_numeric_values_fail_closed(bad):
    with pytest.raises(ValueError):
        row("x", "baseline", ttfa=bad)
    with pytest.raises(ValueError):
        row("x", "candidate", frame_ms=bad)
    with pytest.raises(ValueError):
        row("x", "baseline", gpu=bad)


def test_bad_variant_id_sample_counts_and_bool_fail_closed():
    with pytest.raises(ValueError):
        row("../path", "baseline")
    with pytest.raises(ValueError):
        row("safe", "arbitrary")
    with pytest.raises(ValueError):
        row("safe", "baseline", finished=1)
    with pytest.raises(ValueError, match="120..5000"):
        RealtimeRun("safe", "baseline", "game", "v1", 100, (20.0,), 250, True)
    with pytest.raises(ValueError, match="minimum_pairs"):
        compare_realtime(cohort(2), minimum_pairs=0)


def test_jsonl_decoder_rejects_undeclared_fields_and_converts_frame_arrays(tmp_path):
    row_dict = {
        "pair_id": "pair1", "variant": "baseline", "game_id": "game",
        "game_version": "v1", "first_audio_ms": 200,
        "frame_times_ms": [16.7] * 120, "gpu_peak_mib": 1000,
        "audio_finished": True,
    }
    path = tmp_path / "host.jsonl"
    path.write_text(json.dumps(row_dict) + "\n", encoding="utf8")
    decoded = read_jsonl(path)
    assert len(decoded) == 1
    assert type(decoded[0].frame_times_ms) is tuple
    row_dict["raw_chat_text"] = "private text should never be parsed"
    path.write_text(json.dumps(row_dict), encoding="utf8")
    with pytest.raises(ValueError, match="only the eight"):
        read_jsonl(path)


def test_no_frames_and_gpu_overcommit_never_pass():
    records = cohort()
    with pytest.raises(ValueError):
        compare_realtime(records, gpu_budget_mib=float("nan"))
    with pytest.raises(ValueError, match="too many recorded runs"):
        compare_realtime(
            row(f"overflow-{i // 2}", "baseline" if i % 2 == 0 else "candidate")
            for i in range(1002)
        )


def test_one_bad_audible_reply_cannot_hide_under_aggregate_p95():
    records = cohort()
    records[-1] = row("pair-23", "candidate", ttfa=1300, frame_ms=16.8,
                      gpu=5400)
    result = compare_realtime(records)
    assert result.verdict == "regressed"
    assert result.candidate_pair_audio_regressions == 1


def test_one_severe_display_hitch_cannot_hide_under_p99():
    records = cohort()
    last = records[-1]
    records[-1] = RealtimeRun(last.pair_id, last.variant, last.game_id,
                              last.game_version, last.first_audio_ms,
                              (16.8,) * 149 + (333.0,), 5400, True)
    result = compare_realtime(records)
    assert result.verdict == "regressed"
    assert result.candidate_hitch_runs == 1
    assert result.candidate_new_hitch_runs == 1


def test_one_pair_fps_loss_cannot_hide_in_group_bootstrap():
    records = cohort()
    records[-1] = row("pair-23", "candidate", ttfa=420, frame_ms=19.7,
                      gpu=5400)
    result = compare_realtime(records)
    assert result.verdict == "regressed"
    assert result.candidate_pair_fps_regressions == 1


def test_inherited_severe_hitch_is_inconclusive_not_falsely_new_regression():
    records = cohort()
    baseline = records[-2]
    candidate = records[-1]
    records[-2] = RealtimeRun(baseline.pair_id, baseline.variant,
                              baseline.game_id, baseline.game_version,
                              baseline.first_audio_ms, (16.7,) * 149 + (333.0,),
                              5000, True)
    records[-1] = RealtimeRun(candidate.pair_id, candidate.variant,
                              candidate.game_id, candidate.game_version,
                              candidate.first_audio_ms, (16.8,) * 149 + (300.0,),
                              5400, True)
    result = compare_realtime(records)
    assert result.verdict == "inconclusive"
    assert result.candidate_hitch_runs == 1
    assert result.candidate_new_hitch_runs == 0


def test_custom_thresholds_and_bad_limits_fail_closed():
    records = cohort()
    assert compare_realtime(records, max_pair_audio_regression_ms=300,
                            max_pair_fps_loss=10,
                            max_candidate_frame_ms=250).verdict == "eligible_for_manual_pilot"
    for options in ({"max_pair_audio_regression_ms": True},
                    {"max_pair_fps_loss": float("nan")},
                    {"max_candidate_frame_ms": 1},
                    {"max_candidate_frame_ms": float("inf")}):
        with pytest.raises(ValueError):
            compare_realtime(records, **options)
