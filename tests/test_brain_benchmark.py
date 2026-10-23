"""Tests do not claim any real model benchmark was run."""
import pytest
from contextlib import contextmanager
from threading import Barrier, Lock
from star.brain_benchmark import local_endpoint, parse_sse_data, summarize, run_samples


def test_benchmark_allows_only_loopback_api():
    assert local_endpoint("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/v1"
    assert local_endpoint("http://localhost:1234/v1/") == "http://localhost:1234/v1"
    for bad in ("https://api.example.com/v1", "http://127.0.0.1:8080/admin",
                "http://127.0.0.1:8080/v1?token=x", "http://localhost:80/v1",
                "http://localhost:8080/v1#frag", "http://user:pw@127.0.0.1:8080/v1",
                "http://0.0.0.0:8080/v1", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            local_endpoint(bad)


def test_sse_parser_discards_incomplete_or_nondata_frames():
    assert parse_sse_data("data: [DONE]") is None
    assert parse_sse_data("not data") is None
    assert parse_sse_data("data: {broken}") is None
    assert parse_sse_data('data: {"choices": [{"delta": {"content": "hi"}}]}')["choices"][0]["delta"]["content"] == "hi"


def test_aggregator_reports_measured_not_invented_numbers():
    samples = [
        {"ttft_ms": 100, "total_ms": 800, "output_chars_per_s": 50},
        {"ttft_ms": 80, "total_ms": 1000, "output_chars_per_s": 40},
        {"ttft_ms": 90, "total_ms": 850, "output_chars_per_s": 60},
    ]
    summary = summarize(samples)
    assert summary["runs"] == 3
    assert summary["median_ttft_ms"] == 90
    assert summary["p95_total_ms"] == 1000
    assert summary["median_output_chars_per_s"] == 50
    with pytest.raises(ValueError):
        summarize([])


def test_concurrent_model_benchmark_measures_real_parallel_requests_and_cache_counters():
    # A fake HTTP stream exercises concurrent scheduling without starting a model.
    barrier = Barrier(2, timeout=2)
    lock = Lock()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Hello"}}]}'
            yield ('data: {"choices":[],"timings":'
                   '{"prompt_n":35,"cache_n":100,"prompt_ms":800.5,"predicted_n":2}}')
            yield 'data: [DONE]'

    class FakeClient:
        def __init__(self):
            self.active = 0
            self.peak = 0
            self.calls = []

        @contextmanager
        def stream(self, method, url, *, json, headers):
            assert method == "POST" and url == "http://127.0.0.1:8080/v1/chat/completions"
            assert json["stream"] is True and json["max_tokens"] == 32
            with lock:
                self.active += 1
                self.peak = max(self.active, self.peak)
                self.calls.append(json["model"])
            try:
                barrier.wait()
                yield FakeResponse()
            finally:
                with lock:
                    self.active -= 1

    client = FakeClient()
    measurements, wall_ms = run_samples(client, "http://127.0.0.1:8080/v1", "local-model",
                                         "Test prompt", runs=2, parallel=2, max_tokens=32)
    assert client.peak == 2
    assert client.active == 0
    assert client.calls == ["local-model", "local-model"]
    assert all(row["actual_completion_tokens"] == 2 for row in measurements)
    assert all(row["prompt_tokens_cached"] == 100 for row in measurements)
    assert all(row["prompt_tokens_evaluated"] == 35 for row in measurements)
    summary = summarize(measurements, wall_ms=wall_ms, parallel=2)
    assert summary["median_prompt_tokens_cached"] == 100
    assert summary["median_prompt_tokens_evaluated"] == 35
    assert summary["median_prompt_eval_ms"] == 800.5
    assert summary["aggregate_output_tokens_per_second"] > 0
    assert summary["parallel"] == 2 and summary["requests_per_second"] > 0
    assert "queueing" in summary["note"]


def test_concurrent_benchmark_rejects_unbounded_work_without_network():
    for runs, parallel in ((0, 1), (11, 1), (2, 0), (2, 3), (10, 5), (2, True)):
        with pytest.raises(ValueError):
            run_samples(object(), "http://127.0.0.1:8080/v1", "local-model",
                        "Test", runs=runs, parallel=parallel)
    with pytest.raises(ValueError):
        summarize([{"ttft_ms": 1}], wall_ms=0)
    with pytest.raises(ValueError):
        summarize([{"ttft_ms": 1}], parallel=5)


def test_cache_metrics_are_not_invented_without_server_timings():
    rows = [{"ttft_ms": 90, "total_ms": 150, "output_chars_per_s": 20,
             "actual_completion_tokens": None}]
    result = summarize(rows, wall_ms=150)
    assert "median_prompt_tokens_cached" not in result
    assert "median_prompt_eval_ms" not in result
    assert "aggregate_output_tokens_per_second" not in result


def _report(ttfts, *, scale=1.0, model="star-fast", parallel=1):
    rows = [{"ttft_ms": t * scale, "total_ms": (t + 500) * scale, "output_chars_per_s": 40} for t in ttfts]
    return {"model": model, "scenario": "chat", "target": "local", "endpoint": "http://127.0.0.1:8080/v1",
            "measurements": rows, "summary": {"runs": len(rows), "parallel": parallel}}


def test_compare_reports_reaches_a_verdict_with_any_sample_count():
    from star.brain_benchmark import compare_reports
    base = _report([400, 420, 380, 450, 410, 395])          # 6 runs, not the old fixed 10
    faster = compare_reports(base, _report([400, 420, 380, 450, 410, 395], scale=0.7))
    assert faster["decision"] == "PROMOTE" and faster["pairs"] == 6
    assert faster["metrics"]["ttft_ms"]["wins"] == 6 and faster["metrics"]["ttft_ms"]["p_better"] < 0.05
    assert faster["metrics"]["ttft_ms"]["mean_saved_ms_interval"][0] > 0
    slower = compare_reports(base, _report([400, 420, 380, 450, 410, 395], scale=1.3))
    assert slower["decision"] == "REJECT" and slower["metrics"]["total_ms"]["losses"] == 6
    few = compare_reports(_report([400, 420, 380]), _report([300, 320, 280]))
    assert few["decision"] == "INCONCLUSIVE"
    assert any("cannot reach significance" in note for note in few["notes"])
    mixed = compare_reports(base, _report([390, 430, 370, 460, 400, 405]))
    assert mixed["decision"] == "INCONCLUSIVE"


def test_compare_refuses_unlike_reports():
    from star.brain_benchmark import compare_reports
    with pytest.raises(ValueError, match="model"):
        compare_reports(_report([1, 2, 3]), _report([1, 2, 3], model="star-deep"))
    with pytest.raises(ValueError, match="parallel"):
        compare_reports(_report([1, 2, 3]), _report([1, 2, 3], parallel=2))
    broken = _report([1, 2, 3])
    broken["measurements"][0]["ttft_ms"] = float("nan")
    with pytest.raises(ValueError, match="ttft_ms"):
        compare_reports(_report([1, 2, 3]), broken)


def test_compare_cli_reads_saved_reports_without_any_request(tmp_path, monkeypatch, capsys):
    import json
    import star.brain_benchmark as bench
    monkeypatch.setattr(bench, "benchmark_target", lambda *a, **k: pytest.fail("compare must not connect"))
    before, after, other = tmp_path / "before.json", tmp_path / "after.json", tmp_path / "other.json"
    before.write_text(json.dumps(_report([400, 420, 380, 450, 410, 395, 405])), encoding="utf-8")
    after.write_text(json.dumps(_report([400, 420, 380, 450, 410, 395, 405], scale=0.8)), encoding="utf-8")
    other.write_text(json.dumps(_report([1, 2, 3], model="star-deep")), encoding="utf-8")
    assert bench.main(["--compare", str(before), str(after)]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "PROMOTE"
    assert bench.main(["--compare", str(after), str(before)]) == 1
    capsys.readouterr()
    assert bench.main(["--compare", str(before), str(other)]) == 2
    assert json.loads(capsys.readouterr().out)["decision"] == "UNUSABLE"
    with pytest.raises(SystemExit):
        bench.main([])                                       # measuring still needs --model
