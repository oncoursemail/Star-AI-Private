"""`metallic control serve --config control.toml`: collector + API + UI in one process.

The config lives only on the collector host (it names private hosts); server/control/control.example.toml shows the
shape with placeholders.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import tomllib

from .actions import Runner
from .collector import Collector, _read_secret
from .server import App, Auth, serve
from .store import Store


def load_config(path: str | Path) -> dict:
    conf = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    ids = [m.get("id") for m in conf.get("machine", [])]
    if len(ids) != len(set(ids)) or not all(ids):
        raise ValueError("every [[machine]] needs a unique id")
    return conf


def ssh_base(conf: dict) -> list[str]:
    base = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3"]
    if conf.get("ssh_key"):
        base += ["-i", conf["ssh_key"], "-o", "IdentitiesOnly=yes"]
    if conf.get("known_hosts"):
        base += ["-o", f"UserKnownHostsFile={conf['known_hosts']}", "-o", "StrictHostKeyChecking=yes"]
    return base


def new_token() -> str:
    return secrets.token_urlsafe(32)


def write_token(path: str | Path) -> None:
    """A fresh token in an owner-only file (refuses to overwrite: delete the old file on purpose first)."""
    p = Path(path)
    if p.exists():
        raise FileExistsError(f"{p} exists; delete it first to rotate the token")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(new_token() + "\n")


def run(config_path: str) -> int:
    conf = load_config(config_path)
    store = Store(conf.get("db", "control.sqlite3"))
    machines = conf.get("machine", [])
    base = ssh_base(conf)
    runner = Runner(store, machines, base, conf.get("audit_file"))
    collector = Collector(conf, store, runner)
    auth = Auth(_read_secret(conf["login_token_file"]), _read_secret(conf["push_token_file"]))
    host = conf.get("listen", "0.0.0.0")
    servers = [serve(App(collector, store, runner, auth, machines, conf.get("ui")), host, int(conf.get("port", 8470)))]
    if conf.get("tls_port") and conf.get("tls_cert") and conf.get("tls_key"):
        servers.append(serve(App(collector, store, runner, auth, machines, conf.get("ui"), secure_cookie=True), host,
                             int(conf["tls_port"]), (conf["tls_cert"], conf["tls_key"])))
    collector.start(base)
    print(f"metallic control: listening on {host}:{conf.get('port', 8470)}"
          + (f" and https {conf['tls_port']}" if len(servers) > 1 else ""), file=sys.stderr, flush=True)
    done = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: done.set())
    done.wait()
    collector.stop.set()
    for s in servers:
        s.shutdown()
    return 0
