"""Knowledge-service watchdog restarts reach the owner as Discord DMs, once each (star/discord_bot/digest_task.py)."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from star.discord_bot import digest_task

OWNER = 111
NOW = datetime(2026, 10, 20, 7, 40, tzinfo=timezone.utc)


def config(tmp_path):
    return digest_task.DigestConfig.from_env({
        "STAR_DISCORD_OWNER_IDS": str(OWNER), "STAR_DISCORD_LEARNING_DM_OPT_IN": "1",
        "STAR_DISCORD_LEARNING_REPORT_SSH": "star@brain.invalid",
        "STAR_DISCORD_LEARNING_STATE": str(tmp_path / "state" / "dms.sqlite3")})


def runner_for(state, code=0):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[-1] == digest_task.REMOTE_WATCHDOG_COMMAND and "BatchMode=yes" in argv
        return SimpleNamespace(returncode=code, stdout=json.dumps(state).encode())
    return runner, calls


def run(cfg, runner, now=NOW):
    if not digest_task.shutil.which("ssh"):
        pytest.skip("ssh client not installed")
    sent = []

    async def send(body, visual):
        sent.append(body)
    count = asyncio.run(digest_task.send_watchdog_alerts(cfg, send, runner=runner, now=now))
    return count, sent


def test_each_recent_restart_is_sent_once_and_old_ones_are_history(tmp_path):
    cfg = config(tmp_path)
    state = {"failures": 0, "restarts": [
        {"at": "2026-10-18T03:00:00Z", "reason": "HTTP 500", "failures": 2, "done": True},       # 2 days old
        {"at": "2026-10-20T07:09:00Z", "reason": "TimeoutError: timed out", "failures": 2, "done": True}]}
    runner, calls = runner_for(state)
    count, sent = run(cfg, runner)
    assert count == 1 and len(sent) == 1 and len(calls) == 1
    assert "restarted by its watchdog" in sent[0] and "2026-10-20T07:09:00Z" in sent[0] and "timed out" in sent[0]
    assert "FAILED" not in sent[0]
    assert run(cfg, runner, NOW + timedelta(minutes=30)) == (0, [])          # already sent: no second DM
    state["restarts"].append({"at": "2026-10-20T08:00:00Z", "reason": "HTTP 503", "failures": 2, "done": False})
    count, sent = run(cfg, runner_for(state)[0], NOW + timedelta(hours=1))
    assert count == 1 and "HTTP 503" in sent[0] and "FAILED" in sent[0]


def test_reason_text_is_reduced_to_plain_characters(tmp_path):
    state = {"restarts": [{"at": "2026-10-20T07:09:00Z", "reason": "<@everyone> **x**", "failures": 2, "done": True}]}
    _, sent = run(config(tmp_path), runner_for(state)[0])
    assert "@" not in sent[0].split("(")[-1] and "<" not in sent[0]


def test_no_watchdog_file_or_bad_json_sends_nothing(tmp_path):
    assert run(config(tmp_path), runner_for({}, code=1)[0]) == (0, [])
    bad = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=b"{not json")   # noqa: E731
    assert run(config(tmp_path), bad) == (0, [])
