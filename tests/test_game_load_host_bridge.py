"""Adversarial tests for passive, real-host game/OBS load evidence conversion."""
from __future__ import annotations

from dataclasses import replace

import pytest

from star.game_capture_to_action_benchmark import CaptureToActionTrial
from star.game_load_host_bridge import GameHostLoadTick, assess_host_game_load
from star.obs_stats_window import ObsLagWindow


def tick(
    n: int, *, latency_shift: int = 0, variant: str = "baseline",
    output_lag: float = .1, render_lag: float = .1, version: str = "v1",
) -> GameHostLoadTick:
    start = n * 1000 + 100
    trial = CaptureToActionTrial(
        pair_id=f"pair{n}", variant=variant, episode_id=f"episode{n}",
        game_id="privategame", game_version=version,
        scenario_id=f"room{n}", initial_state_sha256="a" * 64,
        capture_start_ms=start, capture_end_ms=start + 5,
        transfer_end_ms=start + 15, preprocess_end_ms=start + 25,
        inference_end_ms=start + 65,
        input_ack_ms=start + 90 + latency_shift,
        scene_deadline_ms=start + 500,
        world_frame_at_capture=n * 100 + 1000,
        world_frame_at_preprocess=n * 100 + 1001,
        world_frame_at_inference=n * 100 + 1003,
        world_frame_at_ack=n * 100 + 1005,
        nominal_world_fps=60,
        progress_before=0, progress_after=.1, objective_success=False,
        game_p99_frame_ms=18, obs_dropped_pct=.1,
        independently_measured=True,
    )
    return GameHostLoadTick(
        trial=trial,
        obs=ObsLagWindow(
            observed_ms=(n + 1) * 1000,
            render_lag_pct=render_lag, output_lag_pct=output_lag,
            window_ms=1000,
        ),
        host_session_id="windows-host", profile="stream_live",
        gpu_free_mib=3000, host_verified=True, obs_continuity_verified=True,
    )


@pytest.fixture
def windows():
    return tuple(tick(i) for i in range(24)), tuple(tick(i) for i in range(24, 48))


def check(before, after, *, now_ms=49000, **kwargs):
    return assess_host_game_load(before, after, now_ms=now_ms, **kwargs)


def test_stable_observation_never_authorizes_gameplay_or_broadcast(windows):
    report = check(*windows)
    assert report.status == "stable_observation"
    assert report.baseline_count == report.current_count == 24
    assert report.baseline_p95_ms == report.current_p95_ms == 90
    assert report.profile == "stream_live"
    assert not report.candidate_for_manual_rehearsal
    assert not report.authorizes_real_gameplay
    assert not report.authorizes_skill_promotion
    assert not report.authorizes_broadcast


def test_translation_uses_full_latency_not_just_inference():
    row = tick(0).to_sample()
    assert row.capture_to_ack_ms == 90
    assert row.inference_ms == 40
    assert row.dispatch_ms == 25
    assert row.obs_skipped_pct == .1
    assert row.game_scope == "privategame:v1"


def test_drift_uses_both_render_and_output_lag(windows):
    before, after = windows
    after = tuple(replace(x, obs=replace(x.obs, output_lag_pct=2)) if i == 7
                  else x for i, x in enumerate(after))
    report = check(before, after)
    assert report.status == "degraded"
    assert "obs_frame_skip_regression" in report.reasons
    after = tuple(replace(x, obs=replace(x.obs, render_lag_pct=3)) if i == 7
                  else x for i, x in enumerate(windows[1]))
    assert "obs_frame_skip_regression" in check(before, after).reasons


def test_latency_spikes_survive_conversion(windows):
    before, after = windows
    # +110ms on a single action; update OBS end to preserve enclosure.
    after = tuple(replace(x, trial=replace(x.trial,
                     input_ack_ms=x.trial.input_ack_ms + 110,
                     world_frame_at_ack=x.trial.world_frame_at_ack + 7))
                  if i == 13 else x for i, x in enumerate(after))
    assert "single_action_latency_spike" in check(before, after).reasons


def test_missing_ack_is_degraded_and_never_discarded(windows):
    before, after = windows
    after = tuple(replace(x, trial=replace(x.trial,
                     input_ack_ms=None, world_frame_at_ack=None))
                  if i == 5 else x for i, x in enumerate(after))
    report = check(before, after)
    assert report.status == "degraded"
    assert report.missed_input_acks == 1
    assert "missing_input_ack" in report.reasons
    assert after[5].to_sample().dispatch_ms is None


def test_unverified_game_or_obs_continuity_rejected(windows):
    item = windows[0][0]
    for changed in (
        replace(item, host_verified=False),
        replace(item, obs_continuity_verified=False),
        replace(item, trial=replace(item.trial, independently_measured=False)),
    ):
        with pytest.raises(ValueError, match="evidence required"):
            changed.to_sample()


def test_false_or_string_verified_flags_not_silently_accepted():
    item = tick(0)
    for field in ("host_verified", "obs_continuity_verified"):
        with pytest.raises(ValueError):
            replace(item, **{field: 1}).to_sample()
        with pytest.raises(ValueError):
            replace(item, **{field: "true"}).to_sample()


def test_window_reuse_with_different_episode_ids_rejected(windows):
    before, after = windows
    source = before[1].trial
    moved = replace(
        source, capture_start_ms=300, capture_end_ms=305,
        transfer_end_ms=315, preprocess_end_ms=325,
        inference_end_ms=365, input_ack_ms=390, scene_deadline_ms=800,
    )
    second = replace(before[1], trial=moved, obs=before[0].obs)
    assert second.to_sample().capture_to_ack_ms == 90
    with pytest.raises(ValueError, match="overlapping OBS"):
        check((before[0], second) + before[2:], after)


def test_partially_overlapping_windows_rejected(windows):
    before, after = windows
    second = tick(1)
    second = replace(second, obs=ObsLagWindow(
        observed_ms=1500, window_ms=1000,
        render_lag_pct=.1, output_lag_pct=.1))
    with pytest.raises(ValueError, match="overlapping OBS"):
        check((before[0], second) + before[2:], after)


def test_reused_game_trial_time_rejected(windows):
    before, after = windows
    duplicated = replace(before[1], trial=replace(
        before[1].trial,
        capture_start_ms=before[0].trial.capture_start_ms,
        capture_end_ms=before[0].trial.capture_end_ms,
        transfer_end_ms=before[0].trial.transfer_end_ms,
        preprocess_end_ms=before[0].trial.preprocess_end_ms,
        inference_end_ms=before[0].trial.inference_end_ms,
        input_ack_ms=before[0].trial.input_ack_ms,
        scene_deadline_ms=before[0].trial.scene_deadline_ms))
    with pytest.raises(ValueError):
        check((before[0], duplicated) + before[2:], after)


def test_game_version_change_inconclusive(windows):
    before, after = windows
    after = tuple(replace(x, trial=replace(x.trial, game_version="v2")) for x in after)
    report = check(before, after)
    assert report.status == "inconclusive"
    assert "changed_host_game_or_load_profile" in report.reasons


def test_model_variant_switch_cannot_masquerade_as_load_drift(windows):
    before, after = windows
    after = tuple(replace(x, trial=replace(x.trial, variant="candidate")) for x in after)
    with pytest.raises(ValueError, match="distinct model variants"):
        check(before, after)


def test_game_world_freeze_rejected_not_promoted():
    row = tick(0)
    frozen = replace(row, trial=replace(
        row.trial, world_frame_at_preprocess=1000,
        world_frame_at_inference=1000, world_frame_at_ack=1000))
    with pytest.raises(ValueError, match="world did not"):
        frozen.to_sample()


def test_invalid_metric_cannot_create_stable_observation():
    row = tick(0)
    for obs in (
        replace(row.obs, output_lag_pct=float("nan")),
        replace(row.obs, render_lag_pct=120),
        replace(row.obs, window_ms=-2),
        replace(row.obs, observed_ms=float("inf")),
    ):
        with pytest.raises(ValueError):
            replace(row, obs=obs).to_sample()
    with pytest.raises(ValueError):
        replace(row, gpu_free_mib=True).to_sample()


def test_bad_clock_enclosure_rejected():
    row = tick(0)
    with pytest.raises(ValueError, match="enclosed"):
        replace(row, obs=replace(row.obs, window_ms=100)).to_sample()
    with pytest.raises(ValueError, match="enclosed"):
        replace(row, obs=replace(row.obs, observed_ms=150)).to_sample()


def test_no_unbounded_input_consumption(windows):
    before, after = windows
    infinite = (tick(i) for i in range(1000000000))
    with pytest.raises(ValueError, match="too many host observations"):
        check(infinite, after)


def test_stale_evidence_inconclusive(windows):
    report = check(*windows, now_ms=60000)
    assert report.status == "inconclusive"
    assert "stale_or_future_current_window" in report.reasons


def test_unsupported_host_profile_rejected():
    row = tick(0)
    with pytest.raises(ValueError):
        replace(row, profile="stream_live;broadcast").to_sample()


def test_short_windows_cannot_claim_stability(windows):
    before, after = windows
    report = check(before[:5], after[:5])
    assert report.status == "inconclusive"
    assert "insufficient_samples" in report.reasons
