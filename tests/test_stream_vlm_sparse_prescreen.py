"""Offline sparse-prescreen correctness: only full-frame SHA can skip VLM work."""
from __future__ import annotations

from array import array
import json

import pytest

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def frame(ms: int, *, color: int = 20, width: int = 64, height: int = 48) -> CapturedVisionFrame:
    rgb = bytes((color, 44, 56)) * (width * height)
    return CapturedVisionFrame(memoryview(rgb), width, height, ms)


def reply() -> bytes:
    result = {"findings": [{"kind": "scene_change", "region": "world", "confidence": 0.8}]}
    return json.dumps({"choices": [{"finish_reason": "stop",
                                     "message": {"content": json.dumps(result)}}]}).encode()


def worker(*, transport=None, **kwargs) -> LocalLlamaComparisonWorker:
    host = LocalLlamaComparisonWorker(
        model="local-test", skip_identical=True, raw_exact_fast_path=True,
        raw_sparse_prescreen=True,
        transport=transport or (lambda _: (200, reply())), **kwargs,
    )
    host.enable(owner_approved=True, local_model_approved=True)
    return host


def test_off_by_default_and_host_only_boolean_validation():
    assert LocalLlamaComparisonWorker(model="local-test").metrics()[
        "raw_sparse_prescreen_enabled"] is False
    for bad in (None, 1, "true", [], {}, 0):
        with pytest.raises(ValueError):
            LocalLlamaComparisonWorker(model="local-test", raw_sparse_prescreen=bad)
    with pytest.raises(ValueError, match="requires exact RGB gating"):
        LocalLlamaComparisonWorker(model="local-test", raw_sparse_prescreen=True)


def test_static_frames_still_skip_pil_jpeg_and_model(monkeypatch):
    requests = []
    host = worker(transport=lambda data: (requests.append(data) or 200, reply()))
    assert host(frame(1000)) == WorkerReport(True, True)
    assert host.metrics()["raw_sha_computations"] == 1

    def fail_encode(_):
        raise AssertionError("truly identical RGB cannot go through PIL")

    monkeypatch.setattr(host, "_encode", fail_encode)
    for stamp in (1500, 2000, 2500):
        assert host(frame(stamp)) == WorkerReport(True, True)
    assert requests == []
    result = host.metrics()
    assert result["raw_exact_fast_skips"] == 3
    assert result["sparse_checks"] == 4
    assert result["sparse_mismatch_hash_skips"] == 0
    assert result["raw_sha_computations"] == 4


def test_motion_skips_full_hash_not_jpeg_or_inference():
    requests = []
    host = worker(transport=lambda data: (requests.append(data) or 200, reply()))
    assert host(frame(1000, color=20)).succeeded
    assert host(frame(1500, color=220)).succeeded
    assert len(requests) == 1  # a sampled change is real, never an identical skip
    result = host.metrics()
    assert result["raw_sha_computations"] == 1
    assert result["sparse_mismatch_hash_skips"] == 1
    assert result["raw_exact_fast_skips"] == 0
    assert result["accepted"] == 1


def test_unprobed_pixel_change_is_still_verified_by_full_hash(monkeypatch):
    host = worker()
    initial = frame(1000)
    assert host(initial).succeeded
    rgb = bytearray(initial.rgb)
    positions = {i * (len(rgb) - 1) // 63 for i in range(64)}
    target = next(i for i in range(128, len(rgb) - 128) if i not in positions)
    rgb[target] ^= 0xFF
    changed = CapturedVisionFrame(memoryview(rgb).toreadonly(), 64, 48, 1500)
    assert host._sparse_digest(initial.rgb) == host._sparse_digest(changed.rgb)
    calls = []
    original = host._encode

    def record(frame_):
        calls.append(frame_.captured_ms)
        return original(frame_)

    monkeypatch.setattr(host, "_encode", record)
    assert host(changed).stopped
    assert calls == [1500]
    assert host.metrics()["raw_sha_computations"] == 2
    assert host.metrics()["raw_exact_fast_skips"] == 0


def test_new_stable_scene_can_regain_exact_skip_after_motion():
    host = worker()
    assert host(frame(1000, color=12)).succeeded
    assert host(frame(1500, color=200)).succeeded
    # A completed model comparison clears its reference. First stationary
    # capture re-establishes a new scene baseline; next one can fast-skip.
    assert host(frame(2000, color=200)).succeeded
    previous = host.metrics()["raw_exact_fast_skips"]
    assert host(frame(2500, color=200)).succeeded
    assert host.metrics()["raw_exact_fast_skips"] == previous + 1


def test_clock_and_geometry_mismatch_cannot_suppress_full_hash():
    host = worker(max_gap_ms=1000)
    assert host(frame(1000, color=20)).succeeded
    assert host(frame(3000, color=220)).succeeded   # expired
    assert host(frame(2500, color=100)).succeeded   # reversed
    assert host(frame(2600, color=80, width=48, height=64)).succeeded
    result = host.metrics()
    assert result["sparse_mismatch_hash_skips"] == 0
    assert result["raw_sha_computations"] == 4
    assert result["baselines"] == 4


def test_invalid_frame_erases_reference_and_releases_digest():
    host = worker()
    assert host(frame(1000)).succeeded
    old = host._previous
    assert old.sparse_digest is not None
    assert host(CapturedVisionFrame(memoryview(b"abc"), 64, 48, 1500)) == (
        WorkerReport(True, False))
    assert not host.metrics()["reference_cached"]
    assert old.sparse_digest is None
    assert old.raw_sha256 is None
    assert all(b == 0 for b in old.jpeg)


def test_optout_and_reenable_never_reuse_cached_samples():
    host = worker()
    assert host(frame(1000)).succeeded
    previous = host._previous
    host.disable()
    assert previous.sparse_digest is None
    host.enable(owner_approved=True, local_model_approved=True)
    assert host(frame(1500)).succeeded
    assert host.metrics()["baselines"] == 2
    assert host.metrics()["raw_exact_fast_skips"] == 0


def test_quarantine_on_uncertain_inference_stop_still_wins():
    def timeout(_):
        raise TimeoutError("inference may still be running")
    host = worker(transport=timeout)
    host(frame(1000))
    assert host(frame(1500, color=220)) == WorkerReport(False, False)
    assert host.metrics()["quarantined"] is True
    assert host(frame(2000, color=220)) == WorkerReport(True, False)


def test_sparse_digest_supports_readonly_and_signed_byte_layout():
    unsigned = frame(1000)
    assert LocalLlamaComparisonWorker._sparse_digest(unsigned.rgb) == (
        LocalLlamaComparisonWorker._sparse_digest(unsigned.rgb.toreadonly()))
    signed = array("b", [1] * (64 * 48 * 3))
    signed_frame = CapturedVisionFrame(memoryview(signed), 64, 48, 1000)
    assert worker()(signed_frame).stopped


def test_sample_mismatch_outside_roi_may_still_skip_vlm_by_jpeg_gate():
    # A game world animating outside a host-selected HUD should not be spoken
    # as a change to that HUD. The cheap prefilter can only bypass raw SHA.
    from PIL import Image
    initial = Image.new("RGB", (160, 100), (25, 25, 25))
    changed = initial.copy()
    for y in range(25, 75):
        for x in range(100, 159):
            changed.putpixel((x, y), (220, 25, 25))
    host = worker(focus_box=(0, 0, 500, 1000))
    a = CapturedVisionFrame(memoryview(initial.tobytes()), 160, 100, 1000)
    b = CapturedVisionFrame(memoryview(changed.tobytes()), 160, 100, 1500)
    assert host(a).succeeded and host(b).succeeded
    assert host.metrics()["requests"] == 0
    assert host.metrics()["raw_exact_fast_skips"] == 0
    assert host.metrics()["identical_pairs_skipped"] == 1


def test_sparse_digest_is_nondecisive_even_when_two_views_have_same_jpeg(monkeypatch):
    host = worker()
    assert host(frame(1000, color=20)).succeeded
    calls = []
    # Force identical JPEG on a real pixel change: sampler MUST NOT
    # claim full-frame identity, but existing JPEG fallback can.
    jpeg = bytearray(host._previous.jpeg)
    monkeypatch.setattr(host, "_encode", lambda _: (calls.append(True) or bytearray(jpeg)))
    assert host(frame(1500, color=24)).succeeded
    assert calls
    assert host.metrics()["raw_exact_fast_skips"] == 0
    assert host.metrics()["identical_pairs_skipped"] == 1


@pytest.mark.parametrize("focus", [None, (0, 0, 350, 600)])
def test_deterministic_randomized_equivalence_with_existing_exact_gate(focus):
    """Optional prescreen can change CPU cost, never model/cue decisions."""
    import random
    rng = random.Random(20261028)
    calls = [[], []]
    workers = []
    for sparse in (False, True):
        slot = int(sparse)

        def transport(payload, index=slot):
            calls[index].append(payload)
            return 200, reply()

        w = LocalLlamaComparisonWorker(
            model="local-test", skip_identical=True,
            raw_exact_fast_path=True, raw_sparse_prescreen=sparse,
            focus_box=focus, transport=transport,
        )
        w.enable(owner_approved=True, local_model_approved=True)
        workers.append(w)

    last = None
    for i in range(90):
        width, height = (72, 48) if i < 80 else (96, 36)
        if last is not None and i % 7 in (0, 1) and len(last) == width * height * 3:
            pixels = bytearray(last)
        else:
            color = rng.randrange(256)
            pixels = bytearray((color, rng.randrange(256), 90) * (width * height))
        if i % 9 == 0:
            # A small difference outside most sparse sample positions.
            pixels[125] ^= 0x7F
        last = bytes(pixels)
        timestamp = 1000 + i * 300
        if i % 23 == 22:
            timestamp -= 1000  # force invalid age/reversed time
        f = CapturedVisionFrame(memoryview(last), width, height, timestamp)
        observed = tuple(w(f) for w in workers)
        assert observed[0] == observed[1], (i, focus, observed)
    assert calls[0] == calls[1], "sparse optimization must not change VLM requests"
