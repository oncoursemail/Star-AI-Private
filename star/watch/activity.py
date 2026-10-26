"""The "watch_videos" activity of STAR Home: browse, choose, watch, react, learn; up to a few videos per session.

Parts that live in other processes are plugged in with `configure(...)` by whoever wires star-home to the voice loop:
  hub      a star.senses SensesHub that is already listening to the PC's sound (else captions are used when available)
  speak    speak(text, prosody=None) -> bool: the voice loop's say-queue (False = she is busy talking with someone)
  chat     chat(text): one line into her chat
  brain / vision / browser   overrides (default: the Home brain's chat(); the same chat as vision when config has
                             "vision": true; HostBrowser over the Home executor)
Nothing configured still works in a reduced way: no hub and no captions = she watches by picture only; no speaker =
reactions go to the chat only; no brain = the activity reports failure without touching her browser.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import time
from typing import Callable

from .. import curiosity
from . import captions as caps
from .browser import BrowserError, HostBrowser, VisionScreenReader
from .choose import WatchHistory, pick, rank
from .frames import LiveFrameSampler
from .hearing import HubHearing
from .learn import finish
from .llm import ChatBrain, chat_vision
from .model import Candidate, WatchResult
from .session import WatchSession
from .settings import WatchSettings
from .understand import clock

INTEREST = {"watch_videos": {"weight": 1.0, "about": "watch videos on YouTube, react out loud, and learn from them"}}


@dataclass
class Parts:
    hub: object | None = None
    speak: Callable[..., bool] | None = None
    chat: Callable[[str], None] | None = None
    brain: object | None = None
    vision: Callable | None = None
    browser: object | None = None
    idle_seconds: Callable[[], float] | None = None
    run: Callable | None = None                  # yt-dlp runner (tests)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random | None = None
    mood: Callable[[], str] | None = None
    prosody: Callable[[], dict | None] | None = None


PARTS = Parts()


def configure(**parts) -> Parts:
    """Plug in the other processes' parts (see the module docstring); returns the active Parts."""
    for key, value in parts.items():
        if not hasattr(PARTS, key):
            raise TypeError(f"unknown watch part {key!r}")
        setattr(PARTS, key, value)
    return PARTS


def ensure_interest(life) -> None:
    """Add her `watch_videos` interest to an existing life folder (seed interests only exist for new installs)."""
    if "watch_videos" not in life.interests():
        life.set_interest("watch_videos", INTEREST["watch_videos"]["weight"], INTEREST["watch_videos"]["about"])


def _mood() -> str:
    try:
        from .. import emotion
        return emotion.directive()
    except Exception:
        return ""


def _prosody() -> dict | None:
    try:
        from .. import emotion
        value = emotion.prosody_of(emotion.current())
        if value is None:
            return None
        return value if isinstance(value, dict) else emotion.prosody_dict(value)
    except Exception:
        return None


def _interest_text(interests: dict) -> str:
    ranked = sorted(((v.get("weight", 1.0), k) for k, v in interests.items() if k != "watch_videos"), reverse=True)
    return ", ".join(name.replace("_", " ") for _, name in ranked[:6])


def _query(interests: dict, topics: list[str], rng: random.Random) -> str:
    """A search phrase from her tastes: a curiosity topic's words or one of her weighted interests."""
    if topics and rng.random() < 0.4:
        words_ = [w for w in topics[0].split() if len(w) > 3 and ":" not in w][:5]
        if words_:
            return " ".join(words_)
    names = [k for k in interests if k != "watch_videos"]
    if not names:
        return "how things work"
    name = rng.choices(names, weights=[float(interests[k].get("weight", 1.0)) for k in names], k=1)[0]
    from .choose import TOPIC_KEYWORDS
    keys = TOPIC_KEYWORDS.get(name) or (name.replace("_", " "),)
    return f"{rng.choice(keys)} {'tutorial' if name in ('drawing', 'game_making', 'music') else ''}".strip()


class Chooser:
    """Browse the feed (or a recommendation), scroll like a person, and take the first thing worth watching."""

    def __init__(self, browser, settings: WatchSettings, parts: Parts, ctx, history: WatchHistory, rng: random.Random):
        self.browser, self.settings, self.parts, self.ctx, self.history, self.rng = browser, settings, parts, ctx, history, rng
        self.blind = 0                               # feed reads that returned nothing

    def _kwargs(self) -> dict:
        topics = [i.topic for i in curiosity.ranked(8, paths=(Path(self.ctx.home) / "curiosity.jsonl",))]
        self.topics = topics
        return dict(interests=self.ctx.life.interests(), curiosity_topics=topics, seen=self.history.seen_ids(),
                    channels=self.history.recent_channels(), liked_topic=self.history.liked_topic(),
                    settings=self.settings)

    def choose(self, *, follow: bool) -> Candidate | None:
        kwargs = self._kwargs()
        seen_cards: dict[str, Candidate] = {}
        if not follow:
            self.browser.open_home()
        for step in range(self.settings.browse_scrolls + 1):
            for card in self.browser.feed():
                seen_cards.setdefault(card.id, card)
            ranked = rank(list(seen_cards.values()), **kwargs)
            chosen = pick(ranked, self.settings, self.rng)
            if chosen:
                return chosen.candidate
            if not seen_cards and step >= 1:
                self.blind += 1
                break
            self.browser.scroll()
        if ranked_best := rank(list(seen_cards.values()), **kwargs):
            return ranked_best[0].candidate           # nothing above min_score after scrolling: the best seen
        if self.settings.search_fallback:
            found = caps.search(_query(kwargs["interests"], self.topics, self.rng), run=self.parts.run or caps.default_run)
            chosen = pick(rank(found, **kwargs), self.settings, self.rng) or next(iter(rank(found, **kwargs)), None)
            return chosen.candidate if chosen else None
        return None


def _hearing(parts: Parts, settings: WatchSettings, url: str, workdir: Path):
    if parts.hub is not None:
        return HubHearing(parts.hub), "audio"
    if settings.use_captions and url:
        cues = caps.fetch_captions(url, workdir, run=parts.run or caps.default_run)
        if cues:
            return caps.CaptionHearing(cues), "captions"
    return None, "picture only"


def watch_one(ctx, parts: Parts, settings: WatchSettings, browser, candidate: Candidate, brain, vision,
              history: WatchHistory, session: WatchSession | None, interests: str, deadline: float):
    """Open `candidate`, watch it, learn from it. Returns (WatchResult, Learned, how it was heard)."""
    workdir = Path(ctx.home) / "watch" / "work"
    clk = parts.clock
    browser.open_candidate(candidate)
    url = candidate.url or (browser.ensure_url() if hasattr(browser, "ensure_url") else "")
    meta = caps.fetch_metadata(url, run=parts.run or caps.default_run) if (url and settings.use_captions) else {}
    hearing, how = _hearing(parts, settings, url, workdir)
    sampler = LiveFrameSampler(workdir / "frames", keep=settings.keep_frames)
    watcher = WatchSession(
        browser=browser, hearing=hearing, brain=brain, vision=vision, speak=parts.speak, chat=parts.chat,
        settings=settings, sampler=sampler, mood=parts.mood or _mood, prosody=parts.prosody or _prosody,
        interests=interests, clock=clk, sleep=parts.sleep, rng=parts.rng,
        should_stop=lambda: _stopped(ctx.home))
    if session is not None:                           # keep the reaction budget across the videos of one session
        watcher.policy = session.policy
    result = watcher.watch(title=candidate.title or meta.get("title", ""), channel=candidate.channel or meta.get("channel", ""),
                           description=meta.get("description", "") or candidate.description, chapters=meta.get("chapters"),
                           max_seconds=max(60.0, deadline - clk()))
    result.url = result.url or url
    sampler.clear()
    learned = finish(result, brain, home=Path(ctx.home), life=ctx.life, history=history)
    return result, learned, how, watcher


def _stopped(home) -> bool:
    try:
        from ..home import control
        return control.stopped(Path(home))
    except Exception:
        return False


def idle_seconds() -> float:  # pragma: no cover - Windows only
    import ctypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def run(ctx, parts: Parts | None = None) -> dict:
    parts = parts or PARTS
    settings = WatchSettings.load(ctx.home)
    fail = lambda why: {"ok": False, "verified": False, "summary": why, "evidence": [], "failures": [f"watch_videos: {why}"]}  # noqa: E731
    if not settings.enabled:
        return fail("watching videos is switched off in watch/settings.json")
    if settings.only_when_owner_idle_s > 0:
        idle = (parts.idle_seconds or idle_seconds)()
        if idle < settings.only_when_owner_idle_s:
            return fail(f"the owner used the PC {int(idle)} s ago; not taking over the screen")
    brain = parts.brain or (ChatBrain(ctx.chat) if ctx.chat else None)
    if brain is None:
        return fail("no brain connection")
    vision = parts.vision or (chat_vision(ctx.chat) if ctx.chat and ctx.config.get("vision") else None)
    rng = parts.rng or random.Random()
    browser = parts.browser or HostBrowser(ctx.executor, VisionScreenReader(vision) if vision else None,
                                           resync_s=settings.resync_s, rng=rng)
    history = WatchHistory(ctx.home)
    chooser = Chooser(browser, settings, parts, ctx, history, rng)
    interests = _interest_text(ctx.life.interests())
    started = parts.clock()
    deadline = started + settings.session_minutes * 60
    done: list[tuple[WatchResult, object, str]] = []
    follow = False
    session = None
    try:
        while len(done) < settings.max_videos_per_session and parts.clock() < deadline - 60 and not _stopped(ctx.home):
            candidate = chooser.choose(follow=follow)
            if candidate is None:
                break
            result, learned, how, watcher = watch_one(ctx, parts, settings, browser, candidate, brain, vision, history,
                                                      session, interests, deadline)
            session = watcher
            done.append((result, learned, how))
            follow = learned.liked >= 0.6 and not chooser.blind     # a good one: look at what is recommended next
    except BrowserError as why:
        if not done:
            return fail(f"the browser step failed: {why}")
    if not done:
        return fail("no video found to watch" + (" (could not read the feed on screen)" if chooser.blind else ""))
    parts_text, evidence = [], []
    for result, learned, how in done:
        parts_text.append(f"'{result.title[:60]}' ({clock(result.watched_s)}, {how}, {len(result.reactions)} reactions, "
                          f"{len(learned.facts)} facts" + (f", goal {learned.goal['id']}" if learned.goal else "") + ")")
        evidence += [result.url] + [f"note {n}" for n in learned.note_ids[:3]]
    verified = any(l.note_ids and (r.lines or r.frames) for r, l, _ in done)
    return {"ok": True, "verified": verified, "evidence": [e for e in evidence if e][:10],
            "summary": "watched " + "; ".join(parts_text), "goal_done": False}


def register_home_activities(registry) -> None:
    registry.register("watch_videos", "watch_videos", run,
                      "watch YouTube and other videos in her own browser, react out loud, and learn", needs_brain=True)
