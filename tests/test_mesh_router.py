"""STAR compute-mesh router (server/mesh/router.py) against fake GPU nodes and a fake brain on 127.0.0.1."""
from __future__ import annotations

import asyncio
import http.client
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh import router as mesh  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))

KEY = "client-key-for-tests"


class Fake:
    """A fake node (status on /status, llama-server-like chat on /v1/chat/completions) or a fake brain."""

    def __init__(self, name, state="idle", tok_s=30.0, loaded=True, first_delay=0.0, words=("Hi", " there", "!"),
                 die_before_token=False, die_after=None, http_status=200, end="finish", cut_body=False):
        self.name, self.state, self.tok_s, self.loaded = name, state, tok_s, loaded
        self.first_delay, self.words, self.die_before_token, self.die_after = first_delay, words, die_before_token, die_after
        self.http_status = http_status
        self.end, self.cut_body = end, cut_body        # end: finish | clean (no finish_reason) | error (error event)
        self.requests, self.auth, self.loads, self.cancelled = [], [], [], 0
        self.server, self.port = None, 0

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    async def handle(self, reader, writer):
        try:
            line = await reader.readline()
            method, path = line.decode().split(" ")[:2]
            headers = {}
            while (h := await reader.readline()) not in (b"\r\n", b""):
                k, _, v = h.decode().partition(":")
                headers[k.strip().lower()] = v.strip()
            body = await reader.readexactly(int(headers.get("content-length", 0)))
            if path == "/status":
                st = {"node": self.name, "state": self.state, "reason": "test",
                      "models": [{"id": "litha-fast", "url": f"{self.url}/v1", "loaded": self.loaded,
                                  "tok_s": self.tok_s}]}
                return await self.reply(writer, 200, json.dumps(st).encode())
            if path == "/load":
                self.loads.append(json.loads(body))
                return await self.reply(writer, 200, b"{}")
            if path == "/health":
                return await self.reply(writer, 200, b'{"status":"ok"}')
            if path == "/v1/models":
                return await self.reply(writer, 200, json.dumps({"data": [{"id": "star-fast"}, {"id": "star-deep"}]}).encode())
            if path == "/v1/embeddings":
                self.requests.append(json.loads(body))
                return await self.reply(writer, 200, b'{"data":[{"embedding":[0.1]}]}')
            req = json.loads(body)
            self.requests.append(req)
            self.auth.append(headers.get("authorization", ""))
            if self.http_status != 200:
                return await self.reply(writer, self.http_status, b'{"error":{"message":"nope"}}')
            if not req.get("stream"):
                await asyncio.sleep(self.first_delay)
                out = {"model": req["model"], "choices": [{"message": {"role": "assistant",
                                                                      "content": "".join(self.words)}}],
                       "timings": {"predicted_per_second": self.tok_s}}
                if self.cut_body:                      # killed while writing a non-stream answer
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
                                 + json.dumps(out).encode()[:20])
                    await writer.drain()
                    return
                return await self.reply(writer, 200, json.dumps(out).encode())
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
            await self.chunk(writer, {"choices": [{"delta": {"role": "assistant", "content": None}}]})
            await asyncio.sleep(self.first_delay)
            if self.die_before_token:
                writer.transport.abort()
                return
            for i, w in enumerate(self.words):
                if self.die_after is not None and i == self.die_after:
                    writer.transport.abort()
                    return
                await self.chunk(writer, {"model": req["model"], "choices": [{"delta": {"content": w}}]})
                await asyncio.sleep(0.01)
            if self.end == "error":
                await self.chunk(writer, {"error": {"message": "slot killed", "type": "server_error"}})
            elif self.end == "finish":
                await self.chunk(writer, {"choices": [{"delta": {}, "finish_reason": "stop"}],
                                          "timings": {"predicted_per_second": self.tok_s}})
                await self.chunk(writer, "[DONE]")
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            self.cancelled += 1
        finally:
            writer.close()

    async def chunk(self, writer, obj):
        data = b"data: " + (obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()) + b"\n\n"
        writer.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        await writer.drain()

    async def reply(self, writer, status, body):
        writer.write(f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                     f"\r\n".encode() + body)
        await writer.drain()


def call(port, method, path, body=None, key=KEY, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json", **(headers or {})}
    if key:
        h["Authorization"] = f"Bearer {key}"
    conn.request(method, path, json.dumps(body).encode() if body is not None else None, h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), data


def sse_text(data: bytes) -> str:
    out = []
    for line in data.decode().splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            obj = json.loads(line[6:])
            for c in obj.get("choices", []):
                out.append((c.get("delta") or {}).get("content") or "")
    return "".join(out)


async def setup(tmp_path, nodes=(), brain=None, **cfg):
    brain = await (brain or Fake("brain", tok_s=10.0, words=("Brain", " here"))).start()
    for n in nodes:
        await n.start()
    (tmp_path / "keys").write_text(f"# comment\n{KEY}\nsecond-key\n")
    (tmp_path / "token").write_text("mesh-token-for-tests\n")
    conf = {**mesh.DEFAULTS, "listen": "127.0.0.1", "port": 0, "brain_url": brain.url,
            "client_keys_file": str(tmp_path / "keys"), "mesh_token_file": str(tmp_path / "token"),
            "nodes": [{"name": n.name, "status_url": f"{n.url}/status"} for n in nodes], **cfg}
    r = mesh.Router(conf)
    server = await r.serve()
    port = server.sockets[0].getsockname()[1]
    await asyncio.gather(r.poll_brain(), *(r.poll_node(n) for n in r.nodes))
    return r, port, brain


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


CHAT = {"model": "litha", "stream": True, "messages": [{"role": "user", "content": "hi"}]}


def test_routes_litha_to_fastest_idle_node(tmp_path):
    async def go():
        slow, fast = Fake("laptop", tok_s=12.0, words=("slow",)), Fake("owner-pc", tok_s=31.0, words=("Fast", "!"))
        r, port, brain = await setup(tmp_path, [slow, fast])
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert status == 200 and headers["X-Mesh-Backend"] == "owner-pc"
        assert sse_text(data) == "Fast!" and data.rstrip().endswith(b"data: [DONE]")
        assert fast.requests[0]["model"] == "litha-fast" and fast.auth[0] == "Bearer mesh-token-for-tests"
        assert not slow.requests and not brain.requests
        d = r.decisions[-1]
        assert d["chosen"] == "owner-pc" and d["outcome"] == "ok" and d["tok_s"] == 31.0
    run(go())


def test_busy_and_unloaded_nodes_are_skipped_and_unloaded_one_is_warmed(tmp_path):
    async def go():
        busy = Fake("owner-pc", state="busy", tok_s=31.0)
        cold = Fake("laptop", loaded=False, tok_s=20.0)
        r, port, brain = await setup(tmp_path, [busy, cold])
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1" and sse_text(data) == "Brain here"
        assert brain.requests[0]["model"] == "star-fast" and brain.auth[0] == f"Bearer {KEY}"
        assert not busy.requests and not cold.requests
        await asyncio.sleep(0.05)
        assert cold.loads == [{"model": "litha-fast"}] and not busy.loads
        reason = r.decisions[-1]["reason"]
        assert "owner-pc: busy" in reason and "laptop: model not loaded" in reason
    run(go())


def test_unreachable_or_stale_node_falls_back_to_brain(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0)
        r, port, brain = await setup(tmp_path, [node])
        r.nodes[0].last_ok -= 60            # status is stale
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert headers["X-Mesh-Backend"] == "brain1" and "status stale" in r.decisions[-1]["reason"]
        node.server.close()
        await node.server.wait_closed()
        await r.poll_node(r.nodes[0])
        assert r.nodes[0].state == "off"
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert headers["X-Mesh-Backend"] == "brain1" and not node.requests
    run(go())


def test_failure_before_first_token_retries_next_backend(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, die_before_token=True)
        r, port, brain = await setup(tmp_path, [node])
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1" and sse_text(data) == "Brain here"
        assert len(node.requests) == 1 and r.decisions[-1]["errors"][0].startswith("owner-pc")
        assert r.node_usable(r.nodes[0], time.monotonic())[1].startswith("cooling down")
        node.http_status = 500                # an HTTP error from a node also moves on
        r.nodes[0].fail_until = 0
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert headers["X-Mesh-Backend"] == "brain1"
    run(go())


def test_mid_stream_drop_continues_on_next_backend_with_the_sent_words_as_prefix(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, words=("Hello", " wor", "ld", " again"), die_after=2)
        brain = Fake("brain", tok_s=10.0, words=(" world", " again", "."))
        r, port, brain = await setup(tmp_path, [node], brain=brain)
        body = {**CHAT, "max_tokens": 100}
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", body)
        assert headers["X-Mesh-Backend"] == "owner-pc"
        assert sse_text(data) == "Hello world again." and data.count(b"[DONE]") == 1 and b"error" not in data
        cont = brain.requests[0]
        assert cont["messages"][-1] == {"role": "assistant", "content": "Hello"}       # stops before the cut word
        assert cont["messages"][:-1] == CHAT["messages"] and cont["max_tokens"] == 98 and cont["stream"]
        d = r.decisions[-1]
        assert d["outcome"] == "cut, continued on brain1: ok" and d["continued_on"] == ["brain1"]
        assert d["cuts"][0]["backend"] == "owner-pc" and d["cuts"][0]["sent_chars"] == 9
        assert r.nodes[0].inflight == 0 and r.brain.inflight == 0 and r.nodes[0].fail_until > time.monotonic()
    run(go())


def test_stream_ending_without_finish_reason_or_with_an_error_event_is_a_cut(tmp_path):
    async def go():
        for end in ("clean", "error"):
            node = Fake("owner-pc", tok_s=31.0, words=("One", " two"), end=end)
            brain = Fake("brain", tok_s=10.0, words=(" two", " three"))
            r, port, brain = await setup(tmp_path, [node], brain=brain)
            status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
            assert sse_text(data) == "One two three" and b"slot killed" not in data, end
            assert brain.requests[0]["messages"][-1]["content"] == "One"
            assert r.decisions[-1]["outcome"].startswith("cut") and r.decisions[-1]["cuts"][0]["why"].startswith(
                "error event" if end == "error" else "stream ended without")
    run(go())


def test_cut_with_nobody_to_continue_sends_an_error_event_and_logs_cut(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, words=("a", " b", " c", " d"), die_after=2)
        brain = Fake("brain", tok_s=10.0, words=(" b", " c"), die_after=1)
        r, port, brain = await setup(tmp_path, [node], brain=brain)
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert sse_text(data) == "a b" and b"stopped in the middle" in data and data.rstrip().endswith(b"[DONE]")
        d = r.decisions[-1]
        assert d["outcome"].startswith("cut: brain1") and len(d["cuts"]) == 2
        assert r.nodes[0].inflight == 0 and r.brain.inflight == 0
    run(go())


def test_cut_before_any_word_is_a_plain_retry(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, words=("x",), die_after=0)
        r, port, brain = await setup(tmp_path, [node])
        body = {**CHAT, "max_tokens": 50}
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", body)
        assert sse_text(data) == "Brain here" and brain.requests[0]["messages"] == CHAT["messages"]
        assert brain.requests[0]["max_tokens"] == 50
    run(go())


def test_cut_non_stream_body_retries_next_backend(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, words=("partial",), cut_body=True)
        r, port, brain = await setup(tmp_path, [node])
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions",
                                                        {**CHAT, "stream": False})
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1"
        assert json.loads(data)["choices"][0]["message"]["content"] == "Brain here"
        assert "incomplete body" in r.decisions[-1]["errors"][0]
    run(go())


def test_prefix_split_and_tail_strip():
    assert mesh._split_prefix("1. Mercury\n2. Ve") == ("1. Mercury\n2.", " Ve")
    assert mesh._split_prefix("end)\n") == ("end)", "\n")
    assert mesh._split_prefix("Hi") == ("", "Hi")
    assert mesh._split_prefix("x" * 100) == ("x" * 100, "")
    assert mesh._strip_tail(" Venus", " Ve") == ("nus", "")
    assert mesh._strip_tail(" V", " Ve") == ("", "e")
    assert mesh._strip_tail("Mars", " Ve") == ("Mars", "")


def test_draining_node_is_skipped(tmp_path):
    async def go():
        node = Fake("owner-pc", state="draining", tok_s=31.0)
        r, port, brain = await setup(tmp_path, [node])
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert headers["X-Mesh-Backend"] == "brain1" and not node.requests
        assert "owner-pc: draining" in r.decisions[-1]["reason"]
    run(go())


def test_hedging_keeps_first_token_winner_and_cancels_other(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, first_delay=1.5, words=("node",))
        r, port, brain = await setup(tmp_path, [node])
        t0 = time.monotonic()
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT,
                                                        headers={"X-Mesh-Hedge": "1"})
        assert time.monotonic() - t0 < 1.2
        assert headers["X-Mesh-Backend"] == "brain1" and sse_text(data) == "Brain here"
        assert len(node.requests) == 1 and len(brain.requests) == 1
        await asyncio.sleep(1.7)
        assert node.cancelled == 1           # the node's stream was cut, so llama-server stops generating
        d = r.decisions[-1]
        assert d["hedge"] and d["cancelled"] == ["owner-pc"] and r.nodes[0].inflight == 0 and r.brain.inflight == 0
        # body flag works too and is not forwarded
        node.first_delay = 0
        await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", {**CHAT, "mesh_hedge": True})
        assert "mesh_hedge" not in node.requests[-1]
    run(go())


def test_streaming_passthrough_and_models(tmp_path):
    async def go():
        r, port, brain = await setup(tmp_path)
        body = {"model": "star-deep", "stream": True, "messages": []}
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", body)
        assert status == 200 and headers["Content-Type"] == "text/event-stream" and sse_text(data) == "Brain here"
        assert brain.requests[-1]["model"] == "star-deep"
        await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", {**body, "model": "litha-deep"})
        assert brain.requests[-1]["model"] == "star-deep"
        status, _, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions",
                                                  {**body, "stream": False, "model": "litha"})
        assert status == 200 and json.loads(data)["choices"][0]["message"]["content"] == "Brain here"
        status, _, data = await asyncio.to_thread(call, port, "POST", "/v1/embeddings", {"model": "star-embed",
                                                                                         "input": "x"})
        assert status == 200 and json.loads(data)["data"][0]["embedding"] == [0.1]
        status, _, data = await asyncio.to_thread(call, port, "GET", "/v1/models")
        ids = [m["id"] for m in json.loads(data)["data"]]
        assert ids == ["litha", "litha-deep", "star-fast", "star-deep"]
        status, _, data = await asyncio.to_thread(call, port, "GET", "/mesh/status")
        st = json.loads(data)
        assert st["brain"]["healthy"] is True and len(st["decisions"]) == 3 and st["decisions"][0]["model"] == "litha"
    run(go())


def test_litha_deep_thinks_on_an_idle_node_else_brain_star_deep(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=31.0, words=("Deep", "!"))
        r, port, brain = await setup(tmp_path, [node])
        deep = {**CHAT, "model": "litha-deep", "max_tokens": 1400, "chat_template_kwargs": {"enable_thinking": False}}
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", deep)
        assert status == 200 and headers["X-Mesh-Backend"] == "owner-pc" and sse_text(data) == "Deep!"
        sent = node.requests[-1]
        assert sent["model"] == "litha-fast" and sent["chat_template_kwargs"] == {"enable_thinking": True}
        assert sent["thinking_budget_tokens"] == 1500 and sent["max_tokens"] == 2900 and not brain.requests
        assert sent["reasoning_budget_message"].startswith(" Okay, I have thought enough")
        assert r.decisions[-1]["reason"] == "litha-deep -> owner-pc (thinking) > brain star-deep"
        # the node fails before its first token -> brain star-deep, without the node's thinking fields
        node.die_before_token = True
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", deep)
        assert headers["X-Mesh-Backend"] == "brain1" and sse_text(data) == "Brain here"
        assert brain.requests[-1]["model"] == "star-deep" and brain.requests[-1]["max_tokens"] == 1400
        assert "thinking_budget_tokens" not in brain.requests[-1]
        # node busy (owner gaming) -> straight to the brain, the reason says why
        node.die_before_token, node.state = False, "busy"
        await r.poll_node(r.nodes[0])
        r.nodes[0].fail_until = 0
        n = len(node.requests)
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", deep)
        assert headers["X-Mesh-Backend"] == "brain1" and len(node.requests) == n
        assert r.decisions[-1]["reason"].startswith("litha-deep -> brain star-deep (no usable node: owner-pc: busy")
        # thinking requests never touch the fast path's plain litha body
        node.state = "idle"
        await r.poll_node(r.nodes[0])
        await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert "chat_template_kwargs" not in node.requests[-1]
    run(go())


def test_auth_uses_brain_key_file(tmp_path):
    async def go():
        r, port, brain = await setup(tmp_path)
        assert (await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT, key=None))[0] == 401
        assert (await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT, key="wrong"))[0] == 401
        assert (await asyncio.to_thread(call, port, "GET", "/mesh/status", key="# comment"))[0] == 401
        assert (await asyncio.to_thread(call, port, "GET", "/mesh/status", key="second-key"))[0] == 200
        assert (await asyncio.to_thread(call, port, "GET", "/health", key=None))[0] == 200
        assert not brain.requests
        (tmp_path / "keys").write_text("rotated\n")         # re-read when the file changes
        import os
        os.utime(tmp_path / "keys", (time.time() + 5, time.time() + 5))
        assert (await asyncio.to_thread(call, port, "GET", "/mesh/status"))[0] == 401
        assert (await asyncio.to_thread(call, port, "GET", "/mesh/status", key="rotated"))[0] == 200
    run(go())


def test_queue_lowers_a_busy_nodes_rank():
    r = mesh.Router({**mesh.DEFAULTS, "nodes": [{"name": "a", "status_url": "http://x/status"},
                                                 {"name": "b", "status_url": "http://y/status"}]})
    for n, tok in zip(r.nodes, (30.0, 20.0)):
        n.state, n.last_ok, n.tok_s = "idle", time.monotonic(), tok
        n.status = {"models": [{"id": "litha-fast", "url": "http://n/v1", "loaded": True}]}
    assert [b.name for b, _, _ in r.plan("litha")[0]] == ["a", "b", "brain1"]
    r.nodes[0].inflight = 1                 # 30/2 = 15 < 20
    assert [b.name for b, _, _ in r.plan("litha")[0]] == ["b", "a", "brain1"]
    r.nodes[0].inflight, r.nodes[1].inflight = 3, 3   # 7.5 and 5 < brain 10
    assert [b.name for b, _, _ in r.plan("litha")[0]][0] == "brain1"


def test_self_registration_routes_expires_and_needs_mesh_token(tmp_path):
    async def go():
        node = Fake("star-pc", tok_s=40.0, words=("Reg", "!"))
        static = Fake("owner-pc", state="busy")
        await node.start()
        r, port, brain = await setup(tmp_path, [static], register_ttl_s=0.6)
        reg = {"node": "star-pc", "status_url": f"{node.url}/status"}
        # refused without / with a wrong token (a client key is not a mesh token either)
        for key in (None, KEY, "wrong"):
            assert (await asyncio.to_thread(call, port, "POST", "/mesh/register", reg, key=key))[0] == 401
        assert len(r.nodes) == 1
        status, _, data = await asyncio.to_thread(call, port, "POST", "/mesh/register", reg,
                                                  key="mesh-token-for-tests")
        out = json.loads(data)
        assert status == 200 and out["source"] == "registered" and out["status_url"] == f"{node.url}/status"
        await asyncio.sleep(0.1)                   # registration triggers an immediate poll
        status, headers, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert headers["X-Mesh-Backend"] == "star-pc" and sse_text(data) == "Reg!"
        assert node.auth[0] == "Bearer mesh-token-for-tests"
        st = json.loads((await asyncio.to_thread(call, port, "GET", "/mesh/status"))[2])
        src = {n["name"]: n["source"] for n in st["nodes"]}
        assert src == {"owner-pc": "static", "star-pc": "registered"}
        # a static node may register too (new URL while fresh, static again after expiry)
        await asyncio.to_thread(call, port, "POST", "/mesh/register",
                                {"node": "owner-pc", "status_url": f"{static.url}/status",
                                 "model_url": "http://127.0.0.1:9/v1"}, key="mesh-token-for-tests")
        assert r.nodes[0].source == "static+registered"
        # heartbeat stops -> the registered node is gone, the static one stays
        await asyncio.sleep(0.7)
        r.expire()
        assert [(n.name, n.source) for n in r.nodes] == [("owner-pc", "static")]
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", CHAT)
        assert headers["X-Mesh-Backend"] == "brain1"
    run(go())


def test_registration_fills_missing_or_loopback_addresses_from_source_ip():
    async def go():
        r = mesh.Router({**mesh.DEFAULTS})
        code, out = r.register({"node": "laptop"}, "192.0.2.7")
        assert code == 200 and out["status_url"] == "http://192.0.2.7:8099/status" and out["model_url"] == ""
        code, out = r.register({"node": "laptop", "model_url": "http://127.0.0.1:8098/v1"}, "192.0.2.7")
        assert out["model_url"] == "http://192.0.2.7:8098/v1"
        assert r.register({"node": "bad name!"}, "192.0.2.7")[0] == 400
        assert r.register({"node": "x", "status_url": "ftp://h/status"}, "192.0.2.7")[0] == 400
        n = r.nodes[0]                               # a loopback URL in the node's status is reached via its address
        n.status = {"models": [{"id": "litha-fast", "url": "http://127.0.0.1:8098/v1", "loaded": True}]}
        n.reg_model_url = None
        assert n.model(["litha-fast"])["url"] == "http://192.0.2.7:8098/v1"
        await asyncio.sleep(0)
    asyncio.run(go())
