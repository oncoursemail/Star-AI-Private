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
def test_team_opens_pages_only_when_both_research_and_deep_setting_are_enabled(
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
                            deep_research_enabled=enabled)
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
                            deep_research_enabled=True)
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
                            deep_research_enabled=True, router_models_dir=str(tmp_path),
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
