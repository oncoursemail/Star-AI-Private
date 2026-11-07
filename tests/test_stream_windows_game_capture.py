"""Mocked Windows HWND -> real measured vision gate; no screen is captured."""
from dataclasses import replace

import pytest

from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_observe import ObservationGovernor
from star.stream_vision_host import StreamVisionHost
from star.stream_windows_game_capture import (
    WindowState, WindowsGameCaptureHost, grab_windows_window,
    CapturedVisionFrame, WorkerReport,
)

HWND, PID = 1234, 2468


class FakeImage:
    def __init__(self, *, width=96, height=96, color=0):
        self.size = (width, height)
        self.color = color
        self.converted = False

    def convert(self, fmt):
        assert fmt == "RGB"
        self.converted = True
        return self

    def tobytes(self):
        return bytes([self.color]) * (self.size[0] * self.size[1] * 3)


class Rig:
    def __init__(self, *, with_telemetry=True, probe=None, grab=None, worker=None):
        self.now = [1000.]
        self.cpu = [100, 1000]
        self.used = [2000]
        self.probes = 0
        self.grabs = 0
        self.image = FakeImage()
        self.hardware = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": self.used[0]},
            memory_probe=lambda: (32768, 20000),
            cpu_probe=lambda: tuple(self.cpu),
            clock_ms=lambda: self.now[0],
        )
        self.hardware.set_context(live=False, game_active=False, owner_approved=True)
        self.vision = StreamVisionHost(
            telemetry=self.hardware, governor=ObservationGovernor(),
            clock_ms=lambda: self.now[0],
        )
        self.vision.enable(owner_approved=True, capture_approved=True)
        if with_telemetry:
            self.fresh()
        self.state = WindowState(HWND, PID, True, False, 96, 96)

        def real_probe(hwnd):
            self.probes += 1
            assert hwnd == HWND
            return self.state

        def real_grab(hwnd):
            self.grabs += 1
            assert hwnd == HWND
            return self.image

        self.capture = WindowsGameCaptureHost(
            self.vision, hwnd=HWND, pid=PID, clock_ms=lambda: self.now[0],
            probe=real_probe if probe is None else probe,
            grab=real_grab if grab is None else grab,
            hud_region=(0, 0, 24, 16),
            focus_regions=((12, 12, 16, 16),),
            trusted_worker=worker,
        )

    def fresh(self):
        assert self.hardware.refresh_hardware()
        self.cpu[0] += 10
        self.cpu[1] += 100
        assert self.hardware.refresh_hardware()

    def enable(self):
        self.capture.enable(owner_approved=True, capture_approved=True)


def test_off_by_default_and_separate_authorizations():
    rig = Rig()
    assert rig.capture.capture_once().reason == "window_capture_disabled"
    assert rig.grabs == 0
    with pytest.raises(PermissionError):
        rig.capture.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        rig.capture.enable(capture_approved=True)
    rig.enable()
    with pytest.raises(RuntimeError):
        rig.enable()
    rig.capture.disable()
    rig.vision.disable()
    with pytest.raises(RuntimeError):
        rig.enable()


def test_real_vision_governor_admits_window_pixels_with_one_host_only_grab():
    rig = Rig()
    rig.enable()
    out = rig.capture.capture_once()
    assert out.admitted and out.lease is not None
    assert rig.image.converted
    assert rig.grabs == 1 and rig.probes == 2
    assert rig.vision.status()["pixel_fingerprinted"] == 1
    assert rig.capture.status()["captures"] == 1
    assert rig.vision.acknowledge_worker_stopped(
        out.lease, worker_stopped=True, succeeded=True,
    )
    rig.now[0] += 1200
    # Even with a fresh screenshot, a duplicate does not trigger VLM work.
    result = rig.capture.capture_once()
    assert not result.admitted and result.reason == "low_visual_novelty"
    assert rig.grabs == 2


def test_missing_host_telemetry_rejects_before_any_capture():
    rig = Rig(with_telemetry=False)
    rig.enable()
    result = rig.capture.capture_once()
    assert result.reason == "trusted_hardware_game_audio_missing"
    assert rig.grabs == 0 and rig.probes == 0
    assert rig.capture.status()["preflight_skipped"] == 1


def test_inference_in_flight_prevents_second_screenshot():
    rig = Rig()
    rig.enable()
    first = rig.capture.capture_once()
    rig.now[0] += 600
    second = rig.capture.capture_once()
    assert first.admitted
    assert second.reason == "vision_request_already_in_flight"
    assert rig.grabs == 1


def test_revoked_capture_during_slow_grab_never_reaches_vision():
    rig = Rig()

    def stop_during_grab(_hwnd):
        rig.grabs += 1
        rig.capture.disable()
        return FakeImage()

    rig.capture._grab = stop_during_grab
    rig.enable()
    result = rig.capture.capture_once()
    assert result.reason == "window_capture_revoked"
    assert rig.vision.status()["pixel_fingerprinted"] == 0
    assert not rig.vision.status()["inflight"]


@pytest.mark.parametrize(
    "state",
    [
        WindowState(HWND, PID + 1, True, False, 96, 96),
        WindowState(HWND, PID, False, False, 96, 96),
        WindowState(HWND, PID, True, True, 96, 96),
        WindowState(HWND + 1, PID, True, False, 96, 96),
        WindowState(HWND, PID, True, False, 5000, 5000),
        WindowState(HWND, PID, True, False, 0, 0),
    ],
)
def test_wrong_pid_recycled_hwnd_hidden_minimized_oversized_fails_closed(state):
    rig = Rig()
    rig.state = state
    rig.enable()
    outcome = rig.capture.capture_once()
    assert outcome.reason == "window_identity_or_size_rejected"
    assert rig.grabs == 0
    assert rig.vision.status()["pixel_fingerprinted"] == 0


def test_swapped_window_mid_capture_discards_pixels():
    rig = Rig()
    original = rig.state

    def grab_and_replace(_hwnd):
        rig.grabs += 1
        rig.state = replace(original, pid=PID + 7)
        return FakeImage()

    rig.capture._grab = grab_and_replace
    rig.enable()
    result = rig.capture.capture_once()
    assert result.reason == "window_changed_during_capture"
    assert rig.vision.status()["pixel_fingerprinted"] == 0


def test_slow_capture_discarded_without_cue_or_lease():
    rig = Rig()

    def slow_grab(_hwnd):
        rig.grabs += 1
        rig.now[0] += 1800
        return FakeImage()

    rig.capture._grab = slow_grab
    rig.enable()
    result = rig.capture.capture_once()
    assert result.reason == "window_capture_stale"
    assert not rig.vision.status()["inflight"]


def test_backend_failure_no_desktop_fallback_and_no_media_in_status():
    rig = Rig()

    def failure(_hwnd):
        raise RuntimeError("capture backend issue [private details never logged]")

    rig.capture._grab = failure
    rig.enable()
    result = rig.capture.capture_once()
    assert result.reason == "window_capture_backend_failed"
    assert "private" not in repr(rig.capture.status())
    assert rig.vision.status()["pixel_fingerprinted"] == 0


def test_picture_too_large_is_never_converted_into_pixel_bytes():
    rig = Rig()
    rig.image = FakeImage(width=5000, height=5000)
    rig.enable()
    result = rig.capture.capture_once()
    assert result.reason == "window_capture_backend_failed"
    assert not rig.image.converted


def test_throttle_and_fps_preflight_avoid_repeated_capture():
    rig = Rig()
    rig.enable()
    first = rig.capture.capture_once()
    second = rig.capture.capture_once()
    assert first.admitted
    assert second.reason == "window_capture_interval"
    assert rig.grabs == 1
    assert rig.capture.status()["deferred"] == 1


def test_high_vram_pressure_prevents_capture():
    rig = Rig()
    rig.used[0] = 8000
    rig.fresh()
    rig.enable()
    assert not rig.capture.capture_once().admitted
    assert rig.grabs == 0


def test_non_windows_real_capture_cannot_fallback_to_desktop():
    import os
    if os.name != "nt":
        with pytest.raises(RuntimeError, match="Windows"):
            grab_windows_window(HWND)


@pytest.mark.skipif(__import__("os").name != "nt", reason="native HWND smoke runs only on Windows")
def test_native_pillow_only_captures_our_temporary_synthetic_window():
    """No screen/user app captured; exercises the real Win32 and Pillow APIs."""
    import ctypes
    import os
    import tkinter as tk
    from star.stream_windows_game_capture import probe_windows_window

    root = tk.Tk()
    try:
        root.title("STAR-owned synthetic capture test")
        root.geometry("320x180")
        root.update()
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
        state = probe_windows_window(hwnd)
        assert state.pid == os.getpid()
        assert state.visible and not state.minimized
        assert state.width >= 300 and state.height >= 170
        image = grab_windows_window(hwnd)
        try:
            assert image.size[0] >= 300 and image.size[1] >= 170
        finally:
            image.close()
    finally:
        root.destroy()


def test_config_rejects_untrusted_roi_and_invalid_handles():
    rig = Rig()
    args = dict(
        vision=rig.vision, hwnd=HWND, pid=PID,
        clock_ms=lambda: rig.now[0], probe=lambda _h: rig.state,
        grab=lambda _h: rig.image,
    )
    for roi in (((-1, 0, 16, 16),), ((0, 0, 3, 3),)):
        with pytest.raises(ValueError):
            WindowsGameCaptureHost(**args, focus_regions=roi)
    with pytest.raises(ValueError):
        WindowsGameCaptureHost(**{**args, "hwnd": 0})


def test_capture_preflight_is_only_a_hint_not_an_actual_lease():
    rig = Rig()
    readiness = rig.vision.capture_preflight()
    assert readiness.admitted
    assert readiness.lease is None
    assert not rig.vision.status()["inflight"]
    rig.enable()
    admitted = rig.capture.capture_once()
    assert admitted.lease is not None
    rig.vision.disable()
    assert not rig.vision.capture_preflight().admitted


def test_trusted_worker_is_optional_and_not_invoked_by_plain_capture():
    calls = []

    def worker(frame):
        calls.append(frame)
        return WorkerReport(stopped=True, succeeded=True)

    rig = Rig(worker=worker)
    rig.enable()
    plain = rig.capture.capture_once()
    assert plain.admitted
    assert calls == []
    assert rig.vision.status()["inflight"]
    assert rig.vision.acknowledge_worker_stopped(
        plain.lease, worker_stopped=True, succeeded=True,
    )


def test_worker_receives_exact_scoped_rgb_then_is_scrubbed_and_released():
    observed = []
    retained = []

    def worker(frame):
        assert isinstance(frame, CapturedVisionFrame)
        assert frame.width == frame.height == 96
        assert frame.rgb.readonly
        assert bytes(frame.rgb[:9]) == bytes(9)
        with pytest.raises(TypeError):
            frame.rgb[0] = 2
        retained.append(frame.rgb)
        observed.append(frame.captured_ms)
        return WorkerReport(stopped=True, succeeded=True)

    rig = Rig(worker=worker)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.admission.admitted
    assert outcome.state == "worker_result_accepted"
    assert outcome.worker_invoked and outcome.worker_accepted
    assert len(observed) == 1
    assert all(byte == 0 for byte in retained[0])
    assert not rig.vision.status()["inflight"]
    assert rig.capture.status()["worker_accepted"] == 1


def test_worker_failure_is_reported_without_crediting_inference():
    rig = Rig(worker=lambda _frame: WorkerReport(stopped=True, succeeded=False))
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.admission.admitted
    assert outcome.state == "worker_result_discarded"
    assert outcome.worker_invoked and not outcome.worker_accepted
    assert rig.capture.status()["worker_failed"] == 1
    assert rig.vision.status()["discarded"] == 1
    assert not rig.vision.status()["inflight"]


def test_worker_without_confirmed_physical_stop_keeps_vision_quarantined():
    retained = []

    def worker(frame):
        retained.append(frame.rgb)
        return WorkerReport(stopped=False, succeeded=False)

    rig = Rig(worker=worker)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.state == "worker_stop_unconfirmed"
    assert outcome.admission.lease is not None
    assert rig.vision.status()["inflight"]
    assert not any(retained[0])
    rig.now[0] += 1000
    assert rig.capture.capture_and_process_once().admission.reason == "vision_request_already_in_flight"
    assert rig.vision.acknowledge_worker_stopped(
        outcome.admission.lease, worker_stopped=True, succeeded=False,
    ) is False
    assert not rig.vision.status()["inflight"]


def test_worker_exception_is_private_and_does_not_forge_stopped_ack():
    retained = []

    def broken(frame):
        retained.append(frame.rgb)
        raise RuntimeError("SECRET viewer name: should never leave host")

    rig = Rig(worker=broken)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.state == "worker_stop_unconfirmed"
    assert rig.vision.status()["inflight"]
    assert not any(retained[0])
    assert "SECRET" not in repr(outcome) + repr(rig.capture.status())
    assert rig.capture.status()["worker_unconfirmed"] == 1
    assert not rig.vision.acknowledge_worker_stopped(
        outcome.admission.lease, worker_stopped=True, succeeded=False,
    )


def test_invalid_worker_return_does_not_forge_stop_confirmation():
    rig = Rig(worker=lambda _frame: True)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.state == "worker_stop_unconfirmed"
    assert rig.vision.status()["inflight"]
    assert not rig.vision.acknowledge_worker_stopped(
        outcome.admission.lease, worker_stopped=True, succeeded=False,
    )


def test_revoked_capture_during_processing_discards_successful_worker_result():
    rig = None

    def worker(_frame):
        rig.capture.disable()
        return WorkerReport(stopped=True, succeeded=True)

    rig = Rig(worker=worker)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.state == "worker_result_discarded"
    assert not outcome.worker_accepted
    assert not rig.vision.status()["inflight"]
    assert not rig.capture.status()["enabled"]
    assert rig.capture.status()["worker_failed"] == 1


def test_window_swapped_during_processing_discards_result():
    rig = None

    def worker(_frame):
        rig.state = replace(rig.state, pid=PID + 9)
        return WorkerReport(stopped=True, succeeded=True)

    rig = Rig(worker=worker)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.state == "worker_result_discarded"
    assert not rig.vision.status()["inflight"]
    assert rig.capture.status()["worker_failed"] == 1


def test_worker_never_receives_stale_window_or_busy_hardware_pixels():
    observed = []

    def worker(frame):
        observed.append(frame)
        return WorkerReport(stopped=True, succeeded=True)

    rig = Rig(with_telemetry=False, worker=worker)
    rig.enable()
    out = rig.capture.capture_and_process_once()
    assert not out.admission.admitted
    assert not out.worker_invoked
    assert rig.grabs == 0 and observed == []
    rig.fresh()
    rig.state = replace(rig.state, pid=PID + 5)
    out = rig.capture.capture_and_process_once()
    assert not out.admission.admitted
    assert rig.grabs == 0 and observed == []


def test_missing_configured_worker_rejects_before_screen_capture():
    rig = Rig()
    rig.enable()
    with pytest.raises(RuntimeError, match="trusted"):
        rig.capture.capture_and_process_once()
    assert rig.grabs == 0 and not rig.vision.status()["inflight"]


@pytest.mark.parametrize(
    "stopped, succeeded, error",
    [(1, True, TypeError), (True, "yes", TypeError), (False, True, ValueError)],
)
def test_worker_report_rejects_ambiguous_completion(stopped, succeeded, error):
    with pytest.raises(error):
        WorkerReport(stopped=stopped, succeeded=succeeded)

def test_revoke_between_admission_and_worker_blocks_dispatch():
    calls = []
    rig = Rig(worker=lambda frame: calls.append(frame) or WorkerReport(True, True))
    original = rig.vision.consider_pixels

    def admit_then_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        rig.capture.disable()
        return result

    rig.vision.consider_pixels = admit_then_revoke
    rig.enable()
    out = rig.capture.capture_and_process_once()
    assert out.admission.admitted
    assert out.state == "capture_revoked_before_worker"
    assert not out.worker_invoked and not out.worker_accepted
    assert calls == []
    assert rig.capture.status()["worker_runs"] == 0
    assert not rig.vision.status()["inflight"]


# Visual perception is a bounded CATEGORICAL addendum, not a success claim.
from star.stream_visual_perception import VisualFinding, VisualPacket, parse_visual_packet


def test_accepted_worker_packet_is_bound_to_original_frame_and_zeroized():
    packet_seen = []
    retained = []

    def worker(frame):
        retained.append(frame.rgb)
        packet = parse_visual_packet(
            {"findings": [{"kind": "hud_change", "region": "hud",
                           "confidence": 0.91}]},
            captured_ms=frame.captured_ms, width=frame.width, height=frame.height,
        )
        packet_seen.append(packet)
        return WorkerReport(stopped=True, succeeded=True, perception=packet)

    rig = Rig(worker=worker)
    rig.enable()
    outcome = rig.capture.capture_and_process_once()
    assert outcome.admission.admitted and outcome.worker_accepted
    assert outcome.perception is packet_seen[0]
    assert outcome.perception.findings[0].kind == "hud_change"
    assert rig.capture.status()["perception_accepted"] == 1
    assert rig.vision.status()["completed"] == 1
    assert not any(retained[0])
    assert "rgb" not in repr(outcome)


@pytest.mark.parametrize("tamper", [
    lambda frame: (frame.captured_ms + 1, frame.width, frame.height),
    lambda frame: (frame.captured_ms, frame.width + 1, frame.height),
    lambda frame: (frame.captured_ms, frame.width, frame.height + 1),
])
def test_wrong_frame_stamp_or_geometry_discards_packet_and_releases_worker(tamper):
    def worker(frame):
        stamp, width, height = tamper(frame)
        packet = VisualPacket(
            stamp, width, height,
            (VisualFinding("scene_change", "world", .97),),
        )
        return WorkerReport(True, True, packet)

    rig = Rig(worker=worker)
    rig.enable()
    result = rig.capture.capture_and_process_once()
    assert result.admission.admitted
    assert result.state == "worker_result_discarded"
    assert not result.worker_accepted
    assert result.perception is None
    assert not rig.vision.status()["inflight"]
    assert rig.capture.status()["perception_rejected"] == 1


def test_revoked_session_discards_even_valid_visual_model_packet():
    rig = None

    def worker(frame):
        packet = VisualPacket(
            frame.captured_ms, frame.width, frame.height,
            (VisualFinding("scene_change", "world", .95),),
        )
        rig.capture.disable()
        return WorkerReport(True, True, packet)

    rig = Rig(worker=worker)
    rig.enable()
    result = rig.capture.capture_and_process_once()
    assert result.perception is None and not result.worker_accepted
    assert rig.capture.status()["perception_rejected"] == 1
    assert not rig.vision.status()["inflight"]


def test_missing_pixel_bytes_fail_closed_without_claiming_visual_observation():
    """An unexpected image backend result cannot be treated as a valid RGB frame."""
    class MissingBytesImage(FakeImage):
        def tobytes(self):
            return None

    rig = Rig()
    rig.image = MissingBytesImage()
    rig.enable()
    outcome = rig.capture.capture_once()
    assert outcome.reason == "window_capture_backend_failed"
    assert rig.image.converted
    assert rig.vision.status()["pixel_fingerprinted"] == 0
    assert not rig.vision.status()["inflight"]
    assert rig.capture.status()["capture_failed"] == 1
    assert not rig.capture.status()["capture_busy"]
