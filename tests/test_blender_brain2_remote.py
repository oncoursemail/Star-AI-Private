"""STAR's Blender on brain 2: everything that does not need the real machine (fake launcher + fake Lab session)."""
from __future__ import annotations

import ast
import asyncio
import base64
import json
import os
import re
import shutil
import struct
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import blender_brain2 as bb
from star.desktop_core import Settings
from star.react_shell import PERMITTED_SETTINGS

PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 360) + b"\x08\x02\x00\x00\x00" + b"\0" * 20
COMMAND = ["ssh", "brain2-host", "lxc", "exec", "box", "--", "blender-lab.sh"]


def make_glb(triangles=12, meshes=1) -> bytes:
    document = {"asset": {"version": "2.0"}, "nodes": [{"mesh": i} for i in range(meshes)],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]} for _ in range(meshes)],
                "accessors": [{"count": 8}, {"count": triangles * 3}], "materials": [{"name": "Iron"}],
                "extensionsUsed": ["KHR_materials_emissive_strength"]}
    body = json.dumps(document).encode()
    body += b" " * (-len(body) % 4)
    return b"glTF" + struct.pack("<II", 2, 20 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body


class FakeLauncher:
    """Stands in for `ssh ... blender-lab.sh <sub-command>`; records every call, never runs anything."""

    def __init__(self, running=True, files=None):
        self.running = running
        self.calls = []
        self.files = files or {}

    async def __call__(self, argv, timeout):
        assert argv[:len(COMMAND)] == COMMAND
        sub = argv[len(COMMAND):]
        self.calls.append(sub)
        if sub[0] == "status":
            return 0, json.dumps({"running": self.running, "mcp_port_open": self.running, "available_mb": 5000}).encode(), b""
        if sub[0] == "start":
            self.running = True
            return 0, b'{"started":true,"seconds_to_mcp":2.1}', b""
        if sub[0] == "stop":
            self.running = False
            return 0, b'{"stopped":true,"was_running":true}', b""
        if sub[0] == "shot":
            return 0, b'{"path":"shots/x.png","bytes":9}', b""
        if sub[0] == "list":
            return 0, b"lantern.blend\t1234\nexports/lantern.glb\t99\n", b""
        if sub[0] == "fetch":
            if sub[1] in self.files:
                return 0, self.files[sub[1]], b""
            return 7, b"", b"no such file"
        raise AssertionError(sub)


class FakeSession:
    def __init__(self, replies=None, reopen=False):
        self.calls = []
        self.replies = replies or []
        self.ensures = []          # the "is my scene the open file?" checks, answered separately
        self.reopen = reopen

    async def call_tool(self, name, arguments):
        if "create it with new_scene first" in arguments.get("code", ""):
            self.ensures.append(arguments["code"])
            return SimpleNamespace(structuredContent={"status": "ok", "result": {"reopened": self.reopen}}, content=[],
                                   isError=False)
        self.calls.append((name, arguments))
        reply = self.replies.pop(0) if self.replies else {"status": "ok", "result": {}}
        return SimpleNamespace(structuredContent=reply, content=[], isError=reply.get("status") != "ok")


def client(tmp_path, *, edit=True, launcher=None, session=None):
    launcher = launcher or FakeLauncher()
    session = session or FakeSession()

    @asynccontextmanager
    async def factory():
        yield session

    return bb.BrainTwoBlender(COMMAND, home=tmp_path, edit=edit, runner=launcher, session_factory=factory), launcher, session


def run(coro):
    return asyncio.run(coro)


def text(reply) -> dict:
    return json.loads(reply["content"][0]["text"])


# --------------------------------------------------------------------------- the filter for model Python

GOOD = [
    bb.LANTERN,
    "import bpy\nbpy.ops.mesh.primitive_cube_add(size=2)\nresult = {'n': len(bpy.data.objects)}",
    "import bpy, math, mathutils\nfor i in range(5):\n    bpy.ops.mesh.primitive_uv_sphere_add(location=(i, 0, 0))\n",
    "import bmesh, bpy\nm = bpy.data.meshes.new('x')\nb = bmesh.new()\nbmesh.ops.create_cube(b, size=1)\nb.to_mesh(m)\nb.free()",
    # learned on the dragon builds: bmesh.utils, f-string labels, sculpt/paint operators, bakes kept in memory
    "import bmesh\nb = bmesh.new()\ne = b.edges.new((b.verts.new((0, 0, 0)), b.verts.new((1, 0, 0))))\nbmesh.utils.edge_split(e, e.verts[0], 0.5)",
    "a, b = 1, 2\nlabel = f'{a}/{b} done'",
    "import bpy\nbpy.ops.object.mode_set(mode='SCULPT')\nbpy.ops.sculpt.mesh_filter(type='INFLATE', strength=0.1)",
    "import bpy\nbpy.ops.paint.vertex_color_dirt(blur_strength=1.0)",
    "import bpy\nbpy.ops.object.bake(type='NORMAL', use_selected_to_active=True, cage_extrusion=0.05)",
]
BAD = [
    ("import os", "Import of 'os'"),
    ("import subprocess", "Import of 'subprocess'"),
    ("from os import path", "Import of 'os'"),
    ("import bpy\nx = bpy.ops\nx.wm.quit_blender()", "bpy.ops must be used directly"),
    ("import bpy\nbpy.ops.wm.save_mainfile()", "bpy.ops.wm is not allowed"),
    ("import bpy\nbpy.ops.export_scene.fbx(filepath='a')", "is not allowed"),
    ("import bpy\nbpy.ops.object.bake(type='AO', save_mode='EXTERNAL')", "'save_mode=' is not allowed"),
    ("import bpy\nbpy.ops.object.bake(type='AO', filepath=chr(47) + 'tmp')", "'filepath=' is not allowed"),
    ("import bpy\nopts = dict(directory='x')", "'directory=' is not allowed"),
    ("import bpy as bmesh\nbmesh.utils.register_class(1)", "is not allowed"),
    ("import bpy, bmesh\nbmesh = bpy\nbmesh.utils.execfile('x')", ".utils"),
    ("import bpy, bmesh\ndef f(bmesh):\n    return bmesh.utils\n", ".utils"),
    ("import bpy\nx = f'{1}/etc/passwd'", "path or URL"),
    ("import bpy\nx = f'..{1}'", "path or URL"),
    ("import bpy\nbpy.ops.image.new(name='x')", "bpy.ops.image is not allowed"),
    ("import bpy\nbpy.ops.render.render()", "bpy.ops.render is not allowed"),
    ("import bpy\nbpy.ops.script.python_file_run()", "bpy.ops.script is not allowed"),
    ("from bpy import ops", "Importing bpy.ops"),
    ("open('a')", "'open'"),
    ("exec('1')", "'exec'"),
    ("eval('1')", "'eval'"),
    ("import bpy\ngetattr(bpy, 'x')", "'getattr'"),
    ("x = ().__class__", "'.__class__'"),
    ("__import__('os')", "__import__"),
    ("import bpy\nbpy.data.libraries.load('a')", "is not allowed"),
    ("import bpy\nbpy.data.images.load('a')", ".load"),
    ("import bpy\nbpy.app.timers.register(print)", "is not allowed"),
    ("import bpy\nbpy.utils.register_class(1)", "is not allowed"),
    ("import bpy\nbpy.context.preferences.view", ".preferences"),
    ("import bpy\nbpy.context.scene.render.filepath = 'a'", ".filepath"),
    ("while True:\n    pass", "While"),
    ("class A:\n    pass", "ClassDef"),
    ("x = '/etc/passwd'", "path or URL"),
    ("x = '..\\\\a'", "path or URL"),
    ("x = 'C:/Users'", "path or URL"),
    ("x = 'http://example.com'", "path or URL"),
    ("for i in range(900000):\n    pass", "range()"),
    ("def f(:", "syntax error"),
    # Module escapes through what allowed modules carry (random._os, typing.sys, operator.attrgetter, ...)
    ("import random\nrandom._os.read(1)", "'._os'"),
    ("import collections\ncollections._sys", "'._sys'"),
    ("from random import _os", "private names"),
    ("from collections import _sys", "private names"),
    ("import typing", "Import of 'typing'"),
    ("from typing import sys", "Import of 'typing'"),
    ("from bpy_extras.io_utils import os", "private names or modules"),
    ("import bpy_extras\nbpy_extras.io_utils.os", "'.os'"),
    ("import bpy\nbpy.types.sys", "'.sys'"),
    ("", "needs Python code"),
]


@pytest.mark.parametrize("code", GOOD)
def test_good_code_passes(code):
    assert bb.check_bpy_code(code) == code


@pytest.mark.parametrize("code,reason", BAD)
def test_bad_code_is_refused_with_a_reason(code, reason):
    with pytest.raises(ValueError) as error:
        bb.check_bpy_code(code)
    assert reason in str(error.value)


def test_code_size_and_type_limits():
    with pytest.raises(ValueError):
        bb.check_bpy_code("x = 1\n" * 5000)
    with pytest.raises(ValueError):
        bb.check_bpy_code(None)
    with pytest.raises(ValueError):
        bb.check_bpy_code("x = 1\x00")


# --------------------------------------------------------------------------- the fixed code that runs in Blender

@pytest.mark.parametrize("template,values", [
    (bb.NEW_SCENE, {"SCENE": "lantern"}), (bb.OPEN_SCENE, {"SCENE": "lantern"}), (bb.SAVE_SCENE, {"SCENE": "lantern"}),
    (bb.VIEW, {"AZ": 40.0, "EL": 25.0, "ZOOM": 1.0, "HASC": 0, "CX": 0.0, "CY": 0.0, "CZ": 0.0}),
    (bb.RENDER, {"W": 640, "H": 360, "AZ": 0.0, "EL": 0.0, "ZOOM": 1.0, "ENGINE": "workbench", "NAME": "a-front",
                 "SAMPLES": 0, "DENOISE": 0, "CAMERA": "auto", "LOOK": "clay", "HASC": 1, "CX": 0.0, "CY": -3.1, "CZ": 5.6}),
    (bb.BAKE, {"SCENE": "dragon", "OBJECT": "Low Body", "SOURCE": "High", "SIZE": 2048, "MAPS": "normal,ao,color",
               "SAMPLES": 16, "EXTRUSION": 0.05, "MARGIN": 8}),
    (bb.EXPORT, {"SCENE": "lantern", "FORMAT": "glb"}),
])
def test_templates_are_valid_python_with_values_as_literals(template, values):
    code = bb.fill(template, **values)
    ast.parse(code)
    assert "@@" not in code


def test_fill_refuses_missing_and_non_literal_values():
    with pytest.raises(ValueError):
        bb.fill(bb.NEW_SCENE)
    with pytest.raises(ValueError):
        bb.fill(bb.NEW_SCENE, SCENE=["a"])
    with pytest.raises(ValueError):
        bb.fill(bb.NEW_SCENE, SCENE=True)
    evil = bb.fill(bb.NEW_SCENE, SCENE="a'; import os #")   # even if one slipped through, it stays one string literal
    tree = ast.parse(evil)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import) and n.names[0].name == "os"]


def test_sandbox_comes_from_the_environment_not_from_the_repo():
    for template in (bb.NEW_SCENE, bb.RENDER, bb.EXPORT, bb.OPEN_SCENE):
        assert 'os.environ["BLENDER_LAB_SANDBOX"]' in template
        assert "/home/" not in template


# --------------------------------------------------------------------------- the tool surface and its gates

def test_off_by_default_and_gated_by_settings(tmp_path):
    settings = Settings()
    assert settings.blender_brain2 is False and settings.blender_enabled is False
    assert "blender_brain2" in PERMITTED_SETTINGS
    with pytest.raises(ValueError):
        Settings(blender_brain2=True).validate()
    Settings(blender_enabled=True, blender_brain2=True).validate()
    with pytest.raises(ValueError):
        Settings(blender_enabled=True, blender_brain2="yes").validate()

    async def connect(s):
        async with bb.connect_brain2_blender(s, tmp_path) as c:
            return c
    with pytest.raises(PermissionError):
        run(connect(Settings(blender_enabled=True)))
    with pytest.raises(RuntimeError):   # enabled but no launcher command stored
        run(connect(Settings(blender_enabled=True, blender_brain2=True)))
    bb.save_command(tmp_path, COMMAND)
    got = run(connect(Settings(blender_enabled=True, blender_brain2=True, blender_edit=True)))
    assert got.edit is True and run(connect(Settings(blender_enabled=True, blender_brain2=True))).edit is False


def test_catalog_hides_edit_actions_without_the_edit_permission(tmp_path):
    read_only, _, _ = client(tmp_path, edit=False)
    full, _, _ = client(tmp_path, edit=True)
    ro = read_only.catalog[0]["inputSchema"]["properties"]["action"]["enum"]
    assert set(ro) == set(bb.READ_ACTIONS) and "run_bpy" not in ro and "start" not in ro
    assert set(full.catalog[0]["inputSchema"]["properties"]["action"]["enum"]) == set(bb.READ_ACTIONS + bb.EDIT_ACTIONS)
    assert read_only.owns(bb.TOOL) and not read_only.owns("star_blender_status")


def test_definitions_only_for_blender_prompts(tmp_path):
    c, _, _ = client(tmp_path)
    assert c.definitions("Build a lantern in Blender and export a GLB")
    assert c.definitions("what is the weather") == []


def test_validation_errors_are_results_not_crashes(tmp_path):
    c, launcher, session = client(tmp_path, edit=False)
    for args in ({}, {"action": "nope"}, {"action": "status", "extra": 1}, {"action": "screenshot", "angles": ["sideways"]},
                 {"action": "docs"}, {"action": "screenshot", "azimuth": 9999}):
        reply = run(c.call(bb.TOOL, args))
        assert reply["isError"] is True and "error" in text(reply)
    denied = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "a-b", "code": "x=1"}))
    assert denied["isError"] and "edit permission" in text(denied)["error"]
    assert launcher.calls == [] and session.calls == []   # nothing reached the machine
    with pytest.raises(PermissionError):
        run(c.call("something_else", {}))


def test_run_bpy_blocked_code_never_reaches_blender(tmp_path):
    c, launcher, session = client(tmp_path)
    reply = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "lantern", "code": "import os\nos.system('x')"}))
    assert reply["isError"] and "Import of 'os'" in text(reply)["error"]
    bad_scene = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "../etc", "code": "x = 1"}))
    assert bad_scene["isError"]
    assert launcher.calls == [] and session.calls == []


def test_run_bpy_runs_then_saves_the_scene(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"built": ["Lantern_Iron"]}},
                           {"status": "ok", "result": {"triangles": 636, "scene": "lantern"}}])
    c, launcher, _ = client(tmp_path, session=session)
    reply = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "lantern", "code": "result = {'a': 1}"}))
    assert not reply["isError"], reply
    assert text(reply)["ran"] == {"built": ["Lantern_Iron"]} and text(reply)["scene"]["triangles"] == 636
    assert session.calls[0] == ("execute_blender_code", {"code": "result = {'a': 1}"})
    assert "save_as_mainfile" in session.calls[1][1]["code"] and "'lantern'" in session.calls[1][1]["code"]


def test_a_failing_run_is_reported_and_not_saved(tmp_path):
    session = FakeSession([{"status": "error", "message": "Traceback...\nNameError: name 'zz' is not defined"}])
    c, _, _ = client(tmp_path, session=session)
    reply = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "lantern", "code": "zz"}))
    assert reply["isError"] and "NameError" in text(reply)["error"]
    assert len(session.calls) == 1   # the save step did not run


def test_edit_actions_start_blender_when_it_is_not_running(tmp_path):
    c, launcher, session = client(tmp_path, launcher=FakeLauncher(running=False), session=FakeSession([{"status": "ok", "result": {"scene": "a-b"}}]))
    reply = run(c.call(bb.TOOL, {"action": "new_scene", "scene": "a-b"}))
    assert not reply["isError"]
    assert [call[0] for call in launcher.calls][:3] == ["status", "start", "status"]


def test_read_actions_never_start_blender(tmp_path):
    c, launcher, session = client(tmp_path, launcher=FakeLauncher(running=False))
    reply = run(c.call(bb.TOOL, {"action": "screenshot", "angles": ["front"]}))
    assert reply["isError"] and "not running" in text(reply)["error"]
    assert [call[0] for call in launcher.calls] == ["status"] and session.calls == []
    inspect = run(c.call(bb.TOOL, {"action": "inspect"}))
    assert inspect["isError"]


def test_screenshot_returns_images_and_keeps_evidence(tmp_path):
    launcher = FakeLauncher(files={"shots/lantern-front.png": PNG, "shots/lantern-top.png": PNG})
    session = FakeSession([{"status": "ok", "result": {"crop": [0, 24, 1574, 932], "meshes": 3}},
                           {"status": "ok", "result": {"crop": [0, 24, 1574, 932], "meshes": 3}}])
    c, _, _ = client(tmp_path, edit=False, launcher=launcher, session=session)
    reply = run(c.call(bb.TOOL, {"action": "screenshot", "scene": "lantern", "angles": ["front", "top"]}))
    assert not reply["isError"], reply
    images = [b for b in reply["content"] if b["type"] == "image"]
    assert len(images) == 2 and base64.b64decode(images[0]["data"]) == PNG
    shots = text(reply)["screenshots"]
    assert [s["angle"] for s in shots] == ["front", "top"] and shots[0]["size"] == [640, 360]
    assert (tmp_path / shots[0]["evidence"]).read_bytes() == PNG
    # the angle numbers really went into the view code (front = az 0 el 0, top = az 0 el 90)
    assert "math.radians(90.0 - 0.0)" in session.calls[0][1]["code"] and "math.radians(90.0 - 90.0)" in session.calls[1][1]["code"]
    crop = [c for c in launcher.calls if c[0] == "shot"][0]
    assert crop == ["shot", "lantern-front", "0", "24", "1574", "932"]


def test_screenshot_rejects_a_non_png_and_an_empty_scene(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"crop": [0, 0, 10, 10], "meshes": 0}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"shots/v-front.png": b"junk"}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "screenshot", "angles": ["front"]}))
    assert reply["isError"] and "no visible mesh" in text(reply)["error"]
    session2 = FakeSession([{"status": "ok", "result": {"crop": [0, 0, 10, 10], "meshes": 1}}])
    c2, _, _ = client(tmp_path, launcher=FakeLauncher(files={"shots/view-front.png": b"junk"}), session=session2)
    reply2 = run(c2.call(bb.TOOL, {"action": "screenshot", "angles": ["front"]}))
    assert reply2["isError"] and "PNG" in text(reply2)["error"]


def test_render_preview_uses_the_requested_size_engine_and_angle(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"file": "previews/lantern-three_quarter.png", "engine": "workbench", "size": [320, 180]}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/lantern-three_quarter.png": PNG}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "lantern", "width": 320, "height": 180,
                                 "engine": "workbench", "angles": ["three_quarter"]}))
    assert not reply["isError"], reply
    code = session.calls[0][1]["code"]
    assert "w, h = 320, 180" in code and "engine = 'workbench'" in code and "math.radians(40.0)" in code
    assert len([b for b in reply["content"] if b["type"] == "image"]) == 1
    too_big = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "lantern", "width": 4000}))
    assert too_big["isError"]


def test_export_glb_is_inspected_from_the_real_bytes(tmp_path):
    glb = make_glb(triangles=212, meshes=3)
    session = FakeSession([{"status": "ok", "result": {"file": "exports/lantern.glb", "bytes": len(glb), "triangles": 636,
                                                       "size_m": [0.5, 0.5, 0.9]}, "stdout": "INFO exporter chatter"}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"exports/lantern.glb": glb}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "export", "scene": "lantern", "format": "glb"}))
    info = text(reply)
    assert not reply["isError"], info
    assert info["glb"]["meshes"] == 3 and info["glb"]["triangles"] == 636 and "stdout" not in info
    assert (tmp_path / info["evidence"]).read_bytes() == glb
    assert "Nothing was uploaded" in info["roblox_note"]


def test_export_defaults_to_glb_and_checks_the_fbx_header(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"file": "exports/a-b.fbx"}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"exports/a-b.fbx": b"not an fbx"}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "export", "scene": "a-b", "format": "fbx"}))
    assert reply["isError"] and "FBX header" in text(reply)["error"]
    session2 = FakeSession([{"status": "ok", "result": {"file": "exports/a-b.fbx"}}])
    c2, _, _ = client(tmp_path, launcher=FakeLauncher(files={"exports/a-b.fbx": b"Kaydara FBX Binary  \x00" + b"0" * 30}), session=session2)
    assert not run(c2.call(bb.TOOL, {"action": "export", "scene": "a-b", "format": "fbx"}))["isError"]
    assert "'glb'" in bb.fill(bb.EXPORT, SCENE="x-y", FORMAT="glb")


def test_list_files_stop_and_status(tmp_path):
    c, launcher, _ = client(tmp_path, edit=True)
    files = text(run(c.call(bb.TOOL, {"action": "list_files"})))["files"]
    assert files[0] == {"file": "lantern.blend", "bytes": 1234}
    assert text(run(c.call(bb.TOOL, {"action": "status"})))["edit_permission"] is True
    assert text(run(c.call(bb.TOOL, {"action": "stop"})))["stopped"] is True and launcher.running is False


def test_errors_never_leak_the_command_or_remote_output(tmp_path):
    async def exploding(argv, timeout):
        raise OSError("ssh brain2-host: connection refused " + " ".join(argv))
    c = bb.BrainTwoBlender(COMMAND, home=tmp_path, edit=True, runner=exploding)
    reply = run(c.call(bb.TOOL, {"action": "status"}))
    assert reply["isError"]
    flat = json.dumps(reply)
    assert "brain2-host" not in flat and "blender-lab.sh" not in flat and "OSError" in flat

    async def failing(argv, timeout):
        return 5, b"", b"secret stderr details"
    memory = bb.BrainTwoBlender(COMMAND, home=tmp_path, edit=True, runner=failing)
    flat = json.dumps(run(memory.call(bb.TOOL, {"action": "status"})))
    assert "memory" in flat and "details" not in flat and "secret" not in flat


def test_inspect_and_docs_use_only_the_labs_read_tools(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"collections": ["Scene"]}}, {"status": "ok", "result": {"matches": 1}}])
    c, _, _ = client(tmp_path, session=session)
    assert not run(c.call(bb.TOOL, {"action": "inspect"}))["isError"]
    assert not run(c.call(bb.TOOL, {"action": "docs", "query": "primitive_cube_add"}))["isError"]
    assert [call[0] for call in session.calls] == ["get_objects_summary", "search_api_docs"]
    detail = FakeSession([{"status": "ok", "result": {}}])
    c2, _, _ = client(tmp_path, session=detail)
    run(c2.call(bb.TOOL, {"action": "inspect", "object": "Lantern_Iron"}))
    assert detail.calls[0] == ("get_object_detail_summary", {"name": "Lantern_Iron"})
    assert run(c2.call(bb.TOOL, {"action": "inspect", "object": "x'); import os"}))["isError"]


# --------------------------------------------------------------------------- helpers and the stored command

def test_inspect_glb_reads_the_header_and_refuses_junk():
    info = bb.inspect_glb(make_glb(triangles=10, meshes=2))
    assert info["version"] == 2 and info["meshes"] == 2 and info["triangles"] == 20
    assert info["declared_bytes"] == info["actual_bytes"] and info["materials"] == ["Iron"]
    for junk in (b"", b"glTF", b"PK\x03\x04" + b"0" * 40):
        with pytest.raises(ValueError):
            bb.inspect_glb(junk)


def test_png_helpers():
    assert bb.is_png(PNG) and not bb.is_png(b"GIF89a") and bb.png_size(PNG) == (640, 360)


def test_command_storage_validation_and_privacy(tmp_path, monkeypatch):
    monkeypatch.delenv(bb.COMMAND_ENV, raising=False)
    assert bb.load_command(tmp_path) == [] and bb.public(tmp_path) == {"configured": False, "program": ""}
    shown = bb.save_command(tmp_path, COMMAND)
    assert shown == {"configured": True, "program": "ssh"} and "brain2-host" not in json.dumps(shown)
    assert bb.load_command(tmp_path) == COMMAND
    monkeypatch.setenv(bb.COMMAND_ENV, json.dumps(["other", "x"]))
    assert bb.load_command(tmp_path) == ["other", "x"]
    for bad in ([], "ssh", ["ssh", ""], ["a"] * 41, ["a\nb"], [1], None):
        with pytest.raises(ValueError):
            bb.validate_command(bad)
    monkeypatch.setenv(bb.COMMAND_ENV, "{not json")
    assert bb.load_command(tmp_path) == []
    (tmp_path / "blender" / "brain2.json").write_text("garbage", encoding="utf-8")
    monkeypatch.delenv(bb.COMMAND_ENV)
    assert bb.load_command(tmp_path) == []


def test_command_line_without_a_command_is_a_clear_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(bb.COMMAND_ENV, raising=False)
    assert bb.main(["--home", str(tmp_path), "--status"]) == 2
    assert "No launcher command" in capsys.readouterr().out
    assert bb.main(["--home", str(tmp_path), "--set-command", json.dumps(COMMAND)]) == 0
    assert bb.main(["--home", str(tmp_path)]) == 0


def test_the_demo_runs_the_whole_chain_through_the_tool(tmp_path):
    glb = make_glb(triangles=636, meshes=3)
    launcher = FakeLauncher(files={
        "shots/lantern-three_quarter.png": PNG, "shots/lantern-front.png": PNG, "shots/lantern-top.png": PNG,
        "previews/lantern-three_quarter.png": PNG, "exports/lantern.glb": glb, "shots/gui-window.png": PNG})
    view = {"status": "ok", "result": {"crop": [0, 24, 1574, 932], "meshes": 3}}
    session = FakeSession([
        {"status": "ok", "result": {"scene": "lantern"}},                       # new_scene
        {"status": "ok", "result": {"built": ["Lantern_Iron", "Lantern_Glass", "Lantern_Flame"]}},   # run_bpy
        {"status": "ok", "result": {"triangles": 636}},                         # save
        view, view, view,                                                       # three views
        {"status": "ok", "result": {"file": "previews/lantern-three_quarter.png", "engine": "eevee", "size": [640, 360]}},
        {"status": "ok", "result": {"file": "exports/lantern.glb", "bytes": len(glb), "triangles": 636}},
    ])
    c, _, _ = client(tmp_path, launcher=launcher, session=session)
    report = run(bb.run_demo(c, tmp_path / "out"))
    assert [s["step"] for s in report["steps"]] == ["status", "new_scene", "run_bpy", "screenshot", "render_preview", "export"]
    assert all(s["ok"] for s in report["steps"])
    out = tmp_path / "out"
    assert (out / "lantern.glb").read_bytes() == glb and (out / "report.json").is_file()
    assert {p.name for p in out.glob("*.png")} == {"viewport-three_quarter.png", "viewport-front.png", "viewport-top.png",
                                                    "render-three_quarter.png", "gui-window.png"}
    # the demo's own code passes the same filter a model's code must pass
    assert bb.check_bpy_code(session.calls[1][1]["code"])


# --------------------------------------------------------------------------- the launcher script (syntax + sandbox rules)

SCRIPT = Path(__file__).resolve().parents[1] / "server" / "brain2_blender" / "blender-lab.sh"
BASH = shutil.which("bash")


_BASH_RUNTIME_TROUBLE = re.compile(rb"fork|Win32 error|cygheap|signal pipe|couldn't|Resource temporarily|Cannot allocate", re.I)


def run_bash(argv, **kwargs):
    """subprocess.run for Git Bash. Its fork emulation can fail to start a child while the PC is saturated (the full
    suite beside other work): a crash code or a runtime message, never the script's own exit codes 0-7. Only that is
    retried, a few times; every real answer of the script is returned at once."""
    for attempt in range(4):
        result = subprocess.run(argv, capture_output=True, timeout=60, **kwargs)
        code = result.returncode
        trouble = (code < 0 or code >= 0xC0000000 or code >= 126 and bool(_BASH_RUNTIME_TROUBLE.search(result.stderr)))
        if not trouble or attempt == 3:
            return result
        time.sleep(1 + attempt)


def sh(tmp_path, *args):
    env = {**os.environ, "BLENDER_LAB_HOME": str(tmp_path), "HOME": str(tmp_path),
           "BLENDER_PATH": str(tmp_path / "missing-blender")}
    return run_bash([BASH, str(SCRIPT), *args], env=env)


def test_the_bash_helper_retries_only_runtime_trouble_and_never_a_real_script_answer(monkeypatch):
    answers = [SimpleNamespace(returncode=0xC0000142, stderr=b"", stdout=b""),
               SimpleNamespace(returncode=128, stderr=b"bash: fork: retry: Resource temporarily unavailable", stdout=b""),
               SimpleNamespace(returncode=7, stderr=b"", stdout=b"")]
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(1) or answers.pop(0))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert run_bash(["bash"]).returncode == 7 and len(calls) == 3        # two transient failures, then the answer
    calls.clear()
    answers[:] = [SimpleNamespace(returncode=3, stderr=b"fork is in the message of a real refusal", stdout=b"")]
    assert run_bash(["bash"]).returncode == 3 and len(calls) == 1        # the script's own exit codes are final


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_launcher_script_syntax_and_no_private_names():
    assert run_bash([BASH, "-n", str(SCRIPT)]).returncode == 0
    body = SCRIPT.read_text(encoding="utf-8")
    assert "0.0.0.0" not in body.replace("never 0.0.0.0", "") and "127.0.0.1" in body
    assert "/home/" not in body and "@" not in body.replace("${", "")
    assert not re.search(r"\d+\.\d+\.\d+\.\d+", body.replace("127.0.0.1", "").replace("0.0.0.0", ""))


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_launcher_fetch_only_serves_validated_names_inside_the_sandbox(tmp_path):
    (tmp_path / "sandbox" / "exports").mkdir(parents=True)
    (tmp_path / "sandbox" / "exports" / "a.glb").write_bytes(b"glTFdata")
    (tmp_path / "secret.txt").write_text("nope")
    ok = sh(tmp_path, "fetch", "exports/a.glb")
    assert ok.returncode == 0 and ok.stdout == b"glTFdata"
    for bad in ("../secret.txt", "exports/../../secret.txt", "/etc/passwd", "a/b/c.txt", ".hidden", "a b", "exports/missing.glb", ""):
        result = sh(tmp_path, "fetch", bad)
        assert result.returncode == 7 and result.stdout == b"", bad


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_launcher_refuses_to_start_without_blender_and_rejects_bad_shot_names(tmp_path):
    assert sh(tmp_path, "start").returncode == 3
    assert sh(tmp_path, "shot", "../x", "0", "0", "1", "1").returncode == 7
    assert sh(tmp_path, "shot", "x", "1", "2").returncode in (2, 7)
    assert sh(tmp_path, "nonsense").returncode == 2


# --------------------------------------------------------------------------- dragon hard test (2026-10-13) additions

def test_a_blender_error_inside_the_mcp_session_is_shown_not_hidden(tmp_path):
    """anyio task groups (the real stdio session) wrap a LabError raised in their body in an ExceptionGroup; the model
    must still get 'Blender code failed: ...', not 'could not be reached (ExceptionGroup)'."""
    session = FakeSession([{"status": "error", "message": "Traceback...\nAttributeError: 'NoneType' has no attribute 'x'"}])

    @asynccontextmanager
    async def wrapping_factory():
        try:
            yield session
        except Exception as error:
            raise ExceptionGroup("unhandled errors in a TaskGroup", [error]) from None

    c = bb.BrainTwoBlender(COMMAND, home=tmp_path, edit=True, runner=FakeLauncher(), session_factory=wrapping_factory)
    reply = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "dragon", "code": "x = 1"}))
    assert reply["isError"] and text(reply)["error"].startswith("Blender code failed: AttributeError")
    # a real transport failure still only shows its kind
    assert bb._first_safe_error(ExceptionGroup("g", [OSError("secret-launcher-host refused")])) is None


def test_screenshot_zoom_and_frame_reach_the_view_code(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"crop": [0, 24, 1574, 932], "meshes": 6}}])
    c, _, _ = client(tmp_path, edit=False, launcher=FakeLauncher(files={"shots/dragon-front.png": PNG}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "screenshot", "scene": "dragon", "angles": ["front"], "zoom": 2.0, "frame": 25}))
    assert not reply["isError"], reply
    code = session.calls[0][1]["code"]
    assert code.startswith("import bpy\nbpy.context.scene.frame_set(25)\n")
    assert "r3d.view_distance *= 0.95 / 2.0" in code and "show_bones = False" in code
    for bad in ({"zoom": 9}, {"zoom": 0.1}, {"frame": -1}, {"frame": 1.5}, {"frame": "1); import os"}):
        assert run(c.call(bb.TOOL, {"action": "screenshot", "angles": ["front"], **bad}))["isError"]
    with pytest.raises(ValueError):
        bb._at_frame("x = 1", True)


def test_render_preview_zoom_and_frame(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"file": "previews/dragon-right.png", "engine": "eevee", "size": [960, 540]}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/dragon-right.png": PNG}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "dragon", "engine": "eevee", "angles": ["right"],
                                 "width": 960, "height": 540, "zoom": 2.0, "frame": 13}))
    assert not reply["isError"], reply
    code = session.calls[0][1]["code"]
    assert code.startswith("import bpy\nbpy.context.scene.frame_set(13)\n") and "* 1.12 / 2.0" in code
    ast.parse(code)


def test_export_takes_the_deforming_rig_and_its_animation():
    code = bb.fill(bb.EXPORT, SCENE="dragon", FORMAT="fbx")
    ast.parse(code)
    assert "object_types={'MESH', 'ARMATURE'}" in code and "bake_anim=animated" in code
    assert "m.type == 'ARMATURE' and m.object == o" in code and "export_animations=animated" in code
    assert "per_mesh_triangles=per_mesh" in code and "add_leaf_bones=False" in code


def test_inspect_glb_reports_skins_and_animations():
    document = {"asset": {"version": "2.0"}, "nodes": [{"mesh": 0}], "accessors": [{"count": 8}, {"count": 6}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
                "skins": [{"joints": [1, 2, 3]}], "animations": [{"name": "Dragon_WingFlap", "channels": [{}, {}]}]}
    body = json.dumps(document).encode()
    body += b" " * (-len(body) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 20 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body
    info = bb.inspect_glb(glb)
    assert info["skins"] == [3] and info["animations"] == [{"name": "Dragon_WingFlap", "channels": 2}]
    assert bb.inspect_glb(make_glb())["animations"] == []


def test_command_line_call_file_avoids_argument_quoting(tmp_path, monkeypatch, capsys):
    seen = []

    class FakeClient:
        def __init__(self, command, *, home, edit):
            self.home = home

        async def call(self, name, arguments):
            seen.append(arguments)
            return {"isError": False, "content": [{"type": "text", "text": "{}"}]}

    monkeypatch.setattr(bb, "BrainTwoBlender", FakeClient)
    monkeypatch.setenv(bb.COMMAND_ENV, json.dumps(COMMAND))
    code = "s = \"quote ' and \\\" and $HOME and %PATH%\"\nresult = {'n': 1}\n" * 50
    call = tmp_path / "call.json"
    call.write_text(json.dumps({"action": "run_bpy", "scene": "dragon", "code": code}), encoding="utf-8")
    assert bb.main(["--home", str(tmp_path), "--edit", "--call-file", str(call)]) == 0
    assert seen == [{"action": "run_bpy", "scene": "dragon", "code": code}]


# --------------------------------------------------------------------------- dragon v3: bakes, scene camera, labels

def test_bake_saves_textures_fetches_them_and_saves_the_scene(tmp_path):
    files = {"textures/dragon-Dragon_Low-normal.png": PNG, "textures/dragon-Dragon_Low-ao.png": PNG}
    session = FakeSession([
        {"status": "ok", "result": {"object": "Dragon_Low", "source": "Dragon_High", "size": 2048, "maps": [
            {"map": "normal", "image": "Dragon_Low_normal", "file": "textures/dragon-Dragon_Low-normal.png", "seconds": 3.1},
            {"map": "ao", "image": "Dragon_Low_ao", "file": "textures/dragon-Dragon_Low-ao.png", "seconds": 40.2}]}},
        {"status": "ok", "result": {"saved_bytes": 12345}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files=files), session=session)
    reply = run(c.call(bb.TOOL, {"action": "bake", "scene": "dragon", "object": "Dragon_Low", "source": "Dragon_High",
                                 "maps": ["normal", "ao"], "size": 2048, "samples": 16, "extrusion": 0.06,
                                 "label": "p3"}))
    info = text(reply)
    assert not reply["isError"], info
    code = session.calls[0][1]["code"]
    ast.parse(code)
    assert "size, maps = 2048, 'normal,ao'.split(\",\")" in code and "bpy.ops.object.bake(**options)" in code
    assert "cage_extrusion=0.06" in code and "scene.cycles.samples = 16" in code and "img.save()" in code
    assert "os.path.join(SB, rel)" in code and "'Dragon_High'" in code
    assert "o.hide_render = True" in code and "o.hide_render = False" in code   # others sit out, then come back
    assert "save_as_mainfile" in session.calls[1][1]["code"]   # the scene (with the new image links) is saved
    assert [m["evidence"] for m in info["maps"]] == ["blender/brain2/dragon/p3-dragon-Dragon_Low-normal.png",
                                                    "blender/brain2/dragon/p3-dragon-Dragon_Low-ao.png"]
    assert (tmp_path / info["maps"][0]["evidence"]).read_bytes() == PNG and info["maps"][0]["size"] == [640, 360]
    assert len([b for b in reply["content"] if b["type"] == "image"]) == 2 and info["scene_saved_bytes"] == 12345


@pytest.mark.parametrize("bad", [
    {"action": "bake", "scene": "dragon"},                                                    # no target
    {"action": "bake", "scene": "dragon", "object": "A", "source": "A"},                      # same mesh
    {"action": "bake", "scene": "dragon", "object": "A", "maps": ["albedo"]},                 # unknown map
    {"action": "bake", "scene": "dragon", "object": "A", "size": 4096},                       # too big for Roblox
    {"action": "bake", "scene": "dragon", "object": "A", "maps": ["ao", "ao"]},               # duplicate
    {"action": "bake", "object": "A"},                                                        # no scene
    {"action": "bake", "scene": "dragon", "object": "A/../x"},                                # bad name
    {"action": "render_preview", "camera": "orbit"}, {"action": "render_preview", "samples": 0},
    {"action": "render_preview", "label": "../x"}, {"action": "render_preview", "width": 4096},
    {"action": "render_preview", "preset": "square8k"}, {"action": "render_preview", "look": "xray"},
])
def test_bake_and_render_options_are_validated(tmp_path, bad):
    c, launcher, session = client(tmp_path)
    reply = run(c.call(bb.TOOL, bad))
    assert reply["isError"] and not session.calls and launcher.calls == []


def test_bake_needs_the_edit_permission(tmp_path):
    c, launcher, session = client(tmp_path, edit=False)
    reply = run(c.call(bb.TOOL, {"action": "bake", "scene": "dragon", "object": "A"}))
    assert reply["isError"] and "edit permission" in text(reply)["error"] and not session.calls
    assert "bake" not in c.catalog[0]["inputSchema"]["properties"]["action"]["enum"]


def test_a_failed_bake_is_reported_and_nothing_is_fetched(tmp_path):
    session = FakeSession([{"status": "error", "message": "Traceback\nRuntimeError: bake: the target mesh has no UV map"}])
    c, launcher, _ = client(tmp_path, session=session)
    reply = run(c.call(bb.TOOL, {"action": "bake", "scene": "dragon", "object": "A"}))
    assert reply["isError"] and "no UV map" in text(reply)["error"]
    assert not [call for call in launcher.calls if call[0] == "fetch"]


def test_render_through_the_scene_camera_with_samples_denoise_and_a_label(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"file": "previews/dragon-camera.png", "engine": "cycles", "size": [1280, 720]}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/dragon-camera.png": PNG}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "dragon", "engine": "cycles", "camera": "scene",
                                 "angles": ["front", "right"], "width": 1280, "height": 720, "samples": 96,
                                 "denoise": True, "label": "hero-p3"}))
    info = text(reply)
    assert not reply["isError"], info
    assert len(session.calls) == 1   # the scene camera is one view; the angles do not apply
    code = session.calls[0][1]["code"]
    ast.parse(code)
    assert "use_scene_camera = 'scene' == \"scene\"" in code and "samples, denoise = 96, bool(1)" in code
    assert "scene.camera = old_cam if use_scene_camera else cam" in code
    assert info["previews"][0]["evidence"] == "blender/brain2/dragon/hero-p3-render-camera.png"


def test_screenshot_label_keeps_earlier_passes(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"crop": [0, 0, 10, 10], "meshes": 1}},
                           {"status": "ok", "result": {"crop": [0, 0, 10, 10], "meshes": 1}}])
    c, _, _ = client(tmp_path, edit=False, launcher=FakeLauncher(files={"shots/dragon-front.png": PNG}), session=session)
    one = text(run(c.call(bb.TOOL, {"action": "screenshot", "scene": "dragon", "angles": ["front"], "label": "p1"})))
    two = text(run(c.call(bb.TOOL, {"action": "screenshot", "scene": "dragon", "angles": ["front"], "label": "p2"})))
    assert one["screenshots"][0]["evidence"].endswith("/p1-front.png")
    assert two["screenshots"][0]["evidence"].endswith("/p2-front.png")
    assert (tmp_path / one["screenshots"][0]["evidence"]).exists()


def test_existing_world_is_kept_by_renders():
    code = bb.fill(bb.RENDER, W=64, H=64, AZ=0.0, EL=0.0, ZOOM=1.0, ENGINE="eevee", NAME="x", SAMPLES=32, DENOISE=0,
                   CAMERA="auto", LOOK="material", **bb._centre(None))
    assert "    if scene.world is None:   # a world the scene already has" in code
    assert "scene.eevee.taa_render_samples = samples" in code


def test_scene_actions_reopen_their_scene_after_a_blender_restart(tmp_path):
    # Blender restarted (30-minute limit or a crash): the factory scene is open. run_bpy must not edit and then save
    # the factory cube over the real scene, and a render must not show the cube.
    session = FakeSession([{"status": "ok", "result": {"made": 1}}, {"status": "ok", "result": {"saved_bytes": 9}}],
                          reopen=True)
    c, _, _ = client(tmp_path, session=session)
    reply = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "dragon", "code": "result = {'made': 1}"}))
    info = text(reply)
    assert not reply["isError"] and "reopened" in info["note"]
    assert len(session.ensures) == 1 and "'dragon' + \".blend\"" in session.ensures[0]
    assert "bpy.ops.wm.open_mainfile(filepath=path)" in session.ensures[0]
    ast.parse(session.ensures[0])
    for call, files in (({"action": "render_preview", "scene": "dragon", "angles": ["front"]}, {"previews/dragon-front.png": PNG}),
                        ({"action": "export", "scene": "dragon"}, {"exports/dragon.glb": make_glb()}),
                        ({"action": "bake", "scene": "dragon", "object": "Low"}, {})):
        s2 = FakeSession([{"status": "ok", "result": {"file": next(iter(files), ""), "maps": []}},
                          {"status": "ok", "result": {"saved_bytes": 1}}])
        c2, _, _ = client(tmp_path, launcher=FakeLauncher(files=files), session=s2)
        run(c2.call(bb.TOOL, call))
        assert len(s2.ensures) == 1, call
    shot = FakeSession([{"status": "ok", "result": {"crop": [0, 0, 10, 10], "meshes": 1}}])
    c3, _, _ = client(tmp_path, edit=False, launcher=FakeLauncher(files={"shots/view-front.png": PNG}), session=shot)
    run(c3.call(bb.TOOL, {"action": "screenshot", "angles": ["front"]}))
    assert shot.ensures == []          # no scene named: nothing to reopen


def test_lit_bake_combines_colour_ao_and_glow_under_a_white_sky():
    code = bb.fill(bb.BAKE, SCENE="dragon", OBJECT="Low", SOURCE="High", SIZE=1024, MAPS="lit", SAMPLES=32,
                   EXTRUSION=0.05, MARGIN=8)
    ast.parse(code)
    assert '"lit": ("COMBINED", "sRGB")' in code and "{'DIFFUSE', 'DIRECT', 'INDIRECT', 'COLOR', 'EMIT'}" in code
    assert "scene.world = sky" in code and "scene.world = old_world" in code
    assert "lit" in bb.BAKE_MAPS


def test_close_ups_look_at_a_chosen_point(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"file": "previews/dragon-az30_el10.png", "engine": "eevee", "size": [960, 540]}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/dragon-az30_el10.png": PNG}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "dragon", "engine": "eevee", "azimuth": 30,
                                 "elevation": 10, "zoom": 6, "center": [0, -3.1, 5.6]}))
    assert not reply["isError"], text(reply)
    code = session.calls[0][1]["code"]
    ast.parse(code)
    assert "if 1:   # look at a chosen point" in code and "mathutils.Vector((0.0, -3.1, 5.6))" in code
    shot = FakeSession([{"status": "ok", "result": {"crop": [0, 0, 10, 10], "meshes": 1}}])
    c2, _, _ = client(tmp_path, edit=False, launcher=FakeLauncher(files={"shots/view-front.png": PNG}), session=shot)
    run(c2.call(bb.TOOL, {"action": "screenshot", "angles": ["front"], "center": [1, 2, 3]}))
    assert "r3d.view_location = mathutils.Vector((1.0, 2.0, 3.0))" in shot.calls[0][1]["code"]
    for bad in ([1, 2], [1, 2, "3"], [1, 2, 1e9], "1,2,3"):
        assert run(c2.call(bb.TOOL, {"action": "screenshot", "center": bad}))["isError"]
    with pytest.raises(ValueError):
        bb._centre([True, 1, 2])


# --------------------------------------------------------------------------- dragon v4 lessons: square renders, form
# looks (clay / silhouette), sculpt strokes, memory in replies, line numbers in errors, no undo memory

def test_square_hero_preset_keeps_a_big_render_as_evidence_without_attaching_it(tmp_path):
    big = PNG[:16] + struct.pack(">II", 2048, 2048) + PNG[24:] + b"\0" * (bb.MAX_IMAGE + 10)
    session = FakeSession([{"status": "ok", "result": {"file": "previews/dragon-camera.png", "engine": "cycles", "size": [2048, 2048]}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/dragon-camera.png": big}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "dragon", "engine": "cycles", "camera": "scene",
                                 "preset": "square2k", "samples": 64, "denoise": True, "label": "hero"}))
    info = text(reply)
    assert not reply["isError"], info
    assert "w, h = 2048, 2048" in session.calls[0][1]["code"]
    note = info["previews"][0]
    assert note["size"] == [2048, 2048] and note["attached"] is False and note["bytes"] == len(big)
    assert not [b for b in reply["content"] if b["type"] == "image"]
    assert (tmp_path / note["evidence"]).read_bytes() == big
    assert bb.PRESETS["square1k"] == (1024, 1024)


@pytest.mark.parametrize("look", ["clay", "silhouette", "paint"])
def test_form_looks_render_through_workbench_and_restore_the_scene(tmp_path, look):
    session = FakeSession([{"status": "ok", "result": {"file": "previews/dragon-front.png", "engine": "workbench", "size": [640, 360]}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/dragon-front.png": PNG}), session=session)
    reply = run(c.call(bb.TOOL, {"action": "render_preview", "scene": "dragon", "engine": "cycles", "look": look,
                                 "angles": ["front"]}))
    assert not reply["isError"], text(reply)
    assert text(reply)["previews"][0]["look"] == look
    code = session.calls[0][1]["code"]
    ast.parse(code)
    assert f"look = {look!r}" in code and 'scene.render.engine = "BLENDER_WORKBENCH"' in code
    # everything the look changes is put back in `finally`, so the scene's own lighting design survives
    assert "for (part, key), value in kept.items():" in code and "setattr(owner, key, value)" in code
    assert "scene.world.color = (1.0, 1.0, 1.0)" in code and "shading.single_color = (0.0, 0.0, 0.0)" in code
    assert "shading.color_type = 'VERTEX' if look == \"paint\" else 'SINGLE'" in code


def test_sculpt_strokes_are_validated_filled_as_literals_and_saved(tmp_path):
    session = FakeSession([{"status": "ok", "result": {"object": "Hi_Head", "vertices": 900, "strokes": [{"brush": "crease", "vertices": 40}]}},
                           {"status": "ok", "result": {"saved_bytes": 77}}])
    c, _, _ = client(tmp_path, session=session)
    reply = run(c.call(bb.TOOL, {"action": "sculpt", "scene": "dragon", "object": "Hi_Head", "mirror_x": True,
                                 "strokes": [{"brush": "crease", "points": [[0.1, -3, 5.8], [0.3, -2.8, 5.9]],
                                              "radius": 0.05, "strength": 0.8}]}))
    info = text(reply)
    assert not reply["isError"], info
    code = session.calls[0][1]["code"]
    ast.parse(code)
    assert "obj = bpy.data.objects.get('Hi_Head')" in code and "if 1:   # symmetry" in code
    assert '"brush": "crease"' in code and '"radius": 0.05' in code   # one JSON string literal, parsed in Blender
    assert "save_as_mainfile" in session.calls[1][1]["code"]
    assert info["sculpt"]["strokes"][0]["vertices"] == 40 and info["scene_saved_bytes"] == 77


@pytest.mark.parametrize("bad", [
    {"action": "sculpt", "scene": "dragon", "object": "A"},                                              # no strokes
    {"action": "sculpt", "scene": "dragon", "strokes": [{"brush": "draw", "points": [[0, 0, 0]], "radius": 1}]},
    {"action": "sculpt", "scene": "dragon", "object": "A", "strokes": [{"brush": "dynamite", "points": [[0, 0, 0]], "radius": 1}]},
    {"action": "sculpt", "scene": "dragon", "object": "A", "strokes": [{"brush": "draw", "points": [[0, 0]], "radius": 1}]},
    {"action": "sculpt", "scene": "dragon", "object": "A", "strokes": [{"brush": "draw", "points": [[0, 0, 0]], "radius": 0}]},
    {"action": "sculpt", "scene": "dragon", "object": "A", "strokes": [{"brush": "draw", "points": [[0, 0, 0]], "radius": 1, "strength": 9}]},
    {"action": "sculpt", "scene": "dragon", "object": "A", "strokes": [{"brush": "draw", "points": [[0, 0, 0]] * 65, "radius": 1}]},
    {"action": "sculpt", "scene": "dragon", "object": "A", "strokes": [{"brush": "draw", "points": [[0, 0, 0]], "radius": 1, "code": "x"}]},
    {"action": "sculpt", "object": "A", "strokes": [{"brush": "draw", "points": [[0, 0, 0]], "radius": 1}]},  # no scene
    {"action": "sculpt", "scene": "dragon", "object": "A'); import os #", "strokes": [{"brush": "draw", "points": [[0, 0, 0]], "radius": 1}]},
])
def test_sculpt_refuses_bad_strokes_before_blender(tmp_path, bad):
    c, launcher, session = client(tmp_path)
    reply = run(c.call(bb.TOOL, bad))
    assert reply["isError"] and not session.calls and launcher.calls == []


def test_sculpt_needs_the_edit_permission(tmp_path):
    c, _, session = client(tmp_path, edit=False)
    reply = run(c.call(bb.TOOL, {"action": "sculpt", "scene": "dragon", "object": "A",
                                 "strokes": [{"brush": "smooth", "points": [[0, 0, 0]], "radius": 1}]}))
    assert reply["isError"] and "edit permission" in text(reply)["error"] and not session.calls


def test_heavy_actions_report_blenders_memory(tmp_path):
    class MemLauncher(FakeLauncher):
        async def __call__(self, argv, timeout):
            if argv[len(COMMAND):][0] == "status":
                self.calls.append(["status"])
                return 0, json.dumps({"running": True, "mcp_port_open": True, "blender_mb": 1834, "mem_max": "2560M"}).encode(), b""
            return await super().__call__(argv, timeout)
    session = FakeSession([{"status": "ok", "result": {"n": 1}}, {"status": "ok", "result": {"saved_bytes": 5}}])
    c, _, _ = client(tmp_path, launcher=MemLauncher(), session=session)
    info = text(run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "dragon", "code": "result = {'n': 1}"})))
    assert info["blender_mb"] == 1834 and info["blender_mem_max"] == "2560M"


def test_errors_name_the_failing_line_of_the_sent_code(tmp_path):
    message = ('Traceback (most recent call last):\n  File "/lab/mcp/x.py", line 88, in run\n'
               '  File "<string>", line 12, in <module>\n  File "<string>", line 7, in f\nZeroDivisionError: division by zero')
    session = FakeSession([{"status": "error", "message": message}])
    c, _, _ = client(tmp_path, session=session)
    reply = run(c.call(bb.TOOL, {"action": "run_bpy", "scene": "dragon", "code": "x = 1"}))
    assert reply["isError"]
    assert text(reply)["error"] == "Blender code failed (line 7 of the code): ZeroDivisionError: division by zero"
    assert "/lab/" not in text(reply)["error"]


def test_scene_check_turns_off_undo_memory():
    code = bb.fill(bb.ENSURE_SCENE, SCENE="dragon")
    ast.parse(code)
    assert "bpy.context.preferences.edit.undo_steps = 1" in code
    assert "bpy.context.preferences.edit.undo_memory_limit = 64" in code


def test_big_cycles_frames_skip_the_denoiser_and_say_so(tmp_path):
    code = bb.fill(bb.RENDER, W=2048, H=2048, AZ=0.0, EL=0.0, ZOOM=1.0, ENGINE="cycles", NAME="x", SAMPLES=64, DENOISE=1,
                   CAMERA="scene", LOOK="material", **bb._centre(None))
    ast.parse(code)
    assert "if engine == \"cycles\" and denoise and w * h > 1700000:" in code and "samples = max(samples, 128)" in code
    assert "scene.cycles.use_adaptive_sampling = True" in code
    session = FakeSession([{"status": "ok", "result": {"file": "previews/dragon-camera.png", "engine": "cycles",
                                                       "size": [2048, 2048], "denoise_skipped": True}}])
    c, _, _ = client(tmp_path, launcher=FakeLauncher(files={"previews/dragon-camera.png": PNG}), session=session)
    info = text(run(c.call(bb.TOOL, {"action": "render_preview", "scene": "dragon", "engine": "cycles", "camera": "scene",
                                      "preset": "square2k", "denoise": True})))
    assert "denoise skipped" in info["previews"][0]["note"]
