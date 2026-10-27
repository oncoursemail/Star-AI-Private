"""Fair, signed-evidence OFFLINE practice across several owner-curated games.

STAR's existing GameLearningLadder learns one game/version/objective at a time.
This coordinator multiplexes those independent ladders through a single
ActivePracticePlanner. It schedules different games without making up wins,
inspecting held-out validation, starting a game, or sending any input.

Important: this is a scheduler, NOT a game controller or a learning model.
The trusted host must separately authorize a private game environment, obtain
an input permit, run the action and submit an independently signed PRACTICE
GameTrial with the exact reserved run_id. Keep all signing keys host-side.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from threading import RLock
from typing import Sequence

from .active_practice import ActivePracticePlanner
from .game_learning_ladder import GameLearningLadder, LadderAdvice
from .game_prediction_lab import GamePredictionLab
from .gameplay_skill_bank import GameplaySkillBank
from .stream_budget import StreamTelemetry, advise_workload

_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


@dataclass(frozen=True)
class PortfolioAdvice:
    status: str  # practice_candidate | deferred | manual_diagnosis | complete
    reason: str
    game_id: str | None = None
    game_version: str | None = None
    objective_id: str | None = None
    situation_id: str | None = None
    action_id: str | None = None
    difficulty: int | None = None
    ticket: int | None = None
    expected_run_id: str | None = None
    authorized_to_play: bool = False


@dataclass(frozen=True)
class _Pending:
    ticket: int
    game_index: int
    expires_at: int
    offer: PortfolioAdvice


class GamePortfolioPractice:
    """Advisory cross-game curriculum with one host-signed trial at a time.

    The host constructs each ladder with a curated versioned game scenario,
    opts into EACH ladder separately, then opts into this portfolio. This
    component owns its private ActivePracticePlanner and can safely disable
    pending reservations without touching other agents' pending work.

    Fairness uses the *number of offers* rather than claimed success: a broken
    game cannot monopolize every practice slot. Unverified attempts introduce
    bounded per-game cooldowns and eventually require manual diagnosis.
    Completion/mastery always remains ladder/practice-only evidence; separate
    holdout evaluation is required before claiming cross-game proficiency.

    An optional owner-supplied, independently enabled GamePredictionLab can
    prioritize *already eligible* actions with repeatedly inaccurate forecasts.
    This breaks ties among equally offered games; focus never overrides
    prerequisites, failure cooldowns, stream priority or signed results.
    """

    def __init__(
        self, bank: GameplaySkillBank, *,
        ladders: Sequence[GameLearningLadder],
        reservation_seconds: int = 90,
        unverified_cooldown_seconds: int = 15,
        max_unverified_per_game: int = 3,
        prediction_lab: GamePredictionLab | None = None,
        prediction_model_id: str | None = None,
    ) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("expected a signed GameplaySkillBank")
        if (type(ladders) not in (list, tuple)
                or not 2 <= len(ladders) <= 12
                or any(not isinstance(item, GameLearningLadder) for item in ladders)):
            raise ValueError("provide 2..12 owner-curated per-game ladders")
        if any(getattr(item, "_bank", None) is not bank for item in ladders):
            raise ValueError("every ladder must use the same independent evidence bank")
        # One track per game, not a hundred objectives of one game masquerading
        # as generalization. Versions are still pinned within the ladder.
        games = [item.game_id for item in ladders]
        if len(set(games)) != len(games):
            raise ValueError("portfolio requires distinct game IDs")
        if (prediction_lab is None) != (prediction_model_id is None):
            raise ValueError("forecast routing needs both a verified lab and model ID")
        if prediction_lab is not None:
            if not isinstance(prediction_lab, GamePredictionLab) or prediction_lab._bank is not bank:
                raise ValueError("forecast lab must share the independent signed practice bank")
            if type(prediction_model_id) is not str or not _MODEL_ID.fullmatch(prediction_model_id):
                raise ValueError("forecast model ID must be a bounded host-owned identifier")
        if (type(reservation_seconds) is not int
                or not 10 <= reservation_seconds <= 600
                or type(unverified_cooldown_seconds) is not int
                or not 1 <= unverified_cooldown_seconds <= 600
                or type(max_unverified_per_game) is not int
                or not 1 <= max_unverified_per_game <= 10):
            raise ValueError("invalid bounded portfolio budgets")

        self._ladders = tuple(sorted(ladders, key=lambda x: x.game_id))
        self._prediction_lab = prediction_lab
        self._prediction_model_id = prediction_model_id
        self._planner = ActivePracticePlanner(
            bank, reservation_seconds=reservation_seconds
        )
        self._reservation_s = reservation_seconds
        self._cooldown_s = unverified_cooldown_seconds
        self._max_unverified = max_unverified_per_game
        self._lock = RLock()
        self._enabled = False
        self._clock_s: int | None = None
        self._pending: _Pending | None = None
        self._offers = [0] * len(self._ladders)
        self._unverified = [0] * len(self._ladders)
        self._cooldowns = [0] * len(self._ladders)
        self._stats = {
            "offered": 0, "deferred": 0, "verified": 0,
            "unverified": 0, "expired": 0, "reviews": 0,
            "focus_routed": 0, "focus_unavailable": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("portfolio practice requires explicit owner opt-in")
        with self._lock:
            if self._enabled:
                raise RuntimeError("portfolio is already enabled")
            self._planner.enable(owner_approved=True)
            self._enabled = True
            self._offers = [0] * len(self._ladders)
            self._unverified = [0] * len(self._ladders)
            self._cooldowns = [0] * len(self._ladders)

    def disable(self) -> None:
        """Invalidate the in-flight reservation, including its signed run ID."""
        with self._lock:
            self._planner.disable()
            self._pending = None
            self._enabled = False
            self._clock_s = None

    def _advance(self, now_unix_s: int) -> int:
        if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
            raise ValueError("now_unix_s must be a positive Unix integer")
        if self._clock_s is not None and now_unix_s < self._clock_s:
            raise ValueError("portfolio clock cannot move backwards")
        self._clock_s = now_unix_s
        if self._pending is not None and now_unix_s > self._pending.expires_at:
            expired = self._pending
            self._pending = None
            # The planner refuses to acknowledge a timed-out run; we must not
            # resurrect it by trusting an old host-reported completion.
            self._planner.finish(
                expired.ticket, now_unix_s=now_unix_s,
                host_reports_recorded=False,
            )
            self._record_unverified(expired.game_index, now_unix_s)
            self._stats["expired"] += 1
        return now_unix_s

    def _record_unverified(self, idx: int, now: int) -> None:
        self._stats["unverified"] += 1
        self._unverified[idx] += 1
        self._cooldowns[idx] = now + self._cooldown_s

    def reserve(
        self, *, now_unix_s: int,
        telemetry: StreamTelemetry | None,
    ) -> PortfolioAdvice:
        """Choose one fair, practice-only game action with a scoped run ID."""
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be trusted StreamTelemetry or None")
        with self._lock:
            now = self._advance(now_unix_s)

            def defer(reason: str, *, status: str = "deferred") -> PortfolioAdvice:
                self._stats["deferred"] += 1
                return PortfolioAdvice(status, reason)

            if not self._enabled:
                return defer("owner_opt_in_missing")
            if self._pending is not None:
                return defer("signed_practice_pending")
            if telemetry is None:
                return defer("trusted_telemetry_missing")
            if telemetry.live:
                return defer("stream_live_no_background_practice")
            if telemetry.game_active and telemetry.game_fps < 50:
                return defer("gameplay_fps_protected")
            if telemetry.speech_backlog_ms > 250:
                return defer("audible_speech_protected")
            if not advise_workload("training", telemetry).allowed:
                return defer("insufficient_offline_compute_headroom")

            candidates: list[tuple[int, LadderAdvice]] = []
            statuses: list[str] = []
            for idx, ladder in enumerate(self._ladders):
                if self._unverified[idx] >= self._max_unverified:
                    statuses.append("manual_diagnosis")
                    continue
                if now < self._cooldowns[idx]:
                    statuses.append("cooldown")
                    continue
                advice = ladder.recommend(now_unix_s=now, telemetry=telemetry)
                statuses.append(advice.status)
                if advice.status == "practice_candidate":
                    candidates.append((idx, advice))
            if not candidates:
                if statuses and all(x == "complete" for x in statuses):
                    return defer("practice_mastery_not_holdout_proof", status="complete")
                if "manual_diagnosis" in statuses and not (
                    "deferred" in statuses or "cooldown" in statuses
                ):
                    self._stats["reviews"] += 1
                    return defer("game_mechanics_need_review", status="manual_diagnosis")
                return defer("no_safe_practice_candidate")

            # Never let a forecast outrank fair coverage, private-game safety,
            # owner-curated actions, prerequisite mastery or retry cooldowns.
            # Only consult diagnostics for games tied at the lowest offer count.
            lowest_offers = min(self._offers[idx] for idx, _ in candidates)
            focus: dict[int, float] = {}
            if self._prediction_lab is not None:
                try:
                    if self._prediction_lab.metrics()["enabled"] is True:
                        assert self._prediction_model_id is not None
                        for idx, target in candidates:
                            if self._offers[idx] != lowest_offers:
                                continue
                            ladder = self._ladders[idx]
                            for card in self._prediction_lab.focus_suggestions(
                                self._prediction_model_id, game_id=ladder.game_id,
                                game_version=ladder.game_version,
                                now_unix_s=now, minimum_trials=8, limit=10,
                            ):
                                if (card.authorized_to_play is False
                                        and card.objective_id == ladder.objective_id
                                        and card.situation_id == target.situation_id
                                        and card.action_id == target.action_id):
                                    focus[idx] = card.brier_score * min(1.0, card.trials / 24)
                                    break
                except Exception:
                    # Closed or corrupt diagnostic stores must not authorize
                    # practice or silently become model-authored priorities.
                    self._stats["focus_unavailable"] += 1
                    return defer("verified_prediction_diagnostics_unavailable")

            # Exposure fairness is primary. Among tied games, prefer a real
            # verified prediction-error pattern, not a model's self-report.
            idx, target = min(candidates, key=lambda pair: (
                self._offers[pair[0]], -focus.get(pair[0], 0.0),
                pair[1].practice_trials, pair[1].difficulty or 0,
                self._ladders[pair[0]].game_id,
            ))
            ladder = self._ladders[idx]
            assert target.situation_id is not None and target.action_id is not None
            reservation = self._planner.reserve(
                ladder.game_id, ladder.game_version, ladder.objective_id,
                target.situation_id, (target.action_id,),
                now_unix_s=now, telemetry=telemetry,
            )
            if (reservation.status != "practice_candidate"
                    or reservation.ticket is None
                    or reservation.expected_run_id is None):
                return defer("practice_planner_" + reservation.reason)
            offer = PortfolioAdvice(
                "practice_candidate", "fair_cross_game_signed_practice_only",
                ladder.game_id, ladder.game_version, ladder.objective_id,
                target.situation_id, target.action_id, target.difficulty,
                reservation.ticket, reservation.expected_run_id,
            )
            self._pending = _Pending(
                reservation.ticket, idx, now + self._reservation_s, offer
            )
            self._offers[idx] += 1
            self._stats["offered"] += 1
            if focus.get(idx, 0.0) > 0:
                self._stats["focus_routed"] += 1
            return offer

    def matches_reservation(
        self, offer: PortfolioAdvice, *, now_unix_s: int,
    ) -> bool:
        """Check a complete active game/run/action binding, never grant input.

        The random run ID is an evidence correlation identifier, NOT a Studio
        permission. This check must be repeated at the actual dispatch boundary;
        caller must still use the separate private-Studio input authorization.
        """
        if not isinstance(offer, PortfolioAdvice):
            raise TypeError("offer must be a PortfolioAdvice")
        with self._lock:
            now = self._advance(now_unix_s)
            return bool(self._enabled and self._pending is not None
                        and now <= self._pending.expires_at
                        and offer == self._pending.offer
                        and offer.authorized_to_play is False)

    def finish(
        self, ticket: int, *, now_unix_s: int,
        host_reports_recorded: bool = False,
    ) -> bool:
        """Accept only independently signed evidence for the exact reservation."""
        if type(ticket) is not int or ticket < 1 or type(host_reports_recorded) is not bool:
            raise ValueError("expected exact ticket and explicit host receipt flag")
        with self._lock:
            now = self._advance(now_unix_s)
            if not self._enabled or self._pending is None or ticket != self._pending.ticket:
                return False
            idx = self._pending.game_index
            verified = self._planner.finish(
                ticket, now_unix_s=now,
                host_reports_recorded=host_reports_recorded,
            )
            self._pending = None
            if verified:
                self._stats["verified"] += 1
                self._unverified[idx] = 0
            else:
                self._record_unverified(idx, now)
            return verified

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate counters only, no game IDs, run tokens, receipts or keys."""
        with self._lock:
            return {
                **self._stats, "enabled": self._enabled,
                "pending": self._pending is not None,
                "games": len(self._ladders),
                "games_requiring_review": sum(
                    count >= self._max_unverified for count in self._unverified
                ),
            }


__all__ = ["PortfolioAdvice", "GamePortfolioPractice"]
