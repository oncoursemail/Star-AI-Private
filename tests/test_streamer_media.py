"""Synthetic data; no real audio was listened to and no video was edited."""
import struct

import pytest

from star.streamer_media import (
    AudioMotionFrame, VocalRegion, VerifiedRecording, VerifiedMoment,
    audio_motion_frames, plan_highlights,
)


def pcm(seconds=1, value=10000, rate=16000):
    return struct.pack("<h", value) * (seconds * rate)


def moment(i, start, end, score=0.9, *, privacy=True, rights=True, category="funny"):
    return VerifiedMoment(f"moment-{i}", start, end, f"proof-{i}", score, category, rights, privacy)


def test_actual_pcm_amplitudes_not_text_generate_motion_cues():
    frames = audio_motion_frames(pcm(), 16000, (
        VocalRegion("speech", 0, 500), VocalRegion("laugh", 500, 1000),
    ))
    assert len(frames) == 50
    assert frames[0].speech > 0 and frames[0].laughter == 0
    assert frames[30].laughter > 0 and frames[30].speech == 0
    assert frames[0].amplitude > 0 and frames[-1].amplitude > 0
    assert frames[0].at_ms == 0 and frames[30].at_ms == 600


def test_silence_does_not_make_fake_laughter():
    frames = audio_motion_frames(pcm(value=0), 16000, (VocalRegion("laugh", 0, 1000),))
    assert all(f.laughter == 0 and f.speech == 0 for f in frames)
    assert all(f.amplitude == 0 for f in frames)


def test_raw_audio_alone_does_not_claim_speech_laughter_or_animal():
    frames = audio_motion_frames(pcm(), 16000)
    assert frames[0].amplitude > 0
    assert frames[0].speech == 0 and frames[0].laughter == 0
    assert frames[0].animal_sound == ""


def test_cat_puppy_region_tags_only_follow_external_verified_annotations():
    frames = audio_motion_frames(pcm(), 16000, (
        VocalRegion("purr", 0, 400), VocalRegion("woof", 400, 1000),
    ))
    assert frames[0].animal_sound == "purr" and frames[0].laughter == 0
    assert frames[30].animal_sound == "woof"


def test_pcm_invalid_inputs_and_unverified_region_rejected():
    with pytest.raises(ValueError):
        audio_motion_frames(b"", 16000)
    with pytest.raises(ValueError):
        audio_motion_frames(b"\x01", 16000)
    with pytest.raises(ValueError):
        audio_motion_frames(pcm(), 8000)
    with pytest.raises(ValueError):
        audio_motion_frames(pcm(), 16000, (VocalRegion("unknown", 0, 1000),))
    with pytest.raises(ValueError):
        audio_motion_frames(pcm(), 16000, (VocalRegion("laugh", 20, 99999),))
    with pytest.raises(ValueError):
        audio_motion_frames(pcm(), 16000, hop_ms=30)


def test_highlight_plan_requires_verified_recording():
    rec = VerifiedRecording("session-1", 60000, False)
    with pytest.raises(ValueError, match="verified"):
        plan_highlights(rec, (moment(1, 2000, 7000),))


def test_safe_rough_cuts_are_chronological_source_backed():
    rec = VerifiedRecording("session-1", 60000, True)
    result = plan_highlights(rec, (
        moment(2, 40000, 45000, score=0.91),
        moment(1, 5000, 12000, score=0.97),
    ), aspect="portrait")
    assert result.aspect == "portrait"
    assert [c.moment_id for c in result.cuts] == ["moment-1", "moment-2"]
    assert [(c.source_start_ms, c.source_end_ms) for c in result.cuts] == [
        (4000, 13000), (39000, 46000),
    ]
    assert result.output_duration_ms == 16000
    assert all(c.evidence_id.startswith("proof-") for c in result.cuts)


def test_editor_skips_private_uncleared_or_low_quality_moments():
    rec = VerifiedRecording("session-1", 30000, True)
    result = plan_highlights(rec, (
        moment(1, 1000, 2000, privacy=False),
        moment(2, 3000, 4000, rights=False),
        moment(3, 5000, 6000, score=0.1),
        moment(4, 7000, 9000, score=0.9),
    ))
    assert [c.moment_id for c in result.cuts] == ["moment-4"]


def test_nonoverlap_and_budget_keep_edit_valid():
    rec = VerifiedRecording("session-1", 60000, True)
    result = plan_highlights(rec, (
        moment(1, 5000, 14000, score=1.0),
        moment(2, 8000, 15000, score=0.9),
        moment(3, 40000, 50000, score=0.95),
    ), budget_ms=12500)
    assert len(result.cuts) == 1
    assert result.cuts[0].moment_id == "moment-1"
    assert result.output_duration_ms <= 12500


def test_edl_duplicate_invalid_range_and_unverified_evidence_rejected():
    rec = VerifiedRecording("session-1", 20000, True)
    with pytest.raises(ValueError, match="duplicate"):
        plan_highlights(rec, (moment(1, 2000, 3000), moment(1, 4000, 5000)))
    with pytest.raises(ValueError, match="out-of-range"):
        plan_highlights(rec, (moment(2, 1000, 40000),))
    with pytest.raises(ValueError):
        plan_highlights(rec, (moment(3, 1000, 3000),), aspect="square")


def test_rough_cut_never_exports_or_posts():
    result = plan_highlights(VerifiedRecording("session-1", 20000, True),
                             (moment(1, 1000, 3000),))
    assert result.cuts
    assert not hasattr(result, "upload_url")
    assert not hasattr(result, "rendered_video_path")
