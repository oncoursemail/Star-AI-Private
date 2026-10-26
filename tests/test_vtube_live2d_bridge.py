"""No-network tests for Star's original, stage-bound Live2D API adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import math
import unittest

from star.stream_director import StreamSignal
from star.stream_motion import AudioLevel
from star.stream_stage import StarStage
from star.vtube_live2d_bridge import VTubeLive2DBridge


def audible_stage():
    stage = StarStage(clock=lambda: 100.0)
    stage.enable(owner_approved=True, mode="cat")
    sig = StreamSignal(
        signal_id="win",
        kind="game_success",
        timestamp=100,
        detail="Round result independently observed",
        evidence="observed",
    )
    assert stage.offer(sig, now=100)
    plan = stage.prepare(now=100)
    assert plan is not None
    assert stage.queue_audio(plan, now=100)
    assert stage.acknowledge_audible(plan, now=100)
    return stage, plan


class Live2DBridgeTests(unittest.TestCase):
    def setUp(self):
        self.stage, self.plan = audible_stage()
        self.bridge = VTubeLive2DBridge(self.stage, owner_approved=True)
        self.assertTrue(self.bridge.bind(self.plan, playback_epoch="audio-0001"))
        self.frames = self.stage.motion(
            self.plan,
            duration_s=1.0,
            audio_levels=[AudioLevel(0, 0.7)],
            fps=30,
            seed=1,
        )

    def packet(self, index=0, *, at_ms=1000.0, cursor=None, epoch="audio-0001"):
        frame = self.frames[index]
        return self.bridge.frame_packet(
            self.plan,
            playback_epoch=epoch,
            frame=frame,
            sampled_ms=at_ms,
            audible_cursor_s=frame.at_s if cursor is None else cursor,
        )

    def test_owner_opt_in_and_real_stage_required(self):
        with self.assertRaises(PermissionError):
            VTubeLive2DBridge(self.stage)
        with self.assertRaises(PermissionError):
            VTubeLive2DBridge(self.stage, owner_approved=1)
        with self.assertRaises(TypeError):
            VTubeLive2DBridge(object(), owner_approved=True)

    def test_real_custom_parameter_registration_schema(self):
        requests = self.bridge.registration_requests()
        self.assertEqual(len(requests), 14)
        self.assertEqual(len({r["data"]["parameterName"] for r in requests}), 14)
        self.assertTrue(all(r["messageType"] == "ParameterCreationRequest" for r in requests))
        self.assertTrue(
            all(4 <= len(r["data"]["parameterName"]) <= 32 and r["data"]["parameterName"].isalnum() for r in requests)
        )
        self.assertEqual(requests[0]["data"]["min"], 0)
        self.assertEqual(requests[1]["data"]["defaultValue"], 1)

    def test_bind_rejects_non_audible_and_duplicate(self):
        self.assertFalse(self.bridge.bind(self.plan, playback_epoch="again"))
        other = StarStage(clock=lambda: 100)
        other.enable(owner_approved=True)
        other.offer(StreamSignal("one", "ambient", 100, "Look at this"), now=100)
        pending = other.prepare(now=100)
        bridge = VTubeLive2DBridge(other, owner_approved=True)
        self.assertFalse(bridge.bind(pending, playback_epoch="epoch-one"))

    def test_valid_packet_is_real_vts_schema_not_device_io(self):
        packet = self.packet()
        self.assertEqual(packet["apiName"], "VTubeStudioPublicAPI")
        self.assertEqual(packet["apiVersion"], "1.0")
        self.assertEqual(packet["messageType"], "InjectParameterDataRequest")
        self.assertEqual(packet["data"]["mode"], "set")
        self.assertNotIn("faceFound", packet["data"])
        values = {v["id"]: v["value"] for v in packet["data"]["parameterValues"]}
        self.assertGreater(values["StarMouthOpen"], 0)
        self.assertEqual(values["StarEyeOpenLeft"], 1)
        self.assertTrue(all(v["weight"] == 1 for v in packet["data"]["parameterValues"]))
        self.assertNotIn("Round result", json.dumps(packet))
        self.assertNotIn("audio-0001", json.dumps(packet))

    def test_no_future_or_outdated_motion_is_ever_emitted(self):
        self.assertIsNone(self.packet(3, at_ms=1000, cursor=0))
        self.assertIsNone(self.packet(0, at_ms=1000, cursor=0.2))
        self.assertEqual(self.bridge.status().accepted_frames, 0)
        self.assertIsNotNone(self.packet(0, at_ms=1000, cursor=0))

    def test_duplicate_timestamp_dropped_even_with_new_clock(self):
        self.assertIsNotNone(self.packet())
        self.assertIsNone(self.packet(at_ms=1040))
        self.assertIsNotNone(self.packet(2, at_ms=1070))

    def test_rate_limit_rejects_even_if_stage_frames_are_fast(self):
        self.assertIsNotNone(self.packet())
        self.assertIsNone(self.packet(1, at_ms=1010))
        self.assertIsNotNone(self.packet(1, at_ms=1033))

    def test_clock_reversal_and_audio_cursor_reversal(self):
        self.assertIsNotNone(self.packet(0, at_ms=1000))
        self.assertIsNotNone(self.packet(2, at_ms=1070))
        self.assertIsNone(self.packet(3, at_ms=1060))
        self.assertIsNone(self.packet(3, at_ms=1100, cursor=0.03))

    def test_epoch_mismatch_drop_and_untrusted_epoch_rejection(self):
        self.assertIsNone(self.packet(epoch="wrong"))
        for epoch in ("", "hello xyz", "../escape", "x" * 65, None):
            with self.subTest(epoch=epoch):
                with self.assertRaises(ValueError):
                    self.packet(epoch=epoch)
        self.assertEqual(self.bridge.status().accepted_frames, 0)

    def test_interrupted_stage_revokes_frames(self):
        self.stage.interrupt(now=100.1)
        self.assertIsNone(self.packet())
        self.assertIsNone(self.packet(1, at_ms=1034))
        self.assertFalse(self.stage.current(self.plan))

    def test_reset_requires_stopped_device_and_neutralizes_all_channels(self):
        with self.assertRaises(PermissionError):
            self.bridge.reset(self.plan, playback_epoch="audio-0001")
        self.stage.interrupt(now=100.1)
        reset = self.bridge.reset(
            self.plan,
            playback_epoch="audio-0001",
            playback_stopped=True,
        )
        values = {v["id"]: v["value"] for v in reset["data"]["parameterValues"]}
        self.assertEqual(values["StarMouthOpen"], 0)
        self.assertEqual(values["StarHairSway"], 0)
        self.assertEqual(values["StarTailSway"], 0)
        self.assertEqual(values["StarEyeOpenLeft"], 1)
        self.assertFalse(self.bridge.status().active)
        self.assertIsNone(self.packet())
        self.assertIsNone(
            self.bridge.reset(
                self.plan,
                playback_epoch="audio-0001",
                playback_stopped=True,
            )
        )

    def test_cannot_rebind_the_same_turn_after_reset(self):
        self.assertIsNotNone(
            self.bridge.reset(
                self.plan,
                playback_epoch="audio-0001",
                playback_stopped=True,
            )
        )
        self.assertFalse(self.bridge.bind(self.plan, playback_epoch="audio-replay"))

    def test_old_reset_cannot_override_a_new_turn(self):
        self.stage.interrupt(now=100.1)
        self.assertIsNotNone(
            self.bridge.reset(
                self.plan,
                playback_epoch="audio-0001",
                playback_stopped=True,
            )
        )
        new_signal = StreamSignal("new-turn", "game_danger", 100.2, "Obstacle", evidence="observed")
        self.assertTrue(self.stage.offer(new_signal, now=100.2))
        new_plan = self.stage.prepare(now=100.2)
        self.assertTrue(self.stage.queue_audio(new_plan, now=100.2))
        self.assertTrue(self.stage.acknowledge_audible(new_plan, now=100.2))
        self.assertTrue(self.bridge.bind(new_plan, playback_epoch="audio-0002"))
        self.assertIsNone(
            self.bridge.reset(
                self.plan,
                playback_epoch="audio-0001",
                playback_stopped=True,
            )
        )
        self.assertTrue(self.bridge.status().active)
        self.assertEqual(self.bridge.status().active_sequence, new_plan.sequence)

    def test_forged_frame_values_rejected_not_clipped(self):
        for field, value in (
            ("mouth_open", math.nan),
            ("mouth_open", math.inf),
            ("mouth_open", -1),
            ("smile", 2),
            ("hair_sway", 2),
            ("eye_open_left", False),
            ("at_s", -1),
            ("at_s", 16),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.bridge.frame_packet(
                        self.plan,
                        playback_epoch="audio-0001",
                        frame=replace(self.frames[0], **{field: value}),
                        audible_cursor_s=0,
                        sampled_ms=1000,
                    )
        self.assertEqual(self.bridge.status().accepted_frames, 0)

    def test_invalid_host_clock_rejected(self):
        for sampled_ms, cursor in ((math.nan, 0), (-1, 0), (0, math.inf), (False, 0), (0, -1)):
            with self.subTest(ms=sampled_ms, cursor=cursor):
                with self.assertRaises(ValueError):
                    self.bridge.frame_packet(
                        self.plan,
                        playback_epoch="audio-0001",
                        frame=self.frames[0],
                        audible_cursor_s=cursor,
                        sampled_ms=sampled_ms,
                    )

    def test_parallel_same_frame_admits_once(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.packet(), range(32)))
        self.assertEqual(sum(packet is not None for packet in results), 1)
        self.assertEqual(self.bridge.status().accepted_frames, 1)

    def test_frame_interval_requires_bounded_finite_number(self):
        for interval in (15, 201, math.nan, True, "33"):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    VTubeLive2DBridge(
                        self.stage,
                        owner_approved=True,
                        min_frame_interval_ms=interval,
                    )

    def test_finish_stage_revokes_old_motion(self):
        self.assertIsNotNone(self.packet())
        self.assertTrue(self.stage.finish(self.plan, now=100.1, played_to_end=True))
        self.assertIsNone(self.packet(1, at_ms=1034))
        self.assertEqual(self.stage.metrics()["director"]["completed"], 1)


if __name__ == "__main__":
    unittest.main()
