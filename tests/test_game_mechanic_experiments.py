"""Adversarial offline regressions for preregistered game-mechanic comparisons."""
from dataclasses import replace
import hashlib
import hmac
import unittest

from star.game_mechanic_experiments import (
    MechanicHypothesis, MechanicPairTicket, PairedMechanicLab, exact_mcnemar_p,
)
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry


PRACTICE_KEY = b"p" * 32
VALIDATION_KEY = b"v" * 32


def telemetry(*, live=False, fps=90, backlog=0):
    return StreamTelemetry(
        live=live, game_active=True, free_vram_mib=4096,
        total_vram_mib=8192, game_fps=fps, speech_backlog_ms=backlog,
    )


class TestMechanicLab(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(
            practice_key=PRACTICE_KEY, validation_key=VALIDATION_KEY)
        self.hypothesis = MechanicHypothesis(
            "dash-gap-test", "obby", "v1", "finish", "gap1",
            "walk", "dash", target_pairs=12)
        self.lab = PairedMechanicLab(self.bank, self.hypothesis)
        self.t = 1_000_000

    def tearDown(self):
        self.bank.close()

    def issue(self, *, now=None):
        when = self.t if now is None else now
        return self.lab.reserve(now_unix_s=when, telemetry=telemetry())

    def record(self, ticket, *, baseline_success=False, candidate_success=True,
               omitted=None, fake_outcome=False, same_proof=False,
               reverse_order=False, split="practice", wrong_scope=False):
        by_action = {"baseline": ("walk", ticket.baseline_run_id, baseline_success),
                     "candidate": ("dash", ticket.candidate_run_id, candidate_success)}
        trials = {}
        for order_index, role in enumerate(ticket.execution_order):
            action, run, success = by_action[role]
            if role == omitted:
                continue
            event_time = ticket.issued_unix_s + (2 - order_index if reverse_order
                                                 else order_index + 1)
            trial = GameTrial(
                trial_id=f"t_{ticket.serial}_{role}",
                game_id="other" if wrong_scope and role == "candidate" else "obby",
                game_version="v1", objective_id="finish",
                situation_id="gap1", action_id=action, run_id=run,
                split=split, outcome="success" if success else "failure",
                evidence_sha256=hashlib.sha256(
                    (f"witness.{ticket.serial}.{role}" if not same_proof
                     else f"witness.{ticket.serial}").encode()).hexdigest(),
                observed_unix_s=event_time,
            )
            receipt_key = PRACTICE_KEY if split == "practice" else VALIDATION_KEY
            receipt = hmac.new(receipt_key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
            self.bank.ingest(trial, receipt, now_unix_s=event_time + 2)
            trials[role] = trial
        if fake_outcome and "candidate" in trials:
            original = trials["candidate"]
            trials["candidate"] = replace(
                original,
                outcome="failure" if original.outcome == "success" else "success",
            )
        return trials

    def accept_pair(self, *, baseline_success=False, candidate_success=True):
        ticket = self.issue()
        self.assertIsInstance(ticket, MechanicPairTicket)
        trials = self.record(ticket, baseline_success=baseline_success,
                             candidate_success=candidate_success)
        self.assertTrue(self.lab.submit_pair(
            ticket, baseline=trials["baseline"],
            candidate=trials["candidate"],
            now_unix_s=self.t + 3))
        self.t += 8

    def test_opt_in_and_live_stream_resourcing(self):
        self.assertIsNone(self.issue())
        with self.assertRaises(PermissionError):
            self.lab.enable()
        self.lab.enable(owner_approved=True)
        self.assertIsNone(self.lab.reserve(now_unix_s=self.t, telemetry=None))
        self.assertIsNone(self.lab.reserve(
            now_unix_s=self.t, telemetry=telemetry(live=True)))
        self.assertIsNone(self.lab.reserve(
            now_unix_s=self.t, telemetry=telemetry(fps=10)))
        self.assertIsNone(self.lab.reserve(
            now_unix_s=self.t, telemetry=telemetry(backlog=1000)))
        self.assertIsNotNone(self.issue())

    def test_candidate_advantage_only_after_fixed_sample(self):
        self.lab.enable(owner_approved=True)
        for idx in range(12):
            self.accept_pair()
            report = self.lab.report(now_unix_s=self.t)
            if idx < 11:
                self.assertEqual(report.status, "collecting")
                self.assertIsNone(report.exact_two_sided_p)
                self.assertEqual(report.candidate_only, 0)
        self.assertEqual(report.status, "candidate_advantage")
        self.assertEqual(report.accepted_pairs, 12)
        self.assertEqual(report.candidate_only, 12)
        self.assertEqual(report.baseline_only, 0)
        self.assertEqual(report.effect_bps, 10000)
        self.assertAlmostEqual(report.exact_two_sided_p, 2 / 4096)
        self.assertFalse(report.authorized_to_play)
        self.assertFalse(report.established_causal_mechanic)
        self.assertIsNone(self.issue())
        self.assertEqual(self.lab.metrics()["accepted"], 12)

    def test_baseline_advantage_and_no_difference(self):
        self.lab.enable(owner_approved=True)
        for _ in range(12):
            self.accept_pair(baseline_success=True, candidate_success=False)
        report = self.lab.report(now_unix_s=self.t)
        self.assertEqual(report.status, "baseline_advantage")
        self.assertEqual(report.baseline_only, 12)

    def test_inconclusive_with_mixed_pairs(self):
        self.lab.enable(owner_approved=True)
        for idx in range(12):
            self.accept_pair(baseline_success=(idx < 6),
                             candidate_success=(idx >= 6))
        report = self.lab.report(now_unix_s=self.t)
        self.assertEqual(report.status, "inconclusive")
        self.assertEqual(report.candidate_only, 6)
        self.assertEqual(report.baseline_only, 6)
        self.assertAlmostEqual(report.exact_two_sided_p, 1.0)

    def test_reject_unsigned_substitution_and_invalidate(self):
        self.lab.enable(owner_approved=True)
        ticket = self.issue()
        trials = self.record(ticket, fake_outcome=True)
        self.assertFalse(self.lab.submit_pair(
            ticket, baseline=trials["baseline"],
            candidate=trials["candidate"], now_unix_s=self.t + 3))
        self.assertEqual(self.lab.report(now_unix_s=self.t + 4).status, "invalid")
        self.assertIsNone(self.lab.reserve(
            now_unix_s=self.t + 5, telemetry=telemetry()))

    def test_wrong_scope_and_validation_are_rejected(self):
        for variation in ("wrong_scope", "validation"):
            with self.subTest(variation=variation):
                self.tearDown()
                self.setUp()
                self.lab.enable(owner_approved=True)
                ticket = self.issue()
                trials = self.record(ticket, **(
                    {"wrong_scope": True} if variation == "wrong_scope"
                    else {"split": "validation"}
                ))
                self.assertFalse(self.lab.submit_pair(
                    ticket, baseline=trials["baseline"],
                    candidate=trials["candidate"], now_unix_s=self.t + 3))
                self.assertEqual(self.lab.report(now_unix_s=self.t + 4).status, "invalid")

    def test_same_witness_and_wrong_order_fail_closed(self):
        for variation in ("same_proof", "reverse_order"):
            with self.subTest(variation=variation):
                self.tearDown()
                self.setUp()
                self.lab.enable(owner_approved=True)
                ticket = self.issue()
                trials = self.record(ticket, **{variation: True})
                self.assertFalse(self.lab.submit_pair(
                    ticket, baseline=trials["baseline"],
                    candidate=trials["candidate"], now_unix_s=self.t + 3))
                self.assertTrue(self.lab.metrics()["invalid"])

    def test_missing_trial_and_timeout_are_not_skippable(self):
        self.lab.enable(owner_approved=True)
        ticket = self.issue()
        trials = self.record(ticket, omitted="candidate")
        self.assertFalse(self.lab.submit_pair(
            ticket, baseline=trials["baseline"], candidate=None,
            now_unix_s=self.t + 3))
        self.assertEqual(self.lab.report(now_unix_s=self.t + 4).status, "invalid")

    def test_timeout_before_next_reservation_invalidates_incomplete_pair(self):
        self.lab.enable(owner_approved=True)
        ticket = self.issue()
        self.assertIsNone(self.lab.reserve(
            now_unix_s=ticket.expires_unix_s + 1, telemetry=telemetry()))
        self.assertEqual(self.lab.report(
            now_unix_s=ticket.expires_unix_s + 1).status, "invalid")

    def test_stale_ticket_replacement_never_consumes_live_ticket(self):
        self.lab.enable(owner_approved=True)
        ticket = self.issue()
        copy = replace(ticket)
        trials = self.record(ticket)
        self.assertFalse(self.lab.submit_pair(
            copy, baseline=trials["baseline"],
            candidate=trials["candidate"], now_unix_s=self.t + 3))
        # The identity-mismatched ticket didn't consume the legitimate one.
        self.assertTrue(self.lab.submit_pair(
            ticket, baseline=trials["baseline"],
            candidate=trials["candidate"], now_unix_s=self.t + 3))

    def test_clock_reversal_disables_valid_conclusion(self):
        self.lab.enable(owner_approved=True)
        self.issue()
        with self.assertRaises(ValueError):
            self.lab.report(now_unix_s=self.t - 1)
        self.assertEqual(self.lab.report(now_unix_s=self.t).status, "invalid")

    def test_partial_shutdown_cannot_be_restarted_or_reported(self):
        self.lab.enable(owner_approved=True)
        self.accept_pair()
        self.lab.disable()
        with self.assertRaises(RuntimeError):
            self.lab.enable(owner_approved=True)
        self.assertEqual(self.lab.report(now_unix_s=self.t).status, "invalid")

    def test_preregistration_rejects_gaming_the_spec(self):
        with self.assertRaises(ValueError):
            replace(self.hypothesis, candidate_action="walk")
        with self.assertRaises(ValueError):
            replace(self.hypothesis, target_pairs=5)
        with self.assertRaises(ValueError):
            replace(self.hypothesis, target_pairs=True)
        with self.assertRaises(ValueError):
            replace(self.hypothesis, minimum_effect_bps=0)

    def test_mcnemar_exact_and_invalid_inputs(self):
        self.assertEqual(exact_mcnemar_p(0, 0), 1.0)
        self.assertAlmostEqual(exact_mcnemar_p(0, 8), 2 / 256)
        self.assertEqual(exact_mcnemar_p(6, 6), 1.0)
        for invalid in ((-1, 4), (True, 1), (100, 100)):
            with self.assertRaises(ValueError):
                exact_mcnemar_p(*invalid)


if __name__ == "__main__":
    unittest.main()
