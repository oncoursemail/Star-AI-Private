"""Discord reactions: when a reaction is the right answer, which emoji, and how often (research section 10).

`ReactionPolicy.decide()` returns one of: reply (words needed), react (emoji only), react_then_reply (a nod first), ignore.
Hearts are allowed. The meaning map is informal convention, the server's own custom emoji win when it has one for the
feeling. Budget: at most 1 reaction per 5 messages in a channel, at most 2 emoji on one message, never on the same
person's last 3 messages in a row, never more than the channel's top regular. Never: blocked or muted people, sad or
serious messages with a laughing/skull/fire emoji, bullying, romantic messages from anyone who may be a minor, mod
announcements. The avoid list (thumbs up, slightly smiling face, plain check mark) is never used in chat.
It decides only; doing the click in the app is the adapter's `react` hook (not verified on the real Discord UI).
"""
from __future__ import annotations

import random
import re
import time
from collections import deque
from dataclasses import dataclass

from . import rules

AVOID = {"\U0001F44D", "\U0001F642", "✔️", "✔", "✅", "☑️", "\U0001F44C"}   # thumbs up, slight smile, checks, ok
BUDGET_MESSAGES = 5
MAX_EMOJI_PER_MESSAGE = 2

# feeling -> emoji choices (hearts, hugging, skull for funny, crying only for cute, sparkles for wins, eyes for "tell me more")
MEANING = {
    "sweet": ("❤️", "\U0001F495", "\U0001F970", "\U0001F917"),
    "funny": ("\U0001F480", "\U0001F602"),
    "cute": ("\U0001F62D", "\U0001F970", "❤️"),
    "win": ("✨", "\U0001F64C"),
    "hype": ("\U0001F525", "\U0001F4AF"),
    "intrigue": ("\U0001F440",),
    "support": ("\U0001F97A", "\U0001F917", "❤️"),
    "goodnight": ("\U0001F319", "❤️"),
    "brb": ("\U0001F44B",),
}
_FUNNY = re.compile(r"\b(?:lol|lmao|lmfao|rofl|haha+|hehe+|bruh|cursed|i'?m\s+dead|dying)\b|[\U0001F602\U0001F923\U0001F480]", re.I)
_SWEET = re.compile(r"\b(?:thanks?|thank\s+you|thx|ty|aww+|love\s+you|miss\s+you|appreciate)\b|[❤\U0001F495\U0001F970]", re.I)
_CUTE = re.compile(r"\b(?:so\s+cute|too\s+cute|adorable|my\s+(?:cat|dog)|puppy|kitten)\b", re.I)
_WIN = re.compile(r"\b(?:i\s+(?:got|passed|finished|beat|made|won)|got\s+the\s+(?:job|role)|promotion|new\s+record|finally\s+(?:beat|finished))\b", re.I)
_HYPE = re.compile(r"\b(?:clutch|insane\s+play|let'?s\s+go+|poggers|W\b|gg|ace)\b", re.I)
_INTRIGUE = re.compile(r"\b(?:guess\s+what|you\s+won'?t\s+believe|plot\s+twist|so\s+i\s+heard|spill|tea)\b", re.I)
_GOODNIGHT = re.compile(r"\b(?:gn|good\s?night|night\s+(?:all|everyone|guys)|going\s+to\s+(?:bed|sleep))\b", re.I)
_BRB = re.compile(r"\b(?:brb|be\s+right\s+back|afk|back\s+in\s+a\s+bit)\b", re.I)
_SAD = re.compile(r"\b(?:sad|depress\w*|cry\w*|lonely|hurt\w*|died|passed\s+away|broke\s+up|breakup|anxious|panic\w*|hate\s+myself|"
                  r"give\s+up|can'?t\s+do\s+this|so\s+tired|stressed|funeral|sick|scared|abuse\w*|kill\s+myself|kms)\b|[\U0001F622\U0001F62D\U0001F494]", re.I)
_BULLY = re.compile(r"\b(?:loser|ugly|stupid|idiot|kys|noob|trash|shut\s+up|nobody\s+likes\s+you|you\s+suck)\b", re.I)
_QUESTION = re.compile(r"\?\s*$|\b(?:can|could|would|will)\s+you\b|\bwanna\b|\bhelp\b|\bplease\b", re.I)
_AMBIGUOUS = re.compile(r"\b(?:jk|just\s+kidding|joking|kidding|/s)\b", re.I)
_ANNOUNCE = re.compile(r"@everyone|@here|\bannouncement\b|\bserver\s+(?:rules|update)\b", re.I)


@dataclass(frozen=True)
class ReactionDecision:
    action: str                    # reply | react | react_then_reply | ignore
    emoji: str = ""
    delay_s: float = 0.0
    reason: str = ""


def classify(text: str) -> str:
    """The feeling a message carries: sad, bully, announce, question, goodnight, brb, ambiguous, funny, cute, win, hype,
    intrigue, sweet, or "" (nothing in particular)."""
    t = text or ""
    if _SAD.search(t):
        return "sad"
    if _ANNOUNCE.search(t):
        return "announce"
    if _BULLY.search(t):
        return "bully"
    if _FUNNY.search(t) and (_AMBIGUOUS.search(t) or re.search(r"\b(?:done\s+with|hate|worst|so\s+tired)\b", t, re.I)):
        return "ambiguous"
    if _QUESTION.search(t):
        return "question"
    if _GOODNIGHT.search(t):
        return "goodnight"
    if _BRB.search(t):
        return "brb"
    for name, pattern in (("funny", _FUNNY), ("cute", _CUTE), ("win", _WIN), ("hype", _HYPE), ("intrigue", _INTRIGUE), ("sweet", _SWEET)):
        if pattern.search(t):
            return name
    return ""


class ReactionPolicy:
    def __init__(self, *, rng: random.Random | None = None, clock=time.time, server_emoji: dict[str, str] | None = None,
                 budget_messages: int = BUDGET_MESSAGES) -> None:
        self._rng = rng or random.Random()
        self._clock = clock
        self.server_emoji = dict(server_emoji or {})         # feeling -> the server's own emoji ("funny": ":kekw:")
        self.budget_messages = budget_messages
        self._recent: dict[str, deque[bool]] = {}            # per channel: did she react to each of the last messages
        self._by_author: dict[tuple[str, str], deque[bool]] = {}
        self._count: dict[str, int] = {}

    def _budget_free(self, channel: str) -> bool:
        window = list(self._recent.get(channel, deque()))[-(self.budget_messages - 1):] if self.budget_messages > 1 else []
        return not any(window)

    def _author_streak(self, channel: str, author: str) -> bool:
        last = self._by_author.get((channel, author.lower()), deque())
        return len(last) >= 3 and all(list(last)[-3:])

    def _record(self, channel: str, author: str, reacted: bool) -> None:
        self._recent.setdefault(channel, deque(maxlen=20)).append(reacted)
        self._by_author.setdefault((channel, author.lower()), deque(maxlen=5)).append(reacted)
        if reacted:
            self._count[channel] = self._count.get(channel, 0) + 1

    def _pick(self, feeling: str, existing: dict[str, int]) -> str:
        if feeling in self.server_emoji:
            return self.server_emoji[feeling]
        choices = [e for e in MEANING.get(feeling, ()) if e not in AVOID]
        joined = [e for e in choices if existing.get(e, 0) >= 1]
        return self._rng.choice(joined or choices) if choices else ""

    def decide(self, channel: str, author: str, text: str, *, addressed: bool = False, person=None, age_status: str = "unknown",
               existing: dict[str, int] | None = None, mine_on_message: int = 0, top_regular_reactions: int | None = None,
               task_context: bool = False) -> ReactionDecision:
        """What to do with one message. `existing` = the emoji already on it and how many people added each;
        `mine_on_message` = emoji she already put on it; `person` = friend memory's Person (blocked/muted) or None."""
        existing = existing or {}
        out = self._decide(channel, author, text, addressed, person, age_status, existing, mine_on_message,
                           top_regular_reactions)
        self._record(channel, author, out.action in ("react", "react_then_reply"))
        return out

    def _decide(self, channel, author, text, addressed, person, age_status, existing, mine_on_message, top_regular) -> ReactionDecision:
        if person is not None and (getattr(person, "blocked", False) or getattr(person, "muted", False)):
            return ReactionDecision("ignore", reason="blocked or muted")
        feeling = classify(text)
        if feeling == "announce":
            return ReactionDecision("ignore", reason="a moderator announcement")
        if feeling == "bully":
            return ReactionDecision("ignore", reason="someone is being mocked: she stays out")
        if feeling == "sad":
            return ReactionDecision("reply" if addressed else "ignore",
                                    reason="serious: words, not an emoji" if addressed else "serious and not for her")
        if rules.ROMANTIC.search(text or "") and age_status != "adult":
            return ReactionDecision("ignore", reason="romantic and the person is or may be a minor")
        if feeling == "question" or (addressed and not feeling):
            return ReactionDecision("reply", reason="needs words")
        if not feeling and not addressed:
            return ReactionDecision("ignore", reason="nothing to say to it")
        # Can she react at all? budget, per-message cap, same-person streak, top regular.
        if mine_on_message + 1 > MAX_EMOJI_PER_MESSAGE:
            return ReactionDecision("reply" if addressed else "ignore", reason="already two emoji of hers on it")
        if not self._budget_free(channel):
            return ReactionDecision("reply" if addressed and feeling not in ("goodnight", "brb") else "ignore",
                                    reason="reaction budget: one per five messages")
        if self._author_streak(channel, author):
            return ReactionDecision("reply" if addressed else "ignore", reason="not a fourth reaction in a row to the same person")
        if top_regular is not None and self._count.get(channel, 0) >= top_regular:
            return ReactionDecision("reply" if addressed else "ignore", reason="more reactions than the top regular")
        # Joining an emoji others already put there (2+ of the same) is the most natural reaction.
        popular = [e for e, n in existing.items() if n >= 2 and e not in AVOID]
        if popular and not addressed:
            return ReactionDecision("react", popular[0], self._rng.uniform(1.0, 5.0), "joined an emoji others already used")
        if feeling == "ambiguous":
            return ReactionDecision("react", self.server_emoji.get("intrigue", "\U0001F440"), self._rng.uniform(1.0, 5.0),
                                    "cannot tell if it is a joke: eyes, not a skull")
        emoji = self._pick(feeling, existing)
        if not emoji:
            return ReactionDecision("reply" if addressed else "ignore", reason="no fitting emoji")
        delay = self._rng.uniform(1.0, 5.0) if len(text or "") <= 140 else self._rng.uniform(5.0, 20.0)
        if feeling in ("goodnight", "brb"):
            return ReactionDecision("react", emoji if feeling == "goodnight" else self.server_emoji.get("brb", "👋"),
                                    delay, "no reply needed, a nod is enough")
        if addressed and feeling in ("sweet", "win", "cute", "support", "intrigue"):
            return ReactionDecision("react_then_reply", emoji, delay, "small or emotional, aimed at her: a nod, then words")
        if addressed:
            return ReactionDecision("reply", reason="aimed at her: words")
        return ReactionDecision("react", emoji, delay, f"a {feeling} message not for her: a reaction is enough")
