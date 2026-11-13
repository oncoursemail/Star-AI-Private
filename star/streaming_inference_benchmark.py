"""Measured streaming inference probes for STAR's local/STAR Server models.

The probe uses a fixed, content-free prompt and an already-running OpenAI-compatible
endpoint. It records first non-empty content, completion time, and usage metadata
when the server supplies it. It never records generated text or sends project data.
"""
from __future__ import annotations

import asyncio
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
    """Summarize measured stream timings without inventing token counts."""
    if not samples or wall_ms <= 0 or not 1 <= parallel <= 4:
        raise ValueError("No valid streaming measurements")
    succeeded = [sample for sample in samples if sample.ok]
    first_content = [
        float(sample.first_content_ms)
        for sample in succeeded
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
    return {
        "requests": len(samples),
        "successful": len(succeeded),
        "failed": len(samples) - len(succeeded),
        "parallel_limit": parallel,
        "wall_ms": wall_ms,
        "first_content_p50_ms": round(median(first_content), 2) if first_content else None,
        "first_content_p95_ms": _nearest_rank(first_content, 0.95),
        "total_p50_ms": round(median(total), 2) if total else None,
        "total_p95_ms": _nearest_rank(total, 0.95),
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
            "token timestamp. Per-token timing is reported only when exact completion-token usage "
            "is supplied by the endpoint. Measurements are not a quality or speedup claim."
        ),
    }


async def benchmark_local_model_streaming(
    endpoint: str,
    model: str,
    *,
    requests: int = 4,
    parallel: int = 1,
    client: Any | None = None,
    server: bool = False,
) -> dict[str, Any]:
    """Measure real streamed requests to a validated local or STAR Server endpoint."""
    if server:
        config = Settings(provider="star_server", server_endpoint=endpoint, model=model)
    else:
        config = Settings(endpoint=endpoint, model=model)
    config.validate()
    if not model.strip() or not 1 <= requests <= 12 or not 1 <= parallel <= 4:
        raise ValueError("Streaming benchmark requires a model, 1..12 requests and 1..4 slots")

    own = client is None
    if own:
        from .providers import open_client

        client = open_client(config, request_timeout=None if server else 90.0)

    semaphore = asyncio.Semaphore(parallel)

    async def one() -> StreamingProbe:
        async with semaphore:
            started = monotonic()
            stream: Any | None = None
            first_content_ms: int | None = None
            output_tokens: int | None = None
            try:
                stream = await client.chat.completions.create(
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
                async for chunk in stream:
                    choices = getattr(chunk, "choices", None)
                    if choices:
                        delta = getattr(choices[0], "delta", None)
                        content = getattr(delta, "content", None)
                        if isinstance(content, str) and content and first_content_ms is None:
                            first_content_ms = max(0, int((monotonic() - started) * 1000))
                    usage = getattr(chunk, "usage", None)
                    count = getattr(usage, "completion_tokens", None) if usage is not None else None
                    if type(count) is int and count >= 0:
                        output_tokens = count

                elapsed = max(0, int((monotonic() - started) * 1000))
                if first_content_ms is None:
                    raise RuntimeError("Streaming response contained no text")
                return StreamingProbe(first_content_ms, elapsed, output_tokens, True)
            except Exception:
                elapsed = max(0, int((monotonic() - started) * 1000))
                return StreamingProbe(None, elapsed, None, False)
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
        if own:
            await client.close()
