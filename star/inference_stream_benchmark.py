"""Bounded, opt-in FIRST-VISIBLE-TEXT latency measurement for local STAR models.

A model may return a completion quickly but still have terrible streaming
startup latency, which delays natural VTuber speech. Conversely, a transport
can emit an empty/reasoning-only chunk immediately without giving STAR any
usable words. Measure the first nonempty *visible* content delta and the
end of a completed response separately.

Uses only synthetic prompts already defined in inference_benchmark. Does not
start a server, change model settings, capture gameplay, invoke any tool, save
model text, or authorize streaming/broadcast. A trusted host must choose an
idle/authorized endpoint before explicitly calling this benchmark.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import math
from statistics import median
from time import monotonic

from .desktop_core import Settings
from .inference_benchmark import _SYSTEM, _select_cases, _workload_digest

_MAX_REQUESTS = 8
_MAX_PARALLEL = 2
_REQUEST_TIMEOUT_SECONDS = 45.0
_OUTPUT_BOUND = 256


@dataclass(frozen=True)
class StartupProbe:
    """One measured response; no prompt, output, identity, or exception body."""

    case_id: str
    first_visible_ms: float | None
    complete_ms: float
    status: str
    canary_ok: bool | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * fraction) - 1], 2)


def summarize_stream_startup(
    probes: list[StartupProbe], wall_ms: float, *, parallel: int,
    workload: str, workload_digest: str,
) -> dict[str, object]:
    """Summarize completed visible responses, not first network/SSE packets."""
    if (not probes or any(not isinstance(p, StartupProbe) for p in probes)
            or type(parallel) is not int or not 1 <= parallel <= _MAX_PARALLEL
            or type(workload) is not str or workload not in {"mixed", "repeat", "canary"}
            or type(workload_digest) is not str or len(workload_digest) != 64
            or any(c not in "0123456789abcdef" for c in workload_digest)
            or type(wall_ms) not in (float, int) or not math.isfinite(wall_ms)
            or wall_ms <= 0):
        raise ValueError("invalid streaming measurements")
    if any(
        type(p.case_id) is not str or len(p.case_id) > 40
        or type(p.complete_ms) not in (int, float)
        or not math.isfinite(p.complete_ms) or p.complete_ms < 0
        or (p.first_visible_ms is not None and (
            type(p.first_visible_ms) not in (int, float)
            or not math.isfinite(p.first_visible_ms)
            or p.first_visible_ms < 0 or p.first_visible_ms > p.complete_ms + 1))
        or p.status not in {"ok", "empty", "incomplete", "truncated",
                            "canary_mismatch", "failed", "timeout"}
        for p in probes
    ):
        raise ValueError("invalid probe state")
    good = [p for p in probes if p.ok and p.first_visible_ms is not None]
    starts = [float(p.first_visible_ms) for p in good if p.first_visible_ms is not None]
    totals = [float(p.complete_ms) for p in good]
    return {
        "workload": workload,
        "workload_sha256": workload_digest,
        "requests": len(probes),
        "completed": len(good),
        "failed": len(probes) - len(good),
        "parallel_limit": parallel,
        "wall_ms": round(wall_ms, 2),
        "first_visible_p50_ms": round(median(starts), 2) if starts else None,
        "first_visible_p95_ms": _percentile(starts, 0.95),
        "complete_p50_ms": round(median(totals), 2) if totals else None,
        "complete_p95_ms": _percentile(totals, 0.95),
        "statuses": {status: sum(p.status == status for p in probes)
                     for status in ("ok", "empty", "incomplete", "truncated",
                                    "canary_mismatch", "failed", "timeout")},
        "partial_visible_failures": sum(
            not p.ok and p.first_visible_ms is not None for p in probes
        ),
        "canary_mismatches": sum(p.canary_ok is False for p in probes),
        "repeated_prompt_warning": workload == "repeat" and len(probes) > 1,
        "note": (
            "First-visible-text is NOT time to first audible TTS sample, "
            "a game FPS measurement, intelligence, factual quality, or a "
            "deployment recommendation. An early SSE/reasoning/role delta "
            "does not count. Only fully stopped nonempty text responses "
            "contribute to latency. Compare identical workloads, model "
            "hashes, slot counts, temperatures and hardware; test audio "
            "playout and OBS separately."
        ),
    }


async def benchmark_stream_startup(
    endpoint: str, model: str, *, requests: int = 4,
    parallel: int = 1, workload: str = "mixed", client=None,
    server: bool = False,
) -> dict[str, object]:
    """Measure actual local OpenAI-compatible streaming response startup.

    This does not run automatically. The caller must choose an authorized,
    idle local or private-LAN STAR server, not a live gameplay/OBS session.
    All captured text is discarded after one bounded response comparison.
    """
    if type(server) is not bool or type(model) is not str or not model.strip():
        raise ValueError("invalid streaming model configuration")
    if type(requests) is not int or not 1 <= requests <= _MAX_REQUESTS:
        raise ValueError("streaming benchmark allows 1..8 requests")
    if type(parallel) is not int or not 1 <= parallel <= _MAX_PARALLEL:
        raise ValueError("streaming benchmark allows 1..2 parallel requests")
    if type(workload) is not str or workload not in {"mixed", "repeat", "canary"}:
        raise ValueError("unknown synthetic workload")
    if workload == "canary" and parallel != 1:
        raise ValueError("canary workload must be sequential")
    cases = _select_cases(requests, workload)
    # Reuse STAR's existing local/private-LAN endpoint and credential checks.
    config = (Settings(provider="star_server", server_endpoint=endpoint, model=model)
              if server else Settings(endpoint=endpoint, model=model))
    config.validate()
    own = client is None
    if own:
        from .providers import open_client
        client = open_client(config, request_timeout=None if server else 90.0)
    semaphore = asyncio.Semaphore(parallel)

    async def one(case) -> StartupProbe:
        async with semaphore:
            begin = monotonic()
            first_visible: float | None = None
            chars: list[str] = []
            collected = 0
            stopped = False
            truncated = False

            async def consume() -> None:
                nonlocal first_visible, collected, stopped, truncated
                stream = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": case.question},
                    ],
                    max_tokens=96, temperature=0, stream=True,
                )
                try:
                    async for packet in stream:
                        for choice in (getattr(packet, "choices", None) or ()):
                            reason = getattr(choice, "finish_reason", None)
                            if reason == "stop":
                                stopped = True
                            elif reason is not None:
                                truncated = True
                            delta = getattr(choice, "delta", None)
                            content = getattr(delta, "content", None)
                            if type(content) is not str or not content:
                                continue  # role/reasoning/empty deltas are NOT speech
                            if first_visible is None:
                                first_visible = (monotonic() - begin) * 1000
                            if collected < _OUTPUT_BOUND:
                                piece = content[:_OUTPUT_BOUND - collected]
                                chars.append(piece)
                                collected += len(piece)
                            if case.expected_token and len(content) > len(piece):
                                truncated = True  # only exact canaries need full text
                finally:
                    # The official async stream has close(); fake streams may
                    # not. This also closes on cancellation/failure.
                    close = getattr(stream, "close", None)
                    if callable(close):
                        result = close()
                        if inspect.isawaitable(result):
                            await result

            try:
                await asyncio.wait_for(consume(), timeout=_REQUEST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                status = "timeout"
            except Exception:
                # Never expose provider errors: they can include keys/prompts.
                status = "failed"
            else:
                if first_visible is None:
                    status = "empty"
                elif truncated:
                    status = "truncated"
                elif not stopped:
                    status = "incomplete"
                elif case.expected_token and "".join(chars).strip() != case.expected_token:
                    status = "canary_mismatch"
                else:
                    status = "ok"
            canary_ok = (True if status == "ok" else
                         False if status == "canary_mismatch" else None) if case.expected_token else None
            return StartupProbe(
                case.case_id,
                round(first_visible, 2) if first_visible is not None else None,
                round((monotonic() - begin) * 1000, 2),
                status, canary_ok,
            )

    started = monotonic()
    try:
        probes = await asyncio.gather(*(one(case) for case in cases))
        return summarize_stream_startup(
            probes, max(0.01, (monotonic() - started) * 1000),
            parallel=parallel, workload=workload,
            workload_digest=_workload_digest(cases),
        )
    finally:
        if own:
            await client.close()


__all__ = [
    "StartupProbe", "summarize_stream_startup", "benchmark_stream_startup",
]
