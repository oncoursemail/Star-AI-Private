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

from .host import Executor, Refused
from . import control

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
        if raw.startswith(("\\\\", "//")):
            return False
        path = executor._check_path(raw)
        return path.is_file() and path.stat().st_size > 0
    except (OSError, ValueError, RuntimeError, Refused):
        return False


def _finish_args(args: dict) -> dict:
    if (set(args) - {"summary", "success", "artifacts", "goal_done"}
            or not isinstance(args.get("summary"), str) or type(args.get("success")) is not bool
            or type(args.get("goal_done", False)) is not bool):
        raise ValueError("finish requires a text summary and boolean success/goal_done")
    artifacts = args.get("artifacts", [])
    if (not isinstance(artifacts, list) or len(artifacts) > 10
            or any(not isinstance(path, str) or not path.strip() or len(path) > 4096 or "\0" in path
                   for path in artifacts)):
        raise ValueError("artifacts must be up to ten nonempty file paths")
    try:
        for value in [args["summary"], *artifacts]:
            value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("finish contains invalid text") from None
    return {**args, "artifacts": artifacts, "goal_done": args.get("goal_done", False)}


def run_session(chat, executor: Executor, life, *, interest: str, brief: str, goal: dict | None,
                max_steps: int = 12, session_minutes: float = 20, clock=time.monotonic, stop=None,
                recall_history: bool = False) -> dict:
    """One session. Returns {ok, verified, summary, evidence, steps, failures, goal_done}. `stop()` -> True asks it to
    end now (a friend needs her): the result is {"paused": True}; a brain session is not resumable, it starts over."""
    goal_line = f"Goal {goal['id']}: {goal['text']}" if goal else "No open goal: choose one and add it with add_goal."
    interests = ", ".join(f"{k} {v.get('weight')}" for k, v in life.interests().items())
    # Unlike everyday chat, STAR Home can explicitly opt in to a small same-
    # interest *metadata* reminder per session. The prior desktop A/B found
    # that unsolicited, long autobiographical text harmed response quality.
    recall = ""
    if recall_history is True:
        from ..living_continuity import home_session_context
        recall = home_session_context(life, interest)
    messages: list[dict] = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Session: {interest} ({brief}).\n{goal_line}\nWorkspace: "
                 f"{executor.workspace}\nYour interest weights: {interests}"
                 + (f"\n{recall}" if recall else "")}]
    tools = tool_defs()
    deadline = clock() + session_minutes * 60
    steps, done_actions, failures = 0, 0, []
    finish = None

    def ended(summary: str, *, paused: bool = False) -> dict:
        result = {"ok": False, "verified": False, "summary": summary, "evidence": [],
                  "steps": steps, "failures": failures, "goal_done": False}
        if paused:
            result["paused"] = True
        return result

    def interrupted() -> dict | None:
        home = getattr(executor, "home", None)
        if home is not None and control.stopped(home):
            return ended("stopped by owner")
        try:
            if stop is not None and stop():
                return ended("paused: someone needs her", paused=True)
        except Exception:
            return ended("session stopped: interruption check unavailable")
        if clock() >= deadline:
            return ended("session ran out of time")
        return None

    while finish is None and steps < max_steps and clock() < deadline:
        stopped = interrupted()
        if stopped is not None:
            return stopped
        try:
            reply = chat(messages, tools)
        except Exception as error:
            failures.append(f"brain: {type(error).__name__}; no automatic retry")
            return ended("brain request failed; earlier action outcomes are retained in the action log")
        stopped = interrupted()
        if stopped is not None:
            return stopped
        if not isinstance(reply, dict):
            return ended("brain returned an invalid message")
        calls = reply.get("tool_calls")
        calls = [] if calls is None else calls
        if not isinstance(calls, list):
            return ended("brain returned an invalid tool batch")
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls} if calls
                        else {"role": "assistant", "content": reply.get("content") or ""})
        if not calls:
            messages.append({"role": "user", "content": "Use a tool, or call finish to end the session."})
            steps += 1
            continue
        for call in calls:
            stopped = interrupted()
            if stopped is not None:
                return stopped
            steps += 1
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                return ended("brain returned an invalid tool call")
            name = call["function"].get("name", "")
            if not isinstance(name, str):
                return ended("brain returned an invalid tool name")
            try:
                raw_args = call["function"].get("arguments", "{}")
                if not isinstance(raw_args, str):
                    raise ValueError("arguments must be JSON text")
                args = json.loads(raw_args or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be an object")
            except ValueError as why:
                text = f"bad arguments: {why}"
                failures.append(f"{name}: {text}")
            else:
                if name == "finish":
                    try:
                        finish = _finish_args(args)
                        text = "session ended"
                    except ValueError as error:
                        text = f"invalid finish: {error}"
                        failures.append(text)
                elif name in LIFE_TOOLS:
                    if name == "set_goal" and args.get("status") == "done":
                        text = "refused: report goal_done through finish; completion requires a verified session"
                        failures.append("set_goal: premature completion refused")
                    else:
                        try:
                            text = json.dumps(getattr(life, name)(**args))
                        except (TypeError, ValueError, KeyError) as why:
                            text = f"error: {type(why).__name__}"
                            failures.append(f"{name}: {text}")
                elif name in ACTION_TOOLS:
                    try:
                        result = executor.do(name, args)
                    except Exception as error:
                        failures.append(f"{name}: outcome unknown ({type(error).__name__}); inspect before retrying")
                        return ended("host action outcome unknown; no automatic retry")
                    text, ok = getattr(result, "text", None), getattr(result, "ok", None)
                    if not isinstance(text, str) or type(ok) is not bool:
                        failures.append(f"{name}: invalid host result; outcome unknown")
                        return ended("host action returned an invalid result; no automatic retry")
                    try:
                        text.encode("utf-8", errors="strict")
                    except UnicodeError:
                        failures.append(f"{name}: invalid host result text; outcome unknown")
                        return ended("host action returned invalid text; no automatic retry")
                    if ok is True and name not in READ_ONLY:
                        done_actions += 1
                    elif ok is not True:
                        failures.append(f"{name}: {text[:200]}")
                else:
                    text = f"unknown tool {name}"
                    failures.append(text)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": text[:6000]})
            stopped = interrupted()
            if stopped is not None:
                return stopped
            if finish is not None or steps >= max_steps:
                break
    if finish is None:
        return {"ok": False, "verified": False, "summary": "session ran out of steps or time without finish",
                "evidence": [], "steps": steps, "failures": failures, "goal_done": False}
    stopped = interrupted()
    if stopped is not None:
        return stopped
    artifacts = finish["artifacts"]
    evidence = [a for a in artifacts if _artifact_ok(executor, a)]
    claimed = finish["success"] is True
    verified = claimed and done_actions > 0 and len(evidence) == len(artifacts) and not executor.dry_run
    return {"ok": claimed, "verified": verified, "summary": str(finish.get("summary", ""))[:600],
            "evidence": evidence, "steps": steps, "failures": failures,
            "goal_done": verified and finish["goal_done"] is True}
