"""Offline checks for independent heldout skill reports; no AI-game claims."""
import unittest

from star.game_skill_promotion import SkillPromotionGate, SkillTrial


def trial(i=1, *, game="obby", skill="jump", revision="v1", session=None,
          environment="world1", split="holdout", passed=True, unsafe=False,
          scenario=None):
    return SkillTrial(game, skill, revision, str(i) if session is None else session,
                      environment, f"{i:064x}" if scenario is None else scenario,
                      split, passed, unsafe)


class SkillPromotionTests(unittest.TestCase):
    def setUp(self):
        self.g = SkillPromotionGate(min_holdout=12, min_environments=3,
                                    minimum_lower=0.5)

    def record(self, row):
        return self.g.record(row, trusted_host=True)

    def fill(self, n=32, split="holdout", bad=0, revision="v1"):
        for i in range(1, n + 1):
            self.record(trial(i, environment=f"world{i % 4}", split=split,
                              passed=i > bad, revision=revision))

    def test_empty_is_not_ready(self):
        self.assertEqual(self.g.report("obby", "jump", "v1").status,
                         "insufficient_holdout")

    def test_host_only(self):
        with self.assertRaises(PermissionError):
            self.g.record(trial())

    def test_distinct_heldout_can_reach_review(self):
        self.fill(32)
        r = self.g.report("obby", "jump", "v1")
        self.assertEqual(r.status, "ready_for_owner_review")
        self.assertEqual((r.holdout_sessions, r.passed, r.environments), (32, 32, 4))

    def test_training_only_cannot_promote(self):
        self.fill(32, split="practice")
        self.assertEqual(self.g.report("obby", "jump", "v1").status,
                         "insufficient_holdout")

    def test_cross_split_replay_detected(self):
        self.record(trial(1, split="practice"))
        with self.assertRaises(ValueError):
            self.record(trial(2, scenario=f"{1:064x}", split="holdout"))

    def test_one_session_cannot_inflate_results(self):
        self.record(trial(1))
        with self.assertRaises(ValueError):
            self.record(trial(2, session="1"))

    def test_one_environment_cannot_claim_transfer(self):
        for i in range(1, 33):
            self.record(trial(i, environment="same"))
        self.assertEqual(self.g.report("obby", "jump", "v1").status,
                         "insufficient_transfer_coverage")

    def test_low_success_stays_below_gate(self):
        self.fill(32, bad=24)
        self.assertEqual(self.g.report("obby", "jump", "v1").status,
                         "below_reliability_gate")

    def test_unsafe_trial_vetoes_all_other_success(self):
        self.fill(32)
        self.record(trial(33, passed=False, unsafe=True, split="practice"))
        self.assertEqual(self.g.report("obby", "jump", "v1").status,
                         "unsafe_veto")

    def test_revision_must_be_revalidated(self):
        self.fill(32, revision="v1")
        self.assertEqual(self.g.report("obby", "jump", "v2").status,
                         "insufficient_holdout")

    def test_other_skill_is_separate(self):
        self.fill(32)
        self.assertEqual(self.g.report("obby", "dash", "v1").holdout_sessions, 0)

    def test_new_revision_cannot_reuse_scenario_id(self):
        self.record(trial(1))
        with self.assertRaises(ValueError):
            self.record(trial(1, revision="v2"))
        self.assertEqual(self.g.summary()["trials"], 1)

    def test_replay_not_mutate_count(self):
        self.record(trial())
        with self.assertRaises(ValueError):
            self.record(trial())
        self.assertEqual(self.g.summary()["trials"], 1)

    def test_capacity(self):
        gate = SkillPromotionGate(max_trials=1)
        gate.record(trial(1), trusted_host=True)
        with self.assertRaises(OverflowError):
            gate.record(trial(2), trusted_host=True)

    def test_bool_validation(self):
        for kw in ({"passed": 1}, {"unsafe": 0}, {"passed": True, "unsafe": True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                trial(**kw)

    def test_split_validation(self):
        with self.assertRaises(ValueError):
            trial(split="fake")

    def test_scenario_digest_validation(self):
        for bad in ("0123", "G" * 64):
            with self.assertRaises(ValueError):
                trial(scenario=bad)

    def test_name_validation(self):
        with self.assertRaises(ValueError):
            trial(skill="../../pwn")

    def test_parameter_validation(self):
        for kw in ({"min_holdout": 4}, {"min_environments": 1},
                   {"minimum_lower": float("nan")}, {"minimum_lower": True},
                   {"max_trials": 0}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                SkillPromotionGate(**kw)

    def test_report_scope_validation(self):
        with self.assertRaises(ValueError):
            self.g.report("bad/slash", "jump", "v1")

    def test_summary_metadata_only(self):
        self.record(trial())
        self.assertEqual(self.g.summary(), {"trials": 1,
                                           "holdout_trials": 1,
                                           "distinct_skills": 1})


if __name__ == "__main__":
    unittest.main()
