"""Opt-in, read-only Roblox Studio CLI structural audit.

Uses Roblox Studio's documented --task RunScript command with fixed Luau.
Neither model-provided code nor unattended published-place edits are allowed.
Reports are heuristic observations, NEVER verified gameplay completion.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from typing import Callable

MARK = "STAR_CLI_SCENE_AUDIT "
MAX_OUTPUT_BYTES = 65536
MAX_DESCENDANTS = 50000
FIELDS = ("descendants", "base_parts", "unanchored_collidable",
          "invisible_collidable", "tiny_parts", "spawn_locations",
          "models_without_primary_part")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True)
class CliSceneAudit:
    status: str  # observed | disabled | unavailable | invalid | timeout
    place_id: int | None = None
    game_id: int | None = None
    counts: tuple[tuple[str, int], ...] = ()
    warnings: tuple[str, ...] = ()
    verified_playthrough: bool = False
    authorized_to_edit: bool = False


def build_scene_probe(challenge: str) -> str:
    """Create an immutable bounded read-only Luau probe for the CLI."""
    if type(challenge) is not str or _HEX32.fullmatch(challenge) is None:
        raise ValueError("invalid audit challenge")
    return (
        "-- STAR fixed read-only scene audit. No model code or writes.\n"
        "local HttpService = game:GetService(\"HttpService\")\n"
        f"local challenge = {json.dumps(challenge)}\n"
        f"local maxNodes = {MAX_DESCENDANTS}\n"
        "local function emit(data)\n"
        "  data.challenge = challenge\n"
        f"  print({json.dumps(MARK)} .. HttpService:JSONEncode(data))\n"
        "end\n"
        "local ok, result = pcall(function()\n"
        "  local nodes = workspace:GetDescendants()\n"
        "  if #nodes > maxNodes then return {ok = false, reason = \"too_large\"} end\n"
        "  local c = {descendants = #nodes, base_parts = 0,\n"
        "    unanchored_collidable = 0, invisible_collidable = 0,\n"
        "    tiny_parts = 0, spawn_locations = 0, models_without_primary_part = 0}\n"
        "  for _, instance in ipairs(nodes) do\n"
        "    if instance:IsA(\"BasePart\") then\n"
        "      c.base_parts += 1\n"
        "      if instance.CanCollide and not instance.Anchored then\n"
        "        c.unanchored_collidable += 1\n"
        "      end\n"
        "      if instance.CanCollide and instance.Transparency >= 0.95 then\n"
        "        c.invisible_collidable += 1\n"
        "      end\n"
        "      local size = instance.Size\n"
        "      if size.X < 0.05 or size.Y < 0.05 or size.Z < 0.05 then\n"
        "        c.tiny_parts += 1\n"
        "      end\n"
        "    end\n"
        "    if instance:IsA(\"SpawnLocation\") then c.spawn_locations += 1 end\n"
        "    if instance:IsA(\"Model\") and #instance:GetChildren() > 0\n"
        "      and instance.PrimaryPart == nil then\n"
        "      c.models_without_primary_part += 1\n"
        "    end\n"
        "  end\n"
        "  return {ok = true, place_id = game.PlaceId,\n"
        "    game_id = game.GameId, counts = c}\n"
        "end)\n"
        "if not ok or type(result) ~= \"table\" then\n"
        "  emit({ok = false, reason = \"audit_error\"})\n"
        "else\n"
        "  emit(result)\n"
        "end\n"
    )


def _parse_output(log: bytes, challenge: str) -> CliSceneAudit:
    if type(log) is not bytes or len(log) > MAX_OUTPUT_BYTES:
        return CliSceneAudit("invalid")
    try:
        # Studio outputFile echoes script source prefixed with "> ".
        # Only standalone printed evidence at column zero is acceptable.
        marked = [line[len(MARK):].strip()
                  for line in log.decode("utf-8-sig", "strict").splitlines()
                  if line.startswith(MARK)]
        if len(marked) != 1:
            return CliSceneAudit("invalid")
        obj = json.loads(marked[0])
        if (type(obj) is not dict or set(obj) !=
                {"ok", "challenge", "place_id", "game_id", "counts"}
                or obj["challenge"] != challenge or obj["ok"] is not True):
            return CliSceneAudit("invalid")
        counts = obj["counts"]
        if type(counts) is not dict or set(counts) != set(FIELDS):
            return CliSceneAudit("invalid")
        if any(type(counts[field]) is not int or not 0 <= counts[field] <= MAX_DESCENDANTS
               for field in FIELDS):
            return CliSceneAudit("invalid")
        if any(counts[field] > counts["descendants"] for field in FIELDS[1:]):
            return CliSceneAudit("invalid")
        if any(counts[field] > counts["base_parts"] for field in (
                "unanchored_collidable", "invisible_collidable", "tiny_parts",
                "spawn_locations")):
            return CliSceneAudit("invalid")
        place_id, game_id = obj["place_id"], obj["game_id"]
        if (type(place_id) is not int or not 0 <= place_id < 2**64
                or type(game_id) is not int or not 0 <= game_id < 2**64):
            return CliSceneAudit("invalid")
        warnings = tuple(name for name in FIELDS[2:] if name != "spawn_locations"
                         and counts[name] > 0)
        if counts["spawn_locations"] == 0:
            warnings += ("no_spawn_location",)
        return CliSceneAudit("observed", place_id, game_id,
                             tuple((field, counts[field]) for field in FIELDS),
                             warnings)
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        return CliSceneAudit("invalid")


def _local_fixture(path: Path, workspace: Path) -> Path:
    if not isinstance(path, Path) or not isinstance(workspace, Path):
        raise TypeError("expected Path for fixture and workspace")
    if not path.is_absolute() or not workspace.is_absolute():
        raise ValueError("fixture and workspace must be absolute")
    if str(path).startswith("\\\\") or str(workspace).startswith("\\\\"):
        raise ValueError("network shares are not local fixtures")
    if path.suffix.lower() not in (".rbxl", ".rbxlx"):
        raise ValueError("only Roblox place files are supported")
    try:
        root = workspace.resolve(strict=True)
        selected = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("trusted fixture or workspace does not exist") from exc
    if not root.is_dir() or not selected.is_file() or not selected.is_relative_to(root):
        raise ValueError("fixture must be an existing file inside trusted workspace")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("fixture symlinks are not trusted")
    return selected


def audit_local_scene(*, studio_executable: Path, fixture: Path | None = None,
                      trusted_workspace: Path | None = None, owner_approved: bool = False,
                      timeout_seconds: int = 120,
                      runner: Callable[..., object] | None = None) -> CliSceneAudit:
    """Call fixed Studio CLI probe; caller owns/trusts fixture and budgets.

    The testing-only runner injection MUST be omitted in production. Loading
    even a read-only place may execute its authored scripts; never run
    untrusted downloaded places. No Studio source, secrets, or logs returned.
    """
    if owner_approved is not True:
        return CliSceneAudit("disabled")
    if type(timeout_seconds) is not int or not 20 <= timeout_seconds <= 300:
        raise ValueError("timeout must be 20..300 seconds")
    if not isinstance(studio_executable, Path):
        raise TypeError("studio_executable must be a Path")
    if (not studio_executable.is_absolute()
            or studio_executable.name.lower() not in ("robloxstudiobeta.exe", "robloxstudio.exe")):
        raise ValueError("only an absolute Roblox Studio executable is supported")
    try:
        exe = studio_executable.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Studio executable does not exist") from exc
    if not exe.is_file() or studio_executable.is_symlink():
        raise ValueError("not an executable Studio file")
    if fixture is None:
        if trusted_workspace is not None:
            raise ValueError("workspace without explicit fixture is not allowed")
        selected = None  # Studio CLI creates its own fresh empty Baseplate.
    else:
        if trusted_workspace is None:
            raise ValueError("explicit fixture requires a trusted workspace")
        selected = _local_fixture(fixture, trusted_workspace)
    if runner is None:
        if os.name != "nt":
            return CliSceneAudit("unavailable")
        runner = subprocess.run
    challenge = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="star-scene-audit-") as temp:
        script, output = Path(temp, "probe.luau"), Path(temp, "output.log")
        script.write_text(build_scene_probe(challenge), encoding="utf-8")
        argv = [str(exe), "--task", "RunScript"]
        if selected is not None:
            argv += ["--localPlaceFile", str(selected)]
        argv += ["--runScriptFile", str(script),
                 "--outputFile", str(output), "--quitAfterExecution"]
        try:
            done = runner(argv, timeout=timeout_seconds, check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if getattr(done, "returncode", None) != 0:
                return CliSceneAudit("unavailable")
            if not output.exists() or not output.is_file():
                return CliSceneAudit("invalid")
            if output.stat().st_size > MAX_OUTPUT_BYTES:
                return CliSceneAudit("invalid")
            report = _parse_output(output.read_bytes(), challenge)
            # Without --localPlaceFile Studio must have opened an empty baseplate.
            if selected is None and report.status == "observed" and (
                report.place_id != 0 or report.game_id != 0
            ):
                return CliSceneAudit("invalid")
            return report
        except subprocess.TimeoutExpired:
            return CliSceneAudit("timeout")
        except (OSError, UnicodeError, ValueError):
            return CliSceneAudit("unavailable")


__all__ = ["CliSceneAudit", "audit_local_scene", "build_scene_probe"]
