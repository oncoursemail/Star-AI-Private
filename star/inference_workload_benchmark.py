"""Local-only, mixed-workload streaming inference benchmark for STAR.

Measures client-observed first-content latency and end-to-end streaming behavior
against an already-running loopback model. It deliberately stores no generated
text, prompts beyond this fixed synthetic catalog, credentials, or user data.
It is a measurement tool, not an automatic model selector or speedup claim.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import math
import inspect
from pathlib import Path
from statistics import median
from time import monotonic
from typing import Any, Iterable, Sequence

from .desktop_core import Settings
from .providers import open_client

MAX_REQUESTS = 32
MAX_PARALLEL = 2
_SYSTEM = (
    "You are STAR's local synthetic benchmark model. Follow the task directly. "
    "Do not use tools, browse, or request private information."
)


@dataclass(frozen=True)
class InferenceWorkload:
    category: str
    prompt: str


# Fixed, content-free prompts cover different shapes of work. They are latency
# probes only: the benchmark does not grade the answers for correctness.
WORKLOADS = (
    InferenceWorkload("short_chat", "In one sentence, describe a square."),
    InferenceWorkload("general_knowledge", "Explain photosynthesis in two concise sentences."),
    InferenceWorkload("reasoning", "A box has 4 red and 3 blue tokens. How many tokens are there? Explain briefly."),
    InferenceWorkload("luau", "Write a tiny --!strict Luau function that clamps a number between 0 and 1."),
    InferenceWorkload("debugging", "A loop uses for i = 1, #items - 1. State the likely off-by-one bug."),
    InferenceWorkload("game_strategy", "In a grid game, a hazard blocks the shortest route. Give a safe planning heuristic."),
    InferenceWorkload("stream_commentary", "Game event: the player narrowly avoids an obstacle and keeps moving. Give one brief reaction."),
    InferenceWorkload("summarization", "Summarize: inspect first; make one change; run the test; compare the result; keep or revert."),
)


@dataclass(frozen=True)
class StreamingProbe:
    category: str
    elapsed_ms: float
    first_content_ms: float | None
    inter_chunk_gaps_ms: tuple[float, ...]
    output_chars: int
    output_tokens: int | None
    ok: bool
    error_kind: str | None = None

    def __post_init__(self) -> None:
        allowed = {item.category for item in WORKLOADS} | {"warmup"}
        if type(self.category) is not str or self.category not in allowed:
            raise ValueError("unsupported workload category")
        if (type(self.elapsed_ms) not in (int, float) or not math.isfinite(self.elapsed_ms)
                or self.elapsed_ms <= 0):
            raise ValueError("elapsed_ms must be finite and positive")
        if self.first_content_ms is not None:
            if (type(self.first_content_ms) not in (int, float)
                    or not math.isfinite(self.first_content_ms)
                    or not 0 <= self.first_content_ms <= self.elapsed_ms):
                raise ValueError("first_content_ms must fall inside the measured request")
        if type(self.inter_chunk_gaps_ms) is not tuple or any(
            type(gap) not in (int, float) or not math.isfinite(gap) or gap < 0
            for gap in self.inter_chunk_gaps_ms
        ):
            raise ValueError("inter_chunk_gaps_ms must contain finite nonnegative numbers")
        if type(self.output_chars) is not int or self.output_chars < 0:
            raise ValueError("output_chars must be a nonnegative integer")
        if self.output_tokens is not None and (
            type(self.output_tokens) is not int or self.output_tokens < 0
        ):
            raise ValueError("output_tokens must be a nonnegative integer or absent")
        if type(self.ok) is not bool:
            raise ValueError("ok must be an explicit boolean")
        if self.error_kind is not None and (
            type(self.error_kind) is not str or not 1 <= len(self.error_kind) <= 64
        ):
            raise ValueError("error_kind must be a bounded class name")
        if self.ok and (self.output_chars < 1 or self.error_kind is not None):
            raise ValueError("successful probes require output and no error")
        if not self.ok and not self.error_kind:
            raise ValueError("failed probes require a bounded error kind")


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if fraction == 0.5:
        return round(float(median(ordered)), 2)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(float(ordered[index]), 2)


def _text_piece(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices and isinstance(chunk, dict):
        choices = chunk.get("choices")
    if not choices:
        return ""
    first = choices[0]
    delta = getattr(first, "delta", None)
    if delta is None and isinstance(first, dict):
        delta = first.get("delta")
    content = getattr(delta, "content", None) if delta is not None else None
    if content is None and isinstance(delta, dict):
        content = delta.get("content")
    return content if isinstance(content, str) else ""


def _usage_tokens(chunk: Any) -> int | None:
    usage = getattr(chunk, "usage", None)
    if usage is None and isinstance(chunk, dict):
        usage = chunk.get("usage")
    count = getattr(usage, "completion_tokens", None) if usage is not None else None
    if count is None and isinstance(usage, dict):
        count = usage.get("completion_tokens")
    return count if type(count) is int and count >= 0 else None


async def _close_stream(stream: Any) -> None:
    closer = getattr(stream, "aclose", None) or getattr(stream, "close", None)
    if not callable(closer):
        return
    try:
        result = closer()
        if inspect.isawaitable(result):
            await result
    except Exception:
        # A close failure is already reflected by the request/transport layer;
        # it must not mask the measured result or trigger an automatic retry.
        return


async def _one_streaming_request(
    client: Any,
    model: str,
    workload: InferenceWorkload,
    *,
    max_tokens: int,
) -> StreamingProbe:
    began = monotonic()
    first_content: float | None = None
    previous_content: float | None = None
    gaps: list[float] = []
    output_chars = 0
    output_tokens: int | None = None
    stream: Any = None
    error_kind: str | None = None
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": workload.prompt},
            ],
            stream=True,
            stream_options={"include_usage": True},
            max_tokens=max_tokens,
            temperature=0,
        )
        if not hasattr(stream, "__aiter__"):
            raise TypeError("streaming endpoint did not return an async iterator")
        async for chunk in stream:
            observed = monotonic()
            count = _usage_tokens(chunk)
            if count is not None:
                output_tokens = count
            piece = _text_piece(chunk)
            if not piece:
                continue
            if first_content is None:
                first_content = observed
            if previous_content is not None:
                gaps.append(max(0.0, (observed - previous_content) * 1000))
            previous_content = observed
            output_chars += len(piece)
    except Exception as exc:
        error_kind = type(exc).__name__
    finally:
        if stream is not None:
            await _close_stream(stream)

    ended = monotonic()
    elapsed_ms = max(0.01, (ended - began) * 1000)
    first_ms = round((first_content - began) * 1000, 2) if first_content is not None else None
    ok = error_kind is None and output_chars > 0
    if error_kind is None and output_chars == 0:
        error_kind = "EmptyStream"
    return StreamingProbe(
        category=workload.category,
        elapsed_ms=round(elapsed_ms, 2),
        first_content_ms=first_ms,
        inter_chunk_gaps_ms=tuple(round(gap, 2) for gap in gaps),
        output_chars=output_chars,
        output_tokens=output_tokens,
        ok=ok,
        error_kind=error_kind,
    )


def _category_summary(probes: Sequence[StreamingProbe]) -> dict[str, Any]:
    succeeded = [probe for probe in probes if probe.ok]
    first = [probe.first_content_ms for probe in succeeded if probe.first_content_ms is not None]
    elapsed = [probe.elapsed_ms for probe in succeeded]
    gaps = [gap for probe in succeeded for gap in probe.inter_chunk_gaps_ms]
    chars = sum(probe.output_chars for probe in succeeded)
    char_ms = sum(probe.elapsed_ms for probe in succeeded)
    usage_complete = bool(succeeded) and all(type(probe.output_tokens) is int for probe in succeeded)
    tokens = sum(probe.output_tokens or 0 for probe in succeeded) if usage_complete else None
    post_first_content_ms = sum(
        max(0.0, probe.elapsed_ms - (probe.first_content_ms or 0.0))
        for probe in succeeded
    )
    return {
        "samples": len(probes),
        "successful": len(succeeded),
        "failed": len(probes) - len(succeeded),
        "first_content_p50_ms": _percentile(first, 0.50),
        "first_content_p95_ms": _percentile(first, 0.95),
        "end_to_end_p50_ms": _percentile(elapsed, 0.50),
        "end_to_end_p95_ms": _percentile(elapsed, 0.95),
        "inter_chunk_gap_p95_ms": _percentile(gaps, 0.95),
        "output_chars_per_second": round(chars * 1000 / char_ms, 2) if char_ms else None,
        "output_tokens": tokens,
        "client_output_tokens_per_second_after_first_content": (
            round(tokens * 1000 / post_first_content_ms, 2)
            if tokens is not None and post_first_content_ms > 0 else None
        ),
        "usage_complete": usage_complete,
        "error_kinds": sorted({probe.error_kind for probe in probes if probe.error_kind}),
    }


def summarize_streaming_probes(
    probes: Iterable[StreamingProbe],
    *,
    wall_ms: float,
    parallel: int,
    warmup_ms: float,
    workload_order: Sequence[str],
) -> dict[str, Any]:
    rows = list(probes)
    if not rows or any(not isinstance(probe, StreamingProbe) for probe in rows):
        raise ValueError("A nonempty set of streaming probes is required")
    if type(parallel) is not int or not 1 <= parallel <= MAX_PARALLEL:
        raise ValueError("A parallel limit from 1 to 2 is required")
    if (type(wall_ms) not in (int, float) or not math.isfinite(wall_ms) or wall_ms <= 0
            or type(warmup_ms) not in (int, float) or not math.isfinite(warmup_ms) or warmup_ms < 0):
        raise ValueError("Benchmark clocks must be finite and valid")
    if (not isinstance(workload_order, Sequence)
            or isinstance(workload_order, (str, bytes))
            or any(type(name) is not str or not name or len(name) > 64 for name in workload_order)):
        raise ValueError("workload_order must be a sequence of bounded category names")
    categories = sorted({probe.category for probe in rows})
    by_category = {
        category: _category_summary([probe for probe in rows if probe.category == category])
        for category in categories
    }
    overall = _category_summary(rows)
    overall.update({
        "requests_per_second": round(overall["successful"] * 1000 / wall_ms, 3),
        "wall_ms": round(wall_ms, 2),
        "warmup_ms": round(warmup_ms, 2),
        "parallel_limit": parallel,
    })
    return {
        "schema_version": 1,
        "verdict": "measured" if overall["successful"] else "no_successful_samples",
        "overall": overall,
        "by_category": by_category,
        "workload_order": list(workload_order),
        "note": (
            "Synthetic local-only streaming benchmark. first_content is the first nonempty text chunk, "
            "not a tokenizer-level TTFT measurement. The post-first-content token rate is client-observed and includes "
            "network/chunk scheduling; it is not raw engine decode speed. Token counts are reported only when the server "
            "returns complete completion-token usage. No answer-quality, GPU-speedup, or model-intelligence claim is implied; "
            "compare identical prompts, model/runtime revisions, context and hardware."
        ),
    }


async def benchmark_local_streaming(
    endpoint: str,
    model: str,
    *,
    requests: int = 8,
    parallel: int = 1,
    client: Any = None,
) -> dict[str, Any]:
    """Warm a loopback model, then measure a deterministic mixed workload over streaming responses."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("A local model name is required")
    if type(requests) is not int or not 1 <= requests <= MAX_REQUESTS:
        raise ValueError(f"requests must be from 1 to {MAX_REQUESTS}")
    if type(parallel) is not int or not 1 <= parallel <= MAX_PARALLEL:
        raise ValueError(f"parallel must be from 1 to {MAX_PARALLEL}")

    settings = Settings(endpoint=endpoint, model=model)
    settings.validate()  # loopback-only endpoint and normal model-name validation
    own_client = client is None
    if own_client:
        client = open_client(settings, request_timeout=90.0)

    try:
        warmup = await _one_streaming_request(
            client, model,
            InferenceWorkload("warmup", "Reply with the single word ready."),
            max_tokens=8,
        )
        if not warmup.ok:
            raise RuntimeError("Local model warm-up failed; measured run was not started")
        warmup_ms = warmup.elapsed_ms

        workloads = [WORKLOADS[index % len(WORKLOADS)] for index in range(requests)]
        semaphore = asyncio.Semaphore(parallel)

        async def run(workload: InferenceWorkload) -> StreamingProbe:
            async with semaphore:
                return await _one_streaming_request(client, model, workload, max_tokens=192)

        began = monotonic()
        probes = await asyncio.gather(*(run(workload) for workload in workloads))
        wall_ms = max(0.01, (monotonic() - began) * 1000)
        return summarize_streaming_probes(
            probes,
            wall_ms=wall_ms,
            parallel=parallel,
            warmup_ms=warmup_ms,
            workload_order=[workload.category for workload in workloads],
        )
    finally:
        if own_client:
            await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure mixed-workload local STAR streaming inference.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1", help="Loopback model URL ending in /v1")
    parser.add_argument("--model", required=True, help="Configured local model alias")
    parser.add_argument("--requests", type=int, default=8, help=f"Measured requests (1..{MAX_REQUESTS})")
    parser.add_argument("--parallel", type=int, default=1, help=f"Concurrent requests (1..{MAX_PARALLEL})")
    parser.add_argument("--output", type=Path, help="Optional local JSON report path")
    args = parser.parse_args()
    report = asyncio.run(benchmark_local_streaming(
        args.endpoint, args.model, requests=args.requests, parallel=args.parallel
    ))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
