"""Real PCM envelope tests: deterministic waveforms, not fake level observations."""
from __future__ import annotations

from array import array
import math
import sys
import unittest

from star.stream_director import StreamSignal
from star.stream_motion import plan_motion
from star.stream_pcm_envelope import PcmEnvelopeBuilder, pcm16_to_envelope
from star.stream_playout_clock import StarPlayoutClock
from star.stream_stage import StarStage


def pcm(values: list[int]) -> bytes:
    samples = array("h", values)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def tone(*, rate: int = 24000, frames: int = 24000,
         amplitude: int = 9000, channels: int = 1,
         silence_frames: int = 0) -> bytes:
    samples: list[int] = []
    for index in range(frames):
        value = (0 if index < silence_frames
                 else round(amplitude * math.sin(2 * math.pi * 330 * index / rate)))
        samples.append(value)
        if channels == 2:
            samples.append(-value)
    return pcm(samples)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class PcmEnvelopeTests(unittest.TestCase):
    def test_real_wave_makes_mouth_move_after_silence(self):
        audio = tone(frames=24000, silence_frames=4800)
        env = pcm16_to_envelope(audio, sample_rate_hz=24000)
        self.assertEqual(env.frames, 24000)
        self.assertEqual(env.duration_s, 1.0)
        self.assertEqual(env.audio_levels[0].at_s, 0)
        self.assertEqual(env.audio_levels[0].rms, 0)
        self.assertTrue(all(x.rms == 0 for x in env.audio_levels if x.at_s <= .20))
        self.assertGreater(max(x.rms for x in env.audio_levels), .6)
        # Star's actual rig planner receives signal-derived levels, not a text guess.
        frames = plan_motion(duration_s=env.duration_s, audio_levels=env.audio_levels, fps=30)
        self.assertTrue(all(f.mouth_open == 0 for f in frames if f.at_s <= .15))
        self.assertGreater(max(f.mouth_open for f in frames if f.at_s >= .3), .4)

    def test_stereo_opposite_phase_preserves_energy(self):
        mono = pcm16_to_envelope(tone(frames=2400), sample_rate_hz=24000)
        stereo = pcm16_to_envelope(tone(frames=2400, channels=2),
                                   sample_rate_hz=24000, channels=2)
        self.assertEqual(stereo.frames, mono.frames)
        for a, b in zip(mono.audio_levels, stereo.audio_levels):
            self.assertAlmostEqual(a.rms, b.rms, places=7)

    def test_byte_fragmentation_does_not_change_timing(self):
        audio = tone(rate=11025, frames=11025, channels=2)
        expected = pcm16_to_envelope(audio, sample_rate_hz=11025, channels=2)
        for chunk_size in (1, 3, 7, 59, 901, 32768):
            with self.subTest(chunk_size=chunk_size):
                builder = PcmEnvelopeBuilder(sample_rate_hz=11025, channels=2)
                for index in range(0, len(audio), chunk_size):
                    builder.feed(audio[index:index + chunk_size])
                self.assertEqual(builder.finish(), expected)
        self.assertEqual(expected.audio_levels[-1].at_s, 1.0)

    def test_window_timestamps_at_end_not_future_onset(self):
        # 10 ms of sound cannot open the mouth at t=0: only t=10 ms is known.
        audio = tone(rate=24000, frames=240)
        env = pcm16_to_envelope(audio, sample_rate_hz=24000, window_ms=10)
        self.assertEqual([x.at_s for x in env.audio_levels], [0.0, .01])
        self.assertEqual(env.audio_levels[0].rms, 0)
        self.assertGreater(env.audio_levels[-1].rms, 0)

    def test_partial_last_window_uses_real_end_timestamp(self):
        audio = tone(frames=2447)
        env = pcm16_to_envelope(audio, sample_rate_hz=24000)
        self.assertEqual(env.frames, 2447)
        self.assertEqual(env.audio_levels[-1].at_s, 2447 / 24000)
        self.assertEqual(len(env.audio_levels), 7)

    def test_very_quiet_audio_gated_and_gain_bounded(self):
        audio = tone(amplitude=90)
        quiet = pcm16_to_envelope(audio, sample_rate_hz=24000)
        self.assertTrue(all(x.rms == 0 for x in quiet.audio_levels))
        loud = pcm16_to_envelope(tone(amplitude=30000),
                                 sample_rate_hz=24000, gain=12)
        self.assertTrue(all(0 <= x.rms <= 1 for x in loud.audio_levels))
        self.assertIn(1.0, [x.rms for x in loud.audio_levels])

    def test_silent_audio_never_opens_mouth(self):
        env = pcm16_to_envelope(pcm([0] * 24000), sample_rate_hz=24000)
        self.assertTrue(all(x.rms == 0 for x in env.audio_levels))
        frames = plan_motion(duration_s=1, audio_levels=env.audio_levels)
        self.assertTrue(all(x.mouth_open == 0 for x in frames))

    def test_full_15_seconds_at_10ms_avoids_motion_point_overflow(self):
        audio = pcm([0] * (8000 * 15))
        env = pcm16_to_envelope(audio, sample_rate_hz=8000, window_ms=10)
        self.assertEqual(len(env.audio_levels), 1500)
        self.assertEqual(env.audio_levels[0].at_s, 0.01)
        self.assertEqual(env.audio_levels[-1].at_s, 15)
        self.assertEqual(len(plan_motion(
            duration_s=15, audio_levels=env.audio_levels, fps=30,
        )), 451)

    def test_rejects_truncated_audio_without_pretend_frames(self):
        b = PcmEnvelopeBuilder(sample_rate_hz=24000, channels=2)
        b.feed(b"\x01\x00\x02\x00\xff")
        with self.assertRaisesRegex(ValueError, "truncated"):
            b.finish()
        with self.assertRaises(RuntimeError):
            b.feed(b"")

    def test_empty_and_malformed_and_replayed_finalize(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            PcmEnvelopeBuilder(sample_rate_hz=24000).finish()
        with self.assertRaises((ValueError, TypeError)):
            pcm16_to_envelope(b"\x00", sample_rate_hz=24000)
        b = PcmEnvelopeBuilder(sample_rate_hz=24000)
        with self.assertRaises(ValueError):
            b.feed("bad")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            b.feed(b"\0" * 1_048_577)
        b.feed(pcm([1] * 240))
        self.assertEqual(b.finish().frames, 240)
        with self.assertRaises(RuntimeError):
            b.finish()

    def test_strict_numeric_parameters_and_limits(self):
        for rate, channels, gain, floor, win in (
            (True, 1, 4., .01, 20),
            (24000, False, 4., .01, 20),
            (24000, 3, 4., .01, 20),
            (24000, 1, float("nan"), .01, 20),
            (24000, 1, 4., float("inf"), 20),
            (24000, 1, 4., -.1, 20),
            (24000, 1, 4., .01, 17),
        ):
            with self.subTest(params=(rate, channels, gain, floor, win)):
                with self.assertRaises(ValueError):
                    PcmEnvelopeBuilder(sample_rate_hz=rate, channels=channels,
                                       gain=gain, noise_floor=floor, window_ms=win)
        b = PcmEnvelopeBuilder(sample_rate_hz=8000)
        b.feed(pcm([0] * (8000 * 15)))
        with self.assertRaisesRegex(ValueError, "15 seconds"):
            b.feed(pcm([0]))

    def test_no_motion_before_real_device_playhead(self):
        clock = Clock()
        stage = StarStage(clock=clock)
        stage.enable(owner_approved=True)
        self.assertTrue(stage.offer(StreamSignal(
            "pcm-event", "game_success", clock.now, "checkpoint", evidence="observed"
        ), now=clock.now))
        plan = stage.prepare(now=clock.now)
        self.assertIsNotNone(plan)
        assert plan is not None
        rig = StarPlayoutClock(stage, clock=clock)
        rig.enable(owner_approved=True)
        audio = tone(frames=14400, silence_frames=4800)
        # Neither a TTS buffer nor an armed animation is proof of actual playout.
        self.assertFalse(rig.arm_pcm16(plan, pcm16le=audio, sample_rate_hz=24000))
        self.assertTrue(stage.queue_audio(plan, now=clock.now))
        self.assertFalse(rig.arm_pcm16(plan, pcm16le=audio, sample_rate_hz=24000))
        self.assertTrue(stage.acknowledge_audible(plan, now=clock.now))
        self.assertTrue(rig.arm_pcm16(plan, pcm16le=audio, sample_rate_hz=24000))
        self.assertAlmostEqual(rig.duration_if_armed(plan), .6)
        self.assertIsNone(rig.sample(plan))  # no heard cursor yet
        self.assertTrue(rig.observe_playhead(
            plan, position_s=0, sampled_at=clock.now))
        self.assertEqual(rig.sample(plan).motion.mouth_open, 0)
        for i in range(1, 5):
            clock.now += .1
            self.assertTrue(rig.observe_playhead(
                plan, position_s=.1 * i, sampled_at=clock.now))
        frame = rig.sample(plan)
        self.assertIsNotNone(frame)
        self.assertGreater(frame.motion.mouth_open, .3)
        self.assertTrue(rig.current(frame))
        stage.interrupt(now=clock.now)
        self.assertFalse(rig.current(frame))
        self.assertIsNone(rig.sample(plan))


if __name__ == "__main__":
    unittest.main()
