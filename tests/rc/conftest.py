"""Fakes for the RC module tests: a fake PC, a fake RC CLI, a fake Windows task and backend, a fake process list."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2]))

import fake_rc  # noqa: E402
from launcher.rc.module import RcModule  # noqa: E402
from launcher.rc.paths import TOOLS_EXE, Paths  # noqa: E402
from launcher.rc.proc import CmdResult  # noqa: E402

STEAM_ROOT = r"C:\Program Files (x86)\Steam\steamapps\common\RecRoom"
CAMPUS_ROOT = r"C:\Users\player\Documents\Campus\Campus2025"
CAMPUS_LAUNCHER = r"C:\Users\player\Desktop\Campus.exe"
NEXA_ROOT = r"C:\Users\player\Downloads\NexaNet\NexaNet"


class FakeBackend:
    """The Metallic-RC-Backend task and the service behind it."""

    def __init__(self):
        self.task = "Ready"  # Ready | Running | Disabled | absent
        self.up = False
        self.other_service = False  # something else owns the port
        self.polls_until_up = 2
        self._starting = None
        self.start_calls = 0
        self.stop_calls = 0
        self.stop_fails = False
        self.verified = False

    def fetch(self, url: str, timeout: float):
        path = url.split(":4187", 1)[-1]
        if self._starting is not None:
            self._starting -= 1
            if self._starting <= 0:
                self.up, self._starting, self.task = True, None, "Running"
        if self.other_service:
            return (200, {"service": "something-else"}) if path == "/healthz" else (404, None)
        if not self.up:
            raise OSError("connection refused")
        if path == "/healthz":
            return 200, {"status": "ok", "service": "metallic-rc-backend", "instanceId": "abc123"}
        if path == "/readyz":
            return 200, {"status": "owned-backend-ready", "nativeClientReady": False}
        if path == "/metallic/v1/capabilities":
            return 200, {"product": "Metallic-RC", "compatibility": {"actualGameClientVerified": self.verified, "nativeLogin": False,
                                                                     "nativeRoomJoin": False, "nativeGameplay": False, "nativeVoice": False},
                         "implemented": {"ownedAccounts": True, "persistentRoomDirectory": True}}
        return 404, None


class FakeRunner:
    def __init__(self, pc: Path, backend: FakeBackend):
        self.pc, self.backend = pc, backend
        self.calls: list[list[str]] = []
        self.rc_delay = None

    def run(self, argv, *, timeout, cwd=None, cancelled=None) -> CmdResult:
        self.calls.append(list(argv))
        if argv[0].endswith(TOOLS_EXE):
            if self.rc_delay == "timeout":
                return CmdResult(-1, "", "", timed_out=True)
            os.environ["FAKE_RC_PC"] = str(self.pc)
            out, err = io.StringIO(), io.StringIO()
            code = 0
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    fake_rc.main(argv[1:])
                except SystemExit as exit_:
                    code = int(exit_.code or 0)
            return CmdResult(code, out.getvalue(), err.getvalue())
        if argv[0] == "powershell":
            text = " ".join(argv)
            b = self.backend
            if "Get-ScheduledTask" in text and "Enable-" not in text:
                return CmdResult(0, b.task + "\n")
            if "Enable-ScheduledTask" in text:
                b.task = "Ready"
                return CmdResult(0)
            if "Start-ScheduledTask" in text:
                b.start_calls += 1
                b._starting = b.polls_until_up
                return CmdResult(0)
            if "Stop-LocalBackend.ps1" in text:
                b.stop_calls += 1
                if b.stop_fails:
                    return CmdResult(1, "", "Backend instance does not match local state.")
                b.up, b.task = False, ("Disabled" if "-DisableAutoStart" in text else "Ready")
                return CmdResult(0, "{}")
        raise AssertionError(f"unexpected command {argv}")

    def spawn(self, argv, *, cwd=None) -> int:
        raise AssertionError("spawn is not used by the RC module")


class FakeProcs:
    def __init__(self, pc: Path):
        self.pc = pc
        self.extra: dict[int, str] = {}

    def snapshot(self) -> dict[int, str]:
        try:
            procs = {int(k): v for k, v in json.loads((self.pc / "procs.json").read_text(encoding="utf-8")).items()}
        except (OSError, ValueError):
            procs = {}
        return {**procs, **self.extra}


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.pc = tmp / "pc"
        self.pc.mkdir()
        self.paths = Paths(tmp / "home", tmp / "rc")
        self.backend = FakeBackend()
        self.runner = FakeRunner(self.pc, self.backend)
        self.procs = FakeProcs(self.pc)
        self.packages = tmp / "packages"
        self.packages.mkdir()
        self.legacy = True  # the RC agent's older desktop build is on this fake PC unless a test says otherwise
        self.vr = {"available": True, "runtimes": ["SteamVR"], "steamvrRunning": False, "note": "VR runtime found: SteamVR"}
        self.set_clients({STEAM_ROOT: {"name": "Rec Room \u00b7 Steam installation", "evidence": "Installed Steam client"}})

    def set_clients(self, clients: dict) -> None:
        (self.pc / "pc.json").write_text(json.dumps({"clients": clients}), encoding="utf-8")

    def full_pc(self) -> None:
        self.set_clients({
            STEAM_ROOT: {"name": "Rec Room \u00b7 Steam installation", "evidence": "Installed Steam client"},
            CAMPUS_ROOT: {"name": "Campus \u00b7 existing installation", "launcherPath": CAMPUS_LAUNCHER, "exe": "Recroom_Release.exe",
                          "unity": "2021.3.1f1", "evidence": "Campus launcher's configured game directory"},
            NEXA_ROOT: {"name": "NexaNet \u00b7 existing installation", "modified": True,
                        "evidence": "Existing modified client; its own supported launcher is required"},
        })

    def tamper(self, root: str) -> None:
        iid = hashlib.md5(root.lower().encode()).hexdigest()
        (self.pc / "tamper.json").write_text(json.dumps([iid]), encoding="utf-8")

    def install_legacy_tools(self) -> None:
        exe = self.paths.legacy_tools_exe
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"legacy exe")
        files = {TOOLS_EXE: b"legacy exe", "a.dll": b"aaa"}
        (exe.parent / "a.dll").write_bytes(b"aaa")
        (exe.parent / "build-manifest.json").write_text(json.dumps(manifest_for(files)), encoding="utf-8")

    def make_package(self, version: str, *, extra: dict | None = None, folder: Path | None = None, bad_hash: bool = False) -> Path:
        folder = folder or self.packages
        files = {TOOLS_EXE: f"exe {version}".encode(), "lib/core.dll": b"core " + version.encode(), "readme.txt": b"hello"}
        files.update(extra or {})
        zpath = folder / f"Metallic-RC-{version}-tools-win-x64.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in files.items():
                zf.writestr(name, data)
            zf.writestr("build-manifest.json", json.dumps(manifest_for(files)))
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        if bad_hash:
            digest = "0" * 64
        sums = folder / "SHA256SUMS.txt"
        old = sums.read_text(encoding="utf-8") if sums.exists() else ""
        sums.write_text(old + f"{digest}  {zpath.name}\n", encoding="utf-8")
        return zpath

    def module(self, **kw) -> RcModule:
        if self.legacy and not self.paths.legacy_tools_exe.exists():
            self.install_legacy_tools()
        kw.setdefault("spawn", lambda fn: fn())  # tasks run inline: no sleeping, no races
        kw.setdefault("sleep", lambda s: None)
        kw.setdefault("confirm_seconds", 3.0)
        mod = RcModule(self.paths, runner=self.runner, procs=self.procs, fetch=self.backend.fetch, vr_detect=lambda: self.vr, **kw)
        mod.settings = {**mod.settings, "source": {"kind": "folder", "path": str(self.packages)}}
        return mod


def manifest_for(files: dict) -> dict:
    return {"schemaVersion": 1, "product": "Metallic-RC", "runtime": "win-x64", "sdk": "10.0.402",
            "files": [{"path": p, "bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()} for p, d in files.items()]}


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def finish(mod: RcModule, response: dict) -> dict:
    """Result of a started task (tasks run inline in tests)."""
    return mod.tasks.wait(response["task"]["id"], timeout=5)
