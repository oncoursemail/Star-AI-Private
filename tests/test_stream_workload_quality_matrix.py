"""Synthetic multi-skill speed+quality gates; no real GPU, OBS or AI measured."""
from dataclasses import replace

import pytest

from star.stream_realtime_benchmark import RealtimeRun
from star.stream_realtime_quality_gate import QualityWitness
from star.stream_workload_quality_matrix import (
    REQUIRED_WORKLOADS, WorkloadEvidence, assess_workload_matrix,
)


def make_batch(workload: str, count: int = 24) -> WorkloadEvidence:
    runs = []
    witnesses = []
    for i in range(count):
        pair_id = f"{workload}-pair{i}"
        for variant in ("baseline", "candidate"):
            runs.append(RealtimeRun(
                pair_id, variant, f"scenario_{workload}", "v1",
                730 + i % 5 if variant == "baseline" else 420 + i % 5,
                (16.7 if variant == "baseline" else 16.8,) * 150,
                5200, True,
            ))
            witnesses.append(QualityWitness(
                pair_id, variant, True, True, True, 25.0,
            ))
    return WorkloadEvidence(workload, tuple(runs), tuple(witnesses))


def matrix() -> list[WorkloadEvidence]:
    return [make_batch(workload) for workload in REQUIRED_WORKLOADS]


def mutate_witness(batch: WorkloadEvidence, **changes) -> WorkloadEvidence:
    witnesses = list(batch.witnesses)
    witnesses[1] = replace(witnesses[1], **changes)
    return replace(batch, witnesses=tuple(witnesses))


def test_all_four_independent_quality_verified_workloads_are_needed():
    group = matrix()
    report = assess_workload_matrix(group)
    assert report.status == "eligible_for_manual_review"
    assert report.observed_workloads == report.required_workloads == 4
    assert report.total_matched_pairs == 96
    assert report.total_quality_witnesses == 192
    assert report.authorized_to_stream is False
    assert all(item.status == "eligible_for_manual_rehearsal"
               for item in report.results)
    assert report == assess_workload_matrix(reversed(group))


def test_missing_knowledge_workload_is_not_masked_by_fast_gameplay():
    group = matrix()
    report = assess_workload_matrix(group[:1] + group[2:])
    assert report.status == "insufficient_evidence"
    assert report.observed_workloads == 3
    assert report.results[1].status == "missing"


def test_wrong_general_knowledge_blocks_even_when_every_model_is_fast():
    group = matrix()
    group[1] = mutate_witness(group[1], correct=False)
    report = assess_workload_matrix(group)
    assert report.status == "quality_regressed"
    assert report.results[1].status == "quality_regressed"


def test_ungrounded_game_claim_and_missing_obs_sound_block():
    group = matrix()
    group[0] = mutate_witness(group[0], grounded=False)
    assert assess_workload_matrix(group).status == "quality_regressed"
    group = matrix()
    group[3] = mutate_witness(group[3], obs_audible=False, av_offset_ms=None)
    assert assess_workload_matrix(group).status == "quality_regressed"


def test_slow_roblox_creation_blocks_aggregate_speed_claim():
    group = matrix()
    batch = group[2]
    runs = tuple(replace(run, first_audio_ms=880)
                 if run.variant == "candidate" else run for run in batch.runs)
    group[2] = replace(batch, runs=runs)
    report = assess_workload_matrix(group)
    assert report.status == "speed_not_verified"
    assert report.results[2].status == "speed_not_verified"


def test_incomplete_knowledge_witness_is_not_success():
    group = matrix()
    group[1] = replace(group[1], witnesses=group[1].witnesses[:-1])
    report = assess_workload_matrix(group)
    assert report.status == "insufficient_evidence"


def test_partial_pair_does_not_count_as_complete():
    group = matrix()
    group[0] = replace(group[0], runs=group[0].runs[:-1],
                       witnesses=group[0].witnesses[:-1])
    assert assess_workload_matrix(group).status == "insufficient_evidence"


def test_repeated_pair_ids_across_skills_are_rejected():
    group = matrix()
    batch = group[1]
    source_pair = group[0].runs[0].pair_id
    old_pair = batch.runs[0].pair_id
    runs = tuple(replace(r, pair_id=source_pair)
                 if r.pair_id == old_pair else r for r in batch.runs)
    witnesses = tuple(replace(w, pair_id=source_pair)
                      if w.pair_id == old_pair else w for w in batch.witnesses)
    group[1] = replace(batch, runs=runs, witnesses=witnesses)
    with pytest.raises(ValueError, match="reused"):
        assess_workload_matrix(group)


def test_duplicate_or_unregistered_workload_cannot_override_failed_batch():
    group = matrix()
    with pytest.raises(ValueError, match="duplicate"):
        assess_workload_matrix(group + [group[0]])
    with pytest.raises(ValueError, match="unrecognized"):
        WorkloadEvidence("only_easy_gameplay", (), ())


@pytest.mark.parametrize("bad", [True, 0, 9, 201, "20", None])
def test_invalid_workload_sample_budget(bad):
    with pytest.raises(ValueError):
        assess_workload_matrix(matrix(), minimum_pairs_per_workload=bad)


def test_input_boundaries_and_no_private_case_ids_in_report():
    group = matrix()
    with pytest.raises(TypeError):
        assess_workload_matrix(group + [{"workload": "live_dialogue"}])
    with pytest.raises(ValueError, match="bounded"):
        WorkloadEvidence("live_dialogue", group[3].runs, (None,))
    with pytest.raises(ValueError, match="1..1000"):
        WorkloadEvidence("live_dialogue", (), ())
    text = str(assess_workload_matrix(group))
    assert "pair0" not in text and "scenario_" not in text
