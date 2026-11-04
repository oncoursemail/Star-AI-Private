"""Offline adversarial tests; never opens a real OBS connection."""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import unittest

from star.stream_obs_local_readonly_probe import (
    LocalObsProbeReport, _authentication, _packet, main, observe_local_obs,
)


class FakeObs:
    def __init__(self, *, stream_active=False, record_active=False,
                 authenticated=True, mismatch=False, wrong_op=False, rpc=1,
                 record_paused=False):
        self.stream_active = stream_active
        self.record_active = record_active
        self.record_paused = record_paused
        self.authenticated = authenticated
        self.mismatch = mismatch
        self.wrong_op = wrong_op
        self.rpc = rpc
        self.closed = False
        self.requests: list[dict] = []
        self.hello = {"op": 0, "d": {"rpcVersion": rpc}}
        if authenticated:
            self.hello["d"]["authentication"] = {"salt": "salty", "challenge": "challenge"}
        self.pending: list[str] = [json.dumps(self.hello)]
        self.stats_reads = 0

    def send(self, payload: str):
        m = json.loads(payload)
        self.requests.append(m)
        if m["op"] == 1:
            self.pending.append(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": self.rpc}}))
        elif m["op"] == 6:
            kind = m["d"]["requestType"]
            if kind == "GetStats":
                self.stats_reads += 1
                body = {"renderSkippedFrames": self.stats_reads,
                        "renderTotalFrames": 100 + 60 * self.stats_reads,
                        "outputSkippedFrames": 0, "outputTotalFrames": 0}
            elif kind == "GetStreamStatus":
                body = {"outputActive": self.stream_active}
            elif kind == "GetRecordStatus":
                body = {"outputActive": self.record_active, "outputPaused": self.record_paused}
            else:
                raise AssertionError("unapproved OBS request")
            reply = {"op": 7, "d": {
                "requestType": kind,
                "requestId": "forged" if self.mismatch else m["d"]["requestId"],
                "requestStatus": {"result": True, "code": 100},
                "responseData": body,
            }}
            if self.wrong_op:
                reply["op"] = 5
            self.pending.append(json.dumps(reply))
        else:
            raise AssertionError("writes must be Identify or read-only requests")

    def recv(self):
        return self.pending.pop(0)

    def close(self):
        self.closed = True


class TestLocalObsProbe(unittest.TestCase):
    def setUp(self):
        self.sock = FakeObs()
        self.ticks = iter(i * 0.05 for i in range(1000))
        self.ids = iter(f"opaque{i:016d}" for i in range(100))

    def observe(self, **kwargs):
        return observe_local_obs(
            owner_approved=True, password="private-not-logged",
            connect=lambda port, timeout: self.sock,
            clock=lambda: next(self.ticks),
            sleep=lambda seconds: None,
            token=lambda size: next(self.ids),
            **kwargs,
        )

    def test_off_by_default_even_with_password(self):
        calls = []
        with self.assertRaises(PermissionError):
            observe_local_obs(password="secret", connect=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_refuse_without_secret_without_socket(self):
        calls = []
        result = observe_local_obs(owner_approved=True, connect=lambda *a: calls.append(a))
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(calls, [])

    def test_auth_and_only_three_allowed_request_types(self):
        report = self.observe(samples=3)
        self.assertEqual(report.status, "candidate")
        self.assertEqual(report.samples, 3)
        self.assertTrue(report.nonbroadcast_verified_only_at_sample_times)
        self.assertFalse(report.recording_verified)
        self.assertFalse(report.authorizes_broadcast)
        self.assertFalse(report.authorizes_recording)
        self.assertTrue(self.sock.closed)
        sent = self.sock.requests
        self.assertEqual([p["op"] for p in sent], [1] + [6] * 9)
        self.assertEqual([p["d"]["requestType"] for p in sent[1:]],
                         ["GetStats", "GetStreamStatus", "GetRecordStatus"] * 3)
        self.assertEqual(sent[0]["d"]["eventSubscriptions"], 0)
        self.assertEqual(sent[0]["d"]["rpcVersion"], 1)
        sent_wire = json.dumps(sent)
        self.assertNotIn("private-not-logged", sent_wire)
        self.assertNotIn("opaque", report.to_json())
        self.assertNotIn("private-not-logged", report.to_json())
        self.assertAlmostEqual(report.render_skipped_fraction or 0, 1 / 60, places=5)

    def test_valid_authentication_formula(self):
        secret = base64.b64encode(sha256(b"private-not-loggedsalty").digest()).decode()
        expected = base64.b64encode(sha256((secret + "challenge").encode()).digest()).decode()
        self.assertEqual(_authentication("private-not-logged", "salty", "challenge"), expected)
        self.observe()
        self.assertEqual(self.sock.requests[0]["d"]["authentication"], expected)

    def test_block_active_stream_output(self):
        self.sock = FakeObs(stream_active=True)
        with self.assertRaises(PermissionError):
            self.observe()
        self.assertTrue(self.sock.closed)

    def test_block_active_record_output(self):
        self.sock = FakeObs(record_active=True)
        with self.assertRaises(PermissionError):
            self.observe()
        self.assertTrue(self.sock.closed)

    def test_private_recording_is_verified_without_starting_or_stopping_obs(self):
        self.sock = FakeObs(record_active=True)
        result = self.observe(samples=3, verify_private_recording=True)
        self.assertEqual(result.status, "candidate")
        self.assertTrue(result.recording_verified)
        self.assertTrue(result.nonbroadcast_verified_only_at_sample_times)
        self.assertFalse(result.authorizes_recording)
        self.assertFalse(result.authorizes_broadcast)
        self.assertEqual([request["d"]["requestType"] for request in self.sock.requests[1:]],
                         ["GetStats", "GetStreamStatus", "GetRecordStatus"] * 3)
        self.assertTrue(self.sock.closed)

    def test_private_recording_must_be_active_and_unpaused(self):
        for recorder in (FakeObs(record_active=False),
                         FakeObs(record_active=True, record_paused=True)):
            self.sock = recorder
            with self.subTest(active=recorder.record_active, paused=recorder.record_paused):
                with self.assertRaises(PermissionError):
                    self.observe(verify_private_recording=True)
                self.assertTrue(recorder.closed)

    def test_private_recording_never_allows_broadcast(self):
        self.sock = FakeObs(stream_active=True, record_active=True)
        with self.assertRaises(PermissionError):
            self.observe(verify_private_recording=True)
        self.assertTrue(self.sock.closed)

    def test_private_recording_input_must_be_exact_bool(self):
        calls = []
        with self.assertRaises(ValueError):
            observe_local_obs(
                owner_approved=True, password="secret", verify_private_recording=1,
                connect=lambda *args: calls.append(args),
            )
        self.assertEqual(calls, [])

    def test_block_unauthenticated_obs_even_if_local(self):
        self.sock = FakeObs(authenticated=False)
        with self.assertRaises(PermissionError):
            self.observe()
        self.assertTrue(self.sock.closed)
        self.assertEqual(self.sock.requests, [])

    def test_no_trust_in_supplied_response_request_ids(self):
        self.sock = FakeObs(mismatch=True)
        with self.assertRaises(ValueError):
            self.observe()
        self.assertTrue(self.sock.closed)

    def test_only_request_response_opcode(self):
        self.sock = FakeObs(wrong_op=True)
        with self.assertRaises(ValueError):
            self.observe()
        self.assertTrue(self.sock.closed)

    def test_rpc_protocol_version_checked(self):
        self.sock = FakeObs(rpc=0)
        with self.assertRaises(ValueError):
            self.observe()
        self.assertTrue(self.sock.closed)

    def test_invalid_session_inputs_fail_before_connect(self):
        invalid = [
            {"samples": 1}, {"samples": 10}, {"port": 80},
            {"port": 65536}, {"timeout_s": 9}, {"interval_s": 0.01},
        ]
        for config in invalid:
            calls = []
            with self.subTest(config=config), self.assertRaises(ValueError):
                observe_local_obs(owner_approved=True, password="x",
                    connect=lambda *a: calls.append(a), **config)
            self.assertEqual(calls, [])

    def test_packet_bounds_and_op_validation(self):
        with self.assertRaises(ValueError):
            _packet("a" * 65537, 7)
        with self.assertRaises(ValueError):
            _packet('{"op":7,"d":null}', 7)
        with self.assertRaises(ValueError):
            _packet('{"op":5,"d":{}}', 7)
        with self.assertRaises(ValueError):
            _packet('{"op":true,"d":{}}', 7)

    def test_report_is_minimal_and_non_authorizing(self):
        result = LocalObsProbeReport("candidate", "read_only", 3)
        report = json.loads(result.to_json())
        self.assertFalse(report["authorizes_recording"])
        self.assertFalse(report["authorizes_broadcast"])
        self.assertNotIn("host", report)

    def test_cli_without_explicit_flag_cannot_probe(self):
        from unittest.mock import patch
        from io import StringIO
        out = StringIO()
        with patch("sys.stdout", out), patch(
            "star.stream_obs_local_readonly_probe.observe_local_obs",
            side_effect=AssertionError("would contact OBS"),
        ):
            self.assertEqual(main([]), 2)
        self.assertIn("explicit_observe_flag_required", out.getvalue())

    def test_cli_explicit_private_recording_flag_is_only_a_read_probe(self):
        from unittest.mock import patch
        from io import StringIO
        out = StringIO()
        with patch("sys.stdout", out), patch(
            "star.stream_obs_local_readonly_probe.observe_local_obs",
            return_value=LocalObsProbeReport("candidate", "read_only", 3, recording_verified=True),
        ) as probe:
            self.assertEqual(main(["--observe", "--verify-private-recording"]), 0)
            self.assertIs(probe.call_args.kwargs["verify_private_recording"], True)
        self.assertIn('"recording_verified":true', out.getvalue())

    def test_cli_fails_closed_without_password(self):
        from unittest.mock import patch
        from io import StringIO
        out = StringIO()
        with patch.dict("os.environ", {}, clear=True), patch("sys.stdout", out):
            self.assertEqual(main(["--observe"]), 1)
        self.assertIn("local_obs_password_required", out.getvalue())


if __name__ == "__main__":
    unittest.main()
