"""Threaded host-side revocation tests, with no network, GPU or game capture."""
from __future__ import annotations

from threading import Event, Thread
import json

import pytest

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def _frame(at: int, shade: int = 42) -> CapturedVisionFrame:
    return CapturedVisionFrame(
        memoryview(bytes([shade]) * (64 * 48 * 3)), 64, 48, at,
    )


def _response() -> bytes:
    return json.dumps({"choices": [{
        "finish_reason": "stop",
        "message": {"content": json.dumps({"findings": [{
            "kind": "hud_change", "region": "hud", "confidence": 0.93,
        }]})},
    }]}).encode()


class _BlockingTransport:
    def __init__(self, failure: Exception | None = None):
        self.started = Event()
        self.release = Event()
        self.calls = 0
        self.failure = failure

    def __call__(self, payload: bytes) -> tuple[int, bytes]:
        assert b'"stream":false' in payload
        self.calls += 1
        self.started.set()
        if not self.release.wait(4):
            raise TimeoutError("test transport exceeded cleanup deadline")
        if self.failure is not None:
            raise self.failure
        return 200, _response()


def _worker(transport: _BlockingTransport) -> LocalLlamaComparisonWorker:
    worker = LocalLlamaComparisonWorker(model="local-paired-vlm", transport=transport)
    worker.enable(owner_approved=True, local_model_approved=True)
    assert worker(_frame(1000)).succeeded
    return worker


def _start(worker: LocalLlamaComparisonWorker):
    results: list[WorkerReport] = []
    errors: list[BaseException] = []

    def run():
        try:
            results.append(worker(_frame(1400, shade=100)))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, results, errors


def test_disable_does_not_wait_for_blocked_model_and_rejects_late_success():
    blocked = _BlockingTransport()
    worker = _worker(blocked)
    thread, results, errors = _start(worker)
    try:
        assert blocked.started.wait(2)
        assert worker.metrics()["inflight"] is True
        # Use a separate thread so a regression that holds the network lock
        # cannot hang this test indefinitely.
        revoked = Event()
        disable_thread = Thread(target=lambda: (worker.disable(), revoked.set()),
                                daemon=True)
        disable_thread.start()
        assert revoked.wait(1), "disable blocked behind the model transport"
        disable_thread.join(timeout=1)
        assert not worker.metrics()["enabled"]
        with pytest.raises(RuntimeError):
            worker.enable(owner_approved=True, local_model_approved=True)
        assert worker(_frame(1500)) == WorkerReport(True, False)
    finally:
        blocked.release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors
    assert results == [WorkerReport(True, False)]  # Never consume stale VLM JSON.
    assert worker.metrics()["accepted"] == 0
    assert worker.metrics()["revoked_results"] == 1
    assert worker.metrics()["inflight"] is False
    assert worker.metrics()["transport_samples"] == 1
    assert worker.metrics()["transport_ms_last"] >= 0
    assert worker.metrics()["transport_ms_p95"] >= 0
    assert blocked.calls == 1


def test_second_request_during_transport_is_rejected_without_reading_pixels():
    blocked = _BlockingTransport()
    worker = _worker(blocked)
    thread, results, errors = _start(worker)
    try:
        assert blocked.started.wait(2)
        invalid = CapturedVisionFrame(memoryview(b""), 64, 48, 1700)
        assert worker(invalid) == WorkerReport(True, False)
        assert worker.metrics()["busy_rejected"] == 1
        assert worker.metrics()["invalid_frames"] == 0
        assert blocked.calls == 1
    finally:
        blocked.release.set()
        thread.join(timeout=3)
    assert not errors
    assert results and results[0].perception is not None
    assert worker.metrics()["inflight"] is False


def test_completed_revoked_request_requires_new_session_baseline():
    blocked = _BlockingTransport()
    worker = _worker(blocked)
    thread, results, errors = _start(worker)
    try:
        assert blocked.started.wait(2)
        worker.disable()
        with pytest.raises(RuntimeError):
            worker.clear_quarantine(
                owner_approved=True, physical_request_stopped=True,
            )
    finally:
        blocked.release.set()
        thread.join(timeout=3)
    assert not errors and results == [WorkerReport(True, False)]
    worker.enable(owner_approved=True, local_model_approved=True)
    assert worker(_frame(2000)) == WorkerReport(True, True, None)
    assert worker.metrics()["baselines"] == 2
    assert blocked.calls == 1  # Never uses a frame from the revoked epoch.


def test_timeout_after_disable_still_quarantines_uncertain_physical_worker():
    blocked = _BlockingTransport(TimeoutError("server may still be running"))
    worker = _worker(blocked)
    thread, results, errors = _start(worker)
    try:
        assert blocked.started.wait(2)
        worker.disable()
        assert worker.metrics()["inflight"]
    finally:
        blocked.release.set()
        thread.join(timeout=3)
    assert not errors and results == [WorkerReport(False, False)]
    assert worker.metrics()["quarantined"] is True
    assert worker.metrics()["ambiguous_stop"] == 1
    with pytest.raises(RuntimeError):
        worker.enable(owner_approved=True, local_model_approved=True)
    with pytest.raises(PermissionError):
        worker.clear_quarantine(owner_approved=True)
    worker.clear_quarantine(
        owner_approved=True, physical_request_stopped=True,
    )
    worker.enable(owner_approved=True, local_model_approved=True)
    assert worker(_frame(3000)).succeeded
    assert blocked.calls == 1


def test_connection_refused_during_revocation_is_known_not_started():
    blocked = _BlockingTransport(ConnectionRefusedError("nothing listening"))
    worker = _worker(blocked)
    thread, results, errors = _start(worker)
    try:
        assert blocked.started.wait(2)
        worker.disable()
    finally:
        blocked.release.set()
        thread.join(timeout=3)
    assert not errors and results == [WorkerReport(True, False)]
    assert worker.metrics()["quarantined"] is False
    assert worker.metrics()["inflight"] is False
    worker.enable(owner_approved=True, local_model_approved=True)


def test_fresh_success_without_revocation_remains_accepted():
    blocked = _BlockingTransport()
    worker = _worker(blocked)
    thread, results, errors = _start(worker)
    blocked.release.set()
    thread.join(timeout=3)
    assert not errors
    assert results and results[0].perception is not None
    assert results[0].perception.findings[0].kind == "hud_change"
    assert worker.metrics()["accepted"] == 1
    assert worker.metrics()["revoked_results"] == 0


def test_capture_host_revocation_drops_late_visual_packet_and_releases_lease():
    """Integrated synthetic window + real telemetry scheduler, no OS capture."""
    from PIL import Image

    from star.stream_hardware_telemetry import RealtimeTelemetryHost
    from star.stream_observe import ObservationGovernor
    from star.stream_vision_host import StreamVisionHost
    from star.stream_windows_game_capture import WindowState, WindowsGameCaptureHost

    now = [1000.0]
    cpu = [100, 1000]
    hw = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2000},
        memory_probe=lambda: (32768, 24000),
        cpu_probe=lambda: tuple(cpu), clock_ms=lambda: now[0],
    )
    hw.set_context(live=False, game_active=False, owner_approved=True)
    assert hw.refresh_hardware()
    cpu[0] += 20
    cpu[1] += 100
    assert hw.refresh_hardware()

    vision = StreamVisionHost(
        telemetry=hw, governor=ObservationGovernor(), clock_ms=lambda: now[0],
    )
    vision.enable(owner_approved=True, capture_approved=True)
    state = WindowState(123, 456, True, False, 96, 96)
    shade = [20]
    blocked = _BlockingTransport()
    worker = LocalLlamaComparisonWorker(
        model="local-paired-vlm", transport=blocked,
    )
    worker.enable(owner_approved=True, local_model_approved=True)
    capture = WindowsGameCaptureHost(
        vision, hwnd=123, pid=456, clock_ms=lambda: now[0],
        probe=lambda hwnd: state,
        grab=lambda hwnd: Image.new("RGB", (96, 96), (shade[0],) * 3),
        trusted_worker=worker,
    )
    capture.enable(owner_approved=True, capture_approved=True)
    assert capture.capture_and_process_once().worker_accepted
    now[0] += 1200
    shade[0] = 160

    decisions = []
    errors = []

    def run():
        try:
            decisions.append(capture.capture_and_process_once())
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    try:
        assert blocked.started.wait(2)
        revoked = Event()
        stop = Thread(target=lambda: (
            capture.disable(), worker.disable(), vision.disable(), revoked.set(),
        ), daemon=True)
        stop.start()
        assert revoked.wait(1), "capture revoke blocked on local vision model"
        stop.join(timeout=1)
        assert worker.metrics()["inflight"] is True
        assert capture.capture_and_process_once().state == "not_admitted"
    finally:
        blocked.release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors
    assert len(decisions) == 1
    assert not decisions[0].worker_accepted
    assert decisions[0].perception is None
    assert not vision.status()["inflight"]
    assert worker.metrics()["revoked_results"] == 1
