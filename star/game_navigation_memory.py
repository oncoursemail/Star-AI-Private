"""Bounded, episode-local navigation memory for offline/private game practice.

This advisor turns host-verified observations into symbolic movement hints.
Unknown space is never treated as traversable. It cannot see the game, press
keys, authorize a model, publish OBS, or prove that an observation was real.
A separate trusted game host must supply verified frames and independently
gate any actual control through GameActionGate / RealtimeGameLoop.

The planner uses Dijkstra on observed walkable cells, avoiding reported high
risk and retaining an explicit frontier-exploration state. It is NOT a
cross-game trained policy or evidence of gaming performance on real games.
"""
from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
import math
import re
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_CELLS = 4096
_NEIGHBORS = ((0, -1, "up"), (-1, 0, "left"), (1, 0, "right"), (0, 1, "down"))
_RISK_BLOCK = 7500


def _clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host clock must be numeric")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid host clock") from exc
    if not math.isfinite(number) or not 0 <= number <= 1e13:
        raise ValueError("host clock out of bounds")
    return number


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be an opaque bounded ID")
    return value


@dataclass(frozen=True, order=True)
class GridPosition:
    x: int
    y: int

    def __post_init__(self) -> None:
        if (type(self.x) is not int or type(self.y) is not int
                or not -32 <= self.x <= 31 or not -32 <= self.y <= 31):
            raise ValueError("grid coordinates must be integers in [-32, 31]")


@dataclass(frozen=True)
class ObservedTile:
    position: GridPosition
    walkable: bool
    risk_bps: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.position, GridPosition):
            raise TypeError("observed tile requires grid position")
        if type(self.walkable) is not bool:
            raise ValueError("walkable must be host verified boolean")
        if type(self.risk_bps) is not int or not 0 <= self.risk_bps <= 10000:
            raise ValueError("risk_bps must be a bounded integer")


@dataclass(frozen=True)
class NavigationObservation:
    game_id: str
    game_version: str
    episode_id: str
    sequence: int
    captured_ms: float
    player: GridPosition
    tiles: tuple[ObservedTile, ...]
    goal: GridPosition | None = None

    def __post_init__(self) -> None:
        for name in ("game_id", "game_version", "episode_id"):
            _id(getattr(self, name), name)
        if type(self.sequence) is not int or not 1 <= self.sequence <= 2**63 - 1:
            raise ValueError("sequence must strictly increase within the episode")
        _clock(self.captured_ms)
        if not isinstance(self.player, GridPosition):
            raise TypeError("player requires GridPosition")
        if self.goal is not None and not isinstance(self.goal, GridPosition):
            raise TypeError("goal requires GridPosition")
        if type(self.tiles) is not tuple or not 1 <= len(self.tiles) <= 128:
            raise ValueError("observation must contain 1..128 host-witnessed tiles")
        seen: set[GridPosition] = set()
        player_ok = False
        for tile in self.tiles:
            if not isinstance(tile, ObservedTile) or tile.position in seen:
                raise ValueError("tiles must be typed and unique")
            seen.add(tile.position)
            if tile.position == self.player:
                player_ok = tile.walkable and tile.risk_bps < _RISK_BLOCK
        if not player_ok:
            raise ValueError("player position must be witnessed as safe walkable")


@dataclass(frozen=True)
class NavigationAdvice:
    status: str          # move | observe | await_observation | arrived | abstain
    reason: str
    action_id: str | None = None   # symbolic only; never an OS key
    target: GridPosition | None = None
    observed_cells: int = 0
    authorizes_input: bool = False
    authorizes_broadcast: bool = False


class GroundedNavigationMemory:
    """Owner-enabled, fixed-session map learner. Advises only in private lab."""

    def __init__(self, *, max_observation_age_ms: int = 600) -> None:
        if (type(max_observation_age_ms) is not int
                or not 100 <= max_observation_age_ms <= 3000):
            raise ValueError("max observation age must be 100..3000 ms")
        self._max_age = max_observation_age_ms
        self._lock = RLock()
        self._scope: tuple[str, str, str] | None = None
        self._tiles: dict[GridPosition, ObservedTile] = {}
        self._last_sequence = 0
        self._last_capture_ms = -1.0
        self._last_host_ms = -1.0
        self._observation: NavigationObservation | None = None
        self._frontier_requested_seq: int | None = None
        self._counts = {"accepted": 0, "rejected": 0, "moves": 0,
                        "observe_requests": 0, "abstentions": 0}

    def start(
        self, *, game_id: str, game_version: str, episode_id: str,
        owner_approved: bool = False,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("private practice requires owner permission")
        scope = (_id(game_id, "game_id"), _id(game_version, "game_version"),
                 _id(episode_id, "episode_id"))
        with self._lock:
            if self._scope is not None:
                raise RuntimeError("explicit stop required before another episode")
            self._scope = scope
            self._tiles.clear()
            self._observation = None
            self._last_sequence = 0
            self._last_capture_ms = -1
            self._last_host_ms = -1
            self._frontier_requested_seq = None

    def stop(self) -> None:
        with self._lock:
            self._scope = None
            self._tiles.clear()
            self._observation = None
            self._frontier_requested_seq = None

    def ingest(
        self, observation: NavigationObservation, *, now_ms: float,
        host_verified: bool = False,
    ) -> bool:
        if not isinstance(observation, NavigationObservation):
            raise TypeError("expected typed host observation")
        now = _clock(now_ms)
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be boolean")
        with self._lock:
            if (self._scope is None
                    or self._scope != (observation.game_id,
                                      observation.game_version,
                                      observation.episode_id)
                    or not host_verified
                    or observation.sequence <= self._last_sequence
                    or observation.captured_ms <= self._last_capture_ms
                    or now < self._last_host_ms
                    or observation.captured_ms > now
                    or now - observation.captured_ms > self._max_age
                    or len(self._tiles.keys() | {t.position for t in observation.tiles})
                       > _MAX_CELLS):
                self._counts["rejected"] += 1
                return False
            self._tiles.update({t.position: t for t in observation.tiles})
            self._last_sequence = observation.sequence
            self._last_capture_ms = observation.captured_ms
            self._last_host_ms = now
            self._observation = observation
            self._frontier_requested_seq = None
            self._counts["accepted"] += 1
            return True

    @staticmethod
    def _adjacent(position: GridPosition) -> tuple[tuple[GridPosition, str], ...]:
        result: list[tuple[GridPosition, str]] = []
        for dx, dy, action in _NEIGHBORS:
            try:
                next_pos = GridPosition(position.x + dx, position.y + dy)
            except ValueError:
                continue
            result.append((next_pos, action))
        return tuple(result)

    def _paths(
        self, player: GridPosition,
    ) -> tuple[dict[GridPosition, int], dict[GridPosition, tuple[GridPosition, str]]]:
        costs = {player: 0}
        previous: dict[GridPosition, tuple[GridPosition, str]] = {}
        queue: list[tuple[int, GridPosition]] = [(0, player)]
        while queue:
            cost, here = heappop(queue)
            if cost != costs[here]:
                continue
            for neighbor, direction in self._adjacent(here):
                tile = self._tiles.get(neighbor)
                if tile is None or not tile.walkable or tile.risk_bps >= _RISK_BLOCK:
                    continue
                next_cost = cost + 1000 + tile.risk_bps // 2
                if next_cost < costs.get(neighbor, 10**18):
                    costs[neighbor] = next_cost
                    previous[neighbor] = (here, direction)
                    heappush(queue, (next_cost, neighbor))
        return costs, previous

    def advise(self, *, now_ms: float) -> NavigationAdvice:
        now = _clock(now_ms)
        with self._lock:
            observed = len(self._tiles)
            def abstain(reason: str) -> NavigationAdvice:
                self._counts["abstentions"] += 1
                return NavigationAdvice("abstain", reason, observed_cells=observed)

            frame = self._observation
            if self._scope is None or frame is None:
                return abstain("disabled_or_unobserved")
            if now < self._last_host_ms or now < frame.captured_ms:
                return abstain("host_clock_reversed")
            if now - frame.captured_ms > self._max_age:
                return abstain("observation_expired")
            here = frame.player
            goal = frame.goal
            if goal is not None and goal == here:
                return NavigationAdvice("arrived", "witnessed_goal_position",
                                        observed_cells=observed)
            costs, previous = self._paths(here)
            if goal in costs:
                target = goal
                reason = "verified_path_to_goal"
            else:
                # Only known/reachable cells can become exploration frontiers.
                frontiers = [p for p in costs if any(
                    adj not in self._tiles for adj, _ in self._adjacent(p))]
                if not frontiers:
                    return abstain("no_safe_observed_frontier")
                # A stationary host capture cannot expose more tiles merely
                # because the current cell has an unknown neighbor. Prefer a
                # reachable *different* frontier to avoid endless reobserve.
                moving_frontiers = [p for p in frontiers if p != here]
                if moving_frontiers:
                    frontiers = moving_frontiers
                if goal is None:
                    target = min(frontiers, key=lambda p: (costs[p], p))
                else:
                    # A heuristic ranks frontier choices, never authorizes an
                    # unsafe step through unobserved space.
                    target = min(frontiers, key=lambda p: (
                        costs[p] + 1500 * (abs(goal.x - p.x) +
                                          abs(goal.y - p.y)), costs[p], p))
                reason = "explore_witnessed_frontier"
            if target == here:
                if self._frontier_requested_seq == frame.sequence:
                    return NavigationAdvice("await_observation",
                                            "new_host_capture_required",
                                            observed_cells=observed)
                self._frontier_requested_seq = frame.sequence
                self._counts["observe_requests"] += 1
                return NavigationAdvice("observe", reason,
                                        target=target, observed_cells=observed)
            node = target
            while previous[node][0] != here:
                node = previous[node][0]
            direction = previous[node][1]
            self._counts["moves"] += 1
            return NavigationAdvice("move", reason, action_id=direction,
                                    target=target, observed_cells=observed)

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._counts, "enabled": self._scope is not None,
                    "observed_cells": len(self._tiles)}
