"""The audio path: star.senses.SensesHub hears all PC audio and transcribes it; this turns what it heard into video lines.

HubHearing.poll(position) returns the speech the hub finished transcribing since the last call, placed on the video's
own clock (the hub runs on its monotonic clock, the player on seconds into the video). state() says whether someone in
the video is talking right now, which the reaction policy uses so she does not talk over the video's speech.
Only the loopback stream is used: the microphone is the room, not the video.
"""
from __future__ import annotations

from .model import AudioState, Line


class HubHearing:
    def __init__(self, hub, *, source: str = "loopback") -> None:
        self.hub, self.source = hub, source
        self._seen_end = float("-inf")

    def poll(self, position: float) -> list[Line]:
        now = self.hub.clock()
        out = []
        for heard in list(self.hub.lines):
            if heard.source != self.source or heard.end <= self._seen_end:
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
