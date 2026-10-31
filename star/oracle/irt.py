"""L3: adaptive paired eval. An item-response model fitted on past eval runs picks the most informative tasks first;
a sequential test on the discordant pairs stops as soon as the answer is clear.

Item model (2PL): P(run r passes task t) = sigmoid(a_t * (theta_r - b_t)), fitted by penalised maximum likelihood on
every stored result file (each file = one run; errored tasks are missing data). theta = the run's ability, b = task
difficulty, a = discrimination. Priors keep a tiny history sane: theta ~ N(0, 1), b ~ N(0, 2^2), log a ~ N(0, 0.5^2).

Order: tasks by Fisher information a^2 p (1 - p) at the baseline's ability, i.e. tasks the baseline passes about half
the time and that separate strong runs from weak ones; those are the tasks where a pair is most likely to disagree.

Stopping (paired, interleaved: each task runs base then candidate): two one-sided SPRTs on the discordant pairs,
H0 P(win | discordant) = 0.5 against H1 0.75 (BETTER) and 0.25 (WORSE), Wald bounds A = (1 - beta) / alpha and
B = beta / (1 - alpha). BETTER or WORSE when one ratio crosses A; NO_CLEAR_DIFFERENCE when both are below B (a change
of the H1 size is unlikely); INCONCLUSIVE when the task budget runs out first, or early (futility) when even a
perfect finish could not make the exact sign test significant, i.e. the full suite would be INCONCLUSIVE too.
The exact sign test of
star.eval_stats on the same pairs is reported next to it; promotion still belongs to star.evals gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path

from .. import eval_stats

BETTER, WORSE, NO_DIFF, INCONCLUSIVE = "BETTER", "WORSE", "NO_CLEAR_DIFFERENCE", "INCONCLUSIVE"


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    z = math.exp(x)
    return z / (1 + z)


def task_key(suite_file: str, task_id: str) -> str:
    return f"{Path(suite_file).stem}:{task_id}"


def outcomes(result: dict) -> dict[str, bool]:
    """task key -> passed, for scored tasks of one runner result file (errors and skips are missing)."""
    suite = (result.get("suite") or {}).get("file", "")
    out = {}
    for tid, rec in (result.get("tasks") or {}).items():
        if rec.get("status") in ("pass", "fail"):
            out[task_key(suite, tid)] = rec["status"] == "pass"
    return out


def load_runs(paths) -> dict[str, dict[str, bool]]:
    """run name -> outcomes; a run = one result file (the file path is its name)."""
    runs = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        got = outcomes(data)
        if got:
            runs[str(path)] = got
    return runs


@dataclass
class ItemModel:
    theta: dict[str, float] = field(default_factory=dict)
    a: dict[str, float] = field(default_factory=dict)
    b: dict[str, float] = field(default_factory=dict)
    loglik: float = 0.0

    def p(self, theta: float, task: str) -> float:
        return _sigmoid(self.a[task] * (theta - self.b[task]))

    def information(self, theta: float, task: str) -> float:
        p = self.p(theta, task)
        return self.a[task] ** 2 * p * (1 - p)

    def ability(self, obs: dict[str, bool], iters: int = 200) -> float:
        """MAP ability of a new run with fixed items (N(0, 1) prior)."""
        theta = 0.0
        for _ in range(iters):
            grad, hess = -theta, -1.0
            for t, y in obs.items():
                if t in self.a:
                    p = self.p(theta, t)
                    grad += self.a[t] * (y - p)
                    hess -= self.a[t] ** 2 * p * (1 - p)
            step = grad / hess
            theta -= step
            if abs(step) < 1e-6:
                break
        return theta

    def to_dict(self) -> dict:
        return {"loglik": round(self.loglik, 3), "runs": {k: round(v, 3) for k, v in self.theta.items()},
                "tasks": {t: {"a": round(self.a[t], 3), "b": round(self.b[t], 3)} for t in sorted(self.a)}}


def fit(runs: dict[str, dict[str, bool]], *, iters: int = 400, lr: float = 0.05) -> ItemModel:
    """Penalised joint maximum likelihood by gradient ascent (small data: runs x tasks of a few thousand cells)."""
    tasks = sorted({t for obs in runs.values() for t in obs})
    m = ItemModel(theta={r: 0.0 for r in runs}, a={t: 1.0 for t in tasks}, b={t: 0.0 for t in tasks})
    for _ in range(iters):
        g_theta = {r: -m.theta[r] for r in runs}
        g_b = {t: -m.b[t] / 4 for t in tasks}
        g_loga = {t: -math.log(m.a[t]) / 0.25 for t in tasks}
        ll = 0.0
        for r, obs in runs.items():
            th = m.theta[r]
            for t, y in obs.items():
                a, b = m.a[t], m.b[t]
                p = _sigmoid(a * (th - b))
                ll += math.log(p if y else 1 - p) if 0 < p < 1 else -30.0
                e = (1.0 if y else 0.0) - p
                g_theta[r] += a * e
                g_b[t] -= a * e
                g_loga[t] += a * (th - b) * e
        for r in runs:
            m.theta[r] += lr * g_theta[r]
        for t in tasks:
            m.b[t] += lr * g_b[t]
            m.a[t] = min(4.0, max(0.1, math.exp(math.log(m.a[t]) + lr * g_loga[t])))
        m.loglik = ll
    return m


def order(model: ItemModel, theta: float, candidates) -> list[str]:
    """Candidate tasks, most informative first (unknown tasks last, in the given order)."""
    known = [t for t in candidates if t in model.a]
    unknown = [t for t in candidates if t not in model.a]
    return sorted(known, key=lambda t: (-model.information(theta, t), t)) + unknown


@dataclass
class Sequential:
    alpha: float = 0.05
    beta: float = 0.2
    q1: float = 0.75
    wins: int = 0
    losses: int = 0
    ties: int = 0

    def add(self, base: bool, cand: bool) -> None:
        if cand and not base:
            self.wins += 1
        elif base and not cand:
            self.losses += 1
        else:
            self.ties += 1

    def ratios(self) -> tuple[float, float]:
        """(LR for BETTER, LR for WORSE) against H0 = coin flip on discordant pairs."""
        up = self.wins * math.log(2 * self.q1) + self.losses * math.log(2 * (1 - self.q1))
        down = self.wins * math.log(2 * (1 - self.q1)) + self.losses * math.log(2 * self.q1)
        return math.exp(up), math.exp(down)

    def decision(self) -> str | None:
        upper, lower = (1 - self.beta) / self.alpha, self.beta / (1 - self.alpha)
        better, worse = self.ratios()
        if better >= upper:
            return BETTER
        if worse >= upper:
            return WORSE
        if better <= lower and worse <= lower:
            return NO_DIFF
        return None


def futile(wins: int, losses: int, done: int, remaining: int, *, alpha: float = 0.05, slack: float = 2.0) -> bool:
    """True when even an all-wins (or all-losses) finish cannot reach significance: the remaining tasks are assumed
    to give `slack` times as many discordant pairs as the rate so far (at least 2), and every one of them must go the
    same way. Then the full suite would end INCONCLUSIVE too, so running it is wasted brain time."""
    # The discordance rate so far, never below the gate's no-effect noise floor (1 pair in 6 disagrees): a run of
    # early ties must not look like "nothing will ever differ".
    rate = max((wins + losses + 1) / (done + 2), eval_stats.DEFAULT_NOISE_DISCORDANCE)
    extra = max(2, math.ceil(slack * rate * remaining))
    best = eval_stats.sign_test(wins + extra, losses)["p_better"]
    worst = eval_stats.sign_test(wins, losses + extra)["p_worse"]
    return best > alpha and worst > alpha


def run_adaptive(tasks: list[str], run_pair, *, max_tasks: int | None = None, min_tasks: int = 6,
                 futility_after: int = 12, seq: Sequential | None = None, log=lambda *_: None) -> dict:
    """Run tasks in the given order; run_pair(task) -> (base_pass, cand_pass) or None (errored: skipped).
    Stops at the first sequential decision after min_tasks, when the rest cannot change an INCONCLUSIVE outcome
    (futility, after futility_after tasks), or after max_tasks."""
    seq = seq or Sequential()
    trace = []
    decision = None
    stopped = ""
    planned = tasks[:max_tasks or len(tasks)]
    for index, task in enumerate(planned):
        got = run_pair(task)
        if got is None:
            trace.append({"task": task, "error": True})
            continue
        seq.add(*got)
        trace.append({"task": task, "base": got[0], "cand": got[1]})
        log(f"L3 {task}: base {'pass' if got[0] else 'fail'}, cand {'pass' if got[1] else 'fail'} "
            f"({seq.wins}W/{seq.losses}L/{seq.ties}T)")
        done = sum(1 for x in trace if "error" not in x)
        if done >= min_tasks:
            decision = seq.decision()
            if decision:
                break
        if futility_after and done >= futility_after and futile(seq.wins, seq.losses, done,
                                                                len(planned) - index - 1, alpha=seq.alpha):
            stopped = "futility: the remaining tasks cannot make this significant"
            break
    test = eval_stats.sign_test(seq.wins, seq.losses)
    return {"decision": decision or INCONCLUSIVE, "stopped": stopped,
            "tasks_run": sum(1 for x in trace if "error" not in x), "wins": seq.wins, "losses": seq.losses,
            "ties": seq.ties, "sign_p_better": round(test["p_better"], 4), "sign_p_worse": round(test["p_worse"], 4),
            "trace": trace}


def _arm_outcomes(files, base_dir: Path) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for f in files:
        out.update(outcomes(json.loads((base_dir / f).read_text(encoding="utf-8"))))
    return out


def replay(entry: dict, base_dir: Path, history_runs: dict[str, dict[str, bool]]) -> dict:
    """Replay one stored A/B through the L3 order + stopping rule. The item model is fitted WITHOUT this A/B's own
    files, so the order never uses the answers it is about to read."""
    own = {str(base_dir / f) for f in entry["base"] + entry["cand"]}
    model = fit({k: v for k, v in history_runs.items() if k not in own})
    base, cand = _arm_outcomes(entry["base"], base_dir), _arm_outcomes(entry["cand"], base_dir)
    common = sorted(set(base) & set(cand))
    # The baseline's ability from its OWN past runs would be ideal; the history mean is the honest stand-in.
    theta = sum(model.theta.values()) / len(model.theta) if model.theta else 0.0
    if entry.get("baseline_like"):
        theta = model.theta.get(str(base_dir / entry["baseline_like"]), theta)
    ordered = order(model, theta, common)
    result = run_adaptive(ordered, lambda t: (base[t], cand[t]))
    full = eval_stats.paired_decision({t: [base[t]] for t in common}, {t: [cand[t]] for t in common})
    result.pop("trace")
    return {"name": entry["name"], "tasks_total": len(common), **result, "full_decision": full.decision,
            "full_wins": full.wins, "full_losses": full.losses}


def replay_registry(registry: list[dict], *, base_dir: Path, history=()) -> dict:
    files = [str(base_dir / f) for e in registry for f in e["base"] + e["cand"]] + [str(Path(h)) for h in history]
    runs = load_runs(dict.fromkeys(files))
    rows = [replay(e, base_dir, runs) for e in registry if not e.get("no_task_outcomes")]
    used = sum(r["tasks_run"] for r in rows)
    total = sum(r["tasks_total"] for r in rows)
    agree = sum(1 for r in rows if r["decision"] in (INCONCLUSIVE, NO_DIFF) and r["full_decision"] == "INCONCLUSIVE"
                or (r["decision"] == BETTER and r["full_decision"] == "PROMOTE")
                or (r["decision"] == WORSE and r["full_decision"] == "REJECT"))
    contradict = sum(1 for r in rows if (r["decision"] == BETTER and r["full_decision"] == "REJECT")
                     or (r["decision"] == WORSE and r["full_decision"] == "PROMOTE"))
    return {"entries": rows, "tasks_used": used, "tasks_total": total,
            "task_share": round(used / total, 3) if total else None, "agree": agree, "contradict": contradict}


def replay_markdown(result: dict) -> str:
    lines = ["| A/B | tasks used / total | L3 decision | W/L/T | full eval |", "|---|---|---|---|---|"]
    for r in result["entries"]:
        lines.append(f"| {r['name']} | {r['tasks_run']}/{r['tasks_total']} | {r['decision']} | "
                     f"{r['wins']}/{r['losses']}/{r['ties']} | {r['full_decision']} "
                     f"({r['full_wins']}W/{r['full_losses']}L) |")
    lines.append(f"\nTasks used: {result['tasks_used']}/{result['tasks_total']} ({result['task_share']}); same "
                 f"conclusion as the full eval: {result['agree']}/{len(result['entries'])}; contradictions: "
                 f"{result['contradict']}")
    return "\n".join(lines)
