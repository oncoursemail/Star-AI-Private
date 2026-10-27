"""Offline adversarial tests of preregistered, owner-only game transfer auditing."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
from pathlib import Path
import sqlite3
import tempfile
import unittest

from star.game_transfer_audit import GameTransferAuditor, TransferProtocol
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank

PRACTICE = b"practice-fixture-only-key-32bytes!"
VALIDATION = b"validation-fixture-only-key-32by!"
REGISTRATION = b"owner-prereg-fixture-only-key-32b!"
NOW = 2_000_000_000
HASH = "a" * 64


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.audit = GameTransferAuditor(self.bank, registration_key=REGISTRATION)
        self.sequence = 0
        self.protocol = TransferProtocol(
            "transfer_1", "obby", "v1", "reach", "training_ledges", "jump",
            "obby", "v2", "reach", "unseen_castle", "jump",
            NOW + 10,
        )

    def tearDown(self):
        self.audit.close()
        self.bank.close()

    def add(self, *, target=False, split="practice", outcome="success",
            at=NOW, action="jump", game=None, situation=None):
        self.sequence += 1
        trial = GameTrial(
            trial_id=f"trial{self.sequence}",
            game_id=game or "obby",
            game_version="v2" if target else "v1",
            objective_id="reach",
            situation_id=situation or ("unseen_castle" if target else "training_ledges"),
            action_id=action,
            run_id=f"run{self.sequence}",
            split=split,
            outcome=outcome,
            evidence_sha256=HASH,
            observed_unix_s=at,
        )
        key = PRACTICE if split == "practice" else VALIDATION
        sig = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, sig, now_unix_s=at)
        return trial

    def practice(self, attempts=15, successes=15):
        for i in range(attempts):
            self.add(outcome="success" if i < successes else "failure")

    def register(self):
        self.audit.enable(owner_approved=True)
        return self.audit.register(
            self.protocol, now_unix_s=NOW + 10, owner_approved=True
        )

    def report(self, *, at=NOW + 31):
        return self.audit.owner_report(
            "transfer_1", now_unix_s=at, owner_approved=True
        )

    def test_default_off_and_owner_gate(self):
        self.practice()
        with self.assertRaises(PermissionError):
            self.audit.enable()
        with self.assertRaises(PermissionError):
            self.audit.register(self.protocol, now_unix_s=NOW + 10)
        with self.assertRaises(PermissionError):
            self.audit.owner_report("transfer_1", now_unix_s=NOW + 10)
        assert not self.audit.register(
            self.protocol, now_unix_s=NOW + 10, owner_approved=True
        )
        self.assertTrue(self.register())
        self.assertFalse(self.register())  # cannot rewrite preregistered conditions
        self.audit.disable()
        self.assertIsNone(self.report())

    def test_heldout_success_is_bounded_evidence_not_game_permission(self):
        self.practice()
        self.assertTrue(self.register())
        self.assertEqual(self.report().status, "insufficient_independent_holdout")
        for _ in range(25):
            self.add(target=True, split="validation", at=NOW + 20)
        outcome = self.report()
        self.assertEqual(outcome.status, "bounded_transfer_evidence_for_owner_review")
        self.assertEqual((outcome.source_trials, outcome.holdout_trials), (15, 25))
        self.assertGreater(outcome.holdout_wilson_lower, 0.8)
        self.assertEqual(outcome.observed_gap, 0.0)
        self.assertFalse(outcome.authorized_to_play)
        # Validation never enters the model-facing practice evidence.
        self.assertEqual(self.bank.practice_evidence(
            "obby", "v2", "reach", "unseen_castle", now_unix_s=NOW + 31
        ), ())

    def test_failed_holdout_vetoes_perfect_practice(self):
        self.practice()
        assert self.register()
        for i in range(24):
            self.add(target=True, split="validation", at=NOW + 20,
                     outcome="success" if i < 6 else "failure")
        result = self.report()
        self.assertEqual(result.status, "heldout_transfer_not_demonstrated")
        self.assertLess(result.holdout_wilson_lower, 0.55)
        self.assertGreater(result.observed_gap, .70)

    def test_holdout_must_be_unseen_before_preregistration(self):
        self.practice()
        self.add(target=True, split="validation", at=NOW + 1)
        self.assertFalse(self.register())
        # Even previous PRACTICE in the target with a different action is
        # disqualifying; the exact version/scene, not just action, must be new.
        other = TransferProtocol(
            "other", "obby", "v1", "reach", "training_ledges", "jump",
            "obby", "v2", "reach", "novel", "jump", NOW + 10,
        )
        self.add(target=True, split="practice", situation="novel", action="dodge")
        self.assertFalse(self.audit.register(other, now_unix_s=NOW + 10,
                                             owner_approved=True))

    def test_cross_game_mapping_with_curated_target_is_allowed(self):
        self.practice()
        alt = replace(self.protocol, target_game="other_game", target_action="vault")
        self.audit.enable(owner_approved=True)
        self.assertTrue(self.audit.register(
            alt, now_unix_s=NOW + 10, owner_approved=True
        ))

    def test_post_registration_practice_contaminates_even_with_many_wins(self):
        self.practice()
        assert self.register()
        for _ in range(25):
            self.add(target=True, split="validation", at=NOW + 20)
        self.add(target=True, split="practice", at=NOW + 25, action="dodge")
        result = self.report()
        self.assertEqual(result.status, "holdout_contaminated_by_practice")
        self.assertIsNone(result.holdout_success_rate)

    def test_frozen_baseline_ignores_late_source_practice(self):
        self.practice(12, 10)
        assert self.register()
        for _ in range(10):
            self.add(outcome="success", at=NOW + 20)
        result = self.report()
        self.assertEqual(result.source_trials, 12)
        self.assertAlmostEqual(result.source_success_rate, 10 / 12, places=4)

    def test_expiry_and_scarce_holdout_fail_conservatively(self):
        self.practice()
        assert self.register()
        for _ in range(11):
            self.add(target=True, split="validation", at=NOW + 20)
        self.assertEqual(self.report().status, "insufficient_independent_holdout")
        later = self.report(at=NOW + 31 * 86400)
        self.assertEqual(later.status, "evaluation_window_expired")

    def test_invalid_plans_and_insufficient_baseline(self):
        with self.assertRaises(ValueError):
            replace(self.protocol, target_version="v1",
                    target_situation="training_ledges")
        with self.assertRaises(ValueError):
            replace(self.protocol, target_wilson_floor_bps=9900)
        self.practice(8, 8)
        self.assertFalse(self.register())
        self.assertIsNone(self.report())

    def test_different_action_and_scope_do_not_count(self):
        self.practice()
        assert self.register()
        for _ in range(20):
            self.add(target=True, split="validation", at=NOW + 20, action="duck")
        result = self.report()
        self.assertEqual(result.holdout_trials, 0)
        self.assertEqual(result.status, "insufficient_independent_holdout")

    def test_bad_signature_or_tampering_cannot_certify_transfer(self):
        self.practice()
        assert self.register()
        one = self.add(target=True, split="validation", at=NOW + 20)
        self.bank._db.execute(
            "UPDATE gameplay_trials SET payload_json=REPLACE("
            "payload_json, 'success', 'failure') WHERE trial_id=?",
            (one.trial_id,)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.report()

    def test_durable_preregistration_and_no_secret_material(self):
        self.practice()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transfer.db"
            with GameTransferAuditor(self.bank, path, registration_key=REGISTRATION) as audit:
                audit.enable(owner_approved=True)
                self.assertTrue(audit.register(
                    self.protocol, now_unix_s=NOW + 10, owner_approved=True
                ))
            with GameTransferAuditor(self.bank, path, registration_key=REGISTRATION) as reopened:
                reopened.enable(owner_approved=True)
                self.assertFalse(reopened.register(
                    self.protocol, now_unix_s=NOW + 10, owner_approved=True
                ))
                result = reopened.owner_report(
                    "transfer_1", now_unix_s=NOW + 11, owner_approved=True
                )
                self.assertEqual(result.source_trials, 15)
            raw = path.read_bytes()
            self.assertNotIn(PRACTICE, raw)
            self.assertNotIn(VALIDATION, raw)
            self.assertNotIn(REGISTRATION, raw)

    def test_weak_source_is_not_claimed_as_transfer(self):
        self.practice(15, 8)
        self.assertFalse(self.register())

    def test_registration_rollback_or_altered_mapping_is_rejected(self):
        self.practice()
        assert self.register()
        self.audit._db.execute(
            "UPDATE transfer_protocols SET specification=REPLACE("
            "specification, 'unseen_castle', 'easier_castle')"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.report()

    def test_late_signed_retroactive_source_result_invalidates_baseline(self):
        self.practice()
        assert self.register()
        self.add(outcome="success", at=NOW + 9)
        with self.assertRaises(sqlite3.IntegrityError):
            self.report()

    def test_protocol_database_corruption_is_not_evidence(self):
        self.practice()
        assert self.register()
        self.audit._db.execute(
            "UPDATE transfer_protocols SET specification='{}' "
            "WHERE protocol_id='transfer_1'"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.report()


if __name__ == "__main__":
    unittest.main()
