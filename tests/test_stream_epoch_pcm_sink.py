"""Offline fake-speaker tests. No sounddevice, physical audio or network."""

from __future__ import annotations

from threading import Event, Thread

import pytest

from star.stream_epoch_pcm_sink import LocalEpochPCMSink
from star.stream_output_consumer_queue import StreamOutputConsumerQueue
from star.stream_output_epoch_fence import StreamOutputEpochFence
from star.stream_natural_turn_physical_host import PhysicalTurnResult
from star.stream_director import SpeechIntent


class FakeSpeaker:
    sample_rate = 24000

    def __init__(self) -> None:
        self.data: list[bytes] = []
        self.pending = 0.0
        self.stopped = 0
        self.fail_play = False
        self.fail_stop = False
        self.bad_probe = False

    def play(self, pcm: bytes, sample_rate: int) -> None:
        assert sample_rate == self.sample_rate
        if self.fail_play:
            raise OSError("offline-simulated")
        self.data.append(pcm)
        self.pending += len(pcm) / (2 * self.sample_rate)

    def stop(self) -> None:
        self.stopped += 1
        self.pending = 0.0
        if self.fail_stop:
            raise OSError("offline-simulated")

    def pending_seconds(self) -> float:
        if self.bad_probe:
            raise OSError("offline-simulated")
        return self.pending


def sink(*, max_buffered_ms: int = 600) -> tuple[LocalEpochPCMSink, FakeSpeaker]:
    speaker = FakeSpeaker()
    host = LocalEpochPCMSink(speaker, max_buffered_ms=max_buffered_ms)
    return host, speaker


def start(host: LocalEpochPCMSink, epoch: str = "voice_1") -> None:
    host.enable(owner_approved=True)
    assert host.bind(epoch, independently_quiet=True).status == "ready"


def test_disabled_by_default_and_owner_approved() -> None:
    host, device = sink()
    assert host.bind("e", independently_quiet=True).status == "held"
    assert not host.submit("e", "tts_pcm", b"aa")
    with pytest.raises(PermissionError):
        host.enable()
    start(host)
    assert host.metrics()["active"] is True
    assert host.metrics()["queued"] == 0
    assert host.submit("voice_1", "tts_pcm", b"\x00\x01")
    assert device.data == [b"\x00\x01"]
    assert host.metrics()["queued_bytes_total"] == 2
    assert host.metrics()["enabled"] is True


@pytest.mark.parametrize("epoch", ["", "bad space", "🔥", "x" * 65])
def test_invalid_native_epoch_fails_closed(epoch: str) -> None:
    host, _ = sink()
    host.enable(owner_approved=True)
    with pytest.raises(ValueError):
        host.bind(epoch, independently_quiet=True)


@pytest.mark.parametrize(
    "payload,kind",
    [
        (b"", "tts_pcm"),
        (b"x", "tts_pcm"),
        ("voice", "tts_pcm"),
        (bytearray(b"xx"), "tts_pcm"),
        (b"ab", "avatar_motion"),
        (b"ab", "model_text"),
        (b"ab", ""),
        (b"y" * 65538, "tts_pcm"),
    ],
)
def test_only_bounded_even_length_native_pcm16(payload: object, kind: str) -> None:
    host, device = sink()
    start(host)
    assert host.submit("voice_1", kind, payload) is False  # type: ignore[arg-type]
    assert device.data == []


def test_wrong_epoch_is_never_written_even_if_looks_valid() -> None:
    host, device = sink()
    start(host)
    assert not host.submit("voice_2", "tts_pcm", b"ab")
    assert not host.submit("VOICE_1", "tts_pcm", b"ab")
    assert device.data == []


def test_queue_backpressure_before_native_enqueue() -> None:
    host, device = sink(max_buffered_ms=100)
    start(host)
    assert host.submit("voice_1", "tts_pcm", b"0" * 4800)
    assert not host.submit("voice_1", "tts_pcm", b"0" * 2)
    assert len(device.data) == 1
    assert host.metrics()["rejected"] == 1


def test_bad_or_unavailable_device_observation_fails_closed() -> None:
    host, device = sink()
    host.enable(owner_approved=True)
    device.bad_probe = True
    assert host.bind("voice_1", independently_quiet=True).status == "held"
    device.bad_probe = False
    device.pending = 0.05
    assert host.bind("voice_1", independently_quiet=True).status == "held"
    device.pending = 0.0
    assert host.bind("voice_1", independently_quiet=True).status == "ready"
    device.bad_probe = True
    assert not host.submit("voice_1", "tts_pcm", b"aa")


def test_stop_invalidates_then_requires_independently_attested_native_flush() -> None:
    host, device = sink()
    start(host)
    assert host.submit("voice_1", "tts_pcm", b"ab")
    assert host.request_stop("voice_1")
    assert device.stopped == 1
    # Model cancellation and the physical stop host can both request stop.
    # A second stop request is safe but does not establish native silence.
    assert host.request_stop("voice_1")
    assert device.stopped == 1
    assert host.observe_quiet("voice_1").status == "held"
    assert not host.submit("voice_1", "tts_pcm", b"cd")
    assert host.bind("voice_2", independently_quiet=True).status == "held"
    assert host.observe_quiet("voice_1").status == "held"
    assert host.observe_quiet("wrong", native_output_flushed=True).status == "held"
    assert host.observe_quiet("voice_1", native_output_flushed=True).status == "quiet"
    assert host.bind("voice_1", independently_quiet=True).status == "held"
    assert host.bind("voice_2", independently_quiet=True).status == "ready"
    assert host.submit("voice_2", "tts_pcm", b"ef")
    assert device.data[-1] == b"ef"


def test_bad_flush_observation_and_nonempty_queue_prevent_rearm() -> None:
    host, device = sink()
    start(host)
    assert host.request_stop("voice_1")
    device.pending = 0.001
    assert host.observe_quiet("voice_1", native_output_flushed=True).status == "held"
    device.pending = 0.0
    with pytest.raises(ValueError):
        host.observe_quiet("voice_1", native_output_flushed=1)  # type: ignore[arg-type]
    assert host.observe_quiet("voice_1", native_output_flushed=True).status == "quiet"


def test_native_play_exception_latches_fault_and_wont_reuse_epoch() -> None:
    host, device = sink()
    start(host)
    device.fail_play = True
    assert not host.submit("voice_1", "tts_pcm", b"xx")
    assert device.stopped == 1
    assert host.metrics()["faulted"] is True
    assert host.observe_quiet("voice_1", native_output_flushed=True).status == "fault"
    assert host.bind("voice_2", independently_quiet=True).status == "held"
    assert host.disable().status == "fault"


def test_native_stop_failure_never_counts_as_verified_silence() -> None:
    host, device = sink()
    start(host)
    device.fail_stop = True
    assert not host.request_stop("voice_1")
    assert host.metrics()["faulted"] is True
    assert host.observe_quiet("voice_1", native_output_flushed=True).status == "fault"


def test_disable_fences_submissions_and_clears_app_buffer() -> None:
    host, device = sink()
    start(host)
    assert host.submit("voice_1", "tts_pcm", b"xx")
    state = host.disable()
    assert state.status == "disabled"
    assert state.authorizes_game_input is False
    assert state.authorizes_broadcast is False
    assert state.device_audibility_verified is False
    assert device.stopped == 1
    assert not host.submit("voice_1", "tts_pcm", b"yy")
    assert host.metrics()["pending_quiet"] is True


def test_native_endpoint_never_replays_used_ids_across_enable_cycles() -> None:
    host, _ = sink()
    start(host)
    assert host.request_stop("voice_1")
    assert host.observe_quiet("voice_1", native_output_flushed=True).status == "quiet"
    host.disable()
    host.enable(owner_approved=True)
    assert host.bind("voice_1", independently_quiet=True).status == "held"
    assert host.bind("voice_2", independently_quiet=True).status == "ready"


def test_callback_delivery_serializes_with_stop() -> None:
    entered, release = Event(), Event()

    class SlowFake(FakeSpeaker):
        def play(self, pcm: bytes, sample_rate: int) -> None:
            entered.set()
            assert release.wait(2)
            super().play(pcm, sample_rate)

    device = SlowFake()
    host = LocalEpochPCMSink(device)
    start(host)
    statuses: list[bool] = []
    producer = Thread(target=lambda: statuses.append(host.submit("voice_1", "tts_pcm", b"aa")))
    stopper = Thread(target=lambda: statuses.append(host.request_stop("voice_1")))
    producer.start()
    assert entered.wait(2)
    stopper.start()
    release.set()
    producer.join(timeout=2)
    stopper.join(timeout=2)
    assert not producer.is_alive() and not stopper.is_alive()
    assert sorted(statuses) == [True, True]
    assert not host.submit("voice_1", "tts_pcm", b"bb")
    assert device.stopped == 1


def _prepared() -> PhysicalTurnResult:
    return PhysicalTurnResult(
        "prepare",
        "host_may_review_speech_intent",
        intent=SpeechIntent(
            signal_id="game",
            kind="game_moment",
            context="safe",
            evidence="trusted_host",
            deadline_at=100.0,
            instruction="respond",
            interrupt_current=False,
            untrusted_context=False,
        ),
    )


def test_two_stage_output_queue_reaches_real_speaker_interface_only_once() -> None:
    """Queue + fence + native PCM boundary: no physical playback in this test."""
    host, device = sink()
    start(host, epoch="game_turn_1")
    cancelled: list[str] = []
    fence = StreamOutputEpochFence(
        cancel_model=lambda ep: cancelled.append("model:" + ep) or True,
        cancel_tts=lambda ep: host.request_stop(ep),
    )
    fence.enable(owner_approved=True)
    ticket = fence.issue(_prepared(), epoch="game_turn_1", now_ms=10)
    queue = StreamOutputConsumerQueue(fence)
    assert queue.enqueue(ticket, kind="tts_pcm", payload=b"aa", now_ms=11).status == "accepted"
    assert queue.consume_one(now_ms=12, submit=host.submit).status == "accepted"
    assert device.data == [b"aa"]
    assert queue.enqueue(ticket, kind="tts_pcm", payload=b"bb", now_ms=13).status == "accepted"
    assert fence.revoke(ticket, reason="owner_interrupt").status == "revoked"
    assert cancelled == ["model:game_turn_1"]
    assert device.stopped == 1
    assert queue.consume_one(now_ms=14, submit=host.submit).status == "rejected"
    assert device.data == [b"aa"]
    assert host.observe_quiet("game_turn_1").status == "held"
    assert host.observe_quiet("game_turn_1", native_output_flushed=True).status == "quiet"
    assert host.metrics()["unique_epochs"] == 1
    assert fence.metrics()["quiet_pending"] is True
