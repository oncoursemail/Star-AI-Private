#!/usr/bin/env python3
"""star-fast generation speed for the Windows-VM impact runs (run inside the starai container, standard library).

    python3 chatbench.py --tag novm [--rounds 1]

Sends the same 5 short Roblox/Luau prompts (greedy, 160 tokens) to star-fast through the router and prints the
server-side generation tok/s per request plus the median. Before each request it waits until no star-fast/star-voice
slot is busy; a request during which another slot started work is marked "busy" and left out of the median.
The API key is read from /opt/star/secrets/api_keys and never printed.
"""
import argparse
import json
import statistics
import time
import urllib.request

BASE = "http://127.0.0.1:8080"
PROMPTS = [
    "Write a Luau function that returns the sum of a numeric array, with a short comment.",
    "Explain in four sentences how RemoteEvents carry data from client to server in Roblox.",
    "Write a Luau ModuleScript with a Stack class: push, pop, peek and isEmpty.",
    "List five common causes of DataStore request throttling and one fix for each.",
    "Write a Luau script that tweens a Part's transparency from 0 to 1 over two seconds.",
]


def key():
    with open("/opt/star/secrets/api_keys", encoding="utf-8") as f:
        return f.read().split()[0]


def call(path, k, body=None, timeout=300):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + k, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def busy(k):
    n = 0
    for m in ("star-fast", "star-voice"):
        try:
            n += sum(1 for s in call("/slots?model=" + m, k, timeout=10) if s.get("is_processing"))
        except Exception:
            pass
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--tokens", type=int, default=160)
    a = ap.parse_args()
    k = key()
    rows = []
    for _ in range(a.rounds):
        for i, p in enumerate(PROMPTS):
            for _w in range(20):
                if busy(k) == 0:
                    break
                time.sleep(1.5)
            t0 = time.time()
            r = call("/v1/chat/completions", k, {"model": "star-fast", "messages": [{"role": "user", "content": p}],
                                                  "temperature": 0, "max_tokens": a.tokens, "cache_prompt": False})
            t = r.get("timings", {})
            rows.append({"i": i, "gen": t.get("predicted_per_second", 0), "pp": t.get("prompt_per_second", 0),
                         "n": t.get("predicted_n", 0), "wall": time.time() - t0, "other_busy": busy(k)})
            print(f"{a.tag} p{i} gen {rows[-1]['gen']:.2f} tok/s  n {rows[-1]['n']}  pp {rows[-1]['pp']:.1f}  "
                  f"wall {rows[-1]['wall']:.1f}s  other_busy {rows[-1]['other_busy']}", flush=True)
    clean = [r["gen"] for r in rows if r["other_busy"] == 0]
    med = statistics.median(clean) if clean else 0
    print(f"RESULT {a.tag} median_gen {med:.2f} tok/s  mean {statistics.mean(clean) if clean else 0:.2f}  "
          f"clean {len(clean)}/{len(rows)}  load {open('/proc/loadavg').read().split()[0]}", flush=True)


if __name__ == "__main__":
    main()
