"""Offline adversarial checks for the scratch-only real-engine canary."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from star import studio_cli_scene_audit as audit
from star import studio_cli_engine_canary as canary


def studio(tmp_path: Path) -> Path:
    exe = tmp_path / "RobloxStudioBeta.exe"
    exe.write_bytes(b"test stub: never executed")
    return exe


def counts(canary_part: bool) -> dict[str, int]:
    start = {
        "descendants": 6, "base_parts": 3, "spawn_locations": 1,
        "unanchored_collidable": 0, "invisible_collidable": 0,
        "tiny_parts": 0, "models_without_primary_part": 0,
    }
    if canary_part:
        for name in ("descendants", "base_parts", "unanchored_collidable",
                     "invisible_collidable", "tiny_parts"):
            start[name] += 1
    return start


class FakeStudio:
    def __init__(self, *, baseline_bad=False, candidate_bad=False,
                 baseline_timeout=False, candidate_timeout=False,
                 wrong_candidate=False, unexpected_place=False,
                 forged=False, baseline_failure=False, candidate_failure=False):
        self.calls = []
        self.baseline_bad, self.candidate_bad = baseline_bad, candidate_bad
        self.baseline_timeout, self.candidate_timeout = baseline_timeout, candidate_timeout
        self.wrong_candidate = wrong_candidate
        self.unexpected_place = unexpected_place
        self.forged = forged
        self.baseline_failure, self.candidate_failure = baseline_failure, candidate_failure

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        # Crucial: no saved file, published place ID, universe ID or editing task.
        assert argv[1:3] == ["--task", "RunScript"]
        assert "--localPlaceFile" not in argv
        assert "--placeId" not in argv and "--universeId" not in argv
        assert "--quitAfterExecution" in argv
        source = Path(argv[argv.index("--runScriptFile") + 1]).read_text()
        match = re.search(r'local challenge = "([0-9a-f]{32})"', source)
        assert match, "all probes must carry a bounded unpredictable challenge"
        challenge = match.group(1)
        modified = '_STAR_ENGINE_CANARY_TEMP' in source
        if (not modified and self.baseline_timeout) or (modified and self.candidate_timeout):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if (not modified and self.baseline_failure) or (modified and self.candidate_failure):
            return SimpleNamespace(returncode=3)
        marker = {
            "ok": True, "challenge": challenge,
            "place_id": 55 if modified and self.unexpected_place else 0,
            "game_id": 0,
            "counts": counts(modified and not self.wrong_candidate),
        }
        data = (audit.MARK + json.dumps(marker) + "\n").encode()
        if (modified and self.candidate_bad) or (not modified and self.baseline_bad):
            data = b"no admissible evidence\n"
        if modified and self.forged:
            data += audit.MARK.encode() + json.dumps(marker).encode() + b"\n"
        Path(argv[argv.index("--outputFile") + 1]).write_bytes(data)
        return SimpleNamespace(returncode=0)


def test_default_disabled_never_uses_studio(tmp_path):
    fake = FakeStudio()
    result = canary.run_engine_regression_canary(
        studio_executable=studio(tmp_path), runner=fake)
    assert result.status == "disabled" and not fake.calls
    assert not result.verified_gameplay and not result.authorized_to_publish


def test_must_be_idle_before_running(tmp_path):
    fake = FakeStudio()
    result = canary.run_engine_regression_canary(
        studio_executable=studio(tmp_path), owner_approved=True, runner=fake)
    assert result.status == "deferred" and not fake.calls


def test_detects_known_engine_regression_from_two_runs(tmp_path):
    fake = FakeStudio()
    result = canary.run_engine_regression_canary(
        studio_executable=studio(tmp_path), owner_approved=True,
        streaming_idle=True, runner=fake)
    assert result.status == "passed"
    assert result.reason == "known_engine_defect_detected"
    assert len(fake.calls) == 2
    assert dict(result.observed_delta)["base_parts"] == 1
    assert dict(result.observed_delta)["unanchored_collidable"] == 1
    assert result.verified_real_game is False
    assert result.verified_gameplay is False
    assert result.authorized_to_edit is False
    assert result.authorized_to_publish is False


def test_canary_script_changes_only_unsaved_local_scene():
    code = canary.build_canary_probe("a" * 32)
    assert code.startswith("-- STAR scratch-only regression canary")
    assert 'assert(game.PlaceId == 0 and game.GameId == 0' in code
    assert 'Instance.new("Part")' in code
    assert 'starCanary.Parent = workspace' in code
    assert 'workspace:GetDescendants()' in code
    assert "SaveToFile" not in code and "SavePlace" not in code
    assert "InsertService" not in code and "HttpGet" not in code
    with pytest.raises(ValueError):
        canary.build_canary_probe('bad" --\nprint(1)')


@pytest.mark.parametrize(("opts", "expected"), [
    ({"baseline_bad": True}, "invalid"),
    ({"candidate_bad": True}, "invalid"),
    ({"baseline_timeout": True}, "unavailable"),
    ({"candidate_timeout": True}, "unavailable"),
    ({"baseline_failure": True}, "unavailable"),
    ({"candidate_failure": True}, "unavailable"),
    ({"wrong_candidate": True}, "failed"),
    ({"unexpected_place": True}, "invalid"),
    ({"forged": True}, "invalid"),
])
def test_failure_and_forgery_are_not_reported_as_success(tmp_path, opts, expected):
    fake = FakeStudio(**opts)
    result = canary.run_engine_regression_canary(
        studio_executable=studio(tmp_path), owner_approved=True,
        streaming_idle=True, runner=fake)
    assert result.status == expected


def test_reject_invalid_options_before_spawning(tmp_path):
    exe = studio(tmp_path)
    fake = FakeStudio()
    for timeout in [1, 301, 50.5, True]:
        with pytest.raises(ValueError):
            canary.run_engine_regression_canary(
                studio_executable=exe, owner_approved=True,
                streaming_idle=True, timeout_seconds=timeout, runner=fake)
    assert not fake.calls
    invalid = tmp_path / "RobloxGame.exe"
    invalid.write_bytes(b"test")
    with pytest.raises(ValueError):
        canary.run_engine_regression_canary(
            studio_executable=invalid, owner_approved=True,
            streaming_idle=True, runner=fake)
    with pytest.raises(ValueError):
        canary.run_engine_regression_canary(
            studio_executable=Path("relative/RobloxStudioBeta.exe"),
            owner_approved=True, streaming_idle=True, runner=fake)
    assert not fake.calls
