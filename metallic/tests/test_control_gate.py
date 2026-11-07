"""The Metallic Control host gate (server/control/metallic_control_gate.py): parsers of the real /proc and journal
formats, and the allow-list (a verb is looked up or refused; nothing is built from the caller's text)."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess

import pytest

GATE = Path(__file__).resolve().parents[2] / "server" / "control" / "metallic_control_gate.py"
spec = importlib.util.spec_from_file_location("metallic_control_gate", GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

STAT = """cpu  100 5 50 1000 20 1 2 3 0 0
cpu0 50 2 25 500 10 0 1 1 0 0
cpu1 50 3 25 500 10 1 1 2 0 0
intr 12345
"""
MEMINFO = """MemTotal:       131072000 kB
MemFree:         1000000 kB
MemAvailable:   58720256 kB
SwapTotal:       4194304 kB
SwapFree:        1048576 kB
"""
NETDEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 999 9 0 0 0 0 0 0 999 9 0 0 0 0 0 0
  eno2: 5000 10 0 0 0 0 0 0 7000 12 0 0 0 0 0 0
vethab12: 1 1 0 0 0 0 0 0 1 1 0 0 0 0 0 0
starnat0: 4 4 0 0 0 0 0 0 4 4 0 0 0 0 0 0
"""
DISKSTATS = """   8       0 sda 100 0 2000 50 200 0 4000 80 0 100 130 0 0 0 0
   8       1 sda1 90 0 1800 40 190 0 3800 70 0 90 110 0 0 0 0
   7       0 loop0 1 0 8 0 0 0 0 0 0 0 0 0 0 0 0
 259       0 nvme0n1 10 0 80 1 20 0 160 2 0 3 3 0 0 0 0
"""


def test_proc_parsers_read_the_real_formats():
    st = gate.parse_stat(STAT)
    assert st == {"cpu": [100, 5, 50, 1000, 20, 1, 2, 3], "ncpu": 2}
    mem = gate.parse_meminfo(MEMINFO)
    assert mem["total"] == 131072000 * 1024 and mem["available"] == 58720256 * 1024
    assert mem["swap_total"] - mem["swap_free"] == 3145728 * 1024
    assert gate.parse_net_dev(NETDEV) == {"eno2": [5000, 7000]}          # no lo, veth or bridges
    assert gate.parse_diskstats(DISKSTATS) == {"sda": [2000, 4000], "nvme0n1": [80, 160]}   # whole disks only
    assert gate.parse_loadavg("1.50 2.00 3.25 2/900 1234") == [1.5, 2.0, 3.25]
    assert gate.parse_psi("some avg10=9.00 avg60=9.35 avg300=9.30 total=1\nfull avg10=0.00") == 9.0


def test_process_stat_with_spaces_and_parentheses_in_the_name():
    text = "4242 (Web Content (x)) S 1 2 3 4 5 6 7 8 9 10 700 300 0 0 20 0 1 0 100 200 300"
    assert gate.parse_proc_pid_stat(text) == ("Web Content (x)", 1000)
    assert gate.parse_proc_pid_stat("garbage") is None
    assert gate.container_of("0::/lxc.payload.starai/system.slice/star-brain.service") == "starai"
    assert gate.container_of("0::/user.slice") == ""


def test_temperatures_and_containers_from_sysfs(tmp_path):
    chip = tmp_path / "class" / "hwmon" / "hwmon0"
    chip.mkdir(parents=True)
    (chip / "name").write_text("k10temp\n")
    (chip / "temp1_input").write_text("73000\n")
    (chip / "temp1_label").write_text("Tctl\n")
    (chip / "temp3_input").write_text("70250\n")
    (chip / "temp3_label").write_text("Tccd1\n")
    empty = tmp_path / "class" / "hwmon" / "hwmon4"
    empty.mkdir()                                         # a chip with no sensors (seen on brain 1)
    assert gate.temperatures(tmp_path) == {"k10temp/Tctl": 73.0, "k10temp/Tccd1": 70.2}
    group = tmp_path / "fs" / "cgroup" / "lxc.payload.starai"
    group.mkdir(parents=True)
    (group / "cpu.stat").write_text("usage_usec 16715992274570\nuser_usec 1\n")
    (group / "memory.current").write_text("75629158400\n")
    (group / "memory.max").write_text("max\n")
    assert gate.containers(tmp_path) == {"starai": {"cpu_usec": 16715992274570, "mem": 75629158400, "mem_max": None}}


def test_timings_join_the_three_print_timing_lines_into_one_request():
    t = gate.Timings()
    lines = [
        "[46613] 579.04.119.931 I slot print_timing: id  1 | task 212818 | prompt eval time =   11804.10 ms /   516 "
        "tokens (   22.88 ms per token,    43.71 tokens per second)",
        "[46613] 579.04.119.937 I slot print_timing: id  1 | task 212818 |        eval time =  166604.38 ms /  1452 "
        "tokens (  114.82 ms per token,     8.71 tokens per second)",
        "[51883] 577.05.504.932 I slot launch_slot_: id  3 | task 6977 | processing task, is_child = 0",
    ]
    assert [t.feed(line, now=1000.0) for line in lines] == [None, None, None]
    done = t.feed("[46613] 579.04.119.938 I slot print_timing: id  1 | task 212818 |       total time =  178408.47 "
                  "ms /  1968 tokens", now=1000.0)
    assert done == {"port": "46613", "slot": 1, "task": 212818, "prompt_ms": 11804.1, "prompt_tokens": 516,
                    "eval_ms": 166604.38, "eval_tokens": 1452, "total_ms": 178408.47, "t": 1000.0}
    assert t.take() == [done] and t.take() == []
    progress = ("[46613] 615.44.009.387 I slot print_timing: id  1 | task 226817 | n_gen =   2895, tg =   9.06 t/s, "
                "tg_3s =   7.48 t/s")
    assert t.feed(progress, now=2000.0) is None
    assert t.generating(now=2005.0) == [{"port": "46613", "slot": 1, "task": 226817, "n_gen": 2895, "tg": 9.06,
                                         "tg3": 7.48, "t": 2000.0}]
    assert t.generating(now=2011.0) == []                 # no progress line for 10 s: not generating any more
    # a plain llama-server (brain 2's model) logs without the [port] prefix
    for what in ("prompt eval time =   10.00 ms /   5 tokens", "eval time =   100.00 ms /  10 tokens",
                 "total time =   110.00 ms /  15 tokens"):
        row = t.feed(f"slot print_timing: id  0 | task 7 | {what}", now=5.0)
    assert row["port"] == "" and row["eval_tokens"] == 10


CFG = {"machine": "brain2", "star": {"container": "starai", "gate": "/opt/star/discord-gate/star_gate.py"},
       "runners": [{"name": "github", "kind": "github", "container": "ci-runner", "unit": "actions.runner.x.service"}],
       "backups": [{"set": "starai", "status": "~/s.json", "unit": "star-recovery-backup.service"}],
       "forge_backups": {"container": "metallic-forge", "path": "/var/backups/forgejo", "unit": "forgejo-backup.service"},
       "actions": ["restart:star-discord", "ns-pause", "runner-stop:github", "backup-now:starai", "backup-now:forge",
                   "restart:not-a-star-unit"]}


def test_actions_are_looked_up_never_built_from_text():
    lxc = gate.LXC
    assert gate.action_command("restart:star-discord", CFG) == [lxc, "exec", "starai", "--", "/usr/bin/python3",
                                                                 "/opt/star/discord-gate/star_gate.py",
                                                                 "restart:star-discord"]
    assert gate.action_command("runner-stop:github", CFG) == [lxc, "exec", "ci-runner", "--", "systemctl", "stop",
                                                               "actions.runner.x.service"]
    assert gate.action_command("backup-now:starai", CFG) == ["systemctl", "--user", "start", "--no-block",
                                                              "star-recovery-backup.service"]
    assert gate.action_command("backup-now:forge", CFG)[-1] == "forgejo-backup.service"
    # enabled in gate.json but not a STAR unit the gate knows: refused
    assert gate.action_command("restart:not-a-star-unit", CFG) is None
    # known verbs this host does not enable: refused
    assert gate.action_command("restart:star-brain", CFG) is None
    assert gate.action_command("runner-start:github", CFG) is None
    assert gate.action_command("ns-pause; rm -rf /", CFG) is None
    assert gate.action_command("litha-brain:off", CFG) is None
    on = {**CFG, "actions": ["litha-brain:on", "litha-brain:off"]}
    helper = str(GATE.with_name("litha_brain.py"))
    assert gate.action_command("litha-brain:off", on) == ["/usr/bin/python3", helper, "off"]
    assert gate.action_command("litha-brain:on", on) == ["/usr/bin/python3", helper, "on"]


def test_litha_brain_switches_router_and_model_in_a_safe_order(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("litha_brain", GATE.with_name("litha_brain.py"))
    lb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lb)
    ran = []

    def fake_run(container, args, timeout=130):
        ran.append((container, args[-1] if args[0] == "python3" else " ".join(args)))
        out = {lb.MESH: "off\n", lb.BRAIN: "unloaded\n"}.get(container, "") if args[0] == "python3" else ""
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(lb, "_run", fake_run)
    assert lb.main("off") == 0
    # router first (no request reloads the model), then the unload
    assert ran == [(lb.MESH, "off"), (lb.MESH, "systemctl restart star-mesh"), (lb.BRAIN, "off")]
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "text": "litha-26b on brain 1: unloaded; router brain fallback: off"}
    ran.clear()
    assert lb.main("on") == 0
    assert ran == [(lb.BRAIN, "on"), (lb.MESH, "on"), (lb.MESH, "systemctl restart star-mesh")]
    capsys.readouterr()
    assert lb.main("rm") == 2 and not json.loads(capsys.readouterr().out)["ok"]


def test_act_and_main_refuse_without_running_anything(monkeypatch, capsys):
    ran = []

    def fake_run(args, timeout=20):
        ran.append(args)
        return subprocess.CompletedProcess(args, 0, '{"ok":true,"text":"night school paused (HOLD file)"}', "")
    code, result = gate.act("ns-pause", CFG, run=fake_run)
    assert code == 0 and result["text"] == "night school paused (HOLD file)" and len(ran) == 1
    code, result = gate.act("id", CFG, run=fake_run)
    assert code == 2 and not result["ok"] and len(ran) == 1
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "cat /etc/shadow")
    assert gate.main([]) == 2
    assert "refused" in json.loads(capsys.readouterr().out)["text"]
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "act")
    assert gate.main([]) == 2
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "ping")
    assert gate.main([]) == 0


def test_stream_writes_json_lines_with_slow_data_on_the_first_tick(monkeypatch, tmp_path):
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    (proc / "pressure").mkdir()
    (proc / "stat").write_text(STAT)
    (proc / "meminfo").write_text(MEMINFO)
    (proc / "loadavg").write_text("0.5 0.4 0.3 1/2 3")
    (proc / "net" / "dev").write_text(NETDEV)
    (proc / "diskstats").write_text(DISKSTATS)
    monkeypatch.setattr(gate, "PROC", proc)
    monkeypatch.setattr(gate, "SYS", tmp_path / "sys")
    monkeypatch.setattr(gate, "star_facts", lambda cfg: {"services": []})
    monkeypatch.setattr(gate, "inventory", lambda cfg: [{"name": "starai", "limits": {"cpu": "40"}}])
    ticks = iter(range(0, 100, 5))
    out = io.StringIO()
    gate.stream({"machine": "brain1", "mounts": [str(tmp_path)]}, out=out, clock=lambda: next(ticks),
                sleep=lambda s: None, lifetime=9)
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(rows) >= 1 and rows[0]["kind"] == "sample" and rows[0]["machine"] == "brain1"
    assert rows[0]["cpu"] == [100, 5, 50, 1000, 20, 1, 2, 3] and rows[0]["net"] == {"eno2": [5000, 7000]}
    assert rows[0]["slow"]["facts"] == {"services": []} and rows[0]["inventory"][0]["name"] == "starai"
    assert str(tmp_path) in rows[0]["fs"]


@pytest.mark.parametrize("verb", ["stream extra", "act ns-pause extra", "facts", ""])
def test_unknown_shapes_are_refused(monkeypatch, verb):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", verb)
    assert gate.main([]) == 2
