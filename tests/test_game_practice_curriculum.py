"""Deterministic practice-only self-play curriculum safety and progression tests."""
from __future__ import annotations

from dataclasses import dataclass
import pytest

from star.game_practice_curriculum import PracticeTarget, recommend_practice


NOW = 1_798_000_000


@dataclass(frozen=True)
class PracticeAggregate:
    action_id: str
    trials: int
    successes: int
    most_recent_unix_s: int = NOW - 30


class EvidenceBank:
    def __init__(self, data=None):
        self.data = data or {}
        self.calls = []

    def practice_evidence(self, game_id, game_version, objective_id, situation_id, *, now_unix_s, max_age_s):
        self.calls.append((game_id, game_version, objective_id, situation_id, now_unix_s, max_age_s))
        return tuple(self.data.get(situation_id, ()))


def target(situation="map_1", action="jump", difficulty=1):
    return PracticeTarget("obby", "v3", "jump_timing", situation, action, difficulty)


def plan(bank, *targets, **opts):
    return recommend_practice(bank, targets=targets, now_unix_s=NOW, owner_approved=True, **opts)


def test_default_off_and_never_reads_bank_without_opt_in():
    bank = EvidenceBank()
    advice = recommend_practice(bank, targets=(target(),), now_unix_s=NOW)
    assert advice.status == "disabled" and advice.target is None
    assert not advice.authorized_to_play and not advice.heldout_evaluated
    assert bank.calls == []


def test_new_challenges_start_at_easiest_and_are_only_advisory():
    advice = plan(EvidenceBank(), target("hard", difficulty=4), target("easy", difficulty=1))
    assert advice.target.situation_id == "easy"
    assert advice.status == "rehearse"
    assert advice.reason == "lowest_unmastered_difficulty"
    assert not advice.authorized_to_play


def test_higher_tier_unlocks_only_after_every_lower_situation_is_ready():
    bank = EvidenceBank({"a": (PracticeAggregate("jump", 12, 12),),
                         "b": (PracticeAggregate("jump", 6, 6),)})
    advice = plan(bank, target("a"), target("b"), target("advanced", difficulty=2))
    assert advice.target.situation_id == "b"   # insufficient sample count
    bank.data["b"] = (PracticeAggregate("jump", 12, 12),)
    advice = plan(bank, target("a"), target("b"), target("advanced", difficulty=2))
    assert advice.target.situation_id == "advanced"


def test_failure_heavy_lower_tier_blocks_harder_tasks():
    bank = EvidenceBank({"weak": (PracticeAggregate("jump", 12, 6),),
                         "strong": (PracticeAggregate("jump", 12, 12),)})
    advice = plan(bank, target("strong"), target("weak"), target("boss", difficulty=5))
    assert advice.target.situation_id == "weak"


def test_cold_scenarios_rank_before_overpracticed_ones():
    bank = EvidenceBank({"seen": (PracticeAggregate("jump", 7, 1),)})
    assert plan(bank, target("seen"), target("cold")).target.situation_id == "cold"


def test_review_required_after_bounded_unsuccessful_self_play():
    bank = EvidenceBank({"a": (PracticeAggregate("jump", 41, 1),)})
    advice = plan(bank, target("a"), target("new"), target("hard", difficulty=2))
    assert advice.status == "review_required"
    assert advice.target.situation_id == "a"
    assert not advice.authorized_to_play


def test_stale_signed_lifetime_wins_cannot_unlock_new_difficulty():
    old = NOW - (8 * 24 * 3600)
    bank = EvidenceBank({"easy": (PracticeAggregate("jump", 20, 20, old),)})
    advice = plan(bank, target("easy"), target("boss", difficulty=5))
    assert advice.status == "review_required"
    assert advice.target.situation_id == "easy"
    assert advice.reason == "practice_evidence_stale_requires_fresh_assessment"
    assert advice.trials == 20 and advice.successes == 20
    assert not advice.authorized_to_play and not advice.heldout_evaluated


def test_fresh_retention_evidence_allows_progress_and_staleness_boundary():
    day = 24 * 3600
    bank = EvidenceBank({"easy": (PracticeAggregate("jump", 20, 20, NOW - 7 * day),)})
    advice = plan(bank, target("easy"), target("boss", difficulty=2))
    assert advice.status == "rehearse"
    assert advice.target.situation_id == "boss"
    bank.data["easy"] = (PracticeAggregate("jump", 20, 20, NOW - 7 * day - 1),)
    assert plan(bank, target("easy"), target("boss", difficulty=2)).status == "review_required"


def test_missing_evidence_is_not_misclassified_as_expired():
    advice = plan(EvidenceBank(), target("unseen"))
    assert advice.status == "rehearse"
    assert advice.reason == "lowest_unmastered_difficulty"


def test_expiration_budget_requires_bounded_integer():
    for invalid in (True, 0, -1, 30.1, 60 * 60 * 24 * 31):
        with pytest.raises(ValueError):
            plan(EvidenceBank(), target(), max_evidence_age_s=invalid)


def test_complete_is_not_model_promotion_or_holdout_evaluation():
    bank = EvidenceBank({"map_1": (PracticeAggregate("jump", 20, 20),)})
    advice = plan(bank, target())
    assert advice.status == "complete" and advice.target is None
    assert not advice.heldout_evaluated and not advice.authorized_to_play


def test_target_scope_is_separate_and_no_mixed_games():
    bank = EvidenceBank()
    alien = PracticeTarget("other", "v3", "jump_timing", "map_1", "jump", 1)
    with pytest.raises(ValueError):
        plan(bank, target(), alien)
    assert bank.calls == []


def test_duplicate_and_contradictory_difficulty_rejected_without_bank_io():
    bank = EvidenceBank()
    with pytest.raises(ValueError):
        plan(bank, target(), target())
    with pytest.raises(ValueError):
        plan(bank, target(difficulty=1), target(action="dash", difficulty=2))
    assert bank.calls == []


def test_verified_practice_scope_is_looked_up_once_per_situation():
    bank = EvidenceBank()
    plan(bank, target(action="jump"), target(action="dash"))
    assert len(bank.calls) == 1
    assert bank.calls[0][-1] == 7 * 24 * 3600


@pytest.mark.parametrize("bad", [
    PracticeAggregate("jump", True, 1),
    PracticeAggregate("jump", 2, 3),
    PracticeAggregate("jump", 2, 1, NOW + 20),
    PracticeAggregate("jump", 0, 0),
])
def test_malformed_practice_aggregates_fail_closed(bad):
    bank = EvidenceBank({"map_1": (bad,)})
    with pytest.raises(ValueError):
        plan(bank, target())


def test_duplicate_bank_records_fail_closed():
    row = PracticeAggregate("jump", 2, 1)
    with pytest.raises(ValueError):
        plan(EvidenceBank({"map_1": (row, row)}), target())


def test_bank_integrity_error_propagates_instead_of_training():
    class CorruptBank:
        def practice_evidence(self, *args, **kwargs):
            raise RuntimeError("invalid independent practice receipt")
    with pytest.raises(RuntimeError):
        plan(CorruptBank(), target())


def test_canonical_ids_and_parameter_bounds():
    for invalid in ("", "bad name", "../../", "x" * 65):
        with pytest.raises(ValueError):
            PracticeTarget(invalid, "v1", "objective", "map", "jump", 1)
    with pytest.raises(ValueError):
        target(difficulty=True)
    with pytest.raises(ValueError):
        plan(EvidenceBank(), target(), min_trials=3)
    with pytest.raises(ValueError):
        plan(EvidenceBank(), target(), minimum_lower_bound=float("nan"))
    with pytest.raises(ValueError):
        plan(EvidenceBank(), *[target(f"map{i}") for i in range(65)])


def test_no_targets_and_configuration_validation():
    assert plan(EvidenceBank()).status == "no_targets"
    with pytest.raises(ValueError):
        plan(EvidenceBank(), target(), max_trials_before_review=5)
