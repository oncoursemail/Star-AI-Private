"""On-device inference measurements with cache-aware, synthetic mixed workloads.

The default mixed workload deliberately avoids identical repeated prompts:
replaying one tiny prompt can exaggerate local cache or speculative decoding
gains and conceal cross-request slot-state problems. Explicit repeat mode is
for cache diagnostics ONLY, never for claiming broad inference speedups.

All requests are synthetic/public and use an owner-configured loopback model,
or the owner's validated STAR Server LAN endpoint. This module neither loads
models nor changes inference settings or promotes a candidate automatically.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import re
from statistics import median
from time import monotonic

from .desktop_core import Settings


@dataclass(frozen=True)
class Probe:
    elapsed_ms: int
    output_tokens: int | None
    ok: bool
    case_id: str = ""
    canary_ok: bool | None = None
    case_category: str = ""

    def __post_init__(self) -> None:
        # Reject corrupted host measurements before they can inflate speed or
        # report a clean cache check with a contradictory correctness flag.
        if type(self.elapsed_ms) is not int or not 0 <= self.elapsed_ms <= 86_400_000:
            raise ValueError("probe latency must be a bounded integer in ms")
        if self.output_tokens is not None and (
            type(self.output_tokens) is not int
            or not 0 <= self.output_tokens <= 2**31 - 1
        ):
            raise ValueError("probe token count must be a nonnegative integer")
        if type(self.ok) is not bool:
            raise ValueError("probe success must be a strict boolean")
        if (type(self.case_id) is not str or
            (self.case_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,39}", self.case_id) is None)):
            raise ValueError("probe case_id must be an opaque canonical identifier")
        if self.canary_ok is not None and type(self.canary_ok) is not bool:
            raise ValueError("canary_ok must be boolean or absent")
        if (type(self.case_category) is not str or
            (self.case_category and re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}", self.case_category
            ) is None)):
            raise ValueError("case_category must be a bounded canonical identifier")
        if (self.canary_ok is True and not self.ok) or (self.canary_ok is False and self.ok):
            raise ValueError("canary correctness contradicts probe success")


@dataclass(frozen=True)
class _Case:
    case_id: str
    category: str
    question: str
    expected_token: str = ""


# Fixed, non-sensitive development inputs; no project text, personal memory,
# stream transcript, secrets, copyrighted excerpts, or hidden eval answers.
# Each case has a distinct input. Long contexts are synthetic to exercise
# prefill as well as decoding. They are *not* an intelligence benchmark.
_CASES = (
    _Case("geometry", "short", "Describe a geometric square in one sentence."),
    _Case("count", "reasoning", "There are 9 blue counters and 7 gold counters. "
          "Three gold counters are removed. How many remain in total? Explain briefly."),
    _Case("studio-layout", "coding", "In a Roblox Studio UI, a button collides "
          "with a bottom HUD on narrow screens. Suggest two testable layout fixes."),
    _Case("luau-review", "coding", "What is wrong with this Luau pseudocode? "
          "local x = nil; print(x.Name). Provide a safe two-line correction."),
    _Case("game-reflex", "gaming", "In a private obstacle-course test, the player "
          "is on a moving platform approaching a gap. Give a cautious two-step "
          "observation-first plan; do not claim any action was performed."),
    _Case("world-prediction", "reasoning", "An agent predicts a jump succeeds "
          "with probability 0.9, but 2 out of 10 comparable practice jumps "
          "succeeded. What can be concluded and what should be tested next?"),
    _Case("voice-tone", "conversation", "Write a short, natural VTuber reaction "
          "to a verified completed practice jump. Avoid claiming a level win "
          "or inventing feelings, chatters, memories, or personal history."),
    _Case("viewer-conversation", "conversation", "A viewer asks what the game "
          "objective is, but the objective hasn't been observed. How should "
          "a helpful AI streamer answer without inventing knowledge?"),
    _Case("debug-plan", "coding", "A 3D prop appears detached from a wall in "
          "one camera angle. Propose a concise geometry, anchor and collision "
          "inspection checklist for a private game scene."),
    _Case("task-transfer", "gaming", "One learned jump skill works in a 30 FPS "
          "offline test but not in a new 60 FPS simulation. List two hypotheses "
          "and one controlled experiment to test transfer."),
    _Case("document-summary", "long-context",
          "Summarize the decisions from this fictional release note without "
          "inventing a shipment or deployment: "
          "Module Cedar passed an offline parser check. Module Fern needs "
          "more accessibility review. Module Quartz passed three local unit "
          "tests but has not been tested on Windows. Module Amber is postponed "
          "until camera artifacts are resolved. No module has been released."),
    _Case("fact-provenance", "long-context",
          "Given these fictional test notes, state only what is supported: "
          "Trial one observed 49 frames per second during speech. Trial two "
          "observed 54 frames per second with no speech. Trial three has a "
          "missing GPU telemetry sample. All three trials use different game "
          "levels and different camera positions. Explain why these notes "
          "alone cannot prove that a new voice model speeds up games."),
)
# Intentionally run long -> short prompts through the *same* one-slot backend.
# A stale per-slot speculative n-gram cache may reuse an unrelated prompt.
# This is a syntactic transport diagnostic, not a model-knowledge evaluation.
_CANARY_CONTEXT = " ".join(
    f"Fictional checkpoint {index} contains a blue triangle and a green tile."
    for index in range(110)
)
_CANARY_CASES = tuple(
    _Case(
        f"slot-{index:02d}",
        "canary-long" if index % 2 == 0 else "canary-short",
        (
            f"{_CANARY_CONTEXT if index % 2 == 0 else 'Short synthetic input.'} "
            f"Return exactly this token, nothing else: STAR-CANARY-{index:02d}"
        ),
        f"STAR-CANARY-{index:02d}",
    )
    for index in range(12)
)
_VERSION = "star-synthetic-mixed-v1"
_SYSTEM = ("You are a local, offline model performance probe. "
           "Reply clearly and briefly. Never claim to have executed a tool.")


def _select_cases(requests: int, workload: str) -> tuple[_Case, ...]:
    if type(requests) is not int or not 1 <= requests <= len(_CASES):
        raise ValueError("Benchmark requires 1..12 bounded requests")
    if type(workload) is not str or workload not in {"mixed", "repeat", "canary"}:
        raise ValueError("workload must be mixed, repeat or canary")
    if workload == "repeat":
        return (_CASES[0],) * requests
    if workload == "canary":
        return _CANARY_CASES[:requests]
    # Represent gaming, conversational speech, long prefill and short reply
    # within the first four *default* requests. Preserve order across runs.
    order = (0, 4, 6, 10, 2, 1, 8, 11, 3, 5, 7, 9)
    return tuple(_CASES[index] for index in order[:requests])


def _workload_digest(cases: tuple[_Case, ...]) -> str:
    # Hash *inputs*, not generated model outputs. Enables meaningful A/B
    # identity checks without logging generated text, screenshots or chats.
    records = [(_VERSION, case.case_id, case.category, _SYSTEM, case.question, case.expected_token)
               for case in cases]
    payload = json.dumps(records, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarize_probes(
    samples: list[Probe], wall_ms: int, *, parallel: int,
    workload: str = "unlabeled", workload_digest: str | None = None,
) -> dict:
    if (not samples or type(wall_ms) is not int
            or not 1 <= wall_ms <= 86_400_000
            or type(parallel) is not int or not 1 <= parallel <= 4):
        raise ValueError("No valid measurements")
    if type(workload) is not str or workload not in {"unlabeled", "mixed", "repeat", "canary"}:
        raise ValueError("Unknown benchmark workload")
    if workload_digest is not None and (
        type(workload_digest) is not str or len(workload_digest) != 64
        or any(char not in "0123456789abcdef" for char in workload_digest)
    ):
        raise ValueError("invalid synthetic workload digest")
    if any(not isinstance(sample, Probe) for sample in samples):
        raise TypeError("expected Probe measurements")
    if workload == "canary" and any(
        sample.ok and sample.canary_ok is not True for sample in samples
    ):
        # A successful transport with an unverified canary is not a verified
        # response. Missing verdicts must not appear as zero mismatches.
        raise ValueError("successful canary must explicitly match its expected token")
    succeeded = [sample for sample in samples if sample.ok]
    durations = sorted(sample.elapsed_ms for sample in succeeded)
    # Partial usage metadata undercounts output and misleads comparisons.
    tokens = [sample.output_tokens for sample in succeeded] if succeeded and all(
        sample.output_tokens is not None for sample in succeeded
    ) else []
    p95 = durations[max(0, (len(durations) * 95 + 99) // 100 - 1)] if durations else None
    case_ids = {sample.case_id for sample in samples if sample.case_id}
    category_durations: dict[str, list[int]] = {}
    for sample in succeeded:
        if sample.case_category:
            category_durations.setdefault(sample.case_category, []).append(
                sample.elapsed_ms
            )
    category_latency_ms: dict[str, dict[str, int | float]] = {}
    for category, values in sorted(category_durations.items()):
        ordered = sorted(values)
        p95 = ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)]
        category_latency_ms[category] = {
            "count": len(ordered),
            "p50_ms": round(median(ordered), 1),
            "p95_ms": p95,
        }
    canary_mismatch_case_ids = sorted(
        sample.case_id for sample in samples
        if sample.canary_ok is False and sample.case_id
    )
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
        "workload": workload,
        "workload_version": _VERSION if workload != "unlabeled" else None,
        "workload_sha256": workload_digest,
        "distinct_cases": len(case_ids) if case_ids else None,
        "repeated_prompt_warning": workload == "repeat" and len(samples) > 1,
        "canary_mismatches": sum(sample.canary_ok is False for sample in samples),
        "canary_mismatch_case_ids": canary_mismatch_case_ids,
        "category_latency_ms": category_latency_ms,
        "note": (
            "Actual completed responses to the owner's model; synthetic "
            "non-private inputs. Repeat mode is cache-sensitive, not general "
            "speed evidence. Completion-time measurements do not measure "
            "first-audible speech, game FPS, factual quality or intelligence. "
            "Canary mode checks exact response tokens for sequential slot reuse. "
            "No deployment or quality improvement is implied."
        ),
    }


async def benchmark_local_model(
    endpoint: str,
    model: str,
    *,
    requests: int = 4,
    parallel: int = 1,
    workload: str = "mixed",
    client=None,
    server: bool = False,
    case_order: str = "default",
) -> dict:
    """Measure varied response latencies and throughput on approved hardware.

    'mixed' is the default to avoid falsely treating a warm repeated-prompt
    cache as broad performance improvement. 'repeat' is explicit and
    diagnostic. 'canary' checks exact unique response tokens in one slot.
    For canaries, case_order may be 'default', 'long_first', or 'short_first'.
    Comparing configurations requires identical workload_sha256,
    same concurrency, backend/environment and preferably randomized A/B order.
    This benchmark does not promote the faster route or verify correctness.
    """
    if type(server) is not bool:
        raise ValueError("server must be boolean")
    if type(model) is not str or not model.strip():
        raise ValueError("Benchmark requires a model")
    if type(parallel) is not int or not 1 <= parallel <= 4:
        raise ValueError("Benchmark requires 1..4 slots")
    cases = _select_cases(requests, workload)
    if type(case_order) is not str:
        raise ValueError("case_order must be a string")
    if workload == "canary":
        if case_order not in {"default", "long_first", "short_first"}:
            raise ValueError("canary case_order must be default, long_first or short_first")
        if case_order == "long_first":
            cases = tuple(c for c in cases if c.category == "canary-long") + tuple(
                c for c in cases if c.category == "canary-short"
            )
        elif case_order == "short_first":
            cases = tuple(c for c in cases if c.category == "canary-short") + tuple(
                c for c in cases if c.category == "canary-long"
            )
        if len(cases) != requests:
            raise ValueError("canary order requires the requested number of cases")
        if parallel != 1:
            raise ValueError("canary slot-state probing must be sequential")
    elif case_order != "default":
        raise ValueError("case_order is only available for canary workloads")
    if server:
        # Same private-IP validation and keyring key as normal STAR Server chat.
        config = Settings(provider="star_server", server_endpoint=endpoint, model=model)
    else:
        config = Settings(endpoint=endpoint, model=model)
    config.validate()
    own = client is None
    if own:
        from .providers import open_client
        client = open_client(config, request_timeout=None if server else 90.0)
    sem = asyncio.Semaphore(parallel)

    async def one(case: _Case) -> Probe:
        async with sem:
            began = monotonic()
            try:
                result = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": case.question},
                    ],
                    max_tokens=96, temperature=0,
                )
                choice = result.choices[0]
                # Throughput from a length-truncated/tool-diverted or
                # unverified response is not usable gaming/voice intelligence.
                # The OpenAI-compatible API reports "stop" on completion.
                if getattr(choice, "finish_reason", None) != "stop":
                    raise RuntimeError("Unverified or unfinished completion")
                output = str(choice.message.content or "").strip()
                if not output:
                    raise RuntimeError("Empty model output")
                usage = getattr(result, "usage", None)
                count = getattr(usage, "completion_tokens", None) if usage else None
                if type(count) is not int or count < 0:
                    count = None
                token_ok = output == case.expected_token if case.expected_token else None
                return Probe(
                    int((monotonic() - began) * 1000), count,
                    token_ok is not False, case.case_id, token_ok, case.category,
                )
            except Exception:
                return Probe(
                    int((monotonic() - began) * 1000), None, False,
                    case.case_id, None, case.category,
                )

    started = monotonic()
    try:
        samples = await asyncio.gather(*(one(case) for case in cases))
        wall = max(1, int((monotonic() - started) * 1000))
        return summarize_probes(
            samples, wall, parallel=parallel, workload=workload,
            workload_digest=_workload_digest(cases),
        )
    finally:
        if own:
            await client.close()


@dataclass(frozen=True)
class CacheOrderAudit:
    """Same-process, one-slot canary comparison across opposite prompt orders."""

    verdict: str
    requests_per_order: int
    long_first_mismatches: tuple[str, ...]
    short_first_mismatches: tuple[str, ...]
    order_sensitive_case_ids: tuple[str, ...]
    long_first_short_p95_ms: float | None
    short_first_short_p95_ms: float | None
    long_first_long_p95_ms: float | None
    short_first_long_p95_ms: float | None
    short_p95_delta_ms: float | None
    long_p95_delta_ms: float | None
    note: str = (
        "Synthetic exact-token diagnostic only. Both orders share one client "
        "and are sent sequentially to the same configured endpoint, but this "
        "cannot attest server process identity, slot count, llama.cpp commit, "
        "cache internals, or physical host conditions. The second pass inherits "
        "state from the first, so this is a carry-over stress test, not an "
        "independent randomized A/B. A clean result is not proof of cache "
        "isolation or a general speedup."
    )


def _category_p95(summary: dict, category: str) -> float | None:
    category_rows = summary.get("category_latency_ms")
    if not isinstance(category_rows, dict):
        return None
    row = category_rows.get(category)
    if not isinstance(row, dict):
        return None
    value = row.get("p95_ms")
    return float(value) if type(value) in (int, float) else None


async def audit_cache_order(
    endpoint: str,
    model: str,
    *,
    requests: int = 12,
    client=None,
    server: bool = False,
) -> CacheOrderAudit:
    """Probe long→short and short→long prompt order on one sequential client.

    Run against a private single-slot llama-server (normally --np 1).
    The audit deliberately keeps the same client/server endpoint across both
    orders so a persistent slot cache can influence the second pass. It does
    not restart or reconfigure the server.
    """
    if type(requests) is not int or not 2 <= requests <= 12:
        raise ValueError("cache order audit requires 2..12 canary cases per order")
    if type(server) is not bool:
        raise ValueError("server must be boolean")
    own = client is None
    if own:
        if server:
            config = Settings(provider="star_server", server_endpoint=endpoint, model=model)
        else:
            config = Settings(endpoint=endpoint, model=model)
        config.validate()
        from .providers import open_client
        client = open_client(config, request_timeout=None if server else 90.0)
    try:
        long_first = await benchmark_local_model(
            endpoint, model, requests=requests, parallel=1,
            workload="canary", client=client, server=server,
            case_order="long_first",
        )
        short_first = await benchmark_local_model(
            endpoint, model, requests=requests, parallel=1,
            workload="canary", client=client, server=server,
            case_order="short_first",
        )
    finally:
        if own:
            await client.close()

    long_bad = tuple(long_first["canary_mismatch_case_ids"])
    short_bad = tuple(short_first["canary_mismatch_case_ids"])
    order_sensitive = tuple(sorted(set(long_bad) ^ set(short_bad)))
    transport_failed = (
        long_first["failed"] > long_first["canary_mismatches"]
        or short_first["failed"] > short_first["canary_mismatches"]
    )
    if transport_failed:
        verdict = "inconclusive"
    elif order_sensitive:
        verdict = "order_sensitive"
    elif long_bad or short_bad:
        verdict = "canary_failed"
    else:
        verdict = "passed"

    long_short = _category_p95(long_first, "canary-short")
    short_short = _category_p95(short_first, "canary-short")
    long_long = _category_p95(long_first, "canary-long")
    short_long = _category_p95(short_first, "canary-long")
    return CacheOrderAudit(
        verdict=verdict,
        requests_per_order=requests,
        long_first_mismatches=long_bad,
        short_first_mismatches=short_bad,
        order_sensitive_case_ids=order_sensitive,
        long_first_short_p95_ms=long_short,
        short_first_short_p95_ms=short_short,
        long_first_long_p95_ms=long_long,
        short_first_long_p95_ms=short_long,
        short_p95_delta_ms=(
            round(short_short - long_short, 2)
            if long_short is not None and short_short is not None else None
        ),
        long_p95_delta_ms=(
            round(short_long - long_long, 2)
            if long_long is not None and short_long is not None else None
        ),
    )


__all__ = [
    "Probe", "summarize_probes", "benchmark_local_model",
    "CacheOrderAudit", "audit_cache_order",
]
