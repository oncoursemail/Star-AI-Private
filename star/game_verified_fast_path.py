"""Bounded, cached *independently evaluated* skill hints for Star's game loop.

Reading the signed SQLite GameplaySkillBank every 16 ms wastes frame budget.
The host refreshes this one-situation cache on its database-owning worker.
The real-time caller only performs O(1) scope, freshness and focus checks.

This module NEVER sends input, runs a model, discloses individual hidden
holdout cases, starts a stream or authorizes a game action. A cached hint is not proof that
the game is in the claimed state. The host must independently authenticate
game focus, obtain a physical input permit and use its key-up watchdog.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
import time
from typing import Callable, cast

from .gameplay_skill_bank import GameplaySkillBank, SkillSuggestion

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_CLOCK = 1e13


def _ms(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("trusted monotonic milliseconds required")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid monotonic clock") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK:
        raise ValueError("invalid monotonic clock")
    return number


def _id(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("host scope must be a bounded identifier")
    return value


@dataclass(frozen=True)
class FastSkillAdvice:
    status: str  # candidate_for_host_review | hold
    reason: str
    action_id: str | None = None
    authorized_to_play: bool = False
    authorizes_game_input: bool = False


@dataclass(frozen=True)
class _Snapshot:
    suggestion: SkillSuggestion
    sampled_ms: float
    expires_ms: float
    generation: int


class VerifiedGameSkillFastPath:
    """Owner-scoped, single-situation cache; no live DB queries in advise().

    A separate host worker must call refresh() with the REAL signed bank.
    refresh() may be slow and must NEVER run on a game render/input thread.
    Concurrent disable/refresh or slow/out-of-order refreshes are rejected.
    An application must keep the bank, validation signing key, and this
    instance inaccessible to model and viewer tools.
    """

    def __init__(
        self,
        bank: GameplaySkillBank,
        *,
        game_id: str,
        game_version: str,
        objective_id: str,
        situation_id: str,
        allowed_actions: tuple[str, ...],
        cache_ttl_ms: int = 1000,
        min_practice: int = 8,
        min_validation: int = 12,
        min_validation_lower_bound: float = 0.60,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
    ) -> None:
        if type(bank) is not GameplaySkillBank:
            raise TypeError("independent signed GameplaySkillBank required")
        self._scope = tuple(
            _id(x)
            for x in (
                game_id,
                game_version,
                objective_id,
                situation_id,
            )
        )
        if (
            type(allowed_actions) is not tuple
            or not 1 <= len(allowed_actions) <= 16
            or len(set(allowed_actions)) != len(allowed_actions)
        ):
            raise ValueError("1..16 distinct trusted action IDs required")
        self._allowed = frozenset(_id(action) for action in allowed_actions)
        if type(cache_ttl_ms) is not int or not 50 <= cache_ttl_ms <= 10_000:
            raise ValueError("cache TTL must be 50..10000 ms")
        if (
            type(min_practice) is not int
            or not 5 <= min_practice <= 100
            or type(min_validation) is not int
            or not 8 <= min_validation <= 100
            or type(min_validation_lower_bound) not in (int, float)
            or not math.isfinite(min_validation_lower_bound)
            or not 0.55 <= min_validation_lower_bound <= 0.95
        ):
            raise ValueError("invalid independently validated skill thresholds")
        if not callable(clock_ms):
            raise TypeError("trusted monotonic clock callback required")
        self._clock_ms = clock_ms
        self._bank = bank
        self._cache_ttl_ms = cache_ttl_ms
        self._thresholds = (min_practice, min_validation, float(min_validation_lower_bound))
        self._lock = RLock()
        self._enabled = False
        self._generation = 0
        self._refresh_serial = 0
        self._highwater_ms = 0.0
        self._snapshot: _Snapshot | None = None
        self._counts = {
            "refreshes": 0,
            "candidates": 0,
            "holds": 0,
            "stale": 0,
            "bad_scope": 0,
            "superseded_refreshes": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("local game-skill fast path requires owner opt-in")
        with self._lock:
            if self._enabled:
                raise RuntimeError("fast path already enabled")
            self._enabled = True
            self._generation += 1
            self._highwater_ms = 0.0
            self._snapshot = None

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._generation += 1
            self._snapshot = None

    def refresh(self, *, now_unix_s: int) -> bool:
        """Refresh only on the trusted bank's SQLite-owner worker.

        A concurrently cancelled or slower older refresh cannot resurrect a
        candidate. Only a host-owned aggregate from the signed bank is cached;
        no heldout case identities or receipts enter this module's API.
        """
        if type(now_unix_s) is not int or not 1 <= now_unix_s <= 10**11:
            raise ValueError("trusted Unix timestamp required")
        start = _ms(self._clock_ms())
        with self._lock:
            if not self._enabled:
                return False
            generation = self._generation
            self._refresh_serial += 1
            refresh_serial = self._refresh_serial
            if start < self._highwater_ms:
                self._snapshot = None
                self._counts["stale"] += 1
                return False
        # Expensive bank verification deliberately occurs OUTSIDE the real-time
        # lock: advise() must never wait for SQLite or HMAC verification.
        try:
            suggestion = self._bank.suggest(
                *self._scope,
                now_unix_s=now_unix_s,
                min_practice=self._thresholds[0],
                min_validation=self._thresholds[1],
                min_validation_lower_bound=self._thresholds[2],
            )
        except Exception:
            # Corrupt/locked/missing evidence must invalidate old advice;
            # don't mask the original diagnostic on the trusted worker.
            with self._lock:
                if self._generation == generation and self._refresh_serial == refresh_serial:
                    self._snapshot = None
            raise
        completed = _ms(self._clock_ms())
        with self._lock:
            if (
                not self._enabled
                or generation != self._generation
                or refresh_serial != self._refresh_serial
                or completed < start
                or completed < self._highwater_ms
            ):
                self._counts["superseded_refreshes"] += 1
                return False
            self._snapshot = _Snapshot(suggestion, completed, completed + self._cache_ttl_ms, generation)
            self._highwater_ms = completed
            self._counts["refreshes"] += 1
            return suggestion.status == "ready_for_host_review" and suggestion.action_id in self._allowed

    def advise(
        self,
        *,
        now_ms: float,
        game_id: str,
        game_version: str,
        objective_id: str,
        situation_id: str,
        host_scope_verified: bool,
        game_focused: bool,
        gameplay_critical: bool = False,
    ) -> FastSkillAdvice:
        """Constant-time hint for the trusted host; never a physical action."""
        now = _ms(now_ms)
        if any(
            type(x) is not bool
            for x in (
                host_scope_verified,
                game_focused,
                gameplay_critical,
            )
        ):
            raise ValueError("trusted live-state observations must be booleans")
        scope = tuple(
            _id(x)
            for x in (
                game_id,
                game_version,
                objective_id,
                situation_id,
            )
        )
        with self._lock:

            def hold(reason: str) -> FastSkillAdvice:
                self._counts["holds"] += 1
                return FastSkillAdvice("hold", reason)

            if not self._enabled:
                return hold("owner_opt_in_missing")
            if now < self._highwater_ms:
                self._snapshot = None
                self._counts["stale"] += 1
                return hold("host_monotonic_clock_reversed")
            self._highwater_ms = now
            if not host_scope_verified or scope != self._scope:
                self._counts["bad_scope"] += 1
                return hold("unverified_or_changed_game_situation")
            if not game_focused:
                return hold("game_focus_lost")
            if gameplay_critical:
                return hold("critical_gameplay_fast_path_suppressed")
            snapshot = self._snapshot
            if (
                snapshot is None
                or snapshot.generation != self._generation
                or now > snapshot.expires_ms
                or now < snapshot.sampled_ms
            ):
                self._counts["stale"] += 1
                return hold("missing_or_expired_signed_skill_snapshot")
            hint = snapshot.suggestion
            if hint.status != "ready_for_host_review" or hint.action_id not in self._allowed:
                return hold("independent_validation_or_action_allowlist_missing")
            self._counts["candidates"] += 1
            return FastSkillAdvice(
                "candidate_for_host_review",
                "fresh_signed_holdout_checked_hint",
                hint.action_id,
            )

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate counters only: no private experiments or viewer data."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled, "cached": self._snapshot is not None}


__all__ = ["VerifiedGameSkillFastPath", "FastSkillAdvice"]
