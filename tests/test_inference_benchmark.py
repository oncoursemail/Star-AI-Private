"""Measured local inference, bounded concurrency, safe endpoint tests."""
import asyncio
from types import SimpleNamespace

import pytest

from star.inference_benchmark import (
    Probe, summarize_probes, benchmark_local_model, audit_cache_order,
)


def test_probe_statistics_real_and_empty_state():
    data = summarize_probes([
        Probe(100,8,True),Probe(250,9,True),Probe(500,None,False)
    ],wall_ms=350,parallel=2)
    assert data["successful"]==2 and data["failed"]==1
    assert data["output_tokens"]==17
    assert data["requests_per_second"] == round(2/.35,3)
    assert data["median_request_ms"]==175
    assert data["p95_request_ms"]==250
    with pytest.raises(ValueError):
        summarize_probes([],100,parallel=1)


def test_benchmark_really_calls_local_model_and_counts_slots():
    class Fake:
        def __init__(self):
            self.active=0
            self.peak=0
            self.calls=[]
        async def create(self,**kwargs):
            self.active += 1
            self.peak=max(self.peak,self.active)
            self.calls.append(kwargs)
            await asyncio.sleep(.02)
            self.active-=1
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content="A square has four equal sides"), finish_reason="stop")
            ],usage=SimpleNamespace(completion_tokens=8))
    async def go():
        f=Fake()
        c=SimpleNamespace(chat=SimpleNamespace(completions=f))
        result=await benchmark_local_model("http://127.0.0.1:8080/v1","qwen",
                                            requests=4,parallel=2,client=c)
        assert result["successful"]==4 and f.peak==2
        assert result["output_tokens"]==32
        assert result["parallel_limit"]==2
        assert all([m["role"] for m in x["messages"]]==["system","user"] for x in f.calls)
    asyncio.run(go())


def test_no_external_benchmark_hosts_or_unbounded_load():
    async def run(endpoint,parallel=1):
        return await benchmark_local_model(endpoint,"x",parallel=parallel,
            client=SimpleNamespace(chat=SimpleNamespace(completions=None)))
    with pytest.raises(ValueError):
        asyncio.run(run("https://provider.example.com/v1"))
    with pytest.raises(ValueError):
        asyncio.run(run("http://127.0.0.1:8080/v1",parallel=10))


def test_summarize_probes_reports_category_latency_and_mismatch_identity():
    data = summarize_probes([
        Probe(100, 8, True, "a", True, "canary-long"),
        Probe(120, 8, True, "b", True, "canary-long"),
        Probe(300, None, False, "c", False, "canary-short"),
    ], wall_ms=600, parallel=1, workload="canary", workload_digest="0" * 64)
    assert data["canary_mismatches"] == 1
    assert data["canary_mismatch_case_ids"] == ["c"]
    assert data["category_latency_ms"]["canary-long"] == {
        "count": 2, "p50_ms": 110, "p95_ms": 120,
    }
    assert "canary-short" not in data["category_latency_ms"]


def test_canary_workload_runs_exact_unique_tokens_sequentially():
    import re

    class Fake:
        def __init__(self):
            self.active = 0
            self.peak = 0
            self.calls = []

        async def create(self, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            text = kwargs["messages"][1]["content"]
            self.calls.append(text)
            token = re.search(r"STAR-CANARY-\d{2}", text).group(0)
            self.active -= 1
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=token), finish_reason="stop",
                )],
                usage=SimpleNamespace(completion_tokens=1),
            )

    async def go():
        fake = Fake()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        result = await benchmark_local_model(
            "http://127.0.0.1:8080/v1", "qwen", requests=12,
            parallel=1, workload="canary", client=client,
        )
        assert result["successful"] == 12
        assert result["canary_mismatches"] == 0
        assert result["canary_mismatch_case_ids"] == []
        assert result["distinct_cases"] == 12
        assert fake.peak == 1
        assert len(fake.calls) == 12
        assert "canary-long" in result["category_latency_ms"]
        assert "canary-short" in result["category_latency_ms"]

    asyncio.run(go())


def test_cache_order_audit_detects_long_to_short_order_sensitivity():
    import re

    class OrderSensitiveFake:
        def __init__(self):
            self.previous_was_long = False
            self.calls = []
            self.active = 0
            self.peak = 0

        async def create(self, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            text = kwargs["messages"][1]["content"]
            self.calls.append(text)
            token = re.search(r"STAR-CANARY-\d{2}", text).group(0)
            is_short = "Short synthetic input." in text
            is_long = "Fictional checkpoint" in text
            output = "STAR-CANARY-99" if is_short and self.previous_was_long else token
            self.previous_was_long = is_long
            self.active -= 1
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=output), finish_reason="stop",
                )],
                usage=SimpleNamespace(completion_tokens=1),
            )

    async def go():
        fake = OrderSensitiveFake()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        report = await audit_cache_order(
            "http://127.0.0.1:8080/v1", "qwen", requests=12, client=client,
        )
        assert report.verdict == "order_sensitive"
        assert report.long_first_mismatches == ("slot-01",)
        assert report.short_first_mismatches == ()
        assert report.order_sensitive_case_ids == ("slot-01",)
        assert fake.peak == 1
        assert len(fake.calls) == 24
        assert "Fictional checkpoint" in fake.calls[0]
        assert "Short synthetic input." in fake.calls[12]

    asyncio.run(go())


def test_cache_order_audit_passes_when_both_orders_match():
    import re

    class Fake:
        async def create(self, **kwargs):
            text = kwargs["messages"][1]["content"]
            token = re.search(r"STAR-CANARY-\d{2}", text).group(0)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=token), finish_reason="stop",
                )],
                usage=SimpleNamespace(completion_tokens=1),
            )

    async def go():
        client = SimpleNamespace(chat=SimpleNamespace(completions=Fake()))
        report = await audit_cache_order(
            "http://127.0.0.1:8080/v1", "qwen", requests=12, client=client,
        )
        assert report.verdict == "passed"
        assert report.long_first_mismatches == ()
        assert report.short_first_mismatches == ()
        assert report.order_sensitive_case_ids == ()
        assert report.long_first_short_p95_ms is not None
        assert report.short_first_short_p95_ms is not None

    asyncio.run(go())


def test_cache_order_audit_is_inconclusive_on_transport_failures():
    class Fake:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=""), finish_reason="length",
                )],
                usage=SimpleNamespace(completion_tokens=0),
            )

    async def go():
        client = SimpleNamespace(chat=SimpleNamespace(completions=Fake()))
        report = await audit_cache_order(
            "http://127.0.0.1:8080/v1", "qwen", requests=4, client=client,
        )
        assert report.verdict == "inconclusive"

    asyncio.run(go())


def test_cache_order_audit_rejects_invalid_request_count_and_parallel_case_order():
    with pytest.raises(ValueError):
        asyncio.run(audit_cache_order(
            "http://127.0.0.1:8080/v1", "qwen", requests=1,
            client=SimpleNamespace(chat=SimpleNamespace(completions=None)),
        ))
    with pytest.raises(ValueError):
        asyncio.run(benchmark_local_model(
            "http://127.0.0.1:8080/v1", "qwen", requests=4,
            parallel=2, workload="canary",
            client=SimpleNamespace(chat=SimpleNamespace(completions=None)),
        ))
