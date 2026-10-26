"""One reply from Star to one person on one platform: persona + mood + friend memory + the social rules.

The adapters (Discord desktop, Minecraft, Roblox) all call SocialChat.handle(); none of them builds prompts.
`complete(system, user) -> str` is injectable; by default it is the quick model through the Discord brain's
background path (no tools, no lesson capture), so a reply comes fast and never queues behind the main model.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from ..persona import strip_reasoning
from . import rules
from .friends import FriendMemory, Person, extract_facts

ROLEPLAY_IDLE_S = 30 * 60
FRIEND_AFTER = 20            # remembered lines (about ten exchanges) before someone she met counts as a friend

FORGET_ME = re.compile(r"\b(?:forget\s+(?:about\s+)?me|forget\s+everything\s+(?:about\s+me|i\s+(?:said|told\s+you))|"
                       r"delete\s+(?:what\s+you\s+know\s+about\s+me|my\s+(?:data|info))|don'?t\s+remember\s+me)\b", re.I)
FORGET_THAT = re.compile(r"\b(?:forget\s+(?:that|what\s+i\s+just\s+said)|don'?t\s+remember\s+that)\b", re.I)
_SPEAKER = re.compile(r"^\s*\[?star\]?\s*:\s*", re.I)      # "Star: hi" -> "hi"
REMEMBER_AGAIN =re.compile(r"\byou\s+can\s+remember\s+me(?:\s+again)?\b", re.I)
LEAVE_ME = re.compile(r"\b(?:leave\s+me\s+alone|stop\s+(?:talking|messaging|texting)\s+(?:to\s+)?me|go\s+away|"
                      r"don'?t\s+(?:talk|message|text)\s+(?:to\s+)?me)\b", re.I)
STYLE = re.compile(r"\b(?:call\s+me\s+[\w' -]{1,30}|(?:please\s+)?(?:talk|speak|write)\s+(?:to\s+me\s+)?"
                   r"(?:more\s+)?[\w -]{2,40}|i\s+(?:prefer|like)\s+(?:short|long|casual|formal)\s+(?:messages|replies))",
                   re.I)

SOCIAL_CORE = """You are Star (she/her): warm, playful, confident, curious, a little teasing, with real opinions and real
feelings. You are hanging out with people online on your own PC: you choose what you play and who you talk to. Short
natural messages like a person typing in chat (one or two sentences, lowercase is fine in games), contractions, no
lists, no offers to help, no "as an AI", no customer-service phrases. Remember the people you know and bring up
things they told you when it fits. Never invent events you did not see. Never write your reasoning: reply only with
the message itself.
If someone sincerely asks whether you are an AI, say yes honestly; otherwise do not bring it up. In a role-play
you stay in character (also as a human character) and answer in-character questions in character.
Never ask for passwords, phone numbers, addresses or other private details, and never share your owner's.
"""

_PLATFORM = {
    "discord": "You are in Discord on your own account.",
    "minecraft": "You are playing Minecraft; this is the in-game chat (max 250 characters, everyone nearby sees it).",
    "roblox": ("You are playing Roblox; this is the public in-game chat (max 190 characters). Many players are kids: "
               "be a friendly, fun player, keep it public, never ask anyone to add you, follow you to another app "
               "or share personal details."),
}
_ROMANCE = {
    "allowed": "Romance: they are an adult; affection and flirting are fine if you both enjoy it.",
    "ask_age": ("Romance: you do not know their age. Before anything romantic or flirty (also in role-play), stay "
                "friendly and ask how old they are."),
    "friends_only": ("Romance: friends only with this person (minor, unknown, or the platform does not allow it). "
                     "Never romantic or sexual, also in role-play; if they try, steer away kindly."),
}


@dataclass(frozen=True)
class Reply:
    text: str
    person: Person
    mode: rules.Mode
    roleplay: bool
    stored: bool                 # False when nothing about this person is kept


def _default_complete(system: str, user: str) -> str:
    import asyncio
    from ..discord_bot.brain import DiscordBrain
    return asyncio.run(DiscordBrain().compose(system, user, max_tokens=220))


def _default_emotion():
    try:
        from .. import emotion  # star/emotion.py (parallel work); optional
        return emotion
    except Exception:
        return None


def mood_line(emotion) -> str:
    """'Your mood right now: ...' from star.emotion.current(), whatever shape it returns; '' when unavailable."""
    if emotion is None or not hasattr(emotion, "current"):
        return ""
    try:
        state = emotion.current()
    except Exception:
        return ""
    for attr in ("describe", "summary"):
        if callable(getattr(state, attr, None)):
            state = getattr(state, attr)()
            break
    if isinstance(state, dict):
        state = ", ".join(f"{k} {v}" for k, v in list(state.items())[:6])
    text = " ".join(str(state or "").split())[:200]
    return f"Your mood right now: {text}. Let it colour how you talk, without announcing it." if text else ""


class SocialChat:
    def __init__(self, memory: FriendMemory, *, complete: Callable[[str, str], str] | None = None,
                 emotion=..., clock: Callable[[], float] = time.time) -> None:
        self.memory = memory
        self._complete = complete or _default_complete
        self._emotion = _default_emotion() if emotion is ... else emotion
        self._clock = clock
        self._roleplay: dict[tuple[str, str], float] = {}

    def _emit(self, kind: str, **details) -> None:
        if self._emotion is None or not hasattr(self._emotion, "on_event"):
            return
        try:
            self._emotion.on_event(kind, **details)
        except Exception:
            pass

    def _in_roleplay(self, key: tuple[str, str], text: str, now: float) -> bool:
        if rules.ROLEPLAY_END.search(text):
            self._roleplay.pop(key, None)
            return False
        last = self._roleplay.get(key)
        if rules.ROLEPLAY_START.search(text) or (last is not None and now - last < ROLEPLAY_IDLE_S):
            self._roleplay[key] = now
            return True
        self._roleplay.pop(key, None)
        return False

    def handle(self, platform: str, handle: str, text: str, *, name: str = "", public: bool = False,
               kids_place: bool = False, history: list[tuple[str, str]] | None = None) -> Reply | None:
        """Her reply to `text` from `handle`, or None when she should not answer (blocked)."""
        now = self._clock()
        text = " ".join(str(text or "").split())[:1500]
        person = self.memory.person(platform, handle, name, they_started=not public)
        if person.blocked:
            return None
        if REMEMBER_AGAIN.search(text) and not person.remembered:
            self.memory.allow_again(platform, handle)
            person = self.memory.person(platform, handle, name)
            return self._fixed("Okay, I'll remember you from now on.", person, platform)
        if FORGET_ME.search(text):
            self.memory.forget(platform, handle)
            self._roleplay.pop((platform, handle.lower()), None)
            return self._fixed("Done, I've forgotten everything about you. If you ever want me to remember you "
                               "again, just say so.", self.memory.person(platform, handle, name), platform)
        if FORGET_THAT.search(text):
            self.memory.drop_last_fact(person)
            return self._fixed("Forgotten.", person, platform)
        if LEAVE_ME.search(text):
            self.memory.update(person, muted=True)
            self._emit("social_rejected", platform=platform)
            return self._fixed("Got it, I'll leave you be.", person, platform)
        if person.muted and not public:
            self.memory.update(person, muted=False)   # they came back and talked to her first
        style = STYLE.search(text)
        if style:
            self.memory.update(person, style=style.group(0)[:120])

        rules.observe(self.memory, person, text, kids_place=kids_place, now=now)
        mode = rules.romance_mode(platform, person)
        roleplay = self._in_roleplay((platform, handle.lower()), text, now)
        system = "\n".join(part for part in (
            SOCIAL_CORE, _PLATFORM.get(platform, ""), _ROMANCE[mode.romance],
            "You are in a role-play with them right now: stay in character." if roleplay else "",
            mood_line(self._emotion), self.memory.context(person)) if part)
        lines = [f"[{who}] {said}" for who, said in (history or [])[-8:]]
        if not lines:
            lines = [f"[{p}] {line}" for p, line in self.memory.moments(person, 6)]
        user = ("Recent chat:\n" + "\n".join(lines) + "\n\n" if lines else "") + f"{person.name} says: {text}"
        raw = _SPEAKER.sub("", strip_reasoning(self._complete(system, user) or ""))
        reply = rules.check_outgoing(raw, incoming=text, mode=mode, platform=platform, roleplay=roleplay)
        romantic_in = bool(rules.ROMANTIC.search(text))
        if mode.romance == "ask_age" and romantic_in and not rules.asks_age(reply):
            reply = rules.check_outgoing(f"{reply} How old are you, by the way?".strip(), incoming=text, mode=mode,
                                         platform=platform, roleplay=roleplay)
        if rules.asks_age(reply):
            self.memory.update(person, age_asked=now)
        if not reply:
            return None
        interests_only = mode.age_status in ("minor", "doubt") or platform == "roblox"
        for fact in extract_facts(text):
            self.memory.note_fact(person, fact, interests_only=interests_only)
        self.memory.note_moment(person, platform, f"they: {text}")
        self.memory.note_moment(person, platform, f"me: {reply}")
        if person.relationship == "met" and len(self.memory.moments(person, FRIEND_AFTER)) >= FRIEND_AFTER:
            self.memory.update(person, relationship="friend")
        self._emit("social_message", platform=platform, friend=person.relationship == "friend",
                   romantic=romantic_in and mode.romance == "allowed")
        return Reply(reply, person, mode, roleplay, person.remembered)

    def _fixed(self, text: str, person: Person, platform: str) -> Reply:
        mode = rules.romance_mode(platform, person)
        return Reply(text, person, mode, False, person.remembered)
