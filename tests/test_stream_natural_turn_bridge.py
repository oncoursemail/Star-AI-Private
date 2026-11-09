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


def load_sample(sample_id: str, measured_at_s: float, *,
                render_missed_pct: float = 0.0):
    from star.stream_load_governor import StreamLoadSample
    return StreamLoadSample(
        sample_id=sample_id, measured_at_s=measured_at_s,
        game_p95_frame_ms=12.0, game_target_fps=60.0,
        obs_render_missed_pct=render_missed_pct,
        obs_encode_skipped_pct=0.0, obs_network_dropped_pct=0.0,
        gpu_vram_used_mb=3800.0, gpu_vram_total_mb=8192.0,
        tts_first_audio_p95_ms=190.0,
    )


def load_governor(*, warmed: bool = True):
    from star.stream_load_governor import StreamLoadGovernor
    governor = StreamLoadGovernor()
    governor.enable(owner_approved=True)
    if warmed:
        for number, stamp in enumerate((0.1, 0.2, 0.39), start=1):
            assert governor.ingest(
                load_sample(f"normal_{number}", stamp),
                now_s=stamp + .001, host_verified=True,
            )
        assert governor.recommend(now_s=.4).profile == "normal"
    return governor


def test_opt_in_governor_allows_verified_normal_load_and_mutes_on_obs_lag():
    governor = load_governor()
    host = NaturalTurnBridge(load_governor=governor)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    prepared = decide(host)
    assert prepared.action == "prepare"
    assert prepared.intent is not None
    assert governor.ingest(
        load_sample("severe_render_lag", 0.405, render_missed_pct=4.0),
        now_s=0.406, host_verified=True,
    )
    assert governor.recommend(now_s=.41).profile == "critical"
    suppressed = decide(host, 410)
    assert suppressed.action == "hold"
    assert suppressed.reason == "no_safe_event_due"
    assert not host.complete(
        prepared.intent, now_ms=415, host_confirmed_spoken=True,
    )
    # Real high-priority game danger can still be considered during OBS lag.
    assert host.offer(signal(420, signal_id="danger", kind="game_danger"),
                      now_ms=420)
    urgent = decide(host, 420)
    assert urgent.action == "prepare"
    assert urgent.intent is not None
    assert urgent.intent.kind == "game_danger"
    assert not urgent.authorizes_playback


def test_opt_in_governor_fails_quiet_without_fresh_authenticated_telemetry():
    governor = load_governor(warmed=False)
    host = NaturalTurnBridge(load_governor=governor)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    assert decide(host).reason == "no_safe_event_due"
    # Three verified healthy samples are required, not one forged 'normal'.
    assert governor.ingest(
        load_sample("only_one", .405), now_s=.406, host_verified=True)
    assert decide(host, 410).reason == "no_safe_event_due"


def test_stale_stream_samples_revoke_prepared_speech_not_already_spoken():
    governor = load_governor()
    host = NaturalTurnBridge(load_governor=governor)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    old_plan = decide(host).intent
    assert old_plan is not None
    ready(host, at=4000)
    assert decide(host, 4000).reason == "no_safe_event_due"
    assert not host.complete(old_plan, now_ms=4010, host_confirmed_spoken=True)


def test_backward_resource_clock_rejects_planning_and_drops_prepared_intent():
    governor = load_governor()
    host = NaturalTurnBridge(load_governor=governor)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    assert intent is not None
    # Advance resource producer's monotonic clock separately from this bridge.
    assert governor.ingest(
        load_sample("advanced_host_clock", 2.0),
        now_s=2.001, host_verified=True,
    )
    held = decide(host, 405)
    assert held.action == "hold"
    assert held.reason == "resource_clock_invalid"
    assert not host.complete(intent, now_ms=410, host_confirmed_spoken=True)


def test_governor_must_be_exact_trusted_type_and_legacy_is_unchanged():
    with pytest.raises(TypeError, match="trusted StreamLoadGovernor"):
        NaturalTurnBridge(load_governor=object())
    host = NaturalTurnBridge()
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    assert decide(host).action == "prepare"


def test_opt_in_single_flight_coalesces_polling_without_tts_restarts():
    host = NaturalTurnBridge(single_flight_tts=True)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    first = decide(host).intent
    assert first is not None
    # Repeated 20-ms loop iterations must not start another TTS worker.
    for now in (410, 420, 430, 440, 450):
        decision = decide(host, now)
        assert (decision.action, decision.reason) == (
            "hold", "tts_preparation_in_flight",
        )
        assert decision.intent is None
    assert host.metrics()["single_flight_coalesced"] == 5
    assert host.metrics()["prepared"] == 1
    assert host.complete(first, now_ms=460, host_confirmed_spoken=True)
    assert decide(host, 470).action == "hold"


def test_opt_in_single_flight_lease_reissues_only_with_fresh_silence():
    host = NaturalTurnBridge(single_flight_tts=True, preparation_lease_ms=300)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    old = decide(host).intent
    assert old is not None
    assert decide(host, 650).action == "hold"  # expired quiet proof
    ready(host, at=900)
    current = decide(host, 900).intent
    assert current is not None and current is not old
    assert not host.complete(old, now_ms=910, host_confirmed_spoken=True)
    assert host.complete(current, now_ms=920, host_confirmed_spoken=True)
    assert host.metrics()["prepared"] == 2


def test_opt_in_single_flight_real_viewer_question_preempts_ambient_draft():
    host = NaturalTurnBridge(single_flight_tts=True)
    host.enable(owner_approved=True)
    ready(host)
    ambient = StreamSignal(
        "ambient1", "ambient", 0.4, "A quiet moment to think.",
    )
    assert host.offer(ambient, now_ms=400)
    old = decide(host).intent
    assert old is not None and old.kind == "ambient"
    question = signal(410)
    assert host.offer(question, now_ms=410)
    next_decision = decide(host, 410)
    assert next_decision.action == "prepare"
    assert next_decision.intent is not None
    assert next_decision.intent.kind == "viewer_question"
    assert not host.complete(old, now_ms=420, host_confirmed_spoken=True)


def test_opt_in_single_flight_game_danger_overrides_pending_question():
    host = NaturalTurnBridge(single_flight_tts=True)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    old = decide(host).intent
    assert old is not None
    assert host.offer(signal(410, signal_id="danger1", kind="game_danger"),
                      now_ms=410)
    urgent = decide(host, 410)
    assert urgent.action == "prepare"
    assert urgent.intent is not None and urgent.intent.kind == "game_danger"
    assert not host.complete(old, now_ms=420, host_confirmed_spoken=True)


def test_opt_in_single_flight_resource_pressure_revokes_old_draft():
    governor = load_governor()
    host = NaturalTurnBridge(
        load_governor=governor, single_flight_tts=True,
    )
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    old = decide(host).intent
    assert old is not None
    assert decide(host, 401).reason == "tts_preparation_in_flight"
    assert governor.ingest(
        load_sample("critical_speech_budget", 0.405, render_missed_pct=4.0),
        now_s=0.406, host_verified=True,
    )
    held = decide(host, 410)
    assert held.reason == "no_safe_event_due"
    assert not host.complete(old, now_ms=415, host_confirmed_spoken=True)


def test_opt_in_single_flight_disable_and_quiet_revoke_draft():
    host = NaturalTurnBridge(single_flight_tts=True)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    old = decide(host).intent
    assert old is not None
    host.observe_voice(voice(450, guest=1))
    assert not host.complete(old, now_ms=450, host_confirmed_spoken=True)
    assert host.disable(host_playout_active=False) is None
    host.enable(owner_approved=True)
    assert decide(host, 450).action == "hold"


@pytest.mark.parametrize("kwargs", [
    {"single_flight_tts": 1},
    {"single_flight_tts": None},
    {"preparation_lease_ms": True},
    {"preparation_lease_ms": 249},
    {"preparation_lease_ms": 15001},
    {"preparation_lease_ms": 8.5},
])
def test_single_flight_configuration_rejects_untrusted_types(kwargs):
    with pytest.raises(ValueError):
        NaturalTurnBridge(**kwargs)


# Live TTS worker must present its original plan at the final first-PCM
# boundary. This is opt-in, advisory, and never an audio/broadcast permission.
def review(host, intent, now=410, *, active=False, critical=False,
           healthy=True, ready_pcm=True, verified=True):
    return host.revalidate_prepared(
        intent, now_ms=now, host_playout_active=active,
        gameplay_critical=critical, output_healthy=healthy,
        pcm_output_ready=ready_pcm, host_verified=verified,
    )


def test_strict_preplay_requires_fresh_review_before_spoken_commit():
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    assert intent is not None
    assert not host.complete(intent, now_ms=401, host_confirmed_spoken=True)
    result = review(host, intent)
    assert (result.action, result.reason) == ("reviewed", "fresh_preplay_candidate")
    assert result.intent is intent
    assert not result.authorizes_playback and not result.authorizes_broadcast
    assert not result.authorizes_game_input
    assert review(host, intent, 411).reason == "preplay_ticket_already_reviewed"
    assert host.complete(intent, now_ms=420, host_confirmed_spoken=True)
    assert not host.complete(intent, now_ms=421, host_confirmed_spoken=True)
    assert host.metrics()["preplay_reviewed"] == 1
    assert host.metrics()["preplay_denied"] == 1


@pytest.mark.parametrize("kwargs,expected", [
    ({"verified": False}, "physical_host_evidence_missing"),
    ({"ready_pcm": False}, "physical_host_evidence_missing"),
    ({"active": True}, "unsafe_native_output_or_gameplay"),
    ({"critical": True}, "unsafe_native_output_or_gameplay"),
    ({"healthy": False}, "unsafe_native_output_or_gameplay"),
])
def test_strict_preplay_denies_untrusted_or_unhealthy_native_handoff(kwargs, expected):
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    stale = decide(host).intent
    assert stale is not None
    assert review(host, stale, **kwargs).reason == expected
    assert not host.complete(stale, now_ms=415, host_confirmed_spoken=True)


def test_strict_preplay_denies_expired_worker_and_old_replaced_plan():
    host = NaturalTurnBridge(
        single_flight_tts=True, require_preplay_recheck=True,
        preparation_lease_ms=300,
    )
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    first = decide(host).intent
    assert first is not None
    assert review(host, first, 700).reason == "preplay_ticket_expired_or_scene_changed"
    assert not host.complete(first, now_ms=705, host_confirmed_spoken=True)
    ready(host, at=1000)
    newest = decide(host, 1000).intent
    assert newest is not None and newest is not first
    assert review(host, first, 1001).reason == "stale_or_superseded_tts_ticket"
    assert review(host, newest, 1010).action == "reviewed"


def test_strict_preplay_fresh_vad_is_required_after_delayed_synthesis():
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    pending = decide(host).intent
    assert pending is not None
    assert review(host, pending, 600).reason.startswith("audio_turn_")
    assert not host.complete(pending, now_ms=610, host_confirmed_spoken=True)


def test_strict_preplay_revalidates_source_after_game_scene_rebind():
    from star.stream_director import StreamDirector
    director = StreamDirector()
    host = NaturalTurnBridge(
        director=director, single_flight_tts=True,
        require_preplay_recheck=True,
    )
    host.enable(owner_approved=True)
    director.bind_game_scope("game-a", owner_approved=True)
    ready(host)
    game_signal = StreamSignal(
        "scene-event", "game_success", 0.4, "Finished a level!",
        evidence="observed", game_scope="game-a",
    )
    assert host.offer(game_signal, now_ms=400)
    pending = decide(host).intent
    assert pending is not None
    assert director.has_live_intent(pending, now=.4)
    director.bind_game_scope("game-b", owner_approved=True)
    assert not director.has_live_intent(pending, now=.405)
    assert review(host, pending, 410).reason == "preplay_ticket_expired_or_scene_changed"
    assert not host.complete(pending, now_ms=420, host_confirmed_spoken=True)


def test_strict_preplay_revokes_on_observed_critical_load_between_tts_and_pcm():
    governor = load_governor()
    host = NaturalTurnBridge(
        load_governor=governor, single_flight_tts=True,
        require_preplay_recheck=True,
    )
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    pending = decide(host).intent
    assert pending is not None
    assert governor.ingest(
        load_sample("preplay_render_pressure", .405, render_missed_pct=4),
        now_s=.406, host_verified=True,
    )
    assert review(host, pending, 410).reason == "resource_pressure_at_preplay"
    assert not host.complete(pending, now_ms=415, host_confirmed_spoken=True)


def test_strict_preplay_rejects_counterfeit_and_backward_host_clock():
    from dataclasses import replace
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    pending = decide(host).intent
    assert pending is not None
    assert review(host, replace(pending), 405).reason == "stale_or_superseded_tts_ticket"
    assert review(host, pending, 399).reason == "host_clock_reversed"
    assert review(host, pending, 410).action == "reviewed"


@pytest.mark.parametrize("kwargs", [
    {"require_preplay_recheck": 1, "single_flight_tts": True},
    {"require_preplay_recheck": None, "single_flight_tts": True},
    {"require_preplay_recheck": True},
])
def test_strict_preplay_config_fails_closed(kwargs):
    with pytest.raises(ValueError):
        NaturalTurnBridge(**kwargs)


@pytest.mark.parametrize("bad_kwargs", [
    {"host_playout_active": 1},
    {"gameplay_critical": "false"},
    {"output_healthy": None},
    {"pcm_output_ready": 1},
    {"host_verified": 1},
])
def test_strict_preplay_rejects_untyped_host_evidence(bad_kwargs):
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    intent = decide(host).intent
    assert intent is not None
    kwargs = {
        "now_ms": 410, "host_playout_active": False,
        "gameplay_critical": False, "output_healthy": True,
        "pcm_output_ready": True, "host_verified": True,
    }
    kwargs.update(bad_kwargs)
    with pytest.raises(ValueError):
        host.revalidate_prepared(intent, **kwargs)


def test_strict_preplay_concurrent_tts_callbacks_cannot_double_review():
    from concurrent.futures import ThreadPoolExecutor
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    host.offer(signal(), now_ms=400)
    pending = decide(host).intent
    assert pending is not None
    with ThreadPoolExecutor(max_workers=12) as pool:
        decisions = list(pool.map(lambda _: review(host, pending), range(30)))
    assert sum(item.action == "reviewed" for item in decisions) == 1
    assert all(item.action in {"reviewed", "hold"} for item in decisions)
    assert host.metrics()["preplay_reviewed"] == 1


def test_strict_preplay_game_danger_preempts_older_synthesized_question():
    host = NaturalTurnBridge(single_flight_tts=True, require_preplay_recheck=True)
    host.enable(owner_approved=True)
    ready(host)
    assert host.offer(signal(), now_ms=400)
    old = decide(host).intent
    assert old is not None
    assert host.offer(signal(410, signal_id="observed-danger", kind="game_danger"),
                      now_ms=410)
    assert review(host, old, 410).reason == "stale_or_superseded_tts_ticket"
    current = decide(host, 410).intent
    assert current is not None and current.kind == "game_danger"
    assert review(host, current, 411).action == "reviewed"
