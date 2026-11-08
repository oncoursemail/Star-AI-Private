"""Offline regression: no real models, PCM devices, avatar, OBS or game input."""

from __future__ import annotations

from dataclasses import replace
from threading import Event, Thread
from typing import Callable

import pytest

from star.stream_director import SpeechIntent
from star.stream_natural_turn_physical_host import PhysicalTurnResult
from star.stream_output_epoch_fence import (
    OutputEpochTicket,
    StreamOutputEpochFence,
)


def prepared() -> PhysicalTurnResult:
    return PhysicalTurnResult(
        "prepare",
        "host_may_review_speech_intent",
        intent=SpeechIntent(
            signal_id="event_01",
            kind="game_moment",
            context="safe",
            evidence="trusted_host",
            deadline_at=10.0,
            instruction="respond",
            interrupt_current=False,
            untrusted_context=False,
        ),
    )


class Host:
    def __init__(self) -> None:
        self.model: list[str] = []
        self.tts: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.model_ok = True
        self.tts_ok = True
        self.submit_ok = True

    def cancel_model(self, epoch: str) -> bool:
        self.model.append(epoch)
        return self.model_ok

    def cancel_tts(self, epoch: str) -> bool:
        self.tts.append(epoch)
        return self.tts_ok

    def submit(self, epoch: str, kind: str) -> bool:
        self.sent.append((epoch, kind))
        return self.submit_ok


def ready(
    *, max_age_ms: float = 30_000, max_chunks: int = 8192
) -> tuple[Host, StreamOutputEpochFence, OutputEpochTicket]:
    host = Host()
    fence = StreamOutputEpochFence(
        cancel_model=host.cancel_model,
        cancel_tts=host.cancel_tts,
        max_age_ms=max_age_ms,
        max_chunks=max_chunks,
    )
    fence.enable(owner_approved=True)
    ticket = fence.issue(prepared(), epoch="native_01", now_ms=10)
    return host, fence, ticket


QUIET = dict(model_idle=True, tts_idle=True, pcm_drained=True, avatar_neutral=True)


def test_owner_opt_in_and_prepared_required() -> None:
    host = Host()
    fence = StreamOutputEpochFence(cancel_model=host.cancel_model, cancel_tts=host.cancel_tts)
    with pytest.raises(PermissionError):
        fence.enable()
    with pytest.raises(RuntimeError):
        fence.issue(prepared(), epoch="epoch", now_ms=10)
    fence.enable(owner_approved=True)
    with pytest.raises(ValueError):
        fence.issue(PhysicalTurnResult("hold", "noise"), epoch="epoch", now_ms=10)
    with pytest.raises(ValueError):
        fence.issue(replace(prepared(), authorizes_playback=True), epoch="epoch", now_ms=10)
    with pytest.raises(ValueError):
        fence.issue(replace(prepared(), authorizes_broadcast=True), epoch="epoch", now_ms=10)
    with pytest.raises(ValueError):
        fence.issue(prepared(), epoch="bad/epoch", now_ms=10)


@pytest.mark.parametrize("kind", ["model_text", "tts_pcm", "avatar_motion"])
def test_host_queue_accepted_without_claiming_hardware(kind: str) -> None:
    host, fence, ticket = ready()
    result = fence.dispatch(ticket, kind=kind, now_ms=12, submit=host.submit)
    assert result.status == "accepted"
    assert result.authorizes_broadcast is False
    assert result.authorizes_game_input is False
    assert host.sent == [("native_01", kind)]
    assert fence.metrics()["accepted"] == 1


@pytest.mark.parametrize("kind", ["pcm", "", "broadcast", 5, None])
def test_unknown_output_kind_rejected(kind: object) -> None:
    host, fence, ticket = ready()
    with pytest.raises(ValueError):
        fence.dispatch(ticket, kind=kind, now_ms=12, submit=host.submit)  # type: ignore[arg-type]
    assert not host.sent


def test_same_fields_cannot_forge_ticket() -> None:
    host, fence, ticket = ready()
    impostor = OutputEpochTicket(ticket.serial, ticket.epoch)
    assert fence.dispatch(impostor, kind="tts_pcm", now_ms=12, submit=host.submit).status == "rejected"
    assert fence.revoke(impostor, reason="owner_interrupt").status == "rejected"
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=13, submit=host.submit).status == "accepted"
    assert host.model == []


def test_stop_invalidates_then_cancels_both_lanes() -> None:
    host, fence, ticket = ready()
    assert fence.dispatch(ticket, kind="model_text", now_ms=11, submit=host.submit).status == "accepted"
    result = fence.revoke(ticket, reason="owner_interrupt")
    assert result.status == "revoked"
    assert host.model == ["native_01"]
    assert host.tts == ["native_01"]
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=12, submit=host.submit).status == "rejected"
    assert fence.metrics()["quiet_pending"] is True
    with pytest.raises(RuntimeError):
        fence.issue(prepared(), epoch="next", now_ms=15)
    assert fence.revoke(ticket, reason="owner_interrupt").status == "rejected"
    assert len(host.model) == len(host.tts) == 1


@pytest.mark.parametrize("field", list(QUIET))
def test_no_rearm_until_each_independent_lane_quiet(field: str) -> None:
    _, fence, ticket = ready()
    assert fence.revoke(ticket, reason="critical_gameplay").status == "revoked"
    observations = {**QUIET, field: False}
    assert fence.settle(ticket, **observations).status == "rejected"
    assert fence.metrics()["quiet_pending"] is True
    assert fence.settle(ticket, **QUIET).status == "settled"
    assert fence.metrics()["enabled"] is False
    fence.enable(owner_approved=True)
    new_ticket = fence.issue(prepared(), epoch="next", now_ms=30)
    assert new_ticket is not ticket


def test_wrong_ack_and_repeat_ack_rejected() -> None:
    _, fence, ticket = ready()
    other = OutputEpochTicket(ticket.serial, ticket.epoch)
    assert fence.revoke(ticket, reason="session_end").status == "revoked"
    assert fence.settle(other, **QUIET).status == "rejected"
    assert fence.settle(ticket, **QUIET).status == "settled"
    assert fence.settle(ticket, **QUIET).status == "rejected"


@pytest.mark.parametrize("field", list(QUIET))
def test_natural_finish_requires_all_drained_and_idle(field: str) -> None:
    host, fence, ticket = ready()
    assert not fence.retire_finished(ticket, **{**QUIET, field: False})
    assert fence.dispatch(ticket, kind="model_text", now_ms=11, submit=host.submit).status == "accepted"
    assert fence.retire_finished(ticket, **QUIET)
    assert fence.dispatch(ticket, kind="model_text", now_ms=12, submit=host.submit).status == "rejected"
    again = fence.issue(prepared(), epoch="next", now_ms=13)
    assert again is not ticket


@pytest.mark.parametrize("max_age,chunk_limit", [(1, 999), (200, 1)])
def test_expired_or_exhausted_turn_autocancels(max_age: int, chunk_limit: int) -> None:
    host, fence, ticket = ready(max_age_ms=max_age, max_chunks=chunk_limit)
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=10, submit=host.submit).status == "accepted"
    at = 12 if max_age == 1 else 11
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=at, submit=host.submit).status == "revoked"
    assert fence.metrics()["quiet_pending"] is True
    assert host.model == ["native_01"]
    assert host.tts == ["native_01"]


def test_reversed_clock_fails_closed() -> None:
    host, fence, ticket = ready()
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=12, submit=host.submit).status == "accepted"
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=11, submit=host.submit).status == "revoked"
    assert len(host.sent) == 1


@pytest.mark.parametrize("which", ["submit_false", "submit_exception"])
def test_failed_output_submission_quarantines(which: str) -> None:
    host, fence, ticket = ready()
    callback: Callable[[str, str], bool] = host.submit
    if which == "submit_false":
        host.submit_ok = False
    else:

        def raise_submit(epoch: str, kind: str) -> bool:
            raise OSError("device failed")

        callback = raise_submit

    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=11, submit=callback).status == "fault"
    assert fence.metrics()["quiet_pending"] is True
    assert host.model == ["native_01"]
    assert host.tts == ["native_01"]
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=12, submit=host.submit).status == "rejected"


def test_failed_cancel_requires_explicit_owner_recovery() -> None:
    host, fence, ticket = ready()
    host.model_ok = False
    result = fence.revoke(ticket, reason="physical_stop")
    assert result.status == "fault"
    assert host.model == ["native_01"] and host.tts == ["native_01"]
    assert fence.settle(ticket, **QUIET).status == "fault"
    assert fence.settle(ticket, **QUIET, owner_recovery=True).status == "settled"
    assert fence.metrics()["faulted"] is False
    assert fence.metrics()["enabled"] is False


def test_owner_recovery_never_bypasses_uncertain_device() -> None:
    host, fence, ticket = ready()
    host.tts_ok = False
    fence.revoke(ticket, reason="unhealthy_output")
    assert fence.settle(ticket, **{**QUIET, "pcm_drained": False}, owner_recovery=True).status == "rejected"
    assert fence.metrics()["quiet_pending"] is True


def test_disable_latches_stop_and_no_automatic_reenable() -> None:
    host, fence, ticket = ready()
    assert fence.disable().status == "revoked"
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=11, submit=host.submit).status == "rejected"
    assert fence.settle(ticket, **QUIET).status == "settled"
    with pytest.raises(RuntimeError):
        fence.issue(prepared(), epoch="new", now_ms=20)
    fence.enable(owner_approved=True)
    assert fence.issue(prepared(), epoch="new", now_ms=20).serial == ticket.serial + 1


def test_reentrant_cancellation_blocks_late_output() -> None:
    host, fence, ticket = ready()

    def submit(_epoch: str, _kind: str) -> bool:
        assert fence.revoke(ticket, reason="owner_interrupt").status == "revoked"
        return True

    result = fence.dispatch(ticket, kind="tts_pcm", now_ms=11, submit=submit)
    assert result.status == "fault"
    assert fence.metrics()["accepted"] == 0
    assert fence.metrics()["quiet_pending"] is True
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=12, submit=host.submit).status == "rejected"


def test_parallel_revocation_waits_for_short_host_submission() -> None:
    host, fence, ticket = ready()
    entered = Event()
    release = Event()
    statuses: list[str] = []

    def bounded_submit(_epoch: str, _kind: str) -> bool:
        entered.set()
        return release.wait(timeout=2)

    def submitter() -> None:
        statuses.append(fence.dispatch(ticket, kind="tts_pcm", now_ms=11, submit=bounded_submit).status)

    worker = Thread(target=submitter)
    worker.start()
    assert entered.wait(timeout=2)
    # The callback represents a host-owned, very short queue operation.
    # Revocation cannot be allowed to run concurrently through its lease check.
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert statuses == ["accepted"]
    assert fence.revoke(ticket, reason="owner_interrupt").status == "revoked"
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=12, submit=host.submit).status == "rejected"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "10", 1e15])
def test_bad_host_clocks_fail_closed(bad: object) -> None:
    host, fence, ticket = ready()
    with pytest.raises(ValueError):
        fence.dispatch(ticket, kind="model_text", now_ms=bad, submit=host.submit)  # type: ignore[arg-type]


def test_strict_parameters_and_boolean_observations() -> None:
    host = Host()
    with pytest.raises(ValueError):
        StreamOutputEpochFence(cancel_model=host.cancel_model, cancel_tts=host.cancel_tts, max_chunks=True)
    with pytest.raises(ValueError):
        StreamOutputEpochFence(cancel_model=host.cancel_model, cancel_tts=host.cancel_tts, max_age_ms=float("nan"))
    _, fence, ticket = ready()
    fence.revoke(ticket, reason="session_end")
    with pytest.raises(ValueError):
        fence.settle(ticket, **{**QUIET, "pcm_drained": 1})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        fence.revoke(ticket, reason="viewer-supplied-arbitrary-reason")


def test_metrics_cannot_disclose_user_or_native_epoch() -> None:
    host, fence, ticket = ready()
    result = fence.dispatch(ticket, kind="model_text", now_ms=12, submit=host.submit)
    payload = repr(fence.metrics()) + repr(result)
    assert "native_01" not in payload
    assert "safe" not in payload
    assert "viewer" not in payload


def test_full_bridge_physical_stop_and_stale_output_fence() -> None:
    """The real NaturalTurnBridge/PhysicalHost handshake composes with a fence."""
    from star.stream_director import StreamSignal
    from star.stream_natural_turn_bridge import NaturalTurnBridge
    from star.stream_natural_turn_physical_host import NaturalTurnPhysicalHost
    from star.stream_turntaking import VoiceFrame

    class Rig:
        drained = False
        neutral = False

        def stop(self, epoch: str) -> bool:
            assert epoch == "native_01"
            self.drained = True
            return True

        def flush(self, epoch: str) -> bool:
            assert epoch == "native_01"
            return True

        def reset(self, epoch: str) -> bool:
            assert epoch == "native_01"
            self.neutral = True
            return True

        def is_drained(self, epoch: str) -> bool:
            assert epoch == "native_01"
            return self.drained

        def is_neutral(self, epoch: str) -> bool:
            assert epoch == "native_01"
            return self.neutral

    rig = Rig()
    bridge = NaturalTurnBridge()
    physical = NaturalTurnPhysicalHost(
        bridge,
        request_pcm_stop=rig.stop,
        request_animation_flush=rig.flush,
        request_avatar_neutral=rig.reset,
        pcm_drained_probe=rig.is_drained,
        avatar_neutral_probe=rig.is_neutral,
    )
    physical.enable(owner_approved=True)
    for ms in range(50, 401, 50):
        assert bridge.observe_voice(VoiceFrame(ms, 50, 0, 0, True))
    assert bridge.offer(
        StreamSignal(
            signal_id="q1",
            kind="viewer_question",
            timestamp=0.4,
            detail="How did you dodge?",
            speaker_id="guest",
            evidence="reported",
        ),
        now_ms=400,
    )
    prepared_result = physical.drive(
        now_ms=400,
        host_playout_active=False,
        gameplay_critical=False,
        output_healthy=True,
    )
    assert prepared_result.action == "prepare"
    host = Host()
    fence = StreamOutputEpochFence(
        cancel_model=host.cancel_model,
        cancel_tts=host.cancel_tts,
    )
    fence.enable(owner_approved=True)
    ticket = fence.issue(prepared_result, epoch="native_01", now_ms=400)
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=401, submit=host.submit).status == "accepted"
    physical.bind_playout("native_01", host_observed_active=True)
    assert fence.revoke(ticket, reason="critical_gameplay").status == "revoked"
    stopped = physical.drive(now_ms=450, host_playout_active=True, gameplay_critical=True, output_healthy=True)
    assert stopped.action == "stopped" and stopped.pcm_drained and stopped.avatar_neutral
    assert (
        fence.settle(
            ticket,
            model_idle=True,
            tts_idle=True,
            pcm_drained=stopped.pcm_drained,
            avatar_neutral=stopped.avatar_neutral,
        ).status
        == "settled"
    )
    assert fence.dispatch(ticket, kind="tts_pcm", now_ms=460, submit=host.submit).status == "rejected"
    assert len(host.sent) == 1
