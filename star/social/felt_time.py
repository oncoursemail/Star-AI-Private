"""Felt time: she knows when things happen, and how long it has been.

Three small pieces that `lifecycle.Bonds` uses on every incoming line (pure functions, local time, no model):

* `when(text, now)`: "tomorrow", "tonight", "on friday", "next week", "in 3 days", "this weekend" -> the local day it
  points at (None when there is no time phrase).
* `dated_event(text, now)`: "i have my driving test on friday", "going to the dentist tomorrow", "my birthday is
  saturday" -> what it is, the question to ask AFTER it ("how did your driving test go?"), the moment that question
  becomes askable (the evening of that day, the next morning for "tonight"), and the day itself (for a good-luck before
  it). A birthday is not asked about afterwards: she wishes them a happy birthday on the day.
* `gap_note(...)`: how a new conversation feels after a gap: earlier today, yesterday, a couple of days, and for a
  friend who was gone for a while she missed them (said warmly, never as a complaint).
* `promise_from(reply, now)`: something SHE said she would do later ("i'll show you tomorrow"), so she can keep it.

Everything here is a hint for her own words; nothing is sent from this module.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WD = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?"
_NUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "couple": 2, "few": 3}
_WHEN = re.compile(
    r"\b(?:(?P<dat>(?:the\s+)?day\s+after\s+tomorrow)|(?P<tmr>tomorrow|tmrw|tmr|tmw)|(?P<tonight>tonight|this\s+evening|later\s+tonight)|"
    r"(?P<today>today|this\s+(?:morning|afternoon)|later\s+today)|"
    r"(?P<inn>in\s+(?:(?P<n>\d{1,2}|a|one|two|three|four|five|six|seven|a\s+couple(?:\s+of)?|a\s+few)\s+)?(?P<unit>days?|weeks?))|"
    r"(?P<nextweek>next\s+week)|(?P<weekend>(?:this|the|next)\s+weekend|on\s+the\s+weekend)|"
    r"(?:(?P<next>next|this|on|on\s+the)\s+)?(?P<wd>" + _WD + r"))\b", re.I)
_PERSONAL = re.compile(r"\b(?:i|i'm|im|i've|ive|i'll|ill|my|we|we're|we've|me)\b", re.I)
_DROPPED_SUBJECT = re.compile(r"^\W*(?:going\s+to|gonna|gotta|got|have|having|off\s+to|heading\s+to)\b", re.I)   # "going to the dentist tmrw"
_NEGATED = re.compile(r"\b(?:no|don'?t|didn'?t|not|isn'?t|cancel+ed|postponed)\b", re.I)
_EVENT_NOUN = (r"(?:test|exam|quiz|finals?|midterms?|interview|dentist|orthodontist|doctor|appointment|check-?up|surgery|"
               r"operation|tryouts?|recital|concert|audition|presentation|match|tournament|game|race|party|date|trip|flight|"
               r"wedding|funeral|vet|meeting|deadline|first\s+day|shift|birthday|bday|competition)")
_EVENT = re.compile(r"\b(?:(?P<det>my|a|an|the|our)\s+(?P<mods>(?:[a-z]+\s+){0,2}?))?(?P<noun>" + _EVENT_NOUN + r")\b", re.I)
_NEEDS_OWN = {"game", "match", "race", "date", "meeting", "shift", "deadline"}   # "the game" is not theirs; "my game" is
_FILLER = {"have", "got", "a", "an", "the", "my", "our", "big", "huge", "going", "to", "at", "for", "is", "its", "it's", "this",
           "next", "on", "and", "so", "i", "im", "i'm", "we", "really", "super", "scary", "stupid", "important", "first"}
_PLACE = {"dentist", "orthodontist", "doctor", "vet", "party", "trip", "wedding", "concert", "date", "funeral", "shift", "flight"}
_SENSITIVE_EVENT = re.compile(r"\b(?:surgery|operation|funeral|doctor|appointment|check-?up)\b", re.I)

ASK_HOUR = 18            # a day-anchored event is over by the evening
MORNING_HOUR = 9


def _local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts)


def _at(day: datetime, hour: int) -> float:
    return time.mktime(day.replace(hour=hour, minute=0, second=0, microsecond=0).timetuple())


@dataclass(frozen=True)
class When:
    day: datetime            # local midnight of the day it points at
    evening: bool            # "tonight": over late, so ask the next morning
    vague: bool              # "next week", "in 2 weeks": the day is a guess
    phrase: str


def when(text: str, now: float) -> When | None:
    """The first time phrase in `text`, as the local day it points at; None when there is none."""
    match = _WHEN.search(str(text or ""))
    if match is None:
        return None
    today = _local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    g = match.groupdict()
    evening = vague = False
    if g["dat"]:
        day = today + timedelta(days=2)
    elif g["tmr"]:
        day = today + timedelta(days=1)
    elif g["tonight"]:
        day, evening = today, True
    elif g["today"]:
        day = today
    elif g["inn"]:
        raw = (g["n"] or "a").lower().replace(" of", "")
        n = int(raw) if raw.isdigit() else _NUM.get(raw.split()[-1], _NUM.get(raw.split()[0], 1))
        weeks = (g["unit"] or "").lower().startswith("week")
        day, vague = today + timedelta(days=n * (7 if weeks else 1)), weeks
    elif g["nextweek"]:
        day, vague = today + timedelta(days=7), True
    elif g["weekend"]:
        ahead = (5 - today.weekday()) % 7
        day = today + timedelta(days=ahead + (7 if g["weekend"].lower().startswith("next") else 0))
    else:
        word = g["wd"].lower()
        target = next(i for i, name in enumerate(WEEKDAYS) if name.startswith(word[:3]))
        ahead = (target - today.weekday()) % 7
        if (g["next"] or "").lower() == "next" and ahead < 2:
            ahead += 7                   # "next friday" on a thursday is a week later, not tomorrow
        day = today + timedelta(days=ahead)
    return When(day, evening, vague, match.group(0))


@dataclass(frozen=True)
class Event:
    what: str                # "your driving test"
    noun: str                # "test"
    question: str            # what to ask after it ("how did your driving test go?"), or the birthday wish
    ask_after: float         # when that becomes askable
    day: float               # local start of the day it happens (for a good luck before it)
    birthday: bool = False
    sensitive: bool = False  # doctor, surgery: ask gently


def dated_event(text: str, now: float) -> Event | None:
    """Something dated in their own life ("my exam is on friday"), or None. One per message."""
    text = " ".join(str(text or "").split())
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        found = when(sentence, now)
        event = _EVENT.search(sentence)
        if found is None or event is None or not (_PERSONAL.search(sentence) or _DROPPED_SUBJECT.search(sentence)):
            continue
        if _NEGATED.search(sentence[: event.start()]) and re.search(r"\b(?:no|don'?t|not)\s+(?:have\s+)?(?:a|an|my|any)?\s*$",
                                                                     sentence[: event.start()], re.I):
            continue
        noun = event.group("noun").lower()
        if noun in _NEEDS_OWN and (event.group("det") or "").lower() not in ("my", "a", "an", "our"):
            continue
        mods = [w for w in (event.group("mods") or "").lower().split() if w not in _FILLER and not _WHEN.fullmatch(w)]
        core = " ".join(mods + [noun]).strip()
        birthday = noun in ("birthday", "bday")
        if birthday:
            if not re.search(r"\bmy\s+(?:\w+\s+)?b(?:irth)?day\b|\bit'?s\s+my\s+b(?:irth)?day\b|\bmy\s+b(?:irth)?day\b", sentence, re.I):
                continue                   # someone else's birthday: not hers to wish
            day = found.day
            return Event("your birthday", noun, "happy birthday!", _at(day, 8), _at(day, 0), birthday=True)
        det = (event.group("det") or "").lower()
        what = ("the " + core) if noun in _PLACE and det in ("", "the", "a", "an") else ("your " + core)
        ask = f"how was {what}?" if noun in _PLACE else f"how did {what} go?"
        day = found.day
        ask_after = _at(day + timedelta(days=1), MORNING_HOUR) if found.evening else (
            _at(day, ASK_HOUR) if not found.vague else _at(day + timedelta(days=1), ASK_HOUR))
        if ask_after <= now:
            continue                       # "today" said at 23:00: it's over, nothing to look forward to
        return Event(what, noun, ask, ask_after, _at(day, 0), sensitive=bool(_SENSITIVE_EVENT.search(core)))
    return None


def luck_line(event: Event, now: float) -> str:
    """A good-luck to bring up while the event is still ahead (the day before or that day), else ''."""
    if event.birthday:
        return ""
    day = _local(event.day)
    rel = "today" if _local(now).date() == day.date() else "tomorrow" if (day.date() - _local(now).date()).days == 1 else ""
    return f"{event.what} is {rel}" if rel else ""


# -- gaps -------------------------------------------------------------------------------------------------------------
SAME_CONVO_S = 30 * 60
MISS_AFTER_DAYS = 5.0


def _days_between(a: float, b: float) -> int:
    return (_local(b).date() - _local(a).date()).days


def gap_note(last_seen: float, now: float, stage: str) -> str:
    """How a NEW conversation feels after the gap ('' inside a conversation, for strangers, or after 3+ days, which
    lifecycle's reunion line already covers). Never numbers of hours; never a reproach."""
    if not last_seen or now - last_seen < SAME_CONVO_S or stage == "met":
        return ""
    days = _days_between(last_seen, now)
    if days == 0:
        return "you already talked earlier today, so no big hello"
    if days == 1:
        return "you last talked yesterday"
    if days == 2:
        return "you last talked two days ago"
    return "you last talked a few days ago"      # 3 calendar days but under 72 h: lifecycle's reunion line has not started


def miss_note(gap_days: float, stage: str) -> str:
    """After a longer silence a friend coming back is a happy moment: she missed them a little."""
    if gap_days < MISS_AFTER_DAYS or stage not in ("friend", "close_friend"):
        return ""
    return "you missed them a bit and you're really happy they're back: you can say so warmly, never as a complaint"


# -- her own promises -------------------------------------------------------------------------------------------------
_PROMISE = re.compile(
    r"\b(?:i'?ll|i\s+will|i'?m\s+gonna|i'?m\s+going\s+to|lemme|let\s+me)\s+"
    r"(?P<what>(?:show|send|tell|teach|help|bring|build|make|draw|find|message|text|dm|ping|call|play|check|try|look)\b[^.!?\n]{0,60})", re.I)
_MESSAGE = re.compile(r"\b(?:message|text|dm|ping|call|talk|play)\b", re.I)


@dataclass(frozen=True)
class Promise:
    text: str                # "i'll show you my castle tomorrow"
    due: float               # when it is due
    reach_out: bool          # "i'll message you tomorrow": keeping it means writing first


def promise_from(reply: str, now: float) -> Promise | None:
    """A promise in her own reply, with a time ("tomorrow", "later", "next time" counts as the next chat)."""
    reply = " ".join(str(reply or "").split())
    match = _PROMISE.search(reply)
    if match is None:
        return None
    what = match.group("what").strip(" ,")
    found = when(what, now)
    if found is None and not re.search(r"\b(?:later|next\s+time|soon|after)\b", what, re.I):
        return None
    due = now + 3 * 3600 if found is None else _at(found.day, 12 if not found.evening else 19)
    text = re.sub(r"\s+", " ", match.group(0)).strip(" ,")[:120]
    return Promise(text, max(due, now + 1800), bool(_MESSAGE.search(what)) and found is not None)
