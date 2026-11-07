"""Offline, deterministic QoS tests: no live Studio, network, GPU or audio."""
import asyncio
import base64
import unittest

from star.game_action_gate import GameScope
from star.stream_budget import StreamTelemetry
from star.studio_visual_evidence import StudioVisualObserver, VisualAssessment
from star.studio_vision_qos import StudioVisionQoS


SID = "studio_7"
SCOPE = GameScope("obby", "v1", "test_1")
PNG = b"\x89PNG\r\n\x1a\n" + b"opaque-fake-image"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"different-opaque-image"


def tele(*, live=False, fps=60, vram=4200, backlog=0, active=True):
    return StreamTelemetry(live, active, vram, 8192, fps, backlog)


class FakeMCP:
    def __init__(self):
        self.calls = []
        self.image = PNG
        self.mode = "Playing"
        self.fail = False

    async def call_tool(self, name, arguments=None):
        self.calls.append(name)
        if name == "list_roblox_studios":
            return {"isError": False, "content": [
                {"type": "text", "text": '{"studios":[{"id":"studio_7","name":"private obby"}]}'}]}
        if name == "get_studio_state":
            return {"isError": False, "structuredContent": {"playState": self.mode}}
        if name == "screen_capture":
            if self.fail:
                raise OSError("private credentials should not appear in errors")
            return {"isError": False, "content": [
                {"type": "image", "mimeType": "image/png",
                 "data": base64.b64encode(self.image).decode("ascii")}]}
        raise AssertionError("unexpected tool " + name)


class TestStudioVisionQoS(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mcp = FakeMCP()
        self.tick = [1000.0]
        self.permission = [True]

        async def assess(_data):
            return VisualAssessment(True, .95, "Visible private obby.")

        self.observer = StudioVisualObserver(
            session=self.mcp, studio_id=SID, scope=SCOPE,
            focus_and_private=lambda _id: self.permission[0],
            assessor=assess, clock_ms=lambda: self.tick[0])
        self.qos = StudioVisionQoS(
            self.observer, clock_ms=lambda: self.tick[0])

    async def arm(self):
        await self.observer.arm(owner_approved=True)

    def captures(self):
        return self.mcp.calls.count("screen_capture")

    async def test_explicit_observer_consent_remains_required(self):
        result = await self.qos.sample(tele())
        self.assertEqual(result.reason, "visual_observation_unavailable")
        self.assertEqual(self.captures(), 0)
        self.assertFalse(self.qos.metrics()["observer_armed"])

    async def test_missing_inactive_and_bad_telemetry_never_capture(self):
        await self.arm()
        self.assertFalse((await self.qos.sample(None)).attempted)
        self.assertFalse((await self.qos.sample(tele(active=False))).attempted)
        with self.assertRaises(TypeError):
            await self.qos.sample({"game_fps": 60})
        self.assertEqual(self.captures(), 0)

    async def test_live_stream_caps_at_one_hz(self):
        await self.arm()
        self.assertTrue((await self.qos.sample(tele(live=True))).evidence.changed)
        self.tick[0] = 1999
        denied = await self.qos.sample(tele(live=True))
        self.assertEqual(denied.reason, "visual_sampling_cooldown")
        self.assertEqual(self.captures(), 1)
        self.tick[0] = 2000
        duplicate = await self.qos.sample(tele(live=True))
        self.assertFalse(duplicate.evidence.changed)
        self.assertEqual(duplicate.evidence.frame.perception_confidence, 0)
        self.assertEqual(self.qos.metrics()["duplicates"], 1)

    async def test_offline_cadence_and_exponential_duplicate_backoff(self):
        await self.arm()
        self.assertEqual((await self.qos.sample(tele())).reason, "new_visual_evidence")
        self.tick[0] = 1250
        self.assertEqual((await self.qos.sample(tele())).reason,
                         "identical_scene_no_new_action_evidence")
        self.tick[0] = 1749
        self.assertEqual((await self.qos.sample(tele())).reason, "visual_sampling_cooldown")
        self.tick[0] = 1750
        self.assertFalse((await self.qos.sample(tele())).evidence.changed)
        self.tick[0] = 2750
        self.mcp.image = PNG2
        self.assertTrue((await self.qos.sample(tele())).evidence.changed)
        self.tick[0] = 2999
        self.assertEqual((await self.qos.sample(tele())).reason, "visual_sampling_cooldown")
        self.tick[0] = 3000
        self.assertTrue((await self.qos.sample(tele())).attempted)
        self.assertEqual(self.qos.metrics()["duplicates_in_row"], 1)
        self.assertEqual(self.captures(), 5)

    async def test_live_telemetry_pressure_disables_capture_without_consuming_slot(self):
        await self.arm()
        self.assertEqual((await self.qos.sample(tele(live=True, fps=39))).reason,
                         "stream_vision_deferred")
        self.assertEqual((await self.qos.sample(tele(live=True, vram=1024))).reason,
                         "stream_vision_deferred")
        self.assertEqual((await self.qos.sample(tele(live=True, backlog=351))).reason,
                         "stream_vision_deferred")
        self.assertEqual(self.captures(), 0)
        self.assertTrue((await self.qos.sample(tele(live=True))).attempted)

    async def test_offline_low_fps_and_voice_pressure_still_protected(self):
        await self.arm()
        self.assertEqual((await self.qos.sample(tele(fps=29))).reason,
                         "realtime_game_or_voice_pressure")
        self.assertEqual((await self.qos.sample(tele(backlog=999))).reason,
                         "realtime_game_or_voice_pressure")
        self.assertEqual(self.captures(), 0)

    async def test_error_backoff_bounded_and_recovery(self):
        await self.arm()
        self.mcp.fail = True
        self.assertEqual((await self.qos.sample(tele())).reason,
                         "visual_observation_unavailable")
        self.tick[0] = 1999
        self.assertFalse((await self.qos.sample(tele())).attempted)
        self.tick[0] = 2000
        self.assertTrue((await self.qos.sample(tele())).attempted)
        self.tick[0] = 4000
        self.mcp.fail = False
        recovered = await self.qos.sample(tele())
        self.assertTrue(recovered.evidence.changed)
        self.assertEqual(self.qos.metrics()["sensor_failures_in_row"], 0)
        self.assertEqual(self.qos.metrics()["sensor_failures"], 2)

    async def test_no_concurrent_burst_sampling(self):
        await self.arm()
        results = await asyncio.gather(*(self.qos.sample(tele()) for _ in range(15)))
        self.assertEqual(sum(bool(x.evidence) for x in results), 1)
        self.assertEqual(self.captures(), 1)
        self.assertEqual(self.qos.metrics()["cadence_skips"], 14)

    async def test_revocation_still_blocks_sampling(self):
        await self.arm()
        self.observer.disarm()
        self.assertEqual((await self.qos.sample(tele())).reason,
                         "visual_observation_unavailable")
        self.assertEqual(self.captures(), 0)

    async def test_clock_reversal_is_not_reused_for_future_frames(self):
        await self.arm()
        await self.qos.sample(tele())
        self.tick[0] = 999
        with self.assertRaisesRegex(ValueError, "clock reversed"):
            await self.qos.sample(tele())
        self.tick[0] = 5000
        self.assertEqual((await self.qos.sample(tele())).reason, "visual_sampling_cooldown")

    async def test_no_sensitive_data_in_metrics_or_failures(self):
        await self.arm()
        self.mcp.fail = True
        await self.qos.sample(tele())
        values = str(self.qos.metrics())
        self.assertNotIn(SID, values)
        self.assertNotIn("opaque-fake-image", values)
        self.assertNotIn("private credentials", values)

    async def test_strict_constructor_bounds(self):
        with self.assertRaises(TypeError):
            StudioVisionQoS(object())
        with self.assertRaises(ValueError):
            StudioVisionQoS(self.observer, duplicate_backoff_cap_ms=10)
        with self.assertRaises(ValueError):
            StudioVisionQoS(self.observer, error_backoff_cap_ms=10)
