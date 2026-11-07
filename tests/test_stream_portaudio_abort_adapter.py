"""Strict native PortAudio abort and recovery tests: all fake hardware/offline."""

from __future__ import annotations

import collections
import threading
from threading import Event, Thread
import time
import pytest

from star.stream_epoch_pcm_sink import LocalEpochPCMSink
from star.stream_portaudio_abort_adapter import NativeAbortPCMSpeaker
from star.voice.devices import SoundSpeaker


class FakeAbortSpeaker:
    sample_rate = 24000

    def __init__(self) -> None:
        self.mode = "running"
        self.pending = 0.0
        self.played: list[bytes] = []
        self.calls: list[str] = []
        self.abort_ok = True
        self.start_ok = True
        self.abort_raises = False
        self.start_raises = False
        self.play_raises = False
        self.read_raises = False
        self.begin_play: Event | None = None
        self.allow_play: Event | None = None

    def play(self, pcm: bytes, sample_rate: int) -> None:
        assert sample_rate == self.sample_rate
        if self.begin_play:
            self.begin_play.set()
        if self.allow_play:
            assert self.allow_play.wait(2)
        if self.play_raises:
            raise OSError("fake playback failure")
        self.calls.append("play")
        self.played.append(pcm)
        self.pending += len(pcm) / (2 * self.sample_rate)

    def pending_seconds(self) -> float:
        if self.read_raises:
            raise OSError("unavailable queue")
        return self.pending

    def native_output_state(self) -> str:
        return self.mode

    def abort_pending_output(self) -> bool:
        self.calls.append("abort")
        if self.abort_raises:
            raise OSError("native device failure")
        if self.abort_ok:
            self.mode = "stopped"
            self.pending = 0
        return self.abort_ok

    def restart_after_abort(self) -> bool:
        self.calls.append("start")
        if self.start_raises:
            raise OSError("native device failure")
        if self.start_ok:
            self.mode = "running"
        return self.start_ok


def setup() -> tuple[LocalEpochPCMSink, NativeAbortPCMSpeaker, FakeAbortSpeaker]:
    fake = FakeAbortSpeaker()
    speaker = NativeAbortPCMSpeaker(fake, owner_approved=True)
    host = LocalEpochPCMSink(speaker)
    host.enable(owner_approved=True)
    assert host.bind("turn_1", independently_quiet=True).status == "ready"
    return host, speaker, fake


def test_owner_only_and_fresh_started_native_transport() -> None:
    fake = FakeAbortSpeaker()
    with pytest.raises(PermissionError):
        NativeAbortPCMSpeaker(fake)
    fake.mode = "stopped"
    with pytest.raises(RuntimeError):
        NativeAbortPCMSpeaker(fake, owner_approved=True)
    fake.mode = "running"
    fake.pending = 0.01
    with pytest.raises(RuntimeError):
        NativeAbortPCMSpeaker(fake, owner_approved=True)


def test_stop_aborts_native_pending_buffers_instead_of_draining() -> None:
    sink, speaker, native = setup()
    assert sink.submit("turn_1", "tts_pcm", b"\x01\x00" * 120)
    assert native.pending > 0
    assert sink.request_stop("turn_1")
    assert native.calls == ["play", "abort"]
    assert native.mode == "stopped"
    assert speaker.metrics()["requires_independent_quiet"] is True
    assert not sink.submit("turn_1", "tts_pcm", b"\x01\x00")
    assert sink.request_stop("turn_1")  # no duplicate PortAudio abort
    assert native.calls.count("abort") == 1
    assert speaker.metrics()["native_aborts"] == 1


def test_rearm_requires_native_quiet_and_fresh_epoch() -> None:
    sink, speaker, native = setup()
    assert sink.request_stop("turn_1")
    assert speaker.resume_after_flush() is False
    assert sink.observe_quiet("turn_1").status == "held"
    assert sink.observe_quiet("turn_1", native_output_flushed=True).status == "quiet"
    assert speaker.resume_after_flush(independently_quiet=True)
    assert speaker.metrics()["native_restarts"] == 1
    assert sink.bind("turn_1", independently_quiet=True).status == "held"
    assert sink.bind("turn_2", independently_quiet=True).status == "ready"
    assert not sink.submit("turn_1", "tts_pcm", b"ab")
    assert sink.submit("turn_2", "tts_pcm", b"cd")
    assert native.played == [b"cd"]


def test_native_abort_exception_never_claims_silence() -> None:
    sink, speaker, native = setup()
    native.abort_raises = True
    assert not sink.request_stop("turn_1")
    assert speaker.metrics()["faulted"] is True
    assert sink.observe_quiet("turn_1", native_output_flushed=True).status == "fault"
    assert not speaker.resume_after_flush(independently_quiet=True)
    assert sink.bind("turn_2", independently_quiet=True).status == "held"


def test_native_abort_false_or_inconsistent_stream_state_latches_fault() -> None:
    for mode in ("false", "state"):
        sink, speaker, native = setup()
        if mode == "false":
            native.abort_ok = False
        else:
            native.mode = "unknown"
            native.abort_ok = False
        assert not sink.request_stop("turn_1")
        assert speaker.metrics()["faulted"] is True


def test_native_restart_failure_requires_manual_recovery() -> None:
    sink, speaker, native = setup()
    assert sink.request_stop("turn_1")
    assert sink.observe_quiet("turn_1", native_output_flushed=True).status == "quiet"
    native.start_raises = True
    assert not speaker.resume_after_flush(independently_quiet=True)
    assert speaker.metrics()["faulted"] is True
    assert native.calls == ["abort", "start", "abort"]


def test_native_queue_corruption_prevents_restart() -> None:
    sink, speaker, native = setup()
    assert sink.request_stop("turn_1")
    native.pending = 0.001
    assert not speaker.resume_after_flush(independently_quiet=True)
    assert speaker.metrics()["requires_independent_quiet"] is True
    native.pending = 0
    assert speaker.resume_after_flush(independently_quiet=True)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.001, 121, True])
def test_invalid_native_queue_measurement_rejected(invalid: object) -> None:
    _sink, speaker, native = setup()
    native.pending = invalid  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        speaker.pending_seconds()


def test_native_play_exception_is_latched_by_both_layers() -> None:
    sink, speaker, native = setup()
    native.play_raises = True
    assert not sink.submit("turn_1", "tts_pcm", b"ab")
    assert speaker.metrics()["faulted"] is True
    assert sink.metrics()["faulted"] is True
    assert native.calls == ["abort"]  # play failure still requests native abort


def test_native_stop_wins_over_concurrent_pcm_submission() -> None:
    sink, speaker, native = setup()
    native.begin_play = Event()
    native.allow_play = Event()
    results: list[bool] = []
    writer = Thread(target=lambda: results.append(sink.submit("turn_1", "tts_pcm", b"ab")))
    writer.start()
    assert native.begin_play.wait(2)
    stopper = Thread(target=lambda: results.append(sink.request_stop("turn_1")))
    stopper.start()
    time.sleep(0.03)  # stop cannot overtake the in-flight PCM write
    native.allow_play.set()
    writer.join(2)
    stopper.join(2)
    assert not writer.is_alive() and not stopper.is_alive()
    assert results == [True, True]
    assert native.calls == ["play", "abort"]
    assert not sink.submit("turn_1", "tts_pcm", b"ef")


def test_metrics_never_contain_pcm_or_epoch_identity() -> None:
    _sink, speaker, _native = setup()
    metrics = str(speaker.metrics())
    assert "turn_1" not in metrics
    assert "pcm" not in metrics.lower()
    assert speaker.metrics()["native_aborts"] == 0


class FakeRawStream:
    def __init__(self) -> None:
        self.active = True
        self.stopped = False
        self.calls: list[object] = []
        self.fail_abort = False

    def abort(self, *, ignore_errors: bool) -> None:
        self.calls.append(("abort", ignore_errors))
        if self.fail_abort:
            raise RuntimeError("simulated PortAudio failure")
        self.active = False
        self.stopped = True

    def start(self) -> None:
        self.calls.append("start")
        self.stopped = False
        self.active = True


def bare_sound_speaker() -> tuple[SoundSpeaker, FakeRawStream]:
    # Avoids opening any hardware or importing sounddevice.
    speaker = SoundSpeaker.__new__(SoundSpeaker)
    speaker._lock = threading.Lock()
    speaker.sample_rate = 24000
    speaker._buffer = bytearray(b"\x01\x00" * 64)
    speaker._played = 0
    speaker._first_output_callback_at = None
    speaker._levels = collections.deque(maxlen=64)
    stream = FakeRawStream()
    speaker._stream = stream
    return speaker, stream


def test_real_sound_speaker_uses_strict_abort_and_latched_native_state() -> None:
    speaker, raw = bare_sound_speaker()
    assert speaker.native_output_state() == "running"
    assert speaker.abort_pending_output() is True
    assert speaker.pending_seconds() == 0
    assert speaker.native_output_state() == "stopped"
    assert raw.calls == [("abort", False)]
    assert speaker.restart_after_abort() is True
    assert speaker.native_output_state() == "running"
    assert raw.calls[-1] == "start"


def test_real_sound_speaker_aborts_are_not_silently_ignored() -> None:
    speaker, raw = bare_sound_speaker()
    raw.fail_abort = True
    with pytest.raises(RuntimeError, match="PortAudio"):
        speaker.abort_pending_output()
    assert speaker.pending_seconds() == 0
    assert raw.calls == [("abort", False)]
    assert speaker.native_output_state() == "running"


def test_unexpected_native_stream_flags_fail_closed() -> None:
    speaker, raw = bare_sound_speaker()
    raw.active = True
    raw.stopped = True
    assert speaker.native_output_state() == "unknown"
    assert not speaker.restart_after_abort()
