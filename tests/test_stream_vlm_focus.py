"""Offline ROI / unchanged-image regression tests: no game, model or network."""
from __future__ import annotations

import base64
from io import BytesIO
import json

import pytest
from PIL import Image, ImageDraw

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def frame(at: float, *, outside=False, inside=False,
          size=(320, 240)) -> CapturedVisionFrame:
    image = Image.new("RGB", size, (35, 45, 65))
    canvas = ImageDraw.Draw(image)
    if outside:
        canvas.rectangle((int(size[0] * .65), 30,
                          int(size[0] * .85), 80), fill=(220, 25, 25))
    if inside:
        canvas.rectangle((30, 35, 95, 76), fill=(20, 230, 20))
    return CapturedVisionFrame(memoryview(image.tobytes()), *size, at)


def response(kind="hud_change", region="hud", confidence=.9):
    payload = {"findings": [{"kind": kind, "region": region,
                             "confidence": confidence}]}
    return json.dumps({"choices": [
        {"finish_reason": "stop",
         "message": {"content": json.dumps(payload)}}
    ]}).encode()


def make(*, focus=None, transport=None, **options):
    worker = LocalLlamaComparisonWorker(
        model="star-local-test", max_image_side=256, focus_box=focus,
        skip_identical=True,
        transport=transport or (lambda _: (200, response())), **options,
    )
    worker.enable(owner_approved=True, local_model_approved=True)
    return worker


@pytest.mark.parametrize("invalid", [
    [], "0,0,500,500", (0, 0, 0, 800), (20, 20, 10, 800),
    (0, 0, 1001, 1000), (-1, 0, 500, 500), (0, 0, True, 800),
    (0.0, 0, 500, 500), (0, 0, 49, 1000), (0, 0, 1000, 40),
    (0, 1, 2), (0, 1, 2, 3, 4), (900, 900, 50, 50),
])
def test_focus_geometry_rejects_malformed_or_too_small_boxes(invalid):
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(model="test", focus_box=invalid)


def test_identical_gate_must_be_explicitly_enabled_by_host():
    assert LocalLlamaComparisonWorker(model="test").metrics()["identical_gate_enabled"] is False
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(model="test", skip_identical=1)
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(model="test", skip_identical="true")


def test_static_identical_images_skip_network_and_refresh_baseline():
    calls = []
    def transport(payload):
        calls.append(payload)
        return 200, response()
    w = make(transport=transport)
    assert w(frame(1000)) == WorkerReport(True, True)
    assert w(frame(1500)) == WorkerReport(True, True)
    assert w(frame(2000)) == WorkerReport(True, True)
    assert len(calls) == 0
    assert w.metrics()["identical_pairs_skipped"] == 2
    assert w.metrics()["requests"] == 0
    assert w.metrics()["reference_cached"] is True
    # The latest identical frame (2000) is the new baseline.
    assert w._previous.captured_ms == 2000
    report = w(frame(2400, inside=True))
    assert report.succeeded is True and report.perception is not None
    assert len(calls) == 1
    assert w.metrics()["reference_cached"] is False
    assert w.metrics()["focus_enabled"] is False


def test_focus_ignores_changes_outside_crop_but_sees_inside_changes():
    bodies = []
    def transport(payload):
        bodies.append(json.loads(payload))
        return 200, response()
    w = make(focus=(0, 0, 450, 1000), transport=transport)
    assert w(frame(1000)).perception is None
    # The right-hand change is outside the owner-configured focus.
    assert w(frame(1500, outside=True)) == WorkerReport(True, True)
    assert w.metrics()["identical_pairs_skipped"] == 1
    assert not bodies
    # The left-hand change is inside; this comparison requires inference.
    result = w(frame(1700, outside=True, inside=True))
    assert result.succeeded and result.stopped
    assert result.perception.width == 320
    assert result.perception.height == 240
    assert result.perception.captured_ms == 1700
    assert len(bodies) == 1
    assert w.metrics()["focused_pairs"] == 1
    assert w.metrics()["focus_enabled"] is True
    assert w.metrics()["requests"] == 1
    content = bodies[0]["messages"][1]["content"]
    assert "fixed host-selected crop" in content[0]["text"]
    images = [
        base64.b64decode(x["image_url"]["url"].split(",", 1)[1])
        for x in content[1:]
    ]
    assert len(images) == 2 and images[0] != images[1]
    for data in images:
        with Image.open(BytesIO(data)) as image:
            assert image.size == (144, 240)
    # Pre- and post-frames are not saved, sent to public URLs, or narrated.
    assert all(x["image_url"]["url"].startswith("data:image/jpeg;base64,")
               for x in content[1:])


def test_without_focus_outside_change_is_not_discarded():
    calls = []
    w = make(transport=lambda data: (calls.append(data) or 200, response()))
    w(frame(1000))
    assert w(frame(1500, outside=True)).perception is not None
    assert len(calls) == 1


def test_tiny_at_runtime_focus_box_fails_closed_without_model_request():
    calls = []
    w = make(focus=(900, 900, 1000, 1000),
             transport=lambda data: calls.append(data))
    report = w(frame(1000, size=(64, 48)))
    assert report == WorkerReport(True, False)
    assert not calls
    assert w.metrics()["invalid_frames"] == 1
    assert not w.metrics()["reference_cached"]


def test_focused_pair_preserves_timeout_quarantine_and_lease():
    def timeout(_):
        raise TimeoutError("underlying request may still be running")
    w = make(focus=(0, 0, 450, 1000), transport=timeout)
    w(frame(1000))
    result = w(frame(1600, inside=True))
    assert result == WorkerReport(False, False)
    assert w.metrics()["quarantined"] is True
    assert w.metrics()["reference_cached"] is False
    assert w(frame(1900, inside=True)) == WorkerReport(True, False)
    w.disable()
    with pytest.raises(PermissionError):
        w.clear_quarantine(owner_approved=True)
    w.clear_quarantine(owner_approved=True, physical_request_stopped=True)
    assert not w.metrics()["quarantined"]


def test_focused_pair_does_not_leak_jpeg_after_use():
    w = make(focus=(0, 0, 450, 1000))
    w(frame(1000))
    previous = w._previous.jpeg
    assert any(previous)
    w(frame(1500, inside=True))
    assert all(v == 0 for v in previous)
    assert not w.metrics()["reference_cached"]
