"""Offline contract tests for STAR's practice-only hypothesis comparisons."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import unittest

from star.active_practice import ActivePracticePlanner
from star.game_mechanic_probe_lab import (
    GameMechanicProbeLab, MechanicAdvice, MechanicHypothesis,
)
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry

PRACTICE = hashlib.sha256(b"fixture-practice-must-never-be-production").digest()
VALIDATION = hashlib.sha256(b"fixture-validation-must-never-be-production").digest()
EVIDENCE = hashlib.sha256(b"offline-fake-independent-observation").hexdigest()
NOW = 2_000_000_000


def status(*, live=False, active=True, fps=70.0, free=4096., backlog=0.):
    return StreamTelemetry(live, active, free, 8192., fps, backlog)


class GameMechanicProbeTests(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.planner = ActivePracticePlanner(self.bank, spacing_seconds=1)
        self.hypothesis = MechanicHypothesis("jump_choice", "pit1", "short", "long")
        self.lab = self.make_lab()
        self.sequence = 0

    def tearDown(self):
        self.bank.close()

    def make_lab(self, hypotheses=None, *, bank=None, planner=None, game="obby", version="v1"):
        return GameMechanicProbeLab(
            bank or self.bank, planner or self.planner,
            game_id=game, game_version=version, objective_id="finish",
            hypotheses=(self.hypothesis,) if hypotheses is None else hypotheses,
        )

    def add(self, *, action="short", outcome="success", split="practice",
            run_id=None, game="obby", version="v1", situation="pit1",
            timestamp=NOW, ingest_at=NOW):
        self.sequence += 1
        trial = GameTrial(
            f"mechanic_trial_{self.sequence}", game, version, "finish", situation,
            action, run_id or f"mechanic_run_{self.sequence}", split,
            outcome, EVIDENCE, timestamp)
        key = PRACTICE if split == "practice" else VALIDATION
        signature = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, signature, now_unix_s=ingest_at)
        return trial

    def suggest(self, now=NOW, telemetry=None, lab=None):
        return (lab or self.lab).suggest(
            now_unix_s=now, telemetry=status() if telemetry is None else telemetry)

    def enable(self):
        self.lab.enable(owner_approved=True)
        self.planner.enable(owner_approved=True)

    def test_opt_in_is_required_for_lab_and_planner(self):
        self.assertEqual(self.suggest().reason, "owner_opt_in_missing")
        for flag in (False, 1, "yes", None):
            with self.subTest(flag=flag):
                with self.assertRaises(PermissionError):
                    self.lab.enable(owner_approved=flag)
        self.lab.enable(owner_approved=True)
        self.assertEqual(self.suggest().reason,
                         "underlying_practice_planner_owner_opt_in_missing")
        self.planner.enable(owner_approved=True)
        result = self.suggest()
        self.assertEqual(result.status, "practice_candidate")
        self.assertFalse(result.authorized_to_play)
        self.assertEqual(result.action_id, "short")
        self.assertTrue(result.expected_run_id.startswith("apr_"))

    def test_host_verified_delivery_not_inferred_from_reservation(self):
        self.enable()
        task = self.suggest()
        self.assertFalse(self.lab.finish(
            task.ticket, now_unix_s=NOW, host_reports_recorded=True))
        self.assertEqual(self.lab.metrics()["rejected_unverified"], 1)
        self.assertEqual(self.suggest(now=NOW + 1).action_id, "short")

    def test_matching_signed_run_counts_and_balances_arms(self):
        self.enable()
        one = self.suggest()
        self.add(action=one.action_id, run_id=one.expected_run_id)
        self.assertTrue(self.lab.finish(one.ticket, now_unix_s=NOW,
                                        host_reports_recorded=True))
        two = self.suggest(now=NOW + 1)
        self.assertEqual(two.action_id, "long")
        self.add(action=two.action_id, run_id=two.expected_run_id,
                 timestamp=NOW + 1, ingest_at=NOW + 1)
        self.assertTrue(self.lab.finish(two.ticket, now_unix_s=NOW + 1,
                                        host_reports_recorded=True))
        self.assertEqual(self.lab.metrics()["accepted_signed"], 2)
        three = self.suggest(now=NOW + 2)
        self.assertEqual(three.action_id, "short")
        self.assertEqual((three.baseline_trials, three.candidate_trials), (1, 1))

    def test_no_duplicate_tickets_or_completed_model_claims(self):
        self.enable()
        one = self.suggest()
        self.assertEqual(self.suggest().reason, "signed_practice_pending")
        self.assertFalse(self.lab.finish(one.ticket + 1, now_unix_s=NOW,
                                         host_reports_recorded=True))
        self.assertEqual(self.suggest().reason, "signed_practice_pending")
        self.assertFalse(self.lab.finish(one.ticket, now_unix_s=NOW,
                                         host_reports_recorded=False))
        self.assertEqual(self.lab.metrics()["accepted_signed"], 0)

    def test_independent_holdout_is_invisible(self):
        self.enable()
        for i in range(15):
            self.add(action="short", outcome="failure",
                     split="validation")
            self.add(action="long", outcome="success",
                     split="validation")
        answer = self.suggest()
        self.assertEqual(answer.action_id, "short")
        self.assertEqual((answer.baseline_trials, answer.candidate_trials), (0, 0))
        self.assertNotIn("validation", str(self.lab.metrics()).lower())

    def test_different_game_version_and_situation_are_excluded(self):
        self.enable()
        for i in range(15):
            self.add(action="long", game="other", outcome="success")
            self.add(action="long", version="v2", outcome="success")
            self.add(action="long", situation="pit2", outcome="success")
        answer = self.suggest()
        self.assertEqual((answer.baseline_trials, answer.candidate_trials), (0, 0))

    def test_promising_practice_is_not_promoted_to_mastery(self):
        self.enable()
        for i in range(12):
            self.add(action="short", outcome="failure")
            self.add(action="long", outcome="success")
        report = self.suggest()
        self.assertEqual(report.status, "provisional_candidate")
        self.assertEqual(report.provisional_preference, "long")
        self.assertFalse(report.authorized_to_play)
        self.assertIsNone(report.ticket)
        self.assertIn("independent_holdout_required", report.reason)

    def test_baseline_can_still_win(self):
        self.enable()
        for i in range(12):
            self.add(action="short", outcome="success")
            self.add(action="long", outcome="failure")
        report = self.suggest()
        self.assertEqual(report.status, "retain_baseline")
        self.assertEqual(report.provisional_preference, "short")

    def test_insufficient_evidence_does_not_claim_effect(self):
        self.enable()
        for i in range(11):
            self.add(action="short", outcome="failure")
            self.add(action="long", outcome="success")
        report = self.suggest()
        self.assertEqual(report.status, "practice_candidate")
        self.assertFalse(report.authorized_to_play)

    def test_equal_evidence_stops_bounded_experiment_inconclusive(self):
        h = MechanicHypothesis("equal", "pit1", "short", "long", 8, 8, 0.08)
        lab = self.make_lab((h,))
        lab.enable(owner_approved=True)
        self.planner.enable(owner_approved=True)
        for i in range(8):
            self.add(action="short", outcome="success" if i < 4 else "failure")
            self.add(action="long", outcome="success" if i < 4 else "failure")
        report = self.suggest(lab=lab)
        self.assertEqual(report.status, "inconclusive")
        self.assertIsNone(report.provisional_preference)

    def test_overlapping_intervals_trigger_more_samples(self):
        self.enable()
        for i in range(12):
            self.add(action="short", outcome="success" if i < 6 else "failure")
            self.add(action="long", outcome="success" if i < 7 else "failure")
        self.assertEqual(self.suggest().status, "practice_candidate")

    def test_separate_hypotheses_get_exploration(self):
        other = MechanicHypothesis("2nd", "pit2", "walk", "dash")
        lab = self.make_lab((self.hypothesis, other))
        lab.enable(owner_approved=True)
        self.planner.enable(owner_approved=True)
        for i in range(5):
            self.add(action="short")
            self.add(action="long")
        one = self.suggest(lab=lab)
        self.assertEqual((one.experiment_id, one.action_id), ("2nd", "walk"))

    def test_live_fps_voice_memory_and_missing_sensors_block(self):
        self.enable()
        attempts = (
            (status(live=True), "never_experiment_while_live"),
            (status(fps=49), "game_fps_below_practice_floor"),
            (status(backlog=251), "speech_backlog_protection"),
            (status(free=1000), "insufficient_offline_compute_headroom"),
            (None, "trusted_telemetry_missing"),
        )
        for telemetry, reason in attempts:
            with self.subTest(reason=reason):
                result = self.lab.suggest(now_unix_s=NOW, telemetry=telemetry)
                self.assertEqual((result.status, result.reason), ("deferred", reason))
        self.assertEqual(self.lab.metrics()["suggestions"], 0)

    def test_model_cannot_fake_clock_and_telemetry_types(self):
        self.enable()
        for invalid in (None, True, -1, 0, 1.25, "now"):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    self.lab.suggest(now_unix_s=invalid, telemetry=status())
        with self.assertRaises(TypeError):
            self.lab.suggest(now_unix_s=NOW, telemetry={"fps": 120})
        self.suggest()
        with self.assertRaises(ValueError):
            self.suggest(now=NOW - 1)

    def test_invalid_hypotheses_rejected_before_action(self):
        cases = (
            ("", "pit1", "short", "long"),
            ("x", "pit1", "short", "short"),
            ("x", "bad space", "short", "long"),
            ("x", "pit1", "short", "NOT/ALLOWED"),
        )
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    MechanicHypothesis(*args)
        with self.assertRaises(ValueError):
            MechanicHypothesis("x", "pit", "a", "b", min_trials_per_arm=True)
        with self.assertRaises(ValueError):
            MechanicHypothesis("x", "pit", "a", "b", minimum_effect=float("nan"))
        with self.assertRaises(ValueError):
            self.make_lab(())
        with self.assertRaises(ValueError):
            self.make_lab((self.hypothesis, self.hypothesis))
        with self.assertRaises(ValueError):
            self.make_lab((self.hypothesis,
                           MechanicHypothesis("other", "pit1", "a", "b")))
        with self.assertRaises(ValueError):
            self.make_lab(game="space game")

    def test_immutable_read_model_status_no_private_receipts(self):
        self.enable()
        proposed = self.suggest()
        self.assertIsInstance(proposed, MechanicAdvice)
        self.assertEqual(proposed.reason, "balanced_probe_not_skill_mastery")
        text = str(self.lab.metrics())
        for private in (EVIDENCE, "apr_", "run", "trial", "owner"):
            self.assertNotIn(private, text)

    def test_manual_disable_does_not_reuse_stale_tickets(self):
        self.enable()
        first = self.suggest()
        self.lab.disable()
        self.assertFalse(self.lab.finish(first.ticket, now_unix_s=NOW,
                                         host_reports_recorded=True))
        self.assertEqual(self.suggest().reason, "owner_opt_in_missing")
        self.lab.enable(owner_approved=True)
        self.assertEqual(self.suggest().status, "deferred")

    def test_concurrent_proposals_return_at_most_one_active_ticket(self):
        # SQLite connections in the real bank are thread-affine. A host must
        # invoke that bank on its owning thread; here a thread-safe fake
        # checks the lab/planner reservation locks independently.
        class ThreadSafeBank(GameplaySkillBank):
            def __init__(self):
                pass

            def practice_evidence(self, *args, **kwargs):
                return ()

        bank = ThreadSafeBank()
        planner = ActivePracticePlanner(bank, spacing_seconds=1)
        lab = self.make_lab(bank=bank, planner=planner)
        planner.enable(owner_approved=True)
        lab.enable(owner_approved=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: lab.suggest(now_unix_s=NOW, telemetry=status()),
                range(24)))
        self.assertEqual(sum(r.status == "practice_candidate" for r in results), 1)
        self.assertTrue(lab.metrics()["pending"])

    def test_default_pending_reservation_recovers_at_actual_planner_ttl(self):
        self.enable()
        self.assertEqual(self.planner.reservation_seconds, 90)
        self.assertEqual(self.planner.max_trials_per_action, 24)
        first = self.suggest()
        self.assertEqual(self.suggest(now=NOW + 90).reason,
                         "signed_practice_pending")
        # Default host ticket expires after 90s, NOT after 600s.
        second = self.suggest(now=NOW + 91)
        self.assertEqual(second.status, "practice_candidate")
        self.assertNotEqual(second.ticket, first.ticket)
        self.assertEqual(self.planner.metrics()["expired"], 1)
        self.assertFalse(self.lab.finish(first.ticket, now_unix_s=NOW + 91,
                                         host_reports_recorded=True))

    def test_custom_short_reservation_recovers_on_configured_deadline(self):
        planner = ActivePracticePlanner(
            self.bank, reservation_seconds=10, spacing_seconds=1
        )
        lab = self.make_lab(planner=planner)
        planner.enable(owner_approved=True)
        lab.enable(owner_approved=True)
        first = self.suggest(lab=lab)
        self.assertEqual(self.suggest(now=NOW + 10, lab=lab).reason,
                         "signed_practice_pending")
        next_probe = self.suggest(now=NOW + 11, lab=lab)
        self.assertEqual(next_probe.status, "practice_candidate")
        self.assertNotEqual(next_probe.ticket, first.ticket)
        self.assertEqual(planner.metrics()["expired"], 1)

    def test_default_host_arm_budget_ends_inconclusive_without_stalling(self):
        self.enable()
        # Hypothesis allows 36 attempts, but the default planner only
        # permits 24 per action. A flat comparison must terminate at 24.
        for i in range(24):
            result = "success" if i % 2 else "failure"
            self.add(action="short", outcome=result)
            self.add(action="long", outcome=result)
        screened = self.suggest()
        self.assertEqual(screened.status, "inconclusive")
        self.assertEqual(screened.baseline_trials, 24)
        self.assertEqual(screened.candidate_trials, 24)
        self.assertIsNone(screened.ticket)
        self.assertFalse(self.planner.metrics()["pending"])

    def test_smaller_host_budget_never_bypasses_minimum_evidence(self):
        planner = ActivePracticePlanner(
            self.bank, max_trials_per_action=8, spacing_seconds=1
        )
        hypothesis = MechanicHypothesis(
            "hard_cap", "pit1", "short", "long",
            min_trials_per_arm=12, max_trials_per_arm=36,
        )
        lab = self.make_lab((hypothesis,), planner=planner)
        planner.enable(owner_approved=True)
        lab.enable(owner_approved=True)
        # Strong practice imbalance is STILL insufficient for a preferred
        # arm: the hypothesis requires at least twelve trials per arm.
        for _ in range(8):
            self.add(action="short", outcome="failure")
            self.add(action="long", outcome="success")
        screened = self.suggest(lab=lab)
        self.assertEqual(screened.status, "inconclusive")
        self.assertIsNone(screened.provisional_preference)
        self.assertFalse(screened.authorized_to_play)
        self.assertFalse(planner.metrics()["pending"])

    def test_expired_ticket_eventually_allows_new_probe(self):
        self.enable()
        first = self.suggest()
        again = self.suggest(now=NOW + 601)
        self.assertEqual(again.status, "practice_candidate")
        self.assertNotEqual(again.ticket, first.ticket)
        self.assertFalse(self.lab.finish(first.ticket, now_unix_s=NOW + 601,
                                         host_reports_recorded=True))

    def test_cross_bank_planner_rejected(self):
        other = GameplaySkillBank(practice_key=PRACTICE,
                                  validation_key=VALIDATION)
        try:
            with self.assertRaises(ValueError):
                self.make_lab(bank=other)
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
