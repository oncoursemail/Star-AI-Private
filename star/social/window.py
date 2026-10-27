"""Conversation-window checks W1-W10 (docs/research/human-texting-20261027.md section 9.3): what a run of her messages
in one channel looks like, not one message. `StyleWindow.review()` adjusts a draft that would extend a robotic pattern;
`hints()` gives the model a one-line nudge for the NEXT message. Pure bookkeeping, no I/O, no model.

W1 question-ending ratio over 35 % or two "?" endings in a row   -> the trailing question is dropped (when something is left)
W2 length uniformity (stdev under 25 % of the mean over 6)         -> a long draft is cut to its first sentence; hint for variety
W3 same opener word in 3 of the last 5                             -> the opener is dropped
W4 emoji in more than 25 % of messages                             -> emoji removed
W5 every message capitalised and full-stopped                      -> lowercase start and no final period
W6 she answered every one of the last 10 incoming messages         -> `silence_ok` (a reaction or silence is fine next)
W7 the other person's name in every message                        -> the name is dropped
W8 near-duplicate line within 10 minutes (6+ words)                -> flagged on the review (the adapters' Pacer blocks exact repeats)
W9 constant reply latency over the last 5                          -> see pacing.Jitter (jitter added there)
W10 no message under 15 characters in the last 8                   -> a long draft is cut to its first sentence; hint for a short ack
"""
from __future__ import annotations

import re
import statistics
import time
from collections import deque
from dataclasses import dataclass, field

from . import style

SIZE = 12
QUESTION_RATIO = 0.35
EMOJI_RATIO = 0.25
DUPLICATE_WINDOW_S = 600.0
_OPENERS = {"oh", "haha", "wait", "lol", "omg", "aww", "ok", "okay", "yeah", "hmm", "ooh", "wow", "hey", "honestly"}


@dataclass
class Review:
    text: str
    notes: list[str] = field(default_factory=list)
    silence_ok: bool = False
    duplicate: bool = False        # W8: a near-duplicate of a line she sent in the last 10 minutes (the text is kept)


def _opener(text: str) -> str:
    m = re.match(r"[A-Za-z']+", text.strip().lower())
    return m.group(0) if m else ""


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _first_sentence(text: str) -> str:
    parts = style.sentences(text)
    return parts[0] if parts else text


def _is_perfect(text: str) -> bool:
    t = text.strip()
    return bool(t) and t[0].isupper() and t[-1] in ".!?" and len(t) > 25


class StyleWindow:
    def __init__(self, *, clock=time.time, size: int = SIZE) -> None:
        self._clock = clock
        self._size = size
        self._sent: dict[str, deque[tuple[float, str]]] = {}
        self._streak: dict[str, int] = {}

    def _hist(self, channel: str) -> deque:
        return self._sent.setdefault(channel, deque(maxlen=self._size))

    def sent(self, channel: str, text: str, now: float | None = None) -> None:
        """Record a message she sent (all lines of a burst together) and that she answered."""
        self._hist(channel).append((self._clock() if now is None else now, text))
        self._streak[channel] = self._streak.get(channel, 0) + 1

    def skipped(self, channel: str) -> None:
        """She chose a reaction or silence for an incoming message: the answer-everything streak ends."""
        self._streak[channel] = 0

    def recent(self, channel: str, n: int) -> list[str]:
        return [t for _, t in list(self._hist(channel))[-n:]]

    # -- the checks as predicates over the recent messages -----------------------------------------------------------
    def question_heavy(self, channel: str) -> bool:
        last = self.recent(channel, self._size)
        if not last:
            return False
        ends = [m.rstrip().endswith("?") for m in last]
        two_in_a_row = len(ends) >= 2 and ends[-1] and ends[-2]
        return bool(two_in_a_row or (len(last) >= 3 and sum(ends) / len(ends) > QUESTION_RATIO))

    def uniform_length(self, channel: str) -> bool:
        last = [len(t) for t in self.recent(channel, 6)]
        if len(last) < 6:
            return False
        mean = statistics.mean(last)
        return mean > 0 and statistics.pstdev(last) < 0.25 * mean

    def repeated_opener(self, channel: str) -> str:
        last = [_opener(t) for t in self.recent(channel, 5)]
        for word in set(last):
            if word in _OPENERS and last.count(word) >= 3:
                return word
        return ""

    def emoji_heavy(self, channel: str) -> bool:
        last = self.recent(channel, self._size)
        return len(last) >= 4 and sum(1 for t in last if style.emojis(t)) / len(last) > EMOJI_RATIO

    def perfect_grammar(self, channel: str) -> bool:
        last = self.recent(channel, 6)
        return len(last) >= 6 and all(_is_perfect(t) for t in last)

    def answered_everything(self, channel: str) -> bool:
        return self._streak.get(channel, 0) >= 10

    def always_named(self, channel: str, name: str) -> bool:
        last = self.recent(channel, 4)
        return bool(name) and len(last) >= 4 and all(re.search(rf"\b{re.escape(name)}\b", t, re.I) for t in last)

    def no_short_message(self, channel: str) -> bool:
        last = self.recent(channel, 8)
        return len(last) >= 8 and min(len(t) for t in last) >= 15

    def near_duplicate(self, channel: str, text: str, now: float) -> bool:
        mine = _tokens(text)
        if len(mine) < 6:                      # short lines ("lol", "same", "sounds good") repeat naturally
            return False
        for ts, old in self._hist(channel):
            if now - ts <= DUPLICATE_WINDOW_S:
                theirs = _tokens(old)
                if theirs and len(mine & theirs) / len(mine | theirs) >= 0.8:
                    return True
        return False

    # -- apply --------------------------------------------------------------------------------------------------------
    def review(self, channel: str, draft: str, *, name: str = "", now: float | None = None) -> Review:
        now = self._clock() if now is None else now
        text, notes = " ".join(str(draft or "").split()), []
        if not text:
            return Review("", notes)
        opener = self.repeated_opener(channel)
        if opener and _opener(text) == opener:
            rest = re.sub(rf"^\W*{re.escape(opener)}\b[\s,.!:-]*", "", text, count=1, flags=re.I).strip()
            if rest:
                text = rest
                notes.append(f"W3 dropped the repeated opener {opener!r}")
        if self.emoji_heavy(channel) and style.emojis(text):
            text = " ".join(_strip_emoji(text).split())
            notes.append("W4 emoji removed (too many lately)")
        if self.question_heavy(channel) and text.rstrip().endswith("?"):
            parts = style.sentences(text)
            if len(parts) > 1:
                text = " ".join(parts[:-1])
                notes.append("W1 dropped the trailing question")
        if (self.uniform_length(channel) or self.no_short_message(channel)) and len(style.sentences(text)) > 1:
            text = _first_sentence(text)
            notes.append("W2/W10 cut to the first sentence for variety")
        if self.always_named(channel, name) and re.search(rf"\b{re.escape(name)}\b", text, re.I):
            cleaned = re.sub(rf",?\s*\b{re.escape(name)}\b[,!]?", "", text, count=1, flags=re.I).strip(" ,")
            if cleaned:
                text = cleaned
                notes.append("W7 dropped the name")
        if self.perfect_grammar(channel) and _is_perfect(text):
            text = style.drop_final_period(style.lowercase_start(text))
            notes.append("W5 relaxed capital and full stop")
        duplicate = self.near_duplicate(channel, text, now)
        if duplicate:
            notes.append("W8 near-duplicate of a recent line")
        return Review(text, notes, self.answered_everything(channel), duplicate)

    def hints(self, channel: str) -> str:
        """A one-line nudge for the next message ("" when her recent messages look fine)."""
        tips = []
        if self.question_heavy(channel):
            tips.append("no question this time")
        if self.no_short_message(channel):
            tips.append("a very short reply, a few words")
        elif self.uniform_length(channel):
            tips.append("vary the length: much shorter or a little longer than usual")
        word = self.repeated_opener(channel)
        if word:
            tips.append(f"do not start with '{word}'")
        return f"({'; '.join(tips)})" if tips else ""


def _strip_emoji(text: str) -> str:
    return style._EMOJI.sub("", text)
