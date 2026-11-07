"""Offline consumer-side queue regressions: NO real PCM/OBS/VTS/game use."""

from __future__ import annotations

from threading import Event, Thread

import pytest

from star.stream_director import SpeechIntent
from star.stream_natural_turn_physical_host import PhysicalTurnResult
from star.stream_output_consumer_queue import StreamOutputConsumerQueue
from star.stream_output_epoch_fence import OutputEpochTicket, StreamOutputEpochFence


def prepared() -> PhysicalTurnResult:
    return PhysicalTurnResult(
        "prepare",
        "host_may_review_speech_intent",
        intent=SpeechIntent(
            signal_id="game_01",
            kind="game_moment",
            context="safe",
            evidence="trusted_host",
            deadline_at=100.0,
            instruction="respond",
            interrupt_current=False,
            untrusted_context=False,
        ),
    )


def ready(
    **queue_options: int,
) -> tuple[
    StreamOutputEpochFence,
    StreamOutputConsumerQueue,
    OutputEpochTicket,
    list[str],
    list[str],
]:
    cancelled_model: list[str] = []
    cancelled_tts: list[str] = []
    fence = StreamOutputEpochFence(
        cancel_model=lambda epoch: cancelled_model.append(epoch) or True,
        cancel_tts=lambda epoch: cancelled_tts.append(epoch) or True,
    )
    fence.enable(owner_approved=True)
    ticket = fence.issue(prepared(), epoch="physical_1", now_ms=10)
    queue = StreamOutputConsumerQueue(fence, **queue_options)
    return fence, queue, ticket, cancelled_model, cancelled_tts


def test_two_stage_enqueue_and_consume_checked_before_native_output() -> None:
    fence, queue, ticket, _, _ = ready()
    delivered: list[tuple[str, str, bytes | str]] = []
    for kind, payload in [
        ("model_text", "hello"),
        ("tts_pcm", b"\x01\x02"),
        ("avatar_motion", b"{}"),
    ]:
        outcome = queue.enqueue(ticket, kind=kind, payload=payload, now_ms=11)
        assert outcome.status == "accepted"
        assert outcome.authorizes_broadcast is False
    assert queue.metrics()["pending"] == 3
    assert queue.metrics()["buffered_bytes"] == 9

    def sink(epoch: str, kind: str, payload: bytes | str) -> bool:
        delivered.append((epoch, kind, payload))
        return True

    for t in (12, 13, 14):
        result = queue.consume_one(now_ms=t, submit=sink)
        assert result.status == "accepted"
        assert result.authorizes_game_input is False
    assert queue.consume_one(now_ms=15, submit=sink).status == "empty"
    assert delivered == [
        ("physical_1", "model_text", "hello"),
        ("physical_1", "tts_pcm", b"\x01\x02"),
        ("physical_1", "avatar_motion", b"{}"),
    ]
    assert fence.metrics()["accepted"] == 6  # enqueue + final handoff
    assert queue.metrics()["consumed"] == 3
    assert queue.metrics()["buffered_bytes"] == 0


def test_revoked_after_queue_acceptance_never_reaches_native_consumer() -> None:
    fence, queue, ticket, model, tts = ready()
    for now in (11, 12):
        assert queue.enqueue(ticket, kind="tts_pcm", payload=b"voice", now_ms=now).status == "accepted"
    assert fence.revoke(ticket, reason="owner_interrupt").status == "revoked"
    reached_native: list[bytes | str] = []

    def sink(_epoch: str, _kind: str, payload: bytes | str) -> bool:
        reached_native.append(payload)
        return True

    result = queue.consume_one(now_ms=13, submit=sink)
    assert result.status == "rejected"
    assert reached_native == []
    assert queue.metrics()["pending"] == 0
    assert queue.metrics()["dropped"] == 2
    assert model == tts == ["physical_1"]


def test_queue_rejects_forged_or_retired_ticket() -> None:
    fence, queue, ticket, _, _ = ready()
    impostor = OutputEpochTicket(ticket.serial, ticket.epoch)
    result = queue.enqueue(impostor, kind="model_text", payload="fake", now_ms=11)
    assert result.status == "rejected"
    assert queue.metrics()["pending"] == 0
    assert queue.enqueue(ticket, kind="model_text", payload="real", now_ms=12).status == "accepted"
    assert fence.retire_finished(
        ticket,
        model_idle=True,
        tts_idle=True,
        pcm_drained=True,
        avatar_neutral=True,
    )
    assert queue.consume_one(now_ms=13, submit=lambda *_: True).status == "rejected"


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("model_text", ""),
        ("model_text", b"bad"),
        ("model_text", "🔥" * 2049),
        ("tts_pcm", ""),
        ("tts_pcm", b""),
        ("tts_pcm", bytearray(b"mutable")),
        ("tts_pcm", b"z" * 262145),
        ("avatar_motion", "not-encoded"),
        ("avatar_motion", b"a" * 8193),
        ("wrong_kind", b"payload"),
    ],
)
def test_bad_kinds_types_and_actual_payload_size_fail_closed(
    kind: str,
    payload: bytes | str,
) -> None:
    _, queue, ticket, _, _ = ready()
    with pytest.raises(ValueError):
        queue.enqueue(ticket, kind=kind, payload=payload, now_ms=11)
    assert queue.metrics()["pending"] == 0


@pytest.mark.parametrize("max_pending,max_bytes", [(1, 524288), (64, 8192)])
def test_backpressure_revokes_lease_and_does_not_queue_extra_output(
    max_pending: int,
    max_bytes: int,
) -> None:
    fence, queue, ticket, model, tts = ready(
        max_pending=max_pending,
        max_buffered_bytes=max_bytes,
    )
    data = b"z" * (4096 if max_pending == 1 else 8192)
    assert queue.enqueue(ticket, kind="tts_pcm", payload=data, now_ms=11).status == "accepted"
    result = queue.enqueue(ticket, kind="tts_pcm", payload=data, now_ms=12)
    assert result.status == "fault"
    assert fence.metrics()["quiet_pending"] is True
    assert model == tts == ["physical_1"]
    assert queue.consume_one(now_ms=13, submit=lambda *_: True).status == "rejected"
    assert queue.metrics()["pending"] == 0


def test_native_callback_false_or_exception_revokes_epoch() -> None:
    for sink in (lambda *_: False, lambda *_: (_ for _ in ()).throw(OSError("device"))):
        fence, queue, ticket, model, tts = ready()
        queue.enqueue(ticket, kind="tts_pcm", payload=b"test", now_ms=11)
        result = queue.consume_one(now_ms=12, submit=sink)
        assert result.status == "fault"
        assert fence.metrics()["quiet_pending"] is True
        assert model == tts == ["physical_1"]
        assert queue.metrics()["dropped"] == 1


def test_closed_queue_clears_payloads_revokes_epoch_and_never_reopens() -> None:
    fence, queue, ticket, model, tts = ready()
    assert queue.enqueue(ticket, kind="model_text", payload="private", now_ms=11).status == "accepted"
    assert queue.close().status == "revoked"
    assert queue.metrics()["pending"] == 0
    assert queue.metrics()["buffered_bytes"] == 0
    assert queue.metrics()["closed"] is True
    assert queue.consume_one(now_ms=12, submit=lambda *_: True).status == "empty"
    assert model == tts == ["physical_1"]
    assert queue.enqueue(ticket, kind="tts_pcm", payload=b"x", now_ms=13).status == "rejected"
    assert fence.metrics()["enabled"] is False


def test_cancel_hook_may_clear_queue_without_lock_inversion() -> None:
    queue_holder: list[StreamOutputConsumerQueue] = []
    fence = StreamOutputEpochFence(
        cancel_model=lambda _epoch: queue_holder[0].discard_ticket(ticket) >= 0,
        cancel_tts=lambda _epoch: True,
    )
    fence.enable(owner_approved=True)
    ticket = fence.issue(prepared(), epoch="one", now_ms=10)
    queue = StreamOutputConsumerQueue(fence, max_pending=1)
    queue_holder.append(queue)
    assert queue.enqueue(ticket, kind="tts_pcm", payload=b"aa", now_ms=11).status == "accepted"
    # Overflow triggers fence cancellation while holding fence lock;
    # cancellation may acquire queue lock without cycles.
    assert queue.enqueue(ticket, kind="tts_pcm", payload=b"bb", now_ms=12).status == "fault"
    assert queue.metrics()["pending"] == 0


def test_race_revocation_before_last_handoff_drops_queued_audio() -> None:
    fence, queue, ticket, _, _ = ready()
    queue.enqueue(ticket, kind="tts_pcm", payload=b"already_queued", now_ms=11)
    # Simulate the host's pause before it pumps the audio work queue.
    entered = Event()
    proceed = Event()
    result: list[str] = []

    def worker() -> None:
        entered.set()
        assert proceed.wait(2)
        outcome = queue.consume_one(now_ms=14, submit=lambda *_: True)
        result.append(outcome.status)

    t = Thread(target=worker)
    t.start()
    try:
        assert entered.wait(2)
        assert fence.revoke(ticket, reason="critical_gameplay").status == "revoked"
    finally:
        proceed.set()
        t.join(timeout=2)
    assert not t.is_alive()
    assert result == ["rejected"]


def test_nonblocking_handoff_serializes_with_revocation() -> None:
    fence, queue, ticket, _, _ = ready()
    queue.enqueue(ticket, kind="tts_pcm", payload=b"last", now_ms=11)
    entered = Event()
    release = Event()
    delivered: list[str] = []
    outcomes: list[str] = []

    def sink(epoch: str, _kind: str, _payload: bytes | str) -> bool:
        entered.set()
        assert release.wait(2)  # synthetic scheduling only; actual host must not block
        delivered.append(epoch)
        return True

    consumer = Thread(target=lambda: outcomes.append(queue.consume_one(now_ms=12, submit=sink).status))
    stopper = Thread(target=lambda: outcomes.append(fence.revoke(ticket, reason="owner_interrupt").status))
    consumer.start()
    assert entered.wait(2)
    stopper.start()
    release.set()
    consumer.join(timeout=2)
    stopper.join(timeout=2)
    assert not consumer.is_alive() and not stopper.is_alive()
    assert delivered == ["physical_1"]
    assert sorted(outcomes) == ["accepted", "revoked"]
    assert queue.enqueue(ticket, kind="tts_pcm", payload=b"late", now_ms=13).status == "rejected"


def test_constructor_and_bad_clock_fail_before_consumption() -> None:
    fence, queue, ticket, _, _ = ready()
    with pytest.raises(ValueError):
        StreamOutputConsumerQueue(fence, max_pending=0)
    with pytest.raises(ValueError):
        StreamOutputConsumerQueue(fence, max_buffered_bytes=1)
    assert queue.enqueue(ticket, kind="model_text", payload="okay", now_ms=11).status == "accepted"
    with pytest.raises(ValueError):
        queue.consume_one(now_ms=float("nan"), submit=lambda *_: True)
    assert queue.metrics()["pending"] == 1
    with pytest.raises(TypeError):
        queue.consume_one(now_ms=12, submit=None)  # type: ignore[arg-type]
    assert queue.metrics()["pending"] == 1
