"""Offline tests for the real HTTP SSE probe and the conservative paired gate."""
import copy
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import tempfile
from pathlib import Path
from threading import Thread
import unittest

from star.inference_ab import (
    PROMPTS, SUITE_SHA256, compare, file_digest, loopback_endpoint,
    probe, run_arm,
)


def _rows(arm, *, latency=100.0, chars=80, repeats=2):
    return {
        "schema": 1, "arm": arm, "model": "local-gguf", "suite_sha256": SUITE_SHA256,
        "model_sha256": "a" * 64, "binary_sha256": "b" * 64,
        "host_sha256": "h" * 64, "repeats": repeats, "warmup_ok": True,
        "samples": [
            {"task_id": task_id, "repeat": repeat, "ok": True,
             "total_ms": latency, "ttft_ms": latency / 4, "characters": chars,
             "output_sha256": "c" * 64, "completion_tokens": 20}
            for repeat in range(repeats) for task_id, _ in PROMPTS
        ],
    }


class LocalHandler(BaseHTTPRequestHandler):
    mode = "ok"
    messages = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        type(self).messages.append(request)
        self.send_response(200 if self.mode not in {"http_error"} else 503)
        self.send_header("Content-Type", "text/event-stream" if self.mode != "wrong_type" else "application/json")
        self.end_headers()
        if self.mode in {"http_error", "wrong_type"}:
            return
        data = [
            {"choices": [{"delta": {"content": "Hello "}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "world!"}, "finish_reason": "stop"}]},
            {"usage": {"completion_tokens": 3}, "choices": []},
        ]
        if self.mode == "invalid_json":
            self.wfile.write(b"data: not-json\n\n")
            return
        for event in data:
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
        if self.mode != "no_done":
            self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


class InferenceABTests(unittest.TestCase):
    def test_endpoint_accepts_only_numeric_loopback_address_and_v1(self):
        for endpoint in [
            "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1/",
        ]:
            host, port = loopback_endpoint(endpoint)
            self.assertIn(host, {"127.0.0.1", "::1"})
            self.assertEqual(port, 8080)
        for invalid in [
            "https://127.0.0.1:8080/v1", "http://localhost:8080/v1",
            "http://8.8.8.8:8080/v1", "http://192.168.1.2:8080/v1",
            "http://evil.com@127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1?x=1",
            "http://127.0.0.1:8080/v2", "http://127.0.0.1:99999/v1",
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                loopback_endpoint(invalid)

    def test_real_http_sse_and_errors_remain_offline(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1"
            LocalHandler.messages = []
            LocalHandler.mode = "ok"
            result = probe(endpoint, "local", "private? synthetic prompt only")
            self.assertTrue(result["ok"])
            self.assertEqual(result["characters"], 12)
            self.assertEqual(result["completion_tokens"], 3)
            self.assertEqual(result["output_sha256"], sha256(b"Hello world!").hexdigest())
            self.assertGreaterEqual(result["total_ms"], result["ttft_ms"])
            self.assertEqual(LocalHandler.messages[0]["stream"], True)
            for mode in ("http_error", "invalid_json", "no_done", "wrong_type"):
                with self.subTest(mode=mode):
                    LocalHandler.mode = mode
                    failed = probe(endpoint, "local", "hello")
                    self.assertFalse(failed["ok"])
                    self.assertNotIn("hello", json.dumps(failed))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_run_arm_has_bounded_deterministic_tasks_and_private_hashes(self):
        calls = []
        def fake(endpoint, model, prompt):
            calls.append((endpoint, model, prompt))
            return {"ok": True, "ttft_ms": 20.0, "total_ms": 120.0,
                    "characters": 40, "completion_tokens": None, "output_sha256": "e" * 64}
        with tempfile.TemporaryDirectory() as root:
            artifact = Path(root) / "model.gguf"
            binary = Path(root) / "llama-server.exe"
            artifact.write_bytes(b"hello model")
            binary.write_bytes(b"hello executable")
            result = run_arm("baseline", "http://127.0.0.1:5555/v1", "model",
                             repeats=2, model_file=str(artifact), binary_file=str(binary),
                             probe_fn=fake)
            self.assertEqual(len(calls), 1 + len(PROMPTS) * 2)
            self.assertEqual(len(result["samples"]), 16)
            self.assertEqual(result["model_sha256"], file_digest(str(artifact)))
            self.assertEqual(result["binary_sha256"], file_digest(str(binary)))
            self.assertNotIn(str(root), json.dumps(result))
            self.assertNotIn("hello model", json.dumps(result))
            self.assertEqual(result["suite_sha256"], SUITE_SHA256)
        for bad_repeats in (0, 5, 1.1, True):
            with self.subTest(repeats=bad_repeats), self.assertRaises(ValueError):
                run_arm("baseline", "http://127.0.0.1/v1", "x", repeats=bad_repeats,
                        probe_fn=fake)

    def test_speed_signal_and_never_auto_enable(self):
        base, fast = _rows("baseline"), _rows("candidate", latency=85.0)
        result = compare(base, fast)
        self.assertEqual(result["performance_signal"], "promising_only")
        self.assertFalse(result["automatic_enablement"])
        self.assertEqual(result["paired"], 16)
        self.assertEqual(result["relative_median_total"], 0.85)
        self.assertEqual(result["identical_model_and_server_binary_hashes"], True)
        slow = compare(base, _rows("candidate", latency=130.0))
        self.assertEqual(slow["performance_signal"], "regression")
        same = compare(base, _rows("candidate", latency=100.0))
        self.assertEqual(same["performance_signal"], "inconclusive")
        short = compare(base, _rows("candidate", latency=60.0, chars=30))
        self.assertEqual(short["performance_signal"], "not_comparable_output_lengths")

    def test_rejects_false_or_incomplete_evidence(self):
        base, cand = _rows("baseline"), _rows("candidate", latency=80)
        for key, value in [
            ("model", "different"), ("model_sha256", "z" * 64),
            ("binary_sha256", "x" * 64), ("host_sha256", "new-host"),
            ("suite_sha256", "bad"),
            ("repeats", 3), ("arm", "baseline"),
        ]:
            bad = copy.deepcopy(cand)
            bad[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                compare(base, bad)
        bad = copy.deepcopy(cand)
        bad["samples"] = bad["samples"][:-1]
        with self.assertRaises(ValueError):
            compare(base, bad)
        bad = copy.deepcopy(cand)
        bad["samples"][1] = bad["samples"][0]
        with self.assertRaises(ValueError):
            compare(base, bad)
        bad = copy.deepcopy(cand)
        bad["samples"][0]["ttft_ms"] = math.nan
        with self.assertRaises(ValueError):
            compare(base, bad)
        bad = copy.deepcopy(cand)
        bad["samples"][0]["ok"] = False
        self.assertEqual(compare(base, bad)["performance_signal"], "invalid_failures")
        bad = copy.deepcopy(cand)
        bad["warmup_ok"] = False
        self.assertEqual(compare(base, bad)["performance_signal"], "invalid_warmup")

    def test_one_repeat_insufficient_to_promote(self):
        a = _rows("baseline", repeats=1)
        b = _rows("candidate", latency=60.0, repeats=1)
        result = compare(a, b)
        self.assertEqual(result["performance_signal"], "inconclusive")
        self.assertFalse(result["automatic_enablement"])


if __name__ == "__main__":
    unittest.main()
