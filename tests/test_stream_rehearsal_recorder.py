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
        record(r, "pcm_stopped", 1200, opaque_id="s1")
        record(r, "obs_stats_sampled", 1210, skipped_frames=3, total_frames=1000)
        record(r, "obs_stats_sampled", 1230, skipped_frames=4, total_frames=1100)
        for i in range(120):
            record(r, "frame_presented", 1240 + i,
                   duration_ms=16 if i != 119 else 45)
        r.end(at_ms=1400, host_verified=True)
        report = r.report()
        self.assertTrue(report["clean_shutdown"])
        self.assertEqual(report["scene_to_action_p95_ms"], 80.0)
        self.assertEqual(report["speech_to_audible_p95_ms"], 70.0)
        self.assertEqual(report["pcm_to_avatar_p95_ms"], 8.0)
        self.assertEqual(report["obs_skipped_fraction"], 0.01)
        self.assertEqual(report["max_frame_time_ms"], 45.0)
        self.assertEqual(report["frame_samples"], 120)
        self.assertEqual(report["workers_exited"], 1)
        run = r.to_realtime_run(
            pair_id="same_scene_1", variant="baseline", game_id="obby",
            game_version="1", gpu_peak_mib=4100,
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
                game_version="1", gpu_peak_mib=4000,
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
                game_version="v", gpu_peak_mib=4000,
            )

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
