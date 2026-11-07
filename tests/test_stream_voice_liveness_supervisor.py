"""Offline VAD-feed loss tests; no real capture, audio, games or OBS."""
from __future__ import annotations

from threading import Event
import unittest

from star.stream_director import StreamSignal
from star.stream_interrupt_host import StreamInterruptionHost
from star.stream_stage import StarStage
from star.stream_turntaking import TurnTakingGate, VoiceFrame
from star.stream_voice_liveness_supervisor import StreamVoiceLivenessSupervisor


class TestLiveVoiceSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        self.now_ms = 100000.0
        self.stops: list[str] = []
        self.flushes: list[str] = []
        self.stop_ok = True
        self.notified = Event()
        self.stage = StarStage(clock=lambda: self.now_ms / 1000)
        self.stage.enable(owner_approved=True)
        self.assertTrue(self.stage.offer(
            StreamSignal("event", "game_success", 100, "Observed game result",
                         evidence="observed"), now=100,
        ))
        plan = self.stage.prepare(now=100)
        assert plan is not None
        self.plan = plan
        self.assertTrue(self.stage.queue_audio(plan, now=100))
        self.assertTrue(self.stage.acknowledge_audible(plan, now=100))
        self.host = StreamInterruptionHost(
            stage=self.stage, turns=TurnTakingGate(),
            stop_epoch=self._stop_audio, flush_animation=self._flush,
            clock_ms=lambda: self.now_ms, owner_approved=True,
            maximum_voice_gap_ms=200,
        )
        self.supervisor = StreamVoiceLivenessSupervisor(
            self.host, interval_s=0.02, on_lost=self.notified.set,
        )

    def tearDown(self) -> None:
        self.supervisor.stop()

    def _stop_audio(self, epoch: str) -> bool:
        self.stops.append(epoch)
        return self.stop_ok

    def _flush(self, epoch: str) -> bool:
        self.flushes.append(epoch)
        return True

    def _arm(self) -> None:
        self.host.enable(owner_approved=True, require_live_voice=True)
        self.supervisor.start(owner_approved=True)
        for now in range(100000, 100361, 30):
            self.now_ms = float(now)
            self.supervisor.observe(VoiceFrame(self.now_ms, 30, 0, 0, True))
        self.assertTrue(self.supervisor.arm(self.plan, playback_epoch="pcm-epoch"))

    def test_requires_owner_and_fresh_live_source(self) -> None:
        with self.assertRaises(PermissionError):
            self.supervisor.start()
        with self.assertRaises(RuntimeError):
            self.supervisor.start(owner_approved=True)
        self.host.enable(owner_approved=True)  # legacy mode is not strict
        with self.assertRaises(RuntimeError):
            self.supervisor.start(owner_approved=True)
        with self.assertRaises(RuntimeError):
            self.supervisor.arm(self.plan, playback_epoch="never")
        self.assertEqual(self.stops, [])

    def test_independent_tick_stops_audio_even_when_no_more_frames_arrive(self) -> None:
        self._arm()
        self.now_ms = 100561.0  # 201 ms past last authenticated VAD
        self.assertTrue(self.notified.wait(0.8))
        self.assertFalse(self.stage.current(self.plan))
        self.assertEqual(self.stops, ["pcm-epoch"])
        self.assertEqual(self.flushes, ["pcm-epoch"])
        state = self.supervisor.metrics()
        self.assertTrue(state.revoked)
        self.assertFalse(state.running)
        self.assertGreaterEqual(state.checks, 1)
        self.assertEqual(state.observed_frames, 13)
        with self.assertRaises(RuntimeError):
            self.supervisor.arm(self.plan, playback_epoch="next")
        self.assertTrue(self.host.metrics()["voice_liveness_stops"] >= 1)

    def test_disable_attempts_physical_stop_without_flagging_false_success(self) -> None:
        self._arm()
        outcome = self.supervisor.stop()
        self.assertEqual(outcome.status, "interrupted")
        self.assertTrue(outcome.audio_stopped)
        self.assertEqual(self.stops, ["pcm-epoch"])
        self.assertEqual(self.flushes, ["pcm-epoch"])
        self.assertFalse(self.supervisor.metrics().running)
        self.assertFalse(self.notified.is_set())

    def test_failed_device_stop_still_notifies_operator(self) -> None:
        self._arm()
        self.stop_ok = False
        self.now_ms = 100561
        self.assertTrue(self.notified.wait(0.8))
        self.assertTrue(self.host.metrics()["fault"])
        self.assertEqual(self.stops, ["pcm-epoch"])
        self.assertEqual(self.flushes, ["pcm-epoch"])
        self.assertFalse(self.supervisor.metrics().running)

    def test_operator_diagnostic_callback_failure_never_restores_audio(self) -> None:
        self.supervisor = StreamVoiceLivenessSupervisor(
            self.host, interval_s=0.02,
            on_lost=lambda: (_ for _ in ()).throw(OSError("reporter unavailable")),
        )
        self._arm()
        self.now_ms = 100561
        # Manual health polling ensures deterministic callback delivery.
        with self.assertRaises(RuntimeError):
            self.supervisor.health()
        self.assertTrue(self.supervisor.metrics().notification_failed)
        self.assertEqual(self.stops, ["pcm-epoch"])


    def test_invalid_replayed_voice_frame_immediately_revokes_pcm(self) -> None:
        self._arm()
        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            self.supervisor.observe(VoiceFrame(100360.0, 30, 0, 0, True))
        self.assertEqual(self.stops, ["pcm-epoch"])
        self.assertEqual(self.flushes, ["pcm-epoch"])
        self.assertTrue(self.notified.is_set())
        self.assertTrue(self.supervisor.metrics().revoked)
        self.assertFalse(self.supervisor.metrics().running)

    def test_clock_failure_during_health_check_attempts_real_audio_stop(self) -> None:
        self._arm()
        self.now_ms = float("nan")
        with self.assertRaises(RuntimeError):
            self.supervisor.health()
        self.assertEqual(self.stops, ["pcm-epoch"])
        self.assertEqual(self.flushes, ["pcm-epoch"])
        self.assertFalse(self.stage.metrics()["enabled"])
        self.assertTrue(self.notified.is_set())
        self.assertFalse(self.supervisor.metrics().running)

    def test_watchdog_probe_exception_fails_closed_synchronously(self) -> None:
        self._arm()
        self.host.tick = lambda: (_ for _ in ()).throw(OSError("probe died"))
        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            self.supervisor.health()
        self.assertEqual(self.stops, ["pcm-epoch"])
        self.assertTrue(self.notified.is_set())
        self.assertTrue(self.supervisor.metrics().revoked)


if __name__ == "__main__":
    unittest.main()
