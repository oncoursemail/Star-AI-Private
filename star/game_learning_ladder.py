"""Offline, practice-only curriculum ladder for STAR's game-learning agent.

A host predefines small, versioned practice situations and trusted symbolic
actions. This planner selects *where to practice next* using the existing
GameplaySkillBank's signed PRACTICE aggregates, not model claims or withheld
validation results. It never acts in a game, generates a map, performs training,
reads media, talks on stream, or authorizes device access.

Prerequisites form a directed acyclic skill ladder. A situation unlocks only
after enough practice success to cross a conservative Wilson lower bound.
Failing repeatedly produces a design/debug recommendation, not an infinite
retry loop. The actual action host must still obtain independent permission.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from threading import RLock
from typing import Sequence

from .gameplay_skill_bank import GameplaySkillBank, PracticeEvidence, wilson_lower
from .stream_budget import StreamTelemetry, advise_workload

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _id(value: object, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a bounded symbolic ID")
    return value


@dataclass(frozen=True)
class PracticeSituation:
    """Owner/host-curated practice objective; NEVER a hidden evaluation case."""

    situation_id: str
    action_id: str
    difficulty: int
    prerequisites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.situation_id, "situation_id")
        _id(self.action_id, "action_id")
        if type(self.difficulty) is not int or not 1 <= self.difficulty <= 5:
            raise ValueError("difficulty must be an integer from 1 to 5")
        if (type(self.prerequisites) is not tuple
                or len(self.prerequisites) > 8
                or any(type(p) is not str or not _ID.fullmatch(p) for p in self.prerequisites)
                or len(set(self.prerequisites)) != len(self.prerequisites)
                or self.situation_id in self.prerequisites):
            raise ValueError("invalid or duplicate prerequisite situation IDs")


@dataclass(frozen=True)
class LadderAdvice:
    status: str               # practice_candidate | manual_diagnosis | complete | deferred
    reason: str
    situation_id: str | None = None
    action_id: str | None = None
    difficulty: int | None = None
    practice_trials: int = 0
    practice_successes: int = 0
    practice_lower_bound: float = 0.0
    mastered_situations: int = 0
    total_situations: int = 0
    authorized_to_play: bool = False


class GameLearningLadder:
    """Bounded advisory progression without leaking independent validation.

    The practice bank itself checks and aggregates signed events. Each scenario
    has exactly one curated target action; aggregates for other actions, games,
    versions, objectives, situations and validation runs are excluded.

    The host should feed a proposed situation/action into ActivePracticePlanner
    and a separately authorized Studio/game host; this API grants no controls.
    """

    def __init__(self, bank: GameplaySkillBank, *, game_id: str,
                 game_version: str, objective_id: str,
                 situations: Sequence[PracticeSituation], min_trials: int = 12,
                 max_trials: int = 36, mastery_lower_bound: float = 0.55,
                 no_success_review_trials: int = 12) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("bank must be an existing GameplaySkillBank")
        self.game_id = _id(game_id, "game_id")
        self.game_version = _id(game_version, "game_version")
        self.objective_id = _id(objective_id, "objective_id")
        if (type(situations) not in (tuple, list)
                or not 1 <= len(situations) <= 64
                or any(not isinstance(s, PracticeSituation) for s in situations)):
            raise ValueError("provide 1..64 curated practice situations")
        by_id = {s.situation_id: s for s in situations}
        if len(by_id) != len(situations):
            raise ValueError("situation IDs must be unique")
        for s in situations:
            for parent_id in s.prerequisites:
                parent = by_id.get(parent_id)
                if parent is None or parent.difficulty >= s.difficulty:
                    raise ValueError("prerequisites must exist at a lower difficulty")
        # Strictly increasing difficulty along every edge also prohibits cycles.
        if (type(min_trials) is not int or not 6 <= min_trials <= 32
                or type(max_trials) is not int or not min_trials <= max_trials <= 128
                or type(no_success_review_trials) is not int
                or not min_trials <= no_success_review_trials <= max_trials
                or type(mastery_lower_bound) not in (float, int)
                or not 0.50 <= mastery_lower_bound <= 0.90):
            raise ValueError("invalid bounded curriculum thresholds")
        self._bank = bank
        self._situations = tuple(sorted(situations, key=lambda s: (s.difficulty, s.situation_id)))
        self._min_trials = min_trials
        self._max_trials = max_trials
        self._no_success_review = no_success_review_trials
        self._threshold = float(mastery_lower_bound)
        self._enabled = False
        self._lock = RLock()
        self._clock_s: int | None = None

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must explicitly enable the practice curriculum")
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._clock_s = None

    def recommend(self, *, now_unix_s: int,
                  telemetry: StreamTelemetry | None) -> LadderAdvice:
        """Suggest a practice-only situation, never request input or infer wins."""
        if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
            raise ValueError("now_unix_s must be a positive Unix integer")
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be StreamTelemetry or None")
        with self._lock:
            if self._clock_s is not None and now_unix_s < self._clock_s:
                raise ValueError("planner time cannot go backwards")
            self._clock_s = now_unix_s

            def defer(reason: str) -> LadderAdvice:
                return LadderAdvice("deferred", reason, total_situations=len(self._situations))

            if not self._enabled:
                return defer("owner_practice_opt_in_missing")
            if telemetry is None:
                return defer("trusted_host_telemetry_missing")
            if telemetry.live:
                return defer("stream_live_practice_is_paused")
            if telemetry.game_active and telemetry.game_fps < 50:
                return defer("game_fps_below_practice_floor")
            if telemetry.speech_backlog_ms > 250:
                return defer("speech_backlog_protection")
            if not advise_workload("training", telemetry).allowed:
                return defer("insufficient_compute_headroom")

            summaries: dict[str, tuple[int, int, float, bool, bool]] = {}
            for situation in self._situations:
                rows = self._bank.practice_evidence(
                    self.game_id, self.game_version, self.objective_id,
                    situation.situation_id, now_unix_s=now_unix_s,
                )
                # The ledger returns only signed practice aggregates; never
                # inspect validation successes or user/model self-reports.
                evidence = next((x for x in rows if x.action_id == situation.action_id),
                                PracticeEvidence(situation.action_id, 0, 0, 0))
                n, successes = evidence.trials, evidence.successes
                lower = wilson_lower(successes, n) if n else 0.0
                mastered = n >= self._min_trials and lower >= self._threshold
                stalled = (not mastered and (n >= self._max_trials or
                           (n >= self._no_success_review and successes == 0)))
                summaries[situation.situation_id] = (n, successes, lower, mastered, stalled)

            mastered_count = sum(stats[3] for stats in summaries.values())
            if mastered_count == len(self._situations):
                return LadderAdvice("complete", "practice_mastery_requires_separate_holdout",
                                    mastered_situations=mastered_count,
                                    total_situations=len(self._situations))

            eligible = [s for s in self._situations if
                        all(summaries[pre][3] for pre in s.prerequisites)
                        and not summaries[s.situation_id][3]]
            can_train = [s for s in eligible if not summaries[s.situation_id][4]]
            if can_train:
                # Attempt broad coverage before repeatedly practicing a single
                # situation, but do not unlock advanced skills prematurely.
                target = min(can_train, key=lambda s: (
                    s.difficulty, summaries[s.situation_id][0], s.situation_id))
                n, wins, lower, _, _ = summaries[target.situation_id]
                return LadderAdvice(
                    "practice_candidate", "lowest_unmastered_unblocked_practice_situation",
                    target.situation_id, target.action_id, target.difficulty,
                    n, wins, round(lower, 4), mastered_count, len(self._situations))
            stalled = [s for s in eligible if summaries[s.situation_id][4]]
            if stalled:
                target = min(stalled, key=lambda s: (s.difficulty, s.situation_id))
                n, wins, lower, _, _ = summaries[target.situation_id]
                return LadderAdvice(
                    "manual_diagnosis", "repeated_failure_or_practice_budget_exhausted",
                    target.situation_id, target.action_id, target.difficulty,
                    n, wins, round(lower, 4), mastered_count, len(self._situations))
            return defer("prerequisites_not_yet_mastered")


__all__ = ["PracticeSituation", "LadderAdvice", "GameLearningLadder"]
