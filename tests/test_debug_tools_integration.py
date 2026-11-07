"""Exercise opt-in tools through STAR's real agent and desktop Settings boundary."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from star import agent, desktop_core as core
from star.debug_common import SCHEMA, write_report
from star.debug_evidence import DebugEvidenceTools, TOOL_NAMES
from star.react_shell import apply_setting_changes
from star.turn_memory import TurnMemory
from star.workspace import Workspace


def reply(*, text=None, calls=None):
    return SimpleNamespace(model="offline", choices=[SimpleNamespace(
        message=SimpleNamespace(content=text, tool_calls=calls),
        finish_reason="tool_calls" if calls else "stop")])


def call(name, args, identifier="call_1"):
    return SimpleNamespace(id=identifier, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class Models:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        return self.responses.pop(0) if self.responses else reply(text="done")


class Client:
    def __init__(self, models):
        self.chat = SimpleNamespace(completions=models)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    write_report(root / "failure.json", {
        "schema": SCHEMA, "producer": "pytest", "run_id": "synthetic-failed-run", "status": "failed",
        "exit_code": 1, "truncated": False,
        "tests": [{"nodeid": "test_app.py::test_value", "file": "test_app.py", "outcome": "failed"}],
        "failures": [{"file": "app.py", "line": 2, "exception_type": "AssertionError",
                      "message": "Expected 3, observed 2. password=tiny"}],
    })
    return Workspace(root)


def run_agent(responses, *, workspace=None, tools=None, prompt="Debug the failing test", **kwargs):
    models = Models(responses)
    result = asyncio.run(agent.execute(client=Client(models), model="offline", prompt=prompt,
                                      image_paths=[], workspace=workspace, debug_evidence=tools,
                                      now="", **kwargs))
    return result, models.requests


def offered(request):
    return {item["function"]["name"] for item in request.get("tools", [])}


def tool_payloads(request):
    return [json.loads(item["content"]) for item in request["messages"] if item["role"] == "tool"]


def test_actual_agent_reads_grouped_evidence_and_receives_redacted_source(workspace):
    tools = DebugEvidenceTools(workspace, enabled=True)
    result, requests = run_agent([
        reply(calls=[call("star_debug_report", {"path": "failure.json"})]),
        reply(text="The reported return value is 2; reproduce the expectation before editing."),
    ], workspace=workspace, tools=tools)
    assert "reported return value" in result[0]
    assert TOOL_NAMES <= offered(requests[0])
    output = tool_payloads(requests[1])[0]
    assert output["isError"] is False
    evidence = json.loads(output["output"])
    assert evidence["failing_test_count"] == 1 and evidence["verified_fix"] is False
    assert evidence["failure_groups"][0]["source"]["lines"][-1]["text"] == "    return 2"
    assert "tiny" not in json.dumps(requests)
    assert not {"star_debug_execute", "star_debug_attach", "star_debug_evaluate"} & offered(requests[0])


@pytest.mark.parametrize("enabled", [None, False])
def test_disabled_tool_calls_are_rejected_before_dispatch(workspace, enabled):
    tools = None if enabled is None else DebugEvidenceTools(workspace, enabled=enabled)
    _, requests = run_agent([
        reply(calls=[call("star_debug_report", {"path": "failure.json"})]), reply(text="done"),
    ], workspace=workspace, tools=tools)
    assert not TOOL_NAMES & offered(requests[0])
    assert "rejected" in json.dumps(tool_payloads(requests[-1]))
    assert "Expected 3" not in json.dumps(requests)


def test_unrelated_prompt_does_not_offer_or_dispatch_debugger(workspace):
    _, requests = run_agent([
        reply(calls=[call("star_debug_source", {"path": "app.py", "line": 2})]), reply(text="done"),
    ], workspace=workspace, tools=DebugEvidenceTools(workspace, enabled=True), prompt="Hello there")
    assert not TOOL_NAMES & offered(requests[0])
    assert "rejected" in json.dumps(tool_payloads(requests[-1]))


def test_bad_tool_argument_cannot_add_an_execution_operation(workspace):
    _, requests = run_agent([
        reply(calls=[call("star_debug_report", {"path": "failure.json", "command": "run code"})]),
        reply(text="done"),
    ], workspace=workspace, tools=DebugEvidenceTools(workspace, enabled=True))
    assert tool_payloads(requests[-1])[0]["isError"] is True
    assert "Expected 3" not in json.dumps(requests)


def test_bad_path_errors_do_not_echo_untrusted_exception_text(workspace):
    _, requests = run_agent([
        reply(calls=[call("star_debug_report", {"path": "../credentials.json"})]), reply(text="done"),
    ], workspace=workspace, tools=DebugEvidenceTools(workspace, enabled=True))
    output = tool_payloads(requests[-1])[0]
    assert output["isError"] is True
    assert output["output"] in {"Debug evidence unavailable: PermissionError", "Debug evidence unavailable: FileNotFoundError"}
    assert "credentials" not in output["output"]


def test_sticky_tools_drop_immediately_when_owner_switches_off(workspace):
    memory = TurnMemory(sticky=True)
    tools = DebugEvidenceTools(workspace, enabled=True)
    _, first = run_agent([reply(text="done")], workspace=workspace, tools=tools, tool_memory=memory)
    assert TOOL_NAMES <= offered(first[0])
    _, followup = run_agent([reply(text="done")], workspace=workspace, tools=tools,
                           prompt="Continue", tool_memory=memory)
    assert TOOL_NAMES <= offered(followup[0])
    tools.enabled = False
    _, off = run_agent([reply(text="done")], workspace=workspace, tools=tools,
                      prompt="Continue", tool_memory=memory)
    assert not TOOL_NAMES & offered(off[0])


def test_report_text_cannot_reenable_full_luau_execution(workspace):
    from tests.test_luau_after_untrusted import LUAU_ARGS, LUAU_TOOL, Studio
    studio = Studio()
    _, requests = run_agent([
        reply(calls=[call("star_debug_report", {"path": "failure.json"})]),
        reply(calls=[call("execute_luau", LUAU_ARGS, "call_2")]), reply(text="done"),
    ], workspace=workspace, tools=DebugEvidenceTools(workspace, enabled=True),
        studio=studio, discovered=[LUAU_TOOL], studio_id="s1", may_edit=True, allow_luau=True)
    assert studio.calls == []
    assert "rejected" in json.dumps(tool_payloads(requests[-1])[-1])


def test_setting_defaults_false_round_trips_and_rejects_non_boolean(tmp_path):
    file = tmp_path / "settings.json"
    assert core.Settings.load(file).debug_evidence_enabled is False
    settings = apply_setting_changes(core.Settings(), {"debug_evidence_enabled": True})
    assert settings.debug_evidence_enabled is True
    settings.save(file)
    assert core.Settings.load(file).debug_evidence_enabled is True
    for invalid in (1, "true", None):
        with pytest.raises(ValueError):
            apply_setting_changes(core.Settings(), {"debug_evidence_enabled": invalid}).save(file)


@pytest.mark.parametrize(("enabled", "has_workspace", "expected"), [
    (False, True, False), (True, False, False), (True, True, True),
])
def test_desktop_agent_route_wires_only_owner_enabled_workspace_tools(
        tmp_path, monkeypatch, workspace, enabled, has_workspace, expected):
    from star import server_roles, turn_memory
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    server_roles.forget()
    turn_memory.forget()
    models = Models([reply(text="done")])
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(models))
    # This exercises desktop routing and the real agent loop with an offline model.
    # Disable unrelated services and never load the owner's actual app settings.
    settings = core.Settings(provider="local", model="offline", knowledge_endpoint="off",
                             web_auto_search=False, skills_enabled=False, graphify_enabled=False,
                             debug_evidence_enabled=enabled, workspace=str(workspace.root) if has_workspace else "")
    result = core.run_task(settings, "Debug this Python assertion failure", mode="agent")
    assert result == "done" and len(models.requests) == 1
    assert (TOOL_NAMES <= offered(models.requests[0])) is expected
    server_roles.forget()
    turn_memory.forget()
