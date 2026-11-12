from __future__ import annotations

import copy

import pytest

from star.stream_rehearsal_eval import RehearsalLimits
from star.stream_rehearsal_recorder import StreamRehearsalRecorder


def configured_limits() -> RehearsalLimits:
    return RehearsalLimits(
        min_observations=20,
        max_first_content_p95_ms=200.0,
        max_first_audible_p95_ms=400.0,
        max_game_frame_p99_ms=20.0,
        max_avatar_sync_p95_ms=10.0,
        max_audio_underrun_rate=0.01,
        max_obs_render_skip_rate=0.01,
        max_obs_output_skip_rate=0.01,
        min_turn_precision=0.95,
        min_turn_recall=0.95,
        min_task_recovery_rate=0.95,
        min_held_out_skill_transfer_rate=0.95,
        max_stale_task_resumes=0,
        max_duplicate_speech_replays=0,
    )


def complete_recorder(run_id: str = "run-1") -> StreamRehearsalRecorder:
    recorder = StreamRehearsalRecorder(run_id, max_samples=100)
    for index in range(21):
        started = 1_000.0 + index * 1_000.0
        assert recorder.record_latency(
            "first_content",
            event_id=f"request-{index}",
            epoch="inference-1",
            started_ms=started,
            first_ms=started + 100.0,
        )
        assert recorder.record_latency(
            "first_audible",
            event_id=f"request-{index}",
            epoch="audio-1",
            started_ms=started,
            first_ms=started + 250.0,
        )
        assert recorder.record_avatar_sync(
            event_id=f"sync-{index}",
            audio_epoch="audio-1",
            avatar_epoch="avatar-1",
            playback_at_ms=started + 250.0,
            avatar_update_at_ms=started + 255.0,
        )
        if index == 0:
            assert recorder.record_frame_present(epoch="game-1", at_ms=0.0)
        else:
            assert recorder.record_frame_present(
                epoch="game-1", at_ms=index * 16.6667
            )
        assert recorder.observe_audio_counters(
            epoch="audio-1",
            underruns_total=0,
            playback_chunks_total=index * 10,
        ) is (index > 0)
        assert recorder.observe_obs_counters(
            epoch="obs-1",
            render_skipped_total=0,
            render_total=index * 100,
            output_skipped_total=0,
            output_total=index * 100,
        ) is (index > 0)
        if index < 20:
            assert recorder.record_turn_outcome(
                event_id=f"turn-{index}",
                true_positives=1,
                false_positives=0,
                false_negatives=0,
                independently_labeled=True,
            )
            assert recorder.record_task_recovery(
                event_id=f"recovery-{index}", succeeded=True
            )
            assert recorder.record_speech_replay(
                event_id=f"speech-{index}", duplicate=False
            )
            assert recorder.record_held_out_skill_trial(
                event_id=f"skill-{index}",
                succeeded=True,
                independently_scored=True,
            )
    return recorder


def test_complete_recorder_feeds_existing_rehearsal_evaluator():
    recorder = complete_recorder()
    snapshot = recorder.snapshot()

    assert set(snapshot) == {
        "schema_version",
        "run_id",
        "first_content_latency_ms",
        "first_audible_latency_ms",
        "game_frame_time_ms",
        "avatar_sync_error_ms",
        "audio_underrun_chunks",
        "audio_playback_chunks",
        "obs_render_skipped_frames",
        "obs_render_total_frames",
        "obs_output_skipped_frames",
        "obs_output_total_frames",
        "turn_true_positives",
        "turn_false_positives",
        "turn_false_negatives",
        "task_recovery_attempts",
        "task_recovery_successes",
        "stale_task_resumes",
        "duplicate_speech_replays",
        "held_out_skill_trials",
        "held_out_skill_successes",
    }
    report = recorder.evaluate(configured_limits())

    assert report["overall"] == "PASS"
    assert report["metrics"]["first_content_p95_ms"] == 100.0
    assert report["metrics"]["first_audible_p95_ms"] == 250.0
    assert report["metrics"]["avatar_sync_p95_ms"] == 5.0
    assert report["metrics"]["game_frame_p99_ms"] == pytest.approx(16.667, abs=0.001)
    assert report["metrics"]["held_out_skill_transfer_rate"] == 1.0


def test_cumulative_audio_counters_are_differenced_only_within_epoch():
    recorder = StreamRehearsalRecorder("audio-run")

    assert not recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=10, playback_chunks_total=100
    )
    assert recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=12, playback_chunks_total=120
    )
    assert not recorder.observe_audio_counters(
        epoch="audio-b", underruns_total=0, playback_chunks_total=0
    )
    assert recorder.observe_audio_counters(
        epoch="audio-b", underruns_total=1, playback_chunks_total=10
    )

    snapshot = recorder.snapshot()
    assert snapshot["audio_underrun_chunks"] == 3
    assert snapshot["audio_playback_chunks"] == 30
    health = recorder.health()
    assert health["source_restarts"]["audio"] == 1
    assert health["baseline_observations"]["audio"] == 2


def test_counter_regression_requires_a_new_epoch_and_preserves_last_good_baseline():
    recorder = StreamRehearsalRecorder("counter-run")
    assert not recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=5, playback_chunks_total=10
    )
    assert not recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=4, playback_chunks_total=9
    )
    assert recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=6, playback_chunks_total=20
    )

    snapshot = recorder.snapshot()
    assert snapshot["audio_underrun_chunks"] == 1
    assert snapshot["audio_playback_chunks"] == 10
    assert recorder.health()["counter_regressions"] == 1


def test_old_epoch_cannot_be_reused_after_a_restart():
    recorder = StreamRehearsalRecorder("epoch-run")
    assert not recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=0, playback_chunks_total=0
    )
    assert not recorder.observe_audio_counters(
        epoch="audio-b", underruns_total=0, playback_chunks_total=0
    )
    assert not recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=1, playback_chunks_total=10
    )
    assert recorder.snapshot()["audio_playback_chunks"] == 0
    assert recorder.health()["rejected_observations"] == 1


def test_obs_render_and_output_counters_remain_separate():
    recorder = StreamRehearsalRecorder("obs-run")
    assert not recorder.observe_obs_counters(
        epoch="obs-a",
        render_skipped_total=1,
        render_total=100,
        output_skipped_total=2,
        output_total=200,
    )
    assert recorder.observe_obs_counters(
        epoch="obs-a",
        render_skipped_total=3,
        render_total=300,
        output_skipped_total=5,
        output_total=500,
    )
    snapshot = recorder.snapshot()
    assert snapshot["obs_render_skipped_frames"] == 2
    assert snapshot["obs_render_total_frames"] == 200
    assert snapshot["obs_output_skipped_frames"] == 3
    assert snapshot["obs_output_total_frames"] == 300


def test_obs_counter_reset_with_same_epoch_is_rejected():
    recorder = StreamRehearsalRecorder("obs-reset")
    assert not recorder.observe_obs_counters(
        epoch="obs-a",
        render_skipped_total=0,
        render_total=100,
        output_skipped_total=0,
        output_total=100,
    )
    assert not recorder.observe_obs_counters(
        epoch="obs-a",
        render_skipped_total=0,
        render_total=0,
        output_skipped_total=0,
        output_total=0,
    )
    assert recorder.health()["counter_regressions"] == 1
    assert recorder.snapshot()["obs_render_total_frames"] == 0


def test_game_epoch_change_does_not_create_a_cross_process_frame_hitch():
    recorder = StreamRehearsalRecorder("game-epoch", max_samples=10)
    assert recorder.record_frame_present(epoch="game-a", at_ms=0.0)
    assert recorder.record_frame_present(epoch="game-a", at_ms=16.0)
    assert recorder.record_frame_present(epoch="game-b", at_ms=50_000.0)
    assert recorder.record_frame_present(epoch="game-b", at_ms=50_016.0)

    assert recorder.snapshot()["game_frame_time_ms"] == [16.0, 16.0]
    assert recorder.health()["source_restarts"]["game"] == 1


def test_long_pause_is_marked_as_discontinuity_not_a_frame_sample():
    recorder = StreamRehearsalRecorder("pause-run")
    assert recorder.record_frame_present(epoch="game-a", at_ms=0.0)
    assert not recorder.record_frame_present(epoch="game-a", at_ms=20_000.0)
    assert recorder.record_frame_present(epoch="game-a", at_ms=20_016.0)
    assert recorder.snapshot()["game_frame_time_ms"] == [16.0]
    assert recorder.health()["frame_discontinuities"] == 1


def test_reservoir_is_bounded_and_deterministic_for_same_run_and_sequence():
    def fill() -> StreamRehearsalRecorder:
        value = StreamRehearsalRecorder("reservoir-run", max_samples=5)
        assert value.record_frame_present(epoch="game-a", at_ms=0.0)
        for index in range(1, 101):
            assert value.record_frame_present(epoch="game-a", at_ms=index * 16.0)
        return value

    first = fill()
    second = fill()

    assert len(first.snapshot()["game_frame_time_ms"]) == 5
    assert first.snapshot()["game_frame_time_ms"] == second.snapshot()["game_frame_time_ms"]
    assert first.health()["sample_series"]["game_frame_time_ms"] == {
        "observed": 100,
        "retained": 5,
        "sampling_fraction": 0.05,
    }


def test_latency_deduplication_and_duplicate_speech_count_are_bounded():
    recorder = StreamRehearsalRecorder("dedupe-run")
    assert recorder.record_latency(
        "first_content",
        event_id="request-1",
        epoch="inference-a",
        started_ms=10.0,
        first_ms=20.0,
    )
    assert not recorder.record_latency(
        "first_content",
        event_id="request-1",
        epoch="inference-a",
        started_ms=10.0,
        first_ms=30.0,
    )
    assert recorder.record_speech_replay(event_id="playback-1", duplicate=True)
    assert not recorder.record_speech_replay(event_id="playback-1", duplicate=True)

    assert recorder.snapshot()["first_content_latency_ms"] == [10.0]
    assert recorder.snapshot()["duplicate_speech_replays"] == 1
    assert recorder.health()["duplicate_events"] == 2


def test_turn_and_skill_results_require_independent_scoring():
    recorder = StreamRehearsalRecorder("scorer-run")
    with pytest.raises(PermissionError):
        recorder.record_turn_outcome(
            event_id="turn-1",
            true_positives=1,
            false_positives=0,
            false_negatives=0,
            independently_labeled=False,
        )
    with pytest.raises(PermissionError):
        recorder.record_held_out_skill_trial(
            event_id="skill-1",
            succeeded=True,
            independently_scored=False,
        )
    assert recorder.snapshot()["held_out_skill_trials"] == 0


def test_stale_task_resume_cannot_be_counted_as_success():
    recorder = StreamRehearsalRecorder("recovery-run")
    with pytest.raises(ValueError):
        recorder.record_task_recovery(
            event_id="recovery-1", succeeded=True, stale_resume=True
        )
    assert recorder.snapshot()["task_recovery_attempts"] == 0


def test_missing_audio_and_obs_baselines_remain_inconclusive():
    recorder = StreamRehearsalRecorder("missing-baseline")
    recorder.observe_audio_counters(
        epoch="audio-a", underruns_total=0, playback_chunks_total=0
    )
    recorder.observe_obs_counters(
        epoch="obs-a",
        render_skipped_total=0,
        render_total=0,
        output_skipped_total=0,
        output_total=0,
    )
    report = recorder.evaluate(
        RehearsalLimits(
            max_audio_underrun_rate=0.01,
            max_obs_render_skip_rate=0.01,
            max_obs_output_skip_rate=0.01,
        )
    )
    assert report["overall"] == "INCONCLUSIVE"


@pytest.mark.parametrize("bad", [True, -1, 10**1000, float("nan"), float("inf"), "12"])
def test_invalid_timestamps_are_rejected(bad):
    recorder = StreamRehearsalRecorder("bad-time")
    with pytest.raises((ValueError, OverflowError)):
        recorder.record_latency(
            "first_content",
            event_id="request-1",
            epoch="inference-a",
            started_ms=bad,
            first_ms=20.0,
        )


@pytest.mark.parametrize(
    "values",
    [
        (2, 1),
        (-1, 10),
        (1, True),
        (10**1000, 10**1000),
    ],
)
def test_invalid_audio_counters_are_rejected(values):
    recorder = StreamRehearsalRecorder("bad-audio")
    with pytest.raises(ValueError):
        recorder.observe_audio_counters(
            epoch="audio-a",
            underruns_total=values[0],
            playback_chunks_total=values[1],
        )


def test_invalid_obs_relationships_are_rejected():
    recorder = StreamRehearsalRecorder("bad-obs")
    with pytest.raises(ValueError):
        recorder.observe_obs_counters(
            epoch="obs-a",
            render_skipped_total=2,
            render_total=1,
            output_skipped_total=0,
            output_total=1,
        )


def test_event_ledger_capacity_fails_closed():
    recorder = StreamRehearsalRecorder("event-cap", max_event_ids=1)
    assert recorder.record_task_recovery(event_id="event-1", succeeded=True)
    with pytest.raises(RuntimeError):
        recorder.record_task_recovery(event_id="event-2", succeeded=True)


def test_snapshot_and_health_do_not_mutate_recorder_state():
    recorder = complete_recorder("stable-run")
    before = copy.deepcopy(recorder.snapshot())
    health_before = copy.deepcopy(recorder.health())

    assert recorder.snapshot() == before
    assert recorder.health() == health_before
