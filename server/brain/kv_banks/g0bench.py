#!/usr/bin/env python3
"""G0 first-token bench: a code edit with a few thousand tokens of context, cold vs prefilled vs restored.

Runs next to a SIDE llama-server (srv.sh: 127.0.0.1, no key, --slot-save-path), never the live brain.
Standard library only. Usage:

    python3 g0bench.py BASE CONTEXT.json OUT.json ARM [ARM ...]

CONTEXT.json: {"system": str, "history": [{"role", "content"}...], "question": str, "paste": str,
              "long_paste": str}
Arms (each repeated --reps times, slot 0 unless noted, greedy, 48 new tokens):
  bank        read the stable start (system message) alone on slot 0 and save it: bytes, save ms, read time
  restored    G0b: erase slot 0, restore the bank, then the turn: first token after Enter (+ restore ms)
  prefilled   G0a: the slot holds the start (restored, standing in for the post-answer warm-up), the owner's draft
              (question minus its last words) is primed in chunks as the app does, Enter 0.3 s later
  cold        a nonce in front of the system message: nothing cached, the whole prompt is read after Enter
  background  slot 1 generates 256 tokens alone, then again while slot 0 (holding the chat's start) primes a paste
              in chunks: tok/s ratio
  contention  another client's short request on slot 1, 1 s into the owner's draft prefill of a long paste on slot 0:
              its first token with no draft, with the draft as one request, in chunks, and in chunks that stop
              while another slot generates (the app's behaviour)
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
import time
import urllib.parse
import uuid

CHUNK_CHARS = 400            # star/prefill_warm.py CHUNK_CHARS
BANK = "g0-bench-bank.bin"
NEW_TOKENS = 48


def _conn(base: str, timeout: float = 900.0) -> http.client.HTTPConnection:
    url = urllib.parse.urlsplit(base)
    return http.client.HTTPConnection(url.hostname, url.port or 80, timeout=timeout)


def post(base: str, path: str, body: dict, timeout: float = 900.0) -> dict:
    conn = _conn(base, timeout)
    try:
        conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        reply = conn.getresponse()
        data = json.loads(reply.read() or b"{}")
        if reply.status != 200:
            raise RuntimeError(f"{path} -> {reply.status} {str(data)[:200]}")
        return data
    finally:
        conn.close()


def slot(base: str, n: int, action: str, filename: str = "") -> dict:
    return post(base, f"/slots/{n}?action={action}", {"filename": filename} if filename else {})


def render(base: str, messages: list) -> str:
    return post(base, "/apply-template", {"messages": messages})["prompt"]


def prime(base: str, prompt: str, n: int) -> dict:
    began = time.perf_counter()
    reply = post(base, "/v1/completions", {"prompt": prompt, "max_tokens": 1, "temperature": 0,
                                            "cache_prompt": True, "id_slot": n})
    t = reply.get("timings") or {}
    return {"s": round(time.perf_counter() - began, 3), "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n")}


def chat(base: str, messages: list, n: int, max_tokens: int = NEW_TOKENS) -> dict:
    """Streamed turn: seconds to the first token, the text and the server's timings."""
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "cache_prompt": True, "id_slot": n, "timings_per_token": False}
    conn = _conn(base)
    began = time.perf_counter()
    first, text, timings = None, [], {}
    try:
        conn.request("POST", "/v1/chat/completions", json.dumps(body), {"Content-Type": "application/json"})
        reply = conn.getresponse()
        if reply.status != 200:
            raise RuntimeError(f"chat -> {reply.status} {reply.read()[:200]!r}")
        for raw in reply:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            if event.get("timings"):
                timings = event["timings"]
            for choice in event.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content") or ""
                if piece:
                    if first is None:
                        first = time.perf_counter() - began
                    text.append(piece)
    finally:
        conn.close()
    keep = ("prompt_n", "cache_n", "prompt_per_second", "predicted_n", "predicted_per_second",
            "draft_n", "draft_n_accepted")
    return {"ttft_s": round(first or -1, 3), "total_s": round(time.perf_counter() - began, 3),
            "text": "".join(text), **{k: timings[k] for k in keep if k in timings}}


def prefix_of(base: str, system: dict) -> str:
    """The stable start as star/cache_banks.py banks it: the common start of two renders."""
    a = render(base, [system, {"role": "user", "content": "alpha"}])
    b = render(base, [system, {"role": "user", "content": "omega"}])
    n = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
    return a[:n]


def draft_cut(base: str, messages: list, draft: str) -> str:
    """The raw text the app primes for a draft: the turn rendered with the draft as the last user message, cut
    right after the draft (star/prefill_warm.py)."""
    prompt = render(base, messages[:-1] + [{"role": "user", "content": draft}])
    if prompt.rfind(draft) < 0:
        raise ValueError("the template changed the draft (it strips surrounding white space): strip it first")
    return prompt[:prompt.rfind(draft) + len(draft)]


def busy(base: str, n: int) -> bool:
    conn = _conn(base, 10)
    try:
        conn.request("GET", "/slots")
        rows = json.loads(conn.getresponse().read())
    finally:
        conn.close()
    return any(row.get("id") == n and row.get("is_processing") for row in rows)


def chunked(base: str, text: str, start: int, n: int, stop=None, yield_to=None) -> list:
    """Prime `text` from character `start` on in CHUNK_CHARS steps, as the app's chunk_ends does; with `yield_to`,
    stop before the next chunk while that slot is generating (the app's others_busy check)."""
    out, at = [], start
    while at < len(text):
        if out and yield_to is not None and busy(base, yield_to):
            break
        end = min(len(text), at + CHUNK_CHARS)
        if end < len(text):
            space = max(text.rfind(" ", at + CHUNK_CHARS // 2, end), text.rfind("\n", at + CHUNK_CHARS // 2, end))
            end = space + 1 if space >= 0 else end
        if stop is not None and stop.is_set():
            break
        out.append(prime(base, text[:end], n))
        at = end
    return out


def run(base: str, ctx: dict, arms: list, reps: int) -> dict:
    ctx = {**ctx, **{k: ctx[k].strip() for k in ("question", "paste", "long_paste") if k in ctx}}   # as the app sends
    system = {"role": "system", "content": ctx["system"]}
    messages = [system, *ctx["history"], {"role": "user", "content": ctx["question"]}]
    words = ctx["question"].split(" ")
    draft = " ".join(words[:-2])
    out: dict = {"base_prompt_chars": len(render(base, messages))}

    if "bank" in arms:
        slot(base, 0, "erase")
        prefix = prefix_of(base, system)
        read = prime(base, prefix, 0)
        saved = slot(base, 0, "save", BANK)
        out["bank"] = {"prefix_chars": len(prefix), "read": read, "n_saved": saved.get("n_saved"),
                       "bytes": saved.get("n_written"), "save_ms": (saved.get("timings") or {}).get("save_ms")}
        print("bank", json.dumps(out["bank"]), flush=True)

    def restore() -> float:
        slot(base, 0, "erase")
        return (slot(base, 0, "restore", BANK).get("timings") or {}).get("restore_ms")

    for arm in ("restored", "prefilled", "cold"):
        if arm not in arms:
            continue
        rows = []
        for rep in range(reps):
            row: dict = {}
            turn = messages
            if arm == "restored":
                row["restore_ms"] = restore()
            elif arm == "prefilled":
                row["restore_ms"] = restore()
                full = draft_cut(base, messages, draft)
                row["draft_chunks"] = chunked(base, full, len(full) - len(draft), 0)
                time.sleep(0.3)
            else:
                turn = [{"role": "system", "content": f"[{uuid.uuid4()}]\n" + ctx["system"]}, *messages[1:]]
                slot(base, 0, "erase")
            row.update(chat(base, turn, 0))
            rows.append(row)
            print(arm, rep, json.dumps({k: v for k, v in row.items() if k != "text"}), flush=True)
        out[arm] = rows

    if "background" in arms:
        bg = [{"role": "user", "content": "Write a Luau ModuleScript for a round-based minigame lobby with a "
                                          "countdown, player teleport and a winner board. Code only."}]
        alone = chat(base, bg, 1, 256)
        out["background"] = {"alone_tps": alone.get("predicted_per_second")}
        for label, yield_to in (("chunks", None), ("chunks_yield", 1)):
            stop = threading.Event()
            typed: list = []
            restore()               # the owner's chat: its start is in slot 0, the paste is new

            def typist():
                paste_turn = messages[:-1] + [{"role": "user", "content": ctx["paste"]}]
                text = draft_cut(base, paste_turn, ctx["paste"])
                typed.extend(chunked(base, text, len(text) - len(ctx["paste"]), 0, stop, yield_to))
            worker = threading.Thread(target=typist)
            worker.start()
            shared = chat(base, bg, 1, 256)
            stop.set()
            worker.join()
            out["background"][label] = {"tps": shared.get("predicted_per_second"), "prefill_requests": len(typed),
                                        "same_text": alone["text"] == shared["text"]}
        print("background", json.dumps(out["background"]), flush=True)

    if "contention" in arms:
        # Another client's request (slot 1) arrives 1 s into the owner's draft prefill of a long paste (slot 0).
        # llama.cpp fills each batch (2048 tokens) from slot 0 first, so one long request can hold slot 1 back.
        other = [{"role": "user", "content": "In one sentence: what does RunService.Heartbeat fire on?"}]
        rows = []
        for mode in ("no_draft", "one_request", "chunks", "chunks_yield"):
            restore()
            paste_turn = messages[:-1] + [{"role": "user", "content": ctx["long_paste"]}]
            text = draft_cut(base, paste_turn, ctx["long_paste"])
            start = len(text) - len(ctx["long_paste"])
            stop = threading.Event()
            worker = None
            if mode == "one_request":
                worker = threading.Thread(target=lambda: prime(base, text, 0))
            elif mode == "chunks":
                worker = threading.Thread(target=lambda: chunked(base, text, start, 0, stop))
            elif mode == "chunks_yield":
                worker = threading.Thread(target=lambda: chunked(base, text, start, 0, stop, yield_to=1))
            if worker is not None:
                worker.start()
                time.sleep(1.0)
            row = chat(base, other, 1, 16)
            stop.set()
            if worker is not None:
                worker.join()
            row["mode"] = mode
            rows.append(row)
            print("contention", json.dumps({k: v for k, v in row.items() if k != "text"}), flush=True)
        out["contention"] = rows
    return out


def main(argv: list) -> int:
    reps = 3
    if "--reps" in argv:
        i = argv.index("--reps")
        reps = int(argv[i + 1])
        del argv[i:i + 2]
    base, ctx_file, out_file, *arms = argv[1:]
    with open(ctx_file, encoding="utf-8") as f:
        ctx = json.load(f)
    result = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "reps": reps, "arms": arms,
              **run(base, ctx, arms, reps)}
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
