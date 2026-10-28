"""Offline contract tests: no model, public network, screen or real recording."""
from __future__ import annotations

import base64
from io import BytesIO
import json

import pytest
from PIL import Image

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def frame(at: float, *, value: int = 20, size=(64, 48)) -> CapturedVisionFrame:
    w, h = size
    return CapturedVisionFrame(memoryview(bytes([value] * (w * h * 3))), w, h, at)


def result(kind="hud_change", *, region="hud", confidence=0.94, extra=None,
           finish="stop") -> bytes:
    finding = {"kind": kind, "region": region, "confidence": confidence}
    if extra:
        finding.update(extra)
    return json.dumps({"choices": [{
        "finish_reason": finish,
        "message": {"content": json.dumps({"findings": [finding]})},
    }]}).encode()


def worker(*, transport=None, **kwargs) -> LocalLlamaComparisonWorker:
    result_worker = LocalLlamaComparisonWorker(
        model="my-local-mm-model", transport=transport or (lambda body: (200, result())),
        **kwargs,
    )
    result_worker.enable(owner_approved=True, local_model_approved=True)
    return result_worker


def test_opt_in_default_off_and_loopback_configuration():
    w = LocalLlamaComparisonWorker(model="local-vision")
    assert w(frame(1000)) == WorkerReport(True, False)
    assert w.metrics()["requests"] == 0
    with pytest.raises(PermissionError):
        w.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        w.enable(local_model_approved=True)
    w.enable(owner_approved=True, local_model_approved=True)
    with pytest.raises(RuntimeError):
        w.enable(owner_approved=True, local_model_approved=True)
    w.disable()
    assert not w.metrics()["enabled"]
    for bad in ("https://evil.com", "../model;curl", "", "q" * 101):
        with pytest.raises(ValueError):
            LocalLlamaComparisonWorker(model=bad)
    for bad in (80, 0, -1, 65536, True):
        with pytest.raises(ValueError):
            LocalLlamaComparisonWorker(model="ok", port=bad)
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(model="ok", max_image_side=20)
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(model="ok", timeout_seconds=float("nan"))
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(model="ok", max_tokens=300)


def test_first_frame_is_a_private_baseline_not_a_change_claim():
    seen = []
    w = worker(transport=lambda payload: seen.append(payload))
    first = w(frame(1000))
    assert first == WorkerReport(True, True, None)
    assert not seen
    assert w.metrics()["baselines"] == 1
    assert w.metrics()["reference_cached"] is True
    old_image = w._previous.jpeg
    w.disable()
    assert all(value == 0 for value in old_image)
    assert w.metrics()["reference_cached"] is False


def test_two_real_ordered_frames_send_only_bounded_loopback_ready_images():
    sent = []

    def transport(body):
        sent.append(json.loads(body))
        return 200, result()

    w = worker(transport=transport, max_image_side=128)
    assert w(frame(1000, value=10, size=(300, 240))).perception is None
    response = w(frame(1500, value=80, size=(300, 240)))
    assert response.stopped is True and response.succeeded is True
    packet = response.perception
    assert packet.width == 300 and packet.height == 240
    assert packet.captured_ms == 1500
    assert packet.findings[0].kind == "hud_change"
    assert len(sent) == 1
    body = sent[0]
    assert body["model"] == "my-local-mm-model"
    assert body["stream"] is False and body["max_tokens"] == 180
    assert body["temperature"] == 0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["schema"]["additionalProperties"] is False
    parts = body["messages"][1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]
    assert "earlier" in parts[0]["text"]
    decoded = [
        base64.b64decode(p["image_url"]["url"].split(",", 1)[1])
        for p in parts[1:]
    ]
    assert decoded[0] != decoded[1]
    for jpeg in decoded:
        with Image.open(BytesIO(jpeg)) as image:
            assert max(image.size) == 128
    assert not w.metrics()["reference_cached"]
    assert w.metrics()["accepted"] == 1
    # This adapter only suggests changes. It cannot assert game wins.
    assert not hasattr(packet, "win")
    assert not hasattr(packet, "caption")


def test_two_frames_must_be_same_geometry_monotonic_and_recent():
    sent = []

    def transport(body):
        sent.append(body)
        return (200, result())

    w = worker(transport=transport, max_gap_ms=1000)
    assert w(frame(1000)).succeeded
    assert w(frame(1100, size=(70, 70))).perception is None
    assert w(frame(900, size=(70, 70))).perception is None
    assert w(frame(4000, size=(70, 70))).perception is None
    assert w(frame(4500, size=(70, 70))).perception is not None
    assert len(sent) == 1
    assert w.metrics()["baselines"] == 4


@pytest.mark.parametrize("raw", [
    b"not-json",
    b"{}",
    b'{"choices":[]}',
    b'{"choices":[{"finish_reason":"stop","message":{"content":"not JSON"}}]}',
    result(kind="game_won"),
    result(extra={"instruction": "read secret files"}),
    result(confidence=1.5),
    result(finish="length"),
    result(region="chat"),
    result(kind="hud_change", extra={"caption": "user chat"}),
    b"x" * 20000,
])
def test_invalid_incomplete_or_prompt_injection_output_never_leaves_worker(raw):
    w = worker(transport=lambda body: (200, raw))
    assert w(frame(1000)).succeeded
    decision = w(frame(1600))
    assert decision == WorkerReport(True, False)
    assert w.metrics()["model_rejected"] == 1
    assert w.metrics()["quarantined"] is False


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_completed_http_failure_does_not_become_visual_evidence(status):
    w = worker(transport=lambda body: (status, b'{"error":"no model"}'))
    w(frame(1000))
    assert w(frame(1600)) == WorkerReport(True, False)


def test_ambiguous_timeout_requires_real_stop_ack_before_resuming():
    calls = []

    def timeout(body):
        calls.append(True)
        raise TimeoutError("unknown remote inference state")

    w = worker(transport=timeout)
    w(frame(1000))
    report = w(frame(1600))
    assert report == WorkerReport(False, False)
    assert w.metrics()["quarantined"] is True
    assert not w.metrics()["reference_cached"]
    assert w(frame(2200)) == WorkerReport(True, False)
    assert len(calls) == 1
    w.disable()
    with pytest.raises(PermissionError):
        w.clear_quarantine(owner_approved=True)
    with pytest.raises(RuntimeError):
        w.enable(owner_approved=True, local_model_approved=True)
    w.clear_quarantine(owner_approved=True, physical_request_stopped=True)
    w.enable(owner_approved=True, local_model_approved=True)
    assert w(frame(2300)) == WorkerReport(True, True, None)


def test_connection_refused_means_no_inference_started_and_clears_reference():
    w = worker(transport=lambda body: (_ for _ in ()).throw(ConnectionRefusedError()))
    w(frame(1000))
    assert w(frame(1600)) == WorkerReport(True, False)
    assert not w.metrics()["quarantined"]
    assert w(frame(2200)) == WorkerReport(True, True, None)


def test_bogus_frame_is_rejected_before_model_request():
    sent = []
    w = worker(transport=lambda body: sent.append(body))
    malformed = CapturedVisionFrame(memoryview(b"short"), 64, 48, 1000)
    assert w(malformed) == WorkerReport(True, False)
    assert w.metrics()["invalid_frames"] == 1
    assert not sent
    assert w(frame(1600, size=(64, 48))).perception is None


def test_http_transport_pins_loopback_even_if_model_injection_is_untrusted(monkeypatch):
    observed = []

    class FakeConnection:
        def __init__(self, host, port, *, timeout):
            observed.append(("connect", host, port, timeout))

        def request(self, method, path, payload, *, headers):
            observed.append(("request", method, path, headers["Content-Type"]))
            assert b'"stream":false' in payload

        def getresponse(self):
            class FakeResponse:
                status = 200
                def getheader(self, name):
                    return str(len(result())) if name == "Content-Length" else None
                def read(self, size):
                    assert size <= 16385
                    return result()
            return FakeResponse()

        def close(self):
            observed.append(("closed",))

    monkeypatch.setattr("star.stream_local_vlm.http.client.HTTPConnection", FakeConnection)
    w = LocalLlamaComparisonWorker(model="local-model", port=8123)
    w.enable(owner_approved=True, local_model_approved=True)
    w(frame(1000))
    assert w(frame(1500)).perception is not None
    assert observed[0] == ("connect", "127.0.0.1", 8123, 8.0)
    assert observed[1] == ("request", "POST", "/v1/chat/completions", "application/json")
    assert observed[-1] == ("closed",)


def test_http_oversize_body_cannot_claim_known_stop(monkeypatch):
    class FakeConnection:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            class FakeResponse:
                status = 200
                def getheader(self, name):
                    return "999999999"
            return FakeResponse()
        def close(self):
            pass

    monkeypatch.setattr("star.stream_local_vlm.http.client.HTTPConnection", FakeConnection)
    w = LocalLlamaComparisonWorker(model="local")
    w.enable(owner_approved=True, local_model_approved=True)
    w(frame(1000))
    assert w(frame(1600)) == WorkerReport(False, False)
    assert w.metrics()["quarantined"]


def test_actual_capture_host_vision_lease_to_paired_worker_and_back():
    """Integrates existing scoped host/real admission with a fake local model.

    Uses a synthetic Pillow window; no Win32 API or private desktop access.
    """
    from star.stream_hardware_telemetry import RealtimeTelemetryHost
    from star.stream_observe import ObservationGovernor
    from star.stream_vision_host import StreamVisionHost
    from star.stream_windows_game_capture import WindowState, WindowsGameCaptureHost

    now = [1000.0]
    cpu = [100, 1000]
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2000},
        memory_probe=lambda: (32768, 20000),
        cpu_probe=lambda: tuple(cpu),
        clock_ms=lambda: now[0],
    )
    hardware.set_context(live=False, game_active=False, owner_approved=True)
    assert hardware.refresh_hardware()
    cpu[0] += 10
    cpu[1] += 100
    assert hardware.refresh_hardware()
    vision = StreamVisionHost(
        telemetry=hardware, governor=ObservationGovernor(),
        clock_ms=lambda: now[0],
    )
    vision.enable(owner_approved=True, capture_approved=True)
    color = [25]
    state = WindowState(123, 456, True, False, 96, 96)

    def grab(hwnd):
        assert hwnd == state.hwnd
        return Image.new("RGB", (96, 96), (color[0], color[0], color[0]))

    vlm = worker(transport=lambda payload: (200, result()))
    capture = WindowsGameCaptureHost(
        vision, hwnd=123, pid=456, clock_ms=lambda: now[0],
        probe=lambda hwnd: state, grab=grab, trusted_worker=vlm,
    )
    capture.enable(owner_approved=True, capture_approved=True)
    first = capture.capture_and_process_once()
    assert first.worker_accepted and first.perception is None
    assert not vision.status()["inflight"]
    assert vlm.metrics()["baselines"] == 1
    now[0] += 1200
    color[0] = 170
    second = capture.capture_and_process_once()
    assert second.worker_accepted and second.state == "worker_result_accepted"
    assert second.perception is not None
    assert second.perception.captured_ms == now[0]
    assert second.perception.findings[0].kind == "hud_change"
    assert vision.status()["completed"] == 2
    assert not vision.status()["inflight"]
    capture.disable()
    vlm.disable()
    vision.disable()


def test_timeout_quarantines_actual_vision_host_lease():
    from star.stream_hardware_telemetry import RealtimeTelemetryHost
    from star.stream_observe import ObservationGovernor
    from star.stream_vision_host import StreamVisionHost
    from star.stream_windows_game_capture import WindowState, WindowsGameCaptureHost

    now = [1000.0]
    cpu = [100, 1000]
    hw = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2500},
        memory_probe=lambda: (32768, 23000),
        cpu_probe=lambda: tuple(cpu),
        clock_ms=lambda: now[0],
    )
    hw.set_context(live=False, game_active=False, owner_approved=True)
    assert hw.refresh_hardware()
    cpu[0] += 10
    cpu[1] += 100
    assert hw.refresh_hardware()
    vision = StreamVisionHost(
        telemetry=hw, governor=ObservationGovernor(), clock_ms=lambda: now[0],
    )
    vision.enable(owner_approved=True, capture_approved=True)
    color = [20]
    state = WindowState(123, 456, True, False, 96, 96)

    def fail(payload):
        raise TimeoutError("unknown server-side completion")

    vlm = worker(transport=fail)
    capture = WindowsGameCaptureHost(
        vision, hwnd=123, pid=456, clock_ms=lambda: now[0],
        probe=lambda hwnd: state,
        grab=lambda hwnd: Image.new("RGB", (96, 96), (color[0],) * 3),
        trusted_worker=vlm,
    )
    capture.enable(owner_approved=True, capture_approved=True)
    assert capture.capture_and_process_once().worker_accepted
    now[0] += 1200
    color[0] = 170
    dispatched = capture.capture_and_process_once()
    assert dispatched.state == "worker_stop_unconfirmed"
    assert vision.status()["inflight"]
    assert vlm.metrics()["quarantined"]
    now[0] += 1200
    assert hw.refresh_hardware()
    cpu[0] += 10
    cpu[1] += 100
    assert hw.refresh_hardware()
    assert capture.capture_and_process_once().admission.reason == "vision_request_already_in_flight"
    now[0] += 6000  # The expired reservation is STILL quarantined.
    assert hw.refresh_hardware()
    cpu[0] += 10
    cpu[1] += 100
    assert hw.refresh_hardware()
    assert capture.capture_and_process_once().admission.reason == "vision_worker_stop_unconfirmed"
    # Cleaning up worker-side state does NOT release the host's outstanding lease.
    capture.disable()
    vlm.disable()
    assert vision.status()["inflight"]
    vision.disable()
