"""Offline tests for paired, randomized local inference comparisons."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from star.inference_paired_benchmark import (
    PairedStreamingProbe,
    benchmark_paired_local_streaming,
    summarize_paired_streaming_probes,
)
from star.inference_workload_benchmark import StreamingProbe


def probe(category, *, elapsed, first, ok=True):
    return StreamingProbe(
        category=category,
        elapsed_ms=elapsed,
        first_content_ms=first if ok else None,
        inter_chunk_gaps_ms=(),
        output_chars=2 if ok else 0,
        output_tokens=None,
        ok=ok,
        error_kind=None if ok else "SyntheticFailure",
    )


def paired(pair_id, model, order, category, *, elapsed, first, ok=True):
    return PairedStreamingProbe(
        pair_id, model, order, probe(category, elapsed=elapsed, first=first, ok=ok)
    )


def test_paired_summary_uses_signed_deltas_and_keeps_failed_pairs_visible():
    models = ("baseline", "candidate")
    schedule = [
        {"pair_id": 0, "category": "short_chat", "model_order": ["candidate", "baseline"]},
        {"pair_id": 1, "category": "reasoning", "model_order": ["baseline", "candidate"]},
        {"pair_id": 2, "category": "luau", "model_order": ["candidate", "baseline"]},
    ]
    rows = [
        paired(0, "candidate", 0, "short_chat", elapsed=280, first=80),
        paired(0, "baseline", 1, "short_chat", elapsed=300, first=100),
        paired(1, "baseline", 0, "reasoning", elapsed=310, first=120),
        paired(1, "candidate", 1, "reasoning", elapsed=330, first=130),
        paired(2, "candidate", 0, "luau", elapsed=400, first=150, ok=False),
        paired(2, "baseline", 1, "luau", elapsed=350, first=140),
    ]
    report = summarize_paired_streaming_probes(
        rows, models=models, pair_schedule=schedule, seed=7,
        wall_ms=1000, warmup_ms=100,
        warmup_by_model_ms={"baseline": 50, "candidate": 50},
    )
    comparison = report["by_candidate"]["candidate"]["overall"]
    assert report["verdict"] == "paired_observations"
    assert comparison["paired_samples"] == 2
    assert comparison["incomplete_pairs"] == 1
    assert comparison["first_content_delta_p50_ms"] == -5
    assert comparison["first_content_delta_p95_ms"] == 10
    assert comparison["candidate_faster_pairs"] == 1
    assert comparison["candidate_slower_pairs"] == 1
    assert comparison["candidate_tied_pairs"] == 0
    assert report["failed_requests"] == 1
    assert report["by_candidate"]["candidate"]["by_category"]["luau"]["incomplete_pairs"] == 1


def test_paired_summary_rejects_duplicate_or_missing_probe_rows():
    models = ("baseline", "candidate")
    schedule = [{"pair_id": 0, "category": "short_chat",
                 "model_order": ["baseline", "candidate"]}]
    base = paired(0, "baseline", 0, "short_chat", elapsed=100, first=20)
    candidate = paired(0, "candidate", 1, "short_chat", elapsed=90, first=15)
    kwargs = dict(
        models=models, pair_schedule=schedule, seed=1, wall_ms=10, warmup_ms=1,
        warmup_by_model_ms={"baseline": 1, "candidate": 1},
    )
    with pytest.raises(ValueError, match="exactly one probe"):
        summarize_paired_streaming_probes([base], **kwargs)
    with pytest.raises(ValueError, match="duplicate"):
        summarize_paired_streaming_probes([base, candidate, candidate], **kwargs)


def test_paired_summary_rejects_schedule_order_and_category_mismatches():
    models = ("baseline", "candidate")
    schedule = [{"pair_id": 0, "category": "short_chat",
                 "model_order": ["candidate", "baseline"]}]
    rows = [
        paired(0, "baseline", 0, "short_chat", elapsed=100, first=20),
        paired(0, "candidate", 1, "short_chat", elapsed=90, first=15),
    ]
    kwargs = dict(
        models=models, pair_schedule=schedule, seed=1, wall_ms=10, warmup_ms=1,
        warmup_by_model_ms={"baseline": 1, "candidate": 1},
    )
    with pytest.raises(ValueError, match="recorded randomized schedule"):
        summarize_paired_streaming_probes(rows, **kwargs)
    wrong_category = [
        paired(0, "candidate", 0, "reasoning", elapsed=90, first=15),
        paired(0, "baseline", 1, "short_chat", elapsed=100, first=20),
    ]
    with pytest.raises(ValueError, match="preregistered workload"):
        summarize_paired_streaming_probes(wrong_category, **kwargs)


def test_invalid_models_seed_and_warmup_coverage_are_rejected():
    schedule = [{"pair_id": 0, "category": "short_chat",
                 "model_order": ["baseline", "candidate"]}]
    rows = [
        paired(0, "baseline", 0, "short_chat", elapsed=100, first=20),
        paired(0, "candidate", 1, "short_chat", elapsed=90, first=15),
    ]
    base = dict(pair_schedule=schedule, wall_ms=10, warmup_ms=1,
                warmup_by_model_ms={"baseline": 1, "candidate": 1})
    with pytest.raises(ValueError, match="unique"):
        summarize_paired_streaming_probes(rows, models=["baseline", "baseline"],
                                          seed=1, **base)
    with pytest.raises(ValueError, match="32-bit"):
        summarize_paired_streaming_probes(rows, models=["baseline", "candidate"],
                                          seed=True, **base)
    with pytest.raises(ValueError, match="cover every"):
        summarize_paired_streaming_probes(
            rows, models=["baseline", "candidate"], seed=1,
            pair_schedule=schedule, wall_ms=10, warmup_ms=1,
            warmup_by_model_ms={"baseline": 1},
        )


class FakeStream:
    def __init__(self, owner, *, empty=False):
        self.owner = owner
        self.empty = empty

    async def __aiter__(self):
        self.owner.active += 1
        self.owner.peak = max(self.owner.peak, self.owner.active)
        try:
            if not self.empty:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(completion_tokens=1),
                )
        finally:
            self.owner.active -= 1

    async def aclose(self):
        return None


class FakeCompletions:
    def __init__(self, *, fail_warmup_model=""):
        self.calls = []
        self.active = 0
        self.peak = 0
        self.fail_warmup_model = fail_warmup_model

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        empty = (
            kwargs["max_tokens"] == 8
            and kwargs["model"] == self.fail_warmup_model
        )
        return FakeStream(self, empty=empty)


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)
        self.closed = False

    async def close(self):
        self.closed = True


def test_paired_runner_warms_each_model_randomizes_order_and_runs_sequentially():
    async def run():
        completions = FakeCompletions()
        client = FakeClient(completions)
        report = await benchmark_paired_local_streaming(
            "http://127.0.0.1:8080/v1",
            ["baseline", "candidate"],
            seed=1234,
            client=client,
        )
        assert report["verdict"] == "paired_observations"
        assert report["pair_count"] == 8
        assert report["total_requests"] == 16
        assert report["successful_requests"] == 16
        assert len(completions.calls) == 18  # two warm-ups plus 16 paired requests
        assert [call["model"] for call in completions.calls[:2]] == ["baseline", "candidate"]
        assert completions.peak == 1
        assert completions.calls[0]["max_tokens"] == 8
        assert all(call["stream"] is True for call in completions.calls)
        measured = completions.calls[2:]
        for pair in report["pair_schedule"]:
            start = pair["pair_id"] * 2
            calls = measured[start:start + 2]
            assert [call["model"] for call in calls] == pair["model_order"]
            assert calls[0]["messages"][1]["content"] == calls[1]["messages"][1]["content"]
        encoded = json.dumps(report)
        assert "photosynthesis" not in encoded
        assert '"ok"' not in encoded
        assert client.closed is False  # injected clients remain caller-owned

    asyncio.run(run())


def test_failed_warmup_aborts_before_any_measured_request():
    async def run():
        completions = FakeCompletions(fail_warmup_model="candidate")
        client = FakeClient(completions)
        with pytest.raises(RuntimeError, match="Warm-up failed"):
            await benchmark_paired_local_streaming(
                "http://127.0.0.1:8080/v1",
                ["baseline", "candidate"],
                client=client,
            )
        assert len(completions.calls) == 2
        assert all(call["max_tokens"] == 8 for call in completions.calls)

    asyncio.run(run())


def test_paired_runner_enforces_loopback_and_global_request_budget():
    async def run():
        completions = FakeCompletions()
        client = FakeClient(completions)
        with pytest.raises(ValueError):
            await benchmark_paired_local_streaming(
                "https://example.com/v1", ["baseline", "candidate"], client=client
            )
        with pytest.raises(ValueError, match="exceeds"):
            await benchmark_paired_local_streaming(
                "http://127.0.0.1:8080/v1",
                ["one", "two", "three"],
                repeats_per_workload=4,
                client=client,
            )
        assert completions.calls == []

    asyncio.run(run())


def test_seeded_schedule_is_reproducible_and_third_model_is_supported():
    async def run():
        reports = []
        for _ in range(2):
            completions = FakeCompletions()
            client = FakeClient(completions)
            reports.append(await benchmark_paired_local_streaming(
                "http://127.0.0.1:8080/v1",
                ["baseline", "candidate", "alternate"],
                seed=99,
                client=client,
            ))
        assert reports[0]["pair_schedule"] == reports[1]["pair_schedule"]
        assert all(len(item["model_order"]) == 3 for item in reports[0]["pair_schedule"])
        assert set(reports[0]["by_candidate"]) == {"candidate", "alternate"}

    asyncio.run(run())
