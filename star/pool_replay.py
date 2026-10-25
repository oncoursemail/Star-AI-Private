"""M5 offline replay: score candidate-selection rules from stored answers at zero model cost.

    python -m star.pool_replay inspect --results work/eval-runs/qab-20261020/*.json ...
    python -m star.pool_replay replay  --results ... --budgets 2,3,4 --out replay.json
    python -m star.pool_replay fixes   --results ...            # Q7: ladder fix rounds vs a fresh sample
    python -m star.pool_replay grade   --pool DIR/pool-x.jsonl --suite S.json [server options]   # live pools only

(`python -m star.evals pool ...` is the same command.) Inputs are eval result files (one stored answer per task
per run: a "pool" of independent-enough samples of STAR on the same tasks) and, for live pools written with
`--pool DIR` (star/candidate_pool.py), the graded candidates of the check-fix ladder.

A selection rule sees only what STAR sees at answer time (the compile/type check, anti-slop score, answer text,
the ladder's rungs): never the task's hidden tests. The true grade is used only to score the choice. `oracle` (pick
a passing candidate if any) is the ceiling the rules are measured against, not a rule STAR can run.

For a budget N, every task contributes its expected pass rate under the rule, averaged over N-sized draws from that
task's pool (all draws when few, else 2000 seeded ones; the first drawn candidate plays "the sample STAR would
have written"). The baseline is `first`: the pass rate of one sample. Paired by task: bootstrap interval of the
mean change (star.eval_stats.bootstrap_ci), exact sign test on the tasks that changed, and the MDE for that many
tasks. A rule is called a clear win only if the 95 % interval is above 0 and the sign test passes Bonferroni
across the rules compared; anything else is "no clear difference" and never a reason to switch a setting on.
Caveat printed with every report: the pool's candidates come from different runs and settings of STAR, so they are
not exactly iid samples of one generator.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import lru_cache
import itertools
import json
import math
from pathlib import Path
import random
import re
import sys
from typing import Callable

from . import candidate_pool, eval_stats

MAX_DRAWS = 2000
_FENCE = re.compile(r"```[ \t]*(?:lua|luau)\b[^\n]*\n(.*?)```", re.S | re.I)
_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]|--[^\n]*", re.S)
_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\w\s]")
_UNIT_SHARE = re.compile(r"(\d+)/(\d+) passed")
CAVEAT = ("pool candidates are runs of different STAR settings on the same tasks, not exactly iid samples of one "
          "generator; the answer to 'does selection help' is a screen, not a promotion decision")


@dataclass
class Cand:
    task: str                          # "<suite file>:<task id>"
    source: str                        # run label (file) or "<tag>/<answer>" for a live pool
    passed: bool | None                # the true grade: hidden from rules
    view: dict = field(default_factory=dict)   # what STAR can see (compile_ok, slop_hard, slop, chars, ladder_ok ...)
    code: str = ""
    seconds: float = 0.0
    blocks: tuple = ()                 # the fenced Luau blocks of the answer (the ladder checks the first two)
    idx: int = 0                       # position in a ladder chain (0 = as the model wrote it)
    origin: str = "sample"             # sample | first | rewrite | fix


@dataclass(frozen=True)
class Seen:
    """A candidate as a rule sees it: no grade."""
    pos: int
    view: dict
    code: str


# --- reading stored result files ---------------------------------------------------------------------------------

def blocks_of(answer: str) -> list[str]:
    return [m.group(1) for m in _FENCE.finditer(answer or "")]


def _compile_ok(checks: list[dict]) -> bool | None:
    rows = [c for c in checks if str(c.get("id", "")).startswith(("luau_check", "luau_block"))]
    return all(c.get("ok") for c in rows) if rows else None


def _unit_share(checks: list[dict]) -> float | None:
    for c in checks:
        if c.get("id") == "unit_tests":
            found = _UNIT_SHARE.search(str(c.get("detail", "")))
            return int(found.group(1)) / int(found.group(2)) if found else (1.0 if c.get("ok") else 0.0)
    return None


def processed(run: dict, record: dict) -> bool:
    """True when this answer went through a repair loop after the model wrote it (so it is not a raw sample)."""
    settings = run.get("settings") or {}
    return bool(settings.get("verify_ladder") == "on" or settings.get("luau_retry_ladder") is True
                or settings.get("slop_check") == "repair"
                or any(e.get("event") == "verify_finished" for e in record.get("events", [])))


def load_results(paths, *, labels: dict | None = None) -> list[Cand]:
    """One Cand per scored task record of each eval result file."""
    out: list[Cand] = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "tasks" not in data or "suite" not in data:
            continue
        label = (labels or {}).get(str(path)) or f"{Path(path).parent.name}/{Path(path).stem}"
        run = data.get("run") or {}
        for tid, rec in data["tasks"].items():
            if rec.get("status") not in ("pass", "fail"):
                continue
            checks = rec.get("checks") or []
            slop = rec.get("slop") or {}
            ladder = next((e for e in rec.get("events", []) if e.get("event") == "verify_finished"), None)
            view = {"compile_ok": _compile_ok(checks), "slop": slop.get("score", 0), "slop_hard": bool(slop.get("hard")),
                    "chars": rec.get("answer_chars", 0), "processed": processed(run, rec),
                    "prompt": rec.get("prompt_sha256", ""), "unit_share": _unit_share(checks)}
            if ladder:
                view.update(ladder_ok=bool(ladder.get("verified")), ladder_rounds=int(ladder.get("rounds") or 0),
                            ladder_fixed=bool(ladder.get("fixed")))
            code = blocks_of(rec.get("answer", ""))
            out.append(Cand(f"{data['suite'].get('file')}:{tid}", label, rec["status"] == "pass", view,
                            "\n".join(code), float(rec.get("seconds") or 0.0), tuple(code)))
    return _consistent(out)


def _consistent(cands: list[Cand]) -> list[Cand]:
    """Per task keep only candidates asked the modal prompt (a suite edit between runs would mix tasks)."""
    by_task: dict[str, dict[str, int]] = {}
    for c in cands:
        by_task.setdefault(c.task, {}).setdefault(c.view.get("prompt", ""), 0)
        by_task[c.task][c.view.get("prompt", "")] += 1
    modal = {t: max(v, key=lambda prompt: v[prompt]) for t, v in by_task.items()}
    return [c for c in cands if c.view.get("prompt", "") == modal[c.task]]


def pools(cands: list[Cand], *, raw_only: bool = True, sources=None) -> dict[str, list[Cand]]:
    out: dict[str, list[Cand]] = {}
    for c in cands:
        if c.passed is None or (raw_only and c.view.get("processed")) or (sources and c.source not in sources):
            continue
        out.setdefault(c.task, []).append(c)
    return out


def offline_rungs(cands: list[Cand], suites_dir: Path | None = None) -> int:
    """Add what the ladder's two local rungs say about each stored answer (`api_ok`: real Roblox API members, local
    dump; `deprecated_ok`: Roblox's deprecated list). No server and no model: pure Python on the stored code. A
    candidate without a Luau block, or whose task prompt cannot be found unchanged, gets None. Returns how many
    candidates were checked."""
    from . import slop, verify_ladder
    root = Path(suites_dir) if suites_dir else Path("evals")       # run from the repo root
    prompts: dict[str, dict[str, str]] = {}
    dump = slop.bundled_api_dump()
    checked = 0
    for c in cands:
        suite, _, tid = c.task.partition(":")
        if suite not in prompts:
            found = next(iter(sorted(root.rglob(suite))), None)
            prompts[suite] = ({t["id"]: t["prompt"] for t in json.loads(found.read_text(encoding="utf-8"))}
                              if found else {})
        prompt = prompts[suite].get(tid, "")
        if not c.blocks or not prompt or candidate_pool.prompt_key(prompt) != c.view.get("prompt"):
            c.view.update(api_ok=None, deprecated_ok=None)
            continue
        tools = verify_ladder.Tools(dump=dump, prompt=prompt)
        rungs = [(verify_ladder.check_api(b, tools), verify_ladder.check_deprecated(b, tools))
                 for b in c.blocks[:verify_ladder.MAX_BLOCKS]]
        c.view.update(api_ok=all(a.status != "fail" for a, _ in rungs),
                      deprecated_ok=all(d.status != "fail" for _, d in rungs))
        checked += 1
    return checked


# --- selection rules ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _shingles(code: str) -> frozenset:
    tokens = _TOKEN.findall(_COMMENT.sub("", code))
    return frozenset(zip(tokens, tokens[1:], tokens[2:])) or frozenset(tokens)


@lru_cache(maxsize=None)
def _similar(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def _fails(c: Seen) -> bool:
    return c.view.get("compile_ok") is False or bool(c.view.get("slop_hard"))


def first(seen: list[Seen]) -> int:
    return 0


def verified_first(seen: list[Seen]) -> int:
    """Sequential resample: stop at the first candidate whose compile/type check and anti-slop check are clean."""
    return next((i for i, c in enumerate(seen) if not _fails(c)), 0)


def verified_rank(seen: list[Seen]) -> int:
    """All N written, then the cleanest one: no compile error, no hard slop, lowest slop score, earliest."""
    return min(range(len(seen)), key=lambda i: (_fails(seen[i]), seen[i].view.get("slop", 0), i))


def static_fails(c: Seen) -> int:
    """How many of the ladder's first three rungs (compile, real API, deprecated) this candidate fails."""
    return sum(c.view.get(k) is False for k in ("compile_ok", "api_ok", "deprecated_ok"))


def ladder_first(seen: list[Seen]) -> int:
    """Sequential resample on the ladder's own static rungs: the first candidate that clears compile, API, deprecated."""
    return next((i for i, c in enumerate(seen) if not static_fails(c)), 0)


def ladder_rank_pick(seen: list[Seen]) -> int:
    """All N written, then the one that clears the most static rungs, then the lowest slop score, then the earliest."""
    return min(range(len(seen)), key=lambda i: (static_fails(seen[i]), seen[i].view.get("slop", 0), i))


def compile_first(seen: list[Seen]) -> int:
    """Sequential resample on the compile/type check alone (no candidate that compiled has ever failed it: see
    signal_report); the real-API rung flags many answers that pass, so this leaves it out."""
    return next((i for i, c in enumerate(seen) if c.view.get("compile_ok") is not False), 0)


def consensus(seen: list[Seen], *, only_clean: bool = False) -> int:
    """The candidate most similar to the others (token 3-gram Jaccard of the code): the largest cluster's centre.
    Textual agreement, not behavioural: identical wrong answers win. `only_clean` drops compile/slop failures."""
    pool = [i for i in range(len(seen)) if not (only_clean and _fails(seen[i]))] or list(range(len(seen)))
    sets = {i: _shingles(seen[i].code) for i in pool}
    return max(pool, key=lambda i: (sum(_similar(sets[i], sets[j]) for j in pool if j != i), -i))


def consensus_clean(seen: list[Seen]) -> int:
    return consensus(seen, only_clean=True)


RULES: dict[str, Callable[[list[Seen]], int]] = {
    "verified_first": verified_first, "verified_rank": verified_rank, "compile_first": compile_first,
    "ladder_first": ladder_first, "ladder_rank": ladder_rank_pick, "consensus": consensus, "consensus_clean": consensus_clean,
}
SEQUENTIAL = (verified_first, compile_first, ladder_first, "oracle")    # stop at the first acceptable draw: fewer generations


# --- replay -------------------------------------------------------------------------------------------------------

def _draws(m: int, n: int, rng: random.Random):
    """Ordered draws of n of m candidates: every ordering when there are few, else 2000 seeded ones. The order
    matters: the first drawn candidate is the one STAR would have written first."""
    if math.perm(m, n) <= MAX_DRAWS:
        yield from itertools.permutations(range(m), n)
        return
    for _ in range(MAX_DRAWS):
        yield rng.sample(range(m), n)


def expected(cands: list[Cand], rule: Callable[[list[Seen]], int] | str, n: int, seed: int = 0) -> tuple[float, float]:
    """(expected pass rate, expected generations used) of `rule` for budget n on one task's pool. `oracle` picks a
    passing candidate when the draw has one."""
    rng = random.Random(f"{seed}:{cands[0].task}:{n}")
    wins = used = total = 0
    for order in _draws(len(cands), n, rng):
        drawn = [cands[i] for i in order]
        if isinstance(rule, str):                      # "oracle"
            pick = next((i for i, c in enumerate(drawn) if c.passed), 0)
        else:
            pick = rule([Seen(p, c.view, c.code) for p, c in enumerate(drawn)])
        wins += bool(drawn[pick].passed)
        used += pick + 1 if rule in SEQUENTIAL else n
        total += 1
    return wins / total, used / total


def compare(rule_by_task: dict[str, float], base_by_task: dict[str, float], *, alpha: float = 0.05) -> dict:
    """Paired by task: mean pass of each, mean change with a 95 % bootstrap interval, sign test on changed tasks."""
    ids = sorted(set(rule_by_task) & set(base_by_task))
    diffs = [rule_by_task[t] - base_by_task[t] for t in ids]
    wins = sum(d > 1e-9 for d in diffs)
    losses = sum(d < -1e-9 for d in diffs)
    test = eval_stats.sign_test(wins, losses)
    low, high = eval_stats.bootstrap_ci(diffs, seed=0, n_boot=4000, level=0.95)
    n = len(ids)
    mde = eval_stats.minimum_detectable_effect(n, 1).effect_tasks if n else None
    return {"tasks": n, "rule": round(sum(rule_by_task[t] for t in ids) / n, 4) if n else None,
            "base": round(sum(base_by_task[t] for t in ids) / n, 4) if n else None,
            "delta": round(sum(diffs) / n, 4) if n else 0.0, "ci95": [round(low, 4), round(high, 4)],
            "task_wins": wins, "task_losses": losses, "p_better": round(test["p_better"], 4),
            "p_worse": round(test["p_worse"], 4), "mde_tasks": mde}


def verdict(row: dict, alpha: float) -> str:
    if row["ci95"][0] > 0 and row["p_better"] <= alpha:
        return "CLEAR WIN"
    if row["ci95"][1] < 0 and row["p_worse"] <= alpha:
        return "CLEAR LOSS"
    return "no clear difference"


def replay(by_task: dict[str, list[Cand]], budgets: list[int], *, rules=None, seed: int = 0) -> dict:
    """The full table: for each budget, every rule against `first`, plus the oracle ceiling."""
    rules = rules or RULES
    base = {t: sum(bool(c.passed) for c in cs) / len(cs) for t, cs in by_task.items() if cs}
    alpha = 0.05 / max(1, len(rules) * len(budgets))
    report: dict = {"tasks_with_candidates": len(base), "candidates": sum(len(v) for v in by_task.values()),
                    "mixed_tasks": sum(1 for cs in by_task.values() if 0 < sum(bool(c.passed) for c in cs) < len(cs)),
                    "first_mean": round(sum(base.values()) / len(base), 4) if base else None,
                    "alpha_per_rule": round(alpha, 4), "caveat": CAVEAT, "budgets": {}}
    for n in budgets:
        eligible = {t: cs for t, cs in by_task.items() if len(cs) >= n}
        rows: dict = {}
        base_n = {t: base[t] for t in eligible}
        for name, fn in (*rules.items(), ("oracle", "oracle")):
            picked = {t: expected(cs, fn, n, seed) for t, cs in eligible.items()}
            row = compare({t: v[0] for t, v in picked.items()}, base_n, alpha=alpha)
            row["generations"] = round(sum(v[1] for v in picked.values()) / len(picked), 2) if picked else None
            row["verdict"] = "ceiling (not a rule)" if name == "oracle" else verdict(row, alpha)
            rows[name] = row
        report["budgets"][str(n)] = {"tasks": len(eligible), "rules": rows}
    return report


def leave_one_out(cands: list[Cand], rule: str, budget: int, *, raw_only: bool = True, seed: int = 0) -> dict:
    """The rule's paired change against `first` at one budget with each source (run file) left out in turn: does one
    run carry the result? Returns {"all": row, "<source>": row, ...} (rows as `compare`)."""
    fn = RULES[rule]
    sources = sorted({c.source for c in cands})
    out = {}
    for drop in [None, *sources]:
        by_task = pools(cands, raw_only=raw_only, sources={s for s in sources if s != drop})
        eligible = {t: cs for t, cs in by_task.items() if len(cs) >= budget}
        base = {t: sum(bool(c.passed) for c in cs) / len(cs) for t, cs in eligible.items()}
        out["all" if drop is None else drop] = compare({t: expected(cs, fn, budget, seed)[0] for t, cs in eligible.items()}, base)
    return out


def signal_report(by_task: dict[str, list[Cand]]) -> dict:
    """How well each thing STAR can see predicts a pass: pass rate of candidates with and without it (Wilson 95 %)."""
    rows = {}
    flat = [c for cs in by_task.values() for c in cs]

    def rate(label: str, group: list[Cand]) -> None:
        passed = sum(bool(c.passed) for c in group)
        low, high = eval_stats.wilson_interval(passed, len(group))
        rows[label] = {"n": len(group), "pass": passed, "rate": round(passed / len(group), 3) if group else None,
                       "ci95": [round(low, 3), round(high, 3)]}
    rate("all", flat)
    for label, test in (("compile_ok", lambda c: c.view.get("compile_ok") is True),
                        ("compile_fail", lambda c: c.view.get("compile_ok") is False),
                        ("api_fail", lambda c: c.view.get("api_ok") is False),
                        ("api_ok", lambda c: c.view.get("api_ok") is True),
                        ("deprecated_fail", lambda c: c.view.get("deprecated_ok") is False),
                        ("slop_hard", lambda c: bool(c.view.get("slop_hard"))),
                        ("slop_clean", lambda c: not c.view.get("slop_hard")),
                        ("clean (compile ok, no hard slop)", lambda c: not (c.view.get("compile_ok") is False
                                                                          or c.view.get("slop_hard")))):
        group = [c for c in flat if test(c)]
        if group:
            rate(label, group)
    return rows


# --- Q7: a ladder fix round or a fresh sample ----------------------------------------------------------------------

def fix_vs_resample(all_cands: list[Cand], *, seed: int = 0) -> dict:
    """Stored runs with the ladder on: for each task where the ladder made a fix call, did the fixed answer pass, and
    how often does a fresh sample of that task pass (raw samples from other runs, never the same run)? The fresh
    sample is either one unchecked draw (`resample1`) or up to two draws with the first clean one kept
    (`resample2_verified`: STAR's own compile/slop check as the filter). Paired by task."""
    fixed_runs = [c for c in all_cands if c.view.get("ladder_rounds", 0) > 0 and c.passed is not None]
    raw = pools(all_cands, raw_only=True)
    fix, one, two, used, rows = {}, {}, {}, [], []
    every, every_first, every_static = {}, {}, {}        # every task of every ladder-on run, fix call or not
    for c in all_cands:
        others = [r for r in raw.get(c.task, []) if r.source != c.source]
        if "ladder_ok" in c.view and c.passed is not None and len(others) >= 2:
            key = f"{c.task}@{c.source}"
            every[key] = float(bool(c.passed))
            every_first[key] = sum(bool(r.passed) for r in others) / len(others)
            every_static[key] = expected(others, ladder_first, 2, seed)[0]
    for c in fixed_runs:
        others = [r for r in raw.get(c.task, []) if r.source != c.source]
        if len(others) < 2:
            continue
        key = f"{c.task}@{c.source}"
        fix[key] = float(bool(c.passed))
        one[key] = sum(bool(r.passed) for r in others) / len(others)
        two[key] = expected(others, verified_first, 2, seed)[0]
        used.append(c)
        rows.append({"task": c.task, "run": c.source, "fix_passed": bool(c.passed), "fix_accepted": c.view.get("ladder_fixed"),
                     "rounds": c.view.get("ladder_rounds"), "fresh_pass_rate": round(one[key], 2), "fresh_n": len(others)})
    return {"fix_calls_tasks": len(fix), "fix_pass": sum(fix.values()),
            "fix_accepted": sum(1 for c in used if c.view.get("ladder_fixed")),
            "vs_resample1": compare(fix, one), "vs_resample2_verified": compare(fix, two), "rows": rows,
            "all_ladder_tasks": {"tasks": len(every), "vs_one_raw_sample": compare(every, every_first),
                                 "vs_resample_on_static_failure": compare(every, every_static)},
            "note": "fix = ladder answer after >=1 fix call (any outcome); the fresh-sample pools exclude that run. "
                    + CAVEAT}


# --- live pools: grading and chains ----------------------------------------------------------------------------------

def grade_pool(pool_file: Path, suite_tasks: list[dict], scorer, out: Path, *, log=print) -> int:
    """Score every candidate of a live pool with the task's own checks (`scorer(task, answer) -> TaskScore`). One
    line per candidate in `out`, resumable. Returns the number scored now."""
    by_prompt = {candidate_pool.prompt_key(t["prompt"]): t for t in suite_tasks}
    records = candidate_pool.read_lines(pool_file)
    answers = {r["answer_id"]: r for r in records if r["kind"] == "answer"}
    done = set()
    if Path(out).is_file():
        done = {(r["source"], r["answer_id"], r.get("block", 0), r["idx"])
                for r in candidate_pool.read_lines(out) if r["kind"] == "grade"}
    scored = 0
    for r in records:
        if r["kind"] != "candidate":
            continue
        key = (r["source"], r["answer_id"], r.get("block", 0), r["idx"])
        task = by_prompt.get(r["prompt_sha256"])
        if key in done or task is None:
            continue
        if r["source"] == "ladder":
            raw = answers.get(r["answer_id"])
            if raw is None:
                continue
            text = candidate_pool.rebuild_answer(raw["answer"], raw["blocks"], r["block"], r["code"])
        else:
            text = r.get("answer", "")
        try:
            score = scorer(task, text)
        except Exception as exc:                      # infrastructure, not a wrong answer: leave it ungraded
            log(f"{task['id']} #{r['idx']}: not graded ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        with Path(out).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema": candidate_pool.SCHEMA, "kind": "grade", "source": r["source"],
                                     "answer_id": r["answer_id"], "block": r.get("block", 0), "idx": r["idx"],
                                     "task": task["id"], "passed": bool(score.passed),
                                     "reasons": list(score.reasons)[:3]}) + "\n")
        scored += 1
    return scored


def load_chains(pool_file: Path, grades_file: Path) -> list[list[Cand]]:
    """The graded ladder versions of every (answer, block): [version 0 (as written), 1, 2 ...]."""
    grades = {(r["source"], r["answer_id"], r.get("block", 0), r["idx"]): r
              for r in candidate_pool.read_lines(grades_file) if r["kind"] == "grade"}
    chains: dict[tuple, list[Cand]] = {}
    for r in candidate_pool.read_lines(pool_file):
        if r["kind"] != "candidate" or r["source"] != "ladder":
            continue
        grade = grades.get(("ladder", r["answer_id"], r.get("block", 0), r["idx"]))
        view = {"ladder_ok": r["ok"], "rank": tuple(r["rank"]), "accepted": r["accepted"], "compile_ok": next(
            (x["status"] == "pass" for x in r["rungs"] if x["rung"] == "compile"), None)}
        chains.setdefault((r["answer_id"], r.get("block", 0)), []).append(
            Cand(f"{r['prompt_sha256']}:{r.get('block', 0)}", r["answer_id"], grade["passed"] if grade else None, view,
                 r["code"], float(r.get("fix_seconds") or 0.0), idx=r["idx"], origin=r["origin"]))
    return [sorted(v, key=lambda c: c.idx) for v in chains.values()]


def chain_policies(chains: list[list[Cand]]) -> dict:
    """Over graded chains: the pass rate of keeping `first` (no fix), the ladder's own `best` (the accepted version
    with the highest rank), the `last` version and the `oracle` (any version passes), paired against `first`."""
    chains = [c for c in chains if c and all(x.passed is not None for x in c)]
    key = lambda i, ch: f"{ch[0].source}:{ch[0].task}"      # noqa: E731
    first_ = {key(i, ch): float(bool(ch[0].passed)) for i, ch in enumerate(chains)}
    best = {key(i, ch): float(bool(max((x for x in ch if x.view.get("accepted")), key=lambda x: (x.view["rank"], x.idx)
                                       ).passed)) for i, ch in enumerate(chains)}
    last = {key(i, ch): float(bool(ch[-1].passed)) for i, ch in enumerate(chains)}
    oracle = {key(i, ch): float(any(x.passed for x in ch)) for i, ch in enumerate(chains)}
    return {"chains": len(chains), "with_fix_rounds": sum(1 for c in chains if len(c) > 1),
            **{name: compare(values, first_) for name, values in (("best_vs_first", best), ("last_vs_first", last),
                                                                   ("oracle_vs_first", oracle))}}


# --- text report --------------------------------------------------------------------------------------------------

def text_report(rep: dict) -> str:
    lines = [f"pool: {rep['tasks_with_candidates']} tasks, {rep['candidates']} candidates, {rep['mixed_tasks']} mixed "
             f"(some pass, some fail); one sample passes {rep['first_mean']:.1%} of the time",
             f"Bonferroni alpha per comparison {rep['alpha_per_rule']} (rules x budgets); {rep['caveat']}"]
    for n, block in rep["budgets"].items():
        lines.append(f"\nbudget N={n} ({block['tasks']} tasks with >= {n} candidates)")
        lines.append(f"  {'rule':16} {'pass':>6} {'base':>6} {'delta':>7} {'95% interval':>18} {'W/L':>7} {'p(better)':>9} "
                     f"{'gens':>5}  verdict")
        for name, r in block["rules"].items():
            lines.append(f"  {name:16} {r['rule']:6.3f} {r['base']:6.3f} {r['delta']:+7.3f} "
                         f"{r['ci95'][0]:+8.3f}..{r['ci95'][1]:+7.3f} {r['task_wins']:>3}/{r['task_losses']:<3} "
                         f"{r['p_better']:9.4f} {r['generations']:5.1f}  {r['verdict']}")
    return "\n".join(lines)


# --- command line -------------------------------------------------------------------------------------------------

def _paths(patterns: list[str]) -> list[Path]:
    import glob
    found: list[Path] = []
    for pattern in patterns:
        found.extend(Path(p) for p in sorted(glob.glob(pattern)))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.pool_replay")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "replay", "fixes"):
        p = sub.add_parser(name)
        p.add_argument("--results", nargs="+", required=True, help="eval result files or globs")
        p.add_argument("--include-processed", action="store_true",
                       help="also use answers that went through a repair loop (default: raw samples only)")
        p.add_argument("--out", type=Path)
        p.add_argument("--no-offline-rungs", action="store_true",
                       help="skip the local API and deprecated-API rungs on the stored code")
        if name == "replay":
            p.add_argument("--budgets", default="2,3,4")
            p.add_argument("--seed", type=int, default=0)
            p.add_argument("--leave-one-out", metavar="RULE", choices=sorted(RULES),
                           help="also print RULE's change at the first budget with each source left out in turn")
    grade = sub.add_parser("grade", help="score a live pool's candidates with the task's own checks (uses the server)")
    from .eval_runner import add_common
    add_common(grade)
    grade.add_argument("--pool", required=True, type=Path)
    grade.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "grade":
        from .eval_runner import build_real, load_suite
        suite = load_suite(args.suite)
        args._suite = suite
        _info, _ask, scorer, _probe, _secrets = build_real(args)
        print(f"graded {grade_pool(args.pool, suite.runnable(), scorer, args.out)} candidates")
        return 0
    cands = load_results(_paths(args.results))
    by_task = pools(cands, raw_only=not args.include_processed)
    if not args.no_offline_rungs:
        offline_rungs([c for cs in by_task.values() for c in cs])
    if args.command == "inspect":
        sizes: dict[int, int] = {}
        for cs in by_task.values():
            sizes[len(cs)] = sizes.get(len(cs), 0) + 1
        print(json.dumps({"records": len(cands), "sources": sorted({c.source for c in cands}),
                          "tasks_with_raw_samples": len(by_task), "pool_size_histogram": dict(sorted(sizes.items())),
                          "signals": signal_report(by_task)}, indent=1))
        return 0
    if args.command == "fixes":
        result = fix_vs_resample(cands)
    else:
        result = replay(by_task, [int(x) for x in args.budgets.split(",") if x], seed=args.seed)
        result["signals"] = signal_report(by_task)
        print(text_report(result))
        if args.leave_one_out:
            budget = int(args.budgets.split(",")[0])
            result["leave_one_out"] = {"rule": args.leave_one_out, "budget": budget,
                                       "rows": leave_one_out(cands, args.leave_one_out, budget, raw_only=not args.include_processed,
                                                             seed=args.seed)}
            print(f"\nleave-one-source-out: {args.leave_one_out} at N={budget}")
            for name, row in result["leave_one_out"]["rows"].items():
                print(f"  {name:52} {row['delta']:+.3f}  [{row['ci95'][0]:+.3f}, {row['ci95'][1]:+.3f}]  "
                      f"{row['task_wins']}/{row['task_losses']}  p={row['p_better']}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    if args.command == "fixes":
        print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
