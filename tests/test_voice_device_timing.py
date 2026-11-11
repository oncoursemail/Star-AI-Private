"""PortAudio stream-clock mapping tests without opening a physical audio device."""
import threading
from types import SimpleNamespace

import pytest

from star.voice import devices
from star.voice.devices import _device_output_monotonic


def test_portaudio_dac_time_maps_to_host_monotonic_clock():
    info = SimpleNamespace(currentTime=10.0, outputBufferDacTime=10.024)
    assert _device_output_monotonic(50.0, info) == pytest.approx(50.024)


def test_small_negative_dac_offset_is_clamped_to_callback_time():
    info = SimpleNamespace(currentTime=10.0, outputBufferDacTime=9.99)
    assert _device_output_monotonic(50.0, info) == pytest.approx(50.0)


@pytest.mark.parametrize(
    "info",
    [
        None,
        SimpleNamespace(currentTime=float("nan"), outputBufferDacTime=10.0),
        SimpleNamespace(currentTime=10.0, outputBufferDacTime=float("inf")),
        SimpleNamespace(currentTime=10.0, outputBufferDacTime=12.0),
        SimpleNamespace(currentTime=10.0, outputBufferDacTime=9.0),
        SimpleNamespace(currentTime="bad", outputBufferDacTime=10.0),
    ],
)
def test_invalid_or_implausible_portaudio_clock_mapping_is_unknown(info):
    assert _device_output_monotonic(50.0, info) is None


def test_nonfinite_host_clock_is_rejected():
    info = SimpleNamespace(currentTime=10.0, outputBufferDacTime=10.01)
    assert _device_output_monotonic(float("nan"), info) is None


class _FakeRawOutputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def _fake_speaker(monkeypatch):
    fake_sounddevice = SimpleNamespace(RawOutputStream=_FakeRawOutputStream)
    monkeypatch.setattr(devices, "_sounddevice", lambda: fake_sounddevice)
    return devices.SoundSpeaker(sample_rate=24000)


def test_pcm_rms_is_computed_from_native_pcm16_without_numpy():
    assert devices._pcm_rms(b"\x00\x40" * 8) == pytest.approx(0.5)
    assert devices._pcm_rms(b"\x00\x00" * 8) == 0.0
    assert devices._pcm_rms(b"\x01") == 0.0


def test_output_callback_does_not_wait_for_level_meter_worker(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original_rms = devices._pcm_rms

    def slow_rms(pcm):
        entered.set()
        release.wait(2.0)
        return original_rms(pcm)

    monkeypatch.setattr(devices, "_pcm_rms", slow_rms)
    speaker = _fake_speaker(monkeypatch)
    pcm = b"\x00\x40" * 8
    output = bytearray(len(pcm))
    returned = threading.Event()
    callback_thread = threading.Thread(
        target=lambda: (speaker._callback(
            output, len(pcm) // 2,
            SimpleNamespace(currentTime=1.0, outputBufferDacTime=1.0), None
        ), returned.set()),
        daemon=True,
    )
    try:
        speaker.play(pcm, 24000)
        callback_thread.start()
        assert entered.wait(1.0)
        assert returned.wait(0.2)
        assert bytes(output) == pcm
        # Until the asynchronous meter catches up, the echo gate must not mistake
        # unknown speaker output for silence.
        assert speaker.level() == 1.0

        more = pcm * 65
        speaker.play(more, 24000)
        last_output = bytearray(len(pcm))
        for _ in range(65):
            last_output = bytearray(len(pcm))
            speaker._callback(
                last_output, len(pcm) // 2,
                SimpleNamespace(currentTime=1.0, outputBufferDacTime=1.0), None
            )
        assert bytes(last_output) == pcm
        assert speaker.pending_seconds() == 0.0
        assert speaker.played_seconds() == pytest.approx(66 * (len(pcm) // 2) / 24000)
        assert speaker.dropped_level_blocks >= 1
        assert speaker.level() == 1.0
    finally:
        release.set()
        callback_thread.join(1.0)
        speaker.close()
    assert speaker._level_worker is not None
    assert not speaker._level_worker.is_alive()
