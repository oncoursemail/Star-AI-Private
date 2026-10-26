"""Independent behavioral checks for bounded, provenance-preserving research.

Only controlled providers run here. Their call records are the independent
oracle for budgets and deduplication; a session's own counters are not proof
that it performed the right amount of work.
"""
import asyncio
from hashlib import sha256
import json
import re

import pytest

from star.research_session import ResearchBudget, ResearchSession
from star.web_fetch import FetchRefused, Page


QUESTION = "Compare Roblox animation APIs and documented quality limitations"


def _page(url, text="Roblox animation APIs require documented quality checks.", *, final_url=None):
    return Page(url=final_url or url, title="Animation reference", text=text,
                content_type="text/html", truncated=False)


def test_query_and_page_budgets_apply_to_collection_and_followup_together():
    async def scenario():
        queries, opened = [], []

        async def search(query, *, limit):
            queries.append(query)
            batch = len(queries)
            return [{"url": f"https://references.example/batch-{batch}/{i}",
                     "title": f"Reference {batch}-{i}", "snippet": "Roblox animation documentation"}
                    for i in range(limit)]

        async def fetch(url):
            opened.append(url)
            return _page(url)

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_queries=4, max_pages=6,
                                                        max_sources=16, concurrency=2,
                                                        total_seconds=5))
        assert await session.collect() is session
        assert len(queries) == 3
        assert len(opened) == 4  # Two real page slots remain for the critic's question.
        assert await session.followup("Roblox animation limitations measured evaluation")
        assert len(queries) == 4
        assert len(opened) == 6
        assert len(set(opened)) == len(opened)
        assert not await session.followup("Roblox animation independent benchmark details")
        assert len(queries) == 4 and len(opened) == 6
        summary = session.summary()
        assert summary["queries"] == len(queries)
        assert summary["pages"] == len(opened)
        assert summary["sources_read"] == len(opened)

    asyncio.run(scenario())


def test_source_limit_and_no_page_budget_do_not_claim_pages_were_read():
    async def scenario():
        calls = []

        async def search(query, *, limit):
            calls.append(query)
            return [{"url": f"https://references.example/{len(calls)}/{i}",
                     "title": "Discovered result", "snippet": "Only a search snippet"}
                    for i in range(limit)]

        async def forbidden_fetch(url):
            raise AssertionError("A zero-page budget must not open any page")

        session = ResearchSession(QUESTION, searcher=search, fetcher=forbidden_fetch,
                                  budget=ResearchBudget(max_sources=5, max_pages=0,
                                                        total_seconds=5))
        await session.collect()
        manifest = session.source_manifest()
        assert len(manifest) == 5
        assert all(row["status"] == "discovered" for row in manifest)
        assert session.summary()["pages"] == 0
        assert session.summary()["sources_read"] == 0
        check = session.validate_citations("This claim refers to a snippet [S1].")
        assert "S1" in check["unread_source_ids"]
        assert check["semantic_support"] == "unchecked"

    asyncio.run(scenario())


def test_searches_overlap_within_limit_and_ids_survive_out_of_order_completion():
    async def scenario():
        released = [asyncio.Event() for _ in range(3)]
        two_started, three_started = asyncio.Event(), asyncio.Event()
        calls, finished = [], []
        active = peak = 0

        async def search(query, *, limit):
            nonlocal active, peak
            number = len(calls)
            calls.append(query)
            active += 1
            peak = max(peak, active)
            if len(calls) == 2:
                two_started.set()
            if len(calls) == 3:
                three_started.set()
            try:
                await released[number].wait()
                finished.append(number)
                return [{"url": f"https://references.example/{number}",
                         "title": f"Question {number}", "snippet": "Retrieved snippet"}]
            finally:
                active -= 1

        session = ResearchSession(QUESTION, searcher=search,
                                  budget=ResearchBudget(concurrency=2, max_pages=0,
                                                        total_seconds=5))
        task = asyncio.create_task(session.collect())
        try:
            await asyncio.wait_for(two_started.wait(), timeout=1)
            assert active == 2 and len(calls) == 2
            released[1].set()
            await asyncio.wait_for(three_started.wait(), timeout=1)
            released[2].set()
            # Let the third worker finish while the first remains blocked.
            await asyncio.sleep(0)
            released[0].set()
            await asyncio.wait_for(task, timeout=1)
        finally:
            for gate in released:
                gate.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert peak == 2 and active == 0
        assert finished.index(1) < finished.index(0)
        manifest = session.source_manifest()
        assert [(row["id"], row["title"]) for row in manifest] == [
            ("S1", "Question 0"), ("S2", "Question 1"), ("S3", "Question 2")]

    asyncio.run(scenario())


def test_fragments_and_trackers_deduplicate_but_version_parameters_remain_distinct():
    async def scenario():
        opened = []

        async def search(query, *, limit):
            return [{"url": url, "title": "Reference", "snippet": "Roblox animation APIs"}
                    for url in (
                        "https://references.example/guide?utm_source=one#start",
                        "https://references.example/guide?utm_source=two#end",
                        "https://references.example/guide?version=1",
                        "https://references.example/guide?version=2",
                    )]

        async def fetch(url):
            opened.append(url)
            return _page(url)

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(total_seconds=5))
        await session.collect()
        assert len(session.source_manifest()) == 3
        assert len(opened) == 3 and len(set(opened)) == 3
        assert any("version=1" in url for url in opened)
        assert any("version=2" in url for url in opened)

    asyncio.run(scenario())


def test_only_one_related_nonduplicate_followup_can_spend_remaining_budget():
    async def scenario():
        calls = []

        async def search(query, *, limit):
            calls.append(query)
            return [{"url": f"https://references.example/{len(calls)}",
                     "snippet": "Roblox animation documentation"}]

        session = ResearchSession(QUESTION, searcher=search,
                                  budget=ResearchBudget(max_pages=0, total_seconds=5))
        await session.collect()
        for candidate in (QUESTION, "https://references.example/secret", "NONE",
                          "Completely unrelated climate policy question"):
            assert not await session.followup(candidate)
        assert len(calls) == 3
        assert await session.followup("Roblox animation APIs version-specific limitations")
        assert not await session.followup("Roblox animation APIs independently measured behavior")
        assert len(calls) == 4

    asyncio.run(scenario())


def test_manifest_distinguishes_read_failed_and_discovered_evidence():
    async def scenario():
        body = "Roblox animation documentation: version A supports ten channels."
        original = "https://references.example/first"
        redirected = "https://references.example/current"

        async def search(query, *, limit):
            return [{"url": f"https://references.example/{name}", "title": name,
                     "snippet": f"Search-only {name}", "published": "2025-01-02"}
                    for name in ("first", "second", "third")]

        async def fetch(url):
            if url == original:
                return _page(url, body, final_url=redirected)
            raise FetchRefused("provider-token-should-not-appear")

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_pages=2, total_seconds=5))
        await session.collect()
        manifest = session.source_manifest()
        assert [row["status"] for row in manifest] == ["read", "failed", "discovered"]
        read, failed, unopened = manifest
        assert read["requested_url"] == original and read["final_url"] == redirected
        assert read["text_sha256"] == sha256(body.encode()).hexdigest()
        assert read["retrieved_at"]
        assert read["published_metadata"]
        assert failed["error_code"]
        assert not unopened.get("text_sha256")
        assert all("text" not in extract for row in manifest for extract in row.get("extracts", []))
        assert body not in json.dumps(manifest)
        context = session.context(max_chars=3000)
        assert body in context and "untrusted" in context.lower()
        assert len(context) <= 3000
        assert "provider-token-should-not-appear" not in json.dumps(manifest)

    asyncio.run(scenario())


def test_citation_integrity_does_not_claim_semantic_fact_verification():
    async def scenario():
        async def search(query, *, limit):
            return [{"url": "https://references.example/guide", "snippet": "Ten channels"},
                    {"url": "https://references.example/unopened", "snippet": "Unopened result"}]

        async def fetch(url):
            return _page(url, "Roblox animation version A supports ten channels.")

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_pages=1, total_seconds=5))
        await session.collect()
        # A valid ID on an incorrect statement must never receive a fact-verified label.
        known = session.validate_citations("Version A supports a million channels [S1].")
        assert known["integrity_ok"] is True
        assert known["semantic_support"] == "unchecked"
        broken = session.validate_citations(
            "Unopened evidence [S2]. Invented reference [S999]. "
            "https://invented.example/not-retrieved")
        assert broken["integrity_ok"] is False
        assert "S999" in broken["unknown_source_ids"]
        assert "S2" in broken["unread_source_ids"]
        assert "https://invented.example/not-retrieved" in broken["unknown_urls"]
        assert broken["semantic_support"] == "unchecked"

    asyncio.run(scenario())


def test_clipped_context_preserves_exact_displayed_offsets_and_complete_frames():
    async def scenario():
        body = "Roblox animation " + " ".join(f"token{number:04d}" for number in range(400))

        async def search(query, *, limit):
            return [{"url": "https://references.example/long", "snippet": "Long reference"}]

        async def fetch(url):
            return _page(url, body)

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_pages=1, total_seconds=5))
        await session.collect()
        for maximum in (0, 300, 1000, 1700):
            context = session.context(max_chars=maximum)
            assert len(context) <= maximum
            assert context.count("<<<PAGE") == context.count("PAGE>>>")
            spans = re.findall(r"\[readable-text chars (\d+):(\d+)\]\n([^\n]*)", context)
            if maximum >= 1000:
                assert spans
            for start, end, shown in spans:
                assert shown == body[int(start):int(end)]
        for extract in session.source_manifest()[0]["extracts"]:
            assert 0 <= extract["start"] < extract["end"] <= len(body)

    asyncio.run(scenario())


def test_followup_reuses_a_known_redirect_destination_without_relabeling_retrieval_time():
    async def scenario():
        calls, opened = [], []
        original = "https://references.example/old-guide"
        final = "https://references.example/current-guide"

        async def search(query, *, limit):
            calls.append(query)
            return [{"url": original if len(calls) <= 3 else final,
                     "snippet": "Roblox animation reference"}]

        async def fetch(url):
            opened.append(url)
            return _page(url, final_url=final)

        session = ResearchSession(QUESTION, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_pages=2, total_seconds=5))
        await session.collect()
        before = session.source_manifest()[0]
        assert await session.followup("Roblox animation reference after documented redirect")
        manifest = session.source_manifest()
        assert opened == [original] and len(calls) == 4
        assert len(manifest) == 1 and manifest[0]["id"] == before["id"]
        assert manifest[0]["retrieved_at"] == before["retrieved_at"]
        assert manifest[0]["text_sha256"] == before["text_sha256"]

    asyncio.run(scenario())


def test_failed_queries_return_an_honest_result_without_provider_secrets():
    async def scenario():
        events, calls = [], []

        async def broken(query, *, limit):
            calls.append(query)
            raise RuntimeError("Bearer definitely-private-test-value")

        session = ResearchSession(QUESTION, searcher=broken, on_event=events.append,
                                  budget=ResearchBudget(max_pages=0, total_seconds=5))
        await session.collect()
        summary = session.summary()
        assert len(calls) == 3
        assert summary["failed_queries"] == 3
        assert summary["status"] == "failed"
        assert summary["sources_found"] == summary["sources_read"] == 0
        exposed = json.dumps([summary, session.source_manifest(), events, session.context()])
        assert "definitely-private-test-value" not in exposed
        assert "Bearer" not in exposed

    asyncio.run(scenario())


def test_expanded_plan_obeys_shared_limits_and_reserves_one_followup():
    async def scenario():
        questions = tuple(f"Roblox animation documented {angle}" for angle in (
            "API behavior", "runtime constraints", "version support", "benchmark methods",
            "known failures", "implementation examples", "conflicting evidence"))
        release, three_started = asyncio.Event(), asyncio.Event()
        queries, opened = [], []
        active = peak = 0

        async def search(query, *, limit):
            nonlocal active, peak
            queries.append(query)
            number = len(queries)
            active += 1
            peak = max(peak, active)
            if active == 3:
                three_started.set()
            try:
                await release.wait()
                return [{"url": f"https://references.example/{number}/{i}",
                         "snippet": "Roblox animation reference"} for i in range(limit)]
            finally:
                active -= 1

        async def fetch(url):
            nonlocal active, peak
            opened.append(url)
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0)
                return _page(url)
            finally:
                active -= 1

        session = ResearchSession(QUESTION, queries=questions, searcher=search, fetcher=fetch,
                                  budget=ResearchBudget(max_queries=8, max_pages=12,
                                                        max_sources=32, concurrency=3,
                                                        total_seconds=5))
        task = asyncio.create_task(session.collect())
        try:
            await asyncio.wait_for(three_started.wait(), timeout=1)
            assert len(queries) == 3 and active == 3
            release.set()
            await asyncio.wait_for(task, timeout=1)
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert len(queries) == 7 and len(opened) == 10
        assert await session.followup("Roblox animation independently measured limitations")
        assert len(queries) == 8 and len(opened) == 12
        assert len(session.source_manifest()) == 32
        assert peak == 3 and active == 0
        assert not await session.followup("Roblox animation further implementation verification")
        assert len(queries) == 8 and len(opened) == 12

    asyncio.run(scenario())


def test_query_plan_normalization_and_lower_budget_preserve_followup_capacity():
    async def scenario():
        queries = []
        first = "Roblox animation API behavior"
        second = "Roblox animation version limitations"

        async def search(query, *, limit):
            queries.append(query)
            return [{"url": f"https://references.example/{len(queries)}", "snippet": "Retrieved"}]

        session = ResearchSession(
            QUESTION, searcher=search,
            queries=(first, "  Roblox   animation API behavior  ", second,
                     "Roblox animation additional implementation comparison"),
            budget=ResearchBudget(max_queries=3, max_pages=0, total_seconds=5))
        await session.collect()
        assert queries == [first, second]
        assert await session.followup("Roblox animation independent evaluation methodology")
        assert len(queries) == 3

    asyncio.run(scenario())


def test_untrusted_or_malformed_query_plans_are_rejected_before_any_provider_call():
    calls = []

    async def search(query, *, limit):
        calls.append(query)
        return []

    invalid_plans = (
        (),
        "Roblox animation query",  # A string must not silently become character queries.
        (7,),
        ("Roblox animation " + "x" * 600,),
        ("Roblox animation https://unapproved.example/",),
        ("Roblox animation\nadditional command",),
        ("An unrelated climate treaty accounting question",),
    )
    for candidate in invalid_plans:
        with pytest.raises((TypeError, ValueError)):
            ResearchSession(QUESTION, queries=candidate, searcher=search)
    assert calls == []
