"""Offline holdout-gate tests, with synthetic trials (no real game has been played)."""
import pytest
from star.streamer_skill_eval import GameplayTrial, compare_policies


def data(success_b=False, success_c=True, safety_b=0, safety_c=0):
    baseline, candidate = [], []
    for i in range(30):
        task = f"level{i % 5}"
        baseline.append(GameplayTrial(task, i, success_b, safety_b, f"b-{i}"))
        candidate.append(GameplayTrial(task, i, success_c, safety_c, f"c-{i}"))
    return baseline, candidate


def test_well_supported_holdout_gain_recommends_review_not_approval():
    b, c = data()
    result = compare_policies(b, c)
    assert result.recommend_human_review
    assert result.gained == 30 and result.lost == 0
    assert result.mcnemar_two_sided_p < 0.05
    assert "not automatically approved" in result.reason


def test_same_policy_no_illusory_gain():
    b, c = data(success_b=True, success_c=True)
    result = compare_policies(b, c)
    assert not result.recommend_human_review
    assert result.mcnemar_two_sided_p == 1


def test_safety_regression_blocks_candidate_even_if_success_higher():
    b, c = data(safety_c=1)
    assert not compare_policies(b, c).recommend_human_review
    assert "safety" in compare_policies(b, c).reason


def test_holdout_mismatch_and_duplicates_cannot_pass():
    b, c = data()
    with pytest.raises(ValueError, match="paired"):
        compare_policies(b, c[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        compare_policies(b + b[:1], c)
    with pytest.raises(ValueError, match="holdout"):
        compare_policies(b, [GameplayTrial(t.task_id, t.seed, t.success, 0, t.evidence_id, "train") for t in c])


def test_missing_independent_evidence_cannot_pass():
    b, c = data()
    c[0] = GameplayTrial(c[0].task_id, c[0].seed, True, 0, b[0].evidence_id)
    with pytest.raises(ValueError, match="independent"):
        compare_policies(b, c)


def test_need_three_tasks_and_20_trials():
    b, c = data()
    with pytest.raises(ValueError, match="three"):
        compare_policies([GameplayTrial("same", i, False, 0, f"b{i}") for i in range(30)],
                         [GameplayTrial("same", i, True, 0, f"c{i}") for i in range(30)])
    with pytest.raises(ValueError, match="20"):
        compare_policies(b[:19], c[:19])


def test_invalid_outcome_and_duplicate_evidence_rejected():
    b, c = data()
    b[0] = GameplayTrial("level0", 0, 1, 0, "b-0")
    with pytest.raises(ValueError, match="observed"):
        compare_policies(b, c)
