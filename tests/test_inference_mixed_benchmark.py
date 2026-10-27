"""Offline synthetic tests: no models, internet, Twitch, Studio or audio."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from star.inference_benchmark import Probe, benchmark_local_model, summarize_probes


class StubCompletions:
    def __init__(self, *, fail_on: int | None = None, no_usage_on: int | None = None):
        self.calls: list[dict] = []
        self.active = 0
        self.peak = 0
        self.fail_on = fail_on
        self.no_usage_on = no_usage_on

    async def create(self, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append(kwargs)
        call = len(self.calls)
        try:
            await asyncio.sleep(0.001)
            if call == self.fail_on:
                raise RuntimeError("offline injected failure")
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="Synthetic answer")
                )],
                usage=(None if call == self.no_usage_on else
                       SimpleNamespace(completion_tokens=8)),
            )
        finally:
            self.active -= 1


def _client(stub):
    return SimpleNamespace(chat=SimpleNamespace(completions=stub))


def _run(stub, **kwargs):
    return asyncio.run(benchmark_local_model(
        "http://127.0.0.1:8080/v1", "local-test", client=_client(stub),
        **kwargs,
    ))


def test_default_mixed_workload_has_independent_non_private_questions():
    stub = StubCompletions()
    metrics = _run(stub, requests=12, parallel=3)
    assert metrics["workload"] == "mixed"
    assert metrics["workload_version"] == "star-synthetic-mixed-v1"
    assert len(metrics["workload_sha256"]) == 64
    assert metrics["requests"] == metrics["successful"] == 12
    assert metrics["distinct_cases"] == 12
    assert not metrics["repeated_prompt_warning"]
    assert stub.peak <= 3
    assert stub.peak > 1
    inputs = [call["messages"][1]["content"] for call in stub.calls]
    assert len(set(inputs)) == 12
    assert all(call["temperature"] == 0 and call["max_tokens"] == 96
               for call in stub.calls)
    assert all([message["role"] for message in call["messages"]] ==
               ["system", "user"] for call in stub.calls)
    assert sum(len(item) > 180 for item in inputs) >= 2
    assert "model" in metrics["note"].lower() and "quality" in metrics["note"].lower()
    assert "Synthetic answer" not in str(metrics)


def test_identical_workload_is_stable_and_repeat_mode_marks_cache_bias():
    first = _run(StubCompletions(), requests=5, parallel=2)
    second = _run(StubCompletions(), requests=5, parallel=1)
    assert first["workload_sha256"] == second["workload_sha256"]
    repeated_stub = StubCompletions()
    repeat = _run(repeated_stub, requests=5, workload="repeat")
    assert repeat["workload_sha256"] != first["workload_sha256"]
    assert repeat["repeated_prompt_warning"]
    assert repeat["distinct_cases"] == 1
    assert len({call["messages"][1]["content"]
                for call in repeated_stub.calls}) == 1
    assert repeat["successful"] == 5
    assert repeat["output_tokens"] == 40


def test_mixed_single_request_is_not_claimed_as_broad_speed_gain():
    single = _run(StubCompletions(), requests=1)
    assert single["distinct_cases"] == 1
    assert single["repeated_prompt_warning"] is False
    assert "no deployment" in single["note"].lower()


def test_failures_preserve_attempted_workload_and_do_not_truncate_metrics():
    stub = StubCompletions(fail_on=3)
    result = _run(stub, requests=4, parallel=1)
    assert result["requests"] == 4
    assert result["successful"] == 3 and result["failed"] == 1
    assert result["distinct_cases"] == 4
    assert result["output_tokens"] == 24
    assert "failed" in result


def test_incomplete_token_usage_does_not_inflate_throughput():
    result = _run(StubCompletions(no_usage_on=2), requests=4)
    assert result["successful"] == 4
    assert result["output_tokens"] is None
    assert result["output_tokens_per_second"] is None


@pytest.mark.parametrize("options", [
    {"requests": 0}, {"requests": 13}, {"requests": True},
    {"requests": 3.5}, {"parallel": 0}, {"parallel": 5},
    {"parallel": True}, {"workload": "random"},
    {"workload": None}, {"workload": 1}, {"server": 1},
    {"model": ""}, {"model": None},
])
def test_unsafe_requests_fail_before_model_dispatch(options):
    stub = StubCompletions()
    with pytest.raises((ValueError, TypeError)):
        _run(stub, **options)
    assert not stub.calls


def test_untrusted_external_endpoint_still_blocked_by_settings():
    stub = StubCompletions()
    with pytest.raises(ValueError):
        asyncio.run(benchmark_local_model(
            "https://public-model.example/v1", "local-test",
            requests=2, workload="mixed", client=_client(stub),
        ))
    assert not stub.calls


def test_unlabeled_legacy_samples_preserve_existing_contract():
    record = summarize_probes(
        [Probe(100, 10, True), Probe(200, None, False)], 250, parallel=1,
    )
    assert record["median_request_ms"] == 100
    assert record["output_tokens"] == 10
    assert record["workload"] == "unlabeled"
    assert record["workload_sha256"] is None
    assert record["distinct_cases"] is None
    with pytest.raises(ValueError):
        summarize_probes([Probe(1, 1, True)], 1,
                         parallel=1, workload_digest="not-a-digest")


class CanaryModel(StubCompletions):
    def __init__(self, *, stale_slot: bool = False):
        super().__init__()
        self.stale_slot = stale_slot
        self.previous = None

    async def create(self, **kwargs):
        import re
        self.calls.append(kwargs)
        text = kwargs["messages"][1]["content"]
        found = re.findall(r"STAR-CANARY-\d{2}", text)
        assert len(found) == 1
        token = found[0]
        response = self.previous if self.stale_slot and self.previous is not None else token
        self.previous = token
        await asyncio.sleep(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response))],
            usage=SimpleNamespace(completion_tokens=5),
        )


def test_sequential_long_short_canary_catches_stale_slot_responses():
    good = CanaryModel()
    ok = _run(good, requests=8, workload="canary", parallel=1)
    assert ok["successful"] == 8
    assert ok["canary_mismatches"] == 0
    assert ok["distinct_cases"] == 8
    assert ok["workload_sha256"] != _run(
        CanaryModel(), requests=8, workload="mixed"
    )["workload_sha256"]
    lengths = [len(call["messages"][1]["content"]) for call in good.calls]
    assert lengths[0] > 5000 and lengths[1] < 150
    assert lengths[2] > 5000 and lengths[3] < 150

    contaminated = CanaryModel(stale_slot=True)
    faulty = _run(contaminated, requests=8, workload="canary", parallel=1)
    assert faulty["canary_mismatches"] == 7
    assert faulty["failed"] == 7
    assert faulty["successful"] == 1
    assert faulty["distinct_cases"] == 8


def test_canary_rejects_parallel_dispatch_and_does_not_call_backend():
    stub = CanaryModel()
    with pytest.raises(ValueError, match="sequential"):
        _run(stub, requests=6, parallel=2, workload="canary")
    assert not stub.calls


def test_canary_failure_does_not_count_wrong_answer_tokens_as_success():
    result = _run(CanaryModel(stale_slot=True), requests=4,
                  parallel=1, workload="canary")
    assert result["output_tokens"] == 5
    assert result["canary_mismatches"] == 3
    assert "Synthetic answer" not in str(result)
