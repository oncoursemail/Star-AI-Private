"""Litha loop (server/mesh/loop): cheap signals, judge parsing, the hidden tool loop, and the router hook with a fake
2-slot node and a fake verifier on 127.0.0.1."""
from __future__ import annotations

import asyncio
import http.client
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh import router as mesh  # noqa: E402
from mesh.loop import checks, judge, patch, runner  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))

KEY = "client-key-for-tests"
GOOD = "Use a ProximityPrompt.\n\n```lua\nlocal p = script.Parent\np.Triggered:Connect(function(player)\n  print(player)\nend)\n```\n"
BAD = "Old way.\n\n```lua\nlocal p = script.Parent\nwait(1)\np.Triggered:connect(function(player)\n  print(player)\nend)\n```\n"


def problem(kind, severity, name, line, suggestion=None, **extra):
    return {"kind": kind, "severity": severity, "name": name, "message": f"{name} problem", "suggestion": suggestion,
            "line": line, **extra}


def fake_verify_report(text: str) -> dict:
    """Stands in for /mesh/verify: flags wait( and :connect( in Luau blocks."""
    blocks = []
    for k, b in enumerate(patch.blocks(text)):
        probs = []
        for i, ln in enumerate(b["code"].split("\n"), 1):
            if "wait(" in ln and "task.wait(" not in ln:
                probs.append(problem("deprecated", "warning", "wait", i, "task.wait"))
            if ":connect(" in ln:
                probs.append(problem("deprecated", "warning", "Triggered:connect", i, "Connect"))
            if "Explode" in ln:
                probs.append(problem("unknown_api", "error", "Part:Explode", i, None, candidates=["Destroy"]))
        blocks.append({"index": k, "language": "luau", "ok": not any(p["severity"] == "error" for p in probs),
                       "needs_fix": bool(probs), "problems": probs})
    return {"ok": all(b["ok"] for b in blocks), "needs_fix": any(b["needs_fix"] for b in blocks), "blocks": blocks,
            "problems": []}


# ---- cheap signals ---------------------------------------------------------------------------------------------------
def test_lint_flags_the_common_strict_failures():
    assert "localscript-never-runs" in checks.lint("Put this LocalScript inside the door part in Workspace.")
    assert "localscript-never-runs" not in checks.lint("Put this LocalScript in StarterPlayerScripts.")
    trust = ("```lua\nremote.OnServerEvent:Connect(function(player, amount)\n"
             "  player.leaderstats.Coins.Value = player.leaderstats.Coins.Value + amount\nend)\n```")
    assert "server-trusts-client-amount" in checks.lint(trust)
    safe = ("```lua\nremote.OnServerEvent:Connect(function(player)\n"
            "  player.leaderstats.Coins.Value = player.leaderstats.Coins.Value + 10\nend)\n```")
    assert "server-trusts-client-amount" not in checks.lint(safe)
    assert "touched-no-debounce" in checks.lint("part.Touched:Connect(function(hit) hit:BreakJoints() end)")
    assert "touched-no-debounce" not in checks.lint("local debounce = {}\npart.Touched:Connect(function(hit) end)")
    assert "unity-old-input-unsaid" in checks.lint("float x = Input.GetAxis(\"Horizontal\");")
    assert "unity-old-input-unsaid" not in checks.lint("Old Input Manager: Input.GetAxis(\"Horizontal\");")
    assert "datastore-http-myth" in checks.lint("Turn on Allow HTTP Requests for DataStores.")


def test_pick_compares_levels_in_order():
    a = checks.signals(GOOD, fake_verify_report(GOOD))
    b = checks.signals(BAD, fake_verify_report(BAD))
    assert checks.clean(a) and not checks.clean(b)
    assert checks.pick(a, b)[0] == "A" and checks.pick(b, a)[0] == "B"
    assert checks.pick(a, dict(a)) == (None, "tied on cheap signals")
    cut = checks.signals(GOOD[:-5], fake_verify_report(GOOD))     # closing fence lost: cut beats everything else
    assert cut["cut"] and checks.pick(cut, b)[0] == "B"
    assert checks.signals(GOOD, None, "length")["cut"]
    lint_only = checks.signals(GOOD + "\nAdd it as a LocalScript inside the part in Workspace.", fake_verify_report(GOOD))
    assert checks.pick(a, lint_only) == ("A", "lint 0 vs 1")


def judge_reply(p_bad: float) -> dict:
    lp = [{"token": "bad", "logprob": math.log(max(p_bad, 1e-9))},
          {"token": "ok", "logprob": math.log(max(1 - p_bad, 1e-9))}]
    return {"choices": [{"message": {"content": "bad" if p_bad > 0.5 else "ok"},
                         "logprobs": {"content": [{"token": "ok", "top_logprobs": lp}]}}]}


def test_judge_request_and_p_bad():
    body = judge.request("q?", "an answer")
    assert body["max_tokens"] == 1 and body["grammar"] == judge.GRAMMAR and body["logprobs"] is True
    assert "Question:\nq?" in body["messages"][1]["content"] and "Answer:\nan answer" in body["messages"][1]["content"]
    assert abs(judge.p_bad(judge_reply(0.8)) - 0.8) < 1e-6
    assert judge.p_bad({"choices": [{"message": {"content": "bad"}}]}) == 1.0     # no logprobs: the verdict
    assert judge.p_bad({"choices": [{"message": {"content": "ok"}}]}) == 0.0
    assert judge.p_bad({}) is None


# ---- tool loop -------------------------------------------------------------------------------------------------------
def test_exact_fix_rewrites_only_one_to_one_replacements():
    code = 'wait(1)\nPlayers.PlayerAdded:connect(f)\nprint(p.userId)\nf.Name = "Leaderstats"\ntask.wait(2)\n'
    probs = [problem("deprecated", "warning", "wait", 1, "task.wait"),
             problem("deprecated", "warning", "PlayerAdded:connect", 2, "Connect"),
             problem("deprecated", "warning", "Player.userId", 3, "Player.UserId"),
             problem("roblox_rule", "error", "Leaderstats", 4, '"leaderstats"'),
             problem("deprecated", "warning", "Humanoid:LoadAnimation", 5, "Animator:LoadAnimation")]
    out = patch.exact_fix(code, probs)
    assert out == 'task.wait(1)\nPlayers.PlayerAdded:Connect(f)\nprint(p.UserId)\nf.Name = "leaderstats"\ntask.wait(2)\n'


def test_apply_patch_keeps_indent_and_deletes():
    code = "local a = 1\nif a then\n  Part:Explode()\n  print(a)\nend"
    assert patch.apply_patch(code, "3: Part:Destroy()\n4:\n") == "local a = 1\nif a then\n  Part:Destroy()\nend"
    assert patch.apply_patch(code, "no lines here") == code
    assert patch.apply_patch(code, "```lua\n99: x\n```") == code


def arun(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def test_tool_loop_exact_then_model_with_budget():
    async def verify(text):
        return fake_verify_report(text)
    calls = []

    async def model(body):
        calls.append(body)
        return "3: Part:Destroy()"
    text = "x\n```lua\nwait(1)\nlocal Part = script.Parent\nPart:Explode()\n```\n"
    out, info = arun(patch.run(text, fake_verify_report(text), verify, model, 1.5))
    assert "task.wait(1)" in out and "Part:Destroy()" in out and info["exact"] == 1 and info["model"] == 1
    assert "real members: Destroy" in calls[0]["messages"][1]["content"]
    assert "  3: Part:Explode()" in calls[0]["messages"][1]["content"]

    async def slow(body):
        await asyncio.sleep(1)
        return "3: Part:Destroy()"
    out, info = arun(patch.run(text, fake_verify_report(text), verify, slow, 0.3))
    assert info["timeout"] and "task.wait(1)" in out and "Part:Explode()" in out   # exact part kept, model too slow

    async def worse(body):
        return "3: Part:Explode() wait(2)"
    out, info = arun(patch.run(text, fake_verify_report(text), verify, worse, 1.5))
    assert info["rejected"] == 1 and "Part:Explode()\n" in out


def test_tool_loop_leaves_clean_or_non_luau_answers_alone():
    async def verify(text):
        return fake_verify_report(text)

    async def model(body):
        raise AssertionError("no model call expected")
    out, info = arun(patch.run(GOOD, fake_verify_report(GOOD), verify, model))
    assert out == GOOD and info["exact"] == 0 and info["model"] == 0


def test_wanted_needs_opt_in_and_stream():
    assert runner.wanted({"mesh_loop": True, "stream": True}, {})
    assert not runner.wanted({"mesh_loop": True, "stream": False}, {})
    assert runner.wanted({"stream": True}, {"x-mesh-loop": "1"})
    req = {"mesh_loop": True, "stream": True}
    runner.wanted(req, {})
    assert "mesh_loop" not in req                     # never forwarded to a backend
    msgs = runner.careful_messages([{"role": "system", "content": "S"}, {"role": "user", "content": "q"}])
    assert msgs[0]["content"].startswith("S\n\nBefore you answer") and msgs[1] == {"role": "user", "content": "q"}


# ---- router hook ------------------------------------------------------------------------------------------------------
class Node:
    """Fake node: /status, a streamed answer (candidate A) and a non-stream answer (candidate B or a tool call)."""

    def __init__(self, a_text, b_text, b_delay=0.0, patch_reply="", name="owner-pc"):
        self.a_text, self.b_text, self.b_delay, self.patch_reply, self.name = a_text, b_text, b_delay, patch_reply, name
        self.requests, self.b_cancelled, self.judged = [], 0, []
        self.p_bad = lambda answer: 0.9 if "wait(1)" in answer else 0.1

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
                st = {"node": self.name, "state": "idle", "models": [{"id": "litha-fast", "url": f"{self.url}/v1",
                                                                     "loaded": True, "tok_s": 40.0}]}
                return await reply(writer, json.dumps(st).encode())
            if path in ("/health", "/v1/models"):
                return await reply(writer, b'{"status":"ok","data":[]}')
            req = json.loads(body)
            if req.get("grammar"):                     # the one-token judge: P(bad) set per answer text
                answer = req["messages"][1]["content"]
                self.judged.append(answer)
                return await reply(writer, json.dumps(judge_reply(self.p_bad(answer))).encode())
            self.requests.append(req)
            if not req.get("stream"):
                patching = "changed LINES" in req["messages"][0]["content"] or "changed lines" in req["messages"][0]["content"]
                if not patching:
                    try:
                        await asyncio.sleep(self.b_delay)
                    except asyncio.CancelledError:
                        raise
                text = self.patch_reply if patching else self.b_text
                out = {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
                return await reply(writer, json.dumps(out).encode())
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
            for i in range(0, len(self.a_text), 12):
                await chunk(writer, {"choices": [{"delta": {"content": self.a_text[i:i + 12]}}]})
            await chunk(writer, {"choices": [{"delta": {}, "finish_reason": "stop"}]})
            await chunk(writer, "[DONE]")
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            self.b_cancelled += 1
        finally:
            writer.close()


class Verifier:
    def __init__(self):
        self.calls = 0

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def handle(self, reader, writer):
        try:
            await reader.readline()
            headers = {}
            while (h := await reader.readline()) not in (b"\r\n", b""):
                k, _, v = h.decode().partition(":")
                headers[k.strip().lower()] = v.strip()
            body = json.loads(await reader.readexactly(int(headers.get("content-length", 0))))
            self.calls += 1
            await reply(writer, json.dumps(fake_verify_report(body["answer"])).encode())
        finally:
            writer.close()


async def chunk(writer, obj):
    data = b"data: " + (obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()) + b"\n\n"
    writer.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
    await writer.drain()


async def reply(writer, body, status=200):
    writer.write(f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode()
                 + body)
    await writer.drain()


def call(port, body, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    conn.request("POST", "/v1/chat/completions", json.dumps(body).encode(),
                 {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}", **(headers or {})})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return data


def events(data: bytes):
    out = []
    for line in data.decode().splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            out.append(json.loads(line[6:]))
    return out


def streamed_text(evs) -> str:
    return "".join((c.get("delta") or {}).get("content") or "" for e in evs for c in e.get("choices", []))


async def setup(tmp_path, node, **cfg):
    await node.start()
    ver = await Verifier().start()
    (tmp_path / "keys").write_text(f"{KEY}\n")
    (tmp_path / "token").write_text("mesh-token-for-tests\n")
    conf = {**mesh.DEFAULTS, "listen": "127.0.0.1", "port": 0, "brain_url": "http://127.0.0.1:9",
            "client_keys_file": str(tmp_path / "keys"), "mesh_token_file": str(tmp_path / "token"),
            "nodes": [{"name": node.name, "status_url": f"{node.url}/status"}],
            "verify_url": f"http://127.0.0.1:{ver.port}", "loop_best_of_nodes": [node.name], **cfg}
    r = mesh.Router(conf)
    server = await r.serve()
    await r.poll_node(r.nodes[0])
    return r, server.sockets[0].getsockname()[1], ver


CHAT = {"model": "litha", "stream": True, "mesh_loop": True,
        "messages": [{"role": "system", "content": "You are Litha."},
                     {"role": "user", "content": "roblox door that opens with a prompt"}]}


def test_router_swaps_in_b_when_a_fails_and_b_is_clean(tmp_path):
    async def go():
        node = Node(BAD, GOOD)
        r, port, ver = await setup(tmp_path, node)
        data = await asyncio.to_thread(call, port, CHAT)
        evs = events(data)
        assert streamed_text(evs) == BAD                       # A streamed as usual
        rep = [e for e in evs if e.get("object") == "mesh.replace"]
        assert len(rep) == 1 and rep[0]["mesh_replace"]["content"] == GOOD and rep[0]["mesh_replace"]["source"] == "B"
        assert data.rstrip().endswith(b"data: [DONE]")
        b_req = [q for q in node.requests if not q.get("stream")][0]
        assert "Before you answer" in b_req["messages"][0]["content"] and "mesh_loop" not in b_req
        assert all("mesh_loop" not in q for q in node.requests)
        log = r.decisions[-1]["loop"]
        assert log["result"].startswith("replaced: B") and r.nodes[0].inflight == 0
    arun(go())


def test_router_keeps_a_and_cancels_b_when_a_is_clean(tmp_path):
    async def go():
        node = Node(GOOD, BAD, b_delay=5.0)
        r, port, ver = await setup(tmp_path, node)
        data = await asyncio.to_thread(call, port, CHAT)
        evs = events(data)
        assert streamed_text(evs) == GOOD and not [e for e in evs if e.get("object") == "mesh.replace"]
        await asyncio.sleep(0.2)
        assert r.decisions[-1]["loop"]["result"] == "A kept (A clean and judged ok)" and r.nodes[0].inflight == 0
    arun(go())


def test_router_patches_a_when_b_is_also_bad(tmp_path):
    async def go():
        node = Node(BAD, BAD.replace("print(player)", "print(player.Name)"))
        r, port, ver = await setup(tmp_path, node)
        evs = events(await asyncio.to_thread(call, port, CHAT))
        rep = [e for e in evs if e.get("object") == "mesh.replace"]
        assert len(rep) == 1 and rep[0]["mesh_replace"]["source"] == "patch"
        fixed = rep[0]["mesh_replace"]["content"]
        assert "task.wait(1)" in fixed and ":Connect(" in fixed and rep[0]["mesh_replace"]["verify"]["warnings"] == 0
    arun(go())


def test_tool_loop_runs_without_a_second_slot_and_no_opt_in_means_no_loop(tmp_path):
    async def go():
        node = Node(BAD, GOOD)
        r, port, ver = await setup(tmp_path, node, loop_best_of_nodes=[])
        evs = events(await asyncio.to_thread(call, port, CHAT))
        rep = [e for e in evs if e.get("object") == "mesh.replace"]
        assert rep and rep[0]["mesh_replace"]["source"] == "patch"
        assert not [q for q in node.requests if not q.get("stream") and "Before you answer" in
                    q["messages"][0]["content"]]
        before = ver.calls
        plain = {k: v for k, v in CHAT.items() if k != "mesh_loop"}
        evs = events(await asyncio.to_thread(call, port, plain))
        assert streamed_text(evs) == BAD and not [e for e in evs if e.get("object") == "mesh.replace"]
        assert ver.calls == before and "loop" not in r.decisions[-1]
    arun(go())


def test_cheap_tie_goes_to_the_judge_with_a_margin(tmp_path):
    async def go():
        b_text = GOOD.replace("print(player)", "print(player.Name)")
        node = Node(GOOD, b_text)
        node.p_bad = lambda answer: 0.1 if "player.Name" in answer else 0.95
        r, port, ver = await setup(tmp_path, node)
        evs = events(await asyncio.to_thread(call, port, CHAT))
        rep = [e for e in evs if e.get("object") == "mesh.replace"]
        assert len(rep) == 1 and rep[0]["mesh_replace"]["content"] == b_text
        assert rep[0]["mesh_replace"]["why"].startswith("judge P(bad) A 0.95 vs B 0.10")
        assert any("roblox door" in j for j in node.judged)      # the judge sees the question

        node.p_bad = lambda answer: 0.3 if "player.Name" in answer else 0.6     # gap 0.3 < margin 0.5: A stays
        evs = events(await asyncio.to_thread(call, port, CHAT))
        assert not [e for e in evs if e.get("object") == "mesh.replace"]
        assert r.decisions[-1]["loop"]["result"].startswith("A kept (judge")
    arun(go())


def test_dot_method_calls_become_colon_calls_in_luau_only():
    text = "x\n```lua\nlocal music = workspace.Music\nmusic.Play()\nlocal t = task.wait(1)\nInstance.new(\"Part\")\n```\n"
    out = patch.dot_calls(text, fake_verify_report(text))
    assert "music:Play()" in out and "task.wait(1)" in out and 'Instance.new("Part")' in out

    async def verify(t):
        return fake_verify_report(t)

    async def model(body):
        raise AssertionError("no model call expected")
    fixed, info = arun(patch.run(text, fake_verify_report(text), verify, model))
    assert "music:Play()" in fixed and info["dot_calls"] == 1
    other = {"blocks": [{"index": 0, "language": "csharp", "problems": []}]}
    assert patch.dot_calls(text, other) == text
