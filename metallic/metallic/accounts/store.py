"""SQLite storage: one connection, one lock, WAL. Holds no secrets in clear (hashes, digests and sealed TOTP only)."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, uname TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
  pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', age_band TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, pw_changed REAL NOT NULL,
  totp_sealed TEXT, totp_pending TEXT, totp_last_step INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0, fail_first REAL NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
  lockouts INTEGER NOT NULL DEFAULT 0,
  presence_visibility TEXT NOT NULL, friend_requests_from TEXT NOT NULL, invites_from TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recovery_codes (
  account TEXT NOT NULL, digest TEXT NOT NULL, used REAL, PRIMARY KEY (account, digest));
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, account TEXT NOT NULL, refresh_digest TEXT NOT NULL, created REAL NOT NULL,
  last_used REAL NOT NULL, expires REAL NOT NULL, revoked REAL, client TEXT, amr TEXT NOT NULL, generation INTEGER
  NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account);
CREATE TABLE IF NOT EXISTS friends (a TEXT NOT NULL, b TEXT NOT NULL, since REAL NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS friend_requests (
  src TEXT NOT NULL, dst TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY (src, dst));
CREATE TABLE IF NOT EXISTS blocks (blocker TEXT NOT NULL, blocked TEXT NOT NULL, PRIMARY KEY (blocker, blocked));
CREATE TABLE IF NOT EXISTS presence (
  account TEXT PRIMARY KEY, status TEXT NOT NULL, game TEXT, detail TEXT, joinable INTEGER NOT NULL DEFAULT 0,
  updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS invites (
  id TEXT PRIMARY KEY, src TEXT NOT NULL, dst TEXT NOT NULL, game TEXT NOT NULL, target TEXT NOT NULL,
  created REAL NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL DEFAULT 'open');
CREATE INDEX IF NOT EXISTS invites_dst ON invites(dst);
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, game TEXT, author TEXT NOT NULL,
  created REAL NOT NULL, pinned INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS owner_codes (digest TEXT PRIMARY KEY, expires REAL NOT NULL, used REAL);
CREATE TABLE IF NOT EXISTS identities (
  provider TEXT NOT NULL, subject TEXT NOT NULL, account TEXT NOT NULL, email TEXT, email_verified INTEGER NOT NULL
  DEFAULT 0, name TEXT, created REAL NOT NULL, last_used REAL, PRIMARY KEY (provider, subject));
CREATE INDEX IF NOT EXISTS identities_account ON identities(account);
CREATE TABLE IF NOT EXISTS flows (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, provider TEXT, secret TEXT, nonce TEXT, challenge TEXT, redirect TEXT,
  account TEXT, data TEXT, created REAL NOT NULL, expires REAL NOT NULL, used REAL);
CREATE TABLE IF NOT EXISTS passkeys (
  id TEXT PRIMARY KEY, account TEXT NOT NULL, public_key TEXT NOT NULL, alg INTEGER NOT NULL, sign_count INTEGER
  NOT NULL DEFAULT 0, name TEXT, created REAL NOT NULL, last_used REAL);
CREATE INDEX IF NOT EXISTS passkeys_account ON passkeys(account);
CREATE TABLE IF NOT EXISTS used_nonces (nonce TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, event TEXT NOT NULL, account TEXT, actor TEXT,
  ip TEXT, ok INTEGER NOT NULL, detail TEXT);
"""


class Store:
    def __init__(self, path: str | Path, audit_file: str | Path | None = None, clock=time.time):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.clock = clock
        self.audit_file = Path(audit_file) if audit_file else None
        with self.lock:
            if str(path) != ":memory:":
                self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript(SCHEMA)
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema', '1')")

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.db.execute(sql, args).rowcount

    def tx(self):
        """`with store.tx():` one transaction (the lock is held for its whole body)."""
        store = self

        class _Tx:
            def __enter__(self):
                store.lock.acquire()
                store.db.execute("BEGIN IMMEDIATE")

            def __exit__(self, kind, *_):
                try:
                    store.db.execute("ROLLBACK" if kind else "COMMIT")
                finally:
                    store.lock.release()
        return _Tx()

    def audit(self, event: str, ok: bool, account: str | None = None, actor: str | None = None,
              ip: str | None = None, **detail) -> None:
        ts = self.clock()
        text = json.dumps(detail, separators=(",", ":"), sort_keys=True) if detail else None
        self.x("INSERT INTO audit (ts, event, account, actor, ip, ok, detail) VALUES (?,?,?,?,?,?,?)",
               (ts, event, account, actor, ip, int(ok), text))
        if self.audit_file:
            line = json.dumps({"ts": round(ts, 3), "event": event, "ok": ok, "account": account, "actor": actor,
                               "ip": ip, **detail}, separators=(",", ":"))
            with self.lock, open(self.audit_file, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def audit_rows(self, limit: int = 200, account: str | None = None) -> list[dict]:
        if account:
            rows = self.q("SELECT * FROM audit WHERE account=? ORDER BY id DESC LIMIT ?", (account, limit))
        else:
            rows = self.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [{**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else {}} for r in rows]
