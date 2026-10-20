"""Logic checks for server/winvm (throwaway Windows CI VMs): QEMU command line, guest protocol, pool policy, pins."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "server" / "winvm"
spec = importlib.util.spec_from_file_location("winvm", ROOT / "winvm.py")
winvm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(winvm)

CFG = dict(winvm.DEFAULTS, pool=1, max_vms=2)


def args(mode, **kw):
    return winvm.qemu_args("v1", "/run/winvm/v1", "/srv/d.qcow2", 8, 8192, mode, helper=["py", "w.py"], **kw)


def test_resume_has_same_devices_as_golden_plus_incoming():
    # A saved state only loads into an identical machine: resumed clones may differ from the golden run only by
    # -incoming (the disk path and VM id are not part of the device model).
    golden, resume = args("golden"), args("resume")
    assert resume[:len(golden)] == golden
    assert resume[len(golden):] == ["-incoming", "defer"]


def test_install_mode_boots_first_iso_and_keeps_disk():
    a = args("install", isos=("/iso/win.iso", "/iso/cfg.iso"))
    joined = " ".join(a)
    assert "file=/iso/win.iso" in joined and "file=/iso/cfg.iso" in joined
    assert "ide-cd,drive=cd0,bus=ide.0,bootindex=0" in a
    assert "ide-cd,drive=cd1,bus=ide.1" in a
    assert "-incoming" not in a
    assert "cdrom" not in " ".join(args("resume"))


def test_guestfwd_routes_to_this_vm_and_disk_is_throwaway():
    a = args("resume")
    netdev = a[a.index("-netdev") + 1]
    assert netdev.endswith("guestfwd=tcp:%s:80-cmd:py w.py guest-http v1" % winvm.GUEST_IP)
    drive = [x for x in a if x.startswith("if=none,id=d0")][0]
    assert "cache=unsafe" in drive and drive.endswith("file=/srv/d.qcow2")


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        args("boot")


def test_parse_request():
    assert winvm.parse_request(b"GET /done?rc=3&x=1 HTTP/1.1\r\nHost: a\r\n\r\n") == ("/done", {"rc": "3", "x": "1"})
    assert winvm.parse_request(b"") == (None, {})


def test_task_is_served_once_and_first_poll_recorded(tmp_path):
    assert winvm.guest_reply(str(tmp_path), "/task", {}, 100.0) == {"kind": "wait", "epoch": 100}
    assert (tmp_path / "first_poll").read_text() == "100.000"
    (tmp_path / "task.json").write_text(json.dumps({"kind": "github", "jit": "abc"}))
    assert winvm.guest_reply(str(tmp_path), "/task", {}, 101.0) == {"kind": "github", "jit": "abc", "epoch": 101}
    assert winvm.guest_reply(str(tmp_path), "/task", {}, 102.0)["kind"] == "wait"
    assert (tmp_path / "first_poll").read_text() == "100.000"


def test_done_and_unknown(tmp_path):
    assert winvm.guest_reply(str(tmp_path), "/done", {"rc": "0"}, 1.0) == {"ok": True}
    assert (tmp_path / "done").read_text() == "0"
    assert "error" in winvm.guest_reply(str(tmp_path), "/etc/passwd", {}, 1.0)


def test_guest_http_end_to_end(tmp_path):
    env = dict(os.environ, WINVM_RUN=str(tmp_path))
    (tmp_path / "v9").mkdir()
    (tmp_path / "v9" / "task.json").write_text(json.dumps({"kind": "shell", "script": "exit 0"}))
    r = subprocess.run([sys.executable, str(ROOT / "winvm.py"), "guest-http", "v9"], env=env, timeout=30,
                       input=b"GET /task HTTP/1.1\r\nHost: vm\r\n\r\n", capture_output=True, check=True)
    head, body = r.stdout.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 OK")
    assert int(re.search(rb"Content-Length: (\d+)", head).group(1)) == len(body)
    assert json.loads(body)["kind"] == "shell"


@pytest.mark.parametrize("busy,idle_s,running,ready,demand,expect", [
    (True, 0, 0, 0, 0, 0),      # brain busy, no job: no warm VM
    (False, 30, 0, 0, 0, 0),    # idle, but not for 60 s yet
    (False, 120, 0, 0, 0, 1),   # idle: fill the pool of 1
    (False, 120, 1, 1, 0, 0),   # pool already full
    (True, 0, 0, 0, 3, 2),      # queued jobs are served even while the brain is busy, up to max_vms
    (True, 0, 1, 1, 1, 0),      # the ready VM takes the queued job
    (False, 300, 2, 0, 5, 0),   # no room
])
def test_want_pool(busy, idle_s, running, ready, demand, expect):
    assert winvm.want_pool(busy, idle_s, running, ready, demand, CFG) == expect


def test_brain_state_missing_or_stale_counts_as_busy(tmp_path):
    p = tmp_path / "brain.json"
    assert winvm.brain_state(str(p)) == (True, 0.0)
    p.write_text(json.dumps({"busy": False, "idle_s": 75}))
    assert winvm.brain_state(str(p)) == (False, 75.0)
    old = time.time() - 60
    os.utime(p, (old, old))
    assert winvm.brain_state(str(p)) == (True, 0.0)


def test_unattend_renders_to_valid_xml_without_placeholders():
    out = winvm.render_unattend((ROOT / "guest" / "autounattend.xml").read_text(encoding="utf-8"), "W1n-abcDEF123")
    assert "@@" not in out
    ET.fromstring(out.encode("utf-8"))
    with pytest.raises(ValueError):
        winvm.render_unattend("x", "a<b")


def test_tools_are_pinned_and_used_by_provisioning():
    spec_ = json.loads((ROOT / "tools.json").read_text(encoding="utf-8"))
    items = [spec_["windows_iso"]] + spec_["tools"]
    names = [t["name"] for t in items]
    assert len(set(names)) == len(names)
    for t in items:
        assert re.fullmatch(r"[0-9a-f]{64}", t["sha256"]), t["name"]
        assert t["url"].startswith("https://"), t["name"]
    assert spec_["windows_iso"]["url"].startswith("https://software-static.download.prss.microsoft.com/")
    provision = (ROOT / "guest" / "provision.ps1").read_text(encoding="utf-8")
    for t in spec_["tools"]:
        assert t["name"] in provision, t["name"] + " is pinned but provision.ps1 does not install it"


@pytest.mark.parametrize("chat,quiet_s,expect", [(True, 0, "stop"), (False, 0.3, "stop"), (False, 1.5, "cont")])
def test_gate_holds_vms_during_chat_and_one_second_after(chat, quiet_s, expect):
    assert winvm.gate_want(chat, quiet_s) == expect


def test_brain_watch_state():
    spec2 = importlib.util.spec_from_file_location("brain_watch", ROOT / "brain_watch.py")
    bw = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bw)
    idle = [{"id": 0, "is_processing": False}, {"id": 1, "is_processing": False}]
    assert bw.state(idle, idle) == (False, False)
    background = [{"id": 0, "is_processing": False}, {"id": 1, "is_processing": True}]
    assert bw.state(background, idle) == (True, True)    # slot 1 may be the owner too: freeze
    owner = [{"id": 0, "is_processing": True}, {"id": 1, "is_processing": False}]
    assert bw.state(owner, idle) == (True, True)
    assert bw.state(idle, owner) == (True, True)          # voice counts as chat


@pytest.mark.parametrize("state,expect", [
    ({"chat": False, "lock": ""}, False),
    ({"chat": True, "lock": ""}, True),
    ({"chat": False, "lock": "claude-prio"}, True),     # someone else's timing run: stay out of it
    ({"chat": False, "lock": "claude-winvm"}, True),    # other winvm timing runs (e.g. the LXD load VM) too
    ({"chat": False, "lock": "claude-winvm-run"}, False),  # a timing run of these VMs needs them running
])
def test_must_yield(tmp_path, state, expect):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(state))
    assert winvm.must_yield(str(p)) is expect
    assert winvm.must_yield(str(tmp_path / "missing.json")) is True


def test_guest_log_is_decoded(tmp_path):
    winvm.guest_reply(str(tmp_path), "/log", {"m": "STEP%20ok%20pip%20180s"}, 5.0)
    assert (tmp_path / "guest.log").read_text() == "5 STEP ok pip 180s\n"


def test_guest_file_only_serves_plain_names_from_files_dir(tmp_path):
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "dist.zip").write_bytes(b"zip")
    (tmp_path / "secret").write_text("x")
    assert winvm.guest_file(str(tmp_path), "/file/dist.zip") == str(tmp_path / "files" / "dist.zip")
    for bad in ("/file/../secret", "/file/", "/file/.hidden", "/file/a\b", "/task", None, "/file/missing"):
        assert winvm.guest_file(str(tmp_path), bad) is None


def test_guest_http_streams_a_file(tmp_path):
    env = dict(os.environ, WINVM_RUN=str(tmp_path))
    (tmp_path / "v8" / "files").mkdir(parents=True)
    (tmp_path / "v8" / "files" / "a.bin").write_bytes(b"\x00\x01" * 1000)
    r = subprocess.run([sys.executable, str(ROOT / "winvm.py"), "guest-http", "v8"], env=env, timeout=30,
                       input=b"GET /file/a.bin HTTP/1.1\r\n\r\n", capture_output=True, check=True)
    head, body = r.stdout.split(b"\r\n\r\n", 1)
    assert b"Content-Length: 2000" in head and body == b"\x00\x01" * 1000
