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
                independently_reviewed=True, source_turn_id=f"source_{i}",
            ))
            rows.append(EndpointPause(
                case_id=f"final_{i}", variant=variant, pause_type="final_turn",
                decision_after_pause_ms=550 if variant == "baseline" else 450,
                independently_reviewed=True, source_turn_id=f"source_{i}",
            ))
    return rows


def update(rows: list[EndpointPause], case: str, variant: str, **changes):
    return [replace(row, **changes) if (row.case_id, row.variant)
            == (case, variant) else row for row in rows]


def test_fast_and_low_cutoff_candidate_passes_manual_rehearsal_only():
    result = assess_endpointing(pauses(60))
    assert result.status == "eligible_for_manual_rehearsal"
    assert result.complete_pairs == 120
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
    rows = update(pauses(120), "hesitation_0", "baseline", decision_after_pause_ms=270)
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

def test_twenty_clean_pauses_cannot_prove_five_percent_false_cutoff_rate():
    result = assess_endpointing(pauses(20))
    assert result.status == "insufficient_evidence"
    assert result.reason == "false_cutoff_uncertainty_exceeds_budget"
    assert result.candidate_false_cutoff_rate == 0.0
    assert 0.13 < result.candidate_false_cutoff_upper_95 < 0.14


def test_sixty_clean_pauses_supports_manual_rehearsal_at_five_percent():
    result = assess_endpointing(pauses(60))
    assert result.status == "eligible_for_manual_rehearsal"
    assert 0.048 < result.candidate_false_cutoff_upper_95 < 0.049


def test_one_cutoff_requires_more_than_sixty_pauses_for_confidence():
    rows = update(pauses(60), "hesitation_0", "baseline", decision_after_pause_ms=250)
    rows = update(rows, "hesitation_0", "candidate", decision_after_pause_ms=250)
    result = assess_endpointing(rows)
    assert result.status == "insufficient_evidence"
    assert result.new_false_cutoffs == 0
    assert result.candidate_false_cutoff_upper_95 > 0.05

def test_missing_independent_turn_provenance_never_qualifies():
    rows = [replace(row, source_turn_id=None) for row in pauses(80)]
    result = assess_endpointing(rows)
    assert result.status == "insufficient_evidence"


def test_many_hesitations_from_one_turn_are_not_independent_trials():
    rows = [
        replace(row, source_turn_id="same_source_turn")
        if row.pause_type == "mid_turn" else row
        for row in pauses(80)
    ]
    result = assess_endpointing(rows)
    assert result.independent_mid_turns == 1
    assert result.candidate_false_cutoff_upper_95 > 0.9
    assert result.status == "insufficient_evidence"


def test_source_turn_identity_must_match_in_paired_variants():
    rows = update(pauses(80), "hesitation_0", "candidate",
                  source_turn_id="other_source_turn")
    with pytest.raises(ValueError, match="source"):
        assess_endpointing(rows)


@pytest.mark.parametrize("source", ["", "space id", "ꙮ", True, 42, "a" * 65])
def test_invalid_source_turn_identifiers_rejected(source):
    with pytest.raises(ValueError, match="source_turn_id"):
        EndpointPause(
            "test", "candidate", "mid_turn", None, 300, True,
            source_turn_id=source,
        )


def test_reusing_source_id_for_two_final_turns_is_rejected():
    rows = update(pauses(60), "final_1", "baseline", source_turn_id="source_0")
    rows = update(rows, "final_1", "candidate", source_turn_id="source_0")
    with pytest.raises(ValueError, match="duplicate final"):
        assess_endpointing(rows)


def test_all_premature_cutoffs_get_unit_risk_bound_and_fail():
    rows = [
        replace(row, decision_after_pause_ms=100)
        if row.pause_type == "mid_turn" else row
        for row in pauses(60)
    ]
    result = assess_endpointing(rows)
    assert result.candidate_turns_with_false_cutoff == 60
    assert result.independent_mid_turns == 60
    assert result.candidate_false_cutoff_upper_95 == 1.0
    assert result.status == "naturalness_regressed"


def test_one_shared_cutoff_can_qualify_only_with_enough_distinct_source_turns():
    rows = pauses(120)
    rows = update(rows, "hesitation_0", "baseline", decision_after_pause_ms=100)
    rows = update(rows, "hesitation_0", "candidate", decision_after_pause_ms=100)
    result = assess_endpointing(rows)
    assert result.candidate_turns_with_false_cutoff == 1
    assert result.independent_mid_turns == 120
    assert result.candidate_false_cutoff_upper_95 < 0.05
    assert result.status == "eligible_for_manual_rehearsal"
