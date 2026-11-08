"""Deterministic raw-WebSocket contract tests; no OBS, GPU or network required."""
from __future__ import annotations

from collections import deque
import base64
import hashlib
import json
import unittest

from star.obs_nonbroadcast_rehearsal_host import (
    ObsNonbroadcastRehearsalHost,
    ObsOfflineHostError,
)
from star.stream_rehearsal_recorder import StreamRehearsalRecorder


class FakeObsSocket:
    """Protocol simulator: responses are correlated to actual sent request IDs."""

    def __init__(self, *, authenticated: bool = True, stream_active: bool = False,
                 record_active: bool = False):
        hello = {
            "op": 0, "d": {
                "obsWebSocketVersion": "5.5.0", "rpcVersion": 1,
            },
        }
        if authenticated:
            hello["d"]["authentication"] = {"challenge": "challenge", "salt": "salt"}
        self.incoming = deque([hello])
        self.sent = []
        self.closed = False
        self.sample_index = 0
        self.stream_active = stream_active
        self.record_active = record_active
        self.inject_event: str | None = None
        self.inject_many_events = 0
        self.wrong_request_id = False
        self.wrong_opcode = False
        self.disconnect_on_request = False
        self.extra_unrelated_event = False

    def send(self, raw: str):
        if self.closed:
            raise OSError("closed socket")
        data = json.loads(raw)
        self.sent.append(data)
        if data["op"] == 1:
            self.incoming.append({
                "op": 2, "d": {"negotiatedRpcVersion": 1},
            })
            return
        if data["op"] != 6:
            raise AssertionError("OBS host attempted an unsafe request")
        request = data["d"]["requestType"]
        if request not in ("GetStats", "GetStreamStatus", "GetRecordStatus"):
            raise AssertionError("non-read-only OBS method")
        if self.disconnect_on_request:
            return
        if request == "GetStats":
            self.sample_index += 1
            if self.inject_event is not None:
                self.incoming.append({
                    "op": 5, "d": {"eventType": self.inject_event,
                                    "eventData": {"path": "PRIVATE_VIDEO.mkv"}},
                })
                self.inject_event = None
            for _ in range(self.inject_many_events):
                self.incoming.append({"op": 5, "d": {"eventType": "SceneChanged"}})
            if self.extra_unrelated_event:
                self.incoming.append({"op": 5, "d": {"eventType": "SceneChanged"}})
        bodies = {
            "GetStats": {
                "renderTotalFrames": 100 * self.sample_index,
                "renderSkippedFrames": self.sample_index,
                "outputTotalFrames": 0,
                "outputSkippedFrames": 0,
            },
            "GetStreamStatus": {"outputActive": self.stream_active},
            "GetRecordStatus": {"outputActive": self.record_active},
        }
        self.incoming.append({
            "op": 6 if self.wrong_opcode else 7,
            "d": {
                "requestType": request,
                "requestId": "wrong" if self.wrong_request_id else data["d"]["requestId"],
                "requestStatus": {"result": True, "code": 100},
                "responseData": bodies[request],
            },
        })

    def recv(self):
        if not self.incoming:
            raise TimeoutError("read timeout")
        return json.dumps(self.incoming.popleft())

    def close(self):
        self.closed = True


class TestObsNonbroadcastRehearsalHost(unittest.TestCase):
    def setUp(self):
        self.fake = FakeObsSocket()
        self.proc = [(64, 123.0)]
        self.calls = []
        self.tick = [1.0]

    def clock(self):
        self.tick[0] += 0.01
        return self.tick[0]

    def factory(self, **kwargs):
        self.calls.append(kwargs)
        return self.fake

    def host(self):
        return ObsNonbroadcastRehearsalHost(
            socket_factory=self.factory,
            process_identity=lambda: self.proc[0],
            monotonic_clock=self.clock,
        )

    def connected(self):
        host = self.host()
        host.connect(password="SECRET_PASSWORD", owner_approved=True)
        return host

    def test_owner_consent_before_any_socket(self):
        host = self.host()
        with self.assertRaises(PermissionError):
            host.connect(password="SECRET_PASSWORD")
        with self.assertRaises(ValueError):
            host.connect(password="", owner_approved=True)
        self.assertEqual(self.calls, [])

    def test_explicit_authenticated_local_socket_no_unsafe_requests(self):
        host = self.connected()
        self.assertEqual(self.calls, [{
            "url": "ws://127.0.0.1:4455", "timeout": 3,
            "enable_multithread": True,
        }])
        self.assertEqual(self.fake.sent[0]["op"], 1)
        self.assertEqual(self.fake.sent[0]["d"]["eventSubscriptions"], 65)
        secret = base64.b64encode(hashlib.sha256(
            b"SECRET_PASSWORDsalt",
        ).digest()).decode("ascii")
        expected_auth = base64.b64encode(hashlib.sha256(
            (secret + "challenge").encode("ascii"),
        ).digest()).decode("ascii")
        self.assertEqual(self.fake.sent[0]["d"]["authentication"], expected_auth)
        host.sample()
        report = host.finish()
        self.assertTrue(report["sealed"])
        self.assertTrue(report["continuity_intact_to_last_fence"])
        self.assertFalse(report["authorized_to_broadcast"])
        self.assertTrue(self.fake.closed)
        self.assertEqual(
            [m["d"]["requestType"] for m in self.fake.sent[1:]],
            ["GetStats", "GetStreamStatus", "GetRecordStatus"] * 2,
        )
        with self.assertRaises(ObsOfflineHostError):
            host.sample()

    def test_no_private_values_in_report_or_exception(self):
        host = self.connected()
        report = host.sample()
        self.assertEqual(report["sample_count"], 1)
        self.assertIsNone(report["render_skipped_fraction"])
        host.finish()
        public = json.dumps(host.report())
        for text in ("SECRET_PASSWORD", "challenge", "salt", "127.0.0.1",
                     "PRIVATE_VIDEO", "star_obs_", "requestId", "path"):
            self.assertNotIn(text, public)

    def test_correlated_real_response_ids(self):
        host = self.connected()
        host.sample()
        ids = [m["d"]["requestId"] for m in self.fake.sent[1:]]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(len(token) < 80 for token in ids))

    def test_unrelated_events_are_discarded_without_data_retention(self):
        self.fake.extra_unrelated_event = True
        host = self.connected()
        host.sample()
        self.assertTrue(host.finish()["continuity_intact_to_last_fence"])
        self.assertNotIn("PRIVATE_VIDEO", json.dumps(host.report()))

    def test_output_state_change_between_samples_revokes_host(self):
        host = self.connected()
        host.sample()
        self.fake.inject_event = "StreamStateChanged"
        with self.assertRaisesRegex(ObsOfflineHostError, "continuity"):
            host.sample()
        self.assertTrue(host.report()["host_revoked"])
        self.assertFalse(host.report()["continuity_intact_to_last_fence"])
        self.assertTrue(self.fake.closed)
        with self.assertRaises(ObsOfflineHostError):
            host.sample()

    def test_record_event_even_when_now_inactive_is_disqualifying(self):
        host = self.connected()
        host.sample()
        self.fake.inject_event = "RecordStateChanged"
        with self.assertRaises(ObsOfflineHostError):
            host.finish()
        self.assertTrue(host.report()["host_revoked"])

    def test_recording_or_streaming_live_is_never_accepted(self):
        for kind in ("stream", "record"):
            with self.subTest(kind=kind):
                self.setUp()
                setattr(self.fake, kind + "_active", True)
                host = self.connected()
                with self.assertRaises(ObsOfflineHostError):
                    host.sample()
                self.assertEqual(host.report()["sample_count"], 0)
                self.assertTrue(host.report()["host_revoked"])
                self.assertTrue(self.fake.closed)

    def test_wrong_response_id_or_opcode_revokes_session(self):
        for field in ("wrong_request_id", "wrong_opcode"):
            with self.subTest(field=field):
                self.setUp()
                setattr(self.fake, field, True)
                host = self.connected()
                with self.assertRaises(ObsOfflineHostError):
                    host.sample()
                self.assertTrue(host.report()["host_revoked"])

    def test_socket_error_and_missing_response_are_sanitized(self):
        self.fake.disconnect_on_request = True
        host = self.connected()
        with self.assertRaises(ObsOfflineHostError) as ctx:
            host.sample()
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertTrue(self.fake.closed)

    def test_flood_of_non_output_events_fails_closed(self):
        self.fake.inject_many_events = 129
        host = self.connected()
        with self.assertRaises(ObsOfflineHostError):
            host.sample()
        self.assertTrue(host.report()["host_revoked"])

    def test_process_restart_and_invalid_clock_revoke_session(self):
        host = self.connected()
        host.sample()
        self.proc[0] = (64, 999.0)
        with self.assertRaises(ObsOfflineHostError):
            host.sample()
        self.assertTrue(host.report()["host_revoked"])

        self.setUp()
        host = self.connected()
        self.tick[0] = float("nan")
        with self.assertRaises(ObsOfflineHostError):
            host.sample()
        self.assertTrue(host.report()["host_revoked"])

    def test_invalid_auth_protocol_and_missing_auth_never_connect(self):
        self.fake = FakeObsSocket(authenticated=False)
        host = self.host()
        with self.assertRaises(ObsOfflineHostError):
            host.connect(password="SECRET_PASSWORD", owner_approved=True)
        self.assertTrue(self.fake.closed)
        with self.assertRaises(ObsOfflineHostError):
            host.connect(password="SECRET_PASSWORD", owner_approved=True)

    def test_sealed_host_not_reusable_even_if_socket_healthy(self):
        host = self.connected()
        host.sample()
        host.sample()
        # Closing an unfinished observation is NOT a successful final fence.
        self.assertFalse(host.report()["continuity_intact_to_last_fence"])
        host.close()
        self.assertFalse(host.connected)
        self.assertTrue(host.report()["sealed"])
        self.assertFalse(host.report()["final_fence_completed"])
        self.assertFalse(host.report()["continuity_intact_to_last_fence"])
        with self.assertRaises(ObsOfflineHostError):
            host.sample()
        with self.assertRaises(ObsOfflineHostError):
            host.connect(password="SECRET_PASSWORD", owner_approved=True)

    def test_recorded_obs_samples_require_true_host_clock(self):
        host = self.connected()
        recorder = StreamRehearsalRecorder(
            episode_id="host_test", owner_approved=True,
        )
        recorder.record("scene_observed", at_ms=900, host_verified=True, scene_sequence=1)
        host.sample(recorder=recorder)
        host.finish(recorder=recorder)
        recorder.end(at_ms=1600, host_verified=True)
        report = recorder.report()
        self.assertEqual(report["obs_samples"], 2)
        self.assertEqual(report["obs_skipped_fraction"], 0.01)

    def test_downstream_failure_revokes_host_without_partial_sample(self):
        host = self.connected()
        recorder = StreamRehearsalRecorder(
            episode_id="host_test", owner_approved=True,
        )
        recorder.record("scene_observed", at_ms=9000, host_verified=True, scene_sequence=1)
        with self.assertRaises(ObsOfflineHostError):
            host.sample(recorder=recorder)
        self.assertEqual(host.report()["sample_count"], 0)
        self.assertTrue(host.report()["host_revoked"])

    def test_invalid_concurrent_sample_no_reentrance(self):
        host = self.connected()
        self.assertTrue(host._mutex.acquire(blocking=False))
        try:
            with self.assertRaises(ObsOfflineHostError):
                host.sample()
        finally:
            host._mutex.release()
        self.assertFalse(host.report()["host_revoked"])
        self.assertEqual(host.report()["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
