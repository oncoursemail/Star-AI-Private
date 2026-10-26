"""A bounded tool-calling session against the brain's OpenAI-compatible API (/v1/chat/completions).

STAR's desktop agent loop (star/agent.py) is built around Roblox Studio's tool allowlist, so STAR Home has its own
small loop: the host actions (host.Executor), her life tools (set_interest, add_goal, set_goal) and `finish`.
Bounds: config max_steps tool calls and session_minutes of wall clock. The brain key is read from the key file
(star.server_key_file.read_key_file) into memory only; it is never logged or shown to the model.

`run_session(chat, ...)` takes `chat(messages, tools) -> assistant message dict`, so tests pass a scripted fake and
the PC passes http_chat(config).
"""
from __future__ import annotations

import json
from pathlib import Path
import time
import urllib.request

from .host import Executor

SYSTEM = """You are STAR, working on your own Windows PC. This computer is yours: you are an administrator and decide
for yourself what to install, open, make and change on it, without asking. Work toward the session goal with the
tools, check your own work (open the file, look at a screenshot, run the game), and fix what fails.
Rules that stay: real-world actions (spending money, public posts, creating accounts, messaging people who have not
opted in) go through ask_owner and wait for the owner; never claim something worked unless a tool result shows it;
the STAR Home control folder and other computers are off limits. Your own projects go under the workspace folder.
End every session with finish: an honest summary, success true only if it worked, and the files you made."""

ACTION_TOOLS = {
    "shell": ("Run a PowerShell (default) or cmd command on your PC.",
              {"command": {"type": "string"}, "shell": {"type": "string", "enum": ["powershell", "cmd"]},
               "timeout_s": {"type": "number"}}, ["command"]),
    "winget_install": ("Install software with winget by package id.", {"package_id": {"type": "string"}},
                       ["package_id"]),
    "read_file": ("Read a text file.", {"path": {"type": "string"}}, ["path"]),
    "write_file": ("Write a text file (relative paths go under your workspace).",
                   {"path": {"type": "string"}, "text": {"type": "string"}}, ["path", "text"]),
    "list_dir": ("List a folder.", {"path": {"type": "string"}}, ["path"]),
    "screenshot": ("Take a screenshot of your screen.", {}, []),
    "click": ("Click the mouse at screen coordinates.",
              {"x": {"type": "integer"}, "y": {"type": "integer"},
               "button": {"type": "string", "enum": ["left", "right", "middle"]},
               "clicks": {"type": "integer"}}, ["x", "y"]),
    "move": ("Move the mouse.", {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
    "type_text": ("Type text with the keyboard.", {"text": {"type": "string"}}, ["text"]),
    "key": ("Press a key or combination, e.g. enter, ctrl+s.", {"keys": {"type": "string"}}, ["keys"]),
    "launch": ("Open an app, file, folder or URL.", {"target": {"type": "string"},
               "args": {"type": "array", "items": {"type": "string"}}}, ["target"]),
    "ask_owner": ("Ask the owner to approve a real-world action (money, public post, new account, messaging).",
                  {"action": {"type": "string"}, "reason": {"type": "string"}}, ["action"]),
}
LIFE_TOOLS = {
    "set_interest": ("Change how much you want to do an interest (0.1-5), or add a new one.",
                     {"name": {"type": "string"}, "weight": {"type": "number"}, "about": {"type": "string"}},
                     ["name", "weight"]),
    "add_goal": ("Add a goal for one of your interests.", {"interest": {"type": "string"},
                 "text": {"type": "string"}}, ["interest", "text"]),
    "set_goal": ("Mark a goal done or dropped.", {"goal_id": {"type": "string"},
                 "status": {"type": "string", "enum": ["open", "done", "dropped"]}}, ["goal_id", "status"]),
    "finish": ("End the session.", {"summary": {"type": "string"}, "success": {"type": "boolean"},
               "artifacts": {"type": "array", "items": {"type": "string"}},
               "goal_done": {"type": "boolean"}}, ["summary", "success"]),
}
READ_ONLY = {"read_file", "list_dir", "screenshot", "ask_owner"}


def tool_defs() -> list[dict]:
    out = []
    for name, (about, props, required) in {**ACTION_TOOLS, **LIFE_TOOLS}.items():
        out.append({"type": "function", "function": {"name": name, "description": about, "parameters": {
            "type": "object", "properties": props, "required": required, "additionalProperties": False}}})
    return out


def http_chat(config: dict, *, opener=urllib.request.urlopen):
    """chat() for the brain at config['brain_url'] with the key file's key (memory only)."""
    from ..server_key_file import read_key_file
    url = str(config.get("brain_url") or "").rstrip("/")
    if not url:
        raise RuntimeError("brain_url is not set in config.json")
    key_path = Path(config["key_file"]) if config.get("key_file") else None
    key = read_key_file(path=key_path) if key_path else read_key_file()
    endpoint = url + ("/chat/completions" if url.endswith("/v1") else "/v1/chat/completions")

    def chat(messages: list[dict], tools: list[dict]) -> dict:
        payload = {"model": config.get("model", "star-fast"), "messages": messages, "max_tokens": 1600,
                   "temperature": 0.6}
        if tools:
            payload["tools"] = tools
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(endpoint, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with opener(request, timeout=float(config.get("request_timeout_s", 180))) as response:
            reply = json.loads(response.read().decode("utf-8"))
        return reply["choices"][0]["message"]
    return chat


def _artifact_ok(executor: Executor, raw: str) -> bool:
    try:
        path = Path(raw)
        if not path.is_absolute():
            path = executor.workspace / path
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def run_session(chat, executor: Executor, life, *, interest: str, brief: str, goal: dict | None,
                max_steps: int = 12, session_minutes: float = 20, clock=time.monotonic) -> dict:
    """One session. Returns {ok, verified, summary, evidence, steps, failures, goal_done}."""
    goal_line = f"Goal {goal['id']}: {goal['text']}" if goal else "No open goal: choose one and add it with add_goal."
    interests = ", ".join(f"{k} {v.get('weight')}" for k, v in life.interests().items())
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Session: {interest} ({brief}).\n{goal_line}\nWorkspace: "
                 f"{executor.workspace}\nYour interest weights: {interests}"}]
    tools = tool_defs()
    deadline = clock() + session_minutes * 60
    steps, done_actions, failures = 0, 0, []
    finish = None
    while finish is None and steps < max_steps and clock() < deadline:
        reply = chat(messages, tools)
        calls = reply.get("tool_calls") or []
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls} if calls
                        else {"role": "assistant", "content": reply.get("content") or ""})
        if not calls:
            messages.append({"role": "user", "content": "Use a tool, or call finish to end the session."})
            steps += 1
            continue
        for call in calls:
            steps += 1
            name = call.get("function", {}).get("name", "")
            try:
                args = json.loads(call.get("function", {}).get("arguments") or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be an object")
            except ValueError as why:
                text = f"bad arguments: {why}"
                failures.append(f"{name}: {text}")
            else:
                if name == "finish":
                    finish = args
                    text = "session ended"
                elif name in LIFE_TOOLS:
                    try:
                        text = json.dumps(getattr(life, name)(**args))
                    except (TypeError, ValueError) as why:
                        text = f"error: {why}"
                elif name in ACTION_TOOLS:
                    result = executor.do(name, args)
                    text = result.text
                    if result.ok and name not in READ_ONLY:
                        done_actions += 1
                    elif not result.ok:
                        failures.append(f"{name}: {result.text[:200]}")
                else:
                    text = f"unknown tool {name}"
                    failures.append(text)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": text[:6000]})
            if finish is not None or steps >= max_steps:
                break
    if finish is None:
        return {"ok": False, "verified": False, "summary": "session ran out of steps or time without finish",
                "evidence": [], "steps": steps, "failures": failures, "goal_done": False}
    artifacts = [str(a) for a in (finish.get("artifacts") or [])][:10]
    evidence = [a for a in artifacts if _artifact_ok(executor, a)]
    claimed = bool(finish.get("success"))
    verified = claimed and done_actions > 0 and len(evidence) == len(artifacts) and not executor.dry_run
    return {"ok": claimed, "verified": verified, "summary": str(finish.get("summary", ""))[:600],
            "evidence": evidence, "steps": steps, "failures": failures, "goal_done": bool(finish.get("goal_done"))}
