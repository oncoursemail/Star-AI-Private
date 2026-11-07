"""Recorded HTTP only: deadlines, responsiveness and real blocking-worker ownership."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

from star import web_fetch

PUBLIC = "93.184.215.14"


@pytest.fixture
def workers(monkeypatch):
    # One slot makes exhausted capacity observable without starting many threads.
    dns = web_fetch._BlockingWorkers(1, "test-page-dns")
    text = web_fetch._BlockingWorkers(1, "test-page-text")
    monkeypatch.setattr(web_fetch, "_DNS_WORKERS", dns)
    monkeypatch.setattr(web_fetch, "_PARSE_WORKERS", text)
    yield dns, text
    dns._executor.shutdown(wait=True, cancel_futures=True)
    text._executor.shutdown(wait=True, cancel_futures=True)


def public_resolver(host, port):
    return [PUBLIC]


def recorded_page(seen):
    def handler(request):
        seen.append((str(request.url), request.headers.get("host"), request.extensions.get("sni_hostname")))
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              content=b"<title>Recorded</title><p>Known article.</p>")
    return httpx.MockTransport(handler)


async def worker_drained(pool):
    # A barrier after the blocked job ensures its done callback has returned the admission
    # slot. This avoids timing sleeps or assuming that a worker-set Event means it exited.
    await asyncio.wait_for(asyncio.wrap_future(pool._executor.submit(lambda: None)), timeout=2)


def test_stalled_dns_returns_on_budget_without_queuing_more_work(monkeypatch, workers):
    monkeypatch.setattr(web_fetch, "TOTAL_TIMEOUT", 0.15)
    release = threading.Event()
    attempts, seen = [], []

    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocked_resolver(host, port):
            attempts.append(host)
            loop.call_soon_threadsafe(entered.set)
            release.wait(3)
            return [PUBLIC]

        task = asyncio.create_task(web_fetch.fetch_page(
            "https://example.com/", resolver=blocked_resolver, transport=recorded_page(seen)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            with pytest.raises(web_fetch.FetchRefused, match="too long"):
                await asyncio.wait_for(task, timeout=1)
            assert not release.is_set() and seen == []
            # The timed-out caller has gone away, but its OS call still owns the only slot.
            for _ in range(5):
                with pytest.raises(web_fetch.FetchRefused, match="busy"):
                    await web_fetch.fetch_page("https://example.com/", resolver=blocked_resolver,
                                              transport=recorded_page(seen))
            assert attempts == ["example.com"] and seen == []
        finally:
            task.cancel()
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await worker_drained(workers[0])
        monkeypatch.setattr(web_fetch, "TOTAL_TIMEOUT", 2.0)
        page = await web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                         transport=recorded_page(seen))
        assert page.text == "Known article."
        assert len(seen) == 1

    asyncio.run(scenario())


def test_cancelling_dns_preserves_slot_and_default_executor_capacity(workers):
    release = threading.Event()
    seen = []

    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocked_resolver(host, port):
            loop.call_soon_threadsafe(entered.set)
            release.wait(3)
            return [PUBLIC]

        task = asyncio.create_task(web_fetch.fetch_page(
            "https://example.com/", resolver=blocked_resolver, transport=recorded_page(seen)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(web_fetch.FetchRefused, match="busy"):
                await web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                          transport=recorded_page(seen))
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "other app work"), timeout=1) == "other app work"
            assert seen == []
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await worker_drained(workers[0])
        assert (await web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                          transport=recorded_page(seen))).title == "Recorded"

    asyncio.run(scenario())


def test_parser_runs_off_loop_while_heartbeat_keeps_working(monkeypatch, workers):
    release = threading.Event()
    seen, parser_threads, heartbeats = [], [], []
    original = web_fetch.readable_text

    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()

        def controlled_parser(html):
            parser_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(entered.set)
            release.wait(3)
            return original(html)

        monkeypatch.setattr(web_fetch, "readable_text", controlled_parser)
        task = asyncio.create_task(web_fetch.fetch_page(
            "https://example.com/", resolver=public_resolver, transport=recorded_page(seen)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            for _ in range(4):
                await asyncio.sleep(0)
                heartbeats.append(len(heartbeats))
            assert not task.done()
            assert len(parser_threads) == 1 and parser_threads[0] != loop_thread
            release.set()
            page = await asyncio.wait_for(task, timeout=1)
            assert page == web_fetch.Page("https://example.com/", "Recorded", "Known article.", "text/html", False)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await worker_drained(workers[1])
        assert len(heartbeats) == 4
        assert seen == [(f"https://{PUBLIC}/", "example.com", "example.com")]

    asyncio.run(scenario())


def test_parsing_timeout_keeps_slot_until_real_completion(monkeypatch, workers):
    monkeypatch.setattr(web_fetch, "TOTAL_TIMEOUT", 0.15)
    release = threading.Event()
    calls, seen = [], []
    original = web_fetch.readable_text

    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocked_parser(html):
            calls.append(html)
            loop.call_soon_threadsafe(entered.set)
            release.wait(3)
            return original(html)

        monkeypatch.setattr(web_fetch, "readable_text", blocked_parser)
        task = asyncio.create_task(web_fetch.fetch_page(
            "https://example.com/", resolver=public_resolver, transport=recorded_page(seen)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            with pytest.raises(web_fetch.FetchRefused, match="too long"):
                await asyncio.wait_for(task, timeout=1)
            with pytest.raises(web_fetch.FetchRefused, match="busy"):
                await web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                          transport=recorded_page(seen))
            assert len(calls) == 1 and not release.is_set()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await worker_drained(workers[1])
        monkeypatch.setattr(web_fetch, "readable_text", original)
        monkeypatch.setattr(web_fetch, "TOTAL_TIMEOUT", 2.0)
        assert (await web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                          transport=recorded_page(seen))).text == "Known article."

    asyncio.run(scenario())


def test_dns_and_redirects_share_the_original_deadline(monkeypatch, workers):
    # Advance only the reader's monotonic clock. The event loop retains its real clock.
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(web_fetch, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(web_fetch, "TOTAL_TIMEOUT", 1.0)
    resolved, paths = [], []

    def resolver(host, port):
        resolved.append(host)
        clock.now += 0.6
        return [PUBLIC]

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(302, headers={"location": "https://second.example/final"})

    with pytest.raises(web_fetch.FetchRefused, match="too long"):
        asyncio.run(web_fetch.fetch_page("https://first.example/start", resolver=resolver,
                                         transport=httpx.MockTransport(handler)))
    assert resolved == ["first.example", "second.example"]
    assert paths == ["/start"]  # no second HTTP request after the shared budget expires


def test_worker_failure_returns_its_slot(workers):
    seen = []

    def unavailable(host, port):
        raise OSError("resolver unavailable")

    async def scenario():
        with pytest.raises(web_fetch.FetchRefused, match="Could not resolve"):
            await web_fetch.fetch_page("https://example.com/", resolver=unavailable,
                                      transport=recorded_page(seen))
        assert (await web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                          transport=recorded_page(seen))).text == "Known article."

    asyncio.run(scenario())
    assert len(seen) == 1


def test_cancelled_body_read_closes_the_response(workers):
    async def scenario():
        entered = asyncio.Event()
        closed = []

        class ControlledStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield b"unreachable"

            async def aclose(self):
                closed.append(True)

        def handler(request):
            return httpx.Response(200, headers={"content-type": "text/plain"}, stream=ControlledStream())

        task = asyncio.create_task(web_fetch.fetch_page(
            "https://example.com/", resolver=public_resolver, transport=httpx.MockTransport(handler)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("addresses", [["127.0.0.1"], [PUBLIC, "169.254.169.254"]])
def test_bounded_dns_preserves_all_address_checks(workers, addresses):
    seen = []
    with pytest.raises(web_fetch.FetchRefused, match="private or reserved"):
        asyncio.run(web_fetch.fetch_page("https://example.com/", resolver=lambda host, port: addresses,
                                         transport=recorded_page(seen)))
    assert seen == []


def test_oversized_body_is_refused_before_parser_admission(monkeypatch, workers):
    def forbidden(*args):
        pytest.fail("An oversized page must not reach the parser")

    monkeypatch.setattr(web_fetch, "_reduce_page", forbidden)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=b"x" * (web_fetch.MAX_BYTES + 1))

    with pytest.raises(web_fetch.FetchRefused, match="2 MB"):
        asyncio.run(web_fetch.fetch_page("https://example.com/", resolver=public_resolver,
                                         transport=httpx.MockTransport(handler)))
