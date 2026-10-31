"""Night prompt pool with clean provenance, and decontamination against the held-out evaluation.

Training prompts are written by our own models only:
  - gemma-4-12b paraphrases of the Litha distill questions (distill questions.json `generated_paraphrases`); the
    agent-written questions, hand paraphrases and held-out paraphrases are never used as training text
  - Qwen3.5-9B questions/tasks generated from Roblox Creator Docs passages (gpu pilot queries-q9.jsonl, Apache-2.0
    model, CC-BY-4.0 docs); the passage is kept as the judge's reference
Held out (never trained, also removed by similarity): every evaluation prompt, every distill item that is in the
evaluation set or close to an evaluation prompt (all its phrasings), and prompts too close to any of them.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
from pathlib import Path

WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an the to in on of for and or is it i my me how do does can what with make get you your this that "
           "roblox studio please pls".split())


def words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def grams(text: str, n: int = 2) -> set[tuple]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))} or {tuple(w)}


def similar(a: str, b: str) -> bool:
    """Close enough to count as the same question (tuned to catch paraphrases, not topic neighbours)."""
    wa, wb = set(words(a)), set(words(b))
    if not wa or not wb:
        return False
    jac = len(wa & wb) / len(wa | wb)
    contain = len(wa & wb) / min(len(wa), len(wb))
    ga, gb = grams(a), grams(b)
    gj = len(ga & gb) / max(1, len(ga | gb))
    return jac >= 0.6 or gj >= 0.4 or (contain >= 0.85 and min(len(wa), len(wb)) >= 4)


def heldout_texts(qset: dict, eval_qs: dict, distill: dict) -> tuple[list[str], set[str]]:
    """All held-out phrasings and the distill item ids that must never be trained."""
    texts = [x["prompt"] for x in qset["items"]] + [q.get("prompt") or q.get("question", "") for q in
                                                    eval_qs.get("questions", [])]
    banned = {x["id"][2:] for x in qset["items"] if x["id"].startswith("d:")}
    for it in distill["items"]:
        if it["id"] in banned or any(similar(it["question"], t) for t in texts):
            banned.add(it["id"])
    for it in distill["items"]:
        if it["id"] in banned:
            texts += [it["question"]] + it.get("paraphrases", []) + it.get("held_out", []) + \
                it.get("generated_paraphrases", [])
    return [t for t in texts if t], banned


def build_pool(distill_path: str, queries_path: str, kb_path: str, qset_path: str, eval_path: str) -> dict:
    distill = json.load(open(distill_path, encoding="utf-8"))
    qset = json.load(open(qset_path, encoding="utf-8"))
    eval_qs = json.load(open(eval_path, encoding="utf-8"))
    held, banned = heldout_texts(qset, eval_qs, distill)
    held_words = [(t, set(words(t))) for t in held]
    pool, dropped = [], {"heldout_item": 0, "too_close": 0, "duplicate": 0}
    seen: set[str] = set()

    def close_to_heldout(text: str) -> bool:
        ws = set(words(text))
        return any(len(ws & hw) >= 2 and similar(text, t) for t, hw in held_words)

    def add(row: dict) -> None:
        key = " ".join(sorted(set(words(row["prompt"]))))
        if key in seen:
            dropped["duplicate"] += 1
            return
        if close_to_heldout(row["prompt"]):
            dropped["too_close"] += 1
            return
        seen.add(key)
        row["pid"] = hashlib.sha256(row["prompt"].encode()).hexdigest()[:16]
        pool.append(row)

    for it in distill["items"]:
        if it["id"] in banned:
            dropped["heldout_item"] += len(it.get("generated_paraphrases", []))
            continue
        for p in it.get("generated_paraphrases", []):
            add({"prompt": p, "group": "d:" + it["id"], "source": "gemma-4-12b paraphrase (distill)",
                 "category": it.get("category", "")})
    texts = {}
    if kb_path and Path(kb_path).exists():
        con = sqlite3.connect(kb_path)
        texts = dict(con.execute("select text_sha, text from chunks"))
    for line in open(queries_path, encoding="utf-8"):
        r = json.loads(line)
        if not r.get("ok"):
            continue
        for field in ("question", "task"):
            if r.get(field):
                add({"prompt": r[field], "group": "q:" + r["text_sha"][:16], "source": "Qwen3.5-9B docs " + field,
                     "category": "roblox", "reference": texts.get(r["text_sha"], "")[:3000],
                     "doc": r.get("path", "")})
    return {"pool": pool, "dropped": dropped, "heldout_texts": len(held), "banned_items": sorted(banned)}


def parse_shard(text: str) -> tuple[int, int]:
    i, n = (int(x) for x in (text or "0/1").split("/"))
    return i, max(1, n)


def in_shard(pid: str, shard: tuple[int, int]) -> bool:
    if shard[1] <= 1:
        return True
    return int(hashlib.sha256(pid.encode()).hexdigest()[:8], 16) % shard[1] == shard[0]


def group_counts(prompts: list[dict]) -> dict:
    out: dict[str, int] = {}
    for p in prompts:
        k = p["group"].split(":")[0] + (":" + p["group"].split(":")[1] if p["group"].startswith("g:") else "")
        out[k] = out.get(k, 0) + 1
    return out


def night_sample(pool: list[dict], n: int, used: set[str], seed: int, distill_share: float = 0.5,
                 shard: tuple[int, int] = (0, 1), gap_share: float = 0.0) -> list[dict]:
    """n prompts not used before (and in this card's shard): gap-targeted prompts first (gap_share, spread evenly
    over the gap classes), then distill paraphrases (max 2 per item) and docs prompts sharing the rest."""
    rnd = random.Random(seed)
    fresh = [p for p in pool if p["pid"] not in used and in_shard(p["pid"], shard)]
    g = [p for p in fresh if p["group"].startswith("g:")]
    d = [p for p in fresh if p["group"].startswith("d:")]
    q = [p for p in fresh if p["group"].startswith("q:")]
    for x in (g, d, q):
        rnd.shuffle(x)
    picked: list[dict] = []
    classes: dict[str, list[dict]] = {}
    for p in g:
        classes.setdefault(p["group"], []).append(p)
    want_g = int(n * gap_share)
    while len(picked) < want_g and any(classes.values()):
        for k in sorted(classes):
            if classes[k] and len(picked) < want_g:
                picked.append(classes[k].pop())
    rest = n - len(picked)
    per: dict[str, int] = {}
    n_d = 0
    for p in d:
        if n_d >= int(rest * distill_share):
            break
        if per.get(p["group"], 0) < 2:
            per[p["group"]] = per.get(p["group"], 0) + 1
            picked.append(p)
            n_d += 1
    picked += q[: n - len(picked)]
    return picked


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="build the clean prompt pool")
    ap.add_argument("--distill", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--kb", default="")
    ap.add_argument("--qset", required=True, help="held-out evaluation set (litha-brain qset.json)")
    ap.add_argument("--eval", required=True, help="docs/agents/litha-eval/questions.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = build_pool(a.distill, a.queries, a.kb, a.qset, a.eval)
    Path(a.out).write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in res["pool"]) + "\n", encoding="utf-8")
    print(json.dumps({"pool": len(res["pool"]), "dropped": res["dropped"], "heldout_texts": res["heldout_texts"],
                      "banned_items": len(res["banned_items"])}))


if __name__ == "__main__":
    main()
