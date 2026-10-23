"""Offline tests for star.agent_fleet using throwaway git repos and python subprocesses."""
import subprocess
import sys
import threading
import time

import pytest

from star import agent_fleet as fl

PY = sys.executable
RES = {"ram_total_mib": 32000, "ram_free_mib": 20000, "cpu_busy": 0.1, "cpus": 16}


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("base\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


def writer(text):
    return [PY, "-c", f"open('a.txt','a').write({text!r})"]


PASS = [PY, "-c", "import sys; sys.exit(0)"]
FAIL = [PY, "-c", "import sys; sys.exit(1)"]


def test_plan_slots_honest_states():
    assert fl.plan_slots({**RES, "ram_free_mib": None})[0] == 0
    assert "waiting" in fl.plan_slots({**RES, "cpu_busy": 0.95})[1]
    assert fl.plan_slots({**RES, "ram_free_mib": 5000})[0] == 0
    assert fl.plan_slots(RES)[0] == 4
    assert fl.plan_slots(RES, cap=2)[0] == 2


def test_live_sample_has_expected_keys():
    assert set(fl.sample_resources(0.05)) == {"ram_total_mib", "ram_free_mib", "cpu_busy", "cpus"}


def test_off_by_default(repo, monkeypatch):
    monkeypatch.delenv("STAR_AGENT_FLEET", raising=False)
    r = fl.run_fleet(repo, [fl.FleetTask("t1", writer("x"), PASS)], resources=RES)
    assert r.slots == 0 and r.receipts == [] and "disabled" in r.reason


def test_protected_refused(tmp_path):
    p = tmp_path / "Paintball"
    p.mkdir()
    assert "protected" in fl.run_fleet(p, [], enabled=True, resources=RES).reason


def test_only_passing_task_is_proposed_and_nothing_merged(repo, tmp_path):
    tasks = [fl.FleetTask("good", writer("g"), PASS), fl.FleetTask("bad", writer("b"), FAIL),
             fl.FleetTask("noop", PASS, PASS), fl.FleetTask("crash", FAIL, PASS),
             fl.FleetTask("off", writer("o"), PASS, enabled=False)]
    r = fl.run_fleet(repo, tasks, enabled=True, resources=RES, worktrees=tmp_path / "wts")
    st = {x.task_id: x.status for x in r.receipts}
    assert st == {"good": "proposed", "bad": "tests_failed", "noop": "no_changes", "crash": "agent_failed",
                  "off": "disabled"}
    assert "a.txt" in r.receipts[0].diffstat
    assert (repo / "a.txt").read_text() == "base\n"
    count = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", "main"], capture_output=True, text=True)
    assert count.stdout.strip() == "1"


def test_no_test_command_is_never_a_pass(repo, tmp_path):
    r = fl.run_fleet(repo, [fl.FleetTask("t", writer("x"), [])], enabled=True, resources=RES,
                     worktrees=tmp_path / "w")
    assert r.receipts[0].status == "error"


def test_cancel_during_test_run(repo, tmp_path):
    cancel = threading.Event()
    slow = [PY, "-c", "import time; time.sleep(30)"]
    threading.Timer(2.0, cancel.set).start()
    t0 = time.monotonic()
    r = fl.run_fleet(repo, [fl.FleetTask("t", writer("x"), slow)], enabled=True, resources=RES,
                     worktrees=tmp_path / "w", cancel=cancel)
    assert r.receipts[0].status == "cancelled" and time.monotonic() - t0 < 20


def test_three_agents_edit_same_file_without_conflict(repo, tmp_path):
    tasks = [fl.FleetTask(f"w{i}", writer(f"line{i}\n"), PASS) for i in range(3)]
    r = fl.run_fleet(repo, tasks, enabled=True, resources=RES, worktrees=tmp_path / "w")
    assert [x.status for x in r.receipts] == ["proposed"] * 3


# --- slice 2: ACP hand-off inside a fleet worktree, receipts on disk, orphan listing, CLI probes ---

ACP_FAKE = r'''
import json, sys
mode = sys.argv[1]
def out(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line); meth, i = m.get("method"), m.get("id")
    if meth == "initialize":
        if mode == "auth":
            out({"jsonrpc": "2.0", "id": i, "error": {"code": -32000, "message": "login"}})
        else:
            out({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": 1}})
    elif meth == "session/new":
        out({"jsonrpc": "2.0", "id": i, "result": {"sessionId": "s1"}})
    elif meth == "session/prompt":
        out({"jsonrpc": "2.0", "id": 77, "method": "session/request_permission",
             "params": {"sessionId": "s1", "toolCall": {"toolCallId": "t1", "title": "write a.txt"},
                        "options": [{"optionId": "a", "kind": "allow_once"}, {"optionId": "r", "kind": "reject_once"}]}})
        r = json.loads(sys.stdin.readline())
        if r["result"]["outcome"].get("optionId") == "a":
            open("a.txt", "a").write(mode)   # relative: the fleet must have set cwd to the worktree
        out({"jsonrpc": "2.0", "id": i, "result": {"stopReason": "end_turn"}})
'''


@pytest.fixture
def acp(tmp_path):
    p = tmp_path / "acp_agent.py"
    p.write_text(ACP_FAKE)
    return lambda mode="ok": [PY, str(p), mode]


def test_acp_handoff_edits_only_with_host_approval_and_passes_only_host_tests(repo, tmp_path, acp):
    tasks = [fl.FleetTask("yes", acp("edit"), PASS, acp_prompt="append to a.txt", approve=lambda p: True),
             fl.FleetTask("no", acp("edit"), PASS, acp_prompt="append to a.txt"),
             fl.FleetTask("yes-fail", acp("edit"), FAIL, acp_prompt="append", approve=lambda p: True),
             fl.FleetTask("auth", acp("auth"), PASS, acp_prompt="x", approve=lambda p: True)]
    r = fl.run_fleet(repo, tasks, enabled=True, resources=RES, worktrees=tmp_path / "w")
    st = {x.task_id: x for x in r.receipts}
    assert st["yes"].status == "proposed" and "a.txt" in st["yes"].diffstat
    assert st["no"].status == "no_changes"            # the host refused the write: nothing changed
    assert st["yes-fail"].status == "tests_failed"     # the agent's "end_turn" is not a pass
    assert st["auth"].status == "agent_failed" and "auth_required" in st["auth"].detail
    assert (repo / "a.txt").read_text() == "base\n"   # the main checkout is untouched


def test_receipts_are_written_as_json_lines(repo, tmp_path):
    out = tmp_path / "receipts.jsonl"
    fl.run_fleet(repo, [fl.FleetTask("t", writer("x"), PASS)], enabled=True, resources=RES,
                 worktrees=tmp_path / "w", receipts_file=out)
    import json
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["task_id"] == "t" and rows[0]["status"] == "proposed" and rows[0]["seconds"] >= 0
    assert rows[0]["resources"]["cpus"] == 16 and rows[0]["slots"] == 4


def test_fleet_worktrees_are_listed_for_recovery_never_deleted(repo, tmp_path):
    fl.run_fleet(repo, [fl.FleetTask("left", writer("x"), PASS)], enabled=True, resources=RES,
                 worktrees=tmp_path / "w")
    found = fl.fleet_worktrees(repo)
    assert [b for _, b in found] == ["star/fleet-left"]
    assert (tmp_path / "w" / "left" / "a.txt").exists()


def test_probe_agents_reports_missing_cli_honestly(monkeypatch):
    monkeypatch.setattr(fl.shutil, "which", lambda name: None)
    rows = fl.probe_agents()
    assert {r["agent"] for r in rows} == {"opencode", "codex", "claude"}
    assert all(r["installed"] is False and r["auth"] == "unknown" for r in rows)
