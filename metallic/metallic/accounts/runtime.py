"""`metallic accounts init|serve|owner-code|rotate-key`. Config: server/accounts/accounts.example.toml."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading
import tomllib

from . import crypto
from .server import App, serve
from .service import Accounts
from .store import Store


def _write_private(path: Path, data: bytes) -> None:
    """Owner-only new file; refuses to overwrite (delete on purpose to rotate)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def init_keys(directory: str | Path) -> list[str]:
    """Signing key (ES256) and data key (AES-256-GCM for TOTP secrets). Existing files are kept."""
    d = Path(directory)
    made = []
    if not (d / "signing-key.pem").exists():
        _write_private(d / "signing-key.pem", crypto.new_signing_key_pem())
        made.append("signing-key.pem")
    if not (d / "data-key").exists():
        _write_private(d / "data-key", os.urandom(32))
        made.append("data-key")
    return made


def rotate_key(directory: str | Path) -> None:
    """current -> previous (still published so live tokens keep working for 15 minutes), new current."""
    d = Path(directory)
    if (d / "previous-key.pem").exists():
        (d / "previous-key.pem").unlink()
    (d / "signing-key.pem").rename(d / "previous-key.pem")
    _write_private(d / "signing-key.pem", crypto.new_signing_key_pem())


def load_providers(conf: dict) -> dict:
    """[providers.<id>] tables from accounts.toml or the private providers_file; secrets only via *_file paths."""
    providers = dict(conf.get("providers", {}))
    if conf.get("providers_file") and Path(conf["providers_file"]).is_file():
        providers.update(tomllib.loads(Path(conf["providers_file"]).read_text(encoding="utf-8")).get("providers", {}))
    out = {}
    for pid, p in providers.items():
        p = dict(p)
        for key in ("client_secret", "web_api_key"):
            path = p.pop(key + "_file", None)
            if path:
                p[key] = Path(path).read_text(encoding="utf-8").strip()
        out[pid] = p
    return out


def build_federation(conf: dict, accounts: Accounts):
    from .federation import Federation
    return Federation(accounts, load_providers(conf), rp_id=conf.get("webauthn_rp_id", "localhost"),
                      origins=tuple(conf.get("webauthn_origins", ["http://localhost:47615"])))


def build(conf: dict) -> tuple[Accounts, Store]:
    keys = Path(conf["key_dir"])
    store = Store(conf.get("db", "accounts.sqlite3"), conf.get("audit_file"))
    signer = crypto.Signer.from_files(keys / "signing-key.pem", keys / "previous-key.pem")
    sealer = crypto.Sealer((keys / "data-key").read_bytes())
    return Accounts(store, signer, sealer, registration=conf.get("registration", "open")), store


def load(path: str) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def run(config_path: str) -> int:
    conf = load(config_path)
    accounts, _ = build(conf)
    host, port = conf.get("listen", "0.0.0.0"), int(conf.get("port", 8475))
    tls = (conf["tls_cert"], conf["tls_key"]) if conf.get("tls_cert") else None
    if tls is None and not conf.get("allow_plain_http_for_tests"):
        print("refusing to serve without tls_cert/tls_key", file=sys.stderr)
        return 2
    app = App(accounts, exempt=tuple(conf.get("rate_limit_exempt", ())), federation=build_federation(conf, accounts))
    server = serve(app, host, port, tls)
    print(f"metallic accounts: listening on {host}:{port} ({'https' if tls else 'http'})", file=sys.stderr, flush=True)
    done = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: done.set())
    done.wait()
    server.shutdown()
    return 0


def main(args: list[str]) -> int:
    usage = ("metallic accounts init KEY_DIR | serve --config F | owner-code --config F --out FILE | "
             "rotate-key --config F")
    if not args:
        print(usage, file=sys.stderr)
        return 2
    cmd, rest = args[0], args[1:]
    opts = dict(zip(rest[::2], rest[1::2]))
    if cmd == "init" and rest:
        print("created: " + (", ".join(init_keys(rest[0])) or "nothing (keys exist)"))
        return 0
    if cmd == "serve" and "--config" in opts:
        return run(opts["--config"])
    if cmd == "owner-code" and "--config" in opts and "--out" in opts:
        accounts, _ = build(load(opts["--config"]))
        _write_private(Path(opts["--out"]), (accounts.new_owner_code() + "\n").encode())
        print(f"one-time owner code written to {opts['--out']} (valid 24 hours, never printed)")
        return 0
    if cmd == "rotate-key" and "--config" in opts:
        rotate_key(load(opts["--config"])["key_dir"])
        print("rotated; restart the service")
        return 0
    print(usage, file=sys.stderr)
    return 2
