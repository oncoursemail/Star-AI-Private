"""Adversarial integrity checks for measured local inference and speech startup.

These are pure data tests: never contact model servers or control OBS.
"""
import math

import pytest

from star.inference_benchmark import Probe, summarize_probes
from star.inference_stream_benchmark import StartupProbe, summarize_stream_startup


@pytest.mark.parametrize("values", [
    (-1, 4, True, "", None),
    (True, 4, True, "", None),
    (5.4, 4, True, "", None),
    (5, -2, True, "", None),
    (5, True, True, "", None),
    (5, 4, 1, "", None),
    (5, 4, True, "invalid\nlabel", None),
    (5, 4, True, "x" * 80, None),
    (5, 4, True, "", False),
    (5, 4, False, "", True),
    (5, 4, True, "", "true"),
])
def test_completion_summary_rejects_corrupted_measurement(values):
    # The old code accepted these as valid, potentially reporting impossible
    # negative time/tokens or contradicting canary correctness.
    with pytest.raises(ValueError):
        sample = Probe(*values)
        summarize_probes([sample], 100, parallel=1)


@pytest.mark.parametrize("wall", [True, 0.5, math.nan, math.inf, -1, 10**20])
def test_completion_summary_requires_bounded_host_wall_clock(wall):
    with pytest.raises(ValueError):
        summarize_probes([Probe(5, 3, True)], wall, parallel=1)


def test_canary_success_requires_an_explicit_correct_response():
    # Missing correctness data cannot masquerade as a clean cache/slot check.
    with pytest.raises(ValueError):
        summarize_probes(
            [Probe(5, 3, True, "slot-00")], 50,
            parallel=1, workload="canary", workload_digest="a" * 64,
        )
    # Transport failures still have legitimate missing canary verdicts.
    failures = summarize_probes(
        [Probe(5, None, False, "slot-00")], 50,
        parallel=1, workload="canary", workload_digest="a" * 64,
    )
    assert failures["successful"] == 0
    mismatch = summarize_probes(
        [Probe(5, 3, False, "slot-00", False)], 50,
        parallel=1, workload="canary", workload_digest="a" * 64,
    )
    assert mismatch["canary_mismatches"] == 1 and mismatch["successful"] == 0


@pytest.mark.parametrize("probe", [
    StartupProbe("case", None, 10, "ok"),
    StartupProbe("case", 5, 10, "canary_mismatch", True),
    StartupProbe("case", 5, 10, "ok", False),
    StartupProbe("case", 5, 10, "timeout", True),
    StartupProbe("case", 5, 10, "failed", True),
])
def test_streaming_summary_rejects_contradictory_statuses(probe):
    with pytest.raises(ValueError):
        summarize_stream_startup(
            [probe], 50, parallel=1, workload="mixed",
            workload_digest="a" * 64,
        )


def test_streaming_canary_needs_explicit_verification():
    with pytest.raises(ValueError):
        summarize_stream_startup(
            [StartupProbe("slot-00", 5, 10, "ok")], 50,
            parallel=1, workload="canary", workload_digest="a" * 64,
        )
    valid = summarize_stream_startup(
        [StartupProbe("slot-00", 5, 10, "ok", True)], 50,
        parallel=1, workload="canary", workload_digest="a" * 64,
    )
    assert valid["completed"] == 1


def test_explicit_truncated_reply_is_not_a_successful_fast_response():
    import asyncio
    from types import SimpleNamespace
    from star.inference_benchmark import benchmark_local_model

    class Truncated:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content="Fast but unfinished."),
                )],
                usage=SimpleNamespace(completion_tokens=3),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Truncated()))
    result = asyncio.run(benchmark_local_model(
        "http://127.0.0.1:8080/v1", "local-test", client=client,
        requests=1, parallel=1,
    ))
    assert result["successful"] == 0
    assert result["failed"] == 1
    assert result["output_tokens_per_second"] is None
