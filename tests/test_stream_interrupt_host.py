"""Adversarial, offline tests for playback epoch-scoped Star VTuber barge-in."""
from __future__ import annotations

import unittest

from star.stream_director import StreamSignal
from star.stream_interrupt_host import StreamInterruptionHost
from star.stream_stage import StarStage
from star.stream_turntaking import TurnTakingGate, VoiceFrame


class FakeAvatar:
    def __init__(self):
        self.connected = True
        self.calls = []
        self.closed = False
        self.reset_ok = True
        self.raise_reset = False

    def send_neutral(self, plan, *, playback_epoch, playback_stopped=False):
        self.calls.append((plan, playback_epoch, playback_stopped))
        if self.raise_reset:
            raise OSError("simulated renderer loss")
        return self.reset_ok

    def close(self):
        self.closed = True
        self.connected = False


class Rig(unittest.TestCase):
    def setUp(self):
        self.now = 100000.0
        self.stage = StarStage(clock=lambda: self.now / 1000)
        self.stage.enable(owner_approved=True, mode="cat")
        self.turns = TurnTakingGate()
        self.avatar = FakeAvatar()
        self.stop_calls = []
        self.flush_calls = []
        self.stop_ok = True
        self.flush_ok = True
        self.delay_ms = 0
        self.stop_raises = False
        self.flush_raises = False

        self.stage.offer(
            StreamSignal("evt1", "game_success", 100.0, "Verified round completed",
                         evidence="observed"), now=100.0,
        )
        self.plan = self.stage.prepare(now=100.0)
        assert self.plan is not None
        assert self.stage.queue_audio(self.plan, now=100.0)
        assert self.stage.acknowledge_audible(self.plan, now=100.0)

        self.host = self.make_host()

    def stop(self, epoch):
        self.stop_calls.append(epoch)
        self.now += self.delay_ms
        if self.stop_raises:
            raise OSError("device unavailable")
        return self.stop_ok

    def flush(self, epoch):
        self.flush_calls.append(epoch)
        if self.flush_raises:
            raise OSError("queue unavailable")
        return self.flush_ok

    def make_host(self, *, avatar=True, **kwargs):
        return StreamInterruptionHost(
            stage=self.stage, turns=self.turns,
            stop_epoch=self.stop, flush_animation=self.flush,
            avatar=self.avatar if avatar else None,
            clock_ms=lambda: self.now, owner_approved=True, **kwargs,
        )

    def arm(self):
        self.host.enable(owner_approved=True)
        self.assertFalse(self.host.arm(self.plan, playback_epoch="test-epoch-A"))
        self.assertEqual(self.host.observe(
            VoiceFrame(self.now, 30, 0, 0, True)
        ).status, "speak")
        self.assertTrue(self.host.arm(self.plan, playback_epoch="test-epoch-A"))

    def voice(self, at, *, owner=0, guest=0, echo=True):
        self.now = float(at)
        return self.host.observe(VoiceFrame(
            self.now, 30.0, float(owner), float(guest), echo,
        ))

    def barge(self, *, owner=1, guest=0, echo=True):
        result = None
        for at in (100030, 100060, 100090, 100120):
            result = self.voice(at, owner=owner, guest=guest, echo=echo)
        return result

    def test_opt_in_and_invalid_ports_rejected(self):
        with self.assertRaises(PermissionError):
            StreamInterruptionHost(
                stage=self.stage, turns=self.turns,
                stop_epoch=self.stop, flush_animation=self.flush,
            )
        with self.assertRaises(TypeError):
            StreamInterruptionHost(
                stage=self.stage, turns=self.turns,
                stop_epoch=object(), flush_animation=self.flush, owner_approved=True,
            )
        with self.assertRaises(ValueError):
            self.make_host(maximum_stop_ms=float("nan"))
        with self.assertRaises(ValueError):
            self.make_host(maximum_stop_ms=501)
        with self.assertRaises(PermissionError):
            self.host.enable()
        self.assertEqual(self.host.observe(
            VoiceFrame(100000, 30, 0, 0, True)
        ).status, "disabled")
        self.assertFalse(self.host.arm(self.plan, playback_epoch="test-epoch-A"))
        self.assertTrue(self.stage.current(self.plan))

    def test_arm_only_audible_plan_bounded_epoch_and_connected_avatar(self):
        self.host.enable(owner_approved=True)
        self.host.observe(VoiceFrame(self.now, 30, 0, 0, True))
        for invalid in ("", "../evil", "x" * 65, "\n", "id:bad", 123):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.host.arm(self.plan, playback_epoch=invalid)
        self.avatar.connected = False
        self.assertFalse(self.host.arm(self.plan, playback_epoch="test-epoch-A"))
        self.avatar.connected = True
        self.assertTrue(self.host.arm(self.plan, playback_epoch="test-epoch-A"))
        self.assertFalse(self.host.arm(self.plan, playback_epoch="another-epoch"))
        self.assertEqual(self.host.metrics()["armed"], 1)

    def test_no_speech_can_arm_while_guest_or_owner_is_talking(self):
        self.host.enable(owner_approved=True)
        # Confirmed guest speech means the stage must wait rather than talk over.
        for at in (100000, 100030, 100060, 100090):
            self.voice(at, guest=1)
        self.assertFalse(self.host.arm(self.plan, playback_epoch="test-epoch-A"))
        # A long quiet window eventually releases the floor.
        self.voice(100500)
        self.assertTrue(self.host.arm(self.plan, playback_epoch="test-epoch-A"))

    def test_non_owner_silence_and_single_spike_do_not_stop_audio(self):
        self.arm()
        self.assertEqual(self.voice(100030).status, "speak")
        self.assertEqual(self.voice(100060, owner=1).status, "hold")
        self.assertEqual(self.voice(100090).status, "hold")
        self.assertEqual(self.stop_calls, [])
        self.assertEqual(self.avatar.calls, [])
        self.assertTrue(self.stage.current(self.plan))

    def test_guest_voice_cannot_interrupt(self):
        self.arm()
        self.assertEqual(self.barge(owner=0, guest=1).status, "hold")
        self.assertTrue(self.stage.current(self.plan))
        self.assertEqual(self.stop_calls, [])

    def test_echo_uncleared_cannot_interrupt(self):
        self.arm()
        self.assertEqual(self.barge(owner=1, echo=False).status, "hold")
        self.assertEqual(self.stop_calls, [])

    def test_barge_in_stops_audio_then_flushes_then_neutralizes(self):
        self.arm()
        result = self.barge()
        self.assertEqual(result.status, "interrupted")
        self.assertTrue(result.audio_stopped)
        self.assertTrue(result.avatar_reset)
        self.assertEqual(result.stop_latency_ms, 0.0)
        self.assertEqual(self.stop_calls, ["test-epoch-A"])
        self.assertEqual(self.flush_calls, ["test-epoch-A"])
        self.assertEqual(self.avatar.calls, [(self.plan, "test-epoch-A", True)])
        self.assertFalse(self.stage.current(self.plan))
        self.assertFalse(self.stage.finish(self.plan, played_to_end=True))
        self.assertEqual(self.stage.metrics()["director"]["completed"], 0)
        self.assertEqual(self.host.metrics()["interruptions"], 1)
        self.assertNotIn("test-epoch-A", str(self.host.metrics()))
        # Further VAD cannot stop the same epoch twice.
        self.assertNotEqual(self.voice(100150, owner=1).status, "interrupted")
        self.assertEqual(len(self.stop_calls), 1)

    def test_stale_voice_cannot_interrupt(self):
        self.arm()
        # Evidence from an older VAD stream is more than 250ms old.
        self.now = 100500.0
        for at in (100030, 100060, 100090, 100120):
            self.host.observe(VoiceFrame(at, 30, 1, 0, True))
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(self.stage.current(self.plan))

    def test_duplicate_overlap_or_future_frame_rejected_without_stop(self):
        self.arm()
        self.voice(100030, owner=1)
        with self.assertRaises(ValueError):
            self.host.observe(VoiceFrame(100030, 30, 1, 0, True))
        with self.assertRaises(ValueError):
            self.host.observe(VoiceFrame(100090, 30, 1, 0, True))
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(self.stage.current(self.plan))

    def test_device_stop_failure_latches_fault_and_never_claims_reset(self):
        self.arm()
        self.stop_ok = False
        report = self.barge()
        self.assertEqual(report.status, "fault")
        self.assertFalse(report.audio_stopped)
        self.assertFalse(report.avatar_reset)
        self.assertFalse(self.stage.current(self.plan))
        self.assertEqual(len(self.flush_calls), 1)
        self.assertEqual(self.avatar.calls, [])
        self.assertTrue(self.avatar.closed)
        self.assertTrue(self.host.metrics()["fault"])
        self.assertFalse(self.host.arm(self.plan, playback_epoch="second-epoch"))
        with self.assertRaises(RuntimeError):
            self.host.enable(owner_approved=True)

    def test_stop_exception_is_fail_closed(self):
        self.arm()
        self.stop_raises = True
        self.assertEqual(self.barge().status, "fault")
        self.assertTrue(self.host.metrics()["fault"])
        self.assertEqual(self.host.metrics()["stop_failures"], 1)

    def test_flush_failure_never_claims_neutral_rig(self):
        self.arm()
        self.flush_ok = False
        result = self.barge()
        self.assertEqual(result.status, "fault")
        self.assertTrue(result.audio_stopped)
        self.assertFalse(result.avatar_reset)
        self.assertEqual(self.avatar.calls, [])
        self.assertTrue(self.avatar.closed)

    def test_flush_exception_is_fail_closed(self):
        self.arm()
        self.flush_raises = True
        self.assertEqual(self.barge().status, "fault")
        self.assertTrue(self.avatar.closed)

    def test_vtube_studio_reset_error_blocks_new_turn(self):
        self.arm()
        self.avatar.raise_reset = True
        result = self.barge()
        self.assertEqual(result.status, "fault")
        self.assertFalse(result.avatar_reset)
        self.assertTrue(self.avatar.closed)
        self.assertTrue(self.host.metrics()["fault"])

    def test_slow_stop_completes_cleanup_but_latches_latency_fault(self):
        self.arm()
        self.delay_ms = 150
        result = self.barge()
        self.assertEqual(result.status, "fault")
        self.assertEqual(result.stop_latency_ms, 150)
        self.assertTrue(result.audio_stopped)
        self.assertEqual(len(self.avatar.calls), 1)
        self.assertEqual(self.host.metrics()["latency_faults"], 1)

    def test_missing_avatar_allows_audio_only_recovery(self):
        self.host = self.make_host(avatar=False)
        self.arm()
        self.assertEqual(self.barge().status, "interrupted")
        self.assertEqual(self.avatar.calls, [])

    def test_atomic_revoke_does_not_interrupt_unrelated_new_turn(self):
        self.arm()
        self.assertTrue(self.stage.finish(self.plan, now=100, played_to_end=True))
        self.stage.offer(
            StreamSignal("evt2", "game_danger", 100.0, "Verified obstacle", evidence="observed"),
            now=100.0,
        )
        next_plan = self.stage.prepare(now=100)
        self.assertTrue(self.stage.queue_audio(next_plan, now=100))
        self.assertTrue(self.stage.acknowledge_audible(next_plan, now=100))
        self.assertEqual(self.voice(100030, owner=1).status, "stale")
        self.assertTrue(self.stage.current(next_plan))
        self.assertEqual(self.stop_calls, [])
        self.assertIsNone(self.stage.interrupt_if_current(self.plan, now=100.03))

    def test_manual_stop_is_epoch_scoped_and_idempotent(self):
        self.arm()
        result = self.host.emergency_stop()
        self.assertEqual(result.status, "interrupted")
        self.assertEqual(result.reason, "operator_requested_stop")
        self.assertEqual(self.host.emergency_stop().status, "disabled")
        self.assertEqual(self.stop_calls, ["test-epoch-A"])

    def test_disable_stops_playback_then_revokes_vad(self):
        self.arm()
        self.assertEqual(self.host.disable().status, "interrupted")
        self.assertFalse(self.host.metrics()["enabled"])
        self.assertEqual(self.voice(100030, owner=1).status, "disabled")
        self.assertEqual(self.stop_calls, ["test-epoch-A"])

    def test_fault_recovery_requires_explicit_real_hardware_acknowledgements(self):
        self.arm()
        self.stop_ok = False
        self.barge()
        for opts in ({}, {"owner_approved": True},
                     {"owner_approved": True, "physical_audio_stopped": True}):
            with self.subTest(opts=opts), self.assertRaises(PermissionError):
                self.host.recover(**opts)
        self.host.recover(owner_approved=True, physical_audio_stopped=True,
                          avatar_neutral_or_disconnected=True)
        self.assertFalse(self.host.metrics()["fault"])
        self.assertFalse(self.host.metrics()["enabled"])
        self.assertEqual(self.stop_calls, ["test-epoch-A"])

    def test_bad_clock_and_frame_payload_never_stop_sound(self):
        self.arm()
        with self.assertRaises(TypeError):
            self.host.observe({"at_ms": 100})
        with self.assertRaises(ValueError):
            self.host.observe(VoiceFrame(100031, 30, 1, 0, True))
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(self.stage.current(self.plan))

    def test_metrics_are_bounded_counts_only(self):
        self.arm()
        self.barge()
        self.assertEqual(set(self.host.metrics()), {
            "armed", "held", "interruptions", "stop_failures", "reset_failures",
            "latency_faults", "stale", "faults", "enabled", "fault", "active",
        })
        self.assertNotIn("Verified round completed", str(self.host.metrics()))


if __name__ == "__main__":
    unittest.main()
