"""Synthetic OFFLINE tests only; they cannot certify a real game or recording."""
from __future__ import annotations

from dataclasses import replace
import json
from typing import cast

import pytest

from star.game_state_transition_witness import AttestedGameMoment
from star.native_game_roundtrip_audit import NativeRoundtripReport
from star.stream_av_recording_host import RecordingAVResult
from star.stream_av_sync_audit import AVSyncReport
from star.stream_episode_journal import GameMoment
from star.stream_moment_receipts import sign_game_moment
from star.stream_obs_readonly_evidence import ObsCounters
from star.stream_obs_recording_artifact_probe import RecordingArtifactReport
from star.stream_private_rehearsal_scorecard import score_private_vtuber_rehearsal
from star.stream_windows_private_rehearsal_cli import PrivateRehearsalReadiness

_KEY = b"k" * 32
_SESSION = "a" * 32


def _reports() -> dict:
    moment = GameMoment("checkpoint.r1.p2", "private_game", "checkpoint", 100.0, "cp2")
    return {
        "owner_approved": True,
        "host_confirms_same_session": True,
        "host_confirms_same_recording": True,
        "host_confirms_broadcast_inactive": True,
        "readiness": PrivateRehearsalReadiness(
            "candidate", (), 5, 3200, 2048, 40, True, True,
        ),
        "native": NativeRoundtripReport(
            "host_roundtrip_only", 3, 3, 140, 50, 200,
            observed_frames=10, no_action_frames=7,
            host_frame_coverage_declared=True, all_frame_decision_p95_ms=140,
        ),
        "game_moment": AttestedGameMoment(
            moment, sign_game_moment(moment, session_id=_SESSION, sequence=1, key=_KEY), 102.0,
        ),
        "receipt_session_id": _SESSION,
        "receipt_key": _KEY,
        "recording": RecordingArtifactReport(
            "candidate_for_owner_review", 10.0, 300, 1280, 720, 1, 0,
        ),
        "av": RecordingAVResult(
            AVSyncReport(
                "eligible_for_owner_review", "acceptable_sync", 300, 10000.0,
                estimated_mouth_lag_ms=20, best_alignment_f1=.94,
            ),
            300, 0, .75, True, True,
        ),
        "obs_before": ObsCounters(1000, 12, 500, 7, 490),
        "obs_after": ObsCounters(11000, 14, 800, 8, 790),
    }


def test_all_five_independent_report_families_agree_advisory_only():
    result = score_private_vtuber_rehearsal(**_reports())
    assert result.status == "candidate_for_owner_review"
    assert result.missing == ()
    assert result.game_state_receipt_valid is True
    assert result.native_actions_completed == 3
    assert result.observed_native_frames == 10
    assert result.obs_presented_frames == 300
    assert result.obs_output_frames == 300
    assert result.obs_render_drop_pct == .667
    assert result.obs_output_drop_pct == .333
    assert result.av_mouth_lag_ms == 20
    assert not result.authorizes_gameplay
    assert not result.authorizes_broadcast
    assert not result.certifies_humanlike_behavior
    assert not result.certifies_game_mastery
    serialized = result.to_json()
    assert json.loads(serialized)["status"] == "candidate_for_owner_review"
    assert _SESSION not in serialized
    assert _KEY.decode() not in serialized
    assert "private_game" not in serialized


@pytest.mark.parametrize("flag,reason", [
    ("host_confirms_same_session", "host_session_correlation_missing"),
    ("host_confirms_same_recording", "host_recording_identity_missing"),
    ("host_confirms_broadcast_inactive", "host_private_broadcast_state_missing"),
])
def test_missing_session_recording_and_nonbroadcast_host_claims_defer(flag, reason):
    data = _reports()
    data[flag] = False
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert reason in result.missing
    assert not result.authorizes_broadcast


@pytest.mark.parametrize("field,reason", [
    ("readiness", "sustained_game_gpu_readiness_missing"),
    ("native", "native_gameplay_frame_and_release_audit_missing"),
    ("game_moment", "corroborated_game_state_receipt_missing"),
    ("recording", "decoded_private_obs_recording_missing"),
    ("av", "audible_star_avatar_alignment_missing"),
    ("obs_after", "obs_counter_window_missing"),
])
def test_a_single_missing_domain_never_inherits_positive_evidence(field, reason):
    data = _reports()
    data[field] = None
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert reason in result.missing


@pytest.mark.parametrize("update", [
    {"min_free_gpu_mib": 449}, {"game_process_pinned": False},
    {"stable_processes": False}, {"status": "deferred"},
])
def test_insufficient_gpu_or_unpinned_game_deferred(update):
    data = _reports()
    data["readiness"] = replace(data["readiness"], **update)
    assert "sustained_game_gpu_readiness_missing" in score_private_vtuber_rehearsal(**data).missing


@pytest.mark.parametrize("update", [
    {"status": "decision_only_no_input", "attempted": 0, "completed": 0},
    {"host_frame_coverage_declared": False},
    {"completed": 2}, {"observed_frames": 9},
    {"frame_to_release_p95_ms": 1050},
    {"inference_p95_ms": None},
])
def test_unverified_stale_incomplete_and_no_action_only_native_measurements_defer(update):
    data = _reports()
    data["native"] = replace(data["native"], **update)
    assert "native_gameplay_frame_and_release_audit_missing" in (
        score_private_vtuber_rehearsal(**data).missing
    )


def test_hmac_binds_state_not_the_title_of_a_performance_claim():
    data = _reports()
    data["receipt_session_id"] = "b" * 32
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert not result.game_state_receipt_valid
    assert "corroborated_game_state_receipt_missing" in result.missing


def test_game_event_cannot_be_replayed_as_another_game_or_backdated():
    data = _reports()
    source = data["game_moment"]
    data["game_moment"] = replace(
        source, moment=replace(source.moment, game_scope="another_game"),
    )
    assert not score_private_vtuber_rehearsal(**data).game_state_receipt_valid
    data = _reports()
    data["game_moment"] = replace(data["game_moment"], now_s=1000.0)
    assert not score_private_vtuber_rehearsal(**data).game_state_receipt_valid


def test_decodable_media_and_synthetic_av_without_actual_output_witness_are_not_success():
    data = _reports()
    data["recording"] = replace(data["recording"], local_media_decoded=False)
    data["av"] = replace(data["av"], captured_output_attested=False)
    result = score_private_vtuber_rehearsal(**data)
    assert "decoded_private_obs_recording_missing" in result.missing
    assert "audible_star_avatar_alignment_missing" in result.missing


def test_mismatched_recording_audio_track_and_unsynchronized_mouth_block_review():
    data = _reports()
    data["av"] = replace(data["av"], audio_track=1)
    assert "audible_star_avatar_alignment_missing" in score_private_vtuber_rehearsal(**data).missing
    data = _reports()
    data["av"] = replace(
        data["av"], report=replace(data["av"].report, verdict="needs_improvement"),
    )
    assert "audible_star_avatar_alignment_missing" in score_private_vtuber_rehearsal(**data).missing


@pytest.mark.parametrize("after,reason", [
    (ObsCounters(11000, 14, 510, 8, 500), "obs_frame_continuity_missing"),
    (ObsCounters(11000, 14, 800, 8, 489), "obs_frame_continuity_missing"),
    (ObsCounters(11000, 30, 800, 8, 790), "obs_frame_drops_exceeded"),
    (ObsCounters(11000, 14, 800, 100, 790), "obs_frame_drops_exceeded"),
    (ObsCounters(3000, 14, 800, 8, 790), "obs_counter_window_duration_invalid"),
    (ObsCounters(11000, 14, 800, 8, cast(int, 790.5)), "obs_counter_window_invalid"),
    (ObsCounters(11000, True, 800, 8, 790), "obs_counter_window_invalid"),
])
def test_real_obs_render_and_encode_metrics_must_span_contiguous_good_window(after, reason):
    data = _reports()
    data["obs_after"] = after
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert reason in result.missing


@pytest.mark.parametrize("kwargs", [
    {"max_obs_drop_pct": float("nan")}, {"max_obs_drop_pct": True},
    {"max_native_p95_ms": float("inf")}, {"max_native_p95_ms": 0},
    {"minimum_gpu_free_mib": 0}, {"minimum_gpu_free_mib": True},
    {"host_confirms_same_session": 1},
])
def test_refuses_unbounded_or_ambiguous_host_configuration(kwargs):
    data = _reports()
    data.update(kwargs)
    with pytest.raises(ValueError):
        score_private_vtuber_rehearsal(**data)


def test_scorecard_fails_without_local_owner_opt_in():
    data = _reports()
    data["owner_approved"] = False
    with pytest.raises(PermissionError):
        score_private_vtuber_rehearsal(**data)


def test_unrealistic_obs_counter_rate_is_not_accepted_as_smooth_footage():
    data = _reports()
    data["obs_after"] = ObsCounters(11000, 14, 50000, 8, 50000)
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert "obs_frame_rate_outside_rehearsal_bounds" in result.missing


def test_inconsistent_native_latency_statistics_cannot_look_complete():
    data = _reports()
    data["native"] = replace(data["native"], frame_to_release_p95_ms=100)
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert "native_gameplay_frame_and_release_audit_missing" in result.missing


def test_obs_drop_boundary_is_strict_without_rounding_before_comparison():
    data = _reports()
    # 6/300=2% exactly; allowed, subject to all other checks.
    data["obs_after"] = ObsCounters(11000, 18, 800, 8, 790)
    assert score_private_vtuber_rehearsal(**data).status == "candidate_for_owner_review"
    # 7/300 exceeds the same acceptance budget.
    data["obs_after"] = ObsCounters(11000, 19, 800, 8, 790)
    assert "obs_frame_drops_exceeded" in score_private_vtuber_rehearsal(**data).missing


# These synthetic tests probe collisions between independently passing lanes.
# They do NOT establish artifact origin or prove a real VTuber rehearsal.
@pytest.mark.parametrize("change,reason", [
    ({"duration_s": 12.0}, "recording_obs_duration_mismatch"),
    ({"video_frames": 220}, "recording_obs_frame_count_mismatch"),
    ({"video_frames": 500}, "recording_obs_frame_count_mismatch"),
    ({"duration_s": float("nan")}, "private_recording_metadata_inconsistent"),
    ({"video_frames": True}, "private_recording_metadata_inconsistent"),
    ({"audio_streams": 0}, "private_recording_metadata_inconsistent"),
    ({"selected_audio_track": 1}, "private_recording_metadata_inconsistent"),
    ({"video_width": -1}, "private_recording_metadata_inconsistent"),
])
def test_valid_individual_recording_report_can_conflict_with_other_lanes(change, reason):
    data = _reports()
    data["recording"] = replace(data["recording"], **change)
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert reason in result.missing
    assert not result.authorizes_broadcast


@pytest.mark.parametrize("change,reason", [
    ({"duration_ms": 12000}, "recording_av_duration_mismatch"),
    ({"duration_ms": float("nan")}, "recording_av_sample_timeline_missing"),
    ({"sample_count": 200}, "recording_av_alignment_statistics_invalid"),
    ({"best_alignment_f1": float("nan")}, "recording_av_alignment_statistics_invalid"),
    ({"estimated_mouth_lag_ms": 300}, "recording_av_alignment_statistics_invalid"),
    ({"verified_humanlike": True}, "recording_av_alignment_statistics_invalid"),
    ({"automated_deployment_allowed": True}, "recording_av_alignment_statistics_invalid"),
])
def test_valid_looking_av_verdict_is_not_enough_without_consistent_statistics(change, reason):
    data = _reports()
    data["av"] = replace(data["av"], report=replace(data["av"].report, **change))
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert reason in result.missing


def test_audio_frames_from_different_clip_must_not_pass_same_session_claim():
    data = _reports()
    data["av"] = replace(data["av"], observed_frames=210)
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert "recording_av_frame_rate_mismatch" in result.missing


def test_frame_rate_crosschecks_do_not_confuse_mixed_obs_and_clip_counts():
    data = _reports()
    data["obs_after"] = ObsCounters(11000, 14, 800, 8, 950)
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "deferred"
    assert "recording_obs_frame_count_mismatch" in result.missing


def test_small_recording_stop_offset_within_tolerance_remains_review_candidate():
    data = _reports()
    data["recording"] = replace(data["recording"], duration_s=10.3, video_frames=302)
    data["av"] = replace(data["av"], report=replace(data["av"].report, duration_ms=10290))
    # 30 Hz resampling: 309 samples for 10.29 seconds.
    data["av"] = replace(data["av"], observed_frames=309,
                         report=replace(data["av"].report, sample_count=309))
    result = score_private_vtuber_rehearsal(**data)
    assert result.status == "candidate_for_owner_review"
    assert result.missing == ()
