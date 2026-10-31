"""Self-upgrade watcher (server/mesh/upgrade/watch.py): release parsing, weekly check decisions, the self-model's weekly
hook, and a whole night trial on a fake node (verified sandbox download, promote on a win, reject, rollback, gates)."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.upgrade import watch  # noqa: E402
from mesh.selfmodel import service  # noqa: E402
sys.path.remove(str(ROOT / "server"))

ASSET_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11976/llama-b11976-bin-win-cuda-12.4-x64.zip"


def zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("llama-server.exe", b"MZ fake new engine")
        z.writestr("ggml-cuda.dll", b"dll")
    return buf.getvalue()


ZIP = zip_bytes()
RELEASES = [
    {"tag_name": "b11976", "prerelease": True, "published_at": "2026-10-29T02:28:08Z", "assets": [
        {"name": "llama-b11976-bin-ubuntu-x64.tar.gz", "browser_download_url": "x", "digest": "sha256:" + "0" * 64},
        {"name": "llama-b11976-bin-win-cuda-12.4-x64.zip", "browser_download_url": ASSET_URL,
         "digest": "sha256:" + hashlib.sha256(ZIP).hexdigest(), "size": len(ZIP)}]},
    {"tag_name": "v0.8.0", "prerelease": False, "assets": [{"name": "nightly-tag.txt"}]},
    {"tag_name": "b11972", "prerelease": True, "assets": [
        {"name": "llama-b11972-bin-win-cuda-12.4-x64.zip", "browser_download_url": ASSET_URL, "digest": "sha256:" + "1" * 64}]},
]
FORGE = [{"tag_name": "v17.0.2", "prerelease": False}, {"tag_name": "v17.0.1", "prerelease": False}]


def get(url, timeout=20):
    if url == watch.LLAMA_API:
        return json.dumps(RELEASES).encode()
    if url == watch.FORGEJO_API:
        return json.dumps(FORGE).encode()
    if url.startswith(watch.HF_API):
        return json.dumps({"sha": "abc123def4567890", "lastModified": "2026-10-20"}).encode()
    raise OSError(url)


def test_release_parsing():
    best = watch.latest_llama(RELEASES)
    assert best["tag"] == "b11976" and best["build"] == 11976 and best["asset"]["url"] == ASSET_URL
    assert watch.build_of("version: 0.7.0-dev (build 11936, commit 27b7a8a00)") == 11936
    assert watch.latest_stable(FORGE) == "17.0.2" and watch.version_tuple("17.0.10") > watch.version_tuple("17.0.9")


def test_check_decisions():
    cfg = {"components": {"llama.cpp": {"current": "b11936", "trial_nodes": ["owner-pc"]}, "forgejo": {"current": "17.0.1"},
                          "models": {"org/model": "abc123def4567890", "org/other": "fff"}}}
    state = {}
    recs = {r["component"]: r for r in watch.check(cfg, state, get, now=1000.0)}
    assert recs["llama.cpp"]["decision"] == "trial" and "40 builds newer" in recs["llama.cpp"]["why"]
    assert recs["forgejo"]["decision"] == "available" and "by hand" in recs["forgejo"]["why"]
    assert recs["model org/model"]["decision"] == "none" and recs["model org/other"]["decision"] == "available"
    assert state["checked_at"] == 1000.0 and not watch.due(state, 1000.0 + 3600) and watch.due(state, 1000.0 + watch.WEEK_S)
    cfg["components"]["llama.cpp"] = {"current": "b11976"}
    assert watch.check(cfg, {}, get)[0]["decision"] == "none"
    cfg["components"]["llama.cpp"] = {"current": "b11900"}
    assert watch.check(cfg, {}, get)[0]["decision"] == "available"         # no trial node: report only


def test_self_model_runs_the_check_weekly(tmp_path):
    (tmp_path / "keys").write_text("k\n")
    cfg = {**service.DEFAULTS, "state_dir": str(tmp_path), "client_keys_file": str(tmp_path / "keys"),
           "mesh_token_file": str(tmp_path / "keys"),
           "upgrade": {"components": {"llama.cpp": {"current": "b11936"}, "forgejo": {"current": "17.0.1"}}}}
    m = service.SelfModel(cfg, service.KeyFile(str(tmp_path / "keys")))
    assert len(m.upgrade_check(get, now=1.8e9)) == 2
    assert m.upgrade_check(get, now=1.8e9 + 60) == []                      # not due again
    m.reports.add({"kind": "upgrade", "component": "llama.cpp", "decision": "promote", "latest": "b11976"})
    recs = m.upgrade_check(get, now=1.8e9 + watch.WEEK_S)
    assert recs[0]["current"] == "b11976" and recs[0]["decision"] == "none"   # a node's promotion counts
    assert m.reports.summary()["upgrade"][-1]["component"] == "forgejo"


def test_fetch_build_verifies_and_sandboxes(tmp_path):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "llama-server.exe").write_bytes(b"old")
    (engine_dir / "cudart64_12.dll").write_bytes(b"rt")
    latest = watch.latest_llama(RELEASES)
    exe = watch.fetch_build(tmp_path, latest, engine_dir / "llama-server.exe", download=lambda u, d: d.write_bytes(ZIP))
    assert exe == tmp_path / "upgrade" / "b11976" / "llama-server.exe" and exe.read_bytes() == b"MZ fake new engine"
    assert (exe.parent / "cudart64_12.dll").is_file() and not list(exe.parent.glob("*.zip"))
    bad = {**latest, "tag": "bX", "asset": {**latest["asset"], "digest": "sha256:" + "2" * 64}}
    with pytest.raises(ValueError, match="mismatch"):
        watch.fetch_build(tmp_path, bad, engine_dir / "llama-server.exe", download=lambda u, d: d.write_bytes(ZIP))
    with pytest.raises(ValueError, match="no sha256"):
        watch.fetch_build(tmp_path, {**latest, "asset": {**latest["asset"], "digest": None}}, engine_dir / "x.exe")
    with pytest.raises(ValueError, match="unexpected download URL"):
        watch.fetch_build(tmp_path, {**latest, "asset": {**latest["asset"], "url": "https://evil.example/x.zip"}},
                          engine_dir / "x.exe")


sys.path.insert(0, str(ROOT / "tests"))
import test_autotune as ta  # noqa: E402
sys.path.remove(str(ROOT / "tests"))


@pytest.fixture()
def home(tmp_path):
    for f in ("autotune/autotune.py", "upgrade/watch.py", "node/node_agent.py"):
        shutil.copy(ROOT / "server" / "mesh" / f, tmp_path / Path(f).name)
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "llama-server.exe").write_bytes(b"old")
    cfg = {**ta.NODE, "node": "test-pc", "llama_server": "engine/llama-server.exe", "resume_seconds": 0,
           "upgrade": {"trial_enabled": True, "load_timeout_s": 0.05}}
    (tmp_path / "node.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (tmp_path / "logs").mkdir()
    return tmp_path


class EngineByExe(ta.FakeEngine):
    def __init__(self, new_speed, new_quality_bad=False):
        super().__init__()
        self.new_speed, self.new_bad = new_speed, new_quality_bad

    def chat(self, prompt, max_tokens):
        text, tps = ta.FakeEngine.chat(self, prompt, max_tokens)
        if "upgrade" in str(self.cfg.get("llama_server")):
            if self.new_bad and prompt == ta.at.EVAL[0][0]:
                text = "390"
            return text, self.new_speed
        return text, 45.0


def _trial(home, engine, node, **kw):
    return watch.trial(home, now=True, get=get, download=lambda u, d: d.write_bytes(ZIP), engine=engine,
                       status=node.status, restart=node.restart, sleep=lambda s: None, current_build=11936, **kw)


def test_trial_promotes_a_faster_build(home):
    node = ta.FakeNode(home)
    rec = _trial(home, EngineByExe(50.0), node)
    assert rec["decision"] == "promote" and rec["latest"] == "b11976" and rec["current"] == "b11936"
    cfg = json.loads((home / "node.json").read_text())
    assert cfg["llama_server"].endswith(str(Path("upgrade/b11976/llama-server.exe"))) and node.restarted == 1
    assert not (home / "OFF").exists()


def test_trial_rejects_slower_or_worse(home):
    before = (home / "node.json").read_text()
    assert _trial(home, EngineByExe(44.0), ta.FakeNode(home))["decision"] == "reject"
    rec = _trial(home, EngineByExe(60.0, new_quality_bad=True), ta.FakeNode(home))
    assert rec["decision"] == "reject" and "quality 9 < 10" in rec["why"]
    assert (home / "node.json").read_text() == before


def test_trial_rolls_back_and_gates(home):
    before = (home / "node.json").read_text()
    rec = _trial(home, EngineByExe(50.0), ta.FakeNode(home, after_restart=("away", False, None)))
    assert rec["decision"] == "rollback" and (home / "node.json").read_text() == before
    assert watch.trial(home, now=True, get=get, current_build=11976, status=ta.FakeNode(home).status)["decision"] == "none"
    cfg = json.loads(before)
    cfg["upgrade"]["trial_enabled"] = False
    (home / "node.json").write_text(json.dumps(cfg))
    assert watch.trial(home, now=True, get=get)["decision"] == "skip"
