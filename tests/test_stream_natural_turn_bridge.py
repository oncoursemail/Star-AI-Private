"""Offline regression tests for joined VAD + stream speech arbitration."""
from dataclasses import replace

import pytest

from star.stream_director import StreamSignal
from star.stream_natural_turn_bridge import NaturalTurnBridge
from star.stream_turntaking import VoiceFrame


def voice(at_ms: float, *, owner: float = 0, guest: float = 0,
          echo: bool = True) -> VoiceFrame:
    return VoiceFrame(at_ms, 50, owner, guest, echo)


def ready(host: NaturalTurnBridge, *, at: int = 400) -> None:
    for end in range(at - 350, at + 1, 50):
        assert host.observe_voice(voice(end))


def signal(now_ms: int = 400, *, signal_id: str = "question1",
           kind: str = "viewer_question") -> StreamSignal:
    return StreamSignal(
        signal_id=signal_id, kind=kind, timestamp=now_ms / 1000,
        detail="How did you get past the obstacle?",
        speaker_id="viewer42" if kind.startswith("viewer") else "",
        evidence="reported",
    )


def decide(host: NaturalTurnBridge, now: float = 400,
           *, speaking: bool = False, critical: bool = False,
           healthy: bool = True):
    return host.advise(
        now_ms=now, host_playout_active=speaking,
        gameplay_critical=critical, output_healthy=healthy,
    )


def test_approval_and_verified_quiet_required():
    host = NaturalTurnBridge()
    with pytest.raises(PermissionError):
        host.enable()
    assert decide(host).action == "hold"
    host.enable(owner_approved=True)
    assert decide(host).reason == "audio_turn_vad_missing_or_stale"
    assert host.offer(signal(), now_ms=400)
    assert decide(host).action == "hold"
    ready(host)
    planned = decide(host)
    assert planned.action == "prepare"
    assert planned.intent is not None
    assert not planned.authorizes_playback
    assert not planned.authorizes_broadcast
    assert not planned.authorizes_game_input


def test_complete_only_latest_prepared_ticket_after_measured_playout():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    first = decide(host).intent
    assert first is not None
    second = decide(host).intent
    assert second is not None and second is not first
    assert not host.complete(first, now_ms=405, host_confirmed_spoken=True)
    assert host.complete(second, now_ms=410, host_confirmed_spoken=True)
    assert not host.complete(second, now_ms=420, host_confirmed_spoken=True)
    assert decide(host, 430).action == "hold"


def test_barrier_survives_disable_until_pcm_and_avatar_confirmed():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    host.observe_voice(voice(450, owner=1))
    host.observe_voice(voice(500, owner=1))
    host.observe_voice(voice(550, owner=1))
    stop = decide(host, 550, speaking=True)
    assert stop.action == "stop_playback"
    assert stop.reason == "authenticated_owner_barge_in"
    assert stop.stop_token == 1
    assert decide(host, 560, speaking=False).stop_token == 1
    assert host.disable(host_playout_active=False) == 1
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    assert not host.acknowledge_stopped(1, pcm_drained=True, avatar_neutral=False)
    assert not host.acknowledge_stopped(0, pcm_drained=True, avatar_neutral=True)
    assert host.acknowledge_stopped(1, pcm_drained=True, avatar_neutral=True)
    assert not host.acknowledge_stopped(1, pcm_drained=True, avatar_neutral=True)
    host.enable(owner_approved=True)
    assert decide(host, 700).action == "hold"
    assert host.metrics()["stops_requested"] == 1
    assert host.metrics()["stops_confirmed"] == 1


def test_ambiguous_guest_and_uncleared_echo_cannot_interrupt():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    for t in [450, 500, 550]:
        host.observe_voice(voice(t, guest=1))
    assert decide(host, 550, speaking=True).action == "hold"
    host.observe_voice(voice(600, owner=1, echo=False))
    assert decide(host, 600, speaking=True).action == "hold"
    assert host.metrics()["stops_requested"] == 0


@pytest.mark.parametrize("critical,healthy,reason", [
    (True, True, "critical_gameplay"),
    (False, False, "output_unhealthy"),
])
def test_real_time_safety_requests_stop_and_invalidates_intent(
    critical, healthy, reason,
):
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    stop = decide(host, 410, speaking=True, critical=critical, healthy=healthy)
    assert stop.action == "stop_playback"
    assert stop.reason == reason
    assert stop.stop_token == 1
    assert not host.complete(intent, now_ms=420, host_confirmed_spoken=True)
    assert decide(host, 420).action == "stop_playback"
    assert host.acknowledge_stopped(1, pcm_drained=True, avatar_neutral=True)


@pytest.mark.parametrize("critical,healthy,reason", [
    (True, True, "critical_gameplay"),
    (False, False, "output_unhealthy"),
])
def test_no_new_utterance_in_critical_or_unhealthy_state(critical, healthy, reason):
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    held = decide(host, critical=critical, healthy=healthy)
    assert held.action == "hold" and held.reason == reason


def test_stale_voice_and_long_capture_hole_hold():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    assert decide(host, 600).reason == "audio_turn_quiet_frame_not_recent"
    host.observe_voice(voice(1000))
    assert decide(host, 1000).action == "hold"


def test_reversed_clock_and_expired_event_never_prepare():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    assert decide(host, 405).action == "prepare"
    assert decide(host, 404).reason == "host_clock_reversed"
    assert not host.offer(signal(signal_id="another"), now_ms=404)
    assert decide(host, 40000).action == "hold"


def test_replay_stop_ack_cannot_clear_new_stop():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    old = host.disable(host_playout_active=True)
    assert old == 1
    assert host.acknowledge_stopped(old, pcm_drained=True, avatar_neutral=True)
    host.enable(owner_approved=True)
    new = host.disable(host_playout_active=True)
    assert new == 2
    assert not host.acknowledge_stopped(old, pcm_drained=True, avatar_neutral=True)
    assert host.acknowledge_stopped(new, pcm_drained=True, avatar_neutral=True)


@pytest.mark.parametrize("bad", [True, None, "500", float("nan"),
                                 float("inf"), -5.0, 1e20])
def test_untrusted_host_clocks_rejected(bad):
    host = NaturalTurnBridge()
    with pytest.raises(ValueError):
        decide(host, bad)


def test_disabling_active_playout_requires_host_stop_confirmation():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    assert decide(host, 100, speaking=True).action == "hold"
    token = host.disable(host_playout_active=False)
    assert token == 1
    assert host.acknowledge_stopped(token, pcm_drained=True, avatar_neutral=True)


def test_invalid_type_or_forged_ticket():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    assert intent is not None
    assert not host.complete(replace(intent), now_ms=410, host_confirmed_spoken=True)
    for data in (dict(host_playout_active=1), dict(gameplay_critical=1),
                 dict(output_healthy=1)):
        with pytest.raises(ValueError):
            host.advise(**{
                "now_ms": 410, "host_playout_active": False,
                "gameplay_critical": False, "output_healthy": True,
                **data,
            })
    with pytest.raises(ValueError):
        host.complete(intent, now_ms=420, host_confirmed_spoken=1)
    with pytest.raises(ValueError):
        host.acknowledge_stopped(True, pcm_drained=True, avatar_neutral=True)


def test_while_disabled_cannot_admit_or_speak():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    host.disable(host_playout_active=False)
    assert not host.offer(signal(), now_ms=400)
    assert not host.observe_voice(voice(400))
    assert decide(host).action == "hold"


def test_metrics_do_not_leak_voice_or_chat_content():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    decide(host)
    metrics = host.metrics()
    assert set(metrics) == {
        "prepared", "stops_requested", "stops_confirmed",
        "enabled", "stop_outstanding",
    }
    assert metrics["prepared"] == 1


def test_game_urgency_hold_invalidates_prepared_speech():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    assert intent is not None
    assert decide(host, 410, critical=True).action == "hold"
    assert not host.complete(intent, now_ms=420, host_confirmed_spoken=True)


def test_owner_event_or_new_guest_voice_invalidates_pending_tts():
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    assert intent is not None
    # A 50ms host VAD frame is not yet an authenticated barge-in, but it
    # invalidates still-pending TTS until the owner goes quiet.
    assert host.observe_voice(voice(450, guest=1))
    assert not host.complete(intent, now_ms=450, host_confirmed_spoken=True)

    # A high-priority game event supersedes a queued viewer response.
    for t in range(500, 900, 50):
        host.observe_voice(voice(t))
    intent = decide(host, 850).intent
    assert intent is not None
    host.offer(signal(850, signal_id="danger", kind="game_danger"), now_ms=850)
    assert not host.complete(intent, now_ms=860, host_confirmed_spoken=True)
