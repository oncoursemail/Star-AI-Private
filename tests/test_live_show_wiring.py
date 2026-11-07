"""The live-show planner through its two entry points: `star live-show` and the opt-in agent tool."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from star import agent, cli, desktop_core as core
from star.live_show import REQUIRED_CHECKS, TOOL_NAMES, LiveShowTools, parse_manifest
from star.react_shell import apply_setting_changes
from star.workspace import Workspace

PILOT = Path(__file__).resolve().parents[1] / "examples" / "live_show" / "pilot.json"
PROMPT = "Plan the live show episode manifest in pilot.json"


def reply(*, text=None, calls=None):
    return SimpleNamespace(model="offline", choices=[SimpleNamespace(
        message=SimpleNamespace(content=text, tool_calls=calls),
        finish_reason="tool_calls" if calls else "stop")])


def call(name, args):
    return SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


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
    shutil.copy(PILOT, root / "pilot.json")
    return Workspace(root)


def run_agent(responses, *, workspace, tools, prompt=PROMPT):
    models = Models(responses)
    asyncio.run(agent.execute(client=Client(models), model="offline", prompt=prompt, image_paths=[],
                              workspace=workspace, live_show=tools, now=""))
    return models.requests


def offered(request):
    return {item["function"]["name"] for item in request.get("tools", [])}


def tool_payload(request):
    return json.loads([m for m in request["messages"] if m["role"] == "tool"][-1]["content"])


def cli_report(capsys, **fields):
    args = dict(command="live-show", manifest=str(PILOT), reviews=None, questions=None, post_episode=False)
    args.update(fields)
    asyncio.run(cli.main(argparse.Namespace(**args)))
    return json.loads(capsys.readouterr().out)


def test_live_show_is_a_registered_cli_subcommand(monkeypatch):
    seen = []

    async def fake_main(args):
        seen.append(args)

    monkeypatch.setattr("sys.argv", ["star", "live-show", str(PILOT), "--post-episode"])
    monkeypatch.setattr(cli, "setup", lambda: None)
    monkeypatch.setattr(cli, "main", fake_main)
    cli.cli()
    assert seen[0].command == "live-show" and seen[0].post_episode is True and seen[0].reviews is None


def test_cli_plans_the_manifest_offline(capsys):
    report = cli_report(capsys)
    assert report["simulation"] is True and report["broadcasting"] is False
    assert report["manifest"]["episode_id"] == "weather-report-animatic"
    assert report["readiness"]["status"] == "HOLD" and report["playout_recommendation"] == "INTERMISSION"


def test_cli_reviews_bound_to_the_exact_bytes_make_it_ready(capsys, tmp_path):
    digest = parse_manifest(PILOT.read_bytes()).sha256
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps([{"check": name, "result": "PASS", "manifest_sha256": digest}
                                   for name in sorted(REQUIRED_CHECKS)]), encoding="utf-8")
    assert cli_report(capsys, reviews=str(reviews))["playout_recommendation"] == "EPISODE"


def test_cli_rejects_an_invalid_manifest(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(cli.main(argparse.Namespace(command="live-show", manifest=str(bad), reviews=None,
                                                questions=None, post_episode=False)))


def test_agent_offers_and_runs_the_tool_only_when_enabled_and_asked(workspace):
    requests = run_agent([reply(calls=[call("star_live_show_plan", {"manifest": "pilot.json"})]),
                          reply(text="done")], workspace=workspace, tools=LiveShowTools(workspace, enabled=True))
    assert TOOL_NAMES <= offered(requests[0])
    payload = tool_payload(requests[1])
    assert payload["isError"] is False
    report = json.loads(payload["output"])
    assert report["manifest"]["episode_id"] == "weather-report-animatic" and report["broadcasting"] is False
    for tools, prompt in ((LiveShowTools(workspace, enabled=False), PROMPT),
                          (LiveShowTools(workspace, enabled=True), "Fix this Python test"), (None, PROMPT)):
        assert not TOOL_NAMES & offered(run_agent([reply(text="done")], workspace=workspace,
                                                  tools=tools, prompt=prompt)[0])


def test_agent_tool_stays_inside_the_workspace_and_rejects_unlisted_calls(workspace, tmp_path):
    (tmp_path / "outside.json").write_text(PILOT.read_text(encoding="utf-8"), encoding="utf-8")
    requests = run_agent([reply(calls=[call("star_live_show_plan", {"manifest": "../outside.json"})]),
                          reply(text="done")], workspace=workspace, tools=LiveShowTools(workspace, enabled=True))
    assert tool_payload(requests[1])["isError"] is True
    assert "weather-report-animatic" not in json.dumps(requests[1]["messages"][-1])
    # A tool that was not offered this turn (the prompt does not ask for it) is refused too.
    requests = run_agent([reply(calls=[call("star_live_show_plan", {"manifest": "pilot.json"})]),
                          reply(text="done")], workspace=workspace, tools=LiveShowTools(workspace, enabled=True),
                         prompt="Fix this Python test")
    assert "rejected" in json.dumps(tool_payload(requests[1]))


def test_setting_defaults_false_round_trips_and_rejects_non_boolean(tmp_path):
    file = tmp_path / "settings.json"
    assert core.Settings.load(file).live_show_enabled is False
    apply_setting_changes(core.Settings(), {"live_show_enabled": True}).save(file)
    assert core.Settings.load(file).live_show_enabled is True
    for invalid in (1, "true", None):
        with pytest.raises(ValueError):
            apply_setting_changes(core.Settings(), {"live_show_enabled": invalid}).save(file)


@pytest.mark.parametrize(("enabled", "has_workspace", "expected"), [
    (False, True, False), (True, False, False), (True, True, True)])
def test_desktop_route_wires_only_owner_enabled_workspace_tool(tmp_path, monkeypatch, workspace,
                                                              enabled, has_workspace, expected):
    from star import server_roles, turn_memory
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    server_roles.forget()
    turn_memory.forget()
    models = Models([reply(text="done")])
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(models))
    settings = core.Settings(provider="local", model="offline", knowledge_endpoint="off", web_auto_search=False,
                             skills_enabled=False, graphify_enabled=False, live_show_enabled=enabled,
                             workspace=str(workspace.root) if has_workspace else "")
    assert core.run_task(settings, PROMPT, mode="agent") == "done"
    assert (TOOL_NAMES <= offered(models.requests[0])) is expected
    server_roles.forget()
    turn_memory.forget()
