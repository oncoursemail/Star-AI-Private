"""STAR search gateway: the only door from the network to the container's SearXNG.

SearXNG listens on 127.0.0.1:8888 inside the starai container and has no authentication. This
small stdlib-only service sits in front of it on the container's port 8093 and

  * requires the STAR Server key (same key file as the brain: `Authorization: Bearer <key>`);
  * accepts GET /search?q=...&n=5[&time_range=day|week|month|year][&categories=general|news], and
    GET /watched?since=<iso time>: the watched-page snapshots of the nightly poll (server/research), read-only;
  * rate-limits (token bucket, default 30 searches/minute, burst 10) and caps concurrency (4);
  * re-shapes SearXNG's JSON field by field (title, url, snippet, engine, published date), drops
    anything that is not an http(s) link, and caps every size, so the reply cannot grow without bound;
  * never logs queries (set STAR_SEARCH_LOG_QUERIES=1 to debug).

GET /health needs no key and says whether SearXNG answered recently. Python 3.12 stdlib only:

  python3 -I gateway.py --host 0.0.0.0 --port 8093
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_KEY_FILE = "/opt/star/secrets/api_keys"
DEFAULT_UPSTREAM = "http://127.0.0.1:8888"
MAX_QUERY_CHARS = 600
MAX_RESULTS = 10
MAX_UPSTREAM_BYTES = 3 * 1024 * 1024
UPSTREAM_TIMEOUT = 10.0
MAX_INFLIGHT = 4
RATE_PER_MINUTE = 30.0
RATE_BURST = 10.0
DEFAULT_WATCH_DB = "/opt/star/research/research-store.sqlite3"   # written by server/research (nightly poll)
WATCHED_PAGE_CHARS = 400_000
WATCHED_MAX_BYTES = 6 * 1024 * 1024
TIME_RANGES = frozenset({"day", "week", "month", "year"})
CATEGORIES = frozenset({"general", "news", "it", "science"})


def load_keys(key_file: str) -> list[bytes]:
    path = Path(key_file)
    if not path.is_file():
        return []
    return [line.strip().encode() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TokenBucket:
    def __init__(self, rate_per_minute: float = RATE_PER_MINUTE, burst: float = RATE_BURST,
                 clock=time.monotonic) -> None:
        self.rate = rate_per_minute / 60.0
        self.burst = burst
        self.tokens = burst
        self.clock = clock
        self.updated = clock()
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


def _text(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def reshape(payload, limit: int) -> dict:
    """SearXNG JSON -> the small, bounded shape STAR reads. Never raises on odd input."""
    results, seen = [], set()
    raw = payload.get("results") if isinstance(payload, dict) else None
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")[:1200]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            continue
        if url in seen:
            continue
        seen.add(url)
        engines = item.get("engines") if isinstance(item.get("engines"), list) else [item.get("engine")]
        results.append({
            "title": _text(item.get("title") or "Untitled", 200),
            "url": url,
            "snippet": _text(item.get("content"), 1000),
            "engines": [_text(e, 40) for e in engines if e][:5],
            "published": _text(item.get("publishedDate"), 40),
        })
        if len(results) >= limit:
            break
    answers = []
    for answer in (payload.get("answers") if isinstance(payload, dict) else None) or []:
        text = answer.get("answer") if isinstance(answer, dict) else answer
        if isinstance(text, str) and text.strip():
            answers.append(_text(text, 500))
        if len(answers) >= 2:
            break
    return {"results": results, "answers": answers}


def fetch_upstream(upstream: str, params: dict) -> dict:
    url = upstream.rstrip("/") + "/search?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "star-search-gateway"})
    # A plain opener: no system proxy for a loopback call.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=UPSTREAM_TIMEOUT) as response:
        body = response.read(MAX_UPSTREAM_BYTES + 1)
    if len(body) > MAX_UPSTREAM_BYTES:
        raise ValueError("upstream reply too large")
    return json.loads(body.decode("utf-8", errors="replace"))


class Gateway:
    def __init__(self, keys: list[bytes], *, upstream: str = DEFAULT_UPSTREAM, fetch=fetch_upstream,
                 bucket: TokenBucket | None = None, clock=time.time, watch_db: str = DEFAULT_WATCH_DB) -> None:
        self.keys = keys
        self.watch_db = watch_db
        self.upstream = upstream
        self.fetch = fetch
        self.bucket = bucket or TokenBucket()
        self.inflight = threading.BoundedSemaphore(MAX_INFLIGHT)
        self.clock = clock
        self.last_ok = 0.0
        self.counters = {"search": 0, "denied": 0, "limited": 0, "failed": 0}
        self.log_queries = os.environ.get("STAR_SEARCH_LOG_QUERIES") == "1"

    def authorized(self, header: str | None) -> bool:
        supplied = str(header or "").encode("utf-8", errors="replace")
        ok = False
        for key in self.keys:   # no early exit: every configured key is compared
            ok = hmac.compare_digest(supplied, b"Bearer " + key) or ok
        return ok

    def health(self) -> tuple[int, dict]:
        recent = self.last_ok and self.clock() - self.last_ok < 600
        return 200, {"ok": True, "service": "star-search-gateway", "searxng_recent_ok": bool(recent),
                     "keys_loaded": bool(self.keys), "counters": dict(self.counters)}

    def search(self, query_string: str, auth_header: str | None) -> tuple[int, dict]:
        if not self.keys or not self.authorized(auth_header):
            self.counters["denied"] += 1
            return 401, {"error": "STAR Server key required"}
        params = urllib.parse.parse_qs(query_string, keep_blank_values=False, max_num_fields=10)
        query = " ".join((params.get("q") or [""])[0].split())
        if not 1 <= len(query) <= MAX_QUERY_CHARS:
            return 400, {"error": f"q must be 1-{MAX_QUERY_CHARS} characters"}
        try:
            limit = int((params.get("n") or ["5"])[0])
        except ValueError:
            return 400, {"error": "n must be a number"}
        if not 1 <= limit <= MAX_RESULTS:
            return 400, {"error": f"n must be 1-{MAX_RESULTS}"}
        upstream = {"q": query, "format": "json", "safesearch": "1"}
        time_range = (params.get("time_range") or [""])[0]
        if time_range:
            if time_range not in TIME_RANGES:
                return 400, {"error": "time_range must be day, week, month or year"}
            upstream["time_range"] = time_range
        category = (params.get("categories") or [""])[0]
        if category:
            if category not in CATEGORIES:
                return 400, {"error": "categories must be general, news, it or science"}
            upstream["categories"] = category
        if not self.bucket.take():
            self.counters["limited"] += 1
            return 429, {"error": "rate limited; try again shortly"}
        if not self.inflight.acquire(blocking=False):
            self.counters["limited"] += 1
            return 503, {"error": "busy"}
        try:
            if self.log_queries:
                print(f"search: {query[:120]!r}", file=sys.stderr)
            payload = self.fetch(self.upstream, upstream)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            self.counters["failed"] += 1
            return 502, {"error": f"SearXNG unavailable ({type(exc).__name__})"}
        finally:
            self.inflight.release()
        self.counters["search"] += 1
        self.last_ok = self.clock()
        return 200, {"query": query, **reshape(payload, limit)}

    def watched(self, query_string: str, auth_header: str | None) -> tuple[int, dict]:
        """Snapshots of the pages STAR's nightly watch poll keeps (server/research/), changed after `since`,
        oldest change first, at most WATCHED_MAX_BYTES of text per reply ("more": true = ask again from "newest")."""
        if not self.keys or not self.authorized(auth_header):
            self.counters["denied"] += 1
            return 401, {"error": "STAR Server key required"}
        params = urllib.parse.parse_qs(query_string, keep_blank_values=False, max_num_fields=4)
        since = (params.get("since") or [""])[0][:40]
        if not self.bucket.take():
            self.counters["limited"] += 1
            return 429, {"error": "rate limited; try again shortly"}
        path = Path(self.watch_db)
        if not path.is_file():
            return 200, {"pages": [], "newest": since, "more": False}
        pages, used, newest, more = [], 0, since, False
        try:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            try:
                rows = db.execute("SELECT url,name,title,text,fetched_at,changed_at FROM pages WHERE text IS NOT NULL "
                                  "AND text!='' AND COALESCE(changed_at,'')>? ORDER BY changed_at", (since,)).fetchall()
            finally:
                db.close()
        except sqlite3.Error as exc:
            return 503, {"error": f"watch store unavailable ({type(exc).__name__})"}
        for url, name, title, text, fetched, changed in rows:
            text = str(text)[:WATCHED_PAGE_CHARS]
            if not str(url).startswith("https://"):
                continue
            if pages and used + len(text) > WATCHED_MAX_BYTES:
                # One poll gives every changed page the same time: resume from before this row's time, so the
                # rest of its group comes in the next reply (pages already sent are simply stored again).
                more = True
                cut = _text(changed, 40)
                newest = max((p["changed_at"] for p in pages if p["changed_at"] < cut), default=since)
                break
            used += len(text)
            pages.append({"url": str(url)[:1200], "name": _text(name, 80), "title": _text(title, 200), "text": text,
                          "fetched_at": _text(fetched, 40), "changed_at": _text(changed, 40)})
            newest = _text(changed, 40)
        self.counters["watched"] = self.counters.get("watched", 0) + 1
        return 200, {"pages": pages, "newest": newest, "more": more}


def make_handler(gateway: Gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "star-search-gateway"
        sys_version = ""
        timeout = 15

        def log_message(self, fmt, *args):   # the default access log would print the query
            pass

        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/health":
                self._send(*gateway.health())
            elif path == "/search":
                self._send(*gateway.search(query, self.headers.get("Authorization")))
            elif path == "/watched":
                self._send(*gateway.watched(query, self.headers.get("Authorization")))
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            self._send(405, {"error": "GET only"})

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8093)
    args = parser.parse_args(argv)
    keys = load_keys(os.environ.get("STAR_SEARCH_KEY_FILE", DEFAULT_KEY_FILE))
    if not keys:
        print("no STAR Server key found; every search will be refused", file=sys.stderr)
    gateway = Gateway(keys, upstream=os.environ.get("STAR_SEARXNG_URL", DEFAULT_UPSTREAM),
                      watch_db=os.environ.get("STAR_RESEARCH_DB", DEFAULT_WATCH_DB))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(gateway))
    server.daemon_threads = True
    print(f"star-search-gateway on {args.host}:{args.port} -> {gateway.upstream}", file=sys.stderr)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
