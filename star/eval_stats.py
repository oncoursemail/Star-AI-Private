"""Paired statistics for every decision STAR makes about itself (W1 of docs/research/self-improving-star-claude-v2.md).

The old rule ("the 12-task check is not worse than a stored baseline") decides below the noise floor: the same
validation slice read 3/12 one night and 7/12 another with the same lessons. This module replaces it with a paired
comparison run in ONE session:

* baseline and candidate answer the SAME tasks, interleaved (sample j of the baseline next to sample j of the
  candidate), k samples per task;
* each (baseline sample j, candidate sample j) pair is a win, a loss or a tie; under "no difference" the two arms are
  exchangeable, so every discordant pair is a fair coin and an exact sign test (binomial, ties dropped) is valid
  without any normal approximation;
* a cluster bootstrap over tasks gives a confidence interval for the mean per-task change in pass rate;
* the minimum detectable effect (MDE) for the current task count and k is printed next to every verdict;
* the verdict is PROMOTE, REJECT, UNDERPOWERED or INCONCLUSIVE. A non-significant result is UNDERPOWERED ("not
  enough power") when the design could not have detected the smallest effect of interest (default 10 % of the
  tasks) with 80 % power; it is INCONCLUSIVE only when the design was powered for that effect, which then means
  "no effect of that size". **Neither promotes.** INCOMPLETE (a task without a complete pair) never promotes either.

"Regression" means a task the baseline mostly passes and the candidate fails in at least 2 samples and at least 2/3 of
its samples ("fails 2 of 3"); one failed sample is reported as unconfirmed, never as a regression. A confirmed
regression on a canary task (the most stable passing tasks) vetoes the change; an unconfirmed canary failure blocks
PROMOTE (the verdict becomes INCONCLUSIVE until a rerun).

Pure Python, no model, no files, no network. Everything random takes a seed, so the same input gives the same output.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
import math
import random
from statistics import NormalDist

PROMOTE, REJECT, INCONCLUSIVE, INCOMPLETE = "PROMOTE", "REJECT", "INCONCLUSIVE", "INCOMPLETE"
UNDERPOWERED = "UNDERPOWERED"
DECISIONS = (PROMOTE, REJECT, INCONCLUSIVE, INCOMPLETE, UNDERPOWERED)
# The smallest improvement worth deciding on, as a share of the tasks. Below the design's MDE for it, a non-significant
# result says "not enough power" instead of "inconclusive".
DEFAULT_SMALLEST_EFFECT = 0.10
# "The same prompt flips about 1 time in 6": the share of (baseline, candidate) sample pairs that disagree when the
# change does nothing (eval-gains reruns, night school's unchanged slice). Used only for the MDE estimate.
DEFAULT_NOISE_DISCORDANCE = 1 / 6
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.8
_PRUNE = 1e-13


# --- exact binomial pieces ------------------------------------------------------------------------------------

def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


@lru_cache(maxsize=4096)
def binom_tail_ge(n: int, k: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p), exact (summed in log space)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(_log_choose(n, i) + i * lp + (n - i) * lq) for i in range(k, n + 1)))


def sign_test(wins: int, losses: int) -> dict:
    """Exact sign test on discordant pairs (ties are not passed in). One-sided p-values for each direction and the
    two-sided p-value (twice the smaller tail, capped at 1)."""
    if wins < 0 or losses < 0:
        raise ValueError("wins and losses must be non-negative")
    n = wins + losses
    if n == 0:
        return {"n": 0, "p_better": 1.0, "p_worse": 1.0, "p_two_sided": 1.0}
    p_better = binom_tail_ge(n, wins)
    p_worse = binom_tail_ge(n, losses)
    return {"n": n, "p_better": p_better, "p_worse": p_worse, "p_two_sided": min(1.0, 2 * min(p_better, p_worse))}


@lru_cache(maxsize=4096)
def critical_wins(discordant: int, alpha: float = DEFAULT_ALPHA) -> int | None:
    """Smallest number of wins out of `discordant` pairs that the one-sided sign test calls significant at `alpha`;
    None when even `discordant` wins out of `discordant` is not enough (fewer pairs than the test can ever resolve)."""
    for wins in range((discordant + 1) // 2, discordant + 1):
        if binom_tail_ge(discordant, wins) <= alpha:
            return wins
    return None


def min_resolvable_pairs(alpha: float = DEFAULT_ALPHA) -> int:
    """With fewer discordant pairs than this, no outcome can be significant: 0.5 ** n > alpha."""
    return max(1, math.ceil(math.log(alpha) / math.log(0.5)))


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a pass rate (95 % by default). (0, 1) when n is 0."""
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= successes <= n:
        raise ValueError("successes must be between 0 and n")
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def flip_probability(pair_discordance: float = DEFAULT_NOISE_DISCORDANCE) -> float:
    """Per-sample flip probability f with 2 f (1 - f) = pair discordance (two independent samples disagree)."""
    if not 0 <= pair_discordance <= 0.5:
        raise ValueError("pair discordance must be between 0 and 0.5")
    return (1 - math.sqrt(1 - 2 * pair_discordance)) / 2


# --- power and minimum detectable effect ----------------------------------------------------------------------

def _group(m: int, p_win: float, p_loss: float) -> dict[tuple[int, int], float]:
    """Distribution of (wins, losses) over m independent pairs, each a win / loss / tie (closed-form trinomial)."""
    p_tie = max(0.0, 1.0 - p_win - p_loss)
    if m == 0:
        return {(0, 0): 1.0}
    out: dict[tuple[int, int], float] = {}
    logs = {name: (math.log(v) if v > 0 else None) for name, v in (("w", p_win), ("l", p_loss), ("t", p_tie))}
    for a in range(m + 1):
        if a and logs["w"] is None:
            break
        for b in range(m - a + 1):
            if b and logs["l"] is None:
                break
            c = m - a - b
            if c and logs["t"] is None:
                continue
            value = (math.lgamma(m + 1) - math.lgamma(a + 1) - math.lgamma(b + 1) - math.lgamma(c + 1)
                     + (a * logs["w"] if a else 0.0) + (b * logs["l"] if b else 0.0) + (c * logs["t"] if c else 0.0))
            p = math.exp(value)
            if p > _PRUNE:
                out[(a, b)] = p
    return out


def power(n_tasks: int, k: int, effect_tasks: int, *, noise_discordance: float = DEFAULT_NOISE_DISCORDANCE,
          alpha: float = DEFAULT_ALPHA) -> float:
    """Probability that the paired sign test calls PROMOTE when `effect_tasks` of `n_tasks` truly go from fail to
    pass and every sample flips with the noise rate (exact under that model, pruned below 1e-13).

    Model: a noise task's pair disagrees with probability `noise_discordance`, either way; an effect task's baseline
    sample passes with probability f and its candidate sample with 1 - f (f = flip_probability)."""
    if not 0 <= effect_tasks <= n_tasks or k < 1:
        raise ValueError("need 0 <= effect_tasks <= n_tasks and k >= 1")
    f = flip_probability(noise_discordance)
    noise = _group((n_tasks - effect_tasks) * k, noise_discordance / 2, noise_discordance / 2)
    effect = _group(effect_tasks * k, (1 - f) * (1 - f), f * f)
    total = 0.0
    for (w0, l0), p0 in noise.items():
        for (w1, l1), p1 in effect.items():
            wins, losses = w0 + w1, l0 + l1
            need = critical_wins(wins + losses, alpha)
            if need is not None and wins >= need:
                total += p0 * p1
    return min(1.0, total)


@dataclass
class MDE:
    n_tasks: int
    k: int
    alpha: float
    target_power: float
    noise_discordance: float
    effect_tasks: int | None        # smallest number of tasks that must truly go fail -> pass (None: not reachable)
    power_at_effect: float
    net_wins_needed: int | None     # net pair wins the test needs at the expected noise discordance (no effect)

    def text(self) -> str:
        reach = (f"+{self.effect_tasks} of {self.n_tasks} tasks (power {self.power_at_effect:.0%})"
                 if self.effect_tasks is not None else f"no effect within {self.n_tasks} tasks reaches "
                 f"{self.target_power:.0%} power")
        need = (f"; needs about +{self.net_wins_needed} net pair wins" if self.net_wins_needed is not None
                else "; too few pairs for any significant result")
        return (f"MDE at {self.target_power:.0%} power, alpha {self.alpha:g}, k={self.k}: {reach}{need} "
                f"(ESTIMATE: assumes independent tasks and {self.noise_discordance:.0%} noise discordance)")


@lru_cache(maxsize=256)
def _mde(n_tasks: int, k: int, noise: float, alpha: float, target: float) -> MDE:
    pairs = n_tasks * k
    expected = round(pairs * noise)
    need_w = critical_wins(expected, alpha)
    if need_w is not None:
        net = 2 * need_w - expected
    else:   # the noise alone gives too few pairs: the smallest significant outcome is all wins on the minimum pairs
        net = min_resolvable_pairs(alpha) if pairs >= min_resolvable_pairs(alpha) else None
    best = power(n_tasks, k, n_tasks, noise_discordance=noise, alpha=alpha) if n_tasks else 0.0
    if best < target:
        return MDE(n_tasks, k, alpha, target, noise, None, best, net)
    lo, hi = 0, n_tasks
    while lo < hi:      # power rises with the effect: binary search for the smallest effect reaching the target
        mid = (lo + hi) // 2
        if power(n_tasks, k, mid, noise_discordance=noise, alpha=alpha) >= target:
            hi = mid
        else:
            lo = mid + 1
    return MDE(n_tasks, k, alpha, target, noise, lo, power(n_tasks, k, lo, noise_discordance=noise, alpha=alpha), net)


def tasks_needed(smallest_effect: float = DEFAULT_SMALLEST_EFFECT, k: int = 1, *,
                 noise_discordance: float = DEFAULT_NOISE_DISCORDANCE, alpha: float = DEFAULT_ALPHA,
                 target_power: float = DEFAULT_POWER) -> int | None:
    """About how many tasks the paired sign test needs to detect `smallest_effect` (share of tasks truly going
    fail -> pass) with `target_power` at k samples. Normal approximation of the same model as `power` (advice for
    sizing a set; the verdict itself always uses the exact test). None for a non-positive effect."""
    if smallest_effect <= 0 or k < 1:
        return None
    f = flip_probability(noise_discordance)
    e = min(1.0, smallest_effect)
    p_win = noise_discordance / 2 * (1 - e) + e * (1 - f) ** 2
    p_loss = noise_discordance / 2 * (1 - e) + e * f * f
    mu, q = p_win - p_loss, p_win + p_loss
    z_a, z_b = NormalDist().inv_cdf(1 - alpha), NormalDist().inv_cdf(target_power)
    pairs = ((z_a * math.sqrt(q) + z_b * math.sqrt(max(0.0, q - mu * mu))) / mu) ** 2
    return max(1, math.ceil(pairs / k))


def minimum_detectable_effect(n_tasks: int, k: int = 1, *, noise_discordance: float = DEFAULT_NOISE_DISCORDANCE,
                              alpha: float = DEFAULT_ALPHA, target_power: float = DEFAULT_POWER) -> MDE:
    """The smallest true improvement (tasks going fail -> pass) the paired test detects with `target_power`."""
    if n_tasks < 0 or k < 1:
        raise ValueError("n_tasks must be >= 0 and k >= 1")
    return _mde(int(n_tasks), int(k), float(noise_discordance), float(alpha), float(target_power))


# --- bootstrap ----------------------------------------------------------------------------------------------

def bootstrap_ci(task_diffs: list[float], *, seed: int = 0, n_boot: int = 2000, level: float = 0.90) -> tuple[float, float]:
    """Percentile cluster bootstrap (resampling tasks) of the mean per-task change in pass rate. Deterministic for a
    seed. With few tasks the interval is too narrow (anti-conservative); the sign test is the default decision."""
    if not task_diffs or n_boot <= 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(task_diffs)
    means = sorted(sum(task_diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    tail = (1 - level) / 2
    lo = means[max(0, min(n_boot - 1, int(math.floor(tail * n_boot))))]
    hi = means[max(0, min(n_boot - 1, int(math.ceil((1 - tail) * n_boot)) - 1))]
    return (lo, hi)


# --- the paired verdict -----------------------------------------------------------------------------------

@dataclass
class PairedReport:
    decision: str
    method: str
    n_tasks: int
    k: int
    wins: int = 0                    # sample pairs: candidate passed, baseline failed
    losses: int = 0
    ties: int = 0
    task_wins: int = 0               # tasks whose candidate pass rate is higher
    task_losses: int = 0
    baseline_pass: int = 0           # samples
    candidate_pass: int = 0
    samples: int = 0                 # paired samples per arm
    p_better: float = 1.0
    p_worse: float = 1.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    alpha: float = DEFAULT_ALPHA
    mde: dict = field(default_factory=dict)
    smallest_effect: float = DEFAULT_SMALLEST_EFFECT
    power_at_smallest: float = 0.0   # power of this design for the smallest effect of interest
    observed_discordance: float = 0.0
    regressions: list[str] = field(default_factory=list)
    unconfirmed_regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    canary_vetoes: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def promote(self) -> bool:
        return self.decision == PROMOTE

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("p_better", "p_worse", "ci_low", "ci_high"):
            data[key] = round(data[key], 6)
        return data

    def summary(self) -> dict:
        """The few numbers worth storing next to a decision (night school state, result files)."""
        return {"decision": self.decision, "method": self.method, "tasks": self.n_tasks, "k": self.k,
                "wins": self.wins, "losses": self.losses, "ties": self.ties, "p_better": round(self.p_better, 4),
                "p_worse": round(self.p_worse, 4), "ci": [round(self.ci_low, 3), round(self.ci_high, 3)],
                "mde_tasks": self.mde.get("effect_tasks"), "smallest_effect": self.smallest_effect,
                "power_at_smallest": round(self.power_at_smallest, 3),
                "observed_discordance": round(self.observed_discordance, 4), "regressions": list(self.regressions),
                "canary_vetoes": list(self.canary_vetoes)}

    def text(self) -> str:
        lines = [f"paired gate: {self.decision} ({self.method}) - candidate {self.candidate_pass}/{self.samples} vs "
                 f"baseline {self.baseline_pass}/{self.samples} samples on {self.n_tasks} tasks x k={self.k}",
                 f"  pairs: {self.wins} wins, {self.losses} losses, {self.ties} ties; tasks: {self.task_wins} better, "
                 f"{self.task_losses} worse; sign test p(better)={self.p_better:.4f}, p(worse)={self.p_worse:.4f}, "
                 f"alpha {self.alpha:g}",
                 f"  mean change in pass rate per task: {self.ci_low:+.3f} .. {self.ci_high:+.3f} (bootstrap interval)"]
        if self.mde:
            lines.append("  " + MDE(**self.mde).text())
            lines.append(f"  power for the smallest effect of interest (+{self.smallest_effect:.0%} of tasks): "
                         f"{self.power_at_smallest:.0%}; observed pair discordance {self.observed_discordance:.1%}")
        for label, ids in (("regressions (fail 2 of 3)", self.regressions),
                           ("failed once, not confirmed", self.unconfirmed_regressions),
                           ("improvements", self.improvements), ("canary veto", self.canary_vetoes),
                           ("no complete pair (no verdict)", self.incomplete)):
            if ids:
                lines.append(f"  {label}: {', '.join(sorted(ids))}")
        lines.extend("  note: " + n for n in self.notes)
        return "\n".join(lines)


def _clean(samples) -> list[bool]:
    if samples is None:
        return []
    if isinstance(samples, bool):
        return [samples]
    out = []
    for value in samples:
        if value is None:           # an errored sample: not a pass, not a fail
            continue
        if not isinstance(value, bool):
            raise ValueError("samples must be True (pass), False (fail) or None (error)")
        out.append(value)
    return out


def is_regression(baseline: list[bool], candidate: list[bool]) -> str:
    """'confirmed', 'unconfirmed' or ''. Confirmed: the baseline passes at least half its samples and the candidate
    fails at least 2 samples and at least 2/3 of them. One failed sample is never more than 'unconfirmed'."""
    if not baseline or not candidate or sum(baseline) * 2 < len(baseline):
        return ""
    fails = len(candidate) - sum(candidate)
    if fails >= 2 and fails * 3 >= 2 * len(candidate):
        return "confirmed"
    if fails >= 1 and sum(candidate) * len(baseline) < sum(baseline) * len(candidate):
        return "unconfirmed"
    return ""


def paired_decision(baseline: dict, candidate: dict, *, alpha: float = DEFAULT_ALPHA, method: str = "sign",
                    canary=(), seed: int = 0, n_boot: int = 2000,
                    noise_discordance: float = DEFAULT_NOISE_DISCORDANCE, target_power: float = DEFAULT_POWER,
                    smallest_effect: float = DEFAULT_SMALLEST_EFFECT) -> PairedReport:
    """Paired verdict from two arms run in the same session.

    `baseline` and `candidate` map task id -> list of sample outcomes (True pass, False fail, None error), in the
    order they were run: sample j of the baseline is paired with sample j of the candidate. Tasks present in only
    one arm, or without a complete pair, are listed as incomplete and make the verdict INCOMPLETE.

    method "sign" (default): PROMOTE when the exact sign test's one-sided p(better) <= alpha, REJECT when
    p(worse) <= alpha. method "bootstrap": PROMOTE when the (1 - 2 alpha) bootstrap interval of the mean per-task
    change lies above 0, REJECT when it lies below 0. Both statistics are always reported.
    """
    if method not in ("sign", "bootstrap"):
        raise ValueError("method must be 'sign' or 'bootstrap'")
    if not 0 < alpha < 0.5:
        raise ValueError("alpha must be between 0 and 0.5")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError("baseline and candidate must map task id -> samples")
    ids = sorted(set(baseline) | set(candidate))
    canary = set(canary or ())
    report = PairedReport(INCONCLUSIVE, method, 0, 0, alpha=alpha)
    diffs: list[float] = []
    ks: set[int] = set()
    for tid in ids:
        base, cand = _clean(baseline.get(tid)), _clean(candidate.get(tid))
        pairs = min(len(base), len(cand))
        if pairs == 0:
            report.incomplete.append(tid)
            continue
        if len(base) != len(cand):
            report.notes.append(f"{tid}: {len(base)} baseline vs {len(cand)} candidate samples; "
                                f"the first {pairs} of each are paired")
        base, cand = base[:pairs], cand[:pairs]
        ks.add(pairs)
        report.n_tasks += 1
        report.samples += pairs
        report.baseline_pass += sum(base)
        report.candidate_pass += sum(cand)
        for b, c in zip(base, cand):
            if c and not b:
                report.wins += 1
            elif b and not c:
                report.losses += 1
            else:
                report.ties += 1
        diff = (sum(cand) - sum(base)) / pairs
        diffs.append(diff)
        if diff > 0:
            report.task_wins += 1
            if sum(base) * 2 < pairs:
                report.improvements.append(tid)
        elif diff < 0:
            report.task_losses += 1
        kind = is_regression(base, cand)
        if kind == "confirmed":
            report.regressions.append(tid)
            if tid in canary:
                report.canary_vetoes.append(tid)
        elif kind == "unconfirmed":
            report.unconfirmed_regressions.append(tid)
    report.k = max(ks) if ks else 0
    if len(ks) > 1:
        report.notes.append(f"tasks have different sample counts {sorted(ks)}; the MDE uses k={report.k}")
    test = sign_test(report.wins, report.losses)
    report.p_better, report.p_worse = test["p_better"], test["p_worse"]
    report.ci_low, report.ci_high = bootstrap_ci(diffs, seed=seed, n_boot=n_boot, level=1 - 2 * alpha)
    report.smallest_effect = smallest_effect
    if report.samples:
        report.observed_discordance = (report.wins + report.losses) / report.samples
    if report.n_tasks:
        report.mde = asdict(minimum_detectable_effect(report.n_tasks, report.k, noise_discordance=noise_discordance,
                                                      alpha=alpha, target_power=target_power))
        target = min(report.n_tasks, max(1, math.ceil(smallest_effect * report.n_tasks)))
        report.power_at_smallest = power(report.n_tasks, report.k, target, noise_discordance=noise_discordance,
                                         alpha=alpha)
    if method == "sign":
        better, worse = report.p_better <= alpha, report.p_worse <= alpha
    else:
        better, worse = report.ci_low > 0, report.ci_high < 0
    if report.incomplete or not report.n_tasks:
        report.decision = INCOMPLETE
        report.notes.append("tasks without a complete pair: no verdict (never promotes)")
    elif report.canary_vetoes:
        report.decision = REJECT
        report.notes.append("a canary task fails reproducibly: vetoed")
    elif worse:
        report.decision = REJECT
    elif better:
        unconfirmed_canary = sorted(set(report.unconfirmed_regressions) & canary)
        if unconfirmed_canary:
            report.decision = INCONCLUSIVE
            report.notes.append("a canary task failed once: rerun it before promoting (" + ", ".join(unconfirmed_canary) + ")")
        else:
            report.decision = PROMOTE
    elif report.power_at_smallest < target_power:
        report.decision = UNDERPOWERED
        need = tasks_needed(smallest_effect, report.k, noise_discordance=noise_discordance, alpha=alpha,
                            target_power=target_power)
        need2 = tasks_needed(smallest_effect, report.k + 1, noise_discordance=noise_discordance, alpha=alpha,
                             target_power=target_power)
        report.notes.append(
            f"not enough power: {report.n_tasks} tasks x k={report.k} detect a +{smallest_effect:.0%} effect only "
            f"{report.power_at_smallest:.0%} of the time (need {target_power:.0%}); about "
            + (f"{need} tasks at k={report.k}" if need else "more than 2000 tasks")
            + (f" or {need2} at k={report.k + 1}" if need2 else "") + " would be enough. No decision either way.")
    else:
        report.decision = INCONCLUSIVE
        report.notes.append(f"powered ({report.power_at_smallest:.0%} for +{smallest_effect:.0%}) and not significant: "
                            f"an effect of +{smallest_effect:.0%} of tasks or more is unlikely; smaller effects are not "
                            "ruled out. Does not promote.")
    return report


def simulate(n_tasks: int, k: int, effect_tasks: int, *, runs: int = 1000, seed: int = 0, base_pass_share: float = 0.5,
             noise_discordance: float = DEFAULT_NOISE_DISCORDANCE, alpha: float = DEFAULT_ALPHA,
             method: str = "sign") -> dict:
    """Synthetic paired sessions (used by the tests and to sanity-check the MDE): each task has a true state (pass or
    fail), every sample flips with probability f, and `effect_tasks` failing tasks truly pass for the candidate.
    Returns the share of runs per decision. Deterministic for a seed."""
    rng = random.Random(seed)
    f = flip_probability(noise_discordance)
    passing = int(round(n_tasks * base_pass_share))
    if effect_tasks > n_tasks - passing:
        raise ValueError("effect_tasks must fit in the baseline's failing tasks")
    counts = {d: 0 for d in DECISIONS}
    for run in range(runs):
        base, cand = {}, {}
        for t in range(n_tasks):
            true_base = t < passing
            true_cand = true_base or t >= n_tasks - effect_tasks
            base[f"T{t}"] = [(rng.random() >= f) == true_base for _ in range(k)]
            cand[f"T{t}"] = [(rng.random() >= f) == true_cand for _ in range(k)]
        report = paired_decision(base, cand, alpha=alpha, method=method, seed=run,
                                 n_boot=400 if method == "bootstrap" else 0)
        counts[report.decision] += 1
    return {d: counts[d] / runs for d in DECISIONS}
