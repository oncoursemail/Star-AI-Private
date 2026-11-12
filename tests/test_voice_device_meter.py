"""Hardware-free tests for the asynchronous PortAudio speaker level meter."""
from __future__ import annotations

import struct
import threading
import time
from types import SimpleNamespace

import pytest

from star.voice import devices


class FakeRawOutputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.stopped = 0
        self.closed = 0

    def start(self):
        pass

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed += 1


def make_speaker(monkeypatch):
    fake = SimpleNamespace(RawOutputStream=FakeRawOutputStream)
    monkeypatch.setattr(devices, "_sounddevice", lambda: fake)
    return devices.SoundSpeaker(sample_rate=24000)


def emit(speaker, pcm: bytes, *, underflow: bool = False) -> bytes:
    frames = len(pcm) // 2
    output = bytearray(frames * 2)
    speaker._callback(
        output,
        frames,
        SimpleNamespace(currentTime=1.0, outputBufferDacTime=1.0),
        SimpleNamespace(output_underflow=underflow),
    )
    return bytes(output)


def wait_for_meter(speaker, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (
            speaker._level_processed_seq >= speaker._level_submitted_seq
            and not speaker._level_queue
        ):
            return True
        time.sleep(0.005)
    return False


def test_pcm_rms_uses_native_pcm16_and_handles_empty_or_malformed_data():
    half_scale = struct.pack("=h", 16384) * 8
    assert devices._pcm_rms(half_scale) == pytest.approx(0.5)
    assert devices._pcm_rms(b"\x00\x00" * 8) == 0.0
    assert devices._pcm_rms(b"\x01") == 0.0
    assert devices._pcm_rms(b"") == 0.0


def test_callback_preserves_pcm_and_playback_telemetry_while_worker_measures_level(monkeypatch):
    speaker = make_speaker(monkeypatch)
    pcm = struct.pack("=h", 16384) * 8
    try:
        speaker.play(pcm, 24000)
        assert emit(speaker, pcm, underflow=True) == pcm
        snapshot = speaker.playback_snapshot()
        assert snapshot.first_playback_at is not None
        assert snapshot.output_callbacks_with_audio == 1
        assert snapshot.output_underflows == 1
        assert wait_for_meter(speaker)
        assert speaker.level() == pytest.approx(0.5)
    finally:
        speaker.close()


def test_slow_meter_worker_never_blocks_audio_callback(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    original = devices._pcm_rms

    def slow_meter(pcm):
        entered.set()
        release.wait(2.0)
        return original(pcm)

    monkeypatch.setattr(devices, "_pcm_rms", slow_meter)
    speaker = make_speaker(monkeypatch)
    pcm = struct.pack("=h", 8192) * 8
    try:
        speaker.play(pcm, 24000)

        def run_callback():
            emit(speaker, pcm)
            returned.set()

        callback_thread = threading.Thread(target=run_callback, daemon=True)
        callback_thread.start()
        assert entered.wait(1.0)
        assert returned.wait(0.2), "audio callback waited for the RMS worker"
        assert speaker.level() == 1.0  # pending telemetry is unknown, not silence
        callback_thread.join(0.2)
        assert not callback_thread.is_alive()
    finally:
        release.set()
        speaker.close()


def test_meter_overflow_drops_only_telemetry_never_pcm(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = devices._pcm_rms

    def blocked_meter(pcm):
        entered.set()
        release.wait(2.0)
        return original(pcm)

    monkeypatch.setattr(devices, "_pcm_rms", blocked_meter)
    speaker = make_speaker(monkeypatch)
    pcm = struct.pack("=h", 4096) * 8
    try:
        speaker.play(pcm, 24000)
        assert emit(speaker, pcm) == pcm
        assert entered.wait(1.0)

        # The worker is held on its first sample. Overflow may discard meter
        # samples, but every corresponding PCM block must still reach output.
        more_pcm = pcm * 65
        speaker.play(more_pcm, 24000)
        last_output = b""
        for _ in range(65):
            last_output = emit(speaker, pcm)
        assert last_output == pcm
        assert len(speaker._level_queue) <= devices._LEVEL_QUEUE_CAPACITY
        assert speaker.pending_seconds() == pytest.approx(0.0)
        assert speaker.played_seconds() == pytest.approx(66 * 8 / 24000)
        assert speaker.level() == 1.0
    finally:
        release.set()
        assert wait_for_meter(speaker, timeout=2.0)
        assert speaker.dropped_level_blocks >= 1
        assert speaker.level() == 1.0  # overflow remains conservative for the echo window
        speaker.close()
    assert not speaker._level_worker.is_alive()


def test_meter_failure_is_conservative_and_close_is_idempotent(monkeypatch):
    def failed_meter(_pcm):
        raise RuntimeError("synthetic meter failure")

    monkeypatch.setattr(devices, "_pcm_rms", failed_meter)
    speaker = make_speaker(monkeypatch)
    pcm = struct.pack("=h", 2048) * 8
    speaker.play(pcm, 24000)
    assert emit(speaker, pcm) == pcm
    assert wait_for_meter(speaker)
    assert speaker.level() == 1.0
    speaker.close()
    worker = speaker._level_worker
    speaker.close()
    assert not worker.is_alive()
