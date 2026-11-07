"""L1 (distribution distance) and L2 (likelihood probe) from prefill-only scoring with llama-score.

One scorer run per config reads every probe item once: the prefix (Star's prompt for the request under that config)
and the targets [GOOD, BAD twins...]. The reference (base) run also writes the top-K next-token distribution over
each GOOD answer; the candidate run reads it back and reports KL(base || cand) and top-1 agreement per token (L1).

L2 statistic: for each GOOD answer i and twin j, margin m_ij = logp(GOOD_i) - logp(BAD_ij) (summed over the answer's
tokens, so a one-token defect is judged at the defect). The change's effect is the mean of m_cand - m_base over the
correctness twins (bugs and invented API), with a bootstrap interval over GOOD answers (twins of one answer are not
independent). Slop twins are reported per kind only: their margins are many times larger (the twin adds whole
sentences) and would swamp the correctness signal in a pooled mean.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import random
import subprocess
import time

from . import prompts
from .config import Config
from .probe import CORRECTNESS_KINDS, KINDS, Pair


def items_for(cfg: Config, pairs: list[Pair]) -> list[dict]:
    return [{"id": p.id, "prefix": prompts.prefix(cfg, p.prompt, exclude_answer=p.good),
             "targets": [prompts.target(cfg, p.good), *(prompts.target(cfg, b["text"]) for b in p.bads)]}
            for p in pairs]


def run_scorer(cfg: Config, items: list[dict], workdir: Path, *, topk: int = 0, ref: Path | None = None,
               log=print) -> tuple[list[dict], dict]:
    """Score items with cfg's model; returns (rows, cost) where cost has seconds and token counts."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    src, out = workdir / f"{cfg.name}.items.jsonl", workdir / f"{cfg.name}.scores.jsonl"
    src.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    cmd = [cfg.tool("llama-score"), "-m", cfg.model, "--in", str(src), "--out", str(out), "-ngl", str(cfg.ngl),
           "-c", str(cfg.ctx)]
    for path in cfg.lora:
        cmd += ["--lora", path]
    if cfg.threads:
        cmd += ["-t", str(cfg.threads)]
    if topk:
        cmd += ["--topk", str(topk)]
    if ref is not None:
        cmd += ["--ref", str(ref)]
    log(f"oracle: scoring {len(items)} items with {cfg.name}")
    started = time.monotonic()
    with open(workdir / f"{cfg.name}.scorer.log", "w", encoding="utf-8") as err:
        done = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=err,
                              env={**os.environ, **cfg.launch.get("env", {})})
    seconds = time.monotonic() - started
    if done.returncode != 0:
        raise RuntimeError(f"llama-score failed for {cfg.name} (exit {done.returncode}); see {err.name}")
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    tokens = sum(r["n_prefix"] + sum(t.get("n", 0) for t in r["targets"]) for r in rows)
    scored = sum(t.get("n", 0) for r in rows for t in r["targets"])
    return rows, {"seconds": round(seconds, 1), "tokens": tokens, "target_tokens": scored, "items": len(rows),
                  "scores": str(out)}


def margins(pairs: list[Pair], rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """pair id -> [(kind, logp(GOOD) - logp(BAD))] for every twin both texts of which were scored."""
    by_id = {r["id"]: r for r in rows}
    out: dict[str, list[tuple[str, float]]] = {}
    for p in pairs:
        r = by_id.get(p.id)
        if r is None or "sum_logprob" not in r["targets"][0]:
            continue
        good = r["targets"][0]["sum_logprob"]
        out[p.id] = [(b["kind"], good - t["sum_logprob"]) for b, t in zip(p.bads, r["targets"][1:])
                     if "sum_logprob" in t]
    return out


def bootstrap_mean_ci(groups: list[list[float]], *, level: float = 0.90, n_boot: int = 2000,
                      seed: int = 0) -> tuple[float, float, float]:
    """(mean, low, high) of the pooled mean, resampling whole groups."""
    flat = [x for g in groups for x in g]
    if not flat:
        return 0.0, 0.0, 0.0
    mean = sum(flat) / len(flat)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        pick = [groups[rng.randrange(len(groups))] for _ in groups]
        values = [x for g in pick for x in g]
        if values:
            stats.append(sum(values) / len(values))
    stats.sort()
    lo = stats[int((1 - level) / 2 * len(stats))]
    hi = stats[min(len(stats) - 1, int((1 + level) / 2 * len(stats)))]
    return mean, lo, hi


def l2_report(pairs: list[Pair], base_rows: list[dict], cand_rows: list[dict], *, kinds=None) -> dict:
    """Mean margin per arm, the paired change with a bootstrap interval (over `kinds`, default the correctness
    kinds), and the mean change per defect kind (all kinds)."""
    mb, mc = margins(pairs, base_rows), margins(pairs, cand_rows)
    allowed = set(kinds or CORRECTNESS_KINDS)
    groups, per_kind = [], {k: [] for k in KINDS}
    base_all, cand_all = [], []
    for pid in sorted(set(mb) & set(mc)):
        diffs = []
        for (kind, b), (kind2, c) in zip(mb[pid], mc[pid]):
            if kind != kind2:
                continue
            per_kind[kind].append(c - b)
            if kind not in allowed:
                continue
            diffs.append(c - b)
            base_all.append(b)
            cand_all.append(c)
        if diffs:
            groups.append(diffs)
    mean, lo, hi = bootstrap_mean_ci(groups)
    n = len(base_all)
    return {"answers": len(groups), "twins": n,
            "base_margin": round(sum(base_all) / n, 4) if n else None,
            "cand_margin": round(sum(cand_all) / n, 4) if n else None,
            "base_pref_acc": round(sum(x > 0 for x in base_all) / n, 4) if n else None,
            "cand_pref_acc": round(sum(x > 0 for x in cand_all) / n, 4) if n else None,
            "delta": round(mean, 4), "delta_ci90": [round(lo, 4), round(hi, 4)],
            "per_kind": {k: {"twins": len(v), "delta": round(sum(v) / len(v), 4)} for k, v in per_kind.items() if v}}


def l1_report(cand_rows: list[dict]) -> dict | None:
    """Mean KL(base || cand) per token and top-1 agreement over the GOOD answers (None without a reference)."""
    kl = agree = n = 0
    for r in cand_rows:
        t = r["targets"][0]
        if "kl_sum" in t:
            kl += t["kl_sum"]
            agree += t["agree"]
            n += t["n"]
    if not n:
        return None
    return {"tokens": n, "kl_per_token": round(kl / n, 6), "top1_agreement": round(agree / n, 5)}


def mean_logprob(rows: list[dict]) -> float:
    """Mean per-token log-probability of the GOOD answers (a perplexity-style sanity number)."""
    s = n = 0
    for r in rows:
        t = r["targets"][0]
        if "sum_logprob" in t:
            s += t["sum_logprob"]
            n += t["n"]
    return s / n if n else math.nan
