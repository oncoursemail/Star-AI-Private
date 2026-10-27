"""SQLite for the API service: server keys (digests only), scoped tokens (digest + sealed upstream token), webhooks
(sealed secrets), the delivery log, live server heartbeats, release sequences seen, and an audit trail."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL, scopes TEXT NOT NULL, games TEXT NOT NULL,
  rate INTEGER NOT NULL, created REAL NOT NULL, created_by TEXT, last_used REAL, revoked REAL);
CREATE TABLE IF NOT EXISTS tokens (
  digest TEXT PRIMARY KEY, sub TEXT NOT NULL, name TEXT, role TEXT, minor INTEGER NOT NULL, scopes TEXT NOT NULL,
  client TEXT, sealed TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, revoked REAL);
CREATE INDEX IF NOT EXISTS tokens_sub ON tokens(sub);
CREATE TABLE IF NOT EXISTS webhooks (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, url TEXT NOT NULL, events TEXT NOT NULL, description TEXT,
  secret_sealed TEXT NOT NULL, created REAL NOT NULL, deleted REAL);
CREATE TABLE IF NOT EXISTS deliveries (
  id TEXT PRIMARY KEY, webhook TEXT NOT NULL, event_id TEXT NOT NULL, event TEXT NOT NULL, body TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, http_status INTEGER, error TEXT, created REAL NOT NULL,
  next_attempt REAL, delivered REAL);
CREATE INDEX IF NOT EXISTS deliveries_due ON deliveries(status, next_attempt);
CREATE INDEX IF NOT EXISTS deliveries_webhook ON deliveries(webhook, created);
CREATE TABLE IF NOT EXISTS heartbeats (
  game TEXT NOT NULL, server_id TEXT NOT NULL, key TEXT NOT NULL, players INTEGER NOT NULL, max_players INTEGER,
  version TEXT, updated REAL NOT NULL, PRIMARY KEY (game, server_id));
CREATE TABLE IF NOT EXISTS channels_seen (channel TEXT PRIMARY KEY, sequence INTEGER NOT NULL, seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, event TEXT NOT NULL, actor TEXT, ip TEXT, ok INTEGER NOT NULL,
  detail TEXT);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:", audit_file: str | Path | None = None):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.audit_file = Path(audit_file) if audit_file else None

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.db.execute(sql, args).rowcount

    def audit(self, ts: float, event: str, ok: bool, actor: str | None = None, ip: str | None = None, **detail) -> None:
        """Never pass secrets, tokens or player names here."""
        text = json.dumps(detail, separators=(",", ":"), sort_keys=True) if detail else None
        self.x("INSERT INTO audit (ts, event, actor, ip, ok, detail) VALUES (?,?,?,?,?,?)",
               (ts, event, actor, ip, int(ok), text))
        if self.audit_file:
            line = json.dumps({"ts": ts, "event": event, "actor": actor, "ip": ip, "ok": ok, **detail},
                              separators=(",", ":"))
            with self.lock, open(self.audit_file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
