"""ACP pilot adapter against a fake agent process (a simulation, not a real agent)."""
import asyncio
import sys
import textwrap

import pytest

from star.acp_adapter import AcpAdapter

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
    assert missing.probe()["installed"] is False
    assert run(missing.run_turn("hi")).state == "unavailable"
