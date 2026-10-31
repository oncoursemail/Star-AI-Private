"""STAR Camera (star/vtuber): lip-sync, rig, model, sinks, loop, VMC, control, Discord steps, activities.

Everything runs with fakes: synthetic vowels for her voice, a fake clock, a fake pyvirtualcam module, a fake
screen/planner/clicker. Nothing opens a camera, an audio device or Discord.
"""
from __future__ import annotations

import json
import socket
import struct
import tempfile
import threading
import time
import unittest
import wave
from collections import Counter
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from star.stream_stage import _CUES as STAGE_CUES
from star.stream_motion import CUES
from star.vtuber import activities, control, discord_ui, lipsync, vmc
from star.vtuber.camera import StarCamera
from star.vtuber.model import ModelError, find_starface_dir, load_manifest, load_model, starface_spec
from star.vtuber.rig import REACTIONS, LiveRig
from star.vtuber.sample import render_sample
from star.vtuber.sinks import MemorySink, PyVirtualCamSink, SinkError

RATE = 16000


def vowel(f1: float, f2: float, f0: float = 120, dur: float = 0.3, gain: float = 0.2, f3: float = 2900) -> np.ndarray:
    """Source-filter vowel: an impulse train through three formant resonators (no recorded speech needed)."""
    n = int(RATE * dur)
    src = np.zeros(n)
    src[::int(RATE / f0)] = 1.0
    y = src
    for f, bw in ((f1, 80), (f2, 120), (f3, 200)):
        r, th = np.exp(-np.pi * bw / RATE), 2 * np.pi * f / RATE
        a1, a2, out = -2 * r * np.cos(th), r * r, np.zeros(n)
        for i in range(n):
            out[i] = y[i] - a1 * (out[i - 1] if i > 0 else 0) - a2 * (out[i - 2] if i > 1 else 0)
        y = out
    return (gain * y / np.max(np.abs(y))).astype(np.float32)


AA, OU, EE = (800, 1200), (320, 850), (290, 2300)


def top_visemes(samples: np.ndarray) -> Counter:
    frames = lipsync.Analyzer().push(samples, RATE)
    return Counter(f.viseme for f in frames[3:])


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class LipSyncTests(unittest.TestCase):
    def test_silence_and_quiet_noise_keep_the_mouth_shut(self):
        frames = lipsync.Analyzer().push(np.zeros(RATE // 2, dtype=np.float32), RATE)
        self.assertEqual(len(frames), 25)
        self.assertTrue(all(f.open == 0 and f.viseme == "sil" for f in frames))
        quiet = (0.004 * np.random.default_rng(1).standard_normal(RATE // 2)).astype(np.float32)
        self.assertTrue(all(f.open == 0 for f in lipsync.Analyzer().push(quiet, RATE)))

    def test_vowels_pick_their_own_mouth_shape(self):
        for f0 in (100, 140, 180):
            self.assertEqual(top_visemes(vowel(*AA, f0=f0)).most_common(1)[0][0], "aa", f0)
            self.assertEqual(top_visemes(vowel(*OU, f0=f0)).most_common(1)[0][0], "ou", f0)
            self.assertEqual(top_visemes(vowel(*EE, f0=f0)).most_common(1)[0][0], "ee", f0)

    def test_louder_speech_opens_the_mouth_wider(self):
        soft = lipsync.Analyzer().push(vowel(*AA, gain=0.03), RATE)
        loud = lipsync.Analyzer().push(vowel(*AA, gain=0.4), RATE)
        self.assertGreater(np.mean([f.open for f in loud[3:]]), np.mean([f.open for f in soft[3:]]) + 0.4)

    def test_a_hiss_gets_a_small_teeth_shape_not_a_round_mouth(self):
        noise = np.random.default_rng(2).standard_normal(RATE // 2)
        spectrum = np.fft.rfft(noise) * (np.fft.rfftfreq(len(noise), 1 / RATE) > 4500)
        hiss = np.fft.irfft(spectrum)
        hiss = (0.3 * hiss / np.max(np.abs(hiss))).astype(np.float32)
        frames = lipsync.Analyzer().push(hiss, RATE)[3:]
        self.assertTrue(all(f.viseme == "ih" and 0 < f.open < 0.3 for f in frames))

    def test_tail_shorter_than_a_hop_is_carried_not_lost(self):
        analyzer = lipsync.Analyzer()
        x = vowel(*AA, dur=0.25)
        got = len(analyzer.push(x[:500], RATE)) + len(analyzer.push(x[500:], RATE))
        self.assertEqual(got, len(x) // 320)

    def test_timeline_shows_a_frame_only_when_it_is_audible(self):
        clock = FakeClock(10.0)
        line = lipsync.Timeline(clock)
        frames = [lipsync.MouthFrame(0.9, (1, 0, 0, 0, 0))] * 5
        line.push(frames, audible_at=10.5)
        self.assertEqual(line.at(10.4).open, 0.0)               # queued but not yet audible: no early mouth
        self.assertEqual(line.at(10.51).open, 0.9)
        self.assertEqual(line.at(10.5 + 0.1 + 0.2).open, 0.0)   # past the last frame by more than 110 ms: silence
        line.clear()
        self.assertEqual(line.at(10.51).open, 0.0)

    def test_timeline_queues_chunks_in_order(self):
        line = lipsync.Timeline(FakeClock(0.0))
        one = [lipsync.MouthFrame(0.5, (1, 0, 0, 0, 0))] * 10          # 0.2 s
        line.push(one, 1.0)
        line.push([lipsync.MouthFrame(0.8, (0, 0, 1, 0, 0))] * 10, 1.0)   # asked for the same moment: plays after
        self.assertEqual(line.at(1.05).open, 0.5)
        self.assertEqual(line.at(1.25).open, 0.8)

    def test_speaker_wrapper_sends_frames_for_the_moment_the_speaker_reaches_them_and_clears_on_stop(self):
        class Speaker:
            def __init__(self):
                self.played, self.stopped = [], 0

            def pending_seconds(self):
                return 0.35

            def play(self, pcm, rate):
                self.played.append((len(pcm), rate))

            def stop(self):
                self.stopped += 1

            def reset(self):
                pass

            def level(self):
                return 0.0

        class Feed:
            def __init__(self):
                self.pushed, self.cleared = [], 0

            def push(self, frames, delay):
                self.pushed.append((len(frames), delay))

            def clear(self):
                self.cleared += 1

        speaker, feed = Speaker(), Feed()
        wrapped = lipsync.LipSyncSpeaker(speaker, feed)
        pcm = (vowel(*AA, dur=0.2) * 32767).astype("<i2").tobytes()
        wrapped.play(pcm, RATE)
        self.assertEqual(feed.pushed, [(10, 0.35)])
        self.assertEqual(speaker.played, [(len(pcm), RATE)])
        self.assertEqual(wrapped.level(), 0.0)                  # everything else is the speaker's own
        wrapped.stop()
        self.assertEqual((speaker.stopped, feed.cleared), (1, 1))

    def test_her_voice_still_plays_when_lipsync_breaks(self):
        class Speaker:
            played = 0

            def pending_seconds(self):
                return 0.0

            def play(self, pcm, rate):
                self.played += 1

        class Broken:
            def push(self, *_):
                raise RuntimeError("camera exploded")

        speaker = Speaker()
        lipsync.LipSyncSpeaker(speaker, Broken()).play((vowel(*AA) * 32767).astype("<i2").tobytes(), RATE)
        self.assertEqual(speaker.played, 1)

    def test_udp_feed_reaches_the_listener_across_sockets(self):
        line = lipsync.Timeline(time.monotonic)
        events = []
        local = lipsync.LocalFeed(line, on_event=lambda k, s: events.append((k, s)))
        listener = lipsync.UdpListener(local, port=0)
        listener.start()
        try:
            feed = lipsync.UdpFeed(listener.port)
            feed.push([lipsync.MouthFrame(0.7, (0, 0, 1, 0, 0))] * 12, 0.0)
            feed.event("game_win", 0.9)
            deadline = time.time() + 3
            while time.time() < deadline and (not events or line.at().open == 0.0):
                time.sleep(0.02)
            self.assertAlmostEqual(line.at().open, 0.7, places=2)
            self.assertEqual(events, [("game_win", 0.9)])
            feed.clear()
            deadline = time.time() + 3
            while time.time() < deadline and line.at().open != 0.0:
                time.sleep(0.02)
            self.assertEqual(line.at().open, 0.0)
            feed.close()
        finally:
            listener.close()
            listener.join(2)

    def test_datagram_parser_rejects_malformed_and_out_of_range(self):
        ok = json.dumps({"t": "m", "d": 0.1, "f": [[0.5, 1, 0, 0, 0, 0]]}).encode()
        self.assertEqual(lipsync.parse_datagram(ok)[0], "mouth")
        for bad in (b"garbage", b'{"t":"m","d":0.1,"f":[[2,0,0,0,0,0]]}', b'{"t":"m","d":0.1,"f":[[0.5,1]]}',
                    b'{"t":"m","d":999,"f":[]}', b'{"t":"zz"}', b'{"t":"m","d":0,"f":' + b"[[0,0,0,0,0,0]]," * 60 + b"[]]}",
                    b"\xff\xfe"):
            self.assertIsNone(lipsync.parse_datagram(bad), bad)
        kind, (name, strength) = lipsync.parse_datagram(b'{"t":"e","k":"x","s":7}')
        self.assertEqual((kind, name, strength), ("event", "x", 1.0))


class RigTests(unittest.TestCase):
    def run_rig(self, rig, seconds, mouth=None, fps=30):
        mouth = mouth or lipsync.SILENT
        return [rig.step(i / fps, mouth) for i in range(int(seconds * fps))]

    def test_mouth_rises_smoothly_and_releases_slower_than_it_attacks(self):
        rig = LiveRig()
        open_frame = lipsync.MouthFrame(1.0, (1, 0, 0, 0, 0))
        rise = [rig.step(i / 30, open_frame).mouth_open for i in range(8)]
        self.assertTrue(all(b > a for a, b in zip(rise, rise[1:])))
        self.assertLess(rise[0], 0.8)                            # not a one-frame pop
        fall = [rig.step((8 + i) / 30, lipsync.SILENT).mouth_open for i in range(8)]
        self.assertTrue(all(b <= a for a, b in zip(fall, fall[1:])))
        self.assertGreater(fall[0], 0.4 * rise[-1])              # release is slower than attack
        self.assertEqual(rig.step(9.0, lipsync.SILENT).mouth_open, 0.0)

    def test_blinks_happen_and_eyes_reopen(self):
        poses = self.run_rig(LiveRig(), 12.0)
        closed = [p for p in poses if p.eye_open_left < 0.3]
        self.assertGreater(len(closed), 3)
        self.assertEqual(poses[-1].eye_open_left > 0.8 or poses[-2].eye_open_left > 0.8, True)
        blinks = sum(1 for a, b in zip(poses, poses[1:]) if a.eye_open_left >= 0.3 > b.eye_open_left)
        self.assertTrue(2 <= blinks <= 6, blinks)

    def test_idle_breathes_and_sways_but_reduced_motion_is_still(self):
        moving = self.run_rig(LiveRig(), 8.0)
        self.assertGreater(max(p.head_x for p in moving) - min(p.head_x for p in moving), 0.03)
        self.assertGreater(max(p.breath for p in moving) - min(p.breath for p in moving), 0.5)
        still = self.run_rig(LiveRig(reduced_motion=True), 8.0)
        self.assertTrue(all(p.head_x == 0 and p.breath == 0 and p.head_roll == 0 for p in still))

    def test_same_seed_same_motion_different_seed_differs(self):
        a, b, c = (self.run_rig(LiveRig(seed=s), 5.0) for s in (3, 3, 4))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_events_become_cues_and_unknown_events_do_nothing(self):
        rig = LiveRig()
        self.run_rig(rig, 1.0)
        self.assertTrue(rig.react("game_danger", 1.0, now=1.0))
        self.assertGreater(rig.step(1.05).brow_raise, 0.3)
        self.assertFalse(rig.react("something_else"))
        self.assertFalse(rig.react("owner_interrupt"))
        self.assertTrue(rig.react("video_funny", 1.0, now=3.0))
        later = rig.step(3.2)
        self.assertGreater(later.smile, 0.3)
        self.assertEqual(later.face, "happy")

    def test_every_stage_event_has_a_reaction_with_a_valid_cue(self):
        self.assertTrue(set(STAGE_CUES) <= set(REACTIONS))
        for kind, reaction in REACTIONS.items():
            if reaction is not None:
                self.assertIn(reaction[0], CUES, kind)
        for kind, stage in STAGE_CUES.items():
            self.assertEqual(REACTIONS[kind], stage, kind)

    def test_mood_holds_the_face_and_fires_a_cue_once_per_change(self):
        rig = LiveRig()
        self.run_rig(rig, 1.0)
        mood = {"face": "happy", "cue": "joy", "strength": 0.8, "energy": 0.6}
        rig.set_mood(mood)
        self.assertEqual(rig.step(1.1).face, "happy")
        first = rig.step(1.2).smile
        for i in range(30):                                       # polled again every second: must not re-fire
            rig.set_mood(mood)
            rig.step(1.3 + i / 30)
        self.assertLess(rig.step(3.0).smile, first)               # the joy cue decayed; the face stayed happy
        self.assertEqual(rig.step(3.05).face, "happy")
        rig.set_mood(None)
        self.assertEqual(rig.step(3.1).face, "idle")

    def test_neutral_resets_the_mouth_at_once(self):
        rig = LiveRig()
        for i in range(10):
            rig.step(i / 30, lipsync.MouthFrame(1.0, (1, 0, 0, 0, 0)))
        self.assertEqual(rig.neutral(0.4).mouth_open, 0.0)

    def test_pose_params_name_every_binding_target(self):
        params = LiveRig().step(0.0).params()
        for name in ("head_x", "head_y", "head_roll", "body_lean", "breath", "blink", "talk", "smile", "brow_raise",
                     "gaze_x", "gaze_y", "hair_sway", "v_aa", "v_oh", "face", "viseme"):
            self.assertIn(name, params)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model("placeholder")

    def pose(self, **changes):
        import dataclasses
        base = LiveRig().step(0.0)
        base = dataclasses.replace(base, eye_open_left=1.0, eye_open_right=1.0, head_x=0.0, head_y=0.0, head_roll=0.0,
                                   body_lean=0.0, breath=0.5, gaze_x=0.0, gaze_y=0.0, hair_sway=0.0, brow_raise=0.0)
        return dataclasses.replace(base, **changes)

    def region(self, frame, box):
        x0, y0, x1, y1 = box
        return frame[y0:y1, x0:x1].astype(int)

    def test_renders_an_rgb_frame_of_the_model_size(self):
        frame = self.model.render(self.pose())
        self.assertEqual((frame.shape, frame.dtype), ((720, 1280, 3), np.uint8))
        self.assertGreater(frame.std(), 10)

    def test_open_mouth_and_closed_mouth_look_different_where_the_mouth_is(self):
        mouth = (580, 395, 700, 470)
        closed = self.model.render(self.pose(mouth_open=0.0, viseme="sil", shape=(0,) * 5))
        wide = self.model.render(self.pose(mouth_open=0.9, viseme="aa", shape=(0.9, 0, 0, 0, 0)))
        rounded = self.model.render(self.pose(mouth_open=0.9, viseme="ou", shape=(0, 0, 0.9, 0, 0)))
        self.assertGreater(np.abs(self.region(closed, mouth) - self.region(wide, mouth)).mean(), 5)
        self.assertGreater(np.abs(self.region(rounded, mouth) - self.region(wide, mouth)).mean(), 2)
        outside = (0, 0, 400, 300)
        self.assertEqual(np.abs(self.region(closed, outside) - self.region(wide, outside)).max(), 0)

    def test_a_blink_swaps_open_eyes_for_closed_ones(self):
        eyes = (520, 270, 760, 340)
        open_eyes = self.model.render(self.pose())
        blink = self.model.render(self.pose(eye_open_left=0.0, eye_open_right=0.0))
        self.assertGreater(np.abs(self.region(open_eyes, eyes) - self.region(blink, eyes)).mean(), 8)

    def test_the_head_group_moves_its_children(self):
        centre = self.model.render(self.pose(head_x=0.0)).astype(int)
        right = self.model.render(self.pose(head_x=0.8)).astype(int)
        self.assertGreater(np.abs(centre - right).mean(), 1)
        face_cols = np.where((np.abs(centre[:, :, :] - np.array([255, 224, 196])).sum(axis=2) < 12).any(axis=0))[0]
        face_cols_right = np.where((np.abs(right[:, :, :] - np.array([255, 224, 196])).sum(axis=2) < 12).any(axis=0))[0]
        self.assertGreater(face_cols_right.min(), face_cols.min() + 20)

    def test_fast_quality_matches_high_quality_closely(self):
        pose = self.pose(head_roll=0.5, head_x=0.3, mouth_open=0.5, viseme="aa", shape=(0.5, 0, 0, 0, 0))
        high = self.model.render(pose).astype(int)
        self.model.quality = "fast"
        try:
            fast = self.model.render(pose).astype(int)
        finally:
            self.model.quality = "high"
        self.assertLess(np.abs(high - fast).mean(), 2.0)

    def test_starface_pack_uses_the_mascot_art_and_swaps_faces_by_mood(self):
        self.assertIsNotNone(find_starface_dir())
        model = load_model("starface")
        happy = model.render(self.pose(face="happy", eye_open_left=1.0))
        nervous = model.render(self.pose(face="oops", eye_open_left=1.0))
        self.assertGreater(np.abs(happy.astype(int) - nervous.astype(int)).mean(), 2)
        spec, _ = starface_spec()
        self.assertEqual(spec["layers"][1]["states"]["oops"], "nervous.png")      # same mapping as StarFace.tsx

    def test_bad_models_are_refused_with_a_reason(self):
        base = Path(tempfile.mkdtemp())
        from PIL import Image
        Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(base / "a.png")

        def spec(**layer):
            return {"size": [320, 200], "layers": [{"id": "a", "image": "a.png", "pos": [10, 10], **layer}]}

        load_manifest(spec(), base)
        with self.assertRaisesRegex(ModelError, "unknown parameter"):
            load_manifest(spec(bind={"tx": {"param": "head_xx", "gain": 1}}), base)
        with self.assertRaisesRegex(ModelError, "unknown channel"):
            load_manifest(spec(bind={"warp": {"param": "head_x", "gain": 1}}), base)
        with self.assertRaisesRegex(ModelError, "outside the avatar folder"):
            load_manifest(spec(image="../a.png"), base)
        with self.assertRaisesRegex(ModelError, "image not found"):
            load_manifest(spec(image="missing.png"), base)
        with self.assertRaisesRegex(ModelError, "parent must be an earlier layer"):
            load_manifest(spec(parent="later"), base)
        with self.assertRaisesRegex(ModelError, "bad 'when'"):
            load_manifest(spec(when={"head_x": [1]}), base)
        with self.assertRaisesRegex(ModelError, "size out of range"):
            load_manifest({"size": [10, 10], "layers": [{"id": "a", "pos": [1, 1]}]}, base)

    def test_a_model_folder_is_the_setting(self):
        folder = Path(tempfile.mkdtemp())
        from PIL import Image
        Image.new("RGBA", (40, 40), (0, 255, 0, 255)).save(folder / "g.png")
        (folder / "avatar.json").write_text(json.dumps({"name": "mine", "size": [320, 200], "background": [0, 0, 0],
                                                         "layers": [{"id": "g", "image": "g.png", "pos": [160, 100]}]}))
        for source in (folder, folder / "avatar.json"):
            model = load_model(source)
            frame = model.render(LiveRig().step(0.0))
            self.assertEqual(model.name, "mine")
            self.assertEqual(tuple(frame[100, 160]), (0, 255, 0))
            self.assertEqual(tuple(frame[5, 5]), (0, 0, 0))
        with self.assertRaises(ModelError):
            load_model(folder / "nope")


class FakePyVirtualCam:
    class PixelFormat:
        RGB = "RGB"

    def __init__(self):
        self.created, self.fail = [], False
        outer = self

        class Camera:
            def __init__(self, **kw):
                if outer.fail:
                    raise RuntimeError("no camera registered")
                outer.created.append(kw)
                self.device, self.sent, self.closed = kw.get("device", "OBS Virtual Camera"), [], False

            def send(self, frame):
                self.sent.append(frame.shape)

            def close(self):
                self.closed = True

        self.Camera = Camera


class SinkTests(unittest.TestCase):
    def test_virtual_camera_is_requested_by_the_name_star_camera_on_the_unity_capture_backend(self):
        fake = FakePyVirtualCam()
        sink = PyVirtualCamSink(1280, 720, 30, pyvirtualcam=fake)
        self.assertEqual(fake.created, [{"width": 1280, "height": 720, "fps": 30, "fmt": "RGB",
                                         "backend": "unitycapture", "device": "STAR Camera"}])
        sink.send(np.zeros((720, 1280, 3), np.uint8))
        self.assertEqual(sink._cam.sent, [(720, 1280, 3)])
        self.assertEqual(sink.device, "STAR Camera")

    def test_obs_backend_cannot_be_renamed_so_no_device_is_requested(self):
        fake = FakePyVirtualCam()
        PyVirtualCamSink(640, 360, 15, backend="obs", pyvirtualcam=fake)
        self.assertEqual(fake.created[0]["backend"], "obs")
        self.assertNotIn("device", fake.created[0])

    def test_a_missing_driver_is_a_clear_error(self):
        fake = FakePyVirtualCam()
        fake.fail = True
        with self.assertRaisesRegex(SinkError, "no virtual camera named 'STAR Camera'"):
            PyVirtualCamSink(pyvirtualcam=fake)


class CameraLoopTests(unittest.TestCase):
    def make(self, **kw):
        clock = FakeClock(100.0)
        model = load_model("placeholder")
        sink = MemorySink()
        camera = StarCamera(model, [sink], clock=clock, sleep=lambda s: None, **kw)
        return camera, sink, clock

    def test_each_tick_sends_one_frame_and_the_mouth_follows_the_audible_audio(self):
        camera, sink, clock = self.make()
        camera.feed.push([lipsync.MouthFrame(0.9, (1, 0, 0, 0, 0))] * 20, 0.5)       # audible from t = 100.5
        before = camera.tick(100.4)
        after = [camera.tick(100.5 + i * 0.033) for i in range(8)][-1]
        self.assertEqual(before.mouth_open, 0.0)
        self.assertGreater(after.mouth_open, 0.5)
        self.assertEqual(sink.count, 9)
        self.assertEqual(sink.last.shape, (720, 1280, 3))

    def test_events_from_another_thread_are_applied_on_the_camera_thread(self):
        camera, _, _ = self.make()
        camera.tick(100.0)
        threading.Thread(target=lambda: camera.feed.event("game_win", 1.0)).start()
        time.sleep(0.1)
        self.assertGreater(camera.tick(100.1).smile, 0.3)

    def test_a_failing_mood_source_never_stops_the_camera_and_is_polled_once_a_second(self):
        calls = []

        def mood():
            calls.append(1)
            raise RuntimeError("db locked")

        camera, sink, _ = self.make(mood_source=mood)
        for i in range(60):
            camera.tick(100.0 + i / 30)
        self.assertEqual(sink.count, 60)
        self.assertEqual(len(calls), 2)

    def test_mood_from_the_emotion_engine_changes_the_face(self):
        camera, _, _ = self.make(mood_source=lambda: {"face": "oops", "cue": None, "strength": 0, "energy": 0.4})
        self.assertEqual(camera.tick(100.0).face, "oops")

    def test_a_broken_sink_is_counted_not_fatal(self):
        camera, sink, _ = self.make()

        class Broken:
            def send(self, frame):
                raise OSError("device gone")

        camera.sinks.insert(0, Broken())
        camera.tick(100.0)
        self.assertEqual((sink.count, camera.sink_errors), (1, 1))

    def test_slow_rendering_lowers_quality_first_then_frame_rate_and_says_so(self):
        clock = FakeClock(0.0)

        class SlowModel:
            quality = "high"

            def render(self, pose):
                clock.t += 0.045                               # 45 ms per frame against a 33 ms budget
                return np.zeros((4, 4, 3), np.uint8)

        camera = StarCamera(SlowModel(), [MemorySink()], clock=clock, sleep=lambda s: None, fps=30)
        for _ in range(35):
            camera.tick(clock.t)
        self.assertEqual(camera.model.quality, "fast")
        for _ in range(35):
            camera.tick(clock.t)
        self.assertEqual(camera.fps, 15.0)
        self.assertEqual(len(camera.degraded), 2)
        self.assertIn("quality fast", camera.stats()["degraded"][0])

    def test_late_frames_are_dropped_not_queued(self):
        clock = FakeClock(0.0)
        slept = []
        camera = StarCamera(load_model("placeholder"), [MemorySink()], clock=clock, fps=30, adaptive=False,
                            sleep=lambda s: slept.append(s))
        original = camera.tick

        def slow_tick(now=None):
            pose = original(now)
            clock.t += 0.2                                      # each frame takes 200 ms: six frame slots
            if camera.frames >= 3:
                camera._stop.set()
            return pose

        camera.tick = slow_tick
        camera.run()
        self.assertGreaterEqual(camera.dropped, 10)
        self.assertEqual(slept, [])                             # never sleeps when behind

    def test_start_and_stop_run_a_real_thread_and_close_the_sinks(self):
        sink = MemorySink()
        camera = StarCamera(load_model("placeholder"), [sink], fps=60)
        camera.start()
        deadline = time.time() + 5
        while time.time() < deadline and sink.count < 3:
            time.sleep(0.02)
        camera.stop()
        self.assertGreaterEqual(sink.count, 3)
        self.assertTrue(sink.closed)


class VmcTests(unittest.TestCase):
    def decode(self, data: bytes):
        def string(buf, pos):
            end = buf.index(b"\0", pos)
            return buf[pos:end].decode(), (end + 4) // 4 * 4
        address, pos = string(data, 0)
        tags, pos = string(data, pos)
        args = []
        for tag in tags[1:]:
            if tag == "s":
                value, pos = string(data, pos)
            elif tag == "f":
                value, pos = struct.unpack(">f", data[pos:pos + 4])[0], pos + 4
            else:
                value, pos = struct.unpack(">i", data[pos:pos + 4])[0], pos + 4
            args.append(value)
        return address, args

    def test_osc_message_encoding_is_exact(self):
        self.assertEqual(vmc.osc_message("/VMC/Ext/Blend/Val", "A", 0.5),
                         b"/VMC/Ext/Blend/Val\0\0,sf\0A\0\0\0" + struct.pack(">f", 0.5))
        self.assertEqual(vmc.osc_message("/VMC/Ext/Blend/Apply"), b"/VMC/Ext/Blend/Apply\0\0\0\0,\0\0\0")
        self.assertEqual(self.decode(vmc.osc_message("/x", "s", 3, 1.5)), ("/x", ["s", 3, 1.5]))

    def test_pose_becomes_vrm_blendshapes_then_apply_then_bones(self):
        rig = LiveRig()
        pose = rig.step(0.0, lipsync.MouthFrame(1.0, (1, 0, 0, 0, 0)))
        for i in range(10):
            pose = rig.step(i / 30, lipsync.MouthFrame(1.0, (1, 0, 0, 0, 0)))
        decoded = [self.decode(m) for m in vmc.pose_messages(pose, t=1.0)]
        addresses = [a for a, _ in decoded]
        values = {args[0]: args[1] for a, args in decoded if a == "/VMC/Ext/Blend/Val"}
        self.assertGreater(values["A"], 0.5)
        self.assertEqual(values["U"], 0.0)
        self.assertIn("Blink_L", values)
        apply_at = addresses.index("/VMC/Ext/Blend/Apply")
        self.assertTrue(all(a != "/VMC/Ext/Blend/Val" for a in addresses[apply_at:]))
        bones = [args for a, args in decoded if a == "/VMC/Ext/Bone/Pos"]
        self.assertEqual([b[0] for b in bones], ["Head", "Neck", "Spine"])
        self.assertTrue(all(len(b) == 8 for b in bones))
        quat = bones[0][4:]
        self.assertAlmostEqual(sum(v * v for v in quat), 1.0, places=4)

    def test_sink_sends_one_bundle_over_udp(self):
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(3)
        sink = vmc.VmcSink(port=receiver.getsockname()[1])
        sink.send_pose(LiveRig().step(0.0))
        data, _ = receiver.recvfrom(65535)
        self.assertTrue(data.startswith(b"#bundle\0"))
        self.assertIn(b"/VMC/Ext/Blend/Apply", data)
        sink.close()
        receiver.close()


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def test_config_keeps_good_values_ignores_wrong_types_and_clamps(self):
        (self.folder / "config.json").write_text(json.dumps(
            {"model": "C:/models/star", "fps": 500, "width": 10, "backend": 5, "mode": "cat", "reduced_motion": "yes",
             "feed_port": 4000, "unknown": 1}))
        cfg = control.load_config(self.folder)
        self.assertEqual((cfg.model, cfg.fps, cfg.width, cfg.mode, cfg.feed_port), ("C:/models/star", 60.0, 64, "cat", 4000))
        self.assertEqual((cfg.backend, cfg.reduced_motion), ("unitycapture", False))
        (self.folder / "config.json").write_text("not json")
        self.assertEqual(control.load_config(self.folder), control.Config())

    def test_alive_means_a_fresh_heartbeat(self):
        control.write_status(self.folder, frames=5)
        self.assertTrue(control.read_status(self.folder)["alive"])
        self.assertFalse(control.read_status(self.folder, now=time.time() + 30)["alive"])
        control.write_status(self.folder, error="no driver")
        self.assertFalse(control.read_status(self.folder)["alive"])
        self.assertFalse(control.read_status(self.folder / "missing")["alive"])

    def test_start_launches_once_and_waits_for_frames(self):
        launched = []

        def spawn(argv, env, log):
            launched.append((argv[-2:], env["STAR_VTUBER_DIR"]))
            control.write_status(self.folder, frames=12, fps=30)

        first = control.start(self.folder, spawn=spawn, sleep=lambda s: None)
        self.assertTrue(first["alive"] and first["started"])
        again = control.start(self.folder, spawn=spawn, sleep=lambda s: None)
        self.assertEqual((again["started"], len(launched)), (False, 1))
        self.assertEqual(launched[0], (["star.vtuber", "run"], str(self.folder)))

    def test_start_reports_why_the_camera_would_not_come_up(self):
        def spawn(argv, env, log):
            control.write_status(self.folder, error="no virtual camera named 'STAR Camera'", frames=0)

        result = control.start(self.folder, spawn=spawn, sleep=lambda s: None)
        self.assertFalse(result["alive"])
        self.assertIn("STAR Camera", result["error"])

        def silent(argv, env, log):
            pass

        clock = iter(range(0, 1000))
        result = control.start(self.folder, spawn=silent, sleep=lambda s: None, clock=lambda: next(clock), wait_s=5)
        self.assertIn("no frames", result["error"])

    def test_stop_asks_nicely_then_kills_the_tree_when_ignored(self):
        control.write_status(self.folder, frames=3)
        killed = []
        clock = iter(x * 0.5 for x in range(1000))
        result = control.stop(self.folder, kill=killed.append, sleep=lambda s: None, clock=lambda: next(clock), wait_s=2)
        self.assertTrue((self.folder / "stop.flag").exists())
        self.assertEqual((result["forced"], len(killed)), (True, 1))
        self.assertFalse(control.read_status(self.folder)["alive"])

        control.write_status(self.folder, frames=3)
        ticks = {"n": 0}

        def polite_sleep(_):                                   # the process notices the flag and exits
            ticks["n"] += 1
            control.write_status(self.folder, stopped=True)

        killed.clear()
        result = control.stop(self.folder, kill=killed.append, sleep=polite_sleep, wait_s=5)
        self.assertEqual((result["forced"], killed), (False, []))

    def test_frames_flowing_needs_a_growing_counter_not_just_a_beat(self):
        control.write_status(self.folder, frames=10)
        self.assertFalse(control.frames_flowing(self.folder, wait_s=0.3, sleep=lambda s: time.sleep(0.05)))
        calls = {"n": 0}

        def sleeper(_):
            calls["n"] += 1
            control.write_status(self.folder, frames=10 + calls["n"])

        self.assertTrue(control.frames_flowing(self.folder, wait_s=2, sleep=sleeper))


class FakeUi:
    def __init__(self, title="Discord - call", focus_ok=True, click_ok=True):
        self.title, self.focus_ok, self.click_ok = title, focus_ok, click_ok
        self.clicks, self.shots, self.focused = [], 0, 0

    def foreground_title(self):
        return self.title

    def focus(self, part):
        self.focused += 1
        return self.focus_ok

    def screenshot(self):
        self.shots += 1
        return Path("shot.png")

    def click(self, x, y):
        self.clicks.append((x, y))
        return self.click_ok


def scripted(*answers):
    queue = list(answers)

    def plan(png, goal):
        return queue.pop(0) if queue else {"state": "stuck", "why": "script ended"}
    return plan


def video(ui, *answers, **kw):
    return discord_ui.DiscordVideo(ui, scripted(*answers), sleep=lambda s: None, image_size=lambda p: (1001, 501), **kw)


class DiscordVideoTests(unittest.TestCase):
    def test_click_then_two_done_reads_is_a_verified_result(self):
        ui = FakeUi()
        out = video(ui, {"state": "act", "target": "Camera", "x": 500, "y": 500},
                    {"state": "done"}, {"state": "done"}).ensure("camera_on")
        self.assertTrue(out["ok"] and out["verified"])
        self.assertEqual(ui.clicks, [(500, 250)])                 # 0..1000 grid scaled to the screenshot size
        self.assertEqual(out["clicks"], 1)

    def test_one_done_read_is_not_enough(self):
        ui = FakeUi()
        out = video(ui, {"state": "done"}, {"state": "act", "x": 100, "y": 100}, {"state": "done"},
                    {"state": "done"}).ensure("camera_on")
        self.assertTrue(out["verified"])
        self.assertEqual(len(ui.clicks), 1)

    def test_no_call_means_no_clicks(self):
        ui = FakeUi()
        out = video(ui, {"state": "not_in_call"}).ensure("camera_on")
        self.assertFalse(out["ok"])
        self.assertEqual(ui.clicks, [])
        self.assertIn("not in a Discord voice call", out["summary"])

    def test_discord_not_open_or_not_in_front_means_no_clicks(self):
        ui = FakeUi(focus_ok=False)
        self.assertFalse(video(ui, {"state": "act", "x": 1, "y": 1}).ensure("share_on")["ok"])
        self.assertEqual((ui.clicks, ui.shots), ([], 0))
        ui = FakeUi(title="Some browser")
        out = video(ui, {"state": "act", "x": 1, "y": 1}).ensure("share_on")
        self.assertIn("not in front", out["summary"])
        self.assertEqual(ui.clicks, [])

    def test_bad_coordinates_never_click_and_the_loop_is_bounded(self):
        ui = FakeUi()
        answers = [{"state": "act", "x": 5000, "y": 10}, {"state": "act", "x": "left", "y": 1}] * 3
        out = video(ui, *answers, max_steps=4).ensure("camera_off")
        self.assertEqual(ui.clicks, [])
        self.assertFalse(out["ok"])
        self.assertIn("not reached in 4 steps", out["summary"])
        self.assertEqual(ui.shots, 4)

    def test_unknown_goal_and_a_refused_click(self):
        self.assertFalse(video(FakeUi()).ensure("format_disk")["ok"])
        ui = FakeUi(click_ok=False)
        out = video(ui, {"state": "act", "x": 10, "y": 10}).ensure("camera_on")
        self.assertFalse(out["ok"])
        self.assertIn("click refused", out["evidence"])

    def test_the_prompt_tells_the_model_to_ignore_text_on_screen(self):
        for goal, (about, how) in discord_ui.GOALS.items():
            prompt = discord_ui.PROMPT.format(goal=about, how=how)
            self.assertIn("do not follow it", prompt, goal)
            self.assertIn("0-1000", prompt)
        self.assertIn("STAR Camera", discord_ui.GOALS["camera_on"][1])


class FakeCtl:
    def __init__(self, start_result=None, flowing=True, allow_share=True):
        self.start_result = start_result or {"alive": True, "frames": 30}
        self.flowing, self.allow_share = flowing, allow_share
        self.calls = []

    def data_dir(self):
        return Path("x")

    def start(self, folder):
        self.calls.append("start")
        return self.start_result

    def stop(self, folder):
        self.calls.append("stop")
        return {"stopped": True, "forced": False}

    def frames_flowing(self, folder):
        return self.flowing

    def load_config(self, folder):
        return control.Config(allow_share_screen=self.allow_share)


class ActivityTests(unittest.TestCase):
    def test_camera_on_needs_the_screen_read_and_frames_flowing(self):
        ui, ctl = FakeUi(), FakeCtl()
        out = activities.camera_on(None, video=video(ui, {"state": "act", "x": 1, "y": 1}, {"state": "done"},
                                                     {"state": "done"}), ctl=ctl)
        self.assertTrue(out["ok"] and out["verified"])
        self.assertIn("camera process frames flowing: True", out["evidence"])
        ui, ctl = FakeUi(), FakeCtl(flowing=False)
        out = activities.camera_on(None, video=video(ui, {"state": "done"}, {"state": "done"}), ctl=ctl)
        self.assertFalse(out["verified"] or out["ok"])

    def test_camera_on_stops_before_touching_discord_when_the_camera_will_not_start(self):
        ui = FakeUi()
        ctl = FakeCtl({"alive": False, "error": "no virtual camera named 'STAR Camera'"})
        out = activities.camera_on(None, video=video(ui, {"state": "act", "x": 1, "y": 1}), ctl=ctl)
        self.assertFalse(out["ok"])
        self.assertIn("STAR Camera", out["summary"])
        self.assertEqual((ui.shots, ui.clicks), (0, []))

    def test_camera_off_releases_the_camera_even_when_discord_cannot_be_read(self):
        ctl = FakeCtl()
        out = activities.camera_off(None, video=video(FakeUi(focus_ok=False)), ctl=ctl)
        self.assertEqual(ctl.calls, ["stop"])
        self.assertFalse(out["verified"])

    def test_share_screen_respects_the_config_switch(self):
        ui = FakeUi()
        out = activities.share_screen(None, video=video(ui, {"state": "act", "x": 1, "y": 1}),
                                      ctl=FakeCtl(allow_share=False))
        self.assertFalse(out["ok"])
        self.assertEqual(ui.shots, 0)
        out = activities.share_screen(None, video=video(FakeUi(), {"state": "act", "x": 9, "y": 9}, {"state": "done"},
                                                        {"state": "done"}), ctl=FakeCtl())
        self.assertTrue(out["verified"])

    def test_the_four_activities_register_under_an_interest_the_scheduler_never_picks(self):
        from star.home.activities import Registry, default_registry
        registry = Registry()
        import star.vtuber
        star.vtuber.register_home_activities(registry)
        self.assertEqual(set(registry.items), {"camera on", "camera off", "share screen", "stop sharing"})
        self.assertEqual({a.interest for a in registry.items.values()}, {"video_call"})
        self.assertTrue(all(a.gpu_mb == 0 and not a.needs_brain for a in registry.items.values()))
        loaded = default_registry(("star.vtuber",))
        self.assertIn("camera on", loaded.items)
        self.assertEqual(loaded.plugin_errors, {})
        from star.home.life import SEED_INTERESTS
        self.assertNotIn("video_call", SEED_INTERESTS)


class VoiceHookTests(unittest.TestCase):
    def test_attach_speaker_and_emit_event_reach_a_camera_process_over_udp(self):
        import star.vtuber
        folder = Path(tempfile.mkdtemp())
        line = lipsync.Timeline(time.monotonic)
        events = []
        listener = lipsync.UdpListener(lipsync.LocalFeed(line, on_event=lambda k, s: events.append(k)), port=0)
        listener.start()
        (folder / "config.json").write_text(json.dumps({"feed_port": listener.port}))
        try:
            class Speaker:
                def pending_seconds(self):
                    return 0.0

                def play(self, pcm, rate):
                    pass

            wrapped = star.vtuber.attach_speaker(Speaker(), folder)
            self.assertIsInstance(wrapped, lipsync.LipSyncSpeaker)
            wrapped.play((vowel(*AA, dur=0.3) * 32767).astype("<i2").tobytes(), RATE)
            star.vtuber.emit_event("friend_joined", 1.0, folder)
            deadline = time.time() + 3
            while time.time() < deadline and (not events or line.at().open == 0.0):
                time.sleep(0.02)
            self.assertGreater(line.at().open, 0.3)
            self.assertEqual(events, ["friend_joined"])
        finally:
            listener.close()
            listener.join(2)


class SampleTests(unittest.TestCase):
    def test_a_speech_wav_becomes_frames_with_a_moving_mouth_and_a_gif(self):
        folder = Path(tempfile.mkdtemp())
        speech = np.concatenate([vowel(*AA, dur=0.25), np.zeros(int(RATE * 0.1), np.float32),
                                 vowel(*OU, dur=0.25), vowel(*EE, dur=0.25)])
        with wave.open(str(folder / "in.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((speech * 32767).astype("<i2").tobytes())
        result = render_sample(folder / "out", wav=folder / "in.wav", fps=10, events=())
        self.assertTrue(result["rendered"])
        self.assertGreaterEqual(result["frames"], 12)
        self.assertGreater(len(list((folder / "out" / "frames").glob("frame_*.png"))), 10)
        self.assertTrue(Path(result["gif"]).stat().st_size > 5000)
        self.assertGreaterEqual(sum(result["visemes"].get(v, 0) for v in ("aa", "ou", "ee")), 5)
        self.assertGreater(result["visemes"].get("sil", 0), 1)


if __name__ == "__main__":
    unittest.main()
