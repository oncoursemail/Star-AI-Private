"""Owner-only, offline paired holdout evaluation of Star's game-learning transfer.

A trusted *independent* game scorer signs validation GameTrial outcomes using
its secret held outside the AI process. The evaluated agent must never see the
held-out cases, score receipts, validation key or per-case results. This module
issues only an advisory verdict, not game input or permission to deploy.

Matches baseline/candidate trials on the same preregistered game, version,
objective and situation (a host-chosen, withheld level/seed identifier).
A missing trial counts as incomplete, never as a favorable result.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math
import json
import re
from typing import Sequence

from .gameplay_skill_bank import GameTrial

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_VALIDATION_AGE_S = 30 * 86400


@dataclass(frozen=True)
class HoldoutCase:
    game_id: str
    game_version: str
    objective_id: str
    situation_id: str

    def __post_init__(self) -> None:
        for field in ("game_id", "game_version", "objective_id", "situation_id"):
            value = getattr(self, field)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError("holdout scope must use bounded opaque identifiers")


@dataclass(frozen=True)
class SignedHoldoutTrial:
    trial: GameTrial
    receipt: str


@dataclass(frozen=True)
class TransferReport:
    verdict: str  # eligible_for_owner_pilot | regressed | inconclusive
    preregistered_pairs: int
    completed_pairs: int
    incomplete_pairs: int
    distinct_games: int
    baseline_success_rate: float | None
    candidate_success_rate: float | None
    paired_success_gain: float | None
    candidate_only_successes: int
    baseline_only_successes: int
    mcnemar_one_sided_p: float | None
    note: str = "advisory only; independent validation, no automatic promotion"


def _one_sided_p(wins: int, losses: int) -> float:
    """Exact paired sign/McNemar test: H0 no candidate advantage."""
    n = wins + losses
    if not n:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (1 << n)


def roster_digest(cases: Sequence[HoldoutCase]) -> str:
    """Versioned SHA-256 for an owner's *previously sealed* holdout roster.

    The host must commit this digest in a timestamped, independent audit log
    BEFORE either agent sees a game. Passing an on-the-fly digest does not
    constitute preregistration and does not prevent cherry picking.
    """
    if type(cases) not in (tuple, list) or not 1 <= len(cases) <= 512:
        raise ValueError("provide 1..512 preregistered holdout cases")
    if any(not isinstance(case, HoldoutCase) for case in cases) or len(set(cases)) != len(cases):
        raise ValueError("holdout roster has invalid or repeated cases")
    rows = sorted((case.game_id, case.game_version, case.objective_id, case.situation_id)
                  for case in cases)
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(b"star.game-transfer.holdout-roster.v1\x00" + payload).hexdigest()


def evaluate_transfer(
    cases: Sequence[HoldoutCase],
    signed_trials: Sequence[SignedHoldoutTrial],
    *,
    validation_key: bytes,
    expected_roster_sha256: str,
    baseline_action_id: str,
    candidate_action_id: str,
    now_unix_s: int,
    minimum_pairs: int = 40,
    minimum_games: int = 5,
    min_cases_per_game: int = 3,
) -> TransferReport:
    """Evaluate precommitted unseen game cases against a matched baseline.

    A host must preregister all cases BEFORE execution and must sign actual
    results independently of Star. Neither signature validity nor this test
    can prove that the host's scorer is truthful or the holdouts remained secret.

    Baseline and candidate use different run IDs but the same hidden case.
    Two-sided gameplay coverage and one-sided exact McNemar significance are
    both required for a candidate to be eligible for *manual* hardware pilots.
    """
    if type(validation_key) is not bytes or len(validation_key) < 32:
        raise ValueError("requires independent host-owned validation key")
    if (type(baseline_action_id) is not str or not _ID.fullmatch(baseline_action_id)
            or type(candidate_action_id) is not str or not _ID.fullmatch(candidate_action_id)
            or baseline_action_id == candidate_action_id):
        raise ValueError("distinct bounded baseline and candidate actions required")
    if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
        raise ValueError("invalid current Unix timestamp")
    if (type(minimum_pairs) is not int or not 20 <= minimum_pairs <= 512
            or type(minimum_games) is not int or not 2 <= minimum_games <= 50
            or type(min_cases_per_game) is not int or not 2 <= min_cases_per_game <= 40):
        raise ValueError("invalid preregistered acceptance thresholds")
    digest = roster_digest(cases)
    if (type(expected_roster_sha256) is not str or not _SHA.fullmatch(expected_roster_sha256)
            or not hmac.compare_digest(digest, expected_roster_sha256)):
        raise PermissionError("holdout roster does not match independently sealed manifest")
    if type(signed_trials) not in (tuple, list) or len(signed_trials) > 1024:
        raise ValueError("provide at most 1024 signed validation trials")

    roster = set(cases)
    slots: dict[HoldoutCase, dict[str, GameTrial]] = {case: {} for case in cases}
    seen_trials: set[str] = set()
    seen_runs: set[str] = set()
    for signed in signed_trials:
        if not isinstance(signed, SignedHoldoutTrial) or not isinstance(signed.trial, GameTrial):
            raise TypeError("expected host-signed GameTrial")
        trial = signed.trial
        if trial.split != "validation":
            raise PermissionError("practice evidence cannot be reused as a holdout")
        if trial.action_id not in (baseline_action_id, candidate_action_id):
            raise ValueError("unexpected action in sealed validation cohort")
        case = HoldoutCase(trial.game_id, trial.game_version, trial.objective_id, trial.situation_id)
        if case not in roster:
            raise ValueError("trial was not in the preregistered holdout roster")
        if not (0 <= now_unix_s - trial.observed_unix_s <= _MAX_VALIDATION_AGE_S):
            raise ValueError("stale or future-dated validation trial")
        if type(signed.receipt) is not str or not _SHA.fullmatch(signed.receipt):
            raise PermissionError("invalid validation receipt")
        expected = hmac.new(validation_key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signed.receipt):
            raise PermissionError("independent validation signature mismatch")
        if trial.trial_id in seen_trials or trial.run_id in seen_runs:
            raise ValueError("reused trial/run identity across validation cases")
        if trial.action_id in slots[case]:
            raise ValueError("duplicate variant in the same holdout case")
        seen_trials.add(trial.trial_id)
        seen_runs.add(trial.run_id)
        slots[case][trial.action_id] = trial

    completed = [slot for slot in slots.values() if len(slot) == 2]
    incomplete = len(cases) - len(completed)
    distinct_games = len({case.game_id for case in cases})
    if incomplete:
        # Do not reveal results of a selectively incomplete evaluation.
        return TransferReport("inconclusive", len(cases), len(completed), incomplete,
                              distinct_games, None, None, None, 0, 0, None)

    counts: dict[str, list[int]] = {}
    baseline_wins = candidate_wins = candidate_only = baseline_only = 0
    for case, slot in slots.items():
        base = slot[baseline_action_id]
        candidate = slot[candidate_action_id]
        # If conditions drifted by more than one day, comparisons aren't matched.
        if abs(base.observed_unix_s - candidate.observed_unix_s) > 86400:
            raise ValueError("paired runs were not executed within one day")
        b, c = int(base.outcome == "success"), int(candidate.outcome == "success")
        baseline_wins += b
        candidate_wins += c
        candidate_only += int(c == 1 and b == 0)
        baseline_only += int(b == 1 and c == 0)
        values = counts.setdefault(case.game_id, [0, 0, 0])
        values[0] += 1
        values[1] += b
        values[2] += c

    total = len(cases)
    p_value = _one_sided_p(candidate_only, baseline_only)
    gain = (candidate_wins - baseline_wins) / total
    coverage = (total >= minimum_pairs and distinct_games >= minimum_games
                and all(n >= min_cases_per_game for n, _, _ in counts.values()))
    # A large aggregate gain should not conceal a catastrophic game regression.
    no_major_per_game_regression = all((c - b) / n >= -0.2 - 1e-12
                                       for n, b, c in counts.values())
    eligible = (coverage and gain >= 0.10 - 1e-12 and p_value < 0.025
                and no_major_per_game_regression)
    regressed = (coverage and gain <= -0.10 + 1e-12
                 and _one_sided_p(baseline_only, candidate_only) < 0.025)
    return TransferReport(
        "eligible_for_owner_pilot" if eligible else "regressed" if regressed else "inconclusive",
        total, total, 0, distinct_games,
        round(baseline_wins / total, 4), round(candidate_wins / total, 4),
        round(gain, 4), candidate_only, baseline_only, round(p_value, 7),
    )


__all__ = ["HoldoutCase", "SignedHoldoutTrial", "TransferReport", "roster_digest", "evaluate_transfer"]
