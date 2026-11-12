"""Unit tests for callback-level playback telemetry without an audio device."""
import pytest

from star.voice.playback import PlaybackTelemetry


def test_first_nonempty_output_callback_and_underflows_are_counted():
    telemetry = PlaybackTelemetry()
    telemetry.record_callback(frames=128, emitted_frames=0, at=1.0)
    telemetry.record_callback(frames=128, emitted_frames=64, at=1.01)
    telemetry.record_callback(frames=128, emitted_frames=128, output_underflow=True, at=1.02)
    snapshot = telemetry.snapshot()
    assert snapshot.first_playback_at == pytest.approx(1.01)
    assert snapshot.output_callbacks_with_audio == 2
    assert snapshot.output_underflows == 1


def test_reset_starts_a_fresh_reply_window():
    telemetry = PlaybackTelemetry()
    telemetry.record_callback(frames=64, emitted_frames=64, output_underflow=True, at=4.0)
    telemetry.reset()
    snapshot = telemetry.snapshot()
    assert snapshot.first_playback_at is None
    assert snapshot.output_callbacks_with_audio == 0
    assert snapshot.output_underflows == 0


@pytest.mark.parametrize("kwargs", [
    {"frames": True, "emitted_frames": 0},
    {"frames": 10, "emitted_frames": -1},
    {"frames": 10, "emitted_frames": 11},
    {"frames": 10, "emitted_frames": 0, "output_underflow": 1},
    {"frames": 10, "emitted_frames": 0, "at": float("nan")},
])
def test_invalid_callback_observations_are_rejected(kwargs):
    telemetry = PlaybackTelemetry()
    with pytest.raises(ValueError):
        telemetry.record_callback(**kwargs)



def test_idle_underflow_flag_does_not_count_as_playback_dropout():
    telemetry = PlaybackTelemetry()
    telemetry.record_callback(frames=128, emitted_frames=0, output_underflow=True, at=2.0)
    snapshot = telemetry.snapshot()
    assert snapshot.output_underflows == 0
    assert snapshot.output_callbacks_with_audio == 0
