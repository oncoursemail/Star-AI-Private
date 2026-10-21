"""Metallic Control API: token login, sessions, CSRF, the admin allow-list end to end (ssh hosts and the PC agent),
the audit log, the push token, and the UI file server."""
from __future__ import annotations

import json
import subprocess
import time

import pytest

from metallic.control.actions import Runner
from metallic.control.collector import Collector
from metallic.control.server import App, Auth
from metallic.control.store import Store

LOGIN = "L" * 40
PUSH = "P" * 40
MACHINES = [{"id": "brain1", "name": "Brain 1", "ssh": "gate@b1", "actions": ["ns-pause", "restart:star-brain"]},
            {"id": "pc", "name": "PC", "kind": "pc", "actions": ["sunshine-stop"]}]


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture()
def app(tmp_path):
    clock = Clock(1000.0)
    store = Store(":memory:", clock=clock)
    ran = []

    def fake_run(args, **kw):
        ran.append(args)
        return subprocess.CompletedProcess(args, 0, '{"ok":true,"text":"night school paused (HOLD file)"}', "")
    runner = Runner(store, MACHINES, ["ssh", "-T"], str(tmp_path / "audit.jsonl"), run=fake_run, clock=clock)
    collector = Collector({"machine": MACHINES}, store, runner, clock=clock)
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>Metallic Control</title>")
    (ui / "assets" / "app-1.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("do not serve")
    a = App(collector, store, runner, Auth(LOGIN, PUSH, clock=clock), MACHINES, str(ui))
    a.ran, a.clock, a.tmp = ran, clock, tmp_path
    return a


def call(app, method, path, body=None, cookie=None, csrf=None, headers=None, client="192.0.2.5"):
    h = {"host": "control.lan"}
    if cookie:
        h["cookie"] = cookie
    if csrf:
        h["x-csrf-token"] = csrf
    h.update(headers or {})
    code, extra, data = app.handle(method, path, h, json.dumps(body).encode() if body is not None else b"", client)
    try:
        return code, extra, json.loads(data)
    except ValueError:
        return code, extra, data


def sign_in(app):
    code, extra, body = call(app, "POST", "/api/login", {"token": LOGIN})
    assert code == 200
    return extra["Set-Cookie"].split(";")[0], body["csrf"]


def test_login_sets_a_strict_http_only_cookie_and_wrong_tokens_are_rate_limited(app):
    code, extra, body = call(app, "POST", "/api/login", {"token": LOGIN})
    assert code == 200 and "HttpOnly" in extra["Set-Cookie"] and "SameSite=Strict" in extra["Set-Cookie"]
    assert "Secure" not in extra["Set-Cookie"]                  # plain-HTTP port; the HTTPS app sets Secure
    for _ in range(5):
        assert call(app, "POST", "/api/login", {"token": "nope"}, client="192.0.2.9")[0] == 401
    assert call(app, "POST", "/api/login", {"token": LOGIN}, client="192.0.2.9")[0] == 429
    app.clock.t += 301
    assert call(app, "POST", "/api/login", {"token": LOGIN}, client="192.0.2.9")[0] == 200


def test_every_api_read_needs_a_session(app):
    for path in ("/api/state", "/api/series?keys=a", "/api/actions", "/api/audit", "/api/session"):
        assert call(app, "GET", path)[0] == 401
    assert call(app, "GET", "/api/state", cookie="mc_session=forged")[0] == 401
    cookie, _ = sign_in(app)
    code, _, state = call(app, "GET", "/api/state", cookie=cookie)
    assert code == 200 and {m["id"] for m in state["machines"]} == {"brain1", "pc"}
    assert call(app, "GET", "/api/series?keys=a&range=year", cookie=cookie)[0] == 400
    app.clock.t += 12 * 3600 + 1                                 # sessions expire
    assert call(app, "GET", "/api/state", cookie=cookie)[0] == 401


def test_posts_need_the_csrf_token_and_a_same_origin(app):
    cookie, csrf = sign_in(app)
    body = {"action": "brain1/ns-pause", "confirm": "brain1/ns-pause"}
    assert call(app, "POST", "/api/actions/run", body, cookie=cookie)[0] == 403
    assert call(app, "POST", "/api/actions/run", body, cookie=cookie, csrf="wrong")[0] == 403
    assert call(app, "POST", "/api/actions/run", body, cookie=cookie, csrf=csrf,
                headers={"origin": "http://evil.example"})[0] == 403
    assert app.ran == []


def test_allowed_action_runs_through_the_host_gate_and_is_audited(app):
    cookie, csrf = sign_in(app)
    code, _, actions = call(app, "GET", "/api/actions", cookie=cookie)
    assert [a["id"] for a in actions["actions"]] == ["brain1/restart:star-brain", "brain1/ns-pause", "pc/sunshine-stop"]
    mismatch = {"action": "brain1/ns-pause", "confirm": "brain1/restart:star-brain"}
    assert call(app, "POST", "/api/actions/run", mismatch, cookie=cookie, csrf=csrf)[0] == 400
    code, _, res = call(app, "POST", "/api/actions/run", {"action": "brain1/ns-pause", "confirm": "brain1/ns-pause"},
                        cookie=cookie, csrf=csrf)
    assert code == 200 and res["state"] == "pending"
    journal_file = app.tmp / "audit.jsonl"
    deadline = time.monotonic() + 5                              # the ssh call runs on a worker thread
    while time.monotonic() < deadline and not (journal_file.exists() and journal_file.read_text().endswith("\n")):
        time.sleep(0.01)
    row = call(app, "GET", "/api/audit", cookie=cookie)[2]["audit"][0]
    assert app.ran == [["ssh", "-T", "gate@b1", "act", "ns-pause"]]
    assert row["state"] == "ok" and row["text"] == "night school paused (HOLD file)"
    assert row["label"] == "Pause night school (Brain 1)" and row["actor"].startswith("owner ")
    journal = [json.loads(line) for line in journal_file.read_text().splitlines()]
    assert journal[-1]["id"] == row["id"] and journal[-1]["state"] == "ok"


def test_anything_outside_the_allow_list_is_refused_and_still_audited(app):
    cookie, csrf = sign_in(app)
    for action in ("brain1/restart:star-discord", "brain1/rm -rf /", "pc/ns-pause", "brain9/ns-pause"):
        code, _, res = call(app, "POST", "/api/actions/run", {"action": action, "confirm": action}, cookie=cookie,
                            csrf=csrf)
        assert code == 403 and not res["ok"]
    audit = call(app, "GET", "/api/audit", cookie=cookie)[2]["audit"]
    assert len(audit) == 4 and {r["state"] for r in audit} == {"refused"}
    assert app.ran == []


def test_pc_actions_go_through_the_agent_push_and_come_back(app):
    cookie, csrf = sign_in(app)
    assert call(app, "POST", "/api/push", {"sample": {}}, headers={"authorization": "Bearer " + LOGIN})[0] == 401
    res = call(app, "POST", "/api/actions/run", {"action": "pc/sunshine-stop", "confirm": "pc/sunshine-stop"},
               cookie=cookie, csrf=csrf)[2]
    code, _, push = call(app, "POST", "/api/push", {"sample": {}}, headers={"authorization": "Bearer " + PUSH})
    assert code == 200 and push["commands"] == [{"audit": res["audit"], "verb": "sunshine-stop"}]
    # sent once only
    assert call(app, "POST", "/api/push", {"sample": {}}, headers={"authorization": "Bearer " + PUSH})[2]["commands"] == []
    call(app, "POST", "/api/push", {"sample": {}, "results": [{"audit": res["audit"], "ok": True, "exit": 0,
                                                               "text": "STOP_PENDING"}]},
         headers={"authorization": "Bearer " + PUSH})
    row = call(app, "GET", "/api/audit", cookie=cookie)[2]["audit"][0]
    assert row["state"] == "ok" and row["text"] == "STOP_PENDING" and app.ran == []
    # the push token cannot read anything
    assert call(app, "GET", "/api/state", headers={"authorization": "Bearer " + PUSH})[0] == 401


def test_pc_command_that_is_never_picked_up_fails_after_two_minutes(app):
    cookie, csrf = sign_in(app)
    call(app, "POST", "/api/actions/run", {"action": "pc/sunshine-stop", "confirm": "pc/sunshine-stop"},
         cookie=cookie, csrf=csrf)
    app.clock.t += 121
    call(app, "POST", "/api/push", {"sample": {}}, headers={"authorization": "Bearer " + PUSH})
    row = call(app, "GET", "/api/audit", cookie=cookie)[2]["audit"][0]
    assert row["state"] == "failed" and "did not pick it up" in row["text"]


def test_ui_files_and_path_traversal(app):
    code, extra, data = app.handle("GET", "/assets/app-1.js", {}, b"", "x")
    assert code == 200 and "immutable" in extra["Cache-Control"]
    code, _, data = app.handle("GET", "/servers", {}, b"", "x")             # SPA route -> the shell
    assert code == 200 and b"Metallic Control" in data
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        code, _, data = app.handle("GET", path, {}, b"", "x")
        assert b"do not serve" not in data


def test_logout_ends_the_session(app):
    cookie, csrf = sign_in(app)
    assert call(app, "POST", "/api/logout", {}, cookie=cookie, csrf=csrf)[0] == 200
    assert call(app, "GET", "/api/state", cookie=cookie)[0] == 401


def test_short_tokens_are_rejected():
    with pytest.raises(ValueError):
        Auth("short", PUSH)
