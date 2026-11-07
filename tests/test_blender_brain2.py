"""Real MCP-memory dispatch with a fake offline Blender process; no GPU/network needed."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from star.blender_bridge import BlenderController, discover_blender, status, validate_scene
from star.blender_mcp import (ANIMATION_EXPORT, BUILD, INSPECT, MOTION_QA, NAMES, PROBE, STATUS,
                              connect_blender, make_server, wants_blender)
from star.desktop_core import Settings
from star.react_shell import ALLOWED_ACTIONS, PERMITTED_SETTINGS

SCENE = {
    "name": "SmallVillage",
    "objects": [
        {"name": "Roof", "kind": "roof", "location": [0, 0, 4],
         "scale": [4, 3, 2], "color": "#AF5033"},
        {"name": "Trunk", "kind": "tree", "location": [8, 4, 0],
         "scale": [2, 2, 3], "color": "#416E52"},
        {"name": "Arch", "kind": "arch", "location": [-6, 0, 0],
         "scale": [2, 1, 3]},
    ],
    "camera": {"location": [12, -18, 8], "target": [0, 0, 1]},
    "render_preview": False,
}


class FakeBlenderProcess:
    """Simulates only STAR's worker outputs. Does not execute user Python."""

    def __init__(self, args):
        self.args = args
        self.returncode = 0

    async def communicate(self):
        if "--python-expr" in self.args:
            return b"Blender 4.5\nSTAR_BLENDER_VERSION=4.5.1 LTS\n", b""
        assert "--python" in self.args and self.args[-2] == "--"
        script = Path(self.args[self.args.index("--python") + 1])
        assert script.name == "blender_worker.py"
        input_file = Path(self.args[-1])
        assert input_file.name == "scene.json"
        spec = json.loads(input_file.read_text())
        folder = input_file.parent
        (folder / "scene.blend").write_bytes(b"BLENDER-MOCK")
        (folder / "scene.glb").write_bytes(b"glTF-MOCK")
        (folder / "result.json").write_text(json.dumps({
            "job_id": folder.name, "status": "completed", "scene": spec["name"],
            "objects": len(spec["objects"]), "mesh_count": 9, "triangle_count": 1234,
        }), encoding="utf-8")
        return b"Star fake success", b""


def fake_spawn(calls):
    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeBlenderProcess(args)
    return spawn


def test_validation_guards_geometry_and_scripts():
    result = validate_scene(SCENE)
    result["objects"][0]["name"] = "changed"
    assert SCENE["objects"][0]["name"] == "Roof"
    for invalid in (
        {**SCENE, "script": "import os; os.system('x')"},
        {**SCENE, "objects": []},
        {**SCENE, "objects": [{**SCENE["objects"][0], "location": [float("nan"), 0, 0]}]},
        {**SCENE, "objects": [SCENE["objects"][0], dict(SCENE["objects"][0], name="roof")]},
        {**SCENE, "objects": [dict(SCENE["objects"][0], scale=[-1, 2, 3])]},
        {**SCENE, "camera": {"location": [0, 0, 0], "target": [0, 0, 0]}},
        {**SCENE, "objects": [dict(SCENE["objects"][0], color="javascript:alert(1)")]},
    ):
        with pytest.raises(ValueError):
            validate_scene(invalid)


def test_path_discovery_is_local_only(tmp_path, monkeypatch):
    blender = tmp_path / ("blender.exe" if __import__("os").name == "nt" else "blender")
    blender.write_text("fake trusted binary")
    blender.chmod(0o755)
    assert discover_blender(str(blender)) == blender.resolve()
    assert discover_blender("https://evil.test/blender") is None
    assert discover_blender("//server/blender") is None
    link = tmp_path / "linked"
    try:
        link.symlink_to(blender)
    except (OSError, NotImplementedError):
        pass  # Windows runners may disallow symlinks without elevated privileges.
    else:
        assert discover_blender(str(link)) is None
    assert status(Settings(blender_enabled=False, blender_executable=str(blender)))["enabled"] is False


def test_settings_reject_malformed_permission_and_remote_binary():
    for value in (True, 1, "yes"):
        with pytest.raises(ValueError):
            Settings(blender_enabled=False, blender_edit=value).validate()
    with pytest.raises(ValueError):
        Settings(blender_enabled=True, blender_executable="https://download.test/blender").validate()
    with pytest.raises(ValueError):
        Settings(blender_enabled=True, blender_executable="\\\\server\\blender.exe").validate()
    assert {"blender_enabled", "blender_edit", "blender_executable"} <= PERMITTED_SETTINGS
    assert "testBlender" in ALLOWED_ACTIONS


def test_disabled_tools_cannot_mutate_and_catalog_is_bounded(tmp_path):
    controller = BlenderController(settings=Settings(), home=tmp_path)
    server, catalog = make_server(controller)
    assert BUILD not in {t["name"] for t in catalog}
    with pytest.raises(PermissionError):
        asyncio.run(controller.build(SCENE))
    with pytest.raises(PermissionError):
        controller.inspect("0" * 24)
    assert not list(tmp_path.iterdir())


def test_probe_and_actual_new_job_does_not_touch_existing_files(tmp_path, monkeypatch):
    import star.blender_bridge as bridge
    executable = tmp_path / "fake-bin" / ("blender.exe" if __import__("os").name == "nt" else "blender")
    executable.parent.mkdir()
    executable.write_text("test-binary")
    executable.chmod(0o755)
    monkeypatch.setattr(bridge, "discover_blender", lambda _: executable)
    settings = Settings(project="My Roblox Project", blender_enabled=True,
                        blender_edit=True, blender_executable=str(executable))
    calls = []
    host = BlenderController(settings=settings, home=tmp_path, spawn=fake_spawn(calls))

    async def run():
        assert (await host.probe())["version"] == "4.5.1 LTS"
        return await host.build(SCENE), await host.build(SCENE)

    first, second = asyncio.run(run())
    assert first["job_id"] != second["job_id"]
    assert first["mesh_count"] == 9 and first["triangle_count"] == 1234
    assert Path(first["blend_file"]).read_bytes() == b"BLENDER-MOCK"
    assert Path(second["glb_file"]).read_bytes() == b"glTF-MOCK"
    assert host.inspect(first["job_id"]) == first
    assert len(calls) == 3
    assert all("--factory-startup" in call[0] for call in calls)
    assert all("OPENAI_API_KEY" not in str(call[1]["env"]) for call in calls)
    assert all(Path(first["blend_file"]).parent.parent == Path(second["blend_file"]).parent.parent
               for _ in range(1))
    with pytest.raises(ValueError):
        host.inspect("../secret")
    with pytest.raises(ValueError):
        BlenderController(settings=Settings(project="Other Project", blender_enabled=True), home=tmp_path).inspect(first["job_id"])


def test_process_environment_drops_secrets(monkeypatch):
    from star.blender_bridge import _worker_environment
    monkeypatch.setenv("STAR_ROBLOX_KEY", "sensitive")
    monkeypatch.setenv("OPENAI_API_KEY", "sensitive")
    monkeypatch.setenv("PATH", "/local/bin")
    result = _worker_environment()
    assert "PATH" in result and "STAR_ROBLOX_KEY" not in result and "OPENAI_API_KEY" not in result


def test_mcp_tool_names_trigger_only_relevant_requests():
    assert wants_blender("Use Blender to generate trees and export a GLB")
    assert wants_blender("Brain 2, create a 3D model")
    assert not wants_blender("Tell me about a Roblox Studio GUI")
    assert not wants_blender("Write my shopping list")


def test_actual_sdk_mcp_bridge_blocks_write_without_owner_permission(tmp_path):
    settings = Settings(blender_enabled=True, blender_edit=False, blender_executable="")
    async def run():
        async with connect_blender(settings, tmp_path) as client:
            defs = client.definitions("Use Blender")
            assert {item["name"] for item in defs} == NAMES - {BUILD, ANIMATION_EXPORT, MOTION_QA}
            status_reply = await client.call(STATUS, {})
            assert status_reply["isError"] is False
            denied = await client.call(INSPECT, {"job_id": "../secret"})
            assert denied["isError"] is True
            with pytest.raises(PermissionError):
                await client.call(BUILD, SCENE)
    asyncio.run(run())
    assert not list(tmp_path.iterdir())


def test_mcp_server_exposes_build_only_after_owner_opt_in_and_validates(tmp_path, monkeypatch):
    import star.blender_bridge as bridge
    executable = tmp_path / "blender"
    executable.write_text("test-binary")
    monkeypatch.setattr(bridge, "discover_blender", lambda _: executable)
    settings = Settings(blender_enabled=True, blender_edit=True, blender_executable=str(executable))
    async def run():
        async with connect_blender(settings, tmp_path) as client:
            assert BUILD in {t["name"] for t in client.catalog}
            rejected = await client.call(BUILD, {"name": "abc", "objects": [], "python": "exec('bad')"})
            assert rejected["isError"] is True
            status_reply = await client.call(STATUS, {})
            assert status_reply["isError"] is False
    asyncio.run(run())
    assert not (tmp_path / "blender" / "jobs").exists()



def test_brain_two_agent_can_call_blender_through_real_mcp_memory_transport(tmp_path):
    from types import SimpleNamespace
    from star.agent import execute

    class Model:
        def __init__(self):
            self.seen = []

        async def create(self, **kwargs):
            self.seen.append(kwargs)
            if len(self.seen) == 1:
                call = SimpleNamespace(id="blender-1", function=SimpleNamespace(
                    name=STATUS, arguments="{}"))
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content="", tool_calls=[call]))])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Blender was inspected without starting a scene job.", tool_calls=None))])

    async def run():
        model = Model()
        client = SimpleNamespace(chat=SimpleNamespace(completions=model))
        settings = Settings(blender_enabled=True, blender_edit=False)
        async with connect_blender(settings, tmp_path) as blender:
            answer, messages, _ = await execute(client=client, model="local",
                prompt="Use Blender to check whether the local version is connected",
                image_paths=[], blender=blender)
        assert "inspected" in answer
        assert any(m.get("role") == "tool" for m in messages)
        assert STATUS in {item["function"]["name"] for item in model.seen[0]["tools"]}
        assert BUILD not in {item["function"]["name"] for item in model.seen[0]["tools"]}
        assert not (tmp_path / "blender" / "jobs").exists()

    asyncio.run(run())


def test_static_blender_worker_has_no_model_code_execution_or_asset_fetching():
    import ast
    source = Path(__file__).resolve().parents[1] / "star" / "blender_worker.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "json", "math", "pathlib", "sys", "bpy", "mathutils"}
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)]
    assert not ({"exec", "eval", "compile", "__import__"} & set(calls))



def test_auto_route_uses_blender_without_touching_studio():
    from star.desktop_core import needs_project_tools, needs_studio_connection
    assert needs_project_tools("Use Blender to build a forest cottage 3D model", blender=True)
    assert not needs_studio_connection("Use Blender to build a Roblox-ready GLB asset", blender=True)
    assert needs_studio_connection("Use Blender to build a model and import it into Roblox Studio", blender=True)
    # With the Blender switch off (the default) routing is what it was before Blender existed.
    assert not needs_project_tools("Use Blender to build a forest cottage 3D model")
    assert not needs_project_tools("Create a 3D model of a sword")
    assert needs_studio_connection("Fix the Roblox tree I exported from Blender")
