"""Deterministic offline tests for owner-preregistered gameplay experiments."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import hmac
import unittest

from star.game_paired_study import (
    PairedGameStudy, PairedStudyProtocol, PairedReservation, _p_one_sided,
)
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry

PRACTICE = hashlib.sha256(b"paired-study-fake-practice-not-prod").digest()
VALIDATION = hashlib.sha256(b"paired-study-fake-validation-not-prod").digest()
RANDOM = hashlib.sha256(b"paired-study-fake-randomness-not-prod").digest()
STATE = hashlib.sha256(b"host-reset-observed-state").hexdigest()
NOW = 2_000_000_000


def telemetry(*, live=False, active=True, fps=75, vram=4096, backlog=0):
    return StreamTelemetry(live, active, vram, 8192, fps, backlog)


class PairedStudyTests(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.num = 0
        self.protocol = PairedStudyProtocol(
            "study1", "obby", "v1", "reach_goal", "left", "right",
            tuple(f"scene_{i}" for i in range(16)), NOW, min_complete_pairs=8,
        )
        self.study = self.make_study()

    def tearDown(self):
        self.bank.close()

    def make_study(self, *, protocol=None, key=RANDOM, ttl=180):
        return PairedGameStudy(
            self.bank, protocol or self.protocol, randomization_key=key,
            reservation_ttl_s=ttl,
        )

    def ingest(self, slot, *, outcome="failure", timestamp=NOW,
               split="practice", scene=None, action=None, run=None):
        self.num += 1
        trial = GameTrial(
            f"cx_test_trial_{self.num}", "obby", "v1", "reach_goal",
            scene if scene is not None else slot.situation_id,
            action if action is not None else slot.action_id,
            run if run is not None else slot.expected_run_id,
            split, outcome, hashlib.sha256(
                f"independent-observation-{self.num}".encode("ascii")
            ).hexdigest(), timestamp,
        )
        key = PRACTICE if split == "practice" else VALIDATION
        receipt = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, receipt, now_unix_s=timestamp)
        return trial

    def enable(self, study=None, *, at=NOW):
        (study or self.study).enable(owner_approved=True, now_unix_s=at)

    def next(self, study=None, *, at=NOW, snapshot=None):
        return (study or self.study).next_assignment(
            now_unix_s=at, telemetry=telemetry() if snapshot is None else snapshot,
        )

    def record(self, study=None, *, at=NOW, outcome=None, digest=STATE,
               slot=None, reset=True):
        study = study or self.study
        slot = slot or self.next(study, at=at)
        trial = self.ingest(slot, outcome=outcome or
                            ("success" if slot.action_id == "right" else "failure"),
                            timestamp=at)
        result = study.accept_signed_trial(
            slot.ticket, trial, now_unix_s=at, initial_state_sha256=digest,
            reset_verified=reset,
        )
        return result

    def test_preregistration_validation_and_security_defaults(self):
        self.assertFalse(self.study.metrics()["enabled"])
        self.assertFalse(self.study.next_assignment(
            now_unix_s=NOW, telemetry=telemetry()))
        with self.assertRaises(PermissionError):
            self.study.enable(owner_approved="yes", now_unix_s=NOW)
        with self.assertRaises(ValueError):
            self.make_study(key=b"too-short")
        with self.assertRaises(ValueError):
            self.make_study(ttl=29)
        with self.assertRaises(ValueError):
            replace(self.protocol, candidate_action_id="left")
        with self.assertRaises(ValueError):
            replace(self.protocol, scenario_ids=("scene_0",) * 8)
        with self.assertRaises(ValueError):
            replace(self.protocol, scenario_ids=tuple(f"s{i}" for i in range(9)))
        with self.assertRaises(ValueError):
            replace(self.protocol, min_complete_pairs=7)
        with self.assertRaises(ValueError):
            replace(self.protocol, minimum_lift=float("nan"))
        with self.assertRaises(ValueError):
            replace(self.protocol, registered_unix_s=True)
        with self.assertRaises(ValueError):
            self.study.enable(owner_approved=True, now_unix_s=NOW - 1)

    def test_allocation_blinded_balanced_and_one_flight(self):
        self.enable()
        first_by_arm = {"left": 0, "right": 0}
        all_actions = set()
        for i in range(16):
            first = self.next()
            self.assertIsInstance(first, PairedReservation)
            self.assertEqual(first.situation_id, f"scene_{i}")
            self.assertFalse(first.authorized_to_play)
            self.assertFalse(first.authorized_to_broadcast)
            self.assertIs(first, self.next())
            first_by_arm[first.action_id] += 1
            all_actions.add(first.action_id)
            self.assertTrue(self.record(slot=first))
            second = self.next()
            self.assertEqual(second.situation_id, first.situation_id)
            self.assertNotEqual(second.action_id, first.action_id)
            self.assertNotEqual(second.expected_run_id, first.expected_run_id)
            self.assertTrue(self.record(slot=second))
        self.assertEqual(first_by_arm, {"left": 8, "right": 8})
        self.assertEqual(all_actions, {"left", "right"})
        self.assertIsNone(self.next())
        self.assertEqual(self.study.metrics()["signed"], 32)

    def test_model_cannot_choose_result_or_replay_ticket(self):
        self.enable()
        slot = self.next()
        trial = GameTrial(
            "madeup", "obby", "v1", "reach_goal", slot.situation_id,
            slot.action_id, slot.expected_run_id, "practice",
            "success", STATE, NOW,
        )
        self.assertFalse(self.study.accept_signed_trial(
            slot.ticket, trial, now_unix_s=NOW,
            initial_state_sha256=STATE, reset_verified=True))
        genuine = self.ingest(slot, outcome="failure")
        forged = replace(genuine, outcome="success")
        for bad_ticket, bad_trial in [
            (slot.ticket, forged),
            ("x" * len(slot.ticket), genuine),
            (slot.ticket, replace(genuine, run_id="not_reservation")),
            (slot.ticket, replace(genuine, split="validation")),
            (slot.ticket, replace(genuine, action_id="other")),
            (slot.ticket, replace(genuine, situation_id="scene_15")),
        ]:
            with self.subTest(bad_ticket=bad_ticket, bad_trial=bad_trial):
                self.assertFalse(self.study.accept_signed_trial(
                    bad_ticket, bad_trial, now_unix_s=NOW,
                    initial_state_sha256=STATE, reset_verified=True))
        self.assertFalse(self.study.accept_signed_trial(
            slot.ticket, genuine, now_unix_s=NOW,
            initial_state_sha256=STATE, reset_verified=False))
        self.assertFalse(self.study.accept_signed_trial(
            slot.ticket, genuine, now_unix_s=NOW,
            initial_state_sha256="garbage", reset_verified=True))
        self.assertTrue(self.study.accept_signed_trial(
            slot.ticket, genuine, now_unix_s=NOW,
            initial_state_sha256=STATE, reset_verified=True))
        self.assertFalse(self.study.accept_signed_trial(
            slot.ticket, genuine, now_unix_s=NOW,
            initial_state_sha256=STATE, reset_verified=True))
        self.assertEqual(self.study.metrics()["signed"], 1)

    def test_preexisting_practice_data_invalidates_study(self):
        slot = PairedReservation("fixture", "scene_0", "left", "run_old", NOW + 90)
        self.ingest(slot)
        with self.assertRaises(RuntimeError):
            self.enable()
        self.assertTrue(self.study.metrics()["contaminated"])
        self.assertIsNone(self.next())

    def test_external_record_after_enable_fails_closed(self):
        self.enable()
        slot = self.next()
        self.ingest(PairedReservation("external", slot.situation_id,
                                      "left", "outside_run", NOW + 60))
        with self.assertRaises(RuntimeError):
            self.study.next_assignment(now_unix_s=NOW, telemetry=telemetry())
        self.assertTrue(self.study.metrics()["contaminated"])

    def test_expired_ticket_drops_entire_pair_without_imputation(self):
        self.enable()
        first = self.next()
        self.assertTrue(self.record(slot=first))
        other = self.next(at=NOW + 1)
        self.assertEqual(first.situation_id, other.situation_id)
        nxt = self.next(at=NOW + 182)
        self.assertEqual(nxt.situation_id, "scene_1")
        self.assertNotEqual(nxt.ticket, other.ticket)
        self.assertEqual(self.study.metrics()["invalid_pairs"], 1)
        self.assertEqual(self.study.metrics()["expired"], 1)
        self.assertFalse(self.study.accept_signed_trial(
            other.ticket, GameTrial("late", "obby", "v1", "reach_goal",
                                    other.situation_id, other.action_id,
                                    other.expected_run_id, "practice", "success",
                                    STATE, NOW + 182),
            now_unix_s=NOW + 182, initial_state_sha256=STATE, reset_verified=True,
        ))

    def test_mismatched_reset_invalidates_completed_pair(self):
        self.enable()
        self.assertTrue(self.record(digest=STATE))
        self.assertTrue(self.record(digest="f" * 64))
        self.assertEqual(self.study.metrics()["invalid_pairs"], 1)
        self.assertEqual(self.next().situation_id, "scene_1")

    def test_no_interim_p_hacking_or_unapproved_review(self):
        self.enable()
        self.assertTrue(self.record())
        with self.assertRaises(PermissionError):
            self.study.owner_report(now_unix_s=NOW)
        report = self.study.owner_report(now_unix_s=NOW, owner_approved=True)
        self.assertEqual(report.status, "preregistered_not_complete")
        self.assertIsNone(report.exact_one_sided_p)
        self.assertFalse(report.authorized_to_promote)

    def test_full_study_detects_only_exploratory_candidate_advantage(self):
        self.enable()
        for _ in range(32):
            self.assertTrue(self.record())
        report = self.study.owner_report(now_unix_s=NOW, owner_approved=True)
        self.assertEqual(report.status, "exploratory_candidate_preferred")
        self.assertEqual(report.complete_pairs, 16)
        self.assertEqual(report.candidate_wins, 16)
        self.assertEqual(report.baseline_wins, 0)
        self.assertEqual(report.ties, 0)
        self.assertEqual(report.paired_success_lift, 1.0)
        self.assertLess(report.exact_one_sided_p, 0.001)
        self.assertFalse(report.authorized_to_play)
        self.assertFalse(report.authorized_to_promote)
        self.assertNotIn("success", str(self.study.metrics()))

    def test_ties_have_no_statistically_supported_advantage(self):
        self.enable()
        for _ in range(32):
            self.assertTrue(self.record(outcome="success"))
        report = self.study.owner_report(now_unix_s=NOW, owner_approved=True)
        self.assertEqual(report.status, "insufficient_discordant_pairs")
        self.assertEqual((report.candidate_wins, report.baseline_wins, report.ties),
                         (0, 0, 16))
        self.assertEqual(report.exact_one_sided_p, 1.0)

    def test_aborted_and_restarts_fail_closed(self):
        self.enable()
        self.assertIsNotNone(self.next())
        self.study.disable()
        self.assertIsNone(self.next())
        self.assertEqual(self.study.owner_report(
            now_unix_s=NOW, owner_approved=True).status, "aborted")
        with self.assertRaises(RuntimeError):
            self.enable()

    def test_offline_qos_protects_streaming_and_fps(self):
        self.enable()
        for current in [
            None, telemetry(live=True), telemetry(fps=40),
            telemetry(vram=500), telemetry(backlog=300),
        ]:
            with self.subTest(snapshot=current):
                self.assertIsNone(self.study.next_assignment(
                    now_unix_s=NOW, telemetry=current))
        self.assertEqual(self.study.metrics()["issued"], 0)
        self.assertIsNotNone(self.next())

    def test_signed_validation_holdout_never_admits_practice(self):
        # Signed validation may exist, but none of its outcomes must enter
        # the practice randomizer or reported statistics.
        slot = PairedReservation("fixture", "scene_0", "left", "val_run", NOW + 90)
        self.ingest(slot, outcome="success", split="validation")
        self.enable()
        first = self.next()
        self.assertTrue(self.record(slot=first))
        self.assertEqual(self.study.metrics()["signed"], 1)
        self.assertEqual(self.study.owner_report(
            now_unix_s=NOW, owner_approved=True).status, "preregistered_not_complete")

    def test_thread_confinement_and_clock_reversal(self):
        self.enable()
        with ThreadPoolExecutor(max_workers=1) as executor:
            exc = executor.submit(self.next).exception()
        self.assertIsInstance(exc, RuntimeError)
        self.assertIsNotNone(self.next(at=NOW + 10))
        with self.assertRaises(ValueError):
            self.next(at=NOW + 9)

    def test_expiry_and_missing_proof_cannot_be_reclassified_success(self):
        self.enable()
        slot = self.next()
        self.ingest(slot, timestamp=NOW + 1)
        with self.assertRaises(RuntimeError):
            # Unsubmitted but already signed trial is out-of-band evidence.
            self.study.next_assignment(now_unix_s=NOW + 1, telemetry=telemetry())
        self.assertFalse(self.study.metrics()["signed"] > 0)
        # The host may still accept the exact reservation but the ledger is now
        # contaminated, so this study must be abandoned permanently.
        with self.assertRaises(RuntimeError):
            self.study.enable(owner_approved=True, now_unix_s=NOW + 1)

    def test_exact_one_sided_test_boundary(self):
        self.assertEqual(_p_one_sided(0, 0), 1.0)
        self.assertAlmostEqual(_p_one_sided(8, 0), 1 / 256)
        self.assertAlmostEqual(_p_one_sided(4, 4), 163 / 256)
        self.assertAlmostEqual(_p_one_sided(0, 8), 1.0)


    def test_live_pressure_hides_already_pending_task(self):
        self.enable()
        slot = self.next()
        self.assertIsNone(self.study.next_assignment(
            now_unix_s=NOW + 1, telemetry=telemetry(live=True)))
        self.assertIsNone(self.study.next_assignment(
            now_unix_s=NOW + 2, telemetry=telemetry(fps=25)))
        self.assertEqual(self.study.metrics()["signed"], 0)
        self.assertEqual(self.study.metrics()["issued"], 1)
        self.assertIs(self.next(at=NOW + 3), slot)

    def test_mismatched_state_causes_attrition_even_if_other_pairs_succeed(self):
        self.enable()
        for i in range(32):
            self.assertTrue(self.record(digest="f" * 64 if i == 1 else STATE))
        report = self.study.owner_report(now_unix_s=NOW, owner_approved=True)
        self.assertEqual(report.status, "attrition_requires_independent_review")
        self.assertEqual(report.complete_pairs, 15)
        self.assertEqual(report.dropped_pairs, 1)
        self.assertEqual(report.candidate_wins, 15)
        self.assertFalse(report.authorized_to_promote)

    def test_signed_ledger_corruption_fails_closed(self):
        import sqlite3

        self.enable()
        slot = self.next()
        self.assertTrue(self.record(slot=slot))
        # A modified receipt is not treated as a legitimate trial even if
        # the JSON payload still claims the originally signed outcome.
        self.bank._db.execute(
            "UPDATE gameplay_trials SET receipt=? WHERE run_id=?",
            ("0" * 64, slot.expected_run_id))
        with self.assertRaises(sqlite3.IntegrityError):
            self.next()
        self.assertEqual(self.study.metrics()["signed"], 1)

    def test_invalid_outcome_signed_before_task_issuance_is_not_accepted(self):
        self.enable()
        slot = self.next(at=NOW + 20)
        backdated = self.ingest(slot, timestamp=NOW + 19)
        self.assertFalse(self.study.accept_signed_trial(
            slot.ticket, backdated, now_unix_s=NOW + 20,
            initial_state_sha256=STATE, reset_verified=True))
        with self.assertRaises(RuntimeError):
            self.next(at=NOW + 20)

    def test_exact_pvalue_never_rounds_a_tiny_probability_to_zero(self):
        self.assertGreater(_p_one_sided(64, 0), 0.0)
        self.assertAlmostEqual(_p_one_sided(64, 0), 2**-64)



if __name__ == "__main__":
    unittest.main()
