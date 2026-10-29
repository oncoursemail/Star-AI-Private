"""Synthetic-only QoE join tests. No actual OBS, avatar, game or voice output."""
from dataclasses import replace
from hashlib import sha256

import pytest

from star.stream_av_recording_host import RecordingAVResult
from star.stream_av_sync_audit import AVSyncReport
from star.stream_obs_qos_gate import ObsFrameWindow, ObsStatsCounters
from star.stream_output_qoe_gate import (
    OutputAVWindow, compare_stream_output_qoe,
)
from star.stream_realtime_benchmark import RealtimeRun


def good_report(*, lag=20, f1=0.96, silent=0.01, coverage=0.97,
                verdict="eligible_for_owner_review"):
    return AVSyncReport(
        verdict=verdict, reason="bounded_av_sync_targets_met",
        sample_count=240, duration_ms=8000.0,
        estimated_mouth_lag_ms=lag, best_alignment_f1=f1,
        zero_lag_f1=0.93, voiced_mouth_coverage=coverage,
        silent_mouth_rate=silent, audible_transitions=14,
    )


def run(pair, variant, *, ttfa=None, frame=16.7, gpu=5000.0):
    return RealtimeRun(
        pair, variant, "obby", "v2",
        float(ttfa if ttfa is not None else
              (650 if variant == "baseline" else 400)),
        (frame,) * 150, gpu, True,
    )


def frame_window(pair, variant, *, render_drop=0, output_drop=0,
                 obs_session=None, duration=10000):
    return ObsFrameWindow(
        pair, variant, "obby", "v2",
        obs_session or ("obs_" + variant),
        1000.0, 1000.0 + duration,
        ObsStatsCounters(1000, 10, 1000, 10),
        ObsStatsCounters(1600, 10 + render_drop,
                         1600, 10 + output_drop),
        True, False,
    )


def recording_window(pair, variant, *, report=None, capture=True,
                     isolated=True, obs_session=None, start=2000.0,
                     end=10000.0, digest=None):
    unique = digest or sha256(f"{pair}:{variant}".encode()).hexdigest()
    return OutputAVWindow(
        pair, variant, "obby", "v2", obs_session or ("obs_" + variant),
        unique, start, end, capture, isolated, report or good_report(),
    )


def study(n=24):
    runs, obs, clips = [], [], []
    for i in range(n):
        pair = f"pair{i:03d}"
        for variant in ("baseline", "candidate"):
            runs.append(run(pair, variant))
            obs.append(frame_window(pair, variant))
            clips.append(recording_window(pair, variant))
    return runs, obs, clips


def test_good_join_remains_owner_review_only_and_aggregate():
    runs, obs, clips = study()
    report = compare_stream_output_qoe(runs, obs, clips)
    assert report.verdict == "eligible_for_owner_review"
    assert report.speed_and_obs_verdict == "eligible_for_manual_pilot"
    assert report.complete_av_pairs == 24
    assert report.missing_av_windows == report.unverified_av_windows == 0
    assert report.degraded_av_pairs == 0
    assert report.worst_candidate_abs_mouth_lag_ms == 20
    assert report.mean_candidate_alignment_f1 == 0.96
    assert "automatic" in report.note
    assert "pair000" not in repr(report)
    assert "private" not in repr(report).lower()
    assert compare_stream_output_qoe(
        runs[::-1], obs[::-1], clips[::-1],
    ) == report


@pytest.mark.parametrize(
    "changed",
    [
        good_report(lag=80),  # still under absolute 100 ms threshold
        good_report(f1=0.88),  # strong aligned score, worse than baseline
        good_report(silent=0.052),
        good_report(coverage=0.88),
        good_report(verdict="needs_improvement"),
    ],
)
def test_avatar_degradation_vetoes_faster_tts_even_with_healthy_obs(changed):
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1], report=changed)
    report = compare_stream_output_qoe(runs, obs, clips)
    assert report.speed_and_obs_verdict == "eligible_for_manual_pilot"
    assert report.verdict == "regressed"
    assert report.degraded_av_pairs == 1


def test_a_single_bad_candidate_cannot_hide_in_average():
    runs, obs, clips = study(48)
    clips[-1] = replace(clips[-1], report=good_report(lag=100))
    decision = compare_stream_output_qoe(runs, obs, clips)
    assert decision.degraded_av_pairs == 1
    assert decision.verdict == "regressed"
    assert decision.worst_candidate_abs_mouth_lag_ms == 100


@pytest.mark.parametrize("bad_flag", ["output_capture_attested",
                                      "isolated_star_audio_attested"])
def test_missing_host_observation_never_promotes(bad_flag):
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1], **{bad_flag: False})
    report = compare_stream_output_qoe(runs, obs, clips)
    assert report.verdict == "inconclusive"
    assert report.unverified_av_windows == 1
    assert report.degraded_av_pairs == 0


def test_insufficient_candidate_report_is_inconclusive_not_good():
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1], report=AVSyncReport(
        "insufficient_evidence", "too_few_samples", 20, 0.0,
    ))
    report = compare_stream_output_qoe(runs, obs, clips)
    assert report.verdict == "inconclusive"
    assert report.unverified_av_windows == 1


def test_unusable_baseline_cannot_be_counted_as_a_good_comparison():
    runs, obs, clips = study()
    clips[0] = replace(clips[0], report=good_report(
        verdict="needs_improvement",
    ))
    assert compare_stream_output_qoe(runs, obs, clips).verdict == "inconclusive"


def test_missing_clips_and_too_few_pairs_do_not_prove_improvement():
    runs, obs, clips = study()
    report = compare_stream_output_qoe(runs, obs, clips[:-1])
    assert report.verdict == "inconclusive"
    assert report.missing_av_windows == 1
    report = compare_stream_output_qoe(runs[:16], obs[:16], clips[:16])
    assert report.verdict == "inconclusive"
    assert report.complete_av_pairs == 8


def test_obs_frame_drop_overrules_successful_av_and_fast_audio():
    runs, obs, clips = study()
    obs[-1] = frame_window("pair023", "candidate", output_drop=9)
    report = compare_stream_output_qoe(runs, obs, clips)
    assert report.speed_and_obs_verdict == "regressed"
    assert report.verdict == "regressed"
    assert report.degraded_av_pairs == 0


def test_game_fps_gpu_and_first_audible_metrics_still_gate():
    runs, obs, clips = study()
    runs[-1] = replace(runs[-1], gpu_peak_mib=7000)
    assert compare_stream_output_qoe(runs, obs, clips).verdict == "regressed"
    runs, obs, clips = study()
    runs = [replace(x, first_audio_ms=900) if x.variant == "candidate"
            else x for x in runs]
    assert compare_stream_output_qoe(runs, obs, clips).verdict == "regressed"


def test_mismatched_or_duplicate_recording_fails_closed():
    runs, obs, clips = study()
    with pytest.raises(ValueError, match="duplicate"):
        compare_stream_output_qoe(runs, obs, clips + [clips[-1]])
    clips[-1] = replace(clips[-1], recording_sha256=clips[0].recording_sha256)
    with pytest.raises(ValueError, match="reused"):
        compare_stream_output_qoe(runs, obs, clips)
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1], game_version="v3")
    with pytest.raises(ValueError, match="scope"):
        compare_stream_output_qoe(runs, obs, clips)
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1], obs_session_id="new_process")
    with pytest.raises(ValueError, match="process"):
        compare_stream_output_qoe(runs, obs, clips)
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1], capture_start_ms=3500, capture_end_ms=11500)
    with pytest.raises(ValueError, match="inside"):
        compare_stream_output_qoe(runs, obs, clips)


def test_unfair_clips_are_rejected_not_interpreted_as_a_win():
    runs, obs, clips = study()
    clips[-1] = replace(clips[-1],
                        capture_end_ms=13200,
                        report=replace(good_report(), duration_ms=11200))
    obs[-2] = frame_window("pair023", "baseline", duration=13000)
    obs[-1] = frame_window("pair023", "candidate", duration=13000)
    with pytest.raises(ValueError, match="unfair"):
        compare_stream_output_qoe(runs, obs, clips)


@pytest.mark.parametrize("overrides", [
    {"capture_end_ms": 8100},  # cannot silently swap longer/shorter clips
    {"recording_sha256": "not-a-digest"},
    {"recording_sha256": "F" * 64},
    {"output_capture_attested": 1},
    {"isolated_star_audio_attested": "yes"},
    {"pair_id": "a\nsecret"},
    {"variant": "best"},
    {"report": "llm-says-good"},
    {"report": good_report(lag=99)},
    {"report": good_report(f1=float("nan"))},
    {"report": good_report(coverage=float("inf"))},
    {"report": good_report(silent=-0.01)},
    {"report": replace(good_report(), verified_humanlike=True)},
    {"report": replace(good_report(), automated_deployment_allowed=True)},
    {"report": replace(good_report(), audible_transitions=0)},
    {"report": replace(good_report(), sample_count=12)},
])
def test_invalid_observation_or_claim_rejected(overrides):
    with pytest.raises((ValueError, TypeError)):
        replace(recording_window("p", "candidate"), **overrides)


@pytest.mark.parametrize("value", [True, -1, 500, float("nan"), "5"])
def test_policy_limits_are_bounded(value):
    runs, obs, clips = study()
    with pytest.raises(ValueError):
        compare_stream_output_qoe(
            runs, obs, clips, max_extra_mouth_lag_ms=value,
        )
    with pytest.raises(ValueError):
        compare_stream_output_qoe(
            runs, obs, clips, max_f1_loss=value,
        )


def test_real_decoder_adapter_preserves_host_attestations():
    decoded = RecordingAVResult(
        report=good_report(), observed_frames=240, audio_track=1,
        calibration_separation=0.75, captured_output_attested=True,
        isolated_star_audio_attested=False,
    )
    params = dict(pair_id="p", variant="candidate", game_id="obby",
                  game_version="v2", obs_session_id="obs_candidate",
                  recording_sha256="a" * 64,
                  capture_start_ms=2000.0, capture_end_ms=10000.0)
    clip = OutputAVWindow.from_recording(**params, decoded=decoded)
    assert clip.report is decoded.report
    assert not clip.independently_usable
    with pytest.raises(TypeError):
        OutputAVWindow.from_recording(**params, decoded=good_report())
    with pytest.raises(ValueError, match="provenance"):
        OutputAVWindow.from_recording(
            **params, decoded=replace(decoded, provenance="external_model_assertion"),
        )


def test_no_data_does_not_claim_a_win():
    assert compare_stream_output_qoe([], [], []).verdict == "inconclusive"
    assert compare_stream_output_qoe([], [], []).complete_av_pairs == 0
