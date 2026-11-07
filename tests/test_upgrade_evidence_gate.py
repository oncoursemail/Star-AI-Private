"""Offline regression, provenance and quality tests for Star's upgrade gate."""
from dataclasses import replace

import pytest

from star.upgrade_evidence_gate import (
    CATEGORIES,
    UpgradeCase,
    UpgradeObservation,
    UpgradePlan,
    compare_upgrade,
)

SUITE = "a" * 64
BASELINE = "b" * 64
CANDIDATE = "c" * 64
SCORER = "d" * 64
ENV = "e" * 64


def fixture_data():
    cases = tuple(
        UpgradeCase(f"{category}-{i:02}", category, ENV)
        for category in CATEGORIES
        for i in range(12)
    )
    plan = UpgradePlan(
        SUITE, SCORER, BASELINE, CANDIDATE, cases, True, True,
    )
    rows = []
    for index, case in enumerate(cases):
        order = "AB" if index % 2 == 0 else "BA"
        rows.append(UpgradeObservation(
            case.case_id, "baseline", order, ENV, SCORER,
            True, 450.0, 2100.0, True, True, False,
        ))
        rows.append(UpgradeObservation(
            case.case_id, "candidate", order, ENV, SCORER,
            True, 180.0, 2400.0, True, True, False,
        ))
    return plan, rows


def change(rows, *, case, variant="candidate", **changes):
    for position, row in enumerate(rows):
        if row.case_id == case and row.variant == variant:
            rows[position] = replace(row, **changes)
            return
    raise AssertionError("case not found")


def test_full_six_category_heldout_is_eligible_only_for_owner_review():
    plan, rows = fixture_data()
    report = compare_upgrade(plan, rows)
    assert report.verdict == "eligible_for_owner_review"
    assert report.reason == "paired_multidomain_checks_pass"
    assert report.complete_pairs == 72
    assert report.missing_pairs == report.untrusted_pairs == 0
    assert report.mean_latency_gain_ms == 270
    assert report.gain_ci95_ms == (270, 270)
    assert report.baseline_latency_p95_ms == 450
    assert report.candidate_latency_p95_ms == 180
    assert len(report.categories) == len(CATEGORIES)
    assert all(group.pairs == 12 and group.success_delta_ci95 == (0, 0)
               for group in report.categories)
    assert "no proof" in report.note.lower()


def test_order_independence_of_observation_array():
    plan, rows = fixture_data()
    assert compare_upgrade(plan, list(reversed(rows))) == compare_upgrade(plan, rows)


def test_missing_case_pair_is_inconclusive_not_fictitious_success():
    plan, rows = fixture_data()
    report = compare_upgrade(plan, rows[:-1])
    assert report.verdict == "inconclusive"
    assert report.missing_pairs == 1
    assert report.complete_pairs == 71


@pytest.mark.parametrize("attribute,value", [
    ("completed", False),
    ("host_scored", False),
])
def test_unverified_or_unfinished_run_cannot_be_paired(attribute, value):
    plan, rows = fixture_data()
    change(rows, case=plan.cases[0].case_id, **{attribute: value})
    report = compare_upgrade(plan, rows)
    assert report.verdict == "inconclusive"
    assert report.untrusted_pairs == 1
    assert report.complete_pairs == 71


def test_no_holdout_blocks_upgrade():
    plan, rows = fixture_data()
    assert compare_upgrade(replace(plan, heldout=False), rows).reason == (
        "independent_heldout_precommit_missing"
    )


def test_no_preregistration_blocks_upgrade():
    plan, rows = fixture_data()
    assert compare_upgrade(replace(plan, preregistered=False), rows).verdict == "inconclusive"


def test_unbalanced_order_blocks_cache_artifact():
    plan, rows = fixture_data()
    rows = [replace(row, order="AB") for row in rows]
    assert compare_upgrade(plan, rows).reason == "unbalanced_ab_ba_warmup_order"


def test_one_pair_order_mismatch_is_rejected():
    plan, rows = fixture_data()
    change(rows, case=plan.cases[0].case_id, order="BA")
    with pytest.raises(ValueError, match="presentation orders"):
        compare_upgrade(plan, rows)


def test_duplicate_variant_is_rejected_instead_of_best_of_many():
    plan, rows = fixture_data()
    with pytest.raises(ValueError, match="duplicate"):
        compare_upgrade(plan, rows + [rows[0]])


def test_new_unregistered_case_rejected():
    plan, rows = fixture_data()
    with pytest.raises(ValueError, match="pre-registered"):
        compare_upgrade(plan, rows + [replace(rows[0], case_id="extra")])


@pytest.mark.parametrize("change_field,change_value", [
    ("scorer_sha256", "f" * 64),
    ("environment_sha256", "f" * 64),
])
def test_cannot_switch_scorer_or_environment(change_field, change_value):
    plan, rows = fixture_data()
    change(rows, case=plan.cases[0].case_id,
           **{change_field: change_value})
    with pytest.raises(ValueError, match="environment or scorer"):
        compare_upgrade(plan, rows)


def test_safety_case_loss_vetoes_speed_even_with_other_gains():
    plan, rows = fixture_data()
    change(rows, case="safety-00", success=False)
    report = compare_upgrade(plan, rows)
    assert report.verdict == "regressed"
    assert report.reason == "safety_task_lost"


def test_safety_violation_vetoes_incomplete_suite():
    plan, rows = fixture_data()
    change(rows, case="safety-00", safety_violation=True)
    report = compare_upgrade(plan, rows[:2] + [r for r in rows if r.case_id == "safety-00"])
    assert report.verdict == "regressed"
    assert report.reason == "candidate_safety_violation"


def test_non_safety_accuracy_regression_vetoes_speed_gain():
    plan, rows = fixture_data()
    change(rows, case="general_knowledge-00", success=False)
    change(rows, case="general_knowledge-01", success=False)
    report = compare_upgrade(plan, rows)
    assert report.verdict == "regressed"
    assert report.reason == "category_accuracy_loss"
    assert report.mean_latency_gain_ms > 100


def test_low_absolute_quality_cannot_pass_even_if_both_models_fail():
    plan, rows = fixture_data()
    rows = [replace(row, success=False) for row in rows]
    report = compare_upgrade(plan, rows)
    assert report.reason == "quality_noninferiority_unproven"


def test_equal_latency_cannot_pass():
    plan, rows = fixture_data()
    rows = [replace(row, elapsed_ms=400) for row in rows]
    report = compare_upgrade(plan, rows)
    assert report.reason == "useful_speed_gain_unproven"


def test_measurable_but_too_small_improvement_not_qualified():
    plan, rows = fixture_data()
    rows = [replace(row, elapsed_ms=425) if row.variant == "candidate" else row
            for row in rows]
    assert compare_upgrade(plan, rows).verdict == "inconclusive"


def test_gpu_budget_vetoes_candidate():
    plan, rows = fixture_data()
    change(rows, case=plan.cases[0].case_id, gpu_peak_mib=6700)
    report = compare_upgrade(plan, rows)
    assert report.reason == "gpu_budget_exceeded"


def test_tail_latency_regression_vetoes_candidate():
    plan, rows = fixture_data()
    for i in range(7):
        change(rows, case=plan.cases[i].case_id, elapsed_ms=3000)
    report = compare_upgrade(plan, rows)
    assert report.reason == "tail_latency_regressed"


def test_strict_type_validation_blocks_nans_bools_and_bad_hashes():
    plan, rows = fixture_data()
    with pytest.raises(ValueError):
        UpgradeObservation("z", "candidate", "AB", ENV, SCORER,
                           True, float("nan"), 1, True, True, False)
    with pytest.raises(ValueError):
        replace(rows[0], success=1)
    with pytest.raises(ValueError):
        replace(rows[0], elapsed_ms=True)
    with pytest.raises(ValueError):
        replace(rows[0], scorer_sha256="https://example.com")
    with pytest.raises(ValueError):
        replace(rows[0], gpu_peak_mib=float("inf"))
    with pytest.raises(ValueError):
        replace(plan, baseline_sha256=CANDIDATE)
    with pytest.raises(ValueError):
        UpgradeCase("too/broad", "gameplay", ENV)


def test_observation_bound_blocks_unlimited_data():
    plan, rows = fixture_data()
    with pytest.raises(ValueError, match="bounded"):
        compare_upgrade(plan, rows * 9)


def test_duplicate_case_declaration_is_rejected():
    plan, _ = fixture_data()
    with pytest.raises(ValueError, match="duplicate"):
        replace(plan, cases=plan.cases + (plan.cases[0],))


def test_invalid_plan_and_configuration_rejected():
    plan, rows = fixture_data()
    with pytest.raises(TypeError):
        compare_upgrade("not a plan", rows)
    with pytest.raises(ValueError):
        compare_upgrade(plan, rows, min_pairs_per_category=0)
    with pytest.raises(ValueError):
        compare_upgrade(plan, rows, gpu_budget_mib=-1)
    with pytest.raises(ValueError):
        compare_upgrade(plan, rows, min_candidate_success=True)


def test_missing_category_stays_inconclusive_even_if_other_categories_pass():
    plan, rows = fixture_data()
    rows = [row for row in rows if not row.case_id.startswith("stream_dialogue-")]
    report = compare_upgrade(plan, rows)
    assert report.verdict == "inconclusive"
    assert report.missing_pairs == 12


def test_no_complete_pairs_never_upgrade():
    plan, _ = fixture_data()
    assert compare_upgrade(plan, []).reason == "no_complete_independently_scored_pairs"


def test_categories_are_all_required_no_weighting_out_weaknesses():
    plan, rows = fixture_data()
    assert set(CATEGORIES) == {
        "general_knowledge", "coding", "roblox_build",
        "gameplay", "stream_dialogue", "safety",
    }
    report = compare_upgrade(plan, rows)
    assert {section.category for section in report.categories} == set(CATEGORIES)
