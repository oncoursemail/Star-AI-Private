"""Deterministic host-only tests for the fast-game cognition bridge.

These tests never load a neural model, inject keys, open a game or start OBS.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest

from star.game_action_gate import (
    ActionPermit, GameActionGate, GameActionHint, GameFrame, GameScope,
)
from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.stream_budget import StreamTelemetry


SCOPE = GameScope("sim_obby", "v3", "episode_1")
DIGEST = "a" * 64


def sample(*, live=False, fps=60, backlog=0, active=True):
    return StreamTelemetry(live, active, 4000, 8192, fps, backlog)


def frame(seq=1, captured=1000, **kwargs):
    arguments = dict(
        scope=SCOPE, sequence=seq, captured_ms=captured,
        evidence_sha256=DIGEST, focus_confirmed=True, playable=True,
        perception_confidence=0.95,
    )
    return GameFrame(**{**arguments, **kwargs})


def hint(scene, *, action="jump", digest=None):
    return GameActionHint(
        action_id=action, frame_sequence=scene.sequence,
        frame_sha256=digest or scene.evidence_sha256,
        proposed_ms=scene.captured_ms + 15, hold_ms=70,
    )


def start(*, warm=True, device="cpu"):
    loop = RealtimeGameLoop(
        router=GameDeadlineRouter(minimum_samples=5, reactive_device=device),
    )
    loop.start(SCOPE, ("jump", "left"), owner_approved=True)
    if warm:
        for index in range(1, 6):
            assert loop.record_reactive_latency(
                sample_id=index, duration_ms=60,
                sample_host_ms=100 * index,
                host_measured=True,
            )
    return loop


def offer(loop, scene=None, now=1100, **kwargs):
    args = dict(now_ms=now, host_verified=True, telemetry=sample())
    args.update(kwargs)
    return loop.offer(scene or frame(), **args)


def finish(loop, lease, scene, now=1200, **kwargs):
    args = dict(now_ms=now, host_verified=True, telemetry=sample())
    args.update(kwargs)
    return loop.finish(lease, scene, hint(scene), **args)


class TestRealtimeGameLoop(unittest.TestCase):
    def test_requires_owner_opt_in(self):
        loop = RealtimeGameLoop()
        with self.assertRaises(PermissionError):
            loop.start(SCOPE, ["jump"])
        self.assertEqual(offer(loop).reason, "disabled_or_wrong_game_session")

    def test_end_to_end_advisory_with_final_identity_claim_and_release(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        self.assertEqual(lease.route, "reactive")
        self.assertFalse(lease.authorizes_model_launch)
        self.assertFalse(lease.authorized_to_play)
        permit = finish(loop, lease, scene)
        self.assertTrue(permit.offered)
        self.assertFalse(permit.authorized_to_press_keys)
        self.assertFalse(loop.claim(permit, now_ms=1205))
        self.assertTrue(loop.claim(
            permit, now_ms=1210, host_focus_and_permission=True))
        self.assertFalse(loop.claim(
            permit, now_ms=1211, host_focus_and_permission=True))
        self.assertFalse(loop.release(permit, now_ms=1220))
        self.assertTrue(loop.release(
            permit, now_ms=1220, host_confirmed_released=True))
        self.assertFalse(loop.release(
            permit, now_ms=1221, host_confirmed_released=True))
        self.assertEqual(loop.metrics()["released"], 1)

    def test_untrained_profile_does_not_launch_an_unmeasured_model(self):
        loop = start(warm=False)
        self.assertEqual(
            offer(loop).reason, "insufficient_recent_latency_samples")

    def test_timings_require_host_attestation(self):
        loop = start(warm=False)
        self.assertFalse(loop.record_reactive_latency(
            sample_id=1, duration_ms=10, sample_host_ms=100,
            host_measured=False,
        ))
        self.assertEqual(
            offer(loop).reason, "insufficient_recent_latency_samples")

    def test_stale_model_return_is_rejected_after_new_scene(self):
        loop = start()
        first = frame()
        old_lease = offer(loop, first)
        later = frame(seq=2, captured=1120)
        new_lease = offer(
            loop, later, now=1180, previous_worker_stopped=True,
        )
        self.assertEqual(new_lease.route, "reactive")
        old = finish(loop, old_lease, first, now=1200)
        self.assertFalse(old.offered)
        self.assertEqual(old.reason, "unknown_superseded_or_consumed_lease")
        permit = finish(loop, new_lease, later, now=1250)
        self.assertTrue(permit.offered)
        self.assertEqual(loop.metrics()["superseded"], 1)

    def test_new_bad_frame_invalidates_prior_model_work(self):
        loop = start()
        first = frame()
        lease = offer(loop, first)
        self.assertEqual(offer(
            loop, frame(seq=2, captured=1120, focus_confirmed=False),
            now=1170, previous_worker_stopped=True,
        ).reason, "game_unfocused_or_in_menu")
        self.assertFalse(finish(loop, lease, first, now=1180).offered)

    def test_second_worker_requires_real_first_worker_cancellation(self):
        loop = start()
        first = frame()
        prior = offer(loop, first)
        second = frame(seq=2, captured=1120)
        blocked = offer(loop, second, now=1180)
        self.assertEqual(blocked.reason, "previous_inference_worker_not_stopped")
        self.assertFalse(finish(loop, prior, first, now=1200).offered)
        # After host-confirmed cancellation, a NEW observation can be used.
        third = frame(seq=3, captured=1220)
        new = offer(
            loop, third, now=1270, previous_worker_stopped=True,
        )
        self.assertEqual(new.route, "reactive")
        self.assertTrue(finish(loop, new, third, now=1340).offered)

    def test_unverified_scene_cannot_invalidate_valid_model_work(self):
        loop = start()
        first = frame()
        lease = offer(loop, first)
        self.assertEqual(offer(
            loop, frame(seq=2, captured=1120),
            now=1150, host_verified=False,
        ).reason, "trusted_observation_missing")
        self.assertTrue(finish(loop, lease, first, now=1200).offered)

    def test_repeated_frame_and_same_capture_time_rejected(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        self.assertEqual(lease.route, "reactive")
        self.assertEqual(offer(loop, scene).reason, "stale_or_replayed_scene")
        self.assertEqual(offer(
            loop, frame(seq=2, captured=1000),
        ).reason, "stale_or_replayed_scene")
        # Duplicate reads must not kill the original in-flight computation.
        self.assertTrue(finish(loop, lease, scene, now=1200).offered)

    def test_finish_requires_same_trusted_frame_object(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        clone = replace(scene)
        permit = finish(loop, lease, clone)
        self.assertEqual(permit.reason, "unknown_superseded_or_consumed_lease")
        self.assertTrue(finish(loop, lease, scene, now=1200).offered)

    def test_forged_or_replayed_lease_never_reaches_action_gate(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        fake = replace(lease)
        self.assertFalse(finish(loop, fake, scene).offered)
        permit = finish(loop, lease, scene, now=1200)
        self.assertTrue(permit.offered)
        replay = finish(loop, lease, scene, now=1201)
        self.assertFalse(replay.offered)
        self.assertEqual(replay.reason, "unknown_superseded_or_consumed_lease")
        copied_permit = replace(permit)
        self.assertFalse(loop.claim(
            copied_permit, now_ms=1202, host_focus_and_permission=True))
        self.assertFalse(loop.release(
            copied_permit, now_ms=1202, host_confirmed_released=True))
        self.assertTrue(loop.release(
            permit, now_ms=1204, host_confirmed_released=True))

    def test_completed_inference_must_not_pay_its_p95_cost_twice(self):
        # Admission already budgeted p95=60ms. The actual worker finishes
        # before its scene lease expires, even though there is no longer
        # enough time left to run a SECOND 60ms inference. The completed
        # result should still be eligible for the independent action gate.
        loop = start()
        scene = frame()
        lease = offer(loop, scene, now=1100)
        self.assertEqual(lease.route, "reactive")
        self.assertEqual(lease.expires_ms, 1310)
        permit = finish(loop, lease, scene, now=1280)
        self.assertTrue(permit.offered, permit.reason)
        self.assertFalse(permit.authorized_to_press_keys)
        self.assertTrue(loop.claim(
            permit, now_ms=1285, host_focus_and_permission=True))
        self.assertTrue(loop.release(
            permit, now_ms=1290, host_confirmed_released=True))

    def test_expired_completion_is_not_offered_to_action_gate(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        self.assertEqual(finish(
            loop, lease, scene, now=1320,
        ).reason, "inference_finished_after_scene_deadline")
        self.assertFalse(finish(loop, lease, scene, now=1321).offered)

    def test_host_clock_rollback_does_not_consume_or_revive_a_lease(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        self.assertEqual(offer(
            loop, frame(seq=2, captured=1050), now=1099,
        ).reason, "host_clock_reversed")
        self.assertEqual(
            finish(loop, lease, scene, now=1099).reason,
            "host_clock_reversed",
        )
        self.assertFalse(finish(loop, lease, scene, now=1200).offered)

    def test_unverified_completion_cannot_free_an_unfinished_worker(self):
        loop = start()
        original = frame()
        lease = offer(loop, original)
        # An untrusted or premature completion was previously able to erase
        # the lease and admit a second inference worker without a stop proof.
        self.assertEqual(
            finish(loop, lease, original, now=1200, host_verified=False).reason,
            "trusted_completion_missing",
        )
        self.assertTrue(loop.metrics()["worker_stop_pending"])
        self.assertEqual(
            offer(loop, frame(seq=2, captured=1250), now=1300).reason,
            "previous_inference_worker_not_stopped",
        )
        self.assertFalse(loop.acknowledge_worker_stopped())
        self.assertTrue(loop.acknowledge_worker_stopped(
            host_confirmed_stopped=True))
        self.assertEqual(
            offer(loop, frame(seq=3, captured=1350), now=1400).route,
            "reactive",
        )

    def test_clock_reversed_completion_requires_verified_worker_stop(self):
        loop = start()
        original = frame()
        lease = offer(loop, original)
        self.assertEqual(
            finish(loop, lease, original, now=1099).reason,
            "host_clock_reversed",
        )
        self.assertTrue(loop.metrics()["worker_stop_pending"])
        loop.stop()
        with self.assertRaises(RuntimeError):
            loop.start(SCOPE, ("jump",), owner_approved=True)
        self.assertTrue(loop.acknowledge_worker_stopped(
            host_confirmed_stopped=True))
        loop.start(SCOPE, ("jump",), owner_approved=True)

    def test_verified_failed_completion_does_not_leave_phantom_worker(self):
        loop = start()
        original = frame()
        lease = offer(loop, original)
        self.assertEqual(
            finish(loop, lease, original, cpu_pressure=True).reason,
            "hardware_pressure",
        )
        self.assertFalse(loop.metrics()["worker_stop_pending"])
        self.assertEqual(
            offer(loop, frame(seq=2, captured=1250), now=1300).route,
            "reactive",
        )

    def test_fast_route_rechecked_after_model_under_new_cpu_pressure(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        permit = finish(loop, lease, scene, cpu_pressure=True)
        self.assertEqual(permit.reason, "hardware_pressure")
        self.assertEqual(loop.metrics()["finished"], 0)

    def test_stream_state_conflict_fails_closed_at_both_boundaries(self):
        loop = start()
        scene = frame()
        self.assertEqual(offer(
            loop, scene, telemetry=sample(live=True), stream_live=False,
        ).reason, "stream_state_conflict")
        next_scene = frame(seq=2, captured=1100)
        lease = offer(loop, next_scene, now=1150)
        self.assertEqual(lease.route, "reactive")
        self.assertEqual(finish(
            loop, lease, next_scene, now=1220,
            telemetry=sample(live=True), stream_live=False,
        ).reason, "stream_state_conflict")

    def test_bad_game_and_voice_telemetry_blocks_unnecessary_inference(self):
        for t in (
            sample(fps=29), sample(backlog=351), sample(active=False),
        ):
            loop = start()
            self.assertEqual(offer(loop, telemetry=t).route, "skip")
            self.assertEqual(loop.metrics()["offered"], 0)

    def test_comparison_only_accepts_host_bound_model_output(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        wrong = loop.finish(
            lease, scene, hint(scene, digest="b" * 64),
            now_ms=1200, host_verified=True, telemetry=sample(),
        )
        self.assertEqual(wrong.reason, "proposal_not_bound_to_frame")
        self.assertFalse(loop.claim(
            ActionPermit(True, "fake", 1), now_ms=1201,
            host_focus_and_permission=True,
        ))

    def test_pending_key_release_prevents_second_inference_and_restart(self):
        loop = start()
        scene = frame()
        permit = finish(loop, offer(loop, scene), scene)
        self.assertTrue(permit.offered)
        self.assertEqual(offer(
            loop, frame(seq=2, captured=1250), now=1280,
        ).reason, "pending_host_key_release")
        loop.stop()
        with self.assertRaises(RuntimeError):
            loop.start(SCOPE, ["jump"], owner_approved=True)
        self.assertTrue(loop.release(
            permit, now_ms=1300, host_confirmed_released=True))
        loop.start(SCOPE, ["jump"], owner_approved=True)

    def test_stopped_session_invalidates_old_model_work(self):
        loop = start()
        scene = frame()
        lease = offer(loop, scene)
        loop.stop()
        self.assertFalse(finish(loop, lease, scene).offered)
        self.assertFalse(loop.record_reactive_latency(
            sample_id=7, duration_ms=10, sample_host_ms=900,
            host_measured=True,
        ))

    def test_malformed_inputs_do_not_advance_trusted_sequence(self):
        loop = start()
        scene = frame()
        with self.assertRaises(ValueError):
            offer(loop, scene, host_verified=1)
        with self.assertRaises(ValueError):
            offer(loop, scene, now=float("nan"))
        with self.assertRaises(TypeError):
            offer(loop, scene, telemetry="fake")
        self.assertEqual(offer(loop, scene).route, "reactive")

    def test_concurrent_duplicate_scene_gets_one_lease(self):
        loop = start()
        scene = frame()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: offer(loop, scene), range(16),
            ))
        self.assertEqual(sum(r.route == "reactive" for r in results), 1)
        self.assertEqual(loop.metrics()["offered"], 1)

    def test_slow_fast_model_must_stay_out_of_live_loop(self):
        loop = RealtimeGameLoop(
            router=GameDeadlineRouter(minimum_samples=5),
            action_gate=GameActionGate(frame_max_age_ms=350),
        )
        loop.start(SCOPE, ["jump"], owner_approved=True)
        for i in range(1, 6):
            self.assertTrue(loop.record_reactive_latency(
                sample_id=i, duration_ms=250, sample_host_ms=i * 100,
                host_measured=True,
            ))
        self.assertEqual(
            offer(loop, frame(), now=1100).reason,
            "reactive_p95_exceeds_scene_slack",
        )


    def test_superseded_worker_remains_quarantined_across_multiple_frames(self):
        loop = start()
        oldest = frame()
        old_lease = offer(loop, oldest)
        self.assertEqual(old_lease.route, "reactive")
        second = frame(seq=2, captured=1150)
        self.assertEqual(
            offer(loop, second, now=1200).reason,
            "previous_inference_worker_not_stopped",
        )
        # This third observation used to forget the old worker's existence
        # because the second observation cleared _lease.
        third = frame(seq=3, captured=1250)
        self.assertEqual(
            offer(loop, third, now=1300).reason,
            "previous_inference_worker_not_stopped",
        )
        self.assertTrue(loop.metrics()["worker_stop_pending"])
        self.assertFalse(finish(loop, old_lease, oldest, now=1320).offered)
        fourth = frame(seq=4, captured=1350)
        self.assertEqual(
            offer(loop, fourth, now=1400,
                  previous_worker_stopped=True).route, "reactive",
        )
        self.assertFalse(loop.metrics()["worker_stop_pending"])

    def test_stop_preserves_worker_quarantine_until_host_ack(self):
        loop = start()
        lease = offer(loop)
        self.assertEqual(lease.route, "reactive")
        loop.stop()
        self.assertTrue(loop.metrics()["worker_stop_pending"])
        with self.assertRaises(RuntimeError):
            loop.start(SCOPE, ["jump"], owner_approved=True)
        self.assertFalse(loop.acknowledge_worker_stopped())
        self.assertFalse(loop.acknowledge_worker_stopped(
            host_confirmed_stopped=False))
        self.assertTrue(loop.acknowledge_worker_stopped(
            host_confirmed_stopped=True))
        self.assertFalse(loop.acknowledge_worker_stopped(
            host_confirmed_stopped=True))
        loop.start(SCOPE, ["jump"], owner_approved=True)

    def test_worker_quarantine_survives_burst_of_new_game_frames(self):
        loop = start()
        self.assertEqual(offer(loop).route, "reactive")
        for sequence in range(2, 130):
            capture = 1000 + (sequence - 1) * 90
            decision = offer(
                loop, frame(seq=sequence, captured=capture),
                now=capture + 50,
            )
            self.assertEqual(
                decision.reason, "previous_inference_worker_not_stopped",
            )
        self.assertTrue(loop.metrics()["worker_stop_pending"])
        with self.assertRaises(ValueError):
            loop.acknowledge_worker_stopped(host_confirmed_stopped=1)
        self.assertTrue(loop.acknowledge_worker_stopped(
            host_confirmed_stopped=True))
        capture = 1000 + 129 * 90
        self.assertEqual(
            offer(loop, frame(seq=130, captured=capture),
                  now=capture + 50).route,
            "reactive",
        )

    def test_unverified_new_frame_cannot_claim_worker_stop(self):
        loop = start()
        offer(loop)
        stale = frame(seq=2, captured=1150)
        self.assertEqual(offer(loop, stale, now=1200).route, "skip")
        self.assertEqual(
            offer(loop, frame(seq=3, captured=1250), now=1300,
                  host_verified=False, previous_worker_stopped=True).reason,
            "trusted_observation_missing",
        )
        self.assertTrue(loop.metrics()["worker_stop_pending"])
        self.assertEqual(
            offer(loop, frame(seq=3, captured=1250), now=1300).reason,
            "previous_inference_worker_not_stopped",
        )



if __name__ == "__main__":
    unittest.main()
