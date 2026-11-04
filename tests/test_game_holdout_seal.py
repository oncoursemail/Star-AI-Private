"""Adversarial offline tests: a model cannot mint or rewrite a holdout seal."""
from dataclasses import replace
import hashlib
import hmac
import unittest

from star.game_holdout_seal import GameHoldoutPrecommit, evaluate_precommitted_transfer
from star.game_transfer_eval import HoldoutCase, SignedHoldoutTrial, roster_digest
from star.gameplay_skill_bank import GameTrial

COORDINATOR = b"c" * 32
EVALUATOR = b"e" * 32
NOW = 2_000_000_000
BASE_REV = hashlib.sha256(b"frozen-base").hexdigest()
CAND_REV = hashlib.sha256(b"frozen-candidate").hexdigest()


class GameHoldoutSealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = []
        self.signed = []
        for game in range(5):
            for seed in range(10):
                case = HoldoutCase(f"game{game}", "v2", "complete", f"unseen{seed}")
                self.cases.append(case)
                for action, outcome in (("baseline", "failure"), ("candidate", "success")):
                    trial = GameTrial(
                        f"t{game}_{seed}_{action}", case.game_id, case.game_version,
                        case.objective_id, case.situation_id, action,
                        f"run{game}_{seed}_{action}", "validation", outcome,
                        hashlib.sha256(f"capture:{game}:{seed}:{action}".encode()).hexdigest(),
                        NOW - 5,
                    )
                    receipt = hmac.new(EVALUATOR, trial.canonical_bytes(),
                                       hashlib.sha256).hexdigest()
                    self.signed.append(SignedHoldoutTrial(trial, receipt))
        self.seal = GameHoldoutPrecommit(
            "campaign_42", roster_digest(self.cases), "baseline", "candidate",
            BASE_REV, CAND_REV, NOW - 600, NOW + 3600,
        )

    def sign(self, seal=None, *, key=COORDINATOR):
        return hmac.new(
            key, (seal or self.seal).canonical_bytes(), hashlib.sha256
        ).hexdigest()

    def check(self, *, seal=None, signed=None, cases=None, **overrides):
        opts = dict(
            seal_receipt=self.sign(seal),
            coordinator_key=COORDINATOR,
            validation_key=EVALUATOR,
            expected_evaluation_id="campaign_42",
            observed_baseline_revision_sha256=BASE_REV,
            observed_candidate_revision_sha256=CAND_REV,
            cases=self.cases if cases is None else cases,
            signed_trials=self.signed if signed is None else signed,
            now_unix_s=NOW,
        )
        opts.update(overrides)
        return evaluate_precommitted_transfer(seal or self.seal, **opts)

    def test_good_seal_produces_manual_pilot_eligibility_not_authority(self):
        result = self.check()
        self.assertEqual(result.verdict, "eligible_for_owner_pilot")
        self.assertEqual(result.completed_pairs, 50)
        self.assertFalse(hasattr(result, "authorized_to_play"))

    def test_incomplete_pair_is_not_promoted(self):
        result = self.check(signed=self.signed[:-1])
        self.assertEqual(result.verdict, "inconclusive")
        self.assertIsNone(result.candidate_success_rate)

    def test_changed_roster_even_same_size_rejected(self):
        changed = list(self.cases)
        changed[0] = replace(changed[0], situation_id="replaced")
        with self.assertRaises(PermissionError):
            self.check(cases=changed)

    def test_seal_signature_required_and_not_mintable_with_evaluator_key(self):
        bad_receipts = ["", "0" * 64, "A" * 64, self.sign(key=EVALUATOR)]
        for receipt in bad_receipts:
            with self.subTest(receipt=receipt[:8]), self.assertRaises(PermissionError):
                self.check(seal_receipt=receipt)
        with self.assertRaises(ValueError):
            self.check(coordinator_key=EVALUATOR)
        with self.assertRaises(ValueError):
            self.check(coordinator_key=b"short")
        with self.assertRaises(ValueError):
            self.check(validation_key=b"short")

    def test_same_signature_cannot_authorize_changed_seal(self):
        altered = replace(self.seal, expires_unix_s=self.seal.expires_unix_s + 1)
        with self.assertRaises(PermissionError):
            self.check(seal=altered, seal_receipt=self.sign())

    def test_model_revision_binding_rejects_swapped_or_faked_policy(self):
        for field, bad in (
            ("observed_baseline_revision_sha256", CAND_REV),
            ("observed_candidate_revision_sha256", BASE_REV),
            ("observed_candidate_revision_sha256", "A" * 64),
        ):
            with self.subTest(field=field), self.assertRaises(
                (PermissionError, ValueError)
            ):
                self.check(**{field: bad})

    def test_campaign_identity_cannot_be_reused_across_owners(self):
        with self.assertRaises(PermissionError):
            self.check(expected_evaluation_id="campaign_43")

    def test_observation_before_or_at_seal_is_invalid_even_if_signed(self):
        for ts in (self.seal.sealed_unix_s - 1, self.seal.sealed_unix_s):
            changed = replace(self.signed[0].trial, observed_unix_s=ts)
            signature = hmac.new(EVALUATOR, changed.canonical_bytes(),
                                 hashlib.sha256).hexdigest()
            with self.subTest(ts=ts), self.assertRaises(PermissionError):
                self.check(signed=[
                    SignedHoldoutTrial(changed, signature), *self.signed[1:]
                ])

    def test_observation_after_window_is_invalid_even_if_signed(self):
        changed = replace(self.signed[0].trial,
                          observed_unix_s=self.seal.expires_unix_s + 1)
        signature = hmac.new(EVALUATOR, changed.canonical_bytes(),
                             hashlib.sha256).hexdigest()
        with self.assertRaises(PermissionError):
            self.check(signed=[SignedHoldoutTrial(changed, signature),
                               *self.signed[1:]])

    def test_late_or_early_review_is_rejected(self):
        with self.assertRaises(ValueError):
            self.check(now_unix_s=self.seal.sealed_unix_s)
        with self.assertRaises(ValueError):
            self.check(now_unix_s=self.seal.expires_unix_s + 86401)
        with self.assertRaises(ValueError):
            self.check(now_unix_s=True)

    def test_unsigned_result_tamper_rejected_by_existing_evaluator(self):
        changed = replace(self.signed[0].trial, outcome="success")
        with self.assertRaises(PermissionError):
            self.check(signed=[SignedHoldoutTrial(changed, self.signed[0].receipt),
                               *self.signed[1:]])

    def test_extra_off_roster_trial_rejected_by_existing_evaluator(self):
        changed = replace(self.signed[0].trial, situation_id="not_sealed",
                          trial_id="other_trial", run_id="other_run",
                          evidence_sha256=hashlib.sha256(b"other").hexdigest())
        signature = hmac.new(EVALUATOR, changed.canonical_bytes(),
                             hashlib.sha256).hexdigest()
        with self.assertRaises(ValueError):
            self.check(signed=[*self.signed, SignedHoldoutTrial(changed, signature)])

    def test_repeated_capture_rejected_across_all_games(self):
        changed = replace(self.signed[-1].trial,
                          evidence_sha256=self.signed[0].trial.evidence_sha256)
        signature = hmac.new(EVALUATOR, changed.canonical_bytes(),
                             hashlib.sha256).hexdigest()
        with self.assertRaises(ValueError):
            self.check(signed=[*self.signed[:-1], SignedHoldoutTrial(changed, signature)])

    def test_seal_construction_rejects_invalid_identifiers_and_timings(self):
        changes = [
            {"evaluation_id": "../bad"},
            {"roster_sha256": "bad"},
            {"baseline_action_id": "candidate"},
            {"candidate_revision_sha256": BASE_REV},
            {"sealed_unix_s": True},
            {"sealed_unix_s": 0},
            {"expires_unix_s": self.seal.sealed_unix_s + 59},
            {"expires_unix_s": self.seal.sealed_unix_s + 7 * 86400 + 1},
        ]
        for fields in changes:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(self.seal, **fields)

    def test_non_validation_split_is_blocked(self):
        changed = replace(self.signed[0].trial, split="practice")
        signature = hmac.new(EVALUATOR, changed.canonical_bytes(),
                             hashlib.sha256).hexdigest()
        with self.assertRaises(PermissionError):
            self.check(signed=[SignedHoldoutTrial(changed, signature),
                               *self.signed[1:]])


if __name__ == "__main__":
    unittest.main()
