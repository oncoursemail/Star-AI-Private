"""Status, start and stop for the owned RC backend on this PC (the Metallic-RC-Backend scheduled task, port 4187).

Uses only what the RC agent ships: GET /healthz /readyz /metallic/v1/capabilities on 127.0.0.1, the Windows task,
and ops/Stop-LocalBackend.ps1 for a graceful stop. Never reads or sends the admin key (the stop script does that
itself), never talks to anything but loopback, never follows a redirect.

The status is honest about what the backend is: an owned service for Metallic accounts and rooms. The original game
has not logged into it, and `nativeClientVerified` stays false until the RC capabilities say otherwise.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .errors import RcError
from .events import Reporter
from .paths import BACKEND_PORT, BACKEND_TASK, Paths
from .proc import Runner

SERVICE = "metallic-rc-backend"
Fetch = Callable[[str, float], tuple[int, dict | None]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_fetch(url: str, timeout: float) -> tuple[int, dict | None]:
    """GET a loopback URL. Returns (status, json-or-None). Raises OSError when nothing answers."""
    if not url.startswith("http://127.0.0.1:"):
        raise OSError("loopback only")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(url, timeout=timeout) as resp:
            body = resp.read(200_000)
            status = resp.status
    except urllib.error.HTTPError as err:
        return err.code, None
    except urllib.error.URLError as err:
        raise OSError(str(err.reason)) from err
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return status, data if isinstance(data, dict) else None


class BackendController:
    def __init__(self, paths: Paths, runner: Runner, *, fetch: Fetch = http_fetch,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.paths, self.runner, self._fetch, self._sleep, self._clock = paths, runner, fetch, sleep, clock

    # -- identity -------------------------------------------------------------------------------------------------
    def deployment(self) -> dict:
        try:
            data = json.loads((self.paths.backend_dir / "deployment.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        port = data.get("port")
        task = data.get("taskName")
        return {"port": port if isinstance(port, int) and 1024 <= port <= 65535 else BACKEND_PORT,
                "task": task if task == BACKEND_TASK else BACKEND_TASK,
                "deployed": bool(data)}

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.deployment()['port']}{path}"

    # -- the Windows task -----------------------------------------------------------------------------------------
    def task_state(self) -> str:
        """'Running', 'Ready', 'Disabled', ... or 'absent'. Empty string if the query itself failed."""
        task = self.deployment()["task"]
        ps = (f"$t = Get-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue; "
              f"if ($null -eq $t) {{ 'absent' }} else {{ [string]$t.State }}")
        res = self.runner.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=20)
        return res.stdout.strip().splitlines()[-1].strip() if res.code == 0 and res.stdout.strip() else ""

    # -- status ---------------------------------------------------------------------------------------------------
    def status(self, *, with_task: bool = True) -> dict:
        dep = self.deployment()
        out = {"state": "stopped", "port": dep["port"], "task": None, "instanceId": None, "ready": False,
               "nativeClientReady": False, "actualGameClientVerified": False, "implemented": {},
               "honesty": "This is Metallic's own RC backend. The original Rec Room client has not logged into it.",
               "checkedAt": time.time()}
        try:
            code, health = self._fetch(self._url("/healthz"), 1.5)
        except OSError:
            code, health = 0, None
        if code == 200 and health and health.get("service") == SERVICE:
            out.update(state="running", instanceId=health.get("instanceId"))
            for path, apply in (("/readyz", self._apply_ready), ("/metallic/v1/capabilities", self._apply_caps)):
                try:
                    c, d = self._fetch(self._url(path), 2.0)
                    if c == 200 and d:
                        apply(out, d)
                except OSError:
                    pass
            return out
        if code:  # something answered, but it is not us (or it answered badly)
            out["state"] = "unhealthy" if code >= 500 else "conflict"
            return out
        if with_task:
            task = self.task_state()
            out["task"] = task or None
            out["state"] = {"absent": "not_installed", "Disabled": "disabled", "Running": "unhealthy"}.get(task, "stopped")
        return out

    @staticmethod
    def _apply_ready(out: dict, d: dict) -> None:
        out["ready"] = d.get("status") == "owned-backend-ready"
        out["nativeClientReady"] = bool(d.get("nativeClientReady"))

    @staticmethod
    def _apply_caps(out: dict, d: dict) -> None:
        comp = d.get("compatibility") if isinstance(d.get("compatibility"), dict) else {}
        out["actualGameClientVerified"] = bool(comp.get("actualGameClientVerified"))
        out["implemented"] = {k: bool(v) for k, v in (d.get("implemented") or {}).items()} if isinstance(d.get("implemented"), dict) else {}
        out["native"] = {k: bool(comp.get(k)) for k in ("nativeLogin", "nativeRoomJoin", "nativeGameplay", "nativeVoice")}

    def error_for(self, status: dict) -> RcError | None:
        """The problem a non-running status represents (None when running)."""
        return {
            "running": None,
            "stopped": RcError("backend_stopped"),
            "disabled": RcError("backend_disabled"),
            "not_installed": RcError("backend_task_missing"),
            "conflict": RcError("backend_conflict", detail=f"port {status['port']}"),
            "unhealthy": RcError("backend_unhealthy", detail=f"task {status.get('task')}"),
        }.get(status["state"], RcError("backend_stopped"))

    # -- start / stop ---------------------------------------------------------------------------------------------
    def start(self, rep: Reporter, *, enable: bool = False, wait: float = 45.0) -> dict:
        rep.stage("check", "Checking the backend")
        st = self.status()
        if st["state"] == "running":
            rep.skip("start"), rep.skip("wait")
            return {"state": "running", "changed": False}
        if st["state"] in ("conflict", "not_installed"):
            raise self.error_for(st)
        task = self.deployment()["task"]
        if st["state"] == "disabled":
            if not enable:
                raise RcError("backend_disabled")
            self._powershell(f"Enable-ScheduledTask -TaskName '{task}' | Out-Null", "enable the task")
        rep.stage("start", "Asking Windows to start the backend task")
        if st["state"] != "unhealthy":  # a task that is already running is only slow; do not start a second one
            self._powershell(f"Start-ScheduledTask -TaskName '{task}'", "start the task")
        rep.stage("wait", "Waiting for it to answer")
        began = self._clock()
        while self._clock() - began < wait:
            rep.progress(min((self._clock() - began) / wait, 0.95))
            cur = self.status(with_task=False)
            if cur["state"] == "running":
                return {"state": "running", "changed": True, "seconds": round(self._clock() - began, 1)}
            self._sleep(0.5)
        raise RcError("backend_start_timeout", detail=f"{wait:.0f}s")

    def stop(self, rep: Reporter, *, disable_autostart: bool = False, wait: float = 20.0) -> dict:
        rep.stage("check", "Checking the backend")
        st = self.status(with_task=False)
        if st["state"] != "running":
            rep.skip("stop"), rep.skip("wait")
            return {"state": st["state"], "changed": False}
        script = self.paths.backend_dir / "ops" / "Stop-LocalBackend.ps1"
        if not script.is_file():
            raise RcError("backend_task_missing", detail=f"{script} not found")
        rep.stage("stop", "Asking the backend to shut down cleanly")
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-File", str(script)]
        if disable_autostart:
            argv.append("-DisableAutoStart")
        res = self.runner.run(argv, timeout=30, cancelled=lambda: rep.cancelled)
        if res.code != 0:
            raise RcError("backend_unhealthy", detail=(res.stderr or res.stdout)[:300],
                          message="The backend refused to stop cleanly, so it was left running.")
        rep.stage("wait", "Waiting for it to finish")
        began = self._clock()
        while self._clock() - began < wait:
            if self.status(with_task=False)["state"] != "running":
                return {"state": "stopped", "changed": True}
            self._sleep(0.4)
        raise RcError("backend_unhealthy", detail="still answering after the stop request")

    def _powershell(self, command: str, what: str) -> None:
        res = self.runner.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=30)
        if res.code != 0:
            raise RcError("backend_unhealthy", detail=f"could not {what}: {(res.stderr or res.stdout)[:300]}")

    def logs(self, lines: int = 80) -> list[str]:
        """The last lines of the backend's own log (read only)."""
        path = self.paths.backend_dir / "logs" / "backend.log"
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 64_000))
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            return []
        return text.splitlines()[-lines:]
