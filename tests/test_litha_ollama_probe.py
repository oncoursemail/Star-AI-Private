import json

import pytest
from litha.ollama_probe import MAX_STREAM_BYTES, PROMPTS, SUITE_SHA256, main, probe, run, summarize


class Response:
    status = 200

    def __init__(self, lines):
        self.lines = lines

    def __iter__(self):
        return iter(self.lines)


class Connection:
    def __init__(self, host, port, timeout):
        assert host == "127.0.0.1" and port == 11434
        self.sent = None
        self.closed = False

    def request(self, method, path, body, headers):
        self.sent = json.loads(body)
        assert method == "POST" and path == "/api/generate"
        assert self.sent["options"]["num_ctx"] == 4096
        assert self.sent["stream"] is True

    def getresponse(self):
        return Response([
            json.dumps({"response": "Hi"}).encode() + b"\n",
            json.dumps({"response": " there"}).encode() + b"\n",
            json.dumps({"response": "", "done": True, "eval_count": 10,
                        "eval_duration": 200_000_000, "prompt_eval_count": 50,
                        "prompt_eval_cached_count": 10, "prompt_eval_duration": 100_000_000,
                        "total_duration": 500_000_000, "load_duration": 50_000_000}).encode() + b"\n",
        ])

    def close(self):
        self.closed = True


def test_probe_read_only_numeric_and_validated():
    connections = []
    def connection(*args, **kwargs):
        item = Connection(*args, **kwargs)
        connections.append(item)
        return item
    result = probe("qwen3.5:4b-q4_K_M", "Synthetic only", connection_factory=connection)
    assert result["ok"] is True
    assert result["decode_tps"] == 50.0
    assert result["uncached_prefill_tps"] == 400.0
    assert result["cached_prompt_tokens"] == 10
    assert "response" not in result and "Hi" not in str(result)
    assert connections[0].closed
    assert connections[0].sent["keep_alive"] == "5m"


@pytest.mark.parametrize("bad", ["http://evil.com/model", "x\nBAD", "", "⛔", "a" * 129])
def test_probe_model_tag_validation_prevents_bad_requests(bad):
    with pytest.raises(ValueError):
        probe(bad, "safe")


@pytest.mark.parametrize("args", [
    {"port": 80}, {"port": True}, {"num_ctx": 50000},
    {"num_predict": 0}, {"timeout": float("inf")},
    {"prompt": ""},
])
def test_validation_fails_before_any_network(args):
    defaults = {"model": "qwen3.5:4b", "prompt": "ok"}
    defaults.update(args)
    with pytest.raises(ValueError):
        probe(**defaults)


def test_incomplete_stream_returns_failure_without_content():
    class Broken(Connection):
        def getresponse(self):
            return Response([b'{"response":"hi"}\n'])
    r = probe("qwen3.5:4b", "Synthetic", connection_factory=Broken)
    assert r == {"ok": False, "error_type": "RuntimeError"}


def test_malformed_counter_fails_closed():
    class Broken(Connection):
        def getresponse(self):
            return Response([b'{"response":"hi"}\n',
                             b'{"done":true,"response":"","eval_count":1,"eval_duration":false}\n'])
    assert probe("qwen3.5:4b", "Synthetic", connection_factory=Broken)["ok"] is False


def test_stream_size_limit_is_enforced():
    class Huge(Connection):
        def getresponse(self):
            return Response([b'x' * (MAX_STREAM_BYTES + 1)])
    assert probe("qwen3.5:4b", "Synthetic", connection_factory=Huge)["ok"] is False


def sample(ok=True):
    return {"ok": ok, "ttft_ms": 21.0, "wall_ms": 88.0, "decode_tps": 60.0,
            "load_ms": 0.0, "ollama_total_ms": 86.0, "output_tokens": 14}


def test_summarize_must_not_hide_failures():
    invalid = summarize([sample(), sample(False)])
    assert invalid["valid"] is False
    assert invalid["failed"] == 1
    assert "INVALID" in invalid["decision"]


def test_summarize_reports_medians_and_p95_of_real_values():
    summary = summarize([sample(), sample(), sample()])
    assert summary["valid"] and summary["decode_tps"]["p50"] == 60
    assert summary["wall_ms"]["p95"] == 88


def test_run_warmup_and_distinct_cases():
    calls = []
    def fake(model, prompt, **kwargs):
        calls.append((prompt, kwargs["num_predict"]))
        return sample()
    data = run("lfm2.5:8b-a1b-q4_K_M", repeats=2, probe_fn=fake)
    assert len(calls) == 1 + len(PROMPTS) * 2
    assert calls[0][1] == 16
    assert len({s for s, _ in calls[1:]}) == len(PROMPTS) * 2
    assert data["suite_sha256"] == SUITE_SHA256 and data["summary"]["valid"]
    assert data["gpu_fit_verified"] is False


def test_warmup_failure_invalidates_whole_run():
    calls = []
    def fake(model, prompt, **kwargs):
        calls.append(prompt)
        return sample(False) if len(calls) == 1 else sample()
    result = run("qwen3.5:9b-q4_K_M", probe_fn=fake)
    assert not result["summary"]["valid"]
    assert "warmup" in result["summary"]["decision"]


def test_run_never_autodownloads_or_modifies_config(monkeypatch):
    import litha.ollama_probe as module
    monkeypatch.setattr(module, "probe", lambda *a, **k: sample())
    assert module.run("qwen3.5:4b", probe_fn=module.probe)["summary"]["valid"]
