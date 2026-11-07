"""Adversarial timing-evidence tests for an audible game/VTuber rehearsal.

These are synthetic monotonic host events, not actual streaming performance.
"""
import unittest

from star.stream_rehearsal_recorder import StreamRehearsalRecorder
from star.stream_realtime_benchmark import compare_realtime


def emit(recorder, event, at_ms, **data):
    recorder.record(event, at_ms=at_ms, host_verified=True, **data)


def rehearsal(*, first_ms, period_ms, stop_ms, avatar_period_ms=250,
              pair_id="p", variant="candidate"):
    recorder = StreamRehearsalRecorder(
        episode_id="frame_gap_test", owner_approved=True,
    )
    emit(recorder, "speech_queued", 100, opaque_id="voice")
    emit(recorder, "pcm_first_audible", 150, opaque_id="voice")
    events = [
        (first_ms + period_ms * i, "frame") for i in range(120)
    ]
    events.extend(
        (ms, "avatar") for ms in range(200, int(stop_ms), avatar_period_ms)
    )
    for ms, kind in sorted(events):
        if kind == "frame":
            emit(recorder, "frame_presented", ms, duration_ms=16)
        else:
            emit(recorder, "avatar_frame_rendered", ms, opaque_id="voice")
    emit(recorder, "pcm_stopped", stop_ms, opaque_id="voice")
    emit(recorder, "gpu_peak_measured", stop_ms + 5, gpu_peak_mib=3500)
    recorder.end(at_ms=stop_ms + 10, host_verified=True)
    return recorder.to_realtime_run(
        pair_id=pair_id, variant=variant, game_id="g", game_version="1"
    )


class TestAudiblePresentationTiming(unittest.TestCase):
    def test_sparse_frame_callback_timestamps_are_not_falsely_60fps(self):
        # A host reports every 100 ms while claiming each frame took 16 ms.
        # The observed 10 FPS cadence must win over the optimistic duration.
        run = rehearsal(first_ms=200, period_ms=100, stop_ms=12200)
        self.assertEqual(len(run.frame_times_ms), 120)
        self.assertGreaterEqual(min(run.frame_times_ms[1:]), 100)

    def test_audio_boundary_freezes_count_as_visible_game_stalls(self):
        # A one-second initial freeze and long trailing freeze are visible,
        # even though all 120 reported frame durations are only 16 ms.
        run = rehearsal(first_ms=1150, period_ms=16, stop_ms=4000)
        self.assertGreaterEqual(run.frame_times_ms[0], 1000)
        self.assertGreaterEqual(run.frame_times_ms[-1], 900)

    def test_duplicate_presentation_timestamp_rejected_without_poison(self):
        r = StreamRehearsalRecorder(episode_id="dupe", owner_approved=True)
        emit(r, "speech_queued", 10, opaque_id="voice")
        emit(r, "pcm_first_audible", 20, opaque_id="voice")
        emit(r, "frame_presented", 30, duration_ms=16)
        with self.assertRaisesRegex(ValueError, "duplicate|non-increasing"):
            emit(r, "frame_presented", 30, duration_ms=16)
        emit(r, "frame_presented", 46, duration_ms=16)
        self.assertEqual(r.report()["frame_samples"], 2)

    def test_trailing_gap_survives_benchmark_export(self):
        run = rehearsal(first_ms=200, period_ms=16, stop_ms=5000)
        self.assertGreaterEqual(run.frame_times_ms[-1], 2800)

    def test_paired_candidate_cannot_claim_fast_fps_with_sparse_presents(self):
        runs = []
        for index in range(10):
            pair = f"p{index}"
            runs.append(rehearsal(
                first_ms=200, period_ms=16, stop_ms=2300,
                pair_id=pair, variant="baseline",
            ))
            runs.append(rehearsal(
                first_ms=200, period_ms=100, stop_ms=12200,
                pair_id=pair, variant="candidate",
            ))
        result = compare_realtime(runs, minimum_pairs=10)
        self.assertEqual(result.verdict, "regressed")
        self.assertEqual(result.candidate_pair_fps_regressions, 10)


if __name__ == "__main__":
    unittest.main()
