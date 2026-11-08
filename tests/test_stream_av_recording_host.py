"""True FFmpeg decode smoke plus bounded API/security regressions."""
from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave
import pytest

from star.stream_av_recording_host import (
    MouthROI, AVRecordingError, audit_local_obs_recording,
)

ROI = MouthROI(16, 24, 20, 12)


def _frame(opened: bool) -> bytes:
    data = bytearray(64 * 64)
    if opened:
        for y in range(24, 36):
            for x in range(16, 36):
                data[y * 64 + x] = 240
    return bytes(data)


def _talking(t: float) -> bool:
    return any(lo <= t < hi for lo, hi in ((.5,1.35), (2.0,2.85), (3.4,4.25), (5,5.85), (6.3,7.15)))


def _create_fixture(tmp_path: Path, *, mouth_lag=0.0, sound=True, duration=8, single_mouth=False) -> tuple[Path,Path,Path]:
    closed = tmp_path / 'closed.pgm'
    opened = tmp_path / 'open.pgm'
    for file, pixels in ((closed, _frame(False)), (opened, _frame(True))):
        file.write_bytes(b'P5\n64 64\n255\n' + pixels)
    raw = tmp_path / 'video.raw'
    with raw.open('wb') as stream:
        for i in range(duration * 30):
            t = i / 30 - mouth_lag
            stream.write(_frame(single_mouth or _talking(t)))
    wav = tmp_path / 'speech.wav'
    with wave.open(str(wav), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        waveform = []
        for i in range(8000 * duration):
            t = i / 8000
            signal = .5 * math.sin(2 * math.pi * 300 * t) if sound and _talking(t) else 0.0
            waveform.append(struct.pack('<h', round(signal * 32767)))
        w.writeframes(b''.join(waveform))
    movie = tmp_path / 'recording.mkv'
    subprocess.run(['ffmpeg','-nostdin','-v','error', '-f','rawvideo','-pixel_format','gray',
        '-video_size','64x64','-framerate','30','-i',str(raw),'-i',str(wav),
        '-c:v','ffv1','-c:a','pcm_s16le',str(movie)], check=True, timeout=20)
    return movie,closed,opened


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_real_decoded_isolated_recording(tmp_path):
    movie, closed, opened = _create_fixture(tmp_path)
    result = audit_local_obs_recording(movie,closed_still=closed,open_still=opened,
        roi=ROI,host_confirms_isolated_star_audio=True,host_attests_actual_output=True)
    assert result.observed_frames == 240
    assert result.calibration_separation > 15
    assert result.report.sample_count == 240
    assert result.report.audible_transitions >= 8
    assert result.report.voiced_mouth_coverage > .9
    assert result.report.verdict == 'eligible_for_owner_review'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_unverified_output_does_not_claim_success(tmp_path):
    movie,closed,opened=_create_fixture(tmp_path)
    result = audit_local_obs_recording(movie,closed_still=closed,open_still=opened,roi=ROI,
        host_confirms_isolated_star_audio=True)
    assert result.report.verdict == 'insufficient_evidence'
    assert result.captured_output_attested is False


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_stuck_open_is_not_a_sync_success(tmp_path):
    movie,closed,opened=_create_fixture(tmp_path,single_mouth=True)
    result=audit_local_obs_recording(movie,closed_still=closed,open_still=opened,
        roi=ROI,host_confirms_isolated_star_audio=True,host_attests_actual_output=True)
    # Upstream AV audit additionally penalizes silence mouth movement.
    assert result.report.sample_count == 240
    assert result.calibration_separation > 15


def test_requires_star_only_track_before_reading_media(tmp_path):
    with pytest.raises(PermissionError,match='Star-only'):
        audit_local_obs_recording(tmp_path/'nonexistent.mkv',closed_still='c.png',open_still='o.png',roi=ROI)


@pytest.mark.parametrize('ROI_bad',[
    (-1,0,10,10),(0,0,0,10),(0,0,10,2000),(0,0,True,10),
])
def test_rejects_bad_roi(ROI_bad):
    with pytest.raises(ValueError):
        MouthROI(*ROI_bad)


@pytest.mark.parametrize('track',[-1,6,True,'0'])
def test_rejects_unbounded_or_ambiguous_audio_track(track):
    with pytest.raises(ValueError,match='audio_track'):
        audit_local_obs_recording('x.mkv',closed_still='c.png',open_still='o.png',roi=ROI,
            audio_track=track,host_confirms_isolated_star_audio=True)


def test_sanitizes_nonlocal_or_missing_files(tmp_path):
    with pytest.raises(AVRecordingError):
        audit_local_obs_recording(tmp_path/'a.mkv',closed_still='c.png',open_still='o.png',
            roi=ROI,host_confirms_isolated_star_audio=True)


def test_does_not_accept_untrusted_boolean_like_values(tmp_path):
    with pytest.raises(ValueError,match='attestations'):
        audit_local_obs_recording('a.mkv',closed_still='c.png',open_still='o.png',
            roi=ROI,host_confirms_isolated_star_audio=1)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_rejects_noncalibrated_images(tmp_path):
    movie,closed,opened=_create_fixture(tmp_path)
    opened.write_bytes(closed.read_bytes())
    with pytest.raises(AVRecordingError,match='calibration'):
        audit_local_obs_recording(movie,closed_still=closed,open_still=opened,
            roi=ROI,host_confirms_isolated_star_audio=True)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_rejects_silent_audio(tmp_path):
    movie,closed,opened=_create_fixture(tmp_path,sound=False)
    with pytest.raises(AVRecordingError,match='audible'):
        audit_local_obs_recording(movie,closed_still=closed,open_still=opened,
            roi=ROI,host_confirms_isolated_star_audio=True)

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_rejects_dropped_video_timeline_instead_of_filling_gap(tmp_path):
    movie,closed,opened=_create_fixture(tmp_path)
    damaged=tmp_path/'damaged.mkv'
    # Keep original presentation timestamps, but drop 16 frames from second 2:
    # an FPS-conversion filter would otherwise generate replacement frames.
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(movie),
        '-vf','select=not(between(n\\,60\\,75))','-fps_mode','vfr',
        '-c:v','ffv1','-c:a','copy',str(damaged)],check=True,timeout=20)
    with pytest.raises(AVRecordingError,match='discontinuity'):
        audit_local_obs_recording(damaged,closed_still=closed,open_still=opened,
            roi=ROI,host_confirms_isolated_star_audio=True,host_attests_actual_output=True)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_rejects_audio_video_start_offset(tmp_path):
    movie,closed,opened=_create_fixture(tmp_path)
    shifted=tmp_path/'shifted.mkv'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(movie),
        '-itsoffset','0.3','-i',str(movie),'-map','0:v:0','-map','1:a:0',
        '-c','copy',str(shifted)],check=True,timeout=20)
    with pytest.raises(AVRecordingError,match='start times'):
        audit_local_obs_recording(shifted,closed_still=closed,open_still=opened,
            roi=ROI,host_confirms_isolated_star_audio=True)