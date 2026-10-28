"""Deterministic offline tests of live VLM freshness and monotonic backpressure."""

from __future__ import annotations

import json

import pytest

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def _frame(at: int, shade: int = 42) -> CapturedVisionFrame:
    return CapturedVisionFrame(
        memoryview(bytes([shade]) * (64 * 48 * 3)),
        64,
        48,
        at,
    )


def _reply() -> bytes:
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "findings": [
                                    {
                                        "kind": "scene_change",
                                        "region": "world",
                                        "confidence": 0.9,
                                    }
                                ]
                            }
                        )
                    },
                }
            ]
        }
    ).encode()


class FakeClock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms * 1_000_000


def _worker(clock: FakeClock, transport, **kwargs):
    worker = LocalLlamaComparisonWorker(
        model="local-vlm",
        transport=transport,
        clock_ns=clock,
        **kwargs,
    )
    worker.enable(owner_approved=True, local_model_approved=True)
    assert worker(_frame(1000)) == WorkerReport(True, True, None)
    return worker


def test_slow_reply_dropped_and_monotonic_cooldown_skips_pixels():
    clock = FakeClock()
    calls = []

    def transport(data):
        calls.append(data)
        clock.advance(1200 if len(calls) == 1 else 10)
        return 200, _reply()

    worker = _worker(clock, transport, max_result_latency_ms=900, slow_cooldown_ms=3000)
    assert worker(_frame(1500, 50)) == WorkerReport(True, False)
    metrics = worker.metrics()
    assert metrics["stale_results_dropped"] == 1
    assert metrics["accepted"] == 0
    assert metrics["quarantined"] is False
    assert metrics["freshness_gate_enabled"] is True
    assert metrics["cooldown_remaining_ms"] == 3000
    assert not metrics["reference_cached"]

    # Not even an invalid RGB buffer is inspected while the budget blocks
    # processing. A slower model must not continuously saturate a gaming PC.
    invalid = CapturedVisionFrame(memoryview(b""), 64, 48, 1600)
    assert worker(invalid) == WorkerReport(True, False)
    assert worker.metrics()["invalid_frames"] == 0
    clock.advance(2999)
    assert worker(_frame(2000)) == WorkerReport(True, False)
    assert worker.metrics()["cooldown_frames_skipped"] == 2
    clock.advance(1)
    assert worker(_frame(2500)) == WorkerReport(True, True, None)
    assert worker(_frame(2900, 60)).perception is not None
    assert worker.metrics()["accepted"] == 1
    assert len(calls) == 2


def test_latency_budget_is_opt_in_and_does_not_claim_speedup():
    clock = FakeClock()

    def slow_transport(_):
        clock.advance(15000)
        return 200, _reply()

    worker = _worker(clock, slow_transport)
    assert worker(_frame(1500, 90)).perception is not None
    assert worker.metrics()["freshness_gate_enabled"] is False
    assert worker.metrics()["stale_results_dropped"] == 0
    assert worker.metrics()["transport_ms_last"] == 15000


def test_slow_reply_cooldown_survives_disable_and_reenable():
    clock = FakeClock()

    def slow_transport(_):
        clock.advance(1100)
        return 200, _reply()

    worker = _worker(clock, slow_transport, max_result_latency_ms=1000, slow_cooldown_ms=4000)
    assert worker(_frame(1500, 90)) == WorkerReport(True, False)
    worker.disable()
    worker.enable(owner_approved=True, local_model_approved=True)
    assert worker(_frame(1600)) == WorkerReport(True, False)
    clock.advance(4000)
    assert worker(_frame(2000)) == WorkerReport(True, True, None)
    assert worker.metrics()["baselines"] == 2


def test_revoked_result_stays_revoked_even_if_slow():
    clock = FakeClock()
    holder = {}

    def revoke_transport(_):
        clock.advance(2500)
        holder["worker"].disable()
        return 200, _reply()

    worker = _worker(clock, revoke_transport, max_result_latency_ms=1000, slow_cooldown_ms=4000)
    holder["worker"] = worker
    assert worker(_frame(1500)) == WorkerReport(True, False)
    assert worker.metrics()["revoked_results"] == 1
    assert worker.metrics()["stale_results_dropped"] == 0
    assert worker.metrics()["enabled"] is False


def test_uncertain_transport_stop_remains_quarantined():
    clock = FakeClock()

    def timeout(_):
        clock.advance(2500)
        raise TimeoutError("model may still be processing")

    worker = _worker(clock, timeout, max_result_latency_ms=1000, slow_cooldown_ms=4000)
    assert worker(_frame(1500)) == WorkerReport(False, False)
    assert worker.metrics()["quarantined"] is True
    assert worker.metrics()["ambiguous_stop"] == 1
    assert worker.metrics()["stale_results_dropped"] == 0


@pytest.mark.parametrize(
    "budget,cooldown,clock",
    [
        (True, 0, None),
        (99, 0, None),
        (30001, 0, None),
        (1000.5, 0, None),
        (float("nan"), 0, None),
        (None, 1, None),
        (1000, -1, None),
        (1000, True, None),
        (1000, 120001, None),
        (1000, 0, "not-a-clock"),
    ],
)
def test_invalid_freshness_configuration_fails_closed(budget, cooldown, clock):
    with pytest.raises((ValueError, TypeError)):
        LocalLlamaComparisonWorker(
            model="local-vlm", max_result_latency_ms=budget, slow_cooldown_ms=cooldown, clock_ns=clock
        )
