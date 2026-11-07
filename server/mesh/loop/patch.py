"""Hidden tool loop for Roblox code: the verifier (luau-analyze + the Roblox API dump) checks the draft, then
1. exact rewrites that need no model (deprecated globals with a 1:1 replacement, :connect, a case slip on the same
   member, the "leaderstats" folder name), then
2. one short model call that answers with changed LINES only ("12: <new line>"), with the verifier's problems,
   suggestions and the class's real members (the API lookup) in the prompt, bounded by a time budget.
An edit is kept only when the block's (errors, warnings) go down, like the verifier's own fix loop.

    text, info = await run(text, report, verify, call_model, budget_s=1.5)
        verify(text) -> report (awaitable);  call_model(body) -> reply text (awaitable, raises on failure)
"""
from __future__ import annotations

import asyncio
import re
import time

FENCE = re.compile(r"^(?P<ind>[ \t]{0,3})(?P<f>`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n(?P<code>.*?)^(?P=ind)(?P=f)[ \t]*$",
                   re.M | re.S)
DEPRECATED_GLOBALS = {"wait": "task.wait", "spawn": "task.spawn", "delay": "task.delay", "Game": "game",
                      "Workspace": "workspace", "ypcall": "pcall"}
PATCH_LINE = re.compile(r"^\s*(?:line\s*)?(\d+)\s*[:|]\s?(.*)$", re.I)

PATCH_SYSTEM = (
    "You fix Roblox Luau code. You get the code with line numbers and the problems a checker found (it knows every "
    "real Roblox API). Fix only those problems. When a problem gives a suggestion, use it; when it lists the real "
    "members, use the one the code means (it may belong to another object, like a service). Never invent an API. "
    "Reply ONLY with the changed lines, one per line, as `<line number>: <the whole new line>`. To remove a line "
    "write `<line number>:` with nothing after it. No other text.")


def _bad(problems: list[dict]) -> tuple[int, int]:
    return (sum(p.get("severity") == "error" for p in problems), sum(p.get("severity") == "warning" for p in problems))


def blocks(text: str) -> list[dict]:
    return [{"start": m.start("code"), "end": m.end("code"), "code": m.group("code")} for m in FENCE.finditer(text)]


def _sub_line(code: str, line: int, pattern: str, repl: str) -> str:
    lines = code.split("\n")
    if not 1 <= line <= len(lines):
        return code
    lines[line - 1] = re.sub(pattern, lambda _m: repl, lines[line - 1])
    return "\n".join(lines)


def exact_fix(code: str, problems: list[dict]) -> str:
    """Rewrites with exactly one right answer; anything else is left for the model."""
    for p in problems:
        name, sugg, line = p.get("name") or "", p.get("suggestion") or "", p.get("line") or 0
        if not line or p.get("severity") == "info":
            continue
        if p.get("kind") == "deprecated" and name in DEPRECATED_GLOBALS:
            code = _sub_line(code, line, rf"(?<![\w.:]){re.escape(name)}\b", DEPRECATED_GLOBALS[name])
        elif p.get("kind") == "deprecated" and re.fullmatch(r"\w+:(connect|connectParallel)", name):
            meth = name.split(":")[1]
            code = _sub_line(code, line, rf":{meth}\s*\(", ":" + meth[0].upper() + meth[1:] + "(")
        elif p.get("kind") == "roblox_rule" and name and name.lower() == "leaderstats":
            code = _sub_line(code, line, rf"([\"']){re.escape(name)}\1", '"leaderstats"')
        elif p.get("kind") in ("deprecated", "unknown_api") and re.fullmatch(r"\w+[.:]\w+", name) and \
                re.fullmatch(r"\w+[.:]\w+", sugg):
            cls, sep, member = re.split(r"([.:])", name)
            scls, ssep, smember = re.split(r"([.:])", sugg)
            if scls == cls and ssep == sep and smember != member and (
                    p.get("kind") == "deprecated" or smember.lower() == member.lower()):
                code = _sub_line(code, line, rf"{re.escape(sep)}{re.escape(member)}\b", sep + smember)
    return code


# instance methods that are never plain functions on a table, so `x.Play(` is always a slip for `x:Play(`
METHODS = ("Play|Stop|Pause|Resume|Destroy|Clone|FireServer|FireClient|FireAllClients|InvokeServer|Connect|Once|"
           "WaitForChild|FindFirstChild|FindFirstChildOfClass|FindFirstChildWhichIsA|GetChildren|GetDescendants|IsA|"
           "Kick|LoadAnimation|TakeDamage|MoveTo|GetPlayerFromCharacter|GetService|SetAsync|GetAsync|UpdateAsync|"
           "IncrementAsync|RemoveAsync|GetDataStore|ApplyImpulse|PivotTo|GetPivot|GetPlayers")
LIBS = {"math", "string", "table", "task", "Instance", "Vector3", "Vector2", "CFrame", "Color3", "UDim2", "UDim",
        "TweenInfo", "Enum", "os", "coroutine", "utf8", "bit32", "Random", "debug", "buffer", "DateTime", "BrickColor",
        "NumberSequence", "ColorSequence", "NumberRange", "RaycastParams", "OverlapParams", "Ray", "Region3", "Rect"}
DOT_CALL = re.compile(rf"(?<![\w.:])([A-Za-z_]\w*)\.({METHODS})\(")


def dot_calls(text: str, report: dict) -> str:
    """`x.Play(` -> `x:Play(` in the report's Luau blocks (libraries like math/task/Instance are left alone)."""
    spans = blocks(text)
    luau = {b["index"] for b in report.get("blocks") or [] if b.get("language") == "luau"}
    if len(spans) != len(report.get("blocks") or []):
        return text
    for k in sorted(luau, key=lambda k: -spans[k]["start"]):
        s = spans[k]
        code = DOT_CALL.sub(lambda m: m.group(0) if m.group(1) in LIBS else f"{m.group(1)}:{m.group(2)}(", s["code"])
        text = text[:s["start"]] + code + text[s["end"]:]
    return text


def patch_messages(code: str, problems: list[dict]) -> list[dict]:
    numbered = "\n".join(f"{i:>3}: {ln}" for i, ln in enumerate(code.rstrip("\n").split("\n"), 1))
    lines = []
    for p in problems:
        if p.get("severity") == "info":
            continue
        s = f"- line {p['line']}: {p['message']}" if p.get("line") else f"- {p['message']}"
        if p.get("suggestion"):
            s += f" (use: {p['suggestion']})"
        if p.get("candidates"):
            s += f"\n  real members: {', '.join(p['candidates'][:40])}"
        lines.append(s)
    return [{"role": "system", "content": PATCH_SYSTEM},
            {"role": "user", "content": f"Code:\n{numbered}\n\nProblems:\n" + "\n".join(lines)}]


def apply_patch(code: str, reply: str) -> str:
    lines = code.split("\n")
    changes = {}
    for raw in (reply or "").replace("```lua", "").replace("```", "").split("\n"):
        m = PATCH_LINE.match(raw)
        if m and 1 <= int(m.group(1)) <= len(lines):
            changes[int(m.group(1))] = m.group(2).rstrip()
    if not changes:
        return code
    out = []
    for i, ln in enumerate(lines, 1):
        if i not in changes:
            out.append(ln)
        elif changes[i].strip():
            indent = re.match(r"[ \t]*", ln).group(0)
            new = changes[i]
            out.append(new if new[:1] in (" ", "\t") else indent + new.lstrip())
    return "\n".join(out)


def _luau_blocks(report: dict) -> list[dict]:
    return [b for b in report.get("blocks") or [] if b.get("language") == "luau" and b.get("needs_fix")]


async def run(text: str, report: dict, verify, call_model, budget_s: float = 1.5) -> tuple[str, dict]:
    """Repair the Luau blocks that need it. Returns (text, info); text is unchanged when nothing got better."""
    t0 = time.monotonic()
    info = {"exact": 0, "model": 0, "rejected": 0, "timeout": False, "model_ms": 0}
    fixed = dot_calls(text, report)          # `music.Play()` on an untyped child: the verifier cannot see it
    if fixed != text:
        rep2 = await verify(fixed)
        if rep2 is not None and _total(rep2) <= _total(report):
            info["dot_calls"] = 1
            text, report = fixed, rep2
    todo = _luau_blocks(report)
    if not todo:
        return text, info
    spans = blocks(text)
    if len(spans) != len(report.get("blocks") or []):
        info["skipped"] = "block layout differs from the report"
        return text, info
    # 1. exact rewrites (no model)
    new_text = text
    for b in sorted(todo, key=lambda b: -spans[b["index"]]["start"]):
        s = spans[b["index"]]
        fixed = exact_fix(s["code"], b["problems"])
        if fixed != s["code"]:
            new_text = new_text[:s["start"]] + fixed + new_text[s["end"]:]
    if new_text != text:
        rep2 = await verify(new_text)
        if rep2 is not None and _total(rep2) < _total(report):
            info["exact"] = sum(1 for _ in todo)
            text, report = new_text, rep2
    # 2. one short line-patch call per remaining block, inside the budget
    todo = _luau_blocks(report)
    spans = blocks(text)
    if not todo or len(spans) != len(report.get("blocks") or []):
        return text, info
    left = budget_s - (time.monotonic() - t0)
    if left <= 0.2:
        info["timeout"] = True
        return text, info
    t1 = time.monotonic()

    async def one(b):
        s = spans[b["index"]]
        reply = await call_model({"messages": patch_messages(s["code"], b["problems"]), "max_tokens": 160,
                                  "temperature": 0.0, "stream": False,
                                  "chat_template_kwargs": {"enable_thinking": False}})
        return b, s, apply_patch(s["code"], reply)
    try:
        results = await asyncio.wait_for(asyncio.gather(*(one(b) for b in todo)), left)
    except asyncio.TimeoutError:
        info["timeout"] = True
        return text, info
    except Exception as e:                       # model down: keep the draft
        info["error"] = f"{type(e).__name__}"
        return text, info
    finally:
        info["model_ms"] = round((time.monotonic() - t1) * 1000)
    new_text = text
    for b, s, code in sorted(results, key=lambda r: -r[1]["start"]):
        if code != s["code"]:
            new_text = new_text[:s["start"]] + code + new_text[s["end"]:]
    if new_text == text:
        return text, info
    rep2 = await verify(new_text)
    if rep2 is None:
        return text, info
    kept = text
    for b in todo:                               # keep each block's edit only when that block got better
        after = rep2["blocks"][b["index"]] if b["index"] < len(rep2.get("blocks") or []) else None
        if after is not None and _bad(after.get("problems") or []) < _bad(b["problems"]):
            info["model"] += 1
        else:
            info["rejected"] += 1
    if info["model"] and not info["rejected"]:
        kept = new_text
    elif info["model"]:                          # mixed: apply only the improving blocks
        kept_text = text
        for b, s, code in sorted(results, key=lambda r: -r[1]["start"]):
            after = rep2["blocks"][b["index"]]
            if _bad(after.get("problems") or []) < _bad(b["problems"]):
                kept_text = kept_text[:s["start"]] + code + kept_text[s["end"]:]
        kept = kept_text
    return kept, info


def _total(report: dict) -> tuple[int, int]:
    probs = [p for b in report.get("blocks") or [] for p in b.get("problems") or []]
    return _bad(probs)
