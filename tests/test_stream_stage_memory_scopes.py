"""Adversarial offline stage handoffs for verified, public-approved memory packets."""
from __future__ import annotations

import unittest

from star.stream_director import StreamSignal
from star.stream_episode import EpisodePacket
from star.stream_continuity import ContinuityPacket
from star.stream_stage import StarStage


class MemoryScopeTests(unittest.TestCase):
    def stage(self) -> StarStage:
        stage = StarStage(clock=lambda: 100.0)
        stage.enable(owner_approved=True)
        stage.transition_game(game_scope="episode.game_B", owner_approved=True, now=100)
        return stage

    @staticmethod
    def question(stage: StarStage, ident: str = "chatA") -> None:
        assert stage.offer(StreamSignal(
            ident, "viewer_question", 100.0, "What did you practice?",
            speaker_id="viewerA"
        ), now=100, moderated=True)

    def test_older_game_episode_never_leaks_into_new_game_reaction(self):
        s = self.stage()
        self.assertTrue(s.offer(StreamSignal(
            "gameB1", "game_observation", 100.0, "New map appears",
            evidence="observed", game_scope="episode.game_B"
        ), now=100))
        old = EpisodePacket(("jump",), "OLD_GAME_PRIVATE_PRACTICE", "episode.game_A")
        plan = s.prepare(now=100, episode=old, current_game_scope="episode.game_B")
        self.assertIsNotNone(plan)
        self.assertNotIn("OLD_GAME_PRIVATE_PRACTICE", plan.context_record)

    def test_director_binding_alone_blocks_old_memory_even_without_host_scope(self):
        s = self.stage()
        self.question(s)
        old = EpisodePacket(("jump",), "GAME_A_WITH_NO_HOST_SCOPE", "episode.game_A")
        plan = s.prepare(now=100, episode=old)
        self.assertIsNotNone(plan)
        self.assertNotIn("GAME_A_WITH_NO_HOST_SCOPE", plan.context_record)
        self.assertEqual(s.metrics()["off_game_memory"], 1)

    def test_past_game_memory_not_attached_to_unrelated_current_game_question(self):
        s = self.stage()
        self.question(s)
        old = ContinuityPacket(("jump",), "OLD_GAME_PAST_WINS", "episode.game_A")
        plan = s.prepare(now=100, continuity=old, current_game_scope="episode.game_B")
        self.assertIsNotNone(plan)
        self.assertNotIn("OLD_GAME_PAST_WINS", plan.context_record)

    def test_matching_game_scope_retains_grounded_context(self):
        s = self.stage()
        self.question(s)
        recent = EpisodePacket(("jump",), "GAME_B_VERIFIED_PRACTICE", "episode.game_B")
        past = ContinuityPacket(("jump",), "GAME_B_OLDER_PRACTICE", "episode.game_B")
        plan = s.prepare(now=100, episode=recent, continuity=past,
                         current_game_scope="episode.game_B")
        self.assertIsNotNone(plan)
        self.assertIn("GAME_B_VERIFIED_PRACTICE", plan.context_record)
        self.assertIn("GAME_B_OLDER_PRACTICE", plan.context_record)

    def test_unscoped_packet_or_disagreeing_host_scope_does_not_leak(self):
        s = self.stage()
        self.question(s)
        old = EpisodePacket(("jump",), "UNSCOPED_SENSITIVE")
        past = ContinuityPacket(("jump",), "SCOPE_MISMATCH", "episode.game_B")
        plan = s.prepare(now=100, episode=old, continuity=past,
                         current_game_scope="episode.game_A")
        self.assertIsNotNone(plan)
        self.assertNotIn("UNSCOPED_SENSITIVE", plan.context_record)
        self.assertNotIn("SCOPE_MISMATCH", plan.context_record)

    def test_game_to_no_game_transition_silences_old_memory(self):
        s = self.stage()
        s.transition_game(game_scope="", owner_approved=True, now=100)
        self.question(s)
        old = EpisodePacket(("jump",), "STALE_WHEN_NOT_PLAYING", "episode.game_B")
        plan = s.prepare(now=100, episode=old)
        self.assertIsNotNone(plan)
        self.assertNotIn("STALE_WHEN_NOT_PLAYING", plan.context_record)


if __name__ == "__main__":
    unittest.main()
