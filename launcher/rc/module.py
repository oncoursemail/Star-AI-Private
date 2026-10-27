"""RcModule: the one object the launcher talks to for everything Metallic RC.

Contract with the launcher shell (Qt-free, JSON in and out):

    module = RcModule()                         # real paths from the environment; tests inject fakes
    module.call("overview", {})        -> dict  # quick calls return their answer straight away
    module.call("launch.start", {...}) -> {"task": {...}}   # long jobs return a task snapshot; progress arrives as events
    module.call_async(rid, method, params)      # same, on a worker thread; the answer arrives as a "reply" event
    unsubscribe = module.subscribe(fn)          # fn(event: dict): {"type": "task"|"reply"|"log", ...}

A call that fails raises RcError (`err.to_dict()` is what the UI shows: title, message, repair actions). Methods are
listed in METHODS; repair buttons call `repair.run` with an action id from the error.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import installer as inst
from . import vr as vrmod
from .backend import BackendController
from .cli import RcCli
from .clients import Clients
from .errors import ACTIONS, RcError
from .events import EventBus, TaskManager
from .installer import ToolsInstaller
from .launch import LAUNCH_STAGES, REGISTER_STAGES, VERIFY_STAGES, ClientFlows
from .paths import STEAM_APP_ID, Paths
from .proc import ProcessLister, Runner, SubprocessRunner, WindowsProcesses

MODULE_ID = "rc"
DEFAULT_SETTINGS = {"mode": "screen", "startBackendWithClient": False, "source": {}, "lastClient": "steam"}
STEAM_STORE_URL = f"https://store.steampowered.com/app/{STEAM_APP_ID}/"

TOOLS_STAGES = [("check", "Looking for the newest RC tools"), ("download", "Getting the package"),
                ("verify", "Checking the package"), ("unpack", "Unpacking and checking files"), ("switch", "Switching over")]
REPAIR_STAGES = [("inspect", "Checking RC tool files"), *TOOLS_STAGES]
BACKEND_START_STAGES = [("check", "Checking the backend"), ("start", "Starting the task"), ("wait", "Waiting for it to answer")]
BACKEND_STOP_STAGES = [("check", "Checking the backend"), ("stop", "Asking it to stop"), ("wait", "Waiting for it to finish")]


def _validate_settings(data) -> dict:
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if not isinstance(data, dict):
        return out
    if data.get("mode") in ("screen", "vr"):
        out["mode"] = data["mode"]
    if isinstance(data.get("startBackendWithClient"), bool):
        out["startBackendWithClient"] = data["startBackendWithClient"]
    src = data.get("source")
    if isinstance(src, dict):
        if src.get("kind") == "folder" and isinstance(src.get("path"), str) and 0 < len(src["path"]) < 1024:
            out["source"] = {"kind": "folder", "path": src["path"]}
        elif src.get("kind") == "url" and isinstance(src.get("url"), str) and src["url"].startswith(("http://", "https://")) and len(src["url"]) < 1024:
            out["source"] = {"kind": "url", "url": src["url"]}
    if isinstance(data.get("lastClient"), str) and len(data["lastClient"]) < 80:
        out["lastClient"] = data["lastClient"]
    return out


class RcModule:
    id = MODULE_ID

    def __init__(self, paths: Paths | None = None, *, runner: Runner | None = None, procs: ProcessLister | None = None,
                 fetch=None, spawn=None, vr_detect: Callable[[], dict] | None = None, confirm_seconds: float = 15.0,
                 sleep: Callable[[float], None] = time.sleep):
        self.paths = paths or Paths.from_env()
        self.runner = runner or SubprocessRunner(str(self.paths.module_dir / "tmp"))
        self.procs = procs or WindowsProcesses()
        self.bus = EventBus()
        self.tasks = TaskManager(self.bus, spawn=spawn)
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rc-call")
        self.settings = self._load_settings()
        self.installer = ToolsInstaller(self.paths, smoke=self._smoke)
        self.cli = RcCli(self.installer.exe, self.paths.state_dir, self.runner)
        kw = {"fetch": fetch} if fetch else {}
        self.backend = BackendController(self.paths, self.runner, sleep=sleep, **kw)
        self.clients = Clients()
        self.flows = ClientFlows(self.cli, self.backend, self.clients, self.procs, settings=lambda: self.settings,
                                 vr_detect=vr_detect, sleep=sleep, confirm_seconds=confirm_seconds)
        self.bus.subscribe(self._log_task_events)
        self._logged: dict[str, str] = {}
        self.methods: dict[str, Callable[[dict], dict]] = {
            "overview": self.overview,
            "tools.status": lambda p: self.installer.status(),
            "tools.check_update": self._check_update,
            "tools.install": lambda p: self._tools_task("install", "Installing RC tools", TOOLS_STAGES, self._do_install),
            "tools.update": lambda p: self._tools_task("update", "Updating RC tools", TOOLS_STAGES, self._do_install),
            "tools.verify": lambda p: self._tools_task("verify", "Checking RC tools", [("verify", "Checking every file")], self.installer.verify),
            "tools.repair": lambda p: self._tools_task("repair", "Repairing RC tools", REPAIR_STAGES, self._do_repair),
            "tools.rollback": self._rollback,
            "backend.status": lambda p: self.backend.status(),
            "backend.start": self._backend_start,
            "backend.stop": self._backend_stop,
            "backend.logs": lambda p: {"lines": self.backend.logs(int(p.get("lines", 80)))},
            "clients.list": self._clients_list,
            "clients.register": self._clients_register,
            "clients.verify": self._clients_verify,
            "clients.rebaseline": self._clients_rebaseline,
            "vr.status": lambda p: self._vr_info(),
            "launch.start": self._launch,
            "task.cancel": lambda p: {"cancelled": self.tasks.cancel(str(p.get("id", "")))},
            "task.list": lambda p: {"active": self.tasks.active(), "recent": self.tasks.recent(int(p.get("n", 10)))},
            "settings.get": lambda p: dict(self.settings),
            "settings.set": self._settings_set,
            "repair.run": self._repair_run,
            "log.tail": lambda p: {"lines": self.log_tail(int(p.get("lines", 100)))},
        }

    # -- plumbing -------------------------------------------------------------------------------------------------
    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        return self.bus.subscribe(fn)

    def call(self, method: str, params: dict | None = None) -> dict:
        fn = self.methods.get(method)
        if fn is None:
            raise RcError("bad_request", detail=f"unknown method {method}")
        return fn(params if isinstance(params, dict) else {})

    def call_async(self, rid: str, method: str, params: dict | None = None) -> None:
        """Run `call` on a worker thread; the result (or the problem) arrives as {"type":"reply","id":rid,...}."""
        def work() -> None:
            try:
                self.bus.emit({"type": "reply", "id": rid, "ok": True, "result": self.call(method, params)})
            except RcError as err:
                self.bus.emit({"type": "reply", "id": rid, "ok": False, "error": err.to_dict()})
            except Exception as exc:
                self._log(f"call {method} crashed: {type(exc).__name__}: {exc}")
                self.bus.emit({"type": "reply", "id": rid, "ok": False, "error": RcError(
                    "rc_error", detail=f"{type(exc).__name__}: {exc}", message="Something unexpected went wrong.").to_dict()})
        self._pool.submit(work)

    def call_json(self, method: str, params_json: str = "") -> str:
        """For a string-only bridge: JSON in, JSON out, errors as {"error": {...}}."""
        try:
            params = json.loads(params_json) if params_json else {}
            return json.dumps({"ok": True, "result": self.call(method, params)})
        except RcError as err:
            return json.dumps({"ok": False, "error": err.to_dict()})
        except ValueError:
            return json.dumps({"ok": False, "error": RcError("bad_request", detail="bad JSON").to_dict()})

    def close(self) -> None:
        for t in self.tasks.active():
            self.tasks.cancel(t["id"])
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- settings and log -----------------------------------------------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            return _validate_settings(json.loads(self.paths.settings_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return _validate_settings(None)

    def _settings_set(self, p: dict) -> dict:
        merged = dict(self.settings, **{k: v for k, v in p.items() if k in DEFAULT_SETTINGS})
        self.settings = _validate_settings(merged)
        self.paths.module_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.paths.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, indent=1), encoding="utf-8")
        os.replace(tmp, self.paths.settings_file)
        return dict(self.settings)

    def _log(self, line: str) -> None:
        try:
            self.paths.module_dir.mkdir(parents=True, exist_ok=True)
            log = self.paths.log_file
            if log.exists() and log.stat().st_size > 512_000:
                log.replace(log.with_suffix(".log.1"))
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line.replace("\n", " ")[:600] + "\n")
        except OSError:
            pass

    def log_tail(self, lines: int = 100) -> list[str]:
        try:
            return self.paths.log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(lines, 500)):]
        except OSError:
            return []

    def _log_task_events(self, ev: dict) -> None:
        if ev.get("type") != "task":
            return
        t = ev["task"]
        if t["state"] in ("done", "failed", "cancelled") and self._logged.get(t["id"]) != t["state"]:
            self._logged[t["id"]] = t["state"]
            err = t.get("error") or {}
            self._log(f"{t['kind']} {t['id']} {t['state']}" + (f" [{err.get('code')}] {err.get('detail') or err.get('message')}" if err else ""))

    # -- overview -------------------------------------------------------------------------------------------------
    def overview(self, p: dict) -> dict:
        """Everything the RC page draws, gathered in parallel (the slow parts are other programs and the network)."""
        out: dict = {"settings": dict(self.settings), "tools": self.installer.status(), "tasks": self.tasks.active(),
                     "steamUrl": STEAM_STORE_URL}
        parts = {"clients": self.flows.entries, "backend": self.backend.status, "vr": self._vr_info}
        with ThreadPoolExecutor(max_workers=len(parts), thread_name_prefix="rc-overview") as pool:  # not self._pool: no nested waits
            futures = {k: pool.submit(fn) for k, fn in parts.items()}
            return self._overview_collect(out, futures)

    def _overview_collect(self, out: dict, futures: dict) -> dict:
        try:
            out["clients"] = futures["clients"].result()
        except RcError as err:
            out["clients"], out["clientsError"] = self._clients_fallback(), err.to_dict()
        out["backend"] = futures["backend"].result()
        out["vr"] = futures["vr"].result()
        return out

    def _clients_fallback(self) -> list[dict]:
        """With no working RC tools every client shows as 'not checked': the list still draws, and Play explains why."""
        return self.clients.build([], [])

    def _vr_info(self) -> dict:
        return vrmod.detect(processes=self.procs.snapshot)

    # -- tools ----------------------------------------------------------------------------------------------------
    def _source(self):
        return ToolsInstaller.make_source(self.settings.get("source"), self.paths)

    def _smoke(self, exe: Path) -> None:
        RcCli(lambda: exe, self.paths.state_dir, self.runner).list()  # the new package must run and read the catalog

    def _check_update(self, p: dict) -> dict:
        return self.installer.check_update(self._source())

    def _do_install(self, rep) -> dict:
        return self.installer.install(self._source(), rep)

    def _do_repair(self, rep) -> dict:
        return self.installer.repair(self._source(), rep)

    def _tools_task(self, kind: str, title: str, stages, job) -> dict:
        return {"task": self.tasks.start("tools", title, stages, job, exclusive=("launch", "client")) | {"op": kind}}

    def _rollback(self, p: dict) -> dict:
        busy = [t for t in self.tasks.active() if t["kind"] in ("tools", "launch", "client")]
        if busy:
            raise RcError("busy")
        return self.installer.rollback()

    # -- backend --------------------------------------------------------------------------------------------------
    def _backend_start(self, p: dict) -> dict:
        enable = bool(p.get("enable"))
        return {"task": self.tasks.start("backend", "Starting the RC backend", BACKEND_START_STAGES,
                                         lambda rep: self.backend.start(rep, enable=enable))}

    def _backend_stop(self, p: dict) -> dict:
        disable = bool(p.get("disableAutoStart"))
        return {"task": self.tasks.start("backend", "Stopping the RC backend", BACKEND_STOP_STAGES,
                                         lambda rep: self.backend.stop(rep, disable_autostart=disable))}

    # -- clients --------------------------------------------------------------------------------------------------
    def _clients_list(self, p: dict) -> dict:
        return {"clients": self.flows.entries()}

    def _key(self, p: dict) -> str:
        key = p.get("client") or p.get("key")
        if not isinstance(key, str) or not key or len(key) > 80:
            raise RcError("bad_request", detail="client is required")
        return key

    def _clients_register(self, p: dict) -> dict:
        key, launcher, folder = self._key(p), p.get("launcher"), p.get("folder")
        if launcher is not None and not isinstance(launcher, str) or folder is not None and not isinstance(folder, str):
            raise RcError("bad_request", detail="launcher and folder must be paths")
        return {"task": self.tasks.start("client", "Adding a client", REGISTER_STAGES,
                                         lambda rep: self.flows.register(rep, key, launcher=launcher, folder=folder, name=p.get("name")),
                                         exclusive=("launch", "tools"))}

    def _clients_verify(self, p: dict) -> dict:
        key = self._key(p)
        return {"task": self.tasks.start("client", "Checking client files", VERIFY_STAGES, lambda rep: self.flows.verify(rep, key),
                                         exclusive=("launch", "tools"))}

    def _clients_rebaseline(self, p: dict) -> dict:
        key = self._key(p)
        if p.get("confirm") is not True:
            raise RcError("bad_request", detail="rebaseline needs confirm: true", message="Accepting new files as the baseline needs your confirmation.")
        return {"task": self.tasks.start("client", "Accepting the current files", REGISTER_STAGES, lambda rep: self.flows.rebaseline(rep, key),
                                         exclusive=("launch", "tools"))}

    # -- launch ---------------------------------------------------------------------------------------------------
    def _launch(self, p: dict) -> dict:
        key = self._key(p)
        mode = p.get("mode") or self.settings["mode"]
        confirm = p.get("confirmExternal") is True
        self._settings_set({"lastClient": key, **({"mode": mode} if mode in ("screen", "vr") else {})})
        return {"task": self.tasks.start("launch", "Starting Rec Room", LAUNCH_STAGES,
                                         lambda rep: self.flows.launch(rep, key, mode, confirm_external=confirm),
                                         exclusive=("tools", "client"))}

    # -- repair buttons -------------------------------------------------------------------------------------------
    def _repair_run(self, p: dict) -> dict:
        action = p.get("action")
        if action not in ACTIONS:
            raise RcError("bad_request", detail=f"unknown action {action}")
        a = p.get("params") if isinstance(p.get("params"), dict) else {}
        if action in ("install_tools",):
            return self.call("tools.install")
        if action == "repair_tools":
            return self.call("tools.repair")
        if action == "rollback_tools":
            return self.call("tools.rollback")
        if action == "start_backend":
            return self.call("backend.start")
        if action == "enable_and_start":
            return self.call("backend.start", {"enable": True})
        if action == "restart_backend":
            return {"task": self.tasks.start("backend", "Restarting the RC backend", BACKEND_START_STAGES, self._restart_backend)}
        if action == "register_client":
            return self.call("clients.register", a)
        if action == "rebaseline":
            return self.call("clients.rebaseline", dict(a, confirm=a.get("confirm") is True))
        if action == "use_screen":
            self._settings_set({"mode": "screen"})
            return {"settings": dict(self.settings), "message": "Screen mode is on."}
        if action == "install_from_steam":
            return {"openUrl": STEAM_STORE_URL}
        if action == "view_log":
            return {"lines": self.log_tail(100)}
        if action == "open_vr_help":
            return {"help": ["Start SteamVR, or pick an OpenXR runtime in your headset's app.",
                             "Then choose VR again. Screen mode works without any of this."]}
        if action in ("locate_client", "register_launcher"):
            return {"needsInput": "folder" if action == "locate_client" else "launcher"}
        if action == "retry":
            return {"retry": True}
        raise RcError("bad_request", detail=action)

    def _restart_backend(self, rep) -> dict:
        from .events import SubReporter
        self.backend.stop(SubReporter(rep))
        rep.stage("start", "Starting the task")
        return self.backend.start(SubReporter(rep))
