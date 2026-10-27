"""Deterministic, independently signed OFFLINE game foresight review tests.

No Roblox input, model API, internet, streams, or evaluation secrets involved.
Fixtures emulate a trusted local game scorer; these are NOT proof of mastery.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import tempfile
import unittest

from star.game_prediction_lab import GameForecast, GamePredictionLab
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank

NOW = 1_782_500_000
PRACTICE_KEY = b"practice_evaluator_test_key_00000001"
VALIDATION_KEY = b"heldout_evaluator_test_key_00000001"


class TestContextualGameForesight(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(
            practice_key=PRACTICE_KEY, validation_key=VALIDATION_KEY,
        )
        self.lab = GamePredictionLab(self.bank)
        self.lab.enable(owner_approved=True)

    def tearDown(self):
        self.lab.close()
        self.bank.close()

    def record(self, name, *, objective="goal", situation="ledge",
               action="jump", game="obby", version="v1", model="star_v1",
               bps=9000, outcome="failure", at=NOW, split="practice"):
        run = "run_" + name
        forecast = GameForecast(
            game, version, objective, situation, action, run, model, bps, at,
        )
        self.assertTrue(self.lab.precommit(forecast, now_unix_s=at))
        trial = GameTrial(
            "trial_" + name, game, version, objective, situation, action,
            run, split, outcome, "0" * 64, at,
        )
        key = PRACTICE_KEY if split == "practice" else VALIDATION_KEY
        receipt = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, receipt, now_unix_s=at)
        return self.lab.resolve(trial, now_unix_s=at)

    def context(self, **kwargs):
        args = dict(
            game_id="obby", game_version="v1",
            objective_id="goal", situation_id="ledge",
            action_id="jump", proposed_bps=9000, now_unix_s=NOW,
        )
        args.update(kwargs)
        return self.lab.contextual_advice("star_v1", **args)

    def test_separates_distinct_actions_even_inside_same_game_and_bucket(self):
        for i in range(20):
            self.assertTrue(self.record("jump_" + str(i)))
            self.assertTrue(self.record(
                "crouch_" + str(i), action="crouch", outcome="success",
            ))
        jump = self.context()
        crouch = self.context(action_id="crouch")
        self.assertEqual(jump.status, "reviewable_context_calibration")
        self.assertEqual(jump.calibrated_success_bps, round(10000 * 2 / 24))
        self.assertEqual(crouch.calibrated_success_bps, round(10000 * 22 / 24))
        self.assertEqual(jump.bucket_trials, 20)
        self.assertEqual(crouch.bucket_trials, 20)
        self.assertFalse(jump.authorized_to_play)
        self.assertNotEqual(
            self.lab.advise("star_v1", game_id="obby", game_version="v1",
                            proposed_bps=9000).calibrated_success_bps,
            jump.calibrated_success_bps,
        )

    def test_separates_objectives_situations_versions_games_and_model_builds(self):
        variants = [
            dict(objective="boss"), dict(situation="gap"),
            dict(game="racing"), dict(version="v2"), dict(model="star_v2"),
        ]
        for j, variant in enumerate(variants):
            for i in range(20):
                self.assertTrue(self.record(
                    f"other_{j}_{i}", outcome="success", **variant,
                ))
        self.assertEqual(self.context().status, "insufficient_context_evidence")
        for j, variant in enumerate(variants):
            args = {
                "objective": "objective_id", "situation": "situation_id",
                "game": "game_id", "version": "game_version",
                "model": None,
            }
            kw = {args[k]: v for k, v in variant.items() if args[k] is not None}
            if "model" in variant:
                result = self.lab.contextual_advice(
                    variant["model"], game_id="obby", game_version="v1",
                    objective_id="goal", situation_id="ledge",
                    action_id="jump", proposed_bps=9000, now_unix_s=NOW,
                )
            else:
                result = self.context(**kw)
            self.assertEqual(result.bucket_trials, 20, (j, result))
            self.assertEqual(result.status, "reviewable_context_calibration")

    def test_insufficient_sample_and_wrong_probability_bucket(self):
        for i in range(19):
            self.record(str(i), bps=5000, outcome="success")
        self.assertEqual(
            self.context(proposed_bps=5000).status, "insufficient_context_evidence",
        )
        self.record("twentieth", bps=5000, outcome="success")
        uncertain = self.context(proposed_bps=9000)
        self.assertEqual(uncertain.status, "uncertain_context_probability_bucket")
        self.assertEqual(uncertain.bucket_trials, 0)
        self.assertIsNone(uncertain.calibrated_success_bps)

    def test_small_bucket_not_promoted_by_unrelated_large_bucket(self):
        for i in range(20):
            self.record(str(i), bps=5000)
        for i in range(7):
            self.record("high_" + str(i), bps=9000)
        self.assertEqual(self.context().bucket_trials, 7)
        self.assertEqual(
            self.context().status, "uncertain_context_probability_bucket",
        )

    def test_distribution_shift_detects_new_failures_after_old_successes(self):
        for i in range(24):
            self.record(
                str(i), outcome="success" if i < 12 else "failure",
                at=NOW + i,
            )
        advice = self.context(now_unix_s=NOW + 24)
        self.assertEqual(advice.status, "practice_distribution_shift")
        self.assertIsNone(advice.calibrated_success_bps)
        self.assertEqual(advice.bucket_trials, 24)

    def test_stable_action_keeps_non_authoritative_calibration(self):
        for i in range(25):
            self.record(str(i), outcome="success", at=NOW + i)
        advice = self.context(now_unix_s=NOW + 26)
        self.assertEqual(advice.status, "reviewable_context_calibration")
        self.assertEqual(advice.calibrated_success_bps, round(10000 * 27 / 29))
        self.assertFalse(advice.authorized_to_play)

    def test_future_results_and_expired_history_are_not_training_context(self):
        for i in range(20):
            self.record(str(i), at=NOW + i)
        self.assertEqual(
            self.context(now_unix_s=NOW - 2).bucket_trials, 0,
        )
        self.assertEqual(
            self.context(now_unix_s=NOW + 14 * 86400 + 20).bucket_trials, 0,
        )

    def test_heldout_outcome_never_enters_context_or_focus(self):
        for i in range(20):
            self.assertFalse(self.record(
                str(i), split="validation", outcome="success",
            ))
        self.assertEqual(self.context().bucket_trials, 0)
        self.assertEqual(
            self.lab.focus_suggestions(
                "star_v1", game_id="obby", game_version="v1", now_unix_s=NOW,
            ), (),
        )

    def test_focus_prioritizes_overconfidence_and_underestimation(self):
        for i in range(20):
            self.record("hard_" + str(i), objective="cliff", bps=9000)
            self.record(
                "easy_" + str(i), objective="start",
                bps=1000, outcome="success",
            )
            self.record(
                "accurate_" + str(i), objective="routine",
                bps=9000, outcome="success",
            )
        focus = self.lab.focus_suggestions(
            "star_v1", game_id="obby", game_version="v1",
            now_unix_s=NOW, limit=5,
        )
        self.assertEqual(len(focus), 2)
        self.assertEqual(
            {f.finding for f in focus},
            {"overconfident_failures", "underestimated_successes"},
        )
        self.assertEqual({f.objective_id for f in focus}, {"cliff", "start"})
        self.assertTrue(all(not f.authorized_to_play for f in focus))
        self.assertTrue(all(f.trials == 20 for f in focus))
        self.assertTrue(all(f.brier_score >= .8 for f in focus))

    def test_sparse_focus_needs_independent_practice_evidence(self):
        for i in range(7):
            self.record(str(i), outcome="failure")
        self.assertEqual(
            self.lab.focus_suggestions(
                "star_v1", game_id="obby", game_version="v1", now_unix_s=NOW,
            ), (),
        )

    def test_focus_bounded_and_deterministic_sort(self):
        for j in range(4):
            for i in range(8):
                self.record(f"g{j}_{i}", objective=f"o{j}")
        args = dict(game_id="obby", game_version="v1", now_unix_s=NOW, limit=2)
        a = self.lab.focus_suggestions("star_v1", **args)
        b = self.lab.focus_suggestions("star_v1", **args)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 2)
        self.assertEqual([f.objective_id for f in a], ["o0", "o1"])

    def test_scope_validation_rejects_untrusted_input(self):
        for data in (
            dict(proposed_bps=True), dict(proposed_bps="9000"),
            dict(proposed_bps=10000), dict(now_unix_s=True),
            dict(objective_id="../secret"), dict(action_id="hello world"),
            dict(model_id=".."),
        ):
            if "model_id" in data:
                with self.assertRaises(ValueError):
                    self.lab.contextual_advice(
                        data["model_id"], game_id="obby", game_version="v1",
                        objective_id="goal", situation_id="ledge", action_id="jump",
                        proposed_bps=9000, now_unix_s=NOW,
                    )
            else:
                with self.assertRaises(ValueError):
                    self.context(**data)
        for value in (True, 0, 7, 100, "8"):
            with self.assertRaises(ValueError):
                self.lab.focus_suggestions(
                    "star_v1", game_id="obby", game_version="v1",
                    now_unix_s=NOW, minimum_trials=value,
                )
        with self.assertRaises(ValueError):
            self.lab.focus_suggestions(
                "star_v1", game_id="obby", game_version="v1",
                now_unix_s=NOW, limit=11,
            )

    def test_persisted_verified_forecasts_remain_scoped_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "prior.sqlite"
            with GamePredictionLab(self.bank, db) as initial:
                initial.enable(owner_approved=True)
                for i in range(20):
                    run = "restart_" + str(i)
                    pred = GameForecast(
                        "obby", "v1", "goal", "ledge", "jump",
                        run, "star_v1", 9000, NOW,
                    )
                    self.assertTrue(initial.precommit(pred, now_unix_s=NOW))
                    trial = GameTrial(
                        "trial_" + run, "obby", "v1", "goal", "ledge",
                        "jump", run, "practice", "failure", "0" * 64, NOW,
                    )
                    sig = hmac.new(
                        PRACTICE_KEY, trial.canonical_bytes(), hashlib.sha256,
                    ).hexdigest()
                    self.bank.ingest(trial, sig, now_unix_s=NOW)
                    self.assertTrue(initial.resolve(trial, now_unix_s=NOW))
            with GamePredictionLab(self.bank, db) as reopened:
                # Reads are permitted; writes remain OFF after restart.
                result = reopened.contextual_advice(
                    "star_v1", game_id="obby", game_version="v1",
                    objective_id="goal", situation_id="ledge", action_id="jump",
                    proposed_bps=9000, now_unix_s=NOW,
                )
                self.assertEqual(
                    result.status, "reviewable_context_calibration",
                )
                self.assertFalse(reopened.metrics()["enabled"])


if __name__ == "__main__":
    unittest.main()
