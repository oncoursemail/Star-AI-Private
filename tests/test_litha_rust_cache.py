"""Rust answer reuse requires a completed compiler check in the requested edition."""
from __future__ import annotations

import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh import instant, router  # noqa: E402
sys.path.remove(str(ROOT / "server"))


def make_router(tmp_path):
    obj = router.Router.__new__(router.Router)
    obj.cfg = {**router.DEFAULTS, "verify_url": "http://127.0.0.1:1"}
    obj.keys = SimpleNamespace(first=lambda: "fixture-key")
    obj.mesh_token = SimpleNamespace(first=lambda: "fixture-token")
    obj.cache = instant.AnswerCache(str(tmp_path / "answers.sqlite3"))
    obj.counters = Counter()
    return obj


def install_reply(monkeypatch, report, *, timeout=False):
    seen = []

    class Reply:
        status = 200
        closed = False

        async def body(self):
            if timeout:
                raise asyncio.TimeoutError
            return json.dumps(report).encode()

        def close(self):
            self.closed = True

    reply = Reply()

    async def upstream(url, method, body, headers, **kwargs):
        seen.append(json.loads(body))
        return reply

    monkeypatch.setattr(router, "open_upstream", upstream)
    return seen, reply


@pytest.mark.parametrize("checked,expected", [(True, True), (False, None), (None, None), (1, None)])
def test_rust_cache_requires_explicit_completed_check(tmp_path, monkeypatch, checked, expected):
    obj = make_router(tmp_path)
    seen, reply = install_reply(monkeypatch, {
        "ok": True, "needs_fix": False, "blocks": [{"language": "rust", "checked": checked}],
    })
    assert asyncio.run(obj.verify_ok("```rust\nfn main() {}\n```", "Write a Rust 2024 program")) is expected
    assert seen == [{"answer": "```rust\nfn main() {}\n```", "question": "Write a Rust 2024 program",
                     "language": "rust"}]
    assert reply.closed
    obj.cache.db.close()


def test_incomplete_rust_answer_is_not_stored_or_embedded(tmp_path, monkeypatch):
    obj = make_router(tmp_path)
    seen, _ = install_reply(monkeypatch, {
        "ok": True, "needs_fix": False, "blocks": [{"language": "rust", "checked": False}],
    })

    async def unexpected_embed(text):
        raise AssertionError("unverified code must not consume embedding work or be cached")

    obj.embed = unexpected_embed
    status, result = asyncio.run(obj.cache_api(
        "POST", {"authorization": "Bearer fixture-token"}, json.dumps({
            "question": "How do I print a greeting in Rust 2024?",
            "answer": "```rust\nfn main() {}\n```", "score": 3, "max_score": 3,
        }).encode()))
    assert status == 503 and "incomplete" in result["error"]["message"]
    assert obj.cache.stats()["entries"] == 0
    assert seen[0]["question"].endswith("Rust 2024?")
    obj.cache.db.close()


def test_unchecked_reverification_cannot_refresh_a_pass(tmp_path, monkeypatch):
    obj = make_router(tmp_path)
    question = "How do I print a greeting in Rust 2024?"
    answer = "```rust\nfn main() {}\n```"
    rid = obj.cache.put(question, answer, "", "fixture", 1.0, [1.0, 0.0], 3600)
    obj.cache.db.execute("UPDATE answers SET verified_at=123 WHERE id=?", (rid,))
    seen, _ = install_reply(monkeypatch, {
        "ok": True, "needs_fix": False, "blocks": [{"language": "rust", "checked": False}],
    })
    asyncio.run(obj._reverify(rid, answer, question))
    assert obj.cache.get(rid)["verified_at"] == 123
    assert seen[0]["question"] == question
    assert obj.counters["cache_dropped_on_reverify"] == 0  # inconclusive, not a fabricated failure
    obj.cache.db.close()


def test_verifier_timeout_releases_connection(tmp_path, monkeypatch):
    obj = make_router(tmp_path)
    _, reply = install_reply(monkeypatch, {}, timeout=True)
    assert asyncio.run(obj.verify_ok("fixture")) is None
    assert reply.closed
    obj.cache.db.close()


@pytest.mark.parametrize("question,candidate,expected", [
    ("Make a parser in Rust", "Make a parser in Python", "language"),
    ("Make a parser in TypeScript", "Make a parser in Rust", "language"),
    ("Make a parser in Rust", "Make a parser in C++", "language"),
    ("Make a parser in Rust", "Make a parser in Go", "language"),
    ("Make a parser in Rust", "Make a parser in C", "language"),
    ("Make a parser in Rust", "Make a parser in Kotlin", "language"),
    ("Write a Rust 2024 iterator", "Write a Rust 2021 iterator", "rust edition"),
    ("Write a Rust 2024 iterator", "Write a Rust iterator", "rust edition"),
    ("Write a Rust 2030 iterator", "Write a Rust iterator", "rust edition"),
    ("Explain Rust 2021 and Rust 2024", "Explain Rust 2024", "rust edition"),
    ("Write a Rust 2024 iterator", "In Rust edition 2024, write an iterator", None),
    ("Write a Rust iterator", "In Rust 2021, write an iterator", None),
    ("Translate Python to Rust", "Translate Rust to Python", None),  # existing mixed-language cue policy
])
def test_rust_semantic_reuse_preserves_language_and_edition(question, candidate, expected):
    assert instant.intent_conflict(question, candidate) == expected
    assert instant.intent_conflict(candidate, question) == expected


def test_checked_rust_warnings_still_block_cache(tmp_path, monkeypatch):
    obj = make_router(tmp_path)
    install_reply(monkeypatch, {
        "ok": True, "needs_fix": True, "blocks": [{"language": "rust", "checked": True}],
    })
    assert asyncio.run(obj.verify_ok("```rust\nfn main() {}\n```")) is False
    obj.cache.db.close()


@pytest.mark.parametrize("blocks", [None, {}, "rust", [None], []])
def test_missing_or_malformed_rust_checks_cannot_certify_code(tmp_path, monkeypatch, blocks):
    obj = make_router(tmp_path)
    install_reply(monkeypatch, {"ok": True, "needs_fix": False, "blocks": blocks})
    assert asyncio.run(obj.verify_ok("```rust\nfn main() {}\n```")) is None
    obj.cache.db.close()


@pytest.mark.parametrize("answer", [
    "fn main() {}", "const N: usize = 3;", "type Id = u64;", "static READY: bool = true;",
    "pub(crate) fn fixture() {}", "let n = 3;", 'println!("hello");',
    "```\nfn main() {}\n```", "~~~\nfn main() {}\n~~~", "42",
])
def test_raw_or_unlabelled_rust_answer_requests_compilation(tmp_path, monkeypatch, answer):
    obj = make_router(tmp_path)
    seen, _ = install_reply(monkeypatch, {"ok": True, "needs_fix": False, "blocks": []})
    question = "Write a Rust 2024 expression" if answer == "42" else "How does this work in Rust 2024?"
    assert asyncio.run(obj.verify_ok(answer, question)) is None
    assert seen[0]["language"] == "rust"
    obj.cache.db.close()


def test_rust_prose_answer_does_not_invent_a_compile_check(tmp_path, monkeypatch):
    obj = make_router(tmp_path)
    seen, _ = install_reply(monkeypatch, {"ok": True, "needs_fix": False, "blocks": []})
    assert asyncio.run(obj.verify_ok("Ownership is a Rust concept.", "What is Rust ownership?")) is True
    assert "language" not in seen[0]
    obj.cache.db.close()
