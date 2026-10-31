"""Bounded practice-only curriculum advisor for STAR's authorized game lab.

This planner consumes GameplaySkillBank.practice_evidence(), which has already
verified host-signed PRACTICE receipts. It never queries held-out validation,
presses game keys, contacts a model, starts Studio or approves its own lessons.
Host-curated targets are an allowlist; an LLM-suggested target is not authorized.

The progression policy is intentionally conservative: each listed situation
at the current difficulty must clear a practice confidence threshold before
harder exercises become eligible. Independent validation is still required to
promote a skill, and practice confidence is not evidence of transfer mastery.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Protocol, Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_TARGETS = 64
_MAX_AGGREGATES = 256


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded canonical identifier")
    return value


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer in {minimum}..{maximum}")
    return value


def _lower_bound(successes: int, trials: int) -> float:
    """Wilson 95% lower confidence bound; descriptive, never causal proof."""
    if trials == 0:
        return 0.0
    z = 1.959963984540054
    p = successes / trials
    z2 = z * z
    return max(0.0, (p + z2 / (2 * trials) - z * math.sqrt(
        p * (1 - p) / trials + z2 / (4 * trials * trials)
    )) / (1 + z2 / trials))


@dataclass(frozen=True)
class PracticeTarget:
    """A host-approved scenario/action pairing. IDs are not executable inputs."""

    game_id: str
    game_version: str
    objective_id: str
    situation_id: str
    action_id: str
    difficulty: int  # 1..5; the host authors/validates each level

    def __post_init__(self) -> None:
        for field in ("game_id", "game_version", "objective_id", "situation_id", "action_id"):
            _id(getattr(self, field), field)
        _integer(self.difficulty, "difficulty", 1, 5)


class PracticeSummary(Protocol):
    action_id: str
    trials: int
    successes: int
    most_recent_unix_s: int


class PracticeEvidenceSource(Protocol):
    def practice_evidence(self, game_id: str, game_version: str,
                          objective_id: str, situation_id: str, *,
                          now_unix_s: int) -> Sequence[PracticeSummary]: ...


@dataclass(frozen=True)
class PracticeAdvice:
    status: str  # disabled | no_targets | rehearse | review_required | complete
    target: PracticeTarget | None
    reason: str
    trials: int = 0
    successes: int = 0
    practice_lower_bound: float = 0.0
    authorized_to_play: bool = False
    heldout_evaluated: bool = False


def recommend_practice(
    bank: PracticeEvidenceSource, *, targets: Sequence[PracticeTarget],
    now_unix_s: int, owner_approved: bool = False,
    min_trials: int = 8, minimum_lower_bound: float = 0.55,
    max_trials_before_review: int = 40,
) -> PracticeAdvice:
    """Propose *one* next practice exercise without leaking validation.

    Require affirmative owner/session enablement. The host must retain control
    over permitted games, target curation, game focus and action dispatch.
    All records are evaluated from the exact same frozen practice-only view.
    Unverified/corrupted evidence causes an exception, never an action.
    """
    if type(owner_approved) is not bool:
        raise ValueError("owner_approved must be a boolean")
    if not owner_approved:
        return PracticeAdvice("disabled", None, "owner_session_opt_in_missing")
    now = _integer(now_unix_s, "now_unix_s", 1, 10**11)
    _integer(min_trials, "min_trials", 5, 100)
    _integer(max_trials_before_review, "max_trials_before_review", 10, 1000)
    if max_trials_before_review <= min_trials:
        raise ValueError("review budget must exceed minimum evidence count")
    if (type(minimum_lower_bound) not in (int, float)
            or not math.isfinite(minimum_lower_bound)
            or not 0.50 <= minimum_lower_bound <= 0.90):
        raise ValueError("minimum_lower_bound must be 0.50..0.90")
    if not isinstance(targets, (list, tuple)) or len(targets) > _MAX_TARGETS:
        raise ValueError("targets must be a bounded list or tuple")
    if not targets:
        return PracticeAdvice("no_targets", None, "host_has_not_curated_practice_targets")
    if any(not isinstance(t, PracticeTarget) for t in targets):
        raise TypeError("expected host-curated PracticeTarget entries")
    anchor = (targets[0].game_id, targets[0].game_version, targets[0].objective_id)
    if any((t.game_id, t.game_version, t.objective_id) != anchor for t in targets):
        raise ValueError("one game, version and objective per curriculum")
    keys = [(t.situation_id, t.action_id) for t in targets]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate situation/action would distort coverage")
    # A caller cannot redefine the difficulty of one situation in the same
    # curriculum; choose distinct canonical situation IDs for distinct stages.
    situations: dict[str, int] = {}
    for target in targets:
        known = situations.setdefault(target.situation_id, target.difficulty)
        if known != target.difficulty:
            raise ValueError("one situation cannot belong to multiple difficulties")

    # One verified bank lookup per situation. The bank authenticates *every*
    # row before disclosing practice summaries and excludes validation entirely.
    scopes: dict[str, dict[str, PracticeSummary]] = {}
    for situation in sorted(situations):
        summaries = bank.practice_evidence(*anchor, situation, now_unix_s=now)
        if not isinstance(summaries, (list, tuple)) or len(summaries) > _MAX_AGGREGATES:
            raise ValueError("invalid or oversized signed-practice summary")
        by_action: dict[str, PracticeSummary] = {}
        for item in summaries:
            action = _id(item.action_id, "signed action")
            count = _integer(item.trials, "signed trials", 1, 50_000)
            _integer(item.successes, "signed successes", 0, count)
            _integer(item.most_recent_unix_s, "signed recency", 1, now)
            if action in by_action:
                raise ValueError("duplicate signed action aggregate")
            by_action[action] = item
        scopes[situation] = by_action

    pending: list[tuple[PracticeTarget, int, int, float, int]] = []
    for target in targets:
        item = scopes[target.situation_id].get(target.action_id)
        attempts = item.trials if item is not None else 0
        successes = item.successes if item is not None else 0
        recent = item.most_recent_unix_s if item is not None else 0
        lower = _lower_bound(successes, attempts)
        mastered = attempts >= min_trials and lower >= minimum_lower_bound
        if not mastered:
            pending.append((target, attempts, successes, lower, recent))
    if not pending:
        return PracticeAdvice("complete", None,
                              "practice_only_complete_requires_independent_validation")

    # An unmastered lower-tier situation blocks the harder tier; otherwise a
    # strong result on one easy map can hide a failure on another map.
    frontier = min(item[0].difficulty for item in pending)
    candidates = [item for item in pending if item[0].difficulty == frontier]
    # Stop infinite ineffective self-play after a bounded failure budget.
    stalled = [item for item in candidates if item[1] >= max_trials_before_review]
    if stalled:
        target, attempts, successes, lower, _ = min(
            stalled, key=lambda item: (item[0].situation_id, item[0].action_id)
        )
        return PracticeAdvice("review_required", target, "practice_stalled_needs_host_review",
                              attempts, successes, round(lower, 4))
    # Cover neglected scenarios before repeatedly grinding a familiar one.
    target, attempts, successes, lower, _ = min(
        candidates,
        key=lambda item: (item[1], item[3], item[4],
                          item[0].situation_id, item[0].action_id),
    )
    return PracticeAdvice("rehearse", target, "lowest_unmastered_difficulty",
                          attempts, successes, round(lower, 4))


__all__ = ["PracticeTarget", "PracticeAdvice", "recommend_practice"]
