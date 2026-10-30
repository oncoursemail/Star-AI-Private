"""Live, per-turn context: the current time and, for questions about what is happening now, web results.

Used where the model has no tools of its own (Discord, desktop plain chat): the app looks up what
the question needs and appends it at the END of the user's message, after everything else, so the
start of the request stays byte-identical and cached. Desktop/CLI turns get the time line from
star.agent.volatile_context; this module adds the automatic web search and the Discord block.

Nothing here raises into a chat turn: a failed search becomes one line telling the model it failed,
so it says so instead of claiming it has no internet access.
"""
from __future__ import annotations

import asyncio
import re
import time

from .clock import now_line, observe_server_date

AUTO_SEARCH_TIMEOUT = 20.0
SERVER_CLOCK_EVERY = 1800.0

# Questions whose answer changes over time: news, "latest", prices, scores, weather, or an explicit
# request to look something up. Narrow on purpose: "update the script" or "the latest frame" in a
# Roblox coding question must not trigger a search.
_FRESH_WEB = re.compile(
    r"\bnews\b|\bheadlines?\b|\bbreaking\b|"
    r"\blatest\s+(?:news|updates?|version|release|announcements?|on|about|in|from|roblox|events?|patch)\b|"
    r"\bwhat(?:'s|\s+is)\s+(?:new|happening|going\s+on|trending)\b|"
    r"\b(?:recent|recently)\s+(?:news|released|announced|changes|events|updates?)\b|"
    r"\b(?:current|today'?s?|this\s+week'?s?)\s+(?:news|events|price|prices|weather|score|scores|ceo|president|"
    r"prime\s+minister|version|exchange\s+rate)\b|"
    r"\bweather\b|\bforecast\b|\bstock\s+price\b|\bprice\s+of\b|\bexchange\s+rate\b|\bwho\s+won\b|\bscores?\s+(?:of|for|in)\b|"
    r"\b(?:search|google|look\s+up|browse)\s+(?:the\s+web|online|the\s+internet|for)\b|"
    r"\b(?:search|look)\s+(?:it|this|that)\s+up\b|\bon\s+the\s+(?:web|internet)\b|\bhttps?://",
    re.IGNORECASE)

# Facts newer than the model (web-research-20261029: 0 of 62 fresh-fact benchmark questions such as "Which team won
# the 2026 World Series?" or "What new built-in type does Python 3.15 add?" triggered the search above, so chat
# answered them from memory): release notes / changelogs, "who/which team won", "when was X released/held",
# "latest stable", "as of <month/year>", a product with a version number plus a what-changed word, or this or last
# year named in the question.
_RECENT_FACT = re.compile(
    r"\b(?:release|patch)\s+notes?\b|\bchange\s?logs?\b|\brelease\s+date\b|"
    r"\b(?:who|which\s+(?:team|party|country|player|club|company|studio|film|game))\s+won\b|"
    r"\bwhen\s+(?:was|were|did|is|will)\b.{0,80}?\b(?:release[sd]?|launch(?:ed)?|announced?|ship(?:ped)?|"
    r"come\s+out|held|available)\b|"
    r"\blatest\s+stable\b|"
    r"\bas\s+of\s+(?:(?:late|early|mid)[-\s])?(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|20\d\d)\b",
    re.IGNORECASE)
_VERSIONED = re.compile(r"\b[A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z]+)?\s+v?\d+\.\d+(?:\.\d+)?\b")
_CHANGED = re.compile(r"\b(?:add(?:s|ed)?|introduc\w*|new|stabili[sz]\w*|requir\w*|replac\w*|deprecat\w*|remov\w*|"
                      r"chang\w*|released?)\b", re.IGNORECASE)
# A year named on its own ("the 2026 World Series", "in 2026"), not inside a written date or a timestamp.
_YEAR = re.compile(r"(?<![\d/:-])(?<!\d,\s)(?<!\d\s)\b(20\d\d)\b(?![-/:]\d)")

_last_probe = {"at": 0.0}


def wants_fresh_web(prompt: str) -> bool:
    text = prompt or ""
    if _FRESH_WEB.search(text) or _RECENT_FACT.search(text):
        return True
    if _VERSIONED.search(text) and _CHANGED.search(text):
        return True
    this_year = time.gmtime().tm_year
    return any(this_year - 1 <= int(year) <= this_year + 1 for year in _YEAR.findall(text))


async def auto_search(prompt: str, *, settings=None, searcher=None, limit: int = 5) -> tuple[str, list[dict]]:
    """(context text, sources) for a fresh-information question. Never raises.

    The text is the untrusted, cited search block (web_search.source_context), or one line saying the
    search failed. Returns ("", []) when the question does not need the web or no provider is set up.
    (Reading the pages through star.web_research here was measured: 60/62 vs 59/62 correct for +4 s, not shipped.)
    """
    from .web_search import search_web, source_context, web_search_available
    if not wants_fresh_web(prompt):
        return "", []
    if searcher is None and not web_search_available(settings):
        return ("Web search is not set up (no STAR search server or search key), so no live results were "
                "retrieved for this question; say so briefly if the answer depends on them."), []
    query = " ".join(prompt.split())[:600]
    try:
        search = searcher or (lambda q, limit: search_web(q, limit=limit, settings=settings))
        sources = await asyncio.wait_for(search(query, limit=limit), timeout=AUTO_SEARCH_TIMEOUT)
    except Exception as exc:
        return (f"An automatic web search was attempted for this question and failed ({type(exc).__name__}); "
                "say so briefly instead of claiming you have no internet access."), []
    if not sources:
        return "An automatic web search found no usable results for this question.", []
    return source_context(sources), list(sources)


async def refresh_server_clock(settings, *, timeout: float = 1.5, monotonic=time.monotonic, get=None) -> None:
    """Read the STAR Server's clock from the Date header of its /health reply, at most every 30 min.
    Only for the owner's STAR Server (a private address). Never raises."""
    now = monotonic()
    if now - _last_probe["at"] < SERVER_CLOCK_EVERY:
        return
    _last_probe["at"] = now
    try:
        from .providers import uses_star_server, validate_lan_endpoint
        if not uses_star_server(settings):
            return
        endpoint = validate_lan_endpoint(getattr(settings, "server_endpoint", ""),
                                         allow_cgnat=getattr(settings, "allow_cgnat", False))
        url = endpoint[:-len("/v1")] + "/health"
        if get is None:
            import httpx
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                response = await client.get(url)
            date = response.headers.get("date", "")
        else:
            date = await get(url)
        if date:
            observe_server_date(date)
    except Exception:
        return


def refresh_server_clock_soon(settings) -> None:
    """Start `refresh_server_clock` on a daemon thread: the chat turn never waits for it; what it
    reads is used from the next turn on. At most one probe every 30 minutes. Never raises."""
    if time.monotonic() - _last_probe["at"] < SERVER_CLOCK_EVERY:
        return
    import threading
    def probe():
        try:
            asyncio.run(refresh_server_clock(settings))
        except Exception:
            pass
    threading.Thread(target=probe, name="star-server-clock", daemon=True).start()


def forget() -> None:
    _last_probe["at"] = 0.0


async def discord_live(question: str, *, settings=None, searcher=None) -> str:
    """The live block for one Discord message: web results when the question needs them, then the
    current time as the very last line. Never raises."""
    if settings is not None:
        await refresh_server_clock(settings)
    web, _sources = await auto_search(question, settings=settings, searcher=searcher)
    parts = []
    if web:
        parts.append(web)
    parts.append(now_line())
    return "\n\n".join(parts)
