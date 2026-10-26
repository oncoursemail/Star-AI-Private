"""Offline tests for the authenticated, loopback-only Live2D transport."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from star.vtube_live2d_bridge import VTubeLive2DBridge
from star.vtube_local_host import VTSHostError, VTubeLocalHost


class FakeSocket:
    def __init__(self, *, fail_type=None, error_type=None, response_type=None, bad_id=False, bad_param=False):
        self.sent = []
        self.closed = False
        self.timeout = None
        self.fail_type = fail_type
        self.error_type = error_type
        self.response_type = response_type
        self.bad_id = bad_id
        self.bad_param = bad_param

    def send(self, raw):
        packet = json.loads(raw)
        if packet["messageType"] == self.fail_type:
            raise OSError("test socket closed")
        self.sent.append(packet)

    def recv(self):
        request = self.sent[-1]
        kind = request["messageType"]
        data = {}
        if kind == "APIStateRequest":
            data = {"active": True}
        elif kind == "AuthenticationTokenRequest":
            data = {"authenticationToken": "fake-test-only-token"}
        elif kind == "AuthenticationRequest":
            data = {"authenticated": True}
        elif kind == "ParameterCreationRequest":
            data = {"parameterName": "wrong" if self.bad_param else request["data"]["parameterName"]}
        response = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "wrong" if self.bad_id else request["requestID"],
            "messageType": (
                "APIError" if kind == self.error_type else self.response_type or kind.replace("Request", "Response")
            ),
            "data": data,
        }
        return json.dumps(response)

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class FakeStage:
    def __init__(self):
        self.live = True

    def current(self, _):
        return self.live


def bridge_fixture(stage):
    # Isolation: existing playback bridge has its own tests. This suite tests
    # transport state, auth, timing, permissions and error handling instead.
    bridge = object.__new__(VTubeLive2DBridge)
    bridge._stage = stage
    bridge.registration_requests = Mock(
        return_value=tuple(
            {"messageType": "ParameterCreationRequest", "data": {"parameterName": f"StarParam{i}"}}
            for i in range(14)
        )
    )
    bridge.frame_packet = Mock(
        return_value={"messageType": "InjectParameterDataRequest", "data": {"mode": "set", "parameterValues": []}}
    )
    bridge.reset = Mock(
        return_value={"messageType": "InjectParameterDataRequest", "data": {"mode": "set", "parameterValues": []}}
    )
    return bridge


class LocalHostTests(unittest.TestCase):
    def setUp(self):
        self.stage = FakeStage()
        self.bridge = bridge_fixture(self.stage)
        self.socket = FakeSocket()
        self.now = 100.0
        self.host = VTubeLocalHost(
            self.bridge, owner_approved=True, socket_factory=lambda url, timeout: self.socket,
            monotonic=lambda: self.now,
        )

    def connect(self, *, register=True, token="host-token"):
        self.assertEqual(self.host.connect(authentication_token=token), token)
        if register:
            self.host.register_parameters()

    def test_owner_approval_and_loopback_enforced(self):
        with self.assertRaises(PermissionError):
            VTubeLocalHost(self.bridge)
        with self.assertRaises(TypeError):
            VTubeLocalHost(object(), owner_approved=True)
        for endpoint in ("ws://localhost:8001", "ws://0.0.0.0:8001", "wss://127.0.0.1:8001",
                         "ws://127.0.0.1:0", "ws://127.0.0.1:99999", "ws://127.0.0.1:8001/path",
                         "ws://127.0.0.1:8001@attacker.com"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                VTubeLocalHost(self.bridge, owner_approved=True, endpoint=endpoint)
        self.assertFalse(self.host.connected)

    def test_existing_token_auth_and_registration(self):
        self.connect()
        names = [p["messageType"] for p in self.socket.sent]
        self.assertEqual(names[:2], ["APIStateRequest", "AuthenticationRequest"])
        self.assertNotIn("AuthenticationTokenRequest", names)
        self.assertEqual(names.count("ParameterCreationRequest"), 14)
        self.host.register_parameters()
        self.assertEqual(len(self.socket.sent), 16)
        self.assertTrue(self.host.connected)
        self.assertEqual(self.socket.timeout, 0.1)

    def test_first_pairing_requires_owner_specific_flag(self):
        with self.assertRaises(PermissionError):
            self.host.connect()
        token = self.host.connect(allow_new_token=True)
        self.assertEqual(token, "fake-test-only-token")
        self.assertEqual(self.socket.sent[1]["messageType"], "AuthenticationTokenRequest")
        self.assertEqual(self.socket.sent[2]["data"]["authenticationToken"], token)

    def test_invalid_token_not_sent_or_logged(self):
        for token in ("", "bad token", "x" * 65, "token\n", 12, False):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.host.connect(authentication_token=token)
        self.assertEqual(self.socket.sent, [])

    def test_frames_need_registration_and_are_checked_at_send_time(self):
        self.connect(register=False)
        with self.assertRaises(VTSHostError):
            self.host.send_frame("plan", playback_epoch="p1", frame="frame", audible_cursor_s=0, sampled_ms=99999)
        self.host.register_parameters()
        self.assertTrue(self.host.send_frame("plan", playback_epoch="p1", frame="frame", audible_cursor_s=0, sampled_ms=99999))
        self.assertEqual(self.socket.sent[-1]["messageType"], "InjectParameterDataRequest")
        self.assertEqual(self.bridge.frame_packet.call_count, 1)
        self.stage.live = False
        self.assertFalse(self.host.send_frame("plan", playback_epoch="p1", frame="frame", audible_cursor_s=0, sampled_ms=100000))
        self.assertEqual(self.bridge.frame_packet.call_count, 1)

    def test_drops_stale_future_nonfinite_and_bool_timing(self):
        self.connect()
        for stamp in (99899, 100001, float("nan"), float("inf"), True, "100000"):
            with self.subTest(stamp=stamp):
                self.assertFalse(self.host.send_frame("plan", playback_epoch="p", frame="x", audible_cursor_s=0, sampled_ms=stamp))
        self.assertEqual(self.bridge.frame_packet.call_count, 0)
        self.assertEqual(len(self.socket.sent), 16)

    def test_stage_revocation_between_packet_creation_and_send(self):
        self.connect()
        def revoked(*args, **kwargs):
            self.stage.live = False
            return {"messageType": "InjectParameterDataRequest", "data": {"mode": "set", "parameterValues": []}}
        self.bridge.frame_packet.side_effect = revoked
        self.assertFalse(self.host.send_frame("plan", playback_epoch="p", frame="x", audible_cursor_s=0, sampled_ms=100000))
        self.assertEqual(len(self.socket.sent), 16)

    def test_neutral_requires_confirmed_stop_and_is_one_shot_when_bridge_enforces(self):
        self.connect()
        self.bridge.reset.side_effect = [PermissionError("not stopped"), {"messageType": "InjectParameterDataRequest", "data": {}}, None]
        with self.assertRaises(PermissionError):
            self.host.send_neutral("plan", playback_epoch="p")
        self.assertTrue(self.host.send_neutral("plan", playback_epoch="p", playback_stopped=True))
        self.assertFalse(self.host.send_neutral("plan", playback_epoch="p", playback_stopped=True))

    def test_bad_responses_and_auth_fail_closed(self):
        for flags in ({"bad_id": True}, {"response_type": "WrongResponse"}, {"error_type": "AuthenticationRequest"},
                      {"fail_type": "AuthenticationRequest"}):
            with self.subTest(flags=flags):
                self.socket = FakeSocket(**flags)
                with self.assertRaises(VTSHostError):
                    self.host.connect(authentication_token="host-token")
                self.assertFalse(self.host.connected)
                self.assertTrue(self.socket.closed)

    def test_error_disconnects_and_never_replays_failed_frame(self):
        self.connect()
        self.socket.fail_type = "InjectParameterDataRequest"
        with self.assertRaises(VTSHostError):
            self.host.send_frame("plan", playback_epoch="p", frame="x", audible_cursor_s=0, sampled_ms=100000)
        self.assertFalse(self.host.connected)
        self.assertTrue(self.socket.closed)

    def test_close_and_fresh_reconnect(self):
        self.connect()
        self.host.close()
        self.assertFalse(self.host.connected)
        self.assertTrue(self.socket.closed)
        self.socket = FakeSocket()
        self.connect()
        self.assertTrue(self.host.connected)

    def test_registration_rejects_mismatched_parameter_response(self):
        self.socket.bad_param = True
        self.connect(register=False)
        with self.assertRaises(VTSHostError):
            self.host.register_parameters()
        self.assertFalse(self.host.connected)
        self.assertTrue(self.socket.closed)

    def test_serialized_concurrent_registration(self):
        self.connect(register=False)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.host.register_parameters(), range(24)))
        self.assertEqual(len([p for p in self.socket.sent if p["messageType"] == "ParameterCreationRequest"]), 14)


if __name__ == "__main__":
    unittest.main()
