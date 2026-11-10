"""Offline tests for the mixed-workload streaming inference benchmark."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from star.inference_workload_benchmark import (
    StreamingProbe,
    WORKLOADS,
    benchmark_local_streaming,
    summarize_streaming_probes,
)


def _chunk(text=None, tokens=None):
    choices = [] if text is None else [
        SimpleNamespace(delta=SimpleNamespace(content=text))
    ]
    usage = None if tokens is None else SimpleNamespace(completion_tokens=tokens)
    return SimpleNamespace(choices=choices, usage=usage)


class FakeStream:
    def __init__(self, owner, *, usage=True, empty=False):
        self.owner = owner
        self.usage = usage
        self.empty = empty

    async def __aiter__(self):
        self.owner.active += 1
        self.owner.peak = max(self.owner.peak, self.owner.active)
        try:
            if not self.empty:
                yield _chunk("ready")
                await asyncio.sleep(0.003)
                yield _chunk(" now")
                if self.usage:
                    yield _chunk(tokens=2)
        finally:
            self.owner.active -= 1

    async def aclose(self):
        return None


class FakeCompletions:
    def __init__(self, *, usage=True, empty=False):
        self.active = 0
        self.peak = 0
        self.calls = []
        self.usage = usage
        self.empty = empty

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self, usage=self.usage, empty=self.empty)


def test_mixed_workload_benchmark_measures_streaming_and_bounds_concurrency():
    async def run():
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        report = await benchmark_local_streaming(
            "http://127.0.0.1:8080/v1", "qwen", requests=8, parallel=2, client=client
        )
        assert report["verdict"] == "measured"
        assert len(completions.calls) == 9  # one warm-up, eight measured requests
        assert completions.peak == 2
        assert report["overall"]["successful"] == 8
        assert report["overall"]["failed"] == 0
        assert report["overall"]["output_tokens"] == 16
        assert report["overall"]["client_output_tokens_per_second_after_first_content"] is not None
        assert report["overall"]["first_content_p95_ms"] is not None
        assert report["overall"]["inter_chunk_gap_p95_ms"] >= 0
        assert set(report["by_category"]) == {item.category for item in WORKLOADS}
        assert report["workload_order"] == [item.category for item in WORKLOADS]
        assert all(call["stream"] is True for call in completions.calls)
        assert all(call["stream_options"] == {"include_usage": True} for call in completions.calls)
        assert all([message["role"] for message in call["messages"]] == ["system", "user"]
                   for call in completions.calls)
        # Generated text is counted, never retained in the aggregate report.
        assert "ready" not in json.dumps(report)

    asyncio.run(run())


def test_missing_usage_never_invents_token_throughput():
    async def run():
        completions = FakeCompletions(usage=False)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        report = await benchmark_local_streaming(
            "http://127.0.0.1:8080/v1", "qwen", requests=2, parallel=1, client=client
        )
        assert report["overall"]["output_tokens"] is None
        assert report["overall"]["client_output_tokens_per_second_after_first_content"] is None
        assert report["overall"]["usage_complete"] is False
        assert report["overall"]["output_chars_per_second"] > 0

    asyncio.run(run())


def test_failed_warmup_stops_before_measured_requests():
    async def run():
        completions = FakeCompletions(empty=True)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with pytest.raises(RuntimeError, match="warm-up failed"):
            await benchmark_local_streaming(
                "http://127.0.0.1:8080/v1", "qwen", client=client
            )
        assert len(completions.calls) == 1

    asyncio.run(run())


def test_external_endpoints_and_unbounded_parallelism_are_rejected():
    async def run(endpoint, parallel=1):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        return await benchmark_local_streaming(endpoint, "qwen", parallel=parallel, client=client)

    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(run("https://api.example.com/v1"))
    with pytest.raises(ValueError, match="parallel"):
        asyncio.run(run("http://127.0.0.1:8080/v1", parallel=3))
    with pytest.raises(ValueError, match="parallel"):
        asyncio.run(run("http://127.0.0.1:8080/v1", parallel=True))


def test_summary_rejects_empty_or_invalid_clock_evidence():
    probe = StreamingProbe("short_chat", 10.0, 2.0, (1.0,), 4, 2, True)
    with pytest.raises(ValueError):
        summarize_streaming_probes([], wall_ms=10, parallel=1, warmup_ms=1, workload_order=[])
    with pytest.raises(ValueError):
        summarize_streaming_probes([probe], wall_ms=0, parallel=1, warmup_ms=1, workload_order=["chat"])
    report = summarize_streaming_probes(
        [probe], wall_ms=10, parallel=1, warmup_ms=1, workload_order=["chat"]
    )
    assert report["overall"]["successful"] == 1
    assert report["overall"]["output_tokens"] == 2
    assert report["overall"]["first_content_p50_ms"] == 2.0
