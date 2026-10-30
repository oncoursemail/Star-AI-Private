"""Research knowledge that compounds: verified answers and watched pages, each with source, date and re-check date.

* facts: question -> short answer + the exact quote that supports it + source URL, fetch time and a re-check time
  (7 days for news-like questions, 30 for the rest). A repeated question is answered from a fresh fact first
  (no search); a stale fact is re-checked: the page is fetched again and the quote must still be on it.
* pages: snapshots of watched pages (release notes, changelogs, engine blogs) polled on a schedule, so their text is
  already local when STAR is asked; research() adds their best passages to the evidence.

One SQLite file; page text stays untrusted data (it is only ever shown inside the research evidence frame).
CLI (server or PC, night time): python -m star.research_store poll --db PATH   |   recheck --db PATH
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
    ("minecraft-changelogs", "https://feedback.minecraft.net/hc/en-us/sections/360001186971-Release-Changelogs", 24),
)



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
        for url, name, fetched, every in self.db.execute("SELECT url,name,fetched_at,every_hours FROM pages"):
            if not fetched or dt.datetime.fromisoformat(fetched) + dt.timedelta(hours=every or 24) <= now:
                out.append((url, name, every))
        return out

    async def poll(self, fetcher: Fetcher, *, now: dt.datetime | None = None) -> dict:
        """Fetch every due watched page (one at a time: polite), store the new snapshot when its text changed."""
        now = now or _now()
        report = {"checked": 0, "changed": 0, "failed": 0}
        for url, _, _ in self.due_pages(now=now):
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
                self.db.execute("UPDATE pages SET fetched_at=?, error=? WHERE url=?", (now.isoformat(), error, url))
            self.db.commit()
        return report

    def snapshots(self) -> list[tuple[str, str, str, str]]:
        """(url, title, text, fetched_at) of every stored page snapshot."""
        return [tuple(r) for r in self.db.execute(
            "SELECT url,title,text,fetched_at FROM pages WHERE text IS NOT NULL AND text!=''")]


def install_default_watch(store: ResearchStore, *, roblox_next: int | None = None) -> None:
    for name, url, every in DEFAULT_WATCH:
        if "{roblox_next}" in url:
            if roblox_next is None:
                continue
            url = url.format(roblox_next=roblox_next)
        store.watch(name, url, every)


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
            print(json.dumps({"facts": dict(facts), "pages": pages[0], "pages_with_text": pages[1] or 0}))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
