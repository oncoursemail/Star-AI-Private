#!/usr/bin/env python3
"""G0b tail bench: the app's own first token for real Roblox code edits, type-ahead off vs on (draft + reference block).

Runs STAR's real code on the PC (run_task, warmup.warm_up, prefill_warm.warm_draft) against a SIDE star-fast (srv.sh
with HOST set, reached through an ssh tunnel), never the live brain, and the real knowledge service. Per task, two fresh
chats with the same earlier Roblox exchange (its tool list recorded by a model-free seed turn, run with the arm's own
settings: a chat started with type-ahead on has the fixed Roblox tool list from its first message on):

  cold     the post-answer warm-up primed the chat's start; Enter -> run_task reads the owner's words + reference block
  enabled  the same warm-up, then "Start thinking while I type" with the finished text (draft + reference block up to
           the time line); Enter -> run_task

First token = first visible text delta of run_task after the call (the turn is stopped there). For `enabled` the real
request is rendered by the server's /apply-template and checked to start with the last primed text (byte-identical).

    APPDATA=<empty temp dir> STAR_SERVER_API_KEY=<key> python tailbench.py --endpoint http://127.0.0.1:18095/v1 \
        --knowledge http://<brain address>:8091 --out out.json [--start 0 --count 20]

APPDATA must not be the owner's STAR folder. The side server needs no key; the knowledge service does.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

SEED_PROMPT = "Write a Luau script for my Roblox game that spins a part"
SEED_ANSWER = ("Put this Script inside the part:\n\n```luau\nlocal part = script.Parent\n"
               "game:GetService(\"RunService\").Heartbeat:Connect(function(dt)\n"
               "\tpart.CFrame = part.CFrame * CFrame.Angles(0, dt, 0)\nend)\n```")


class Stop(Exception):
    """Raised from the event callback at the first visible text: ends the turn there."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--knowledge", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--tasks", default=str(ROOT / "evals" / "roblox" / "edit-tasks-v1.json"))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--arms", default="cold,enabled")
    parser.add_argument("--deadline", type=float, default=0, help="stop starting new tasks after this many seconds")
    args = parser.parse_args()
    real = Path(os.path.expandvars(r"%USERPROFILE%\AppData\Roaming")).resolve()
    if Path(os.environ.get("APPDATA", str(real))).resolve() == real:
        raise SystemExit("set APPDATA to an empty temporary folder")

    import httpx
    import star.desktop_core as core
    import star.prefill_warm as prefill
    from star import providers, warmup
    from star.desktop_core import Conversations, Settings, run_task

    endpoint = args.endpoint.rstrip("/")
    root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
    providers.remember_server_limits(endpoint, "star-fast", 32768, 2)
    base = Settings(provider="star_server", server_endpoint=endpoint, model="star-fast",
                    knowledge_endpoint=args.knowledge)
    base.validate()
    home = core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    chats = Conversations(home / "conversations.sqlite3")
    tasks = json.load(open(args.tasks, encoding="utf-8"))[args.start:args.start + args.count]

    real_open = core.open_client
    captured: list[dict] = []
    requested: list[float] = []

    class SpyCompletions:
        def __init__(self, inner):
            self.inner = inner

        async def create(self, **kwargs):
            captured.append(json.loads(json.dumps(kwargs, default=str)))
            requested.append(time.perf_counter())
            return await self.inner.create(**kwargs)

    class Spy:
        def __init__(self, settings, **kw):
            self.inner = real_open(settings, **kw)

        async def __aenter__(self):
            client = await self.inner.__aenter__()
            return SimpleNamespace(chat=SimpleNamespace(completions=SpyCompletions(client.chat.completions)),
                                   embeddings=client.embeddings)

        async def __aexit__(self, *exc):
            return await self.inner.__aexit__(*exc)

    class Canned:
        """Model-free seed turn: records the conversation's tool list (turn_memory), answers at once."""
        def __init__(self, settings, **kw):
            async def create(**kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=SEED_ANSWER, tool_calls=None))])
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    primed: list[str] = []

    class Recorder(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            if request.url.path.endswith("/completions"):
                primed.append(json.loads(request.content)["prompt"])
            return await super().handle_async_request(request)

    prefill._TRANSPORT = Recorder()

    def idle(timeout=120.0):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            slots = httpx.get(root + "/slots", timeout=10).json()
            if not any(slot.get("is_processing") for slot in slots):
                return
            time.sleep(0.5)

    def seeded_chat(settings) -> str:
        chat = chats.new_chat("STAR")
        chats.add("STAR", "user", SEED_PROMPT, chat_id=chat)
        core.open_client = Canned
        try:
            run_task(settings, SEED_PROMPT, mode="auto", chat_id=chat)
        finally:
            core.open_client = real_open
        chats.add("STAR", "assistant", SEED_ANSWER, chat_id=chat)
        return chat

    def turn(settings, chat: str, text: str) -> dict:
        chats.add("STAR", "user", text, chat_id=chat)
        seen = {}

        def on_event(event):
            if event.get("event") == "assistant_delta" and str(event.get("text", "")).strip():
                seen["first"] = time.perf_counter()
                raise Stop()
            if event.get("event") == "knowledge_finished":
                seen["knowledge_ms"] = event.get("elapsed_ms")
        captured.clear()
        requested.clear()
        core.open_client = Spy
        began = time.perf_counter()
        try:
            run_task(settings, text, mode="auto", chat_id=chat, stream_tokens=True, on_event=on_event)
        except Stop:
            pass
        except Exception as exc:
            seen["error"] = type(exc).__name__ + ": " + str(exc)[:200]
        finally:
            core.open_client = real_open
        idle()
        out = {"first_token_s": round(seen["first"] - began, 3) if "first" in seen else None,
               "knowledge_ms": seen.get("knowledge_ms"),
               # PC side: run_task's work before the model request (history, lessons, docs, route).
               "request_s": round(requested[0] - began, 3) if requested else None}
        if "error" in seen:
            out["error"] = seen["error"]
        out["request"] = captured[0] if captured else None
        return out

    results, began = [], time.monotonic()
    arms = args.arms.split(",")
    for task in tasks:
        if args.deadline and time.monotonic() - began > args.deadline:
            break
        text = task["prompt"].strip()
        row = {"id": task["id"], "chars": len(text)}
        for arm in arms:
            settings = replace(base, prefill_while_typing=arm == "enabled")
            chat = seeded_chat(settings)
            row[arm + "_warm_up"] = {k: v for k, v in warmup.warm_up(settings, home=home, chat_id=chat).items()
                                     if k in ("primed", "skipped", "prompt_tokens_read", "prompt_tokens_cached", "ms")}
            if arm == "enabled":
                primed.clear()
                started = time.perf_counter()
                report = prefill.warm_draft(settings, home, chat, text, mode="auto")
                row["prefill"] = {**report, "wall_s": round(time.perf_counter() - started, 2)}
                idle()
            result = turn(settings, chat, text)
            request = result.pop("request")
            if arm == "enabled" and request and primed:
                body = {"model": request["model"], "messages": request["messages"]}
                if request.get("tools"):
                    body["tools"] = request["tools"]
                kwargs = (request.get("extra_body") or {}).get("chat_template_kwargs")
                if kwargs:
                    body["chat_template_kwargs"] = kwargs
                rendered = httpx.post(root + "/apply-template", json=body, timeout=30).json()["prompt"]
                result["starts_with_primed"] = rendered.startswith(primed[-1])
                result["after_primed"] = rendered[len(primed[-1]):][:300] if result["starts_with_primed"] else None
                result["request_chars"] = len(rendered)
            row[arm] = result
            print(json.dumps({"id": task["id"], "arm": arm, "first_token_s": result["first_token_s"],
                              "ok": result.get("starts_with_primed"), "error": result.get("error"),
                              "tail": (row.get("prefill") or {}).get("tail") if arm == "enabled" else None}),
                  flush=True)
        results.append(row)
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    chats.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
