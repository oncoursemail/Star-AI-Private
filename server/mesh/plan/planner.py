"""Plan-then-code for big Roblox tasks (inventory, round system, shop with DataStore ...): a short structured plan
(files, remotes, server authority, data schema) is written first and checked by fixed rules, then each file is written
with the plan in view, then the parts are put together as one answer in Litha's format.

    answer, info = await build(task, call_model, system_prompt)
        call_model(body) -> {"text", "finish"} (awaitable); body is an OpenAI chat body without "model"
"""
from __future__ import annotations

import json
import re
import time

PLAN_SYS = (
    "You plan a Roblox game system before any code is written. Reply with ONLY one JSON object, no prose:\n"
    '{"summary": "<one sentence>", "setup": ["<thing to create in Studio, e.g. a RemoteEvent named BuyItem in '
    'ReplicatedStorage>"], "files": [{"name": "<ScriptName>", "type": "Script|LocalScript|ModuleScript", "location": '
    '"<exact place, e.g. ServerScriptService, StarterPlayerScripts, StarterGui.ShopGui, ReplicatedStorage>", "does": '
    '"<what it does>"}], "remotes": [{"name": "<Name>", "kind": "RemoteEvent|RemoteFunction", "from": "client|server", '
    '"args": ["<arg>"], "server_checks": ["<what the server checks before acting>"]}], "data": {"store": "<DataStore name '
    'or empty>", "key": "<e.g. Player_<UserId>>", "value": "<fields>", "save_when": ["PlayerRemoving", "BindToClose"]}, '
    '"authority": ["<rules: the server owns coins, prices, inventory; the client only asks>"]}\n'
    "Rules: Scripts run on the server (ServerScriptService or inside a part); LocalScripts run on the client "
    "(StarterPlayerScripts, StarterGui, StarterCharacterScripts, a Tool); ModuleScripts hold shared code or config. "
    "Never let the client decide amounts, prices, damage or rewards. Use as few files as the task needs (usually 2-4).")

CODE_SYS = (
    "You write ONE file of a Roblox game system. You get the task, the agreed plan and the files already written. Write "
    "only this file's complete Luau code in one ```lua block, using only real, current Roblox APIs (task.wait, "
    "game:GetService, :Connect, Animator:LoadAnimation). Follow the plan exactly: names of remotes, folders, values and "
    "module functions must match. Server code checks everything the client sends; DataStore calls go in pcall; save in "
    "PlayerRemoving and BindToClose and never overwrite data whose load failed. No explanations outside the code block "
    "except short comments in the code.")


def parse_plan(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        plan = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(plan, dict) or not isinstance(plan.get("files"), list) or not plan["files"]:
        return None
    return plan


SERVER_PLACES = re.compile(r"ServerScriptService|ServerStorage|Workspace|\bpart\b|model", re.I)
CLIENT_PLACES = re.compile(r"StarterPlayerScripts|StarterCharacterScripts|StarterGui|PlayerGui|StarterPack|Tool|"
                           r"ReplicatedFirst", re.I)
CLIENT_TRUST = re.compile(r"\b(amount|price|cost|damage|reward|coins?|cash|gold|xp|value|count)\b", re.I)


def check_plan(plan: dict, task: str) -> list[str]:
    """Problems a reviewer would catch in the plan itself (placement, client trust, DataStore safety)."""
    out = []
    for f in plan.get("files") or []:
        t, loc = str(f.get("type", "")), str(f.get("location", ""))
        if t == "LocalScript" and re.search(r"ServerScriptService|ServerStorage", loc):
            out.append(f"File {f.get('name')}: a LocalScript never runs in {loc}; put it in StarterPlayerScripts or StarterGui.")
        if t == "LocalScript" and re.search(r"\bWorkspace\b", loc) and not re.search(r"character", loc, re.I):
            out.append(f"File {f.get('name')}: a LocalScript in Workspace never runs; move it to StarterPlayerScripts.")
        if t == "Script" and CLIENT_PLACES.search(loc) and not re.search(r"Tool", loc):
            out.append(f"File {f.get('name')}: a server Script in {loc} is the wrong side; server code goes in "
                       "ServerScriptService.")
        if t == "Script" and re.search(r"ReplicatedStorage|ServerStorage", loc):
            out.append(f"File {f.get('name')}: a Script in {loc} never runs; put it in ServerScriptService.")
    for r in plan.get("remotes") or []:
        if str(r.get("from", "client")).lower() != "client":
            continue
        args = " ".join(map(str, r.get("args") or []))
        checks = r.get("server_checks") or []
        if CLIENT_TRUST.search(args) and not checks:
            out.append(f"Remote {r.get('name')}: the client sends '{args}' and the server checks nothing; the server "
                       "must decide amounts/prices itself and check the request.")
        elif not checks:
            out.append(f"Remote {r.get('name')}: list what the server checks before acting (cooldown, ownership, "
                       "distance, enough coins).")
    data = plan.get("data") or {}
    wants_save = bool(re.search(r"\bsave|datastore|data store|keep|persist", task, re.I))
    if wants_save and not str(data.get("store") or "").strip():
        out.append("The task asks for saving but the plan has no DataStore.")
    if str(data.get("store") or "").strip():
        when = " ".join(map(str, data.get("save_when") or []))
        if "BindToClose" not in when:
            out.append("Save in game:BindToClose too, not only PlayerRemoving.")
        if "PlayerRemoving" not in when:
            out.append("Save when the player leaves (Players.PlayerRemoving).")
    if len(plan.get("files") or []) > 6:
        out.append("Too many files for this task; merge them into at most 5.")
    return out


def plan_text(plan: dict) -> str:
    return json.dumps(plan, indent=1)[:3000]


def assemble(plan: dict, codes: list[tuple[dict, str]]) -> str:
    parts = [plan.get("summary") or "Here is the whole system, file by file."]
    setup = [s for s in plan.get("setup") or [] if isinstance(s, str)]
    if setup:
        parts.append("**Set up in Studio first:**\n" + "\n".join(f"- {s}" for s in setup[:8]))
    for f, code in codes:
        parts.append(f"**{f.get('type', 'Script')} `{f.get('name', 'Script')}` (in {f.get('location', 'ServerScriptService')}):**"
                     f"\n```lua\n{code.strip()}\n```")
    tips = [a for a in plan.get("authority") or [] if isinstance(a, str)]
    if tips:
        parts.append("Tip: " + tips[0])
    return "\n\n".join(parts)


def _code_of(reply: str) -> str:
    m = re.search(r"```(?:lua|luau)?\s*\n(.*?)```", reply or "", re.S)
    if m:
        return m.group(1)
    m = re.search(r"```(?:lua|luau)?\s*\n(.*)", reply or "", re.S)   # cut off: keep what came
    return m.group(1) if m else (reply or "")


async def build(task: str, call_model, max_files: int = 5, file_tokens: int = 1100) -> tuple[str | None, dict]:
    t0 = time.monotonic()
    info: dict = {"calls": 0}
    body = {"messages": [{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": task}],
            "max_tokens": 900, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}
    r = await call_model(body)
    info["calls"] += 1
    plan = parse_plan(r.get("text") if isinstance(r, dict) else r)
    if plan is None:
        info["result"] = "no plan"
        return None, info
    problems = check_plan(plan, task)
    info["plan_problems"] = problems
    if problems:
        body["messages"] += [{"role": "assistant", "content": plan_text(plan)},
                             {"role": "user", "content": "Fix these problems in the plan and reply with the whole JSON "
                                                         "again:\n" + "\n".join(f"- {p}" for p in problems)}]
        r2 = await call_model(body)
        info["calls"] += 1
        plan2 = parse_plan(r2.get("text") if isinstance(r2, dict) else r2)
        if plan2 is not None:
            info["plan_problems_after"] = check_plan(plan2, task)
            if len(info["plan_problems_after"]) <= len(problems):
                plan = plan2
    info["plan"] = plan
    codes: list[tuple[dict, str]] = []
    for f in (plan.get("files") or [])[:max_files]:
        done = "\n\n".join(f"-- {g.get('type')} {g.get('name')} ({g.get('location')})\n{c[:1500]}" for g, c in codes)
        user = (f"Task:\n{task}\n\nPlan:\n{plan_text(plan)}\n\nFiles already written:\n{done or '(none yet)'}\n\n"
                f"Now write the file {f.get('name')} ({f.get('type')} in {f.get('location')}): {f.get('does', '')}")
        rb = await call_model({"messages": [{"role": "system", "content": CODE_SYS}, {"role": "user", "content": user}],
                               "max_tokens": file_tokens, "temperature": 0.2,
                               "chat_template_kwargs": {"enable_thinking": False}})
        info["calls"] += 1
        codes.append((f, _code_of(rb.get("text") if isinstance(rb, dict) else rb)))
    info["ms"] = round((time.monotonic() - t0) * 1000)
    info["result"] = "built"
    return assemble(plan, codes), info


def wanted(question: str) -> bool:
    """A multi-file system request (plan-then-code helps there), not a single snippet."""
    q = question or ""
    systems = len(re.findall(r"\b(inventory|round|intermission|shop|datastore|data ?store|save[sd]?|gui|leaderstats|"
                             r"team|quest|trade|trading|pet|level|xp|admin|vote|voting|plot|tycoon|checkpoint|ammo|"
                             r"reload|server|remote)\b", q, re.I))
    return len(q) > 120 and systems >= 3
