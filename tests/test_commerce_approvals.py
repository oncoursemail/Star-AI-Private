"""The only gate on real-world commerce actions: an owner-clicked approval.

Everything that spends money, places or changes orders, lists or prices products, posts
publicly, messages customers or touches a third-party account is a proposal until the
owner approves it. Model tools can propose, never approve or run.
"""
import ast
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from star import commerce_tools, intelligence
from star.commerce import approvals
from star.commerce.workspace import commerce_connection, handle_commerce
from star.desktop_core import Settings
from star.react_shell import ALLOWED_ACTIONS, COMMERCE_ACTIONS, apply_setting_changes

ROOT = Path(__file__).resolve().parents[1]


class Sent:
    """A stand-in marketplace: records every call so tests can prove nothing left early."""
    def __init__(self):
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        return {"sent": True}


def board(home, action="commerceBoard", **body):
    return handle_commerce(action, body, project="STAR", home=home)


def propose(home, kind="spend_money", **extra):
    with commerce_connection(home) as conn, conn:
        return approvals.propose(conn, "STAR", kind, "Run a $20 ad", {"budget": "20 USD"},
                                 amount_cents=2000, **extra)


def decide(home, approval_id, decision="approve", **extra):
    return board(home, "commerceApprovalDecide", id=approval_id, decision=decision, **extra)


def execute(home, approval_id, connectors):
    with commerce_connection(home) as conn, conn:
        return approvals.execute(conn, "STAR", {"id": approval_id}, connectors)


@pytest.mark.parametrize("kind", sorted(approvals.KINDS))
def test_every_real_world_kind_waits_and_cannot_run_unapproved(tmp_path, kind):
    sent = Sent()
    row = propose(tmp_path, kind)
    assert row["status"] == "pending" and sent.calls == []
    with pytest.raises(PermissionError, match="owner-approved"):
        execute(tmp_path, row["id"], {kind: sent})
    assert sent.calls == []
    shown = board(tmp_path)["approvals"]
    assert [a["id"] for a in shown] == [row["id"]] and shown[0]["status"] == "pending"


def test_a_click_is_required_then_the_action_runs_exactly_once(tmp_path):
    sent = Sent()
    row = propose(tmp_path)
    with pytest.raises(PermissionError, match="Owner confirmation"):
        decide(tmp_path, row["id"])
    with pytest.raises(PermissionError, match="Owner confirmation"):
        decide(tmp_path, row["id"], owner_confirmed="yes")
    assert board(tmp_path)["approvals"][0]["status"] == "pending"
    assert decide(tmp_path, row["id"], owner_confirmed=True)["approvals"][0]["status"] == "approved"
    assert sent.calls == []  # approving is not running
    done = execute(tmp_path, row["id"], {"spend_money": sent})
    assert done["status"] == "executed" and done["result"] == {"sent": True}
    assert sent.calls == [{"budget": "20 USD"}]
    with pytest.raises(PermissionError):
        execute(tmp_path, row["id"], {"spend_money": sent})
    assert len(sent.calls) == 1


def test_rejected_actions_never_run_and_decisions_are_final(tmp_path):
    sent = Sent()
    row = propose(tmp_path, "message_customer")
    decide(tmp_path, row["id"], "reject", owner_confirmed=True)
    with pytest.raises(PermissionError):
        execute(tmp_path, row["id"], {"message_customer": sent})
    with pytest.raises(ValueError, match="already decided"):
        decide(tmp_path, row["id"], owner_confirmed=True)
    assert sent.calls == []


def test_approved_without_a_connector_sends_nothing_and_stays_approved(tmp_path):
    row = propose(tmp_path, "list_product")
    decide(tmp_path, row["id"], owner_confirmed=True)
    out = board(tmp_path, "commerceApprovalExecute", id=row["id"])["approvals"][0]
    assert out["status"] == "approved"
    out = execute(tmp_path, row["id"], None)
    assert out["result"]["executed"] is False and "Nothing was sent" in out["result"]["reason"]


def test_a_failing_connector_is_recorded_not_retried_silently(tmp_path):
    def broken(payload):
        raise RuntimeError("shop said no")
    row = propose(tmp_path, "place_order")
    decide(tmp_path, row["id"], owner_confirmed=True)
    out = execute(tmp_path, row["id"], {"place_order": broken})
    assert out["status"] == "failed" and "shop said no" in out["result"]["error"]


def test_the_gate_confirms_but_never_filters_content(tmp_path):
    odd = {"anything": "goes", "note": "any product topic, any wording", "nested": {"a": [1, 2]}}
    with commerce_connection(tmp_path) as conn, conn:
        row = approvals.propose(conn, "STAR", "post_public", "Any title at all", odd, amount_cents=0)
    decide(tmp_path, row["id"], owner_confirmed=True)
    sent = Sent()
    assert execute(tmp_path, row["id"], {"post_public": sent})["status"] == "executed"
    assert sent.calls == [odd]


def test_proposals_are_bounded_and_scoped_to_the_project(tmp_path):
    with commerce_connection(tmp_path) as conn, conn:
        with pytest.raises(ValueError, match="Unknown action kind"):
            approvals.propose(conn, "STAR", "delete_everything", "x", {})
        with pytest.raises(ValueError, match="too large"):
            approvals.propose(conn, "STAR", "spend_money", "x", {"a": "b" * 30000})
        with pytest.raises(ValueError, match="whole number"):
            approvals.propose(conn, "STAR", "spend_money", "x", {}, amount_cents=-5)
    row = propose(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        handle_commerce("commerceApprovalDecide", {"id": row["id"], "decision": "approve", "owner_confirmed": True},
                        project="Other", home=tmp_path)


def test_nothing_is_registered_by_default_so_nothing_can_leave_this_pc():
    assert approvals.CONNECTORS == {}


# --- model tools: propose only -------------------------------------------------------------

def hub(home, enabled):
    return intelligence.LocalIntelligence(home=home, skills_enabled=False, graphify_enabled=False,
                                          roblox_research_enabled=False, commerce_enabled=enabled)


def names(instance, prompt):
    return [t["name"] for t in instance.definitions(prompt)]


def test_tools_are_off_until_the_owner_enables_business_and_offer_only_for_commerce_prompts(tmp_path):
    assert not any(n in names(hub(tmp_path, False), "Draft a product listing for my Etsy shop")
                   for n in commerce_tools.COMMERCE_TOOL_NAMES)
    on = hub(tmp_path, True)
    assert set(names(on, "Draft a product listing for my Etsy shop")) == commerce_tools.COMMERCE_TOOL_NAMES
    assert not commerce_tools.COMMERCE_TOOL_NAMES & set(names(on, "Explain Luau metatables"))
    with pytest.raises(PermissionError, match="Business tools"):
        hub(tmp_path, False).call("star_commerce_overview", {}, enabled={"star_commerce_overview"})


def test_model_tools_can_only_propose_never_approve_or_run(tmp_path):
    assert not [n for n in commerce_tools.COMMERCE_TOOL_NAMES if "approve" in n or "execute" in n or "run" in n]
    sent = Sent()
    approvals.register_connector("spend_money", sent)
    try:
        on = hub(tmp_path, True)
        out = on.call("star_commerce_propose_action",
                      {"kind": "spend_money", "title": "Boost the hoodie listing", "details": {"usd": 50},
                       "amount_cents": 5000}, enabled=commerce_tools.COMMERCE_TOOL_NAMES)
        assert out["ran"] is False and out["status"] == "pending"
        assert sent.calls == []
        overview = on.call("star_commerce_overview", {}, enabled=commerce_tools.COMMERCE_TOOL_NAMES)
        assert [a["id"] for a in overview["waiting_for_owner_approval"]] == [out["id"]]
        draft = on.call("star_commerce_draft_candidate",
                        {"channel": "etsy", "title": "Quiet desk mat", "concept": "A felt desk mat."},
                        enabled=commerce_tools.COMMERCE_TOOL_NAMES)
        assert draft["status"] == "draft" and draft["listed"] is False
        assert sent.calls == []
        # Only the owner's click moves it.
        decide(tmp_path, out["id"], owner_confirmed=True)
        assert sent.calls == []
        with commerce_connection(tmp_path) as conn, conn:
            approvals.execute(conn, "STAR", {"id": out["id"]})
        assert sent.calls == [{"usd": 50}]
    finally:
        approvals.CONNECTORS.pop("spend_money", None)


# --- the setting and the Qt bridge ----------------------------------------------------------

def test_commerce_is_opt_in_validated_and_changeable_from_the_interface(tmp_path):
    settings = Settings()
    assert settings.commerce_enabled is False
    settings = apply_setting_changes(settings, {"commerce_enabled": True})
    settings.save(tmp_path / "settings.json")
    reopened = Settings.load(tmp_path / "settings.json")
    assert reopened.commerce_enabled is True
    assert intelligence.for_settings(reopened, tmp_path).status()["commerce"]["enabled"] is True
    reopened.commerce_enabled = "yes"
    with pytest.raises(ValueError):
        reopened.validate()


def bridge_methods(names):
    path = ROOT / "star" / "react_shell.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    launch = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "launch")
    cls = next(n for n in launch.body if isinstance(n, ast.ClassDef) and n.name == "Bridge")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    for method in methods:
        method.decorator_list = []
    return compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec")


@pytest.fixture
def desk(tmp_path):
    settings_file = tmp_path / "settings.json"
    Settings().save(settings_file)
    home = tmp_path / "home"
    namespace = dict(__package__="star", json=json, threading=threading, Settings=Settings,
                     ALLOWED_ACTIONS=ALLOWED_ACTIONS, WARM_UP_STOPPERS=set(), VOICE_ACTIONS=set(),
                     MEDIA_ACTIONS=set(), DISCORD_ACTIONS=set(), CLIP_ACTIONS=set(), CLIP_INTEROP_ACTIONS=set(), MUSIC_ACTIONS=set(),
                     LESSON_ACTIONS=set(), LEARNED_ACTIONS=set(), CORRECTION_ACTIONS=set(),
                     ROBLOX_ACTIONS=set(), STUDIO_HOST_ACTIONS=set(), app_data=lambda: home)
    exec(bridge_methods({"invoke", "_commerce_pilot_tick"}), namespace)
    host = SimpleNamespace(settings_file=settings_file, _closing=False,
                           commerce_pilot_running=threading.Event(),
                           pool=SimpleNamespace(submit=lambda work: work()))
    def call(action, **body):
        return json.loads(namespace["invoke"](host, json.dumps({"action": action, **body})))
    def enable():
        saved = Settings.load(settings_file)
        saved.commerce_enabled = True
        saved.save(settings_file)
    return SimpleNamespace(call=call, enable=enable, host=host, tick=lambda: namespace["_commerce_pilot_tick"](host),
                           home=home)


def test_bridge_refuses_every_commerce_action_until_business_is_enabled(desk):
    assert {"commerceApprovals", "commerceApprovalDecide", "commerceApprovalExecute"} <= COMMERCE_ACTIONS
    for action in sorted(COMMERCE_ACTIONS):
        answer = desk.call(action)
        assert answer["ok"] is False and "Business tools are off" in answer["error"], action
    assert not (desk.home / "commerce").exists()


def test_bridge_owner_approval_flow_end_to_end(desk):
    desk.enable()
    assert desk.call("commerceBoard")["data"]["approvals"] == []
    row = propose(desk.home)
    assert desk.call("commerceApprovalDecide", id=row["id"], decision="approve")["ok"] is False
    answer = desk.call("commerceApprovalDecide", id=row["id"], decision="approve", owner_confirmed=True)
    assert answer["ok"] and answer["data"]["approvals"][0]["status"] == "approved"
    answer = desk.call("commerceApprovalExecute", id=row["id"])
    assert answer["ok"] and answer["data"]["approvals"][0]["status"] == "approved"  # no connector: nothing sent


def test_pilot_scheduler_does_nothing_while_business_is_off(desk, monkeypatch):
    runs = []
    monkeypatch.setattr("star.commerce.autopilot.run_due_pilot_checks", lambda home, project: runs.append(project))
    desk.tick()
    assert runs == []
    desk.enable()
    desk.tick()
    assert runs == ["STAR"]


# --- command line (the owner's other way to approve) ----------------------------------------

def run_cli(home, *args):
    from star.commerce.__main__ import main
    return main(["approvals", *args, "--home", str(home)])


def test_cli_needs_business_enabled_and_the_yes_flag(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    Settings().save(home / "settings.json")
    assert run_cli(home, "list") == 2 and "Business tools are off" in capsys.readouterr().err
    saved = Settings.load(home / "settings.json")
    saved.commerce_enabled = True
    saved.save(home / "settings.json")
    row = propose(home)
    assert run_cli(home, "approve", row["id"]) == 2  # no --yes: nothing decided
    assert "Owner confirmation" in capsys.readouterr().err
    assert board(home)["approvals"][0]["status"] == "pending"
    assert run_cli(home, "run", row["id"], "--yes") == 2  # not approved yet
    assert run_cli(home, "approve", row["id"], "--yes") == 0
    assert "approved" in capsys.readouterr().out
    assert board(home)["approvals"][0]["status"] == "approved"
