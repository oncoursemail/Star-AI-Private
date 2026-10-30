"""STAR tool for 3D template assets (star/asset3d/tools.py) and the style packs (star/shapes/styles.py)."""
from __future__ import annotations

import json

import pytest

from star.asset3d import tools as T
from star.shapes import a3d, styles
from star.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return Workspace(root)


def test_style_from_brief():
    assert styles.style_from_brief("Roblox-ready low-poly sword") == "roblox"
    assert styles.style_from_brief("Low-poly deer with antlers") == "lowpoly"
    assert styles.style_from_brief("High-poly motorcycle with spoked wheels") == "highpoly"
    assert styles.style_from_brief("Stylized hand-painted war hammer") == "stylized"
    assert styles.style_from_brief("a red toolbox") == "pbr"
    assert styles.style_from_brief("a slowpoke statue") == "pbr"  # whole words only
    assert set(styles.STYLE_PACKS) == set(T.A.STYLES)


def test_definitions_are_gated(ws):
    off = T.Asset3DTools(ws, enabled=False, allow_write=True)
    assert off.definitions("make a 3D model of a fox") == []
    read_only = T.Asset3DTools(ws, enabled=True, allow_write=False)
    assert [t["name"] for t in read_only.definitions("make a 3D model of a fox")] == ["workspace_asset3d_check"]
    full = T.Asset3DTools(ws, enabled=True, allow_write=True)
    assert {t["name"] for t in full.definitions("low poly house please")} == T.TOOL_NAMES
    assert full.definitions("what's the weather") == []
    with pytest.raises(PermissionError):
        read_only.call("workspace_asset3d_build", {"output_dir": "a", "template": "barrel"},
                       enabled=T.TOOL_NAMES)
    with pytest.raises(PermissionError):
        full.call("workspace_asset3d_build", {"output_dir": "a", "template": "barrel"}, enabled=set())


def test_schema_rejects_unknown_fields_and_templates(ws):
    tools = T.Asset3DTools(ws, enabled=True, allow_write=True)
    for bad in ({"output_dir": "a", "template": "no_such"}, {"output_dir": "a", "template": "barrel", "code": "x"},
                {"output_dir": "a", "template": "barrel", "style": "photoreal"}):
        with pytest.raises(ValueError):
            tools.call("workspace_asset3d_build", bad, enabled=T.TOOL_NAMES)


def test_build_writes_a_valid_spec_offline(ws, monkeypatch):
    monkeypatch.delenv("STAR_ASSET3D_BUILD", raising=False)
    tools = T.Asset3DTools(ws, enabled=True, allow_write=True)
    res = tools.call("workspace_asset3d_build",
                     {"output_dir": "assets/fox", "template": "creature", "brief": "stylized cartoon fox",
                      "params": {"variant": "fox", "size": 99}, "colors": {"fur": "#d0702a"}},
                     enabled=T.TOOL_NAMES)
    assert res["built"] is False and "no Blender builder" in res["build_note"]
    assert res["style"] == "stylized" and res["category"] == "creature"
    assert any("size" in n for n in res["clamped"])
    spec = json.loads((ws.root / res["files"]["spec"]).read_text(encoding="utf-8"))
    assert spec["style"] == "stylized" and len(spec["parts"]) == res["parts"]
    assert "variant" in res["parameters"] and "fur" in res["colour_roles"]
    with pytest.raises(FileExistsError):
        tools.call("workspace_asset3d_build", {"output_dir": "assets/fox", "template": "creature"},
                   enabled=T.TOOL_NAMES)
    chk = tools.call("workspace_asset3d_check", {"path": res["files"]["spec"]}, enabled=T.TOOL_NAMES)
    assert chk["valid"] and chk["parts"] > 10 and not chk["notes"]


def test_build_runs_the_fixed_builder_only_when_configured(ws, monkeypatch):
    calls = []

    def fake_build(job, outdir, where):
        calls.append((job, where))
        return {"ok": False, "error": "no blender here"}
    monkeypatch.setenv("STAR_ASSET3D_BUILD", "remote")
    res = T.build(ws, {"output_dir": "b1", "template": "barrel", "style": "lowpoly"}, runner_build=fake_build)
    assert calls and calls[0][1] == "remote" and calls[0][0]["spec"]["style"] == "lowpoly"
    assert calls[0][0]["mode"] == "pipeline" and set(calls[0][0]) >= {"spec", "render", "final"}
    assert res["built"] is False and "no blender here" in res["build_note"]
    calls.clear()
    res = T.build(ws, {"output_dir": "b2", "template": "barrel", "render": False}, runner_build=fake_build)
    assert not calls and res["built"] is False
    monkeypatch.setenv("STAR_ASSET3D_BUILD", "anything-else")
    assert T.builder_mode() == "off"


def test_check_reports_invalid_specs(ws):
    (ws.root / "bad.json").write_text(json.dumps({"parts": [{"type": "teapot"}]}), encoding="utf-8")
    res = T.check(ws, "bad.json")
    assert res["valid"] is False and "type" in res["error"]
    (ws.root / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        T.check(ws, "notes.txt")


def test_every_template_is_offered():
    build = next(t for t in T.TOOLS if t["name"] == "workspace_asset3d_build")
    assert set(build["inputSchema"]["properties"]["template"]["enum"]) == set(a3d.TEMPLATES)
    assert {"humanoid", "creature", "building", "shelf", "blunt", "bike", "lantern"} <= set(a3d.TEMPLATES)


def _run_agent(responses, *, workspace, tools, prompt):
    import asyncio

    from star import agent
    from tests.test_debug_tools_integration import Client, Models
    models = Models(responses)
    result = asyncio.run(agent.execute(client=Client(models), model="offline", prompt=prompt, image_paths=[],
                                       workspace=workspace, asset3d_tools=tools, now=""))
    return result, models.requests


def test_agent_builds_through_the_registry(ws, monkeypatch):
    from tests.test_debug_tools_integration import call, offered, reply, tool_payloads
    monkeypatch.delenv("STAR_ASSET3D_BUILD", raising=False)
    args = {"output_dir": "house", "template": "building", "style": "lowpoly", "params": {"variant": "house"}}
    result, requests = _run_agent([reply(calls=[call("workspace_asset3d_build", args)]), reply(text="planned")],
                                  workspace=ws, tools=T.Asset3DTools(ws, enabled=True, allow_write=True),
                                  prompt="make a low poly 3D house model")
    assert result[0] == "planned" and T.TOOL_NAMES <= offered(requests[0])
    payload = tool_payloads(requests[1])[0]
    assert payload["isError"] is False and json.loads(payload["output"])["template"] == "building"
    assert (ws.root / "house" / "spec.json").is_file()
    # switched off: neither offered nor dispatched, nothing written
    _, requests = _run_agent([reply(calls=[call("workspace_asset3d_build", dict(args, output_dir="h2"))]),
                              reply(text="done")], workspace=ws, tools=None, prompt="make a low poly 3D house model")
    assert not T.TOOL_NAMES & offered(requests[0]) and not (ws.root / "h2").exists()


def test_failed_fill_still_builds_the_variant_the_brief_names():
    from star.shapes import core

    class Broken:
        def chat(self, messages, **kw):
            if "template" in messages[-1]["content"].lower() and len(messages[-1]["content"]) < 900:
                return '{"template": "firearm"}', 0.1, {}
            raise ValueError("unterminated JSON object in reply")
    pl = core.plan(Broken(), "Realistic stainless steel revolver with a long barrel", a3d.TEMPLATES, a3d.KINDS,
                   template="firearm")
    assert pl["params"]["variant"] == "revolver"
    assert core._variant_from_brief(a3d.TEMPLATES["firearm"], "a revolver", {"params": {"variant": "pistol"}}) \
        == {"params": {"variant": "pistol"}}
