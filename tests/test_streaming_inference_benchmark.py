"""Offline tests for STAR's bounded streaming inference benchmark."""
import asyncio
from types import SimpleNamespace

import pytest

from star.streaming_inference_benchmark import (
    StreamingProbe,
    benchmark_local_model_streaming,
    summarize_streaming_probes,
)


def test_streaming_summary_keeps_first_content_and_exact_usage_separate():
    result = summarize_streaming_probes(
        [
            StreamingProbe(100, 500, 8, True, 2, (20,)),
            StreamingProbe(200, 700, 10, True, 3, (30, 40)),
            StreamingProbe(None, 300, None, False, failure_kind="timeout"),
        ],
        wall_ms=800,
        parallel=2,
    )
    assert result["successful"] == 2
    assert result["failed"] == 1
    assert result["failure_kinds"] == {"timeout": 1}
    assert result["first_content_p50_ms"] == 150
    assert result["first_content_p95_ms"] == 200
    assert result["total_p50_ms"] == 600
    assert result["output_tokens"] == 18
    assert result["aggregate_output_tokens_per_second"] == 22.5
    assert result["approx_time_per_output_token_p50_ms"] is not None
    assert result["content_chunks_p50"] == 2.5
    assert result["inter_chunk_gap_p95_ms"] == 40
    assert "not a guaranteed server-side token timestamp" in result["note"]
    assert "transport chunks, not individual tokens" in result["note"]


def test_missing_usage_never_fabricates_token_or_tpot_metrics():
    result = summarize_streaming_probes(
        [StreamingProbe(50, 300, None, True, 2, (12,))],
        wall_ms=300,
        parallel=1,
    )
    assert result["output_tokens"] is None
    assert result["aggregate_output_tokens_per_second"] is None
    assert result["approx_time_per_output_token_p50_ms"] is None


def test_streaming_benchmark_uses_bounded_concurrency_and_closes_streams():
    class FakeStream:
        def __init__(self, owner):
            self.owner = owner
            self.closed = False

        def __aiter__(self):
            async def generate():
                await asyncio.sleep(0.005)
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="A "))],
                    usage=None,
                )
                await asyncio.sleep(0.005)
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="square."))],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(completion_tokens=7),
                )
            return generate()

        async def aclose(self):
            if not self.closed:
                self.closed = True
                self.owner.active -= 1
                self.owner.closed += 1

    class FakeCompletions:
        def __init__(self):
            self.active = 0
            self.peak = 0
            self.closed = 0
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            self.active += 1
            self.peak = max(self.peak, self.active)
            return FakeStream(self)

    async def run():
        fake = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        result = await benchmark_local_model_streaming(
            "http://127.0.0.1:8080/v1",
            "star-fast",
            requests=4,
            parallel=2,
            client=client,
        )
        assert result["successful"] == 4
        assert fake.peak == 2
        assert fake.closed == 4
        assert fake.active == 0
        assert result["output_tokens"] == 28
        assert all(call["stream"] is True for call in fake.calls)
        assert all(call["stream_options"] == {"include_usage": True} for call in fake.calls)

    asyncio.run(run())


def test_first_content_timeout_is_bounded_and_stream_is_closed():
    class SlowStream:
        def __init__(self):
            self.closed = False

        def __aiter__(self):
            async def generate():
                await asyncio.sleep(0.2)
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="late"))],
                    usage=None,
                )
            return generate()

        async def aclose(self):
            self.closed = True

    class FakeCompletions:
        def __init__(self):
            self.stream = SlowStream()

        async def create(self, **_kwargs):
            return self.stream

    async def run():
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = await benchmark_local_model_streaming(
            "http://127.0.0.1:8080/v1",
            "star-fast",
            requests=1,
            client=client,
            first_content_timeout_seconds=0.05,
            total_timeout_seconds=0.2,
        )
        assert result["failed"] == 1
        assert result["failure_kinds"] == {"timeout": 1}
        assert completions.stream.closed is True

    asyncio.run(run())


def test_total_deadline_and_empty_stream_are_reported_without_exception_text():
    class SlowTailStream:
        def __init__(self):
            self.closed = False

        def __aiter__(self):
            async def generate():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))],
                    usage=None,
                )
                await asyncio.sleep(0.2)
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="late"))],
                    usage=None,
                )
            return generate()

        async def aclose(self):
            self.closed = True

    class FakeCompletions:
        def __init__(self, stream):
            self.stream = stream

        async def create(self, **_kwargs):
            return self.stream

    async def run_timeout():
        stream = SlowTailStream()
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(stream)))
        result = await benchmark_local_model_streaming(
            "http://127.0.0.1:8080/v1", "star-fast", requests=1,
            client=client, first_content_timeout_seconds=0.05,
            total_timeout_seconds=0.1,
        )
        assert result["failure_kinds"] == {"timeout": 1}
        assert result["first_content_p50_ms"] == 0
        assert stream.closed is True

    asyncio.run(run_timeout())


def test_empty_stream_is_a_failed_probe_and_external_hosts_are_rejected():
    class EmptyStream:
        def __aiter__(self):
            async def generate():
                if False:
                    yield None
            return generate()

        async def aclose(self):
            return None

    class FakeCompletions:
        async def create(self, **_kwargs):
            return EmptyStream()

    async def run_empty():
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        result = await benchmark_local_model_streaming(
            "http://127.0.0.1:8080/v1",
            "star-fast",
            client=client,
        )
        assert result["successful"] == 0
        assert result["failed"] == 4
        assert result["failure_kinds"] == {"empty": 4}

    asyncio.run(run_empty())

    with pytest.raises(ValueError):
        asyncio.run(
            benchmark_local_model_streaming(
                "https://provider.example.com/v1",
                "star-fast",
                client=SimpleNamespace(chat=SimpleNamespace(completions=None)),
            )
        )
    with pytest.raises(ValueError):
        asyncio.run(
            benchmark_local_model_streaming(
                "http://127.0.0.1:8080/v1",
                "star-fast",
                parallel=8,
                client=SimpleNamespace(chat=SimpleNamespace(completions=None)),
            )
        )


def test_deadline_validation_rejects_boolean_infinity_and_inverted_bounds():
    async def run():
        client = SimpleNamespace(chat=SimpleNamespace(completions=None))
        with pytest.raises(ValueError):
            await benchmark_local_model_streaming(
                "http://127.0.0.1:8080/v1", "star-fast", client=client,
                first_content_timeout_seconds=True,
            )
        with pytest.raises(ValueError):
            await benchmark_local_model_streaming(
                "http://127.0.0.1:8080/v1", "star-fast", client=client,
                first_content_timeout_seconds=float("inf"),
            )
        with pytest.raises(ValueError):
            await benchmark_local_model_streaming(
                "http://127.0.0.1:8080/v1", "star-fast", client=client,
                first_content_timeout_seconds=1, total_timeout_seconds=0.5,
            )

    asyncio.run(run())
