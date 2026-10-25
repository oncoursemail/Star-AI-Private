"""Offline regression and adversarial checks for STAR's signed gameplay ledger."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
from pathlib import Path
import sqlite3
import tempfile
import unittest

from star.gameplay_skill_bank import GameTrial, GameplaySkillBank, wilson_lower

PRACTICE = hashlib.sha256(b"fixture-only-practice-key").digest()
VALIDATION = hashlib.sha256(b"fixture-only-independent-evaluator-key").digest()
NOW = 2_000_000_000
DIGEST = hashlib.sha256(b"fixture screenshot transcript, not actual captured data").hexdigest()


def receipt(trial: GameTrial, secret: bytes | None = None) -> str:
    key = (PRACTICE if trial.split == "practice" else VALIDATION) if secret is None else secret
    return hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()


class GameplaySkillBankTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.count = 0

    def tearDown(self) -> None:
        self.bank.close()

    def add(self, split="practice", outcome="success", *, action="jump",
            game="obby", version="v1", objective="cross", situation="bridge",
            at=NOW) -> GameTrial:
        self.count += 1
        trial = GameTrial(
            trial_id=f"trial{self.count}", game_id=game, game_version=version,
            objective_id=objective, situation_id=situation, action_id=action,
            run_id=f"run{self.count}", split=split, outcome=outcome,
            evidence_sha256=DIGEST, observed_unix_s=at)
        self.bank.ingest(trial, receipt(trial), now_unix_s=NOW)
        return trial

    def advice(self, **kwargs):
        return self.bank.suggest("obby", "v1", "cross", "bridge", now_unix_s=NOW, **kwargs)

    def test_no_evidence_abstains(self):
        info = self.advice()
        self.assertEqual(info.status, "no_evidence")
        self.assertIsNone(info.action_id)
        self.assertFalse(info.authorized_to_play)

    def test_practice_requires_several_independent_runs(self):
        for _ in range(4):
            self.add()
        self.assertEqual(self.advice().status, "no_evidence")
        self.add()
        info = self.advice()
        self.assertEqual((info.status, info.action_id), ("rehearsal_only", "jump"))
        self.assertEqual((info.practice_trials, info.validation_trials), (5, 0))

    def test_separate_validation_is_required_for_review(self):
        for _ in range(5):
            self.add()
        for _ in range(8):
            self.add("validation")
        info = self.advice()
        self.assertEqual(info.status, "ready_for_host_review")
        self.assertEqual(info.action_id, "jump")
        self.assertGreater(info.validation_lower_bound, .65)
        self.assertFalse(info.authorized_to_play)

    def test_practice_cannot_fake_holdout(self):
        for _ in range(100):
            self.add()
        info = self.advice()
        self.assertEqual(info.status, "rehearsal_only")
        self.assertEqual(info.validation_trials, 0)

    def test_validation_only_cannot_qualify(self):
        for _ in range(20):
            self.add("validation")
        self.assertEqual(self.advice().status, "no_evidence")

    def test_failed_validation_vetoes_practice_success(self):
        for _ in range(30):
            self.add()
        for _ in range(8):
            self.add("validation", "failure")
        self.assertEqual(self.advice().status, "no_evidence")

    def test_partial_validation_only_rehearsal(self):
        for _ in range(5):
            self.add()
        for _ in range(7):
            self.add("validation")
        self.assertEqual(self.advice().status, "rehearsal_only")

    def test_unimpressive_validation_vetoes(self):
        for _ in range(5):
            self.add()
        for i in range(8):
            self.add("validation", "success" if i < 4 else "failure")
        self.assertEqual(self.advice().status, "no_evidence")

    def test_best_validated_action_wins(self):
        for action in ("jump", "dodge"):
            for _ in range(5):
                self.add(action=action)
        for i in range(15):
            self.add("validation", "success" if i < 14 else "failure", action="jump")
        for _ in range(15):
            self.add("validation", action="dodge")
        self.assertEqual(self.advice().action_id, "dodge")

    def test_game_version_is_isolated(self):
        for _ in range(5):
            self.add(version="v2")
        for _ in range(8):
            self.add("validation", version="v2")
        self.assertEqual(self.advice().status, "no_evidence")
        self.assertEqual(
            self.bank.suggest("obby", "v2", "cross", "bridge", now_unix_s=NOW).status,
            "ready_for_host_review")

    def test_game_objective_and_situation_isolated(self):
        for _ in range(5):
            self.add(game="arena", objective="boss", situation="lowhealth")
        for _ in range(8):
            self.add("validation", game="arena", objective="boss", situation="lowhealth")
        self.assertEqual(self.advice().status, "no_evidence")
        self.assertEqual(
            self.bank.suggest("arena", "v1", "boss", "lowhealth", now_unix_s=NOW).status,
            "ready_for_host_review")

    def test_distinct_signers_required(self):
        with self.assertRaises(ValueError):
            GameplaySkillBank(practice_key=PRACTICE, validation_key=PRACTICE)
        with self.assertRaises(ValueError):
            GameplaySkillBank(practice_key=b"short", validation_key=VALIDATION)

    def test_non_matching_signature_rejected(self):
        t = GameTrial("a", "obby", "v1", "cross", "bridge", "jump", "run",
                      "validation", "success", DIGEST, NOW)
        with self.assertRaises(PermissionError):
            self.bank.ingest(t, receipt(t, PRACTICE), now_unix_s=NOW)
        self.assertEqual(self.advice().status, "no_evidence")

    def test_mutation_after_signature_rejected(self):
        t = GameTrial("a", "obby", "v1", "cross", "bridge", "jump", "run",
                      "practice", "success", DIGEST, NOW)
        sig = receipt(t)
        for altered in (replace(t, outcome="failure"), replace(t, game_version="v2"),
                        replace(t, split="validation"), replace(t, action_id="dodge")):
            with self.assertRaises(PermissionError):
                self.bank.ingest(altered, sig, now_unix_s=NOW)

    def test_replays_and_duplicate_run_rejected(self):
        t = self.add()
        with self.assertRaises(sqlite3.IntegrityError):
            self.bank.ingest(t, receipt(t), now_unix_s=NOW)
        clone = replace(t, trial_id="different", action_id="dodge")
        with self.assertRaises(sqlite3.IntegrityError):
            self.bank.ingest(clone, receipt(clone), now_unix_s=NOW)

    def test_stale_and_future_trials_rejected(self):
        t = GameTrial("a", "obby", "v1", "cross", "bridge", "jump", "run",
                      "practice", "success", DIGEST, NOW - 91 * 86400)
        with self.assertRaises(ValueError):
            self.bank.ingest(t, receipt(t), now_unix_s=NOW)
        future = replace(t, observed_unix_s=NOW + 11)
        with self.assertRaises(ValueError):
            self.bank.ingest(future, receipt(future), now_unix_s=NOW)

    def test_stale_validation_stops_review(self):
        at = NOW - 29 * 86400
        for _ in range(5):
            self.add(at=NOW - 29 * 86400)
        for _ in range(8):
            self.add("validation", at=at)
        fresh = self.advice()
        self.assertEqual(fresh.status, "ready_for_host_review")
        later = self.bank.suggest("obby", "v1", "cross", "bridge",
                                  now_unix_s=NOW + 2 * 86400)
        self.assertEqual(later.status, "rehearsal_only")

    def test_database_reopen_preserves_evidence_not_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "skill-bank.db"
            with GameplaySkillBank(path, practice_key=PRACTICE,
                                   validation_key=VALIDATION) as bank:
                t = GameTrial("one", "obby", "v1", "cross", "bridge", "jump",
                              "run1", "practice", "success", DIGEST, NOW)
                bank.ingest(t, receipt(t), now_unix_s=NOW)
            with GameplaySkillBank(path, practice_key=PRACTICE,
                                   validation_key=VALIDATION) as reopened:
                self.assertEqual(reopened.suggest(
                    "obby", "v1", "cross", "bridge", now_unix_s=NOW,
                    min_practice=3).status, "no_evidence")
            raw = path.read_bytes()
            self.assertNotIn(PRACTICE, raw)
            self.assertNotIn(VALIDATION, raw)

    def test_database_tampering_does_not_become_proof(self):
        self.add()
        self.bank._db.execute(
            "UPDATE gameplay_trials SET payload_json=REPLACE("
            "payload_json, 'success', 'failure')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.advice()

    def test_database_scope_tampering_rejected(self):
        self.add()
        self.bank._db.execute(
            "UPDATE gameplay_trials SET trial_id='other'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.advice()

    def test_invalid_trial_fields_rejected(self):
        t = GameTrial("t", "obby", "v1", "cross", "bridge", "jump", "run",
                      "practice", "success", DIGEST, NOW)
        replacements = (
            {"game_id": "../../secret"}, {"action_id": "run arbitrary code"},
            {"split": "production"}, {"outcome": "maybe"},
            {"evidence_sha256": "not-real"}, {"observed_unix_s": True},
            {"run_id": ""}, {"trial_id": "a" * 65},
        )
        for fields in replacements:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(t, **fields)

    def test_invalid_query_rejected(self):
        with self.assertRaises(ValueError):
            self.bank.suggest("../../secret", "v1", "cross", "bridge",
                              now_unix_s=NOW)
        for options in ({"min_practice": 0}, {"min_validation": True},
                        {"min_validation_lower_bound": float("nan")},
                        {"min_validation_lower_bound": 1.0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.advice(**options)

    def test_wilson_is_conservative_and_bounded(self):
        self.assertGreater(wilson_lower(8, 8), 0.65)
        self.assertLess(wilson_lower(8, 8), 0.70)
        self.assertLess(wilson_lower(7, 8), wilson_lower(8, 8))
        self.assertEqual(wilson_lower(0, 10), 0)
        for s, n in ((-1, 5), (6, 5), (1, 0), (True, 4)):
            with self.assertRaises(ValueError):
                wilson_lower(s, n)


if __name__ == "__main__":
    unittest.main()
