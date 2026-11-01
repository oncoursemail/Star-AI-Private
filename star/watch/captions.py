"""Caption and metadata sources that need no player: yt-dlp (never used to download the video, only text).

  fetch_captions(url)   --skip-download --write-subs --write-auto-subs  -> WebVTT -> timed Lines
  fetch_metadata(url)   -J --skip-download   -> title, channel, duration, chapters, description (data only)
  search(query)         --flat-playlist ytsearchN:   -> Candidates for the "search" way of choosing a video
Everything goes through `run(argv, timeout) -> (exit code, stdout)`, so tests pass a fake and nothing here touches
the network by itself. A video without captions, or a PC without yt-dlp, gives an empty result, never an exception:
she then listens through star.senses instead.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable, cast

from .model import AudioState, Candidate, Line

Run = Callable[[list[str], float], tuple[int, str]]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CUE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/", re.I)


def default_run(argv: list[str], timeout: float) -> tuple[int, str]:  # pragma: no cover - needs yt-dlp on the PC
    exe = shutil.which("yt-dlp")
    command = [exe, *argv] if exe else [sys.executable, "-m", "yt_dlp", *argv]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                              creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, done.stdout


def _seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(text: str) -> list[tuple[float, float, str]]:
    """WebVTT -> [(start, end, text)]. Auto captions repeat the previous line as the first row of the next cue and
    carry <c> tags: tags are dropped and a line already said by the previous cue is not added twice."""
    out: list[tuple[float, float, str]] = []
    last_text: list[str] = []
    block: list[str] = []
    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if line:
            block.append(line)
            continue
        cue = next((i for i, row in enumerate(block) if _CUE.search(row)), None)
        if cue is not None:
            g = cast(re.Match[str], _CUE.search(block[cue])).groups()
            start, end = _seconds(g[0], g[1], g[2], g[3]), _seconds(g[4], g[5], g[6], g[7])
            rows = [re.sub(r"\s+", " ", _TAG.sub("", row)).strip() for row in block[cue + 1:]]
            rows = [row for row in rows if row]
            fresh = [row for row in rows if row not in last_text]
            if fresh and end > start:
                out.append((start, end, " ".join(fresh)))
            if rows:
                last_text = rows
        block = []
    return out


def fetch_captions(url: str, workdir: Path, *, run: Run = default_run, langs: str = "en.*,en",
                   timeout: float = 90.0) -> list[tuple[float, float, str]]:
    if not _URL.match(url or ""):
        return []
    folder = Path(workdir)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("cap_*.vtt"):
        old.unlink(missing_ok=True)
    code, _ = run(["--skip-download", "--no-playlist", "--write-subs", "--write-auto-subs", "--sub-langs", langs,
                   "--sub-format", "vtt", "-o", str(folder / "cap_%(id)s"), url], timeout)
    if code != 0:
        return []
    for path in sorted(folder.glob("cap_*.vtt")):
        try:
            return parse_vtt(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return []


def fetch_metadata(url: str, *, run: Run = default_run, timeout: float = 60.0) -> dict:
    if not _URL.match(url or ""):
        return {}
    code, out = run(["-J", "--skip-download", "--no-playlist", url], timeout)
    if code != 0:
        return {}
    try:
        data = json.loads(out)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {"title": str(data.get("title") or "")[:200], "channel": str(data.get("channel") or data.get("uploader") or "")[:100],
            "duration_s": float(data.get("duration") or 0), "description": str(data.get("description") or "")[:1500],
            "chapters": [{"start": float(c.get("start_time") or 0), "title": str(c.get("title") or "")[:100]}
                         for c in (data.get("chapters") or [])[:30] if isinstance(c, dict)],
            "is_live": bool(data.get("is_live")), "id": str(data.get("id") or "")}


def search(query: str, count: int = 10, *, run: Run = default_run, timeout: float = 60.0) -> list[Candidate]:
    query = " ".join(str(query).split())[:100]
    if not query:
        return []
    code, out = run(["--flat-playlist", "-J", f"ytsearch{max(1, min(20, count))}:{query}"], timeout)
    if code != 0:
        return []
    try:
        entries = json.loads(out).get("entries") or []
    except (ValueError, AttributeError):
        return []
    found = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        duration = float(entry.get("duration") or 0)
        found.append(Candidate(title=str(entry.get("title") or "")[:200],
                               channel=str(entry.get("channel") or entry.get("uploader") or "")[:100],
                               url=str(entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}"),
                               duration_s=duration, views=int(entry.get("view_count") or 0), source="search",
                               is_short=bool(duration and duration <= 60),
                               is_live=entry.get("live_status") in ("is_live",),
                               description=str(entry.get("description") or "")[:400]))
    return found


class CaptionHearing:
    """The HearingSource for a video whose captions were fetched: lines come out as the position passes them."""

    def __init__(self, cues: list[tuple[float, float, str]]) -> None:
        self.cues = sorted(cues)
        self._last = -1.0

    def poll(self, position: float) -> list[Line]:
        out = [Line(start, text, "caption") for start, _end, text in self.cues if self._last < start <= position]
        self._last = max(self._last, position)
        return out

    def state(self, position: float) -> AudioState:
        speaking = any(start <= position <= end for start, end, _ in self.cues)
        return AudioState("speech" if speaking else "silence", -20.0 if speaking else -120.0, speaking)
