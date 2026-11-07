"""Research knowledge that compounds: verified answers and watched pages, each with source, date and re-check date.

* facts: question -> short answer + the exact quote that supports it + source URL, fetch time and a re-check time
  (7 days for news-like questions, 30 for the rest). A repeated question is answered from a fresh fact first
  (no search); a stale fact is re-checked: the page is fetched again and the quote must still be on it.
* pages: snapshots of watched pages (release notes, changelogs, engine blogs) polled on a schedule, so their text is
  already local when STAR is asked; research() adds their best passages to the evidence.

One SQLite file; page text stays untrusted data (it is only ever shown inside the research evidence frame).
CLI (server or PC, night time): python -m star.research_store poll --db PATH   |   recheck --db PATH
The nightly poll runs on STAR Server 1 (server/research/); the desktop app mirrors the snapshots through the search
gateway (GET /watched, sync_watched below). A page that refuses STAR's reader (401/403, robots.txt) is left alone for
BLOCKED_DAYS, never worked around.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .web_research import Fetcher, anchors, key_terms, robots_allowed

NEWS_DAYS, DEFAULT_DAYS = 7, 30
_NEWSY = re.compile(r"\b(?:news|won|wins|election|raise[sd]?|resign\w*|acquir\w*|ipo|vote|killed|earthquake|today|"
                    r"this week|latest|current)\b", re.I)

# Pages STAR polls so she learns what changed before anyone asks (only sites that serve STAR's reader real text).
DEFAULT_WATCH = (
    ("roblox-release-notes", "https://create.roblox.com/docs/release-notes/release-notes-{roblox_next}", 24),
    ("roblox-devforum-release-notes", "https://devforum.roblox.com/c/updates/release-notes/62", 24),
    ("godot-blog", "https://godotengine.org/blog/", 24),
    ("blender-releases", "https://www.blender.org/download/releases/", 72),
    ("python-downloads", "https://www.python.org/downloads/", 72),
    ("rust-blog", "https://blog.rust-lang.org/", 72),
    ("go-releases", "https://go.dev/doc/devel/release", 72),
    ("node-releases", "https://nodejs.org/en/about/previous-releases", 72),
    ("luau-releases", "https://github.com/luau-lang/luau/releases", 72),
    ("minecraft-changelogs", "https://feedback.minecraft.net/hc/en-us/sections/360001186971-Release-Changelogs", 24),
    ("minecraft-java-patch-notes", "https://launchercontent.mojang.com/v2/javaPatchNotes.json", 24),
    ("minecraft-bedrock-patch-notes", "https://launchercontent.mojang.com/v2/bedrockPatchNotes.json", 24),
)
ROBLOX_NOTES = "https://create.roblox.com/docs/release-notes/release-notes-{n}"
ROBLOX_NOTES_FIRST = 745            # the newest number when this list was written; later ones are found by polling
BLOCKED_DAYS = 30                   # a page that answered 401/403 or is disallowed by robots.txt waits this long
PAUSE_S = 2.0                       # between two watched pages (one at a time, never in parallel)
MIRRORED = -1                       # every_hours of a page copied from the server: never polled locally


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def qkey(question: str) -> str:
    return " ".join(sorted(set(key_terms(question))))


@dataclass
class Fact:
    id: int
    question: str
    answer: str
    quote: str
    url: str
    title: str
    fetched_at: str
    recheck_at: str
    status: str


class ResearchStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=10)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, question TEXT, qkey TEXT, anchors TEXT,
                answer TEXT, quote TEXT, url TEXT, title TEXT, fetched_at TEXT, recheck_at TEXT,
                status TEXT DEFAULT 'fresh', hits INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS facts_qkey ON facts(qkey);
            CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, name TEXT, title TEXT, text TEXT, sha TEXT,
                fetched_at TEXT, changed_at TEXT, every_hours INTEGER, error TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -------------------------------------------------------------------------------- facts
    def remember(self, question: str, answer: str, quote: str, url: str, title: str = "",
                 fetched_at: dt.datetime | None = None) -> int:
        if not (question.strip() and answer.strip() and quote.strip() and url.startswith("https://")):
            raise ValueError("a fact needs a question, an answer, a supporting quote and an https source")
        fetched = fetched_at or _now()
        days = NEWS_DAYS if _NEWSY.search(question) else DEFAULT_DAYS
        key = qkey(question)
        self.db.execute("DELETE FROM facts WHERE qkey=?", (key,))
        cur = self.db.execute(
            "INSERT INTO facts(question,qkey,anchors,answer,quote,url,title,fetched_at,recheck_at,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,'fresh')",
            (question.strip()[:600], key, " ".join(anchors(question)), answer.strip()[:1200], quote.strip()[:600],
             url[:1200], title[:200], fetched.isoformat(), (fetched + dt.timedelta(days=days)).isoformat()))
        self.db.commit()
        return int(cur.lastrowid or 0)

    def lookup(self, question: str, *, now: dt.datetime | None = None, min_overlap: float = 0.85) -> Fact | None:
        """A fresh fact for this question: the same key terms (or >= 85% overlap) and exactly the same anchors
        (version numbers / ids), so 'release notes 743' never answers '744'."""
        now = now or _now()
        terms, anchor = set(key_terms(question)), " ".join(anchors(question))
        best, best_score = None, 0.0
        for row in self.db.execute("SELECT id,question,answer,quote,url,title,fetched_at,recheck_at,status,qkey,anchors "
                                   "FROM facts WHERE status='fresh' AND recheck_at>?", (now.isoformat(),)):
            if row[10] != anchor:
                continue
            other = set(row[9].split())
            score = len(terms & other) / (len(terms | other) or 1)
            if score > best_score:
                best, best_score = row, score
        if best is None or best_score < min_overlap:
            return None
        self.db.execute("UPDATE facts SET hits=hits+1 WHERE id=?", (best[0],))
        self.db.commit()
        return Fact(*best[:9])

    def due(self, *, now: dt.datetime | None = None, limit: int = 100) -> list[Fact]:
        now = now or _now()
        rows = self.db.execute("SELECT id,question,answer,quote,url,title,fetched_at,recheck_at,status FROM facts "
                               "WHERE status='fresh' AND recheck_at<=? ORDER BY recheck_at LIMIT ?",
                               (now.isoformat(), limit)).fetchall()
        return [Fact(*row) for row in rows]

    async def recheck(self, fact: Fact, fetcher: Fetcher, *, now: dt.datetime | None = None) -> str:
        """Fetch the source again: the quote still there -> fresh for another period; gone -> 'stale' (never
        served again until researched anew); unreachable -> left due for the next run."""
        now = now or _now()
        try:
            page = await fetcher(fact.url, max_chars=400_000)
        except Exception:  # noqa: BLE001
            return "unreachable"
        text = " ".join(str(getattr(page, "text", "")).split()).lower()
        if " ".join(fact.quote.split()).lower()[:200] in text:
            days = NEWS_DAYS if _NEWSY.search(fact.question) else DEFAULT_DAYS
            self.db.execute("UPDATE facts SET fetched_at=?, recheck_at=? WHERE id=?",
                            (now.isoformat(), (now + dt.timedelta(days=days)).isoformat(), fact.id))
            status = "fresh"
        else:
            self.db.execute("UPDATE facts SET status='stale' WHERE id=?", (fact.id,))
            status = "stale"
        self.db.commit()
        return status

    # -------------------------------------------------------------------------------- watched pages
    def watch(self, name: str, url: str, every_hours: int = 24) -> None:
        if not url.startswith("https://"):
            raise ValueError("watched pages must be https")
        self.db.execute("INSERT INTO pages(url,name,every_hours) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET "
                        "name=excluded.name, every_hours=excluded.every_hours", (url, name, every_hours))
        self.db.commit()

    def due_pages(self, *, now: dt.datetime | None = None) -> list[tuple[str, str, int]]:
        now = now or _now()
        out = []
        for url, name, fetched, every, error in self.db.execute(
                "SELECT url,name,fetched_at,every_hours,error FROM pages"):
            if every is not None and every < 0:
                continue                           # mirrored from the server: polled there, not here
            wait = (dt.timedelta(days=BLOCKED_DAYS) if error in ("http 401", "http 403", "robots")
                    else dt.timedelta(hours=every or 24))
            if not fetched or dt.datetime.fromisoformat(fetched) + wait <= now:
                out.append((url, name, every))
        return out

    async def poll(self, fetcher: Fetcher, *, now: dt.datetime | None = None, pause_s: float = PAUSE_S) -> dict:
        """Fetch every due watched page one at a time with a pause between them, store the new snapshot when its
        text changed. robots.txt is obeyed; a 401/403 or robots refusal is recorded and left alone for
        BLOCKED_DAYS; a 429 stops this run for that host."""
        now = now or _now()
        report = {"checked": 0, "changed": 0, "failed": 0}
        limited: set[str] = set()
        for n, (url, _, _) in enumerate(self.due_pages(now=now)):
            host = url.split("/")[2]
            if host in limited:
                continue
            if n and pause_s > 0:
                await asyncio.sleep(pause_s)
            report["checked"] += 1
            try:
                if not await robots_allowed(url, fetcher):
                    raise PermissionError("robots")
                page = await fetcher(url, max_chars=400_000)
                text = str(getattr(page, "text", ""))
                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                old = self.db.execute("SELECT sha FROM pages WHERE url=?", (url,)).fetchone()
                changed = not old or old[0] != sha
                self.db.execute("UPDATE pages SET title=?, text=?, sha=?, fetched_at=?, error='', "
                                "changed_at=CASE WHEN ? THEN ? ELSE changed_at END WHERE url=?",
                                (str(getattr(page, "title", ""))[:200], text, sha, now.isoformat(), changed,
                                 now.isoformat(), url))
                report["changed"] += int(changed)
            except Exception as exc:  # noqa: BLE001 - one site down never stops the others
                report["failed"] += 1
                status = getattr(getattr(exc, "response", None), "status_code", None)
                error = f"http {status}" if status else ("robots" if isinstance(exc, PermissionError) else type(exc).__name__)
                if status == 429:
                    limited.add(host)
                self.db.execute("UPDATE pages SET fetched_at=?, error=? WHERE url=?", (now.isoformat(), error, url))
            self.db.commit()
        return report

    def snapshots(self) -> list[tuple[str, str, str, str]]:
        """(url, title, text, fetched_at) of every stored page snapshot."""
        return [tuple(r) for r in self.db.execute(
            "SELECT url,title,text,fetched_at FROM pages WHERE text IS NOT NULL AND text!=''")]

    def latest_roblox_notes(self) -> int | None:
        """The highest Roblox release-notes number with a stored snapshot."""
        prefix = ROBLOX_NOTES.format(n="")
        numbers = [int(url[len(prefix):]) for (url,) in self.db.execute(
            "SELECT url FROM pages WHERE url LIKE ? AND text IS NOT NULL AND text!=''", (prefix + "%",))
            if url[len(prefix):].isdigit()]
        return max(numbers) if numbers else None

    # -------------------------------------------------------------------------------- mirror (desktop / Discord)
    def get_meta(self, key: str) -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else ""

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
        self.db.commit()

    def import_pages(self, rows: list[dict]) -> int:
        """Snapshots copied from the server's watch list (GET /watched): stored as mirrored pages, never polled here."""
        count = 0
        for row in rows:
            url, text = str(row.get("url", "")), str(row.get("text", ""))
            if not url.startswith("https://") or not text.strip() or len(url) > 1200:
                continue
            self.db.execute(
                "INSERT INTO pages(url,name,title,text,sha,fetched_at,changed_at,every_hours,error) "
                "VALUES(?,?,?,?,?,?,?,?,'') ON CONFLICT(url) DO UPDATE SET name=excluded.name, title=excluded.title, "
                "text=excluded.text, sha=excluded.sha, fetched_at=excluded.fetched_at, changed_at=excluded.changed_at, "
                "every_hours=excluded.every_hours, error=''",
                (url, str(row.get("name", ""))[:80], str(row.get("title", ""))[:200], text[:400_000],
                 hashlib.sha256(text.encode("utf-8")).hexdigest(), str(row.get("fetched_at", ""))[:40],
                 str(row.get("changed_at", ""))[:40], MIRRORED))
            count += 1
        self.db.commit()
        return count


SYNC_HOURS = 6


async def sync_watched(store: ResearchStore, fetch_rows, *, now: dt.datetime | None = None,
                       timeout: float = 8.0) -> int:
    """Mirror the server's watched-page snapshots into this store, at most every SYNC_HOURS. `fetch_rows(since)`
    returns (rows, newest changed_at) for pages changed after `since` (web_search.fetch_watched). Never raises:
    an unreachable server only means the snapshots stay as they were."""
    now = now or _now()
    last = store.get_meta("watched_synced_at")
    if last and dt.datetime.fromisoformat(last) + dt.timedelta(hours=SYNC_HOURS) > now:
        return 0
    try:
        rows, newest = await asyncio.wait_for(fetch_rows(store.get_meta("watched_since")), timeout)
    except Exception:  # noqa: BLE001 - mirroring is best effort
        return 0
    count = store.import_pages(rows)
    if newest:
        store.set_meta("watched_since", str(newest)[:40])
    store.set_meta("watched_synced_at", now.isoformat())
    return count


def install_default_watch(store: ResearchStore, *, roblox_next: int | None = None) -> None:
    """The default watch list. Roblox release notes: the newest stored number keeps a weekly check and the next
    number is checked daily until it appears (`roblox_next` overrides the next number)."""
    latest = store.latest_roblox_notes()
    if roblox_next is None:
        roblox_next = latest + 1 if latest is not None else ROBLOX_NOTES_FIRST
    for name, url, every in DEFAULT_WATCH:
        if "{roblox_next}" in url:
            url = url.format(roblox_next=roblox_next)
        store.watch(name, url, every)
    if latest is not None and latest != roblox_next:
        store.watch("roblox-release-notes-latest", ROBLOX_NOTES.format(n=latest), 168)
    prefix = ROBLOX_NOTES.format(n="")
    keep = {ROBLOX_NOTES.format(n=roblox_next), ROBLOX_NOTES.format(n=latest)}
    for (url,) in store.db.execute("SELECT url FROM pages WHERE url LIKE ?", (prefix + "%",)).fetchall():
        if url not in keep:
            store.db.execute("DELETE FROM pages WHERE url=? AND (text IS NULL OR text='')", (url,))  # a miss
            store.db.execute("UPDATE pages SET every_hours=720, name='roblox-release-notes-old' WHERE url=?", (url,))
    store.db.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.research_store")
    parser.add_argument("command", choices=["poll", "recheck", "status"])
    parser.add_argument("--db", required=True)
    parser.add_argument("--roblox-next", type=int, default=None, help="next Roblox release notes number to watch")
    args = parser.parse_args(argv)
    from .web_fetch import fetch_page
    store = ResearchStore(args.db)
    try:
        if args.command == "poll":
            install_default_watch(store, roblox_next=args.roblox_next)
            print(json.dumps(asyncio.run(store.poll(fetch_page))))
        elif args.command == "recheck":
            async def run() -> dict:
                counts: dict[str, int] = {}
                for fact in store.due():
                    status = await store.recheck(fact, fetch_page)
                    counts[status] = counts.get(status, 0) + 1
                return counts
            print(json.dumps(asyncio.run(run())))
        else:
            facts = store.db.execute("SELECT status, COUNT(*) FROM facts GROUP BY status").fetchall()
            pages = store.db.execute("SELECT COUNT(*), SUM(text IS NOT NULL AND text!='') FROM pages").fetchone()
            errors = dict(store.db.execute("SELECT name, error FROM pages WHERE error!=''").fetchall())
            print(json.dumps({"facts": dict(facts), "pages": pages[0], "pages_with_text": pages[1] or 0,
                              "page_errors": errors}))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
