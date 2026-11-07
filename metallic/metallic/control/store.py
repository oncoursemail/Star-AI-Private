"""Time series, request timings, latest state and the admin audit log in one SQLite file.

Resolution tiers (each query picks the tier that covers its range):
    raw   every sample (5-10 s)        kept 3 hours    -> "hour"
    m1    1-minute avg/min/max         kept 2 days     -> "day"
    m10   10-minute avg/min/max        kept 8 days     -> "week"
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time

RAW_KEEP = 3 * 3600
M1_KEEP = 2 * 86400
M10_KEEP = 8 * 86400
REQ_KEEP = 8 * 86400
RANGES = {"hour": (3600, "raw"), "day": (86400, "m1"), "week": (7 * 86400, "m10")}

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS raw (sid INTEGER, ts INTEGER, v REAL, PRIMARY KEY (sid, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS m1 (sid INTEGER, ts INTEGER, avg REAL, min REAL, max REAL, PRIMARY KEY (sid, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS m10 (sid INTEGER, ts INTEGER, avg REAL, min REAL, max REAL, PRIMARY KEY (sid, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS reqs (ts REAL, machine TEXT, model TEXT, slot INTEGER, prompt_ms REAL, prompt_tokens INTEGER,
                                 eval_ms REAL, eval_tokens INTEGER);
CREATE INDEX IF NOT EXISTS reqs_ts ON reqs (ts);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, ts REAL, value TEXT);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, action TEXT, label TEXT, machine TEXT,
                                  actor TEXT, client TEXT, state TEXT, exit INTEGER, text TEXT, finished REAL);
"""


class Store:
    def __init__(self, path: str | Path, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._ids: dict[str, int] = dict((k, i) for i, k in self.db.execute("SELECT id, key FROM series"))

    # ------------------------------------------------------------------ writes
    def _sid(self, key: str) -> int:
        sid = self._ids.get(key)
        if sid is None:
            self.db.execute("INSERT OR IGNORE INTO series (key) VALUES (?)", (key,))
            sid = self.db.execute("SELECT id FROM series WHERE key = ?", (key,)).fetchone()[0]
            self._ids[key] = sid
        return sid

    def add(self, ts: float, values: dict[str, float | None]) -> None:
        rows = [(k, float(v)) for k, v in values.items() if isinstance(v, (int, float)) and v == v]
        if not rows:
            return
        with self.lock:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT OR REPLACE INTO raw (sid, ts, v) VALUES (?, ?, ?)",
                                [(self._sid(k), int(ts), v) for k, v in rows])
            self.db.execute("COMMIT")

    def add_requests(self, machine: str, rows: list[dict]) -> None:
        good = [(float(r["t"]), machine, str(r.get("model", ""))[:40], int(r.get("slot", -1)), r.get("prompt_ms"),
                 r.get("prompt_tokens"), r.get("eval_ms"), r.get("eval_tokens")) for r in rows if "t" in r]
        if good:
            with self.lock:
                self.db.executemany("INSERT INTO reqs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", good)

    def put(self, key: str, value) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?, ?)", (key, self.clock(), json.dumps(value)))

    def get(self, key: str, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    # ------------------------------------------------------------------ rollups and retention
    def rollup(self) -> None:
        """Fold finished minutes into m1 and finished 10-minute buckets into m10; drop expired rows."""
        now = int(self.clock())
        with self.lock:
            self.db.execute("BEGIN")
            done1 = int(self._kv_raw("rolled_m1") or 0)
            upto1 = now - now % 60
            if upto1 > done1:
                self.db.execute(
                    "INSERT OR REPLACE INTO m1 SELECT sid, ts - ts % 60, avg(v), min(v), max(v) FROM raw "
                    "WHERE ts >= ? AND ts < ? GROUP BY sid, ts - ts % 60", (done1, upto1))
                self._kv_raw_set("rolled_m1", upto1)
            done10 = int(self._kv_raw("rolled_m10") or 0)
            upto10 = now - now % 600
            if upto10 > done10:
                self.db.execute(
                    "INSERT OR REPLACE INTO m10 SELECT sid, ts - ts % 600, avg(avg), min(min), max(max) FROM m1 "
                    "WHERE ts >= ? AND ts < ? GROUP BY sid, ts - ts % 600", (done10, upto10))
                self._kv_raw_set("rolled_m10", upto10)
            self.db.execute("DELETE FROM raw WHERE ts < ?", (now - RAW_KEEP,))
            self.db.execute("DELETE FROM m1 WHERE ts < ?", (now - M1_KEEP,))
            self.db.execute("DELETE FROM m10 WHERE ts < ?", (now - M10_KEEP,))
            self.db.execute("DELETE FROM reqs WHERE ts < ?", (now - REQ_KEEP,))
            self.db.execute("COMMIT")

    def _kv_raw(self, key: str):
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _kv_raw_set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?, ?)", (key, self.clock(), json.dumps(value)))

    # ------------------------------------------------------------------ reads
    def series(self, keys: list[str], rng: str = "hour") -> dict:
        """{"range", "step", "from", "to", "series": {key: [[ts, avg, min, max], ...]}} (raw rows have min = max = v)."""
        span, tier = RANGES[rng]
        now = int(self.clock())
        since = now - span
        out: dict = {}
        with self.lock:
            for key in keys:
                sid = self._ids.get(key)
                if sid is None:
                    out[key] = []
                    continue
                if tier == "raw":
                    rows = self.db.execute("SELECT ts, v, v, v FROM raw WHERE sid = ? AND ts >= ? ORDER BY ts",
                                           (sid, since)).fetchall()
                else:
                    rows = self.db.execute(f"SELECT ts, avg, min, max FROM {tier} WHERE sid = ? AND ts >= ? ORDER BY ts",
                                           (sid, since)).fetchall()
                    if tier == "m1":       # the current minute is still in raw: append it so "day" ends at now
                        tail = self.db.execute("SELECT ? , avg(v), min(v), max(v) FROM raw WHERE sid = ? AND ts >= ?",
                                               (now - now % 60, sid, now - now % 60)).fetchone()
                        if tail and tail[1] is not None:
                            rows.append(tail)
                out[key] = [[r[0], _round(r[1]), _round(r[2]), _round(r[3])] for r in rows]
        return {"range": rng, "step": {"raw": 5, "m1": 60, "m10": 600}[tier], "from": since, "to": now, "series": out}

    def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._ids if k.startswith(prefix))

    def requests(self, since: float, limit: int = 500) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT ts, machine, model, slot, prompt_ms, prompt_tokens, eval_ms, eval_tokens "
                                   "FROM reqs WHERE ts >= ? ORDER BY ts DESC LIMIT ?", (since, limit)).fetchall()
        names = ("t", "machine", "model", "slot", "prompt_ms", "prompt_tokens", "eval_ms", "eval_tokens")
        return [dict(zip(names, r)) for r in rows]

    def speed_history(self, days: int = 7) -> list[dict]:
        """Per hour and model: requests, median decode tok/s, median prompt time (first-token proxy)."""
        since = self.clock() - days * 86400
        with self.lock:
            rows = self.db.execute("SELECT ts, machine, model, prompt_ms, eval_ms, eval_tokens FROM reqs WHERE ts >= ? "
                                   "AND eval_ms > 0 ORDER BY ts", (since,)).fetchall()
        buckets: dict = {}
        for ts, machine, model, prompt_ms, eval_ms, eval_tokens in rows:
            key = (int(ts) - int(ts) % 3600, machine, model)
            buckets.setdefault(key, []).append((eval_tokens * 1000.0 / eval_ms, prompt_ms or 0.0))
        out = []
        for (hour, machine, model), vals in sorted(buckets.items()):
            tps = sorted(v[0] for v in vals)
            pms = sorted(v[1] for v in vals)
            out.append({"t": hour, "machine": machine, "model": model, "n": len(vals),
                        "tps_median": round(tps[len(tps) // 2], 2), "prompt_ms_median": round(pms[len(pms) // 2], 1)})
        return out

    # ------------------------------------------------------------------ audit
    def audit_start(self, action: str, label: str, machine: str, actor: str, client: str) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO audit (ts, action, label, machine, actor, client, state) "
                                  "VALUES (?, ?, ?, ?, ?, ?, 'pending')", (self.clock(), action, label, machine, actor,
                                                                          client))
            return int(cur.lastrowid)

    def audit_finish(self, entry: int, state: str, exit_code: int | None, text: str) -> None:
        with self.lock:
            self.db.execute("UPDATE audit SET state = ?, exit = ?, text = ?, finished = ? WHERE id = ?",
                            (state, exit_code, text[:500], self.clock(), entry))

    def audit(self, limit: int = 100) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id, ts, action, label, machine, actor, client, state, exit, text, finished "
                                   "FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        names = ("id", "ts", "action", "label", "machine", "actor", "client", "state", "exit", "text", "finished")
        return [dict(zip(names, r)) for r in rows]


def _round(v):
    return None if v is None else round(v, 3)
