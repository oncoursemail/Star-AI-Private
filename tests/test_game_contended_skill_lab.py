"""Adversarial tests for strictly offline multi-load game-timing learning."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import math
import pytest

from star.game_latency_skill_lab import TimingScenario
from star.game_contended_skill_lab import (
    ContendedGameLabReport, LoadCase, LoadPolicy, attempt, evaluate_profile,
    fit_profile_policy, make_cases, run_contended_game_lab,
)

BASE_SEED = 2026110303
TEST_SEED = 2026110304
NAMES = ("idle", "stream_live", "heavy_contention")


@pytest.fixture(scope="module")
def practice():
    return {p: make_cases(seed=BASE_SEED, count=96, profile=p) for p in NAMES}


@pytest.fixture(scope="module")
def report():
    return run_contended_game_lab(practice_seed=BASE_SEED, holdout_seed=TEST_SEED)


def test_synthetic_report_denies_every_live_authority(report):
    assert isinstance(report, ContendedGameLabReport)
    assert report.synthetic_only
    assert not report.authorizes_real_gameplay
    assert not report.authorizes_skill_promotion
    assert not report.authorizes_broadcast
    assert report.untrained_profile_abstentions == 128


def test_load_policy_requires_every_profile(practice):
    policy = fit_profile_policy(practice)
    assert tuple(p for p, _ in policy.profile_offsets) == NAMES
    for name in NAMES:
        assert policy.correction(name) is not None
        assert -230 <= policy.correction(name) <= 40
    assert policy.correction("unseen_contention") is None
    assert policy.correction("owner_chat_says_fast") is None
    assert policy.correction(None) is None


def test_training_outcomes_are_read_only(practice):
    policy = fit_profile_policy(practice)
    with pytest.raises(FrozenInstanceError):
        policy.synthetic_only = False
    assert not policy.authorizes_broadcast


def test_practice_and_holdout_seeds_must_differ():
    with pytest.raises(ValueError, match="different"):
        run_contended_game_lab(practice_seed=123, holdout_seed=123)
    with pytest.raises(ValueError):
        run_contended_game_lab(practice_seed=True, holdout_seed=2)
    with pytest.raises(ValueError):
        run_contended_game_lab(practice_seed=1, holdout_seed=False)


def test_cross_profile_seed_salt_collision_is_detected():
    # train idle seed+101 == holdout streaming seed+211, even though the
    # caller supplied different top-level seeds. The two RNG worlds overlap.
    with pytest.raises(ValueError, match="scene collision"):
        run_contended_game_lab(practice_seed=211, holdout_seed=101,
                               practice_count=96, holdout_count=128)


@pytest.mark.parametrize("profile", (*NAMES, "unseen_contention"))
def test_dataset_deterministic_with_blinded_delays(profile):
    same = make_cases(seed=100, count=40, profile=profile)
    assert same == make_cases(seed=100, count=40, profile=profile)
    assert same != make_cases(seed=101, count=40, profile=profile)
    assert len(same) == 40
    assert all(row.profile == profile for row in same)


@pytest.mark.parametrize("bad", ["live", "", " LIVE", "stream-live", 4, None])
def test_reject_unregistered_profiles(bad):
    with pytest.raises((ValueError, TypeError)):
        make_cases(seed=10, count=40, profile=bad)


@pytest.mark.parametrize("bad", [True, False, -1, 2**63, 1.2, "2"])
def test_reject_bad_seeds(bad):
    with pytest.raises(ValueError):
        make_cases(seed=bad, count=40, profile="idle")


@pytest.mark.parametrize("bad", [0, 39, 2001, True, 20.5, "40"])
def test_reject_bad_episode_counts(bad):
    with pytest.raises(ValueError):
        make_cases(seed=100, count=bad, profile="idle")


def test_implicit_game_truth_never_exposed_as_profile():
    items = make_cases(seed=123, count=40, profile="stream_live")
    assert any(row.extra_dispatch_ms != items[0].extra_dispatch_ms for row in items[1:])
    assert all(row.scene.collision_ms > 0 for row in items)
    assert all(row.extra_inference_ms >= 15 for row in items)
    assert all(row.extra_dispatch_ms >= 20 for row in items)


def test_attempt_invokes_actual_synthetic_delay_and_not_only_inference():
    # At collision=400, perfect jump ack must arrive 195..275.
    s = TimingScenario(400, 400, 0, 0, 60)
    quiet = LoadCase("idle", s, 0, 0)
    delayed = LoadCase("stream_live", s, 0, 100)
    assert attempt(quiet, -50)
    assert not attempt(delayed, -50)


@pytest.mark.parametrize("invalid", [float("nan"), math.inf, -1, 301, True, "10", 10**900])
def test_loadcase_rejects_non_finite_or_invalid_latency(invalid):
    s = TimingScenario(400, 400, 1, 1, 1)
    with pytest.raises(ValueError):
        LoadCase("idle", s, invalid, 10)
    with pytest.raises(ValueError):
        LoadCase("idle", s, 10, invalid)


def test_no_unverified_profile_masquerades_as_idle():
    s = TimingScenario(400, 400, 1, 1, 1)
    with pytest.raises(ValueError):
        LoadCase("viewer_says_idle", s, 0, 0)


def test_train_coverage_is_strict(practice):
    with pytest.raises(ValueError):
        fit_profile_policy({"idle": practice["idle"]})
    with pytest.raises(ValueError):
        fit_profile_policy({**practice, "unexpected": practice["idle"]})
    with pytest.raises(ValueError):
        fit_profile_policy({**practice, "idle": practice["idle"][:39]})
    with pytest.raises(ValueError):
        fit_profile_policy({**practice, "idle": [*practice["idle"]]})


def test_reject_mislabeled_practice(practice):
    corrupted = {**practice, "idle": (practice["stream_live"][0], *practice["idle"][1:])}
    with pytest.raises(ValueError):
        fit_profile_policy(corrupted)


def test_frozen_policy_rejects_missing_or_forged_offsets():
    with pytest.raises(ValueError):
        LoadPolicy((("idle", -70),))
    with pytest.raises(ValueError):
        LoadPolicy((("idle", -70), ("stream_live", -80), ("stream_live", -90)))
    with pytest.raises(ValueError):
        LoadPolicy((("idle", -70), ("stream_live", -80), ("heavy_contention", 50)))
    with pytest.raises(ValueError):
        LoadPolicy((("idle", -70), ("stream_live", -80), ("heavy_contention", True)))


def test_candidate_is_measured_on_exact_matched_holdout(practice):
    policy = fit_profile_policy(practice)
    cases = make_cases(seed=TEST_SEED, count=128, profile="stream_live")
    summary = evaluate_profile(
        cases, fixed_correction=policy.correction("idle"),
        adapted_correction=policy.correction("stream_live"),
    )
    assert summary.holdout_count == 128
    assert (summary.improvements + summary.regressions) <= 128
    assert 0 <= summary.exact_one_sided_p <= 1
    assert summary.profile == "stream_live"


def test_candidate_cannot_be_evaluated_on_blended_profiles(practice):
    with pytest.raises(ValueError):
        evaluate_profile(
            (practice["idle"][0], *practice["stream_live"][:40]),
            fixed_correction=-70, adapted_correction=-80,
        )
    with pytest.raises(ValueError):
        evaluate_profile(
            practice["stream_live"][:1],
            fixed_correction=-70, adapted_correction=-80,
        )


def test_report_is_deterministic_and_json_contains_no_traces(report):
    again = run_contended_game_lab(practice_seed=BASE_SEED, holdout_seed=TEST_SEED)
    assert report == again
    encoded = report.to_json()
    assert json.loads(encoded)["untrained_profile_abstentions"] == 128
    assert "collision_ms" not in encoded
    assert "scene" not in encoded
    assert "timestamp" not in encoded
    assert "private" not in encoded


def test_adaptive_training_improves_synthetic_stream_load(report):
    by_name = {p.profile: p for p in report.profiles}
    assert set(by_name) == set(NAMES)
    assert by_name["stream_live"].adaptive_success_rate > by_name["stream_live"].static_success_rate
    assert by_name["heavy_contention"].adaptive_success_rate > by_name["heavy_contention"].static_success_rate
    assert by_name["stream_live"].improvements > by_name["stream_live"].regressions
    assert by_name["heavy_contention"].improvements > by_name["heavy_contention"].regressions


def test_no_real_load_or_voice_claims(report):
    d = json.loads(report.to_json())
    assert d["synthetic_only"] is True
    assert d["authorizes_real_gameplay"] is False
    assert d["authorizes_skill_promotion"] is False
    assert d["authorizes_broadcast"] is False


def test_distinct_holdouts_cannot_be_fed_to_training_without_explicit_call(practice):
    # A practice-only fit cannot change when evaluation scenes are generated.
    policy = fit_profile_policy(practice)
    heldout = make_cases(seed=TEST_SEED, count=128, profile="heavy_contention")
    _ = evaluate_profile(
        heldout, fixed_correction=policy.correction("idle"),
        adapted_correction=policy.correction("heavy_contention"),
    )
    assert policy == fit_profile_policy(practice)


def test_original_timing_lab_stays_usable():
    from star.game_latency_skill_lab import run_timing_skill_lab
    result = run_timing_skill_lab(practice_seed=101, holdout_seed=102)
    assert result.synthetic_only
    assert not result.authorizes_real_gameplay
