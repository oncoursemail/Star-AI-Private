"""Deterministic PRIVATE maze rehearsal with authenticated navigation frames.

An intentionally small, offline reference environment that owns the full map
and checks outcomes independently of the advisor. No game, Windows input,
network traffic, OBS, AI inference, or skill promotion is connected. Test
fixtures use a fresh ephemeral signing key per trial. Signed frames alone
are not proof that a production game reader is trustworthy.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
import secrets

from .game_navigation_memory import (
    GridPosition, GroundedNavigationMemory, NavigationObservation, ObservedTile,
)
from .game_navigation_source_bridge import (
    AuthenticatedNavigationBridge, sign_navigation_packet,
)

_SCENARIO_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_DELTAS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


@dataclass(frozen=True)
class MazeScenario:
    """Private map truth; ! is lethal and ~ has synthetic exposure risk."""
    scenario_id: str
    rows: tuple[str, ...]
    patrol: tuple[GridPosition, ...] = ()  # engine-owned, hidden moving hazard path

    def __post_init__(self) -> None:
        if type(self.scenario_id) is not str or _SCENARIO_ID.fullmatch(
            self.scenario_id
        ) is None:
            raise ValueError("scenario_id must be a bounded opaque identifier")
        if (type(self.rows) is not tuple or not 2 <= len(self.rows) <= 12
                or any(type(row) is not str for row in self.rows)):
            raise ValueError("maze requires 2..12 string rows")
        width = len(self.rows[0])
        if not 2 <= width <= 12 or any(
            len(row) != width or any(ch not in ".#SG!~" for ch in row)
            for row in self.rows
        ):
            raise ValueError("maze must be rectangular with # . S G ! ~ only")
        if "".join(self.rows).count("S") != 1 or "".join(self.rows).count("G") != 1:
            raise ValueError("maze requires exactly one start and one goal")
        if self.shortest_path_length() is None:
            raise ValueError("private evaluation maze must have a reachable goal")
        if type(self.patrol) is not tuple or (
            self.patrol and not 2 <= len(self.patrol) <= 32
        ):
            raise ValueError("patrol requires 2..32 positions or empty tuple")
        if any(
            type(position) is not GridPosition
            or not self.safe_for_engine(position)
            or position in (self.start, self.goal)
            for position in self.patrol
        ):
            raise ValueError("patrol must stay on nonterminal safe terrain")
        if self.patrol and (
            len(set(self.patrol)) < 2
            or any(
                abs(a.x - b.x) + abs(a.y - b.y) > 1
                for a, b in zip(self.patrol, self.patrol[1:] + self.patrol[:1])
            )
        ):
            raise ValueError("patrol must contain adjacent, cyclic movement")

    def _locate(self, marker: str) -> GridPosition:
        for y, row in enumerate(self.rows):
            x = row.find(marker)
            if x >= 0:
                return GridPosition(x, y)
        raise ValueError("missing maze marker")

    @property
    def start(self) -> GridPosition:
        return self._locate("S")

    @property
    def goal(self) -> GridPosition:
        return self._locate("G")

    def walkable(self, pos: GridPosition) -> bool:
        return (0 <= pos.y < len(self.rows)
                and 0 <= pos.x < len(self.rows[0])
                and self.rows[pos.y][pos.x] != "#")

    def safe_for_engine(self, pos: GridPosition) -> bool:
        """Lethal tiles are physically traversable, but disallowed to the engine."""
        return self.walkable(pos) and self.rows[pos.y][pos.x] != "!"

    def shortest_path_length(self) -> int | None:
        """Independent BFS over engine-safe terrain; kept hidden from advisor."""
        start, goal = self.start, self.goal
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            pos, distance = queue.popleft()
            if pos == goal:
                return distance
            for dx, dy in _DELTAS.values():
                nxt = GridPosition(pos.x + dx, pos.y + dy)
                if nxt not in seen and self.safe_for_engine(nxt):
                    seen.add(nxt)
                    queue.append((nxt, distance + 1))
        return None

    def hazard_at_frame(self, frame: int) -> GridPosition | None:
        """Engine truth remains independent of the advisor's observed map."""
        if type(frame) is not int or frame < 1:
            raise ValueError("frame must be a positive integer")
        return self.patrol[(frame - 1) % len(self.patrol)] if self.patrol else None

    def local_capture(
        self, player: GridPosition, *, moving_hazard: GridPosition | None = None,
        sensor_radius: int = 1,
    ) -> tuple[ObservedTile, ...]:
        """Bounded sensor; wall truth stays in this engine-side fixture."""
        if type(sensor_radius) is not int or sensor_radius not in (1, 2):
            raise ValueError("private sensor radius must be 1 or 2")
        captured: list[ObservedTile] = []
        offsets = [(0, 0), (0, -1), (-1, 0), (1, 0), (0, 1)]
        if sensor_radius == 2:
            offsets.extend((dx, dy) for dy in range(-2, 3)
                           for dx in range(-2, 3)
                           if abs(dx) + abs(dy) == 2)
        for dx, dy in offsets:
            at = GridPosition(player.x + dx, player.y + dy)
            terrain = self.rows[at.y][at.x] if self.walkable(at) else "#"
            risk = (
                10000 if at == moving_hazard or terrain == "!"
                else 6000 if terrain == "~" else 0
            )
            captured.append(ObservedTile(at, terrain != "#", risk_bps=risk))
        return tuple(captured)


@dataclass(frozen=True)
class MazeTrialScore:
    scenario_id: str
    success: bool
    reason: str
    frames: int
    moves: int
    nonmove_hints: int
    invalid_move_attempts: int
    optimal_moves: int
    efficiency_bps: int
    source_revoked: bool
    risk_exposure_bps: int = 0  # Synthetic hazard exposure, NOT actual game health.
    hazard_tile_entries: int = 0
    moving_hazard_hits: int = 0
    moving_hazard_waits: int = 0
    world_ticks: int = 0           # Engine-clock ticks, NOT model throughput.
    decision_delay_ticks: int = 0  # Synthetic inference delay per observation.
    late_actions_suppressed: int = 0
    moving_hazard_delay_hits: int = 0
    # Nearest-rank p95/max/total of per-capture synthetic delay samples.
    # These are NOT inference timings captured from a real model.
    decision_delay_p95_ticks: int = 0
    decision_delay_max_ticks: int = 0
    decision_delay_total_ticks: int = 0
    decision_delay_samples: int = 0  # Captures actually signed, not collided-at-start frames.
    decision_delay_schedule_used: bool = False

    def __post_init__(self) -> None:
        if self.success and (self.reason != "goal_witnessed"
                             or self.invalid_move_attempts):
            raise ValueError("success requires independently witnessed goal")
        if (
            type(self.moving_hazard_hits) is not int
            or not 0 <= self.moving_hazard_hits <= 1
            or type(self.moving_hazard_waits) is not int
            or self.moving_hazard_waits < 0
            or (self.success and self.moving_hazard_hits)
        ):
            raise ValueError("moving-hazard outcome must be independently witnessed")
        if (type(self.hazard_tile_entries) is not int or self.hazard_tile_entries < 0
                or type(self.risk_exposure_bps) is not int
                or self.risk_exposure_bps != self.hazard_tile_entries * 6000):
            raise ValueError("synthetic hazard exposure must match engine events")
        if (type(self.world_ticks) is not int
                or not 0 <= self.world_ticks <= 512
                or self.world_ticks < self.frames
                or type(self.decision_delay_ticks) is not int
                or not 0 <= self.decision_delay_ticks <= 24
                or type(self.late_actions_suppressed) is not int
                or not 0 <= self.late_actions_suppressed <= self.frames
                or type(self.moving_hazard_delay_hits) is not int
                or not 0 <= self.moving_hazard_delay_hits <= self.moving_hazard_hits
                or type(self.decision_delay_p95_ticks) is not int
                or type(self.decision_delay_max_ticks) is not int
                or type(self.decision_delay_total_ticks) is not int
                or type(self.decision_delay_samples) is not int
                or not 0 <= self.decision_delay_samples <= self.frames
                or type(self.decision_delay_schedule_used) is not bool
                or not 0 <= self.decision_delay_p95_ticks <= self.decision_delay_max_ticks <= 24
                or not self.decision_delay_max_ticks <= self.decision_delay_total_ticks
                or self.decision_delay_total_ticks > self.decision_delay_samples * self.decision_delay_max_ticks
                or (not self.decision_delay_schedule_used
                    and (self.decision_delay_max_ticks != self.decision_delay_ticks
                         or self.decision_delay_p95_ticks != self.decision_delay_ticks
                         or self.decision_delay_total_ticks != self.decision_delay_samples * self.decision_delay_ticks))):
            raise ValueError("synthetic real-time telemetry is inconsistent")


def run_signed_maze_trial(
    scenario: MazeScenario, *, owner_approved: bool = False,
    max_frames: int = 256, sensor_radius: int = 1,
    predictive_risk_guard: bool = False,
    decision_delay_ticks: int = 0, action_deadline_ticks: int | None = None,
    decision_delay_schedule: tuple[int, ...] | None = None,
) -> MazeTrialScore:
    """Offline engine->signed packet->bridge->advisor->engine->score loop.

    This IS a real closed loop only for the in-process synthetic maze. The
    advisor cannot view the hidden full map, score itself, press a key, or
    report a win; the test engine alone changes position and checks the goal.
    """
    if owner_approved is not True:
        raise PermissionError("private maze rehearsal requires owner approval")
    if type(scenario) is not MazeScenario:
        raise TypeError("scenario must be a validated MazeScenario")
    if type(max_frames) is not int or not 1 <= max_frames <= 512:
        raise ValueError("max_frames must be 1..512")
    if type(sensor_radius) is not int or sensor_radius not in (1, 2):
        raise ValueError("sensor_radius must be 1 or 2")
    if type(predictive_risk_guard) is not bool:
        raise ValueError("predictive_risk_guard must be boolean")
    if type(decision_delay_ticks) is not int or not 0 <= decision_delay_ticks <= 24:
        raise ValueError("synthetic decision delay must be 0..24 ticks")
    if decision_delay_schedule is not None:
        if (type(decision_delay_schedule) is not tuple
                or not 1 <= len(decision_delay_schedule) <= 256
                or any(type(n) is not int or not 0 <= n <= 24
                       for n in decision_delay_schedule)):
            raise ValueError("decision delay schedule requires 1..256 integers in 0..24")
        if decision_delay_ticks != 0:
            raise ValueError("decision delay schedule cannot mix with fixed delay")
    if action_deadline_ticks is not None and (
        type(action_deadline_ticks) is not int
        or not 0 <= action_deadline_ticks <= 24
    ):
        raise ValueError("action deadline must be 0..24 ticks or None")
    player = scenario.start
    moves = 0
    nonmove = 0
    invalid = 0
    exposure = 0
    hazard_entries = 0
    moving_hits = 0
    hazard_waits = 0
    late_actions = 0
    delay_hits = 0
    applied_delays: list[int] = []
    reason = "frame_budget_exhausted"
    frames = 0
    world_tick = 1
    last_world_tick = 0
    clock = [1010.0]
    nav = GroundedNavigationMemory(
        max_observation_age_ms=250, max_tile_age_ms=250,
        single_move_per_capture=True, max_stalled_captures=3,
        predictive_risk_guard=predictive_risk_guard,
    )
    source_key = secrets.token_bytes(32)
    bridge_session = secrets.token_hex(16)
    bridge = AuthenticatedNavigationBridge(
        navigator=nav, source_id="private_maze_lab",
        session_id=bridge_session, source_key=source_key,
        game_id="synthetic_maze", game_version="v1",
        episode_id=scenario.scenario_id, clock_ms=lambda: clock[0],
    )
    bridge.enable(owner_approved=True)
    try:
        for seq in range(1, max_frames + 1):
            # max_frames is a WORLD-TICK budget, not a free number of model
            # calls: slow reasoning consumes real game time between captures.
            if world_tick > max_frames:
                break
            frames = seq
            last_world_tick = world_tick
            # The timing trace is deterministic and selected by the host,
            # never based on private future hazard positions or advisor output.
            active_delay = (decision_delay_schedule[(seq - 1) % len(decision_delay_schedule)]
                            if decision_delay_schedule is not None
                            else decision_delay_ticks)
            clock[0] = float(1000 + 10 * world_tick)
            # The independent engine advances the hazard even when the model
            # is idle. Collision at tick-start is scored before a new capture.
            moving_hazard = scenario.hazard_at_frame(world_tick)
            if moving_hazard == player:
                moving_hits += 1
                reason = "moving_hazard_hit_player"
                break
            # Only signed/ingested captures incur a modeled reasoning delay.
            # A collision detected before capture cannot add imaginary p95.
            applied_delays.append(active_delay)
            observation = NavigationObservation(
                game_id="synthetic_maze", game_version="v1",
                episode_id=scenario.scenario_id, sequence=seq,
                captured_ms=clock[0], player=player,
                goal=scenario.goal, tiles=scenario.local_capture(
                    player, moving_hazard=moving_hazard,
                    sensor_radius=sensor_radius,
                ),
            )
            packet = sign_navigation_packet(
                observation, source_id="private_maze_lab",
                session_id=bridge_session, source_key=source_key,
            )
            bridge.accept(packet)
            # Simulate model/tool delay WITHOUT revealing the future patrol to
            # the advisor. The independent engine advances while the character
            # remains at its previous location. It can hit the character
            # before delayed advice becomes available.
            action_tick = world_tick + active_delay
            for pending_tick in range(world_tick + 1,
                                      min(action_tick, max_frames) + 1):
                last_world_tick = pending_tick
                if scenario.hazard_at_frame(pending_tick) == player:
                    moving_hits += 1
                    delay_hits += 1
                    reason = "moving_hazard_hit_during_decision"
                    break
            if delay_hits:
                break
            if action_tick > max_frames:
                last_world_tick = max_frames
                break
            last_world_tick = action_tick
            current_hazard = scenario.hazard_at_frame(action_tick)
            clock[0] = float(1000 + 10 * action_tick + 1)
            hint = bridge.advise()
            if hint.authorizes_input or hint.authorizes_broadcast:
                reason = "unexpected_authority"
                break
            if hint.status == "arrived":
                if player == scenario.goal:
                    reason = "goal_witnessed"
                else:
                    reason = "unwitnessed_arrival"
                break
            if hint.status == "move":
                if (action_deadline_ticks is not None
                        and active_delay > action_deadline_ticks):
                    # Discard late *symbolic* advice. The test engine never
                    # executes it, and never credits it as a movement.
                    late_actions += 1
                    nonmove += 1
                    world_tick = action_tick + 1
                    continue
                if hint.action_id not in _DELTAS:
                    invalid += 1
                    reason = "unknown_symbolic_action"
                    break
                dx, dy = _DELTAS[hint.action_id]
                nxt = GridPosition(player.x + dx, player.y + dy)
                if nxt == current_hazard:
                    invalid += 1
                    reason = "engine_rejected_moving_hazard"
                    break
                if not scenario.safe_for_engine(nxt):
                    invalid += 1
                    reason = ("engine_rejected_lethal_tile"
                              if scenario.walkable(nxt)
                              else "engine_rejected_illegal_move")
                    break
                player = nxt  # ONLY the synthetic test engine changes state.
                moves += 1
                if scenario.rows[player.y][player.x] == "~":
                    hazard_entries += 1
                    exposure += 6000
            elif hint.status in {"observe", "await_observation"}:
                nonmove += 1
            elif (scenario.patrol and hint.status == "abstain"
                  and hint.reason == "no_safe_observed_frontier"):
                # Waiting is permitted only in a moving-hazard rehearsal.
                # A new independently signed capture is mandatory next tick.
                nonmove += 1
                hazard_waits += 1
            else:
                reason = "advisor_abstained"
                break
            world_tick = action_tick + 1
        optimal = scenario.shortest_path_length()
        assert optimal is not None
        success = reason == "goal_witnessed" and player == scenario.goal
        # Nearest-rank p95, not interpolated; a single slow capture is
        # visible in max/total even when p95 is unchanged.
        ordered_delays = sorted(applied_delays)
        delay_p95 = ordered_delays[(95 * len(ordered_delays) + 99) // 100 - 1]
        efficiency = (min(10000, 10000 * optimal // moves)
                      if success and moves else 0)
        return MazeTrialScore(
            scenario_id=scenario.scenario_id, success=success,
            reason=reason, frames=frames, moves=moves,
            nonmove_hints=nonmove, invalid_move_attempts=invalid,
            optimal_moves=optimal, efficiency_bps=efficiency,
            source_revoked=bool(bridge.metrics()["revoked"]),
            risk_exposure_bps=exposure, hazard_tile_entries=hazard_entries,
            moving_hazard_hits=moving_hits, moving_hazard_waits=hazard_waits,
            world_ticks=last_world_tick, decision_delay_ticks=decision_delay_ticks,
            late_actions_suppressed=late_actions,
            moving_hazard_delay_hits=delay_hits,
            decision_delay_p95_ticks=delay_p95,
            decision_delay_max_ticks=max(applied_delays),
            decision_delay_total_ticks=sum(applied_delays),
            decision_delay_samples=len(applied_delays),
            decision_delay_schedule_used=decision_delay_schedule is not None,
        )
    finally:
        bridge.disable()


def run_maze_benchmark(
    scenarios: tuple[MazeScenario, ...], *, owner_approved: bool = False,
    max_frames: int = 256, sensor_radius: int = 1,
    predictive_risk_guard: bool = False,
    decision_delay_ticks: int = 0, action_deadline_ticks: int | None = None,
    decision_delay_schedule: tuple[int, ...] | None = None,
) -> tuple[MazeTrialScore, ...]:
    """Independent per-map results; no averages that hide failed trials."""
    if owner_approved is not True:
        raise PermissionError("owner approval required for private benchmark")
    if type(scenarios) is not tuple or not 1 <= len(scenarios) <= 32:
        raise ValueError("benchmark requires 1..32 scenarios")
    if any(type(case) is not MazeScenario for case in scenarios):
        raise TypeError("all cases must be validated MazeScenario objects")
    if len({case.scenario_id for case in scenarios}) != len(scenarios):
        raise ValueError("scenario ids must be unique")
    return tuple(run_signed_maze_trial(
        case, owner_approved=True, max_frames=max_frames,
        sensor_radius=sensor_radius, predictive_risk_guard=predictive_risk_guard,
        decision_delay_ticks=decision_delay_ticks,
        action_deadline_ticks=action_deadline_ticks,
        decision_delay_schedule=decision_delay_schedule,
    ) for case in scenarios)


__all__ = [
    "MazeScenario", "MazeTrialScore", "run_signed_maze_trial", "run_maze_benchmark",
]
