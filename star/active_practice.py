"""Bounded, evidence-grounded active practice planning for STAR's game learning.

A trusted external host owns game capture, controls, evidence-signing keys and
independent evaluation. This module only suggests symbolic IDs for *offline*
practice. It does not play games, read validation outcomes, run models or
authorize game actions. A signed PRACTICE trial must be added to the bank
before a reservation can be acknowledged as newly learned evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import secrets
from threading import RLock
from typing import Sequence

from .gameplay_skill_bank import GameplaySkillBank, PracticeEvidence
from .stream_budget import StreamTelemetry, advise_workload

_ACTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _second(value: int) -> int:
    if type(value) is not int or not 0 < value <= 10**11:
        raise ValueError("now_unix_s must be a valid integer Unix timestamp")
    return value


def _roster(action_ids: Sequence[str]) -> tuple[str, ...]:
    if type(action_ids) not in (tuple, list) or not 1 <= len(action_ids) <= 32:
        raise ValueError("provide 1..32 curated symbolic action IDs")
    if any(type(a) is not str or not _ACTION.fullmatch(a) for a in action_ids):
        raise ValueError("invalid symbolic action ID")
    if len(set(action_ids)) != len(action_ids):
        raise ValueError("duplicate action ID")
    return tuple(sorted(action_ids))


@dataclass(frozen=True)
class PracticeAdvice:
    status: str
    reason: str
    action_id: str | None = None
    ticket: int | None = None
    prior_trials: int = 0
    priority_score: float = 0.0
    authorized_to_control_game: bool = False
    expected_run_id: str | None = None


@dataclass(frozen=True)
class _Reservation:
    ticket: int
    action_id: str
    expected_run_id: str
    scope: tuple[str, str, str, str]
    prior_trials: int
    started_at: int
    expires_at: int


class ActivePracticePlanner:
    """Suggest the next *practice* action while protecting live performance.

    The curriculum cannot inspect held-out results: the bank's practice-only
    aggregate is its entire learning view. Unknown actions get basic coverage,
    then a Beta(1,1) uncertainty/challenge heuristic schedules further trials.
    The score is a bounded heuristic, NOT estimated improvement or proof of
    model intelligence. Nothing is run when a recommendation is produced.

    Rehearsal receipts must be recorded by a trusted, independent game-observer
    host. The planner checks that new signed evidence exists before accepting
    a host 'completed' assertion; no unsigned self-reported success counts.
    """

    def __init__(self, bank: GameplaySkillBank, *,
                 reservation_seconds: int = 90,
                 spacing_seconds: int = 2,
                 max_trials_per_action: int = 24) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("bank must be a GameplaySkillBank")
        if (type(reservation_seconds) is not int or not 10 <= reservation_seconds <= 600
                or type(spacing_seconds) is not int or not 1 <= spacing_seconds <= 30
                or type(max_trials_per_action) is not int or
                not 8 <= max_trials_per_action <= 100):
            raise ValueError("invalid bounded practice budget")
        self._bank = bank
        self._reservation_seconds = reservation_seconds
        self._spacing_seconds = spacing_seconds
        self._max_trials = max_trials_per_action
        self._lock = RLock()
        self._enabled = False
        self._pending: _Reservation | None = None
        self._clock_s: int | None = None
        self._last_offered: int | None = None
        self._next_ticket = 0
        self._stats = {"offered": 0, "deferred": 0, "expired": 0,
                       "verified": 0, "unverified": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner approval required for practice planning")
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._pending = None
            self._clock_s = None
            self._last_offered = None
            # Keep ticket sequence increasing: stale host receipts never revive.

    def _advance(self, now_unix_s: int) -> int:
        now = _second(now_unix_s)
        if self._clock_s is not None and now < self._clock_s:
            raise ValueError("planner session clock moved backward")
        self._clock_s = now
        if self._pending is not None and now > self._pending.expires_at:
            self._pending = None
            self._stats["expired"] += 1
        return now

    @staticmethod
    def _priority(evidence: PracticeEvidence) -> float:
        """Posterior uncertainty times challenge-zone weight; not an oracle."""
        success = evidence.successes
        failure = evidence.trials - success
        a, b = success + 1, failure + 1
        n = a + b
        mean = a / n
        variance = a * b / (n * n * (n + 1))
        challenge = 0.35 + 0.65 * (1 - abs(2 * mean - 1))
        return math.sqrt(variance) * challenge

    def reserve(self, game_id: str, game_version: str, objective_id: str,
                situation_id: str, action_ids: Sequence[str], *,
                now_unix_s: int, telemetry: StreamTelemetry | None) -> PracticeAdvice:
        """Reserve an offline *suggestion*, never authorization to press keys."""
        roster = _roster(action_ids)
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be a StreamTelemetry")
        with self._lock:
            now = self._advance(now_unix_s)

            def no(reason: str) -> PracticeAdvice:
                self._stats["deferred"] += 1
                return PracticeAdvice("deferred", reason)

            if not self._enabled:
                return no("owner_opt_in_missing")
            if self._pending is not None:
                return no("practice_ticket_in_flight")
            if self._last_offered is not None and now - self._last_offered < self._spacing_seconds:
                return no("practice_spacing_budget")
            if telemetry is None:
                return no("telemetry_missing")
            if telemetry.live:
                return no("stream_is_live")
            # Avoid stealing compute from active gameplay and the voice queue.
            if telemetry.game_active and telemetry.game_fps < 50.0:
                return no("game_fps_below_practice_floor")
            if telemetry.speech_backlog_ms > 250.0:
                return no("voice_backlog_too_high")
            if not advise_workload("training", telemetry).allowed:
                return no("insufficient_offline_compute_headroom")

            rows = self._bank.practice_evidence(
                game_id, game_version, objective_id, situation_id, now_unix_s=now)
            counts = {row.action_id: row for row in rows}
            candidates = [(a, counts.get(a, PracticeEvidence(a, 0, 0, 0)))
                          for a in roster]
            candidates = [(a, record) for a, record in candidates
                          if record.trials < self._max_trials]
            if not candidates:
                return no("practice_budget_exhausted")
            coverage = [(a, record) for a, record in candidates if record.trials < 3]
            if coverage:
                action, selected = min(coverage, key=lambda x: (x[1].trials, x[0]))
                score, reason = 1.0 / (1 + selected.trials), "coverage_first"
            else:
                action, selected = min(candidates, key=lambda x: (
                    -self._priority(x[1]), x[1].trials, x[0]))
                score, reason = self._priority(selected), "uncertainty_guided"

            self._next_ticket += 1
            # Collision-resistant scoped practice identity links a future
            # host-signed GameTrial to THIS reservation, not another run.
            expected_run_id = "apr_" + secrets.token_hex(12)
            self._pending = _Reservation(
                self._next_ticket, action, expected_run_id,
                (game_id, game_version, objective_id, situation_id),
                selected.trials, now, now + self._reservation_seconds)
            self._last_offered = now
            self._stats["offered"] += 1
            return PracticeAdvice("practice_candidate", reason, action,
                                  self._next_ticket, selected.trials,
                                  round(score, 6), expected_run_id=expected_run_id)

    def finish(self, ticket: int, *, now_unix_s: int,
               host_reports_recorded: bool = False) -> bool:
        """Confirm only if the bank gained a fresh host-signed practice trial."""
        if type(ticket) is not int or ticket <= 0 or type(host_reports_recorded) is not bool:
            raise ValueError("explicit receipt acknowledgement and positive ticket required")
        with self._lock:
            now = self._advance(now_unix_s)
            pending = self._pending
            if not self._enabled or pending is None or pending.ticket != ticket:
                return False
            if not host_reports_recorded:
                self._pending = None
                self._stats["unverified"] += 1
                return False
            rows = self._bank.practice_evidence(*pending.scope, now_unix_s=now)
            matching = next((row for row in rows if row.action_id == pending.action_id), None)
            verified = bool(
                matching and matching.trials > pending.prior_trials
                and self._bank.signed_practice_run(
                    *pending.scope, pending.action_id, pending.expected_run_id,
                    not_before_unix_s=pending.started_at, now_unix_s=now)
            )
            self._pending = None
            self._stats["verified" if verified else "unverified"] += 1
            return verified

    def metrics(self) -> dict[str, int | bool]:
        """No user names, game content, signatures, private evidence or keys."""
        with self._lock:
            return {**self._stats, "enabled": self._enabled,
                    "pending": self._pending is not None}


__all__ = ["ActivePracticePlanner", "PracticeAdvice"]
