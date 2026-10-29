"""Offline checks for read-only, owner-curated Roblox navigation smoke tests.

These prove bounded code generation, NOT actual Roblox pathfinder behavior.
"""
from dataclasses import replace

import pytest

from star.studio_scene_integrity import (
    NavigableRoute, SceneCheck, StudioSceneTest, compile_scene_integrity,
)

START = ("Workspace", "Arena", "StartPad")
GOAL = ("Workspace", "Arena", "FinishPad")
MID = ("Workspace", "Arena", "MiddlePad")


def _suite(*routes):
    return StudioSceneTest(
        "arena_navigation",
        (SceneCheck(START, "SpawnLocation"),
         SceneCheck(GOAL, "Part"),
         SceneCheck(MID, "Part")),
        navigable_routes=tuple(routes),
    )


def test_route_is_optional_and_default_has_no_pathfinder_work():
    result = compile_scene_integrity(_suite())
    assert "PathfindingService" not in result.server_script
    assert result.verified_in_studio is False


def test_navigation_compiles_bound_read_only_paths_and_failure_signals():
    route = NavigableRoute(START, GOAL, agent_radius=3, agent_height=6,
                           allow_jump=False, allow_climb=True,
                           max_path_studs=420)
    result = compile_scene_integrity(_suite(route))
    server = result.server_script
    assert 'game:GetService("PathfindingService"):CreatePath({' in server
    assert "AgentRadius = 3" in server
    assert "AgentHeight = 6" in server
    assert "AgentCanJump = false" in server
    assert "AgentCanClimb = true" in server
    assert "path1:ComputeAsync(from1, to1)" in server
    assert "path1.Status ~= Enum.PathStatus.Success" in server
    assert "object1.CFrame.UpVector * (object1.Size.Y * 0.5 + 2)" in server
    assert "object2.CFrame.UpVector * (object2.Size.Y * 0.5 + 2)" in server
    assert "distance1 > 420.0" in server
    for reason in ("route_out_of_range_1", "route_parameters_1", "route_compute_1",
                   "route_blocked_1", "route_waypoints_1", "route_endpoint_1",
                   "route_detour_1", "time_budget"):
        assert reason in server
    assert "task.delay(45" in server
    assert "if ended then return end" in server
    assert "sts:EndTest('FAIL:time_budget')" in server
    assert "sts:EndTest('FAIL:verifier_error')" in server
    assert "PASS:arena_navigation:" in result.plugin_script
    assert not result.verified_in_studio
    for forbidden in ("HttpService", "loadstring(", "require(", "SetAsync(",
                      "Instance.new(", "SendKeyEvent", "TeleportAsync"):
        assert forbidden not in server


def test_two_routes_have_separate_objects_and_result_names():
    result = compile_scene_integrity(_suite(
        NavigableRoute(START, MID),
        NavigableRoute(MID, GOAL, agent_radius=1, allow_jump=False),
    ))
    server = result.server_script
    assert "path1:ComputeAsync(from1, to1)" in server
    assert "path2:ComputeAsync(from2, to2)" in server
    assert "object3.Position" in server
    assert "route_blocked_1" in server and "route_blocked_2" in server
    assert "AgentCanJump = false" in server


@pytest.mark.parametrize("updates", [
    {"start_path": GOAL}, {"goal_path": START},
    {"start_path": ("ServerStorage", "Part")},
    {"goal_path": ("Workspace", "Bad\nname")},
    {"start_path": ["Workspace", "StartPad"]},
    {"goal_path": ("Workspace",)},
    {"agent_radius": True}, {"agent_radius": 0}, {"agent_radius": 9},
    {"agent_radius": 1.5}, {"agent_height": True}, {"agent_height": 2},
    {"agent_height": 17}, {"allow_jump": 0}, {"allow_climb": "yes"},
    {"max_path_studs": float("nan")}, {"max_path_studs": float("inf")},
    {"max_path_studs": -5}, {"max_path_studs": 1001},
    {"max_path_studs": True}, {"max_path_studs": "400"},
    {"max_path_studs": 10 ** 10000},
])
def test_rejects_invalid_navigation_routes(updates):
    with pytest.raises(ValueError):
        replace(NavigableRoute(START, GOAL), **updates)


def test_rejects_missing_or_unsafe_endpoints_and_duplicate_routes():
    route = NavigableRoute(START, GOAL)
    bad = NavigableRoute(START, ("Workspace", "Missing"))
    for routes in ((bad,), (route, route), tuple([route] * 9), [route]):
        with pytest.raises(ValueError):
            _suite(*routes) if type(routes) is tuple else StudioSceneTest(
                "bad", (SceneCheck(START, "Part"), SceneCheck(GOAL, "Part")),
                navigable_routes=routes,
            )
    with pytest.raises(ValueError):
        StudioSceneTest("model_is_not_navpoint", (
            SceneCheck(START, "Model"), SceneCheck(GOAL, "Part"),
        ), navigable_routes=(route,))


def test_changes_to_routing_invalidate_signed_suite_marker():
    base = compile_scene_integrity(_suite(NavigableRoute(START, GOAL)))
    for route in (
        NavigableRoute(START, GOAL, max_path_studs=200),
        NavigableRoute(START, GOAL, allow_jump=False),
        NavigableRoute(START, GOAL, agent_radius=4),
        NavigableRoute(START, MID),
    ):
        candidate = compile_scene_integrity(_suite(route))
        assert candidate.spec_sha256 != base.spec_sha256
        assert candidate.plugin_script != base.plugin_script


def test_navigation_is_not_misreported_as_tested_in_studio():
    result = compile_scene_integrity(_suite(NavigableRoute(START, GOAL)))
    assert result.verified_in_studio is False
    assert "PRIVATE test place" in result.server_script
    assert "trusted Studio plugin" in result.plugin_script
