"""Synthetic contracts only: tests do NOT assert live microphone or GPU readings."""
import json
import math

import pytest

from star.stream_realtime_benchmark import RealtimeRun, compare_realtime, read_jsonl
from star.stream_trace_capture import HostStreamTrace


def trace(*, pair="pair1", variant="candidate", audible=True,
          finished=True, gpu=4800.0, first_audio=1180.0):
    collector = HostStreamTrace(
        pair_id=pair, variant=variant, game_id="Obby", game_version="v1",
        playback_epoch="epoch1", owner_approved=True,
    )
    collector.speech_requested(1000.0)
    collector.gpu_memory_observed(1010.0, used_mib=4200.0)
    if audible:
        collector.first_audio_audible(
            first_audio, playback_epoch="epoch1", sound_device_confirmed=True
        )
    for i in range(121):
        collector.presented_frame(1200 + 16.7 * i)
    collector.gpu_memory_observed(3230, used_mib=gpu)
    collector.audio_ended(3300, playback_epoch="epoch1", playback_finished=finished)
    return collector


def test_real_playback_event_converts_to_exact_eight_field_schema(tmp_path):
    c = trace()
    with pytest.raises(RuntimeError, match="finalize"):
        c.to_jsonl()
    row = c.finalize()
    assert isinstance(row, RealtimeRun)
    assert row.first_audio_ms == 180
    assert row.audio_finished is True
    assert row.gpu_peak_mib == 4800.0
    assert len(row.frame_times_ms) == 120
    assert all(n == pytest.approx(16.7) for n in row.frame_times_ms)
    line = c.to_jsonl()
    assert "chat" not in line.lower() and "playback" not in line.lower()
    assert set(json.loads(line)) == {
        "pair_id", "variant", "game_id", "game_version", "first_audio_ms",
        "frame_times_ms", "gpu_peak_mib", "audio_finished",
    }
    path = tmp_path / "host.jsonl"
    path.write_text(line, encoding="utf8")
    assert read_jsonl(path) == [row]
    with pytest.raises(RuntimeError, match="finalized"):
        c.presented_frame(3400)
    with pytest.raises(RuntimeError, match="finalized"):
        c.finalize()


def test_no_audible_output_becomes_failed_run_not_imaginary_fast_speech():
    c = trace(audible=False, finished=False)
    row = c.finalize()
    assert row.first_audio_ms == 120_000
    assert row.audio_finished is False
    pair = [row, trace(variant="baseline").finalize()]
    assert compare_realtime(pair).verdict == "regressed"


def test_host_has_to_ack_playback_not_merely_tts_generated():
    c = HostStreamTrace(pair_id="p", variant="candidate", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    c.speech_requested(1000)
    with pytest.raises(PermissionError, match="stale or foreign"):
        c.first_audio_audible(1090, playback_epoch="old-episode", sound_device_confirmed=True)
    with pytest.raises(PermissionError, match="stale or foreign"):
        c.audio_ended(1095, playback_epoch="old-episode", playback_finished=True)
    with pytest.raises(PermissionError, match="audio generation"):
        c.first_audio_audible(1100, playback_epoch="epoch1", sound_device_confirmed=False)
    with pytest.raises(ValueError, match="audible ACK"):
        c.audio_ended(1200, playback_epoch="epoch1", playback_finished=True)
    c.audio_ended(1201, playback_epoch="epoch1", playback_finished=False)
    with pytest.raises(RuntimeError, match="duplicate/ended"):
        c.first_audio_audible(1300, playback_epoch="epoch1", sound_device_confirmed=True)


def test_frame_and_gpu_samples_can_continue_after_short_utterance():
    c = HostStreamTrace(pair_id="x", variant="baseline", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    c.speech_requested(1000)
    c.first_audio_audible(1100, playback_epoch="epoch1", sound_device_confirmed=True)
    c.audio_ended(1150, playback_epoch="epoch1", playback_finished=True)
    c.gpu_memory_observed(1160, used_mib=3200)
    for i in range(121):
        c.presented_frame(1170 + 16.7 * i)
    assert c.finalize().audio_finished is True


def test_minimum_capture_and_host_gpu_sample_are_required():
    c = HostStreamTrace(pair_id="p", variant="baseline", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    with pytest.raises(RuntimeError, match="speech request"):
        c.presented_frame(100)
    c.speech_requested(100)
    with pytest.raises(RuntimeError, match="one speech request"):
        c.speech_requested(200)
    c.first_audio_audible(201, playback_epoch="epoch1", sound_device_confirmed=True)
    with pytest.raises(RuntimeError, match="duplicate"):
        c.first_audio_audible(202, playback_epoch="epoch1", sound_device_confirmed=True)
    c.audio_ended(210, playback_epoch="epoch1", playback_finished=True)
    with pytest.raises(RuntimeError, match="missing explicit"):
        other = HostStreamTrace(pair_id="z", variant="candidate",
                                game_id="g", game_version="v",
                                playback_epoch="epoch1", owner_approved=True)
        other.speech_requested(1)
        other.finalize()
    with pytest.raises(RuntimeError, match="120"):
        c.finalize()
    for i in range(121):
        c.presented_frame(220 + 17 * i)
    with pytest.raises(RuntimeError, match="GPU"):
        c.finalize()
    c.gpu_memory_observed(2280, used_mib=4000)
    assert c.finalize().first_audio_ms == 101


def test_reject_clock_reversal_forged_ids_and_bool_timestamps():
    with pytest.raises(PermissionError):
        HostStreamTrace(pair_id="p", variant="candidate", game_id="g",
                        game_version="v", playback_epoch="epoch1")
    for bad in ("../secret", "", "😺", "x" * 65):
        with pytest.raises(ValueError, match="opaque"):
            HostStreamTrace(pair_id=bad, variant="candidate", game_id="g",
                            game_version="v", playback_epoch="epoch1", owner_approved=True)
    with pytest.raises(ValueError, match="variant"):
        HostStreamTrace(pair_id="p", variant="not-a-route", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    c = HostStreamTrace(pair_id="p", variant="baseline", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    for bad in (True, math.inf, math.nan, -1, "100", 10**40):
        with pytest.raises(ValueError):
            c.speech_requested(bad)
    c.speech_requested(1000)
    with pytest.raises(ValueError, match="backward"):
        c.gpu_memory_observed(999, used_mib=3000)
    with pytest.raises(ValueError, match="GPU memory"):
        c.gpu_memory_observed(1100, used_mib=math.nan)
    with pytest.raises(ValueError, match="trusted boolean"):
        c.audio_ended(1200, playback_epoch="epoch1", playback_finished=1)
    c.presented_frame(1201)
    with pytest.raises(ValueError, match="interval"):
        c.presented_frame(1201)


def test_invalid_samples_never_become_benchmark_evidence():
    c = HostStreamTrace(pair_id="p", variant="candidate", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    c.speech_requested(100)
    with pytest.raises(ValueError, match="120 seconds"):
        c.first_audio_audible(120_101, playback_epoch="epoch1", sound_device_confirmed=True)
    with pytest.raises(RuntimeError, match="finalize"):
        c.to_jsonl()


def test_paired_runs_are_never_promoted_from_measurement_alone():
    observations = []
    for i in range(20):
        observations.append(trace(pair=f"p{i}", variant="baseline",
                                  first_audio=1170).finalize())
        observations.append(trace(pair=f"p{i}", variant="candidate",
                                  first_audio=1130).finalize())
    # These fabricated runs are only enough for an advisory manual pilot.
    report = compare_realtime(observations)
    assert report.complete_pairs == 20
    assert report.verdict == "eligible_for_manual_pilot"
    assert "automatic" in report.note


def test_frame_overflow_is_not_truncated_or_cherry_picked():
    c = HostStreamTrace(pair_id="p", variant="candidate", game_id="g",
                        game_version="v", playback_epoch="epoch1", owner_approved=True)
    c.speech_requested(1)
    for i in range(5001):
        c.presented_frame(2 + 16 * i)
    with pytest.raises(ValueError, match="exceeds 5000"):
        c.presented_frame(2 + 16 * 5001)
