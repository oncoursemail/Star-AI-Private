"""Generate bounded, read-only Roblox Studio scene-integrity smoke tests.

A trusted operator copies the generated *server Script* into ServerScriptService
and executes the generated *plugin* code in an authorized private Studio place.
This module never opens Studio, writes to a place, injects input, accesses
network services, claims to authenticate the Studio runtime or executes code.

StudioTestService is plugin-security for launching tests; EndTest runs on the
test server. The result is a smoke-test signal, not independent game mastery,
visual polish or evidence of a production-ready experience.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,47}\Z")
_SEGMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_ .-]{0,47}\Z")
_ROOTS = frozenset({"Workspace", "ReplicatedStorage", "ServerStorage", "StarterGui"})
_CLASSES = frozenset({
    "Part", "MeshPart", "UnionOperation", "SpawnLocation", "TrussPart",
    "Model", "Folder", "Attachment", "Sound", "ParticleEmitter", "Beam",
    "ScreenGui", "Frame", "ImageLabel", "ImageButton", "TextLabel",
    "TextButton", "UIListLayout", "UICorner", "Humanoid", "Tool",
})
_BASEPARTS = frozenset({"Part", "MeshPart", "UnionOperation", "SpawnLocation", "TrussPart"})


def _vec3(value: object, *, positive: bool = False) -> tuple[float, float, float]:
    if (type(value) is not tuple or len(value) != 3
            or any(type(v) not in (int, float) for v in value)):
        raise ValueError("expected a 3-vector tuple of finite numbers")
    vals = tuple(float(v) for v in value)
    if any(not math.isfinite(v) or abs(v) > 100_000
           or (positive and not 0 < v <= 100_000) for v in vals):
        raise ValueError("3-vector outside bounded scene limits")
    return vals  # type: ignore[return-value]


@dataclass(frozen=True)
class SceneCheck:
    """An owner-curated read-only presence, property and spatial check."""

    path: tuple[str, ...]  # Root service then 1..7 direct descendant names
    class_name: str
    anchored: bool | None = None
    can_collide: bool | None = None
    max_transparency: float | None = None
    expected_position: tuple[float, float, float] | None = None
    position_tolerance_studs: float = 0.5
    minimum_size: tuple[float, float, float] | None = None
    min_descendants: int | None = None

    def __post_init__(self) -> None:
        if (type(self.path) is not tuple or not 2 <= len(self.path) <= 8
                or type(self.path[0]) is not str or self.path[0] not in _ROOTS
                or any(type(s) is not str or not _SEGMENT.fullmatch(s)
                       for s in self.path[1:])):
            raise ValueError("path must name a root service and 1..7 safe descendants")
        if type(self.class_name) is not str or self.class_name not in _CLASSES:
            raise ValueError("unsupported Roblox class")
        if any(x is not None and type(x) is not bool
               for x in (self.anchored, self.can_collide)):
            raise ValueError("part flags must be bool or None")
        needs_part = any(x is not None for x in (
            self.anchored, self.can_collide, self.max_transparency,
            self.expected_position, self.minimum_size,
        ))
        if needs_part and self.class_name not in _BASEPARTS:
            raise ValueError("part properties require an explicit BasePart subclass")
        if self.max_transparency is not None:
            x = self.max_transparency
            if type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1:
                raise ValueError("max_transparency must be 0..1")
        if self.expected_position is not None:
            _vec3(self.expected_position)
        if self.minimum_size is not None:
            _vec3(self.minimum_size, positive=True)
        if (type(self.position_tolerance_studs) not in (int, float)
                or not math.isfinite(self.position_tolerance_studs)
                or not 0 <= self.position_tolerance_studs <= 32):
            raise ValueError("invalid positional tolerance")
        if self.min_descendants is not None:
            if (self.class_name not in {"Model", "Folder"}
                    or type(self.min_descendants) is not int
                    or not 1 <= self.min_descendants <= 256):
                raise ValueError("min_descendants needs a Model/Folder and 1..256")


@dataclass(frozen=True)
class StudioSceneTest:
    suite_id: str
    checks: tuple[SceneCheck, ...]
    simulated_clients: int = 1

    def __post_init__(self) -> None:
        if type(self.suite_id) is not str or not _ID.fullmatch(self.suite_id):
            raise ValueError("suite_id must be a bounded symbolic name")
        if (type(self.checks) is not tuple or not 1 <= len(self.checks) <= 64
                or any(type(c) is not SceneCheck for c in self.checks)
                or len(set(c.path for c in self.checks)) != len(self.checks)):
            raise ValueError("provide 1..64 unique, curated scene checks")
        if type(self.simulated_clients) is not int or not 1 <= self.simulated_clients <= 8:
            raise ValueError("Studio supports only 1..8 simulated clients")


@dataclass(frozen=True)
class StudioSceneBundle:
    """Static text only. No execution, device controls or Studio permissions."""

    spec_sha256: str
    server_script: str
    plugin_script: str
    verified_in_studio: bool = False


def _lua_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=True)


def _lua_vector(values: tuple[float, float, float]) -> str:
    return "Vector3.new(" + ", ".join(repr(float(x)) for x in values) + ")"


def compile_scene_integrity(test: StudioSceneTest) -> StudioSceneBundle:
    """Create fixed, non-interpolated Luau verification logic.

    The compiled server code never modifies the game world. The plugin script
    starts only a manually authorized Studio test. An echoed hash is an
    integrity marker for this test specification, NOT a signed receipt.
    """
    if not isinstance(test, StudioSceneTest):
        raise TypeError("expected a validated StudioSceneTest")

    canonical = {
        "suite": test.suite_id, "clients": test.simulated_clients,
        "checks": [{
            "path": c.path, "class": c.class_name,
            "anchored": c.anchored, "can_collide": c.can_collide,
            "max_transparency": c.max_transparency,
            "position": c.expected_position, "tolerance": c.position_tolerance_studs,
            "minimum_size": c.minimum_size, "min_descendants": c.min_descendants,
        } for c in test.checks],
    }
    fingerprint = sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("ascii")).hexdigest()
    token = test.suite_id + ":" + fingerprint[:20]
    lines = [
        "-- STAR read-only scene verifier: put in ServerScriptService in a PRIVATE test place.",
        "-- This checks object properties; it cannot certify visuals, playability or gameplay.",
        'if not game:GetService("RunService"):IsStudio() then return end',
        'local sts = game:GetService("StudioTestService")',
        f"if sts:GetTestArgs() ~= {_lua_string(token)} then return end",
        "local function verify()",
        f"    if sts:GetTestArgs() ~= {_lua_string(token)} then return false, 'wrong_suite' end",
    ]
    for idx, c in enumerate(test.checks, start=1):
        lines += [
            f"    -- Check {idx}; no arbitrary Luau from the model is interpolated.",
            f"    local object{idx} = game:GetService({_lua_string(c.path[0])})",
        ]
        for segment in c.path[1:]:
            lines += [f"    object{idx} = object{idx} and object{idx}:FindFirstChild({_lua_string(segment)})"]
        lines += [
            f"    if not object{idx} then return false, 'missing_{idx}' end",
            f"    if object{idx}.ClassName ~= {_lua_string(c.class_name)} "
            f"then return false, 'wrong_class_{idx}' end",
        ]
        if c.anchored is not None:
            want = "true" if c.anchored else "false"
            lines += [f"    if object{idx}.Anchored ~= {want} then return false, 'anchored_{idx}' end"]
        if c.can_collide is not None:
            want = "true" if c.can_collide else "false"
            lines += [f"    if object{idx}.CanCollide ~= {want} then return false, 'collision_{idx}' end"]
        if c.max_transparency is not None:
            lines += [
                f"    if object{idx}.Transparency > {float(c.max_transparency)!r} "
                f"then return false, 'transparent_{idx}' end",
            ]
        if c.expected_position is not None:
            lines += [
                f"    if (object{idx}.Position - {_lua_vector(c.expected_position)}).Magnitude "
                f"> {float(c.position_tolerance_studs)!r} "
                f"then return false, 'position_{idx}' end",
            ]
        if c.minimum_size is not None:
            lines += [
                f"    local size{idx} = object{idx}.Size",
                f"    if size{idx}.X < {float(c.minimum_size[0])!r} "
                f"or size{idx}.Y < {float(c.minimum_size[1])!r} "
                f"or size{idx}.Z < {float(c.minimum_size[2])!r} "
                f"then return false, 'size_{idx}' end",
            ]
        if c.min_descendants is not None:
            lines += [
                f"    if #object{idx}:GetDescendants() < {c.min_descendants} "
                f"then return false, 'incomplete_{idx}' end",
            ]
    lines += [
        "    return true, 'ok'",
        "end",
        "local worked, passed, detail = pcall(verify)",
        "if not worked then",
        "    sts:EndTest('FAIL:verifier_error')",
        "elseif not passed then",
        "    sts:EndTest('FAIL:' .. detail)",
        "else",
        f"    sts:EndTest({_lua_string('PASS:' + token)})",
        "end",
        "",
    ]
    plugin = "\n".join([
        "-- Run ONLY from a trusted Studio plugin after verifying place identity and approval.",
        "-- Install the matching verifier Script in ServerScriptService first.",
        'local sts = game:GetService("StudioTestService")',
        f"local result = sts:ExecuteMultiplayerTestAsync({test.simulated_clients}, "
        f"{_lua_string(token)})",
        f"if result ~= {_lua_string('PASS:' + token)} then",
        "    error('STAR Studio scene smoke test failed or did not finish: ' .. tostring(result))",
        "end",
        "print('STAR Studio scene smoke test passed (not a gameplay/visual certificate)')",
        "",
    ])
    return StudioSceneBundle(
        spec_sha256=fingerprint,
        server_script="\n".join(lines),
        plugin_script=plugin,
    )


__all__ = ["SceneCheck", "StudioSceneTest", "StudioSceneBundle", "compile_scene_integrity"]