"""Deterministic native-epoch stop tests; no real PCM/VTS/OBS touched."""

from __future__ import annotations

from typing import Any, cast

import pytest

from star.stream_director import StreamSignal
from star.stream_natural_turn_bridge import NaturalTurnBridge
from star.stream_natural_turn_physical_host import NaturalTurnPhysicalHost
from star.stream_turntaking import VoiceFrame


class LocalRig:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.drain = False
        self.neutral = False
        self.fail: str | None = None
        self.resume_pcm_during_neutral = False

    def _act(self, name: str, epoch: str) -> bool:
        assert epoch == "local-epoch-1"  # all actions must target pinned audio
        self.events.append(name)
        if self.fail == name:
            raise OSError("simulated device failure")
        if name == "pcm_stop":
            self.drain = True
        if name == "avatar_neutral":
            self.neutral = True
            if self.resume_pcm_during_neutral:
                self.drain = False
        return True

    def stop(self, epoch: str) -> bool:
        return self._act("pcm_stop", epoch)

    def flush(self, epoch: str) -> bool:
        return self._act("animation_flush", epoch)

    def reset(self, epoch: str) -> bool:
        return self._act("avatar_neutral", epoch)

    def drained(self, epoch: str) -> bool:
        assert epoch == "local-epoch-1"
        self.events.append("pcm_probe")
        if self.fail == "pcm_probe":
            raise OSError("sample unavailable")
        return self.drain

    def avatar_ready(self, epoch: str) -> bool:
        assert epoch == "local-epoch-1"
        self.events.append("avatar_probe")
        if self.fail == "avatar_probe":
            return False
        return self.neutral


def host() -> tuple[NaturalTurnBridge, NaturalTurnPhysicalHost, LocalRig]:
    rig = LocalRig()
    bridge = NaturalTurnBridge()
    physical = NaturalTurnPhysicalHost(
        bridge,
        request_pcm_stop=rig.stop,
        request_animation_flush=rig.flush,
        request_avatar_neutral=rig.reset,
        pcm_drained_probe=rig.drained,
        avatar_neutral_probe=rig.avatar_ready,
    )
    return bridge, physical, rig


def tick(
    physical: NaturalTurnPhysicalHost,
    *,
    ms: int = 400,
    active: bool = False,
    danger: bool = False,
    healthy: bool = True,
):
    return physical.drive(
        now_ms=ms,
        host_playout_active=active,
        gameplay_critical=danger,
        output_healthy=healthy,
    )


def loud(physical: NaturalTurnPhysicalHost) -> None:
    physical.bind_playout("local-epoch-1", host_observed_active=True)


def feed_quiet(bridge: NaturalTurnBridge) -> None:
    for ms in range(50, 401, 50):
        assert bridge.observe_voice(VoiceFrame(ms, 50, 0, 0, True))


def test_no_side_effects_without_owner_enable():
    bridge, physical, rig = host()
    assert tick(physical).action == "hold"
    assert physical.disable(host_playout_active=False).action == "hold"
    with pytest.raises(PermissionError):
        physical.enable()
    assert not rig.events and not bridge.metrics()["enabled"]


def test_verified_quiet_prepare_does_not_authorize_pcm_or_broadcast():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    feed_quiet(bridge)
    assert bridge.offer(
        StreamSignal(
            signal_id="q1",
            kind="viewer_question",
            timestamp=0.4,
            detail="What is your strategy?",
            speaker_id="guest",
            evidence="reported",
        ),
        now_ms=400,
    )
    decision = tick(physical)
    assert decision.action == "prepare"
    assert decision.intent is not None
    assert not decision.authorizes_playback
    assert not decision.authorizes_broadcast
    assert rig.events == []


def test_critical_gameplay_physically_stops_pcm_then_flushes_and_neutralizes():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    result = tick(physical, active=True, danger=True)
    assert result.action == "stopped"
    assert result.stop_token == 1
    assert result.pcm_drained and result.avatar_neutral
    assert rig.events == [
        "pcm_stop",
        "animation_flush",
        "pcm_probe",
        "avatar_neutral",
        "avatar_probe",
        "pcm_probe",
    ]
    assert not bridge.metrics()["stop_outstanding"]
    assert physical.metrics()["verified_stops"] == 1
    assert not physical.metrics()["epoch_bound"]


@pytest.mark.parametrize("danger,healthy", [(True, True), (False, False)])
def test_unsafe_playback_interrupts(danger: bool, healthy: bool):
    _, physical, _ = host()
    physical.enable(owner_approved=True)
    loud(physical)
    result = tick(physical, active=True, danger=danger, healthy=healthy)
    assert result.action == "stopped"


def test_authenticated_owner_interrupt_uses_same_physical_stop():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    feed_quiet(bridge)
    for ms in (450, 500, 550):
        assert bridge.observe_voice(VoiceFrame(ms, 50, 1, 0, True))
    result = tick(physical, ms=550, active=True)
    assert result.action == "stopped"
    assert rig.events[0] == "pcm_stop"


def test_guest_voice_does_not_forge_owner_barge_in():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    feed_quiet(bridge)
    for ms in (450, 500, 550):
        assert bridge.observe_voice(VoiceFrame(ms, 50, 0, 1, True))
    assert tick(physical, ms=550, active=True).action == "hold"
    assert rig.events == []


@pytest.mark.parametrize(
    "failure",
    [
        "pcm_stop",
        "animation_flush",
        "pcm_probe",
        "avatar_neutral",
        "avatar_probe",
    ],
)
def test_failed_callback_fault_latches_without_repeating_stop(failure: str):
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    rig.fail = failure
    result = tick(physical, active=True, danger=True)
    assert result.action == "fault"
    old_events = list(rig.events)
    assert tick(physical, ms=410, active=True).action == "fault"
    assert rig.events == old_events
    assert bridge.metrics()["stop_outstanding"]
    assert physical.metrics()["faulted"]
    with pytest.raises(RuntimeError):
        loud(physical)
    # A stop command alone is never enough to clear the bridge obligation.
    assert not physical.recover_after_manual_stop(owner_approved=True)


def test_pcm_resumption_during_avatar_reset_blocks_stop_ack():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    rig.resume_pcm_during_neutral = True
    result = tick(physical, active=True, danger=True)
    assert result.action == "fault"
    assert result.avatar_neutral
    assert not result.pcm_drained
    assert bridge.metrics()["stop_outstanding"]
    assert not physical.recover_after_manual_stop(owner_approved=True)


def test_manual_recovery_requires_independent_probes_and_owner():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    rig.fail = "pcm_stop"
    assert tick(physical, active=True, danger=True).action == "fault"
    with pytest.raises(PermissionError):
        physical.recover_after_manual_stop()
    rig.fail = None
    rig.drain = True  # independent native operator verified physical stop
    rig.neutral = False
    assert not physical.recover_after_manual_stop(owner_approved=True)
    assert bridge.metrics()["stop_outstanding"]
    rig.neutral = True
    assert physical.recover_after_manual_stop(owner_approved=True)
    assert not bridge.metrics()["stop_outstanding"]
    assert not physical.metrics()["faulted"]
    assert tick(physical).reason == "owner_opt_in_missing"
    assert not physical.recover_after_manual_stop(owner_approved=True)
    physical.enable(owner_approved=True)


def test_disable_closes_active_epoch_even_if_clock_unavailable():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    result = physical.disable(host_playout_active=False)
    assert result.action == "stopped"
    assert not bridge.metrics()["enabled"]
    assert rig.events[0] == "pcm_stop"
    assert tick(physical).action == "hold"


def test_stop_failure_stays_pending_across_disable_and_repeated_drive():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    rig.fail = "avatar_probe"
    assert tick(physical, active=True, danger=True).action == "fault"
    old = rig.events[:]
    assert physical.disable(host_playout_active=False).action == "fault"
    assert tick(physical, ms=999, active=True).action == "fault"
    assert rig.events == old
    assert bridge.metrics()["stop_outstanding"]


def test_epoch_mismatch_and_false_active_observation_fails_closed():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    # The OS says it stopped; this is not a verified drain/neutral receipt.
    result = tick(physical, active=False)
    assert result.action == "stopped"
    assert not bridge.metrics()["enabled"]
    assert rig.events[0] == "pcm_stop"


def test_unbound_active_playback_latches_nonrecoverable_fault():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    result = tick(physical, active=True)
    assert result.action == "fault"
    assert result.reason == "unbound_physical_playout"
    assert bridge.metrics()["stop_outstanding"]
    assert not rig.events
    assert not physical.recover_after_manual_stop(owner_approved=True)


def test_normal_retirement_needs_independent_pcm_and_rig_probes():
    _, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    assert not physical.retire_finished("other")
    assert not physical.retire_finished("local-epoch-1")
    rig.drain = True
    assert not physical.retire_finished("local-epoch-1")
    rig.neutral = True
    assert physical.retire_finished("local-epoch-1")
    assert not physical.retire_finished("local-epoch-1")
    loud(physical)


def test_invalid_native_epoch_and_host_booleans_rejected():
    _, physical, _ = host()
    physical.enable(owner_approved=True)
    for epoch in ("", "../escape", "a" * 100, "contains space", None):
        with pytest.raises(ValueError):
            physical.bind_playout(cast(Any, epoch), host_observed_active=True)
    with pytest.raises(ValueError):
        physical.bind_playout("local-epoch-1", host_observed_active=False)
    for key in ("host_playout_active", "gameplay_critical", "output_healthy"):
        args = dict(now_ms=400, host_playout_active=False, gameplay_critical=False, output_healthy=True)
        args[key] = 1
        with pytest.raises(ValueError):
            physical.drive(**cast(Any, args))
    with pytest.raises(ValueError):
        physical.disable(host_playout_active=cast(Any, 1))


def test_no_auto_rearm_after_disable_and_verified_stop():
    bridge, physical, rig = host()
    physical.enable(owner_approved=True)
    loud(physical)
    assert physical.disable(host_playout_active=True).action == "stopped"
    with pytest.raises(RuntimeError):
        physical.bind_playout("local-epoch-1", host_observed_active=True)
    assert tick(physical).action == "hold"
    assert not bridge.metrics()["enabled"]
    assert rig.events.count("pcm_stop") == 1
