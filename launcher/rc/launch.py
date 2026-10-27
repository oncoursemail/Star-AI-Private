"""The things Play and the client cards do, as step-by-step jobs the progress UI can follow.

launch:    Preparing -> Client found -> Files checked -> Backend (optional) -> Plan -> Starting -> Running
register:  add a client to RC's catalog (read-only: fingerprints files, never changes them)
verify:    re-check a registered client's launch files against its baseline
rebaseline: accept the client's current files as the new baseline (explicit, after an update or mod)

The RC tools do the real work (`verify`, `plan`, `launch`); this module orders the steps, turns RC's answers into
plain messages and repair actions, and confirms from the process list whether the client actually came up.
"""
from __future__ import annotations

import ntpath
import time
from typing import Callable

from . import vr as vrmod
from .backend import BackendController
from .clients import Clients
from .cli import RcCli
from .errors import RcError
from .events import Reporter, SubReporter
from .proc import ProcessLister

LAUNCH_STAGES = [("prepare", "Preparing"), ("client", "Finding the client"), ("verify", "Checking files"),
                 ("backend", "RC backend"), ("plan", "Planning the start"), ("start", "Starting"), ("confirm", "Waiting for it to open")]
REGISTER_STAGES = [("inspect", "Reading the client's files"), ("register", "Recording the baseline")]
VERIFY_STAGES = [("verify", "Checking launch files")]


class ClientFlows:
    def __init__(self, cli: RcCli, backend: BackendController, clients: Clients, procs: ProcessLister, *,
                 settings: Callable[[], dict], vr_detect: Callable[[], dict] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, confirm_seconds: float = 15.0):
        self.cli, self.backend, self.clients, self.procs = cli, backend, clients, procs
        self.settings = settings
        self._vr = vr_detect or (lambda: vrmod.detect(processes=procs.snapshot))
        self._sleep, self._clock, self._wall, self.confirm_seconds = sleep, clock, wall, confirm_seconds

    # -- shared ---------------------------------------------------------------------------------------------------
    def entries(self) -> list[dict]:
        return self.clients.build(self.cli.discover(), self.cli.list())

    def _entry(self, key: str) -> dict:
        entry = Clients.find(self.entries(), key)
        if entry is None:
            raise RcError("client_missing", detail=f"unknown client {key}")
        return entry

    def _verify(self, installation_id: str, rep: Reporter) -> dict:
        result = self.cli.verify(installation_id, cancelled=lambda: rep.cancelled)
        errors = [i for i in result.get("issues", []) if i.get("severity") == "error"]
        self.clients.record_verification(installation_id, bool(result.get("isValid")), self._wall(), errors)
        return {"isValid": bool(result.get("isValid")), "errors": errors}

    @staticmethod
    def _changed_error(errors: list[dict]) -> RcError:
        names = [e.get("relativePath") or e.get("code", "") for e in errors]
        detail = "; ".join(f"{e.get('code')}: {e.get('relativePath') or ''}".strip() for e in errors[:8])
        err = RcError("files_changed", detail=detail)
        if names:
            err.message += f" First: {names[0]}" + (f" (and {len(names) - 1} more)." if len(names) > 1 else ".")
        return err

    # -- register / verify / rebaseline ---------------------------------------------------------------------------
    def register(self, rep: Reporter, key: str, *, launcher: str | None = None, folder: str | None = None,
                 name: str | None = None, replace: bool = False) -> dict:
        rep.stage("inspect", "Reading the client's files (nothing is changed)")
        entry = None
        if folder is None:
            entry = self._entry(key)
            folder = entry.get("installRoot")
            if not folder:
                raise RcError("client_missing", detail=key)
            launcher = launcher or entry.get("launcherPath")
            if entry["usesOwnLauncher"] and not launcher:
                raise RcError("external_launcher_required", detail=key)
        else:
            report = self.cli.inspect(folder, cancelled=lambda: rep.cancelled)
            if not report.get("canImport"):
                problems = [i.get("message", "") for i in report.get("issues", []) if i.get("severity") == "error"]
                raise RcError("client_missing", detail="; ".join(problems[:3]), message="That folder does not look like a complete Rec Room client.")
        display = name or (entry["name"] if entry else ntpath.basename(folder.rstrip("\\/")) or "Rec Room")
        rep.stage("register", "Recording the files' fingerprints")
        result = self.cli.import_(folder, display, launcher=launcher, replace=replace, cancelled=lambda: rep.cancelled)
        return {"installationId": result.get("id"), "name": result.get("displayName"), "replaced": replace}

    def verify(self, rep: Reporter, key: str) -> dict:
        rep.stage("verify", "Comparing launch files with the baseline")
        entry = self._entry(key)
        if not entry["installationId"]:
            raise RcError("installation_not_found", detail=key)
        out = self._verify(entry["installationId"], rep)
        return {"isValid": out["isValid"], "problems": [{"code": e.get("code"), "path": e.get("relativePath"), "message": e.get("message")} for e in out["errors"]]}

    def rebaseline(self, rep: Reporter, key: str) -> dict:
        entry = self._entry(key)
        if not entry["installationId"]:
            raise RcError("installation_not_found", detail=key)
        # Same folder, same name and launcher; RC's own --replace is the only thing that rewrites the baseline.
        return self.register(rep, key, launcher=entry.get("launcherPath") if entry["launcherRegistered"] else None, replace=True)

    # -- launch ---------------------------------------------------------------------------------------------------
    def launch(self, rep: Reporter, key: str, mode: str, *, confirm_external: bool = False) -> dict:
        warnings: list[str] = []
        rep.stage("prepare", "Checking the RC tools")
        if mode not in ("screen", "vr"):
            raise RcError("bad_request", detail=f"mode {mode}")
        self.cli.list()  # also proves the tools run at all (tools_missing / tools_corrupt / tools_timeout otherwise)

        rep.stage("client", "Looking for the client")
        entry = self._entry(key)
        state = entry["state"]
        if state == "not_found":
            raise RcError("client_missing", detail=key)
        if state == "needs_launcher":
            raise RcError("external_launcher_required", detail=key)
        installation_id = entry["installationId"]
        if state == "found":
            if entry["usesOwnLauncher"] and not entry.get("launcherPath"):
                raise RcError("external_launcher_required", detail=key)
            rep.note("Adding this client (read-only)")
            res = self.cli.import_(entry["installRoot"], entry["name"], launcher=entry.get("launcherPath") if entry["usesOwnLauncher"] else None,
                                   cancelled=lambda: rep.cancelled)
            installation_id = res["id"]
            entry = self._entry(key)

        rep.stage("verify", "Comparing launch files with the baseline")
        out = self._verify(installation_id, rep)
        if not out["isValid"]:
            raise self._changed_error(out["errors"])

        rep.stage("backend", "Looking at the RC backend")
        bs = self.backend.status()
        if bs["state"] != "running" and self.settings().get("startBackendWithClient"):
            self.backend.start(SubReporter(rep))
            bs = self.backend.status(with_task=False)
        if bs["state"] != "running":
            warnings.append("The RC backend is not running, so Metallic rooms and accounts are unavailable. The client starts with its own services.")

        external = bool(entry["launcherRegistered"]) and entry["usesOwnLauncher"]
        if external:
            if not confirm_external:
                raise RcError("external_launcher_unconfirmed", detail=entry.get("launcherPath") or "",
                              message=f"This opens {entry['name']}'s own launcher ({ntpath.basename(entry['launcherPath'])}), not Metallic's. "
                                      "It then starts the game and handles screen or VR itself.")
            if mode == "vr":
                warnings.append("The client's own launcher chooses screen or VR itself; the mode here is ignored.")
        elif mode == "vr":
            info = self._vr()
            if not info["available"]:
                warnings.append(info["note"])

        rep.stage("plan", "Asking RC for the exact start command")
        target = "external" if external else "client"
        plan = self.cli.plan(installation_id, mode=mode, target=target, approved_launcher=entry["launcherPath"] if external else None)
        if not plan.get("canExecuteOnCurrentPlatform", False):
            raise RcError("platform_not_supported", detail=plan.get("blockReason") or "")
        exe = plan["executablePath"]
        command = " ".join([ntpath.basename(exe), *plan.get("arguments", [])])
        rep.note(command)

        rep.stage("start", command)
        result = self.cli.launch(installation_id, mode=mode, target=target, approved_launcher=entry["launcherPath"] if external else None)
        pid = int(result.get("processId") or 0)

        rep.stage("confirm", "Waiting for it to open")
        wanted = {ntpath.basename(exe).lower()}
        began = self._clock()
        seen = False
        while self._clock() - began < self.confirm_seconds:
            rep.progress(min((self._clock() - began) / self.confirm_seconds, 0.95))
            procs = self.procs.snapshot()
            if pid in procs or wanted & set(procs.values()) or (external and {"recroom.exe", "recroom_release.exe"} & set(procs.values())):
                seen = True
                break
            self._sleep(0.5)
        if not seen:
            raise RcError("exited_early", detail=f"{command}, pid {pid}")
        return {"processId": pid, "command": command, "mode": mode, "target": target, "running": True,
                "warnings": warnings, "client": entry["key"], "backend": bs["state"]}
