"""Laptop busy guard (server/knowledge/laptop/busy_guard.py): pause and resume decisions with a fake desktop.

    python -m pytest -q server/knowledge/tests/test_laptop_busy_guard.py
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "laptop"))

import busy_guard  # noqa: E402

LAPTOP = Path(__file__).resolve().parents[1] / "laptop"


class FakeProbe:
    def __init__(self):
        self.procs = {100: "explorer.exe", 200: "llama-server.exe"}
        self.shown = {}                 # pid -> [window titles]
        self.full = False
        self.paths = {200: str(Path.cwd() / "worker" / "llama-server.exe")}

    def processes(self):
        return dict(self.procs)

    def exe_path(self, pid, name):
        return self.paths.get(pid, "")

    def windows(self, pids):
        return {p: t for p, t in self.shown.items() if p in pids}

    def fullscreen(self):
        return self.full


class FakeGpu:
    def __init__(self):
        self.load = {}

    def per_pid(self):
        return dict(self.load)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def rig(tmp_path):
    base = tmp_path / "starai"
    home = base / "busy-guard"
    home.mkdir(parents=True)
    probe, gpu, clock, hits = FakeProbe(), FakeGpu(), Clock(), []
    probe.paths[200] = str(base / "gpu-worker" / "llama-server.exe")
    config = dict(busy_guard.DEFAULTS, resume_seconds=120)
    guard = busy_guard.Guard(config, home=home, probe=probe, gpu=gpu, clock=clock,
                             kill=lambda ports: hits.append(list(ports)) or [200])
    return guard, probe, gpu, clock, hits, base


def test_free_machine_stays_serving(rig):
    guard, *_ , base = rig
    assert guard.step() == "serving"
    assert not (base / "PAUSE").exists()


@pytest.mark.parametrize("exe", ["VALORANT-Win64-Shipping.exe", "FortniteClient-Win64-Shipping.exe", "RocketLeague.exe",
                                 "RobloxPlayerBeta.exe"])
def test_game_with_a_window_pauses_and_kills_workers(rig, exe):
    guard, probe, _, _, hits, base = rig
    probe.procs[300] = exe
    probe.shown[300] = ["game"]
    assert guard.step() == "paused"
    assert (base / "PAUSE").read_text().strip() == f"{exe} is running"
    assert hits == [[8090]]


def test_game_without_a_window_does_not_pause(rig):
    guard, probe, *_ = rig
    probe.procs[300] = "RocketLeague.exe"
    assert guard.step() == "serving"


def test_obs_pauses_without_a_window_and_our_own_processes_never_count(rig):
    guard, probe, _, _, _, base = rig
    probe.procs[301] = "obs64.exe"
    assert guard.step() == "paused"
    probe.procs.pop(301)
    # a game exe that lives under the workers' folder is ours (e.g. a test copy) and is ignored
    probe.procs[302] = "RocketLeague.exe"
    probe.paths[302] = str(base / "tmp" / "RocketLeague.exe")
    probe.shown[302] = ["x"]
    guard.last_busy = -10_000                      # long free: only the own-process rule can keep it serving
    assert guard.step() == "serving"


def test_fullscreen_and_fake_busy_file(rig):
    guard, probe, _, _, hits, base = rig
    probe.full = True
    assert guard.step() == "paused"
    probe.full = False
    (guard.home / "FAKE_BUSY").write_text("")
    guard.clock.now += 500
    assert guard.step() == "paused"
    assert "FAKE_BUSY" in guard.reason


def test_resumes_only_after_resume_seconds_free(rig):
    guard, probe, _, clock, _, base = rig
    (guard.home / "FAKE_BUSY").write_text("")
    assert guard.step() == "paused"
    (guard.home / "FAKE_BUSY").unlink()
    clock.now += 119
    assert guard.step() == "paused" and (base / "PAUSE").exists()
    clock.now += 2
    assert guard.step() == "serving"
    assert not (base / "PAUSE").exists()


def test_other_programs_gpu_load_needs_three_looks_and_ignores_our_workers(rig):
    guard, probe, gpu, clock, hits, base = rig
    gpu.load = {200: 95.0}                          # our llama-server: never counts
    for _ in range(5):
        clock.now += 3
        assert guard.step() == "serving"
    gpu.load = {200: 20.0, 777: 45.0}               # somebody else
    states = []
    for _ in range(4):
        clock.now += 3
        states.append(guard.step())
    assert states == ["serving", "serving", "paused", "paused"]
    assert "GPU" in guard.reason


def test_still_listening_while_busy_gets_killed_again(rig, monkeypatch):
    guard, probe, _, clock, hits, _ = rig
    probe.procs[300] = "obs64.exe"
    guard.step()
    monkeypatch.setattr(busy_guard, "port_open", lambda port: True)
    clock.now += 6
    guard.step()
    assert len(hits) == 2


def test_start_clears_a_stale_pause_file_and_logs(rig, monkeypatch):
    guard, _, _, _, _, base = rig
    (base / "PAUSE").write_text("old")

    def stop(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(busy_guard.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        guard.run()
    assert not (base / "PAUSE").exists()
    assert "stale PAUSE" in (base / "logs" / "busy-guard.log").read_text()


def test_supervisors_wait_for_pause_and_keep_stop():
    for name in ("run-gpu-worker.cmd", "run-rerank-worker.cmd"):
        text = (LAPTOP / name).read_text(encoding="utf-8")
        assert r'if exist "%B%\PAUSE"' in text and "goto loop" in text and "STOP" in text
        assert "C:" + chr(92) + "Users" not in text            # no user name in committed code


def test_listening_pids_parses_netstat(monkeypatch):
    sample = ("  Proto  Local Address          Foreign Address        State           PID\n"
              "  TCP    0.0.0.0:8090           0.0.0.0:0              LISTENING       11708\n"
              "  TCP    0.0.0.0:8092           0.0.0.0:0              LISTENING       14552\n"
              "  TCP    127.0.0.1:8090          127.0.0.1:5555        ESTABLISHED     11708\n"
              "  TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4\n")

    class R:
        stdout = sample
    monkeypatch.setattr(busy_guard.subprocess, "run", lambda *a, **k: R())
    assert busy_guard.listening_pids([8090, 8092]) == {11708, 14552}


def test_rerank_worker_exits_by_itself_while_the_pause_file_exists(tmp_path):
    import subprocess
    key, pause = tmp_path / "key", tmp_path / "PAUSE"
    key.write_text("k\n")
    cmd = [sys.executable, str(LAPTOP / "rerank_worker.py"), "--model-dir", str(tmp_path), "--key-file", str(key),
           "--host", "127.0.0.1", "--port", "0", "--pause-file", str(pause)]
    quiet = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with pytest.raises(subprocess.TimeoutExpired):          # no PAUSE: it keeps serving
            quiet.wait(timeout=2.5)
        pause.write_text("owner is gaming")
        assert quiet.wait(timeout=5) == 0                        # PAUSE: gone within about half a second
    finally:
        quiet.kill()
