"""Synthetic matched tests for end-of-turn latency / hesitation tradeoffs."""
from dataclasses import replace
import pytest

from star.stream_endpointing_eval import EndpointPause, assess_endpointing


def pauses(size: int = 20) -> list[EndpointPause]:
    rows = []
    for i in range(size):
        for variant in ("baseline", "candidate"):
            rows.append(EndpointPause(
                case_id=f"hesitation_{i}", variant=variant, pause_type="mid_turn",
                mid_turn_pause_ms=300, decision_after_pause_ms=None,
                independently_reviewed=True,
            ))
            rows.append(EndpointPause(
                case_id=f"final_{i}", variant=variant, pause_type="final_turn",
                decision_after_pause_ms=550 if variant == "baseline" else 450,
                independently_reviewed=True,
            ))
    return rows


def update(rows: list[EndpointPause], case: str, variant: str, **changes):
    return [replace(row, **changes) if (row.case_id, row.variant)
            == (case, variant) else row for row in rows]


def test_fast_and_low_cutoff_candidate_passes_manual_rehearsal_only():
    result = assess_endpointing(pauses())
    assert result.status == "eligible_for_manual_rehearsal"
    assert result.complete_pairs == 40
    assert result.candidate_final_p95_ms == 450
    assert result.candidate_false_cutoff_rate == 0
    assert result.authorized_to_stream is False


def test_one_new_cutoff_blocks_even_at_five_percent():
    rows = update(pauses(), "hesitation_0", "candidate",
                  decision_after_pause_ms=250)
    result = assess_endpointing(rows)
    assert result.candidate_false_cutoff_rate == 0.05
    assert result.new_false_cutoffs == 1
    assert result.status == "naturalness_regressed"


def test_old_cutoff_not_new_and_within_budget():
    rows = update(pauses(), "hesitation_0", "baseline", decision_after_pause_ms=270)
    rows = update(rows, "hesitation_0", "candidate", decision_after_pause_ms=250)
    result = assess_endpointing(rows)
    assert result.baseline_false_cutoffs == result.candidate_false_cutoffs == 1
    assert result.status == "eligible_for_manual_rehearsal"


def test_fast_but_reckless_detector_is_not_eligible():
    rows = pauses()
    for i in range(5):
        rows = update(rows, f"hesitation_{i}", "candidate", decision_after_pause_ms=100)
    result = assess_endpointing(rows)
    assert result.candidate_false_cutoffs == 5
    assert result.status == "naturalness_regressed"


def test_no_decision_on_true_turn_is_not_a_latency_win():
    result = assess_endpointing(update(pauses(), "final_0", "candidate",
                                       decision_after_pause_ms=None))
    assert result.candidate_missed_true_ends == 1
    assert result.status == "naturalness_regressed"


def test_large_pairwise_regression_cannot_hide_below_p95():
    result = assess_endpointing(update(pauses(), "final_19", "candidate",
                                       decision_after_pause_ms=850))
    assert result.candidate_final_p95_ms == 450
    assert result.final_pair_latency_regressions == 1
    assert result.status == "naturalness_regressed"


def test_unpaired_unreviewed_and_missing_baseline_prevent_promotion():
    assert assess_endpointing(pauses()[:-1]).status == "insufficient_evidence"
    assert assess_endpointing(update(pauses(), "final_0", "baseline",
                                      decision_after_pause_ms=None)).status == "insufficient_evidence"
    assert assess_endpointing(update(pauses(), "final_0", "candidate",
                                      independently_reviewed=False)).status == "insufficient_evidence"


def test_invalid_pauses_duplicate_evidence_and_mismatched_types_rejected():
    with pytest.raises(ValueError):
        EndpointPause("case", "candidate", "mid_turn", None, mid_turn_pause_ms=50)
    with pytest.raises(ValueError):
        EndpointPause("case", "candidate", "mid_turn", 301, mid_turn_pause_ms=300)
    with pytest.raises(ValueError):
        EndpointPause("case", "candidate", "final_turn", 100, mid_turn_pause_ms=300)
    with pytest.raises(ValueError):
        assess_endpointing(pauses() + [pauses()[0]])
    rows = pauses()
    rows[2] = replace(rows[2], pause_type="final_turn", mid_turn_pause_ms=None)
    with pytest.raises(ValueError):
        assess_endpointing(rows)


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan"), "120"])
def test_invalid_decision_timings_rejected(value):
    with pytest.raises(ValueError):
        EndpointPause("case", "candidate", "final_turn", value)


@pytest.mark.parametrize("settings", [
    {"minimum_per_type": 0}, {"max_false_cutoff_rate": 0.5},
    {"max_false_cutoff_rate": True}, {"max_false_cutoff_rate": 10**400},
    {"max_final_p95_ms": float("nan")},
    {"max_pair_regression_ms": 0},
])
def test_thresholds_bounded(settings):
    with pytest.raises(ValueError):
        assess_endpointing(pauses(), **settings)


def test_unbalanced_small_holdout_never_passes():
    assert assess_endpointing(pauses(12)).status == "insufficient_evidence"
