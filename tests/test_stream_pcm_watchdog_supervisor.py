"""Offline PCM watchdog testing. Never starts real audio, games, OBS or network."""

from __future__ import annotations

from threading import Event
import unittest

from tests.test_stream_preplay_pcm_bridge import PCMBridgeTests
from star.stream_pcm_watchdog_supervisor import StreamPCMWatchdogSupervisor
from star.stream_preplay_pcm_bridge import StreamPreplayPCMBridge


class PCMWatchdogSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the verified three-way director/voice/OBS host fixture.
        self.fixture = PCMBridgeTests("test_disabled_by_default_and_owner_opt_in")
        self.fixture.setUp()
        self.now = 12.06
        self.triggered = Event()
        self.fixture.bridge = StreamPreplayPCMBridge(
            self.fixture.gate,
            self.fixture.sink,
            max_turn_wall_ms=1000,
        )
        self.bridge = self.fixture.bridge
        self.supervisor = StreamPCMWatchdogSupervisor(
            self.bridge,
            clock=lambda: self.now,
            interval_s=0.01,
            on_trip=self.triggered.set,
        )

    def tearDown(self) -> None:
        self.supervisor.stop()

    def _start(self) -> None:
        self.bridge.enable(owner_approved=True)
        self.supervisor.start(owner_approved=True)

    def _admit(self) -> None:
        self.assertEqual(
            self.supervisor.admit(
                self.fixture.review,
                epoch="voice1",
                independently_quiet=True,
            ).state,
            "ready",
        )

    def test_opt_in_owner_and_idempotent_lifecycle(self) -> None:
        with self.assertRaises(PermissionError):
            self.supervisor.start()
        with self.assertRaises(RuntimeError):
            self.supervisor.start(owner_approved=True)
        self._start()
        with self.assertRaises(RuntimeError):
            self.supervisor.start(owner_approved=True)
        state = self.supervisor.health()
        self.assertTrue(state.running)
        self.assertFalse(state.permits_broadcast)
        self.assertFalse(state.verifies_physical_silence)
        self.assertGreater(state.polls, 0)

    def test_frozen_tts_triggers_stop_without_any_pcm_callback(self) -> None:
        self._start()
        self._admit()
        self.now = 13.07
        self.assertTrue(self.triggered.wait(0.8))
        self.assertFalse(self.supervisor.metrics().running)
        self.assertTrue(self.supervisor.metrics().revoked)
        self.assertEqual(self.fixture.speaker.stops, 1)
        self.assertTrue(self.bridge.metrics()["stop_outstanding"])
        self.assertEqual(self.bridge.metrics()["spoken_completions"], 0)
        self.assertEqual(self.bridge.metrics()["turn_wallclock_watchdog_stops"], 1)
        with self.assertRaises(RuntimeError):
            self.supervisor.admit(self.fixture.review, epoch="voice2", independently_quiet=True)

    def test_submit_checks_deadline_before_worker_tick(self) -> None:
        self._start()
        self._admit()
        self.now = 13.07
        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            self.supervisor.submit(self.fixture.intent, epoch="voice1", pcm16=b"\x01\x00" * 40)
        self.assertEqual(self.fixture.speaker.stops, 1)
        self.assertEqual(self.bridge.metrics()["spoken_completions"], 0)

    def test_normal_pcm_stop_does_not_falsely_count_spoken(self) -> None:
        self._start()
        self._admit()
        self.assertTrue(self.supervisor.submit(self.fixture.intent, epoch="voice1", pcm16=b"\x01\x00" * 200))
        state = self.supervisor.metrics()
        self.assertEqual((state.admitted, state.submitted), (1, 1))
        self.assertEqual(self.supervisor.stop().state, "stop_requested")
        self.assertEqual(self.fixture.speaker.stops, 1)
        self.assertTrue(self.bridge.metrics()["stop_outstanding"])
        self.assertEqual(self.bridge.metrics()["spoken_completions"], 0)

    def test_clock_nan_fails_closed(self) -> None:
        self._start()
        self._admit()
        self.now = float("nan")
        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            self.supervisor.health()
        self.assertEqual(self.fixture.speaker.stops, 1)
        self.assertTrue(self.triggered.is_set())
        self.assertFalse(self.supervisor.metrics().running)

    def test_reversed_clock_before_admission_fails_closed(self) -> None:
        self._start()
        self.supervisor.health()
        self.now = 11.5
        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            self.supervisor.health()
        self.assertTrue(self.supervisor.metrics().revoked)
        self.assertEqual(self.fixture.speaker.stops, 0)

    def test_native_stop_failure_never_fakes_silence(self) -> None:
        self._start()
        self._admit()
        self.fixture.speaker.fail_stop = True
        self.now = 13.07
        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            self.supervisor.health()
        self.assertTrue(self.bridge.metrics()["faulted"])
        self.assertEqual(self.fixture.speaker.stops, 1)
        self.assertFalse(self.supervisor.metrics().verifies_physical_silence)

    def test_diagnostic_callback_error_cannot_resume_pcm(self) -> None:
        self.supervisor = StreamPCMWatchdogSupervisor(
            self.bridge,
            clock=lambda: self.now,
            interval_s=0.01,
            on_trip=lambda: (_ for _ in ()).throw(OSError("reporter unavailable")),
        )
        self._start()
        self._admit()
        self.now = 13.07
        with self.assertRaises(RuntimeError):
            self.supervisor.health()
        self.assertTrue(self.supervisor.metrics().notification_failed)
        self.assertTrue(self.bridge.metrics()["stop_outstanding"])
        self.assertEqual(self.fixture.speaker.stops, 1)

    def test_wrong_epoch_and_odd_pcm_remain_rejected(self) -> None:
        self._start()
        self._admit()
        self.assertFalse(self.supervisor.submit(self.fixture.intent, epoch="wrong", pcm16=b"\x01\x00" * 100))
        self.assertFalse(self.supervisor.submit(self.fixture.intent, epoch="voice1", pcm16=b"bad"))
        self.assertEqual(self.supervisor.metrics().submitted, 0)
        self.assertEqual(self.bridge.metrics()["spoken_completions"], 0)
        self.assertTrue(self.supervisor.metrics().running)


if __name__ == "__main__":
    unittest.main()
