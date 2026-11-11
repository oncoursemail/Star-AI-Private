"""On-device, measured local inference benchmarking (never fabricated metrics).

Run explicitly against an already-started loopback model, or with `server=True`
against the owner's STAR Server on the LAN. Benchmark requests contain no chats,
project data or tool calls; nothing leaves the owner's machines.
"""
from __future__ import annotations

import asyncio
import inspect
import math
from dataclasses import dataclass
from statistics import median
from time import monotonic
from typing import Any

from .desktop_core import Settings


_STREAM_FAILURE_CATEGORIES = frozenset({
    "empty_stream",
    "timeout",
    "rate_limited",
    "client_error",
    "server_error",
    "connection_error",
    "protocol_error",
    "request_error",
})


@dataclass(frozen=True)
class Probe:
    elapsed_ms: int
    output_tokens: int | None
    ok: bool


@dataclass(frozen=True)
class StreamingProbe:
    """One streaming request; chunk timing is not token-level ITL."""

    elapsed_ms: float
    first_content_ms: float | None
    inter_chunk_gaps_ms: tuple[float, ...]
    content_chunks: int
    ok: bool
    failure_category: str | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.elapsed_ms, bool) or
                not isinstance(self.elapsed_ms, (int, float)) or
                not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0):
            raise ValueError("elapsed_ms must be finite and nonnegative")
        if type(self.content_chunks) is not int or not 0 <= self.content_chunks <= 1_000_000:
            raise ValueError("content_chunks must be a bounded integer")
        if type(self.ok) is not bool:
            raise ValueError("ok must be a boolean")
        if (self.failure_category is not None and
                (type(self.failure_category) is not str or
                 self.failure_category not in _STREAM_FAILURE_CATEGORIES)):
            raise ValueError("failure_category must be a known category or None")
        if self.ok and self.failure_category is not None:
            raise ValueError("a successful stream cannot have a failure category")
        if type(self.inter_chunk_gaps_ms) is not tuple:
            raise ValueError("inter_chunk_gaps_ms must be a tuple")
        first_content_value: float | None = None
        if self.content_chunks == 0:
            if self.first_content_ms is not None or self.inter_chunk_gaps_ms:
                raise ValueError("an empty stream cannot have content timings")
        else:
            first = self.first_content_ms
            if (isinstance(first, bool) or not isinstance(first, (int, float)) or
                    not math.isfinite(first) or not 0 <= first <= self.elapsed_ms):
                raise ValueError("first_content_ms must be a valid request-relative timestamp")
            first_content_value = float(first)
            if len(self.inter_chunk_gaps_ms) != self.content_chunks - 1:
                raise ValueError("one inter-chunk gap is required between content chunks")
        for gap in self.inter_chunk_gaps_ms:
            if (isinstance(gap, bool) or not isinstance(gap, (int, float)) or
                    not math.isfinite(gap) or gap < 0):
                raise ValueError("inter-chunk gaps must be finite and nonnegative")
        if (first_content_value is not None and
                first_content_value + sum(self.inter_chunk_gaps_ms) > self.elapsed_ms + 1e-6):
            raise ValueError("content timestamps cannot extend beyond request completion")
        if self.ok and self.content_chunks == 0:
            raise ValueError("an empty stream cannot be successful")


def _classify_stream_failure(error: BaseException | None) -> str:
    """Return a bounded, content-free failure label; never persist exception text."""
    if error is None:
        return "empty_stream"
    name = type(error).__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in name:
        return "timeout"
    status_code = getattr(error, "status_code", None)
    if type(status_code) is int:
        if status_code == 429:
            return "rate_limited"
        if status_code in {408, 504}:
            return "timeout"
        if 400 <= status_code < 500:
            return "client_error"
        if 500 <= status_code < 600:
            return "server_error"
    if isinstance(error, (ConnectionError, OSError)) or any(
        token in name for token in ("connection", "connect", "network", "transport")
    ):
        return "connection_error"
    if any(token in name for token in ("json", "decode", "protocol", "validation")):
        return "protocol_error"
    return "request_error"


def _nearest_rank(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(proportion * len(ordered)) - 1)
    return round(ordered[index], 1)


def _validate_benchmark_request(
    endpoint: object, model: object, requests: object, parallel: object, server: object,
) -> None:
    """Reject ambiguous endpoint and workload values before constructing a client."""
    if type(endpoint) is not str or not endpoint.strip():
        raise ValueError("Benchmark endpoint must be a non-empty string")
    if type(model) is not str or not model.strip():
        raise ValueError("Benchmark model must be a non-empty string")
    if type(requests) is not int or not 1 <= requests <= 12:
        raise ValueError("Benchmark requests must be an integer from 1..12")
    if type(parallel) is not int or not 1 <= parallel <= 4:
        raise ValueError("Benchmark concurrency must be an integer from 1..4")
    if type(server) is not bool:
        raise ValueError("server must be a boolean")


def summarize_probes(samples: list[Probe], wall_ms: int, *, parallel: int) -> dict:
    if not samples or wall_ms <= 0 or not 1 <= parallel <= 4:
        raise ValueError("No valid measurements")
    succeeded = [x for x in samples if x.ok]
    durations = sorted(s.elapsed_ms for s in succeeded)
    # Partial usage metadata would undercount output and mislead comparisons.
    tokens = [x.output_tokens for x in succeeded] if all(
        x.output_tokens is not None for x in succeeded
    ) and succeeded else []
    p95 = durations[max(0, (len(durations) * 95 + 99) // 100 - 1)] if durations else None
    return {
        "requests": len(samples),
        "successful": len(succeeded),
        "failed": len(samples) - len(succeeded),
        "parallel_limit": parallel,
        "wall_ms": wall_ms,
        "median_request_ms": round(median(durations), 1) if durations else None,
        "p95_request_ms": p95,
        "requests_per_second": round(len(succeeded) * 1000 / wall_ms, 3),
        "output_tokens": sum(tokens) if tokens else None,
        "output_tokens_per_second": round(sum(tokens) * 1000 / wall_ms, 2) if tokens else None,
        "note": "Measured requests to the owner's own model only. No GPU speedup or model-quality claim is implied.",
    }


def summarize_stream_probes(
    samples: list[StreamingProbe], wall_ms: float, *, parallel: int,
) -> dict:
    """Summarize first-content and chunk cadence without pretending chunks are tokens."""
    if (not samples or isinstance(wall_ms, bool) or
            not isinstance(wall_ms, (int, float)) or
            not math.isfinite(wall_ms) or wall_ms <= 0 or
            type(parallel) is not int or not 1 <= parallel <= 4):
        raise ValueError("No valid streaming measurements")
    if len(samples) > 12 or any(type(sample) is not StreamingProbe for sample in samples):
        raise ValueError("Expected at most 12 validated streaming probes")
    succeeded = [sample for sample in samples if sample.ok]
    first = [float(sample.first_content_ms) for sample in succeeded
             if sample.first_content_ms is not None]
    second = [
        float(sample.first_content_ms) + float(sample.inter_chunk_gaps_ms[0])
        for sample in succeeded
        if sample.content_chunks >= 2 and sample.first_content_ms is not None
    ]
    latency = [float(sample.elapsed_ms) for sample in succeeded]
    gaps = [float(gap) for sample in succeeded for gap in sample.inter_chunk_gaps_ms]
    chunks = sum(sample.content_chunks for sample in succeeded)
    failure_categories: dict[str, int] = {}
    failed_with_partial_content = 0
    partial_content_chunks = 0
    for sample in samples:
        if sample.ok:
            continue
        category = sample.failure_category or "unspecified"
        failure_categories[category] = failure_categories.get(category, 0) + 1
        if sample.content_chunks:
            failed_with_partial_content += 1
            partial_content_chunks += sample.content_chunks
    return {
        "requests": len(samples),
        "successful": len(succeeded),
        "failed": len(samples) - len(succeeded),
        "parallel_limit": parallel,
        "wall_ms": round(float(wall_ms), 1),
        "first_content_p50_ms": _nearest_rank(first, 0.50),
        "first_content_p95_ms": _nearest_rank(first, 0.95),
        "time_to_second_content_p50_ms": _nearest_rank(second, 0.50),
        "time_to_second_content_p95_ms": _nearest_rank(second, 0.95),
        "request_latency_p50_ms": _nearest_rank(latency, 0.50),
        "request_latency_p95_ms": _nearest_rank(latency, 0.95),
        "inter_chunk_gap_p50_ms": _nearest_rank(gaps, 0.50),
        "inter_chunk_gap_p95_ms": _nearest_rank(gaps, 0.95),
        "content_chunks": chunks,
        "content_chunks_per_second": round(chunks * 1000 / wall_ms, 2),
        "requests_per_second": round(len(succeeded) * 1000 / wall_ms, 3),
        "failure_categories": dict(sorted(failure_categories.items())),
        "failed_requests_with_partial_content": failed_with_partial_content,
        "partial_content_chunks_discarded": partial_content_chunks,
        "note": (
            "Local-model streaming measurements only. Content chunks may contain multiple tokens; "
            "inter-chunk gap and time-to-second-content are not token-level ITL/TTST. Use AIPerf "
            "or token-aware server telemetry for token-level comparisons. No GPU speedup or "
            "quality gain is implied."
        ),
    }


async def benchmark_local_model(
    endpoint: str,
    model: str,
    *,
    requests: int = 4,
    parallel: int = 1,
    client: Any | None = None,
    server: bool = False,
) -> dict:
    """Measure real requests. `server=True` treats `endpoint` as the STAR Server address."""
    _validate_benchmark_request(endpoint, model, requests, parallel, server)
    if server:
        # Same private-IP validation and keyring key as normal STAR Server chat.
        config = Settings(provider="star_server", server_endpoint=endpoint, model=model)
    else:
        config = Settings(endpoint=endpoint, model=model)
    config.validate()
    own = client is None
    if client is None:
        from .providers import open_client
        active_client: Any = open_client(config, request_timeout=None if server else 90.0)
    else:
        active_client = client
    sem = asyncio.Semaphore(parallel)

    async def one() -> Probe:
        async with sem:
            began = monotonic()
            try:
                result = await active_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a local model benchmark. Reply briefly."},
                        {"role": "user", "content": "Describe a simple geometric square in one sentence."},
                    ],
                    max_tokens=96, temperature=0,
                )
                output = str(result.choices[0].message.content or "").strip()
                if not output:
                    raise RuntimeError("Empty model output")
                usage = getattr(result, "usage", None)
                count = getattr(usage, "completion_tokens", None) if usage else None
                if not isinstance(count, int) or count < 0:
                    count = None
                return Probe(int((monotonic()-began)*1000), count, True)
            except Exception:
                return Probe(int((monotonic()-began)*1000), None, False)

    started = monotonic()
    try:
        samples = await asyncio.gather(*(one() for _ in range(requests)))
        wall = max(1, int((monotonic() - started)*1000))
        return summarize_probes(samples, wall, parallel=parallel)
    finally:
        if own:
            await active_client.close()


async def benchmark_local_model_streaming(
    endpoint: str,
    model: str,
    *,
    requests: int = 4,
    parallel: int = 1,
    client=None,
    server: bool = False,
) -> dict:
    """Measure first-content and inter-chunk timing from an already-running local model."""
    _validate_benchmark_request(endpoint, model, requests, parallel, server)
    if server:
        config = Settings(provider="star_server", server_endpoint=endpoint, model=model)
    else:
        config = Settings(endpoint=endpoint, model=model)
    config.validate()
    own = client is None
    if client is None:
        from .providers import open_client
        active_client: Any = open_client(config, request_timeout=None if server else 90.0)
    else:
        active_client = client
    sem = asyncio.Semaphore(parallel)

    async def one() -> StreamingProbe:
        async with sem:
            began = monotonic()
            stream = None
            first_content: float | None = None
            previous_content: float | None = None
            gaps: list[float] = []
            content_chunks = 0
            ok = False
            failure: BaseException | None = None
            try:
                stream = await active_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a local model benchmark. Reply briefly."},
                        {"role": "user", "content": "Describe a simple geometric square in one sentence."},
                    ],
                    max_tokens=96, temperature=0, stream=True,
                )
                async for event in stream:
                    choices = getattr(event, "choices", None)
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    content = getattr(delta, "content", None)
                    if not isinstance(content, str) or not content.strip():
                        continue
                    now = monotonic()
                    relative = max(0.0, (now - began) * 1000)
                    if first_content is None:
                        first_content = relative
                    elif previous_content is not None:
                        gaps.append(max(0.0, (now - previous_content) * 1000))
                    previous_content = now
                    content_chunks += 1
                ok = content_chunks > 0
            except Exception as exc:
                failure = exc
                ok = False
            finally:
                closer = getattr(stream, "close", None)
                if not callable(closer):
                    closer = getattr(stream, "aclose", None)
                if callable(closer):
                    try:
                        result = closer()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        pass
            elapsed = max(0.0, (monotonic() - began) * 1000)
            failure_category = None if ok else _classify_stream_failure(failure)
            return StreamingProbe(
                elapsed, first_content, tuple(gaps), content_chunks, ok, failure_category,
            )

    started = monotonic()
    try:
        samples = await asyncio.gather(*(one() for _ in range(requests)))
        wall = max(1.0, (monotonic() - started) * 1000)
        return summarize_stream_probes(samples, wall, parallel=parallel)
    finally:
        if own:
            await active_client.close()
