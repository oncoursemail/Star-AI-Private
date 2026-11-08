"""Offline, outcome-based qualification for Star's autonomous game practice.

This component cannot operate a game, claim a victory, train a model, or
authorize an update. A trusted external game-state harness supplies matched
baseline/candidate trials from unseen maps and seeds. This supplemental
latency/progress diagnostic does NOT replace the signed GameplaySkillBank
and preregistered game_transfer_eval validation gate. The attestation flag
does not authenticate a compromised host. No player IDs, chat or videos here.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, comb, isfinite
import re
from typing import Sequence, cast


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_MODES = frozenset({"realtime", "paused"})
_SPLITS = frozenset({"practice", "holdout"})


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded canonical identifier")
    return value


def _nonnegative_float(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be finite and nonnegative")
    try:
        # Runtime checks reject bool/subclasses; cast only informs Pyright that
        # this validated object is one of the numeric builtin types.
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite and nonnegative") from exc
    if not isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return number


@dataclass(frozen=True)
class GamePerformanceTrial:
    """One independently checked game outcome; metadata excludes personal data."""

    case_id: str
    game_scope: str
    scenario_id: str
    seed: int
    split: str
    mode: str
    success: bool
    progress: float
    action_delay_ms: float
    host_verified: bool = False

    def __post_init__(self) -> None:
        for name in ("case_id", "game_scope", "scenario_id"):
            _id(getattr(self, name), name)
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError("seed must be a bounded unsigned integer")
        if self.split not in _SPLITS or type(self.split) is not str:
            raise ValueError("split must be practice or holdout")
        if self.mode not in _MODES or type(self.mode) is not str:
            raise ValueError("mode must be realtime or paused")
        if type(self.success) is not bool or type(self.host_verified) is not bool:
            raise ValueError("success and host_verified must be explicit booleans")
        value = _nonnegative_float(self.progress, "progress")
        if value > 1:
            raise ValueError("progress must be normalized to 0..1")
        _nonnegative_float(self.action_delay_ms, "action_delay_ms")


@dataclass(frozen=True)
class GameSkillVerdict:
    """Anonymous offline result, never permission to promote a model."""

    eligible: bool
    reasons: tuple[str, ...]
    mode: str
    matched_holdouts: int
    baseline_wins: int
    candidate_wins: int
    baseline_mean_progress: float
    candidate_mean_progress: float
    baseline_p95_action_delay_ms: float
    candidate_p95_action_delay_ms: float
    evidence: str = "host_attested_not_cryptographic_proof"
    authorized_to_promote: bool = False
    authorized_to_play: bool = False
    paired_sign_pvalue: float | None = None


def _key(t: GamePerformanceTrial) -> tuple[str, str, int, str]:
    return (t.game_scope, t.scenario_id, t.seed, t.mode)


def _index(rows: Sequence[GamePerformanceTrial]) -> tuple[
    dict[tuple[str, str, int, str], GamePerformanceTrial],
    set[tuple[str, str, int]], set[tuple[str, str, int]],
]:
    """Reject duplicates and any replay of a practice map/seed in holdouts."""
    if not isinstance(rows, (list, tuple)) or len(rows) > 2048:
        raise ValueError("trials must be a bounded list/tuple")
    found: dict[tuple[str, str, int, str], GamePerformanceTrial] = {}
    seen_cases: set[str] = set()
    seeds_by_split: dict[tuple[str, str, int], str] = {}
    practice_seeds: set[tuple[str, str, int]] = set()
    holdout_seeds: set[tuple[str, str, int]] = set()
    for t in rows:
        if not isinstance(t, GamePerformanceTrial) or not t.host_verified:
            raise ValueError("all trials need structured host attestation")
        if t.case_id in seen_cases:
            raise ValueError("duplicate case identifier")
        seen_cases.add(t.case_id)
        seed_key = (t.game_scope, t.scenario_id, t.seed)
        old_split = seeds_by_split.setdefault(seed_key, t.split)
        if old_split != t.split:
            raise ValueError("training/holdout map and seed overlap")
        if t.split == "holdout":
            holdout_seeds.add(seed_key)
            key = _key(t)
            if key in found:
                raise ValueError("duplicate holdout")
            found[key] = t
        else:
            practice_seeds.add(seed_key)
    return found, practice_seeds, holdout_seeds


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[ceil(0.95 * len(ordered)) - 1]


def _one_sided_sign_pvalue(positive: int, negative: int) -> float | None:
    """Exact one-sided paired sign test, excluding ties.

    This is a conservative screening diagnostic, NOT proof that correlated
    seeds, repeated peeks, or a compromised host are independent evidence.
    """
    n = positive + negative
    if n == 0:
        return None
    return sum(comb(n, k) for k in range(positive, n + 1)) / (1 << n)


def compare_game_skill(
    baseline: Sequence[GamePerformanceTrial], candidate: Sequence[GamePerformanceTrial], *,
    mode: str = "realtime", min_holdouts: int = 20,
) -> GameSkillVerdict:
    """Flag paired performance improvements for further independent review.

    A speed gain alone can qualify if at least 10% faster at p95; a new win or
    >=0.02 mean normalized progress gain also counts. Every previously won case
    must remain won. Per-case progress/latency regressions and p95 latency
    regressions block eligibility, regardless of aggregate score.
    Paused and real-time evidence MUST be compared separately.
    A descriptive one-sided paired sign test rejects weak directional
    evidence despite an impressive mean. It assumes genuinely independent,
    preregistered seeds; the advisory verdict is NEVER deployment authority.
    """
    if mode not in _MODES or type(mode) is not str:
        raise ValueError("mode must be realtime or paused")
    if type(min_holdouts) is not int or not 4 <= min_holdouts <= 1024:
        raise ValueError("min_holdouts must be 4..1024")

    def verdict(reasons: tuple[str, ...], base: list[GamePerformanceTrial] | None = None,
                new: list[GamePerformanceTrial] | None = None,
                sign_p: float | None = None) -> GameSkillVerdict:
        b, n = base or [], new or []
        return GameSkillVerdict(
            eligible=not reasons, reasons=reasons, mode=mode, matched_holdouts=len(b),
            baseline_wins=sum(t.success for t in b),
            candidate_wins=sum(t.success for t in n),
            baseline_mean_progress=sum(t.progress for t in b) / len(b) if b else 0.0,
            candidate_mean_progress=sum(t.progress for t in n) / len(n) if n else 0.0,
            baseline_p95_action_delay_ms=_p95([t.action_delay_ms for t in b]),
            candidate_p95_action_delay_ms=_p95([t.action_delay_ms for t in n]),
            paired_sign_pvalue=sign_p,
        )

    try:
        bindex, bpractice, bholdout = _index(baseline)
        cindex, cpractice, choldout = _index(candidate)
    except (TypeError, ValueError):
        return verdict(("invalid_evidence",))
    # A test seed practiced by EITHER variant is not unseen for EITHER arm.
    # Checking each arm independently misses cross-variant/mode leakage.
    # Cross-split contamination is invalid even if the practiced run was
    # paused and the held-out trial was in real-time mode (or vice versa).
    if (bpractice | cpractice) & (bholdout | choldout):
        return verdict(("invalid_evidence",))
    bkeys = {key for key in bindex if key[3] == mode}
    ckeys = {key for key in cindex if key[3] == mode}
    if bkeys != ckeys or any(bindex[k].case_id != cindex[k].case_id for k in bkeys):
        return verdict(("unmatched_holdouts",))
    keys = sorted(bkeys)
    b, n = [bindex[k] for k in keys], [cindex[k] for k in keys]
    reasons: list[str] = []
    # "20 unseen cases across two maps" is not credible if one map has only
    # one example. Require independently matched observations in every
    # preregistered scenario, not merely two distinct scenario labels.
    scenario_counts: dict[tuple[str, str], int] = {}
    for key in keys:
        scope = (key[0], key[1])
        scenario_counts[scope] = scenario_counts.get(scope, 0) + 1
    min_per_scenario = min(4, max(2, min_holdouts // 5))
    if (len(keys) < min_holdouts or len(scenario_counts) < 2
            or any(count < min_per_scenario for count in scenario_counts.values())):
        reasons.append("insufficient_unseen_scenarios")
    if any(old.success and not new.success for old, new in zip(b, n)):
        reasons.append("new_failures")
    if any(new.progress < old.progress - 0.025 for old, new in zip(b, n)):
        reasons.append("progress_regression")
    # A large win on one map must not hide many small losses on another.
    # The per-case 2.5-point tolerance alone permits this aggregate reversal.
    # Compare each preregistered scenario independently (including game scope).
    by_scenario: dict[tuple[str, str], list[float]] = {}
    scenario_delays: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for old, new in zip(b, n):
        key = (old.game_scope, old.scenario_id)
        by_scenario.setdefault(key, []).append(new.progress - old.progress)
        scenario_delays.setdefault(key, []).append(
            (old.action_delay_ms, new.action_delay_ms)
        )
    if any(sum(deltas) / len(deltas) < -0.01
           for deltas in by_scenario.values()):
        reasons.append("scenario_progress_regression")
    # An easy map may be the only one made significantly slower. Its p95 is
    # invisible beneath a different, naturally slow map's GLOBAL p95.
    # Preserve the original global tail check as a separate safeguard.
    for paired_delays in scenario_delays.values():
        old_p95 = _p95([older for older, _ in paired_delays])
        new_p95 = _p95([newer for _, newer in paired_delays])
        if new_p95 > old_p95 * 1.10 and new_p95 > old_p95 + 20:
            reasons.append("scenario_p95_action_delay_regression")
            break
    if any(new.action_delay_ms > 2 * old.action_delay_ms + 100
           for old, new in zip(b, n)):
        reasons.append("severe_action_delay_regression")
    b95, n95 = _p95([t.action_delay_ms for t in b]), _p95([t.action_delay_ms for t in n])
    if n95 > b95 * 1.10 and n95 > b95 + 20:
        reasons.append("p95_action_delay_regression")
    wins = sum(t.success for t in n) > sum(t.success for t in b)
    progress = bool(b and sum(t.progress - old.progress for t, old in zip(n, b)) / len(b) >= 0.02)
    faster = bool(b and b95 > 0 and n95 <= 0.90 * b95 and b95 - n95 >= 10)
    if not (wins or progress or faster):
        reasons.append("no_verified_improvement")
    else:
        # A single lucky map seed must not qualify a supposedly smarter
        # real-time player. Demand repeated, material paired benefits on at
        # least two independently named scenarios, rather than a global mean
        # inflated by one outlier. This is a conservative screening rule,
        # not a statistical proof of transfer or authority to deploy.
        benefited = [
            (old.game_scope, old.scenario_id)
            for old, new in zip(b, n)
            if (new.success and not old.success
                or new.progress >= old.progress + 0.02 - 1e-9
                or (old.action_delay_ms >= 10
                    and old.action_delay_ms - new.action_delay_ms >= 10
                    and new.action_delay_ms <= old.action_delay_ms * 0.9))
        ]
        if len(benefited) < 5:
            reasons.append("insufficient_repeated_improvement")
        if len(set(benefited)) < 2:
            reasons.append("improvement_not_cross_scenario")
    paired_p: float | None = None
    if wins or progress or faster:
        # Count independent *paired directions*, not how many scenarios or
        # magnitude of a lucky win. Ties do not increase the evidence count.
        # Gameplay outcomes take priority; latency is tested for speed-only
        # improvements. Never select whichever metric has the lowest p-value.
        if wins or progress:
            directions = [
                1 if (new.success and not old.success
                      or (old.success == new.success
                          and new.progress - old.progress >= 0.005))
                else -1 if (old.success and not new.success
                           or (old.success == new.success
                               and old.progress - new.progress >= 0.005))
                else 0
                for old, new in zip(b, n)
            ]
        else:
            directions = [
                1 if old.action_delay_ms - new.action_delay_ms >= 2
                else -1 if new.action_delay_ms - old.action_delay_ms >= 2
                else 0 for old, new in zip(b, n)
            ]
        paired_p = _one_sided_sign_pvalue(
            directions.count(1), directions.count(-1),
        )
        if paired_p is None or paired_p >= 0.05:
            reasons.append("paired_gain_not_statistically_supported")
    return verdict(tuple(reasons), b, n, paired_p)


__all__ = ["GamePerformanceTrial", "GameSkillVerdict", "compare_game_skill"]
