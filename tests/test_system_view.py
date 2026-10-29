"""STAR reads her own system self-model: star/system_view.py (the star_system tool) against the real self-model
service with fake sources, the detector staying in agreement with the server's, and the agent wiring."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import system_view
from star.agent import execute

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.selfmodel import brief, service  # noqa: E402
sys.path.remove(str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
import test_self_model_service as sm  # noqa: E402
sys.path.remove(str(ROOT / "tests"))


def test_app_and_server_detectors_agree():
    for q in sm.SELF_QS + sm.NOT_SELF + ["what's your setup", "self-check please", "what changed in you lately?"]:
        assert system_view.wants_system(q) == brief.wants_self(q), q
    assert system_view.wants_system("how are you running right now?")
    assert not system_view.wants_system("make a day/night cycle script")


@pytest.fixture()
def selfsrv(tmp_path):
    (tmp_path / "keys").write_text(sm.KEY + "\n")
    (tmp_path / "token").write_text(sm.TOKEN + "\n")
    cfg = {**service.DEFAULTS, **sm.CFG, "port": 0, "client_keys_file": str(tmp_path / "keys"),
           "mesh_token_file": str(tmp_path / "token"), "state_dir": str(tmp_path / "state")}
    srv = service.serve(cfg, fetch=sm.fake_fetch([]), read_file=sm.read_file, start_collector=False)
    srv.self_model.refresh()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.stop_collector.set()


def test_read_topics_from_the_live_service(selfsrv):
    text = system_view.read("gpu", url=selfsrv, key=sm.KEY)
    assert "star-pc (NVIDIA GeForce RTX 4060): idle" in text and "owner-pc (NVIDIA GeForce RTX 3060 Ti): busy" in text
    sched = system_view.read("schedule", url=selfsrv, key=sm.KEY)
    assert sched.startswith("Free GPUs now: star-pc (NVIDIA GeForce RTX 4060, 680 MB free, serving Litha)")
    assert "Best for heavy work: star-pc" in sched
    with pytest.raises(OSError):
        system_view.read("gpu", url=selfsrv, key="wrong")


def test_heavy_work_slot(selfsrv, monkeypatch):
    real = system_view.fetch
    night = {"v": True}

    def fake(path, **kw):
        s = real(path, **kw)
        return {**s, "night": night["v"]} if path == "/mesh/self/schedule" else s
    monkeypatch.setattr(system_view, "fetch", fake)
    slot = system_view.heavy_work_slot(6000, url=selfsrv, key=sm.KEY)
    assert slot == {"where": "star-pc", "gpu": "NVIDIA GeForce RTX 4060", "vram_free_mb": 680, "must_unload_litha": True}
    night["v"] = False
    assert system_view.heavy_work_slot(6000, url=selfsrv, key=sm.KEY) is None          # daytime rule
    assert system_view.heavy_work_slot(6000, need_night=False, url=selfsrv, key=sm.KEY)["where"] == "star-pc"


def test_tool_result_errors_are_results(monkeypatch):
    monkeypatch.setenv("STAR_MESH_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(system_view, "_key", lambda: "k")
    out = asyncio.run(system_view.tool_result({"topic": "gpu"}))
    assert out["isError"] and "Self-model unavailable" in out["content"][0]["text"]
    assert asyncio.run(system_view.tool_result({"bad": 1}))["isError"]
    monkeypatch.delenv("STAR_MESH_URL")
    monkeypatch.setattr(system_view, "mesh_url", lambda: "")
    out = asyncio.run(system_view.tool_result({}))
    assert out["isError"]


class Models:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


def reply(content=None, calls=None):
    return SimpleNamespace(model="m", choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls), finish_reason="stop")])


def test_agent_offers_and_runs_star_system_only_for_self_questions(selfsrv, monkeypatch):
    monkeypatch.setenv("STAR_MESH_URL", selfsrv)
    monkeypatch.setattr(system_view, "_key", lambda: sm.KEY)
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="star_system", arguments=json.dumps({"topic": "gpu"})))

    async def run():
        models = Models(reply(None, [call]), reply("I'm on star-pc's RTX 4060."))
        client = SimpleNamespace(chat=SimpleNamespace(completions=models))
        events = []
        await execute(client=client, model="m", prompt="what GPU are you on right now?", image_paths=[], now="",
                      on_event=events.append)
        assert [t["function"]["name"] for t in models.requests[0]["tools"]] == ["star_system"]
        tool_message = [m for m in models.requests[1]["messages"] if m["role"] == "tool"][0]
        assert "star-pc (NVIDIA GeForce RTX 4060): idle" in tool_message["content"]
        assert {"event": "tool_finished", "tool": "star_system", "is_error": False} in events
        # an unrelated prompt gets no star_system tool
        models = Models(reply("Use a ParticleEmitter."))
        client = SimpleNamespace(chat=SimpleNamespace(completions=models))
        await execute(client=client, model="m", prompt="how do I use the GPU for particles in Roblox?", image_paths=[],
                      now="")
        assert "star_system" not in json.dumps(models.requests[0].get("tools") or [])
    asyncio.run(run())
