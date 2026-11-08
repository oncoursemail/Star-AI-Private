"""Real-engine self-test for Star's Roblox Studio regression detector.

Runs two independent *unsaved default Baseplate* Studio CLI sessions. The
second deliberately adds a tiny, invisible, collidable, unanchored Part in
memory before performing the existing fixed audit. Both sessions quit without
saving. It proves the detector sees a controlled regression in a real Studio
DataModel; it does NOT test a user's game, certify model intelligence or
authorize game edits. No user-authored place file is ever opened.

Strictly opt-in and idle-only. The injected runner exists for offline tests,
not as an LLM-accessible extension point.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from typing import Callable

from .studio_cli_scene_audit import (
    CliSceneAudit, FIELDS, MAX_OUTPUT_BYTES, _parse_output,
    audit_local_scene, build_scene_probe,
)
from .studio_cli_scene_regression import compare_scene_audits


@dataclass(frozen=True)
class EngineCanaryResult:
    status: str  # disabled | deferred | unavailable | invalid | passed | failed
    reason: str
    observed_delta: tuple[tuple[str, int], ...] = ()
    verified_real_game: bool = False
    verified_gameplay: bool = False
    authorized_to_edit: bool = False
    authorized_to_publish: bool = False


# Keep this constant; never accept arbitrary Luau, paths, or model-produced
# text in a canary. This is a scratch-only change in an unsaved Baseplate.
_CANARY_PREFIX = """-- STAR scratch-only regression canary: no place is loaded or saved.
assert(game.PlaceId == 0 and game.GameId == 0, "not an unsaved Baseplate")
local starCanary = Instance.new("Part")
starCanary.Name = "_STAR_ENGINE_CANARY_TEMP"
starCanary.Anchored = false
starCanary.CanCollide = true
starCanary.Transparency = 1
starCanary.Size = Vector3.new(0.01, 0.01, 0.01)
starCanary.CFrame = CFrame.new(0, 200, 0)
starCanary.Parent = workspace
"""


def build_canary_probe(challenge: str) -> str:
    """Safe fixed Luau: the existing validator handles the audit receipt."""
    return _CANARY_PREFIX + build_scene_probe(challenge)


def _candidate_audit(
    executable: Path,
    *,
    timeout_seconds: int,
    runner: Callable[..., object] | None,
) -> CliSceneAudit:
    if runner is None:
        if os.name != "nt":
            return CliSceneAudit("unavailable")
        runner = subprocess.run
    challenge = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="star-engine-canary-") as temp:
        script, output = Path(temp, "canary.luau"), Path(temp, "output.log")
        script.write_text(build_canary_probe(challenge), encoding="utf-8")
        argv = [
            str(executable), "--task", "RunScript",
            "--runScriptFile", str(script),
            "--outputFile", str(output), "--quitAfterExecution",
        ]
        try:
            done = runner(
                argv, timeout=timeout_seconds, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if getattr(done, "returncode", None) != 0:
                return CliSceneAudit("unavailable")
            if not output.is_file() or output.stat().st_size > MAX_OUTPUT_BYTES:
                return CliSceneAudit("invalid")
            result = _parse_output(output.read_bytes(), challenge)
            # This canary MUST NOT load a game, local saved place, or remote ID.
            if result.status == "observed" and (
                result.place_id != 0 or result.game_id != 0
            ):
                return CliSceneAudit("invalid")
            return result
        except subprocess.TimeoutExpired:
            return CliSceneAudit("timeout")
        except (OSError, UnicodeError, ValueError):
            return CliSceneAudit("unavailable")


def run_engine_regression_canary(
    *, studio_executable: Path, owner_approved: bool = False,
    streaming_idle: bool = False, timeout_seconds: int = 120,
    runner: Callable[..., object] | None = None,
) -> EngineCanaryResult:
    """Exercise the *actual detector* with a known scratch-only defect.

    A trusted owner-controlled host must confirm streaming is idle; do not
    infer this from viewer chat or from a model. No paths to game files,
    workspace roots or published IDs are accepted by this API. Both processes
    use official --task RunScript on Studio's fresh default Baseplate.
    """
    if owner_approved is not True:
        return EngineCanaryResult("disabled", "owner_opt_in_missing")
    if streaming_idle is not True:
        return EngineCanaryResult("deferred", "streaming_not_confirmed_idle")
    if type(timeout_seconds) is not int or not 20 <= timeout_seconds <= 300:
        raise ValueError("timeout must be 20..300 seconds")
    if not isinstance(studio_executable, Path):
        raise TypeError("studio_executable must be a Path")
    if (not studio_executable.is_absolute()
            or studio_executable.name.lower() not in (
                "robloxstudiobeta.exe", "robloxstudio.exe"
            ) or studio_executable.is_symlink()):
        raise ValueError("expected a local, absolute Studio executable")
    try:
        executable = studio_executable.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Studio executable does not exist") from exc
    if not executable.is_file():
        raise ValueError("Studio executable is not a file")

    before = audit_local_scene(
        studio_executable=executable,
        owner_approved=True, timeout_seconds=timeout_seconds, runner=runner,
    )
    if before.status != "observed":
        return EngineCanaryResult(
            "unavailable" if before.status in {"timeout", "unavailable"} else "invalid",
            f"baseline_{before.status}",
        )
    after = _candidate_audit(
        executable, timeout_seconds=timeout_seconds, runner=runner,
    )
    if after.status != "observed":
        return EngineCanaryResult(
            "unavailable" if after.status in {"timeout", "unavailable"} else "invalid",
            f"candidate_{after.status}",
        )
    if (before.place_id != 0 or before.game_id != 0
            or after.place_id != 0 or after.game_id != 0):
        return EngineCanaryResult("invalid", "not_unsaved_baseplate")

    diff = compare_scene_audits(before, after)
    if diff.status == "invalid":
        return EngineCanaryResult("invalid", "comparison_invalid")
    delta = dict(diff.deltas)
    expected = {
        "descendants": 1,
        "base_parts": 1,
        "unanchored_collidable": 1,
        "invisible_collidable": 1,
        "tiny_parts": 1,
        "spawn_locations": 0,
        "models_without_primary_part": 0,
    }
    if (set(delta) != set(FIELDS) or delta != expected
            or diff.status != "regression"
            or set(diff.concerns) != {
                "increase:unanchored_collidable",
                "increase:invisible_collidable",
                "increase:tiny_parts",
            }):
        return EngineCanaryResult(
            "failed", "expected_regression_not_observed", diff.deltas,
        )
    return EngineCanaryResult(
        "passed", "known_engine_defect_detected", diff.deltas,
    )


__all__ = [
    "EngineCanaryResult", "build_canary_probe", "run_engine_regression_canary",
]
