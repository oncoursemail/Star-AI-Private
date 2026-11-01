"""X-ray Eyes: check a Roblox build with the engine's exact data instead of pixels.

One Luau module (star/data/xray/xray.luau) runs in two places:
  * headless with Lune on .rbxl/.rbxlx/.rbxm/.rbxmx files (CI, Player Twins, no Studio needed);
  * in Roblox Studio through the Studio MCP connector's execute_luau tool (read-only snippet).

    python -m star.xray --place game.rbxl [--json r.json] [--md r.md] [--fixes] [--apply-fixes copy.rbxl]
    python -m star.xray --studio [--studio-id ID]
    python -m star.xray --exam [--trials 50 --seed 1]
    python -m star.xray --sample out.rbxlx [--houses 1] | --defects out.rbxlx --seed 5

Lune: $STAR_LUNE, `lune` on PATH, or a pinned copy in <workspace>/tools-portable/lune-*/ (outside the repo).
Fixes are a reviewable change list; --apply-fixes writes a COPY and never touches the input file.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

LUAU_DIR = Path(__file__).with_name("data") / "xray"
RUNNER = LUAU_DIR / "lune_runner.luau"
STUDIO_MARK = "STAR_XRAY "
SEVERITIES = ("high", "medium", "low")
PLACE_SUFFIXES = (".rbxl", ".rbxlx", ".rbxm", ".rbxmx")
TIMEOUT_SECONDS = 600


class XrayError(RuntimeError):
    pass


def find_lune() -> str | None:
    """$STAR_LUNE, then PATH, then the newest tools-portable/lune-*/ above this checkout."""
    env = os.environ.get("STAR_LUNE")
    if env and Path(env).is_file():
        return env
    found = shutil.which("lune")
    if found:
        return found
    exe = "lune.exe" if os.name == "nt" else "lune"
    for parent in Path(__file__).resolve().parents:
        candidates = sorted(parent.glob(f"tools-portable/lune-*/{exe}"))
        if candidates:
            return str(candidates[-1])
    return None


def _as_list(value) -> list:
    # Lune's JSON encoder writes an empty table as {}; a report list may come back as a dict.
    return value if isinstance(value, list) else []


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def normalize(report: dict) -> dict:
    for key in ("findings", "changes"):
        report[key] = _as_list(report.get(key))
    for key in ("counts", "skipped", "ms"):
        report[key] = _as_dict(report.get(key))
    return report


def run_lune(*args: str, lune: str | None = None, timeout: int = TIMEOUT_SECONDS) -> dict:
    exe = lune or find_lune()
    if not exe:
        raise XrayError("Lune is not installed: set STAR_LUNE or install lune v0.11.0 (see docs/agents/xray-eyes-20261021.md)")
    with tempfile.TemporaryDirectory(prefix="star-xray-") as tmp:
        out = Path(tmp) / "out.json"
        proc = subprocess.run([exe, "run", str(RUNNER), args[0], str(out), *args[1:]], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-12:]
            raise XrayError(f"lune {args[0]} failed (exit {proc.returncode}): " + " | ".join(tail))
        return json.loads(out.read_text(encoding="utf-8"))


def scan_file(place: str | Path, options: dict | None = None, apply_to: str | Path | None = None,
              lune: str | None = None) -> dict:
    place = Path(place)
    if place.suffix.lower() not in PLACE_SUFFIXES:
        raise XrayError(f"not a Roblox place or model file: {place}")
    if not place.is_file():
        raise XrayError(f"file not found: {place}")
    extra: list[str] = [str(place.resolve()), json.dumps(options or {})]
    if apply_to:
        apply_to = Path(apply_to).resolve()
        if apply_to == place.resolve():
            raise XrayError("--apply-fixes must name a new file; the input place is never overwritten")
        extra.append(str(apply_to))
    return normalize(run_lune("scan", *extra, lune=lune))


def exam(trials: int = 50, seed: int = 1, lune: str | None = None) -> dict:
    result = run_lune("exam", str(trials), str(seed), lune=lune)
    for key in ("misses", "alarms"):
        result[key] = _as_list(result.get(key))
    result["clean"]["findings"] = _as_list(result["clean"].get("findings"))
    result["clean"]["counts"] = _as_dict(result["clean"].get("counts"))
    return result


# --------------------------------------------------------------------------- Studio mode

def studio_code(options: dict | None = None) -> str:
    """The module plus a Studio host: exact text bounds, engine spatial queries, pathfinding, terrain,
    the measured R15 rig. Reads only; the one instance it creates (the R15 rig) is never parented.
    Options `rootPath` (dotted full name, e.g. Workspace.Obby) scans only that model or folder; `maxParts`
    returns a `cap` skip instead of a scan when the root holds more parts."""
    module = (LUAU_DIR / "xray.luau").read_text(encoding="utf-8").replace("\r\n", "\n")
    body, sep, _tail = module.rpartition("\nreturn Xray")
    if not sep:
        raise XrayError("xray.luau must end with `return Xray`")
    opts = {"maxFindings": 200, **(options or {})}
    payload = json.dumps(opts)
    if "]==]" in payload:
        raise XrayError("options contain an unsupported sequence")
    host = f"""
-- STAR:xray (reads only)
local HttpService = game:GetService("HttpService")
local TextService = game:GetService("TextService")
local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local OPTIONS = HttpService:JSONDecode([==[{payload}]==])
local env: Env = {{ mode = "studio" }}
env.yield = function()
	task.wait()
end
local textCache = {{}}
env.textSize = function(text: string, size: number, font: any, width: number): (number, number)
	local key = text .. "|" .. size .. "|" .. tostring(font) .. "|" .. width
	local hit = textCache[key]
	if hit then
		return hit[1], hit[2]
	end
	local params = Instance.new("GetTextBoundsParams")
	params.Text = text
	params.Size = size
	if font then
		params.Font = font
	end
	params.Width = math.min(width, 100000)
	local bounds = TextService:GetTextBoundsAsync(params)
	textCache[key] = {{ bounds.X, bounds.Y }}
	return bounds.X, bounds.Y
end
local overlap = OverlapParams.new()
env.partsInBox = function(part: any, margin: number): {{ any }}
	return workspace:GetPartBoundsInBox(part.CFrame, part.Size + Vector3.new(2 * margin, 2 * margin, 2 * margin), overlap)
end
env.pathfind = function(from: any, to: any): string
	local path = PathfindingService:CreatePath({{ AgentRadius = 2, AgentHeight = 5, AgentCanJump = true }})
	path:ComputeAsync(from.Position + Vector3.new(0, from.Size.Y / 2 + 3, 0), to.Position + Vector3.new(0, to.Size.Y / 2 + 1, 0))
	return path.Status.Name
end
local okCells, cells = pcall(function()
	return workspace.Terrain:CountCells()
end)
if okCells and cells > 0 then
	local rays = RaycastParams.new()
	rays.FilterType = Enum.RaycastFilterType.Include
	rays.FilterDescendantsInstances = {{ workspace.Terrain }}
	env.onTerrain = function(x: number, y: number, z: number): boolean
		return workspace:Raycast(Vector3.new(x, y + 0.5, z), Vector3.new(0, -1, 0), rays) ~= nil
	end
end
local okRig, rig = pcall(function()
	return Players:CreateHumanoidModelFromDescription(Instance.new("HumanoidDescription"), Enum.HumanoidRigType.R15)
end)
if okRig and rig then
	local extents = rig:GetExtentsSize()
	env.avatar = {{ height = extents.Y, heightMax = math.max(extents.Y, Xray.AVATAR.heightMax),
		heightClassic = Xray.AVATAR.heightClassic, width = math.max(extents.X, extents.Z), source = "studio R15 rig" }}
	rig:Destroy()
end
local root: any = game
local rootPath = OPTIONS.rootPath
if rootPath then
	for segment in string.gmatch(rootPath, "[^%.]+") do
		root = root:FindFirstChild(segment)
		if not root then
			return "{STUDIO_MARK}" .. HttpService:JSONEncode({{ mode = "studio", parts = 0, skipped = {{ root = "not found: " .. rootPath }} }})
		end
	end
end
if OPTIONS.maxParts then
	local count = if root:IsA("BasePart") then 1 else 0
	for _, d in root:GetDescendants() do
		if d:IsA("BasePart") then
			count += 1
		end
	end
	if count > OPTIONS.maxParts then
		return "{STUDIO_MARK}" .. HttpService:JSONEncode({{ mode = "studio", parts = count,
			skipped = {{ cap = count .. " parts, over the limit of " .. OPTIONS.maxParts }} }})
	end
end
local report = Xray.scan(root, OPTIONS, env)
return "{STUDIO_MARK}" .. HttpService:JSONEncode(report)
"""
    return body + "\n" + host


async def scan_studio(options: dict | None = None, studio_id: str | None = None) -> dict:
    """Run the read-only snippet in a connected Studio. Refuses deny-listed places (e.g. owner projects)."""
    from . import studio as studio_mcp
    from .studio_loop import identify, judge, name_is_denied

    connect: Any = studio_mcp.connect  # an asynccontextmanager; pyright misreads it without the mcp stubs
    async with connect() as client:
        tools = await studio_mcp.list_tools(client)
        names = {tool["name"] for tool in tools}
        if "execute_luau" not in names:
            raise XrayError("this Studio MCP connector has no execute_luau tool")
        instances = await studio_mcp.list_studios(client, tool_count=len(tools))
        if studio_id:
            chosen = studio_mcp.select_studio(instances, studio_id)
        elif len(instances) == 1:
            chosen = instances[0]
        else:
            listing = ", ".join(f"{s['id']} ({s['name']})" for s in instances)
            raise XrayError(f"several Studios are open; pass --studio-id (one of: {listing})")
        if name_is_denied(chosen["name"]):
            raise XrayError("this place is on STAR's deny-list; X-ray does not read it")
        identity = await identify(client, chosen["id"], tools=names, studio_name=chosen["name"])
        if judge(identity, opted_in=False, studio_name=chosen["name"]).kind == "denied":
            raise XrayError("this place is on STAR's deny-list; X-ray does not read it")
        report = await scan_session(client, chosen["id"], options)
        report["studio"] = {"id": chosen["id"], "name": chosen["name"][:120]}
        return report


async def scan_session(session: Any, studio_id: str, options: dict | None = None) -> dict:
    """Run the read-only snippet over an already judged Studio session (the check-fix loop's rung)."""
    from .studio_loop import _marked_json, result_failed, result_text
    result = await session.call_tool("execute_luau", {"studio_id": studio_id, "datamodel_type": "Edit",
                                                      "code": studio_code(options)})
    text = result_text(result)
    report = None if result_failed(result) else _marked_json(text, STUDIO_MARK)
    if report is None:
        raise XrayError("Studio did not return an X-ray report: " + text[:300])
    return normalize(report)


# --------------------------------------------------------------------------- report

def _cell(value) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def render_markdown(report: dict) -> str:
    report = normalize(dict(report))
    findings = report["findings"]
    lines = ["# X-ray Eyes report", ""]
    where = report.get("place") or (report.get("studio") or {}).get("name") or "?"
    lines.append(f"Place: `{where}`. Mode: {report.get('mode')}, {report.get('parts', 0)} parts, "
                 f"{report.get('screenGuis', 0)} ScreenGuis, grid {report.get('grid')}, text metrics "
                 f"{report.get('textMetrics')}, spatial {report.get('spatial')}, scan {report.get('totalMs')} ms.")
    lines.append("")
    by_sev = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEVERITIES}
    lines.append(f"**{report.get('total', len(findings))} findings**: " + ", ".join(f"{n} {s}" for s, n in by_sev.items()))
    if report.get("truncated"):
        lines.append(f"(list cut to {len(findings)}; counts below are complete)")
    if report["counts"]:
        lines += ["", "| Detector | Findings |", "|---|---|"]
        lines += [f"| {d} | {n} |" for d, n in sorted(report["counts"].items())]
    if findings:
        lines += ["", "| Severity | Detector | Instance | Measured | Problem | Fix |", "|---|---|---|---|---|---|"]
        for f in findings:
            measured = f"{f.get('value')} {f.get('unit', '')}".strip()
            if f.get("viewport"):
                measured += f" ({f['viewport']})"
            lines.append(f"| {f.get('severity')} | {f.get('detector')} | `{_cell(f.get('path'))}` | {_cell(measured)} | "
                         f"{_cell(f.get('message'))} | {_cell(f.get('fix'))} |")
    if report["changes"]:
        lines += ["", "## Proposed safe fixes (not applied)", "", "| # | Instance | Move (x, y, z) | Why |", "|---|---|---|---|"]
        for i, c in enumerate(report["changes"], 1):
            lines.append(f"| {i} | `{_cell(c['path'])}` | ({c['dx']}, {c['dy']}, {c['dz']}) | {_cell(c['reason'])} |")
        if report.get("appliedTo"):
            lines.append(f"\nApplied to a copy: `{report['appliedTo']}` (input unchanged).")
    if report["skipped"]:
        lines += ["", "Skipped: " + "; ".join(f"{k} ({v})" for k, v in sorted(report["skipped"].items()))]
    if report.get("textMetrics") == "estimated":
        lines.append("Text overflow uses estimated font metrics headless (flagged only above 10 % overflow); Studio mode measures exactly.")
    return "\n".join(lines) + "\n"


def render_exam(result: dict) -> str:
    lines = ["# X-ray Eyes planted-defect exam", "",
             f"{result['trials']} trials (seed {result['seed']}), one planted defect of every type per trial; "
             f"clean place findings: {result['clean']['total']}.", "",
             "| Detector | Planted | Found | Recall | False alarms | On clean place |", "|---|---|---|---|---|---|"]
    for d in result["detectors"]:
        lines.append(f"| {d['detector']} | {d['planted']} | {d['detected']} | {d['recall']:.1%} | {d['falseAlarms']} | "
                     f"{d['cleanFalseAlarms']} |")
    lines.append(f"| **all** | {result['planted']} | {result['detected']} | {result['recall']:.1%} | {result['falseAlarms']} | "
                 f"{result['clean']['total']} |")
    lines += ["", f"Collateral findings (other detectors on a planted target): {result['collateral']}. "
              f"Mean scan {result['scanMsAvg']} ms. Not examined headless: unreachable (Studio pathfinding)."]
    for m in result["misses"][:10]:
        lines.append(f"- miss: trial {m['trial']} {m['detector']}: {m['note']}")
    for a in result["alarms"][:10]:
        lines.append(f"- false alarm: trial {a['trial']} {a['detector']} {a['path']}: {a['message']}")
    return "\n".join(lines) + "\n"


def _fails(report: dict, level: str | None) -> bool:
    if not level:
        return False
    limit = SEVERITIES.index(level)
    return any(f.get("severity") in SEVERITIES[: limit + 1] for f in report["findings"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.xray", description=(__doc__ or "").split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--place", help=".rbxl/.rbxlx/.rbxm/.rbxmx file (headless, Lune)")
    mode.add_argument("--studio", action="store_true", help="scan the place open in Studio (Studio MCP, read-only)")
    mode.add_argument("--exam", action="store_true", help="run the planted-defect exam")
    mode.add_argument("--sample", metavar="OUT", help="write the clean sample place")
    mode.add_argument("--defects", metavar="OUT", help="write the sample place with one planted defect per type (+ OUT.json)")
    ap.add_argument("--studio-id", help="Studio instance id when several are open")
    ap.add_argument("--json", metavar="FILE", help="write the JSON report")
    ap.add_argument("--md", metavar="FILE", help="write the markdown report")
    ap.add_argument("--fixes", action="store_true", help="include the safe-fix change list")
    ap.add_argument("--apply-fixes", metavar="COPY", help="write a copy of --place with the change list applied")
    ap.add_argument("--detectors", help="comma-separated subset of detectors")
    ap.add_argument("--max-findings", type=int)
    ap.add_argument("--fail-on", choices=SEVERITIES, help="exit 1 when a finding at this severity or worse exists")
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--houses", type=int, default=1)
    args = ap.parse_args(argv)

    options: dict = {}
    if args.fixes or args.apply_fixes:
        options["fixes"] = True
    if args.detectors:
        options["detectors"] = [d.strip() for d in args.detectors.split(",") if d.strip()]
    if args.max_findings:
        options["maxFindings"] = args.max_findings
    try:
        if args.exam:
            result = exam(args.trials, args.seed)
            text = render_exam(result)
        elif args.sample:
            result = run_lune("sample", str(Path(args.sample).resolve()), str(args.houses))
            text = f"wrote {result['written']} ({result['parts']} instances in Workspace)\n"
        elif args.defects:
            result = run_lune("defects", str(Path(args.defects).resolve()), str(args.seed))
            Path(args.defects + ".json").write_text(json.dumps(result["plants"], indent=2), encoding="utf-8")
            text = f"wrote {result['written']} and {args.defects}.json ({len(result['plants'])} planted defects)\n"
        else:
            if args.studio:
                result = asyncio.run(scan_studio(options, args.studio_id))
            else:
                result = scan_file(args.place, options, args.apply_fixes)
                result["place"] = str(args.place)
            text = render_markdown(result)
    except XrayError as exc:
        print(f"xray: {exc}", file=sys.stderr)
        return 2
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(text, encoding="utf-8")
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(errors="replace")  # instance names can hold characters the console code page lacks
    sys.stdout.write(text)
    return 1 if (args.place or args.studio) and _fails(result, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
