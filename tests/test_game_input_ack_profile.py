"""Offline OS-input-ack deadline calibration; no device or game access."""
from __future__ import annotations

import unittest

from star.game_action_gate import GameScope
from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.game_action_gate import GameFrame
from star.stream_budget import StreamTelemetry


SCOPE = "sim_obby:v2"
TRUSTED_GAME = GameScope("sim_obby", "v2", "episode_input_ack")


def new_router(*, strict: bool = True, minimum: int = 5) -> GameDeadlineRouter:
    router = GameDeadlineRouter(
        minimum_samples=minimum,
        strict_input_ack_profile=strict,
        reactive_device="cpu",
    )
    router.enable(owner_approved=True, game_scope=SCOPE)
    return router


def warm(router: GameDeadlineRouter, *, ack_ms: float = 50.0,
         ack_live: bool = False, model_live: bool = False,
         base: int = 100, start_id: int = 1, n: int = 5) -> None:
    for index in range(start_id, start_id + n):
        at = base + (index - start_id) * 100
        assert router.record_reactive_latency(
            game_scope=SCOPE, sample_id=index, duration_ms=60.0,
            sample_host_ms=at, host_measured=True, stream_live=model_live,
        )
        assert router.record_input_ack_latency(
            game_scope=SCOPE, sample_id=index, duration_ms=ack_ms,
            sample_host_ms=at, host_measured=True, stream_live=ack_live,
        )


def advise(router: GameDeadlineRouter, *, at: float = 1000,
           age: float = 100, live: bool = False,
           completed: bool = False):
    return router.advise(
        game_scope=SCOPE, game_active=True, observation_age_ms=age,
        now_host_ms=at, host_verified=True, stream_live=live,
        completed_inference=completed,
    )


class TestInputAckCalibration(unittest.TestCase):
    def test_disabled_by_default_does_not_require_input_measurements(self):
        r = new_router(strict=False)
        for i in range(1, 6):
            self.assertTrue(r.record_reactive_latency(
                game_scope=SCOPE, sample_id=i, duration_ms=60,
                sample_host_ms=100 * i, host_measured=True,
            ))
        self.assertEqual(advise(r).route, "reactive")
        self.assertFalse(r.metrics()["strict_input_ack_profile"])

    def test_strict_missing_measurements_fail_closed_even_after_model_finishes(self):
        r = new_router()
        for i in range(1, 6):
            r.record_reactive_latency(
                game_scope=SCOPE, sample_id=i, duration_ms=60,
                sample_host_ms=100 * i, host_measured=True,
            )
        self.assertEqual(
            advise(r).reason, "insufficient_recent_input_ack_latency_samples",
        )
        self.assertEqual(
            advise(r, completed=True).reason,
            "insufficient_recent_input_ack_latency_samples",
        )

    def test_fast_input_ack_passes_but_slow_input_ack_blocks_launch(self):
        good = new_router()
        warm(good, ack_ms=45)
        self.assertEqual(advise(good).route, "reactive")
        self.assertEqual(advise(good, completed=True).route, "completed")
        slow = new_router()
        warm(slow, ack_ms=230)
        self.assertEqual(
            advise(slow).reason, "reactive_p95_exceeds_scene_slack",
        )
        self.assertEqual(
            advise(slow, completed=True).reason,
            "verified_completion_fits_scene_deadline",
        )  # 250ms remaining before dispatch; 230ms ack still fits
        self.assertEqual(
            advise(slow, age=200, at=1001, completed=True).reason,
            "input_ack_p95_exceeds_scene_slack",
        )

    def test_missing_ack_is_slow_not_fast_and_repeated_measurements_rejected(self):
        r = new_router()
        warm(r, ack_ms=25)
        self.assertTrue(r.record_input_ack_latency(
            game_scope=SCOPE, sample_id=6, duration_ms=2.0,
            sample_host_ms=900, host_measured=True, completed=False,
        ))
        self.assertFalse(r.record_input_ack_latency(
            game_scope=SCOPE, sample_id=6, duration_ms=0.01,
            sample_host_ms=901, host_measured=True,
        ))
        self.assertEqual(r.metrics()["input_ack_p95_ms"], 5000.0)
        self.assertEqual(
            advise(r, at=1000).reason, "input_ack_p95_exceeds_scene_slack",
        )

    def test_wrong_scope_untrusted_and_invalid_shape_cannot_warm_route(self):
        r = new_router()
        self.assertFalse(r.record_input_ack_latency(
            game_scope="different", sample_id=1, duration_ms=10,
            sample_host_ms=100, host_measured=True,
        ))
        self.assertFalse(r.record_input_ack_latency(
            game_scope=SCOPE, sample_id=1, duration_ms=10,
            sample_host_ms=100, host_measured=False,
        ))
        for invalid in (True, float("nan"), -1, float("inf")):
            with self.assertRaises(ValueError):
                r.record_input_ack_latency(
                    game_scope=SCOPE, sample_id=1, duration_ms=invalid,
                    sample_host_ms=100, host_measured=True,
                )
        with self.assertRaises(ValueError):
            GameDeadlineRouter(strict_input_ack_profile="true")  # type: ignore[arg-type]
        self.assertEqual(r.metrics()["input_ack_samples"], 0)

    def test_live_route_cannot_borrow_idle_os_ack_latency(self):
        r = new_router()
        warm(r, ack_ms=35, ack_live=False)
        self.assertEqual(advise(r, live=True).reason,
                         "insufficient_recent_input_ack_latency_samples")
        for i in range(6, 11):
            self.assertTrue(r.record_input_ack_latency(
                game_scope=SCOPE, sample_id=i, duration_ms=40,
                sample_host_ms=500 + 100 * i, host_measured=True,
                stream_live=True,
            ))
        self.assertEqual(advise(r, at=1700, live=True).route, "reactive")

    def test_expired_ack_profile_and_episode_reset(self):
        r = new_router()
        warm(r)
        self.assertEqual(advise(r, at=1000).route, "reactive")
        self.assertEqual(advise(r, at=17_000).reason,
                         "insufficient_recent_input_ack_latency_samples")
        r.disable()
        r.enable(owner_approved=True, game_scope=SCOPE)
        self.assertEqual(r.metrics()["input_ack_samples"], 0)
        self.assertFalse(r.record_input_ack_latency(
            game_scope=SCOPE, sample_id=1, duration_ms=20,
            sample_host_ms=100, host_measured=False,
        ))

    def test_realtime_bridge_records_real_ack_in_strict_mode(self):
        router = GameDeadlineRouter(
            minimum_samples=5, strict_input_ack_profile=True,
        )
        loop = RealtimeGameLoop(router=router)
        loop.start(TRUSTED_GAME, ["jump"], owner_approved=True)
        for i in range(1, 6):
            self.assertTrue(loop.record_reactive_latency(
                sample_id=i, duration_ms=60, sample_host_ms=i * 100,
                host_measured=True,
            ))
        frame = GameFrame(
            scope=TRUSTED_GAME, sequence=1, captured_ms=1000,
            evidence_sha256="a" * 64, focus_confirmed=True,
            playable=True, perception_confidence=0.99,
        )
        stream = StreamTelemetry(False, True, 4000, 8192, 60, 0)
        self.assertEqual(loop.offer(
            frame, now_ms=1100, host_verified=True, telemetry=stream,
        ).reason, "insufficient_recent_input_ack_latency_samples")
        for i in range(1, 6):
            self.assertTrue(loop.record_input_ack_latency(
                sample_id=i, duration_ms=40, sample_host_ms=i * 100,
                host_measured=True,
            ))
        # The first offer consumes a scene, even if skipped. Use a NEW
        # independently verified observation, not a replay of the old frame.
        newer = GameFrame(
            scope=TRUSTED_GAME, sequence=2, captured_ms=1120,
            evidence_sha256="b" * 64, focus_confirmed=True,
            playable=True, perception_confidence=0.99,
        )
        self.assertEqual(loop.offer(
            newer, now_ms=1190, host_verified=True, telemetry=stream,
        ).route, "reactive")
        loop.stop()
        self.assertFalse(loop.record_input_ack_latency(
            sample_id=6, duration_ms=10,
            sample_host_ms=1300, host_measured=True,
        ))


if __name__ == "__main__":
    unittest.main()
