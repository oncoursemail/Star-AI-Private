"""A replay bench whose numbers can be trusted (docs/LITHA_AUTONOMY.md section 8).

Every case of the self-tune replay set (self_tune.cases(): STAR history, Metallic-Club/plateform history and the frozen
extra sets in cases-extra/, Studio excluded) is replayed K times with her model (replicates 0..K-1; answers cached by
case, replicate and prompt, so a rerun costs nothing). Per case the pass rate over the K runs is kept, and:

- score     mean pass rate over the cases, in percent;
- CI        95% bootstrap interval of the score (cases resampled with their K runs);
- MDE       the smallest true difference between two prompts/rules (same cases, K runs each) that a paired test at
            alpha 0.05 finds 80% of the time, given the run-to-run noise measured per case (within-case variance of
            the K runs). Printed for this K and for K=1, in percentage points and in cases;
- A/A       replicate 0 against replicate 1 of the same prompt: the change a no-op shows (must stay inside the MDE).

paired() compares two tables of the same cases: mean difference, paired bootstrap CI, sign-flip p and McNemar on
the per-case majority. The nightly gate (learn_nightly) keeps a change only when the paired CI is above 0.

    python -m litha.trusted_bench score [--k 3] [--cached]      score, CI, MDE (one line) + A/A
    python -m litha.trusted_bench freeze-extra --repo R --base B --clone DIR    frozen cases of a repo with no clone
                                                                                 where the bench runs (private repos)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from litha import self_tune as st

Z_ALPHA = 1.959964                    # two-sided alpha 0.05
Z_POWER = 0.841621                    # power 0.80
K = 3


def table(overrides: dict | None, cases_: list[dict], model, k: int = K, cache: st.Cache | None = None,
          lessons=None, log: Path | None = None) -> dict[str, list[bool]]:
    """{case id: [solved in replicate 0, 1, ..., k-1]} for every case."""
    cache = cache or st.Cache()
    out: dict[str, list[bool]] = {c["id"]: [] for c in cases_}
    for rep in range(k):
        res = st.score(overrides or {}, cases_, model, rep, cache, log=log, lessons=lessons)
        for cid, r in res["cases"].items():
            out[cid].append(r["outcome"] in st.GOOD)
    return out


def _rate(runs: list[bool]) -> float:
    return sum(runs) / len(runs) if runs else 0.0


def _var(runs: list[bool]) -> float:
    """Unbiased within-case variance of one case's K runs (0 for K=1: one run says nothing about its noise)."""
    k = len(runs)
    if k < 2:
        return 0.0
    m = _rate(runs)
    return m * (1 - m) * k / (k - 1)


def mde(tab: dict[str, list[bool]], k: int | None = None) -> float:
    """Minimum detectable effect, in percentage points, of a paired comparison with k runs per case on each side,
    from the per-case run-to-run variance measured in tab (k defaults to tab's own K)."""
    n = len(tab)
    if not n:
        return float("nan")
    k = k or max(len(v) for v in tab.values())
    var_mean_diff = sum(2 * _var(v) / k for v in tab.values()) / n ** 2
    return 100 * (Z_ALPHA + Z_POWER) * math.sqrt(var_mean_diff)


def _boot(values: list[float], boots: int, seed: int) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    rng, n, means = random.Random(seed), len(values), []
    for _ in range(boots):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * boots)], means[min(boots - 1, int(0.975 * boots))]


def summary(tab: dict[str, list[bool]], splits: dict[str, str] | None = None, boots: int = 2000,
            seed: int = 0) -> dict:
    """score, CI, MDE (this K and K=1) for all cases and for the held-out split."""
    def one(ids: list[str]) -> dict:
        sub = {c: tab[c] for c in ids}
        rates = [_rate(v) for v in sub.values()]
        lo, hi = _boot(rates, boots, seed)
        k = max((len(v) for v in sub.values()), default=0)
        m, m1 = mde(sub), mde(sub, 1)
        n = len(ids)
        return {"n": n, "k": k, "score": round(100 * sum(rates) / n, 2) if n else None,
                "ci": [round(100 * lo, 2), round(100 * hi, 2)], "mde_pp": round(m, 2), "mde_cases": round(m * n / 100, 1),
                "mde_k1_pp": round(m1, 2), "mde_k1_cases": round(m1 * n / 100, 1),
                "flaky": sum(0 < _rate(v) < 1 for v in sub.values())}
    out = one(list(tab))
    if splits:
        out["hold"] = one([c for c in tab if splits.get(c) == "hold"])
    if out["k"] >= 2:
        a = {c: v[:1] for c, v in tab.items()}
        b = {c: v[1:2] for c, v in tab.items()}
        aa = paired(a, b, boots=boots, seed=seed)
        out["aa"] = {"diff_pp": aa["diff_pp"], "discordant": aa["mcnemar"]["b"] + aa["mcnemar"]["c"],
                     "inside_mde": abs(aa["diff_pp"]) <= out["mde_k1_pp"]}
    return out


def _binom_two_sided(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired(old: dict[str, list[bool]], new: dict[str, list[bool]], boots: int = 2000, seed: int = 0,
           ids: list[str] | None = None) -> dict:
    """new - old on the same cases: mean difference (pp), 95% paired bootstrap CI, sign-flip p, McNemar on each
    case's majority; significant = the CI is above 0 (a gain beyond the noise)."""
    ids = [c for c in (ids or list(old)) if c in new and old[c] and new[c]]
    d = [_rate(new[c]) - _rate(old[c]) for c in ids]
    n = len(d)
    mean = sum(d) / n if n else 0.0
    lo, hi = _boot(d, boots, seed)
    rng, obs, hits = random.Random(seed + 1), abs(sum(d)), 0
    nz = [x for x in d if x]
    for _ in range(boots):
        hits += abs(sum(x if rng.random() < 0.5 else -x for x in nz)) >= obs - 1e-12
    b = sum(_rate(old[c]) >= 0.5 > _rate(new[c]) for c in ids)        # good -> bad
    c_ = sum(_rate(old[c]) < 0.5 <= _rate(new[c]) for c in ids)       # bad -> good
    return {"n": n, "diff_pp": round(100 * mean, 2), "ci": [round(100 * lo, 2), round(100 * hi, 2)],
            "p": round(hits / boots, 4) if nz else 1.0, "mcnemar": {"b": b, "c": c_, "p": round(_binom_two_sided(b, c_), 4)},
            "significant": bool(n) and lo > 0}


def line(s: dict) -> str:
    """The one line: score, CI, MDE."""
    out = (f"score {s['score']}% CI [{s['ci'][0]}, {s['ci'][1]}] MDE {s['mde_pp']} pp (~{s['mde_cases']} cases) at "
           f"K={s['k']} over {s['n']} cases; K=1: {s['mde_k1_pp']} pp")
    if "hold" in s:
        h = s["hold"]
        out += f"; held-out {h['score']}% CI [{h['ci'][0]}, {h['ci'][1]}] MDE {h['mde_pp']} pp ({h['n']} cases)"
    if "aa" in s:
        out += f"; A/A rep0 vs rep1 {s['aa']['diff_pp']:+} pp ({s['aa']['discordant']} cases differ)"
    return out


def freeze_extra(repo: str, base: str, clone: Path, out_dir: Path | None = None) -> list[dict]:
    """The history cases of a repo the bench machine cannot clone (private), frozen with their commit time ("at"),
    so the bench and the nightly gate replay them like the others; never a repo in self_tune.EXCLUDED."""
    if repo in st.EXCLUDED:
        raise ValueError(f"{repo} is excluded: {st.EXCLUDED[repo]}")
    got = st.history(repo, base, clone)
    shas = sorted({c["commit"] for c in got if c.get("commit")})
    times = {}
    for k in range(0, len(shas), 200):
        r = st.git(clone, "log", "--no-walk", "--format=%H %ct", *shas[k:k + 200])
        times.update(ln.split() for ln in r.stdout.splitlines() if len(ln.split()) == 2)
    for c in got:
        if c.get("commit") in times:
            c["at"] = int(times[c["commit"]])
    folder = out_dir or st.EXTRA
    folder.mkdir(parents=True, exist_ok=True)
    st.pf.write_atomic(folder / f"{repo.replace('/', '__')}.json",
                       json.dumps({"built": int(time.time()), "repo": repo, "cases": got}, ensure_ascii=False))
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.trusted_bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="every case K times: score, CI, MDE")
    s.add_argument("--k", type=int, default=K)
    s.add_argument("--cached", action="store_true", help="read the answer cache only (no model call)")
    s.add_argument("--node", action="store_true", help="her model straight on the GPU node (Brain One)")
    f = sub.add_parser("freeze-extra", help="freeze a repo's history cases into cases-extra/")
    f.add_argument("--repo", required=True)
    f.add_argument("--base", default="main")
    f.add_argument("--clone", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "freeze-extra":
        got = freeze_extra(a.repo, a.base, a.clone)
        print(json.dumps({"repo": a.repo, "cases": len(got), "with_answer": sum(c["good"] is not None for c in got)}))
        return 0
    cases_ = st.cases()
    if a.cached:
        model = st.cached_only
    elif a.node:
        from litha import learn_nightly
        model = learn_nightly.node_model()
    else:
        model = st.pf.ask
    t = time.time()
    tab = table({}, cases_, model, a.k, st.Cache(), log=st.RUNS)
    s_ = summary(tab, {c["id"]: c.get("split", "tune") for c in cases_})
    s_["seconds"] = round(time.time() - t)
    print(line(s_))
    print(json.dumps(s_))
    return 0


if __name__ == "__main__":
    sys.exit(main())
