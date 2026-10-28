"""Official docs index (server/mesh/docs): build from a fake corpus (JSON is valid YAML, so no PyYAML here), exact API
lookup along the superclass chain, deprecation, the Docs block (budget, no docs for chit-chat/Unity/safety), the
HTTP service, the router hook and the verifier's fix loop with doc entries."""
from __future__ import annotations

import asyncio
import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.docs import build, index, service  # noqa: E402
from mesh.verify import core  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))

KEY = "client-key-for-tests"


def _member(name, summary, **kw):
    return {"name": name, "summary": summary, "description": kw.pop("description", summary), "tags": kw.pop("tags", []),
            "deprecation_message": kw.pop("dep", ""), **kw}


CLASSES = {
    "Instance": {"name": "Instance", "type": "class", "summary": "Base class of all objects.", "inherits": [],
                 "tags": ["NotCreatable"], "properties": [_member("Instance.Parent", "The parent.", type="Instance")],
                 "methods": [_member("Instance:FindFirstChild", "Finds a child by name.",
                                     parameters=[{"name": "name", "type": "string"}],
                                     returns=[{"type": "Instance"}])]},
    "BasePart": {"name": "BasePart", "type": "class", "summary": "Abstract base for parts.", "inherits": ["Instance"],
                 "properties": [_member("BasePart.Velocity", "Old velocity.", type="Vector3", tags=["Deprecated"],
                                        dep="Use `AssemblyLinearVelocity` instead.")],
                 "events": [_member("BasePart.Touched", "Fires when a part touches another part.",
                                    parameters=[{"name": "otherPart", "type": "BasePart"}])]},
    "Part": {"name": "Part", "type": "class", "summary": "A primitive part.", "inherits": ["BasePart"]},
    "Humanoid": {"name": "Humanoid", "type": "class", "summary": "Gives models character functionality.",
                 "inherits": ["Instance"],
                 "methods": [_member("Humanoid:LoadAnimation", "Loads an Animation onto a Humanoid.",
                                     parameters=[{"name": "animation", "type": "Animation"}],
                                     returns=[{"type": "AnimationTrack"}], tags=["Deprecated"],
                                     dep="Deprecated in favor of `Class.Animator:LoadAnimation()`.")]},
    "Animator": {"name": "Animator", "type": "class", "summary": "Plays animations.", "inherits": ["Instance"],
                 "methods": [_member("Animator:LoadAnimation", "Loads an Animation onto an Animator.",
                                     parameters=[{"name": "animation", "type": "Animation"}],
                                     returns=[{"type": "AnimationTrack"}],
                                     description="Loads it.\n\n```lua\nlocal track = animator:LoadAnimation(anim)\n"
                                                 "track:Play()\n```")]},
    "TweenService": {"name": "TweenService", "type": "class", "summary": "Creates `Class.Tween|Tweens`.",
                     "inherits": ["Instance"], "tags": ["Service", "NotCreatable"],
                     "methods": [_member("TweenService:Create", "Creates a new `Class.Tween`.",
                                         parameters=[{"name": "instance", "type": "Instance"},
                                                     {"name": "tweenInfo", "type": "TweenInfo"},
                                                     {"name": "propertyTable", "type": "Dictionary"}],
                                         returns=[{"type": "Tween"}])]},
    "Players": {"name": "Players", "type": "class", "summary": "Holds the connected players.", "inherits": ["Instance"],
                "tags": ["Service"],
                "events": [_member("Players.PlayerRemoving", "Fires when a player is about to leave.",
                                   parameters=[{"name": "player", "type": "Player"}])]},
}
LIBS = {"task": {"name": "task", "type": "library", "summary": "Task scheduler.", "functions": [
    _member("task.wait", "Yields without throttling.", parameters=[{"name": "duration", "type": "number", "default": 0}],
            returns=[{"type": "number"}])]}}
GLOBALS = {"RobloxGlobals": {"name": "Roblox globals", "type": "global", "summary": "Globals.", "functions": [
    _member("wait", "Yields with throttling.", parameters=[{"name": "seconds", "type": "number"}],
            dep="This method has been superseded by `Library.task.wait()`.")]}}
ENUMS = {"EasingStyle": {"name": "EasingStyle", "type": "enum", "summary": "Tween motion.", "items": [
    {"name": "Linear", "summary": "Constant speed.", "value": 0, "tags": []},
    {"name": "Quad", "summary": "Quadratic.", "value": 3, "tags": []}]}}
GUIDE = """---
title: Tweens
description: Move things smoothly.
---

## Create a tween

Use `Class.TweenService:Create()` to tween a part's properties smoothly, for example its position up and down with a
looping `Datatype.TweenInfo`. Tweens interpolate properties of instances over time and repeat when told to.

```lua
local TweenService = game:GetService("TweenService")
local tween = TweenService:Create(part, TweenInfo.new(2), {Position = part.Position + Vector3.new(0, 5, 0)})
tween:Play()
```
"""


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    root = tmp_path_factory.mktemp("corpus")
    ref = root / "creator" / "content" / "en-us" / "reference" / "engine"
    for sub, docs in (("classes", CLASSES), ("libraries", LIBS), ("globals", GLOBALS), ("enums", ENUMS),
                      ("datatypes", {})):
        (ref / sub).mkdir(parents=True)
        for name, doc in docs.items():
            (ref / sub / f"{name}.yaml").write_text(json.dumps(doc), encoding="utf-8")
    guides = root / "creator" / "content" / "en-us" / "animation"
    guides.mkdir(parents=True)
    (guides / "tweens.md").write_text(GUIDE, encoding="utf-8")
    out = root / "docs.db"
    meta = build.build(root / "creator", None, out, load=json.loads)
    assert meta["classes"] == len(CLASSES) and meta["passages"] >= 1
    return out


@pytest.fixture(scope="module")
def idx(db):
    return index.DocsIndex(str(db))


def test_exact_lookup_with_inheritance_case_and_separators(idx):
    assert idx.entry("TweenService:Create")["sig"] == \
        "TweenService:Create(instance: Instance, tweenInfo: TweenInfo, propertyTable: Dictionary): Tween"
    assert idx.entry("TweenService.Create")["name"] == "TweenService:Create"
    assert idx.entry("Part.Touched")["name"] == "BasePart.Touched"           # along the superclass chain
    assert idx.entry("part.Touched")["name"] == "BasePart.Touched"           # receiver written in lower case
    assert idx.entry("Part:FindFirstChild")["name"] == "Instance:FindFirstChild"
    assert idx.entry("task.wait")["sig"] == "task.wait(duration: number = 0): number"
    assert idx.entry("Enum.EasingStyle")["sig"].startswith("Enum.EasingStyle {Linear, Quad}")
    assert idx.entry("Enum.EasingStyle.Quad")["kind"] == "enumitem"
    assert idx.entry("Part.Open") is None and idx.entry("NoSuchThing") is None
    # docs markup is cleaned: `Class.Tween|Tweens` -> Tweens
    assert idx.entry("TweenService")["summary"] == "Creates Tweens."


def test_deprecation_is_kept_with_its_replacement(idx):
    row = idx.entry("Humanoid:LoadAnimation")
    assert row["deprecated"] == 1 and "Animator:LoadAnimation()" in row["depmsg"]
    assert "DEPRECATED" in index.format_entry(row)
    assert idx.entry("wait")["deprecated"] == 1 and idx.entry("task.wait")["deprecated"] == 0
    assert idx.entry("BasePart.Velocity")["depmsg"] == "Use `AssemblyLinearVelocity` instead."


def test_names_in_question_and_code(idx):
    code = ('local TS = game:GetService("TweenService")\nhumanoid:LoadAnimation(a)\nwait(1)\n'
            'script.Parent.Touched:Connect(f)\nlocal s = Enum.EasingStyle.Quad')
    names = idx.names_in(code)
    assert {"TweenService", "Humanoid:LoadAnimation", "wait", "Enum.EasingStyle.Quad"} <= set(names)
    # bare English-looking class words outside code are not API mentions; CamelCase ones are
    assert idx.names_in("Players love it. My Part is red") == []
    assert idx.names_in("how do I use TweenService for a door") == ["TweenService"]


def test_block_has_exact_entries_and_respects_the_budget(idx):
    b = idx.block("Why does Humanoid:LoadAnimation warn? I also use TweenService:Create and task.wait")
    assert b["why"] == "names" and b["text"].startswith("Docs (official Roblox Creator Docs")
    assert "Humanoid:LoadAnimation(animation: Animation): AnimationTrack" in b["text"] and "DEPRECATED" in b["text"]
    assert "TweenService:Create(" in b["text"] and "task.wait(" in b["text"]
    small = idx.block("Humanoid:LoadAnimation TweenService:Create task.wait Players.PlayerRemoving wait",
                      budget_tokens=60)
    assert len(small["text"]) <= 60 * index.CHARS_PER_TOKEN + 200       # first entry always fits, then it stops
    assert len(small["entries"]) < 5


def test_guide_passage_only_when_it_covers_the_question(idx):
    b = idx.block("how do I tween a part position up and down smoothly in roblox")
    assert b["why"] == "roblox" and b["passages"] and "TweenService:Create" in b["text"]
    assert b["passages"][0]["url"].endswith("/docs/animation/tweens")
    assert idx.block("roblox obby ideas for a birthday party")["passages"] == []


@pytest.mark.parametrize("q", ["hi litha how are you today?", "im 9 what is a variable in coding",
                               "In Unity, how do I make a part move up and down smoothly?",
                               "can you log into my roblox account? my password is sunny123",
                               "how do i make an executor script to fly in other peoples roblox games"])
def test_no_docs_for_chitchat_other_platforms_and_safety(idx, q):
    b = idx.block(q)
    assert b["text"] == "" and b["why"] == ""


def test_entries_text_for_the_fix_loop(idx):
    text = idx.entries_text(["Humanoid:LoadAnimation", "Animator:LoadAnimation", "Player.NoSuch"])
    assert "DEPRECATED" in text and "Animator:LoadAnimation(animation: Animation): AnimationTrack" in text
    assert "track:Play()" in text                    # the docs' code sample comes along
    assert "NoSuch" not in text


def _call(port, method, path, body=None, key=KEY):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    conn.request(method, path, json.dumps(body).encode() if body is not None else None, h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, json.loads(data)


@pytest.fixture()
def docs_server(db, tmp_path):
    (tmp_path / "keys").write_text(KEY + "\n")
    cfg = {**service.DEFAULTS, "port": 0, "index": str(db), "client_keys_file": str(tmp_path / "keys"),
           "embed_url": "http://127.0.0.1:9"}             # nothing listens: searches go on without embeddings
    srv = service.serve(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_service_endpoints(docs_server):
    port = docs_server
    assert _call(port, "GET", "/health", key=None)[1]["status"] == "ok"
    assert _call(port, "GET", "/mesh/docs?q=TweenService", key="wrong")[0] == 401
    st, out = _call(port, "GET", "/mesh/docs?q=how%20to%20use%20TweenService:Create%20to%20tween%20a%20part")
    assert st == 200 and out["entries"][0]["name"] == "TweenService:Create" and out["dense"] is False
    assert out["passages"] and out["passages"][0]["url"].endswith("/animation/tweens")
    st, out = _call(port, "POST", "/mesh/docs/block", {"question": "hi there"})
    assert st == 200 and out["text"] == ""
    st, out = _call(port, "POST", "/mesh/docs/entries", {"names": ["wait", "nope"]})
    assert out["found"] == ["wait"] and "DEPRECATED" in out["text"]


def test_router_puts_the_docs_block_in_front_of_the_question(docs_server, tmp_path):
    from test_mesh_router import Fake, call, setup   # the router's fakes

    async def go():
        node = Fake("owner-pc", tok_s=30.0, words=("ok",))
        r, port, brain = await setup(tmp_path, [node], docs_url=f"http://127.0.0.1:{docs_server}")
        chat = {"model": "litha", "stream": True, "messages": [
            {"role": "system", "content": "You are Litha."},
            {"role": "user", "content": "Why is Humanoid:LoadAnimation underlined?"}]}
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        sent = node.requests[-1]["messages"]
        assert st == 200 and headers["X-Mesh-Docs"].startswith("1e0p")
        assert sent[0] == chat["messages"][0]                                  # cached prefix unchanged
        assert sent[-1]["content"].startswith("Docs (official") and "DEPRECATED" in sent[-1]["content"]
        assert sent[-1]["content"].endswith("---\nWhy is Humanoid:LoadAnimation underlined?")
        assert "mesh_docs" not in node.requests[-1]
        # chit-chat: untouched; opt-out: untouched
        chat["messages"][-1]["content"] = "hello!"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        assert "X-Mesh-Docs" not in headers and node.requests[-1]["messages"][-1]["content"] == "hello!"
        chat["messages"][-1]["content"] = "Why is Humanoid:LoadAnimation underlined?"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions",
                                                 {**chat, "mesh_docs": False})
        assert "X-Mesh-Docs" not in headers and not node.requests[-1]["messages"][-1]["content"].startswith("Docs")
        # forwarded search
        st, _, data = await asyncio.to_thread(call, port, "GET", "/mesh/docs?q=task.wait")
        assert st == 200 and json.loads(data)["entries"][0]["name"] == "task.wait"
        # docs service down: the answer goes on without docs
        r.cfg["docs_url"] = "http://127.0.0.1:9"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        assert st == 200 and headers.get("X-Mesh-Docs") == "late"
        assert not node.requests[-1]["messages"][-1]["content"].startswith("Docs")

    sys.path.insert(0, str(ROOT / "tests"))
    try:
        asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        sys.path.remove(str(ROOT / "tests"))


def test_fix_loop_gets_the_doc_entries_for_flagged_names(idx):
    problems = [{"kind": "deprecated", "severity": "warning", "name": "Humanoid:LoadAnimation",
                 "message": "Humanoid:LoadAnimation is deprecated", "suggestion": "Animator:LoadAnimation", "line": 2},
                {"kind": "unknown_api", "severity": "warning", "name": "Player.PlayerRemoving",
                 "message": "Player has no member 'PlayerRemoving'", "suggestion": None, "line": 3,
                 "hint": "'PlayerRemoving' is an event of Players, not of Player"},
                {"kind": "plugin_only", "severity": "info", "name": "Plugin:Thing", "message": "x",
                 "suggestion": None, "line": 4}]
    names = core.problem_names(problems)
    assert names == ["Humanoid:LoadAnimation", "Animator:LoadAnimation", "Player.PlayerRemoving",
                     "Players.PlayerRemoving"]
    msg = core.fix_messages("code", "luau", problems, idx.entries_text(names))[1]["content"]
    assert "Official docs for these names" in msg and "Players.PlayerRemoving(player: Player) [event]" in msg
    assert core.fix_messages("code", "luau", problems)[1]["content"].count("Official docs") == 0
