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
from math import ceil, isfinite
import re
from typing import Sequence


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
        number = float(value)
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


def _key(t: GamePerformanceTrial) -> tuple[str, str, int, str]:
    return (t.game_scope, t.scenario_id, t.seed, t.mode)


def _index(rows: Sequence[GamePerformanceTrial]) -> dict[tuple[str, str, int, str], GamePerformanceTrial]:
    """Reject duplicates and any replay of a practice map/seed in holdouts."""
    if not isinstance(rows, (list, tuple)) or len(rows) > 2048:
        raise ValueError("trials must be a bounded list/tuple")
    found: dict[tuple[str, str, int, str], GamePerformanceTrial] = {}
    seen_cases: set[str] = set()
    seeds_by_split: dict[tuple[str, str, int], str] = {}
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
            key = _key(t)
            if key in found:
                raise ValueError("duplicate holdout")
            found[key] = t
    return found


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[ceil(0.95 * len(ordered)) - 1]


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
    """
    if mode not in _MODES or type(mode) is not str:
        raise ValueError("mode must be realtime or paused")
    if type(min_holdouts) is not int or not 4 <= min_holdouts <= 1024:
        raise ValueError("min_holdouts must be 4..1024")

    def verdict(reasons: tuple[str, ...], base: list[GamePerformanceTrial] | None = None,
                new: list[GamePerformanceTrial] | None = None) -> GameSkillVerdict:
        b, n = base or [], new or []
        return GameSkillVerdict(
            eligible=not reasons, reasons=reasons, mode=mode, matched_holdouts=len(b),
            baseline_wins=sum(t.success for t in b),
            candidate_wins=sum(t.success for t in n),
            baseline_mean_progress=sum(t.progress for t in b) / len(b) if b else 0.0,
            candidate_mean_progress=sum(t.progress for t in n) / len(n) if n else 0.0,
            baseline_p95_action_delay_ms=_p95([t.action_delay_ms for t in b]),
            candidate_p95_action_delay_ms=_p95([t.action_delay_ms for t in n]),
        )

    try:
        bindex, cindex = _index(baseline), _index(candidate)
    except (TypeError, ValueError):
        return verdict(("invalid_evidence",))
    bkeys = {key for key in bindex if key[3] == mode}
    ckeys = {key for key in cindex if key[3] == mode}
    if bkeys != ckeys or any(bindex[k].case_id != cindex[k].case_id for k in bkeys):
        return verdict(("unmatched_holdouts",))
    keys = sorted(bkeys)
    b, n = [bindex[k] for k in keys], [cindex[k] for k in keys]
    reasons: list[str] = []
    if len(keys) < min_holdouts or len({(key[0], key[1]) for key in keys}) < 2:
        reasons.append("insufficient_unseen_scenarios")
    if any(old.success and not new.success for old, new in zip(b, n)):
        reasons.append("new_failures")
    if any(new.progress < old.progress - 0.025 for old, new in zip(b, n)):
        reasons.append("progress_regression")
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
    return verdict(tuple(reasons), b, n)


__all__ = ["GamePerformanceTrial", "GameSkillVerdict", "compare_game_skill"]
