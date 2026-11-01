"""Inspect before code: before a Roblox build/edit turn, STAR reads the open Studio scene for the objects and scripts
the request is about and gives the model that list, so it edits what exists instead of guessing names and paths.

Why: in OpenGameEval (Roblox, arXiv 2610.02563) runs that inspected every object the reference solution touched passed
13.4 points more often on scene tasks and 9.8 on script tasks than runs that inspected none
(docs/research/coding-smarts-20261023.md finding 4). Opt-in (setting `studio_inspect`, default off) until it is
measured on Studio tasks here.

Only read tools are used (`search_game_tree`, through the guarded Studio connection), with a short timeout; any
failure means no section, never a failed turn. The section is data for the model, bounded to MAX_CHARS.
"""
from __future__ import annotations

import asyncio
import json
import re

MAX_CHARS = 1500
MAX_KEYWORDS = 6
MAX_ROWS = 25
TIMEOUT_SECONDS = 8.0
_QUOTED = re.compile(r"[\"'`]([A-Za-z][\w ]{1,40})[\"'`]")
_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9_]{2,40}\b")
_STOP = frozenset("""
the and for with that this from into onto when what which where while make makes making add adds create build
write script scripts code luau roblox studio game place please can could would should will want need them they
their there here have has had not but use using used new old all any each every some one two three more less than
then also just like into over under about after before it's its your you our out off set get let see show move
""".split())


def keywords(prompt: str) -> list[str]:
    """Names the request is about: quoted names first, then CamelCase names, then plain nouns (no stop words)."""
    found: list[str] = []

    def add(word: str) -> None:
        word = word.strip()
        if word and word.lower() not in _STOP and word.lower() not in (w.lower() for w in found):
            found.append(word)

    for name in _QUOTED.findall(prompt or ""):
        add(name)
    words = _WORD.findall(prompt or "")
    for word in words:
        if re.search(r"[a-z][A-Z]|^[A-Z][a-z]+[A-Z]", word):
            add(word)
    for word in words:
        add(word.lower())
    return found[:MAX_KEYWORDS]


def _rows(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("["), text.rfind("]")
        try:
            data = json.loads(text[start:end + 1]) if start >= 0 < end else []
        except ValueError:
            return []
    return [row for row in data if isinstance(row, dict) and row.get("fullPath")] if isinstance(data, list) else []


async def scene_section(studio, prompt: str, *, timeout: float = TIMEOUT_SECONDS) -> str:
    """The text of the ROBLOX STUDIO SCENE section, or "" when nothing relevant was found or Studio did not answer."""
    from .studio_loop import result_failed, result_text
    words = keywords(prompt)
    calls = [{"datamodel_type": "Edit", "instance_type": "BaseScript", "head_limit": 30, "max_depth": 10}]
    if words:
        calls.insert(0, {"datamodel_type": "Edit", "keywords": ", ".join(words), "head_limit": 40, "max_depth": 8})
    lines: list[str] = []
    seen: set[str] = set()
    for arguments in calls:
        try:
            result = await asyncio.wait_for(
                studio.call_tool("search_game_tree", {"studio_id": studio.studio_id, **arguments}), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            return ""
        if result_failed(result):
            continue
        for row in _rows(result_text(result)):
            path = str(row["fullPath"])[:160]
            if path in seen or path.startswith(("CoreGui", "CorePackages")):
                continue
            seen.add(path)
            extra = f", {row['childSummary']}" if row.get("childSummary") else ""
            lines.append(f"- {path} ({str(row.get('className', '?'))[:40]}{extra[:80]})")
            if len(lines) >= MAX_ROWS:
                break
    if not lines:
        return ""
    head = ("Objects and scripts already in the open place that match this request"
            + (f" (searched: {', '.join(words)})" if words else "")
            + ". Read and edit these where they fit instead of creating new ones; use these exact paths:\n")
    text = head + "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS].rsplit("\n", 1)[0]
