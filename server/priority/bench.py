#!/usr/bin/env python3
"""Priority scheduler measurements (run on the brain, under the quiet lock). Stdlib only.

  bench.py latency    --url U [--proxy] --ks 0,1,2,3 --reps 2   P0 first token while K background streams run
  bench.py throughput --url U [--proxy] --k 2 --secs 120 --chat-every 30
                                                               background tokens/s over a window, with or without
                                                               owner chats every N seconds (--chat-every 0: none)
  bench.py batch      --url U [--proxy] --n 6 --k 2 --chat-at 10,50,90
                                                               a fixed background workload (same prompts every run)
                                                               with chats at fixed times: tokens / makespan
  bench.py seam       --url U                                  one long background answer cut by a P0 chat: prints
                                                               the text around each resume point

--proxy adds the class prefixes (/p0 for the chat, /p3 for background); without it both go straight to U.
The key is read from /opt/star/secrets/api_keys when U is the router on :8080 or the proxy (never printed).
One JSON line per measurement on stdout.
"""
from __future__ import annotations

import argparse
import http.client
import json
import socket
import threading
import time
import urllib.parse

TOPICS = ("DataStore session locking", "server-authoritative inventories", "NPC pathfinding with PathfindingService",
          "round lifecycle state machines", "remote event rate limiting", "UI layout with UIListLayout",
          "tool attachment and welds", "economy sinks and sources")
CHAT = "(%f) hey STAR, quick one: how do I make a part spin in Roblox? Keep it short."
KEY_FILE = "/opt/star/secrets/api_keys"


def key_for(url: str) -> str:
    try:
        with open(KEY_FILE, encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


class Call:
    """One streaming chat request; `abort()` closes it from another thread."""

    def __init__(self, url: str, path_prefix: str, body: dict, key: str):
        parts = urllib.parse.urlsplit(url)
        self.conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=900)
        self.path = path_prefix + "/v1/chat/completions"
        self.body, self.key = body, key
        self.tokens, self.text, self.first = 0, "", None
        self.timings: dict = {}
        self.aborted = False

    def run(self) -> "Call":
        t0 = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        try:
            self.conn.request("POST", self.path, json.dumps(self.body), headers)
            resp = self.conn.getresponse()
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text.startswith("data:") or text[5:].strip() == "[DONE]":
                    continue
                try:
                    chunk = json.loads(text[5:])
                except ValueError:
                    continue
                if chunk.get("timings"):
                    self.timings = chunk["timings"]
                for choice in chunk.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        if self.first is None:
                            self.first = time.monotonic() - t0
                        self.tokens += 1
                        self.text += piece
        except (OSError, http.client.HTTPException):
            pass
        self.wall = time.monotonic() - t0
        return self

    def abort(self) -> None:
        self.aborted = True
        sock = self.conn.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def body(prompt: str, n: int) -> dict:
    return {"model": "star-fast", "messages": [{"role": "user", "content": prompt}], "max_tokens": n,
            "temperature": 0, "top_k": 1, "seed": 42, "stream": True, "cache_prompt": True}


class Background:
    """K streams kept busy: each runs long answers back to back until stop()."""

    def __init__(self, url: str, prefix: str, k: int, n: int, key: str):
        self.url, self.prefix, self.k, self.n, self.key = url, prefix, k, n, key
        self.calls: list[Call] = []
        self.done: list[Call] = []
        self.lock = threading.Lock()
        self.stopping = False
        self.threads = [threading.Thread(target=self._loop, args=(i,), daemon=True) for i in range(k)]
        self.counter = 0

    def _loop(self, i: int) -> None:
        while not self.stopping:
            with self.lock:
                self.counter += 1
                prompt = f"({i} {self.counter} {time.time():.3f}) Write a long, detailed guide to Roblox " \
                         f"{TOPICS[self.counter % len(TOPICS)]}, with code."
                call = Call(self.url, self.prefix, body(prompt, self.n), self.key)
                self.calls.append(call)
            call.run()
            with self.lock:
                self.calls.remove(call)
                if not call.aborted:
                    self.done.append(call)

    def start(self) -> "Background":
        for t in self.threads:
            t.start()
        return self

    def tokens(self) -> int:
        with self.lock:
            return sum(c.tokens for c in self.done) + sum(c.tokens for c in self.calls)

    def stop(self) -> None:
        self.stopping = True
        with self.lock:
            for call in self.calls:
                call.abort()
        for t in self.threads:
            t.join(30)


def latency(args, key: str) -> None:
    for k in [int(x) for x in args.ks.split(",")]:
        bg = Background(args.url, "/p3" if args.proxy else "", k, args.bg_tokens, key).start()
        time.sleep(args.warm if k else 0)
        for rep in range(args.reps):
            call = Call(args.url, "/p0" if args.proxy else "", body(CHAT % time.time(), args.chat_tokens), key).run()
            print(json.dumps({"test": "latency", "tag": args.tag, "proxy": args.proxy, "k": k, "rep": rep,
                              "first_token_s": round(call.first, 2) if call.first else None,
                              "wall_s": round(call.wall, 2), "tokens": call.tokens,
                              "chat_tps": round(call.tokens / max(call.wall - (call.first or 0), 1e-6), 2),
                              "prompt_n": call.timings.get("prompt_n"), "cache_n": call.timings.get("cache_n")}),
                  flush=True)
            if rep + 1 < args.reps:
                time.sleep(args.gap)
        bg.stop()


def throughput(args, key: str) -> None:
    bg = Background(args.url, "/p3" if args.proxy else "", args.k, args.bg_tokens, key).start()
    time.sleep(args.warm)
    t0, n0 = time.monotonic(), bg.tokens()
    chats: list[Call] = []
    next_chat = t0 + (args.chat_every or 1e18) / 2
    while time.monotonic() - t0 < args.secs:
        if time.monotonic() >= next_chat:
            chats.append(Call(args.url, "/p0" if args.proxy else "", body(CHAT % time.time(), args.chat_tokens),
                              key).run())
            next_chat += args.chat_every
        time.sleep(0.2)
    wall, made = time.monotonic() - t0, bg.tokens() - n0
    bg.stop()
    print(json.dumps({"test": "throughput", "tag": args.tag, "proxy": args.proxy, "k": args.k,
                      "secs": round(wall, 1), "bg_tokens": made, "bg_tps": round(made / wall, 2),
                      "chats": len(chats), "chat_first_token_s": [round(c.first, 2) if c.first else None for c in chats],
                      "chat_wall_s": [round(c.wall, 2) for c in chats]}), flush=True)


def batch(args, key: str) -> None:
    """A fixed background workload (--n answers of --bg-tokens, the same prompts every run, --k at a time) with owner
    chats at fixed offsets (--chat-at seconds): background tokens / makespan, and each chat's first token."""
    prompts = [f"(batch {i}) Write a long, detailed guide to Roblox {TOPICS[i % len(TOPICS)]}, with code."
               for i in range(args.n)]
    lock, done = threading.Lock(), []

    def worker():
        while True:
            with lock:
                if not prompts:
                    return
                prompt = prompts.pop(0)
            call = Call(args.url, "/p3" if args.proxy else "", body(prompt, args.bg_tokens), key).run()
            with lock:
                done.append(call)
    t0 = time.monotonic()
    workers = [threading.Thread(target=worker) for _ in range(args.k)]
    for w in workers:
        w.start()
    chats = []
    for at in [float(x) for x in args.chat_at.split(",") if x]:
        time.sleep(max(0.0, t0 + at - time.monotonic()))
        chats.append(Call(args.url, "/p0" if args.proxy else "", body(CHAT % time.time(), args.chat_tokens),
                          key).run())
    for w in workers:
        w.join()
    wall = time.monotonic() - t0
    tokens = sum(c.tokens for c in done)
    print(json.dumps({"test": "batch", "tag": args.tag, "proxy": args.proxy, "k": args.k, "n": args.n,
                      "makespan_s": round(wall, 1), "bg_tokens": tokens, "bg_tps": round(tokens / wall, 2),
                      "chat_first_token_s": [round(c.first, 2) if c.first else None for c in chats],
                      "chat_wall_s": [round(c.wall, 2) for c in chats]}), flush=True)


def seam(args, key: str) -> None:
    """One 300-token background answer through the proxy, cut by a P0 chat after 8 s; the same prompt straight to
    the server for comparison. Prints both texts so a reader can check the joins."""
    prompt = "(seam) Write a detailed guide to Roblox DataStore session locking, with code."
    out: dict = {}

    def bg_run():
        out["bg"] = Call(args.url, "/p3", body(prompt, 300), key).run()
    t = threading.Thread(target=bg_run)
    t.start()
    time.sleep(8)
    chat = Call(args.url, "/p0", body(CHAT % time.time(), 40), key).run()
    t.join()
    ref = Call(args.direct, "", body(prompt, 300), key_for(args.direct)).run()
    print(json.dumps({"test": "seam", "chat_first_token_s": chat.first, "bg_tokens": out["bg"].tokens,
                      "ref_tokens": ref.tokens, "identical": out["bg"].text == ref.text,
                      "bg_text": out["bg"].text, "ref_text": ref.text}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("test", choices=("latency", "throughput", "seam", "batch"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--direct", default="")
    parser.add_argument("--proxy", action="store_true")
    parser.add_argument("--tag", default="")
    parser.add_argument("--ks", default="0,1,2,3")
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--gap", type=float, default=8.0)
    parser.add_argument("--warm", type=float, default=8.0)
    parser.add_argument("--secs", type=float, default=120.0)
    parser.add_argument("--chat-every", type=float, default=30.0)
    parser.add_argument("--bg-tokens", type=int, default=400)
    parser.add_argument("--chat-tokens", type=int, default=60)
    parser.add_argument("--n", type=int, default=6)
    parser.add_argument("--chat-at", default="10,50,90")
    args = parser.parse_args()
    key = key_for(args.url)
    {"latency": latency, "throughput": throughput, "seam": seam, "batch": batch}[args.test](args, key)


if __name__ == "__main__":
    main()
