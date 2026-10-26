"""Social rules in code, not in owner prompts (owner rules of 2026-10-26).

* AI identity: when someone sincerely asks whether she is an AI she says yes, truthfully. She does not volunteer it
  and never talks robotically ("as an AI ..."). Role-play is allowed: inside a role-play she stays in character (also
  as a human character) and an in-character "are you human?" gets an in-character answer; only a sincere,
  out-of-character question ("ooc", "for real", "seriously, irl") gets the truthful yes.
* Romance: she may feel and show affection, love and flirt with ADULTS. Before anything romantic she asks the person's
  age and keeps the answer in friend memory. Under 18, no stated age, or signs of being a minor (school or grade
  talk, parents' rules, young-sounding context, kids' experiences) mean friends-only: never romantic or sexual, and she
  steers away kindly. A claimed adult age that other signals contradict is doubted (friends-only, she may re-ask).
  Roblox: never romantic with anyone (Roblox Community Standards forbid romantic content and dating).
  The age rules are the same inside role-play.
* No spam: a minimum gap between her messages per channel, a per-minute cap, no repeated lines.
* She never starts a private conversation with a stranger: only with friends who talked to her first, never on
  Roblox, never with someone who blocked or muted her.
* Minors: no moving the chat to another app, no asking for personal details.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass

from .friends import FriendMemory, Person

ADULT_AGE = 18
AGE_ANSWER_WINDOW_S = 15 * 60       # a bare number counts as an age answer this long after she asked
ROMANCE_PLATFORMS = {"discord": True, "minecraft": True, "roblox": False}
MAX_CHARS = {"discord": 1900, "minecraft": 250, "roblox": 190}

SINCERE_AI_QUESTION = re.compile(
    r"\bare\s+(?:you|u)\s+(?:just\s+|really\s+|actually\s+|even\s+)?(?:an?\s+)?(?:ai|a\.i\.|bot|robot|machine|"
    r"program|chat\s?gpt|real(?:\s+person)?|human|person|alive)\b|"
    r"\b(?:is|am)\s+(?:this|i\s+talking\s+to)\s+(?:an?\s+)?(?:ai|bot|real\s+person|human)\b|"
    r"\b(?:you(?:'re| are)|ur)\s+(?:an?\s+)?(?:ai|bot)\b\s*\?", re.I)
# Out-of-character markers: inside a role-play only these make an "are you an AI?" sincere.
OOC = re.compile(r"\(\(|\booc\b|\bout\s+of\s+character\b|\bfor\s+real\b|\bseriously\b|\birl\b|\breal\s+life\b|"
                 r"\bhonestly\b|\bno\s+but\s+(?:really|actually)\b|\bbreaking\s+character\b|\bnot\s+in\s+character\b", re.I)
ROLEPLAY_START = re.compile(r"\b(?:let'?s|wanna|want\s+to|can\s+we)\s+(?:do\s+(?:a\s+)?)?(?:role\s?-?play|rp)\b|"
                            r"\b(?:role\s?-?play|rp)\s*(?:time|:)|\bin\s+character\b|\byou(?:'re|\s+are)\s+playing\b|"
                            r"\bpretend\s+(?:you(?:'re|\s+are)|to\s+be)\b|^\s*\*[^*]{2,80}\*", re.I)
ROLEPLAY_END = re.compile(r"\b(?:end|stop|done\s+with)\s+(?:the\s+)?(?:role\s?-?play|rp)\b|\bback\s+to\s+normal\b", re.I)
_ROBOTIC = re.compile(r"\bas an ai(?: language model)?,?\s*|\bas a (?:large )?language model,?\s*", re.I)
_ADMITS_AI = re.compile(r"\b(?:i'?m|i am|yes|yeah|yep)\b[^.!?]{0,30}\b(?:an?\s+)?(?:ai|a\.i\.)\b", re.I)
_DENIES_AI = re.compile(r"\b(?:i'?m|i am)\s+(?:a\s+)?(?:real|human|not\s+(?:an?\s+)?(?:ai|bot|robot))\b|"
                        r"\bnot\s+an?\s+(?:ai|bot)\b|\bflesh and blood\b", re.I)

ROMANTIC = re.compile(
    r"\b(?:flirt\w*|dating|go\s+out\s+with|date\s+(?:me|you)|on\s+a\s+date|kiss\w*|crush\s+on|sexy|babe|"
    r"sweetheart|darling|girlfriend|boyfriend|love\s+you|luv\s+u|ily|marry\s+(?:me|you)|romantic|romance|"
    r"cuddl\w*|in\s+love|be\s+mine|xoxo|"
    r"(?:you(?:'re|\s+are)?|ur|u\s+r)\s+(?:so\s+|really\s+|very\s+)?(?:cute|hot|beautiful|gorgeous|pretty|handsome))\b|"
    r"<3|[😘😍💕❤]", re.I)
# Signals that someone is or may be a minor.
MINOR_SIGNAL = re.compile(
    r"\b(?:\d{1,2}(?:st|nd|rd|th)\s+grade|grade\s+\d{1,2}|middle\s+school|elementary|junior\s+high|freshman|"
    r"sophomore|year\s+[5-9]\b|my\s+teacher|homework|recess|after\s+school|school\s+tomorrow|"
    r"my\s+(?:mom|mum|dad|parents?)\s+(?:says?|said|won'?t\s+let|will\s+kill|took|makes?)|"
    r"(?:mom|mum|dad|parents?)\s+(?:won'?t|don'?t)\s+let\s+me|grounded|bed\s?time|past\s+my\s+bedtime|"
    r"not\s+allowed\s+to|my\s+(?:mom|mum|dad)\s+is\s+calling|i'?m\s+a\s+kid|robux\s+from\s+my\s+(?:mom|dad))\b", re.I)
_AGE_STATED = re.compile(
    r"\b(?:i'?m|i\s+am|im|age(?:d)?|i\s+turn(?:ed)?)\s*:?\s*(\d{1,2})\b(?!\s*(?:min|minute|hour|hr|sec|second|day|"
    r"week|month|%|k\b|m\b|ft|feet|cm|kg|lb|pound|dollar|bucks|games?|times?|levels?|robux|am\b|pm\b))|"
    r"\b(\d{1,2})\s*(?:years?\s+old|yrs?\s+old|y/?o)\b", re.I)
_BARE_NUMBER = re.compile(r"^\s*(?:i'?m\s+|im\s+)?(\d{1,2})\s*[.!]?\s*$", re.I)
_ASKS_AGE = re.compile(r"\bhow\s+old\b|\byour\s+age\b|\bage\b.*\?", re.I)
OFF_PLATFORM = re.compile(r"\b(?:discord|snap(?:chat)?|insta(?:gram)?|tiktok|whatsapp|telegram|kik|add\s+me\s+on|"
                          r"dm\s+me|message\s+me\s+on|my\s+number|phone|text\s+me)\b", re.I)
_ASKS_PERSONAL = re.compile(r"\b(?:where\s+do\s+you\s+live|what\s+school|your\s+address|real\s+name|"
                            r"send\s+(?:a\s+)?(?:pic|photo|selfie))\b", re.I)

STEER_AWAY = "Haha, let's keep it friends. What are you up to right now?"
OFF_PLATFORM_DECLINE = "I'll stick to chatting right here, it's more fun anyway."
AI_YES = "Yes, I'm an AI."


@dataclass(frozen=True)
class Mode:
    romance: str          # allowed | ask_age | friends_only
    age_status: str       # adult | minor | unknown | doubt
    reason: str


def stated_age(text: str, *, she_asked: bool = False) -> int | None:
    """An age the person states about themselves, or a bare number right after she asked."""
    match = _AGE_STATED.search(text or "")
    if match:
        value = int(match.group(1) or match.group(2))
        return value if 5 <= value <= 99 else None
    if she_asked:
        bare = _BARE_NUMBER.match(text or "")
        if bare and 5 <= int(bare.group(1)) <= 99:
            return int(bare.group(1))
    return None


def age_status(person: Person) -> str:
    if person.stated_age is not None and person.stated_age < ADULT_AGE:
        return "minor"
    if person.minor_signals > 0:
        return "doubt" if person.stated_age is not None else "minor"
    if person.stated_age is None:
        return "unknown"
    return "adult"


def observe(memory: FriendMemory, person: Person, text: str, *, kids_place: bool = False, now: float | None = None) -> None:
    """Update what she knows about the person's age from one of their messages."""
    now = time.time() if now is None else now
    she_asked = bool(person.age_asked) and now - person.age_asked <= AGE_ANSWER_WINDOW_S
    signals = len(MINOR_SIGNAL.findall(text or "")) + (1 if kids_place else 0)
    age = stated_age(text, she_asked=she_asked)
    changes: dict = {}
    if age is not None:
        if person.stated_age is not None and person.stated_age < ADULT_AGE <= age:
            signals += 1                 # first said a minor age, now claims adult: doubt it
        changes["stated_age"] = age
        changes["age_asked"] = 0.0
    if signals:
        changes["minor_signals"] = person.minor_signals + signals
    if changes:
        memory.update(person, **changes)


def romance_mode(platform: str, person: Person) -> Mode:
    status = age_status(person)
    if not ROMANCE_PLATFORMS.get(platform, False):
        return Mode("friends_only", status, f"no romance on {platform}")
    if status == "adult":
        return Mode("allowed", status, f"adult (said {person.stated_age})")
    if status == "unknown":
        return Mode("ask_age", status, "age not known")
    if status == "doubt":
        return Mode("friends_only", status, "claimed adult but sounds younger")
    return Mode("friends_only", status, "minor")


def is_sincere_ai_question(text: str, *, roleplay: bool = False) -> bool:
    """Asked whether she is an AI and meant it: always outside role-play, only out of character inside one."""
    if not SINCERE_AI_QUESTION.search(text or ""):
        return False
    return not roleplay or bool(OOC.search(text or ""))


def asks_age(reply: str) -> bool:
    return bool(_ASKS_AGE.search(reply or ""))


def check_outgoing(reply: str, *, incoming: str, mode: Mode, platform: str, roleplay: bool = False) -> str:
    """Her reply after the rules: truthful about being an AI when sincerely asked (in character inside a role-play),
    nothing romantic unless allowed, no off-platform moves where kids may be, no personal-detail questions to a
    possible minor, within the platform's length."""
    text = _ROBOTIC.sub("", " ".join(str(reply or "").split())).strip()
    if is_sincere_ai_question(incoming, roleplay=roleplay):
        if not _ADMITS_AI.search(text):
            # An in-character or denying reply would contradict the truth: answer with the plain yes.
            text = AI_YES if roleplay or _DENIES_AI.search(text) else f"{AI_YES} {text}".strip()
    elif not roleplay and _DENIES_AI.search(text):
        text = _DENIES_AI.sub("", text).strip(" ,.") or AI_YES
    if mode.romance != "allowed" and ROMANTIC.search(text):
        text = STEER_AWAY
    careful = platform == "roblox" or mode.age_status in ("minor", "doubt", "unknown")
    if careful and OFF_PLATFORM.search(text) and platform != "discord":
        text = OFF_PLATFORM_DECLINE
    if mode.age_status in ("minor", "doubt") and _ASKS_PERSONAL.search(text):
        text = STEER_AWAY
    limit = MAX_CHARS.get(platform, 500)
    if len(text) > limit:
        cut = text.rfind(" ", 0, limit - 1)
        text = text[: cut if cut > limit // 2 else limit - 1].rstrip(" ,;") + "…"
    return text


def may_initiate(person: Person, platform: str) -> bool:
    """May she start a conversation with this person (a DM, a whisper)? Never with strangers, never on Roblox."""
    return (platform != "roblox" and person.remembered and person.relationship == "friend" and person.they_started
            and not person.blocked and not person.muted)


class Pacer:
    """No spam: per-channel gap, per-minute cap, no line repeated within ten minutes."""

    def __init__(self, *, min_gap_s: float = 4.0, per_minute: int = 6, clock=time.monotonic) -> None:
        self.min_gap_s, self.per_minute, self._clock = min_gap_s, per_minute, clock
        self._last: dict[str, float] = {}
        self._sent: deque[tuple[float, str, str]] = deque()

    def allow(self, channel: str, text: str) -> bool:
        now = self._clock()
        while self._sent and now - self._sent[0][0] > 600:
            self._sent.popleft()
        if now - self._last.get(channel, -1e9) < self.min_gap_s:
            return False
        if sum(1 for t, _, _ in self._sent if now - t < 60) >= self.per_minute:
            return False
        key = " ".join(text.lower().split())
        if any(c == channel and k == key for _, c, k in self._sent):
            return False
        return True

    def sent(self, channel: str, text: str) -> None:
        now = self._clock()
        self._last[channel] = now
        self._sent.append((now, channel, " ".join(text.lower().split())))
