"""STAR learns game design from robot playtests of its own games (milestone 1).

    short game spec --STAR (the brain) writes server Scripts--> applied in STAR Test Place (Workspace/MapDrafts/
    Playtest/<game>, one undo step) --> real Studio playtest: STAR's robot player plays it (server/studio_lab/playtest/robot.luau)
    --> playtest report (which checks passed, where it got stuck, script errors) --> failures go back to STAR as a
    fix task --> re-playtest (capped) --> before/after record --> night-school outbox (worked examples + lessons)

Everything that touches Studio goes through the Studio Lab's guarded path (studio_lab_parallel.open_instance:
STAR Test Place or a blank place only, pinned identity, one undo step per edit, journal). The brain's code is never
run in Edit mode: it is stored as Script sources (string literals) and only runs inside the playtest, so a broken
answer shows up as an error in the output, which is exactly the feedback the fix task needs.

The robot is a server Script (like the Studio Lab probe): GuardedStudio refuses the connector's input tools on
purpose. It drives the character with Humanoid:MoveTo/Jump (real engine physics) toward named goals, detects being
stuck, and prints one marked line per check.

Switch: nothing here runs in Studio unless STAR_PLAYTEST_LEARNING=1 (the brain-only `generate` mode needs it too).
Results are CANDIDATES (reviewed=false) in the night-school outbox formats: worked-examples.jsonl
(star/worked_examples.validate_row) and star-lessons-playtest.json (the app's lesson export).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any, Callable

SWITCH = "STAR_PLAYTEST_LEARNING"
MARK = "STAR_PLAY "
APPLY_MARK = "STAR_PLAY_APPLY "
ROBOT_NAME = "StarPlayRobot"
PLAYTEST_FOLDER = "Playtest"
PAUSED = "StarPlayPaused"
SERVICES_LUAU = ("local SERVICES = {}\nfor _, name in ipairs({ \"Workspace\", \"ServerScriptService\", \"StarterPlayer\", "
                 "\"StarterGui\", \"StarterPack\", \"ReplicatedFirst\", \"ReplicatedStorage\" }) do\n"
                 "\tlocal ok, service = pcall(function() return game:GetService(name) end)\n"
                 "\tif ok and service then table.insert(SERVICES, service) end\nend")
ORIGIN = (0, 30, 500)
DEFAULT_ITERATIONS, MAX_ITERATIONS = 3, 5
MAX_SCRIPTS, MAX_SCRIPT_CHARS = 3, 16000
# Server-only (brain 2): the robot and the specs live in the source checkout, not in the packaged app.
PLAYTEST_DIR = Path(__file__).resolve().parents[1] / "server" / "studio_lab" / "playtest"
SPECS_DIR = PLAYTEST_DIR / "specs"


def robot_source() -> str:
    return (PLAYTEST_DIR / "robot.luau").read_text(encoding="utf-8")
CHECKS = {"reach", "route", "blocked", "touch", "collect", "set_stat", "mark", "expect_stat", "expect_item",
          "expect_speed", "dies_on", "respawn_near", "near", "observe", "wait"}
# The brain's scripts run in a playtest of STAR Test Place: nothing that leaves the place or the session.
FORBIDDEN = [(re.compile(p), what) for p, what in (
    (r"\bHttpService\b", "HttpService"), (r"\bDataStoreService\b", "DataStoreService"),
    (r"\bMarketplaceService\b", "MarketplaceService"), (r"\bTeleportService\b", "TeleportService"),
    (r"\bInsertService\b", "InsertService"), (r"\bloadstring\b", "loadstring"), (r"\b[gs]etfenv\b", "getfenv/setfenv"),
    (r"\brequire\s*\(\s*\d", "require of an asset id"), (r"\bMessagingService\b", "MessagingService"))]
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}\Z")
_SPEC_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{0,39}\Z")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


_LUA_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _lua_string(text: str) -> str:
    """A Luau string literal for any text, in ASCII. Not json.dumps: JSON's \\u2019 is a compile error in Luau (it
    wants \\u{2019}); one curly quote in STAR's answer once broke the whole apply (live run 2026-10-16)."""
    out = []
    for char in text:
        code = ord(char)
        if char in _LUA_ESCAPES:
            out.append(_LUA_ESCAPES[char])
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\{code:03d}")
        elif code > 0x7E:
            out.append(f"\\u{{{code:x}}}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def switched_on() -> bool:
    return os.environ.get(SWITCH, "").strip() == "1"


# --------------------------------------------------------------------------- specs

def check_spec(spec) -> tuple[dict | None, list[str]]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return None, ["a game spec must be a JSON object"]
    unknown = sorted(set(spec) - {"name", "kind", "brief", "contract", "checks", "playSeconds", "maxIterations"})
    if unknown:
        problems.append("unknown keys: " + ", ".join(unknown))
    if not isinstance(spec.get("name"), str) or not _SPEC_NAME.fullmatch(spec["name"]):
        problems.append("name must be 1-40 letters/digits, starting with a letter")
    for key in ("kind", "brief"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            problems.append(f"{key} must be a non-empty string")
    contract = spec.get("contract")
    if not isinstance(contract, list) or not contract or not all(isinstance(x, str) and x.strip() for x in contract):
        problems.append("contract must be a list of sentences")
    checks = spec.get("checks")
    if not isinstance(checks, list) or not checks:
        problems.append("checks must be a non-empty list")
    else:
        for index, step in enumerate(checks, 1):
            if not isinstance(step, dict) or step.get("do") not in CHECKS:
                problems.append(f"check {index}: unknown 'do'")
    seconds = spec.get("playSeconds", 150)
    if not isinstance(seconds, (int, float)) or not 20 <= seconds <= 600:
        problems.append("playSeconds must be 20..600")
    iterations = spec.get("maxIterations", DEFAULT_ITERATIONS)
    if type(iterations) is not int or not 1 <= iterations <= MAX_ITERATIONS:
        problems.append(f"maxIterations must be 1..{MAX_ITERATIONS}")
    if problems:
        return None, problems
    return {**spec, "playSeconds": float(seconds), "maxIterations": iterations}, []


def load_specs(path: Path, only: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    files = sorted(Path(path).glob("*.json")) if Path(path).is_dir() else [Path(path)]
    good, bad = [], []
    for file in files:
        spec, problems = check_spec(json.loads(file.read_text(encoding="utf-8")))
        if spec is None:
            bad.append({"file": file.name, "problems": problems})
        elif not only or spec["name"] in only:
            good.append(spec)
    return good, bad


# --------------------------------------------------------------------------- the brain's side

SYSTEM = f"""You are STAR, building a small Roblox game that a robot player will playtest in Roblox Studio.
Write server Script code in Luau. Rules:
- Answer with 1 to {MAX_SCRIPTS} code blocks (```lua). The FIRST line of each block is `-- Script: <Name>` (letters and
  digits). Each block becomes a server Script inside one Folder; `script.Parent` is that Folder.
- The scripts run when the game starts and nothing else exists yet: first build the level from Parts
  (Instance.new, Anchored = true) parented inside script.Parent, then run the game logic.
- Build around ORIGIN = Vector3.new({ORIGIN[0]}, {ORIGIN[1]}, {ORIGIN[2]}) (the top of the start floor at y = {ORIGIN[1]});
  keep everything within 120 studs of ORIGIN.
- Players have the default character: WalkSpeed 16, JumpHeight 7.2 (safe jumps: at most about 7 studs across and
  6 studs up).
- Scores live in leaderstats (a Folder named "leaderstats" in the Player with IntValue children). Handle players who
  are already in the game when the script starts as well as Players.PlayerAdded.
- Not allowed: HttpService, DataStoreService, MarketplaceService, TeleportService, InsertService, MessagingService,
  loadstring, require of asset ids, getfenv/setfenv.
- Keep it short: at most 150 lines in total. No explanations outside the code blocks."""


def build_request(spec: dict) -> str:
    """The task text STAR gets (also the worked example's instruction)."""
    lines = [f"Game: {spec['brief']}", "", "The robot playtester checks exactly these things, so use these names:"]
    lines += [f"- {item}" for item in spec["contract"]]
    return "\n".join(lines)


def build_messages(spec: dict) -> list[dict]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": build_request(spec)}]


def fix_messages(spec: dict, answer: str, report: dict) -> list[dict]:
    return build_messages(spec) + [
        {"role": "assistant", "content": answer},
        {"role": "user", "content": "A robot played your game in Roblox Studio. What happened:\n" + describe(report)
         + "\n\nFix the game. Answer with the complete corrected scripts in the same format. After the code, write one "
           "line `LESSON: <one sentence a Roblox game developer should remember, general, not about this game>`."}]


# An answer cut off by the model still counts: its last block runs to the end (the playtest shows what breaks).
_BLOCK = re.compile(r"```[ \t]*(?:lua|luau)?[ \t]*\r?\n(.*?)(?:```|\Z)", re.S | re.I)
_HEADER = re.compile(r"^\s*--\s*Script:\s*([A-Za-z][A-Za-z0-9_]{0,39})\s*$")
_LESSON = re.compile(r"(?im)^\s*LESSON:\s*(.{10,300}?)\s*$")


def parse_answer(text: str) -> dict:
    """{scripts: [{name, source}], problems: [...], lesson: str|None} from the brain's answer."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text or "")
    scripts, problems, names = [], [], set()
    for index, block in enumerate(_BLOCK.findall(text), 1):
        lines = block.strip("\n").splitlines()
        header = _HEADER.match(lines[0]) if lines else None
        name = header.group(1) if header else f"Game{index}"
        if name in names or name == ROBOT_NAME:
            name = f"{name}{index}"
        names.add(name)
        source = "\n".join(lines).strip() + "\n"
        if len(source) > MAX_SCRIPT_CHARS:
            problems.append(f"script {name} is longer than {MAX_SCRIPT_CHARS} characters")
            continue
        scripts.append({"name": name, "source": source})
    if not scripts:
        problems.append("the answer has no ```lua code block")
    if len(scripts) > MAX_SCRIPTS:
        problems.append(f"more than {MAX_SCRIPTS} scripts; only the first {MAX_SCRIPTS} were used")
        scripts = scripts[:MAX_SCRIPTS]
    for script in scripts:
        for pattern, what in FORBIDDEN:
            if pattern.search(script["source"]):
                problems.append(f"script {script['name']} uses {what}, which is not allowed in the playtest")
    found = _LESSON.search(text)
    return {"scripts": scripts, "problems": problems, "lesson": found.group(1).strip() if found else None}


def render_scripts(scripts: list[dict]) -> str:
    return "\n\n".join(f"```lua\n{s['source'].rstrip()}\n```" for s in scripts)


class Brain:
    """STAR's model through the brain's OpenAI-compatible endpoint. Operator configuration only (environment):
    STAR_PLAYTEST_BRAIN_URL (or STAR_BRAIN_URL), STAR_PLAYTEST_KEY_FILE (default ~/.star/server_api_key),
    STAR_PLAYTEST_MODEL (default star-fast). The URL and key are never written into a report."""

    def __init__(self, url: str | None = None, *, key_file: str | None = None, model: str | None = None,
                 timeout: float = 900.0, max_tokens: int = 3000, opener=None, extra: dict | None = None):
        self.url = (url or os.environ.get("STAR_PLAYTEST_BRAIN_URL") or os.environ.get("STAR_BRAIN_URL") or "").rstrip("/")
        path = Path(key_file or os.environ.get("STAR_PLAYTEST_KEY_FILE") or Path.home() / ".star" / "server_api_key")
        try:
            self._key = path.read_text(encoding="utf-8").split()[0].strip()
        except (OSError, IndexError):
            self._key = ""
        self.model = model or os.environ.get("STAR_PLAYTEST_MODEL") or "star-fast"
        self.timeout, self.max_tokens = timeout, max_tokens
        self.extra = dict(extra or {})          # extra request fields, e.g. chat_template_kwargs (benchmark)
        import urllib.request
        self._open = opener or urllib.request.urlopen

    def __call__(self, messages: list[dict]) -> dict:
        import urllib.request
        from .background_cap import slot_for
        slot = slot_for(self.url, self._key, self.model, opener=self._open)   # background: never the chat's slot
        body = json.dumps({"model": self.model, "temperature": 0.3, "max_tokens": self.max_tokens,
                           "messages": messages, **self.extra,
                           **({"id_slot": slot} if slot is not None else {})}).encode()
        request = urllib.request.Request(self.url + "/v1/chat/completions", data=body, method="POST", headers={
            "Content-Type": "application/json", **({"Authorization": "Bearer " + self._key} if self._key else {})})
        started = time.monotonic()
        try:
            with self._open(request, timeout=self.timeout) as response:
                answer = json.loads(response.read().decode("utf-8"))
            text = answer["choices"][0]["message"]["content"] or ""
        except Exception as error:              # never echo the URL or the key
            return {"ok": False, "text": "", "error": type(error).__name__,
                    "seconds": round(time.monotonic() - started, 1)}
        usage = answer.get("usage") or {}
        return {"ok": True, "text": text, "seconds": round(time.monotonic() - started, 1), "model": self.model,
                "tokens": usage.get("completion_tokens"), "prompt_tokens": usage.get("prompt_tokens")}


# --------------------------------------------------------------------------- Studio side (Luau STAR writes itself)

def robot_config(spec: dict, run: str) -> dict:
    return {"run": run, "steps": spec["checks"], "startDelay": 4}


def apply_luau(spec: dict, scripts: list[dict], run: str) -> str:
    """Edit-mode Luau: replace Workspace/MapDrafts/Playtest with one folder holding STAR's scripts (as source text,
    never run here) and the robot. The caller sends it through GuardedStudio (one undo step)."""
    if not re.fullmatch(r"[0-9a-f]{8,32}", run) or not _SPEC_NAME.fullmatch(spec["name"]):
        raise ValueError("invalid run token or game name")
    lines = [
        "-- STAR playtest apply (scripts are stored, not run, in Edit mode)",
        "local function folder(parent, name)",
        "\tlocal found = parent:FindFirstChild(name)",
        "\tif found then return found end",
        '\tlocal made = Instance.new("Folder")',
        "\tmade.Name = name",
        "\tmade.Parent = parent",
        "\treturn made",
        "end",
        'local drafts = folder(workspace, "MapDrafts")',
        f"local tests = folder(drafts, {_lua_string(PLAYTEST_FOLDER)})",
        "local removed = #tests:GetChildren()",
        "tests:ClearAllChildren()",
        'local root = Instance.new("Folder")',
        f"root.Name = {_lua_string(spec['name'])}",
        f'root:SetAttribute("StarPlayRun", {_lua_string(run)})',
    ]
    for script in scripts:
        if not _NAME.fullmatch(script["name"]):
            raise ValueError("invalid script name")
        lines += ["do", '\tlocal s = Instance.new("Script")', f"\ts.Name = {_lua_string(script['name'])}",
                  f"\ts.Source = {_lua_string(script['source'])}", "\ts.Parent = root", "end"]
    lines += [
        'local robot = Instance.new("Script")',
        f"robot.Name = {_lua_string(ROBOT_NAME)}",
        f'robot:SetAttribute("StarPlayConfig", {_lua_string(canonical(robot_config(spec, run)))})',
        f"robot.Source = {_lua_string(robot_source())}",
        "robot.Parent = root",
        "-- The playtest tests STAR's game alone: pause every other script of the place (Studio Lab probes, the",
        "-- place's own systems) and mark it, so the cleanup switches exactly those back on.",
        SERVICES_LUAU,
        "local silenced = 0",
        "for _, service in ipairs(SERVICES) do",
        "\tfor _, other in ipairs(service:GetDescendants()) do",
        '\t\tif other:IsA("BaseScript") and other.Enabled and not other:IsDescendantOf(tests) then',
        "\t\t\tother.Enabled = false",
        f"\t\t\tother:SetAttribute({_lua_string(PAUSED)}, true)",
        "\t\t\tsilenced += 1",
        "\t\tend",
        "\tend",
        "end",
        "root.Parent = tests",
        f'return "{APPLY_MARK}" .. game:GetService("HttpService"):JSONEncode({{run = {_lua_string(run)}, '
        f"scripts = {len(scripts)}, removed = removed, silenced = silenced}})",
    ]
    return "\n".join(lines) + "\n"


def remove_luau() -> str:
    """Remove the playtest folder and switch the scripts the apply paused back on."""
    return ("-- STAR playtest cleanup\n" + SERVICES_LUAU + "\nlocal drafts = workspace:FindFirstChild(\"MapDrafts\")\n"
            f"local tests = drafts and drafts:FindFirstChild({_lua_string(PLAYTEST_FOLDER)})\n"
            "local n = 0\nif tests then n = #tests:GetChildren(); tests:Destroy() end\n"
            "local restored = 0\nfor _, service in ipairs(SERVICES) do\n\tfor _, item in ipairs(service:GetDescendants()) do\n"
            f"\t\tif item:IsA(\"BaseScript\") and item:GetAttribute({_lua_string(PAUSED)}) then\n"
            f"\t\t\titem:SetAttribute({_lua_string(PAUSED)}, nil)\n\t\t\titem.Enabled = true\n\t\t\trestored += 1\n"
            "\t\tend\n\tend\nend\n"
            f'return "{APPLY_MARK}" .. game:GetService("HttpService"):JSONEncode({{removed = n, restored = restored}})\n')


def marked_json(text: str, mark: str) -> dict | None:
    at = text.rfind(mark)
    if at < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[at + len(mark):].lstrip())
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def parse_robot(console: str, run: str) -> dict:
    lines = []
    for raw in console.splitlines():
        at = raw.find(MARK)
        if at < 0:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(raw[at + len(MARK):])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("run") == run:
            lines.append(value)
    checks = [line for line in lines if line.get("kind") == "check"]
    done = next((line for line in reversed(lines) if line.get("kind") == "done"), None)
    return {"started": any(line.get("kind") == "start" for line in lines), "finished": done is not None,
            "ok": bool(done and done.get("ok") is True), "problem": (done or {}).get("problem", ""), "checks": checks}


_ERROR = re.compile(r"(?i)\b(error|exception|attempt to|is not a valid member|expected|infinite yield|stack begin)\b")


def output_errors(console: str, run: str, game: str) -> dict:
    """Error lines after this run's robot started: the game's own (they name its folder), the robot's, others."""
    lines = console.splitlines()
    first = next((i for i, line in enumerate(lines) if MARK in line and f'"run":"{run}"' in line.replace(" ", "")), None)
    found: dict[str, list[str]] = {"game": [], "robot": [], "other": []}
    if first is None:
        return found
    folder = f"{PLAYTEST_FOLDER}.{game}."
    for line in lines[first:]:
        if MARK in line or not _ERROR.search(line):
            continue
        bucket = "robot" if ROBOT_NAME in line else "game" if folder in line else "other"
        if len(found[bucket]) < 20:
            found[bucket].append(line.strip()[:400])
    return found


def judge(robot: dict, errors: dict, static_problems: list[str]) -> dict:
    """The playtest report: pass only when the robot finished, every check passed and the game printed no error."""
    failures = []
    for problem in static_problems:
        failures.append({"code": "static", "why": problem})
    if not static_problems:
        if not robot["started"]:
            failures.append({"code": "robot-not-started", "why": "the robot never started (the playtest did not run)"})
        for check in robot["checks"]:
            if not check.get("ok"):
                failures.append({"code": "robot-error" if check.get("robot_error") else str(check.get("do")),
                                 "index": check.get("index"), "why": str(check.get("why", ""))[:500],
                                 "facts": check.get("facts")})
        if robot["started"] and not robot["finished"]:
            failures.append({"code": "robot-incomplete", "why": "the robot did not finish in the playtest time "
                             + (robot.get("problem") or "")})
        if errors.get("game"):
            failures.append({"code": "script-error", "why": "errors in the output: " + " | ".join(errors["game"][:4])})
    game_failures = [f for f in failures if f["code"] not in ("robot-error", "robot-not-started")]
    return {"passed": not failures, "failures": failures, "game_failures": len(game_failures),
            "checks_passed": sum(1 for c in robot["checks"] if c.get("ok")), "checks": len(robot["checks"])}


def _short_facts(facts) -> str:
    if not isinstance(facts, dict):
        return ""
    keep = {k: v for k, v in facts.items() if k in ("stuck", "legs", "found", "collected", "reached", "stat_before",
                                                    "stat_after", "tools", "value", "samples", "statuses", "distance",
                                                    "walk_speed", "position", "standing_on", "reason")}
    text = json.dumps(keep, separators=(",", ":"))
    return text if len(text) <= 600 else text[:600] + "..."


def describe(report: dict) -> str:
    """The failures in plain words for the fix task."""
    out = []
    for failure in report["failures"]:
        head = f"- FAILED ({failure['code']})" + (f" check {failure['index']}" if failure.get("index") is not None else "")
        out.append(f"{head}: {failure['why']}")
        facts = _short_facts(failure.get("facts"))
        if facts and facts != "{}":
            out.append(f"  facts: {facts}")
    passed = report.get("checks_passed", 0)
    if passed:
        out.append(f"- {passed} other check(s) passed.")
    return "\n".join(out) or "- no details"


# --------------------------------------------------------------------------- the loop for one game

class GameRun:
    """Drives one spec through build -> playtest -> fix -> re-playtest on an open GuardedStudio."""

    def __init__(self, guarded, brain: Callable[[list[dict]], dict], out: Path, *, log=print, sleep=asyncio.sleep,
                 poll: float = 2.0, settle: float = 20.0):
        self.guarded, self.brain, self.out = guarded, brain, Path(out)
        self.log, self.sleep, self.poll, self.settle = log, sleep, poll, settle

    async def _luau(self, code: str) -> tuple[bool, str]:
        from .studio_loop import EDIT_MARK, _marked_json, result_failed, result_text
        result = await self.guarded.call_tool("execute_luau", {"studio_id": self.guarded.studio_id,
                                                               "datamodel_type": "Edit", "code": code})
        entry = self.guarded.journal.entries[-1] if self.guarded.journal.entries else {}
        receipt = _marked_json(result_text(result), EDIT_MARK) or {}
        got = receipt.get("result")
        return (not result_failed(result) and entry.get("ok") is True), (got if isinstance(got, str) else result_text(result))

    async def _console(self) -> str:
        from .studio_loop import result_text
        return result_text(await self.guarded.call_tool("get_console_output", {"studio_id": self.guarded.studio_id}))

    async def apply(self, spec: dict, scripts: list[dict], run: str) -> dict:
        code = apply_luau(spec, scripts, run)
        for attempt in range(3):
            ok, text = await self._luau(code)
            # Right after a playtest Studio sometimes cannot say which place is open; GuardedStudio then refuses
            # only this change and sends nothing (live run 2026-10-16), so asking again a little later is safe.
            if ok or "could not confirm which place is open" not in text or attempt == 2:
                break
            await self.sleep(5 * (attempt + 1))
        receipt = marked_json(text, APPLY_MARK) or {}
        return {"ok": ok and receipt.get("run") == run, "scripts": receipt.get("scripts"),
                "detail": "" if ok else text[-300:]}

    async def remove(self) -> dict:
        ok, text = await self._luau(remove_luau())
        return {"ok": ok, **(marked_json(text, APPLY_MARK) or {})}

    async def playtest(self, spec: dict, run: str, folder: Path) -> dict:
        from .studio_loop import result_failed, result_text
        console, robot = "", parse_robot("", run)
        asked = time.monotonic()
        for attempt in range(3):        # same transient as in apply(): refused before anything was sent
            started = await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id,
                                                                       "is_start": True})
            if not result_failed(started) or "could not confirm which place is open" not in result_text(started):
                break
            await self.sleep(5 * (attempt + 1))
        if result_failed(started):
            return {"started": False, "stopped": True, "detail": result_text(started)[:300], "robot": robot,
                    "errors": {"game": [], "robot": [], "other": []}, "seconds": 0.0}
        began = time.monotonic()
        start_s, robot_s, stopped = round(began - asked, 1), None, None
        try:
            deadline = began + spec["playSeconds"]
            while time.monotonic() < deadline:
                await self.sleep(self.poll)
                console = await self._console()
                robot = parse_robot(console, run)
                if robot["started"] and robot_s is None:
                    robot_s = round(time.monotonic() - asked, 1)
                if robot["finished"] or (not robot["started"] and time.monotonic() - began > self.settle + 30):
                    break
            await self.sleep(min(self.poll, 1.0))            # late error lines after the robot's last check
            console = await self._console()
            robot = parse_robot(console, run)
        finally:
            stopped = await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id,
                                                                       "is_start": False})
        # Play start timing as data: slow starts (CPU shared with the night-school worker?) show up in the reports.
        self.log(f"play start: Studio confirmed in {start_s}s, robot up after {robot_s if robot_s is not None else 'never'}s")
        guard = getattr(self.guarded, "play_guard", None)
        edit = await guard.ensure_edit() if guard is not None else None      # stop said ok, is Studio really in Edit?
        errors = output_errors(console, run, spec["name"])
        at = console.find(MARK)
        (folder / "playtest-output.txt").write_text(console[console.rfind("\n", 0, at) + 1:] if at >= 0 else console[-4000:],
                                                    encoding="utf-8")
        return {"started": True, "stopped": not result_failed(stopped) and (edit is None or edit["edit"] is not False),
                "robot": robot, "errors": errors, "seconds": round(time.monotonic() - began, 1),
                "start_s": start_s, "robot_start_s": robot_s, "edit": edit}

    def _ask(self, messages: list[dict], folder: Path, label: str) -> dict:
        answer = self.brain(messages)
        (folder / f"{label}-answer.txt").write_text(answer.get("text", ""), encoding="utf-8")
        return answer

    async def run(self, spec: dict, *, run: str | None = None) -> dict:
        run = run or secrets.token_hex(4)
        self.out.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {"v": 1, "run": run, "game": spec["name"], "kind": spec["kind"],
                                  "request": build_request(spec), "started": _now(), "iterations": [],
                                  "passed": False, "first_pass": False}
        identity = getattr(getattr(self.guarded, "verdict", None), "identity", None)
        if identity is not None:
            report["place"] = {"place_id": identity.place_id, "universe_id": identity.game_id}
        messages = build_messages(spec)
        answer_text, parsed = "", {"scripts": [], "problems": [], "lesson": None}
        for index in range(1, spec["maxIterations"] + 1):
            folder = self.out / f"iteration-{index}"
            folder.mkdir(parents=True, exist_ok=True)
            step: dict[str, Any] = {"index": index, "task": "build" if index == 1 else "fix"}
            report["iterations"].append(step)
            from .discord_bot.native_evidence import emit
            emit("playtest-learning", report, self.out, phase="planning")
            if index > 1:
                messages = fix_messages(spec, answer_text, report["iterations"][-2]["report"])
            answer = await asyncio.to_thread(self._ask, messages, folder, step["task"])
            step["brain"] = {k: answer.get(k) for k in ("ok", "seconds", "tokens", "prompt_tokens", "model", "error")}
            if not answer.get("ok"):
                step["report"] = {"passed": False, "failures": [{"code": "brain-unavailable",
                                                                 "why": answer.get("error", "")}], "game_failures": 0}
                self.log(f"[{index}] brain call failed: {answer.get('error')}")
                break
            answer_text, parsed = answer["text"], parse_answer(answer["text"])
            step["build_sha256"] = digest(parsed["scripts"])
            step["scripts"] = [{"name": s["name"], "lines": s["source"].count("\n"), "sha256": digest(s["source"])[:16]}
                               for s in parsed["scripts"]]
            step["lesson"] = parsed["lesson"]
            for script in parsed["scripts"]:
                (folder / f"{script['name']}.luau").write_text(script["source"], encoding="utf-8")
            token = run + secrets.token_hex(2)
            step["token"] = token
            if parsed["problems"] or not parsed["scripts"]:
                step["playtest"] = None
                step["report"] = judge(parse_robot("", token), {}, parsed["problems"] or ["no scripts"])
            else:
                step["apply"] = await self.apply(spec, parsed["scripts"], token)
                self.log(f"[{index}] apply: {step['apply']}")
                if not step["apply"]["ok"]:
                    step["report"] = {"passed": False, "failures": [{"code": "apply-failed",
                                                                     "why": step["apply"]["detail"]}], "game_failures": 0}
                    report["studio_problem"] = True     # GuardedStudio refuses later edits until a person looks
                    break
                emit("playtest-learning", report, self.out, phase="playtesting")
                play = await self.playtest(spec, token, folder)
                step["playtest"] = {k: play.get(k) for k in ("started", "stopped", "seconds", "errors", "detail", "start_s",
                                                              "robot_start_s", "edit")}
                step["robot"] = play["robot"]
                step["report"] = judge(play["robot"], play["errors"], [])
                if not play["stopped"] or not play["started"]:
                    step["report"]["failures"].append({"code": "studio", "why": "the playtest start/stop was not confirmed"})
                    step["report"]["passed"] = False
                    report["studio_problem"] = True
                    break
            rep = step["report"]
            self.log(f"[{index}] {'PASSED' if rep['passed'] else 'failed'}: "
                     f"{[f['code'] for f in rep['failures']]} ({rep.get('checks_passed', 0)}/{rep.get('checks', 0)} checks)")
            (folder / "step.json").write_text(json.dumps(step, indent=1, default=str), encoding="utf-8")
            if rep["passed"]:
                report["passed"], report["first_pass"] = True, index == 1
                break
            if rep.get("game_failures", 0) == 0:        # only the robot or Studio failed: nothing for STAR to fix
                self.log(f"[{index}] stopping: the failure is not the game's")
                break
        report["final_scripts"] = parsed["scripts"] if report["passed"] else []
        report["finished"] = _now()
        report["lesson"] = lesson_record(report)
        (self.out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        from .discord_bot.native_evidence import emit
        emit("playtest-learning", report, self.out)
        return report


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- records for night school

def failed_codes(report: dict) -> list[str]:
    first = report["iterations"][0]["report"] if report.get("iterations") else {}
    return [f["code"] for f in first.get("failures", [])]


def lesson_record(report: dict) -> dict | None:
    """A lesson CANDIDATE from a game that failed its first real playtest and passed after STAR's own fix; the text
    is STAR's LESSON line from the fix that passed, the evidence is the before/after playtest."""
    iterations = report.get("iterations", [])
    if not report.get("passed") or len(iterations) < 2:
        return None
    text = iterations[-1].get("lesson")
    if not text:
        return None
    first = iterations[0]["report"]
    return {"id": f"playtest-{report['run']}", "kind": "pitfall", "text": text[:300],
            "source": "playtest-learning:" + report["run"], "source_type": "verified-fix", "reviewed": False,
            "evidence": {"game": report["game"], "run": report["run"], "place": report.get("place"),
                         "before": {"iteration": 1, "failed": [f["code"] for f in first.get("failures", [])],
                                    "why": [f["why"][:200] for f in first.get("failures", [])][:3]},
                         "after": {"iteration": iterations[-1]["index"],
                                   "checks": iterations[-1]["report"].get("checks"),
                                   "scripts": iterations[-1].get("scripts")}}}


def lesson_evidence_text(record: dict) -> str:
    e = record["evidence"]
    return (f"playtest-learning: real Roblox Studio playtest by STAR's robot player (game {e['game']}, run {e['run']}): "
            f"{', '.join(e['before']['failed'])} failed in iteration 1; after STAR's fix all {e['after']['checks']} "
            f"checks passed with no script errors in iteration {e['after']['iteration']}.")


def worked_example(report: dict) -> dict | None:
    """The app's worked-example row (star/worked_examples.validate_row) for a game whose final build passed."""
    if not report.get("passed") or not report.get("final_scripts"):
        return None
    last = report["iterations"][-1]
    group = "playtest-" + report["game"]
    row = {"id": "night-school-" + group, "group_id": group, "task_category": "roblox-game-playtested",
           "instruction": report["request"], "response": render_scripts(report["final_scripts"]),
           "evidence": [f"night-school automated checks: real Roblox Studio playtest by STAR's robot player, "
                        f"{last['report'].get('checks')} of {last['report'].get('checks')} checks passed, no script "
                        f"errors (run {report['run']}, iteration {last['index']}"
                        + (", after a failed first playtest)" if last["index"] > 1 else ", first try)")],
           "source": "night-school-verified", "reviewed": False, "rights_confirmed": False, "lessons_in_context": []}
    from .worked_examples import validate_row
    try:
        validate_row(row)
    except ValueError:
        return None
    return row


def write_outbox(outbox: Path, reports: list[dict]) -> dict:
    """Append this run's records; rewrite worked-examples.jsonl (newest passing build per game) and the lesson export."""
    from .lessons import LessonStore, write_export
    import tempfile
    outbox.mkdir(parents=True, exist_ok=True)
    with open(outbox / "playtest-verified.jsonl", "a", encoding="utf-8", newline="\n") as handle:
        for report in reports:
            handle.write(json.dumps({"game": report["game"], "run": report["run"], "finished": report.get("finished"),
                                     "first_pass": report.get("first_pass"), "passed": report.get("passed"),
                                     "iterations": len(report.get("iterations", [])),
                                     "first_failures": failed_codes(report), "lesson": report.get("lesson"),
                                     "example": worked_example(report)}, ensure_ascii=False) + "\n")
    rows: list[dict] = []
    for line in (outbox / "playtest-verified.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    examples = {row["example"]["group_id"]: row["example"] for row in rows if isinstance(row, dict) and row.get("example")}
    with open(outbox / "worked-examples.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(examples):
            handle.write(json.dumps(examples[key], ensure_ascii=False) + "\n")
    lessons = {row["lesson"]["id"]: row["lesson"] for row in rows if isinstance(row, dict) and row.get("lesson")}
    captured = 0
    with tempfile.TemporaryDirectory(prefix="playtest-outbox-") as folder:
        store = LessonStore(Path(folder))
        try:
            for record in lessons.values():
                result = store.capture_inferred(project="roblox", kind=record["kind"], text=record["text"],
                                                source_type="verified-fix", source=record["source"],
                                                evidence=lesson_evidence_text(record))
                captured += 1 if getattr(result, "status", "") != "refused" else 0
            data = store.export("roblox")
        finally:
            store.close()
    data["note"] = ("Written by STAR playtest learning. Every lesson is a CANDIDATE: STAR's own game failed a real "
                    "Roblox Studio playtest by the robot player, STAR fixed it and the re-playtest passed; no person "
                    "has reviewed it.")
    write_export(outbox / "star-lessons-playtest.json", data)
    return {"examples": len(examples), "lessons": captured}


# --------------------------------------------------------------------------- a suite (one Studio, sequential)

def summarize(reports: list[dict], wall: float) -> dict:
    ran = [r for r in reports if r.get("iterations")]
    failed_first = [r for r in ran if not r.get("first_pass")]
    fixable = [r for r in failed_first if r["iterations"][0]["report"].get("game_failures", 0) > 0]
    fixed = [r for r in fixable if r.get("passed")]
    codes: dict[str, int] = {}
    for report in fixable:
        for code in set(failed_codes(report)):
            codes[code] = codes.get(code, 0) + 1
    brain = [it.get("brain", {}).get("seconds") or 0 for r in ran for it in r["iterations"]]
    return {"games": len(reports), "ran": len(ran), "first_pass": sum(1 for r in ran if r.get("first_pass")),
            "failed_first": len(failed_first), "failed_first_game": len(fixable), "fixed": len(fixed),
            "fix_rate": round(len(fixed) / len(fixable), 3) if fixable else None,
            "passed_final": sum(1 for r in ran if r.get("passed")),
            "playtests": sum(1 for r in ran for it in r["iterations"] if (it.get("playtest") or {}).get("started")),
            "brain_calls": len(brain), "brain_seconds": round(sum(brain), 1),
            "first_failure_codes": dict(sorted(codes.items())),
            "lessons": sum(1 for r in ran if r.get("lesson")), "wall_seconds": round(wall, 1)}


async def run_suite(specs: list[dict], open_guarded, brain, out: Path, *, log=print, max_seconds: float | None = None,
                    run_kwargs=None, reopen: int = 2) -> dict:
    """open_guarded: async context manager yielding a GuardedStudio (or None with a problem). When Studio does not
    confirm a playtest start/stop, the guard refuses further edits: the suite then opens a fresh session (the opener
    takes Studio back to Edit mode on exit) and goes on with the next game, at most `reopen` times."""
    out.mkdir(parents=True, exist_ok=True)
    reports, started, queue = [], time.monotonic(), list(enumerate(specs, 1))
    sessions, last_facts = 0, {}
    while queue and sessions <= reopen:
        sessions += 1
        async with open_guarded() as (guarded, facts):
            last_facts = facts
            if guarded is None:
                if not reports:
                    return {"ok": False, "problem": (facts or {}).get("problem") or "no verified STAR test place",
                            "facts": facts}
                log("no verified Studio session to go on with")
                break
            # A run that stopped half-way may have left a playtest folder and paused place scripts: clean up first.
            await GameRun(guarded, brain, out, log=log).remove()
            while queue:
                if max_seconds and time.monotonic() - started > max_seconds:
                    log("runtime cap reached: no new game")
                    queue = []
                    break
                number, spec = queue.pop(0)
                log(f"== {spec['name']} ({number}/{len(specs)})")
                game = GameRun(guarded, brain, out / f"{number:02d}-{spec['name']}",
                               log=lambda t, name=spec["name"]: log(f"{name} {t}"), **(run_kwargs or {}))
                try:
                    report = await game.run(spec)
                except Exception as error:
                    report = {"game": spec["name"], "run": "", "iterations": [], "passed": False,
                              "problem": f"game run failed ({type(error).__name__}: {str(error)[:200]})"}
                    log(report["problem"])
                reports.append(report)
                try:
                    report["cleanup"] = await game.remove()
                except Exception as error:
                    report["cleanup"] = {"ok": False, "error": type(error).__name__}
                (out / "suite.json").write_text(json.dumps({"summary": summarize(reports, time.monotonic() - started),
                                                            "games": [_row(r) for r in reports]}, indent=1),
                                                encoding="utf-8")
                if report.get("studio_problem"):
                    log("Studio did not confirm a playtest start/stop: new session for the next game")
                    break
    summary = summarize(reports, time.monotonic() - started)
    summary["sessions"] = sessions
    suite = {"ok": True, "started_utc": _now(), "summary": summary, "facts": last_facts, "games": [_row(r) for r in reports]}
    (out / "suite.json").write_text(json.dumps(suite, indent=1, default=str), encoding="utf-8")
    suite["reports"] = reports
    return suite


def _row(report: dict) -> dict:
    its = report.get("iterations", [])
    return {"game": report.get("game"), "run": report.get("run"), "first_pass": report.get("first_pass"),
            "passed": report.get("passed"), "iterations": len(its),
            "per_iteration": [{"index": it["index"], "passed": it.get("report", {}).get("passed"),
                               "failures": [f["code"] for f in it.get("report", {}).get("failures", [])],
                               "checks": f"{it.get('report', {}).get('checks_passed', 0)}/{it.get('report', {}).get('checks', 0)}",
                               "brain_s": (it.get("brain") or {}).get("seconds"),
                               "play_s": (it.get("playtest") or {}).get("seconds"),
                               "start_s": (it.get("playtest") or {}).get("start_s")} for it in its],
            "lesson": (report.get("lesson") or {}).get("text"), "problem": report.get("problem", "")}


def studio_opener(home: Path):
    """The Studio Lab's multi-Studio connector (operator command in <home>/studio/lab-multi.json), first Studio."""
    import contextlib
    from . import studio, studio_lab_parallel as parallel

    @contextlib.asynccontextmanager
    async def open_guarded():
        command = parallel.multi_command(home)
        if not command:
            yield None, {"problem": "no Studio connector command configured"}
            return
        make: Any = parallel.connector(command)   # an async context manager factory (studio.connect)
        async with make() as session:
            try:
                listed = await parallel.list_instances(session, expect=1, seconds=60)
            except Exception as error:      # e.g. a connector with zero tools: Studio is signed out or not loaded
                listed = []
                problem = f"the Studio connector did not answer ({type(error).__name__})"
            else:
                problem = "no Studio attached to the connector"
            if not listed:
                yield None, {"problem": problem + ": is Studio running, signed in and on STAR Test Place?"}
                return
            discovered = await studio.list_tools(session)
            guarded, facts = await parallel.open_instance(session, discovered, listed[0]["id"], home=home,
                                                          own_account_id=parallel.configured_account(home))
            try:
                yield guarded, facts
            finally:
                if guarded is not None:
                    await leave_edit_mode(session, listed[0]["id"], facts)
    return open_guarded


async def leave_edit_mode(session, studio_id: str, facts: dict) -> None:
    """A playtest start that Studio reached only after the guard's deadline leaves STAR Test Place in Play, and every
    later session (the Studio Lab nightly too) then sees no Edit place (live run 2026-10-16). At the end of a run,
    stop such a playtest on the same verified instance (Stop on the display if the connector's stop does not take);
    it changes nothing in the place."""
    from .studio_play_fallback import play_guard
    try:
        ready = await play_guard(session, studio_id).ensure_edit(send_stop=True)
        if ready["method"] != "edit":
            facts["left_play_mode"] = ready
    except Exception as error:
        facts["left_play_mode"] = f"failed ({type(error).__name__})"


# --------------------------------------------------------------------------- CLI

def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description="STAR playtest learning: STAR builds games, a robot plays them")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check specs offline")
    check.add_argument("specs")
    generate = sub.add_parser("generate", help="brain only: STAR writes the games, no Studio (parse + static checks)")
    run = sub.add_parser("run", help="build, playtest, fix, re-playtest every spec in Studio")
    ideas = sub.add_parser("ideas", help="STAR invents new game specs into the idea ledger (needs STAR_PLAYTEST_IDEAS=1)")
    ideas.add_argument("specs", help="existing specs (for de-duplication)")
    ideas.add_argument("--ideas-dir", required=True)
    ideas.add_argument("--count", type=int, default=4)
    for command in (generate, run):
        command.add_argument("specs")
        command.add_argument("--out", required=True)
        command.add_argument("--only", default="", help="comma-separated game names")
    run.add_argument("--home", required=True, help="Studio Lab home with studio/lab-multi.json")
    run.add_argument("--outbox", default="", help="night-school outbox folder for examples and lesson candidates")
    run.add_argument("--max-minutes", type=float, default=0, help="no new game after this many minutes (0 = no cap)")
    run.add_argument("--ideas-dir", default="", help="idea ledger: play its build list first, record fun signals "
                                                     "(needs STAR_PLAYTEST_IDEAS=1)")
    chosen = parser.parse_args(arguments)
    only = {name for name in getattr(chosen, "only", "").split(",") if name}
    specs, bad = load_specs(Path(chosen.specs), only or None)
    if chosen.command == "check":
        print(json.dumps({"ok": not bad, "games": [s["name"] for s in specs], "invalid": bad}, indent=1))
        return 0 if not bad else 2
    if not switched_on():
        print(f"playtest learning is switched off (set {SWITCH}=1)")
        return 3
    log = lambda text: print(time.strftime("%H:%M:%S"), text, flush=True)   # noqa: E731
    out = Path(getattr(chosen, "out", ".")) / time.strftime("playtest-%Y%m%dT%H%M%SZ", time.gmtime())
    brain = Brain()
    if not brain.url:
        print("no brain URL (STAR_PLAYTEST_BRAIN_URL)")
        return 2
    from . import playtest_ideas
    ideas_on = bool(getattr(chosen, "ideas_dir", "")) and playtest_ideas.switched_on()
    if chosen.command == "ideas":
        if not ideas_on:
            print(f"game ideas are switched off (set {playtest_ideas.IDEAS_SWITCH}=1)")
            return 3
        result = playtest_ideas.invent(brain, Path(chosen.ideas_dir), specs, count=max(1, min(chosen.count, 8)), log=log)
        return 0 if result["ok"] else 1
    if ideas_on and chosen.command == "run":
        names = {s["name"] for s in specs}
        specs = [s for s in playtest_ideas.build_list(Path(chosen.ideas_dir)) if s["name"] not in names] + specs
    if chosen.command == "generate":
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for spec in specs:
            answer = brain(build_messages(spec))
            parsed = parse_answer(answer.get("text", ""))
            (out / f"{spec['name']}-answer.txt").write_text(answer.get("text", ""), encoding="utf-8")
            rows.append({"game": spec["name"], "ok": answer.get("ok"), "seconds": answer.get("seconds"),
                         "tokens": answer.get("tokens"), "scripts": [s["name"] for s in parsed["scripts"]],
                         "lines": sum(s["source"].count("\n") for s in parsed["scripts"]), "problems": parsed["problems"]})
            log(json.dumps(rows[-1]))
        (out / "generate.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
        return 0
    try:
        suite = asyncio.run(run_suite(specs, studio_opener(Path(chosen.home).expanduser()), brain, out, log=log,
                                      max_seconds=chosen.max_minutes * 60 or None))
    except Exception as error:          # the connector could not start (no Studio, Studio signed out, ...)
        suite = {"ok": False, "problem": f"Studio connection failed ({type(error).__name__})"}
    if chosen.outbox and suite.get("reports"):
        suite["outbox"] = write_outbox(Path(chosen.outbox), suite["reports"])
    if ideas_on and suite.get("reports"):
        suite["ideas_recorded"] = playtest_ideas.record_results(Path(chosen.ideas_dir), suite["reports"])
    print(json.dumps({k: v for k, v in suite.items() if k != "reports"}, indent=1, default=str))
    return 0 if suite.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
