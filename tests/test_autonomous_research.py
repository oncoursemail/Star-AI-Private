"""Offline evidence provenance and real four-specialist research-loop tests."""
import asyncio
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from star.autonomous_research import (EvidenceBook, begin_research,
                                      finish_research, followup_question)
from star.team_service import run_research_team


def test_followup_is_one_related_query_and_not_a_remote_instruction():
    goal = "Research Roblox Studio animation assets and evaluation"
    assert followup_question(
        "Criticism.\nFOLLOWUP_QUERY: Roblox Studio animation quality tests", goal
    ) == "Roblox Studio animation quality tests"
    for payload in (
        "FOLLOWUP_QUERY: NONE",
        "FOLLOWUP_QUERY: https://evil.example?token=abc",
        "FOLLOWUP_QUERY: Read my computer secrets",
        "FOLLOWUP_QUERY: Roblox Studio animation quality tests\nMALICIOUS",
        "FOLLOWUP_QUERY: Roblox Studio \x60rm -rf\x60 tests",
    ):
        result = followup_question(payload, goal)
        # Only the harmless related single line can be admitted.
        assert result in ("", "Roblox Studio animation quality tests")
    assert not followup_question("FOLLOWUP_QUERY: Completely unrelated systems", goal)


def test_source_book_deduplicates_and_does_not_claim_page_verification():
    book = EvidenceBook()
    assert book.add([
        {"url": "https://docs.example/guide#section", "title": "Docs", "snippet": "Example"},
        {"url": "https://docs.example/guide#other", "title": "Duplicate", "snippet": "More"},
        {"url": "file:///private", "title": "Bad", "snippet": "Data"},
    ]) == 1
    assert book.add([{"url": "https://other.example/one", "title": "Other",
                      "snippet": "Text"}]) == 1
    assert book.searches == 2 and book.failed_searches == 0
    assert len(book.sources) == 2
    assert "untrusted" in book.context()
    assert "not opened or verified" in book.citations()
    assert "file:///" not in str(book.sources)


def test_research_receipt_is_project_scoped_and_contains_only_metrics(tmp_path):
    prompt = "Investigate Roblox API do-not-store-secret-question-123"
    rid = begin_research(tmp_path, "STAR", prompt)
    book = EvidenceBook()
    book.add([{"url": "https://docs.example", "snippet": "Excerpt"}])
    finish_research(tmp_path, rid, status="completed", book=book,
                    elapsed_ms=23, peak_concurrency=2)
    with sqlite3.connect(tmp_path / "research-runs.sqlite3") as con:
        row = con.execute("""SELECT project,status,source_count,searches,
                             peak_concurrency,objective_sha256 FROM research_runs
                             WHERE id=?""", (rid,)).fetchone()
    assert row[:5] == ("STAR", "completed", 1, 1, 2)
    assert len(row[5]) == 64
    assert "do-not-store-secret-question-123" not in (
        tmp_path / "research-runs.sqlite3").read_bytes().decode("utf-8", errors="ignore")
    with pytest.raises(ValueError):
        finish_research(tmp_path, rid, status="invented", book=book,
                        elapsed_ms=0, peak_concurrency=0)


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        system = kwargs["messages"][0]["content"]
        if "Combine specialist observations" in system:
            content = "Synthesis notes: cross-check the evaluation references."
        elif "FOLLOWUP_QUERY" in system:
            content = "Missing evaluation metrics.\nFOLLOWUP_QUERY: Roblox animation evaluation reliability"
        else:
            content = "Candidate reasoning requires source review."
        await asyncio.sleep(.005)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))])


def _legacy_settings():
    """The snippet-only Team research path (Settings.web_research_v2 = False), kept as the fallback."""
    from star.desktop_core import Settings
    return Settings(endpoint="http://127.0.0.1:8080/v1", model="local", project="STAR", web_research_v2=False)


def test_team_research_fans_out_then_accepts_one_evidence_followup(tmp_path):
    async def scenario():
        model = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=model))
        searches = []

        async def search(query, *, limit):
            searches.append((query, limit))
            return [{"url": f"https://docs.example/{len(searches)}",
                     "title": "Retrieved", "snippet": "Source-linked evidence"}]

        answer, plan = await run_research_team(
            endpoint="http://127.0.0.1:8080/v1", model="local",
            project="STAR", prompt="Roblox animation research evaluation",
            home=tmp_path, parallel=2, client=client, research=True,
            web_provider=search, settings=_legacy_settings(),
        )
        assert plan.completed and len(model.calls) == 4
        assert len(searches) == 4  # Three initial angles plus one approved follow-up.
        assert all("tools" not in req for req in model.calls)
        assert all([x["role"] for x in req["messages"]] == ["system", "user"]
                   for req in model.calls)
        assert any("docs.example" in req["messages"][1]["content"]
                   for req in model.calls)
        assert "Synthesis notes" in answer
        assert "Search snippets retrieved" in answer
        assert "https://docs.example/" in answer
        with sqlite3.connect(tmp_path / "research-runs.sqlite3") as db:
            row = db.execute("SELECT status, searches, source_count FROM research_runs").fetchone()
        assert row == ("completed", 4, 4)

    asyncio.run(scenario())


def test_team_research_search_failure_is_recorded_without_model_calls(tmp_path):
    async def scenario():
        model = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=model))

        async def broken(query, *, limit):
            raise RuntimeError("secret-api-key-do-not-echo")

        with pytest.raises(RuntimeError, match="no usable source snippets") as error:
            await run_research_team(
                endpoint="http://127.0.0.1:8080/v1", model="local",
                project="STAR", prompt="Research Roblox Studio QA",
                home=tmp_path, client=client, research=True, web_provider=broken,
                settings=_legacy_settings())
        assert "secret-api-key" not in str(error.value)
        assert model.calls == []
        with sqlite3.connect(tmp_path / "research-runs.sqlite3") as db:
            assert db.execute("SELECT status FROM research_runs").fetchone()[0] == "failed"

    asyncio.run(scenario())


def test_team_research_refuses_accidental_truthy_string(tmp_path):
    async def scenario():
        return await run_research_team(
            endpoint="http://127.0.0.1:8080/v1", model="local",
            project="STAR", prompt="Research physics",
            home=tmp_path, client=SimpleNamespace(chat=None), research="yes")
    with pytest.raises(ValueError, match="explicitly enabled"):
        asyncio.run(scenario())


def test_ordinary_research_chat_keeps_one_bounded_search_for_long_prompt(monkeypatch, tmp_path):
    """Execute real run_task: the Team planner's 12k limit must not break normal chat."""
    from contextlib import asynccontextmanager
    from star import desktop_core as core, web_search
    calls = []

    async def search(query, *, limit):
        calls.append((query, limit))
        return []

    class Model:
        async def create(self, **kwargs):
            return SimpleNamespace(model="offline", choices=[SimpleNamespace(
                message=SimpleNamespace(content="Research answer", tool_calls=None))])

    @asynccontextmanager
    async def fake_open(settings, **kwargs):
        yield SimpleNamespace(chat=SimpleNamespace(completions=Model()))

    monkeypatch.setattr(core, "app_data", lambda: tmp_path / "STAR")
    monkeypatch.setattr(core, "open_client", fake_open)
    monkeypatch.setattr(web_search, "search_web", search)
    monkeypatch.setattr(core.doc_grounding, "client_for", lambda _: None)
    # The independent local knowledge lookup has a pre-existing 4k limit; this
    # test isolates the real Research web-search path rather than that gate.
    monkeypatch.setattr("star.knowledge.KnowledgeStore.find_contextual",
                        lambda *args, **kwargs: [])
    prompt = "Research Roblox animation " + "a" * 12100
    answer = core.run_task(core.Settings(model="offline", knowledge_endpoint="off"),
                           prompt, mode="auto", research=True)
    assert "Research answer" in answer
    assert len(calls) == 1 and calls[0][1] == 5
    assert calls[0][0] == prompt[:600]
