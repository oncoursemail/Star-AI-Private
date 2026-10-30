"""Real async cancellation/deadline and Team wiring checks with offline providers.

Event barriers control when operations become active. No external endpoint,
model, saved credential, fixture answer, or baseline is consulted or changed.
"""
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from star.research_session import ResearchBudget, ResearchSession
from star.web_fetch import Page


QUESTION = "Compare Roblox animation APIs and documented quality limitations"


def _page(url):
    return Page(url=url, title="Retrieved animation reference",
                text="Roblox animation version A supports ten channels.",
                content_type="text/plain", truncated=False)


def test_cancelling_searches_preserves_successful_evidence_and_joins_workers():
    async def scenario():
        blocked = asyncio.Event()
        calls, cancelled = [], []
        active = 0

        async def search(query, *, limit):
            nonlocal active
            number = len(calls)
            calls.append(query)
            if number == 0:
                return [{"url": "https://references.example/retained",
                         "title": "Completed search", "snippet": "Evidence already retrieved"}]
            active += 1
            if active == 2:
                blocked.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(number)
                raise
            finally:
                active -= 1

        session = ResearchSession(QUESTION, searcher=search,
                                  budget=ResearchBudget(max_pages=0, concurrency=2,
                                                        total_seconds=5))
        task = asyncio.create_task(session.collect())
        try:
            await asyncio.wait_for(blocked.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert active == 0 and set(cancelled) == {1, 2}
        assert len(calls) == 3
        assert session.summary()["status"] == "cancelled"
        manifest = session.source_manifest()
        assert len(manifest) == 1
        assert manifest[0]["requested_url"] == "https://references.example/retained"
        assert manifest[0]["status"] == "discovered"

    asyncio.run(scenario())


def test_cancelling_page_reads_keeps_finished_page_and_cleans_active_readers():
    async def scenario():
        blocked = asyncio.Event()
        active = 0
        cancelled, opened = [], []

        async def search(query, *, limit):
            return [{"url": f"https://references.example/{name}", "snippet": name}
                    for name in ("retained", "slow-one", "slow-two")]

        async def fetch(url):
            nonlocal active
            opened.append(url)
            if url.endswith("/retained"):
                return _page(url)
            active += 1
            if active == 2:
                blocked.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(url)
                raise
            finally:
                active -= 1

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(concurrency=2, total_seconds=5))
        task = asyncio.create_task(session.collect())
        try:
            await asyncio.wait_for(blocked.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert active == 0 and len(cancelled) == 2
        assert len(opened) == 3
        assert session.summary()["status"] == "cancelled"
        manifest = session.source_manifest()
        assert manifest[0]["status"] == "read"
        assert all(row["status"] != "read" for row in manifest[1:])
        assert "ten channels" in session.context()

    asyncio.run(scenario())


def test_total_deadline_cancels_hung_searches_and_returns_available_evidence():
    async def scenario():
        calls = []
        active = cancelled = 0

        async def search(query, *, limit):
            nonlocal active, cancelled
            calls.append(query)
            if len(calls) == 1:
                return [{"url": "https://references.example/retained", "snippet": "Available"}]
            active += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled += 1
                raise
            finally:
                active -= 1

        session = ResearchSession(QUESTION, searcher=search,
                                  budget=ResearchBudget(max_pages=0, total_seconds=.1))
        assert await asyncio.wait_for(session.collect(), timeout=2) is session
        assert session.summary()["status"] == "timed_out"
        assert active == 0 and cancelled == 2
        assert len(session.source_manifest()) == 1
        calls_before = len(calls)
        assert not await session.followup("Roblox animation evidence after deadline")
        assert len(calls) == calls_before

    asyncio.run(scenario())


def test_total_deadline_also_covers_an_active_page_reader():
    async def scenario():
        started = cancelled = False

        async def search(query, *, limit):
            return [{"url": "https://references.example/slow-page", "snippet": "Snippet only"}]

        async def fetch(url):
            nonlocal started, cancelled
            started = True
            try:
                # Represents a page whose body never finishes, even if bytes keep arriving.
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_pages=1, total_seconds=.1))
        await asyncio.wait_for(session.collect(), timeout=2)
        assert started and cancelled
        summary = session.summary()
        assert summary["status"] == "timed_out"
        assert summary["pages"] == 1 and summary["sources_read"] == 0
        assert session.source_manifest()[0]["status"] != "read"

    asyncio.run(scenario())


def test_followup_cannot_reset_the_session_deadline_after_collection():
    async def scenario():
        queries = []

        async def search(query, *, limit):
            queries.append(query)
            return [{"url": "https://references.example/first", "snippet": "Retrieved"}]

        session = ResearchSession(QUESTION, searcher=search,
                                  budget=ResearchBudget(max_pages=0, total_seconds=.05))
        await session.collect()
        await asyncio.sleep(.07)
        assert not await session.followup("Roblox animation followup after initial processing")
        assert len(queries) == 3

    asyncio.run(scenario())


class _Completions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        system = kwargs["messages"][0]["content"]
        if "Combine specialist observations" in system:
            content = "Version A supports ten channels [S1]."
        elif "FOLLOWUP_QUERY" in system:
            content = "Check the limitations.\nFOLLOWUP_QUERY: Roblox animation version limitations"
        else:
            content = "Use the supplied evidence and preserve its qualifications."
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=None))])


@pytest.mark.parametrize("enabled,research", [(False, True), (True, False), (True, True)])
def test_legacy_team_opens_pages_only_when_both_research_and_deep_setting_are_enabled(
        tmp_path, enabled, research):
    from star.desktop_core import Settings
    from star.team_service import run_research_team

    async def scenario():
        model = _Completions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=model))
        queries, opened = [], []

        async def search(query, *, limit):
            queries.append(query)
            return [{"url": f"https://references.example/{len(queries)}", "title": "Reference",
                     "snippet": "A short discovery snippet"}]

        async def fetch(url):
            opened.append(url)
            return _page(url)

        settings = Settings(endpoint="http://127.0.0.1:8080/v1", model="offline",
                            project="STAR", knowledge_endpoint="off",
                            deep_research_enabled=enabled, web_research_v2=False)
        answer, result = await run_research_team(
            prompt=QUESTION, home=tmp_path, settings=settings, parallel=1,
            client=client, research=research, web_provider=search, page_provider=fetch,
            research_budget=ResearchBudget(total_seconds=5))
        assert result.completed and len(model.calls) == 4
        assert all("tools" not in call for call in model.calls)
        supplied = "\n".join(call["messages"][1]["content"] for call in model.calls)
        if enabled and research:
            assert len(queries) == 4 and len(opened) == 4
            assert "Roblox animation version A supports ten channels." in supplied
            assert "https://references.example/" in answer
        elif research:
            assert len(queries) == 4 and not opened
            assert "pages were not opened" in supplied
            assert "not opened or verified" in answer
        else:
            assert not queries and not opened
        if research:
            with sqlite3.connect(tmp_path / "research-runs.sqlite3") as db:
                status, searches = db.execute("SELECT status,searches FROM research_runs").fetchone()
            assert status == "completed" and searches == len(queries)

    asyncio.run(scenario())


def test_team_cancellation_during_page_read_records_cancelled_and_stops_workers(tmp_path):
    from star.desktop_core import Settings
    from star.team_service import run_research_team

    async def scenario():
        started = asyncio.Event()
        cancelled = False
        model = _Completions()

        async def search(query, *, limit):
            return [{"url": "https://references.example/slow", "snippet": "Discovery"}]

        async def fetch(url):
            nonlocal cancelled
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

        settings = Settings(endpoint="http://127.0.0.1:8080/v1", model="offline",
                            project="STAR", knowledge_endpoint="off",
                            deep_research_enabled=True, web_research_v2=False)
        task = asyncio.create_task(run_research_team(
            prompt=QUESTION, home=tmp_path, settings=settings, research=True,
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)),
            web_provider=search, page_provider=fetch,
            research_budget=ResearchBudget(total_seconds=5)))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert cancelled and not model.calls
        with sqlite3.connect(tmp_path / "research-runs.sqlite3") as db:
            assert db.execute("SELECT status FROM research_runs").fetchone()[0] == "cancelled"

    asyncio.run(scenario())


def test_deep_team_refuses_insufficient_context_before_search_or_model_calls(tmp_path):
    from star.desktop_core import Settings
    from star.team_service import run_research_team

    async def scenario():
        model = _Completions()
        searches, pages = [], []

        async def search(query, *, limit):
            searches.append(query)
            return []

        async def fetch(url):
            pages.append(url)
            return _page(url)

        settings = Settings(endpoint="http://127.0.0.1:8080/v1", model="offline",
                            project="STAR", knowledge_endpoint="off",
                            deep_research_enabled=True, router_models_dir=str(tmp_path),
                            router_context=2048, context_chars=6000)
        with pytest.raises(ValueError, match="context"):
            await run_research_team(
                prompt=QUESTION, home=tmp_path, settings=settings, research=True,
                web_provider=search, page_provider=fetch,
                client=SimpleNamespace(chat=SimpleNamespace(completions=model)))
        assert not searches and not pages and not model.calls

    asyncio.run(scenario())


def test_medium_context_team_keeps_page_frames_and_uses_smaller_output_allowances(tmp_path):
    from star.desktop_core import Settings, model_context_char_budget
    from star.team_service import run_research_team

    async def scenario():
        calls = []

        async def create(**kwargs):
            calls.append(kwargs)
            # Long independent findings exercise synthesis compression without
            # relying on a model to happen to generate a large response.
            content = "Version A allows ten channels, subject to documented limits. " * 100
            if "FOLLOWUP_QUERY" in kwargs["messages"][0]["content"]:
                content += "\nFOLLOWUP_QUERY: NONE"
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None))])

        async def search(query, *, limit):
            return [{"url": "https://references.example/context", "snippet": "Discovery"}]

        async def fetch(url):
            return _page(url)

        settings = Settings(endpoint="http://127.0.0.1:8080/v1", model="offline",
                            project="STAR", knowledge_endpoint="off",
                            deep_research_enabled=True, web_research_v2=False, router_models_dir=str(tmp_path),
                            router_context=4096, context_chars=12000)
        prompt = "Roblox animation APIs and their documented limitations. " * 60
        answer, result = await run_research_team(
            prompt=prompt, home=tmp_path, settings=settings, research=True,
            web_provider=search, page_provider=fetch,
            client=SimpleNamespace(chat=SimpleNamespace(
                completions=SimpleNamespace(create=create))),
            research_budget=ResearchBudget(max_queries=1, max_pages=1, total_seconds=5))
        assert result.completed and len(calls) == 4
        assert [call["max_tokens"] for call in calls] == [700, 700, 700, 1000]
        for call in calls:
            assert sum(len(item["content"]) for item in call["messages"]) <= model_context_char_budget(settings)
            supplied = call["messages"][1]["content"]
            assert supplied.count("<<<PAGE") == supplied.count("PAGE>>>") == 1
            assert "Roblox animation version A supports ten channels." in supplied
            assert "objective was shortened" in supplied
        assert "Claim support has not been automatically verified" in answer

    asyncio.run(scenario())


def test_deep_team_accepts_long_objective_with_bounded_local_knowledge_lookup(tmp_path):
    from star.desktop_core import Settings
    from star.team_service import run_research_team

    async def scenario():
        model = _Completions()
        searches = []
        objective = ("Roblox animation APIs and documented limitations. " * 200) + "TAIL_OBJECTIVE_MARKER"
        assert 4000 < len(objective) < 12000

        async def search(query, *, limit):
            searches.append(query)
            return [{"url": "https://references.example/long-objective", "snippet": "Discovery"}]

        async def fetch(url):
            return _page(url)

        settings = Settings(endpoint="http://127.0.0.1:8080/v1", model="offline",
                            project="STAR", knowledge_endpoint="off",
                            deep_research_enabled=True)
        answer, result = await run_research_team(
            prompt=objective, home=tmp_path, settings=settings, research=True,
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)),
            web_provider=search, page_provider=fetch,
            research_budget=ResearchBudget(max_queries=1, max_pages=1, total_seconds=5))
        assert result.completed and len(searches) == 1 and len(model.calls) == 4
        assert all("objective was shortened" in call["messages"][1]["content"] for call in model.calls)
        assert "https://references.example/long-objective" in answer

    asyncio.run(scenario())


# ---------------------------------------------------------------------------------------- v2 (star.web_research)

V2_TEXT = "Roblox animation API version 2.5 supports ten channels for each AnimationTrack."


class _V2Completions:
    """Synthesis cites [S1] with a version number the page has; the critic asks for no follow-up."""

    def __init__(self, synthesis="Roblox animation API version 2.5 supports ten channels [S1]."):
        self.calls, self.synthesis = [], synthesis

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        system = kwargs["messages"][0]["content"]
        content = (self.synthesis if "Combine specialist observations" in system else
                   "Evidence reviewed.\nFOLLOWUP_QUERY: NONE" if "FOLLOWUP_QUERY" in system else
                   "Use the supplied evidence.")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))])


def _v2_search(log):
    async def search(query, *, limit):
        log.append(query)
        return [{"url": "https://docs.example/roblox-animation-api", "title": "Roblox animation API limitations",
                 "snippet": "Animation channels and documented quality limitations."},
                {"url": "https://blog.example/animation", "title": "Roblox animation quality notes",
                 "snippet": "Comparing Roblox animation APIs."}]
    return search


def _v2_page(url):
    return Page(url=url, title="Roblox animation API", text=V2_TEXT, content_type="text/html", truncated=False)


def _v2_settings(**extra):
    from star.desktop_core import Settings
    return Settings(endpoint="http://127.0.0.1:8080/v1", model="offline", project="STAR",
                    knowledge_endpoint="off", **extra)


@pytest.mark.parametrize("deep", [False, True])
def test_v2_team_reads_pages_with_session_events_sources_claim_check_and_memory(tmp_path, deep):
    from star.research_activity import sanitize_research_event
    from star.research_store import ResearchStore
    from star.team_service import RESEARCH_STORE_FILE, run_research_team

    async def scenario():
        model, queries, opened, events = _V2Completions(), [], [], []

        async def fetch(url):
            opened.append(url)
            if url.endswith("/robots.txt"):
                raise RuntimeError("no robots file")
            return _v2_page(url)

        answer, result = await run_research_team(
            prompt=QUESTION, home=tmp_path, settings=_v2_settings(deep_research_enabled=deep), parallel=1,
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)), research=True,
            web_provider=_v2_search(queries), page_provider=fetch, on_event=events.append,
            research_budget=ResearchBudget(total_seconds=5))
        assert result.completed and len(model.calls) == 4
        pages = [url for url in opened if not url.endswith("/robots.txt")]
        assert sorted(pages) == ["https://blog.example/animation", "https://docs.example/roblox-animation-api"]
        assert 1 <= len(queries) <= 3                     # v2's parallel plan, not seven sequential angles
        supplied = "\n".join(call["messages"][1]["content"] for call in model.calls)
        assert V2_TEXT in supplied and "<<<PAGE" in supplied and "untrusted" in supplied
        # The same activity stream as ResearchSession: every research event passes the desktop's sanitizer.
        research = [e for e in events if str(e.get("event", "")).startswith(("research_", "query_", "source_"))]
        kinds = [e["event"] for e in research]
        assert kinds[0] == "research_started" and "research_finished" in kinds
        assert {"query_started", "query_completed", "source_started", "source_read"} <= set(kinds)
        for event in research:
            assert "activity" in sanitize_research_event(event), event
        # Source list, reference check and the v2 claim check (token match against the cited passage).
        assert "### Research sources" in answer and "<https://docs.example/roblox-animation-api>" in answer
        assert "page read" in answer and "Claim check: 1 of 1 cited sentences" in answer
        assert "[unverified]" not in answer.split("### Research sources")[0]
        with sqlite3.connect(tmp_path / "research-runs.sqlite3") as db:
            status, searches = db.execute("SELECT status,searches FROM research_runs").fetchone()
        assert status == "completed" and searches == len(queries)
        store = ResearchStore(tmp_path / RESEARCH_STORE_FILE)
        try:
            fact = store.lookup(QUESTION)
            assert fact is not None and "2.5" in fact.quote and fact.url.startswith("https://")
        finally:
            store.close()

    asyncio.run(scenario())


def test_v2_team_repeat_question_is_answered_from_research_memory(tmp_path):
    from star.research_store import ResearchStore
    from star.team_service import RESEARCH_STORE_FILE, run_research_team

    store = ResearchStore(tmp_path / RESEARCH_STORE_FILE)
    store.remember(QUESTION, "Version 2.5 supports ten channels.", V2_TEXT, "https://docs.example/roblox-animation-api",
                   "Roblox animation API")
    store.set_meta("watched_synced_at", "2999-01-01T00:00:00+00:00")     # no mirror request in this test
    store.close()

    async def scenario():
        model, queries, events = _V2Completions(), [], []

        async def fetch(url):
            raise AssertionError("a fresh stored fact needs no page read")

        answer, result = await run_research_team(
            prompt=QUESTION, home=tmp_path, settings=_v2_settings(), parallel=1,
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)), research=True,
            web_provider=_v2_search(queries), page_provider=fetch, on_event=events.append,
            research_budget=ResearchBudget(total_seconds=5))
        assert result.completed and not queries
        supplied = model.calls[-1]["messages"][1]["content"]
        assert "STORED" in supplied and "Fetched: " in supplied and V2_TEXT in supplied
        assert "<https://docs.example/roblox-animation-api>" in answer
        assert any(e.get("event") == "source_read" and e.get("cache_hit") for e in events)

    asyncio.run(scenario())


def test_v2_team_cancellation_during_page_read_records_cancelled_and_stops_workers(tmp_path):
    from star.team_service import run_research_team

    async def scenario():
        started = asyncio.Event()
        cancelled = False
        model = _V2Completions()

        async def fetch(url):
            nonlocal cancelled
            if url.endswith("/robots.txt"):
                raise RuntimeError("no robots file")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

        task = asyncio.create_task(run_research_team(
            prompt=QUESTION, home=tmp_path, settings=_v2_settings(), research=True,
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)),
            web_provider=_v2_search([]), page_provider=fetch,
            research_budget=ResearchBudget(total_seconds=5)))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert cancelled and not model.calls
        with sqlite3.connect(tmp_path / "research-runs.sqlite3") as db:
            assert db.execute("SELECT status FROM research_runs").fetchone()[0] == "cancelled"

    asyncio.run(scenario())


def test_v2_session_deadline_keeps_read_pages_and_marks_slow_ones():
    from star.web_research_session import WebResearchSession

    async def scenario():
        async def fetch(url):
            if url.endswith("/robots.txt"):
                raise RuntimeError("no robots file")
            if "blog.example" in url:
                await asyncio.Event().wait()
            return _v2_page(url)

        session = WebResearchSession(QUESTION, searcher=_v2_search([]), fetcher=fetch,
                                     budget=ResearchBudget(total_seconds=1.5))
        await asyncio.wait_for(session.collect(), timeout=5)
        rows = {row["requested_url"]: row for row in session.source_manifest()}
        assert rows["https://docs.example/roblox-animation-api"]["status"] == "read"
        assert rows["https://blog.example/animation"]["status"] == "failed"
        assert rows["https://blog.example/animation"]["error_code"] == "timeout"
        assert V2_TEXT in session.context(max_chars=4000)
        assert session.summary()["status"] == "partial"
        assert session.validate_citations("Ten channels [S1]; unknown [S77].")["unknown_source_ids"] == ["S77"]

    asyncio.run(scenario())


def test_v2_followup_adds_new_sources_with_new_ids():
    from star.web_research_session import WebResearchSession

    async def scenario():
        async def search(query, *, limit):
            if "keyframe" in query.lower():
                return [{"url": "https://docs.example/keyframes", "title": "Roblox animation keyframe limits",
                         "snippet": "Keyframe sequence limits for Roblox animation."}]
            return await _v2_search([])(query, limit=limit)

        async def fetch(url):
            if url.endswith("/robots.txt"):
                raise RuntimeError("no robots file")
            return _v2_page(url)

        session = WebResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                     budget=ResearchBudget(max_queries=8, max_pages=12, total_seconds=5))
        await session.collect()
        before = {row["id"] for row in session.source_manifest()}
        assert await session.followup("Roblox animation keyframe limits")
        rows = session.source_manifest()
        new = [row for row in rows if row["id"] not in before]
        assert [row["requested_url"] for row in new] == ["https://docs.example/keyframes"]
        assert len({row["id"] for row in rows}) == len(rows)
        assert not await session.followup("Roblox animation another gap")      # at most one follow-up

    asyncio.run(scenario())


def test_v2_with_a_small_context_and_no_deep_setting_keeps_search_snippets(tmp_path):
    from star.team_service import run_research_team

    async def scenario():
        model, queries, opened = _Completions(), [], []

        async def fetch(url):
            opened.append(url)
            return _page(url)

        settings = _v2_settings(router_models_dir=str(tmp_path), router_context=2048, context_chars=6000)
        answer, result = await run_research_team(
            prompt=QUESTION, home=tmp_path, settings=settings, parallel=1,
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)), research=True,
            web_provider=_v2_search(queries), page_provider=fetch, research_budget=ResearchBudget(total_seconds=5))
        assert result.completed and queries and not opened
        assert "pages were not opened" in model.calls[0]["messages"][1]["content"]

    asyncio.run(scenario())
