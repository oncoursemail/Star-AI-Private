"""Fail-closed, synthetic tests for Star's game action-to-visual-effect bridge."""
from dataclasses import replace

import pytest

from star.game_action_gate import GameFrame, GameScope
from star.game_visual_effects import (
    EffectTicket, GameVisualEffectProbe,
)
from star.stream_observe import FocusSample, FrameCue

SCOPE = GameScope("roblox_obby", "v1", "episode9")
OTHER = GameScope("roblox_obby", "v1", "episode10")
S1 = FocusSample((0, 0, 20, 20), 0, 0)
S2 = FocusSample((0, 0, 20, 20), 0, 63)
HASH = "a" * 64


def frame(seq=1, at=1000, *, scope=SCOPE, focused=True, playable=True):
    return GameFrame(scope, seq, at, HASH, focused, playable, 0.98)


def cue(at=1000, *, game=0, hud=0, tone=0, hudtone=0, samples=(S1,)):
    return FrameCue(at, game, hud_hash=hud, tone_signature=tone,
                    hud_tone_signature=hudtone, focus_samples=samples)


def ready(**opts):
    probe = GameVisualEffectProbe(**opts)
    probe.start(SCOPE, ("jump", "dash"), owner_approved=True,
                game_session_approved=True)
    return probe


def arm(probe, *, pre=None, initial=None, action="jump",
        released=1070, now=1100, released_ok=True, capture_ok=True):
    return probe.arm(
        pre or frame(), initial or cue(), action_id=action,
        released_ms=released, now_ms=now,
        host_input_released=released_ok, host_capture_verified=capture_ok,
    )


def observe(probe, ticket, *, seq=2, at=1160, now=None, after=None,
            snapshot=None, capture_ok=True):
    return probe.observe(ticket, after or frame(seq, at),
                         snapshot or cue(at), now_ms=at + 10 if now is None else now,
                         host_capture_verified=capture_ok)


def test_no_inferred_permission_default_is_off():
    p = GameVisualEffectProbe()
    assert not p.status()["enabled"]
    with pytest.raises(PermissionError):
        p.start(SCOPE, ["jump"], owner_approved=True)
    with pytest.raises(PermissionError):
        p.start(SCOPE, ["jump"], game_session_approved=True)
    assert not arm(p).accepted
    assert not p.status()["pending"]


@pytest.mark.parametrize("actions", [
    [], ["jump", "jump"], ["!jump"], ["jump"] * 33, ("jump", 3),
])
def test_host_curated_action_validation(actions):
    p = GameVisualEffectProbe()
    with pytest.raises(ValueError):
        p.start(SCOPE, actions, owner_approved=True, game_session_approved=True)


@pytest.mark.parametrize("options", [
    {"window_ms": 299}, {"window_ms": True},
    {"min_frame_spacing_ms": 0}, {"confirmations": 1},
    {"game_novelty_bits": 0}, {"tone_novelty_bins": 64},
    {"window_ms": 300, "min_post_delay_ms": 250,
     "min_frame_spacing_ms": 80, "confirmations": 3},
])
def test_invalid_configurations_fail_closed(options):
    with pytest.raises(ValueError):
        GameVisualEffectProbe(**options)


def test_no_probe_from_non_curated_action_or_model_only_claim():
    p = ready()
    assert arm(p, action="send_chat").reason == "action_not_owner_curated"
    assert arm(p, released_ok=False).reason == "host_release_or_capture_missing"
    assert arm(p, capture_ok=False).reason == "host_release_or_capture_missing"
    assert p.status()["armed"] == 0


def test_fresh_before_capture_and_game_scope_are_mandatory():
    p = ready()
    assert arm(p, pre=frame(scope=OTHER)).reason == "game_version_or_episode_mismatch"
    assert arm(p, pre=frame(focused=False)).reason == "game_focus_or_perception_unavailable"
    assert arm(p, pre=frame(playable=False)).reason == "game_focus_or_perception_unavailable"
    assert arm(p, initial=cue(999)).accepted  # +1ms capture clock tolerance
    p.stop()
    p = ready()
    assert arm(p, initial=cue(900)).reason == "unpaired_before_capture"
    assert arm(p, released=990).reason == "input_release_not_fresh_or_before_capture"
    assert arm(p, released=1080, now=1500).reason == "input_release_not_fresh_or_before_capture"
    p = ready()
    assert arm(p, released=1111, now=1100).reason == "input_release_not_fresh_or_before_capture"


def test_changed_game_requires_two_separate_fresh_frames_and_is_not_game_success():
    p = ready()
    admission = arm(p)
    assert admission.accepted
    assert admission.ticket is not None
    ticket = admission.ticket
    first = observe(p, ticket, snapshot=cue(1160, game=0xFFFF))
    assert first.status == "awaiting_confirmation"
    assert first.comparisons == 1
    assert not first.independently_verified_success
    second = observe(p, ticket, seq=3, at=1230,
                     snapshot=cue(1230, game=0xFFFF))
    assert second.status == "visual_change_detected"
    assert second.game_bits == 16
    assert second.action_to_capture_ms == 160
    assert second.comparisons == 2
    assert not second.authorized_to_play
    assert not second.independently_verified_success
    assert not p.status()["pending"]
    assert p.status()["changed"] == 1
    assert observe(p, ticket, seq=4, at=1320).status == "rejected"


@pytest.mark.parametrize("change", [
    {"hud": 0xFF}, {"hudtone": 63}, {"tone": 63}, {"samples": (S2,)},
])
def test_hud_color_and_focused_region_changes_are_detected_independently(change):
    p = ready()
    ticket = arm(p).ticket
    assert observe(p, ticket, snapshot=cue(1160, **change)).status == (
        "awaiting_confirmation")
    result = observe(p, ticket, seq=3, at=1230,
                     snapshot=cue(1230, **change))
    assert result.status == "visual_change_detected"


def test_unchanged_scene_must_be_observed_twice_without_success_assumption():
    p = ready()
    ticket = arm(p).ticket
    assert observe(p, ticket).status == "awaiting_confirmation"
    finding = observe(p, ticket, seq=3, at=1230)
    assert finding.status == "no_visible_change"
    assert finding.comparisons == 2
    assert finding.game_bits == 0
    assert finding.changed_focus_regions == 0
    assert not finding.independently_verified_success


def test_mixed_novelty_does_not_synthesize_persistent_change():
    p = ready()
    ticket = arm(p).ticket
    observe(p, ticket, snapshot=cue(1160, game=0xFFFF))
    mixed = observe(p, ticket, seq=3, at=1230)
    assert mixed.status == "awaiting_confirmation"
    assert mixed.comparisons == 2
    result = observe(p, ticket, seq=4, at=1300)
    assert result.status == "no_visible_change"
    assert result.comparisons == 3


def test_duplicate_reordered_or_too_soon_post_frame_not_counted():
    p = ready()
    ticket = arm(p).ticket
    assert observe(p, ticket, seq=2, at=1095).reason == "post_frame_not_in_window"
    assert observe(p, ticket, seq=1, at=1160).reason == "duplicate_or_reordered_frame"
    assert observe(p, ticket, seq=2, at=1160).comparisons == 1
    assert observe(p, ticket, seq=2, at=1160).reason == "duplicate_or_reordered_frame"
    assert observe(p, ticket, seq=3, at=1180).reason == "post_frames_too_close"
    assert observe(p, ticket, seq=3, at=1240).status == "no_visible_change"


def test_mismatched_crops_are_inconclusive_not_unchanged():
    p = ready()
    ticket = arm(p).ticket
    changed_roi = FocusSample((30, 30, 20, 20), 0, 0)
    result = observe(p, ticket, snapshot=cue(1160, samples=(changed_roi,)))
    assert result.status == "inconclusive"
    assert result.reason == "capture_regions_or_sensor_scope_changed"
    assert not p.status()["pending"]


@pytest.mark.parametrize("bad_snapshot", [
    cue(1160, hud=None), cue(1160, tone=None),
    cue(1160, hudtone=None), cue(1160, samples=()),
])
def test_scope_changed_or_dropped_sensor_cannot_claim_visual_change(bad_snapshot):
    p = ready()
    ticket = arm(p).ticket
    result = observe(p, ticket, snapshot=bad_snapshot)
    assert result.status == "inconclusive"


def test_invalid_late_or_unfocused_frames_cannot_affect_learning():
    p = ready()
    ticket = arm(p).ticket
    out = observe(p, ticket, after=frame(2, 1160, scope=OTHER))
    assert out.reason == "game_changed_or_unfocused"
    p = ready()
    ticket = arm(p).ticket
    assert observe(p, ticket, after=frame(2, 1160, focused=False)).status == (
        "inconclusive")
    p = ready()
    ticket = arm(p).ticket
    assert observe(p, ticket, after=frame(2, 1160), snapshot=cue(1150)).reason == (
        "unpaired_post_capture")
    p = ready()
    ticket = arm(p).ticket
    assert observe(p, ticket, seq=2, at=1160, now=1500).reason == (
        "post_frame_not_in_window")


def test_deadline_revocation_and_foreign_ticket_are_safe():
    p = ready()
    ticket = arm(p).ticket
    forged = replace(ticket)
    assert observe(p, forged).reason == "stale_or_foreign_ticket"
    assert p.status()["pending"]
    result = observe(p, ticket, seq=2, at=2700, now=2701)
    assert result.reason == "action_effect_window_expired"
    assert p.status()["expired"] == 1
    assert not p.status()["pending"]
    p.stop()
    p.start(SCOPE, ["jump"], owner_approved=True, game_session_approved=True)
    assert observe(p, ticket).status == "rejected"


def test_repeated_start_and_replay_baselines_are_rejected():
    p = ready()
    first = arm(p)
    assert not arm(p).accepted
    assert arm(p).reason == "prior_attempt_unresolved"
    observe(p, first.ticket)
    observe(p, first.ticket, seq=3, at=1230)
    assert arm(p, released=1350, now=1360).reason == "replayed_before_frame"
    assert arm(p, pre=frame(4, 1320), initial=cue(1320),
               released=1350, now=1360).accepted


def test_cue_named_win_does_not_count_as_verified_victory():
    p = ready()
    ticket = arm(p).ticket
    a = FrameCue(1160, 0, cue="win", hud_hash=0,
                 tone_signature=0, hud_tone_signature=0, focus_samples=(S1,))
    b = replace(a, captured_ms=1230)
    assert observe(p, ticket, snapshot=a).status == "awaiting_confirmation"
    finding = observe(p, ticket, seq=3, at=1230, snapshot=b)
    assert finding.status == "no_visible_change"
    assert not finding.independently_verified_success


def test_status_is_private_and_timestamp_is_strict():
    p = ready()
    with pytest.raises(ValueError):
        arm(p, released=float("nan"))
    with pytest.raises(ValueError):
        arm(p, released=True)
    assert arm(p).accepted
    assert set(p.status()) == {
        "armed", "rejected", "changed", "unchanged", "inconclusive",
        "expired", "stopped", "enabled", "pending",
    }
    with pytest.raises(ValueError):
        observe(p, EffectTicket(1, 1, 1), now=1099)
