"""Instant answers in the mesh router (server/mesh/instant.py + router.py): KV affinity, prefetch, verified cache."""
from __future__ import annotations

import asyncio
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))

from mesh import instant  # noqa: E402
from mesh import router as mesh  # noqa: E402
from test_mesh_router import KEY, Fake, call, run, sse_text  # noqa: E402

TOKEN = "mesh-token-for-tests"
SYSTEM = {"role": "system", "content": "You are Litha."}
DOOR = "In Roblox Studio, how do I make a door that opens when a player presses E near it?"
DOOR_ANSWER = "Use a **ProximityPrompt**.\n\n```lua\nlocal prompt = script.Parent.ProximityPrompt\n```"


class Aux:
    """Tiny JSON server: routes {path: fn(body) -> (status, obj)}; records the paths it saw (with query)."""

    def __init__(self, routes):
        self.routes, self.seen = routes, []

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        return self

    async def handle(self, reader, writer):
        line = await reader.readline()
        target = line.decode().split(" ")[1]
        headers = {}
        while (h := await reader.readline()) not in (b"\r\n", b""):
            k, _, v = h.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
        body = await reader.readexactly(int(headers.get("content-length", 0)))
        self.seen.append((target, headers.get("authorization", "")))
        status, obj = self.routes[target.split("?")[0]](json.loads(body or b"{}"))
        data = json.dumps(obj).encode()
        writer.write(f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n"
                     .encode() + data)
        await writer.drain()
        writer.close()


def verifier(body):
    text = body.get("answer") or ""
    return 200, {"ok": "BROKEN" not in text, "needs_fix": "BROKEN" in text, "blocks": []}


STOP = set("a an the in to i do how can my it of when on with for is near".split())


def bow(text: str) -> list[float]:
    """Deterministic fake embedding: hashed bag of words (stop words dropped)."""
    vec = [0.0] * 64
    for w in instant.normalize(text).split():
        if w not in STOP:
            vec[sum(map(ord, w)) % 64] += 1.0
    return vec


async def setup(tmp_path, nodes=(), cache=True, **cfg):
    brain = await Fake("brain", tok_s=10.0, words=("Brain", " here")).start()
    ver = await Aux({"/mesh/verify": verifier}).start()
    for n in nodes:
        await n.start()
    (tmp_path / "keys").write_text(f"{KEY}\n")
    (tmp_path / "token").write_text(f"{TOKEN}\n")
    conf = {**mesh.DEFAULTS, "listen": "127.0.0.1", "port": 0, "brain_url": brain.url, "verify_url": ver.url,
            "client_keys_file": str(tmp_path / "keys"), "mesh_token_file": str(tmp_path / "token"),
            "nodes": [{"name": n.name, "status_url": f"{n.url}/status"} for n in nodes],
            "cache_db": str(tmp_path / "answers.db") if cache else "", "cache_threshold": 0.8, **cfg}
    r = mesh.Router(conf)

    async def fake_embed(text):
        return bow(text)
    r.embed = fake_embed
    server = await r.serve()
    port = server.sockets[0].getsockname()[1]
    await asyncio.gather(r.poll_brain(), *(r.poll_node(n) for n in r.nodes))
    return r, port, brain, ver


def chat(content, conv=None, history=(), **extra):
    body = {"model": "litha", "stream": True, "messages": [SYSTEM, *history, {"role": "user", "content": content}],
            **extra}
    if conv:
        body["conversation_id"] = conv
    return body


async def post(port, path, body, key=KEY, headers=None):
    return await asyncio.to_thread(call, port, "POST", path, body, key, headers)


# ---- conversation keys -------------------------------------------------------------------------------------------------
def test_conversation_key_explicit_or_stable_hash():
    first = chat("how do loops work?")
    follow = chat("and while loops?", history=[{"role": "user", "content": "how do loops work?"},
                                               {"role": "assistant", "content": "A loop repeats..."}])
    k1, k2 = instant.conversation_key(first, {}), instant.conversation_key(follow, {})
    assert k1 == k2 and k1.startswith("h:")
    assert instant.conversation_key(chat("what is a table?"), {}) != k1
    assert instant.conversation_key({**first, "conversation_id": "abc"}, {}) == "id:abc"
    assert instant.conversation_key(first, {"x-conversation-id": "hdr"}) == "id:hdr"
    assert instant.conversation_key({"messages": [SYSTEM]}, {}) is None


# ---- affinity ----------------------------------------------------------------------------------------------------------
def test_follow_up_goes_back_to_the_node_holding_its_kv(tmp_path):
    async def go():
        a, b = Fake("node-a", tok_s=30.0, words=("A",)), Fake("node-b", tok_s=25.0, words=("B",))
        r, port, brain, _ = await setup(tmp_path, [a, b], cache=False)
        a.state = "busy"                                   # turn 1: node-a busy -> node-b serves it
        await r.poll_node(r.nodes[0])
        _, h, _ = await post(port, "/v1/chat/completions", chat("hi", conv="c1"))
        assert h["X-Mesh-Backend"] == "node-b"
        a.state = "idle"
        await r.poll_node(r.nodes[0])
        # follow-up of c1: node-b holds the KV (25 * 2 > 30) -> node-b; another conversation -> fastest node-a
        _, h, _ = await post(port, "/v1/chat/completions", chat("more", conv="c1"))
        assert h["X-Mesh-Backend"] == "node-b" and r.decisions[-1]["affinity"] == "node-b"
        assert "node-b 25.0 tok/s q0 (kv)" in r.decisions[-1]["reason"]
        _, h, _ = await post(port, "/v1/chat/completions", chat("hi", conv="c2"))
        assert h["X-Mesh-Backend"] == "node-a"
        # conversation_id is the router's field: never forwarded; cache_prompt is always on for litha
        assert all("conversation_id" not in q for q in a.requests + b.requests)
        assert all(q.get("cache_prompt") is True for q in a.requests + b.requests)
        # node-b busy now -> c1 moves on to node-a (affinity never sends to an unusable node)
        b.state = "busy"
        await r.poll_node(r.nodes[1])
        _, h, _ = await post(port, "/v1/chat/completions", chat("again", conv="c1"))
        assert h["X-Mesh-Backend"] == "node-a"
    run(go())


def test_affinity_bonus_does_not_keep_a_conversation_on_the_slow_brain():
    r = mesh.Router({**mesh.DEFAULTS, "nodes": [{"name": "gpu", "status_url": "http://x/status"}]})
    n = r.nodes[0]
    n.state, n.last_ok, n.tok_s = "idle", time.monotonic(), 44.0
    n.status = {"models": [{"id": "litha-fast", "url": "http://n/v1", "loaded": True}]}
    r.affinity.set("id:c", "brain1")                      # 10 * 2 = 20 < 44
    assert [b.name for b, _, _ in r.plan("litha", "id:c")[0]] == ["gpu", "brain1"]
    n.tok_s = 15.0                                        # 20 > 15: stay where the KV is
    assert [b.name for b, _, _ in r.plan("litha", "id:c")[0]] == ["brain1", "gpu"]


# ---- prefetch ----------------------------------------------------------------------------------------------------------
def test_prefetch_warms_the_serving_node_then_the_answer_follows_it(tmp_path):
    async def go():
        a, b = Fake("node-a", tok_s=30.0, words=("A",)), Fake("node-b", tok_s=25.0, words=("B",))
        r, port, brain, _ = await setup(tmp_path, [a, b], cache=False)
        status, _, data = await post(port, "/mesh/prefetch",
                                     {"model": "litha", "conversation_id": "c9", "wait": True,
                                      "messages": [SYSTEM, {"role": "user", "content": "how do I make a do"}],
                                      "chat_template_kwargs": {"enable_thinking": False}})
        out = json.loads(data)
        assert status == 200 and out["backend"] == "node-a"
        pre = a.requests[-1]
        assert pre["max_tokens"] == 0 and pre["cache_prompt"] is True and pre["stream"] is False
        assert pre["model"] == "litha-fast" and pre["chat_template_kwargs"] == {"enable_thinking": False}
        assert "conversation_id" not in pre and "wait" not in pre and not brain.requests
        r.nodes[1].tok_s = 40.0                            # node-b is faster now, but node-a holds the prompt
        _, h, _ = await post(port, "/v1/chat/completions", chat("how do I make a door?", conv="c9"))
        assert h["X-Mesh-Backend"] == "node-a"
    run(go())


def test_prefetch_is_debounced_and_latest_text_wins(tmp_path):
    async def go():
        a = Fake("node-a", tok_s=30.0)
        r, port, brain, _ = await setup(tmp_path, [a], cache=False, prefetch_debounce_s=0.3)
        codes = []
        for i in range(1, 7):                              # typing: 6 updates in ~0.1 s
            text = "how do I make a door"[: 3 * i]
            status, _, _ = await post(port, "/mesh/prefetch", {"conversation_id": "t", "messages": [
                SYSTEM, {"role": "user", "content": text}]})
            codes.append(status)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.8)
        assert set(codes) == {202}
        sent = [q for q in a.requests if q.get("max_tokens") == 0]
        assert 1 <= len(sent) <= 2                         # first at once, then one trailing with the newest text
        assert sent[-1]["messages"][-1]["content"] == "how do I make a door"[:18]
        assert r.counters["prefetch_debounced"] >= 4
    run(go())


def test_prefetch_never_loads_a_brain_model_and_skips_busy_backends(tmp_path):
    async def go():
        r, port, brain, _ = await setup(tmp_path, [], cache=False)
        body = {"conversation_id": "b", "wait": True, "messages": [SYSTEM, {"role": "user", "content": "hi"}]}
        r.brain_models = [{"id": "star-fast", "status": {"value": "unloaded"}}]
        r.brain_models_at = time.monotonic()
        out = json.loads((await post(port, "/mesh/prefetch", body))[2])
        assert out["backend"] == "brain1" and "not loaded" in out["skipped"] and not brain.requests
        r.brain_models = [{"id": "star-fast", "status": {"value": "loaded"}}]
        out = json.loads((await post(port, "/mesh/prefetch", {**body, "conversation_id": "b2"}))[2])
        assert out["backend"] == "brain1" and "skipped" not in out
        assert brain.requests[-1]["max_tokens"] == 0 and brain.auth[-1] == f"Bearer {KEY}"
        r.brain.inflight = 1                               # answering someone: do not queue a prefetch behind it
        out = json.loads((await post(port, "/mesh/prefetch", {**body, "conversation_id": "b3"}))[2])
        assert "busy" in out["skipped"]
        r.brain.inflight = 0
        assert (await post(port, "/mesh/prefetch", {**body, "model": "star-deep"}))[0] == 400
        assert (await post(port, "/mesh/prefetch", body, key=None))[0] == 401
    run(go())


# ---- verified answer cache ---------------------------------------------------------------------------------------------
async def add(port, key=TOKEN, **entry):
    e = {"question": DOOR, "answer": DOOR_ANSWER, "score": 3, "max_score": 3, "source": "test", **entry}
    status, _, data = await post(port, "/mesh/cache", e, key=key)
    return status, json.loads(data)


def test_cache_accepts_only_verified_full_mark_self_contained_answers(tmp_path):
    async def go():
        r, port, brain, ver = await setup(tmp_path, [])
        assert (await add(port, key=KEY))[0] == 401         # client keys cannot write the cache
        assert (await add(port, score=2))[0] == 422
        status, out = await add(port, answer="```lua\nBROKEN\n```")
        assert status == 422 and "verifier" in out["error"]["message"]
        status, out = await add(port, question="why does my script give an error: attempt to index nil")
        assert status == 422 and "not cacheable" in out["error"]["message"]
        status, out = await add(port)
        assert status == 200 and out["id"] == 1
        status, out = await add(port, answer=DOOR_ANSWER + "\nTip!")   # same question again: refresh in place
        assert out["id"] == 1 and r.cache.get(1)["answer"].endswith("Tip!")
        listing = json.loads((await asyncio.to_thread(call, port, "GET", "/mesh/cache"))[2])
        assert listing["stats"]["entries"] == 1 and "answer" not in listing["entries"][0]
        assert (await asyncio.to_thread(call, port, "DELETE", "/mesh/cache?id=1", None, KEY))[0] == 401
        assert (await asyncio.to_thread(call, port, "DELETE", "/mesh/cache?id=1", None, TOKEN))[0] == 200
        assert r.cache.stats()["entries"] == 0
    run(go())


def test_cache_hit_exact_and_semantic_streams_at_once_without_a_backend(tmp_path):
    async def go():
        node = Fake("node-a", tok_s=30.0, words=("live",))
        r, port, brain, _ = await setup(tmp_path, [node])
        await add(port)
        t0 = time.monotonic()
        status, h, data = await post(port, "/v1/chat/completions", chat(DOOR.lower().rstrip("?") + " !!"))
        assert status == 200 and h["X-Mesh-Cache"] == "hit" and h["X-Mesh-Cache-Match"] == "exact"
        assert h["X-Mesh-Backend"] == "cache" and sse_text(data) == DOOR_ANSWER
        assert data.rstrip().endswith(b"data: [DONE]") and time.monotonic() - t0 < 0.5
        para = "How can I make a door in Roblox Studio open when a player presses E near it"
        status, h, data = await post(port, "/v1/chat/completions", chat(para, stream=False))
        assert h["X-Mesh-Cache"] == "hit" and h["X-Mesh-Cache-Match"] == "semantic"
        assert json.loads(data)["choices"][0]["message"]["content"] == DOOR_ANSWER
        await asyncio.sleep(0.05)              # the backend started in parallel was cancelled by the hit
        assert r.nodes[0].inflight == 0 and not brain.requests and r.decisions[-1]["chosen"] == "cache"
        # same words, other platform: embeddings score it close, the platform guard keeps it a miss
        unity = "In Unity, how do I make a door that opens when a player presses E near it?"
        assert instant.cosine(bow(unity), bow(DOOR)) > 0.8
        _, h, _ = await post(port, "/v1/chat/completions", chat(unity))
        assert h["X-Mesh-Cache"] == "miss" and h["X-Mesh-Backend"] == "node-a"
        assert not instant.same_platform("how do I make a door open with E", "", DOOR)      # no platform named
        assert instant.same_platform("how do I make a door open with E", "roblox-studio", DOOR)  # page says it
        # a different question misses and is answered live (with the miss marked)
        status, h, data = await post(port, "/v1/chat/completions", chat("How do I save coins with a DataStore?"))
        assert h["X-Mesh-Cache"] == "miss" and h["X-Mesh-Backend"] == "node-a" and sse_text(data) == "live"
        assert float(h["X-Mesh-Cache-Similarity"]) < 0.8
        assert r.cache.get(1)["hits"] == 2 and r.counters["cache_miss"] == 2 and r.counters["cache_hit"] == 2
    run(go())


def test_slow_embedding_never_delays_a_live_answer(tmp_path):
    async def go():
        node = Fake("node-a", tok_s=30.0, words=("live",))
        r, port, brain, _ = await setup(tmp_path, [node])
        await add(port)

        async def slow_embed(text):
            await asyncio.sleep(1.0)
            return bow(text)
        r.embed = slow_embed
        t0 = time.monotonic()
        _, h, data = await post(port, "/v1/chat/completions", chat("How do I save coins with a DataStore?"))
        assert time.monotonic() - t0 < 0.6 and sse_text(data) == "live"
        assert h["X-Mesh-Cache"] == "miss" and h["X-Mesh-Cache-Ms"] == "late"
    run(go())


def test_cache_is_skipped_for_history_user_code_context_and_opt_out(tmp_path):
    async def go():
        node = Fake("node-a", tok_s=30.0, words=("live",))
        r, port, brain, _ = await setup(tmp_path, [node])
        await add(port)
        await add(port, question="How do I make a door open when touched?", context="unity",
                  answer="Use OnTriggerEnter.")
        hist = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "Hi!"}]
        cases = [
            (chat(DOOR, history=hist), "skip"),                                       # follow-up turn
            (chat(DOOR + "\n```lua\nlocal d = script.Parent\n```"), "skip"),           # the user's own code
            (chat("Why does my door script give an error?"), "skip"),                  # the user's error
            (chat(DOOR, mesh_cache=False), "off"),
            (chat("How do I make a door open when touched?", mesh_context="roblox"), "miss"),   # unity-only entry
        ]
        for body, want in cases:
            _, h, data = await post(port, "/v1/chat/completions", body)
            assert h["X-Mesh-Cache"] == want and h["X-Mesh-Backend"] == "node-a", (body, h)
        assert all("mesh_cache" not in q and "mesh_context" not in q for q in node.requests)
        _, h, data = await post(port, "/v1/chat/completions",
                                chat("How do I make a door open when touched?"), headers={"X-Mesh-Context": "unity"})
        assert h["X-Mesh-Cache"] == "hit" and sse_text(data) == "Use OnTriggerEnter."
    run(go())


def test_cache_expiry_and_background_reverify(tmp_path):
    async def go():
        r, port, brain, ver = await setup(tmp_path, [], cache_reverify_s=0.0)
        await add(port)
        r.cache.db.execute("UPDATE answers SET answer = answer || ' BROKEN'")   # the verifier would refuse it now
        _, h, _ = await post(port, "/v1/chat/completions", chat(DOOR))
        assert h["X-Mesh-Cache"] == "hit"
        await asyncio.sleep(0.2)                                                 # re-check failed -> dropped
        assert r.cache.stats()["entries"] == 0 and r.counters["cache_dropped_on_reverify"] == 1
        await add(port)
        r.cache.db.execute("UPDATE answers SET expires = 0")
        _, h, _ = await post(port, "/v1/chat/completions", chat(DOOR))
        assert h["X-Mesh-Cache"] == "miss" and h["X-Mesh-Backend"] == "brain1"
    run(go())


def test_cache_survives_a_restart(tmp_path):
    db = str(tmp_path / "a.db")
    c = instant.AnswerCache(db)
    c.put(DOOR, DOOR_ANSWER, "", "t", 1.0, bow(DOOR), 3600)
    c2 = instant.AnswerCache(db)
    row, sim = c2.nearest(bow(DOOR), "roblox")
    assert row["answer"] == DOOR_ANSWER and math.isclose(sim, 1.0, rel_tol=1e-6)


# ---- verify forwarding, real embed call, seeding -----------------------------------------------------------------------
def test_verify_is_forwarded_to_the_verifier_with_query_and_key(tmp_path):
    async def go():
        r, port, brain, ver = await setup(tmp_path, [], cache=False)
        status, _, data = await post(port, "/mesh/verify?fix=1", {"answer": "x"})
        assert status == 200 and json.loads(data)["ok"] is True
        assert ver.seen[-1] == ("/mesh/verify?fix=1", f"Bearer {KEY}")
        assert (await post(port, "/mesh/verify", {"answer": "x"}, key="wrong"))[0] == 401
        assert len(ver.seen) == 1
    run(go())


def test_embed_calls_the_brain_with_the_prefix(tmp_path):
    async def go():
        seen = []

        def emb(body):
            seen.append(body)
            return 200, {"data": [{"embedding": [0.5, 0.25]}]}
        brain = await Aux({"/v1/embeddings": emb}).start()
        (tmp_path / "keys").write_text(f"{KEY}\n")
        r = mesh.Router({**mesh.DEFAULTS, "brain_url": brain.url, "client_keys_file": str(tmp_path / "keys")})
        assert await r.embed("door") == [0.5, 0.25]
        assert seen[0] == {"model": "star-embed", "input": "task: sentence similarity | query: door"}
        r.cfg["brain_url"] = "http://127.0.0.1:9"
        assert await r.embed("door") is None and r.counters["embed_failed"] == 1
    run(go())


def test_seed_takes_only_full_mark_self_contained_eval_answers():
    base = ROOT.parent.parent / "docs" / "agents" / "litha-eval"
    if not (base / "questions.json").is_file():           # the eval lives in the workspace, outside the repo
        return
    entries = instant.seed_entries(str(base / "questions.json"), str(base / "answers-20261027"))
    ids = [e["source"].split(":")[-1] for e in entries]
    assert "luau-door" in ids and len(ids) == len(set(ids)) >= 8
    assert not any(re.match(r"safety-|.*-bug$", i) for i in ids)
    scores = json.loads((base / "answers-20261027" / "scores.json").read_text())["scores"]
    assert all(scores[e["source"].split(":")[2]][e["source"].split(":")[1]] == 3 for e in entries)
