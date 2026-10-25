"""Offline evidence boundaries for STAR's operational self-model."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from star.self_model import SELF_TOOL, TurnSelfModel, wants_self_inspection


def attached(*names):
    return [{"type": "function", "function": {"name": name}} for name in names]


def test_prompt_gating_preserves_normal_chat():
    assert wants_self_inspection("Show me your capabilities")
    assert wants_self_inspection("What can you actually do?")
    assert wants_self_inspection("Explain STAR's self-awareness")
    assert wants_self_inspection("What are you working on?")
    assert not wants_self_inspection("Write a Roblox obby with good UI")
    assert not wants_self_inspection("Hi!")
    assert not wants_self_inspection(None)


def test_schema_is_read_only_and_does_not_accept_commands():
    assert SELF_TOOL["inputSchema"]["additionalProperties"] is False
    assert set(SELF_TOOL["inputSchema"]["properties"]) == {"tool_names"}
    assert "consciousness" in SELF_TOOL["description"]
    assert "permission" in SELF_TOOL["description"]


def test_truthful_attached_vs_unavailable_inventory():
    model = TurnSelfModel(attached("star_self_state", "workspace_read", "star_web_search"))
    state = model.inspect(["workspace_read", "workspace_write", "star_web_search"])
    assert state["kind"] == "operational_self_model_not_consciousness"
    assert state["tool_count"] == 3
    assert state["tools_omitted"] == 0
    assert state["requested_tools"] == [
        {"name": "workspace_read", "status": "attached_schema_only"},
        {"name": "workspace_write", "status": "not_attached_to_this_turn"},
        {"name": "star_web_search", "status": "attached_schema_only"},
    ]
    assert state["recent_tool_outcomes"] == []


def test_host_observed_tool_receipts_are_not_task_success_proof():
    model = TurnSelfModel(attached("star_self_state", "workspace_read"))
    model.record("workspace_read", executed=True, is_error=False)
    snapshot = model.inspect()
    assert snapshot["recent_tool_outcomes"] == [
        {"tool": "workspace_read", "attached": True, "status": "tool_returned_without_error"}
    ]
    assert "verify" in snapshot["suggested_next_check"].lower()
    assert any("not proof" in line for line in snapshot["limits"])


def test_uncertain_mutations_require_readback_not_blind_retry():
    model = TurnSelfModel(attached("workspace_write"))
    model.record("workspace_write", executed=True, is_error=True, uncertain=True)
    state = model.inspect()
    assert state["recent_tool_outcomes"][-1]["status"] == "outcome_uncertain"
    assert "read back" in state["suggested_next_check"].lower()


def test_rejected_and_failed_actions_not_misrepresented():
    model = TurnSelfModel(attached("star_self_state", "workspace_read"))
    model.record("workspace_write", executed=False, is_error=True)
    assert model.inspect()["recent_tool_outcomes"][-1] == {
        "tool": "workspace_write", "attached": False,
        "status": "rejected_before_execution",
    }
    model.record("workspace_read", executed=True, is_error=True)
    assert model.inspect()["recent_tool_outcomes"][-1]["status"] == "tool_reported_error"


def test_only_bounded_non_sensitive_outcomes_retained():
    model = TurnSelfModel(attached("workspace_read", "star_self_state"))
    for _ in range(18):
        model.record("workspace_read", executed=True, is_error=False)
    report = model.inspect()
    assert len(report["recent_tool_outcomes"]) == 12
    assert "token" not in json.dumps(report).lower()


@pytest.mark.parametrize("bad", [[], [{}], ["bad name"], ["workspace_read"] * 2, ["x"] * 13])
def test_invalid_requested_capabilities_are_rejected(bad):
    model = TurnSelfModel(attached("workspace_read"))
    if bad == []:
        assert model.inspect(bad)["requested_tools"] == []
    else:
        with pytest.raises((TypeError, ValueError)):
            model.inspect(bad)


def test_attached_output_is_bounded_with_explicit_omission_count():
    model = TurnSelfModel(attached(*["tool_" + str(i) for i in range(120)]))
    state = model.inspect()
    assert state["tool_count"] == 120
    assert len(state["attached_tools"]) == 72
    assert state["tools_omitted"] == 48


def reply(content="", calls=None):
    return SimpleNamespace(model="fixture-model", choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls))])


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


def tool_call(name, args):
    return SimpleNamespace(id="test-self-1", function=SimpleNamespace(
        name=name, arguments=json.dumps(args)))


def test_actual_agent_dispatch_self_inspection_is_read_only():
    from star.agent import execute

    completions = FakeCompletions([
        reply(calls=[tool_call("star_self_state", {
            "tool_names": ["star_self_state", "workspace_write"]})]),
        reply("Observed current tools; cannot confirm live services."),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    answer, messages, _archive = asyncio.run(execute(
        client=client, model="fixture", prompt="Show me your current capabilities",
        image_paths=[], max_calls=3, now="", today="2026-10-25",
    ))
    assert "cannot confirm" in answer
    offered = {tool["function"]["name"] for tool in completions.requests[0]["tools"]}
    assert offered == {"star_self_state"}
    tool_messages = [message for message in messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    receipt = json.loads(tool_messages[0]["content"])
    assert receipt["isError"] is False
    details = json.loads(receipt["output"])
    assert details["tool_count"] == 1
    assert details["requested_tools"][1]["status"] == "not_attached_to_this_turn"
    assert details["recent_tool_outcomes"] == []


def test_actual_agent_ordinary_turn_has_no_self_tool():
    from star.agent import execute

    completions = FakeCompletions([reply("Hello.")])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    answer, _messages, _archive = asyncio.run(execute(
        client=client, model="fixture", prompt="Hello!", image_paths=[],
        now="", today="2026-10-25",
    ))
    assert answer == "Hello."
    assert not completions.requests[0].get("tools")
