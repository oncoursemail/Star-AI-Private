#!/usr/bin/env python3
"""Greedy single-stream generation speed on Luau-heavy prompts, for comparing speculative-decoding configs.

  python3 specbench_luau.py --server http://127.0.0.1:8099 --prompts holdout.json --system-from bundle.json \
      --tag LABEL --out LABEL.json [--max-tokens 400]
  python3 specbench_luau.py --compare A.json B.json

Each prompt is sent once (temperature 0, top_k 1, fixed seed, no prompt cache so every config reads the same
prompt from scratch). Per prompt: generated tokens, the server's generation tok/s, draft tokens and accepted drafts,
and the sha256 of the text. --compare prints, per prompt, whether two runs wrote byte-identical text, and the overall
generation tok/s (tokens / generation seconds). Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def ask(server: str, system: str, prompt: str, max_tokens: int) -> dict:
    body = {"model": "star-fast", "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0, "top_k": 1, "seed": 42, "max_tokens": max_tokens, "cache_prompt": False}
    request = urllib.request.Request(server + "/v1/chat/completions", json.dumps(body).encode("utf-8"),
                                     {"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.loads(response.read())
    t = data.get("timings") or {}
    text = data["choices"][0]["message"].get("content") or ""
    return {"wall_s": round(time.monotonic() - started, 2), "gen_n": t.get("predicted_n"),
            "gen_ms": t.get("predicted_ms"), "gen_tps": t.get("predicted_per_second"),
            "prompt_n": t.get("prompt_n"), "prompt_tps": t.get("prompt_per_second"),
            "draft_n": t.get("draft_n"), "draft_accepted": t.get("draft_n_accepted"),
            "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], "text": text}


def overall(rows: list[dict]) -> dict:
    tokens = sum(r["gen_n"] or 0 for r in rows)
    ms = sum(r["gen_ms"] or 0 for r in rows)
    drafted = sum(r["draft_n"] or 0 for r in rows)
    accepted = sum(r["draft_accepted"] or 0 for r in rows)
    return {"tokens": tokens, "gen_tps": round(tokens / (ms / 1000), 2) if ms else None,
            "draft_n": drafted, "accepted": accepted, "accept_rate": round(accepted / drafted, 3) if drafted else None}


def run(args) -> int:
    prompts = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    system = json.loads(Path(args.system_from).read_text(encoding="utf-8"))["system"]
    rows = []
    for item in prompts:
        row = {"id": item["id"], **ask(args.server, system, item["prompt"], args.max_tokens)}
        rows.append(row)
        print(f"{args.tag} {row['id']:8} gen {row['gen_n']:4} tok {row['gen_tps'] or 0:6.2f} tok/s "
              f"draft {row['draft_accepted']}/{row['draft_n']} sha {row['sha']}", flush=True)
    summary = {"tag": args.tag, **overall(rows)}
    print("SUMMARY", json.dumps(summary), flush=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    return 0


def compare(a_path: str, b_path: str) -> int:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a_path, b_path))
    same = 0
    for ra, rb in zip(a["rows"], b["rows"]):
        equal = ra["text"] == rb["text"]
        same += equal
        where = ""
        if not equal:
            k = next((i for i, (x, y) in enumerate(zip(ra["text"], rb["text"])) if x != y),
                     min(len(ra["text"]), len(rb["text"])))
            where = f" first difference at char {k}: {ra['text'][k:k + 40]!r} vs {rb['text'][k:k + 40]!r}"
        print(f"{ra['id']:8} {'identical' if equal else 'DIFFERENT'} {ra['gen_tps']} -> {rb['gen_tps']} tok/s{where}")
    print(f"identical {same}/{len(a['rows'])}; {a['summary']['tag']} {a['summary']['gen_tps']} tok/s -> "
          f"{b['summary']['tag']} {b['summary']['gen_tps']} tok/s")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server")
    parser.add_argument("--prompts")
    parser.add_argument("--system-from")
    parser.add_argument("--tag", default="run")
    parser.add_argument("--out")
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--compare", nargs=2)
    args = parser.parse_args(argv)
    return compare(*args.compare) if args.compare else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
