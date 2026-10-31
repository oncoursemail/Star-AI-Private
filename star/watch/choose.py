"""Choosing what to watch: her interest weights, the curiosity queue, novelty, and following a recommendation.

score(candidate) in [0, 1.05]:
  0.50 interest   best match between the title/channel/description words and her interests, times that interest's
                  weight (weights are 0.1-5, star/home/life.py); a match needs 1 keyword hit, 3 hits is a full match
  0.25 curiosity  word overlap with the top items of the curiosity queue (things she got wrong or did not know)
  0.15 novelty    not seen before; a channel she watched in the last 3 days counts less
  0.10 follow     a recommendation beside a video she liked, sharing its topic words
Ads are never picked; shorts and live streams only if the settings allow; a video much longer than she will watch is
discounted. pick() samples among the best few (softmax) instead of always taking the top, so she does not repeat.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
import re
import time

from .model import Candidate
from .settings import WatchSettings

_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_WORD = re.compile(r"[a-z][a-z0-9+#']{2,}")
STOP = frozenset("""the and for with that this from your you are was were will about what how why when into out over
make made get got new best top video videos full part episode official channel play just all one two not but have has
his her they them our can too very more most some any who whom been being than then there here also its it's""".split())

TOPIC_KEYWORDS = {
    "drawing": ("draw", "drawing", "sketch", "painting", "illustration", "anatomy", "shading", "digital art",
                "character design", "pixel art", "animation", "animate", "procreate", "krita", "inking"),
    "game_making": ("game dev", "gamedev", "game development", "unity", "godot", "unreal", "roblox", "luau", "shader",
                    "level design", "game design", "indie game", "devlog", "programming", "coding", "tutorial"),
    "music": ("music", "song", "beat", "producer", "synth", "piano", "guitar", "mixing", "mastering", "melody",
              "chord", "fl studio", "ableton", "lofi", "soundtrack", "composer"),
    "research": ("explained", "documentary", "how it works", "science", "history", "lecture", "physics", "math",
                 "space", "biology", "engineering", "machine learning", "neural"),
    "practice": ("tutorial", "lesson", "learn", "course", "tips", "beginner", "guide"),
    "play_games": ("gameplay", "speedrun", "walkthrough", "minecraft", "roblox", "let's play", "playthrough"),
}


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in STOP}


def _phrases(candidate: Candidate) -> str:
    return " ".join((candidate.title, candidate.channel, candidate.description[:400])).lower()


class WatchHistory:
    """<home>/watch/history.jsonl: one row per video she watched (what, when, how much she liked it)."""

    def __init__(self, home: Path, clock=time.time) -> None:
        self.path = Path(home) / "watch" / "history.jsonl"
        self.clock = clock

    def rows(self, last: int = 400) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-last:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def add(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.fromtimestamp(self.clock(), timezone.utc).strftime(_STAMP), **row}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def seen_ids(self) -> set[str]:
        return {r.get("id", "") for r in self.rows()}

    def recent_channels(self, days: float = 3.0) -> dict[str, int]:
        cutoff = datetime.fromtimestamp(self.clock(), timezone.utc) - timedelta(days=days)
        out: dict[str, int] = {}
        for row in self.rows():
            try:
                when = datetime.strptime(row.get("ts", ""), _STAMP).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if when >= cutoff and row.get("channel"):
                key = row["channel"].lower()
                out[key] = out.get(key, 0) + 1
        return out

    def liked_topic(self, threshold: float = 0.6) -> set[str]:
        """Words of the title of the most recent video she liked (what a recommendation should resemble)."""
        for row in reversed(self.rows(30)):
            if float(row.get("liked", 0)) >= threshold:
                return words(row.get("title", "")) | words(row.get("topic", ""))
        return set()


@dataclass
class Scored:
    candidate: Candidate
    score: float
    why: str = ""


def interest_keywords(name: str, entry: dict) -> set[str]:
    keys = {k.lower() for k in TOPIC_KEYWORDS.get(name, ())}
    keys |= {w for w in words(entry.get("about", "")) | words(name.replace("_", " "))}
    return keys


def interest_match(candidate: Candidate, interests: dict) -> tuple[float, str]:
    text = _phrases(candidate)
    tokens = words(text)
    best, best_name = 0.0, ""
    for name, entry in interests.items():
        if name in ("watch_videos",):
            continue
        hits = sum(1 for key in interest_keywords(name, entry) if (key in tokens if " " not in key else key in text))
        if not hits:
            continue
        weight = min(5.0, max(0.1, float(entry.get("weight", 1.0))))
        value = min(hits, 3) / 3 * min(1.0, weight / 2.0)
        if value > best:
            best, best_name = value, name
    return best, best_name


def curiosity_overlap(candidate: Candidate, topics: list[str]) -> float:
    tokens = words(_phrases(candidate))
    best = 0.0
    for topic in topics[:8]:
        topic_words = words(topic)
        if topic_words:
            best = max(best, min(1.0, len(topic_words & tokens) / min(3, len(topic_words))))
    return best


def score(candidate: Candidate, *, interests: dict, curiosity_topics: list[str], seen: set[str],
          channels: dict[str, int], liked_topic: set[str], settings: WatchSettings) -> Scored | None:
    """None = never (an ad, already watched, a short or live stream she does not take)."""
    if candidate.is_ad or candidate.id in seen:
        return None
    if candidate.is_short and not settings.allow_shorts:
        return None
    if candidate.is_live and not settings.allow_live:
        return None
    interest, name = interest_match(candidate, interests)
    curious = curiosity_overlap(candidate, curiosity_topics)
    novelty = 1.0 - min(0.6, 0.3 * channels.get(candidate.channel.lower(), 0))
    follow = 0.0
    if candidate.source == "recommended" and liked_topic:
        follow = min(1.0, len(liked_topic & words(_phrases(candidate))) / 2)
    total = 0.50 * interest + 0.25 * curious + 0.15 * novelty + 0.10 * follow
    limit = settings.max_video_minutes * 60
    if candidate.duration_s and candidate.duration_s > 3 * limit:
        total *= 0.6
    why = ", ".join(p for p in (f"interest {name}" if name else "", "curiosity" if curious else "",
                                "follows a video she liked" if follow else "") if p)
    return Scored(candidate, round(total, 4), why)


def rank(candidates: list[Candidate], **kwargs) -> list[Scored]:
    out = [s for s in (score(c, **kwargs) for c in candidates) if s is not None]
    return sorted(out, key=lambda s: -s.score)


def pick(ranked: list[Scored], settings: WatchSettings, rng: random.Random, *, top: int = 4,
         temperature: float = 0.08) -> Scored | None:
    """A softmax draw among the best few above min_score; None = nothing good enough yet (scroll on)."""
    pool = [s for s in ranked if s.score >= settings.min_score][:top]
    if not pool:
        return None
    best = pool[0].score
    weights = [math.exp((s.score - best) / temperature) for s in pool]
    return rng.choices(pool, weights=weights, k=1)[0]
