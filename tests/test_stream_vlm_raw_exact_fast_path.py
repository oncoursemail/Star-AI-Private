"""Offline safety and CPU-avoidance tests; no game, screen or model access."""
from __future__ import annotations

import json

import pytest

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def frame(at: int, *, w: int = 64, h: int = 48, change: bool = False):
    pixels = bytearray([32, 44, 56] * (w * h))
    if change:
        pixels[0] += 1  # a single raw channel must never hash as identical
    return CapturedVisionFrame(memoryview(pixels).toreadonly(), w, h, at)


def response() -> bytes:
    return json.dumps({
        "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"findings": [{
                "kind": "hud_change", "region": "hud", "confidence": 0.93,
            }]})
        }}]
    }).encode()


def worker(*, transport=None, **kwargs):
    host = LocalLlamaComparisonWorker(
        model="test-local", skip_identical=True, raw_exact_fast_path=True,
        transport=transport or (lambda _: (200, response())), **kwargs,
    )
    host.enable(owner_approved=True, local_model_approved=True)
    return host


def test_raw_exact_fastpath_defaults_off_and_requires_identical_gate():
    assert LocalLlamaComparisonWorker(model="safe").metrics()["raw_exact_gate_enabled"] is False
    for flag in (True, 1, "yes", [], None):
        with pytest.raises(ValueError):
            LocalLlamaComparisonWorker(model="safe", raw_exact_fast_path=flag)


def test_identical_frames_do_not_encode_or_infer(monkeypatch):
    calls = []
    host = worker(transport=lambda data: (calls.append(data) or 200, response()))
    baseline = host(frame(1000))
    assert baseline == WorkerReport(True, True, None)

    def no_jpeg(_):
        raise AssertionError("PIL/JPEG must be bypassed on exact raw match")

    monkeypatch.setattr(host, "_encode", no_jpeg)
    for timestamp in (1500, 2000, 2500, 2900):
        assert host(frame(timestamp)) == WorkerReport(True, True, None)
    assert host._previous.captured_ms == 2900
    assert not calls
    metrics = host.metrics()
    assert metrics["raw_exact_fast_skips"] == 4
    assert metrics["identical_pairs_skipped"] == 4
    assert metrics["requests"] == 0


def test_one_pixel_change_still_checks_jpeg_and_model(monkeypatch):
    host = worker()
    assert host(frame(1000)).succeeded
    original_encode = host._encode
    calls = []
    def tracked_encode(src):
        calls.append(src.captured_ms)
        return original_encode(src)

    monkeypatch.setattr(host, "_encode", tracked_encode)
    report = host(frame(1500, change=True))
    assert calls == [1500]
    # JPEG compression can legitimately map a one-channel change to the same
    # JPEG; this test checks only that the raw fast path does NOT discard it.
    assert host.metrics()["raw_exact_fast_skips"] == 0
    assert report.stopped
    assert host.metrics()["requests"] + host.metrics()["identical_pairs_skipped"] == 1


def test_changed_full_image_outside_roi_still_uses_existing_roi_gate():
    from PIL import Image
    baseline = Image.new("RGB", (160, 100), (20, 20, 20))
    modified = baseline.copy()
    modified.putpixel((150, 50), (210, 20, 20))
    host = worker(focus_box=(0, 0, 500, 1000))
    x = CapturedVisionFrame(memoryview(baseline.tobytes()), 160, 100, 1000)
    y = CapturedVisionFrame(memoryview(modified.tobytes()), 160, 100, 1500)
    assert host(x).succeeded
    assert host(y) == WorkerReport(True, True, None)
    assert host.metrics()["raw_exact_fast_skips"] == 0
    assert host.metrics()["identical_pairs_skipped"] == 1
    assert host.metrics()["requests"] == 0


def test_gap_and_reverse_time_never_reuse_raw_fast_path():
    host = worker(max_gap_ms=1000)
    assert host(frame(1000)).succeeded
    assert host(frame(3000)).succeeded
    assert host(frame(2500)).succeeded
    assert host.metrics()["baselines"] == 3
    assert host.metrics()["raw_exact_fast_skips"] == 0


def test_different_geometry_does_not_skip_even_if_equal_byte_count():
    host = worker()
    assert host(frame(1000, w=96, h=32)).succeeded
    assert host(frame(1500, w=64, h=48)).succeeded
    assert host.metrics()["baselines"] == 2
    assert host.metrics()["raw_exact_fast_skips"] == 0


def test_malformed_and_released_buffers_fail_closed_and_erase_reference():
    host = worker()
    assert host(frame(1000)).succeeded
    saved_jpeg = host._previous.jpeg
    corrupt = CapturedVisionFrame(memoryview(b"x"), 64, 48, 1500)
    assert host(corrupt) == WorkerReport(True, False)
    assert not host.metrics()["reference_cached"]
    assert all(b == 0 for b in saved_jpeg)
    released = memoryview(bytearray(64 * 48 * 3))
    released.release()
    assert host(CapturedVisionFrame(released, 64, 48, 2000)) == WorkerReport(True, False)


def test_disable_reenable_never_reuses_old_session_reference():
    host = worker()
    assert host(frame(1000)).succeeded
    saved = host._previous.jpeg
    host.disable()
    assert all(b == 0 for b in saved)
    host.enable(owner_approved=True, local_model_approved=True)
    assert host(frame(1500)).succeeded
    assert host.metrics()["baselines"] == 2
    assert host.metrics()["raw_exact_fast_skips"] == 0


def test_changed_frames_keep_freshness_timeout_quarantine_and_no_speech():
    def fails(_):
        raise TimeoutError("remote server may still be working")
    host = worker(transport=fails, max_result_latency_ms=1000)
    assert host(frame(1000)).succeeded
    strongly_changed = CapturedVisionFrame(memoryview(bytes([200]) * (64 * 48 * 3)), 64, 48, 1500)
    assert host(strongly_changed) == WorkerReport(False, False)
    assert host.metrics()["quarantined"] is True
    assert host.metrics()["raw_exact_fast_skips"] == 0
    assert host(frame(1600)) == WorkerReport(True, False)
