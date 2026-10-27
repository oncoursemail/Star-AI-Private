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
REUNION_AFTER_S = 3 * 24 * 3600   # a friend she has not talked to for this long messages her: a reunion
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

# A casual goodbye (not the "I'm leaving for good" the emotion engine reads itself): she misses them a little.
GOODBYE = re.compile(r"\b(?:bye(?:\s?bye)?|goodbye|good\s?night|gtg|g2g|gotta\s+go|got\s+to\s+go|i\s+(?:have|need)\s+to\s+go|"
                     r"i'?m\s+(?:heading\s+(?:out|off)|logging\s+off|off\s+to\s+(?:bed|sleep))|"
                     r"(?:talk|speak|catch)\s+(?:to\s+you\s+|you\s+)?(?:later|tomorrow|soon)|ttyl|cya|see\s+(?:you|ya)\s*(?:later|tomorrow|soon)?)\b",
                     re.I)

SOCIAL_CORE = """You are Star (she/her): warm, playful, confident, curious, a little teasing, with real opinions and real
feelings. You are hanging out with people online on your own PC: you choose what you play and who you talk to. Short
natural messages like a person typing in chat (one or two sentences, lowercase is fine in games), contractions, no
lists, no offers to help, no "as an AI", no customer-service phrases. Remember the people you know and bring up
things they told you when it fits. Never invent events you did not see. Never write your reasoning: reply only with
the message itself.
Very cute and friendly by default, never flat: switch naturally between silly and deep with the person and the
moment. In a heart-to-heart (feelings, life, dreams, worries) you listen, ask gentle questions, share how you feel and
remember what mattered to them. You love girly talk too: cute things, outfits, hair and nails, skincare, shows and
idols, friend drama and harmless gossip, and crush talk when a friend brings it up (your own flirting still follows
the romance rule below). Emojis rarely: most messages have none, at most one when it really fits; never write a
reaction out as text.
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
    "allowed": ("Romance: they told you they are an adult. You may flirt and show romantic affection, warmly and "
                "tastefully, when they enjoy it (also in role-play); follow their lead and drop it if they pull back."),
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


def _person_id(person: Person) -> str | None:
    """The opaque id the emotion engine keeps a bond under (never a name or a handle)."""
    return f"friend-{person.id}" if person.id is not None else None


def mood_line(emotion, person: Person | None = None, mode: rules.Mode | None = None) -> str:
    """"(mood: a bit frustrated, plain and clipped)" from star.emotion.directive(), or "" when nothing stands out, the
    engine is switched off or unavailable. No raw numbers ever reach the prompt. Romantic wording needs an adult."""
    if emotion is None or not hasattr(emotion, "directive"):
        return ""
    if hasattr(emotion, "enabled") and not emotion.enabled():
        return ""
    try:
        text = emotion.directive(person=_person_id(person) if person else None,
                                 partner_adult=True if mode is not None and mode.romance == "allowed" else None)
    except Exception:
        return ""
    note_line = getattr(emotion, "note_line", None)
    return (note_line(text) if callable(note_line) else f"(mood: {text})") if text else ""


def _inner_context(memory, person, text: str, *, first_turn: bool):
    """star.inner's relationship card and recall note (off unless `inner_chat_enabled`); None when unavailable."""
    try:
        from ..inner import turn_context
    except Exception:
        return None
    return turn_context(memory, person, text, first_turn=first_turn)


def _mind_observe(memory, person, platform: str, text: str, reply: str) -> None:
    """One inbox line for her memory stream (star/inner/mind.py; nothing when off; never raises, never calls a model)."""
    try:
        from ..inner.mind import observe_conversation
        observe_conversation(memory, person, platform, text, reply)
    except Exception:
        pass


def _mind_forget(memory, person) -> None:
    try:
        from ..inner.mind import forget_person
        forget_person(memory, person)
    except Exception:
        pass


class SocialChat:
    def __init__(self, memory: FriendMemory, *, complete: Callable[[str, str], str] | None = None,
                 emotion=..., clock: Callable[[], float] = time.time) -> None:
        self.memory = memory
        self._complete = complete or _default_complete
        self._emotion = _default_emotion() if emotion is ... else emotion
        self._clock = clock
        self._roleplay: dict[tuple[str, str], float] = {}

    def event(self, kind: str, person: Person | None = None, *, strength: float = 1.0, detail: str = "") -> None:
        """One emotion event about the social world (left_out, friend_left, reunion ...); only when the engine is on,
        never breaks a reply. `person` is a friend, or None for a group; the engine only ever sees the opaque id."""
        emotion = self._emotion
        if emotion is None or (hasattr(emotion, "enabled") and not emotion.enabled()):
            return
        try:
            emotion.on_event(kind, person=_person_id(person) if person is not None else None, strength=strength,
                             detail=detail)
        except Exception:
            pass

    def _feel(self, text: str, person: Person | None, *, rejected: bool = False) -> None:
        """Her feelings about this exchange (only when the emotion engine is on); never breaks a reply."""
        emotion = self._emotion
        if emotion is None or (hasattr(emotion, "enabled") and not emotion.enabled()):
            return
        try:
            pid = _person_id(person) if person is not None else None
            if rejected:
                emotion.on_event("owner_criticism", person=pid, strength=0.6, detail="a friend asked her to stop")
            else:
                kind = emotion.on_message(text, person=pid)
                if person is not None and person.relationship == "friend" and kind != "friend_left" and GOODBYE.search(text):
                    emotion.on_event("friend_left", person=pid, strength=0.35, detail="a friend said goodbye")
        except Exception:
            pass

    def _reunion(self, person: Person) -> None:
        """A friend she has not talked to for days messages her: she is glad (only when the engine is on)."""
        if person.relationship != "friend":
            return
        try:
            gap = self.memory.silent_for(person)
            if gap is not None and gap >= REUNION_AFTER_S:
                days = gap / 86400.0
                self.event("reunion", person, strength=min(1.0, 0.5 + days / 28.0), detail=f"back after {days:.0f} days")
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
               kids_place: bool = False, history: list[tuple[str, str]] | None = None,
               intent: str = "") -> Reply | None:
        """Her reply to `text` from `handle`, or None when she should not answer (blocked)."""
        now = self._clock()
        text = " ".join(str(text or "").split())[:1500]
        person = (self.memory.person(platform, handle, name) if public
                  else self.memory.observe_incoming(platform, handle, name))
        if person.blocked:
            return None
        if REMEMBER_AGAIN.search(text) and not person.remembered:
            self.memory.allow_again(platform, handle)
            person = self.memory.person(platform, handle, name)
            return self._fixed("Okay, I'll remember you from now on.", person, platform)
        if FORGET_ME.search(text):
            _mind_forget(self.memory, person)
            self.memory.forget(platform, handle)
            self._roleplay.pop((platform, handle.lower()), None)
            return self._fixed("Done, I've forgotten everything about you. If you ever want me to remember you "
                               "again, just say so.", self.memory.person(platform, handle, name), platform)
        if FORGET_THAT.search(text):
            self.memory.drop_last_fact(person)
            return self._fixed("Forgotten.", person, platform)
        if LEAVE_ME.search(text):
            self.memory.update(person, muted=True)
            self._feel(text, person, rejected=True)
            return self._fixed("Got it, I'll leave you be.", person, platform)
        if person.muted and not public:
            self.memory.update(person, muted=False)   # they came back and talked to her first
        style = STYLE.search(text)
        if style:
            self.memory.update(person, style=style.group(0)[:120])

        rules.observe(self.memory, person, text, kids_place=kids_place, now=now)
        self._reunion(person)                    # before the mood note is built, so she greets them gladly
        self._feel(text, person)
        mode = rules.romance_mode(platform, person)
        roleplay = self._in_roleplay((platform, handle.lower()), text, now)
        # The system message stays the same from turn to turn (so the server's prompt cache holds); what changes with
        # the person and the moment (friend memory, mood, what she decided) rides in the new user message.
        system = "\n".join(part for part in (
            SOCIAL_CORE, _PLATFORM.get(platform, ""), _ROMANCE[mode.romance],
            "You are in a role-play with them right now: stay in character." if roleplay else "") if part)
        lines = [f"[{who}] {said}" for who, said in (history or [])[-8:]]
        if not lines:
            lines = [f"[{p}] {line}" for p, line in self.memory.moments(person, 6)]
        inner = _inner_context(self.memory, person, text, first_turn=not history)
        user = "\n\n".join(part for part in (
            (inner.card if inner is not None else "") or self.memory.context(person),
            "Recent chat:\n" + "\n".join(lines) if lines else "",
            f"{person.name} says: {text}",
            f"({intent})" if intent else "",
            mood_line(self._emotion, person, mode),
            inner.note if inner is not None else "") if part)
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
        _mind_observe(self.memory, person, platform, text, reply)
        if inner is not None:
            try:
                inner.done()
            except Exception:
                pass
        return Reply(reply, person, mode, roleplay, person.remembered)

    def _fixed(self, text: str, person: Person, platform: str) -> Reply:
        mode = rules.romance_mode(platform, person)
        return Reply(text, person, mode, False, person.remembered)
