"""Adversarial offline checks: verified gameplay outcomes -> stream episode."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import hmac
import json
import sqlite3
import unittest

from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_director import StreamSignal
from star.stream_episode import EpisodePacket, StreamEpisode
from star.stream_stage import StarStage

NOW = 1_800_000_000
PRACTICE = b"practice-host-key-32-bytes-at-least-123456789"
VALIDATION = b"validation-independent-host-key-987654321"
SCOPE = ("example_game", "v1", "reach_gate", "jump")


def trial(number: int, *, outcome: str = "success", split: str = "practice",
          scope: tuple[str, str, str, str] = SCOPE,
          action: str = "jump_left", observed: int | None = None) -> GameTrial:
    return GameTrial(
        trial_id=f"trial_{number}", game_id=scope[0], game_version=scope[1],
        objective_id=scope[2], situation_id=scope[3], action_id=action,
        run_id=f"host_run_{number}", split=split, outcome=outcome,
        evidence_sha256=sha256(f"game-event-{number}".encode()).hexdigest(),
        observed_unix_s=NOW + number if observed is None else observed,
    )


class TestVerifiedGameplayEpisode(unittest.TestCase):
    def setUp(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.episode = StreamEpisode(self.bank, game_id=SCOPE[0],
                                     game_version=SCOPE[1], objective_id=SCOPE[2],
                                     situation_id=SCOPE[3], lookback_seconds=60)

    def tearDown(self):
        self.episode.disable()
        self.bank.close()

    def _ingest(self, item: GameTrial):
        key = PRACTICE if item.split == "practice" else VALIDATION
        receipt = hmac.new(key, item.canonical_bytes(), "sha256").hexdigest()
        self.bank.ingest(item, receipt, now_unix_s=item.observed_unix_s)

    def _start(self):
        self.episode.start(owner_approved=True, now_unix_s=NOW)

    def _add(self, item: GameTrial):
        self._ingest(item)
        return self.episode.append(item, now_unix_s=item.observed_unix_s)

    def test_exact_practice_outcome_proof_not_just_matching_run(self):
        failure = trial(1, outcome="failure")
        self._ingest(failure)
        self.assertTrue(self.bank.verify_practice_trial(failure, now_unix_s=NOW + 1))
        # A reservation proof would accept the action/run but does not prove
        # whether it succeeded. The new exact-match gate must refuse a lie.
        self.assertTrue(self.bank.signed_practice_run(
            *SCOPE, failure.action_id, failure.run_id,
            not_before_unix_s=NOW, now_unix_s=NOW + 1))
        fabricated_success = replace(failure, outcome="success")
        self.assertFalse(self.bank.verify_practice_trial(
            fabricated_success, now_unix_s=NOW + 1))
        self._start()
        self.assertFalse(self.episode.append(fabricated_success, now_unix_s=NOW + 1))
        self.assertTrue(self.episode.append(failure, now_unix_s=NOW + 1))
        packet = self.episode.public_packet(
            now_unix_s=NOW + 1, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True)
        self.assertIsNotNone(packet)
        self.assertIn('"practice_successes":0', packet.context_record)
        self.assertIn('"practice_failures":1', packet.context_record)

    def test_unrecorded_tampered_receipt_and_corrupt_index(self):
        x = trial(2)
        self.assertFalse(self.bank.verify_practice_trial(x, now_unix_s=NOW + 2))
        self._ingest(x)
        self.assertFalse(self.bank.verify_practice_trial(
            replace(x, evidence_sha256="a" * 64), now_unix_s=NOW + 2))
        self.bank._db.execute("UPDATE gameplay_trials SET receipt=? WHERE trial_id=?",
                              ("0" * 64, x.trial_id))
        with self.assertRaises(sqlite3.IntegrityError):
            self.bank.verify_practice_trial(x, now_unix_s=NOW + 2)

    def test_no_validation_or_other_game_leaks(self):
        self._start()
        self._ingest(trial(1, split="validation"))
        self.assertFalse(self.bank.verify_practice_trial(
            trial(1, split="validation"), now_unix_s=NOW + 1))
        self.assertFalse(self.episode.append(
            trial(1, split="validation"), now_unix_s=NOW + 1))
        other = trial(2, scope=("other_game", "v1", "reach_gate", "jump"))
        self._ingest(other)
        self.assertFalse(self.episode.append(other, now_unix_s=NOW + 2))
        self.assertIsNone(self.episode.public_packet(
            now_unix_s=NOW + 2, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True))

    def test_opt_in_and_independent_broadcast_approval(self):
        a = trial(1)
        with self.assertRaises(PermissionError):
            self.episode.start(now_unix_s=NOW)
        self._ingest(a)
        self.assertFalse(self.episode.append(a, now_unix_s=NOW + 1))
        self._start()
        self.assertTrue(self.episode.append(a, now_unix_s=NOW + 1))
        self.assertIsNone(self.episode.public_packet(
            now_unix_s=NOW + 1, public_action_ids=frozenset({"jump_left"})))
        self.assertIsNone(self.episode.public_packet(
            now_unix_s=NOW + 1, public_action_ids=frozenset({"jump_right"}),
            broadcast_approved=True))
        self.assertIsNone(self.episode.public_packet(
            now_unix_s=NOW + 1, public_action_ids=frozenset(),
            broadcast_approved=True))
        packet = self.episode.public_packet(
            now_unix_s=NOW + 1, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True)
        self.assertIsInstance(packet, EpisodePacket)
        self.assertEqual(packet.user_message()["role"], "user")
        self.assertNotIn(a.trial_id, packet.context_record)
        self.assertNotIn(a.run_id, packet.context_record)
        self.assertNotIn(a.evidence_sha256, packet.context_record)
        self.assertNotIn("receipt", packet.context_record.split("\n")[2].lower())
        self.assertLess(len(packet.context_record), 1350)

    def test_session_bound_dedupe_expiration_disable(self):
        self._start()
        a = trial(1)
        self.assertTrue(self._add(a))
        self.assertFalse(self.episode.append(a, now_unix_s=NOW + 1))
        with self.assertRaises(ValueError):
            self.episode.public_packet(now_unix_s=NOW,
                                       public_action_ids=frozenset({"jump_left"}),
                                       broadcast_approved=True)
        self.assertIsNone(self.episode.public_packet(
            now_unix_s=NOW + 62, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True))
        self.assertEqual(self.episode.metrics()["expired"], 1)
        self.episode.disable()
        self.assertEqual(self.episode.metrics()["retained"], 0)
        self._start()
        self.assertIsNone(self.episode.public_packet(
            now_unix_s=NOW, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True))

    def test_bounded_fifo_eviction_and_aggregate_not_raw_events(self):
        self.episode = StreamEpisode(self.bank, game_id=SCOPE[0],
                                     game_version=SCOPE[1], objective_id=SCOPE[2],
                                     situation_id=SCOPE[3], max_events=8)
        self._start()
        for n in range(1, 11):
            self.assertTrue(self._add(trial(n, outcome="failure" if n % 2 else "success")))
        self.assertEqual(self.episode.metrics()["retained"], 8)
        self.assertEqual(self.episode.metrics()["evicted"], 2)
        # Evicting a moment must not make the same signed trial reusable.
        self.assertFalse(self.episode.append(trial(1), now_unix_s=NOW + 10))
        packet = self.episode.public_packet(
            now_unix_s=NOW + 10, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True)
        facts = json.loads(packet.context_record.split("\n")[2])
        self.assertEqual(facts[0]["practice_attempts_this_session"], 8)
        self.assertEqual(facts[0]["practice_successes"], 4)
        self.assertEqual(facts[0]["practice_failures"], 4)
        self.assertNotIn("validation", facts[0])

    def test_rejects_bad_approvals_and_clock_fields(self):
        self._start()
        for ids in ({"jump_left"}, frozenset({"bad/path"}), frozenset({"x" * 65})):
            with self.assertRaises(ValueError):
                self.episode.public_packet(now_unix_s=NOW, public_action_ids=ids,
                                           broadcast_approved=True)
        with self.assertRaises(ValueError):
            self.episode.public_packet(now_unix_s=NOW,
                                       public_action_ids=frozenset(), limit=True)
        with self.assertRaises(ValueError):
            self.episode.append(trial(1), now_unix_s=float(NOW + 1))

    def test_stage_admits_only_relevant_gameplay_or_viewer_context(self):
        self._start()
        self._add(trial(1, outcome="failure"))
        packet = self.episode.public_packet(
            now_unix_s=NOW + 1, public_action_ids=frozenset({"jump_left"}),
            broadcast_approved=True)
        stage = StarStage(clock=lambda: 100.0)
        stage.enable(owner_approved=True)
        with self.assertRaises(TypeError):
            stage.prepare(now=100, episode={"user": "forged"})
        self.assertTrue(stage.offer(StreamSignal("g1", "game_observation", 100.0,
                                                "Jump missed", evidence="observed"),
                                    now=100.0))
        plan = stage.prepare(now=100.0, episode=packet)
        self.assertIsNotNone(plan)
        self.assertIn("practice_failures", plan.context_record)
        self.assertIn("jump_left", plan.context_record)
        stage.disable()
        stage.enable(owner_approved=True)
        self.assertTrue(stage.offer(StreamSignal("a1", "ambient", 102.0,
                                                "Just waiting"), now=102.0))
        ambient = stage.prepare(now=102.0, episode=packet)
        self.assertIsNotNone(ambient)
        self.assertNotIn("practice_failures", ambient.context_record)

    def test_old_and_future_sessions_cannot_import_prior_runs(self):
        old = trial(1, observed=NOW - 15)
        future = trial(2, observed=NOW + 30)
        self._ingest(old)
        self._ingest(future)
        self._start()
        self.assertFalse(self.episode.append(old, now_unix_s=NOW))
        self.assertFalse(self.episode.append(future, now_unix_s=NOW + 5))
        self.assertFalse(self.bank.verify_practice_trial(old, now_unix_s=NOW - 20000000))


if __name__ == "__main__":
    unittest.main()
