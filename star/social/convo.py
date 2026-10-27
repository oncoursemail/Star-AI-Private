"""Chatting like a player: short lines, taking turns, group awareness, asking back, knowing when to leave.

shape_reply()  one reply cut to chat size: no lists or walls of text, at most one question, an emoji like a player
               types (none in Minecraft, whose chat cannot show them)
ChatFlow       per channel: who spoke, whether a line is for her (her name, a reply to something she just said, a
               question in a small group), when to stay out of a group, when to stop talking and leave, a goodbye
               line, and when to turn the conversation around with a question
"""
from __future__ import annotations

import random
import re
import time
from collections import deque
from dataclasses import dataclass, field

# A casual goodbye (not the "I'm leaving for good" the emotion engine reads itself): she misses them a little.
GOODBYE = re.compile(r"\b(?:bye(?:\s?bye)?|goodbye|good\s?night|gtg|g2g|gotta\s+go|got\s+to\s+go|i\s+(?:have|need)\s+to\s+go|"
                     r"i'?m\s+(?:heading\s+(?:out|off)|logging\s+off|off\s+to\s+(?:bed|sleep))|"
                     r"(?:talk|speak|catch)\s+(?:to\s+you\s+|you\s+)?(?:later|tomorrow|soon)|ttyl|cya|see\s+(?:you|ya)\s*(?:later|tomorrow|soon)?)\b",
                     re.I)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿❤️]")
_LIST = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
_MARKUP = re.compile(r"\*\*|`+|^#+\s*|^>\s*", re.M)         # bold, code, headers, quotes (a *role-play action* stays)
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_WARM = re.compile(r"\b(?:haha+|lol|lmao|love|nice|awesome|yay|great|amazing|fun|congrats|glad)\b", re.I)
_QUESTION_TO_ALL = re.compile(r"\b(?:anyone|anybody|who(?:'s|\s+is)?\s+(?:wants?|wanna|down|here)|does\s+anyone|any\s+one)\b", re.I)
_TO_SOMEONE = re.compile(r"^\s*@?([A-Za-z0-9_]{3,20})\s*[,:]")
LINE_CHARS = {"discord": 400, "minecraft": 110, "roblox": 110}
MAX_SENTENCES = {"discord": 3, "minecraft": 2, "roblox": 2}
FOLLOWUP_WINDOW_S = 90.0         # a line from the person she just spoke to counts as for her even without her name
GROUP_SPEAKERS = 3               # this many speakers in the last five minutes = a group
QUIET_LEAVE_S = 10 * 60          # nobody answered her for this long: the conversation is over
ASK_BACK_EVERY = 3               # she has not asked anything for this many replies: a question back is due


def shape_reply(text: str, platform: str, *, rng: random.Random | None = None, emoji_chance: float = 0.05) -> str:
    """One reply the way a player types it."""
    rng = rng or random.Random()
    text = _LIST.sub("", str(text or ""))
    text = " ".join(_MARKUP.sub("", text).split())
    if platform == "minecraft":
        text = " ".join(_EMOJI.sub("", text).split())          # Minecraft chat shows emoji as boxes
    sentences = [s for s in _SENTENCE.split(text) if s]
    questions = [s for s in sentences if s.rstrip().endswith("?")]
    if len(questions) > 1:                                      # one question at a time
        last = questions[-1]
        sentences = [s for s in sentences if s not in questions] + [last]
    sentences = sentences[: MAX_SENTENCES.get(platform, 3)]
    limit = LINE_CHARS.get(platform, 400)
    out, size = [], 0
    for s in sentences:
        if size + len(s) > limit and out:
            break
        out.append(s)
        size += len(s) + 1
    text = " ".join(out) if out else text[:limit]
    if len(text) > limit:
        cut = text.rfind(" ", 0, limit - 1)
        text = text[: cut if cut > limit // 2 else limit - 1].rstrip(" ,;") + "…"
    if platform != "minecraft" and text and not _EMOJI.search(text) and _WARM.search(text) and rng.random() < emoji_chance:
        text += " " + rng.choice(("\U0001F604", "\U0001F602", "✨", "\U0001F64C"))
    return text


@dataclass
class _Channel:
    lines: deque = field(default_factory=lambda: deque(maxlen=40))     # (ts, author, text); author "" = herself
    last_spoke: float = 0.0
    last_to: str = ""
    unanswered: int = 0
    replies_since_question: int = 0


class ChatFlow:
    def __init__(self, *, my_names: list[str] | None = None, clock=time.time, rng: random.Random | None = None) -> None:
        self.my_names = [n.lower() for n in (my_names or ["Star"])]
        self._clock = clock
        self._rng = rng or random.Random()
        self._channels: dict[str, _Channel] = {}

    def _chan(self, channel: str) -> _Channel:
        return self._channels.setdefault(channel, _Channel())

    def hear(self, channel: str, author: str, text: str, now: float | None = None) -> None:
        """Every line she can see in a channel (also the ones not meant for her)."""
        now = self._clock() if now is None else now
        c = self._chan(channel)
        if any(a == author.lower() and t == text for _, a, t in list(c.lines)[-3:]):
            return                                              # the adapter and the chat both report the same line
        c.lines.append((now, author.lower(), text))
        c.unanswered = 0

    def spoke(self, channel: str, to: str, text: str, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        c = self._chan(channel)
        c.lines.append((now, "", text))
        c.last_spoke, c.last_to = now, to.lower()
        c.unanswered += 1
        c.replies_since_question = 0 if text.rstrip().endswith("?") else c.replies_since_question + 1

    def speakers(self, channel: str, now: float | None = None, window: float = 300.0) -> set[str]:
        now = self._clock() if now is None else now
        return {a for ts, a, _ in self._chan(channel).lines if a and now - ts <= window}

    def is_group(self, channel: str, now: float | None = None) -> bool:
        return len(self.speakers(channel, now)) >= GROUP_SPEAKERS

    def named(self, text: str) -> bool:
        return any(re.search(rf"\b{re.escape(n)}\b", text.lower()) for n in self.my_names)

    def for_her(self, channel: str, author: str, text: str, now: float | None = None) -> tuple[bool, str]:
        """Is this line meant for her, and why. Call after hear(). Group-aware: she stays out of talk between others."""
        now = self._clock() if now is None else now
        c, author = self._chan(channel), author.lower()
        if self.named(text):
            return True, "named"
        target = _TO_SOMEONE.match(text)
        if target and target.group(1).lower() not in self.my_names and target.group(1).lower() in self.speakers(channel, now, 1800):
            return False, "talking to someone else"
        group = self.is_group(channel, now)
        if c.last_to == author and now - c.last_spoke <= FOLLOWUP_WINDOW_S:
            others = [a for ts, a, _ in c.lines if a and a != author and ts > c.last_spoke]
            if not others or not group:
                return True, "answering her"
        if group:
            if _QUESTION_TO_ALL.search(text) and self._rng.random() < 0.3:
                return True, "question to everybody"
            return False, "group chat, not addressed"
        if text.rstrip().endswith("?"):
            return True, "question in a small chat"
        return False, "not addressed"

    def may_speak_in_group(self, channel: str) -> bool:
        """Never dominate: not when she wrote most of the last few lines."""
        recent = list(self._chan(channel).lines)[-5:]
        return sum(1 for _, a, _ in recent if a == "") < 3

    def ask_back_due(self, channel: str) -> bool:
        return self._chan(channel).replies_since_question >= ASK_BACK_EVERY

    def leave_reason(self, channel: str, now: float | None = None, *, busy: bool = False) -> str:
        """Why she should stop talking in this channel now ('' = keep going)."""
        now = self._clock() if now is None else now
        c = self._chan(channel)
        humans = [(ts, t) for ts, a, t in c.lines if a]
        last_human = humans[-1][0] if humans else 0.0
        if humans and GOODBYE.search(humans[-1][1]):
            return "they said goodbye"
        if c.unanswered >= 2 and now - c.last_spoke >= 90:
            return "nobody answered her"
        if c.last_spoke and now - max(last_human, c.last_spoke) >= QUIET_LEAVE_S:
            return "the conversation went quiet"
        if busy and c.last_spoke:
            return "she has something else to do"
        return ""

    def goodbye_line(self, nickname: str = "", stage: str = "met", exchanged: int = 0) -> str:
        """A short goodbye; '' when the chat was too short to need one (she just slips away)."""
        if exchanged < 2:
            return ""
        name = f" {nickname}" if nickname else ""
        if stage in ("friend", "close_friend"):
            return self._rng.choice((f"gtg{name}, was fun!", f"ok i'm heading off{name}, talk later!", f"see you around{name} \U0001F44B"))
        return self._rng.choice(("gtg, was fun!", "ok bye for now!", "heading off, take care!"))

    def forget_person(self, author: str) -> None:
        """Forget-me: drop what this person said from her short-term view of every channel."""
        author = author.lower()
        for c in self._channels.values():
            c.lines = deque(((ts, a, t) for ts, a, t in c.lines if a != author), maxlen=40)
            if c.last_to == author:
                c.last_to = ""
