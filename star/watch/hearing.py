"""The audio path: star.senses.SensesHub hears all PC audio and transcribes it; this turns what it heard into video lines.

HubHearing.poll(position) returns the speech the hub finished transcribing since the last call, placed on the video's
own clock (the hub runs on its monotonic clock, the player on seconds into the video). state() says whether someone in
the video is talking right now, which the reaction policy uses so she does not talk over the video's speech.
Only the loopback stream is used: the microphone is the room, not the video.
"""
from __future__ import annotations

from .model import AudioState, Line


class HubHearing:
    def __init__(self, hub, *, source: str = "loopback", since: float = float("-inf")) -> None:
        self.hub, self.source = hub, source
        self._since = since
        self._seen_end = since

    def poll(self, position: float) -> list[Line]:
        now = self.hub.clock()
        out = []
        for heard in list(self.hub.lines):
            if heard.source != self.source or heard.end <= self._seen_end or heard.start < self._since:
                continue
            self._seen_end = max(self._seen_end, heard.end)
            out.append(Line(max(0.0, position - (now - heard.start)), heard.text, "heard"))
        return out

    def state(self, position: float) -> AudioState:
        info = self.hub.snapshot().get(self.source)
        if not info:
            return AudioState()
        speaking = info["label"] == "speech" or bool(info.get("partial"))
        return AudioState(info["label"], float(info["level_db"]), speaking)


class FallbackHearing:
    """Switch once from failed live capture to captions; never label missing audio as heard."""

    def __init__(self, hub, fallback, *, since: float):
        self.hub, self.live, self.fallback = hub, HubHearing(hub, since=since), fallback
        self.source, self.mode = self.live, "audio"
        self._position = -1.0

    def _source(self):
        if self.source is self.live:
            try:
                available = getattr(self.hub, "available", lambda: True)
                stopped = getattr(self.hub, "_stop", None)
                if ((stopped is not None and stopped.is_set())
                        or not (available() if callable(available) else available)):
                    raise RuntimeError("live capture unavailable")
            except Exception:
                self._fall_back()
        return self.source

    def _fall_back(self):
        try:
            self.source = self.fallback()
            if self.source is not None:
                self.source.poll(self._position)  # do not replay captions from before capture failed
        except Exception:
            self.source = None
        self.mode = "captions" if self.source is not None else "picture only"

    def poll(self, position: float) -> list[Line]:
        source = self._source()
        try:
            out = source.poll(position) if source is not None else []
        except Exception:
            self._fall_back()
            out = self.source.poll(position) if self.source is not None else []
        self._position = position
        return out

    def state(self, position: float) -> AudioState:
        source = self._source()
        try:
            return source.state(position) if source is not None else AudioState()
        except Exception:
            self._fall_back()
            return self.source.state(position) if self.source is not None else AudioState()
