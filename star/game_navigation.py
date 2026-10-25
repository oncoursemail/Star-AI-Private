"""Host-observed belief-map navigation for opt-in, isolated game practice.

Pure Python: no screenshots, network, model calls, keyboard control or file I/O.
A separately trusted host must interpret observations and authorize actions.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_ACTIONS = (("up", 0, -1), ("left", -1, 0), ("right", 1, 0), ("down", 0, 1))
_WALKABLE = frozenset({"floor", "goal"})
_KINDS = _WALKABLE | {"wall", "hazard"}

def _cell(value: object, width: int, height: int) -> tuple[int, int]:
    if (type(value) is not tuple or len(value) != 2
            or any(type(v) is not int for v in value)
            or not (0 <= value[0] < width and 0 <= value[1] < height)):
        raise ValueError("Invalid grid coordinate")
    return value

@dataclass(frozen=True)
class SeenTile:
    cell: tuple[int, int]
    kind: str

@dataclass(frozen=True)
class GameFrame:
    """Symbolic snapshot provided by a host adapter, not LLM-generated text."""
    game: str
    session: str
    seq: int
    width: int
    height: int
    player: tuple[int, int]
    visible: tuple[SeenTile, ...]

    def __post_init__(self) -> None:
        if any(type(v) is not str or not _ID.fullmatch(v) for v in (self.game, self.session)):
            raise ValueError("Invalid game/session ID")
        if type(self.seq) is not int or not 1 <= self.seq <= 10_000:
            raise ValueError("Sequence out of bounds")
        if (type(self.width) is not int or type(self.height) is not int or
                not 1 <= self.width <= 64 or not 1 <= self.height <= 64 or
                self.width * self.height > 4096):
            raise ValueError("Grid dimensions out of bounds")
        _cell(self.player, self.width, self.height)
        if type(self.visible) is not tuple or not 1 <= len(self.visible) <= 256:
            raise ValueError("Visible tiles must be a bounded tuple")
        points: set[tuple[int, int]] = set()
        player_kind = None
        for tile in self.visible:
            if type(tile) is not SeenTile:
                raise ValueError("Expected SeenTile")
            point = _cell(tile.cell, self.width, self.height)
            if type(tile.kind) is not str or tile.kind not in _KINDS or point in points:
                raise ValueError("Invalid or duplicate visible tile")
            points.add(point)
            if point == self.player:
                player_kind = tile.kind
        if player_kind not in _WALKABLE:
            raise ValueError("Player must be observed on walkable terrain")

@dataclass(frozen=True)
class NavigationAdvice:
    action: str | None
    destination: tuple[int, int] | None
    path: tuple[tuple[int, int], ...]
    reason: str
    exploratory: bool
    observed_cells: int

class NavigationBelief:
    """Bounded deterministic planner, at most O(grid cells) per query.

    PLAY: only traverses known safe cells towards an observed reachable goal.
    PRACTICE: owner-approved sandbox can probe one unknown frontier square,
    then MUST obtain new host observations before the next action.
    Never recommends known walls or hazards; suggestions are not permissions.
    """
    def __init__(self) -> None:
        self._identity: tuple[str, str, int, int] | None = None
        self._seq = 0
        self._player: tuple[int, int] | None = None
        self._known: dict[tuple[int, int], str] = {}

    @property
    def observed_cells(self) -> int:
        return len(self._known)

    def observe(self, frame: GameFrame, *, trusted_host: bool = False) -> None:
        """Caller MUST enforce provenance independently; `trusted_host` is not authentication."""
        if trusted_host is not True:
            raise PermissionError("Trusted host adapter required")
        if type(frame) is not GameFrame:
            raise TypeError("Expected GameFrame")
        identity = (frame.game, frame.session, frame.width, frame.height)
        if self._identity is not None and identity != self._identity:
            raise ValueError("New game/session requires a new belief")
        if frame.seq <= self._seq:
            raise ValueError("Replay or stale frame")
        self._known.update({tile.cell: tile.kind for tile in frame.visible})
        self._identity = identity
        self._seq = frame.seq
        self._player = frame.player

    @staticmethod
    def _neighbors(cell, width, height):
        for action, dx, dy in _ACTIONS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if 0 <= nxt[0] < width and 0 <= nxt[1] < height:
                yield action, nxt

    @staticmethod
    def _route(parent, end):
        path = []
        while end is not None:
            path.append(end)
            end = parent[end]
        return tuple(reversed(path))

    @staticmethod
    def _first_move(route, reason, exploratory, known):
        if len(route) < 2:
            return NavigationAdvice(None, route[0] if route else None, route,
                                    "already_at_destination", False, known)
        x0, y0 = route[0]
        x1, y1 = route[1]
        action = next(a for a, dx, dy in _ACTIONS if (dx, dy) == (x1 - x0, y1 - y0))
        # exploratory describes the FINAL unknown in the route, not an unsafe jump.
        return NavigationAdvice(action, route[1], route, reason, exploratory, known)

    def advise(self, *, mode: str = "play", sandbox_approved: bool = False) -> NavigationAdvice:
        if mode not in ("play", "practice") or type(sandbox_approved) is not bool:
            raise ValueError("Invalid navigation mode or sandbox approval")
        known = len(self._known)
        if self._identity is None or self._player is None:
            return NavigationAdvice(None, None, (), "awaiting_host_observation", False, known)
        _, _, width, height = self._identity
        player = self._player
        if self._known.get(player) == "goal":
            return NavigationAdvice(None, player, (player,), "goal_reached", False, known)
        parent = {player: None}
        distance = {player: 0}
        queue = deque([player])
        while queue:
            here = queue.popleft()
            for _, nxt in self._neighbors(here, width, height):
                if nxt not in parent and self._known.get(nxt) in _WALKABLE:
                    parent[nxt] = here
                    distance[nxt] = distance[here] + 1
                    queue.append(nxt)
        goals = [p for p in parent if self._known.get(p) == "goal"]
        if goals:
            goal = min(goals, key=lambda p: (distance[p], p[1], p[0]))
            return self._first_move(self._route(parent, goal), "verified_route", False, known)
        if mode != "practice" or sandbox_approved is not True:
            return NavigationAdvice(None, None, (), "no_verified_goal_route", False, known)
        # Score candidate frontiers without rebuilding a full path for every
        # visited square. Reconstruct ONLY the chosen route: O(grid cells).
        best: tuple[tuple[int, int, int, int, int], tuple[int, int], tuple[int, int]] | None = None
        for here in parent:
            for _, nxt in self._neighbors(here, width, height):
                if nxt not in self._known:
                    score = (distance[here] + 1, nxt[1], nxt[0], here[1], here[0])
                    if best is None or score < best[0]:
                        best = (score, here, nxt)
        if best is None:
            return NavigationAdvice(None, None, (), "no_safe_frontier", False, known)
        _, here, nxt = best
        path = self._route(parent, here) + (nxt,)
        return self._first_move(path, "sandbox_frontier_probe", True, known)
