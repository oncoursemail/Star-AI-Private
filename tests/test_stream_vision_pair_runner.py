"""Offline A/B vision runner tests with fake local transports and synthetic RGB.

No Windows capture, streaming, real LLM inference or networking occurs here.
"""
import base64
import hashlib
import json

import pytest

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_vision_pair_runner import (
    PairedOfflineVisionRunner, UncertainVisionStop,
)
from star.stream_vision_trace_host import PairedVisionTraceHost
from star.stream_windows_game_capture import CapturedVisionFrame
from star.stream_vision_eval import compare_vision, read_jsonl


class Clock:
    def __init__(self, ms=10_000):
        self.ms = ms

    def __call__(self):
        self.ms += 1.0
        return self.ms


def frames(seq, *, width=20, height=16):
    # Large visual differences ensure no JPEG equality shortcut.
    old = bytearray(bytes((seq * 7 % 256, 8, 10)) * (width * height))
    new = bytearray(bytes((seq * 9 % 256, 60, 130)) * (width * height))
    stamp = float(9900 + 20 * seq)
    return (
        CapturedVisionFrame(memoryview(old), width, height, stamp - 100),
        CapturedVisionFrame(memoryview(new), width, height, stamp),
        old, new,
    )


def response(kind):
    findings = [{"kind": kind, "region": "hud", "confidence": 0.95}]
    payload = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"findings": findings})
    }}]}
    return 200, json.dumps(payload).encode("utf-8")


def worker(kind, *, model="tiny", observe=None, bad_response=False, timeout=False):
    def transport(payload):
        if observe is not None:
            observe(json.loads(payload))
        if timeout:
            raise TimeoutError("ambiguous local inference stop")
        if bad_response:
            return 200, b'{"choices":[]}'
        return response(kind)
    return LocalLlamaComparisonWorker(
        model=model, transport=transport, max_image_side=128,
        timeout_seconds=1.0,
    )


def host():
    traces = PairedVisionTraceHost(
        game_id="private_obby", game_version="v2", max_cases=16)
    traces.enable(owner_approved=True, offline_capture_approved=True)
    return traces


def runner(traces, baseline, candidate):
    return PairedOfflineVisionRunner(
        traces=traces, baseline=baseline, candidate=candidate, clock_ms=Clock())


def approvals():
    return dict(owner_approved=True, capture_approved=True, model_approved=True)


def test_runs_both_models_on_exact_same_two_images_and_seals_truth(tmp_path):
    payloads = {"baseline": [], "candidate": []}
    def observe(name):
        def check(body):
            images = [
                item["image_url"]["url"].split(",", 1)[1]
                for item in body["messages"][1]["content"]
                if item["type"] == "image_url"
            ]
            payloads[name].append(tuple(hashlib.sha256(
                base64.b64decode(im)).hexdigest() for im in images))
        return check

    traces = host()
    a = worker("menu_change", observe=observe("baseline"))
    b = worker("hud_change", observe=observe("candidate"))
    r = runner(traces, a, b)
    old, current, *_ = frames(1)
    result = r.run_pair(1, old, current, **approvals())
    assert result.first_variant == "baseline"
    assert result.baseline_status == "accepted"
    assert result.candidate_status == "accepted"
    assert payloads["baseline"] == payloads["candidate"]
    assert len(payloads["baseline"][0]) == 2
    assert traces.metrics()["results"] == 2
    assert r.metrics() == {
        "completed_pairs": 1, "poisoned": False, "last_sequence": 1}

    # Independent labels are only permitted after both predictions are fixed.
    traces.seal_predictions()
    traces.record_truth(
        result.ticket, labels=(("hud_change", "hud"),),
        truth_source="studio_engine", independent_scorer=True)
    report = traces.owner_report(owner_approved=True)
    assert report["candidate"]["recall"] == 1
    assert report["baseline"]["recall"] == 0
    assert report["verdict"] == "inconclusive"
    destination = tmp_path / "private.jsonl"
    assert traces.export_jsonl(destination, owner_approved=True) == 1
    assert compare_vision(read_jsonl(destination)).to_dict() == report
    assert b"data:image" not in destination.read_bytes()
    assert a.metrics()["accepted"] == 1
    assert b.metrics()["accepted"] == 1


def test_counterbalanced_sequential_order_and_independent_resets():
    call_order = []
    traces = host()
    a = worker("hud_change", observe=lambda _: call_order.append("baseline"))
    b = worker("hud_change", observe=lambda _: call_order.append("candidate"))
    r = runner(traces, a, b)
    older, newer, *_ = frames(1)
    r.run_pair(1, older, newer, **approvals())
    older, newer, *_ = frames(2)
    result = r.run_pair(2, older, newer, **approvals())
    assert call_order == ["baseline", "candidate", "candidate", "baseline"]
    assert result.first_variant == "candidate"
    assert a.metrics()["baselines"] == 2
    assert b.metrics()["baselines"] == 2
    assert traces.metrics()["cases"] == 2


def test_mutating_original_capture_during_baseline_does_not_change_candidate():
    captured = {"baseline": [], "candidate": []}
    older, newer, old_rgb, newer_rgb = frames(1)
    def observe(name):
        def check(body):
            images = tuple(
                item["image_url"]["url"] for item in body["messages"][1]["content"]
                if item["type"] == "image_url"
            )
            captured[name].append(images)
            if name == "baseline":
                newer_rgb[:] = b"\xff" * len(newer_rgb)
                old_rgb[:] = b"\xaa" * len(old_rgb)
        return check
    traces = host()
    r = runner(traces, worker("hud_change", observe=observe("baseline")),
               worker("hud_change", observe=observe("candidate")))
    r.run_pair(1, older, newer, **approvals())
    assert captured["baseline"] == captured["candidate"]
    assert newer_rgb == b"\xff" * len(newer_rgb)


def test_bounded_bad_model_reply_is_a_failure_not_an_unknown_success():
    traces = host()
    r = runner(traces, worker("hud_change", bad_response=True),
               worker("hud_change"))
    older, newer, *_ = frames(1)
    result = r.run_pair(1, older, newer, **approvals())
    assert result.baseline_status == "error"
    assert result.candidate_status == "accepted"
    assert traces.metrics()["failed_workers"] == 1
    traces.seal_predictions()
    traces.record_truth(
        result.ticket, labels=(("hud_change", "hud"),),
        truth_source="human_annotation", independent_scorer=True)
    report = traces.owner_report(owner_approved=True)
    assert report["baseline"]["failed_rate"] == 1


def test_ambiguous_stop_quarantines_worker_aborts_cohort_and_poison_runner():
    traces = host()
    a = worker("hud_change", timeout=True)
    b = worker("hud_change")
    r = runner(traces, a, b)
    older, newer, *_ = frames(1)
    with pytest.raises(UncertainVisionStop, match="quarantine"):
        r.run_pair(1, older, newer, **approvals())
    assert r.metrics()["poisoned"]
    assert traces.metrics()["cases"] == 0
    assert not traces.metrics()["enabled"]
    assert a.metrics()["quarantined"]
    assert b.metrics()["requests"] == 0
    with pytest.raises(UncertainVisionStop, match="poisoned"):
        r.run_pair(2, older, newer, **approvals())
    with pytest.raises(PermissionError):
        a.clear_quarantine(owner_approved=True, physical_request_stopped=False)


def test_consent_replay_geometry_time_and_duplicate_pixels_fail_closed():
    traces = host()
    r = runner(traces, worker("unknown"), worker("unknown"))
    old, current, old_rgb, new_rgb = frames(1)
    with pytest.raises(PermissionError):
        r.run_pair(1, old, current)
    assert traces.metrics()["cases"] == 0
    with pytest.raises(ValueError, match="mismatched"):
        different = CapturedVisionFrame(
            memoryview(bytearray(b"x" * (21 * 16 * 3))), 21, 16, 1000)
        r.run_pair(1, old, different, **approvals())
    with pytest.raises(ValueError, match="nonconsecutive"):
        too_old = CapturedVisionFrame(old.rgb, old.width, old.height, 1000)
        r.run_pair(1, too_old, current, **approvals())
    with pytest.raises(ValueError, match="not fresh"):
        future_old = CapturedVisionFrame(old.rgb, old.width, old.height, 99_900)
        in_future = CapturedVisionFrame(current.rgb, current.width, current.height, 100_000)
        r.run_pair(1, future_old, in_future, **approvals())
    assert traces.metrics()["cases"] == 0
    result = r.run_pair(1, old, current, **approvals())
    assert result.baseline_status == "accepted"
    with pytest.raises(ValueError, match="replayed"):
        r.run_pair(1, old, current, **approvals())
    with pytest.raises(ValueError, match="duplicate frame"):
        r.run_pair(2, old, current, **approvals())
    assert not r.metrics()["poisoned"]
    assert traces.metrics()["cases"] == 1


def test_bad_worker_arguments_fail_without_issuing_model_requests():
    traces = host()
    a = worker("hud_change")
    with pytest.raises(TypeError):
        PairedOfflineVisionRunner(traces=traces, baseline=a, candidate=a)
    with pytest.raises(ValueError):
        PairedOfflineVisionRunner(
            traces=traces, baseline=a, candidate=worker("hud_change"),
            max_capture_age_ms=31)
    r = runner(traces, a, worker("hud_change"))
    old, current, *_ = frames(1)
    with pytest.raises(ValueError, match="positive"):
        r.run_pair(True, old, current, **approvals())
    assert a.metrics()["requests"] == 0


def test_interrupted_inference_aborts_trace_instead_of_reusing_worker():
    traces = host()
    def interrupted(_payload):
        raise KeyboardInterrupt("simulated interruption during HTTP handoff")
    a = LocalLlamaComparisonWorker(
        model="tiny", transport=interrupted, max_image_side=128,
        timeout_seconds=1.0)
    b = worker("hud_change")
    r = runner(traces, a, b)
    older, newer, *_ = frames(1)
    with pytest.raises(KeyboardInterrupt):
        r.run_pair(1, older, newer, **approvals())
    assert r.metrics()["poisoned"]
    assert not traces.metrics()["enabled"]
    assert traces.metrics()["cases"] == 0
    with pytest.raises(UncertainVisionStop):
        r.run_pair(2, older, newer, **approvals())
