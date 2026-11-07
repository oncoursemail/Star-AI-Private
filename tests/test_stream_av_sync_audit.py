"""Adversarial tests for output-observed Star audio/avatar alignment."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from star.stream_av_sync_audit import OutputAVSample, audit_output_av_sync


def clip(*, lag_ms: int = 0, mouth_override: float | None = None,
         count: int = 800, step_ms: float = 40.0):
    """Synthetic square-wave with alternating 1-second speech and silence."""
    frames = []
    for index in range(count):
        now = index * step_ms
        audible = int(now // 1000) % 2 == 0
        mouth_phase = int((now - lag_ms) // 1000) % 2 == 0
        frames.append(OutputAVSample(
            now, 0.9 if audible else 0.0,
            (0.9 if mouth_phase else 0.0) if mouth_override is None else mouth_override,
        ))
    return tuple(frames)


def test_good_output_synchronization_is_advisory_only():
    report = audit_output_av_sync(clip(), output_capture_attested=True)
    assert report.verdict == "eligible_for_owner_review"
    assert report.estimated_mouth_lag_ms == 0
    assert report.best_alignment_f1 == 1
    assert report.voiced_mouth_coverage == 1
    assert report.silent_mouth_rate == 0
    assert report.audible_transitions >= 6
    assert not report.verified_humanlike
    assert not report.automated_deployment_allowed


@pytest.mark.parametrize("lag", [-200, 200])
def test_real_lip_sync_displacement_is_measured_and_rejected(lag):
    report = audit_output_av_sync(clip(lag_ms=lag), output_capture_attested=True)
    # Render sampling and 20 ms lag bins limit timing precision to ~one frame.
    assert abs(report.estimated_mouth_lag_ms - lag) <= 20
    assert report.verdict == "needs_improvement"
    assert report.zero_lag_f1 < report.best_alignment_f1
    assert report.best_alignment_f1 > .95


def test_small_delay_is_reviewable_not_a_claim_of_human_naturalness():
    report = audit_output_av_sync(clip(lag_ms=80), output_capture_attested=True)
    assert report.estimated_mouth_lag_ms == 80
    assert report.verdict == "eligible_for_owner_review"
    assert not report.verified_humanlike


@pytest.mark.parametrize("mouth", [0.0, 1.0])
def test_stuck_mouth_fails_instead_of_scoring_quiet_frames(mouth):
    report = audit_output_av_sync(clip(mouth_override=mouth),
                                  output_capture_attested=True)
    assert report.verdict == "needs_improvement"
    assert report.best_alignment_f1 < .85


def test_untrusted_simulated_capture_cannot_claim_output_sync():
    report = audit_output_av_sync(clip(), output_capture_attested=False)
    assert report.reason == "actual_output_capture_not_attested"
    assert report.verdict == "insufficient_evidence"
    assert report.best_alignment_f1 == 1


def test_silence_and_no_transitions_are_not_false_success():
    frames = tuple(OutputAVSample(i * 40.0, 0.0, 0.0) for i in range(800))
    report = audit_output_av_sync(frames, output_capture_attested=True)
    assert report.verdict == "insufficient_evidence"
    assert report.reason == "insufficient_speech_silence_transitions"


def test_short_audio_clip_or_tiny_cohort_is_inconclusive():
    short = audit_output_av_sync(clip(count=30), output_capture_attested=True)
    assert short.verdict == "insufficient_evidence"
    assert short.reason == "too_few_samples"
    duration = audit_output_av_sync(clip(count=180, step_ms=20.0),
                                    output_capture_attested=True)
    assert duration.reason == "duration_outside_window"


@pytest.mark.parametrize("at,audio,mouth", [
    (True, .2, .3), (float("nan"), .2, .3),
    (float("inf"), .2, .3), (-1, .2, .3),
    (0, float("nan"), .3), (0, -.01, .3),
    (0, 1.01, .3), (0, .2, True),
    (0, .2, 1.01),
])
def test_input_validation_rejects_bad_numbers(at, audio, mouth):
    with pytest.raises(ValueError):
        OutputAVSample(at, audio, mouth)


@pytest.mark.parametrize("condition", ["reversed", "duplicate", "large_gap", "tiny_gap"])
def test_capture_clock_tampering_fails_closed(condition):
    frames = list(clip())
    replacement = {
        "reversed": frames[10].at_ms - 200,
        "duplicate": frames[10].at_ms,
        "large_gap": frames[10].at_ms + 150,
        "tiny_gap": frames[10].at_ms + 1,
    }[condition]
    frames[11] = OutputAVSample(
        replacement, frames[11].audio_rms, frames[11].mouth_open,
    )
    with pytest.raises(ValueError, match="strictly ordered"):
        audit_output_av_sync(tuple(frames), output_capture_attested=True)


def test_invalid_collection_or_host_attestation_never_processed():
    frames = clip()
    with pytest.raises(ValueError):
        audit_output_av_sync(frames, output_capture_attested="yes")
    with pytest.raises(TypeError):
        audit_output_av_sync(frames[:-1] + (None,), output_capture_attested=True)
    with pytest.raises(ValueError):
        audit_output_av_sync(frames * 11, output_capture_attested=True)
    with pytest.raises(ValueError):
        audit_output_av_sync(iter(frames), output_capture_attested=True)


def test_report_and_samples_are_immutable_and_do_not_expose_content():
    frames = clip()
    report = audit_output_av_sync(frames, output_capture_attested=True)
    with pytest.raises(FrozenInstanceError):
        report.verdict = "passed"
    with pytest.raises(FrozenInstanceError):
        frames[0].audio_rms = 1
    assert "recording" not in report.__dict__
    assert "text" not in report.__dict__
    assert "viewer" not in report.__dict__
