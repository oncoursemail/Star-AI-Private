"""One SQLite file for STAR's life extras: the shared scrapbook, her own goals, skill confidence and her creative gallery.
<home>/life/extras/life.sqlite3 (home = STAR Home's data folder, else the app data folder). Nothing here calls a model.

Settings (<home>/settings.json), all read by `flag()`: scrapbook, goals, studio and style are ON by default (her PC profile), the owner-side
pieces (the status API and the desktop weather widget) are opt-in and OFF by default.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

FLAGS = {"life_scrapbook_enabled": True, "life_goals_enabled": True, "life_studio_enabled": True,
         "life_api_enabled": False, "life_widget_enabled": False, "life_style_enabled": True}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS moments (
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
  feeling TEXT NOT NULL DEFAULT '', media TEXT NOT NULL DEFAULT '', media_kind TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL UNIQUE, first_key TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS moments_first ON moments(first_key);
CREATE TABLE IF NOT EXISTS anniversaries (id INTEGER PRIMARY KEY, moment_id INTEGER NOT NULL, label TEXT NOT NULL,
  shown_at REAL NOT NULL, day TEXT NOT NULL, UNIQUE(moment_id, label));
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY, text TEXT NOT NULL, domain TEXT NOT NULL, skill TEXT NOT NULL DEFAULT '',
  interest TEXT NOT NULL DEFAULT '', proof_kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  created REAL NOT NULL, due REAL NOT NULL, tries INTEGER NOT NULL DEFAULT 0, ok_tries INTEGER NOT NULL DEFAULT 0,
  streak INTEGER NOT NULL DEFAULT 0, best_streak INTEGER NOT NULL DEFAULT 0, last_day TEXT NOT NULL DEFAULT '',
  closed REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', proof TEXT NOT NULL DEFAULT '',
  announced INTEGER NOT NULL DEFAULT 0, home_goal TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS goal_log (id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL, ts REAL NOT NULL,
  kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', verified INTEGER NOT NULL DEFAULT 0, ref TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS skills (skill TEXT PRIMARY KEY, confidence REAL NOT NULL, n INTEGER NOT NULL DEFAULT 0,
  updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS works (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, theme TEXT NOT NULL DEFAULT '',
  path TEXT NOT NULL DEFAULT '', created REAL NOT NULL, status TEXT NOT NULL, why TEXT NOT NULL DEFAULT '',
  improve TEXT NOT NULL DEFAULT '', feeling TEXT NOT NULL DEFAULT '', verified INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS style_history (id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, choice TEXT NOT NULL,
  why TEXT NOT NULL DEFAULT '', mood TEXT NOT NULL DEFAULT '', season TEXT NOT NULL DEFAULT '', ref TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, week TEXT NOT NULL, traits TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS style_prefs (trait TEXT PRIMARY KEY, weight REAL NOT NULL, updated REAL NOT NULL);
"""


def base(home=None) -> Path:
    """The data folder: the one handed in, else STAR Home's folder on her PC, else the app data folder."""
    if home is not None:
        return Path(home)
    try:
        from ..home.paths import home_dir
        found = home_dir()
        if found is not None:
            return Path(found)
    except ImportError:
        pass
    from ..desktop_core import app_data
    return app_data()


def flag(name: str, home=None) -> bool:
    try:
        raw = json.loads((base(home) / "settings.json").read_text(encoding="utf-8"))
        value = raw.get(name) if isinstance(raw, dict) else None
    except (OSError, ValueError):
        value = None
    return value if isinstance(value, bool) else FLAGS[name]


def day_of(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class LifeStore:
    def __init__(self, path=None, *, home=None, clock=time.time) -> None:
        self.home = base(home)
        self.path = Path(path) if path else self.home / "life" / "extras" / "life.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        with self.lock:
            self.db.executescript(_SCHEMA)
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def meta(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
            self.db.commit()

    def run(self, sql: str, args: tuple = ()):
        """A write (committed); returns the cursor."""
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        return self.db.execute(sql, args).fetchall()


_stores: dict[str, LifeStore] = {}
_stores_lock = threading.Lock()


def default_store(home=None) -> LifeStore:
    path = str(base(home) / "life" / "extras" / "life.sqlite3")
    with _stores_lock:
        if path not in _stores:
            _stores[path] = LifeStore(path, home=home)
        return _stores[path]
