"""Deterministic offline tests: signed practice, holdout blindness, FPS protection."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import sqlite3
import unittest

from star.active_practice import ActivePracticePlanner
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry

PRACTICE = hashlib.sha256(b"offline-fixture-practice-not-a-real-secret").digest()
HOLDOUT = hashlib.sha256(b"offline-fixture-holdout-not-a-real-secret").digest()
NOW = 2_000_000_000
HASH = hashlib.sha256(b"synthetic fixture evidence only").hexdigest()


def telemetry(*, live=False, active=True, fps=60., free=4096.,
              backlog=0.) -> StreamTelemetry:
    return StreamTelemetry(live, active, free, 8192., fps, backlog)


class ActivePracticeTests(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=HOLDOUT)
        self.planner = ActivePracticePlanner(self.bank)
        self.planner.enable(owner_approved=True)
        self.seq = 0

    def tearDown(self):
        self.bank.close()

    def add(self, *, action="jump", split="practice", outcome="success",
            game="obby", version="v1", objective="cross", situation="bridge",
            timestamp=NOW, ingest_at=NOW, run_id=None):
        self.seq += 1
        trial = GameTrial(
            f"trial{self.seq}", game, version, objective, situation, action,
            f"run{self.seq}" if run_id is None else run_id,
            split, outcome, HASH, timestamp)
        signer = PRACTICE if split == "practice" else HOLDOUT
        receipt = hmac.new(signer, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, receipt, now_unix_s=ingest_at)
        return trial

    def reserve(self, action_ids=("jump", "dodge"), *, now=NOW,
                measurements=None, planner=None):
        return (planner or self.planner).reserve(
            "obby", "v1", "cross", "bridge", action_ids,
            now_unix_s=now, telemetry=telemetry() if measurements is None else measurements)

    def test_requires_exact_owner_consent_and_starts_without_game_io(self):
        other = ActivePracticePlanner(self.bank)
        with self.assertRaises(PermissionError):
            other.enable()
        with self.assertRaises(PermissionError):
            other.enable(owner_approved=1)
        self.assertEqual(self.reserve(planner=other).reason, "owner_opt_in_missing")
        other.enable(owner_approved=True)
        decision = self.reserve(planner=other)
        self.assertFalse(decision.authorized_to_control_game)
        self.assertEqual(decision.status, "practice_candidate")
        self.assertEqual(decision.reason, "coverage_first")
        self.assertIsInstance(decision.ticket, int)
        self.assertTrue(decision.expected_run_id.startswith("apr_"))
        self.assertEqual(other.metrics()["verified"], 0)

    def test_no_inference_when_live_or_voice_or_gameplay_overloaded(self):
        for t, expected in [
            (telemetry(live=True), "stream_is_live"),
            (telemetry(fps=49), "game_fps_below_practice_floor"),
            (telemetry(backlog=251), "voice_backlog_too_high"),
            (telemetry(free=1000), "insufficient_offline_compute_headroom"),
        ]:
            with self.subTest(reason=expected):
                decision = self.reserve(measurements=t)
                self.assertEqual((decision.status, decision.reason),
                                 ("deferred", expected))
        self.assertFalse(self.planner.metrics()["pending"])
        self.assertEqual(self.planner.metrics()["offered"], 0)

    def test_telemetry_missing_fails_conservatively(self):
        decision = self.planner.reserve(
            "obby", "v1", "cross", "bridge", ["jump"],
            now_unix_s=NOW, telemetry=None)
        self.assertEqual(decision.reason, "telemetry_missing")

    def test_first_cover_untried_actions_and_verify_signed_evidence(self):
        first = self.reserve()
        self.assertEqual(first.action_id, "dodge")
        self.assertEqual(first.prior_trials, 0)
        self.assertEqual(self.reserve().reason, "practice_ticket_in_flight")
        self.assertFalse(self.planner.finish(first.ticket, now_unix_s=NOW,
                                             host_reports_recorded=True))
        self.assertEqual(self.planner.metrics()["verified"], 0)
        self.assertEqual(self.reserve(now=NOW + 1).reason, "practice_spacing_budget")

        second = self.reserve(now=NOW + 2)
        self.assertEqual(second.action_id, "dodge")  # no signed trial was added
        self.add(action="dodge", timestamp=NOW + 2, ingest_at=NOW + 2,
                 run_id=second.expected_run_id)
        self.assertTrue(self.planner.finish(
            second.ticket, now_unix_s=NOW + 2, host_reports_recorded=True))
        next_one = self.reserve(now=NOW + 4)
        self.assertEqual(next_one.action_id, "jump")  # now the least tested action
        self.assertFalse(next_one.authorized_to_control_game)

    def test_practice_but_not_holdout_is_visible_for_curriculum(self):
        self.add(action="jump", outcome="failure")
        for _ in range(14):
            self.add(action="dodge", split="validation", outcome="success")
        rows = self.bank.practice_evidence(
            "obby", "v1", "cross", "bridge", now_unix_s=NOW)
        self.assertEqual([(r.action_id, r.trials, r.successes) for r in rows],
                         [("jump", 1, 0)])
        decision = self.reserve(("jump", "dodge"))
        self.assertEqual(decision.action_id, "dodge")
        self.assertNotIn("validation", str(self.planner.metrics()).lower())

    def test_independent_holdout_does_not_change_picked_action(self):
        for _ in range(3):
            self.add(action="jump", outcome="success")
        for _ in range(3):
            self.add(action="dodge", outcome="failure")
        for _ in range(20):
            self.add(action="dodge", split="validation", outcome="success")
        first = self.reserve()
        self.assertEqual(first.reason, "uncertainty_guided")
        self.assertEqual(first.action_id, "dodge")
        self.assertFalse(self.planner.finish(first.ticket, now_unix_s=NOW))
        for _ in range(20):
            self.add(action="jump", split="validation", outcome="failure")
        second = self.reserve(now=NOW + 2)
        self.assertEqual(second.action_id, first.action_id)
        self.assertEqual(second.priority_score, first.priority_score)

    def test_moderately_challenging_beats_easy_after_coverage(self):
        for i in range(4):
            self.add(action="balanced", outcome="success" if i < 2 else "failure")
            self.add(action="mastered", outcome="success")
        decision = self.reserve(("mastered", "balanced"))
        self.assertEqual(decision.reason, "uncertainty_guided")
        self.assertEqual(decision.action_id, "balanced")

    def test_no_false_achievement_from_unsigned_or_wrong_split(self):
        first = self.reserve(["jump"])
        self.add(action="jump", split="validation")
        self.assertFalse(self.planner.finish(
            first.ticket, now_unix_s=NOW, host_reports_recorded=True))
        second = self.reserve(["jump"], now=NOW + 2)
        self.add(action="dodge", split="practice", timestamp=NOW + 2, ingest_at=NOW + 2)
        self.assertFalse(self.planner.finish(
            second.ticket, now_unix_s=NOW + 2, host_reports_recorded=True))
        self.assertEqual(self.planner.metrics()["unverified"], 2)

    def test_old_signed_trials_not_passed_off_as_new_learning(self):
        self.add(action="jump")
        first = self.reserve(["jump"])
        self.assertFalse(self.planner.finish(
            first.ticket, now_unix_s=NOW, host_reports_recorded=True))

    def test_stale_signed_evidence_not_used_for_current_learning(self):
        self.add(action="jump")
        later = NOW + 91 * 86400
        rows = self.bank.practice_evidence("obby", "v1", "cross", "bridge",
                                           now_unix_s=later)
        self.assertEqual(rows, ())
        choice = self.reserve(["jump"], now=later)
        self.assertEqual(choice.prior_trials, 0)

    def test_scope_and_game_version_isolation(self):
        for field in [{"version": "v2"}, {"situation": "ramp"},
                      {"game": "arena"}, {"objective": "boss"}]:
            self.add(action="jump", **field)
        choice = self.reserve(["jump"])
        self.assertEqual(choice.prior_trials, 0)

    def test_invalid_receipt_or_mutated_sqlite_fails_closed(self):
        self.add()
        self.bank._db.execute(
            "UPDATE gameplay_trials SET payload_json = "
            "REPLACE(payload_json, 'success', 'failure')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve(["jump"])
        self.assertFalse(self.planner.metrics()["pending"])

    def test_database_identity_tampering_fails_closed(self):
        self.add()
        self.bank._db.execute("UPDATE gameplay_trials SET run_id='forged'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.bank.practice_evidence("obby", "v1", "cross", "bridge",
                                        now_unix_s=NOW)

    def test_duplicate_run_fails_closed(self):
        trial = self.add()
        sig = hmac.new(PRACTICE, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        with self.assertRaises(sqlite3.IntegrityError):
            self.bank.ingest(trial, sig, now_unix_s=NOW)
        self.assertEqual(self.reserve(["jump"]).prior_trials, 1)

    def test_existing_ticket_backpressures_concurrent_callers(self):
        # SQLite's practice evidence reader is deliberately confined to its
        # creator thread; callers with an in-flight ticket never touch it.
        first = self.reserve()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.reserve(), range(36)))
        self.assertTrue(all(x.reason == "practice_ticket_in_flight" for x in results))
        self.assertEqual(self.planner.metrics()["offered"], 1)
        self.assertTrue(self.planner.metrics()["pending"])
        self.assertIsInstance(first.ticket, int)

    def test_expiring_ticket_never_counts_learning(self):
        first = self.reserve(["jump"])
        second = self.reserve(["jump"], now=NOW + 91)
        self.assertEqual(second.status, "practice_candidate")
        self.assertNotEqual(first.ticket, second.ticket)
        self.assertFalse(self.planner.finish(
            first.ticket, now_unix_s=NOW + 91, host_reports_recorded=True))
        self.assertEqual(self.planner.metrics()["expired"], 1)
        self.assertTrue(self.planner.metrics()["pending"])

    def test_disable_invalidates_ticket_and_prevents_replay(self):
        first = self.reserve(["jump"])
        self.planner.disable()
        self.assertFalse(self.planner.finish(first.ticket, now_unix_s=NOW))
        self.planner.enable(owner_approved=True)
        second = self.reserve(["jump"], now=NOW)
        self.assertGreater(second.ticket, first.ticket)

    def test_exhausted_practice_budget_defers(self):
        planner = ActivePracticePlanner(self.bank, max_trials_per_action=8)
        planner.enable(owner_approved=True)
        for _ in range(8):
            self.add(action="jump")
        response = self.reserve(["jump"], planner=planner)
        self.assertEqual(response.reason, "practice_budget_exhausted")
        self.assertFalse(response.authorized_to_control_game)

    def test_invalid_action_rosters_and_parameters_refused(self):
        for bad in ([], ["a"] * 33, ["jump", "jump"], ["../../etc"],
                    ["paste Lua here"], ["", "jump"], "jump", [True], [1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.reserve(bad)
        for kwargs in ({"reservation_seconds": 0}, {"max_trials_per_action": 2},
                       {"spacing_seconds": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ActivePracticePlanner(self.bank, **kwargs)

    def test_clock_rollback_and_strict_flags_rejected(self):
        first = self.reserve()
        with self.assertRaises(ValueError):
            self.planner.finish(first.ticket, now_unix_s=NOW - 1)
        with self.assertRaises(ValueError):
            self.planner.finish(first.ticket, now_unix_s=NOW,
                                host_reports_recorded=1)
        with self.assertRaises(ValueError):
            self.planner.finish(True, now_unix_s=NOW)
        self.assertTrue(self.planner.metrics()["pending"])

    def test_no_personal_info_or_key_material_in_metrics(self):
        self.add()
        self.reserve(["jump"])
        metrics = str(self.planner.metrics())
        self.assertNotIn("run1", metrics)
        self.assertNotIn(PRACTICE.hex(), metrics)
        self.assertNotIn(HOLDOUT.hex(), metrics)
        self.assertNotIn("obby", metrics)


if __name__ == "__main__":
    unittest.main()
