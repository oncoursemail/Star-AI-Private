"""Deprecated / beta-only Roblox API gate (star/roblox_deprecated.py) and its check-fix ladder rung."""
import asyncio

import pytest

from star import roblox_deprecated as rd, verify_ladder as vl
from star.desktop_core import Settings

OLD = """local Players = game:GetService("Players")
local part = Instance.new("Part")
part.Velocity = Vector3.new(0, 10, 0)
local mover = Instance.new("BodyVelocity")
local hum = character:WaitForChild("Humanoid")
local track = hum:LoadAnimation(anim)
wait(1)
local player = Players:GetPlayerFromCharacter(character)
print(player.userId, workspace:FindPartOnRay(ray), Enum.KeyCode.A)
"""


def messages(code, prompt=""):
    return [(line, message.split(";")[0]) for line, message in rd.findings(code, prompt)]


def test_official_inventory_is_bundled_with_replacements():
    members, enums, globals_, _ = rd._data()
    assert len(members) + len(enums) + len(globals_) == 597
    assert members[("BasePart", "Velocity")] == "use AssemblyLinearVelocity"
    assert globals_[("Roblox globals", "wait")] == "use task.wait()"


def test_deprecated_members_classes_globals_are_found_with_known_receivers():
    found = messages(OLD)
    assert found == [(3, "Part.Velocity is deprecated"), (4, "the BodyVelocity class is deprecated"),
                     (6, "Humanoid.LoadAnimation is deprecated"), (7, "the global wait() is deprecated"),
                     (9, "Player.userId is deprecated"), (9, "Workspace.FindPartOnRay is deprecated")]
    assert "AssemblyLinearVelocity" in rd.findings(OLD)[0][1] and "Animator:LoadAnimation" in rd.findings(OLD)[2][1]


def test_user_tables_own_methods_and_modern_code_are_not_reported():
    code = """local entry = {userId = 1, velocity = 2}
print(entry.userId, entry.velocity, data.className)
local Inventory = {}
function Inventory:Remove(item) end
Inventory:Remove(1)
local function wait(seconds) return seconds end
wait(2)
local part = Instance.new("Part")
part.AssemblyLinearVelocity = Vector3.zero
part.Rotation = Vector3.zero
task.wait(1)
"""
    assert rd.findings(code) == []


def test_beta_only_api_is_reported_unless_the_request_names_it():
    code = 'local g = Instance.new("UIGradient")\ng.Type = Enum.GradientType.Radial\n'
    assert messages(code) == [(2, "Enum.GradientType.Radial is beta (Studio beta feature Upgraded UIGradients): "
                                  "it does not work in a published game")]
    assert rd.findings(code, "make a radial gradient") == []


def test_inventory_parser_and_refresh_refuse_a_changed_page(tmp_path):
    page = ("## Deprecated Methods (1)\n\n| Class/Type | Member | Replacement | Note |\n|---|---|---|---|\n"
            "| Workspace | `FindPartOnRay` | `WorldRoot:Raycast()` | Superseded. |\n")
    assert rd.parse_inventory(page) == [{"kind": "Method", "owner": "Workspace", "member": "FindPartOnRay",
                                         "replacement": "WorldRoot:Raycast()", "note": "Superseded."}]
    with pytest.raises(ValueError):
        rd.refresh(page, path=tmp_path / "deprecated.json")
    assert not (tmp_path / "deprecated.json").exists()


def test_ladder_rung_fails_before_run_and_the_fix_gets_the_replacement():
    async def fix(code, failure, members):
        assert failure.rung == "deprecated" and "task.wait()" in failure.detail
        return "```luau\ntask.wait(1)\nprint(1)\n```"

    answer, record = asyncio.run(vl.review("```luau\nwait(1)\nprint(1)\n```", vl.Tools(fix=fix, prompt="wait")))
    assert record["fixed"] and "task.wait(1)" in answer
    rungs = asyncio.run(vl.run_rungs("wait(1)\n", vl.Tools(deprecated=False), {}))
    assert [r.rung + ":" + r.status for r in rungs][:3] == ["compile:skip", "api:skip", "deprecated:skip"]


def test_setting_defaults_on_and_validates():
    assert Settings().verify_deprecated == "on"
    with pytest.raises(ValueError):
        Settings(verify_deprecated="maybe").validate()
