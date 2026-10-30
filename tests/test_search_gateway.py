"""server/searxng/gateway.py: key required, bounded, rate limited, re-shaped (no network)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import urllib.error

import pytest

PATH = Path(__file__).resolve().parents[1] / "server" / "searxng" / "gateway.py"
spec = importlib.util.spec_from_file_location("star_search_gateway", PATH)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

KEY = b"test-server-key-0123456789"   # synthetic (star:allow)
AUTH = "Bearer " + KEY.decode()
RAW = {"results": [
    {"title": "Roblox news", "url": "https://news.example/a", "content": "x" * 5000, "engine": "bing news",
     "publishedDate": "2026-10-13T10:00:00"},
    {"title": "dup", "url": "https://news.example/a", "content": "dup"},
    {"title": "bad", "url": "javascript:alert(1)", "content": "no"},
    {"title": "creds", "url": "https://u:p@news.example/", "content": "no"},
    {"title": "plain http", "url": "http://old.example/b", "content": "ok", "engines": ["duckduckgo"]},
    "garbage",
], "answers": ["42", {"answer": "forty-two"}, "more"]}


def make(fetch=None, bucket=None):
    calls = []

    def default_fetch(upstream, params):
        calls.append(params)
        return RAW
    return gateway.Gateway([KEY], fetch=fetch or default_fetch, bucket=bucket), calls


def test_key_is_required():
    g, calls = make()
    assert g.search("q=roblox", None)[0] == 401
    assert g.search("q=roblox", "Bearer wrong")[0] == 401
    assert gateway.Gateway([], fetch=lambda u, p: RAW).search("q=roblox", AUTH)[0] == 401
    assert calls == []


def test_results_are_reshaped_and_bounded():
    g, calls = make()
    status, body = g.search("q=roblox+news&n=5&categories=news&time_range=week", AUTH)
    assert status == 200
    assert calls == [{"q": "roblox news", "format": "json", "safesearch": "1", "time_range": "week",
                      "categories": "news"}]
    assert [r["url"] for r in body["results"]] == ["https://news.example/a", "http://old.example/b"]
    first = body["results"][0]
    assert len(first["snippet"]) == 1000 and first["engines"] == ["bing news"]
    assert first["published"] == "2026-10-13T10:00:00"
    assert body["answers"] == ["42", "forty-two"]
    json.dumps(body)


@pytest.mark.parametrize("query", ["", "q=", "q=" + "a" * 601, "q=x&n=0", "q=x&n=11", "q=x&n=abc",
                                   "q=x&time_range=decade", "q=x&categories=images"])
def test_bad_requests(query):
    g, calls = make()
    assert g.search(query, AUTH)[0] == 400
    assert calls == []


def test_rate_limit():
    now = [0.0]
    bucket = gateway.TokenBucket(rate_per_minute=6, burst=2, clock=lambda: now[0])
    g, _ = make(bucket=bucket)
    assert [g.search("q=a", AUTH)[0] for _ in range(3)] == [200, 200, 429]
    now[0] += 10.0          # 6/min = one token per 10 s
    assert g.search("q=a", AUTH)[0] == 200


def test_upstream_failure_is_502_and_health_reports_it():
    def down(upstream, params):
        raise urllib.error.URLError("refused")
    g, _ = make(fetch=down)
    assert g.search("q=a", AUTH)[0] == 502
    status, health = g.health()
    assert status == 200 and health["searxng_recent_ok"] is False and health["counters"]["failed"] == 1


def test_load_keys(tmp_path):
    keyfile = tmp_path / "api_keys"
    keyfile.write_text("one\n\n two \n", encoding="utf-8")
    assert gateway.load_keys(str(keyfile)) == [b"one", b"two"]
    assert gateway.load_keys(str(tmp_path / "missing")) == []


def _watch_db(path, rows):
    import sqlite3
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE pages(url TEXT PRIMARY KEY, name TEXT, title TEXT, text TEXT, sha TEXT, fetched_at TEXT, "
               "changed_at TEXT, every_hours INTEGER, error TEXT DEFAULT '')")
    db.executemany("INSERT INTO pages(url,name,title,text,fetched_at,changed_at) VALUES(?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


def test_watched_snapshots_need_the_key_and_come_since_a_time(tmp_path):
    path = tmp_path / "research-store.sqlite3"
    _watch_db(path, [("https://a.example/notes", "a", "A", "alpha", "t1", "2026-10-30T08:00:00"),
                     ("https://b.example/notes", "b", "B", "beta", "t2", "2026-10-31T08:00:00"),
                     ("https://c.example/empty", "c", "C", "", "t3", "2026-10-31T09:00:00"),
                     ("javascript:alert(1)", "d", "D", "bad", "t4", "2026-10-31T10:00:00")])
    g = gateway.Gateway([KEY], watch_db=str(path))
    assert g.watched("", None)[0] == 401
    status, body = g.watched("", AUTH)
    assert status == 200 and [p["url"] for p in body["pages"]] == ["https://a.example/notes", "https://b.example/notes"]
    assert body["newest"] == "2026-10-31T08:00:00" and body["more"] is False
    status, body = g.watched("since=2026-10-30T08:00:00", AUTH)
    assert [p["text"] for p in body["pages"]] == ["beta"]
    assert gateway.Gateway([KEY], watch_db=str(tmp_path / "missing.sqlite3")).watched("", AUTH)[1]["pages"] == []


def test_watched_reply_is_bounded_and_resumes_before_a_cut_group(tmp_path, monkeypatch):
    path = tmp_path / "research-store.sqlite3"
    _watch_db(path, [("https://a.example/1", "a", "A", "x" * 60, "t", "2026-10-30T08:00:00"),
                     ("https://b.example/2", "b", "B", "y" * 60, "t", "2026-10-31T08:00:00"),
                     ("https://c.example/3", "c", "C", "z" * 60, "t", "2026-10-31T08:00:00")])
    monkeypatch.setattr(gateway, "WATCHED_MAX_BYTES", 130)
    g = gateway.Gateway([KEY], watch_db=str(path))
    body = g.watched("", AUTH)[1]
    assert len(body["pages"]) == 2 and body["more"] is True
    assert body["newest"] == "2026-10-30T08:00:00"             # the 10-31 group comes again, whole
    rest = g.watched("since=" + body["newest"], AUTH)[1]
    assert [p["url"] for p in rest["pages"]] == ["https://b.example/2", "https://c.example/3"]
