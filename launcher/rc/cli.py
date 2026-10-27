"""Thin client for the RC tools' command line (Metallic.RC.Launcher.exe), the interface the RC agent owns.

Every command prints JSON on stdout (or {"error","message"} on stderr with exit 1). Exit 2 on `verify`/`inspect` and
exit 3 on `plan` still carry a JSON result: they mean "checked, and the answer is no", not "the tool broke".
This module never edits RC's files; it only calls the tool and reads the answer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .errors import Cancelled, RcError, from_rc
from .proc import Runner

_ID = re.compile(r"[0-9a-f]{32}")


class RcCli:
    def __init__(self, exe: Callable[[], Path | None], state_dir: Path, runner: Runner):
        self._exe, self.state_dir, self.runner = exe, Path(state_dir), runner

    def _run(self, args: list[str], *, timeout: float, ok: tuple[int, ...] = (0,),
             cancelled: Callable[[], bool] | None = None, state: bool = True):
        exe = self._exe()
        if not exe or not Path(exe).is_file():
            raise RcError("tools_missing")
        argv = [str(exe), *args]
        if state:
            argv += ["--state-dir", str(self.state_dir)]
        try:
            res = self.runner.run(argv, timeout=timeout, cwd=str(Path(exe).parent), cancelled=cancelled)
        except OSError as exc:  # missing runtime DLL, blocked file, bad PE
            raise RcError("tools_corrupt", detail=f"{type(exc).__name__}: {exc}") from exc
        if cancelled and cancelled():
            raise Cancelled()
        if res.timed_out:
            raise RcError("tools_timeout", detail=f"{args[0]} after {timeout:.0f}s")
        data = _json(res.stdout)
        if res.code in ok and data is not None:
            return res.code, data
        err = _json(res.stderr) or data
        if isinstance(err, dict) and "error" in err:
            raise from_rc(str(err["error"]), str(err.get("message", "")))
        raise RcError("tools_bad_output", detail=f"{args[0]} exit {res.code}: {(res.stderr or res.stdout)[:300]}")

    # -- read-only ----------------------------------------------------------------------------------------------
    def discover(self) -> list[dict]:
        """Known client locations RC can see on this PC (Steam, Campus, NexaNet, Meow.Net)."""
        return self._run(["discover"], timeout=30, state=False)[1]

    def list(self) -> list[dict]:
        return self._run(["list"], timeout=30)[1]

    def inspect(self, folder: str, cancelled=None) -> dict:
        return self._run(["inspect", str(folder)], timeout=300, ok=(0, 2), cancelled=cancelled, state=False)[1]

    def verify(self, installation_id: str, cancelled=None) -> dict:
        """Returns {installation, currentInventory, issues, isValid}. `isValid` False is an answer, not an error."""
        _check_id(installation_id)
        return self._run(["verify", installation_id], timeout=300, ok=(0, 2), cancelled=cancelled)[1]

    def plan(self, installation_id: str, *, mode: str = "screen", target: str = "client", approved_launcher: str | None = None) -> dict:
        _check_id(installation_id)
        return self._run(["plan", installation_id, *_launch_args(mode, target, approved_launcher)], timeout=300, ok=(0, 3))[1]

    # -- changes (each one is explicit and recorded by RC) ------------------------------------------------------
    def import_(self, folder: str, name: str, *, launcher: str | None = None, replace: bool = False, cancelled=None) -> dict:
        args = ["import", str(folder), "--name", name]
        if launcher:
            args += ["--launcher", str(launcher)]
        if replace:
            args.append("--replace")
        return self._run(args, timeout=600, cancelled=cancelled)[1]

    def launch(self, installation_id: str, *, mode: str = "screen", target: str = "client", approved_launcher: str | None = None) -> dict:
        """Starts the client (or its own launcher). Returns RC's LaunchResult: {processId, startedAtUtc, plan}."""
        _check_id(installation_id)
        return self._run(["launch", installation_id, *_launch_args(mode, target, approved_launcher)], timeout=300)[1]


def _launch_args(mode: str, target: str, approved: str | None) -> list[str]:
    if mode not in ("screen", "vr") or target not in ("client", "external"):
        raise RcError("bad_request", detail=f"mode={mode} target={target}")
    args = ["--mode", mode, "--target", target]
    if approved:
        args += ["--approved-launcher", str(approved)]
    return args


def _check_id(installation_id: str) -> None:
    if not isinstance(installation_id, str) or not _ID.fullmatch(installation_id):
        raise RcError("bad_request", detail="installation id must be 32 hex characters")


def _json(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None
