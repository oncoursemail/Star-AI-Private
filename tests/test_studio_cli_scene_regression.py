"""Adversarial tests for owner-approved before/after engine QA."""
from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from star.studio_cli_scene_audit import CliSceneAudit, FIELDS, MARK
from star.studio_cli_scene_regression import (
    SceneRegressionPolicy, audit_scene_change, compare_scene_audits,
)


def counts(**updates):
    return {
        "descendants": 12, "base_parts": 6, "spawn_locations": 1,
        "unanchored_collidable": 0, "invisible_collidable": 0,
        "tiny_parts": 0, "models_without_primary_part": 0,
        **updates,
    }


def evidence(**updates):
    c = counts(**updates)
    return CliSceneAudit("observed", place_id=0, game_id=0,
                         counts=tuple((name, c[name]) for name in FIELDS))


def test_no_detected_difference_is_not_quality_pass():
    report = compare_scene_audits(evidence(), evidence())
    assert report.status == "no_detected_difference"
    assert report.concerns == ()
    assert not report.verified_playthrough
    assert not report.authorized_to_edit
    assert not report.authorized_to_publish


def test_improvements_eligible_for_review_not_autopublishing():
    before = evidence(unanchored_collidable=2, invisible_collidable=1,
                      tiny_parts=1, models_without_primary_part=3)
    after = evidence(unanchored_collidable=1, invisible_collidable=0,
                     tiny_parts=0, models_without_primary_part=1)
    report = compare_scene_audits(before, after)
    assert report.status == "ready_for_review"
    assert report.concerns == ()
    assert dict(report.deltas)["unanchored_collidable"] == -1
    assert not report.authorized_to_publish


@pytest.mark.parametrize(("key", "issue"), [
    ("unanchored_collidable", "increase:unanchored_collidable"),
    ("invisible_collidable", "increase:invisible_collidable"),
    ("tiny_parts", "increase:tiny_parts"),
    ("models_without_primary_part", "increase:models_without_primary_part"),
])
def test_new_risks_flagged_even_when_other_metrics_improve(key, issue):
    report = compare_scene_audits(evidence(), evidence(**{key: 1}))
    assert report.status == "regression"
    assert issue in report.concerns


def test_massing_deletion_and_lost_spawns_not_mistaken_for_fix():
    before = evidence(unanchored_collidable=2)
    after = evidence(descendants=5, base_parts=2, spawn_locations=0)
    report = compare_scene_audits(before, after)
    assert report.status == "regression"
    assert "large_basepart_loss" in report.concerns
    assert "large_descendant_loss" in report.concerns
    assert "lost_spawn_locations" in report.concerns


def test_curated_intentional_changes_allow_bounded_thresholds():
    before = evidence()
    after = evidence(base_parts=7, descendants=13, invisible_collidable=1)
    p = SceneRegressionPolicy(allowed_increases=(("invisible_collidable", 1),))
    report = compare_scene_audits(before, after, policy=p)
    assert report.status == "ready_for_review"


@pytest.mark.parametrize("bad", [
    (("no_such_metric", 1),),
    (("tiny_parts", -1),),
    (("tiny_parts", 1.5),),
    (("tiny_parts", True),),
    (("tiny_parts", 1), ("tiny_parts", 2)),
    (("tiny_parts", 50001),),
])
def test_invalid_policy_cannot_widen_thresholds(bad):
    with pytest.raises(ValueError):
        SceneRegressionPolicy(allowed_increases=bad)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_retention_thresholds(value):
    with pytest.raises(ValueError):
        SceneRegressionPolicy(min_basepart_retention=value)
    with pytest.raises(ValueError):
        SceneRegressionPolicy(min_descendant_retention=value)


def test_only_exact_boolean_spawn_setting_is_valid():
    with pytest.raises(ValueError):
        SceneRegressionPolicy(preserve_spawns=1)


def test_invalid_unverified_and_identity_mismatched_audits_fail():
    assert compare_scene_audits(evidence(), CliSceneAudit("timeout")).status == "invalid"
    assert compare_scene_audits(evidence(), CliSceneAudit(
        "observed", place_id=444, game_id=0, counts=evidence().counts,
    )).status == "invalid"
    assert compare_scene_audits(evidence(), CliSceneAudit(
        "observed", place_id=0, game_id=0, counts=(("descendants", 4),),
    )).status == "invalid"
    assert compare_scene_audits(evidence(), CliSceneAudit(
        "observed", place_id=0, game_id=0,
        counts=tuple((k, True if k == "base_parts" else v)
                     for k, v in evidence().counts),
    )).status == "invalid"
    assert compare_scene_audits(evidence(), CliSceneAudit(
        "observed", place_id=0, game_id=0,
        counts=tuple((k, 7 if k == "spawn_locations" else v)
                     for k, v in evidence().counts),
    )).status == "invalid"


def test_invalid_policy_type_rejected():
    with pytest.raises(TypeError):
        compare_scene_audits(evidence(), evidence(), policy=object())


def fixtures(tmp_path):
    exe = tmp_path / "RobloxStudioBeta.exe"
    exe.write_bytes(b"studio-mock")
    trusted = tmp_path / "owner"
    trusted.mkdir()
    before = trusted / "before.rbxlx"
    after = trusted / "after.rbxlx"
    before.write_text("<roblox>known baseline</roblox>")
    after.write_text("<roblox>known candidate</roblox>")
    return exe, trusted, before, after


def runner_factory(before, after, *, change_during=None, bad_second=False):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        source = Path(argv[argv.index("--localPlaceFile") + 1])
        assert source in (before, after)
        code = Path(argv[argv.index("--runScriptFile") + 1]).read_text()
        nonce = re.search(r'local challenge = "([0-9a-f]{32})"', code).group(1)
        c = counts() if source == before else counts(
            descendants=13, base_parts=7, unanchored_collidable=1)
        payload = {
            "challenge": nonce, "ok": True, "place_id": 0, "game_id": 0,
            "counts": c,
        }
        if bad_second and source == after:
            payload["challenge"] = "0" * 32
        output = Path(argv[argv.index("--outputFile") + 1])
        output.write_text(MARK + json.dumps(payload) + "\n")
        if source == after and change_during is not None:
            change_during.write_bytes(b"attacker mutation")
        return SimpleNamespace(returncode=0)
    return run, calls


def run_change(tmp_path, runner, **kw):
    exe, root, before, after = fixtures(tmp_path)
    return audit_scene_change(
        studio_executable=exe, baseline_fixture=before,
        candidate_fixture=after, trusted_workspace=root, runner=runner,
        owner_approved=True, streaming_idle=True, **kw,
    )


def test_realtime_protection_disabled_by_default(tmp_path):
    exe, root, before, after = fixtures(tmp_path)
    def forbidden(*a, **k):
        raise AssertionError("must not launch")
    args = dict(studio_executable=exe, baseline_fixture=before,
                candidate_fixture=after, trusted_workspace=root, runner=forbidden)
    assert audit_scene_change(**args).status == "disabled"
    assert audit_scene_change(**args, owner_approved=True).status == "deferred"
    assert audit_scene_change(**args, owner_approved=1).status == "disabled"
    assert audit_scene_change(**args, owner_approved=True, streaming_idle=1).status == "deferred"


def test_two_real_cli_invocations_with_distinct_nonces(tmp_path):
    exe, root, before, after = fixtures(tmp_path)
    runner, calls = runner_factory(before, after)
    result = audit_scene_change(
        studio_executable=exe, baseline_fixture=before,
        candidate_fixture=after, trusted_workspace=root, runner=runner,
        owner_approved=True, streaming_idle=True,
        policy=SceneRegressionPolicy(
            allowed_increases=(("unanchored_collidable", 1),)),
    )
    assert result.status == "ready_for_review"
    assert result.baseline_sha256 != result.candidate_sha256
    assert re.fullmatch("[0-9a-f]{64}", result.baseline_sha256)
    assert len(calls) == 2
    assert calls[0][0][calls[0][0].index("--localPlaceFile") + 1] == str(before)
    assert calls[1][0][calls[1][0].index("--localPlaceFile") + 1] == str(after)
    assert all("--quitAfterExecution" in argv for argv, _ in calls)
    assert all(kwargs["timeout"] == 120 for _, kwargs in calls)


def test_host_mutation_of_fixture_is_detected(tmp_path):
    exe, root, before, after = fixtures(tmp_path)
    runner, _ = runner_factory(before, after, change_during=before)
    result = audit_scene_change(
        studio_executable=exe, baseline_fixture=before,
        candidate_fixture=after, trusted_workspace=root, runner=runner,
        owner_approved=True, streaming_idle=True,
    )
    assert result.status == "invalid"
    assert "fixture_changed_during_audit" in result.concerns


def test_missing_or_forged_second_audit_fails_closed(tmp_path):
    exe, root, before, after = fixtures(tmp_path)
    runner, _ = runner_factory(before, after, bad_second=True)
    result = audit_scene_change(
        studio_executable=exe, baseline_fixture=before,
        candidate_fixture=after, trusted_workspace=root, runner=runner,
        owner_approved=True, streaming_idle=True,
    )
    assert result.status == "invalid"
    assert result.baseline_sha256 is None
    assert not result.verified_playthrough


def test_same_fixture_and_untrusted_path_never_launch(tmp_path):
    exe, root, before, after = fixtures(tmp_path)
    def forbidden(*a, **k):
        raise AssertionError("must not launch")
    kw = dict(studio_executable=exe, baseline_fixture=before,
              trusted_workspace=root, runner=forbidden,
              owner_approved=True, streaming_idle=True)
    assert audit_scene_change(candidate_fixture=before, **kw).status == "invalid"
    outside = tmp_path / "outside.rbxlx"
    outside.write_text("<roblox/>")
    with pytest.raises(ValueError):
        audit_scene_change(candidate_fixture=outside, **kw)


def test_empty_and_oversized_fixture_fail_without_launch(tmp_path):
    exe, root, before, after = fixtures(tmp_path)
    after.write_bytes(b"")
    def forbidden(*a, **k):
        raise AssertionError("must not launch")
    assert audit_scene_change(
        studio_executable=exe, baseline_fixture=before,
        candidate_fixture=after, trusted_workspace=root,
        owner_approved=True, streaming_idle=True, runner=forbidden,
    ).status == "invalid"
