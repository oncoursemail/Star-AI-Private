"""Offline expression and real camera-path checks using fake clocks and memory sinks.

No chat connection, camera driver, audio output, model inference or external I/O.
"""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import sys
import threading
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.vtuber.camera import StarCamera
from star.vtuber.expressions import (
    CUE_WINDOW_S,
    EXPRESSION_NAMES,
    MAX_CUES_PER_WINDOW,
    ExpressionTimeline,
    encode_expression,
)
from star.vtuber.lipsync import MouthFrame, parse_datagram
from star.vtuber.rig import LiveRig
from star.vtuber.sinks import MemorySink


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class Model:
    quality = "high"
    layers = ()

    def __init__(self):
        self.poses = []

    def render(self, pose):
        self.poses.append(pose)
        return np.zeros((8, 8, 3), dtype=np.uint8)


def base_pose(at=100.0):
    return LiveRig(seed=10).step(at, MouthFrame(0.8, (0.5, 0.0, 0.0, 0.0, 0.5)))


class ExpressionChecks(unittest.TestCase):
    def test_encoding_is_bounded_and_canonical(self):
        for name in EXPRESSION_NAMES:
            encoded = encode_expression(name)
            self.assertLessEqual(len(encoded), 40)
            self.assertTrue(ExpressionTimeline().event(encoded, now=100.0))
        for duration in (0.4, 1.5, 4.0):
            self.assertIn(str(round(duration * 1000)), encode_expression("smile", duration))
        for duration in (True, -1, 0.399, 4.001, float("nan"), float("inf"), 10**1000, "2"):
            with self.subTest(duration=str(duration)[:20]), self.assertRaises(ValueError):
                encode_expression("smile", duration)
        for name in ("angry-forever", "!expression smile", "../smile", {}, None):
            with self.assertRaises(ValueError):
                encode_expression(name)

    def test_neutral_and_owner_interrupt_always_clear(self):
        cues = ExpressionTimeline()
        self.assertTrue(cues.event(encode_expression("surprise"), now=100.0))
        self.assertEqual(cues.apply(base_pose(100.2)).face, "stopped")
        self.assertTrue(cues.event("owner_interrupt", float("nan"), now=100.2))
        pose = base_pose(100.3)
        self.assertIs(cues.apply(pose), pose)
        self.assertTrue(cues.event(encode_expression("smile"), now=101.0))
        self.assertTrue(cues.event(encode_expression("neutral"), now=101.1))
        self.assertEqual(cues.status(now=101.1)["active"], "neutral")

    def test_mouth_visemes_and_body_are_untouched(self):
        changed = {"face", "smile", "brow_raise", "eye_open_left", "eye_open_right", "gaze_x", "gaze_y"}
        for name in EXPRESSION_NAMES[1:]:
            cues = ExpressionTimeline()
            cues.event(encode_expression(name), now=100.0)
            base = base_pose(100.2)
            result = cues.apply(base)
            for field in base.__dataclass_fields__:
                if field not in changed:
                    self.assertEqual(getattr(base, field), getattr(result, field), (name, field))
            self.assertIs(base.shape, result.shape)

    def test_every_expression_expires_without_refresh(self):
        for name in EXPRESSION_NAMES[1:]:
            cues = ExpressionTimeline()
            cues.event(encode_expression(name, 4.0), now=100.0)
            self.assertFalse(cues.event(encode_expression(name, 4.0), now=102.6))
            original = base_pose(104.01)
            self.assertIs(cues.apply(original), original)
            self.assertEqual(cues.status(now=104.01)["active"], "neutral")

    def test_smooth_attack_and_release_have_no_numeric_jump(self):
        cues = ExpressionTimeline()
        cues.event(encode_expression("smile", 1.0), now=100.0)
        baseline = base_pose()
        samples = [cues.apply(replace(baseline, t=100.0 + n / 1000)).smile for n in range(1001)]
        self.assertAlmostEqual(samples[0], baseline.smile)
        self.assertAlmostEqual(samples[-1], baseline.smile)
        self.assertLess(max(abs(a - b) for a, b in zip(samples, samples[1:])), 0.01)
        self.assertGreater(max(samples), 0.5)

    def test_blinks_and_winks_are_not_reopened(self):
        cues = ExpressionTimeline()
        cues.event(encode_expression("surprise"), now=100.0)
        original = replace(base_pose(100.2), eye_open_left=0.0, eye_open_right=0.4)
        result = cues.apply(original)
        self.assertEqual(result.eye_open_left, 0)
        self.assertLessEqual(result.eye_open_right, original.eye_open_right)

    def test_repetition_and_global_budget_drop_without_backlog(self):
        cues = ExpressionTimeline()
        self.assertTrue(cues.event("chat_reading", now=100.0))
        for n in range(1, 200):
            self.assertFalse(cues.event("chat_reading", now=100.0 + n / 100))
        self.assertEqual(cues.status(now=102.0)["accepted"], 1)
        self.assertEqual(cues.status(now=102.0)["remaining_s"], 0.4)
        self.assertEqual(cues.status(now=103.0)["active"], "neutral")
        budget = ExpressionTimeline()
        for n in range(MAX_CUES_PER_WINDOW):
            name = "smile" if n % 2 == 0 else "thinking"
            self.assertTrue(budget.event(encode_expression(name, 0.4), now=100.0 + n * 1.3))
        self.assertFalse(budget.event(encode_expression("surprise"), now=111.0))
        self.assertTrue(budget.event(encode_expression("surprise"), now=100.0 + CUE_WINDOW_S + 0.1))

    def test_priority_allows_urgent_cue_and_rejects_chat_overwrite(self):
        cues = ExpressionTimeline()
        self.assertTrue(cues.event("chat_reading", now=100.0))
        self.assertTrue(cues.event("game_danger", now=100.1))
        self.assertFalse(cues.event("viewer_comment", now=100.2))
        self.assertEqual(cues.apply(base_pose(100.4)).face, "stopped")

    def test_chat_reading_end_clears_only_reading_expression(self):
        cues = ExpressionTimeline()
        cues.event("chat_reading", now=100.0)
        cues.event("chat_reading_end", now=100.5)
        self.assertEqual(cues.status(now=100.5)["active"], "neutral")
        cues.event("game_danger", now=101.0)
        cues.event("chat_reading_end", now=101.1)
        self.assertEqual(cues.status(now=101.1)["active"], "surprise")

    def test_malformed_events_and_nonfinite_strength_do_nothing(self):
        cues = ExpressionTimeline()
        for kind in (
            "!expression surprise",
            "expression:smile:999999",
            "expression:smile:0400",
            "expression:neutral:1000",
            "unknown",
            {},
            None,
        ):
            self.assertFalse(cues.event(kind, now=100.0))
        for value in (True, -1, 1.001, float("nan"), float("inf"), "1", 10**1000):
            self.assertFalse(cues.event("chat_reading", value, now=100.0))
        self.assertEqual(cues.status(now=100.0)["active"], "neutral")

    def test_stalled_camera_does_not_replay_old_cue(self):
        cues = ExpressionTimeline()
        cues.event("game_win", now=100.0)
        base = base_pose(110.0)
        self.assertIs(cues.apply(base), base)
        self.assertFalse(cues.event("video_funny", now=99.0))

    def test_overlay_values_stay_finite_and_bounded(self):
        for name in EXPRESSION_NAMES[1:]:
            cues = ExpressionTimeline()
            cues.event(encode_expression(name), now=100.0)
            for n in range(130):
                result = cues.apply(base_pose(100.0 + n / 30))
                for field in ("smile", "brow_raise", "eye_open_left", "eye_open_right"):
                    value = getattr(result, field)
                    self.assertTrue(math.isfinite(value) and 0 <= value <= 1)
                for field in ("gaze_x", "gaze_y"):
                    self.assertLessEqual(abs(getattr(result, field)), 1)

    def test_real_camera_feed_routes_expression_and_preserves_speech(self):
        clock, model, sink = Clock(), Model(), MemorySink()
        camera = StarCamera(model, [sink], clock=clock, sleep=lambda _: None)
        self.assertIsInstance(camera.expressions, ExpressionTimeline)
        camera.feed.push([MouthFrame(0.9, (1, 0, 0, 0, 0))] * 30, 0.0)
        camera.feed.event(encode_expression("smile"))
        clock.now = 100.2
        pose = camera.tick()
        self.assertEqual(pose.face, "happy")
        self.assertGreater(pose.mouth_open, 0)
        self.assertEqual(pose.viseme, "aa")
        self.assertGreater(pose.smile, 0.3)
        camera.feed.clear()
        self.assertEqual(camera.expressions.status(now=100.2)["active"], "neutral")
        clock.now = 100.4
        self.assertLess(camera.tick().mouth_open, pose.mouth_open)
        camera.stop()
        self.assertEqual(camera.expressions.status(now=100.4)["active"], "neutral")
        self.assertTrue(sink.closed)

    def test_camera_stall_expires_cue_from_receipt_time(self):
        clock, model = Clock(), Model()
        camera = StarCamera(model, [], clock=clock, sleep=lambda _: None)
        camera.feed.event(encode_expression("surprise", 0.4))
        clock.now = 110.0
        self.assertEqual(camera.tick().face, "idle")
        camera.stop()

    def test_legacy_game_cue_also_expires_during_camera_stall(self):
        clock, model = Clock(), Model()
        camera = StarCamera(model, [], clock=clock, sleep=lambda _: None)
        camera.feed.event("game_danger")
        clock.now = 110.0
        pose = camera.tick()
        self.assertEqual(pose.face, "idle")
        self.assertEqual(pose.brow_raise, 0)
        camera.stop()

    def test_camera_stop_rejects_new_cosmetic_events(self):
        clock = Clock()
        camera = StarCamera(Model(), [], clock=clock, sleep=lambda _: None)
        camera.feed.event("chat_reading")
        camera.stop()
        clock.now = 101.0
        camera.feed.event(encode_expression("surprise"))
        self.assertEqual(camera.expressions.status(now=101.0)["active"], "neutral")
        self.assertEqual(camera._events, [])

    def test_empty_and_malformed_datagrams_do_not_become_expression_commands(self):
        for payload in (b"", b"{}", b"[]", b"null", b'{"t":"e","s":{}}', b"not json"):
            self.assertIsNone(parse_datagram(payload))
        self.assertEqual(parse_datagram(b'{"t":"c"}'), ("clear", None))
        kind = encode_expression("reading_chat")
        self.assertEqual(parse_datagram(('{"t":"e","k":"' + kind + '","s":0.7}').encode()), ("event", (kind, 0.7)))

    def test_concurrent_feed_events_remain_bounded(self):
        cues = ExpressionTimeline(clock=lambda: 100.0)
        threads = [threading.Thread(target=lambda: cues.event("chat_reading")) for _ in range(30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        status = cues.status(now=100.0)
        self.assertEqual(status["accepted"], 1)
        self.assertEqual(status["active"], "reading_chat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
