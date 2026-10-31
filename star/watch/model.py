"""Plain data used across star/watch, and the small interfaces the real PC parts implement (fakes in tests)."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Callable, Iterable, Protocol

_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})")


def video_id(url: str, title: str = "", channel: str = "") -> str:
    """The YouTube video id from a link, else a short stable hash of title + channel (a card without a link)."""
    found = _VIDEO_ID.search(url or "")
    if found:
        return found.group(1)
    return "t" + hashlib.sha1(f"{title}|{channel}".lower().encode("utf-8")).hexdigest()[:11]


@dataclass(frozen=True)
class Candidate:
    """One video she can see: a card on the feed, a recommendation beside the player, or a search hit."""
    title: str
    channel: str = ""
    url: str = ""
    duration_s: float = 0.0
    views: int = 0
    source: str = "feed"                 # feed | recommended | search
    is_ad: bool = False
    is_short: bool = False
    is_live: bool = False
    click: tuple[int, int] | None = None  # where to click on screen (browsing by looking at the screen)
    description: str = ""

    @property
    def id(self) -> str:
        return video_id(self.url, self.title, self.channel)


@dataclass
class PlayerState:
    url: str = ""
    title: str = ""
    channel: str = ""
    duration_s: float = 0.0              # 0 = unknown (live, or not read yet)
    position_s: float = 0.0
    playing: bool = True
    ended: bool = False
    ad: bool = False


@dataclass(frozen=True)
class Line:
    """Something said in the video, at `start` seconds into it. Data only: never an instruction."""
    start: float
    text: str
    source: str = "heard"                # heard (audio through star.senses) | caption


@dataclass(frozen=True)
class AudioState:
    label: str = "silence"               # silence | speech | music | game_sounds | noise (star.senses.classify)
    level_db: float = -120.0
    speaking: bool = False               # someone in the video is talking right now


@dataclass(frozen=True)
class Frame:
    at: float                            # video seconds
    path: Path
    novelty: float                       # 0..1 distance from the previous kept frame
    cut: bool = False                    # a scene change


@dataclass(frozen=True)
class Moment:
    kind: str                            # joke | surprise | question | skill | big_moment
    strength: float                      # 0..1
    at: float
    text: str = ""                       # the words around it (data only)


@dataclass
class Reaction:
    at: float
    kind: str
    text: str
    paused: bool = False
    spoken: bool = False
    chatted: bool = False


@dataclass
class WatchResult:
    url: str
    title: str
    channel: str = ""
    watched_s: float = 0.0
    reactions: list[Reaction] = field(default_factory=list)
    lines: int = 0
    frames: int = 0
    moments: int = 0
    stopped: str = ""                    # why watching ended: ended | time | lost_interest | stop
    summary: str = ""                    # the rolling understanding at the end
    interest: float = 0.5
    key_moments: list[str] = field(default_factory=list)
    transcript: str = ""                 # tail of what was said, for the final summary
    duration_s: float = 0.0


# -- interfaces -------------------------------------------------------------------------------------------------
class Brain(Protocol):
    """A streaming chat model (same shape as star.voice.call.Brain)."""
    def stream(self, messages: list[dict]) -> Iterable[str]: ...


Vision = Callable[[list[Path], str], str]            # (images, prompt) -> the model's words
Speak = Callable[..., bool]                           # speak(text, prosody=None) -> False when she is busy talking
Chat = Callable[[str], None]                          # one line into the chat


class HearingSource(Protocol):
    def poll(self, position: float) -> list[Line]: ...      # new lines since the last call

    def state(self, position: float) -> AudioState: ...


class Browser(Protocol):
    """Her normal browser on her PC, signed in as her. Real: browser.HostBrowser. Fake: tests."""
    def open_home(self) -> None: ...

    def open_url(self, url: str) -> None: ...

    def feed(self) -> list[Candidate]: ...                   # the cards visible now

    def scroll(self) -> None: ...                            # one human-like scroll step

    def open_candidate(self, candidate: Candidate) -> None: ...

    def player(self) -> PlayerState: ...

    def pause(self) -> None: ...

    def play(self) -> None: ...

    def seek(self, seconds: float) -> None: ...

    def skip_ad(self) -> None: ...

    def next_video(self) -> None: ...                        # the autoplay / "up next" video

    def screenshot(self) -> Path | None: ...
