"""Offline tests for opt-in lower-cost gaming vision workers (no screen/game)."""
from __future__ import annotations

import unittest

from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_observe import ObservationGovernor
from star.stream_vision_host import StreamVisionHost
from star.stream_visual_perception import VisualFinding, VisualPacket
from star.stream_windows_game_capture import (
    CapturedVisionFrame, WindowsGameCaptureHost, WindowState, WorkerReport,
)

HWND, PID = 1111, 2222


class FakeImage:
    def __init__(self, width=96, height=96, color=17, *, faulty=False):
        self.size = (width, height)
        self.color = color
        self.resized_to = None
        self.faulty = faulty
        self.closed = False

    def convert(self, mode):
        if mode != "RGB":
            raise AssertionError("unexpected conversion")
        return self

    def tobytes(self):
        if self.faulty:
            raise ValueError("simulated private renderer diagnostic")
        return bytes([self.color]) * (self.size[0] * self.size[1] * 3)

    def resize(self, size):
        self.resized_to = size
        return FakeImage(*size, color=self.color, faulty=self.faulty)

    def close(self):
        self.closed = True


class Rig:
    def __init__(self, worker=None, *, budget=None, image=None):
        self.now = [1000.0]
        self.cpu = [100, 1000]
        self.image = image if image is not None else FakeImage()
        self.vision_calls = []
        self.hardware = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 1000},
            memory_probe=lambda: (32768, 20000),
            cpu_probe=lambda: tuple(self.cpu),
            clock_ms=lambda: self.now[0],
        )
        self.hardware.set_context(live=False, game_active=False, owner_approved=True)
        self._fresh()
        self.vision = StreamVisionHost(
            telemetry=self.hardware, governor=ObservationGovernor(),
            clock_ms=lambda: self.now[0],
        )
        self.vision.enable(owner_approved=True, capture_approved=True)
        self.capture = WindowsGameCaptureHost(
            self.vision, hwnd=HWND, pid=PID, worker_max_pixels=budget,
            clock_ms=lambda: self.now[0],
            probe=lambda _: WindowState(HWND, PID, True, False, 96, 96),
            grab=lambda _: self.image,
            trusted_worker=worker if worker is not None else self.worker,
        )
        self.capture.enable(owner_approved=True, capture_approved=True)

    def _fresh(self):
        self.hardware.refresh_hardware()
        self.cpu[0] += 11
        self.cpu[1] += 101
        self.hardware.refresh_hardware()

    def worker(self, frame):
        self.vision_calls.append(frame)
        return WorkerReport(stopped=True, succeeded=True)


class WorkerPixelBudgetTests(unittest.TestCase):
    def test_reject_invalid_budgets_before_capture(self):
        for invalid in (-1, True, 0, 71, 10_000_000, 1.0, "4096"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Rig(budget=invalid)

    def test_off_by_default_retains_native_model_frame(self):
        rig = Rig()
        outcome = rig.capture.capture_and_process_once()
        self.assertTrue(outcome.worker_accepted)
        seen = rig.vision_calls[0]
        self.assertEqual((seen.width, seen.height), (96, 96))
        self.assertEqual((seen.source_width, seen.source_height), (96, 96))
        self.assertEqual(rig.capture.status()["worker_resizes"], 0)

    def test_downscale_worker_only_after_native_evidence_admission(self):
        rig = Rig(budget=4096)
        outcome = rig.capture.capture_and_process_once()
        self.assertEqual(outcome.state, "worker_result_accepted")
        self.assertEqual(rig.capture.status()["worker_resizes"], 1)
        self.assertEqual(rig.vision.status()["pixel_fingerprinted"], 1)
        self.assertEqual(rig.image.resized_to, (64, 64))
        seen = rig.vision_calls[0]
        self.assertEqual((seen.width, seen.height), (64, 64))
        self.assertEqual((seen.source_width, seen.source_height), (96, 96))
        self.assertEqual(len(seen.rgb), 64 * 64 * 3)
        self.assertEqual(bytes(seen.rgb), b"\x00" * (64 * 64 * 3))
        self.assertTrue(rig.image.closed)

    def test_does_not_resize_when_image_fits_budget(self):
        rig = Rig(budget=9216)
        out = rig.capture.capture_and_process_once()
        self.assertTrue(out.worker_accepted)
        self.assertIsNone(rig.image.resized_to)
        self.assertEqual(rig.capture.status()["worker_resizes"], 0)

    def test_capture_only_does_not_resize_or_call_worker(self):
        rig = Rig(budget=4096)
        result = rig.capture.capture_once()
        self.assertTrue(result.admitted)
        self.assertEqual(rig.capture.status()["worker_resizes"], 0)
        self.assertEqual(len(rig.vision_calls), 0)
        self.assertIsNone(rig.image.resized_to)
        self.assertFalse(rig.vision.acknowledge_worker_stopped(
            result.lease, worker_stopped=True, succeeded=False,
        ))
        self.assertFalse(rig.vision.status()["inflight"])

    def test_accepts_matching_worker_geometry_packet(self):
        def report(frame):
            packet = VisualPacket(
                frame.captured_ms, frame.width, frame.height,
                (VisualFinding("hud_change", "hud", 0.91),),
            )
            return WorkerReport(True, True, packet)
        rig = Rig(worker=report, budget=4096)
        result = rig.capture.capture_and_process_once()
        self.assertTrue(result.worker_accepted)
        self.assertEqual(result.perception.width, 64)
        self.assertFalse(rig.vision.status()["inflight"])

    def test_rejects_packet_using_native_instead_of_worker_geometry(self):
        def report(frame):
            packet = VisualPacket(
                frame.captured_ms, frame.source_width, frame.source_height,
                (VisualFinding("hud_change", "hud", 0.91),),
            )
            return WorkerReport(True, True, packet)
        rig = Rig(worker=report, budget=4096)
        result = rig.capture.capture_and_process_once()
        self.assertEqual(result.state, "worker_result_discarded")
        self.assertFalse(result.worker_accepted)
        self.assertIsNone(result.perception)
        self.assertFalse(rig.vision.status()["inflight"])

    def test_no_more_resizes_when_still_image_is_rejected_as_duplicate(self):
        rig = Rig(budget=4096)
        self.assertTrue(rig.capture.capture_and_process_once().worker_accepted)
        rig.now[0] += 1200
        again = rig.capture.capture_and_process_once()
        self.assertFalse(again.worker_invoked)
        self.assertEqual(rig.capture.status()["worker_resizes"], 1)

    def test_resize_failure_does_not_expose_backend_diagnostics_or_poison_lease(self):
        rig = Rig(budget=4096, image=FakeImage(faulty=True))
        out = rig.capture.capture_and_process_once()
        self.assertEqual(out.state, "not_admitted")
        self.assertEqual(out.admission.reason, "window_capture_backend_failed")
        self.assertNotIn("private", repr(out))
        self.assertFalse(rig.vision.status()["inflight"])

    def test_failed_downscale_returns_lease_to_scheduler(self):
        image = FakeImage()
        rig = Rig(budget=4096, image=image)
        def bad_resize(_size):
            return FakeImage(width=64, height=64, faulty=True)
        image.resize = bad_resize
        result = rig.capture.capture_and_process_once()
        self.assertEqual(result.admission.reason, "window_capture_backend_failed")
        self.assertFalse(rig.vision.status()["inflight"])
        self.assertEqual(len(rig.vision_calls), 0)
        self.assertTrue(image.closed)

    def test_slow_resize_discarded_before_worker_and_releases_lease(self):
        image = FakeImage()
        old_resize = image.resize
        rig = Rig(budget=4096, image=image)
        def slow_resize(size):
            rig.now[0] += 1600
            return old_resize(size)
        image.resize = slow_resize
        result = rig.capture.capture_and_process_once()
        self.assertEqual(result.state, "worker_resize_stale")
        self.assertEqual(len(rig.vision_calls), 0)
        self.assertFalse(rig.vision.status()["inflight"])

    def test_explicit_worker_nontermination_keeps_quarantine(self):
        rig = Rig(budget=4096, worker=lambda _: WorkerReport(False, False))
        result = rig.capture.capture_and_process_once()
        self.assertEqual(result.state, "worker_stop_unconfirmed")
        self.assertTrue(rig.vision.status()["inflight"])


if __name__ == "__main__":
    unittest.main()
