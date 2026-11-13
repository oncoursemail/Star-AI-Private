"""Measured streaming inference probes for STAR's local/STAR Server models.

The probe uses a fixed, content-free prompt and an already-running OpenAI-compatible
endpoint. It records first non-empty content, completion time, and usage metadata
when the server supplies it. It never records generated text or sends project data.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from statistics import median
from time import monotonic
from typing import Any

from .desktop_core import Settings


@dataclass(frozen=True)
class StreamingProbe:
    first_content_ms: int | None
    total_ms: int
    output_tokens: int | None
    ok: bool
    content_chunks: int = 0
    inter_chunk_gaps_ms: tuple[int, ...] = ()
    failure_kind: str | None = None


def _nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, (len(ordered) * int(quantile * 100) + 99) // 100)
    return round(ordered[rank - 1], 2)


def summarize_streaming_probes(
    samples: list[StreamingProbe],
    wall_ms: int,
    *,
    parallel: int,
) -> dict[str, Any]:
    """Summarize stream timings without inventing token counts or error details."""
    if not samples or wall_ms <= 0 or not 1 <= parallel <= 4:
        raise ValueError("No valid streaming measurements")
    succeeded = [sample for sample in samples if sample.ok]
    # A stream that later fails can still have delivered its first content. Keep
    # that latency in the first-content distribution instead of hiding partials.
    first_content = [
        float(sample.first_content_ms)
        for sample in samples
        if sample.first_content_ms is not None
    ]
    total = [float(sample.total_ms) for sample in succeeded]
    tpot = [
        (sample.total_ms - sample.first_content_ms) / (sample.output_tokens - 1)
        for sample in succeeded
        if sample.first_content_ms is not None
        and sample.output_tokens is not None
        and sample.output_tokens > 1
        and sample.total_ms >= sample.first_content_ms
    ]
    token_counts = [
        sample.output_tokens
        for sample in succeeded
        if sample.output_tokens is not None
    ]
    all_token_counts_known = bool(succeeded) and len(token_counts) == len(succeeded)
    total_tokens = sum(token_counts) if all_token_counts_known else None
    chunk_counts = [float(sample.content_chunks) for sample in samples if sample.content_chunks]
    inter_chunk_gaps = [
        float(gap)
        for sample in samples
        for gap in sample.inter_chunk_gaps_ms
    ]
    failure_kinds: dict[str, int] = {}
    for sample in samples:
        if not sample.ok:
            kind = sample.failure_kind or "unknown"
            failure_kinds[kind] = failure_kinds.get(kind, 0) + 1
    return {
        "requests": len(samples),
        "successful": len(succeeded),
        "failed": len(samples) - len(succeeded),
        "failure_kinds": failure_kinds,
        "parallel_limit": parallel,
        "wall_ms": wall_ms,
        "first_content_p50_ms": round(median(first_content), 2) if first_content else None,
        "first_content_p95_ms": _nearest_rank(first_content, 0.95),
        "total_p50_ms": round(median(total), 2) if total else None,
        "total_p95_ms": _nearest_rank(total, 0.95),
        "content_chunks_p50": round(median(chunk_counts), 2) if chunk_counts else None,
        "inter_chunk_gap_p50_ms": round(median(inter_chunk_gaps), 2) if inter_chunk_gaps else None,
        "inter_chunk_gap_p95_ms": _nearest_rank(inter_chunk_gaps, 0.95),
        "approx_time_per_output_token_p50_ms": round(median(tpot), 3) if tpot else None,
        "approx_time_per_output_token_p95_ms": _nearest_rank(tpot, 0.95),
        "output_tokens": total_tokens,
        "aggregate_output_tokens_per_second": (
            round(total_tokens * 1000 / wall_ms, 3)
            if total_tokens is not None
            else None
        ),
        "requests_per_second": round(len(succeeded) * 1000 / wall_ms, 3),
        "note": (
            "First content is the first non-empty streamed text chunk, not a guaranteed server-side "
            "token timestamp. Inter-chunk gaps describe transport chunks, not individual tokens. "
            "Per-token timing is approximate and reported only when exact completion-token usage "
            "is supplied. Measurements are not a quality or speedup claim."
        ),
    }


def _valid_deadlines(first_content_timeout_seconds: float, total_timeout_seconds: float) -> bool:
    values = (first_content_timeout_seconds, total_timeout_seconds)
    return (
        all(type(value) in (int, float) and math.isfinite(value) for value in values)
        and 0.05 <= first_content_timeout_seconds <= 600
        and first_content_timeout_seconds <= total_timeout_seconds <= 900
    )


async def benchmark_local_model_streaming(
    endpoint: str,
    model: str,
    *,
    requests: int = 4,
    parallel: int = 1,
    client: Any | None = None,
    server: bool = False,
    first_content_timeout_seconds: float = 120.0,
    total_timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    """Measure streamed requests with hard first-content and total deadlines.

    Exception messages are deliberately not returned: HTTP client errors can contain
    endpoint details. Only a small failure category is included in the aggregate.
    """
    if server:
        config = Settings(provider="star_server", server_endpoint=endpoint, model=model)
    else:
        config = Settings(endpoint=endpoint, model=model)
    config.validate()
    if not isinstance(model, str) or not model.strip() or not 1 <= requests <= 12 or not 1 <= parallel <= 4:
        raise ValueError("Streaming benchmark requires a model, 1..12 requests and 1..4 slots")
    if not _valid_deadlines(first_content_timeout_seconds, total_timeout_seconds):
        raise ValueError("Streaming deadlines must be finite, first-content 0.05..600s, total >= first and <= 900s")

    if client is None:
        from .providers import open_client

        active_client = open_client(config, request_timeout=None if server else 90.0)
        close_client = True
    else:
        active_client = client
        close_client = False

    semaphore = asyncio.Semaphore(parallel)

    async def one() -> StreamingProbe:
        async with semaphore:
            started = monotonic()
            stream: Any | None = None
            first_content_ms: int | None = None
            output_tokens: int | None = None
            content_chunks = 0
            inter_chunk_gaps: list[int] = []
            last_content_at: float | None = None

            def consume(chunk: Any) -> None:
                nonlocal first_content_ms, output_tokens, content_chunks, last_content_at
                choices = getattr(chunk, "choices", None)
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    content = getattr(delta, "content", None)
                    if isinstance(content, str) and content:
                        now = monotonic()
                        if first_content_ms is None:
                            first_content_ms = max(0, int((now - started) * 1000))
                        if last_content_at is not None:
                            inter_chunk_gaps.append(max(0, int((now - last_content_at) * 1000)))
                        last_content_at = now
                        content_chunks += 1
                usage = getattr(chunk, "usage", None)
                count = getattr(usage, "completion_tokens", None) if usage is not None else None
                if type(count) is int and count >= 0:
                    output_tokens = count

            try:
                async with asyncio.timeout(total_timeout_seconds):
                    async with asyncio.timeout(first_content_timeout_seconds):
                        stream = await active_client.chat.completions.create(
                            model=model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a local model benchmark. Reply briefly.",
                                },
                                {
                                    "role": "user",
                                    "content": "Describe a simple geometric square in one sentence.",
                                },
                            ],
                            max_tokens=96,
                            temperature=0,
                            stream=True,
                            stream_options={"include_usage": True},
                        )
                        iterator = stream.__aiter__()
                        while first_content_ms is None:
                            consume(await anext(iterator))
                    async for chunk in iterator:
                        consume(chunk)
                elapsed = max(0, int((monotonic() - started) * 1000))
                return StreamingProbe(
                    first_content_ms, elapsed, output_tokens, True,
                    content_chunks, tuple(inter_chunk_gaps), None,
                )
            except TimeoutError:
                elapsed = max(0, int((monotonic() - started) * 1000))
                return StreamingProbe(
                    first_content_ms, elapsed, None, False, content_chunks,
                    tuple(inter_chunk_gaps), "timeout",
                )
            except StopAsyncIteration:
                elapsed = max(0, int((monotonic() - started) * 1000))
                return StreamingProbe(
                    None, elapsed, None, False, content_chunks,
                    tuple(inter_chunk_gaps), "empty",
                )
            except Exception as exc:
                elapsed = max(0, int((monotonic() - started) * 1000))
                transport_errors = {
                    "APIConnectionError", "APITimeoutError", "ConnectError",
                    "ReadError", "ReadTimeout", "WriteError", "WriteTimeout",
                    "RemoteProtocolError",
                }
                kind = "transport" if type(exc).__name__ in transport_errors else "request_error"
                return StreamingProbe(
                    first_content_ms, elapsed, None, False, content_chunks,
                    tuple(inter_chunk_gaps), kind,
                )
            finally:
                if stream is not None:
                    try:
                        await stream.aclose()
                    except Exception:
                        pass

    wall_started = monotonic()
    try:
        samples = await asyncio.gather(*(one() for _ in range(requests)))
        wall_ms = max(1, int((monotonic() - wall_started) * 1000))
        return summarize_streaming_probes(samples, wall_ms, parallel=parallel)
    finally:
        if close_client:
            await active_client.close()
