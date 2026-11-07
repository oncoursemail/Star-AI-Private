"""Knowledge service watchdog: one real search a minute; restart the service after two failures in a row.

Run by star-knowledge-watchdog.timer (every minute, as root: it restarts a unit). One check:

  * POST /search on 127.0.0.1:8091 with the service key and a query that changes every minute (so the reply cache
    cannot answer it), CHECK_TIMEOUT seconds. Healthy = HTTP 200 with at least one passage (a degraded BM25 reply
    counts: the service itself works).
  * Two failed checks in a row: SIGUSR1 to the service first (serve.py registers faulthandler on it, so every
    thread's stack lands in the journal; the 2026-10-20 07:07Z hang left no trace), then `systemctl restart`.
    At most MAX_RESTARTS_PER_HOUR restarts an hour, so a broken index cannot cause a restart loop.
  * Every result goes to STATE_FILE (JSON, last RESTARTS_KEPT restarts with their reason). The Discord bot reads it
    over its existing ssh login (star/discord_bot/digest_task.py) and DMs the owner about each new restart.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8091/search"
UNIT = "star-knowledge"
STATE_FILE = Path(os.environ.get("STAR_KB_HOME", "/opt/star/knowledge")) / "data" / "watchdog.json"
KEY_FILE = Path(os.environ.get("STAR_KB_KEY_FILE", "/opt/star/secrets/api_keys"))
CHECK_TIMEOUT = 15.0
FAILURES_BEFORE_RESTART = 2
MAX_RESTARTS_PER_HOUR = 3
RESTARTS_KEPT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def check(url: str = URL, key: str = "", timeout: float = CHECK_TIMEOUT, now: datetime | None = None) -> str:
    """"" when the service answered a real search, else a short reason."""
    minute = (now or _now()).strftime("%H:%M")
    body = json.dumps({"query": f"How do I tween a part with TweenService? (watchdog {minute})", "top": 1}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            data = json.loads(reply.read(1_000_000))
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except (OSError, ValueError) as exc:     # refused, timed out, reset, bad JSON
        return type(exc).__name__ + (": timed out" if "timed out" in str(exc) else "")
    if not isinstance(data, dict) or not data.get("passages"):
        return "no passages"
    return ""


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {"failures": 0, "restarts": []}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    tmp.replace(path)


def restart(unit: str = UNIT, run=subprocess.run, sleep=time.sleep) -> bool:
    """Dump the stacks (SIGUSR1 -> faulthandler -> journal), then restart. True if systemctl succeeded."""
    run(["systemctl", "kill", "--signal=SIGUSR1", unit], check=False, timeout=30)
    sleep(2)
    return run(["systemctl", "restart", unit], check=False, timeout=120).returncode == 0


def tick(state: dict, reason: str, now: datetime, do_restart, log=print) -> dict:
    """Apply one check result to the state; restarts through `do_restart()` when due. Returns the new state."""
    state = {**state, "checked_at": _stamp(now), "ok": not reason, "last_error": reason or state.get("last_error", "")}
    restarts = list(state.get("restarts", []))
    if not reason:
        state["failures"] = 0
        return {**state, "restarts": restarts}
    failures = int(state.get("failures", 0)) + 1
    log(f"watchdog: check failed ({reason}), {failures} in a row")
    if failures >= FAILURES_BEFORE_RESTART:
        hour_ago = _stamp(now - timedelta(hours=1))
        recent = [r for r in restarts if r.get("at", "") > hour_ago and r.get("done")]
        if len(recent) >= MAX_RESTARTS_PER_HOUR:
            log(f"watchdog: NOT restarting {UNIT}: {len(recent)} restarts in the last hour already")
        else:
            done = bool(do_restart())
            log(f"watchdog: restarted {UNIT} after {failures} failed checks ({reason}): "
                + ("ok" if done else "systemctl restart FAILED"))
            restarts.append({"at": _stamp(now), "reason": reason, "failures": failures, "done": done})
            failures = 0
    state["failures"] = failures
    return {**state, "restarts": restarts[-RESTARTS_KEPT:]}


def main() -> int:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        print("watchdog: no service key file; nothing checked")
        return 1
    now = _now()
    state = tick(load_state(STATE_FILE), check(key=key, now=now), now, restart)
    save_state(STATE_FILE, state)
    return 0
