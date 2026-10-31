"""What only the owner's PC knows, for Star's live status: sent by the STAR GPU worker over its link every minute.

Read from the workspace folder (the parent of worktrees/, or STAR_PC_FEED_ROOT in ~/.star/gpu-worker.env):
STATE.md's current wave line and "Next actions", COLLAB/BOARD.md claims from the last 6 hours, and from GitHub (the
`gh` CLI the owner is signed in to, run in this checkout, at most every 5 minutes): PRs merged today, open PRs with
their check state, the newest releases. Plus the PC's UTC offset, so the server bot knows the owner's day.
Private addresses are blanked; nothing else from the PC is read.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

GH_EVERY = 300
CLAIM_HOURS = 6
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_LOGIN = re.compile(r"[A-Za-z0-9._-]+@(?:<ip>|[A-Za-z0-9.-]+\.(?:lan|local|internal)\b)")
_CLAIM = re.compile(r"^- \[CLAIMED\] (.+?) \| (\w[\w-]*) \| [^|]* \| (\d{4}-\d\d-\d\d \d\d:\d\d(?::\d\d)?Z)")


def _scrub(text: str, limit: int = 220) -> str:
    text = _LOGIN.sub("<login>", _IP.sub("<ip>", " ".join(str(text).split())))
    return text[:limit]


def state_lines(path: Path) -> tuple[str, list[str]]:
    """(current wave heading, the first bullets under '## Next actions')."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", []
    head = next((line[3:] for line in text.splitlines() if line.startswith("## 20")), "")
    bullets, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## next actions"
            continue
        if inside and line.startswith("- "):
            bullets.append(_scrub(line[2:]))
            if len(bullets) == 6:
                break
    return _scrub(head, 160), bullets


def fresh_claims(path: Path, now: datetime) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        match = _CLAIM.match(line)
        if not match:
            continue
        stamp = match.group(3).replace(" ", "T")
        try:
            since = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ" if stamp.count(":") == 2 else "%Y-%m-%dT%H:%MZ")
        except ValueError:
            continue
        since = since.replace(tzinfo=timezone.utc)
        if now - since <= timedelta(hours=CLAIM_HOURS):
            out.append({"item": _scrub(match.group(1), 120), "owner": match.group(2), "since": stamp})
    return out


def checks_state(rollup) -> str:
    if not rollup:
        return "none"
    states = []
    for row in rollup:
        states.append(str(row.get("conclusion") or row.get("state") or row.get("status") or "").upper())
    if any(s in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"} for s in states):
        return "failing"
    if any(s in {"", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING"} for s in states):
        return "pending"
    return "passing"


class PcFeed:
    """Builds the feed; GitHub answers are cached for GH_EVERY seconds."""

    def __init__(self, root: Path, checkout: Path, *, runner=subprocess.run, clock=time.time) -> None:
        self.root, self.checkout = Path(root), Path(checkout)
        self._run, self._clock = runner, clock
        self._gh: dict = {}
        self._gh_at = 0.0

    def _gh_json(self, args: list[str]):
        gh = shutil.which("gh")
        if not gh:
            return None
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = self._run([gh, *args], cwd=str(self.checkout), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           stdin=subprocess.DEVNULL, check=False, creationflags=flags)
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            return None

    def _github(self, local_date: str) -> dict:
        if self._gh and self._clock() - self._gh_at < GH_EVERY:
            return self._gh
        merged = self._gh_json(["pr", "list", "--state", "merged", "--search", f"merged:>={local_date}",
                                "--json", "number,title,mergedAt", "--limit", "30"])
        opened = self._gh_json(["pr", "list", "--state", "open", "--json",
                                "number,title,isDraft,mergeStateStatus,statusCheckRollup", "--limit", "40"])
        releases = self._gh_json(["release", "list", "--limit", "3", "--json", "tagName,isDraft,createdAt"])
        got = {}
        if merged is not None:
            got["merged_today"] = [{"number": p["number"], "title": _scrub(p.get("title", ""), 90)} for p in merged]
        if opened is not None:
            got["open_prs"] = [{"number": p["number"], "title": _scrub(p.get("title", ""), 90),
                                "draft": bool(p.get("isDraft")), "merge": str(p.get("mergeStateStatus", ""))[:20],
                                "checks": checks_state(p.get("statusCheckRollup"))} for p in opened]
        if releases is not None:
            got["releases"] = [{"tag": _scrub(r.get("tagName", ""), 40), "draft": bool(r.get("isDraft")),
                                "at": str(r.get("createdAt", ""))[:20]} for r in releases]
        if got:
            self._gh, self._gh_at = {**self._gh, **got}, self._clock()
        return self._gh

    def build(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        local = now.astimezone()
        offset = local.utcoffset() or timedelta(0)
        head, bullets = state_lines(self.root / "STATE.md")
        feed = {"v": 1, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tz_offset_min": int(offset.total_seconds() // 60),
                "state_head": head, "state_next": bullets, "claims": fresh_claims(self.root / "COLLAB" / "BOARD.md", now)}
        feed.update(self._github(local.strftime("%Y-%m-%d")))
        return feed


def default_root(checkout: Path) -> Path:
    """The workspace folder: <root>/worktrees/<name> -> <root>; a checkout elsewhere -> its parent."""
    checkout = Path(checkout).resolve()
    return checkout.parents[1] if checkout.parent.name == "worktrees" else checkout.parent
