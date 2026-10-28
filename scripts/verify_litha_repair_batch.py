"""Synthetic checks for the actual Litha repair dispatcher, validators and loopback HTTP service.

No provider, credentials, GPU or submitted-code execution. `--benchmark` times deterministic sleeping callbacks.
"""
from __future__ import annotations

import argparse
import http.client
import json
import statistics
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.verify import core, service  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402
from mesh.verify.batch import MAX_JOBS, MAX_PROMPT_BYTES, RepairBatch  # noqa: E402
sys.path.remove(str(ROOT / "server"))


def answer(*names):
    return "\n".join(f"```python\n{name} = (\n```\n" for name in names)


def original(messages):
    return core.extract_blocks(messages[-1]["content"])[0]["code"]


def repair(messages):
    return original(messages).replace("= (", "= 1")


class BatchChecks(unittest.TestCase):
    def setUp(self):
        self.verifier = core.Verifier(ApiIndex({}))

    def test_default_keeps_serial_calls_and_report(self):
        seen = []

        def call(messages):
            seen.append(original(messages))
            return repair(messages)

        result = self.verifier.fix(answer("a", "a"), call)
        self.assertTrue(result["ok"])
        self.assertEqual(len(seen), 2)
        self.assertNotIn("repair_batch", result)

    def test_parallel_completion_order_does_not_reorder_code(self):
        second_done = threading.Event()
        caller_threads, check_threads = [], []
        check = self.verifier.check_block

        def check_on_owner(*args, **kwargs):
            check_threads.append(threading.get_ident())
            return check(*args, **kwargs)

        self.verifier.check_block = check_on_owner

        def call(messages):
            caller_threads.append(threading.get_ident())
            if original(messages).startswith("a"):
                self.assertTrue(second_done.wait(2))
            else:
                second_done.set()
            return repair(messages)

        result = self.verifier.fix(answer("a", "b"), call, batch=RepairBatch(2))
        self.assertTrue(result["ok"])
        self.assertEqual([b["code"] for b in core.extract_blocks(result["answer"])], ["a = 1\n", "b = 1\n"])
        self.assertEqual([row["block"] for row in result["changes"]], [0, 1])
        self.assertEqual(set(check_threads), {threading.get_ident()})
        self.assertNotIn(threading.get_ident(), caller_threads)
        self.assertEqual(result["repair_batch"]["model_calls"], 2)

    def test_exact_prompt_coalescing_still_checks_each_block(self):
        calls = []

        def call(messages):
            calls.append(messages)
            return repair(messages)

        result = self.verifier.fix(answer("a", "a", "a"), call, batch=RepairBatch(2, coalesce=True))
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result["changes"]), 3)
        self.assertEqual(result["repair_batch"]["coalesced_blocks"], 2)

    def test_different_messages_never_share_results(self):
        calls = []
        messages = [[{"role": "user", "content": text}] for text in ("a", "b", "a")]
        out, stats = RepairBatch(2, coalesce=True).run(messages, lambda m: calls.append(m) or m[0]["content"])
        self.assertEqual([r.reply for r in out], ["a", "b", "a"])
        self.assertEqual((len(calls), stats["model_calls"], stats["coalesced_blocks"]), (2, 2, 1))

    def test_later_round_is_a_fresh_attempt(self):
        calls = []

        def call(messages):
            calls.append(messages)
            return "a = )\n" if len(calls) == 1 else repair(messages)

        result = self.verifier.fix(answer("a", "a"), call, batch=RepairBatch(2, coalesce=True))
        self.assertTrue(result["ok"])
        self.assertEqual((result["rounds"], len(calls)), (2, 2))
        self.assertEqual(sum("rejected" in change for change in result["changes"]), 2)

    def test_no_cross_request_or_cross_caller_memory(self):
        dispatcher = RepairBatch(2, coalesce=True)
        calls = []
        for value in (1, 2):
            result = self.verifier.fix(answer("a", "a"),
                                       lambda m, value=value: calls.append(value) or f"a = {value}\n",
                                       batch=dispatcher)
            self.assertTrue(result["ok"])
            self.assertIn(f"a = {value}", result["answer"])
        self.assertEqual(calls, [1, 2])

    def test_exception_isolated_and_capacity_released(self):
        dispatcher = RepairBatch(2)

        def call(messages):
            if original(messages).startswith("a"):
                raise OSError("synthetic failure")
            return repair(messages)

        result = self.verifier.fix(answer("a", "b"), call, batch=dispatcher)
        self.assertFalse(result["ok"])
        self.assertIn("a = (", result["answer"])
        self.assertIn("b = 1", result["answer"])
        self.assertEqual(len([c for c in result["changes"] if "error" in c]), 2)
        self.assertTrue(self.verifier.fix(answer("c"), repair, batch=dispatcher)["ok"])

    def test_refused_source_does_not_call_model(self):
        source = "```python\n" + "a" * (65 * 1024) + "\n```\n"
        result = self.verifier.fix(source, lambda _: self.fail("model called"), batch=RepairBatch(2))
        self.assertFalse(result["ok"])
        self.assertEqual(result["repair_batch"]["model_calls"], 0)

    def test_placeholders_are_preserved(self):
        source = "```python\nX_POS = 1\na = (\n```\n"
        result = self.verifier.fix(source, lambda _: "a = 1\n", batch=RepairBatch(2))
        self.assertFalse(result["ok"])
        self.assertEqual(result["answer"], source)
        self.assertTrue(all("placeholder" in row["rejected"] for row in result["changes"]))

    def test_shared_candidate_cannot_bypass_local_pack_semantics(self):
        # Identical prompts, but one JSON fence has a local pack filename. Each candidate must be checked there.
        source = 'pack.mcmeta:\n```json\n{"bad": }\n```\n\nordinary.json:\n```json\n{"bad": }\n```\n'
        result = self.verifier.fix(source, lambda _: "{}\n", batch=RepairBatch(2, coalesce=True))
        self.assertFalse(result["ok"])
        blocks = core.extract_blocks(result["answer"])
        self.assertEqual(blocks[0]["code"], '{"bad": }\n')
        self.assertEqual(blocks[1]["code"], '{}\n')
        self.assertEqual(result["repair_batch"]["model_calls"], 2)

    def test_invalid_config_fails_before_work(self):
        for workers in (0, 5, True, "2", 1.5):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                RepairBatch(workers)
        for wait in (-1, 6, True, "1", float("nan"), float("inf")):
            with self.subTest(wait=wait), self.assertRaises(ValueError):
                RepairBatch(wait_s=wait)
        with self.assertRaises(ValueError):
            RepairBatch(coalesce="yes")

    def test_job_and_message_budgets(self):
        messages = [[{"role": "user", "content": "x"}] for _ in range(MAX_JOBS + 1)]
        out, stats = RepairBatch(2).run(messages, lambda _: "ok")
        self.assertEqual(stats["model_calls"], MAX_JOBS)
        self.assertEqual(stats["budget_skipped"], 1)
        self.assertTrue(out[-1].error)
        out, stats = RepairBatch(2).run([[{"role": "user", "content": "x" * MAX_PROMPT_BYTES}]],
                                        lambda _: self.fail("overbudget called"))
        self.assertEqual(stats["model_calls"], 0)
        self.assertTrue(out[0].error)

    def test_callback_mutation_and_wrong_return_do_not_leak(self):
        messages = [[{"role": "user", "content": "a"}]]

        def mutate(value):
            value[0]["content"] = "mutated"
            return {"wrong": "type"}

        out, stats = RepairBatch(2).run(messages, mutate)
        self.assertEqual(messages[0][0]["content"], "a")
        self.assertIn("TypeError", out[0].error)
        self.assertEqual(stats["model_calls"], 1)

    def test_executor_failure_retains_source_in_report(self):
        for target in ("mesh.verify.batch.ThreadPoolExecutor", "mesh.verify.batch.ThreadPoolExecutor.submit"):
            with self.subTest(target=target), patch(target, side_effect=RuntimeError("synthetic executor failure")):
                source = answer("a", "b")
                result = self.verifier.fix(source, lambda _: self.fail("model called"), batch=RepairBatch(2))
                self.assertFalse(result["ok"])
                self.assertEqual(result["answer"], source)
                self.assertEqual(result["repair_batch"]["model_calls"], 0)
                self.assertEqual(result["repair_batch"]["dispatch_skipped"], 2)

    def test_http_requests_share_capacity_and_keep_auth(self):
        entered, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        active, peak, count = 0, 0, 0

        def caller(messages):
            nonlocal active, peak, count
            with lock:
                active += 1
                count += 1
                peak = max(peak, active)
                if active == 2:
                    entered.set()
            try:
                if not release.wait(4):
                    raise TimeoutError("test release not signaled")
                return repair(messages)
            finally:
                with lock:
                    active -= 1

        cfg = {**service.DEFAULTS, "repair_workers": 2, "repair_wait_s": 0.02}
        handler = service.make_handler(cfg, self.verifier, SimpleNamespace(check=lambda key: key == "synthetic"),
                                        lambda cfg, auth: caller)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(name, key="synthetic"):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request("POST", "/mesh/verify?fix=1", json.dumps({"answer": answer(name)}),
                                   {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            with ThreadPoolExecutor(max_workers=2) as clients:
                a, b = clients.submit(request, "a"), clients.submit(request, "b")
                try:
                    self.assertTrue(entered.wait(2))
                    status, busy = request("c")
                    self.assertEqual(status, 200)
                    self.assertFalse(busy["ok"])
                    self.assertEqual(busy["repair_batch"]["model_calls"], 0)
                    self.assertEqual(busy["repair_batch"]["capacity_skipped"], 1)
                    self.assertEqual(request("c", "wrong")[0], 401)
                finally:
                    release.set()
                self.assertTrue(a.result()[1]["ok"])
                self.assertTrue(b.result()[1]["ok"])
            self.assertEqual((peak, count, active), (2, 2, 0))
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)


def benchmark():
    verifier = core.Verifier(ApiIndex({}))
    source = answer("a", "b", "c", "a", "b", "c")
    results = []
    for label, batch in (("original_serial", None), ("coalesce_serial", RepairBatch(1, coalesce=True)),
                         ("coalesce_3_workers", RepairBatch(3, coalesce=True))):
        elapsed, call_counts = [], []
        for _ in range(5):
            calls = []

            def call(messages):
                calls.append(1)
                time.sleep(0.04)
                return repair(messages)

            start = time.perf_counter()
            result = verifier.fix(source, call, batch=batch)
            elapsed.append((time.perf_counter() - start) * 1000)
            call_counts.append(len(calls))
            assert result["ok"] and len(result["changes"]) == 6
        results.append({"mode": label, "median_ms": round(statistics.median(elapsed), 2),
                        "model_calls_each_run": call_counts})
    print(json.dumps({"synthetic_sleep_ms_per_call": 40, "runs_per_mode": 5,
                      "blocks": 6, "distinct_prompts": 3, "results": results}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true")
    args, rest = parser.parse_known_args()
    if args.benchmark:
        benchmark()
    else:
        unittest.main(argv=[sys.argv[0], *rest])
