"""STAR Studio Development Lab: build, playtest and look at Roblox work in a real Studio, then fix and repeat.

    plan --dry run--> apply (one undo step, under Workspace/MapDrafts) --> read back + compare
         --> playtest (a server-side probe drives the character along the route) --> fixed-camera screenshots
         (+ optional vision critique by the brain) --> diagnose --> fix the PLAN --> repeat (capped)

Everything that touches Studio goes through STAR's existing guarded path: star/studio_remote.py pins the session to
STAR Test Place (or a blank place) and star/studio_loop.py's GuardedStudio applies the sandbox rule, records each
Luau edit as one Studio undo step and keeps the change journal. This module adds no new way into Studio: it only
writes Luau that builds inside the managed root, reads with read tools, and starts/stops play.

Why a probe script instead of the connector's input tools: GuardedStudio refuses `character_navigation` and
`user_*_input` on purpose (the connector cannot bind input to STAR's own play request). The probe is a Script inside
the map folder; it runs only while the game runs, takes network ownership of the test character on the server,
walks and jumps it along the plan's route with Humanoid:MoveTo / Humanoid.Jump, and prints one marked JSON line per
leg. That is real engine physics (gravity, collisions, jump height), not a geometric estimate.

Pure parts (spec check, Luau generation, read-back comparison, probe parsing, cameras, diagnosis, plan fixes,
lesson records) have no Studio dependency and are unit-tested. The live parts need a connector session.

Built-in Studio MCP is enough for this loop (screen_capture takes a camera position and a look-at point, start_stop_play,
get_console_output, execute_luau, search_game_tree); ShiroKSH is not used. The plan format is star/map_plan.py
(SceneSpec-style, credit there).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from typing import Any

from . import map_plan

LAB_VERSION = 1
PROBE_MARK = "STAR_LAB_PROBE "
READ_MARK = "STAR_LAB_READ "
APPLY_MARK = "STAR_LAB_APPLY "
PROBE_NAME = "StarLabProbe"
DEFAULT_ITERATIONS, MAX_ITERATIONS = 3, 5
UI_ITERATIONS = 2
DEFAULT_PLAY_SECONDS, MAX_PLAY_SECONDS = 90.0, 240.0
LEG_SECONDS = 8.0
# Real physics (Studio Lab v2/v3 playtests on brain 2, default R15 character, WalkSpeed 16, JumpHeight 7.2): a 7.8-stud
# gap with a 2-stud rise and rises of 6.3 and 7.6 studs were jumped every time; a 9.5-stud flat gap failed in one run
# and was jumped in two others (the edge). The map-plan dry run keeps its player-facing limits (8 gap / 6.5 rise: a
# person does not run the perfect line the probe runs). A FIX aims comfortably inside what was always jumped:
REAL_JUMPED_GAP = 7.8    # studs, always jumped in real playtests
REAL_JUMPED_RISE = 7.6
SAFE_GAP = 7.0           # studs a fix aims for when a jump failed in the playtest (was 6.0 before the measurements)
SAFE_RISE = 6.0          # (was 4.5)
# Free height above the take-off/landing surfaces a running jump needs: the feet rise JumpHeight (7.2) and the
# head is about 5.2 above the feet (R15), plus a margin. Measured in the lab's first Studio runs: a beam 3 studs
# above the surface is jumped over, one 5.8 above is hit by the head.
JUMP_CLEARANCE = 13.5
MAX_PARTS = 600
TEST_PLACE = (10770312935, 128074805767678)

_TOKEN = re.compile(r"^[0-9a-f]{8,32}$")


# --------------------------------------------------------------------------- small helpers

def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    data = value if isinstance(value, bytes) else canonical(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _lua_string(text: str) -> str:
    return json.dumps(text, ensure_ascii=True)   # a JSON string literal is a valid Luau string literal


def _num(value: float) -> str:
    return repr(float(value))


def root_segments(plan: dict) -> list[str]:
    """['MapDrafts', ..., mapName] under workspace. Names are validated by the map plan schema."""
    root = plan.get("rootPath", map_plan.MANAGED_ROOT).rstrip("/")
    return root.split("/")[1:] + [plan["mapName"]]


# --------------------------------------------------------------------------- spec

def check_spec(spec) -> tuple[dict | None, list[str]]:
    """A lab spec: {"name", "kind": "map", "plan": {...map plan...}, "maxIterations"?, "playSeconds"?,
    "lesson"?: {"topic"}}. Returns (normalised spec, problems). The plan must pass the dry run."""
    problems: list[str] = []
    if not isinstance(spec, dict):
        return None, ["A lab spec must be a JSON object"]
    if spec.get("kind") == "ui":
        return check_ui_spec(spec)
    unknown = sorted(set(spec) - {"name", "kind", "plan", "maxIterations", "playSeconds", "description", "lesson",
                                  "defect", "expect"})
    if unknown:
        problems.append("unknown keys: " + ", ".join(unknown))
    if spec.get("kind", "map") != "map":
        problems.append("kind must be 'map' or 'ui'")
    name = spec.get("name") or (spec.get("plan") or {}).get("mapName")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}", name):
        problems.append("name must be 1-64 letters, digits, spaces, _ or -")
    iterations = spec.get("maxIterations", DEFAULT_ITERATIONS)
    if type(iterations) is not int or not 1 <= iterations <= MAX_ITERATIONS:
        problems.append(f"maxIterations must be 1..{MAX_ITERATIONS}")
    seconds = spec.get("playSeconds", DEFAULT_PLAY_SECONDS)
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 10 <= seconds <= MAX_PLAY_SECONDS:
        problems.append(f"playSeconds must be 10..{MAX_PLAY_SECONDS:g}")
    plan = spec.get("plan")
    report = map_plan.dry_run(plan, include_operations=False)
    route_plan = plan if isinstance(plan, dict) else {}   # a non-dict plan already fails the dry run above
    if not report["ok"]:
        problems.append("plan blockers: " + ", ".join(item["code"] for item in report["blockers"]))
    elif report["counts"]["parts"] + report["counts"]["spawns"] > MAX_PARTS:
        problems.append(f"the lab builds at most {MAX_PARTS} parts per run")
    elif report["counts"]["assets"]:
        problems.append("the lab does not insert assets (insert_asset is a blocked tool); remove 'assets'")
    elif not (route_plan.get("route") or {}).get("waypoints"):
        problems.append("the lab needs plan.route.waypoints to playtest (names of the surfaces in order)")
    elif any(not isinstance(w, str) for w in route_plan["route"]["waypoints"]):
        problems.append("the lab route must name objects (coordinates are not playtested)")
    expect, issue = check_expect(spec.get("expect"))
    if issue:
        problems.append(issue)
    if problems:
        return None, problems
    return {"name": name, "kind": "map", "plan": copy.deepcopy(plan), "maxIterations": iterations,
            "playSeconds": float(seconds), "description": str(spec.get("description", ""))[:600],
            "lesson": spec.get("lesson") if isinstance(spec.get("lesson"), dict) else {},
            "defect": str(spec.get("defect", ""))[:80], "expect": expect}, []


def check_expect(raw) -> tuple[dict, str]:
    """The spec's expected outcome: {"first_pass": true|false|null, "defects": [codes, any one], "fixes": [fixes,
    any one]}. ({} , "") when absent; (normalised, "") or ({}, problem)."""
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict) or set(raw) - {"first_pass", "defects", "fixes"}:
        return {}, "expect must be an object with first_pass, defects, fixes"
    first = raw.get("first_pass")
    if first is not None and not isinstance(first, bool):
        return {}, "expect.first_pass must be true, false or null"
    out: dict[str, Any] = {"first_pass": first}
    for key in ("defects", "fixes"):
        value = raw.get(key, [])
        if not isinstance(value, list) or len(value) > 8 or any(not isinstance(v, str) or not 0 < len(v) <= 40
                                                                  for v in value):
            return {}, f"expect.{key} must be a list of short codes"
        out[key] = list(value)
    return out, ""


def expectation(spec: dict, report: dict) -> dict:
    """Did the run do what the spec's author expected? The deliberate defect must REPRODUCE in real Studio (first
    iteration not passed, one of the expected defect codes found), the expected fix must be the one applied, and the
    run must end passed. A control spec (first_pass true) must pass the first time. Pure."""
    expect = spec.get("expect") or {}
    if not expect:
        return {"declared": False}
    iterations = report.get("iterations", [])
    first = iterations[0] if iterations else {}
    found = [d.get("code") for d in first.get("defects", [])] + [p.get("code") for p in first.get("problems", [])]
    fixes = [c.get("fix") for it in iterations for c in it.get("fixes", [])]
    first_pass = bool(first.get("passed"))
    checks = {"passed": bool(report.get("passed"))}
    if expect.get("first_pass") is not None:
        checks["first_pass"] = first_pass == expect["first_pass"]
    if expect.get("defects") and not first_pass:
        checks["defect"] = any(code in expect["defects"] for code in found)
    if expect.get("fixes") and not first_pass:
        checks["fix"] = any(fix in expect["fixes"] for fix in fixes)
    reproduced = None if expect.get("first_pass") is not False else not first_pass
    return {"declared": True, "met": all(checks.values()), "checks": checks, "reproduced": reproduced,
            "found": [c for c in found if c][:6], "fixes": [f for f in fixes if f][:6]}


DEVICES = {
    # id: (what the device simulator is asked for, the size used when no preset matches). "desktop" = no simulation.
    "phone": {"label": "phone (landscape)", "match": ["iPhone", "Phone", "Galaxy", "Pixel"], "fallback": [844, 390]},
    "tablet": {"label": "tablet (landscape)", "match": ["iPad", "Tablet", "Tab "], "fallback": [1180, 820]},
    "desktop": {"label": "desktop (Studio viewport, no simulation)", "match": [], "fallback": None},
}


def check_ui_spec(spec: dict) -> tuple[dict | None, list[str]]:
    """{"name", "kind": "ui", "ui": {...star/roblox_ui_compiler spec...}, "devices": ["phone", "tablet", "desktop"]}."""
    from . import roblox_ui_compiler
    problems = []
    unknown = sorted(set(spec) - {"name", "kind", "ui", "devices", "description", "defect", "expect",
                                  "maxIterations"})
    if unknown:
        problems.append("unknown keys: " + ", ".join(unknown))
    name = spec.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        problems.append("name must be 1-64 letters, digits, _ or -")
    devices = spec.get("devices", ["phone", "tablet", "desktop"])
    if (not isinstance(devices, list) or not 1 <= len(devices) <= 3 or len(set(devices)) != len(devices)
            or any(d not in DEVICES for d in devices)):
        problems.append("devices must be 1..3 of " + ", ".join(DEVICES))
    try:
        compiled = roblox_ui_compiler.compile_ui(spec.get("ui"))  # pyright: ignore[reportArgumentType]  # None -> TypeError, caught
    except (roblox_ui_compiler.SpecError, TypeError, ValueError) as error:
        problems.append("ui spec: " + str(error)[:300])
        compiled = None
    iterations = spec.get("maxIterations", UI_ITERATIONS)
    if type(iterations) is not int or not 1 <= iterations <= MAX_ITERATIONS:
        problems.append(f"maxIterations must be 1..{MAX_ITERATIONS}")
    expect, issue = check_expect(spec.get("expect"))
    if issue:
        problems.append(issue)
    if problems:
        return None, problems
    assert compiled is not None  # compile_ui failing adds a problem
    return {"name": name, "kind": "ui", "ui": copy.deepcopy(spec["ui"]), "devices": list(devices),
            "description": str(spec.get("description", ""))[:600], "defect": str(spec.get("defect", ""))[:80],
            "warnings": [str(w) for w in compiled.warnings][:10], "maxIterations": iterations, "expect": expect}, []


# --------------------------------------------------------------------------- geometry of the route

def _object_boxes(plan: dict) -> dict:
    """name -> {lo, hi, solid, kind, item} for parts and spawns."""
    boxes = {}
    for part in plan.get("parts", []):
        lo, hi = map_plan._aabb(part["position"], part["size"], part.get("rotation", (0, 0, 0)))
        boxes[part["name"]] = {"lo": lo, "hi": hi, "solid": part.get("canCollide", True), "kind": "part", "item": part}
    for spawn in plan.get("spawns", []):
        lo, hi = map_plan._aabb(spawn["position"], map_plan.SPAWN_SIZE)
        boxes[spawn["name"]] = {"lo": lo, "hi": hi, "solid": True, "kind": "spawn", "item": spawn}
    return boxes


def _leg(a: dict, b: dict) -> tuple[float, float]:
    dx = max(0.0, b["lo"][0] - a["hi"][0], a["lo"][0] - b["hi"][0])
    dz = max(0.0, b["lo"][2] - a["hi"][2], a["lo"][2] - b["hi"][2])
    return math.hypot(dx, dz), b["hi"][1] - a["hi"][1]


def probe_config(plan: dict, run: str, *, leg_seconds: float = LEG_SECONDS) -> dict:
    """What the in-game probe needs: the start (first spawn) and, per route surface, its top centre and half size."""
    boxes = _object_boxes(plan)
    names = list(plan["route"]["waypoints"])
    spawns = [s for s in plan.get("spawns", [])]
    first = boxes[names[0]] if names[0] in boxes and boxes[names[0]]["kind"] == "spawn" else boxes[spawns[0]["name"]]
    waypoints, previous = [], first
    lowest = min(box["lo"][1] for box in boxes.values())
    for name in names:
        box = boxes[name]
        if box is first:
            continue
        gap, rise = _leg(previous, box)
        centre = [(box["lo"][i] + box["hi"][i]) / 2 for i in range(3)]
        half = [(box["hi"][i] - box["lo"][i]) / 2 for i in range(3)]
        waypoints.append({"name": name, "top": [round(centre[0], 3), round(box["hi"][1], 3), round(centre[2], 3)],
                          "half": [round(max(half[0], 0.5), 3), round(half[1], 3), round(max(half[2], 0.5), 3)],
                          "jump": gap > 0.3 or rise > 0.5, "reach": round(max(1.5, min(half[0], half[2]) + 0.5), 3)})
        previous = box
    centre = [(first["lo"][i] + first["hi"][i]) / 2 for i in range(3)]
    return {"run": run, "start": [round(centre[0], 3), round(first["hi"][1], 3), round(centre[2], 3)],
            "waypoints": waypoints, "legSeconds": leg_seconds, "killY": round(lowest - 25, 3), "v": LAB_VERSION}


# --------------------------------------------------------------------------- Luau

PROBE_SOURCE = r"""-- STAR Studio Lab playtest probe (server). Runs only while the game runs; does nothing in Edit.
-- Drives the first player's character along the plan's route with Humanoid:MoveTo and Jump and prints one
-- marked JSON line per leg, so the lab can read real physics results from the output.
local RunService = game:GetService("RunService")
if not RunService:IsRunning() or not RunService:IsServer() then
	return
end
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local config = HttpService:JSONDecode(script:GetAttribute("StarLabConfig"))
local function round(x)
	return math.floor(x * 100 + 0.5) / 100
end
local function vec(p)
	return { round(p.X), round(p.Y), round(p.Z) }
end
local function say(kind, data)
	data.kind = kind
	data.run = config.run
	print("STAR_LAB_PROBE " .. HttpService:JSONEncode(data))
end
say("start", {})
local player = Players:GetPlayers()[1]
local waited = 0
while not player and waited < 30 do
	task.wait(0.25)
	waited += 0.25
	player = Players:GetPlayers()[1]
end
if not player then
	say("done", { ok = false, problem = "no player joined the playtest" })
	return
end
local character = player.Character or player.CharacterAdded:Wait()
local humanoid = character:WaitForChild("Humanoid", 15)
local root = character:WaitForChild("HumanoidRootPart", 15)
if not humanoid or not root then
	say("done", { ok = false, problem = "the character has no Humanoid or HumanoidRootPart" })
	return
end
task.wait(1.5)
local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude
params.FilterDescendantsInstances = { character }
local function below()
	-- A block the width of the character, cast down: also finds thin parts the feet stand on off-centre.
	local ok, hit = pcall(function()
		return workspace:Blockcast(root.CFrame, Vector3.new(1.8, 0.4, 1.2), Vector3.new(0, -12, 0), params)
	end)
	if not ok or not hit then
		hit = workspace:Raycast(root.Position, Vector3.new(0, -12, 0), params)
	end
	return if hit then hit.Instance:GetFullName() else ""
end
say("spawned", { position = vec(root.Position), standing_on = below(), gravity = workspace.Gravity,
	walk_speed = humanoid.WalkSpeed, jump_height = humanoid.JumpHeight, jump_power = humanoid.JumpPower,
	use_jump_power = humanoid.UseJumpPower, rig = humanoid.RigType.Name, hip_height = humanoid.HipHeight })
pcall(function()
	root:SetNetworkOwner(nil)
end)
local start = config.start
character:PivotTo(CFrame.new(start[1], start[2] + 3.2, start[3]))
root.AssemblyLinearVelocity = Vector3.zero
task.wait(1)
local allOk = true
for index, point in ipairs(config.waypoints) do
	local target = Vector3.new(point.top[1], point.top[2], point.top[3])
	local deadline = os.clock() + config.legSeconds
	local reached, lowest, highest, jumps, takeoff = false, root.Position.Y, root.Position.Y, 0, nil
	local stood, stoodList, climbed = {}, {}, false
	while os.clock() < deadline do
		humanoid:MoveTo(target)
		local p = root.Position
		local offset = Vector3.new(target.X - p.X, 0, target.Z - p.Z)
		local flat = offset.Magnitude
		local grounded = humanoid.FloorMaterial ~= Enum.Material.Air
		if point.jump and grounded and flat > point.reach then
			-- Jump the way a player does: at the edge of the current surface (no ground 2 studs ahead), or when
			-- the next surface is higher and close.
			local feet = p.Y - humanoid.HipHeight - root.Size.Y / 2
			local ahead = workspace:Raycast(p + offset.Unit * 2.2, Vector3.new(0, -(p.Y - feet) - 4, 0), params)
			local edge = ahead == nil or ahead.Position.Y < feet - 1.5
			local higher = target.Y - feet > 1.2 and flat < point.reach + 5
			if edge or higher then
				humanoid.Jump = true
				jumps += 1
				takeoff = takeoff or vec(p)
			end
		end
		highest = math.max(highest, p.Y)
		if humanoid:GetState() == Enum.HumanoidStateType.Climbing then
			climbed = true
		end
		if grounded and #stoodList < 8 then
			local name = below()
			if name ~= "" and not stood[name] then
				stood[name] = true
				table.insert(stoodList, name)
			end
		end
		lowest = math.min(lowest, p.Y)
		local inside = math.abs(p.X - target.X) <= point.half[1] + 0.25 and math.abs(p.Z - target.Z) <= point.half[3] + 0.25
		if inside and grounded and p.Y >= target.Y + 1.5 and flat <= point.reach then
			reached = true
			break
		end
		if p.Y < config.killY then
			break
		end
		task.wait(0.1)
	end
	local p = root.Position
	say("leg", { index = index, name = point.name, reached = reached, position = vec(p), lowest = round(lowest),
		highest = round(highest), fell = p.Y < target.Y - 4, jumps = jumps, takeoff = takeoff, standing_on = below(),
		stood_on = stoodList, climbed = climbed })
	if not reached then
		allOk = false
		break
	end
	task.wait(0.3)
end
say("done", { ok = allOk })
"""


def apply_luau(plan: dict, run: str) -> str:
    """Luau that (re)builds the plan under the managed root with the probe inside. The caller sends it through
    GuardedStudio, which wraps it as one undo recording. An old draft of the same map is replaced; nothing outside
    Workspace/MapDrafts is touched except Lighting when the plan sets it."""
    if not _TOKEN.fullmatch(run):
        raise ValueError("invalid run token")
    ops = map_plan.operations(plan)
    segments = root_segments(plan)
    config = probe_config(plan, run)
    lines = [
        "-- STAR Studio Lab apply (map plan, dry run passed). " + map_plan.CREDIT,
        "local function folder(parent, name)",
        "\tlocal found = parent:FindFirstChild(name)",
        "\tif found then return found end",
        '\tlocal made = Instance.new("Folder")',
        "\tmade.Name = name",
        "\tmade.Parent = parent",
        "\treturn made",
        "end",
        "local parent = workspace",
    ]
    for name in segments[:-1]:
        lines.append(f"parent = folder(parent, {_lua_string(name)})")
    lines += [
        f"local old = parent:FindFirstChild({_lua_string(segments[-1])})",
        "local replaced = old ~= nil",
        "if old then old:Destroy() end",
        'local root = Instance.new("Folder")',
        f"root.Name = {_lua_string(segments[-1])}",
        f"root:SetAttribute(\"StarLabRun\", {_lua_string(run)})",
        f"root:SetAttribute(\"StarLabPlan\", {_lua_string(digest(plan)[:16])})",
        "local folders = {}",
        f"folders[{_lua_string(ops[0]['path'])}] = root",
        "local count = 0",
    ]
    for op in ops[1:]:
        if op["op"] == "folder":
            name = op["path"].rsplit("/", 1)[1]
            lines += ["do", '\tlocal made = Instance.new("Folder")', f"\tmade.Name = {_lua_string(name)}",
                      "\tmade.Parent = root", f"\tfolders[{_lua_string(op['path'])}] = made", "end"]
        elif op["op"] == "create":
            lines.append("do")
            lines.append(f"\tlocal object = Instance.new({_lua_string(op['class'])})")
            lines.append(f"\tobject.Name = {_lua_string(op['name'])}")
            for prop, value in op["properties"].items():
                lines.append(f"\tobject.{prop} = {map_plan._luau_value(value)}")
            lines.append(f"\tobject.Parent = folders[{_lua_string(op['parent'])}]")
            lines.append("\tcount += 1")
            lines.append("end")
        elif op["op"] == "set":
            for prop, value in op["properties"].items():
                lines.append(f'game:GetService("Lighting").{prop} = {map_plan._luau_value(value)}')
    lines += [
        'local probe = Instance.new("Script")',
        f"probe.Name = {_lua_string(PROBE_NAME)}",
        f"probe:SetAttribute(\"StarLabConfig\", {_lua_string(canonical(config))})",
        f"probe.Source = {_lua_string(PROBE_SOURCE)}",
        "probe.Parent = root",
        "-- Only one probe may drive the character: switch off the probes of other drafts (inside the managed root).",
        "local drafts = workspace:FindFirstChild(" + _lua_string(segments[0]) + ")",
        "local silenced = 0",
        "if drafts then",
        "	for _, other in ipairs(drafts:GetDescendants()) do",
        f"		if other:IsA(\"Script\") and other.Name == {_lua_string(PROBE_NAME)} and other.Enabled then",
        "			other.Enabled = false",
        "			silenced += 1",
        "		end",
        "	end",
        "end",
        "root.Parent = parent",
        f'return "{APPLY_MARK}" .. game:GetService("HttpService"):JSONEncode({{parts = count, replaced = replaced, silenced = silenced, '
        f'run = {_lua_string(run)}}})',
    ]
    return "\n".join(lines) + "\n"


READ_PAGE = 10


def readback_luau(plan: dict, page: int = 0, per_page: int = READ_PAGE) -> str:
    """Reads only. Page 0: does the draft exist, its run mark, its scripts, and solid parts OUTSIDE the draft that
    intersect a solid draft part (spatial query per part, shrunk by 0.05 so touching faces do not count). Pages 1..:
    the draft's parts with their real values, compact. Pages keep every answer under the 2000 characters the edit
    receipt of studio_loop carries."""
    if type(page) is not int or page < 0 or type(per_page) is not int or not 1 <= per_page <= 40:
        raise ValueError("invalid page")
    path = ", ".join(_lua_string(name) for name in root_segments(plan))
    return f"""-- STAR Studio Lab read-back (reads only), page {page}
local HttpService = game:GetService("HttpService")
local node = workspace
for _, name in ipairs({{ {path} }}) do
	node = node and node:FindFirstChild(name)
end
if not node then
	return "{READ_MARK}" .. HttpService:JSONEncode({{ exists = false }})
end
local function r(x)
	return math.floor(x * 1000 + 0.5) / 1000
end
local parts = {{}}
for _, item in ipairs(node:GetDescendants()) do
	if item:IsA("BasePart") then
		table.insert(parts, item)
	end
end
table.sort(parts, function(a, b)
	return a:GetFullName() < b:GetFullName()
end)
local page, per = {page}, {per_page}
if page == 0 then
	local scripts, foreign, seen = {{}}, {{}}, {{}}
	for _, item in ipairs(node:GetDescendants()) do
		if item:IsA("LuaSourceContainer") then
			table.insert(scripts, {{ item.Name, item.ClassName, item:GetAttribute("StarLabConfig") ~= nil }})
		end
	end
	local params = OverlapParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = {{ node }}
	for _, item in ipairs(parts) do
		if item.CanCollide and #foreign < 8 then
			local size = item.Size - Vector3.new(0.1, 0.1, 0.1)
			if size.X > 0 and size.Y > 0 and size.Z > 0 then
				for _, other in ipairs(workspace:GetPartBoundsInBox(item.CFrame, size, params)) do
					local key = other:GetFullName()
					if other.CanCollide and not seen[key] and #foreign < 8 then
						seen[key] = true
						local p, s = other.Position, other.Size
						table.insert(foreign, {{ string.sub(key, 1, 80), item.Name, r(p.X), r(p.Y), r(p.Z), r(s.X), r(s.Y), r(s.Z) }})
					end
				end
			end
		end
	end
	return "{READ_MARK}" .. HttpService:JSONEncode({{ exists = true, run = node:GetAttribute("StarLabRun"),
		plan = node:GetAttribute("StarLabPlan"), total = #parts, scripts = scripts, foreign = foreign }})
end
local rows = {{}}
for index = (page - 1) * per + 1, math.min(page * per, #parts) do
	local item = parts[index]
	local p, s, o = item.Position, item.Size, item.Orientation
	table.insert(rows, {{ item.Name, item.ClassName, r(p.X), r(p.Y), r(p.Z), r(s.X), r(s.Y), r(s.Z),
		r(o.X), r(o.Y), r(o.Z), item.Anchored, item.CanCollide }})
end
return "{READ_MARK}" .. HttpService:JSONEncode({{ exists = true, page = page, total = #parts, rows = rows }})
"""


def merge_readback(pages: list[dict]) -> dict | None:
    """Turn the compact pages into {exists, run, parts:[{name, class, position, size, ...}], scripts, foreign}."""
    if not pages or not isinstance(pages[0], dict):
        return None
    head = pages[0]
    if not head.get("exists"):
        return {"exists": False}
    parts = []
    for page in pages[1:]:
        for row in page.get("rows", []) if isinstance(page, dict) else []:
            if isinstance(row, list) and len(row) == 13:
                parts.append({"name": row[0], "class": row[1], "position": row[2:5], "size": row[5:8],
                              "orientation": row[8:11], "anchored": row[11], "canCollide": row[12]})
    scripts = [{"name": s[0], "class": s[1], "run": s[2]} for s in head.get("scripts", []) if isinstance(s, list) and len(s) == 3]
    foreign = [{"name": f[0], "with": f[1], "position": f[2:5], "size": f[5:8]}
               for f in head.get("foreign", []) if isinstance(f, list) and len(f) == 8]
    return {"exists": True, "run": head.get("run"), "plan": head.get("plan"), "total": head.get("total"),
            "parts": parts, "scripts": scripts, "foreign": foreign, "complete": len(parts) == head.get("total")}


def remove_luau(names: list[str], root: str = map_plan.MANAGED_ROOT) -> str:
    """Delete draft folders by name, only directly under the managed root (one undo step through GuardedStudio)."""
    segments = root.rstrip("/").split("/")[1:]
    pattern = re.compile(map_plan._NAME["pattern"])
    if not names or len(names) > 50 or not all(isinstance(n, str) and pattern.match(n) for n in names)             or not segments or not all(pattern.match(n) for n in segments):
        raise ValueError("invalid draft names")
    path = ", ".join(_lua_string(n) for n in segments)
    wanted = ", ".join(_lua_string(n) for n in names)
    return f"""-- STAR Studio Lab: remove drafts by name (managed root only)
local node = workspace
for _, name in ipairs({{ {path} }}) do
	node = node and node:FindFirstChild(name)
end
local removed = {{}}
if node then
	for _, name in ipairs({{ {wanted} }}) do
		local draft = node:FindFirstChild(name)
		if draft and draft:IsA("Folder") then
			draft:Destroy()
			table.insert(removed, name)
		end
	end
end
return "{APPLY_MARK}" .. game:GetService("HttpService"):JSONEncode({{ removed = removed }})
"""


def marked_json(text: str, mark: str) -> dict | None:
    at = text.rfind(mark)
    if at < 0:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(text[at + len(mark):].lstrip())
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# --------------------------------------------------------------------------- verify (plan vs what Studio has)

def expected_parts(plan: dict) -> dict:
    found = {}
    for part in plan.get("parts", []):
        found[part["name"]] = {"class": part.get("class", "Part"), "position": list(part["position"]),
                               "size": list(part["size"]), "canCollide": part.get("canCollide", True),
                               "anchored": part.get("anchored", True)}
    for spawn in plan.get("spawns", []):
        found[spawn["name"]] = {"class": "SpawnLocation", "position": list(spawn["position"]),
                                "size": list(map_plan.SPAWN_SIZE), "canCollide": True, "anchored": True}
    return found


def verify(plan: dict, read: dict | None, run: str, *, tolerance: float = 0.02) -> dict:
    """Compare the read-back with the plan, and re-check the ACTUAL geometry with the map plan dry run."""
    if not read or not read.get("exists"):
        return {"ok": False, "exists": False, "problems": ["the draft folder is not in Studio"]}
    want = expected_parts(plan)
    have: dict[Any, Any] = {item.get("name"): item for item in read.get("parts", []) if isinstance(item, dict)}
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    mismatched = []
    for name in sorted(set(want) & set(have)):
        expected, actual = want[name], have[name]
        for key in ("position", "size"):
            got = actual.get(key) or [math.inf] * 3
            if any(abs(a - b) > tolerance for a, b in zip(expected[key], got)):
                mismatched.append({"name": name, "property": key, "plan": expected[key], "studio": got})
        for key in ("class", "canCollide", "anchored"):
            if expected[key] != actual.get(key):
                mismatched.append({"name": name, "property": key, "plan": expected[key], "studio": actual.get(key)})
    # The dry run again, on what Studio really holds (catches anything the engine changed, e.g. clamped sizes).
    actual_plan = copy.deepcopy(plan)
    by_name = {p["name"]: p for p in actual_plan.get("parts", [])}
    for name, item in have.items():
        if name in by_name and item.get("position") and item.get("size"):
            by_name[name]["position"], by_name[name]["size"] = list(item["position"]), list(item["size"])
    actual_report = map_plan.dry_run(actual_plan, include_operations=False)
    foreign = [f for f in read.get("foreign", []) if isinstance(f, dict)]
    probe_present = any(s.get("name") == PROBE_NAME and s.get("run") for s in read.get("scripts", []) if isinstance(s, dict))
    problems = []
    if read.get("complete") is False:
        problems.append("the read-back of the draft was incomplete")
    if read.get("run") != run:
        problems.append("the draft in Studio is from another run")
    if missing:
        problems.append(f"{len(missing)} planned parts are missing")
    if mismatched:
        problems.append(f"{len(mismatched)} property values differ from the plan")
    if not probe_present:
        problems.append("the playtest probe script is missing")
    return {"ok": not problems, "exists": True, "problems": problems, "missing": missing, "extra": extra,
            "mismatched": mismatched[:40], "foreign_overlaps": foreign,
            "actual_dry_run": {"ok": actual_report["ok"], "blockers": actual_report["blockers"],
                               "warnings": actual_report["warnings"], "bounds": actual_report.get("bounds")},
            "parts_in_studio": len(have), "build_hash": digest(sorted(read.get("parts", []), key=lambda p: str(p.get("name"))))}


# --------------------------------------------------------------------------- playtest output

def parse_probe(console: str, run: str) -> dict:
    """The probe lines of THIS run (marked with the run token) from the Studio output."""
    lines = []
    for raw in console.splitlines():
        at = raw.find(PROBE_MARK)
        if at < 0:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(raw[at + len(PROBE_MARK):])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("run") == run:
            lines.append(value)
    legs = [line for line in lines if line.get("kind") == "leg"]
    done = next((line for line in reversed(lines) if line.get("kind") == "done"), None)
    spawned = next((line for line in lines if line.get("kind") == "spawned"), None)
    failed = next((leg for leg in legs if not leg.get("reached")), None)
    return {"started": any(line.get("kind") == "start" for line in lines), "finished": done is not None,
            "ok": bool(done and done.get("ok") is True), "problem": (done or {}).get("problem", ""),
            "spawned": spawned, "legs": legs, "failed_leg": failed, "lines": len(lines)}


def console_errors(console: str, run: str) -> list[str]:
    """Error lines printed after this run's first probe line (the place's other scripts may print earlier)."""
    lines = console.splitlines()
    mark = re.compile(r'"run"\s*:\s*"' + re.escape(run) + '"')
    first = next((i for i, line in enumerate(lines) if PROBE_MARK in line and mark.search(line)), None)
    text = "\n".join(lines[first:]) if first is not None else ""
    pattern = re.compile(r"(?i)\b(error|exception|attempt to|is not a valid member|stack begin|infinite yield)\b")
    return [line.strip()[:400] for line in text.splitlines() if pattern.search(line) and PROBE_MARK not in line][:30]


# --------------------------------------------------------------------------- cameras

def cameras(plan: dict) -> list[dict]:
    """Four fixed cameras from the plan's geometry: overview, side (perpendicular to the route), top, route view."""
    boxes = _object_boxes(plan)
    lo = [min(b["lo"][i] for b in boxes.values()) for i in range(3)]
    hi = [max(b["hi"][i] for b in boxes.values()) for i in range(3)]
    centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
    size = [hi[i] - lo[i] for i in range(3)]
    reach = max(size[0], size[2], 20.0)
    along_x = size[0] >= size[2]
    names = [n for n in plan["route"]["waypoints"] if n in boxes]
    first, last = boxes[names[0]], boxes[names[-1]]
    start = [(first["lo"][i] + first["hi"][i]) / 2 for i in range(3)]
    end = [(last["lo"][i] + last["hi"][i]) / 2 for i in range(3)]
    direction = [end[0] - start[0], end[2] - start[2]]
    length = math.hypot(*direction) or 1.0
    back = [start[0] - direction[0] / length * 14, first["hi"][1] + 10, start[2] - direction[1] / length * 14]

    def r(values):
        return [round(v, 2) for v in values]

    side = ([centre[0], hi[1] + reach * 0.25, centre[2] + reach * 0.9] if along_x
            else [centre[0] + reach * 0.9, hi[1] + reach * 0.25, centre[2]])
    return [
        {"id": "overview", "position": r([centre[0] + reach * 0.6, hi[1] + reach * 0.55, centre[2] + reach * 0.6]),
         "look_at": r(centre)},
        {"id": "side", "position": r(side), "look_at": r(centre)},
        {"id": "top", "position": r([centre[0], hi[1] + reach * 1.1, centre[2] + 0.5]), "look_at": r(centre)},
        {"id": "route", "position": r(back), "look_at": r([end[0], last["hi"][1], end[2]])},
    ]


# --------------------------------------------------------------------------- diagnosis and fixes (pure)

CORRIDOR_HALF_WIDTH = 3.5   # studs either side of the line the character runs (centre to centre), R15 is ~2 wide


def _corridor(a: dict, b: dict) -> tuple[list[float], list[float]]:
    """The space a run-and-jump from surface a to surface b passes through: along the leg from a's far side to b's,
    across it a tube around the centre line (narrower than wide floors, so a crate at the side of a broad walkway is
    not 'in the way'), from just above the lower surface to JUMP_CLEARANCE above the higher one."""
    lo = [min(a["lo"][0], b["lo"][0]), min(a["hi"][1], b["hi"][1]) + 0.3, min(a["lo"][2], b["lo"][2])]
    hi = [max(a["hi"][0], b["hi"][0]), max(a["hi"][1], b["hi"][1]) + JUMP_CLEARANCE, max(a["hi"][2], b["hi"][2])]
    ca = [(a["lo"][i] + a["hi"][i]) / 2 for i in (0, 2)]
    cb = [(b["lo"][i] + b["hi"][i]) / 2 for i in (0, 2)]
    across = 2 if abs(cb[0] - ca[0]) >= abs(cb[1] - ca[1]) else 0
    k = 0 if across == 0 else 1
    line_lo, line_hi = min(ca[k], cb[k]) - CORRIDOR_HALF_WIDTH, max(ca[k], cb[k]) + CORRIDOR_HALF_WIDTH
    lo[across], hi[across] = max(lo[across], line_lo), min(hi[across], line_hi)
    return lo, hi


def _corridor_blockers(boxes: dict, source: str, target: str) -> list[str]:
    """Solid parts in the space a jump from `source` to `target` passes through (spawn pads and low steps excluded)."""
    a, b = boxes[source], boxes[target]
    lo, hi = _corridor(a, b)
    step_up = min(a["hi"][1], b["hi"][1]) + 1.2     # spawn pads and steps a character walks over
    return [name for name, box in boxes.items()
            if name not in (source, target) and box["solid"] and box["kind"] != "spawn" and box["hi"][1] > step_up
            and all(box["lo"][i] < hi[i] - 0.05 and box["hi"][i] > lo[i] + 0.05 for i in range(3))]


def _route_legs(plan: dict) -> list[tuple[str, str]]:
    route = [n for n in plan["route"]["waypoints"] if isinstance(n, str)]
    return list(zip(route, route[1:]))


def _all_corridor_blockers(boxes: dict, legs: list[tuple[str, str]]) -> set[str]:
    found = set()
    for source, target in legs:
        if source in boxes and target in boxes:
            found.update(_corridor_blockers(boxes, source, target))
    return found


# Roles a fixer may move aside or remove: they dress the map, the route does not depend on them.
MOVABLE_ROLES = ("decor", "prop", "")
REMOVABLE_ROLES = ("decor", "prop")
# Structural parts above the route (a beam, a roof) keep their place and shape; only their height changes.
OVERHEAD_ROLES = ("roof", "wall", "")
MAX_ASIDE = 12.0          # studs: further away a decoration no longer reads as part of the same spot
ASIDE_MARGIN = 0.5


def _part_box(item: dict) -> dict:
    lo, hi = map_plan._aabb(item["position"], item["size"], item.get("rotation", (0, 0, 0)))
    return {"lo": lo, "hi": hi}


def _fits(plan: dict, name: str, lo: list[float], hi: list[float]) -> bool:
    """Inside the declared bounds and not interpenetrating another solid object of the plan."""
    bounds = plan["bounds"]
    centre = bounds.get("center", [0, 0, 0])
    if any(lo[i] < centre[i] - bounds["size"][i] / 2 - 0.01 or hi[i] > centre[i] + bounds["size"][i] / 2 + 0.01
           for i in range(3)):
        return False
    for other, box in _object_boxes(plan).items():
        if other == name or not box["solid"]:
            continue
        if all(min(hi[i], box["hi"][i]) - max(lo[i], box["lo"][i]) > map_plan.OVERLAP_TOLERANCE for i in range(3)):
            return False
    return True


def _rests_on(plan: dict, name: str) -> bool:
    """True when the part stands on the ground level of the map or on top of another solid object."""
    boxes = _object_boxes(plan)
    box = boxes[name]
    ground = min(b["lo"][1] for b in boxes.values())
    if box["lo"][1] <= ground + map_plan.SUPPORT_TOLERANCE:
        return True
    return any(other != name and b["solid"] and abs(b["hi"][1] - box["lo"][1]) <= map_plan.SUPPORT_TOLERANCE
               and b["lo"][0] < box["hi"][0] and b["hi"][0] > box["lo"][0]
               and b["lo"][2] < box["hi"][2] and b["hi"][2] > box["lo"][2] for other, b in boxes.items())


def aside_moves(plan: dict, name: str) -> list[dict]:
    """Candidate horizontal moves that take `name` out of every route corridor, smallest first. Pure."""
    boxes = _object_boxes(plan)
    _ = boxes[name]["item"]  # an unknown name still raises KeyError here
    legs = _route_legs(plan)
    supported = _rests_on(plan, name)
    candidates = []
    for source, target in legs:
        if name not in _corridor_blockers(boxes, source, target):
            continue
        lo, hi = _corridor(boxes[source], boxes[target])
        box = boxes[name]
        for axis in (0, 2):
            candidates.append((axis, hi[axis] - box["lo"][axis] + ASIDE_MARGIN))
            candidates.append((axis, -(box["hi"][axis] - lo[axis] + ASIDE_MARGIN)))
    moves = []
    seen = set()
    for axis, shift in sorted(candidates, key=lambda c: abs(c[1])):
        shift = round(shift, 3)
        if (axis, shift) in seen or abs(shift) > MAX_ASIDE:
            continue
        seen.add((axis, shift))
        delta = [0.0, 0.0, 0.0]
        delta[axis] = shift
        trial = copy.deepcopy(plan)
        moved = next(p for p in trial["parts"] if p["name"] == name)
        _move(moved, delta)
        box = _part_box(moved)
        if not _fits(trial, name, box["lo"], box["hi"]):
            continue
        if supported and not _rests_on(trial, name):
            continue                    # it stood on something: it must still stand on something (never float it)
        if name in _all_corridor_blockers(_object_boxes(trial), legs):
            continue
        moves.append({"delta": delta, "distance": abs(shift)})
    return moves


def clearing_strategy(plan: dict, name: str, source: str, target: str) -> dict:
    """The smallest change that clears `name` from the route and keeps what the designer meant it to be:
      1. a decoration or prop: move it aside (shortest horizontal move that leaves every jump corridor, stays inside
         the bounds and overlaps nothing), else remove it; never float it in the air;
      2. a structural part already above the route (beam, roof): raise it just enough (its place and shape stay);
      3. anything else on the route (platforms, floors, goals) is never changed by this fixer: report only."""
    boxes = _object_boxes(plan)
    if name not in boxes or boxes[name]["kind"] != "part":
        return {"strategy": None, "object": name, "why": "not a part"}
    item = boxes[name]["item"]
    role = item.get("role", "")
    route = {n for n in plan["route"]["waypoints"] if isinstance(n, str)}
    if name in route:
        return {"strategy": None, "object": name, "why": "a route surface"}
    a, b = boxes[source], boxes[target]
    surface = max(a["hi"][1], b["hi"][1])
    overhead = boxes[name]["lo"][1] >= min(a["hi"][1], b["hi"][1]) + 2.0
    if role in OVERHEAD_ROLES and role != "" and overhead:
        lift = round(surface + JUMP_CLEARANCE - boxes[name]["lo"][1] + ASIDE_MARGIN, 3)
        return {"strategy": "raise-overhead", "object": name, "delta": [0.0, lift, 0.0]}
    if role in MOVABLE_ROLES:
        moves = aside_moves(plan, name)
        if moves:
            return {"strategy": "move-aside", "object": name, "delta": moves[0]["delta"],
                    "distance": moves[0]["distance"]}
        if role in REMOVABLE_ROLES:
            return {"strategy": "remove", "object": name, "why": f"no move aside within {MAX_ASIDE:g} studs fits"}
        if overhead:
            lift = round(surface + JUMP_CLEARANCE - boxes[name]["lo"][1] + ASIDE_MARGIN, 3)
            return {"strategy": "raise-overhead", "object": name, "delta": [0.0, lift, 0.0]}
    return {"strategy": None, "object": name, "why": f"role '{role}' is kept as designed"}


def diagnose(plan: dict, check: dict, probe: dict, errors: list[str]) -> list[dict]:
    """Defects with evidence, each with a `fix` the plan fixer knows, or fix None (report only)."""
    defects = []
    if check.get("missing") or check.get("mismatched"):
        defects.append({"code": "apply-mismatch", "fix": "reapply", "evidence": {
            "missing": check.get("missing", [])[:10], "mismatched": check.get("mismatched", [])[:5]}})
    if check.get("foreign_overlaps"):
        defects.append({"code": "foreign-overlap", "fix": "shift-map", "evidence": check["foreign_overlaps"][:10]})
    if errors:
        defects.append({"code": "runtime-error", "fix": None, "evidence": errors[:5]})
    if not probe.get("finished"):
        defects.append({"code": "probe-silent", "fix": None, "evidence": {"started": probe.get("started"),
                                                                          "problem": probe.get("problem", "")}})
        return defects
    if probe.get("problem"):
        defects.append({"code": "probe-problem", "fix": None, "evidence": probe["problem"]})
    boxes = _object_boxes(plan)
    route = [n for n in plan["route"]["waypoints"]]
    prefix = "Workspace." + ".".join(root_segments(plan)) + "."
    for leg in probe.get("legs", []):
        target = leg.get("name")
        if target not in route or route.index(target) == 0:
            continue
        source = route[route.index(target) - 1]
        allowed = {source, target} | {n for n, b in boxes.items() if b["kind"] == "spawn"}
        extra = sorted({str(name).rsplit(".", 1)[-1] for name in leg.get("stood_on", [])
                        if str(name).startswith(prefix)} - allowed)
        extra = [name for name in extra if name in boxes]
        a, b = boxes[source], boxes[target]
        # Got up a ledge higher than any real jump by CLIMBING its side (Humanoid climbing state; seen live on 9- and
        # 9.5-stud rises in v3): the route works for the probe but is not a jump a player can rely on.
        leg_gap, leg_rise = _leg(a, b)
        if leg.get("climbed") and not extra and leg_rise > REAL_JUMPED_RISE:
            defects.append({"code": "jump-too-high", "fix": "ease-rise", "object": target, "evidence": {
                "leg": f"{source} -> {target}", "gap": round(leg_gap, 2), "rise": round(leg_rise, 2), "climbed": True,
                "probe": leg}})
            return defects
        # Higher than a jump can lift the character (root 3 above the feet + JumpHeight 7.2 + margin), or climbing:
        # it got up on something. Name the parts in the jump corridor.
        too_high = (leg.get("highest") or 0) > max(a["hi"][1], b["hi"][1]) + 3 + 7.2 + 1.5
        if not extra and (too_high or leg.get("climbed")):
            extra = _corridor_blockers(boxes, source, target)
        if extra:
            defects.append(_clearing_defect("route-unintended-support", plan, extra, source, target, {
                "leg": f"{source} -> {target}", "stood_on": leg.get("stood_on"), "highest": leg.get("highest"),
                "probe": leg}))
            return defects
        if too_high:
            # Higher than a jump, and nothing of the plan is in the corridor: never call that a pass.
            defects.append({"code": "route-unexplained-height", "fix": None, "evidence": {
                "leg": f"{source} -> {target}", "highest": leg.get("highest"), "probe": leg}})
            return defects
    failed = probe.get("failed_leg")
    if not failed:
        return defects
    target = failed.get("name")
    if target not in boxes or target not in route:
        defects.append({"code": "route-failed", "fix": None, "evidence": failed})
        return defects
    index = route.index(target)
    if index == 0:
        # The first leg runs from the spawn onto the route's first surface: there is no earlier route surface to
        # measure a gap from or move toward, so report it (a fix would wrap around to the last surface).
        defects.append({"code": "route-failed", "fix": None, "object": target, "evidence": {"leg": f"spawn -> {target}",
                                                                                            "probe": failed}})
        return defects
    source = route[index - 1]
    a, b = boxes[source], boxes[target]
    gap, rise = _leg(a, b)
    evidence = {"leg": f"{source} -> {target}", "gap": round(gap, 2), "rise": round(rise, 2), "probe": failed}
    if not b["solid"]:
        defects.append({"code": "route-surface-not-collidable", "fix": "make-collidable", "object": target,
                        "evidence": evidence})
        return defects
    if b["kind"] == "part" and b["item"].get("anchored", True) is False:
        defects.append({"code": "route-surface-unanchored", "fix": "anchor", "object": target, "evidence": evidence})
        return defects
    corridor_lo, corridor_hi = _corridor(a, b)
    blockers = _corridor_blockers(boxes, source, target)
    if blockers:
        defects.append(_clearing_defect("jump-corridor-blocked", plan, blockers, source, target, {
            **evidence, "clearance_needed": JUMP_CLEARANCE,
            "corridor": {"min": [round(v, 2) for v in corridor_lo], "max": [round(v, 2) for v in corridor_hi]}}))
        return defects
    if rise > SAFE_RISE:
        defects.append({"code": "jump-too-high", "fix": "ease-rise", "object": target, "evidence": evidence})
    elif gap > SAFE_GAP:
        defects.append({"code": "jump-too-far", "fix": "extend-platform", "object": target, "evidence": evidence})
    else:
        defects.append({"code": "route-failed", "fix": "close-gap", "object": target, "heuristic": True,
                        "evidence": evidence})
    return defects


def _clearing_defect(code: str, plan: dict, objects: list[str], source: str, target: str, evidence: dict) -> dict:
    """A defect whose fix clears `objects` from the leg; report only when no object has an allowed strategy."""
    strategies = [clearing_strategy(plan, name, source, target) for name in objects]
    fixable = any(s.get("strategy") for s in strategies)
    return {"code": code, "fix": "clear-route" if fixable else None, "objects": list(objects),
            "leg": [source, target], "strategies": strategies, "evidence": evidence}


def _move(item: dict, delta) -> None:
    item["position"] = [round(p + d, 3) for p, d in zip(item["position"], delta)]


def _axis(a: dict, b: dict) -> tuple[int, float]:
    """The horizontal axis (0 = X, 2 = Z) a leg mostly runs along, and its direction (+1 / -1)."""
    ca = [(a["lo"][i] + a["hi"][i]) / 2 for i in range(3)]
    cb = [(b["lo"][i] + b["hi"][i]) / 2 for i in range(3)]
    axis = 0 if abs(cb[0] - ca[0]) >= abs(cb[2] - ca[2]) else 2
    return axis, (1.0 if cb[axis] >= ca[axis] else -1.0)


def _part(plan: dict, name: str) -> dict | None:
    return next((p for p in plan.get("parts", []) if p["name"] == name), None)


def extend_platform(plan: dict, target: str) -> dict | None:
    """Jump too far: grow the landing part toward the take-off by the missing distance; its far edge, height and the
    rest of the route stay where the designer put them. None when it cannot (a spawn, a rotated part, no room)."""
    route = [n for n in plan["route"]["waypoints"] if isinstance(n, str)]
    index = route.index(target)
    boxes = _object_boxes(plan)
    item = _part(plan, target)
    if item is None or index == 0 or any(item.get("rotation", (0, 0, 0))):
        return None
    a, b = boxes[route[index - 1]], boxes[target]
    gap, _rise = _leg(a, b)
    axis, direction = _axis(a, b)
    grow = round(gap - SAFE_GAP if gap > SAFE_GAP else min(1.5, gap * 0.5), 3)
    if grow <= 0 or grow > item["size"][axis] * 2 + 4:
        return None
    trial = copy.deepcopy(plan)
    grown = _part(trial, target)
    assert grown is not None  # the same part in a copy of the plan
    grown["size"][axis] = round(grown["size"][axis] + grow, 3)
    grown["position"][axis] = round(grown["position"][axis] - direction * grow / 2, 3)
    box = _part_box(grown)
    if not _fits(trial, target, box["lo"], box["hi"]):
        return None
    return {"plan": trial, "change": {"fix": "extend-platform", "object": target, "axis": "XYZ"[axis],
                                      "grown_by": grow, "size": grown["size"], "position": grown["position"]}}


def ease_rise(plan: dict, target: str) -> dict | None:
    """Rise too high: the smallest change that keeps the climb. (a) lower only the target when the next leg still
    climbs a safe amount; (b) add one step platform halfway in the gap. None when neither fits."""
    route = [n for n in plan["route"]["waypoints"] if isinstance(n, str)]
    index = route.index(target)
    boxes = _object_boxes(plan)
    if index == 0:
        return None
    a, b = boxes[route[index - 1]], boxes[target]
    gap, rise = _leg(a, b)
    drop = round(rise - SAFE_RISE, 3)
    item = _part(plan, target)
    if item is not None and drop > 0:
        next_rise = _leg(b, boxes[route[index + 1]])[1] if index + 1 < len(route) else 0.0
        if next_rise + drop <= SAFE_RISE:
            trial = copy.deepcopy(plan)
            moved = _part(trial, target)
            assert moved is not None  # the same part in a copy of the plan
            _move(moved, [0.0, -drop, 0.0])
            box = _part_box(moved)
            if _fits(trial, target, box["lo"], box["hi"]):
                return {"plan": trial, "change": {"fix": "lower-target", "object": target, "lowered_by": drop}}
    if gap >= 2.0:
        axis, direction = _axis(a, b)
        other = 2 if axis == 0 else 0
        lo_edge = a["hi"][axis] if direction > 0 else b["hi"][axis]
        hi_edge = b["lo"][axis] if direction > 0 else a["lo"][axis]
        length = round(max(1.0, (hi_edge - lo_edge) - 1.0), 3)
        across_lo = max(a["lo"][other], b["lo"][other])
        across_hi = min(a["hi"][other], b["hi"][other])
        if across_hi - across_lo < 2.0:          # the platforms do not face each other: use the landing's width
            across_lo, across_hi = b["lo"][other], b["hi"][other]
        width = round(min(6.0, across_hi - across_lo), 3)
        top = a["hi"][1] + rise / 2
        position = [0.0, round(top - 0.5, 3), 0.0]
        position[axis] = round((lo_edge + hi_edge) / 2, 3)
        position[other] = round((across_lo + across_hi) / 2, 3)
        size = [0.0, 1.0, 0.0]
        size[axis], size[other] = length, width
        names = {p["name"] for p in plan.get("parts", [])} | {s["name"] for s in plan.get("spawns", [])}
        candidates = [f"{target}Step"] + [f"{target}Step{n}" for n in range(2, 50)]
        name = next((c for c in candidates if c not in names), None)
        if name is None or len(name) > 64:
            return None
        step = {"name": name, "position": position, "size": size, "role": "platform"}
        for key in ("material", "color", "group"):
            if item is not None and key in item:
                step[key] = item[key]
        trial = copy.deepcopy(plan)
        trial["parts"].append(step)
        box = _part_box(step)
        if _fits(trial, name, box["lo"], box["hi"]):
            waypoints = trial["route"]["waypoints"]
            waypoints.insert(waypoints.index(target), name)
            return {"plan": trial, "change": {"fix": "add-step", "object": name, "before": target,
                                              "position": position, "size": size}}
    return None


def fix_plan(plan: dict, defects: list[dict]) -> tuple[dict, list[dict]]:
    """Apply the fixes the defects name to a COPY of the plan. Returns (new plan, what was changed).

    Strategy order (smallest change that keeps the designer's intent first):
      clear-route      decor/prop: move aside, else remove (never floated); beam/roof above the route: raise it
      extend-platform  grow the landing toward the take-off; fallback: move the rest of the route closer
      ease-rise        lower only the landing, else add one step halfway; fallback: lower the rest of the route
      anchor / make-collidable / shift-map / close-gap / lower-rest / raise-blockers (kept for older reports)"""
    new = copy.deepcopy(plan)
    changes = []
    for defect in defects:
        fix = defect.get("fix")
        objects = {item["name"]: item for key in ("parts", "spawns") for item in new.get(key, [])}
        route = list(new["route"]["waypoints"])
        if fix == "make-collidable":
            objects[defect["object"]]["canCollide"] = True
            changes.append({"fix": fix, "object": defect["object"], "canCollide": True})
        elif fix == "anchor":
            objects[defect["object"]]["anchored"] = True
            changes.append({"fix": fix, "object": defect["object"], "anchored": True})
        elif fix == "clear-route":
            source, target = defect["leg"]
            for name in defect["objects"]:
                if _part(new, name) is None:
                    continue
                chosen = clearing_strategy(new, name, source, target)
                strategy = chosen.get("strategy")
                if strategy in ("move-aside", "raise-overhead"):
                    moved = _part(new, name)
                    assert moved is not None  # checked at the top of this loop
                    _move(moved, chosen["delta"])
                    changes.append({"fix": strategy, "object": name, "delta": chosen["delta"]})
                elif strategy == "remove":
                    new["parts"] = [p for p in new["parts"] if p["name"] != name]
                    changes.append({"fix": "remove", "object": name, "why": chosen.get("why", "")})
                else:
                    changes.append({"fix": None, "object": name, "why": chosen.get("why", "")})
        elif fix in ("extend-platform", "ease-rise"):
            done = (extend_platform if fix == "extend-platform" else ease_rise)(new, defect["object"])
            if done is not None:
                new = done["plan"]
                changes.append(done["change"])
            else:
                fallback = {**defect, "fix": "close-gap" if fix == "extend-platform" else "lower-rest"}
                new, more = fix_plan(new, [fallback])
                changes.extend(more)
        elif fix == "raise-blockers":
            ceiling = defect["evidence"]["corridor"]["max"][1]
            for name in defect["objects"]:
                item = objects[name]
                box = _object_boxes({"parts": [item]} if _part(new, name) is not None else {"spawns": [item]})[name]
                lift = round(ceiling - box["lo"][1] + 0.5, 3)
                _move(item, [0, lift, 0])
                changes.append({"fix": fix, "object": name, "raised_by": lift})
        elif fix in ("close-gap", "lower-rest"):
            boxes = _object_boxes(new)
            index = route.index(defect["object"])
            if index == 0:      # no earlier route surface (route[-1] would be the goal): never move the course
                changes.append({"fix": None, "object": defect["object"], "why": "first route surface"})
                continue
            a, b = boxes[route[index - 1]], boxes[route[index]]
            gap, rise = _leg(a, b)
            if fix == "close-gap":
                ca = [(a["lo"][i] + a["hi"][i]) / 2 for i in (0, 2)]
                cb = [(b["lo"][i] + b["hi"][i]) / 2 for i in (0, 2)]
                length = math.hypot(cb[0] - ca[0], cb[1] - ca[1]) or 1.0
                step = (gap - SAFE_GAP) if gap > SAFE_GAP else min(1.5, gap)
                delta = [-(cb[0] - ca[0]) / length * step, 0.0, -(cb[1] - ca[1]) / length * step]
            else:
                delta = [0.0, -(rise - SAFE_RISE), 0.0]
            delta = [round(d, 3) for d in delta]
            moved = []
            for name in route[index:]:
                if name in objects and name not in moved:
                    _move(objects[name], delta)
                    moved.append(name)
            changes.append({"fix": fix, "objects": moved, "delta": delta})
        elif fix == "shift-map":
            boxes = _object_boxes(new)
            hi_x = max(max(f["position"][0] + f["size"][0] / 2 for f in defect["evidence"]), 0)
            lo_x = min(b["lo"][0] for b in boxes.values())
            delta = [round(hi_x - lo_x + 6, 3), 0.0, 0.0]
            for item in objects.values():
                _move(item, delta)
            bounds = new["bounds"]
            bounds["center"] = [round(c + d, 3) for c, d in zip(bounds.get("center", [0, 0, 0]), delta)]
            changes.append({"fix": fix, "delta": delta})
    return new, changes


# --------------------------------------------------------------------------- vision critique (optional)

class BrainCritic:
    """Asks the brain's vision model (OpenAI-compatible /v1/chat/completions, model alias star-vision) to look at
    the screenshots. Advisory only: its findings are reported, never applied by themselves. Configured by the
    operator: STAR_LAB_VISION_URL (or STAR_BRAIN_URL) and the brain key file (~/.star/server_api_key)."""

    def __init__(self, url: str | None = None, *, key_file: str | None = None, model: str = "star-vision",
                 timeout: float = 300.0, opener=None, max_images: int = 3):
        self.url = (url or os.environ.get("STAR_LAB_VISION_URL") or os.environ.get("STAR_BRAIN_URL") or "").rstrip("/")
        path = Path(key_file or os.environ.get("STAR_LAB_VISION_KEY_FILE") or Path.home() / ".star" / "server_api_key")
        try:
            self._key = path.read_text(encoding="utf-8").strip()
        except OSError:
            self._key = ""
        self.model, self.timeout, self.max_images = model, timeout, max_images
        import urllib.request
        self._open = opener or urllib.request.urlopen

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def __call__(self, images: list[tuple[str, bytes, str]], summary: str) -> dict:
        import urllib.request
        content: list[dict[str, Any]] = [{"type": "text", "text": (
            "You are checking screenshots of a Roblox obby/map blockout built from a plan. Plan summary:\n" + summary +
            "\nLook for visible defects: platforms floating or missing, gaps that look too wide to jump, parts "
            "blocking the path or the head room above it, clipping or z-fighting, the route not visible. Answer ONLY "
            'with JSON: {"defects":[{"code":"short-kebab-code","object":"name or empty","detail":"one sentence"}],'
            '"looks_ok":true|false}')}]
        for label, data, mime in images[:self.max_images]:
            content.append({"type": "text", "text": f"Camera: {label}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(data).decode()}})
        from .background_cap import slot_for
        slot = slot_for(self.url, self._key, self.model, opener=self._open)   # background: never the chat's slot
        body = json.dumps({"model": self.model, "temperature": 0.1, "max_tokens": 700,
                           "messages": [{"role": "user", "content": content}],
                           **({"id_slot": slot} if slot is not None else {})}).encode()
        request = urllib.request.Request(self.url + "/v1/chat/completions", data=body, method="POST", headers={
            "Content-Type": "application/json", **({"Authorization": "Bearer " + self._key} if self._key else {})})
        started = time.monotonic()
        try:
            with self._open(request, timeout=self.timeout) as response:
                answer = json.loads(response.read().decode("utf-8"))
            text = answer["choices"][0]["message"]["content"] or ""
        except Exception as error:   # never echo the URL or key
            return {"ok": False, "error": type(error).__name__, "seconds": round(time.monotonic() - started, 1)}
        text = re.sub(r"(?s)<think>.*?</think>", "", text)
        start = text.find("{")
        try:
            found, _ = json.JSONDecoder().raw_decode(text[start:]) if start >= 0 else (None, 0)
        except ValueError:
            found = None
        result = {"ok": isinstance(found, dict), "seconds": round(time.monotonic() - started, 1),
                  "model": self.model, "advisory": True}
        if isinstance(found, dict):
            listed = found.get("defects")
            defects = listed if isinstance(listed, list) else []
            result["defects"] = [{"code": str(d.get("code", ""))[:40], "object": str(d.get("object", ""))[:64],
                                  "detail": str(d.get("detail", ""))[:300]} for d in defects if isinstance(d, dict)][:12]
            result["looks_ok"] = found.get("looks_ok") is True
        else:
            result["raw"] = text[:600]
        return result


def plan_summary(plan: dict) -> str:
    report = map_plan.dry_run(plan, include_operations=False)
    route = report.get("route") or {}
    legs = "; ".join(f"{leg['from']}->{leg['to']} gap {leg['gap']} rise {leg['rise']}" for leg in route.get("legs", [])[:12])
    return (f"map {plan['mapName']}, {report['counts']['parts']} parts, {report['counts']['spawns']} spawns, "
            f"route legs: {legs}")


# --------------------------------------------------------------------------- lessons (Studio-verified)

LESSON_TEXT = {
    "jump-corridor-blocked": "Roblox obby: keep about 13 studs of free height above every jump (default jump "
                             "height 7.2 plus the character); move decorations aside instead of floating them.",
    "jump-too-far": "Roblox obby: keep jump gaps at or under about 7 studs for a default character (real playtests "
                    "always jumped 7.8, 9.5 only sometimes); widen the landing toward the jump, not the whole course.",
    "jump-too-high": "Roblox obby: keep rises between platforms at or under about 6 studs for a default character "
                     "(7.6 was the most a real playtest jumped); lower the landing or add one step halfway.",
    "route-unintended-support": "Roblox obby: keep decorations out of the jump path; a character can climb onto a "
                                "thin decor part over a gap and skip the jump. Move it beside the path.",
    "route-surface-not-collidable": "Roblox obby: every platform a player must stand on needs CanCollide = true; "
                                    "a non-collidable platform looks fine in Edit mode but players fall through.",
    "route-surface-unanchored": "Roblox obby: anchor every floating platform (Anchored = true); an unanchored one "
                                "looks right in Edit mode but falls away the moment the game runs.",
    "foreign-overlap": "Roblox maps: check a new build's area for existing parts before building; overlapping an "
                       "existing structure blocks the route.",
}


CLEARING_CODES = ("jump-corridor-blocked", "route-unintended-support")
# When the verified fix was not "move the decoration aside", the lesson says what really worked.
FIX_TEXT = {
    "raise-overhead": "Roblox obby: a beam or roof over a jump needs about 13 studs of free height above the take-off "
                      "and landing; raise the beam rather than moving the platforms.",
    "remove": "Roblox obby: a decoration standing in the running line on a small platform cannot move aside and stay "
              "on it; remove it or put it on its own base beside the route.",
}


def lesson_record(report: dict) -> dict | None:
    """A Studio-verified lesson candidate from a run that FAILED in a real playtest, was fixed, and then PASSED.
    The evidence ties the screenshots to the build they show (build hash = sha256 of the read-back parts)."""
    iterations = report.get("iterations", [])
    if len(iterations) < 2 or not report.get("passed"):
        return None
    fixed = [d for it in iterations[:-1] for d in it.get("defects", []) if d.get("code") in LESSON_TEXT
             and not d.get("heuristic")]
    if not fixed:
        return None
    code = fixed[0]["code"]
    first, last = iterations[0], iterations[-1]
    shots = [{"camera": s["camera"], "sha256": s["sha256"], "build_hash": last["verify"].get("build_hash")}
             for s in last.get("screenshots", []) if s.get("ok")]
    evidence = {
        "kind": "studio-verified", "run": report["run"], "place": report.get("place"),
        "studio": "real Roblox Studio playtest through the official Studio MCP (STAR Studio server)",
        "before": {"iteration": first["index"], "failed_leg": (first["probe"].get("failed_leg") or {}).get("name"),
                   "defect": fixed[0].get("evidence", {}).get("leg") or code},
        "fix": [c for it in iterations for c in it.get("fixes", [])][:6],
        "after": {"iteration": last["index"], "legs_reached": sum(1 for leg in last["probe"]["legs"] if leg.get("reached")),
                  "legs": len(last["probe"]["legs"]), "build_hash": last["verify"].get("build_hash")},
        "screenshots": shots, "plan_hash": digest(report.get("final_plan") or {}),
    }
    fixes = [c.get("fix") for it in iterations for c in it.get("fixes", [])]
    text = next((FIX_TEXT[f] for f in fixes if f in FIX_TEXT), None) if code in CLEARING_CODES else None
    text = text or LESSON_TEXT[code]
    return {"id": f"studio-lab-{report['run']}-{code}", "kind": "pitfall", "text": text, "code": code,
            "source": "studio-lab:" + report["run"], "source_type": "verified-fix", "evidence": evidence,
            "reviewed": False}


def lesson_evidence_text(record: dict) -> str:
    e = record["evidence"]
    return (f"studio-lab: real Studio playtest (run {e['run']}, place {e.get('place')}): leg {e['before']['defect']} "
            f"failed in iteration {e['before']['iteration']}; after the fix all {e['after']['legs']} legs were reached "
            f"in iteration {e['after']['iteration']} (build {str(e['after']['build_hash'])[:12]}); "
            f"{len(e['screenshots'])} screenshots tied to that build.")


def write_outbox(outbox: Path, records: list[dict]) -> dict:
    """Studio-verified records as JSON lines plus the app's lesson export format (all CANDIDATES, never accepted)."""
    from .lessons import LessonStore, write_export
    import tempfile
    outbox.mkdir(parents=True, exist_ok=True)
    with open(outbox / "studio-lab-verified.jsonl", "a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    rows = []
    for line in (outbox / "studio-lab-verified.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    newest = {row["id"]: row for row in rows if isinstance(row, dict) and row.get("id")}
    with tempfile.TemporaryDirectory(prefix="studio-lab-outbox-") as folder:
        store = LessonStore(Path(folder))
        try:
            for row in newest.values():
                store.capture_inferred(project="roblox", kind=row["kind"], text=row["text"],
                                       source_type="verified-fix", source=row["source"],
                                       evidence=lesson_evidence_text(row))
            data = store.export("roblox")
        finally:
            store.close()
    data["note"] = ("Written by the STAR Studio Lab. Every lesson is a CANDIDATE backed by a real Studio playtest that "
                    "failed, was fixed and then passed; no person has reviewed it.")
    write_export(outbox / "star-lessons-studio-lab.json", data)
    return {"records": len(newest), "file": "star-lessons-studio-lab.json"}


# --------------------------------------------------------------------------- UI specs (ScreenGui preview at device sizes)

UI_MARK = "STAR_LAB_UI "
UI_ATTRIBUTE = "StarLabUi"
PLAYER_GUI_LINE = 'local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")'
MIN_TOUCH = 44            # px: smallest comfortable touch target on a phone (Apple HIG / Roblox mobile guidance)


def ui_apply_luau(spec: dict, run: str) -> str:
    """Build the compiled ScreenGui in Edit mode, under StarterGui (shown in the edit viewport), tagged with the
    lab attribute; a ScreenGui of an earlier lab run with the same name is replaced. One undo step via GuardedStudio.
    The compiled module is used unchanged except where it would wait for a player's PlayerGui (none in Edit)."""
    from . import roblox_ui_compiler
    if not _TOKEN.fullmatch(run):
        raise ValueError("invalid run token")
    source = roblox_ui_compiler.compile_ui(spec["ui"]).source
    if source.count(PLAYER_GUI_LINE) != 1:
        raise ValueError("the compiled UI does not have the expected PlayerGui line")
    source = source.replace(PLAYER_GUI_LINE, "local playerGui = __starLabParent")
    return "\n".join([
        "-- STAR Studio Lab UI apply (Edit-mode preview of a compiled ScreenGui)",
        'local StarterGui = game:GetService("StarterGui")',
        "local removed = 0",
        "for _, old in ipairs(StarterGui:GetChildren()) do",
        f"\tif old:GetAttribute({_lua_string(UI_ATTRIBUTE)}) == {_lua_string(spec['name'])} then old:Destroy(); removed += 1 end",
        "end",
        "local before = {}",
        "for _, child in ipairs(StarterGui:GetChildren()) do before[child] = true end",
        "local __starLabParent = StarterGui",
        "local module = (function()",
        source,
        "end)()",
        "local made = {}",
        "for _, child in ipairs(StarterGui:GetChildren()) do",
        "\tif not before[child] and child:IsA(\"ScreenGui\") then",
        f"\t\tchild:SetAttribute({_lua_string(UI_ATTRIBUTE)}, {_lua_string(spec['name'])})",
        f"\t\tchild:SetAttribute(\"StarLabRun\", {_lua_string(run)})",
        "\t\ttable.insert(made, child.Name)",
        "\tend",
        "end",
        "local handleCount = 0",
        "if type(module) == \"table\" and type(module.handles) == \"table\" then",
        "\tfor _ in pairs(module.handles) do handleCount += 1 end",
        "end",
        f'return "{UI_MARK}" .. game:GetService("HttpService"):JSONEncode({{made = made, removed = removed, '
        f'run = {_lua_string(run)}, handles = handleCount}})',
    ]) + "\n"


def ui_device_luau(device: str) -> str:
    """Switch Studio's Device Simulator (StudioDeviceSimulatorService, plugin context) to a preset of the wanted
    kind, or stop simulating for 'desktop'. Reads back the viewport size. Changes only Studio's view, not the place."""
    if device not in DEVICES:
        raise ValueError("unknown device")
    match = ", ".join(_lua_string(m) for m in DEVICES[device]["match"])
    return f"""-- STAR Studio Lab: device simulator -> {device}
local HttpService = game:GetService("HttpService")
local ok, svc = pcall(function() return game:GetService("StudioDeviceSimulatorService") end)
local result = {{ device = {_lua_string(device)}, simulator = ok and svc ~= nil }}
if ok and svc then
	local wanted = {{ {match} }}
	if #wanted == 0 then
		pcall(function() svc:StopSimulationAsync() end)
		result.preset = "none"
	else
		local best, bestArea
		local listed, devices = pcall(function() return svc:GetDeviceListAsync() end)
		if listed then
			for _, id in ipairs(devices) do
				local got, info = pcall(function() return svc:GetDeviceInfoAsync(id) end)
				if got and info and info.Name then
					for _, word in ipairs(wanted) do
						if string.find(info.Name, word, 1, true) then
							local area = (info.Width or 0) * (info.Height or 0)
							if not best or area < bestArea then best, bestArea = {{ id = id, info = info }}, area end
						end
					end
				end
			end
		end
		if best then
			local set, problem = pcall(function() svc:SetDeviceAsync(best.id) end)
			pcall(function() svc:SetOrientationAsync(Enum.ScreenOrientation.LandscapeLeft) end)
			result.preset = best.info.Name
			result.set = set
			if not set then result.problem = string.sub(tostring(problem), 1, 160) end
		else
			result.preset = "not found"
		end
	end
	task.wait(0.6)
	local active = pcall(function() result.active = svc:GetDeviceAsync() end)
end
local camera = workspace.CurrentCamera
result.viewport = camera and {{ math.floor(camera.ViewportSize.X), math.floor(camera.ViewportSize.Y) }} or nil
return "{UI_MARK}" .. HttpService:JSONEncode(result)
"""


def ui_layout_luau(name: str, limit: int = 24) -> str:
    """Reads only: every visible GuiObject of the lab's ScreenGui with its on-screen box (compact rows)."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name) or not 1 <= limit <= 40:
        raise ValueError("invalid UI name")
    return f"""-- STAR Studio Lab UI layout read-back (reads only)
local HttpService = game:GetService("HttpService")
local StarterGui = game:GetService("StarterGui")
local camera = workspace.CurrentCamera
local rows, total = {{}}, 0
for _, gui in ipairs(StarterGui:GetChildren()) do
	if gui:GetAttribute({_lua_string(UI_ATTRIBUTE)}) == {_lua_string(name)} then
		for _, item in ipairs(gui:GetDescendants()) do
			if item:IsA("GuiObject") and item.Visible and item.Name ~= "ResponsiveRoot" then
				total += 1
				if #rows < {limit} then
					local p, s = item.AbsolutePosition, item.AbsoluteSize
					local fits = true
					if item:IsA("TextLabel") or item:IsA("TextButton") or item:IsA("TextBox") then fits = item.TextFits end
					table.insert(rows, {{ string.sub(item.Name, 1, 24), item.ClassName, math.floor(p.X), math.floor(p.Y),
						math.floor(s.X), math.floor(s.Y), fits, item:IsA("GuiButton") or item:IsA("TextBox") }})
				end
			end
		end
	end
end
return "{UI_MARK}" .. HttpService:JSONEncode({{ viewport = camera and {{ math.floor(camera.ViewportSize.X),
	math.floor(camera.ViewportSize.Y) }} or nil, total = total, rows = rows }})
"""


def ui_remove_luau(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("invalid UI name")
    return f"""-- STAR Studio Lab: remove lab ScreenGuis by name (only those carrying the lab attribute)
local removed = 0
for _, gui in ipairs(game:GetService("StarterGui"):GetChildren()) do
	if gui:GetAttribute({_lua_string(UI_ATTRIBUTE)}) == {_lua_string(name)} then gui:Destroy(); removed += 1 end
end
return "{UI_MARK}" .. game:GetService("HttpService"):JSONEncode({{ removed = removed }})
"""


def ui_check(layout: dict | None, device: str) -> list[dict]:
    """Layout problems from the read-back: off screen, clipped text, touch targets too small on a phone. Pure."""
    if not layout or not layout.get("viewport"):
        return [{"code": "ui-not-read", "detail": "no layout read-back"}]
    width, height = layout["viewport"]
    problems = []
    if not layout.get("rows"):
        problems.append({"code": "ui-empty", "detail": "the ScreenGui has no visible elements"})
    for row in layout.get("rows", []):
        if not isinstance(row, list) or len(row) != 8:
            continue
        name, cls, x, y, w, h, fits, interactive = row
        if w <= 0 or h <= 0:
            problems.append({"code": "ui-zero-size", "object": name, "detail": f"{cls} is {w}x{h} px"})
        elif x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1:
            problems.append({"code": "ui-off-screen", "object": name,
                             "detail": f"{cls} at {x},{y} size {w}x{h} outside {width}x{height}"})
        if fits is False:
            problems.append({"code": "ui-text-clipped", "object": name, "detail": f"{cls} text does not fit"})
        if interactive and device == "phone" and 0 < min(w, h) < MIN_TOUCH:
            problems.append({"code": "ui-touch-target-small", "object": name,
                             "detail": f"{cls} {w}x{h} px < {MIN_TOUCH} px"})
    return problems


# --------------------------------------------------------------------------- the live loop

def _text(result) -> str:
    from .studio_loop import result_text
    return result_text(result)


def _failed(result) -> bool:
    from .studio_loop import result_failed
    return result_failed(result)


def _images(result) -> list[tuple[bytes, str]]:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    found = []
    for part in (data.get("content", []) if isinstance(data, dict) else []):
        if isinstance(part, dict) and part.get("type") == "image" and part.get("data"):
            try:
                found.append((base64.b64decode(part["data"]), str(part.get("mimeType") or "image/png")))
            except ValueError:
                continue
    return found


def display_capture(command, target: Path) -> dict:
    """Optional operator command that writes a PNG of the true display to stdout (e.g. Studio during Play)."""
    if not command:
        return {"ok": False, "detail": "no display capture command"}
    try:
        done = subprocess.run(command, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "detail": type(error).__name__}
    if done.returncode or not done.stdout.startswith(b"\x89PNG"):
        return {"ok": False, "detail": f"exit {done.returncode}, {len(done.stdout)} bytes"}
    target.write_bytes(done.stdout)
    return {"ok": True, "file": target.name, "bytes": len(done.stdout), "sha256": digest(done.stdout)}


class Lab:
    """Drives one spec through the loop on an already opened GuardedStudio (see run_lab for the connection)."""

    def __init__(self, guarded, out: Path, *, capture_command=None, critic=None, log=print, sleep=asyncio.sleep,
                 poll: float = 2.0, play_lock=None, settle: float = 12.0):
        self.guarded, self.out = guarded, Path(out)
        self.capture_command, self.critic, self.log, self.sleep, self.poll = capture_command, critic, log, sleep, poll
        # Several Studios on one connector host: Play start/stop re-register each Studio's DataModels with the host.
        # Two Studios doing that in the same second once stalled both connectors (2026-10-13 20:54:51Z), so the
        # parallel runner passes one shared lock: a start holds it until this run's probe has printed (or `settle`
        # seconds), a stop holds it while stopping.
        self.play_lock = play_lock if play_lock is not None else contextlib.nullcontext()
        self.settle = settle

    async def _luau(self, code: str) -> tuple[bool, str, dict]:
        result = await self.guarded.call_tool("execute_luau", {"studio_id": self.guarded.studio_id,
                                                               "datamodel_type": "Edit", "code": code})
        entry = self.guarded.journal.entries[-1] if self.guarded.journal.entries else {}
        from .studio_loop import EDIT_MARK, _marked_json
        receipt = _marked_json(_text(result), EDIT_MARK) or {}
        got = receipt.get("result")
        answer = got if isinstance(got, str) else _text(result)
        return (not _failed(result) and entry.get("ok") is True), answer, entry

    async def _read(self, name: str, **arguments):
        return await self.guarded.call_tool(name, {"studio_id": self.guarded.studio_id, **arguments})

    async def apply(self, plan: dict, run: str) -> dict:
        ok, text, entry = await self._luau(apply_luau(plan, run))
        receipt = marked_json(text, APPLY_MARK) or {}
        return {"ok": ok and receipt.get("run") == run, "parts": receipt.get("parts"), "replaced": receipt.get("replaced"),
                "undo_tag": entry.get("tag"), "recorded": entry.get("recorded") or entry.get("connector_recorded"),
                "added": entry.get("added_count"), "removed": entry.get("removed"),
                "detail": "" if ok else (entry.get("diagnostic") or text[-300:])}

    async def remove(self, names: list[str], root: str = map_plan.MANAGED_ROOT) -> dict:
        ok, text, entry = await self._luau(remove_luau(names, root))
        receipt = marked_json(text, APPLY_MARK) or {}
        return {"ok": ok, "removed": receipt.get("removed", []), "undo_tag": entry.get("tag")}

    async def readback(self, plan: dict) -> dict | None:
        # Read-only Luau still goes through execute_luau, so it is journaled as an edit that changed nothing.
        ok, text, _entry = await self._luau(readback_luau(plan, 0))
        head = marked_json(text, READ_MARK) if ok else None
        pages: list[Any] = [head]
        if head and head.get("exists"):
            for page in range(1, math.ceil((head.get("total") or 0) / READ_PAGE) + 1):
                ok, text, _entry = await self._luau(readback_luau(plan, page))
                found = marked_json(text, READ_MARK) if ok else None
                if not found:
                    break
                pages.append(found)
        return merge_readback(pages)

    async def playtest(self, run: str, seconds: float, folder: Path) -> dict:
        console, probe, capture = "", parse_probe("", run), {"ok": False, "detail": "not taken"}
        async with self.play_lock:
            asked = time.monotonic()
            started = await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id,
                                                                       "is_start": True})
            start_s, probe_s = round(time.monotonic() - asked, 1), None
            if _failed(started):
                return {"ok": False, "started": False, "detail": _text(started)[:300], "probe": probe, "errors": []}
            settle_until = time.monotonic() + self.settle
            try:
                while time.monotonic() < settle_until and not probe["started"]:
                    await self.sleep(min(self.poll, 1.0))
                    console = _text(await self._read("get_console_output"))
                    probe = parse_probe(console, run)
                    if probe["started"] and probe_s is None:
                        probe_s = round(time.monotonic() - asked, 1)
            except BaseException:
                # Never leave Studio in Play (GuardedStudio would refuse every later edit): stop while still
                # holding the lock, then let the error go on.
                await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id,
                                                                 "is_start": False})
                raise
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline and not probe["finished"]:
                await self.sleep(self.poll)
                result = await self._read("get_console_output")
                console = _text(result)
                probe = parse_probe(console, run)
                if probe["legs"] and not capture.get("ok") and self.capture_command:
                    capture = display_capture(self.capture_command, folder / "play-display.png")
                if probe["finished"]:
                    break
        finally:
            async with self.play_lock:
                stopped = await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id,
                                                                           "is_start": False})
                # The stop may answer "Game Stopped" while Studio stays in Play (live 2026-10-16): verify, else press Stop.
                guard = getattr(self.guarded, "play_guard", None)
                edit = await guard.ensure_edit() if guard is not None else None
        self.log(f"play start: Studio confirmed in {start_s}s, probe up after {probe_s if probe_s is not None else 'never'}s")
        at = console.find(PROBE_MARK)
        (folder / "playtest-output.txt").write_text(console[console.rfind("\n", 0, at) + 1:] if at >= 0 else console[-4000:],
                                                    encoding="utf-8")
        return {"ok": probe["ok"], "started": True,
                "stopped": not _failed(stopped) and (edit is None or edit["edit"] is not False),
                "start_s": start_s, "probe_start_s": probe_s, "edit": edit,
                "stop_detail": "" if not _failed(stopped) else _text(stopped)[:200],
                "probe": probe, "errors": console_errors(console, run), "display_capture": capture}

    async def look(self, plan: dict, folder: Path, label: str) -> list[dict]:
        shots = []
        for camera in cameras(plan):
            result = await self._read("screen_capture", capture_id=f"StarLab_{label}_{camera['id']}",
                                      camera_position=camera["position"], look_at_position=camera["look_at"])
            images = _images(result)
            if _failed(result) or not images:
                shots.append({"camera": camera["id"], "ok": False, "detail": _text(result)[:200]})
                continue
            data, mime = images[0]
            name = f"{label}-{camera['id']}.{'jpg' if 'jpeg' in mime else 'png'}"
            (folder / name).write_bytes(data)
            shots.append({"camera": camera["id"], "ok": True, "file": name, "mime": mime, "bytes": len(data),
                          "sha256": digest(data), "position": camera["position"], "look_at": camera["look_at"],
                          "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return shots

    async def run(self, spec: dict, *, run: str | None = None) -> dict:
        run = run or secrets.token_hex(4)
        self.out.mkdir(parents=True, exist_ok=True)
        plan = copy.deepcopy(spec["plan"])
        report = {"lab": LAB_VERSION, "run": run, "spec": spec["name"], "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "place": None, "iterations": [], "passed": False, "max_iterations": spec["maxIterations"]}
        identity = getattr(getattr(self.guarded, "verdict", None), "identity", None)
        if identity is not None:
            report["place"] = {"place_id": identity.place_id, "universe_id": identity.game_id}
        for index in range(1, spec["maxIterations"] + 1):
            folder = self.out / f"iteration-{index}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
            token = run + secrets.token_hex(2)    # a token per playtest: the output keeps earlier sessions' lines
            step = {"index": index, "plan_hash": digest(plan), "token": token}
            report["iterations"].append(step)
            from .discord_bot.native_evidence import emit
            emit("studio-lab", report, self.out)
            dry = map_plan.dry_run(plan, include_operations=False)
            step["dry_run"] = {"ok": dry["ok"], "blockers": dry["blockers"], "warnings": dry["warnings"]}
            if not dry["ok"]:
                self.log(f"[{index}] plan blocked: {[b['code'] for b in dry['blockers']]}")
                break
            step["apply"] = await self.apply(plan, token)
            self.log(f"[{index}] apply: {step['apply']}")
            if not step["apply"]["ok"]:
                break
            read = await self.readback(plan)
            (folder / "readback.json").write_text(json.dumps(read, indent=1), encoding="utf-8")
            step["verify"] = verify(plan, read, token)
            self.log(f"[{index}] verify: ok={step['verify']['ok']} problems={step['verify'].get('problems')}")
            step["screenshots"] = await self.look(plan, folder, f"it{index}")
            self.log(f"[{index}] screenshots: {sum(1 for s in step['screenshots'] if s['ok'])}/{len(step['screenshots'])}")
            emit("studio-lab", report, self.out, phase="playtesting")
            step["playtest"] = await self.playtest(token, spec["playSeconds"], folder)
            step["probe"] = step["playtest"]["probe"]
            self.log(f"[{index}] playtest: ok={step['playtest']['ok']} legs="
                     f"{[(leg['name'], leg['reached']) for leg in step['probe']['legs']]} errors={len(step['playtest']['errors'])}")
            if self.critic is not None and getattr(self.critic, "enabled", False):
                images = [(s["camera"], (folder / s["file"]).read_bytes(), s["mime"]) for s in step["screenshots"] if s["ok"]]
                step["critique"] = await asyncio.to_thread(self.critic, images, plan_summary(plan)) if images else None
                self.log(f"[{index}] critique: {step['critique']}")
            step["defects"] = diagnose(plan, step["verify"], step["probe"], step["playtest"]["errors"])
            passed = step["verify"]["ok"] and step["playtest"]["ok"] and not step["defects"]
            step["passed"] = passed
            (folder / "step.json").write_text(json.dumps(step, indent=1, default=str), encoding="utf-8")
            if passed:
                report["passed"] = True
                break
            fixable = [d for d in step["defects"] if d.get("fix")]
            if not fixable or index == spec["maxIterations"]:
                self.log(f"[{index}] stopping: {'no automatic fix' if not fixable else 'iteration cap reached'}")
                break
            plan, step["fixes"] = fix_plan(plan, fixable)
            self.log(f"[{index}] fixes: {step['fixes']}")
        report["final_plan"] = plan
        report["changes"] = self.guarded.journal.report() if hasattr(self.guarded.journal, "report") else {}
        report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["lesson"] = lesson_record(report)
        (self.out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        from .discord_bot.native_evidence import emit
        emit("studio-lab", report, self.out)
        return report


# --------------------------------------------------------------------------- UI fixes (change the UI SPEC, then re-check)

UI_FIXABLE = ("ui-text-clipped", "ui-off-screen", "ui-zero-size")
UI_MARGIN = 12            # px from the screen edge a clamped element keeps
UI_LESSON_TEXT = {
    "ui-text-clipped": "Roblox UI: size a text label or button for its longest text at phone size (about 666x374 in "
                       "Studio's simulator), or let it wrap; a fixed pixel width that fits a short label clips a long one.",
    "ui-off-screen": "Roblox UI: place and size panels with Scale and AnchorPoint (or a UISizeConstraint), not large "
                     "pixel offsets; an offset that fits a desktop screen puts the panel off a phone screen.",
    "ui-zero-size": "Roblox UI: give every visible element a non-zero size; a zero-size element never shows.",
}


def _ui_tree(node: dict, parent=None):
    yield node, parent
    for child in node.get("children", []) or []:
        yield from _ui_tree(child, node)


def _ui_axis(vector: dict | None, axis: str) -> dict:
    return dict(((vector or {}).get(axis) or {}))


def fix_ui(ui: dict, devices: list[dict]) -> tuple[dict, list[dict]]:
    """Fix the UI spec for the layout problems Studio reported (per device read-back). Returns (new spec, changes).
    Smallest change first: widen a clipped label to its text (wrap + smaller text when even 90% of the narrowest
    screen is too small); clamp an off-screen element to the nearest edge with AnchorPoint/Scale; an element larger
    than the screen gets a Scale size with a UISizeConstraint keeping its designed pixel size as the maximum. Pure."""
    new = copy.deepcopy(ui)
    nodes, parents = {}, {}
    for node, parent in _ui_tree(new["root"]):
        key = str(node.get("name", node.get("id", "")))[:24]
        nodes[key], parents[key] = node, (str(parent.get("name", parent.get("id", "")))[:24] if parent else None)
    viewports = [tuple((d.get("layout") or {}).get("viewport") or ()) for d in devices]
    viewports = [v for v in viewports if len(v) == 2 and v[0] > 0 and v[1] > 0]
    if not viewports:
        return new, []
    narrow_w = min(v[0] for v in viewports)
    changes, fixed = [], set()

    def under_fixed(name):
        up = parents.get(name)
        while up:
            if up in fixed:
                return True
            up = parents.get(up)
        return False

    for device in devices:
        layout = device.get("layout") or {}
        viewport = layout.get("viewport") or [0, 0]
        width, height = viewport[0], viewport[1]
        rows = {row[0]: row for row in layout.get("rows", []) if isinstance(row, list) and len(row) == 8}
        for problem in device.get("problems", []):
            code, name = problem.get("code"), problem.get("object")
            node = nodes.get(name)
            if code not in UI_FIXABLE or node is None or name in fixed or under_fixed(name) or node is new["root"]:
                continue
            row = rows.get(name)
            size = node.setdefault("size", {})
            if code == "ui-text-clipped":
                text, text_size = str(node.get("text", "")), float(node.get("textSize", 14))
                need = int(round(len(text) * text_size * 0.56 + 2 * float(node.get("padding", 0)) + 20))
                cap = int(narrow_w * 0.9)
                if need <= cap:
                    size["x"] = {"offset": need}
                    size.setdefault("y", {"offset": 40})
                    changes.append({"fix": "ui-widen-text", "object": name, "width": need})
                else:
                    lines = 2
                    smaller = max(12, int(text_size * min(1.0, lines * cap / max(need, 1))))
                    tall = int(lines * smaller * 1.3 + 12)
                    size["x"] = {"offset": cap}
                    size["y"] = {"offset": max(int(_ui_axis(size, "y").get("offset", 0)), tall)}
                    node["textWrapped"], node["textSize"] = True, smaller
                    changes.append({"fix": "ui-wrap-text", "object": name, "width": cap, "textSize": smaller})
            elif code == "ui-off-screen" and row is not None and width > 0 and height > 0:
                _, _, x, y, w, h, _, _ = row
                if w > width * 0.95 or h > height * 0.95:
                    designed = [int(_ui_axis(size, "x").get("offset", 0)) or int(w),
                                int(_ui_axis(size, "y").get("offset", 0)) or int(h)]
                    size["x"] = {"scale": 0.9} if w > width * 0.95 else (size.get("x") or {"offset": int(w)})
                    size["y"] = {"scale": 0.9} if h > height * 0.95 else (size.get("y") or {"offset": int(h)})
                    node["maxSize"] = {"x": {"offset": designed[0]}, "y": {"offset": designed[1]}}
                    node["anchor"] = {"x": {"scale": 0.5}, "y": {"scale": 0.5}}
                    node["position"] = {"x": {"scale": 0.5}, "y": {"scale": 0.5}}
                    changes.append({"fix": "ui-fit-scale", "object": name, "maxSize": designed})
                else:
                    anchor = node.setdefault("anchor", {})
                    position = node.setdefault("position", {})
                    moved = {}
                    if x + w > width + 1:
                        anchor["x"], position["x"] = {"scale": 1}, {"scale": 1, "offset": -UI_MARGIN}
                        moved["x"] = "right"
                    elif x < -1:
                        anchor["x"], position["x"] = {"scale": 0}, {"offset": UI_MARGIN}
                        moved["x"] = "left"
                    if y + h > height + 1:
                        anchor["y"], position["y"] = {"scale": 1}, {"scale": 1, "offset": -UI_MARGIN}
                        moved["y"] = "bottom"
                    elif y < -1:
                        anchor["y"], position["y"] = {"scale": 0}, {"offset": UI_MARGIN}
                        moved["y"] = "top"
                    if not moved:
                        continue
                    anchor.setdefault("x", {"scale": 0})
                    anchor.setdefault("y", {"scale": 0})
                    position.setdefault("x", {"offset": 0})
                    position.setdefault("y", {"offset": 0})
                    changes.append({"fix": "ui-clamp", "object": name, "edges": moved})
            elif code == "ui-zero-size" and row is not None:
                _, _, _, _, w, h, _, _ = row
                if w <= 0:
                    size["x"] = {"offset": 120}
                if h <= 0:
                    size["y"] = {"offset": 40}
                size.setdefault("x", {"offset": 120})
                size.setdefault("y", {"offset": 40})
                changes.append({"fix": "ui-min-size", "object": name})
            else:
                continue
            fixed.add(name)
    return new, changes


def ui_lesson_record(report: dict) -> dict | None:
    """A Studio-verified UI lesson candidate: a layout problem seen in the real Device Simulator read-back, a fix of
    the UI spec, and a clean read-back on every device afterwards."""
    iterations = report.get("iterations", [])
    if len(iterations) < 2 or not report.get("passed"):
        return None
    codes = [p.get("code") for p in iterations[0].get("problems", []) if p.get("code") in UI_LESSON_TEXT]
    if not codes:
        return None
    code, last = codes[0], iterations[-1]
    evidence = {
        "kind": "studio-verified-ui", "run": report["run"], "place": report.get("place"),
        "studio": "real Roblox Studio Device Simulator read-back through the official Studio MCP",
        "before": {"iteration": 1, "defect": ", ".join(f"{p.get('code')}:{p.get('object')}@{p.get('device')}"
                                                       for p in iterations[0].get("problems", [])[:4])},
        "fix": [c for it in iterations for c in it.get("fixes", [])][:6],
        "after": {"iteration": last["index"], "devices": [d["device"] for d in last.get("devices", [])],
                  "legs": len(last.get("devices", [])), "build_hash": digest(report.get("final_ui") or {})},
        "screenshots": [{"device": d["device"], "sha256": (d.get("screenshot") or {}).get("sha256")}
                        for d in last.get("devices", []) if (d.get("screenshot") or {}).get("ok")],
    }
    return {"id": f"studio-lab-{report['run']}-{code}", "kind": "pitfall", "text": UI_LESSON_TEXT[code], "code": code,
            "source": "studio-lab:" + report["run"], "source_type": "verified-fix", "evidence": evidence,
            "reviewed": False}


class UiLab(Lab):
    """A UI spec: build the compiled ScreenGui in Edit mode, then per device size switch the Device Simulator, read
    the layout back, check it and take a screenshot of the viewport. Problems the fixer knows change the UI spec and
    the loop builds and checks again (maxIterations, default 2). The simulator is put back at the end."""

    async def _ui(self, code: str) -> tuple[bool, dict]:
        ok, text, _entry = await self._luau(code)
        return ok, (marked_json(text, UI_MARK) or {})

    async def _check(self, spec: dict, index: int) -> list[dict]:
        devices = []
        for device in spec["devices"]:
            _, switched = await self._ui(ui_device_luau(device))
            _, layout = await self._ui(ui_layout_luau(spec["name"]))
            shot = await self._read("screen_capture", capture_id=f"StarLabUi_{spec['name']}_{device}_{index}")
            images = _images(shot)
            entry = {"device": device, "simulator": switched, "layout": layout, "problems": ui_check(layout, device)}
            if images and not _failed(shot):
                data, mime = images[0]
                name = f"ui-it{index}-{device}.{'jpg' if 'jpeg' in mime else 'png'}"
                (self.out / name).write_bytes(data)
                entry["screenshot"] = {"ok": True, "file": name, "bytes": len(data), "sha256": digest(data),
                                       "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            else:
                entry["screenshot"] = {"ok": False, "detail": _text(shot)[:200]}
            devices.append(entry)
            self.log(f"[ui {index}] {device}: viewport {layout.get('viewport')} preset {switched.get('preset')} "
                     f"problems {[p['code'] for p in entry['problems']]}")
        return devices

    async def run(self, spec: dict, *, run: str | None = None, keep: bool = True) -> dict:
        run = run or secrets.token_hex(4)
        self.out.mkdir(parents=True, exist_ok=True)
        report = {"lab": LAB_VERSION, "kind": "ui", "run": run, "spec": spec["name"], "devices": [], "iterations": [],
                  "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "passed": False}
        identity = getattr(getattr(self.guarded, "verdict", None), "identity", None)
        if identity is not None:
            report["place"] = {"place_id": identity.place_id, "universe_id": identity.game_id}
        limit = int(spec.get("maxIterations", UI_ITERATIONS))
        current = dict(spec)
        try:
            for index in range(1, limit + 1):
                ok, applied = await self._ui(ui_apply_luau(current, run))
                step = {"index": index, "build_spec": current["ui"],
                        "apply": {"ok": ok and applied.get("run") == run and bool(applied.get("made")),
                                                  **applied}, "devices": [], "problems": [], "fixes": [],
                        "passed": False}
                report["iterations"].append(step)
                from .discord_bot.native_evidence import emit
                emit("studio-ui", report, self.out, phase="inspecting")
                report["apply"] = step["apply"]
                self.log(f"[ui {index}] apply: {step['apply']}")
                if not step["apply"]["ok"]:
                    break
                step["devices"] = await self._check(current, index)
                step["problems"] = [{**p, "device": d["device"]} for d in step["devices"] for p in d["problems"]]
                step["passed"] = bool(step["devices"]) and all(d["screenshot"]["ok"] and not d["problems"]
                                                               for d in step["devices"])
                report["devices"] = step["devices"]
                if step["passed"] or index >= limit:
                    break
                fixed_ui, step["fixes"] = fix_ui(current["ui"], step["devices"])
                self.log(f"[ui {index}] fixes: {step['fixes']}")
                if not step["fixes"]:
                    break
                try:
                    from . import roblox_ui_compiler
                    roblox_ui_compiler.compile_ui(fixed_ui)
                except Exception as error:               # a fix the compiler refuses: stop and report it
                    step["fix_refused"] = type(error).__name__
                    break
                current = {**current, "ui": fixed_ui}
        finally:
            _, reset = await self._ui(ui_device_luau("desktop"))
            report["reset"] = reset
        if not keep:
            report["removed"] = (await self._ui(ui_remove_luau(spec["name"])))[1]
        last = report["iterations"][-1] if report["iterations"] else {}
        report["passed"] = bool(last.get("passed"))
        report["final_ui"] = current["ui"]
        report["lesson"] = ui_lesson_record(report)
        report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (self.out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        from .discord_bot.native_evidence import emit
        emit("studio-ui", report, self.out)
        return report


def _admit(name: str):
    """One admission per lab run from STAR's resource planner when it is configured (fail-open)."""
    try:
        from .planner_client import PlannerClient   # added by the resource planner work (optional)
    except Exception:
        return None, None
    try:
        client = PlannerClient(timeout=3.0)
        if not client.enabled:
            return None, None
        grant = client.admit("studio-test", "studio-lab", "lab-run", universe_id=TEST_PLACE[0],
                             place_id=TEST_PLACE[1], identity_verified=False)
        return client, grant
    except Exception:
        return None, None


async def run_lab(home, spec: dict, out: Path, *, capture_command=None, critic=None, connector=None,
                  log=print) -> dict:
    """Connect to the chosen Studio target (STAR Studio server), check the place, run the loop."""
    from . import studio, studio_remote
    client, grant = _admit(spec["name"])
    if grant is not None and getattr(grant, "action", "") in ("wait", "yield", "refuse"):
        return {"ok": False, "passed": False, "problem": "the resource planner did not admit the lab run now: "
                + (getattr(grant, "reason", "") or grant.action)}
    try:
        async with (connector or studio_remote.connect)(home) as session:
            discovered = await studio.list_tools(session)
            guarded, facts = await studio_remote.open_server(session, discovered, home=home, opted_in=True)
            if guarded is None:
                return {"ok": False, "passed": False, "problem": facts.get("problem")}
            if not (guarded.verdict.editable and facts.get("is_test_place")):
                return {"ok": False, "passed": False, "problem": "the open place is not STAR Test Place or the sandbox "
                        "rule does not allow edits: " + str(facts.get("verdict", {}).get("reason", ""))}
            lab = (UiLab if spec.get("kind") == "ui" else Lab)(guarded, out, capture_command=capture_command,
                                                                  critic=critic, log=log)
            report = await lab.run(spec)
            report["ok"] = True
            return report
    finally:
        if client is not None and getattr(grant, "planned", False):
            try:
                client.release(grant)
            except Exception:
                pass


async def remove_drafts(home, names: list[str], *, connector=None) -> dict:
    """Delete lab drafts by name through the same guarded, pinned path (STAR Test Place only)."""
    from . import studio, studio_remote
    remove_luau(names)      # validate before connecting
    async with (connector or studio_remote.connect)(home) as session:
        discovered = await studio.list_tools(session)
        guarded, facts = await studio_remote.open_server(session, discovered, home=home, opted_in=True)
        if guarded is None or not (guarded.verdict.editable and facts.get("is_test_place")):
            return {"ok": False, "problem": "not STAR Test Place or edits not allowed"}
        return await Lab(guarded, Path(".")).remove(names)


def run_lab_sync(home, spec: dict, out: Path, *, timeout: float = 900.0, **kwargs) -> dict:
    """run_lab in its own thread and event loop, so a synchronous caller (a STAR tool) can use it safely."""
    box: dict = {}

    def target():
        try:
            box["report"] = asyncio.run(run_lab(home, spec, out, log=lambda *_: None, **kwargs))
        except Exception as error:
            box["report"] = {"ok": False, "passed": False, "problem": f"lab run failed ({type(error).__name__})"}

    thread = threading.Thread(target=target, name="star-studio-lab", daemon=True)
    thread.start()
    thread.join(timeout)
    return box.get("report") or {"ok": False, "passed": False, "problem": "the lab run did not finish in time"}


def public_summary(report: dict, out: Path | None = None) -> dict:
    """What a model or the owner sees: results and evidence files, no images, no commands."""
    if report.get("kind") == "ui":
        return {"ok": report.get("ok", False), "passed": report.get("passed", False), "run": report.get("run"),
                "kind": "ui", "problem": report.get("problem", ""), "applied": (report.get("apply") or {}).get("ok"),
                "devices": [{"device": d["device"], "viewport": (d.get("layout") or {}).get("viewport"),
                             "preset": (d.get("simulator") or {}).get("preset"),
                             "problems": [p["code"] for p in d.get("problems", [])],
                             "screenshot": (d.get("screenshot") or {}).get("file")} for d in report.get("devices", [])],
                "evidence_folder": str(out) if out else "",
                "note": "Edit-mode preview under StarterGui (tagged StarLabUi); nothing was saved or published."}
    iterations = []
    for step in report.get("iterations", []):
        probe = step.get("probe") or {}
        iterations.append({"iteration": step["index"], "applied": (step.get("apply") or {}).get("ok"),
                           "verified": (step.get("verify") or {}).get("ok"),
                           "legs": [(leg.get("name"), leg.get("reached")) for leg in probe.get("legs", [])],
                           "errors": len((step.get("playtest") or {}).get("errors", [])),
                           "defects": [d["code"] for d in step.get("defects", [])],
                           "fixes": step.get("fixes", []),
                           "screenshots": [s.get("file") for s in step.get("screenshots", []) if s.get("ok")],
                           "critique": (step.get("critique") or {}).get("defects")})
    return {"ok": report.get("ok", False), "passed": report.get("passed", False), "run": report.get("run"),
            "problem": report.get("problem", ""), "iterations": iterations,
            "lesson_candidate": (report.get("lesson") or {}).get("text"),
            "evidence_folder": str(out) if out else "", "note": "Built in STAR Test Place under Workspace/MapDrafts; "
            "nothing was saved or published. Undo: delete the draft folder or Ctrl+Z in Studio."}


# --------------------------------------------------------------------------- CLI

def _load_specs(path: Path) -> list[dict]:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description="STAR Studio Development Lab (plan, apply, playtest, look, fix)")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a spec offline (no Studio)")
    check.add_argument("spec")
    for name, text in (("run", "run one spec in Studio"), ("nightly", "run every spec in a folder (night school job)")):
        command = sub.add_parser(name, help=text)
        command.add_argument("spec", help="spec file (run) or folder of specs (nightly)")
        command.add_argument("--home", required=True, help="STAR data folder with studio/remote.json")
        command.add_argument("--out", required=True, help="evidence folder")
        command.add_argument("--capture", default="", help="JSON list: command that writes a PNG of the display")
        command.add_argument("--vision", action="store_true", help="ask the brain's vision model for a critique")
        command.add_argument("--outbox", default="", help="folder for Studio-verified lesson candidates")
        if name == "nightly":
            command.add_argument("--studios", type=int, default=0,
                                 help="run on this many Studios through the multi-Studio connector (1..3; 0 = the "
                                      "single-Studio path, every spec in the folder, no rotation)")
            command.add_argument("--rotate", type=int, default=0, help="specs per night (rotating; 0 = all)")
            command.add_argument("--max-minutes", type=float, default=45.0, help="no new spec after this many minutes")
            command.add_argument("--keep", type=int, default=14, help="nightly evidence folders to keep")
    remove = sub.add_parser("remove", help="delete lab drafts by name under Workspace/MapDrafts (one undo step)")
    remove.add_argument("names", nargs="+")
    remove.add_argument("--home", required=True)
    chosen = parser.parse_args(arguments)
    if chosen.command == "remove":
        print(json.dumps(asyncio.run(remove_drafts(Path(chosen.home), chosen.names))))
        return 0
    if chosen.command == "check":
        spec, problems = check_spec(json.loads(Path(chosen.spec).read_text(encoding="utf-8")))
        print(json.dumps({"ok": spec is not None, "problems": problems,
                          "cameras": cameras(spec["plan"]) if spec else [],
                          "probe": probe_config(spec["plan"], "0" * 8) if spec else None}, indent=1))
        return 0 if spec else 2
    if chosen.command == "nightly" and chosen.studios > 0:
        from . import studio_lab_parallel
        result = studio_lab_parallel.nightly(
            Path(chosen.spec), home=Path(chosen.home).expanduser(), out=Path(chosen.out),
            outbox=Path(chosen.outbox) if chosen.outbox else None, studios=chosen.studios, rotate=chosen.rotate,
            max_minutes=chosen.max_minutes, keep=chosen.keep,
            log=lambda text: print(time.strftime("%H:%M:%S"), text, flush=True))
        print(json.dumps({k: v for k, v in result.items() if k != "invalid"} | {"invalid": len(result["invalid"])},
                         indent=1, default=str))
        return 0 if result.get("ok") else 1
    capture = json.loads(chosen.capture) if chosen.capture else None
    critic = BrainCritic() if chosen.vision else None
    records, results = [], []
    for raw in _load_specs(Path(chosen.spec)):
        spec, problems = check_spec(raw)
        if spec is None:
            print(json.dumps({"spec": raw.get("name"), "problems": problems}))
            results.append(False)
            continue
        out = Path(chosen.out) / (spec["name"].replace(" ", "_") + "-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        report = asyncio.run(run_lab(Path(chosen.home), spec, out, capture_command=capture, critic=critic))
        print(json.dumps(public_summary(report, out), indent=1, default=str))
        results.append(bool(report.get("passed")))
        if report.get("lesson"):
            records.append(report["lesson"])
    if chosen.outbox and records:
        print(json.dumps(write_outbox(Path(chosen.outbox), records)))
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
