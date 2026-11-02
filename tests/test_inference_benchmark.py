"""Measured local inference, bounded concurrency, safe endpoint tests."""
import asyncio
from types import SimpleNamespace

import pytest

from star.inference_benchmark import Probe, summarize_probes, benchmark_local_model


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
