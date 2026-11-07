"""Run an answer's Luau in the fake Roblox (mock.luau) and turn what happened into findings.

    report = run(answer_text, question, runner=default_runner())
    report["findings"]: [{"kind": "runtime" | "infinite-yield" | "property" | "hang", "block", "line", "message",
                          "phase"}], report["ran"]: bool, report["ms"]

The answer's blocks are placed the way their labels say (Script in ServerScriptService or in a part, LocalScript in
StarterPlayerScripts / a GUI button / the character, ModuleScripts bound to require calls), then a fixed scenario runs
in virtual time: a player joins, touches every part with a Touched handler (5 quick touches), triggers prompts and
click detectors, clicks GUI buttons, presses E/F/Space/Shift/Q, uses tools, 6 s of Heartbeat, a cheating client fires
every server remote with huge amounts, the player leaves, the server closes. Property checks (props.py) read the
observations. The Luau runtime is the official `luau` CLI (no file, network or OS access; Luau has no io/os.execute)
or Lune for local runs; a process timeout catches code that never yields.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..rules import scan
from . import props

HERE = Path(__file__).resolve().parent
MOCK = HERE / "mock.luau"
MARK = "@@SANDBOX@@"

CLIENT_HINT = re.compile(r"\bLocalPlayer\b|UserInputService|ContextActionService|RenderStepped|PlayerGui|"
                         r"MouseButton1Click|\.Activated\b|\bTextLabel\b|\bTextButton\b|"
                         r"\bGetMouse\b|CurrentCamera|StarterGui:SetCore", re.I)
SERVER_HINT = re.compile(r"PlayerAdded|DataStoreService|OnServerEvent|ServerStorage|ServerScriptService|"
                         r"OnServerInvoke|BindToClose|ProcessReceipt|\.Touched\b|Triggered|MouseClick", re.I)


def members_luau(index: dict) -> str:
    """`local MEMBERS = {...}`: per class "Super|name:k,..." ("|!" = not creatable with Instance.new)."""
    out = ["local MEMBERS = {"]
    for name, c in index.get("classes", {}).items():
        tags = c.get("tags") or []
        sup = c.get("super") or ""
        if sup == "<<<ROOT>>>":
            sup = ""
        flag = "!" if ("NotCreatable" in tags or "Service" in tags) else ""
        mem = ",".join(f"{m}:{v.get('k', '?')}" for m, v in (c.get("members") or {}).items()
                       if re.fullmatch(r"[A-Za-z_]\w*", m))
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            continue
        out.append(f'["{name}"]="{sup}|{flag}{mem}",')
    out.append("}")
    return "\n".join(out)


def _long(s: str) -> str:
    n = 1
    while f"]{'=' * n}]" in s:
        n += 1
    return f"[{'=' * n}[\n{s}]{'=' * n}]"


def _part_name(label: str) -> str | None:
    m = re.search(r"\b(?:inside|in|into|under)\s+(?:the|your|a|an|each|that|this)?\s*\*{0,2}([A-Z]?[A-Za-z]+)", label)
    if not m:
        return None
    w = m.group(1)
    if w.lower() in {"workspace", "serverscriptservice", "it", "part", "script", "studio", "explorer"}:
        return None
    return w[:1].upper() + w[1:]


def plan_blocks(text: str) -> list[dict]:
    """The answer's runnable Luau blocks with kind (server/local/module) and where they go."""
    ans = scan.parse(text)
    out = []
    for b in ans.luau:
        code = b.code
        if len(code.strip()) < 15:
            continue
        kind, place = b.kind, b.place
        if kind == "either":
            continue                      # one block showing several scripts (a comparison or demo)
        if kind == "" and b.start:
            # the label line was long: read the paragraph before the block (without the fence line)
            para = re.sub(r"\n[ \t]*(`{3,}|~{3,})[^\n]*\n?$", "", text[max(0, b.start - 420):b.start]).strip()
            k2, p2 = scan.classify_label(para)
            if k2 in ("local", "server", "module"):
                kind, place = k2, place or p2
                b.label = (b.label or "") + " " + para.split("\n")[-1][:300]
        if kind == "":
            kind = "local" if CLIENT_HINT.search(code) and not SERVER_HINT.search(code) else "server"
            if re.fullmatch(r"\s*return\s+\w+\s*", code.strip().split("\n")[-1]) and \
                    re.search(r"^local\s+\w+\s*=\s*\{", code, re.M):
                kind = "module"
        if kind == "local" and place == "world":
            continue                      # a LocalScript in Workspace never runs (the rules report it)
        label = b.label or ""
        uses_parent = bool(re.search(r"\bscript\.Parent\b", code))
        if kind == "server" and not place and uses_parent:
            place = "world"               # "put this Script in the part": the label did not say where
        d = {"index": b.index + 1, "src": code, "kind": kind, "place": place, "label": label,
             "part": _part_name(label)}
        if kind == "local":
            if re.search(r"text ?button|image ?button|\bbutton\b", label, re.I):
                d["gui"] = "button"
            elif re.search(r"screengui|\bframe\b|\bgui\b|textlabel|starter ?gui", label, re.I):
                d["gui"] = "gui"
            if re.search(r"startercharacterscripts", label, re.I):
                d["where"] = "character"
            elif not d.get("gui") and not place and uses_parent and not re.search(
                    r"script\.Parent\s*[:.]\s*(WaitForChild\(\s*[\"']Humanoid|Humanoid\b)", code):
                d["gui"] = "element"      # a LocalScript that uses script.Parent: a GUI object it was put in
        out.append(d)
    helper = leaderstats_helper(out)
    if helper:
        out.insert(0, helper)
    return out


NOT_STATS = {"Value", "Parent", "Name", "Humanoid", "HumanoidRootPart", "Head", "PlayerGui", "Backpack", "Character",
             "leaderstats", "Torso", "UpperTorso", "Animator", "ProximityPrompt", "ClickDetector", "Handle"}
LS_NAME = re.compile(r"""Name\s*=\s*["']leaderstats["']""")
LS_STAT = re.compile(r"""leaderstats\s*(?:\.\s*|:\s*(?:WaitForChild|FindFirstChild)\(\s*["'])(\w+)""")


def leaderstats_helper(blocks: list[dict]) -> dict | None:
    """The answer uses player.leaderstats made by "your leaderstats script": add that script (block 0, never
    reported) so the rest of the answer can run."""
    code = "\n".join(b["src"] for b in blocks)
    if "leaderstats" not in code or LS_NAME.search(code):
        return None
    found = LS_STAT.findall(code) + re.findall(r"""(?:FindFirstChild|WaitForChild)\(\s*["']([A-Z]\w*)["']\s*\)""", code) + \
        re.findall(r"\.([A-Z]\w*)\.Value\b", code)
    names = [n for n in dict.fromkeys(found) if n not in NOT_STATS][:4] or ["Coins"]
    src = ('local Players = game:GetService("Players")\n'
           'Players.PlayerAdded:Connect(function(p)\n'
           '\tlocal ls = Instance.new("Folder")\n'
           '\tls.Name = "leaderstats"\n'
           '\tfor _, n in ipairs({' + ", ".join(json.dumps(n) for n in names) + '}) do\n'
           '\t\tlocal v = Instance.new("IntValue")\n'
           '\t\tv.Name = n\n'
           '\t\tv.Parent = ls\n'
           '\tend\n'
           '\tls.Parent = p\n'
           'end)\n')
    return {"index": 0, "src": src, "kind": "server", "place": "sss", "label": "helper", "part": None}


def _blocks_luau(blocks: list[dict]) -> str:
    parts = []
    for b in blocks:
        fields = [f"index = {b['index']}", f"src = {_long(b['src'])}", f"kind = {json.dumps(b['kind'])}",
                  f"place = {json.dumps(b['place'])}", f"label = {_long(b['label'][:300])}"]
        for k in ("part", "gui", "where"):
            if b.get(k):
                fields.append(f"{k} = {json.dumps(b[k])}")
        parts.append("{" + ", ".join(fields) + "}")
    return "{\n" + ",\n".join(parts) + "\n}"


SCENARIO = r"""
local SC, PR = MOCK.SC, MOCK.PR
local OBS = {}
SC.set_ds_fail(%(ds_fail)s)
SC.load(BLOCKS)
local p = SC.join("Player1", 1001)
SC.heartbeat(1)
OBS.stats_join = PR.stats(p)
OBS.total_join = PR.total_stats(p)
local parts0 = PR.snapshot_parts()
local h0 = PR.health(p)
OBS.touch_parts = SC.touch_all(p, 5, 0.04)
OBS.total_touch = PR.total_stats(p)
OBS.parts_changed_touch = PR.changed_parts(parts0)
OBS.health_touch = PR.health(p)
OBS.died_touch = PR.died()
SC.advance(1)
OBS.parts_changed_touch_1s = PR.changed_parts(parts0)
SC.advance(2)
OBS.parts_changed_touch_1s = math.max(OBS.parts_changed_touch_1s, PR.changed_parts(parts0))
OBS.total_touch_1s = PR.total_stats(p)
OBS.died_touch = OBS.died_touch or PR.died()
SC.advance(%(wait_s)s)
OBS.parts_changed_after_wait = PR.changed_parts(parts0)
OBS.total_after_wait = PR.total_stats(p)
local parts1 = PR.snapshot_parts()
OBS.prompts = SC.trigger_prompts(p)
SC.advance(1)
OBS.parts_changed_prompt = PR.changed_parts(parts1)
OBS.total_prompt = PR.total_stats(p)
SC.advance(2)
OBS.parts_changed_prompt = math.max(OBS.parts_changed_prompt, PR.changed_parts(parts1))
SC.advance(%(wait_s)s)
OBS.parts_changed_prompt_wait = PR.changed_parts(parts1)
OBS.gui = SC.click_gui(p)
OBS.keys = SC.keys({"E", "F", "Space", "LeftShift", "Q", "R"})
OBS.tools = SC.tools(p)
OBS.total_actions = PR.total_stats(p)
SC.heartbeat(6)
OBS.total_hb = PR.total_stats(p)
OBS.evil = SC.evil_remotes(p)
OBS.total_evil = PR.total_stats(p)
SC.leave(p)
SC.close()
MOCK.event("obs", OBS)
MOCK.finish()
"""


class Runner:
    """Runs a Luau file: the official `luau` CLI (server) or Lune (`lune run`, local)."""

    def __init__(self, exe: str | None = None, timeout_s: float = 4.0):
        self.exe = exe or os.environ.get("STAR_SANDBOX_LUAU") or shutil.which("luau") or ""
        self.timeout_s = timeout_s

    @property
    def available(self) -> bool:
        return bool(self.exe) and Path(self.exe).exists() if os.path.isabs(self.exe or "") else bool(self.exe)

    def __call__(self, source: str) -> tuple[str, bool]:
        with tempfile.TemporaryDirectory(prefix="star-sb-") as d:
            f = Path(d) / "run.luau"
            f.write_text(source, encoding="utf-8")
            cmd = [self.exe, "run", str(f)] if Path(self.exe).stem.lower() == "lune" else [self.exe, str(f)]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s, cwd=d,
                                   encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                return "", True
            return (p.stdout or "") + "\n" + (p.stderr or ""), False


_MEMBERS_CACHE: dict[str, str] = {}


def load_members(index_path: str | Path) -> str:
    key = str(index_path)
    if key not in _MEMBERS_CACHE:
        _MEMBERS_CACHE[key] = members_luau(json.loads(Path(index_path).read_text(encoding="utf-8")))
    return _MEMBERS_CACHE[key]


def build(blocks: list[dict], members: str, ds_fail: bool = False, wait_s: float = 4.0) -> str:
    mock = MOCK.read_text(encoding="utf-8")
    return "\n".join([
        members,
        "local MOCK = (function()\n" + mock + "\nend)()",
        "local BLOCKS = " + _blocks_luau(blocks),
        SCENARIO % {"ds_fail": "true" if ds_fail else "false", "wait_s": wait_s},
    ])


LOC = re.compile(r"blk(\d+)\]?:(\d+):\s*")


def _where(msg: str, tb: str) -> tuple[int | None, int | None]:
    m = LOC.search(msg) or LOC.search(tb or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


IGNORE = re.compile(r"\[mock\]|attempt to (?:compare|perform arithmetic on|concatenate)[^\n]*\btable\b|stub", re.I)


def parse_output(out: str) -> dict | None:
    for line in out.splitlines():
        if line.startswith(MARK):
            try:
                return json.loads(line[len(MARK):])
            except ValueError:
                return None
    return None


def findings_of(raw: dict, blocks: list[dict]) -> list[dict]:
    """Runtime errors and infinite yields that point at the answer's own code."""
    frag = {int(k): v for k, v in (raw.get("fragment") or {}).items()}
    known = {b["index"] for b in blocks}
    out, seen = [], set()
    for e in raw.get("errors") or []:
        msg = e.get("msg") or ""
        blk, line = _where(msg, e.get("tb") or "")
        if blk is None:
            blk = e.get("block")
        if blk not in known or IGNORE.search(msg):
            continue
        first = re.search(r"([\w.\/:-]+?):(\d+):", msg.replace("runtime error: ", ""))
        if first and not first.group(1).endswith(("blk%d" % blk, "blk%d]" % blk)) and "blk" not in first.group(1):
            continue                       # raised inside the mock itself: a limit of the fake, not the answer
        if e.get("phase") == "compile":
            continue                       # syntax is luau-analyze's job (the verifier)
        clean = LOC.sub("", msg).replace("runtime error: ", "").strip()
        clean = re.sub(r"\s*stack traceback:.*", "", clean, flags=re.S)
        if frag.get(blk) and re.search(r"attempt to (index|call) nil", clean):
            continue                       # a snippet that uses a variable defined elsewhere in the answer
        key = (blk, line, clean[:80])
        if key in seen:
            continue
        seen.add(key)
        if e.get("phase") == "evil":
            clean = (f"{clean} (when a cheating client fired the RemoteEvent with unexpected values: check every "
                     f"value from the client with typeof() and limits before using it)")
        out.append({"kind": "runtime", "block": blk, "line": line, "phase": e.get("phase"), "ctx": e.get("ctx"),
                    "message": clean[:300]})
    for w in raw.get("warns") or []:
        blk = w.get("block")
        if blk not in known:
            continue
        key = (blk, "yield", w.get("msg"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": "infinite-yield", "block": blk, "line": None, "phase": w.get("phase"),
                    "message": w.get("msg", "")[:240]})
    return out


def obs_of(raw: dict) -> dict:
    for e in raw.get("events") or []:
        if e.get("kind") == "obs":
            return e
    return {}


def run(text: str, question: str = "", runner: Runner | None = None, members: str | None = None,
        index_path: str | Path | None = None) -> dict:
    t0 = time.monotonic()
    blocks = plan_blocks(text)
    rep: dict = {"ran": False, "findings": [], "blocks": len(blocks)}
    if not blocks:
        rep["why"] = "no runnable Luau"
        return rep
    runner = runner or Runner()
    if not runner.exe:
        rep["why"] = "no luau runtime"
        return rep
    members = members if members is not None else load_members(index_path)
    wait_s = props.wait_seconds(question)
    out, timed_out = runner(build(blocks, members, False, wait_s))
    rep["ran"] = True
    if timed_out:
        rep["findings"] = [{"kind": "hang", "block": None, "line": None, "phase": "?",
                            "message": "the game froze: a loop never yields (add task.wait inside every loop that runs forever)"}]
        rep["ms"] = round((time.monotonic() - t0) * 1000)
        return rep
    raw = parse_output(out)
    if raw is None:
        rep["ran"] = False
        rep["why"] = "no report: " + out.strip()[-300:]
        rep["ms"] = round((time.monotonic() - t0) * 1000)
        return rep
    rep["findings"] = findings_of(raw, blocks)
    obs = obs_of(raw)
    rep["obs"] = {k: v for k, v in obs.items() if k not in ("kind", "t", "phase")}
    rep["events"] = [e for e in raw.get("events") or [] if e.get("kind") != "obs"][:60]
    rep["writes"] = raw.get("writes") or []
    rep["unmodelled"] = raw.get("unmodelled") or {}
    rep["findings"] += props.check(question, text, rep)
    if props.wants_ds_fail(question, text, rep):
        out2, to2 = runner(build(blocks, members, True, wait_s))
        raw2 = parse_output(out2) if not to2 else None
        if raw2 is not None:
            rep["findings"] += props.check_ds_fail(raw2)
    rep["ms"] = round((time.monotonic() - t0) * 1000)
    return rep
