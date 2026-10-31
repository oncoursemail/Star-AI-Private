"""`python -m metallic.api init|serve|key|check`. Config: server/api/api.example.toml."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading
import time
import tomllib

from .auth import Auth, Sealer
from .server import serve
from .service import Api
from .sources import Content
from .spec import Spec
from .store import Store
from .upstream import Accounts
from .webhooks import Webhooks

DOCS = Path(__file__).with_name("docs") / "index.html"


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def init_keys(directory: str | Path) -> list[str]:
    p = Path(directory) / "data-key"
    if p.exists():
        return []
    _write_private(p, os.urandom(32))
    return ["data-key"]


def load(path: str) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def build(conf: dict, clock=time.time, sender=None) -> tuple[Api, Store]:
    store = Store(conf.get("db", "metallic-api.sqlite3"), conf.get("audit_file"))
    fp = conf.get("accounts_fingerprint")
    if not fp and conf.get("accounts_fingerprint_file"):
        fp = Path(conf["accounts_fingerprint_file"]).read_text(encoding="utf-8").strip()
    accounts = Accounts(conf["accounts_url"], fingerprint=fp, cafile=conf.get("accounts_cafile"))
    sealer = Sealer((Path(conf["key_dir"]) / "data-key").read_bytes())
    hooks_kw = {"sender": sender} if sender else {}
    hooks = Webhooks(store, sealer, clock, allow_hosts=tuple(conf.get("webhook_allow_hosts", ())), **hooks_kw)
    docs = DOCS.read_bytes() if DOCS.is_file() else None
    api = Api(store, accounts, Content(store, clock, conf), hooks, sealer, clock,
              allowed_origins=tuple(conf.get("allowed_origins", ())), docs_html=docs)
    return api, store


def run(config_path: str) -> int:
    conf = load(config_path)
    api, _ = build(conf)
    problems = api.spec.check(set(api.handlers))
    if problems:
        print("openapi.json and the code disagree:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    tls = (conf["tls_cert"], conf["tls_key"]) if conf.get("tls_cert") else None
    if tls is None and not conf.get("allow_plain_http_for_tests"):
        print("refusing to serve without tls_cert/tls_key", file=sys.stderr)
        return 2
    host, port = conf.get("listen", "0.0.0.0"), int(conf.get("port", 8476))
    server = serve(api, host, port, tls)
    api.webhooks.start()
    done = threading.Event()

    def watch():
        while not done.wait(float(conf.get("release_watch_seconds", 60))):
            try:
                api.content.watch_releases(api.webhooks.emit)
            except Exception as exc:          # noqa: BLE001
                print(f"release watch: {type(exc).__name__}", file=sys.stderr, flush=True)
    try:
        api.content.watch_releases(api.webhooks.emit)      # first sight is recorded silently
    except Exception:                                     # noqa: BLE001
        pass
    threading.Thread(target=watch, daemon=True, name="release-watch").start()

    def revivals():
        while True:
            try:
                api.content.revivals.sample()
            except Exception as exc:          # noqa: BLE001
                print(f"revival sample: {type(exc).__name__}", file=sys.stderr, flush=True)
            if done.wait(float(conf.get("revival_sample_seconds", 300))):
                return
    threading.Thread(target=revivals, daemon=True, name="revival-sample").start()
    print(f"metallic api: listening on {host}:{port} ({'https' if tls else 'http'})", file=sys.stderr, flush=True)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: done.set())
    done.wait()
    api.webhooks.stop()
    server.shutdown()
    return 0


def _key_cmd(rest: list[str]) -> int:
    sub, opts = (rest[0] if rest else ""), dict(zip(rest[1::2], rest[2::2]))
    if "--config" not in opts:
        return 2
    conf = load(opts["--config"])
    store = Store(conf.get("db", "metallic-api.sqlite3"), conf.get("audit_file"))
    auth = Auth(store, None, None, time.time)
    if sub == "create" and "--name" in opts and "--scopes" in opts and "--out" in opts:
        k = auth.create_key(opts["--name"], opts["--scopes"].split(","),
                            opts["--games"].split(",") if "--games" in opts else None,
                            int(opts.get("--rate", 120)), "cli")
        _write_private(Path(opts["--out"]), (k["secret"] + "\n").encode())
        print(f"{k['id']} created ({', '.join(k['scopes'])}; games {', '.join(k['games'])}; "
              f"{k['rate_per_minute']}/min); secret written to {opts['--out']} (never printed)")
        return 0
    if sub == "list":
        for k in auth.list_keys():
            print(f"{k['id']}  {k['name']:<24} {','.join(k['scopes']):<40} {','.join(k['games']):<12} "
                  f"{k['rate_per_minute']}/min {'REVOKED' if k['revoked'] else ''}")
        return 0
    if sub == "revoke" and "--id" in opts:
        auth.revoke_key(opts["--id"], "cli")
        print(f"{opts['--id']} revoked")
        return 0
    return 2


def main(args: list[str]) -> int:
    usage = ("python -m metallic.api init KEY_DIR | serve --config F | check | "
             "key create --config F --name N --scopes a,b [--games RC,RB] [--rate 120] --out FILE | "
             "key list --config F | key revoke --config F --id key_...")
    cmd, rest = (args[0] if args else ""), args[1:]
    opts = dict(zip(rest[::2], rest[1::2]))
    if cmd == "init" and rest:
        print("created: " + (", ".join(init_keys(rest[0])) or "nothing (data-key exists)"))
        return 0
    if cmd == "serve" and "--config" in opts:
        return run(opts["--config"])
    if cmd == "check":
        problems = Spec().check(set(n[3:] for n in dir(Api) if n.startswith("op_")))
        print("\n".join(problems) or "openapi.json and handlers agree")
        return 1 if problems else 0
    if cmd == "key":
        code = _key_cmd(rest)
        if code != 2:
            return code
    print(usage, file=sys.stderr)
    return 2
