"""Synthetic tests for Star's host-only, privacy-minimal live rehearsal recorder.

These tests never inspect audio, video, chat, live games, OBS or hardware.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest

from star.stream_rehearsal_recorder import StreamRehearsalRecorder
from star.stream_realtime_benchmark import RealtimeRun, compare_realtime


def recorder(**kwargs):
    return StreamRehearsalRecorder(
        episode_id="ep_1", owner_approved=True, **kwargs,
    )


def record(r, event, at_ms, **kwargs):
    r.record(event, at_ms=at_ms, host_verified=True, **kwargs)


class TestStreamRehearsalRecorder(unittest.TestCase):
    def test_off_by_default_and_rejects_untrusted_sensor(self):
        with self.assertRaises(PermissionError):
            StreamRehearsalRecorder(episode_id="ep_1")
        r = recorder()
        with self.assertRaises(PermissionError):
            r.record("scene_observed", at_ms=1000, scene_sequence=1)
        with self.assertRaises(PermissionError):
            r.end(at_ms=1100)
        self.assertEqual(r.report()["events"], 0)

    def test_end_to_end_game_speech_avatar_obs_metrics_and_benchmark_bridge(self):
        r = recorder()
        record(r, "scene_observed", 1000, scene_sequence=1)
        record(r, "worker_started", 1005, scene_sequence=1, opaque_id="w1")
        record(r, "worker_exited", 1030, scene_sequence=1, opaque_id="w1")
        record(r, "action_claimed", 1080, scene_sequence=1, opaque_id="a1")
        record(r, "action_released", 1100, scene_sequence=1, opaque_id="a1")
        record(r, "speech_queued", 1110, opaque_id="s1")
        record(r, "pcm_first_audible", 1180, opaque_id="s1")
        record(r, "avatar_frame_rendered", 1188, opaque_id="s1")
        record(r, "avatar_frame_rendered", 1190, opaque_id="s1")
        record(r, "obs_stats_sampled", 1210, skipped_frames=3, total_frames=1000)
        record(r, "obs_stats_sampled", 1230, skipped_frames=4, total_frames=1100)
        for i in range(120):
            at = 1240 + i * 16
            record(r, "frame_presented", at,
                   duration_ms=16 if i != 119 else 45)
            if i in (9, 29, 49, 69, 89, 109):
                record(r, "avatar_frame_rendered", at + 1, opaque_id="s1")
        record(r, "pcm_stopped", 3200, opaque_id="s1")
        record(r, "gpu_peak_measured", 3300, gpu_peak_mib=4100)
        r.end(at_ms=3400, host_verified=True)
        report = r.report()
        self.assertTrue(report["clean_shutdown"])
        self.assertEqual(report["scene_to_action_p95_ms"], 80.0)
        self.assertEqual(report["speech_to_audible_p95_ms"], 70.0)
        self.assertEqual(report["pcm_to_avatar_p95_ms"], 8.0)
        self.assertEqual(report["obs_skipped_fraction"], 0.01)
        self.assertEqual(report["max_frame_time_ms"], 45.0)
        self.assertEqual(report["frame_samples"], 120)
        self.assertEqual(report["avatar_frame_samples"], 8)
        self.assertLessEqual(report["avatar_frame_gap_max_ms"], 550)
        self.assertEqual(report["audible_frame_samples"], 120)
        self.assertTrue(report["gpu_peak_measured"])
        self.assertEqual(report["gpu_peak_mib"], 4100)
        self.assertEqual(report["workers_exited"], 1)
        run = r.to_realtime_run(
            pair_id="same_scene_1", variant="baseline", game_id="obby",
            game_version="1",
        )
        self.assertIsInstance(run, RealtimeRun)
        self.assertEqual(run.first_audio_ms, 70)
        self.assertEqual(len(run.frame_times_ms), 120)
        # Existing QoS evaluator receives the exact host-measured frame data.
        self.assertEqual(compare_realtime([run]).incomplete_pairs, 1)
        public = json.dumps(report)
        for sensitive in ("ep_1", "w1", "a1", "s1", "same_scene_1"):
            self.assertNotIn(sensitive, public)

    def test_untrusted_and_invalid_sample_cannot_poison_monotonic_clock(self):
        r = recorder()
        record(r, "scene_observed", 100, scene_sequence=1)
        with self.assertRaises(PermissionError):
            r.record("scene_observed", at_ms=1e12,
                     host_verified=False, scene_sequence=2)
        with self.assertRaises(ValueError):
            record(r, "scene_observed", 1e12, scene_sequence=1)
        with self.assertRaises(ValueError):
            record(r, "frame_presented", float("nan"), duration_ms=20)
        record(r, "scene_observed", 101, scene_sequence=2)
        self.assertEqual(r.report()["scenes"], 2)

    def test_strict_schema_never_accepts_transcripts_or_unknown_payload(self):
        r = recorder()
        with self.assertRaises(ValueError):
            record(r, "chat_message", 100, opaque_id="viewer_name")
        with self.assertRaises(TypeError):
            r.record("scene_observed", at_ms=100, host_verified=True,
                     scene_sequence=1, transcript="private")  # type: ignore[call-arg]
        with self.assertRaises(ValueError):
            record(r, "scene_observed", 100, scene_sequence=1,
                   opaque_id="private_chat")
        with self.assertRaises(ValueError):
            record(r, "speech_queued", 100, opaque_id="user message has spaces")
        with self.assertRaises(ValueError):
            record(r, "speech_queued", 100, opaque_id="Star💛")
        self.assertEqual(r.report()["events"], 0)

    def test_invalid_host_types_and_clock_reversal_rejected(self):
        r = recorder()
        with self.assertRaises(PermissionError):
            r.record("scene_observed", at_ms=100,
                     host_verified=1, scene_sequence=1)  # type: ignore[arg-type]
        record(r, "scene_observed", 100, scene_sequence=1)
        with self.assertRaises(ValueError):
            record(r, "scene_observed", 99, scene_sequence=2)
        with self.assertRaises(ValueError):
            record(r, "scene_observed", 101, scene_sequence=True)
        record(r, "scene_observed", 101, scene_sequence=2)

    def test_stale_scene_action_and_double_claim_and_release(self):
        r = recorder()
        record(r, "scene_observed", 100, scene_sequence=1)
        record(r, "scene_observed", 120, scene_sequence=2)
        with self.assertRaises(ValueError):
            record(r, "action_claimed", 125, scene_sequence=1, opaque_id="old")
        record(r, "action_claimed", 125, scene_sequence=2, opaque_id="p1")
        with self.assertRaises(ValueError):
            record(r, "scene_observed", 126, scene_sequence=3)
        with self.assertRaises(ValueError):
            record(r, "action_claimed", 126, scene_sequence=2, opaque_id="p2")
        with self.assertRaises(ValueError):
            record(r, "action_released", 127, scene_sequence=2, opaque_id="wrong")
        record(r, "action_released", 128, scene_sequence=2, opaque_id="p1")
        with self.assertRaises(ValueError):
            record(r, "action_claimed", 129, scene_sequence=2, opaque_id="p1")
        record(r, "scene_observed", 130, scene_sequence=3)
        self.assertEqual(r.report()["actions_released"], 1)

    def test_worker_overlaps_replay_and_unmatched_exit_rejected(self):
        r = recorder()
        record(r, "scene_observed", 100, scene_sequence=1)
        record(r, "worker_started", 101, scene_sequence=1, opaque_id="w1")
        with self.assertRaises(ValueError):
            record(r, "worker_started", 102, scene_sequence=1, opaque_id="w2")
        record(r, "scene_observed", 103, scene_sequence=2)
        with self.assertRaises(ValueError):
            record(r, "action_claimed", 104, scene_sequence=2, opaque_id="p1")
        with self.assertRaises(ValueError):
            record(r, "worker_exited", 105, scene_sequence=2, opaque_id="w1")
        record(r, "worker_exited", 106, scene_sequence=1, opaque_id="w1")
        with self.assertRaises(ValueError):
            record(r, "worker_started", 107, scene_sequence=2, opaque_id="w1")
        record(r, "worker_started", 108, scene_sequence=2, opaque_id="w2")
        record(r, "worker_exited", 109, scene_sequence=2, opaque_id="w2")
        self.assertEqual(r.report()["workers_exited"], 2)

    def test_audio_must_be_audible_before_avatar_and_stop(self):
        r = recorder()
        record(r, "speech_queued", 100, opaque_id="s1")
        with self.assertRaises(ValueError):
            record(r, "avatar_frame_rendered", 101, opaque_id="s1")
        with self.assertRaises(ValueError):
            record(r, "pcm_stopped", 102, opaque_id="s1")
        with self.assertRaises(ValueError):
            record(r, "speech_queued", 103, opaque_id="s2")
        record(r, "pcm_first_audible", 104, opaque_id="s1")
        with self.assertRaises(ValueError):
            record(r, "pcm_first_audible", 105, opaque_id="s1")
        record(r, "pcm_stopped", 106, opaque_id="s1")
        with self.assertRaises(ValueError):
            record(r, "avatar_frame_rendered", 107, opaque_id="s1")
        with self.assertRaises(ValueError):
            record(r, "speech_queued", 108, opaque_id="s1")
        record(r, "speech_queued", 109, opaque_id="s2")
        self.assertEqual(r.report()["utterances_stopped"], 1)

    def test_obs_counter_reset_rejected_without_poisoning_subsequent_sample(self):
        r = recorder()
        record(r, "obs_stats_sampled", 100, skipped_frames=10, total_frames=1000)
        with self.assertRaises(ValueError):
            record(r, "obs_stats_sampled", 101,
                   skipped_frames=20, total_frames=1005)
        with self.assertRaises(ValueError):
            record(r, "obs_stats_sampled", 102,
                   skipped_frames=1, total_frames=3)
        record(r, "obs_stats_sampled", 103,
               skipped_frames=12, total_frames=1100)
        self.assertEqual(r.report()["obs_skipped_fraction"], 0.02)
        self.assertEqual(r.report()["obs_samples"], 2)

    def test_incomplete_worker_and_audio_remain_visible_after_crash(self):
        r = recorder()
        record(r, "scene_observed", 100, scene_sequence=1)
        record(r, "worker_started", 101, scene_sequence=1, opaque_id="worker")
        record(r, "speech_queued", 102, opaque_id="speech")
        r.end(at_ms=103, host_verified=True)
        self.assertFalse(r.report()["clean_shutdown"])
        with self.assertRaises(RuntimeError):
            record(r, "worker_exited", 104, scene_sequence=1, opaque_id="worker")
        with self.assertRaises(ValueError):
            r.to_realtime_run(
                pair_id="pair", variant="candidate", game_id="g",
                game_version="1",
            )

    def test_bounded_samples_and_valid_events_do_not_mutate_after_limit(self):
        r = recorder(max_events=120)
        for i in range(120):
            record(r, "frame_presented", i, duration_ms=16)
        with self.assertRaises(RuntimeError):
            record(r, "frame_presented", 121, duration_ms=16)
        self.assertEqual(r.report()["events"], 120)
        r.end(at_ms=121, host_verified=True)

    def test_long_episode_rejected_and_recovers(self):
        r = recorder(max_duration_ms=1000)
        record(r, "scene_observed", 10, scene_sequence=1)
        with self.assertRaises(ValueError):
            record(r, "scene_observed", 1011, scene_sequence=2)
        record(r, "scene_observed", 1009, scene_sequence=2)
        self.assertEqual(r.report()["scenes"], 2)

    def test_single_utterance_and_frames_required_to_export(self):
        r = recorder()
        record(r, "speech_queued", 1, opaque_id="s1")
        record(r, "pcm_first_audible", 2, opaque_id="s1")
        record(r, "pcm_stopped", 3, opaque_id="s1")
        r.end(at_ms=4, host_verified=True)
        with self.assertRaises(ValueError):
            r.to_realtime_run(
                pair_id="p", variant="candidate", game_id="g",
                game_version="v",
            )

    def _complete_host_run(self, *, avatar_times=(210, 550, 900, 1250, 1600, 1950, 2200),
                           gpu_peak=4200, queue_ms=100, audible_ms=150,
                           stopped_ms=2300, max_avatar_frame_gap_ms=550):
        r = recorder(max_avatar_frame_gap_ms=max_avatar_frame_gap_ms)
        record(r, "speech_queued", queue_ms, opaque_id="speech1")
        record(r, "pcm_first_audible", audible_ms, opaque_id="speech1")
        # Timestamp sorted across both real game presentation and avatar output.
        frames = [
            (200 + i * 16, "frame") for i in range(120)
        ]
        frames.extend((t, "avatar") for t in avatar_times)
        for t, kind in sorted(frames):
            if kind == "avatar":
                record(r, "avatar_frame_rendered", t, opaque_id="speech1")
            else:
                record(r, "frame_presented", t, duration_ms=16.67)
        record(r, "pcm_stopped", stopped_ms, opaque_id="speech1")
        if gpu_peak is not None:
            record(r, "gpu_peak_measured", 2400, gpu_peak_mib=gpu_peak)
        r.end(at_ms=2410, host_verified=True)
        return r

    def test_export_fails_when_gpu_measurement_is_missing(self):
        r = self._complete_host_run(gpu_peak=None)
        self.assertTrue(r.report()["clean_shutdown"])
        self.assertFalse(r.report()["gpu_peak_measured"])
        with self.assertRaisesRegex(ValueError, "host-verified GPU peak"):
            r.to_realtime_run(
                pair_id="pair", variant="candidate",
                game_id="g", game_version="v",
            )
        with self.assertRaises(TypeError):
            r.to_realtime_run(
                pair_id="pair", variant="candidate",
                game_id="g", game_version="v", gpu_peak_mib=0,
            )  # type: ignore[call-arg]

    def test_gpu_event_is_host_verified_one_time_bounded_and_final(self):
        r = recorder()
        with self.assertRaises(PermissionError):
            r.record("gpu_peak_measured", at_ms=10, gpu_peak_mib=4200)
        with self.assertRaises(ValueError):
            record(r, "gpu_peak_measured", 10, gpu_peak_mib=4200)
        record(r, "frame_presented", 11, duration_ms=16.67)
        with self.assertRaisesRegex(ValueError, "before completed audible speech"):
            record(r, "gpu_peak_measured", 12, gpu_peak_mib=4200)
        record(r, "speech_queued", 13, opaque_id="s")
        record(r, "pcm_first_audible", 14, opaque_id="s")
        record(r, "pcm_stopped", 15, opaque_id="s")
        for bad in (float("nan"), True, 0, 262145):
            with self.assertRaises(ValueError):
                record(r, "gpu_peak_measured", 16, gpu_peak_mib=bad)
        record(r, "gpu_peak_measured", 17, gpu_peak_mib=4200)
        with self.assertRaises(ValueError):
            record(r, "gpu_peak_measured", 18, gpu_peak_mib=1)
        with self.assertRaisesRegex(ValueError, "after final GPU peak"):
            record(r, "frame_presented", 19, duration_ms=20)
        self.assertEqual(r.report()["frame_samples"], 1)
        self.assertEqual(r.report()["gpu_peak_mib"], 4200)
        self.assertEqual(r.report()["events"], 5)

    def test_idle_frames_after_audio_do_not_qualify_realtime_game_fps(self):
        r = recorder()
        record(r, "speech_queued", 100, opaque_id="voice")
        record(r, "pcm_first_audible", 150, opaque_id="voice")
        record(r, "avatar_frame_rendered", 155, opaque_id="voice")
        record(r, "pcm_stopped", 160, opaque_id="voice")
        for i in range(120):
            record(r, "frame_presented", 200 + i * 16, duration_ms=16.67)
        record(r, "gpu_peak_measured", 2200, gpu_peak_mib=3000)
        r.end(at_ms=2300, host_verified=True)
        self.assertEqual(r.report()["frame_samples"], 120)
        self.assertEqual(r.report()["audible_frame_samples"], 0)
        with self.assertRaisesRegex(ValueError, "audible-game frames"):
            r.to_realtime_run(
                pair_id="pair", variant="candidate",
                game_id="g", game_version="v",
            )

    def test_benchmark_uses_only_audio_concurrent_frame_durations(self):
        r = recorder()
        record(r, "speech_queued", 100, opaque_id="speech")
        record(r, "pcm_first_audible", 110, opaque_id="speech")
        for i in range(120):
            at = 200 + i * 16
            record(r, "frame_presented", at, duration_ms=20)
            if i % 10 == 0:
                record(r, "avatar_frame_rendered", at + 1, opaque_id="speech")
        record(r, "pcm_stopped", 2150, opaque_id="speech")
        for i in range(30):
            record(r, "frame_presented", 2200 + i * 16, duration_ms=2)
        record(r, "gpu_peak_measured", 2800, gpu_peak_mib=4050)
        r.end(at_ms=2810, host_verified=True)
        self.assertEqual(r.report()["frame_samples"], 150)
        self.assertEqual(r.report()["audible_frame_samples"], 120)
        run = r.to_realtime_run(
            pair_id="pair", variant="candidate",
            game_id="g", game_version="v",
        )
        self.assertEqual(len(run.frame_times_ms), 120)
        self.assertEqual(run.frame_times_ms[0], 90)  # leading audio/game pause
        self.assertEqual(run.frame_times_ms[-1], 46)  # trailing pause
        self.assertEqual(set(run.frame_times_ms[1:-1]), {20})

    def test_missing_avatar_is_not_eligible_for_streaming_comparison(self):
        r = self._complete_host_run(avatar_times=())
        self.assertTrue(r.report()["clean_shutdown"])
        self.assertEqual(r.report()["avatar_frame_samples"], 0)
        with self.assertRaisesRegex(ValueError, "missing or frozen avatar"):
            r.to_realtime_run(
                pair_id="pair", variant="candidate",
                game_id="g", game_version="v",
            )

    def test_one_early_avatar_frame_then_long_freeze_is_rejected(self):
        r = self._complete_host_run(avatar_times=(210,))
        self.assertEqual(r.report()["avatar_frame_gap_max_ms"], 2090)
        with self.assertRaisesRegex(ValueError, "missing or frozen avatar"):
            r.to_realtime_run(
                pair_id="pair", variant="candidate",
                game_id="g", game_version="v",
            )

    def test_continuous_audio_avatar_cadence_allows_export(self):
        r = self._complete_host_run()
        self.assertEqual(r.report()["avatar_frame_gap_max_ms"], 350)
        run = r.to_realtime_run(
            pair_id="pair", variant="candidate",
            game_id="g", game_version="v",
        )
        self.assertEqual(run.first_audio_ms, 50)
        self.assertEqual(run.gpu_peak_mib, 4200)
        self.assertEqual(len(run.frame_times_ms), 120)

    def test_avatar_cadence_tunable_and_strict_validation(self):
        with self.assertRaises(ValueError):
            recorder(max_avatar_frame_gap_ms=0)
        with self.assertRaises(ValueError):
            recorder(max_avatar_frame_gap_ms=float("nan"))
        with self.assertRaises(ValueError):
            recorder(max_avatar_frame_gap_ms=True)
        r = self._complete_host_run(avatar_times=(210, 590, 970, 1350, 1730, 2110))
        self.assertEqual(r.report()["avatar_frame_gap_max_ms"], 380)
        self.assertIsNotNone(r.to_realtime_run(
            pair_id="pair", variant="candidate", game_id="g", game_version="v",
        ))

    def test_concurrent_duplicate_scene_only_one_host_event_wins(self):
        r = recorder()
        def send(_):
            try:
                record(r, "scene_observed", 100, scene_sequence=1)
                return "accepted"
            except ValueError:
                return "replayed"
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(send, range(24)))
        self.assertEqual(replies.count("accepted"), 1)
        self.assertEqual(r.report()["scenes"], 1)


if __name__ == "__main__":
    unittest.main()
