"""The shared scrapbook: things she really did together with the owner (a game won, a picture made, a call, a first), each
saved with a date, a feeling and a reference to the screenshot or clip, and brought up again on anniversaries.

Two rules make it honest, and both are in code:
  * a moment is only stored with a `source` (where it really happened: "home-session:roblox 2026-10-20 21:14", "call:...",
    "owner-added") and a date that is not in the future; the same source is never stored twice;
  * an anniversary line is built only from stored fields (title, feeling, media kind) by a template, never by a model, and
    only for a stored moment whose date really is one month / three / six / twelve... months ago. The chat note hands the
    same facts to the model with "only if it fits", so nothing is invented around them.
Rate limit: at most one anniversary a day and PER_WEEK a week; each (moment, milestone) is brought up once, and it is only
marked as brought up after the reply was sent (`Note.done()`), so a chat that never happened does not use it up.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from .store import LifeStore, day_of, default_store, flag

KINDS = ("game_win", "picture", "call", "first", "build", "song", "other")
PER_WEEK = 2
GRACE_DAYS = 2
_YEARS = ("one year", "two years", "three years", "four years", "five years", "six years", "seven years", "eight years",
          "nine years", "ten years")
MILESTONES = [(1, "one month"), (3, "three months"), (6, "six months")] + [(12 * (i + 1), name) for i, name in enumerate(_YEARS)]
MEDIA_KINDS = {".png": "screenshot", ".jpg": "screenshot", ".jpeg": "screenshot", ".webp": "screenshot",
               ".bmp": "screenshot", ".mp4": "clip", ".webm": "clip", ".gif": "clip", ".mkv": "clip", ".mov": "clip"}


def _clean(text, limit: int) -> str:
    text = " ".join(str(text or "").split())[:limit]
    try:
        from ..redact import redact_text
        return redact_text(text)
    except ImportError:
        return text


def add_moment(store: LifeStore, kind: str, title: str, *, source: str, text: str = "", feeling: str = "",
               media: str = "", ts: float | None = None, first_key: str = "", now: float | None = None) -> int | None:
    """Save one real moment; the new id, or None when it is refused (no source, future date, too short, a repeat, or a
    "first" that is not the first)."""
    now = store.clock() if now is None else now
    ts = now if ts is None else float(ts)
    title, source = _clean(title, 90), _clean(source, 160)
    if kind not in KINDS or len(title) < 4 or len(source) < 4 or ts > now + 60 or ts < 946684800:
        return None
    first_key = "_".join(str(first_key or "").lower().split())[:40]
    if first_key and store.rows("SELECT 1 FROM moments WHERE first_key = ?", (first_key,)):
        return None                                   # it was done before: not a first
    media = str(media or "")[:300]
    media_kind = MEDIA_KINDS.get(Path(media).suffix.lower(), "") if media else ""
    feeling = "".join(c for c in str(feeling or "").lower() if c.isalpha() or c == " ").strip()[:24]
    cur = store.run("INSERT OR IGNORE INTO moments (ts, kind, title, text, feeling, media, media_kind, source, first_key, "
                    "created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts, kind, title, _clean(text, 300), feeling, media, media_kind, source, first_key, now))
    return cur.lastrowid if cur.rowcount else None


def moments(store: LifeStore, limit: int = 100) -> list[dict]:
    cols = ("id", "ts", "kind", "title", "text", "feeling", "media", "media_kind", "source", "first_key")
    return [dict(zip(cols, r)) for r in store.rows(
        f"SELECT {', '.join(cols)} FROM moments ORDER BY ts DESC LIMIT ?", (limit,))]


def _plus_months(date: dt.date, months: int) -> dt.date:
    year, month = divmod(date.year * 12 + date.month - 1 + months, 12)
    month += 1
    return dt.date(year, month, min(date.day, calendar.monthrange(year, month)[1]))


@dataclass
class Anniversary:
    moment: dict
    label: str
    late_days: int = 0
    text: str = ""
    note: str = ""


def milestone_for(ts: float, today: dt.date) -> tuple[str, int] | None:
    """('one month', days late) when `today` is a milestone of the date `ts` or at most GRACE_DAYS after it."""
    start = dt.date.fromtimestamp(ts)
    for months, label in MILESTONES:
        late = (today - _plus_months(start, months)).days
        if 0 <= late <= GRACE_DAYS:
            return label, late
    return None


def compose(moment: dict, label: str, late: int) -> tuple[str, str]:
    """(a plain sentence, a note for the model), both built only from stored fields."""
    when = f"{label} ago" + (" today" if late == 0 else "")
    feeling = f"I felt {moment['feeling']}" if moment["feeling"] else ""
    media = {"screenshot": "I kept a screenshot", "clip": "I kept a clip"}.get(moment["media_kind"], "")
    tail = ". ".join(x for x in (feeling, media) if x)
    first = "the first time: " if moment["first_key"] else ""
    sentence = f"{when[0].upper()}{when[1:]}: {first}{moment['title']}." + (f" {tail}." if tail else "")
    note = (f"(anniversary, only if it fits and only these facts: {when}: {first}{moment['title']}"
            + (f"; {tail}" if tail else "") + ")")
    return sentence, note


def due(store: LifeStore, now: float | None = None) -> Anniversary | None:
    """The anniversary to mention now (usually None): real dated moments only, within the rate limit."""
    now = store.clock() if now is None else now
    today = dt.date.fromtimestamp(now)
    if store.rows("SELECT 1 FROM anniversaries WHERE day = ?", (day_of(now),)):
        return None
    if store.rows("SELECT count(*) FROM anniversaries WHERE shown_at >= ?", (now - 7 * 86400,))[0][0] >= PER_WEEK:
        return None
    found: list[tuple[tuple, Anniversary]] = []
    for moment in moments(store, 1000):
        if moment["ts"] > now or not moment["source"]:
            continue
        hit = milestone_for(moment["ts"], today)
        if hit is None or store.rows("SELECT 1 FROM anniversaries WHERE moment_id = ? AND label = ?",
                                     (moment["id"], hit[0])):
            continue
        text, note = compose(moment, hit[0], hit[1])
        rank = (hit[1], not moment["first_key"], not moment["media"], moment["ts"])   # on time, firsts, with a picture, oldest
        found.append((rank, Anniversary(moment, hit[0], hit[1], text, note)))
    return min(found, key=lambda pair: pair[0])[1] if found else None


def mark_shown(store: LifeStore, anniversary: Anniversary, now: float | None = None) -> None:
    now = store.clock() if now is None else now
    store.run("INSERT OR IGNORE INTO anniversaries (moment_id, label, shown_at, day) VALUES (?,?,?,?)",
              (anniversary.moment["id"], anniversary.label, now, day_of(now)))


@dataclass
class Note:
    """What the chat hook gets: `text` to append to the NEW user message ("" when nothing is due), `done()` after the reply."""
    text: str = ""
    lines: list[str] = field(default_factory=list)
    _done: list = field(default_factory=list)

    def done(self) -> None:
        for call in self._done:
            call()
        self._done = []


def scrapbook_note(home=None, *, store: LifeStore | None = None, now: float | None = None, force: bool = False) -> Note:
    """The scrapbook's part of the chat note (off unless `life_scrapbook_enabled`). Never raises."""
    try:
        if not (force or flag("life_scrapbook_enabled", home)):
            return Note()
        store = store or default_store(home)
        found = due(store, now)
        if found is None:
            return Note()
        return Note(found.note, [found.text], [lambda: mark_shown(store, found, now)])
    except Exception:
        return Note()
