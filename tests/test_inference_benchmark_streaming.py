"""Streaming inference measurements: synthetic clients only, never hardware claims."""
import asyncio
from types import SimpleNamespace

import pytest

from star.inference_benchmark import (
    StreamingProbe,
    benchmark_local_model_streaming,
    summarize_stream_probes,
)


def probe(elapsed=100.0, first=20.0, gaps=(15.0, 25.0), chunks=3, ok=True):
    return StreamingProbe(elapsed, first, gaps, chunks, ok)


def test_stream_summary_reports_first_content_and_chunk_cadence_separately():
    report = summarize_stream_probes(
        [
            probe(elapsed=100, first=20, gaps=(10, 30), chunks=3),
            probe(elapsed=200, first=50, gaps=(20,), chunks=2),
            StreamingProbe(90, None, (), 0, False),
        ],
        wall_ms=300,
        parallel=2,
    )
    assert report["requests"] == 3
    assert report["successful"] == 2
    assert report["failed"] == 1
    assert report["first_content_p50_ms"] == 20
    assert report["first_content_p95_ms"] == 50
    assert report["request_latency_p95_ms"] == 200
    assert report["inter_chunk_gap_p50_ms"] == 20
    assert report["inter_chunk_gap_p95_ms"] == 30
    assert report["content_chunks"] == 5
    assert "token-level ITL" in report["note"]


def test_stream_probe_rejects_inconsistent_or_nonfinite_measurements():
    with pytest.raises(ValueError):
        StreamingProbe(10, float("nan"), (), 1, True)
    with pytest.raises(ValueError):
        StreamingProbe(10, 11, (), 1, True)
    with pytest.raises(ValueError):
        StreamingProbe(10, 1, (), 2, True)
    with pytest.raises(ValueError):
        StreamingProbe(10, None, (), 0, True)
    with pytest.raises(ValueError):
        StreamingProbe(10, 1, (float("inf"),), 2, True)
    with pytest.raises(ValueError):
        StreamingProbe(True, 1, (), 1, True)


def test_stream_summary_rejects_unbounded_or_invalid_inputs():
    with pytest.raises(ValueError):
        summarize_stream_probes([], 100, parallel=1)
    with pytest.raises(ValueError):
        summarize_stream_probes([probe()], float("nan"), parallel=1)
    with pytest.raises(ValueError):
        summarize_stream_probes([probe()], 100, parallel=True)
    with pytest.raises(ValueError):
        summarize_stream_probes([probe()] * 13, 100, parallel=1)


class _FakeCompletions:
    def __init__(self, *, empty=False):
        self.empty = empty
        self.active = 0
        self.peak = 0
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.peak = max(self.peak, self.active)

        async def events():
            try:
                await asyncio.sleep(0.005)
                if not self.empty:
                    yield SimpleNamespace(choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="A square"))
                    ])
                    await asyncio.sleep(0.005)
                    yield SimpleNamespace(choices=[
                        SimpleNamespace(delta=SimpleNamespace(content=" has four sides"))
                    ])
                # Usage/finish chunks with no content must not count as speech.
                yield SimpleNamespace(choices=[])
            finally:
                self.active -= 1

        return events()


def _client(*, empty=False):
    completions = _FakeCompletions(empty=empty)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    ), completions


def test_streaming_benchmark_calls_local_model_and_bounds_concurrency():
    async def run():
        client, fake = _client()
        report = await benchmark_local_model_streaming(
            "http://127.0.0.1:8080/v1", "local-model",
            requests=4, parallel=2, client=client,
        )
        assert report["successful"] == 4
        assert report["failed"] == 0
        assert fake.peak == 2
        assert report["content_chunks"] == 8
        assert report["first_content_p50_ms"] is not None
        assert report["inter_chunk_gap_p50_ms"] is not None
        assert all(call["stream"] is True for call in fake.calls)
        assert all(call["max_tokens"] == 96 for call in fake.calls)
        assert "content" not in report

    asyncio.run(run())


def test_empty_streams_are_failures_not_zero_latency_successes():
    async def run():
        client, fake = _client(empty=True)
        report = await benchmark_local_model_streaming(
            "http://127.0.0.1:8080/v1", "local-model",
            requests=2, parallel=1, client=client,
        )
        assert report["successful"] == 0
        assert report["failed"] == 2
        assert report["first_content_p50_ms"] is None
        assert fake.peak == 1

    asyncio.run(run())


def test_streaming_benchmark_rejects_remote_hosts_and_unbounded_load():
    async def run(endpoint, *, parallel=1, requests=1):
        client, _ = _client()
        return await benchmark_local_model_streaming(
            endpoint, "local-model", requests=requests,
            parallel=parallel, client=client,
        )

    with pytest.raises(ValueError):
        asyncio.run(run("https://provider.example.com/v1"))
    with pytest.raises(ValueError):
        asyncio.run(run("http://127.0.0.1:8080/v1", parallel=5))
    with pytest.raises(ValueError):
        asyncio.run(run("http://127.0.0.1:8080/v1", requests=13))
