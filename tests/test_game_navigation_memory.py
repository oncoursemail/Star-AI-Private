"""Offline-only tests: memory safety, safe frontiers and a hidden maze."""
from __future__ import annotations

from dataclasses import replace

import pytest

from star.game_navigation_memory import (
    GridPosition, GroundedNavigationMemory, NavigationObservation,
    ObservedTile,
)


def pos(x: int, y: int) -> GridPosition:
    return GridPosition(x, y)


def tile(x: int, y: int, walkable: bool = True, risk: int = 0) -> ObservedTile:
    return ObservedTile(pos(x, y), walkable, risk)


def observation(
    *, seq: int = 1, player: GridPosition = pos(0, 0),
    goal: GridPosition | None = pos(2, 0),
    tiles: tuple[ObservedTile, ...] | None = None,
    captured_ms: float | None = None, game_id: str = "maze",
    episode_id: str = "round1",
) -> NavigationObservation:
    return NavigationObservation(
        game_id=game_id, game_version="v1", episode_id=episode_id,
        sequence=seq, captured_ms=1000 + seq * 10 if captured_ms is None
        else captured_ms, player=player,
        tiles=tiles if tiles is not None else (tile(player.x, player.y),),
        goal=goal,
    )


def enabled() -> GroundedNavigationMemory:
    navigator = GroundedNavigationMemory()
    navigator.start(game_id="maze", game_version="v1",
                    episode_id="round1", owner_approved=True)
    return navigator


def test_requires_owner_approval_and_strict_identifiers() -> None:
    navigator = GroundedNavigationMemory()
    with pytest.raises(PermissionError):
        navigator.start(game_id="maze", game_version="v1", episode_id="one")
    with pytest.raises(ValueError):
        navigator.start(game_id="maze", game_version="../v1",
                        episode_id="one", owner_approved=True)
    with pytest.raises(ValueError):
        GridPosition(True, 0)
    with pytest.raises(ValueError):
        ObservedTile(pos(0, 0), True, 10001)
    with pytest.raises(ValueError):
        observation(tiles=(tile(0, 0), tile(0, 0)))
    with pytest.raises(ValueError):
        observation(tiles=(tile(1, 0),))
    with pytest.raises(ValueError):
        observation(tiles=(tile(0, 0, False),))


def test_verified_host_only_and_replay_fences() -> None:
    nav = enabled()
    first = observation()
    assert not nav.ingest(first, now_ms=1010)
    assert nav.metrics()["observed_cells"] == 0
    assert nav.ingest(first, now_ms=1010, host_verified=True)
    assert not nav.ingest(first, now_ms=1015, host_verified=True)
    assert not nav.ingest(observation(seq=2, game_id="other"),
                          now_ms=1020, host_verified=True)
    assert not nav.ingest(observation(seq=2, episode_id="other"),
                          now_ms=1020, host_verified=True)
    assert not nav.ingest(observation(seq=2),
                          now_ms=1009, host_verified=True)
    assert not nav.ingest(observation(seq=2, captured_ms=999),
                          now_ms=1020, host_verified=True)
    assert not nav.ingest(observation(seq=2, captured_ms=1030),
                          now_ms=1020, host_verified=True)
    assert nav.metrics()["accepted"] == 1
    assert nav.ingest(observation(seq=2), now_ms=1020, host_verified=True)
    assert nav.advise(now_ms=1021).status == "observe"


def test_cannot_walk_unknown_blocked_or_high_risk() -> None:
    nav = enabled()
    goal = pos(2, 0)
    frame = observation(
        tiles=(tile(0, 0), tile(1, 0, False), tile(0, 1),
               tile(1, 1), tile(2, 1), tile(2, 0)),
        goal=goal,
    )
    assert nav.ingest(frame, now_ms=1010, host_verified=True)
    advice = nav.advise(now_ms=1011)
    assert advice.status == "move"
    assert advice.action_id == "down"
    assert not advice.authorizes_input
    assert not advice.authorizes_broadcast
    nav2 = enabled()
    frame2 = replace(frame, tiles=(tile(0, 0), tile(1, 0, True, 9000),
                                   tile(0, 1), tile(1, 1), tile(2, 1),
                                   tile(2, 0)))
    assert nav2.ingest(frame2, now_ms=1010, host_verified=True)
    assert nav2.advise(now_ms=1011).action_id == "down"


def test_stale_host_clock_fails_closed_and_episode_reset() -> None:
    nav = enabled()
    assert nav.ingest(observation(), now_ms=1010, host_verified=True)
    assert nav.advise(now_ms=1011).status == "observe"
    assert nav.advise(now_ms=1011).status == "await_observation"
    assert nav.advise(now_ms=1000).reason == "host_clock_reversed"
    assert nav.advise(now_ms=2000).reason == "observation_expired"
    with pytest.raises(RuntimeError):
        nav.start(game_id="maze", game_version="v1", episode_id="round2",
                  owner_approved=True)
    nav.stop()
    assert nav.metrics()["observed_cells"] == 0
    assert nav.advise(now_ms=2000).status == "abstain"
    nav.start(game_id="maze", game_version="v1", episode_id="round2",
              owner_approved=True)
    assert nav.metrics()["observed_cells"] == 0
    assert not nav.ingest(observation(), now_ms=1010, host_verified=True)


def test_frontier_avoids_hallucinating_route_through_unknown() -> None:
    nav = enabled()
    assert nav.ingest(
        observation(tiles=(tile(0, 0), tile(0, 1), tile(1, 0, False))),
        now_ms=1010, host_verified=True)
    first = nav.advise(now_ms=1011)
    assert first.status == "move" and first.action_id == "down"
    assert first.target == pos(0, 1)
    assert first.observed_cells == 3


def test_known_goal_and_no_safe_frontier() -> None:
    nav = enabled()
    cells = (tile(0, 0), tile(1, 0), tile(0, 1, False),
             tile(0, -1, False), tile(-1, 0, False),
             tile(1, -1, False), tile(1, 1, False),
             tile(2, 0, False))
    assert nav.ingest(observation(goal=pos(2, 0), tiles=cells),
                      now_ms=1010, host_verified=True)
    assert nav.advise(now_ms=1011).reason == "no_safe_observed_frontier"
    assert nav.ingest(observation(seq=2, player=pos(1, 0), goal=pos(1, 0),
                                  tiles=(tile(1, 0),)),
                      now_ms=1020, host_verified=True)
    assert nav.advise(now_ms=1021).status == "arrived"


def test_adapts_route_when_newly_observed_tile_becomes_blocked() -> None:
    nav = enabled()
    visible = (tile(0, 0), tile(1, 0), tile(2, 0),
               tile(0, 1), tile(1, 1), tile(2, 1))
    assert nav.ingest(observation(tiles=visible), now_ms=1010,
                      host_verified=True)
    assert nav.advise(now_ms=1010).action_id == "right"
    changed = tuple(tile(1, 0, False) if t.position == pos(1, 0)
                    else t for t in visible)
    assert nav.ingest(observation(seq=2, tiles=changed), now_ms=1020,
                      host_verified=True)
    assert nav.advise(now_ms=1021).action_id == "down"


def test_hidden_maze_improves_on_blind_greedy_and_never_crosses_wall() -> None:
    # Private synthetic environment. Ground truth stays outside the advisor.
    walls = {pos(2, y) for y in (1, 2, 3)}
    start, goal = pos(0, 2), pos(5, 2)
    player = start
    nav = enabled()
    history: list[GridPosition] = [start]
    for seq in range(1, 130):
        tiles = tuple(
            tile(x, y, 0 <= x <= 5 and 0 <= y <= 4
                 and pos(x, y) not in walls)
            for x in range(player.x - 1, player.x + 2)
            for y in range(player.y - 1, player.y + 2)
            if abs(x - player.x) + abs(y - player.y) <= 1
        )
        at = seq * 10 + 1000
        frame = observation(seq=seq, player=player, goal=goal,
                            tiles=tiles)
        assert nav.ingest(frame, now_ms=at, host_verified=True)
        hint = nav.advise(now_ms=at + 1)
        if hint.status == "arrived":
            break
        if hint.status == "move":
            delta = {"up": (0, -1), "down": (0, 1),
                     "left": (-1, 0), "right": (1, 0)}[hint.action_id]
            next_pos = pos(player.x + delta[0], player.y + delta[1])
            assert next_pos not in walls
            assert 0 <= next_pos.x <= 5 and 0 <= next_pos.y <= 4
            player = next_pos
            history.append(player)
        else:
            assert hint.status in {"observe", "await_observation"}
    assert player == goal, f"failed to solve synthetic maze: {history}"
    assert len(history) <= 80
    # Blind rightward policy hits x=2,y=2 and cannot finish.
    blind = start
    for _ in range(130):
        attempt = pos(blind.x + 1, blind.y)
        if attempt not in walls and attempt.x <= 5:
            blind = attempt
    assert blind != goal


@pytest.mark.parametrize("gap_left,gap_right", [
    (0, 0), (0, 4), (4, 0), (4, 4),
])
def test_hidden_zigzag_unseen_layouts(
    gap_left: int, gap_right: int,
) -> None:
    """All layouts stay hidden from the planner until locally observed."""
    walls = {
        pos(wall_x, y)
        for wall_x, gap in ((2, gap_left), (4, gap_right))
        for y in range(5) if y != gap
    }
    player, goal = pos(0, 2), pos(6, 2)
    navigator = enabled()
    for seq in range(1, 200):
        visible = tuple(
            tile(x, y, 0 <= x <= 6 and 0 <= y <= 4
                 and pos(x, y) not in walls)
            for x in range(player.x - 1, player.x + 2)
            for y in range(player.y - 1, player.y + 2)
            if abs(x - player.x) + abs(y - player.y) <= 1
        )
        frame = observation(seq=seq, player=player, goal=goal, tiles=visible)
        assert navigator.ingest(frame, now_ms=frame.captured_ms,
                                host_verified=True)
        answer = navigator.advise(now_ms=frame.captured_ms + 1)
        if answer.status == "arrived":
            break
        if answer.status != "move":
            assert answer.status in {"observe", "await_observation"}
            continue
        dx, dy = {"up": (0, -1), "down": (0, 1),
                  "left": (-1, 0), "right": (1, 0)}[answer.action_id]
        next_pos = pos(player.x + dx, player.y + dy)
        assert next_pos not in walls and 0 <= next_pos.x <= 6
        assert 0 <= next_pos.y <= 4
        player = next_pos
    assert player == goal, (gap_left, gap_right, navigator.metrics())


def test_untrusted_map_change_never_overwrites_verified_memory() -> None:
    nav = enabled()
    good = observation(tiles=(tile(0, 0), tile(1, 0), tile(2, 0)))
    assert nav.ingest(good, now_ms=1010, host_verified=True)
    assert nav.advise(now_ms=1011).action_id == "right"
    fake = observation(seq=2, tiles=(tile(0, 0), tile(1, 0, False),
                                     tile(2, 0, False)))
    assert not nav.ingest(fake, now_ms=1020, host_verified=False)
    assert nav.advise(now_ms=1021).action_id == "right"
