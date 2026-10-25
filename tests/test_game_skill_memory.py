"""Deterministic offline regression checks; never an actual gameplay claim."""
import unittest

from star.game_skill_memory import Episode, GameSkillMemory, wilson_lower_95

SHA = "f" * 64


def ep(*, game="obby", session="s1", seq=1, state="start", action="jump", success=True,
       unsafe=False, elapsed_ms=250, evidence_sha256=SHA):
    return Episode(game, session, seq, state, action, success, unsafe, elapsed_ms, evidence_sha256)


class GameSkillMemoryTests(unittest.TestCase):
    def test_cold_game_abstains(self):
        memory = GameSkillMemory()
        advice = memory.advise("obby", "start", ("jump",))
        self.assertIsNone(advice.action)
        self.assertEqual(advice.reason, "insufficient_safe_evidence")

    def test_verified_host_required(self):
        memory = GameSkillMemory()
        with self.assertRaises(PermissionError):
            memory.record(ep())
        self.assertEqual(memory.summary()["episodes"], 0)

    def test_host_asserted_success_is_not_proof_authentication(self):
        memory = GameSkillMemory()
        memory.record(ep(), trusted_host=True)
        self.assertEqual(memory.evidence("obby", "start", "jump").trials, 1)

    def test_replay_rejected(self):
        memory = GameSkillMemory()
        memory.record(ep(), trusted_host=True)
        with self.assertRaises(ValueError):
            memory.record(ep(), trusted_host=True)
        self.assertEqual(memory.summary()["episodes"], 1)

    def test_out_of_order_across_states(self):
        memory = GameSkillMemory()
        memory.record(ep(seq=2), trusted_host=True)
        with self.assertRaises(ValueError):
            memory.record(ep(seq=1, state="boss"), trusted_host=True)

    def test_strict_game_and_state_scope(self):
        memory = GameSkillMemory()
        for i in range(1, 41):
            memory.record(ep(session=f"s{i}"), trusted_host=True)
        self.assertEqual(memory.advise("obby", "start", ("jump",)).action, "jump")
        self.assertIsNone(memory.advise("other", "start", ("jump",)).action)
        self.assertIsNone(memory.advise("obby", "boss", ("jump",)).action)

    def test_observed_unsafe_vetoes_success(self):
        memory = GameSkillMemory()
        for i in range(1, 41):
            memory.record(ep(session=f"s{i}", success=i != 40, unsafe=i == 40), trusted_host=True)
        self.assertIsNone(memory.advise("obby", "start", ("jump",)).action)

    def test_practice_requires_host_approval(self):
        memory = GameSkillMemory()
        self.assertIsNone(memory.advise("obby", "start", ("left", "right"), mode="practice").action)
        self.assertEqual(memory.advise("obby", "start", ("right", "left"), mode="practice",
                                       sandbox_approved=True).action, "left")

    def test_practice_least_tried(self):
        memory = GameSkillMemory()
        memory.record(ep(action="left"), trusted_host=True)
        advice = memory.advise("obby", "start", ("left", "right"), mode="practice", sandbox_approved=True)
        self.assertEqual(advice.action, "right")

    def test_practice_rejects_known_unsafe(self):
        memory = GameSkillMemory()
        memory.record(ep(action="left", success=False, unsafe=True), trusted_host=True)
        choice = memory.advise("obby", "start", ("left", "right"), mode="practice", sandbox_approved=True)
        self.assertEqual(choice.action, "right")

    def test_practice_all_unsafe_abstains(self):
        memory = GameSkillMemory()
        memory.record(ep(action="left", success=False, unsafe=True), trusted_host=True)
        self.assertIsNone(memory.advise("obby", "start", ("left",), mode="practice", sandbox_approved=True).action)

    def test_chooses_more_reliable_action(self):
        memory = GameSkillMemory()
        for i in range(1, 81):
            memory.record(ep(session=f"s{i}", action="jump", success=i % 5 != 0), trusted_host=True)
        for i in range(81, 121):
            memory.record(ep(session=f"s{i}", action="walk", success=i % 3 == 0), trusted_host=True)
        self.assertEqual(memory.advise("obby", "start", ("jump", "walk")).action, "jump")

    def test_conservative_small_sample(self):
        memory = GameSkillMemory()
        for i in range(1, 9):
            memory.record(ep(session=f"s{i}"), trusted_host=True)
        self.assertIsNone(memory.advise("obby", "start", ("jump",)).action)
        self.assertLess(wilson_lower_95(8, 8), 0.7)

    def test_repeats_in_one_session_are_not_independent_trials(self):
        memory = GameSkillMemory()
        for i in range(1, 101):
            memory.record(ep(seq=i), trusted_host=True)
        evidence = memory.evidence("obby", "start", "jump")
        self.assertEqual(evidence.trials, 1)
        self.assertEqual(evidence.successes, 1)
        self.assertIsNone(memory.advise("obby", "start", ("jump",)).action)

    def test_failed_attempt_reverses_same_session_success(self):
        memory = GameSkillMemory()
        memory.record(ep(seq=1, elapsed_ms=100), trusted_host=True)
        memory.record(ep(seq=2, success=False, elapsed_ms=500), trusted_host=True)
        memory.record(ep(seq=3, success=True), trusted_host=True)
        evidence = memory.evidence("obby", "start", "jump")
        self.assertEqual((evidence.trials, evidence.successes, evidence.mean_duration_ms), (1, 0, None))

    def test_unsafe_attempt_flags_full_session(self):
        memory = GameSkillMemory()
        memory.record(ep(seq=1), trusted_host=True)
        memory.record(ep(seq=2, success=False, unsafe=True), trusted_host=True)
        self.assertEqual(memory.evidence("obby", "start", "jump").unsafe_observations, 1)

    def test_wilson_inputs(self):
        for n, wins in ((-1, 0), (1, 2), (True, 1), (2, True)):
            with self.assertRaises(ValueError):
                wilson_lower_95(wins, n)

    def test_wilson_improves_with_evidence(self):
        self.assertGreater(wilson_lower_95(100, 100), wilson_lower_95(8, 8))
        self.assertEqual(wilson_lower_95(0, 0), 0)

    def test_no_cross_session_monotonic_restriction(self):
        memory = GameSkillMemory()
        memory.record(ep(session="a", seq=9), trusted_host=True)
        memory.record(ep(session="b", seq=1), trusted_host=True)
        self.assertEqual(memory.summary()["sessions"], 2)

    def test_record_capacity_fails_closed(self):
        memory = GameSkillMemory(max_episodes=1)
        memory.record(ep(), trusted_host=True)
        with self.assertRaises(OverflowError):
            memory.record(ep(seq=2), trusted_host=True)
        self.assertEqual(memory.summary()["episodes"], 1)

    def test_session_capacity_fails_closed(self):
        memory = GameSkillMemory(max_sessions=1)
        memory.record(ep(), trusted_host=True)
        with self.assertRaises(OverflowError):
            memory.record(ep(session="s2"), trusted_host=True)

    def test_malformed_records(self):
        bad = [dict(seq=True), dict(game="../secrets"), dict(unsafe="true"),
               dict(evidence_sha256="0"), dict(elapsed_ms=-1), dict(success=True, unsafe=True)]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                ep(**change)

    def test_malformed_actions(self):
        memory = GameSkillMemory()
        for opts in (("a", "a"), (), tuple("a" + str(i) for i in range(33)), ("../bad",)):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                memory.advise("obby", "start", opts)

    def test_explicit_thresholds(self):
        memory = GameSkillMemory()
        with self.assertRaises(ValueError):
            memory.advise("obby", "start", ("a",), min_trials=2)
        with self.assertRaises(ValueError):
            memory.advise("obby", "start", ("a",), minimum_lower=0.1)
        with self.assertRaises(ValueError):
            memory.advise("obby", "start", ("a",), mode="stream")

    def test_no_io_and_summary_only_counts(self):
        memory = GameSkillMemory()
        memory.record(ep(), trusted_host=True)
        self.assertEqual(set(memory.summary()), {"sessions", "episodes", "state_actions"})


if __name__ == "__main__":
    unittest.main()
