"""Offline fake-MCP tests. No Roblox, account, image files, network or TTS."""
import asyncio
import base64
import unittest

from star.game_action_gate import GameActionHint, GameScope
from star.studio_playtest_host import StudioBinding, StudioPlaytestHost, StudioSnapshot
from star.stream_budget import StreamTelemetry
from star.studio_visual_evidence import (
    ObservationRejected, StudioVisualObserver, VisualAssessment,
)

SID = "studio_7"
SCOPE = GameScope("obby_demo", "version_1", "session_2")
PNG = b"\x89PNG\r\n\x1a\n" + b"offline-opaque-image-bytes"
JPEG = b"\xff\xd8\xff" + b"offline-opaque-image-bytes" + b"\xff\xd9"


def reply(*, content=None, structured=None, error=False):
    result = {"isError": error, "content": content or []}
    if structured is not None:
        result["structuredContent"] = structured
    return result


class FakeMCP:
    def __init__(self):
        self.mode = "Playing"
        self.connected = True
        self.fail = ""
        self.image = PNG
        self.mime = "image/png"
        self.text = '{"studios":[{"id":"studio_7","name":"private obby"}]}'
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == self.fail:
            raise OSError("not an image or valid status")
        if name == "list_roblox_studios":
            return reply(content=[{"type": "text", "text": (
                self.text if self.connected else '{"studios":[]}')}])
        if name == "get_studio_state":
            assert arguments == {"studio_id": SID}
            return reply(content=[{"type": "text",
                                   "text": '{"playState":"' + self.mode + '"}'}],
                         structured={"playState": self.mode})
        if name == "screen_capture":
            assert arguments["studio_id"] == SID
            return reply(content=[{"type": "image",
                                   "mimeType": self.mime,
                                   "data": base64.b64encode(self.image).decode("ascii")}])
        raise AssertionError("the observer must not call unknown or write tools")


class TestStudioVisualEvidence(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FakeMCP()
        self.permission = [True]
        self.tick = [1000]
        async def assessor(_image):
            return VisualAssessment(True, 0.91, "Visible platform, jump possible.")
        self.assessor = assessor

    def new_observer(self, **kw):
        opts = dict(session=self.mcp, studio_id=SID, scope=SCOPE,
                    focus_and_private=lambda _studio: self.permission[0],
                    assessor=self.assessor,
                    clock_ms=lambda: self.tick[0])
        opts.update(kw)
        return StudioVisualObserver(**opts)

    async def test_requires_explicit_owner_opt_in_without_tool_calls(self):
        obs = self.new_observer()
        with self.assertRaises(PermissionError):
            await obs.arm(owner_approved=1)
        self.assertFalse(self.mcp.calls)
        with self.assertRaises(PermissionError):
            await obs.observe()

    async def test_arm_requires_private_focus_and_exact_studio_selection(self):
        obs = self.new_observer()
        self.permission[0] = False
        with self.assertRaises(ObservationRejected):
            await obs.arm(owner_approved=True)
        self.assertFalse(self.mcp.calls)
        self.permission[0] = True
        self.mcp.connected = False
        with self.assertRaises(ObservationRejected):
            await obs.arm(owner_approved=True)
        self.assertFalse(obs.metrics()["armed"])

    async def test_rejects_edit_mode_before_capture(self):
        self.mcp.mode = "Edit"
        obs = self.new_observer()
        with self.assertRaisesRegex(ObservationRejected, "studio_not_playing"):
            await obs.arm(owner_approved=True)
        self.assertFalse(any(name == "screen_capture" for name, _ in self.mcp.calls))

    async def test_captures_real_image_digest_as_scoped_frame_not_game_success(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        result = await obs.observe()
        self.assertEqual(result.frame.scope, SCOPE)
        self.assertEqual(result.frame.sequence, 1)
        self.assertTrue(result.frame.focus_confirmed)
        self.assertTrue(result.frame.playable)
        self.assertAlmostEqual(result.frame.perception_confidence, .91)
        self.assertEqual(result.image_bytes, len(PNG))
        self.assertTrue(result.changed)
        self.assertTrue(result.actionable_when_captured)
        self.assertEqual(len(result.frame.evidence_sha256), 64)
        self.assertNotEqual(result.image_sha256, result.frame.evidence_sha256)
        self.assertEqual(obs.metrics()["observations"], 1)
        self.assertEqual([a[0] for a in self.mcp.calls], [
            "list_roblox_studios", "get_studio_state",
            "get_studio_state", "screen_capture"])

    async def test_duplicate_image_is_not_new_visual_information(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        first = await obs.observe()
        second = await obs.observe()
        self.assertFalse(second.changed)
        self.assertEqual(second.frame.perception_confidence, 0.0)
        self.assertFalse(second.actionable_when_captured)
        self.assertEqual(obs.metrics()["cache_hits"], 1)
        self.assertEqual(second.frame.sequence, 2)
        self.assertEqual(first.frame.evidence_sha256, second.frame.evidence_sha256)
        self.assertEqual(obs.metrics()["unchanged"], 1)

    async def test_scope_binds_digest_and_no_success_claim(self):
        obs = self.new_observer()
        other = self.new_observer(scope=GameScope("obby_demo", "version_2", "session_2"))
        await obs.arm(owner_approved=True)
        await other.arm(owner_approved=True)
        self.assertNotEqual((await obs.observe()).frame.evidence_sha256,
                            (await other.observe()).frame.evidence_sha256)

    async def test_lost_focus_after_capture_discards_result(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        async def lose_focus(_image):
            self.permission[0] = False
            return VisualAssessment(True, .9)
        obs._assessor = lose_focus
        with self.assertRaisesRegex(ObservationRejected, "private_focus_unverified"):
            await obs.observe()
        self.assertEqual(obs.metrics()["observations"], 0)

    async def test_host_clock_age_marks_stale_not_actionable(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        async def slow(_image):
            self.tick[0] += 401
            return VisualAssessment(True, .99)
        obs._assessor = slow
        result = await obs.observe()
        self.assertFalse(result.actionable_when_captured)
        self.assertEqual(result.frame.captured_ms, 1000)

    async def test_malformed_image_is_never_passed_to_assessor(self):
        count = [0]
        async def tracked(_image):
            count[0] += 1
            return VisualAssessment(True, .9)
        obs = self.new_observer(assessor=tracked)
        await obs.arm(owner_approved=True)
        self.mcp.image = b"fake content"
        with self.assertRaisesRegex(ObservationRejected, "image_type_mismatch"):
            await obs.observe()
        self.assertEqual(count[0], 0)

    async def test_image_type_mismatch_and_valid_jpeg(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        self.mcp.mime = "image/jpeg"
        with self.assertRaises(ObservationRejected):
            await obs.observe()
        self.mcp.image = JPEG
        result = await obs.observe()
        self.assertEqual(result.image_bytes, len(JPEG))

    async def test_assessor_timeout_fails_closed(self):
        obs = self.new_observer(assess_timeout_s=.05)
        await obs.arm(owner_approved=True)
        async def hang(_image):
            await asyncio.sleep(.2)
            return VisualAssessment(True, .99)
        obs._assessor = hang
        with self.assertRaisesRegex(ObservationRejected, "visual_assessor_unavailable"):
            await obs.observe()
        self.assertEqual(obs.metrics()["observations"], 0)

    async def test_transport_errors_do_not_leak_credentials_or_strings(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        self.mcp.fail = "screen_capture"
        with self.assertRaisesRegex(ObservationRejected, "studio_tool_unavailable") as err:
            await obs.observe()
        self.assertNotIn("image or valid status", str(err.exception))

    async def test_disarm_prevents_future_capture(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        obs.disarm()
        with self.assertRaises(PermissionError):
            await obs.observe()
        self.assertFalse(obs.metrics()["armed"])

    async def test_invalid_assessor_and_unexpected_state_fail_closed(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        self.mcp.mode = "Starting"
        with self.assertRaisesRegex(ObservationRejected, "invalid_studio_state"):
            await obs.observe()
        self.mcp.mode = "Playing"
        async def invalid(_image):
            return {"confidence": 1}
        obs._assessor = invalid
        with self.assertRaisesRegex(ObservationRejected, "invalid_visual_assessment"):
            await obs.observe()

    async def test_revoked_during_vision_never_returns_actionable_evidence(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        async def revoke(_image):
            obs.disarm()
            return VisualAssessment(True, 0.99)
        obs._assessor = revoke
        with self.assertRaisesRegex(ObservationRejected, "observation_session_revoked"):
            await obs.observe()
        self.assertEqual(obs.metrics()["observations"], 0)
        self.assertFalse(obs.metrics()["armed"])

    async def test_arming_twice_requires_explicit_disarm(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        with self.assertRaises(RuntimeError):
            await obs.arm(owner_approved=True)
        obs.disarm()
        await obs.arm(owner_approved=True)
        self.assertEqual((await obs.observe()).frame.sequence, 1)

    async def test_disarm_mid_handshake_does_not_reenable_sensor(self):
        obs = self.new_observer()
        original = self.mcp.call_tool
        async def cancel_during_handshake(name, arguments=None):
            result = await original(name, arguments)
            if name == "get_studio_state":
                obs.disarm()
            return result
        self.mcp.call_tool = cancel_during_handshake
        with self.assertRaisesRegex(ObservationRejected, "authorization_revoked_during_arm"):
            await obs.arm(owner_approved=True)
        self.assertFalse(obs.metrics()["armed"])

    async def test_older_host_mode_line_is_supported(self):
        from star.studio_visual_evidence import _play_state
        result = reply(content=[{"type": "text", "text": "- Current Studio Mode: Play\r\n"}])
        self.assertTrue(_play_state(result))
        with self.assertRaisesRegex(ObservationRejected, "invalid_studio_state"):
            _play_state(reply(content=[{"type": "text", "text": "- Current Studio Mode: Unknown"}]))

    async def test_real_image_frame_enters_existing_protected_action_gate(self):
        obs = self.new_observer()
        await obs.arm(owner_approved=True)
        captured = await obs.observe()
        frame = captured.frame
        # Real screenshot digest rather than a fabricated constant enters
        # the existing trusted private-playtest action gate.
        self.tick[0] = 1020
        host = StudioPlaytestHost(clock_ms=lambda: self.tick[0],
                                  sleeper=lambda sec: self.tick.__setitem__(
                                      0, self.tick[0] + 1000 * sec))
        host.start(studio_id=SID, scope=SCOPE,
                   bindings=[StudioBinding("jump", "SPACE")], owner_approved=True)
        hint = GameActionHint("jump", frame.sequence, frame.evidence_sha256,
                              frame.captured_ms + 10, 70)
        telemetry = StreamTelemetry(False, True, 4200, 8192, 60, 0)
        permit = host.request(frame, hint, now_ms=1020,
                              host_verified=True, telemetry=telemetry)
        self.assertTrue(permit.offered)

        class FakePort:
            def __init__(self):
                self.events = []
            def snapshot(self, studio_id):
                return StudioSnapshot(studio_id, SCOPE, True, True, True, True)
            def key_down(self, studio_id, key):
                self.events.append(("down", studio_id, key))
            def key_up(self, studio_id, key):
                self.events.append(("up", studio_id, key))

        port = FakePort()
        report = host.dispatch(permit, port=port)
        self.assertTrue(report.sent and report.input_released)
        self.assertFalse(report.gameplay_success_verified)
        self.assertEqual(port.events, [("down", SID, "SPACE"), ("up", SID, "SPACE")])
        duplicate = await obs.observe()
        self.assertFalse(duplicate.changed)
        self.assertEqual(duplicate.frame.perception_confidence, 0.0)
        blocked = host.request(duplicate.frame,
                               GameActionHint("jump", duplicate.frame.sequence,
                                              duplicate.frame.evidence_sha256,
                                              self.tick[0] + 1, 50),
                               now_ms=self.tick[0] + 1,
                               host_verified=True, telemetry=telemetry)
        self.assertFalse(blocked.offered)
        self.assertTrue(host.revoke(port=port))

    def test_rejects_untrusted_schema_fields(self):
        with self.assertRaises(ValueError):
            VisualAssessment(True, float("nan"))
        with self.assertRaises(ValueError):
            VisualAssessment(1, .9)
        with self.assertRaises(ValueError):
            VisualAssessment(True, .9, "\x00secret")
        with self.assertRaises(ValueError):
            self.new_observer(studio_id="../other")
