"""Her memory stream (Generative Agents style): every perception, conversation, game event and thought is one record.

One SQLite file <app data>/inner/stream.sqlite3, beside inner.sqlite3 (store.py keeps the older per-person
episodes, cards and diary; this stream is her whole life, not only chats). A record keeps time, place/platform, people (friend-memory keys, never
handles), her emotion at that moment (from star.emotion), importance 0..1, an embedding (model name kept), evidence
links, and for skills the outcome. Kinds:
  episodic    something that happened (a session, a chat, a game moment, something she saw)
  semantic    a fact she learned; facts are bi-temporal (Zep/Graphiti data model): `fact_key`, `valid_from`,
              `invalid_at`. A new value for the same key closes the old one (invalid_at, superseded_by), never deletes it
  procedural  one attempt at a skill: skill, outcome (1/0), verified, the confidence she predicted before it
  reflection  an insight with evidence links to the memories it rests on
  thought     her inner monologue
  dream       a night's dream narrative (always labelled as a dream)

Write path (Letta sleep-time pattern): hot paths (a chat reply, an activity) only append a raw line to
<app data>/inner/stream-inbox.jsonl (`observe`); `ingest` embeds and stores them later, between activities or at night.

Retrieval score = recency x importance x relevance (Park et al. 2023 sum the three; the product makes an irrelevant
memory score 0 however recent): recency = 0.995 ^ hours since last access, importance floored at 0.05, relevance =
max(0, cosine). Privacy: `forget_person` removes every record that names the person and, transitively, every record
whose evidence cites a removed one; a tombstone stops late inbox lines; `purge_orphans` follows friend memory's
"forget me". Possible minors and anyone on Roblox give content-free records only (see mind.observe_conversation).
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from .embed import HASH_MODEL, HashEmbedder, cosine, hash_vector

KINDS = ("episodic", "semantic", "procedural", "reflection", "thought", "dream")
RECENCY_DECAY = 0.995            # per hour since last access (Park et al. 2023)
MIN_IMPORTANCE = 0.05

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY, src TEXT UNIQUE, ts REAL NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '', place TEXT NOT NULL DEFAULT '', people TEXT NOT NULL DEFAULT '[]',
  names TEXT NOT NULL DEFAULT '[]', valence REAL NOT NULL DEFAULT 0, arousal REAL NOT NULL DEFAULT 0,
  feeling TEXT NOT NULL DEFAULT '', importance REAL NOT NULL DEFAULT 0.3, text TEXT NOT NULL,
  emb TEXT NOT NULL DEFAULT '[]', emb_model TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '[]',
  skill TEXT NOT NULL DEFAULT '', outcome INTEGER NOT NULL DEFAULT -1, verified INTEGER NOT NULL DEFAULT 0,
  predicted REAL NOT NULL DEFAULT -1, private INTEGER NOT NULL DEFAULT 0, milestone INTEGER NOT NULL DEFAULT 0,
  fact_key TEXT NOT NULL DEFAULT '', valid_from REAL NOT NULL DEFAULT 0, invalid_at REAL NOT NULL DEFAULT 0,
  superseded_by INTEGER NOT NULL DEFAULT 0, last_access REAL NOT NULL DEFAULT 0, accesses INTEGER NOT NULL DEFAULT 0,
  merged INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS memories_ts ON memories(ts);
CREATE INDEX IF NOT EXISTS memories_kind ON memories(kind, ts);
CREATE INDEX IF NOT EXISTS memories_fact ON memories(fact_key, invalid_at);
"""
_COLS = ("id", "ts", "kind", "source", "platform", "place", "people", "names", "valence", "arousal", "feeling",
         "importance", "text", "emb", "emb_model", "evidence", "skill", "outcome", "verified", "predicted", "private",
         "milestone", "fact_key", "valid_from", "invalid_at", "superseded_by", "last_access", "accesses", "merged")
_JSON = {"people", "names", "emb", "evidence"}


@dataclass(frozen=True)
class Memory:
    id: int
    ts: float
    kind: str
    source: str
    platform: str
    place: str
    people: list
    names: list
    valence: float
    arousal: float
    feeling: str
    importance: float
    text: str
    emb: list = field(repr=False)
    emb_model: str = ""
    evidence: list = field(default_factory=list)
    skill: str = ""
    outcome: int = -1
    verified: int = 0
    predicted: float = -1
    private: int = 0
    milestone: int = 0
    fact_key: str = ""
    valid_from: float = 0
    invalid_at: float = 0
    superseded_by: int = 0
    last_access: float = 0
    accesses: int = 0
    merged: int = 1
    score: float = 0.0


def _row(row) -> Memory:
    values = {c: (json.loads(v or "[]") if c in _JSON else v) for c, v in zip(_COLS, row)}
    return Memory(**values)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", str(text).lower()))


class MemoryStream:
    def __init__(self, directory, *, embedder=None, clock=time.time) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.inbox = self.dir / "stream-inbox.jsonl"
        self.embedder = embedder or HashEmbedder()
        self.clock = clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.dir / "stream.sqlite3"), timeout=10, check_same_thread=False)
        with self._lock:
            self.db.executescript(_SCHEMA)
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def meta(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
            self.db.commit()

    # -- write path ---------------------------------------------------------------------------------------------------
    def observe(self, **record) -> None:
        """Hot path: append one raw record to the inbox (no embedding, no database). Never raises."""
        try:
            record.setdefault("ts", self.clock())
            with self.inbox.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def ingest(self, limit: int = 2000) -> int:
        """Move inbox lines into the stream (batch-embedded). Lines about a forgotten person are dropped."""
        if not self.inbox.exists():
            return 0
        work = self.dir / f"stream-inbox.{os.getpid()}.processing"
        try:
            self.inbox.replace(work)
        except OSError:
            return 0                     # being written right now: next tick
        rows = []
        for line in work.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        rows = [r for r in rows if isinstance(r, dict) and not self._forgotten(r.get("people") or [])][:limit]
        self.add_many(rows)
        work.unlink(missing_ok=True)
        return len(rows)

    def _forgotten(self, people) -> bool:
        return any(self.meta(f"forgotten:{p}") for p in people)

    def add(self, text: str, **fields) -> int | None:
        ids = self.add_many([{"text": text, **fields}])
        return ids[0] if ids else None

    def add_many(self, records: list[dict]) -> list[int | None]:
        clean = []
        for r in records:
            text = " ".join(str(r.get("text") or "").split())[:600]
            if len(text) >= 3 and r.get("kind", "episodic") in KINDS and not self._forgotten(r.get("people") or []):
                clean.append({**r, "text": text})
        if not clean:
            return []
        model, vectors = self.embedder.embed([r["text"] for r in clean])
        out = []
        with self._lock:
            for r, vec in zip(clean, vectors):
                ts = float(r.get("ts") or self.clock())
                values = {
                    "src": r.get("src"), "ts": ts, "kind": r.get("kind", "episodic"), "source": r.get("source", ""),
                    "platform": r.get("platform", ""), "place": r.get("place", ""),
                    "people": json.dumps(list(r.get("people") or [])), "names": json.dumps(list(r.get("names") or [])),
                    "valence": float(r.get("valence") or 0), "arousal": float(r.get("arousal") or 0),
                    "feeling": str(r.get("feeling") or ""),
                    "importance": min(1.0, max(0.0, float(r.get("importance", 0.3)))), "text": r["text"],
                    "emb": json.dumps(vec), "emb_model": model, "evidence": json.dumps(list(r.get("evidence") or [])),
                    "skill": str(r.get("skill") or ""), "outcome": int(r.get("outcome", -1)),
                    "verified": int(bool(r.get("verified"))), "predicted": float(r.get("predicted", -1)),
                    "private": int(bool(r.get("private"))), "milestone": int(bool(r.get("milestone"))),
                    "fact_key": str(r.get("fact_key") or ""), "valid_from": float(r.get("valid_from") or ts),
                    "last_access": ts}
                cur = self.db.execute(f"INSERT OR IGNORE INTO memories ({', '.join(values)}) VALUES "
                                      f"({', '.join('?' * len(values))})", tuple(values.values()))
                out.append(cur.lastrowid if cur.rowcount else None)
            self.db.commit()
        return out

    def add_fact(self, fact_key: str, text: str, *, valid_from: float | None = None, evidence=(), people=(),
                 names=(), importance: float = 0.5, source: str = "night", private: bool = False,
                 kind: str = "semantic") -> int | None:
        """A semantic fact. The same value again only adds evidence; a new value closes the old fact at `valid_from`."""
        valid_from = self.clock() if valid_from is None else valid_from
        current = self.fact(fact_key)
        if current is not None and _norm(current.text) == _norm(text):
            merged = sorted(set(current.evidence) | set(evidence))
            people_all = sorted(set(current.people) | set(people))
            with self._lock:
                self.db.execute("UPDATE memories SET evidence = ?, people = ?, importance = max(importance, ?) "
                                "WHERE id = ?", (json.dumps(merged), json.dumps(people_all), importance, current.id))
                self.db.commit()
            return current.id
        new_id = self.add(text, kind=kind, source=source, fact_key=fact_key, valid_from=valid_from,
                          ts=valid_from, evidence=list(evidence), people=list(people), names=list(names),
                          importance=importance, private=private)
        if current is not None and new_id:
            with self._lock:
                self.db.execute("UPDATE memories SET invalid_at = ?, superseded_by = ? WHERE id = ?",
                                (valid_from, new_id, current.id))
                self.db.commit()
        return new_id

    def fact(self, fact_key: str, as_of: float | None = None) -> Memory | None:
        """The value of a fact now (or as it was at `as_of`)."""
        if as_of is None:
            row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM memories WHERE fact_key = ? AND invalid_at = 0 "
                                  "ORDER BY valid_from DESC LIMIT 1", (fact_key,)).fetchone()
        else:
            row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM memories WHERE fact_key = ? AND valid_from <= ? "
                                  "AND (invalid_at = 0 OR invalid_at > ?) ORDER BY valid_from DESC LIMIT 1",
                                  (fact_key, as_of, as_of)).fetchone()
        return _row(row) if row else None

    def update(self, memory_id: int, **fields) -> None:
        allowed = {"importance", "valence", "accesses", "last_access", "evidence", "merged", "milestone", "private"}
        sets = {k: (json.dumps(v) if k in _JSON else v) for k, v in fields.items() if k in allowed}
        if not sets:
            return
        with self._lock:
            self.db.execute(f"UPDATE memories SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                            (*sets.values(), memory_id))
            self.db.commit()

    # -- read path ----------------------------------------------------------------------------------------------------
    def get(self, memory_id: int) -> Memory | None:
        row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return _row(row) if row else None

    def all(self, *, kind: str | None = None, since: float = 0.0, until: float | None = None, skill: str | None = None,
            limit: int = 5000) -> list[Memory]:
        sql, args = f"SELECT {', '.join(_COLS)} FROM memories WHERE ts >= ?", [since]
        if until is not None:
            sql += " AND ts <= ?"
            args.append(until)
        if kind is not None:
            sql += " AND kind = ?"
            args.append(kind)
        if skill is not None:
            sql += " AND skill = ?"
            args.append(skill)
        rows = self.db.execute(sql + " ORDER BY ts DESC, id DESC LIMIT ?", (*args, limit)).fetchall()
        return [_row(r) for r in reversed(rows)]

    def count(self) -> int:
        return self.db.execute("SELECT count(*) FROM memories").fetchone()[0]

    @staticmethod
    def recency(memory: Memory, now: float) -> float:
        return RECENCY_DECAY ** (max(0.0, now - (memory.last_access or memory.ts)) / 3600.0)

    def relevance(self, memory: Memory, query: str, query_vec: tuple[str, list[float]]) -> float:
        model, vec = query_vec
        if memory.emb_model == model and memory.emb:
            return max(0.0, cosine(vec, memory.emb))
        return max(0.0, cosine(hash_vector(query), memory.emb if memory.emb_model == HASH_MODEL else
                               hash_vector(memory.text)))

    def score(self, memory: Memory, query: str, query_vec, now: float) -> float:
        return self.recency(memory, now) * max(MIN_IMPORTANCE, memory.importance) * self.relevance(memory, query,
                                                                                                   query_vec)

    def retrieve(self, query: str, *, k: int = 5, kinds=None, person: str | None = None, as_of: float | None = None,
                 include_private: bool = False, touch: bool = True, min_relevance: float = 0.12,
                 now: float | None = None) -> list[Memory]:
        """Top-k by recency x importance x relevance. Facts that were superseded are left out (or, with `as_of`, the
        facts valid then and only memories formed by then). Nothing above `min_relevance`: [] (an honest "not stored")."""
        now = self.clock() if now is None else now
        at = now if as_of is None else as_of
        model, vecs = self.embedder.embed([query])
        query_vec = (model, vecs[0])
        hits = []
        for m in self.all(until=at):
            if kinds and m.kind not in kinds:
                continue
            if person is not None and person not in m.people:
                continue
            if m.private and not include_private:
                continue
            if m.fact_key:
                if m.valid_from > at or (m.invalid_at and m.invalid_at <= at):
                    continue
            rel = self.relevance(m, query, query_vec)
            if rel < min_relevance:
                continue
            hits.append(replace(m, score=round(self.recency(m, at) * max(MIN_IMPORTANCE, m.importance) * rel, 6)))
        hits.sort(key=lambda m: (-m.score, -m.ts))
        top = hits[:k]
        if touch and top and as_of is None:
            with self._lock:
                self.db.executemany("UPDATE memories SET last_access = ?, accesses = accesses + 1 WHERE id = ?",
                                    [(now, m.id) for m in top])
                self.db.commit()
        return top

    # -- skills -------------------------------------------------------------------------------------------------------
    def skill_stats(self, now: float | None = None, half_life_days: float = 14.0) -> dict[str, dict]:
        """Per skill, from real outcomes only: recency-weighted Beta(1,1) posterior mean (her calibrated confidence),
        Wilson lower bound, counts, and the Brier score of the confidence she predicted before each attempt."""
        now = self.clock() if now is None else now
        out: dict[str, dict] = {}
        for m in self.all(kind="procedural"):
            if not m.skill or m.outcome not in (0, 1):
                continue
            s = out.setdefault(m.skill, {"n": 0, "wins": 0, "w": 0.0, "ws": 0.0, "brier": [], "last": 0.0})
            weight = 0.5 ** (max(0.0, now - m.ts) / 86400.0 / half_life_days)
            s["n"] += 1
            s["wins"] += m.outcome
            s["w"] += weight
            s["ws"] += weight * m.outcome
            s["last"] = max(s["last"], m.ts)
            if 0.0 <= m.predicted <= 1.0:
                s["brier"].append((m.predicted - m.outcome) ** 2)
        for name, s in out.items():
            n, p = s["n"], s["wins"] / s["n"]
            z = 1.96
            wilson = (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
            out[name] = {"attempts": n, "successes": s["wins"], "confidence": round((1 + s["ws"]) / (2 + s["w"]), 3),
                         "lower_bound": round(wilson, 3), "last": s["last"],
                         "brier": round(sum(s["brier"]) / len(s["brier"]), 3) if s["brier"] else None}
        return out

    # -- forgetting and privacy ---------------------------------------------------------------------------------------
    def _cascade(self, ids: set[int]) -> int:
        """Delete `ids` and every record whose evidence cites a deleted record, until nothing more cites one."""
        removed = 0
        while ids:
            with self._lock:
                self.db.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])
                removed += len(ids)
                self.db.execute("UPDATE memories SET superseded_by = 0, invalid_at = 0 WHERE superseded_by IN "
                                f"({', '.join('?' * len(ids))})", tuple(ids))
                self.db.commit()
            cites = set()
            for mid, evidence in self.db.execute("SELECT id, evidence FROM memories WHERE evidence != '[]'").fetchall():
                if ids & set(json.loads(evidence)):
                    cites.add(mid)
            ids = cites
        return removed

    def forget_person(self, pkey: str) -> int:
        """Everything about one person, everything built on it, their unread inbox lines; and a tombstone."""
        if not pkey:
            return 0
        self.set_meta(f"forgotten:{pkey}", self.clock())
        needle = json.dumps(pkey)
        ids = {r[0] for r in self.db.execute("SELECT id, people FROM memories").fetchall()
               if needle in r[1] and pkey in json.loads(r[1])}
        removed = self._cascade(ids)
        if self.inbox.exists():
            try:
                kept = [line for line in self.inbox.read_text(encoding="utf-8").splitlines() if needle not in line]
                self.inbox.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
            except OSError:
                pass
        return removed

    def forget_ids(self, ids) -> int:
        return self._cascade({int(i) for i in ids})

    def forget_matching(self, text: str, *, threshold: float = 0.5) -> int:
        """"Forget that": records whose text is very close to `text` (hash cosine), and what cites them."""
        vec = hash_vector(text)
        ids = {m.id for m in self.all() if cosine(vec, hash_vector(m.text)) >= threshold}
        return self._cascade(ids)

    def purge_orphans(self, friend_memory) -> int:
        """Follow friend memory's "forget me": people it no longer knows lose every record here."""
        from .store import resolve
        keys = set()
        for (people,) in self.db.execute("SELECT people FROM memories WHERE people != '[]'").fetchall():
            keys.update(json.loads(people))
        return sum(self.forget_person(k) for k in keys if resolve(friend_memory, k) is None)

    # -- consolidation helpers (the night job) ------------------------------------------------------------------------
    def cited(self) -> set[int]:
        out: set[int] = set()
        for (evidence,) in self.db.execute("SELECT evidence FROM memories WHERE evidence != '[]'").fetchall():
            out.update(json.loads(evidence))
        return out

    def merge_duplicates(self, since: float, threshold: float = 0.92) -> int:
        """Same kind, same people, near-identical text since `since`: keep the more important, count the other in."""
        rows = [m for m in self.all(since=since) if m.kind in ("episodic", "thought") and not m.milestone]
        gone: set[int] = set()
        merged = 0
        for i, a in enumerate(rows):
            if a.id in gone:
                continue
            va = hash_vector(a.text)
            for b in rows[i + 1:]:
                if b.id in gone or b.kind != a.kind or sorted(b.people) != sorted(a.people):
                    continue
                if cosine(va, hash_vector(b.text)) >= threshold:
                    keep, drop = (a, b) if a.importance >= b.importance else (b, a)
                    self._rewire(drop.id, keep.id)
                    self.update(keep.id, merged=keep.merged + drop.merged,
                                importance=min(1.0, max(keep.importance, drop.importance) + 0.02))
                    with self._lock:
                        self.db.execute("DELETE FROM memories WHERE id = ?", (drop.id,))
                        self.db.commit()
                    gone.add(drop.id)
                    merged += 1
                    if drop.id == a.id:
                        break
        return merged

    def _rewire(self, old: int, new: int) -> None:
        for mid, evidence in self.db.execute("SELECT id, evidence FROM memories WHERE evidence != '[]'").fetchall():
            ev = json.loads(evidence)
            if old in ev:
                self.update(mid, evidence=sorted({new if e == old else e for e in ev}))

    def prune(self, now: float, *, min_age_days: float = 7.0, floor: float = 0.15, cap: int = 20000) -> int:
        """Drop low-value memories: old, unimportant, never recalled, not a milestone, not evidence for anything;
        then, over `cap`, the lowest importance x recency episodic/thought records."""
        cited = self.cited()
        drop = [m.id for m in self.all(until=now - min_age_days * 86400)
                if m.kind in ("episodic", "thought") and m.importance < floor and m.accesses == 0
                and not m.milestone and m.id not in cited]
        with self._lock:
            self.db.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in drop])
            self.db.commit()
        extra = self.count() - cap
        if extra > 0:
            ranked = sorted((m for m in self.all() if m.kind in ("episodic", "thought") and not m.milestone
                             and m.id not in cited), key=lambda m: m.importance * self.recency(m, now))
            ids = [m.id for m in ranked[:extra]]
            with self._lock:
                self.db.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])
                self.db.commit()
            drop += ids
        return len(drop)
