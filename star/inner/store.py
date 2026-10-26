"""One SQLite file for her inner life: episodes (with full-text search), relationship cards, diary, opinions,
backstory facts, outreach seeds and dreams. <app data>/inner/inner.sqlite3, or <home>/inner/inner.sqlite3.

Nothing here calls a model. People are identified by `person_key(memory, person)`: the friend-memory id plus the
second the person was first met, so a forgotten person's rows can never be handed to a new person who got the same
id. When friend memory no longer knows a key (they said "forget me") `purge_orphans` removes every row about them.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

NIGHT_START, NIGHT_END = 1, 8          # local hours of her sleep window (same as star/gpu_helper.py)
WAKE_HOUR, WAKE_MINUTE = 7, 30         # she wakes at this local time; a dream's morning fade runs from here
QUIET_START, QUIET_END = 22, 9         # no proactive messages from 22:00 to 09:00 local
MAX_EPISODES = 6000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY, src TEXT UNIQUE, ts REAL NOT NULL, kind TEXT NOT NULL, pkey TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL, importance REAL NOT NULL DEFAULT 0.3, emotion REAL NOT NULL DEFAULT 0,
  strength REAL NOT NULL DEFAULT 5, recalls INTEGER NOT NULL DEFAULT 0, last_recall REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS episodes_pkey ON episodes(pkey, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(text, content='episodes', content_rowid='id',
  tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
  INSERT INTO episodes_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
  INSERT INTO episodes_fts(episodes_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE OF text ON episodes BEGIN
  INSERT INTO episodes_fts(episodes_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO episodes_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TABLE IF NOT EXISTS cards (pkey TEXT PRIMARY KEY, text TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS diary (day TEXT PRIMARY KEY, text TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS opinions (topic TEXT PRIMARY KEY, stance TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL, valence REAL NOT NULL, evidence TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT 'earned', updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS backstory (key TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS seeds (id INTEGER PRIMARY KEY, pkey TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '', created REAL NOT NULL, not_before REAL NOT NULL, expires REAL NOT NULL,
  state TEXT NOT NULL DEFAULT 'open', sent_at REAL NOT NULL DEFAULT 0, platform TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS dreams (id INTEGER PRIMARY KEY, night TEXT NOT NULL, text TEXT NOT NULL, gist TEXT NOT NULL,
  valence REAL NOT NULL, vividness REAL NOT NULL, pkeys TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL,
  woke_at REAL NOT NULL, nudged INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS self_versions (version INTEGER PRIMARY KEY, ts REAL NOT NULL, model TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS self_journal (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, field TEXT NOT NULL,
  old TEXT NOT NULL, new TEXT NOT NULL, why TEXT NOT NULL, status TEXT NOT NULL);
"""

_STOP = frozenset("""a about after all also am an and any are as at be been but by can could did do does doing don dont for
from get got had has have he her here hers him his how i if in into is it its just like me more my no not now of on one
or our out over she so some than that the their them then there these they this to too up us was we were what when where
which who why will with would you your yours yeah yes hey hello hi ok okay oh well really very much lol star again""".split())
_WORD = re.compile(r"[a-z0-9']+")


def stem(word: str) -> str:
    word = word.replace("'", "")
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    """Content words of a text (lowercase stems, stop words and one/two-letter words dropped)."""
    return [stem(w) for w in _WORD.findall(str(text or "").lower()) if len(w.replace("'", "")) >= 3
            and w.replace("'", "") not in _STOP]


def overlap(query: list[str], text: str) -> float:
    """Share of the query's content weight (longer words weigh more) that the text contains, 0..1."""
    if not query:
        return 0.0
    have = set(tokens(text))
    weights = {q: min(len(q), 8) for q in query}
    return sum(w for q, w in weights.items() if q in have) / sum(weights.values())


def _home(home) -> Path:
    if home is not None:
        return Path(home)
    from ..desktop_core import app_data
    return app_data()


# Settings in <home>/settings.json. The night job is background work (no chat latency) so it is on by default; the
# per-turn hook changes prompts (measure first) and the outreach sends real messages: both default off.
FLAGS = {"inner_night_enabled": True, "inner_chat_enabled": False, "inner_reachout_enabled": False}


def flag(name: str, home=None) -> bool:
    try:
        raw = json.loads((_home(home) / "settings.json").read_text(encoding="utf-8"))
        value = raw.get(name) if isinstance(raw, dict) else None
    except (OSError, ValueError):
        value = None
    return value if isinstance(value, bool) else FLAGS[name]


def person_key(memory, person) -> str:
    """'<id>.<first met>' for a remembered person, '' for the owner / her own life / someone who was forgotten."""
    if person is None or getattr(person, "id", None) is None:
        return ""
    created = memory.person_created(person)
    return f"{person.id}.{int(created)}" if created is not None else ""


def resolve(memory, pkey: str):
    """The Person behind a key, or None when friend memory no longer holds them (forgotten)."""
    try:
        pid, created = pkey.split(".", 1)
        person = memory.get(int(pid))
        current_created = memory.person_created(person)
        return person if current_created is not None and int(current_created) == int(created) else None
    except (ValueError, KeyError):
        return None


@dataclass(frozen=True)
class Episode:
    id: int
    ts: float
    kind: str
    pkey: str
    text: str
    importance: float
    emotion: float
    strength: float
    recalls: int


_COLUMNS = ("id", "ts", "kind", "pkey", "text", "importance", "emotion", "strength", "recalls")
_SELECT = ", ".join(_COLUMNS)


def initial_strength(importance: float) -> float:
    """Days until a memory has faded to 37 %: trivia about 4 days, things that matter several weeks."""
    return 3.0 + 25.0 * importance


def retention(episode: Episode, now: float) -> float:
    """Forgetting curve R = e^(-age / S), S in days (MemoryBank / Ebbinghaus); S grows each time it is recalled."""
    return math.exp(-max(0.0, now - episode.ts) / 86400.0 / max(0.5, episode.strength))


class InnerStore:
    def __init__(self, path=None, *, home=None, clock=time.time) -> None:
        self.path = Path(path) if path else _home(home) / "inner" / "inner.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        self.db.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self.db.executescript(_SCHEMA)
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def meta(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
            self.db.commit()

    # -- episodes ---------------------------------------------------------------------------------------------------
    def add_episode(self, pkey: str, text: str, *, kind: str = "moment", ts: float | None = None,
                    importance: float = 0.3, emotion: float = 0.0, src: str | None = None) -> int | None:
        text = " ".join(str(text or "").split())[:300]
        if len(text) < 4:
            return None
        importance = min(1.0, max(0.0, importance))
        with self._lock:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO episodes (src, ts, kind, pkey, text, importance, emotion, strength) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (src, self.clock() if ts is None else ts, kind, pkey, text, importance, min(1.0, max(0.0, emotion)),
                 initial_strength(importance)))
            self.db.execute("DELETE FROM episodes WHERE id IN (SELECT id FROM episodes ORDER BY importance * strength "
                            "ASC LIMIT max(0, (SELECT count(*) FROM episodes) - ?))", (MAX_EPISODES,))
            self.db.commit()
        return cur.lastrowid if cur.rowcount else None

    def episode(self, episode_id: int) -> Episode | None:
        row = self.db.execute(f"SELECT {_SELECT} FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        return Episode(*row) if row else None

    def episodes(self, *, pkey: str | None = None, since: float = 0.0, kind: str | None = None,
                 limit: int = 500) -> list[Episode]:
        sql, args = f"SELECT {_SELECT} FROM episodes WHERE ts >= ?", [since]
        if pkey is not None:
            sql += " AND pkey = ?"
            args.append(pkey)
        if kind is not None:
            sql += " AND kind = ?"
            args.append(kind)
        rows = self.db.execute(sql + " ORDER BY ts DESC LIMIT ?", (*args, limit)).fetchall()
        return [Episode(*r) for r in reversed(rows)]

    def search(self, query_tokens: list[str], pkey: str, limit: int = 25) -> list[Episode]:
        """Episodes of `pkey` that contain any of the words (FTS5, porter stems), newest first."""
        words = [t for t in dict.fromkeys(query_tokens) if t.isalnum()]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        cols = ", ".join("e." + c for c in _COLUMNS)
        rows = self.db.execute(
            f"SELECT {cols} FROM episodes_fts f JOIN episodes e ON e.id = f.rowid "
            "WHERE episodes_fts MATCH ? AND e.pkey = ? ORDER BY e.ts DESC LIMIT ?", (match, pkey, limit)).fetchall()
        return [Episode(*r) for r in rows]

    def strengthen(self, ids: list[int], now: float | None = None) -> None:
        """A memory she actually used is remembered longer (spaced repetition: its half-life grows each time)."""
        now = self.clock() if now is None else now
        with self._lock:
            for i in ids:
                self.db.execute("UPDATE episodes SET strength = min(365, strength * 1.7), recalls = recalls + 1, "
                                "last_recall = ? WHERE id = ?", (now, i))
            self.db.commit()

    def delete_episodes(self, ids: list[int]) -> None:
        with self._lock:
            self.db.executemany("DELETE FROM episodes WHERE id = ?", [(i,) for i in ids])
            self.db.commit()

    # -- per-person -------------------------------------------------------------------------------------------------
    def card(self, pkey: str) -> tuple[str, float]:
        row = self.db.execute("SELECT text, updated FROM cards WHERE pkey = ?", (pkey,)).fetchone()
        return (row[0], row[1]) if row else ("", 0.0)

    def set_card(self, pkey: str, text: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO cards VALUES (?, ?, ?)", (pkey, text, self.clock()))
            self.db.commit()

    def pkeys(self) -> list[str]:
        rows = self.db.execute("SELECT pkey FROM episodes WHERE pkey != '' UNION SELECT pkey FROM cards "
                               "UNION SELECT pkey FROM seeds WHERE pkey != ''").fetchall()
        return [r[0] for r in rows]

    def delete_person(self, pkey: str) -> int:
        """Everything about one person: episodes, card, seeds, and dreams they appear in."""
        if not pkey:
            return 0
        with self._lock:
            n = self.db.execute("DELETE FROM episodes WHERE pkey = ?", (pkey,)).rowcount
            n += self.db.execute("DELETE FROM cards WHERE pkey = ?", (pkey,)).rowcount
            n += self.db.execute("DELETE FROM seeds WHERE pkey = ?", (pkey,)).rowcount
            for row in self.db.execute("SELECT id, pkeys FROM dreams").fetchall():
                if pkey in json.loads(row[1] or "[]"):
                    n += self.db.execute("DELETE FROM dreams WHERE id = ?", (row[0],)).rowcount
            self.db.execute("DELETE FROM meta WHERE key LIKE ?", (f"sync:{pkey}:%",))
            self.db.commit()
        return n

    def purge_orphans(self, memory) -> int:
        """Remove people friend memory has forgotten ("forget me" must reach every table here)."""
        return sum(self.delete_person(k) for k in self.pkeys() if resolve(memory, k) is None)

    # -- diary / audits ---------------------------------------------------------------------------------------------
    def add_diary(self, day: str, text: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO diary VALUES (?, ?, ?)", (day, text, self.clock()))
            self.db.commit()

    def diary(self, limit: int = 7) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.db.execute(
            "SELECT day, text FROM diary ORDER BY day DESC LIMIT ?", (limit,)).fetchall()]

    def add_audit(self, kind: str, text: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO audits (ts, kind, text) VALUES (?, ?, ?)", (self.clock(), kind, text[:300]))
            self.db.commit()

    def audits(self, limit: int = 20) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.db.execute(
            "SELECT kind, text FROM audits ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


_stores: dict[str, InnerStore] = {}
_stores_lock = threading.Lock()


def default_store(home=None) -> InnerStore:
    path = str(_home(home) / "inner" / "inner.sqlite3")
    with _stores_lock:
        if path not in _stores:
            _stores[path] = InnerStore(path)
        return _stores[path]


def night_of(ts: float) -> str:
    """The date (local) of the evening a night started: before 08:00 still counts as the night that began yesterday."""
    t = time.localtime(ts)
    if t.tm_hour < NIGHT_END:
        t = time.localtime(ts - 86400)
    return time.strftime("%Y-%m-%d", t)


def in_night_window(ts: float) -> bool:
    return NIGHT_START <= time.localtime(ts).tm_hour < NIGHT_END


def wake_time_after(ts: float) -> float:
    """The first local wake-up (07:30) at or after a moment in her night."""
    t = time.localtime(ts)
    wake = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, WAKE_HOUR, WAKE_MINUTE, 0, 0, 0, -1))
    return wake if wake >= ts else wake + 86400
