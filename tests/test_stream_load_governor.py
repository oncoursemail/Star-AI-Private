"""Synthetic-only regression tests for the VTuber streaming load governor.

No OBS, GPU, game, TTS, Twitch, network, account or credentials are used.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from threading import Barrier
import unittest

from star.stream_load_governor import StreamLoadGovernor, StreamLoadSample


def sample(ident: str = "s1", at: float = 10.0, **changes: object) -> StreamLoadSample:
    fields: dict[str, Any] = dict(
        sample_id=ident,
        measured_at_s=at,
        game_p95_frame_ms=13.0,
        game_target_fps=60.0,
        obs_render_missed_pct=0.0,
        obs_encode_skipped_pct=0.0,
        obs_network_dropped_pct=0.0,
        gpu_vram_used_mb=3500.0,
        gpu_vram_total_mb=8192.0,
        tts_first_audio_p95_ms=150.0,
        obs_connected=True,
    )
    fields.update(changes)
    return StreamLoadSample(**fields)


def enabled(**kwargs: object) -> StreamLoadGovernor:
    governor = StreamLoadGovernor(**kwargs)
    governor.enable(owner_approved=True)
    return governor


class StreamingLoadGovernorTests(unittest.TestCase):
    def test_disabled_default_owner_approval_and_observation_only(self) -> None:
        gov = StreamLoadGovernor()
        self.assertEqual(gov.recommend(now_s=10).profile, "disabled")
        with self.assertRaises(PermissionError):
            gov.enable()
        self.assertFalse(gov.ingest(sample(), now_s=10, host_verified=True))
        self.assertEqual(gov.metrics()["accepted"], 0)
        gov.enable(owner_approved=True)
        self.assertFalse(gov.ingest(sample(), now_s=10, host_verified=False))
        self.assertEqual(gov.recommend(now_s=10).profile, "telemetry_stale")

    def test_normal_requires_multiple_fresh_samples(self) -> None:
        gov = enabled()
        for i in range(2):
            self.assertTrue(gov.ingest(sample(f"ok-{i}", at=10 + i),
                                       now_s=10 + i, host_verified=True))
            self.assertEqual(gov.recommend(now_s=10 + i).profile, "warming")
        self.assertTrue(gov.ingest(sample("ok-2", at=12), now_s=12, host_verified=True))
        advice = gov.recommend(now_s=12)
        self.assertEqual(advice.profile, "normal")
        self.assertTrue(advice.allow_optional_commentary)
        self.assertTrue(advice.pause_background_workers)
        self.assertTrue(advice.allow_extra_gpu_inference)
        self.assertGreater(advice.max_extra_gpu_vram_mb, 1024)

    def test_render_pressure_escalates_immediately_and_disables_optional_work(self) -> None:
        gov = enabled()
        self.assertTrue(gov.ingest(sample(obs_render_missed_pct=3.2),
                                   now_s=10, host_verified=True))
        advice = gov.recommend(now_s=10)
        self.assertEqual(advice.profile, "critical")
        self.assertEqual(advice.reason, "obs_render_lag")
        self.assertFalse(advice.allow_extra_gpu_inference)
        self.assertFalse(advice.allow_optional_commentary)
        self.assertEqual(advice.max_extra_gpu_vram_mb, 0)

    def test_network_encoder_and_disconnection_have_distinct_reasons(self) -> None:
        for name, change, reason in (
            ("network", {"obs_network_dropped_pct": 4.5}, "network_loss"),
            ("encoder", {"obs_encode_skipped_pct": 2.5}, "obs_encoder_lag"),
            ("disconnect", {"obs_connected": False}, "obs_disconnected"),
            ("game", {"game_p95_frame_ms": 31}, "game_frame_deadline"),
            ("vram", {"gpu_vram_used_mb": 8000}, "vram_near_capacity"),
        ):
            with self.subTest(name=name):
                gov = enabled()
                self.assertTrue(gov.ingest(sample(**change), now_s=10,
                                           host_verified=True))
                self.assertEqual(gov.recommend(now_s=10).reason, reason)

    def test_speech_and_game_pressure_do_not_masquerade_as_obs_errors(self) -> None:
        for kwargs, reason in (
            ({"tts_first_audio_p95_ms": 1000}, "speech_latency"),
            ({"game_p95_frame_ms": 24}, "game_frame_pressure"),
            ({"gpu_vram_used_mb": 7300}, "vram_pressure"),
        ):
            with self.subTest(reason=reason):
                gov = enabled()
                gov.ingest(sample(**kwargs), now_s=10, host_verified=True)
                self.assertEqual(gov.recommend(now_s=10).profile, "constrained")
                self.assertEqual(gov.recommend(now_s=10).reason, reason)

    def test_recovery_moves_one_severity_step_per_three_good_snapshots(self) -> None:
        gov = enabled()
        gov.ingest(sample("bad", obs_render_missed_pct=5), now_s=10, host_verified=True)
        self.assertEqual(gov.recommend(now_s=10).profile, "critical")
        for i in range(1, 3):
            gov.ingest(sample(f"heal-{i}", at=10 + i), now_s=10 + i,
                       host_verified=True)
            self.assertEqual(gov.recommend(now_s=10 + i).profile, "critical")
        gov.ingest(sample("heal-3", at=13), now_s=13, host_verified=True)
        self.assertEqual(gov.recommend(now_s=13).profile, "constrained")
        for i in range(4, 6):
            gov.ingest(sample(f"heal-{i}", at=10 + i), now_s=10 + i,
                       host_verified=True)
            self.assertEqual(gov.recommend(now_s=10 + i).profile, "constrained")
        gov.ingest(sample("heal-6", at=16), now_s=16, host_verified=True)
        self.assertEqual(gov.recommend(now_s=16).profile, "normal")

    def test_warmup_counter_resets_after_bad_sample(self) -> None:
        gov = enabled()
        gov.ingest(sample("warm", at=10), now_s=10, host_verified=True)
        gov.ingest(sample("bad", at=11, obs_render_missed_pct=3.5),
                   now_s=11, host_verified=True)
        self.assertEqual(gov.recommend(now_s=11).profile, "critical")
        for i in range(12, 14):
            gov.ingest(sample(f"recover-{i}", at=i), now_s=i, host_verified=True)
            self.assertEqual(gov.recommend(now_s=i).profile, "critical")

    def test_no_rushed_recovery_when_load_fluctuates(self) -> None:
        gov = enabled()
        gov.ingest(sample("bad", obs_encode_skipped_pct=3), now_s=10,
                   host_verified=True)
        gov.ingest(sample("ok1", at=11), now_s=11, host_verified=True)
        gov.ingest(sample("bad2", at=12, obs_encode_skipped_pct=3),
                   now_s=12, host_verified=True)
        gov.ingest(sample("ok2", at=13), now_s=13, host_verified=True)
        gov.ingest(sample("ok3", at=14), now_s=14, host_verified=True)
        self.assertEqual(gov.recommend(now_s=14).profile, "critical")

    def test_stale_telemetry_fails_quiet_even_after_good_stream(self) -> None:
        gov = enabled()
        for i in range(3):
            gov.ingest(sample(f"s{i}", at=10 + i), now_s=10 + i, host_verified=True)
        self.assertEqual(gov.recommend(now_s=12).profile, "normal")
        advice = gov.recommend(now_s=15.01)
        self.assertEqual(advice.profile, "telemetry_stale")
        self.assertTrue(advice.pause_background_workers)
        self.assertFalse(advice.allow_extra_gpu_inference)
        self.assertFalse(advice.allow_optional_commentary)

    def test_replays_future_out_of_order_and_stale_samples_are_rejected(self) -> None:
        gov = enabled(max_sample_age_s=2)
        self.assertFalse(gov.ingest(sample("future", at=11), now_s=10,
                                    host_verified=True))
        self.assertFalse(gov.ingest(sample("old", at=1), now_s=10,
                                    host_verified=True))
        self.assertTrue(gov.ingest(sample("first", at=10), now_s=10,
                                   host_verified=True))
        self.assertFalse(gov.ingest(sample("first", at=10.5), now_s=10.5,
                                    host_verified=True))
        self.assertFalse(gov.ingest(sample("earlier", at=9), now_s=10.5,
                                    host_verified=True))
        self.assertEqual(gov.metrics()["accepted"], 1)
        self.assertEqual(gov.metrics()["rejected"], 4)

    def test_long_telemetry_gap_requires_fresh_warmup(self) -> None:
        gov = enabled()
        for i in range(10, 13):
            self.assertTrue(gov.ingest(sample(f"initial-{i}", at=i),
                                       now_s=i, host_verified=True))
        self.assertEqual(gov.recommend(now_s=12).profile, "normal")
        self.assertEqual(gov.recommend(now_s=19).profile, "telemetry_stale")
        self.assertTrue(gov.ingest(sample("after-gap", at=20),
                                   now_s=20, host_verified=True))
        self.assertEqual(gov.recommend(now_s=20).profile, "warming")
        self.assertFalse(gov.recommend(now_s=20).allow_optional_commentary)
        for i in (21, 22):
            self.assertTrue(gov.ingest(sample(f"new-{i}", at=i),
                                       now_s=i, host_verified=True))
        self.assertEqual(gov.recommend(now_s=22).profile, "normal")

    def test_host_monotonic_clock_cannot_go_backwards(self) -> None:
        gov = enabled()
        gov.ingest(sample(), now_s=10, host_verified=True)
        with self.assertRaisesRegex(ValueError, "backwards"):
            gov.recommend(now_s=9)
        with self.assertRaisesRegex(ValueError, "backwards"):
            gov.ingest(sample("older", at=9), now_s=9, host_verified=True)
        self.assertEqual(gov.recommend(now_s=10).profile, "warming")

    def test_future_recommendation_read_cannot_poison_next_verified_sample(self) -> None:
        gov = enabled()
        self.assertTrue(gov.ingest(sample("first", at=10), now_s=10,
                                   host_verified=True))
        # A routed gaming clock may accidentally use another clock epoch.
        # It must return stale advice, not irreversibly advance the ingest
        # watermark to 1,000,000 seconds.
        self.assertEqual(gov.recommend(now_s=1_000_000).profile, "telemetry_stale")
        self.assertTrue(gov.ingest(sample("recovered", at=11), now_s=11,
                                   host_verified=True))
        self.assertEqual(gov.recommend(now_s=11).profile, "warming")
        self.assertEqual(gov.metrics()["accepted"], 2)

    def test_repeated_snapshot_reads_are_read_only_under_clock_mismatch(self) -> None:
        gov = enabled()
        self.assertTrue(gov.ingest(sample("base", at=10), now_s=10,
                                   host_verified=True))
        for stamp in (20, 400, 100_000):
            self.assertEqual(gov.recommend(now_s=stamp).profile, "telemetry_stale")
        with self.assertRaisesRegex(ValueError, "backwards"):
            gov.recommend(now_s=9)
        # Rejected reads have not changed the canonical monotonic watermark.
        self.assertTrue(gov.ingest(sample("after", at=12), now_s=12,
                                   host_verified=True))
        self.assertEqual(gov.metrics()["accepted"], 2)

    def test_vram_advice_keeps_an_8gb_stream_reserve(self) -> None:
        gov = enabled()
        for i in range(3):
            gov.ingest(sample(f"ok{i}", at=10+i, gpu_vram_used_mb=6300),
                       now_s=10+i, host_verified=True)
        advice = gov.recommend(now_s=12)
        self.assertEqual(advice.profile, "normal")
        self.assertLess(advice.max_extra_gpu_vram_mb, 300)
        self.assertFalse(advice.allow_extra_gpu_inference)

    def test_disable_clears_history_and_requires_new_warmup(self) -> None:
        gov = enabled()
        gov.ingest(sample("bad", obs_render_missed_pct=4), now_s=10,
                   host_verified=True)
        gov.disable()
        self.assertEqual(gov.recommend(now_s=10).profile, "disabled")
        self.assertEqual(gov.metrics()["recent_ids"], 0)
        gov.enable(owner_approved=True)
        self.assertTrue(gov.ingest(sample("bad"), now_s=10, host_verified=True))
        self.assertEqual(gov.recommend(now_s=10).profile, "warming")

    def test_invalid_measurements_rejected_on_construction(self) -> None:
        for changes in (
            {"sample_id": ""}, {"sample_id": "a" * 81},
            {"measured_at_s": float("nan")},
            {"obs_render_missed_pct": -1},
            {"obs_encode_skipped_pct": 101},
            {"obs_network_dropped_pct": float("inf")},
            {"game_target_fps": 0}, {"game_p95_frame_ms": -1},
            {"gpu_vram_used_mb": 10000},
            {"gpu_vram_total_mb": 0},
            {"tts_first_audio_p95_ms": True},
            {"obs_connected": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sample(**changes)

    def test_untrusted_clock_values_cannot_poison_verified_session(self) -> None:
        gov = enabled()
        self.assertTrue(gov.ingest(sample("verified-10", at=10),
                                   now_s=10, host_verified=True))
        # These untrusted packets must not advance the internal clock,
        # even if their syntactically valid timestamps are far in the future.
        self.assertFalse(gov.ingest(sample("forged-future", at=1_000_000),
                                    now_s=1_000_000, host_verified=False))
        self.assertFalse(gov.ingest(sample("forged-past", at=1),
                                    now_s=1, host_verified=False))
        # A malformed object with a purported verified flag also cannot
        # advance the host clock or cause attribute access.
        self.assertFalse(gov.ingest(object(), now_s=1_000_000,
                                    host_verified=True))  # type: ignore[arg-type]
        self.assertTrue(gov.ingest(sample("verified-11", at=11),
                                   now_s=11, host_verified=True))
        self.assertEqual(gov.metrics()["accepted"], 2)
        self.assertEqual(gov.metrics()["rejected"], 3)
        self.assertEqual(gov.recommend(now_s=11).profile, "warming")

    def test_verified_duplicate_from_delayed_queue_cannot_poison_clock(self) -> None:
        gov = enabled()
        self.assertTrue(gov.ingest(sample("first", at=10), now_s=10,
                                   host_verified=True))
        self.assertFalse(gov.ingest(sample("first", at=10), now_s=1_000_000,
                                    host_verified=True))
        # A duplicate is not a new clock attestation. Valid later evidence
        # must recover without forcing an owner-visible session restart.
        self.assertTrue(gov.ingest(sample("next", at=11), now_s=11,
                                   host_verified=True))
        self.assertEqual(gov.metrics()["accepted"], 2)

    def test_verified_stale_future_delivery_cannot_poison_clock(self) -> None:
        gov = enabled()
        self.assertTrue(gov.ingest(sample("first", at=10), now_s=10,
                                   host_verified=True))
        self.assertFalse(gov.ingest(sample("old", at=11), now_s=1_000_000,
                                    host_verified=True))
        self.assertFalse(gov.ingest(sample("future", at=1_001), now_s=12,
                                    host_verified=True))
        self.assertTrue(gov.ingest(sample("next", at=12), now_s=12,
                                   host_verified=True))
        with self.assertRaises(ValueError):
            gov.ingest(sample("rollback", at=13), now_s=9,
                       host_verified=True)
        self.assertTrue(gov.ingest(sample("after", at=13), now_s=13,
                                   host_verified=True))

    def test_concurrent_duplicate_ingest_stays_atomic(self) -> None:
        gov = enabled()
        barrier = Barrier(12)

        def ingest_one(_: int) -> bool:
            barrier.wait()
            return gov.ingest(sample(), now_s=10, host_verified=True)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(ingest_one, range(12)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(gov.metrics()["accepted"], 1)
        self.assertEqual(gov.metrics()["rejected"], 11)


if __name__ == "__main__":
    unittest.main()
