"""Rate limits for computer use: a person's pace for actions, and no mass messaging.

actions_per_minute     every driver step (click, type, key, scroll, open)
messages_per_hour      messages she sends (Discord DM / reply skills, any step marked as a message)
recipients_per_day     different people she messages in 24 h
same_text_recipients   the same text to more people than this is mass messaging: refused
Over a limit: `Gated` (message limits, recorded for the owner) or `Limited` (the action pace: she waits or stops).
"""
from __future__ import annotations

from collections import deque
import re
import time
from typing import Callable

from .gates import Gated

DEFAULTS = {"actions_per_minute": 60, "messages_per_hour": 30, "recipients_per_day": 20, "same_text_recipients": 2}


class Limited(Exception):
    """Too many actions this minute: wait `retry_after` seconds."""

    def __init__(self, why: str, retry_after: float) -> None:
        super().__init__(why)
        self.retry_after = retry_after


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


class RateLimits:
    def __init__(self, cfg: dict | None = None, clock: Callable[[], float] = time.time) -> None:
        self.cfg = dict(DEFAULTS)
        self.cfg.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS and isinstance(v, int)})
        self.clock = clock
        self._actions: deque[float] = deque()
        self._messages: deque[tuple[float, str, str]] = deque()       # (time, recipient, normalized text)

    def action(self) -> None:
        now = self.clock()
        while self._actions and now - self._actions[0] > 60:
            self._actions.popleft()
        if len(self._actions) >= self.cfg["actions_per_minute"]:
            raise Limited(f"more than {self.cfg['actions_per_minute']} actions in a minute",
                          60 - (now - self._actions[0]))
        self._actions.append(now)

    def message(self, recipient: str, text: str) -> None:
        """Call before sending; records the message when it is allowed."""
        now, who, body = self.clock(), _norm(recipient), _norm(text)
        while self._messages and now - self._messages[0][0] > 86400:
            self._messages.popleft()
        hour = [m for m in self._messages if now - m[0] <= 3600]
        if len(hour) >= self.cfg["messages_per_hour"]:
            raise Gated(f"more than {self.cfg['messages_per_hour']} messages in an hour is mass messaging")
        people = {m[1] for m in self._messages}
        if who not in people and len(people) >= self.cfg["recipients_per_day"]:
            raise Gated(f"messages to more than {self.cfg['recipients_per_day']} different people a day")
        same = {m[1] for m in self._messages if m[2] == body} - {who}
        if body and len(same) >= self.cfg["same_text_recipients"]:
            raise Gated(f"the same text to more than {self.cfg['same_text_recipients']} people is mass messaging")
        self._messages.append((now, who, body))
