"""Offline policy regression checks for Star's advisory practice ladder."""
import unittest

from star.game_learning_ladder import GameLearningLadder, PracticeSituation
from star.gameplay_skill_bank import GameplaySkillBank, PracticeEvidence
from star.stream_budget import StreamTelemetry


class PracticeBankFixture(GameplaySkillBank):
    def __init__(self):
        self.rows = {}

    def practice_evidence(self, game, version, objective, situation, *, now_unix_s):
        assert (game, version, objective) == ("obby", "v1", "finish")
        return self.rows.get(situation, ())

    def add(self, situation, action, trials, successes):
        self.rows[situation] = (PracticeEvidence(action, trials, successes, 100),)


class TestPracticeLadder(unittest.TestCase):
    def setUp(self):
        self.bank = PracticeBankFixture()
        self.ladder = GameLearningLadder(
            self.bank, game_id="obby", game_version="v1", objective_id="finish",
            situations=(PracticeSituation("intro", "jump", 1),
                        PracticeSituation("moving", "timing", 2, ("intro",))))

    def advise(self, telemetry=None):
        snapshot = telemetry if telemetry is not None else StreamTelemetry(
            live=False, game_active=True, free_vram_mib=4096,
            total_vram_mib=8192, game_fps=90, speech_backlog_ms=0)
        return self.ladder.recommend(now_unix_s=100, telemetry=snapshot)

    def test_consent_and_prerequisite_mastery(self):
        self.assertEqual(self.advise().status, "deferred")
        with self.assertRaises(PermissionError):
            self.ladder.enable(owner_approved=False)
        self.ladder.enable(owner_approved=True)
        self.assertEqual(self.advise().situation_id, "intro")
        self.bank.add("intro", "jump", 11, 11)
        self.assertEqual(self.advise().situation_id, "intro")
        self.bank.add("intro", "jump", 20, 20)
        self.assertEqual(self.advise().situation_id, "moving")
        self.bank.add("moving", "timing", 20, 20)
        self.assertEqual(self.advise().status, "complete")

    def test_repeated_failure_requires_diagnosis(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "jump", 12, 0)
        decision = self.advise()
        self.assertEqual(decision.status, "manual_diagnosis")
        self.assertFalse(decision.authorized_to_play)

    def test_live_stream_blocks_training(self):
        self.ladder.enable(owner_approved=True)
        live = StreamTelemetry(live=True, game_active=True, free_vram_mib=4096,
            total_vram_mib=8192, game_fps=90, speech_backlog_ms=0)
        self.assertEqual(self.advise(live).status, "deferred")

    def test_wrong_action_cannot_fake_progress(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "other", 100, 100)
        self.assertEqual(self.advise().practice_trials, 0)

    def test_invalid_dependencies_rejected(self):
        with self.assertRaises(ValueError):
            GameLearningLadder(self.bank, game_id="obby", game_version="v1",
                objective_id="finish", situations=(
                    PracticeSituation("intro", "jump", 1),
                    PracticeSituation("bad", "x", 2, ("unknown",))))
