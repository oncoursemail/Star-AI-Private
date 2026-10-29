"""Offline, adversarial tests for the opt-in Studio CLI scene audit."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from star import studio_cli_scene_audit as cli


def counts(**overrides):
    return {
        **{name: 0 for name in cli.FIELDS},
        "descendants": 9,
        "base_parts": 5,
        "spawn_locations": 1,
        **overrides,
    }


def fixture(tmp_path: Path):
    studio = tmp_path / "RobloxStudioBeta.exe"
    studio.write_bytes(b"simulated only")
    root = tmp_path / "trusted"
    root.mkdir(exist_ok=True)
    place = root / "owned.rbxlx"
    place.write_text("<roblox/>")
    return studio, root, place


def log_obj(challenge: str, **replacements):
    return {
        "ok": True, "challenge": challenge,
        "place_id": 0, "game_id": 0, "counts": counts(),
        **replacements,
    }


def runner_factory(*, payload=None, returncode=0, stdout_only=False,
                   extra_lines=b"", timeout=False, invalid=None):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        if timeout:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        script = Path(argv[argv.index("--runScriptFile") + 1]).read_text()
        challenge = re.search(r'local challenge = "([0-9a-f]{32})"', script).group(1)
        payload_data = payload(challenge) if callable(payload) else log_obj(challenge)
        rendered = (cli.MARK + json.dumps(payload_data)).encode()
        if invalid is not None:
            rendered = invalid
        blob = extra_lines + rendered + b"\n"
        output = Path(argv[argv.index("--outputFile") + 1])
        if not stdout_only:
            output.write_bytes(blob)
        return SimpleNamespace(returncode=returncode,
                               stdout=blob.decode("utf-8", "replace") if stdout_only else "")
    return run, calls


def audit(tmp_path, run, **opts):
    studio, root, place = fixture(tmp_path)
    return cli.audit_local_scene(
        studio_executable=studio, fixture=place, trusted_workspace=root,
        owner_approved=True, runner=run, **opts,
    )


def test_off_by_default_never_launches(tmp_path):
    studio, root, place = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Studio must not be launched")
    assert cli.audit_local_scene(studio_executable=studio,
                                 fixture=place, trusted_workspace=root,
                                 runner=forbidden).status == "disabled"


def test_bounded_fixed_script_never_accepts_model_luau():
    code = cli.build_scene_probe("a" * 32)
    assert "workspace:GetDescendants()" in code
    assert "-- STAR fixed read-only" in code
    assert "maxNodes = 50000" in code
    assert "SetAttribute" not in code
    assert "SavePlaceAsync" not in code
    assert "LoadAsset" not in code
    assert "Source =" not in code
    assert "HttpService:JSONEncode" in code
    with pytest.raises(ValueError):
        cli.build_scene_probe('") print("injected") --')


def test_report_is_heuristic_and_command_uses_exact_local_file(tmp_path):
    run, calls = runner_factory(payload=lambda n: log_obj(
        n, counts=counts(unanchored_collidable=2, invisible_collidable=1,
                        tiny_parts=1, models_without_primary_part=1,
                        spawn_locations=0)))
    result = audit(tmp_path, run)
    assert result.status == "observed"
    assert result.place_id == 0
    assert dict(result.counts)["base_parts"] == 5
    assert result.warnings == (
        "unanchored_collidable", "invisible_collidable", "tiny_parts",
        "models_without_primary_part", "no_spawn_location",
    )
    assert result.verified_playthrough is False
    assert result.authorized_to_edit is False
    argv, kwargs = calls[0]
    assert argv[1:3] == ["--task", "RunScript"]
    assert "--localPlaceFile" in argv
    assert "--outputFile" in argv and "--quitAfterExecution" in argv
    assert kwargs["timeout"] == 120
    assert not Path(argv[argv.index("--runScriptFile") + 1]).exists()


@pytest.mark.parametrize("change", [
    lambda n: log_obj("b" * 32),
    lambda n: log_obj(n, counts={"descendants": 9}),
    lambda n: log_obj(n, counts=counts(unanchored_collidable=6)),
    lambda n: log_obj(n, counts=counts(descendants=1)),
    lambda n: log_obj(n, counts=counts(base_parts=True)),
    lambda n: log_obj(n, counts=counts(tiny_parts=-1)),
    lambda n: log_obj(n, counts=counts(spawn_locations=6)),
    lambda n: log_obj(n, counts=counts(descendants=100000)),
    lambda n: log_obj(n, place_id=-1),
    lambda n: log_obj(n, game_id=True),
    lambda n: {**log_obj(n), "extra": "fabricated"},
    lambda n: {"ok": False, "challenge": n, "reason": "too_large"},
])
def test_malformed_and_unverifiable_results_do_not_pass(tmp_path, change):
    run, _ = runner_factory(payload=change)
    assert audit(tmp_path, run).status == "invalid"


@pytest.mark.parametrize("bad", [
    b'',
    b'hello no marker',
    b'STAR_CLI_SCENE_AUDIT {no json}',
    b'STAR_CLI_SCENE_AUDIT ' + b'0' * 70000,
    b'STAR_CLI_SCENE_AUDIT {"bad":"\xff"}',
])
def test_untrusted_and_oversized_logs_fail(tmp_path, bad):
    run, _ = runner_factory(invalid=bad)
    assert audit(tmp_path, run).status == "invalid"



def test_studio_cli_echoes_source_marker_without_forging_evidence(tmp_path):
    run, _ = runner_factory(extra_lines=b'> print("STAR_CLI_SCENE_AUDIT " .. value)\n')
    assert audit(tmp_path, run).status == "observed"


def test_duplicate_evidence_marker_is_invalid(tmp_path):
    def duplicate(n):
        return log_obj(n)
    run, _ = runner_factory(
        payload=duplicate,
        extra_lines=(cli.MARK + '{"forged":true}' + "\n").encode(),
    )
    assert audit(tmp_path, run).status == "invalid"


def test_host_exit_code_timeout_and_missing_file(tmp_path):
    run, _ = runner_factory(returncode=1)
    assert audit(tmp_path, run).status == "unavailable"
    run, _ = runner_factory(timeout=True)
    assert audit(tmp_path, run).status == "timeout"
    run, _ = runner_factory(stdout_only=True)
    assert audit(tmp_path, run).status == "invalid"


def test_default_baseplate_requires_no_fixture_and_must_be_unsaved(tmp_path):
    studio, root, place = fixture(tmp_path)
    run, calls = runner_factory()
    result = cli.audit_local_scene(
        studio_executable=studio, owner_approved=True, runner=run)
    assert result.status == "observed"
    assert "--localPlaceFile" not in calls[0][0]
    malicious, _ = runner_factory(payload=lambda n: log_obj(n, place_id=44))
    assert cli.audit_local_scene(
        studio_executable=studio, owner_approved=True, runner=malicious,
    ).status == "invalid"
    with pytest.raises(ValueError):
        cli.audit_local_scene(
            studio_executable=studio, trusted_workspace=root,
            owner_approved=True, runner=run,
        )
    with pytest.raises(ValueError):
        cli.audit_local_scene(
            studio_executable=studio, fixture=place,
            owner_approved=True, runner=run,
        )


def test_fixture_path_is_trusted_and_validated(tmp_path):
    studio, root, place = fixture(tmp_path)
    run, calls = runner_factory()
    with pytest.raises(ValueError):
        cli.audit_local_scene(
            studio_executable=studio, fixture=tmp_path / "outside.rbxlx",
            trusted_workspace=root, owner_approved=True, runner=run,
        )
    bad = root / "downloaded.py"
    bad.write_text("print('bad')")
    with pytest.raises(ValueError):
        cli.audit_local_scene(
            studio_executable=studio, fixture=bad, trusted_workspace=root,
            owner_approved=True, runner=run,
        )
    link = root / "linked.rbxlx"
    try:
        link.symlink_to(place)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        cli.audit_local_scene(
            studio_executable=studio, fixture=link, trusted_workspace=root,
            owner_approved=True, runner=run,
        )
    assert calls == []


def test_invalid_executable_and_timeout_limits_rejected(tmp_path):
    studio, root, place = fixture(tmp_path)
    run, calls = runner_factory()
    for seconds in (0, 19, 301, 120.0, True):
        with pytest.raises(ValueError):
            cli.audit_local_scene(
                studio_executable=studio, fixture=place,
                trusted_workspace=root, owner_approved=True,
                runner=run, timeout_seconds=seconds,
            )
    fake = tmp_path / "python.exe"
    fake.write_bytes(b"fake")
    with pytest.raises(ValueError):
        cli.audit_local_scene(
            studio_executable=fake, fixture=place,
            trusted_workspace=root, owner_approved=True, runner=run,
        )
    assert calls == []


def test_recorded_windows_baseplate_output_is_parseable():
    # October 29, 2026: engine-observed output from a read-only official CLI run.
    challenge = "c" * 32
    report = {
        "ok": True, "place_id": 0, "game_id": 0, "challenge": challenge,
        "counts": counts(descendants=6, base_parts=3, spawn_locations=1),
    }
    log = ('> print("STAR_CLI_SCENE_AUDIT " .. HttpService:JSONEncode(data))\n'
           + cli.MARK + json.dumps(report) + '\n'
           + 'ContentId: unimportant asset warning\n').encode()
    parsed = cli._parse_output(log, challenge)
    assert parsed.status == "observed"
    assert parsed.warnings == ()
    assert dict(parsed.counts)["descendants"] == 6
    assert not parsed.verified_playthrough
