"""Conductor duel: opt-in, two writers, STAR's checks pick the verified winner, hash-only outbox event."""
import asyncio
import json

import pytest

from star.best_of_n import LuauChecker, PythonChecker
from star.conductor_duel import run_duel

SHA = "a" * 40
GOOD = "```python\ndef add(a, b):\n    return a + b\n```"
BAD = "```python\ndef add(a, b)\n    return a + b\n```"


def _w(text):
    async def w(prompt):
        return text
    return w


def _run(writers, tmp_path, **kw):
    args = dict(enabled=True, project_id="proj", source_sha=SHA, home=tmp_path)
    args.update(kw)
    return asyncio.run(run_duel("write add", writers, PythonChecker(), **args))


def test_off_by_default(tmp_path):
    with pytest.raises(PermissionError):
        _run({"a": _w(GOOD), "b": _w(GOOD)}, tmp_path, enabled=False)


def test_needs_two_writers(tmp_path):
    with pytest.raises(ValueError):
        _run({"a": _w(GOOD)}, tmp_path)


def test_verified_winner_recorded_hash_only(tmp_path):
    r = _run({"bad": _w(BAD), "good": _w(GOOD)}, tmp_path)
    assert r.verified and r.winner == "good"
    line = (tmp_path / "conductor" / "learning_events.jsonl").read_text().strip()
    ev = json.loads(line)
    assert ev["status"] == "pending_owner_review" and ev["winner"] == "good"
    assert "def add" not in line and "write add" not in line


def test_no_winner_when_both_fail(tmp_path):
    r = _run({"x": _w(BAD), "y": _w("no code here")}, tmp_path)
    assert not r.verified and r.winner is None
    assert not (tmp_path / "conductor").exists()


def test_failed_writer_does_not_block_other(tmp_path):
    async def boom(prompt):
        raise RuntimeError("down")
    r = _run({"boom": boom, "good": _w(GOOD)}, tmp_path)
    assert r.winner == "good" and r.verified


def test_luau_checker_without_tools_is_not_verified(tmp_path):
    ck = LuauChecker(lints=False)
    r = asyncio.run(run_duel("p", {"a": _w("```lua\nlocal x = 1\n```"), "b": _w("```lua\nlocal y = 2\n```")}, ck,
                             enabled=True, project_id="proj", source_sha=SHA, home=tmp_path))
    assert not r.verified  # only the code-block check ran: no real verdict
