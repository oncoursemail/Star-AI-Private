"""Recall@5 of the brain-vault questions through the ways STAR can reach the team's notes.

    python scripts/brain_vault_eval.py --vault <vault> [--questions server/knowledge/eval/vault-questions.jsonl]
                                       [--live http://<knowledge-service>:8091 --key-file ~/.star/server_api_key]

Arms:
  bridge  the opt-in Obsidian bridge (star/obsidian_bridge.py search) pointed at the vault: keyword ranking, no index
  live    the live public knowledge index, which does not contain the notes (the "without the vault" arm; the key is
          read from the file and never printed)
For the private knowledge corpus (bm25 / vector / hybrid) use the service's own evaluator, which reports the same
numbers: python -m starkb --db private.sqlite3 eval --questions eval/vault-questions.jsonl --modes bm25,vector,hybrid
A question counts when any expected note is among the first 5 results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from star.obsidian_bridge import ObsidianVault  # noqa: E402


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("//")]


def score(ranked: list[list[str]], questions: list[dict], top: int) -> dict:
    ranks = []
    for paths, question in zip(ranked, questions):
        ranks.append(next((i for i, p in enumerate(paths[:top], 1) if p in question["expected"]), None))
    n = len(questions)
    return {"n": n, f"hits@{top}": sum(1 for r in ranks if r), f"recall@{top}": round(sum(1 for r in ranks if r) / n, 4),
            "recall@1": round(sum(1 for r in ranks if r == 1) / n, 4),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 4),
            "missed": [q["id"] for q, r in zip(questions, ranks) if not r]}


def run_bridge(vault: Path, questions: list[dict], top: int) -> dict:
    notes = ObsidianVault(vault)
    ranked, times = [], []
    for question in questions:
        started = time.perf_counter()
        found = notes.search(question["question"], limit=top)["notes"]
        times.append((time.perf_counter() - started) * 1000)
        ranked.append([n["path"] for n in found])
    return {**score(ranked, questions, top), "median_ms": round(statistics.median(times), 1)}


def run_live(url: str, key_file: Path, questions: list[dict], top: int) -> dict:
    key = key_file.read_text(encoding="utf-8").splitlines()[0].strip()
    ranked, times, sources = [], [], {}
    for question in questions:
        body = json.dumps({"query": question["question"], "top": top}).encode()
        request = urllib.request.Request(url.rstrip("/") + "/search", body,
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=60) as response:
            passages = json.load(response)["passages"]
        times.append((time.perf_counter() - started) * 1000)
        ranked.append([p["path"] for p in passages])
        for p in passages:
            sources[p["source"]] = sources.get(p["source"], 0) + 1
    return {**score(ranked, questions, top), "median_ms": round(statistics.median(times), 1), "result_sources": sources}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--questions", type=Path, default=ROOT / "server" / "knowledge" / "eval" / "vault-questions.jsonl")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--live", help="URL of the live knowledge service (the arm without the vault)")
    parser.add_argument("--key-file", type=Path, default=Path.home() / ".star" / "server_api_key")
    args = parser.parse_args()
    questions = load(args.questions)
    result = {"bridge": run_bridge(args.vault, questions, args.top)}
    if args.live:
        result["live"] = run_live(args.live, args.key_file, questions, args.top)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
