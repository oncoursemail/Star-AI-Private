"""Friend memory: one profile per person across platforms, kept in SQLite under STAR's app data.

A person has handles on platforms (discord / minecraft / roblox), things they told her (facts), shared moments,
how they like to be talked to, and what she knows about their age (needed by rules.py before any romance).
Consent: "forget me" deletes the person and every row about them, and leaves only a salted hash of each handle so
she does not quietly re-learn them; "you can remember me again" removes that hash. Phone numbers, addresses,
e-mails, passwords and similar are never stored; for a stated or suspected minor, and on Roblox, only interests
are kept.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

PLATFORMS = ("discord", "minecraft", "roblox")
MAX_FACTS = 200
MAX_MOMENTS = 300
FACT_CHARS = 240
MOMENT_CHARS = 240

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
  style TEXT NOT NULL DEFAULT '', stated_age INTEGER, age_asked REAL NOT NULL DEFAULT 0,
  minor_signals INTEGER NOT NULL DEFAULT 0, relationship TEXT NOT NULL DEFAULT 'met',
  they_started INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS handles (platform TEXT NOT NULL, handle TEXT NOT NULL,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE, PRIMARY KEY (platform, handle));
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE, text TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS moments (id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE, platform TEXT NOT NULL,
  line TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS forgotten (key TEXT PRIMARY KEY, ts REAL NOT NULL);
"""

# Never stored, whoever says it.
_SENSITIVE = re.compile(
    r"\b(?:password|passcode|pin|token|api key|credit card|card number|social security|ssn|bank|iban|"
    r"address|street|postcode|zip code|phone|cell|number is|e-?mail|@\w+\.\w+|school is|go to school at|"
    r"live (?:in|at|on)|my (?:full|real|last) name)\b|\d{6,}", re.I)
# "I like / love / play / ..." sentences: interests (the only facts kept for a possible minor).
_INTEREST = re.compile(r"^\s*(?:i\s+(?:really\s+)?(?:like|love|enjoy|play|main|collect|draw|build|watch|listen to|hate))\b",
                       re.I)
_FACT = re.compile(r"^\s*(?:i\s+(?:am|'m|m|have|got|work|study|just|was|like|love|enjoy|play|main|collect|draw|build|"
                   r"watch|listen to|hate|prefer|want)|my\s+\w+(?:\s+\w+)?\s+(?:is|are|was))\b", re.I)


@dataclass
class Person:
    id: int | None              # None: someone who asked to be forgotten (nothing is stored for them)
    name: str
    style: str = ""
    stated_age: int | None = None
    age_asked: float = 0.0
    minor_signals: int = 0
    relationship: str = "met"   # met | friend
    they_started: bool = False
    blocked: bool = False
    muted: bool = False

    @property
    def remembered(self) -> bool:
        return self.id is not None


def default_path() -> Path:
    from ..desktop_core import app_data
    return app_data() / "social" / "friends.sqlite3"


def extract_facts(text: str) -> list[str]:
    """Sentences in which someone tells something about themselves ("I love horror games", "my cat is Miso")."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")):
        sentence = " ".join(sentence.split()).strip(" .!?")
        if 6 <= len(sentence) <= FACT_CHARS and _FACT.match(sentence) and not _SENSITIVE.search(sentence):
            out.append(sentence)
    return out


class FriendMemory:
    def __init__(self, path: Path | None = None, *, clock=time.time) -> None:
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        row = self._db.execute("SELECT value FROM meta WHERE key = 'salt'").fetchone()
        if row is None:
            self._db.execute("INSERT INTO meta VALUES ('salt', ?)", (secrets.token_hex(16),))
            self._db.commit()
            row = self._db.execute("SELECT value FROM meta WHERE key = 'salt'").fetchone()
        self._salt = row[0]

    def close(self) -> None:
        self._db.close()

    # -- people ---------------------------------------------------------------------------------------------------
    def _tombstone(self, platform: str, handle: str) -> str:
        return hashlib.sha256(f"{self._salt}\0{platform}\0{handle.lower()}".encode()).hexdigest()

    def is_forgotten(self, platform: str, handle: str) -> bool:
        key = self._tombstone(platform, handle)
        return self._db.execute("SELECT 1 FROM forgotten WHERE key = ?", (key,)).fetchone() is not None

    def person(self, platform: str, handle: str, name: str = "", *, they_started: bool = False) -> Person:
        """The profile behind `platform:handle`, created on first meeting (an unsaved Person if they were forgotten)."""
        if platform not in PLATFORMS:
            raise ValueError(f"unknown platform {platform!r}")
        handle = str(handle).strip()[:100]
        if not handle:
            raise ValueError("empty handle")
        if self.is_forgotten(platform, handle):
            return Person(id=None, name=name or handle)
        row = self._db.execute("SELECT person_id FROM handles WHERE platform = ? AND handle = ?",
                               (platform, handle.lower())).fetchone()
        if row is None:
            now = self._clock()
            cur = self._db.execute("INSERT INTO people (name, created, updated, they_started) VALUES (?, ?, ?, ?)",
                                   ((name or handle)[:100], now, now, int(they_started)))
            self._db.execute("INSERT INTO handles VALUES (?, ?, ?)", (platform, handle.lower(), cur.lastrowid))
            self._db.commit()
            return self.get(cur.lastrowid)
        return self.get(row[0])

    def known(self, platform: str, handle: str) -> Person | None:
        """The profile behind `platform:handle` if she has one; unlike person() it never creates one."""
        handle = str(handle).strip()[:100]
        if platform not in PLATFORMS or not handle or self.is_forgotten(platform, handle):
            return None
        row = self._db.execute("SELECT person_id FROM handles WHERE platform = ? AND handle = ?",
                               (platform, handle.lower())).fetchone()
        return self.get(row[0]) if row else None

    def get(self, person_id: int) -> Person:
        row = self._db.execute(
            "SELECT id, name, style, stated_age, age_asked, minor_signals, relationship, they_started, blocked, muted "
            "FROM people WHERE id = ?", (person_id,)).fetchone()
        if row is None:
            raise KeyError(person_id)
        return Person(row[0], row[1], row[2], row[3], row[4], row[5], row[6], bool(row[7]), bool(row[8]), bool(row[9]))

    def link(self, person: Person, platform: str, handle: str) -> None:
        """The same person on another platform (only when they told her so)."""
        if person.id is None or platform not in PLATFORMS:
            return
        self._db.execute("INSERT OR REPLACE INTO handles VALUES (?, ?, ?)", (platform, handle.strip().lower(), person.id))
        self._db.commit()

    def handles(self, person: Person) -> list[tuple[str, str]]:
        if person.id is None:
            return []
        return self._db.execute("SELECT platform, handle FROM handles WHERE person_id = ? ORDER BY platform",
                                (person.id,)).fetchall()

    _FIELDS = {"name", "style", "stated_age", "age_asked", "minor_signals", "relationship", "they_started",
               "blocked", "muted"}

    def update(self, person: Person, **fields) -> None:
        if person.id is None:
            for key, value in fields.items():
                setattr(person, key, value)
            return
        bad = set(fields) - self._FIELDS
        if bad:
            raise ValueError(f"unknown fields {sorted(bad)}")
        for key, value in fields.items():
            setattr(person, key, value)
            self._db.execute(f"UPDATE people SET {key} = ?, updated = ? WHERE id = ?",
                             (int(value) if isinstance(value, bool) else value, self._clock(), person.id))
        self._db.commit()

    # -- what she remembers -----------------------------------------------------------------------------------------
    def note_fact(self, person: Person, text: str, *, interests_only: bool = False) -> bool:
        text = " ".join(str(text or "").split())[:FACT_CHARS]
        if person.id is None or len(text) < 6 or _SENSITIVE.search(text):
            return False
        if interests_only and not _INTEREST.match(text):
            return False
        if self._db.execute("SELECT 1 FROM facts WHERE person_id = ? AND lower(text) = lower(?)",
                            (person.id, text)).fetchone():
            return False
        self._db.execute("INSERT INTO facts (person_id, text, ts) VALUES (?, ?, ?)", (person.id, text, self._clock()))
        self._db.execute("DELETE FROM facts WHERE person_id = ? AND id NOT IN (SELECT id FROM facts WHERE person_id = ? "
                         "ORDER BY id DESC LIMIT ?)", (person.id, person.id, MAX_FACTS))
        self._db.commit()
        return True

    def drop_last_fact(self, person: Person) -> bool:
        """'Don't remember that': removes the newest fact."""
        if person.id is None:
            return False
        cur = self._db.execute("DELETE FROM facts WHERE id = (SELECT max(id) FROM facts WHERE person_id = ?)",
                               (person.id,))
        self._db.commit()
        return cur.rowcount > 0

    def facts(self, person: Person, limit: int = 12) -> list[str]:
        if person.id is None:
            return []
        rows = self._db.execute("SELECT text FROM facts WHERE person_id = ? ORDER BY id DESC LIMIT ?",
                                (person.id, limit)).fetchall()
        return [r[0] for r in reversed(rows)]

    def note_moment(self, person: Person, platform: str, line: str) -> None:
        line = " ".join(str(line or "").split())[:MOMENT_CHARS]
        if person.id is None or not line:
            return
        self._db.execute("INSERT INTO moments (person_id, platform, line, ts) VALUES (?, ?, ?, ?)",
                         (person.id, platform, line, self._clock()))
        self._db.execute("DELETE FROM moments WHERE person_id = ? AND id NOT IN (SELECT id FROM moments "
                         "WHERE person_id = ? ORDER BY id DESC LIMIT ?)", (person.id, person.id, MAX_MOMENTS))
        self._db.commit()

    def moments(self, person: Person, limit: int = 8) -> list[tuple[str, str]]:
        if person.id is None:
            return []
        rows = self._db.execute("SELECT platform, line FROM moments WHERE person_id = ? ORDER BY id DESC LIMIT ?",
                                (person.id, limit)).fetchall()
        return list(reversed(rows))

    def silent_for(self, person: Person) -> float | None:
        """Seconds since the last remembered exchange with this person (this memory's clock), None if there is none."""
        if person.id is None:
            return None
        row = self._db.execute("SELECT MAX(ts) FROM moments WHERE person_id = ?", (person.id,)).fetchone()
        return max(0.0, self._clock() - row[0]) if row and row[0] is not None else None

    def context(self, person: Person) -> str:
        """The block added to her prompt when she talks to this person."""
        if person.id is None:
            return f"You are talking with {person.name}. They asked you to forget them: you keep nothing about them."
        lines = [f"You are talking with {person.name} ({person.relationship})."]
        others = [f"{p}: {h}" for p, h in self.handles(person)]
        if len(others) > 1:
            lines.append("Same person on: " + ", ".join(others) + ".")
        if person.stated_age is not None:
            lines.append(f"They told you they are {person.stated_age}.")
        if person.style:
            lines.append(f"How they like to be talked to: {person.style}")
        facts = self.facts(person)
        if facts:
            lines.append("Things they told you: " + "; ".join(facts) + ".")
        return "\n".join(lines)

    # -- consent ----------------------------------------------------------------------------------------------------
    def forget(self, platform: str, handle: str) -> bool:
        """Delete the person behind this handle and everything about them; remember only that they said so."""
        now = self._clock()
        row = self._db.execute("SELECT person_id FROM handles WHERE platform = ? AND handle = ?",
                               (platform, handle.strip().lower())).fetchone()
        keys = {self._tombstone(platform, handle.strip())}
        if row is not None:
            for p, h in self._db.execute("SELECT platform, handle FROM handles WHERE person_id = ?", (row[0],)):
                keys.add(self._tombstone(p, h))
            self._db.execute("DELETE FROM people WHERE id = ?", (row[0],))
        self._db.executemany("INSERT OR REPLACE INTO forgotten VALUES (?, ?)", [(k, now) for k in keys])
        self._db.commit()
        return row is not None

    def allow_again(self, platform: str, handle: str) -> None:
        self._db.execute("DELETE FROM forgotten WHERE key = ?", (self._tombstone(platform, handle.strip()),))
        self._db.commit()
