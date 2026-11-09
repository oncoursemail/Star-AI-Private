"""Offline regression tests for paired private inference speed evidence."""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from star.inference_stream_paired_gate import (
    StreamSpeedPair, compare_stream_speed, main,
)

SHA = "0" * 64
HOST = "1" * 64
WORK = "2" * 64
STATUSES = {
    "ok": 4, "empty": 0, "incomplete": 0, "truncated": 0,
    "canary_mismatch": 0, "failed": 0, "timeout": 0,
}


def summary(speech: float, *, complete: float = 450,
            workload: str = "mixed") -> dict:
    return {
        "requests": 4, "completed": 4, "failed": 0,
        "parallel_limit": 1, "workload": workload,
        "workload_sha256": WORK, "wall_ms": 1200,
        "first_visible_p95_ms": speech - 40,
        "first_speakable_p95_ms": speech,
        "complete_p95_ms": complete,
        "speakable_ready": 4, "speakable_missing": 0,
        "canary_mismatches": 0, "statuses": dict(STATUSES),
    }


def pair(index: int, baseline: dict | None = None,
         candidate: dict | None = None) -> StreamSpeedPair:
    # Distinct simulated wall clocks stand in for independent private trials.
    # Reusing identical data under six different IDs is not six experiments.
    baseline = baseline if baseline is not None else summary(300, complete=480)
    candidate = candidate if candidate is not None else summary(175, complete=405)
    baseline = dict(baseline, wall_ms=baseline["wall_ms"] + index)
    candidate = dict(candidate, wall_ms=candidate["wall_ms"] + index)
    return StreamSpeedPair(f"p{index}", SHA, HOST, baseline, candidate)


def evidence(n: int = 6) -> list[StreamSpeedPair]:
    return [pair(i) for i in range(n)]


def test_clear_measured_gain_eligible_only_for_private_pilot():
    report = compare_stream_speed(evidence())
    assert report.verdict == "eligible_for_private_pilot"
    assert report.complete_pairs == 6
    assert report.gain_ci95_ms == (125, 125)
    assert report.baseline_speakable_p95_ms == 300
    assert report.candidate_speakable_p95_ms == 175
    assert report.improved_speakable_pairs == 6
    assert report.non_tied_speakable_pairs == 6
    assert report.paired_sign_test_p == 0.015625
    assert "not attested" in report.note


def test_low_gain_not_promoted():
    pairs = [pair(i, candidate=summary(280)) for i in range(6)]
    assert compare_stream_speed(pairs).verdict == "inconclusive"


def test_one_lucky_tail_cannot_mask_inconsistent_paired_speech():
    # Five large wins can make the bootstrap gain CI look positive although
    # one of the six matched trials became slower. A 5/6 one-sided sign test
    # is not significant at the predeclared 0.05 confidence threshold.
    rows = [
        pair(i, baseline=summary(300), candidate=summary(200))
        for i in range(5)
    ] + [pair(5, baseline=summary(200), candidate=summary(210))]
    report = compare_stream_speed(rows)
    assert report.gain_ci95_ms is not None
    assert report.gain_ci95_ms[0] > 40
    assert report.candidate_speakable_p95_ms < report.baseline_speakable_p95_ms
    assert report.improved_speakable_pairs == 5
    assert report.non_tied_speakable_pairs == 6
    assert report.paired_sign_test_p == 0.109375
    assert report.verdict == "inconclusive"


def test_longer_consistent_paired_cohort_can_tolerate_one_nonwin():
    rows = [
        pair(i, baseline=summary(300), candidate=summary(200))
        for i in range(7)
    ] + [pair(7, baseline=summary(200), candidate=summary(210))]
    report = compare_stream_speed(rows)
    assert report.improved_speakable_pairs == 7
    assert report.non_tied_speakable_pairs == 8
    assert report.paired_sign_test_p == 0.03515625
    assert report.verdict == "eligible_for_private_pilot"


def test_ties_do_not_become_positive_speech_evidence():
    rows = [pair(i, candidate=summary(300)) for i in range(6)]
    report = compare_stream_speed(rows)
    assert report.paired_sign_test_p == 1.0
    assert report.improved_speakable_pairs == 0
    assert report.non_tied_speakable_pairs == 0
    assert report.verdict == "inconclusive"


def test_slow_candidate_regresses():
    pairs = evidence()
    pairs[1] = pair(1, candidate=summary(530, complete=670))
    assert compare_stream_speed(pairs).verdict == "regressed"


def test_candidate_partial_failure_is_not_hidden_by_success_p95():
    pairs = evidence()
    row = summary(180)
    row["completed"] = 3
    row["failed"] = 1
    row["statuses"]["ok"] = 3
    row["statuses"]["timeout"] = 1
    row["speakable_ready"] = 3
    pairs[0] = pair(0, candidate=row)
    report = compare_stream_speed(pairs)
    assert report.verdict == "regressed"
    assert report.complete_pairs == 5


def test_missing_speakable_chunk_is_regression():
    pairs = evidence()
    row = summary(180)
    row["speakable_ready"] = 3
    row["speakable_missing"] = 1
    pairs[-1] = pair(5, candidate=row)
    assert compare_stream_speed(pairs).verdict == "regressed"


def test_baseline_missing_coverage_is_inconclusive():
    pairs = evidence()
    row = summary(300)
    row["speakable_ready"] = 3
    row["speakable_missing"] = 1
    pairs[2] = pair(2, baseline=row)
    assert compare_stream_speed(pairs).verdict == "inconclusive"


def test_repeated_prompt_mode_cannot_be_used_as_broad_speed_proof():
    pairs = [pair(i, summary(300, workload="repeat"),
                  summary(100, workload="repeat")) for i in range(6)]
    assert compare_stream_speed(pairs).verdict == "inconclusive"


def test_not_enough_pairs_never_promote():
    assert compare_stream_speed(evidence(5)).verdict == "inconclusive"


def test_exact_measurement_replay_under_fresh_ids_never_promotes():
    original = pair(0)
    copied = [replace(original, pair_id=f"not-independent-{i}") for i in range(6)]
    report = compare_stream_speed(copied)
    assert report.verdict == "inconclusive"
    assert report.duplicate_summary_pairs == 5
    assert report.complete_pairs == 6


def test_untrusted_note_changes_do_not_launder_replayed_metrics():
    pairs = []
    for i in range(6):
        b, c = summary(300, complete=480), summary(175, complete=405)
        b["note"] = f"trial-{i}-warmup"
        c["note"] = f"trial-{i}-candidate"
        pairs.append(pair(0, baseline=b, candidate=c))
    unique_ids = [replace(p, pair_id=f"r{i}") for i, p in enumerate(pairs)]
    report = compare_stream_speed(unique_ids)
    assert report.verdict == "inconclusive"
    assert report.duplicate_summary_pairs == 5


def test_mismatch_target_host_or_workload_rejected():
    pairs = evidence()
    with pytest.raises(ValueError, match="model or host"):
        compare_stream_speed([*pairs[:-1], replace(pairs[-1], target_model_sha256="f" * 64)])
    with pytest.raises(ValueError, match="model or host"):
        compare_stream_speed([*pairs[:-1], replace(pairs[-1], host_profile_sha256="f" * 64)])
    with pytest.raises(ValueError, match="workload"):
        compare_stream_speed([*pairs[:-1], pair(5, summary(300, workload="canary"),
                                                       summary(175, workload="canary"))])


def test_duplicate_or_truncated_pair_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        compare_stream_speed([pair(0), pair(0)])
    with pytest.raises(ValueError, match="workload"):
        pair(0, candidate=summary(175, workload="canary"))


@pytest.mark.parametrize("key,value", [
    ("requests", True), ("completed", -1), ("wall_ms", float("nan")),
    ("workload_sha256", "invalid"), ("canary_mismatches", True),
    ("first_speakable_p95_ms", float("inf")), ("complete_p95_ms", -1),
    ("speakable_missing", 3),
])
def test_forged_malformed_metrics_rejected(key, value):
    row = summary(175)
    row[key] = value
    with pytest.raises(ValueError):
        pair(0, candidate=row)


def test_status_breakdown_must_match_completion_count():
    row = summary(175)
    row["statuses"]["ok"] = 3
    with pytest.raises(ValueError):
        pair(0, candidate=row)


def test_inconsistent_first_speakable_timestamp_is_rejected():
    with pytest.raises(ValueError):
        pair(0, candidate=summary(900, complete=400))


def test_nonidentical_prompt_hash_fails_before_comparison():
    row = summary(175)
    row["workload_sha256"] = "e" * 64
    with pytest.raises(ValueError):
        pair(0, candidate=row)


def test_strict_json_schema_rejects_unknown_fields():
    from star.inference_stream_paired_gate import StreamSpeedPair
    row = {"pair_id": "id", "target_model_sha256": SHA,
           "host_profile_sha256": HOST,
           "baseline": summary(300), "candidate": summary(170), "secret": "NO"}
    with pytest.raises(ValueError):
        StreamSpeedPair.from_dict(row)


def test_cli_reads_only_aggregate_reports_and_does_not_leak_filename(tmp_path, capsys):
    rows = [dict(pair_id=p.pair_id, target_model_sha256=p.target_model_sha256,
                 host_profile_sha256=p.host_profile_sha256,
                 baseline=p.baseline, candidate=p.candidate) for p in evidence()]
    file = tmp_path / "private-not-logged.json"
    file.write_text(json.dumps({"pairs": rows}))
    assert main([str(file)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["verdict"] == "eligible_for_private_pilot"
    assert "private-not-logged" not in json.dumps(output)
    file.write_text('{"pairs": "not an array"}')
    assert main([str(file)]) == 2
    assert json.loads(capsys.readouterr().out) == {"verdict": "invalid_evidence"}


def test_incomplete_candidate_without_complete_pairs_is_not_speed_gain():
    rows = []
    for i in range(6):
        candidate = summary(170)
        candidate["completed"] = 0
        candidate["failed"] = 4
        candidate["statuses"]["ok"] = 0
        candidate["statuses"]["timeout"] = 4
        candidate["first_speakable_p95_ms"] = None
        candidate["first_visible_p95_ms"] = None
        candidate["complete_p95_ms"] = None
        candidate["speakable_ready"] = 0
        rows.append(pair(i, candidate=candidate))
    assert compare_stream_speed(rows).verdict != "eligible_for_private_pilot"


def test_real_benchmark_summary_schema_is_consumable():
    from star.inference_stream_benchmark import StartupProbe, summarize_stream_startup
    baseline = summarize_stream_startup(
        [StartupProbe("geometry", 180, 460, "ok", first_speakable_ms=300)
         for _ in range(4)],
        1800, parallel=1, workload="mixed", workload_digest=WORK,
    )
    candidate = summarize_stream_startup(
        [StartupProbe("geometry", 90, 340, "ok", first_speakable_ms=180)
         for _ in range(4)],
        1400, parallel=1, workload="mixed", workload_digest=WORK,
    )
    assert StreamSpeedPair("real-probe", SHA, HOST, baseline, candidate)
    # A cloned live-shaped summary is only one observation, however many
    # different pair identifiers are wrapped around it.
    replay = [
        StreamSpeedPair(f"sample{i}", SHA, HOST, baseline, candidate)
        for i in range(6)
    ]
    assert compare_stream_speed(replay).verdict == "inconclusive"
    independent = [
        StreamSpeedPair(
            f"sample{i}", SHA, HOST,
            dict(baseline, wall_ms=1800 + i),
            dict(candidate, wall_ms=1400 + i),
        )
        for i in range(6)
    ]
    assert compare_stream_speed(independent).verdict == "eligible_for_private_pilot"


def test_post_construction_mutations_are_revalidated():
    original = pair(1)
    original.candidate["statuses"]["ok"] = 77
    with pytest.raises(ValueError):
        compare_stream_speed([original])


def test_summary_rejects_unrecognized_private_fields():
    row = summary(180)
    row["private_stream_transcript"] = "do not ingest"
    with pytest.raises(ValueError):
        pair(0, candidate=row)


def test_optional_cache_audit_metadata_is_validated():
    row = summary(300)
    row["canary_mismatch_case_ids"] = []
    row["category_latency_ms"] = {
        "gaming": {"count": 4, "p50_ms": 120, "p95_ms": 180},
    }
    assert pair(0, baseline=row)

    bad_ids = dict(row, canary_mismatch_case_ids=["slot-01"])
    with pytest.raises(ValueError, match="case identities"):
        pair(0, baseline=bad_ids)

    bad_latency = dict(row, category_latency_ms={
        "gaming": {"count": 4, "p50_ms": 180, "p95_ms": 120},
    })
    with pytest.raises(ValueError, match="p95"):
        pair(0, baseline=bad_latency)
