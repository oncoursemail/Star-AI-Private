"""The PC agent's parsers (real Windows command output) and its own allow-list."""
from __future__ import annotations

import subprocess

from metallic.control import pc_agent

NETSTAT = """Interface Statistics

                           Received            Sent

Bytes                    3849979997      1318786529
Unicast packets           227242591        65798470
"""
SC = """SERVICE_NAME: SunshineService
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
"""


def test_parsers():
    assert pc_agent.parse_netstat_e(NETSTAT) == [3849979997, 1318786529]
    assert pc_agent.parse_netstat_e("nothing") is None
    gpu = pc_agent.parse_nvidia("NVIDIA GeForce RTX 3060 Ti, 4, 1007, 8192, 54, 19.99\n")
    assert gpu == {"name": "NVIDIA GeForce RTX 3060 Ti", "util": 4.0, "mem_used": 1007 * 1048576,
                   "mem_total": 8192 * 1048576, "temp": 54.0, "power": 19.99}
    assert pc_agent.parse_nvidia("NVIDIA X, [N/A], 1, 2, 3, [N/A]")["util"] is None
    assert pc_agent.parse_nvidia("") is None
    assert pc_agent.parse_sc_state(SC) == "running"
    assert pc_agent.parse_sc_state("") == "unknown"
    assert pc_agent.summarize_backup({"last_success_utc": "2026-10-21T03:07:07+00:00", "latest_complete": True,
                                      "error": None, "receipt": {"snapshot": "5f0c40ea86c757f3"}})["snapshot"] == "5f0c40ea"


def test_the_agent_runs_only_its_own_verbs():
    ran = []

    def fake(args, timeout=20):
        ran.append(args)
        return subprocess.CompletedProcess(args, 0, "SERVICE_NAME: SunshineService\nSTATE : 3 STOP_PENDING\n", "")
    cfg = {"star_ci_cmd": r"C:\work\star-ci-win.cmd"}
    assert pc_agent.run_command({"audit": 1, "verb": "sunshine-stop"}, cfg, fake)["ok"]
    assert ran[-1] == ["sc.exe", "stop", "SunshineService"]
    pc_agent.run_command({"audit": 2, "verb": "runner-start:pc-win"}, cfg, fake)
    assert ran[-1] == ["cmd.exe", "/c", r"C:\work\star-ci-win.cmd", "start"]
    refused = pc_agent.run_command({"audit": 3, "verb": "restart:star-brain"}, cfg, fake)
    assert refused == {"audit": 3, "ok": False, "exit": None, "text": "refused by the PC agent"} and len(ran) == 2
    assert pc_agent.local_command("runner-start:pc-win", {}) is None        # no runner script configured
