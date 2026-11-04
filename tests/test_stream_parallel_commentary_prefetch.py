"""Offline adversarial tests for background commentary text; never uses OBS/TTS."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import math
import unittest

from star.stream_director import StreamSignal
from star.stream_parallel_commentary_prefetch import (
    PrefetchTicket, StreamParallelCommentaryPrefetch,
)
from star.stream_stage import StarStage


class PrefetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.time = 100.0
        self.stage = StarStage(clock=lambda: self.time)
        self.stage.enable(owner_approved=True)
        self.first = StreamSignal("first", "viewer_question", 100.0,
                                  "How is your game?", speaker_id="viewer-x")
        self.assertTrue(self.stage.offer(self.first, now=100, moderated=True))
        self.audible = self.stage.prepare(now=100)
        assert self.audible is not None
        self.assertTrue(self.stage.queue_audio(self.audible, now=100.01))
        self.assertTrue(self.stage.acknowledge_audible(self.audible, now=100.02))
        self.prefetch = StreamParallelCommentaryPrefetch()
        self.prefetch.enable(owner_approved=True)
        self.next = StreamSignal("next", "game_observation", 100.1,
                                 "A red gate just opened", evidence="observed",
                                 game_scope="game.level1")
        self.assertTrue(self.stage.offer(self.next, now=100.2))

    def reserve(self, signal=None, **kwargs):
        opts = dict(stage=self.stage, audible_plan=self.audible, now_s=100.2,
                    model_epoch=11, scene_epoch=3, host_verified=True,
                    moderated_source=True, spare_compute=True)
        opts.update(kwargs)
        return self.prefetch.reserve(signal or self.next, **opts)

    def choose(self, now=103.3):
        self.time = now
        self.assertTrue(self.stage.finish(self.audible, now=101, played_to_end=True))
        plan = self.stage.prepare(now=now, current_game_scope="game.level1")
        self.assertIsNotNone(plan)
        return plan

    def take(self, ticket, plan, **kwargs):
        opts = dict(stage=self.stage, plan=plan, now_s=103.3, model_epoch=11,
                    scene_epoch=3, host_verified=True, spare_compute=True)
        opts.update(kwargs)
        return self.prefetch.take_for_plan(ticket, **opts)

    def test_success_parallel_draft_is_single_use_and_cannot_play_audio(self):
        ticket = self.reserve()
        self.assertIsNotNone(ticket)
        self.assertTrue(self.prefetch.complete(
            ticket, text="That red gate finally opened!", now_s=100.5,
            model_epoch=11, host_moderated=True))
        plan = self.choose()
        result = self.take(ticket, plan)
        self.assertEqual(result.text, "That red gate finally opened!")
        self.assertFalse(result.authorizes_audio_output)
        self.assertFalse(result.authorizes_broadcast)
        self.assertFalse(self.stage.current(plan))  # Still only prepared.
        self.assertIsNone(self.take(ticket, plan))
        self.assertEqual(self.prefetch.metrics()["consumed"], 1)
        self.assertNotIn("gate", str(self.prefetch.metrics()))

    def test_opt_in_required_and_untrusted_source_rejected(self):
        off = StreamParallelCommentaryPrefetch()
        with self.assertRaises(PermissionError):
            off.enable()
        self.assertIsNone(off.reserve(
            self.next, stage=self.stage, audible_plan=self.audible,
            now_s=100.2, model_epoch=1, scene_epoch=1,
            host_verified=True, moderated_source=True, spare_compute=True))
        self.assertIsNone(self.reserve(host_verified=False))
        self.assertIsNone(self.reserve(moderated_source=False))
        self.assertIsNone(self.reserve(spare_compute=False))
        self.assertEqual(self.prefetch.metrics()["pending"], 0)

    def test_no_prefetch_when_old_stage_is_not_audible(self):
        self.assertTrue(self.stage.finish(self.audible, now=101.0))
        self.assertIsNone(self.reserve())

    def test_only_observed_game_events_and_useful_viewer_questions(self):
        danger = replace(self.next, signal_id="danger", kind="game_danger")
        unconfirmed = replace(self.next, signal_id="unconfirmed", evidence="reported")
        ambient = StreamSignal("ambient", "ambient", 100.1, "What a day")
        for signal in (danger, unconfirmed, ambient):
            self.assertIsNone(self.reserve(signal))
        viewer = StreamSignal("question2", "viewer_question", 100.1,
                              "What happens next?", speaker_id="viewer-y")
        self.assertIsNotNone(self.reserve(viewer))

    def test_capacity_and_duplicate_prevent_flood(self):
        first = self.reserve()
        self.assertIsNone(self.reserve())
        second = replace(self.next, signal_id="next-2")
        self.assertIsNotNone(self.reserve(second))
        third = replace(self.next, signal_id="next-3")
        self.assertIsNone(self.reserve(third))
        self.assertEqual(self.prefetch.metrics()["pending"], 2)
        self.assertIsNotNone(first)

    def test_moderation_required_and_worker_epoch_fenced(self):
        ticket = self.reserve()
        self.assertFalse(self.prefetch.complete(
            ticket, text="Okay", now_s=100.4, model_epoch=11))
        self.assertFalse(self.prefetch.complete(
            ticket, text="Okay", now_s=100.4, model_epoch=12,
            host_moderated=True))
        self.assertTrue(self.prefetch.complete(
            ticket, text="Okay", now_s=100.4, model_epoch=11,
            host_moderated=True))
        plan = self.choose()
        self.assertIsNone(self.take(ticket, plan, model_epoch=12))

    def test_expiry_never_uses_old_game_commentary(self):
        ticket = self.reserve()
        self.assertTrue(self.prefetch.complete(
            ticket, text="Old gate", now_s=100.6,
            model_epoch=11, host_moderated=True))
        self.assertIsNone(self.prefetch.take_for_plan(
            ticket, stage=self.stage, plan=self.audible, now_s=104.2,
            model_epoch=11, scene_epoch=3, host_verified=True,
            spare_compute=True))
        self.assertEqual(self.prefetch.metrics()["stale"], 1)

    def test_scene_changed_and_disable_purge_all_text(self):
        ticket = self.reserve()
        self.assertTrue(self.prefetch.complete(
            ticket, text="Stale after scene", now_s=100.3,
            model_epoch=11, host_moderated=True))
        with self.assertRaises(PermissionError):
            self.prefetch.scene_changed()
        self.prefetch.scene_changed(host_verified=True)
        self.assertEqual(self.prefetch.metrics()["pending"], 0)
        plan = self.choose()
        self.assertIsNone(self.take(ticket, plan))
        self.prefetch.disable()
        self.assertFalse(self.prefetch.metrics()["enabled"])

    def test_prepared_plan_must_match_real_stage_event_and_scope(self):
        ticket = self.reserve()
        self.assertTrue(self.prefetch.complete(
            ticket, text="A gate", now_s=100.3,
            model_epoch=11, host_moderated=True))
        plan = self.choose()
        forged = replace(plan, game_scope="another.game")
        self.assertIsNone(self.take(ticket, forged))
        self.assertEqual(self.prefetch.metrics()["pending"], 0)

    def test_different_scene_epoch_rejected_even_same_game_name(self):
        ticket = self.reserve()
        self.assertTrue(self.prefetch.complete(
            ticket, text="Old round", now_s=100.3,
            model_epoch=11, host_moderated=True))
        plan = self.choose()
        self.assertIsNone(self.take(ticket, plan, scene_epoch=4))

    def test_ticket_identity_prevents_aba_and_fabrication(self):
        ticket = self.reserve()
        fake = PrefetchTicket(ticket.serial, ticket.session_epoch)
        self.assertFalse(self.prefetch.complete(
            fake, text="Hijack", now_s=100.3, model_epoch=11,
            host_moderated=True))
        self.assertTrue(self.prefetch.complete(
            ticket, text="Valid", now_s=100.4, model_epoch=11,
            host_moderated=True))
        plan = self.choose()
        self.assertIsNone(self.take(fake, plan))
        self.assertIsNotNone(self.take(ticket, plan))

    def test_two_playback_threads_cannot_consume_twice(self):
        ticket = self.reserve()
        self.assertTrue(self.prefetch.complete(
            ticket, text="Only once", now_s=100.3,
            model_epoch=11, host_moderated=True))
        plan = self.choose()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.take(ticket, plan), range(24)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.prefetch.metrics()["consumed"], 1)

    def test_explicit_stage_transition_invalidates_pending_speech(self):
        ticket = self.reserve()
        self.assertTrue(self.prefetch.complete(
            ticket, text="Discard after transition", now_s=100.3,
            model_epoch=11, host_moderated=True))
        self.assertTrue(self.stage.finish(self.audible, now=100.6))
        self.prefetch.scene_changed(host_verified=True)
        self.stage.transition_game(
            game_scope="another", owner_approved=True,
            audio_stopped_and_flushed=True, now=100.7)
        self.assertFalse(self.prefetch.complete(
            ticket, text="After transition", now_s=100.8, model_epoch=11,
            host_moderated=True))

    def test_text_and_clock_boundaries(self):
        ticket = self.reserve()
        for bad in ("", "x" * 321, "line\nbreak", "bad\x00control", "\u202eBIDI"):
            with self.subTest(bad=repr(bad)), self.assertRaises(ValueError):
                self.prefetch.complete(
                    ticket, text=bad, now_s=100.4, model_epoch=11,
                    host_moderated=True)
        for value in (True, float("nan"), float("inf"), -1, 1e12):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prefetch.complete(
                    ticket, text="Hi", now_s=value, model_epoch=11,
                    host_moderated=True)
        for value in (True, 0, -1, 1.2):
            with self.subTest(epoch=value), self.assertRaises(ValueError):
                self.reserve(model_epoch=value)
        for value in (0, 4, True):
            with self.subTest(capacity=value), self.assertRaises(ValueError):
                StreamParallelCommentaryPrefetch(capacity=value)
        for value in (0.01, 9.0, math.nan):
            with self.subTest(age=value), self.assertRaises(ValueError):
                StreamParallelCommentaryPrefetch(max_age_s=value)


if __name__ == "__main__":
    unittest.main()
