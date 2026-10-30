"""Team / deep Research collected by star.web_research (v2) behind ResearchSession's interface.

team_service, research_activity and the desktop's activity view read a ResearchSession: its progress events, the
source manifest, the evidence context and the citation checks. WebResearchSession keeps all of that (it is a
subclass) and replaces only how the evidence is collected: v2's parallel query plan, ranked page reading (robots.txt,
one page per host at a time, pages up to 200k characters) and passage rerank. Measured on evals/web_research
(62 held-out questions): v2 61 correct / 60 source-backed vs 53 / 51 for ResearchSession's own collection.
Settings.web_research_v2 = False goes back to ResearchSession unchanged.

`result` holds the v2 ResearchResult (sources numbered as the session's S# ids) for web_research.verify_answer and
web_research.learn after the answer. Page text stays untrusted data: build_context frames and defangs it.
"""
from __future__ import annotations

import asyncio
from hashlib import sha256
import inspect
from time import gmtime, monotonic

from . import web_research as wr
from .research_session import ResearchBudget, ResearchSession, _canonical, _clean, _now, _Source
from .web_search import _safe_results

_STATUS = {"found": "discovered", "read": "read", "stored": "read", "failed": "failed", "skipped": "failed"}


def _error_code(src: wr.Source) -> str:
    if src.status == "skipped":
        return "refused"                      # robots.txt said no: respected, never worked around
    if src.status != "failed":
        return ""
    return {"deadline": "timeout", "cancelled": "cancelled"}.get(src.error, "fetch_failed")


def _takes_max_chars(fetcher) -> bool:
    try:
        params = inspect.signature(fetcher).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "max_chars" or p.kind is p.VAR_KEYWORD for p in params)


class WebResearchSession(ResearchSession):
    """One v2 collection and at most one related follow-up, with ResearchSession's events, budget and deadline."""

    def __init__(self, question: str, *, searcher=None, fetcher=None, on_event=None,
                 budget: ResearchBudget | None = None, queries: tuple[str, ...] | None = None, store=None) -> None:
        # `queries` is accepted for ResearchSession's call shape; v2 plans its own searches (wr.plan_queries).
        super().__init__(question, searcher=searcher, fetcher=fetcher, on_event=on_event, budget=budget)
        self._store = store
        self.result: wr.ResearchResult | None = None
        self._rows: dict[int, _Source] = {}        # id(v2 Source) -> manifest row
        self._skip: set[int] = set()               # v2 Sources that repeat an earlier round's source (or over S99)
        self._started_rows: set[int] = set()
        self._waiting: list[wr.Source] = []         # direct-page reads that began before the ids existed
        raw = self._fetcher
        if _takes_max_chars(raw):
            self._read_page = raw
        else:                                       # a trusted test/app adapter taking only the URL
            async def read_page(url: str, *, max_chars: int = wr.PAGE_CHARS):
                return await raw(url)
            self._read_page = read_page

    # ------------------------------------------------------------------------------------------ rows and events
    async def _search_safe(self, query: str, *, limit: int) -> list[dict]:
        raw = await self._searcher(query, limit=limit)
        if not isinstance(raw, list):
            raise ValueError("Invalid search result")
        safe = []
        for item in raw[:32]:                       # one malformed record never hides the good ones
            try:
                for row in _safe_results([item], text_field="snippet", limit=1):
                    _canonical(row["url"])
                    safe.append(row)
            except (ValueError, TypeError, UnicodeError):
                continue
            if len(safe) == limit:
                break
        return safe

    def _add_row(self, src: wr.Source, number: int) -> _Source | None:
        try:
            key = _canonical(src.url)
        except ValueError:
            key = None
        existing = self._by_url.get(key) if key else None
        if key is None or existing is not None or not 1 <= number <= 99:
            self._skip.add(id(src))
            src.id = existing.id if existing is not None else ""
            return None
        src.id = f"S{number}"
        row = _Source(src.id, src.url, " ".join(_clean(src.title, 160).split()), _clean(src.snippet, 1050),
                      "" if src.status == "stored" else _clean(src.published, 40))
        self._rows[id(src)] = row
        self._by_url[key] = row
        self._sources.append(row)
        return row

    def _adopt(self, sources: list[wr.Source], offset: int) -> None:
        """Rows for a round's ranked sources, numbered after the earlier rounds' ids."""
        for src in sources:
            if id(src) not in self._rows and id(src) not in self._skip:
                self._add_row(src, offset + int(src.id[1:]) if src.id[1:].isdigit() else 0)

    def _sync_row(self, src: wr.Source) -> _Source | None:
        row = self._rows.get(id(src))
        if row is None:
            return None
        row.status = _STATUS.get(src.status, "discovered")
        row.error_code = _error_code(src)
        if row.status == "read" and not row.retrieved_at:
            text = src.text or "\n".join(p.text for p in src.chosen)
            row.final_url = src.url
            row.title = " ".join(_clean(src.title, 160).split()) or row.title
            row.text = text
            row.text_sha256 = sha256(text.encode("utf-8")).hexdigest()
            dated = src.published.split(" ", 1)
            row.retrieved_at = (dated[1] if src.published.startswith(("fetched ", "snapshot ")) and len(dated) == 2
                                else _now())
            row.truncated = len(src.text) >= wr.PAGE_CHARS
        return row

    def _start(self, src: wr.Source) -> None:
        row = self._rows.get(id(src))
        if row is not None and id(src) not in self._started_rows:
            self._started_rows.add(id(src))
            self._source_event("source_started", row)

    def _finish(self, src: wr.Source) -> None:
        row = self._sync_row(src)
        if row is None:
            return
        self._start(src)
        if row.status == "read":
            self._source_event("source_read", row, cache_hit=src.status == "stored")
        else:
            self._source_event("source_failed", row, error_code=row.error_code or "fetch_failed")

    def _progress(self, records: list[dict], offset: int):
        def on(event: str, fields: dict) -> None:
            if event == "query_started":
                record = records[fields["index"]]
                record["started"] = True
                self._searches += 1
                self._active += 1
                self._peak = max(self._peak, self._active)
                self._emit("query_started", phase="search", query_id=record["id"], ordinal=record["ordinal"])
            elif event == "query_finished":
                record = records[fields["index"]]
                self._active = max(0, self._active - 1)
                if fields.get("found"):
                    self._emit("query_completed", phase="search", query_id=record["id"],
                               ordinal=record["ordinal"], found=fields["found"])
                else:
                    self._failed_searches += 1
                    self._emit("query_failed", phase="search", query_id=record["id"], error_code="search_failed")
            elif event == "ranked":
                self._adopt(fields["sources"], offset)
                waiting, self._waiting = self._waiting, []
                for src in waiting:
                    (self._start if src.status == "found" else self._finish)(src)
            elif event == "source_started":
                src = fields["source"]
                self._pages += 1
                self._active += 1
                self._peak = max(self._peak, self._active)
                if id(src) in self._rows:
                    self._start(src)
                elif id(src) not in self._skip:
                    self._waiting.append(src)
            elif event == "source_finished":
                src = fields["source"]
                self._active = max(0, self._active - 1)
                if id(src) in self._rows:
                    self._finish(src)
                elif id(src) not in self._skip and src not in self._waiting:
                    self._waiting.append(src)
        return on

    # ------------------------------------------------------------------------------------------ collection
    async def _round(self, queries: tuple[str, ...], page_limit: int, *, followup: bool) -> None:
        self._busy, self.status, self.stop_reason = True, "running", ""
        question = queries[0] if followup else self.question
        year = gmtime().tm_year
        allowed = self.budget.max_queries - len(self._queries) if followup else max(1, self.budget.max_queries - 1)
        records = []
        for query in wr.plan_queries(question, year=year)[:max(0, min(3, allowed))]:
            self._seen_queries.add(" ".join(query.split()).casefold())
            record = {"id": f"Q{len(self._queries) + 1}", "ordinal": len(self._queries) + 1, "query": query,
                      "results": []}
            records.append(record)
            self._queries.append(record)
        offset = max((int(row.id[1:]) for row in self._sources), default=0)
        on = self._progress(records, offset)
        self._emit("research_followup_started" if followup else "research_started",
                   phase="followup" if followup else "search", planned_queries=len(records))
        try:
            remaining = max(0.0, self._deadline - monotonic())
            got = None
            if records:
                async with asyncio.timeout(remaining):
                    got = await wr.research(
                        question, searcher=self._search_safe, fetcher=self._read_page,
                        max_pages=max(0, min(wr.MAX_PAGES, page_limit)), year=year,
                        deadline_s=max(0.5, remaining - 0.5), store=None if followup else self._store,
                        max_queries=len(records), on_progress=on)
            if got is not None and got.stats.get("store_hit"):
                on("ranked", {"sources": got.sources})          # answered from STAR's verified notes
                for src in got.sources:
                    on("source_started", {"source": src})
                    on("source_finished", {"source": src})
            if got is not None:
                self._merge(got, offset)
            self.status = ("failed" if not self._sources else
                           "partial" if self._failed_searches or any(row.status == "failed" for row in self._sources)
                           else "completed")
            self.stop_reason = "no_sources" if not self._sources else "collection_complete"
        except TimeoutError:
            self.status, self.stop_reason = "timed_out", "deadline_reached"
        except asyncio.CancelledError:
            self.status, self.stop_reason = "cancelled", "cancelled"
            raise
        except Exception:
            self.status, self.stop_reason = "failed", "collector_error"
            raise
        finally:
            self._busy = False
            self._emit("research_finished", phase="finished")

    def _merge(self, got: wr.ResearchResult, offset: int) -> None:
        """Keep the round's sources and passages. Watched-page snapshots (no row yet) stay in the pool and get a
        manifest row only when the evidence actually shows them (context())."""
        self._adopt([s for s in got.sources if not s.published.startswith("snapshot ")], offset)
        taken = {row.id for row in self._sources}
        kept = []
        for src in got.sources:
            if id(src) in self._rows:
                self._sync_row(src)
                kept.append(src)
            elif id(src) not in self._skip and src.published.startswith("snapshot ") and src.id not in taken:
                kept.append(src)
        ids = {src.id for src in kept}
        pool = [p for p in got.pool if p.source in ids]
        if self.result is None:
            self.result = wr.ResearchResult(self.question, kept, got.context, dict(got.stats), pool)
            return
        known = {src.id for src in self.result.sources}
        self.result.sources.extend(src for src in kept if src.id not in known)
        self.result.pool = wr.rank_passages(self.question, self.result.pool + [p for p in pool
                                                                               if p.source not in known])
        self.result.stats.pop("store_hit", None)
        self.result.stats["followup"] = dict(got.stats)

    # ------------------------------------------------------------------------------------------ reading
    def context(self, max_chars: int = 7500) -> str:
        """v2's ranked passages grouped by source as untrusted [S#] frames, re-selected for this character cap."""
        if type(max_chars) is not int or not 0 <= max_chars <= 50000:
            raise ValueError("max_chars must be an integer between 0 and 50000")
        if self.result is None or max_chars < 600:
            return ""
        text = wr.choose(self.result, max_chars)
        for src in self.result.sources:
            if src.chosen and id(src) not in self._rows and id(src) not in self._skip:
                if self._add_row(src, int(src.id[1:]) if src.id[1:].isdigit() else 0):   # a shown snapshot
                    self._sync_row(src)
        return text
