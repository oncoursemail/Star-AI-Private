"""Deterministic, offline tests of prospective game forecast calibration.

Every truth label must be verified from GameplaySkillBank, not LLM confidence,
a caller-provided boolean, a replayed receipt, or a held-out validation run.
"""
from dataclasses import replace
import hashlib
import hmac
from pathlib import Path
import tempfile
import unittest

from star.game_prediction_lab import GameForecast, GamePredictionLab
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank

NOW = 1_782_500_000
PRACTICE = b"p" * 32
VALIDATION = b"v" * 32


class TestGamePredictionLab(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.lab = GamePredictionLab(self.bank)

    def tearDown(self):
        self.lab.close()
        self.bank.close()

    def forecast(self, run="run_1", *, bps=8000, when=NOW, **extra):
        return replace(GameForecast(
            "obby", "v1", "goal", "ledge", "jump", run,
            "star_v1", bps, when), **extra)

    def signed(self, run="run_1", *, outcome="success", split="practice",
               observed=NOW, action="jump", store=True):
        trial = GameTrial("trial_" + run, "obby", "v1", "goal", "ledge",
                          action, run, split, outcome, "a" * 64, observed)
        key = PRACTICE if split == "practice" else VALIDATION
        sig = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        if store:
            self.bank.ingest(trial, sig, now_unix_s=observed)
        return trial

    def test_default_off_and_explicit_opt_in(self):
        pred = self.forecast()
        self.assertFalse(self.lab.precommit(pred, now_unix_s=NOW))
        with self.assertRaises(PermissionError):
            self.lab.enable()
        self.lab.enable(owner_approved=True)
        self.assertTrue(self.lab.precommit(pred, now_unix_s=NOW))
        self.assertFalse(self.lab.precommit(pred, now_unix_s=NOW))
        self.assertEqual(self.lab.metrics()["duplicate"], 1)

    def test_precommitted_forecast_requires_exact_signed_ground_truth(self):
        self.lab.enable(owner_approved=True)
        self.assertTrue(self.lab.precommit(self.forecast(), now_unix_s=NOW))
        forged = self.signed(store=False)
        self.assertFalse(self.lab.resolve(forged, now_unix_s=NOW))
        self.assertEqual(self.lab.report("star_v1").trials, 0)
        real = self.signed()
        self.assertTrue(self.lab.resolve(real, now_unix_s=NOW))
        self.assertFalse(self.lab.resolve(real, now_unix_s=NOW))
        report = self.lab.report("star_v1", game_id="obby", game_version="v1")
        self.assertEqual(report.trials, 1)
        self.assertAlmostEqual(report.brier_score, .04)
        self.assertAlmostEqual(report.expected_calibration_error, .2)
        self.assertEqual(report.status, "diagnostic_only_small_sample")
        self.assertEqual(self.lab.metrics()["persisted_verified"], 1)

    def test_substitution_cannot_turn_signed_failure_into_success(self):
        self.lab.enable(owner_approved=True)
        self.lab.precommit(self.forecast(), now_unix_s=NOW)
        failed = self.signed(outcome="failure")
        forged = replace(failed, outcome="success")
        self.assertFalse(self.lab.resolve(forged, now_unix_s=NOW))
        self.assertEqual(self.lab.report("star_v1").trials, 0)
        self.assertTrue(self.lab.resolve(failed, now_unix_s=NOW))
        self.assertAlmostEqual(self.lab.report("star_v1").brier_score, .64)

    def test_wrong_scope_and_heldout_cannot_train_calibrator(self):
        self.lab.enable(owner_approved=True)
        self.lab.precommit(self.forecast(), now_unix_s=NOW)
        wrong = self.signed(action="crouch")
        self.assertFalse(self.lab.resolve(wrong, now_unix_s=NOW))
        self.assertEqual(self.lab.report("star_v1").trials, 0)
        self.assertFalse(self.lab.resolve(
            replace(wrong, split="validation"), now_unix_s=NOW))
        # Different true host-signed run can be used separately.
        self.lab.precommit(self.forecast("run_2"), now_unix_s=NOW)
        heldout = self.signed("run_2", split="validation")
        self.assertFalse(self.lab.resolve(heldout, now_unix_s=NOW))
        self.assertEqual(self.lab.report("star_v1").trials, 0)

    def test_cannot_precommit_after_signed_outcome(self):
        self.lab.enable(owner_approved=True)
        self.signed("run_1")
        self.assertFalse(self.lab.precommit(self.forecast(), now_unix_s=NOW))
        self.assertEqual(self.lab.metrics()["committed"], 0)

    def test_invalid_probabilities_and_timestamps_are_rejected(self):
        for bps in (0, 10000, -1, True, 200.7, float("nan"), "8000"):
            with self.subTest(bps=bps), self.assertRaises(ValueError):
                self.forecast(bps=bps)
        with self.assertRaises(ValueError):
            self.forecast(model_id="../outside")
        self.lab.enable(owner_approved=True)
        self.assertFalse(self.lab.precommit(
            self.forecast(when=NOW - 2), now_unix_s=NOW))
        self.assertFalse(self.lab.precommit(
            self.forecast(when=NOW + 2), now_unix_s=NOW))
        self.assertFalse(self.lab.precommit(
            self.forecast(when=NOW), now_unix_s=NOW + 2))

    def test_stale_results_and_time_travel_cannot_update(self):
        self.lab.enable(owner_approved=True)
        self.lab.precommit(self.forecast(), now_unix_s=NOW)
        trial = self.signed(observed=NOW)
        self.assertFalse(self.lab.resolve(trial, now_unix_s=NOW + 181))
        self.assertFalse(self.lab.resolve(trial, now_unix_s=NOW + 182))
        self.assertEqual(self.lab.report("star_v1").trials, 0)

    def test_disable_cancels_pending_and_does_not_replay(self):
        self.lab.enable(owner_approved=True)
        self.lab.precommit(self.forecast(), now_unix_s=NOW)
        self.lab.disable()
        self.assertEqual(self.lab.metrics()["pending"], 0)
        self.lab.enable(owner_approved=True)
        self.assertFalse(self.lab.precommit(self.forecast(), now_unix_s=NOW))
        self.assertFalse(self.lab.resolve(self.signed(), now_unix_s=NOW))
        self.assertEqual(self.lab.report("star_v1").trials, 0)

    def test_cancelled_run_id_is_irreversible(self):
        self.lab.enable(owner_approved=True)
        self.lab.precommit(self.forecast(), now_unix_s=NOW)
        self.assertTrue(self.lab.cancel("run_1"))
        self.assertFalse(self.lab.cancel("run_1"))
        self.assertFalse(self.lab.precommit(self.forecast(), now_unix_s=NOW))
        self.assertFalse(self.lab.resolve(self.signed(), now_unix_s=NOW))

    def test_bounded_inflight_predictions(self):
        self.lab.enable(owner_approved=True)
        for i in range(64):
            self.assertTrue(self.lab.precommit(
                self.forecast("run_" + str(i)), now_unix_s=NOW))
        self.assertFalse(self.lab.precommit(
            self.forecast("run_over_limit"), now_unix_s=NOW))
        self.assertEqual(self.lab.metrics()["pending"], 64)

    def test_prospective_overconfidence_is_visible_without_claiming_mastery(self):
        self.lab.enable(owner_approved=True)
        for i in range(25):
            run = "attempt_" + str(i)
            self.assertTrue(self.lab.precommit(
                self.forecast(run, bps=9000), now_unix_s=NOW))
            outcome = self.signed(run, outcome="failure")
            self.assertTrue(self.lab.resolve(outcome, now_unix_s=NOW))
        rep = self.lab.report("star_v1", game_id="obby", game_version="v1")
        self.assertEqual(rep.status, "prospective_diagnostic")
        self.assertEqual(rep.trials, 25)
        self.assertAlmostEqual(rep.brier_score, .81)
        self.assertAlmostEqual(rep.expected_calibration_error, .9)
        advice = self.lab.advise(
            "star_v1", game_id="obby", game_version="v1", proposed_bps=9000)
        self.assertEqual(advice.status, "reviewable_calibration")
        self.assertEqual(advice.calibrated_success_bps, round(10000 * 2 / 29))
        self.assertFalse(advice.authorized_to_play)
        self.assertEqual(advice.bucket_trials, 25)
        self.assertEqual(self.lab.report("another_model").trials, 0)
        self.assertEqual(self.lab.report("star_v1", game_id="race").trials, 0)

    def test_insufficient_samples_and_untested_bucket_are_not_confidence(self):
        self.lab.enable(owner_approved=True)
        self.assertEqual(self.lab.advise(
            "star_v1", game_id="obby", game_version="v1",
            proposed_bps=8000).status, "insufficient_evidence")
        for i in range(20):
            run = "s_" + str(i)
            self.lab.precommit(self.forecast(run, bps=5000), now_unix_s=NOW)
            self.lab.resolve(self.signed(run), now_unix_s=NOW)
        self.assertEqual(self.lab.advise(
            "star_v1", game_id="obby", game_version="v1",
            proposed_bps=9000).status, "uncertain_probability_bucket")

    def test_persistent_offline_forecasts_survive_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "forecast.sqlite"
            with GamePredictionLab(self.bank, db) as first:
                first.enable(owner_approved=True)
                self.assertTrue(first.precommit(self.forecast(), now_unix_s=NOW))
                self.assertTrue(first.resolve(self.signed(), now_unix_s=NOW))
            with GamePredictionLab(self.bank, db) as second:
                # Reading a previous verified report needs no new permission,
                # but accepting new predictions still does.
                self.assertEqual(second.report("star_v1").trials, 1)
                self.assertFalse(second.precommit(
                    self.forecast("new_run"), now_unix_s=NOW))
                second.enable(owner_approved=True)
                self.assertFalse(second.precommit(self.forecast(), now_unix_s=NOW))
                self.assertEqual(second.metrics()["persisted_verified"], 1)

    def test_invalid_database_location_and_report_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            symlink = Path(tmp) / "linked"
            symlink.symlink_to(tmp, target_is_directory=True)
            with self.assertRaises(ValueError):
                GamePredictionLab(self.bank, symlink / "new.sqlite")
        with self.assertRaises(ValueError):
            self.lab.report("star_v1", game_version="v1")
        with self.assertRaises(ValueError):
            self.lab.advise("star_v1", game_id="obby", game_version="v1",
                            proposed_bps=True)


if __name__ == "__main__":
    unittest.main()
