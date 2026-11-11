"""ACP pilot adapter against a fake agent process (a simulation, not a real agent)."""
import asyncio
import os
from pathlib import Path
import sys
import textwrap
import time

import pytest

from star.acp_adapter import AcpAdapter
from star.agent_session import UNMEASURED, AgentSessionAdapter, UsageReport

FAKE = textwrap.dedent('''
    import json, sys
    mode = sys.argv[1]
    def out(o):
        sys.stdout.write(json.dumps(o) + "\\n")
        sys.stdout.flush()
    def upd(x):
        out({"jsonrpc": "2.0", "method": "session/update",
             "params": {"sessionId": "s1", "update": x}})
    for line in sys.stdin:
        m = json.loads(line)
        meth, i = m.get("method"), m.get("id")
        if meth == "initialize":
            if mode == "auth":
                out({"jsonrpc": "2.0", "id": i, "error": {"code": -32000, "message": "login"}})
            else:
                out({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": 1}})
        elif meth == "session/new":
            out({"jsonrpc": "2.0", "id": i, "result": {"sessionId": "s1"}})
        elif meth == "session/prompt":
            if mode == "hang":
                continue
            upd({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hello "}})
            upd({"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "write f",
                 "kind": "edit", "status": "pending"})
            out({"jsonrpc": "2.0", "id": 99, "method": "session/request_permission",
                 "params": {"sessionId": "s1", "toolCall": {"toolCallId": "t1", "title": "write f"},
                            "options": [{"optionId": "a", "kind": "allow_once"},
                                        {"optionId": "r", "kind": "reject_once"}]}})
            r = json.loads(sys.stdin.readline())
            chosen = r["result"]["outcome"].get("optionId")
            upd({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "chose " + str(chosen)}})
            out({"jsonrpc": "2.0", "id": i, "result": {"stopReason": "end_turn"}})
''')


@pytest.fixture
def agent(tmp_path):
    p = tmp_path / "fake_agent.py"
    p.write_text(FAKE)
    return lambda mode="ok", **kw: AcpAdapter([sys.executable, str(p), mode], name="fake", **kw)


def run(coro):
    return asyncio.run(coro)


def test_off_by_default(agent):
    with pytest.raises(PermissionError):
        run(agent().run_turn("hi"))


def test_turn_rejects_permission_and_records_receipts(agent):
    t = run(agent(enabled=True).run_turn("hi"))
    assert t.state == "ok" and t.stop_reason == "end_turn"
    assert t.text == "hello chose r"
    assert t.tool_calls[0]["source"] == "agent_reported" and t.tool_calls[0]["title"] == "write f"
    assert t.permission_requests == ({"tool": "write f", "granted": False},)


def test_host_approval_is_explicit(agent):
    t = run(agent(enabled=True, approve=lambda p: True).run_turn("hi"))
    assert t.text.endswith("chose a") and t.permission_requests[0]["granted"] is True


def test_auth_required_timeout_and_missing(agent):
    assert run(agent("auth", enabled=True).run_turn("hi")).state == "auth_required"
    assert run(agent("hang", enabled=True, timeout=1.5).run_turn("hi")).state == "timeout"
    missing = AcpAdapter(["no-such-agent-binary-xyz"], enabled=True)
    assert missing.probe().installed is False
    assert run(missing.run_turn("hi")).state == "unavailable"


def test_adapter_meets_typed_contract_and_probe_guesses_nothing(agent):
    a = agent()
    assert isinstance(a, AgentSessionAdapter)
    p = a.probe()
    assert p.installed is True and p.enabled is False and p.state == "idle"
    assert p.auth == "unknown" and p.usage is UNMEASURED and p.usage.tier == "unknown"


def test_usage_comes_only_from_the_owner_authorized_probe(agent):
    measured = UsageReport(source="provider_api", models=("m1",), tier="free", billing="zero_spend",
                           measured_at=1_800_000_000.0, endpoint="models.list")
    assert agent(usage_probe=lambda: measured).probe().usage is measured

    def broken():
        raise OSError("offline")
    p = agent(usage_probe=broken).probe()
    assert p.usage is UNMEASURED and "OSError" in p.error
    p = agent(usage_probe=lambda: dict(tier="free")).probe()   # not a measured report: ignored
    assert p.usage is UNMEASURED and p.error


def test_start_stream_stop_keeps_one_session(agent):
    async def go():
        a = agent(enabled=True)
        with pytest.raises(RuntimeError):
            async for _ in a.stream("too early"):
                pass
        assert await a.start() == "ready" and a.auth == "ok"
        first = [e async for e in a.stream("one")]
        assert [e.kind for e in first] == ["text", "tool_call", "permission", "text", "end"]
        assert first[1].data["source"] == "agent_reported"
        assert first[2].data == {"tool": "write f", "granted": False}
        assert first[-1].data["state"] == "ok" and a.state == "ready"
        second = [e async for e in a.stream("two")]      # same process, second prompt
        assert second[-1].data["state"] == "ok" and a.last_turn.text == "hello chose r"
        await a.stop()
        assert a.state == "stopped" and a._proc is None
    run(go())


def test_cancel_reaches_a_silent_agent(agent):
    async def go():
        a = agent("hang", enabled=True, timeout=30)
        assert await a.start() == "ready"
        asyncio.get_running_loop().call_later(0.3, a.cancel)
        t0 = time.monotonic()
        events = [e async for e in a.stream("hi")]
        assert events[-1].data["state"] == "cancelled" and time.monotonic() - t0 < 10
        assert a.state == "ready"     # the session survives a cancelled turn
        await a.stop()
    run(go())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group state checks")
def test_run_turn_stops_descendant_processes_on_session_close(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "child_agent.py"
    script.write_text(textwrap.dedent("""
        import json, pathlib, subprocess, sys
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 60"])
        pathlib.Path(sys.argv[1]).write_text(str(child.pid))
        def out(obj):
            sys.stdout.write(json.dumps(obj) + "\\n")
            sys.stdout.flush()
        for line in sys.stdin:
            msg = json.loads(line)
            method, ident = msg.get("method"), msg.get("id")
            if method == "initialize":
                out({"jsonrpc": "2.0", "id": ident, "result": {"protocolVersion": 1}})
            elif method == "session/new":
                out({"jsonrpc": "2.0", "id": ident, "result": {"sessionId": "s1"}})
            elif method == "session/prompt":
                out({"jsonrpc": "2.0", "id": ident, "result": {"stopReason": "end_turn"}})
    """))
    adapter = AcpAdapter([sys.executable, str(script), str(pid_file)], enabled=True, timeout=5)
    turn = run(adapter.run_turn("hi"))
    assert turn.state == "ok" and pid_file.exists()
    child_pid = int(pid_file.read_text())
    end = time.monotonic() + 4
    while time.monotonic() < end:
        try:
            os.kill(child_pid, 0)
            stat = Path(f"/proc/{child_pid}/stat")
            if stat.exists() and stat.read_text().split()[2] == "Z":
                break
        except ProcessLookupError:
            break
        time.sleep(0.02)
    try:
        os.kill(child_pid, 0)
    except ProcessLookupError:
        return
    stat = Path(f"/proc/{child_pid}/stat")
    assert stat.exists() and stat.read_text().split()[2] == "Z"


def test_auth_and_approval_states_are_explicit(agent):
    async def go():
        a = agent("auth", enabled=True)
        assert await a.start() == "auth_required"
        assert a.auth == "auth_required" and a.probe().state == "auth_required" and a._proc is None
        assert await agent().request_tool_approval(dict()) is False                  # no callback
        assert await agent(approve=lambda p: "yes").request_tool_approval(dict()) is False   # not True

        def boom(p):
            raise ValueError
        assert await agent(approve=boom).request_tool_approval(dict()) is False
        assert await agent(approve=lambda p: True).request_tool_approval(dict()) is True
    run(go())
    with pytest.raises(PermissionError):
        run(agent().start())
