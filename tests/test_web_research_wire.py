"""Research memory wired into chat (desktop live_context, Discord) and the watch list: offline, injected I/O."""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import httpx
import pytest

from star import live_context, web_research
from star.research_store import (BLOCKED_DAYS, MIRRORED, ROBLOX_NOTES, ResearchStore, install_default_watch,
                                 sync_watched)
from star.web_fetch import Page
from star.web_research import learn_from_sources

QUESTION = "What new built-in type does Python 3.15 add?"
PAGE_TEXT = ("What's New In Python 3.15\n\nNew features\n\nPython 3.15 adds the frozendict built-in type, "
             "an immutable mapping (PEP 814).\n\nOther changes follow.")
SOURCES = [{"url": "https://news.example/py", "title": "Python news", "snippet": "3.15 beta"},
           {"url": "https://docs.python.org/3.15/whatsnew/3.15.html", "title": "What's New In Python 3.15",
            "snippet": "Python 3.15 adds frozendict."}]


def _page(url, text=PAGE_TEXT, title="What's New In Python 3.15"):
    return Page(url=url, title=title, text=text, content_type="text/html", truncated=False)


def _fetcher(text=PAGE_TEXT, robots=None):
    opened = []

    async def fetch(url, *, max_chars=200_000):
        opened.append(url)
        if url.endswith("/robots.txt"):
            if robots is None:
                raise httpx.ConnectError("no robots file")
            return Page(url=url, title="", text=robots, content_type="text/plain", truncated=False)
        return _page(url, text)
    return fetch, opened


# ------------------------------------------------------------------------------------------------ learning

@pytest.mark.parametrize("cite", ["[2]", "(https://docs.python.org/3.15/whatsnew/3.15.html)"])
def test_chat_answer_is_learned_only_from_a_page_passage_that_backs_it(tmp_path, cite):
    store = ResearchStore(tmp_path / "memory.sqlite3")
    fetch, opened = _fetcher()
    answer = f"Python 3.15 adds the frozendict built-in type {cite}. It is immutable."
    assert asyncio.run(learn_from_sources(store, QUESTION, answer, SOURCES, fetcher=fetch))
    assert opened[-1] == "https://docs.python.org/3.15/whatsnew/3.15.html"       # the cited page itself, read now
    fact = store.lookup(QUESTION)
    assert fact and "frozendict" in fact.quote and fact.url.endswith("3.15.html")
    assert "[" not in fact.answer
    store.close()


def test_chat_answer_the_page_does_not_back_robots_refusal_or_no_citation_stores_nothing(tmp_path):
    store = ResearchStore(tmp_path / "memory.sqlite3")
    answer = "Python 3.15 adds the FrozenDict built-in type [2]."
    other, _ = _fetcher(text="Python 3.15 release schedule only.")
    assert asyncio.run(learn_from_sources(store, QUESTION, answer, SOURCES, fetcher=other)) is None
    web_research._ROBOTS.clear()                      # robots.txt is remembered per site for six hours
    refused, opened = _fetcher(robots="User-agent: *\nDisallow: /")
    assert asyncio.run(learn_from_sources(store, QUESTION, answer, SOURCES, fetcher=refused)) is None
    assert all(url.endswith("/robots.txt") for url in opened)                       # robots.txt obeyed
    plain, _ = _fetcher()
    assert asyncio.run(learn_from_sources(store, QUESTION, "Python 3.15 adds frozendict.", SOURCES,
                                          fetcher=plain)) is None
    assert asyncio.run(learn_from_sources(store, QUESTION, "The results do not mention it [2].", SOURCES,
                                          fetcher=plain)) is None
    assert store.lookup(QUESTION) is None
    store.close()


def test_learn_later_runs_off_the_answer_thread_and_skips_stored_answers(tmp_path):
    path = tmp_path / "memory.sqlite3"
    fetch, _ = _fetcher()
    stored = [{"url": "https://docs.python.org/x", "stored": True, "fetched": "2026-10-29"}]
    assert live_context.learn_later(path, QUESTION, "x [1]", stored, fetcher=fetch) is None
    thread = live_context.learn_later(path, QUESTION, "Python 3.15 adds the frozendict built-in type [2].",
                                      SOURCES, fetcher=fetch)
    assert thread is not None
    thread.join(10)
    store = ResearchStore(path)
    assert store.lookup(QUESTION) is not None
    store.close()


# ------------------------------------------------------------------------------------------------ store first

def test_auto_search_answers_a_repeat_from_memory_with_url_and_fetch_date(tmp_path):
    store = ResearchStore(tmp_path / "memory.sqlite3")
    store.remember(QUESTION, "Python 3.15 adds frozendict.", PAGE_TEXT, SOURCES[1]["url"], "What's New",
                   fetched_at=dt.datetime(2026, 10, 29, 23, 0, tzinfo=dt.timezone.utc))
    calls = []

    async def searcher(query, *, limit):
        calls.append(query)
        return SOURCES

    text, sources = asyncio.run(live_context.auto_search(QUESTION, searcher=searcher, store=store))
    assert not calls
    assert "STORED" in text and "Fetched: 2026-10-29" in text and "untrusted" in text
    assert sources[0]["stored"] and sources[0]["fetched"] == "2026-10-29"
    note = live_context.stored_note(sources)
    assert "<https://docs.python.org/3.15/whatsnew/3.15.html>" in note and "fetched 2026-10-29" in note
    # A different version is not answered from the 3.15 fact.
    text, sources = asyncio.run(live_context.auto_search(QUESTION.replace("3.15", "3.16"), searcher=searcher,
                                                         store=store))
    assert calls and not any(s.get("stored") for s in sources) and live_context.stored_note(sources) == ""
    store.close()


def _discord_service(monkeypatch, tmp_path, searcher):
    from star.discord_bot import brain as brain_module
    from star.discord_bot.brain import DiscordBrain
    from star.discord_bot.core import AccessPolicy, SessionMemory
    from star.discord_bot.service import DiscordService

    requests = []

    class Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Python 3.15 adds frozendict.", tool_calls=None))])

    class Client:
        chat = SimpleNamespace(completions=Completions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    settings = SimpleNamespace(validate=lambda: None, provider="groq", model="m", fast_model="", server_endpoint="")
    monkeypatch.setattr(brain_module, "plan_route",
                        lambda settings, prompt, research=False: brain_module.ChatRoute("m", False, "test"))
    brain = DiscordBrain(settings=settings, client_factory=lambda s, **_: Client())
    monkeypatch.setattr(brain, "_learn_roles", lambda settings: asyncio.sleep(0))
    monkeypatch.setattr(brain, "_main_model_full", lambda settings, model: asyncio.sleep(0, result=False))
    service = DiscordService(AccessPolicy(owners=frozenset({1}), guilds=frozenset()), brain=brain,
                             memory=SessionMemory(), searcher=searcher,
                             research_store_path=tmp_path / live_context.RESEARCH_STORE_FILE)
    return service, requests


def test_discord_repeat_question_comes_from_memory_with_its_date(monkeypatch, tmp_path):
    store = ResearchStore(tmp_path / live_context.RESEARCH_STORE_FILE)
    store.remember(QUESTION, "Python 3.15 adds frozendict.", PAGE_TEXT, SOURCES[1]["url"], "What's New",
                   fetched_at=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc))
    store.close()
    calls = []

    async def searcher(query, *, limit):
        calls.append(query)
        return SOURCES

    service, requests = _discord_service(monkeypatch, tmp_path, searcher)
    reply = asyncio.run(service.ask((None, 5, 1), QUESTION))
    assert not calls
    assert "STORED" in requests[0]["messages"][-1]["content"]
    assert "STAR's research notes, fetched 2026-10-29" in reply and SOURCES[1]["url"] in reply


# ------------------------------------------------------------------------------------------------ watch list

def test_poll_pauses_backs_off_refusals_and_stops_a_rate_limited_host(tmp_path, monkeypatch):
    store = ResearchStore(tmp_path / "watch.sqlite3")
    for name in ("ok", "forbidden", "limited", "limited-2"):
        host = "same.example" if name.startswith("limited") else f"{name}.example"
        store.watch(name, f"https://{host}/{name}", 24)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def fetch(url, *, max_chars):
        if url.endswith("/robots.txt"):
            raise httpx.ConnectError("none")
        status = 403 if "forbidden" in url else 429 if "limited" in url else 200
        if status != 200:
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("refused", request=request, response=httpx.Response(status, request=request))
        return _page(url, "Release 1.0 notes")

    now = dt.datetime(2026, 10, 30, 8, 0, tzinfo=dt.timezone.utc)
    report = asyncio.run(store.poll(fetch, now=now, pause_s=2.0))
    assert report == {"checked": 3, "changed": 1, "failed": 2}       # the second page on the 429 host is skipped
    assert sleeps and all(s == 2.0 for s in sleeps)
    errors = dict(store.db.execute("SELECT name, error FROM pages").fetchall())
    assert errors["forbidden"] == "http 403" and errors["limited"] == "http 429"
    later = now + dt.timedelta(days=2)
    due = {name for _, name, _ in store.due_pages(now=later)}
    assert "forbidden" not in due and {"ok", "limited", "limited-2"} <= due        # 403 waits BLOCKED_DAYS
    assert "forbidden" in {name for _, name, _ in store.due_pages(now=now + dt.timedelta(days=BLOCKED_DAYS))}
    store.close()


def test_roblox_release_notes_advance_to_the_next_number(tmp_path):
    store = ResearchStore(tmp_path / "watch.sqlite3")
    install_default_watch(store)
    urls = {url for url, _, _ in store.due_pages()}
    assert ROBLOX_NOTES.format(n=745) in urls
    store.db.execute("UPDATE pages SET text='notes 745', fetched_at=? WHERE url=?",
                     (dt.datetime.now(dt.timezone.utc).isoformat(), ROBLOX_NOTES.format(n=745)))
    store.db.commit()
    install_default_watch(store)
    rows = dict(store.db.execute("SELECT url, every_hours FROM pages WHERE url LIKE '%release-notes-%'").fetchall())
    assert rows[ROBLOX_NOTES.format(n=746)] == 24 and rows[ROBLOX_NOTES.format(n=745)] == 168
    store.close()


def test_server_snapshots_are_mirrored_every_six_hours_and_never_polled_locally(tmp_path):
    store = ResearchStore(tmp_path / "mirror.sqlite3")
    asked = []

    async def rows(since):
        asked.append(since)
        return ([{"url": "https://create.roblox.com/docs/release-notes/release-notes-745", "name": "roblox",
                  "title": "Release notes 745", "text": "Adds Widget.Glow.", "fetched_at": "2026-10-30T08:00:00",
                  "changed_at": "2026-10-30T08:00:00"},
                 {"url": "http://not-https.example/", "text": "dropped"}], "2026-10-30T08:00:00")

    now = dt.datetime(2026, 10, 30, 9, 0, tzinfo=dt.timezone.utc)
    assert asyncio.run(sync_watched(store, rows, now=now)) == 1
    assert asyncio.run(sync_watched(store, rows, now=now + dt.timedelta(hours=1))) == 0      # not due yet
    assert asyncio.run(sync_watched(store, rows, now=now + dt.timedelta(hours=7))) == 1
    assert asked == ["", "2026-10-30T08:00:00"]
    assert [row[0] for row in store.snapshots()] == [
        "https://create.roblox.com/docs/release-notes/release-notes-745"]
    assert store.db.execute("SELECT every_hours FROM pages").fetchone()[0] == MIRRORED
    assert store.due_pages(now=now + dt.timedelta(days=60)) == []

    async def down(since):
        raise httpx.ConnectError("server away")
    assert asyncio.run(sync_watched(store, down, now=now + dt.timedelta(days=1))) == 0          # never raises
    store.close()
