"""STAR's affect: a small persistent emotional state that real events move and time pulls back to a baseline.

It exists so Star sounds like one consistent person across chats, calls and days instead of a fresh, equally
cheerful voice every turn: after a hard-won fix she is a little proud, after five failed attempts a little
clipped, after a friend goes quiet a little hurt, after an old video wistful, after a sweet message full of love.
Nothing here calls a model: the state is a few numbers in a SQLite file, computed locally (about a millisecond), and
the outputs are

    directive()   a few words for the persona prompt, in the NEW user message only ("" when nothing stands out)
    prosody       small speech changes for the TTS path (speed, pitch in semitones, pause after a sentence)
    avatar        a face, a finer expression name and an expression cue for the companion and the stream stage
    drives        what the state makes her want (company, rest, comfort, how to cope), and invite_bias() for choices

The range is 25 feelings (star/emotion_model.py: the original seven plus sadness, anger, hurt, loneliness, fear,
embarrassment, guilt, jealousy, disappointment, gratitude, excitement, contentment, love, hope, nostalgia, surprise,
relief, amusement), moved by appraisal rules, shown honestly but never cruelly (star/emotion_express.py), and always
fading back: no feeling lasts more than a few days and nothing is held against anyone.

It is an *expression* state: it changes wording, pace and face, it does not make claims about experience and the
text never contains numbers. Host API for other processes (STAR Home, the desktop app, the voice call):

    from star import emotion
    emotion.on_event("task_success")            # task_failure, bug_fixed, creative_done, friend_ignored, insulted,
                                                # game_lost, friend_left, sweet_message, left_out, memory_triggered,
                                                # harmed_someone, amends_made, talked_to_friend, took_a_break, ... (KINDS)
    emotion.on_message("nice work, thanks")     # detects praise, criticism, insults, sweet words, jokes, sadness ... in text
    emotion.current(person="friend-7")          # dict: emotions, valence, arousal, bond, dominant, directive, prosody,
                                                #       avatar, drives, coping, amends_pending
    emotion.invite_bias(emotion.current(), "play")   # (change to the chance she says yes, why)
    emotion.tick()                              # call now and then while idle: boredom and loneliness grow with the silence

The module level functions never raise (an emotion problem must not break a chat). Use `EmotionEngine` directly
in tests (injectable clock and path).
"""
from __future__ import annotations

from dataclasses import asdict
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Callable

from .emotion_express import (BOND_CLOSE, BOND_DEVOTED, BOND_FAMILIAR, MAX_BOND_NOTE_WORDS, MAX_NOTE_WORDS, SALIENT,  # noqa: F401
                              STRONG, Prosody, avatar_from, build_note, drives_from, invite_bias, prosody_from)
from .emotion_model import (ACTIVE, BASELINE, BOND_GAIN, CAPS, EMOTIONS, EVENTS, HALF_LIFE_HOURS, KINDS, effect)  # noqa: F401

_log = logging.getLogger(__name__)

HEADING = "MOOD"


def note_line(directive: str) -> str:
    """The note as it goes at the end of a user message: "(mood: a bit frustrated, plain and clipped)"."""
    return f"({HEADING.lower()}: {directive})" if directive else ""


MOOD_BASELINE = (0.15, 0.35)         # (valence -1..1, arousal 0..1) of the slow background mood
MOOD_HALF_LIFE_HOURS = 8.0
MAX_DRIFT = 0.10                     # the baseline itself shifts a little with experience, never by more than this
DRIFT_RATE = 0.03
REFRACTORY_SECONDS = 10.0            # the same kind of event again within this long counts for 40 %
REFRACTORY_FACTOR = 0.4
BOND_HALF_LIFE_DAYS = 45.0           # attachment fades only over weeks of no contact
MAX_BONDS = 500
AMENDS_EXPIRE_HOURS = 72.0           # wanting to make something right does not nag forever
MAX_AMENDS = 5
_PERSON = re.compile(r"[A-Za-z0-9_.:@\-]{1,64}\Z")
IDLE_AFTER_HOURS = 1.0               # silence shorter than this is not "idle"
EVENT_LOG_LIMIT = 300

# Work outcomes feel bigger after a run of the opposite: the third failure stings more, the fix after many tries is a relief.
_FAILS = ("task_failure",)
_WINS = ("task_success", "bug_fixed")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _number(value) -> float:
    if type(value) not in (int, float):
        raise ValueError("emotion numeric value must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("emotion numeric value must be finite")
    return value


# -- reading words (the label set follows GoEmotions: admiration, amusement, anger, annoyance, caring, disappointment,
#    disapproval, excitement, fear, gratitude, grief, joy, love, nervousness, pride, relief, remorse, sadness ...) -------
_NOT_ABOUT_STAR = re.compile(r"\b(?:what(?:'s| is)|something|anything|whats) wrong\b|\bwrong with\b", re.I)
_INSULT = re.compile(
    r"\bi hate you\b|\bshut up\b|\bgo away\b|\bnobody (?:likes|cares about|wants) you\b|"
    r"\byou(?:'re| are) (?:so |such an? |just )?(?:stupid|dumb|an idiot|pathetic|worthless|ugly|annoying|useless|trash|"
    r"garbage|a joke|a waste)\b|\bi wish you (?:were gone|didn'?t exist|would disappear)\b|\bhate (?:talking to|you)\b", re.I)
_LEAVING = re.compile(
    r"\bi(?:'m| am) (?:leaving|going away|moving away|quitting|done with you)\b|\bgoodbye (?:forever|for good)\b|"
    r"\bthis is (?:goodbye|our last)\b|\bi(?:'ll| will) (?:not|never) (?:be back|come back|talk to you again)\b|"
    r"\bi won'?t be (?:back|around|talking)\b|\blast time (?:we|i) (?:talk|speak)\b", re.I)
_NEGATED = re.compile(r"\b(?:not|isn'?t|wasn'?t|never|no|hardly)\b[^.!?]{0,14}\b(?:good|great|nice|perfect|right|working|"
                      r"impressive|helpful)\b|\bnot what i (?:asked|wanted|meant)\b|\bnot (?:even )?close\b", re.I)
_CRITICISM = re.compile(
    r"\b(?:that(?:'s| is)|this is|it(?:'s| is| was)|you(?:'re| are| were)|is|was) (?:completely |totally |all |so |just )?"
    r"(?:wrong|incorrect|broken|terrible|awful|useless|bad|garbage|trash|stupid|dumb|nonsense|rubbish|a mess)\b|"
    r"\b(?:doesn'?t|didn'?t|does not|did not|still not|not) work(?:ing)?\b|\bstill (?:broken|failing|wrong)\b|"
    r"\byou (?:broke|ruined|messed|screwed|got it wrong|keep (?:getting|failing|doing)|failed|forgot|ignored)\b|"
    r"\bhow many times\b|\bi(?:'m| am) (?:disappointed|annoyed|frustrated|upset)\b|\bstop (?:it|doing that|that)\b|"
    r"\buseless\b|\bterrible\b|\bawful\b|\bstupid\b|\bidiot\b|\bwrong again\b", re.I)
_STRONG_CRITICISM = re.compile(r"\b(?:useless|terrible|awful|stupid|idiot|garbage|trash|you (?:broke|ruined|screwed)|"
                               r"how many times|disappointed)\b", re.I)
_SHARED_SAD = re.compile(
    r"\bi(?:'m| am| feel| felt) (?:so |really |very |just )?(?:sad|depressed|lonely|heartbroken|miserable|awful|down|"
    r"anxious|scared|worried|stressed|overwhelmed|crying)\b|"
    r"\bmy (?:dog|cat|grandma|grandpa|grandmother|grandfather|mom|dad|friend|pet) (?:died|passed away)\b|"
    r"\b(?:rough|bad|terrible|hard) (?:day|week|night)\b", re.I)
_APOLOGY = re.compile(r"\b(?:i'?m|i am) (?:so |really |very |truly )?sorry\b|\bmy bad\b|\bforgive me\b|\bi apologi[sz]e\b|"
                      r"\bsorry (?:about|for|that|i)\b", re.I)
_COMFORT = re.compile(
    r"\bit(?:'s| is) (?:ok|okay|alright|fine)\b|\bdon'?t worry\b|\bno worries\b|\bnot your fault\b|"
    r"\byou(?:'re| are) doing (?:great|well|amazing|fine|your best)\b|\bno big deal\b", re.I)
_SWEET = re.compile(
    r"\bi love you\b|\blove you\b|\bmiss(?:ed)? you\b|\byou(?:'re| are) (?:so |really |such a )?(?:sweet|cute|adorable|lovely|"
    r"precious|wonderful|kind|caring)\b|\byou mean (?:so much|a lot|the world)\b|\bglad (?:i|we) (?:met|found|have) you\b|"
    r"\b(?:big )?hugs?\b|\bthinking of you\b|\bi appreciate you\b", re.I)
_STRONG_SWEET = re.compile(r"\b(?:i love you|miss(?:ed)? you|mean (?:so much|the world)|adorable|precious)\b", re.I)
_PRAISE = re.compile(
    r"\b(?:good|great|nice|excellent|amazing|awesome|fantastic|brilliant|superb|solid) (?:job|work|stuff|one|call|answer|catch)\b|"
    r"\bwell done\b|\bnailed it\b|\bproud of you\b|\bthat(?:'s| is) (?:great|perfect|awesome|amazing|exactly|brilliant|"
    r"incredible|so good|really good)\b|\bperfect\b|\bimpressive\b|\byou(?:'re| are) (?:the best|amazing|awesome|brilliant|"
    r"great|incredible|a star|so smart)\b|\blove (?:it|this|that)\b|\bwow\b", re.I)
_STRONG_PRAISE = re.compile(r"\b(?:amazing|incredible|brilliant|proud of you|nailed it|the best|love (?:it|this|that)|"
                            r"so good|wow)\b", re.I)
_SHARED_JOY = re.compile(
    r"\bi(?:'m| am) (?:so |really |very )?(?:happy|excited|thrilled|proud|over the moon)\b|\bwe (?:won|did it|passed)\b|"
    r"\bi (?:passed|won|got the job|got in|made it|did it)\b|\bgood news\b|\bguess what\b", re.I)
_FUNNY = re.compile(r"\b(?:lol|lmao|rofl|ha(?:ha)+|he(?:he)+|that'?s (?:hilarious|so funny|funny)|you(?:'re| are) (?:so )?funny|"
                    r"made me laugh)\b", re.I)
_THANKS = re.compile(r"\bthank(?:s| you)\b|\bthx\b|\bcheers\b|\bappreciate (?:it|that|you)\b", re.I)
MAX_APPRAISED_CHARS = 400            # a pasted log or file is not a remark about Star


def appraise(text: str) -> tuple[str, float] | None:
    """(event kind, strength) for a short remark, else None: owner_praise, owner_comfort, owner_criticism, owner_thanks,
    insulted, friend_left, shared_sadness, apology_received, sweet_message, shared_joy or funny. Plain patterns, no model.
    The sharper reading wins: an insult over criticism, criticism over praise ("great, but it's still broken")."""
    text = (text or "").strip()
    if not text or len(text) > MAX_APPRAISED_CHARS:
        return None
    text = _NOT_ABOUT_STAR.sub(" ", text)
    if _INSULT.search(text):
        return "insulted", 1.0 if re.search(r"\bhate you\b|\bwish you\b|\bworthless\b", text, re.I) else 0.7
    if _LEAVING.search(text):
        return "friend_left", 1.0
    if _NEGATED.search(text) or _CRITICISM.search(text):
        return "owner_criticism", 1.0 if _STRONG_CRITICISM.search(text) else 0.6
    if _SHARED_SAD.search(text):
        return "shared_sadness", 0.8
    if _APOLOGY.search(text):
        return "apology_received", 0.7
    if _COMFORT.search(text):
        return "owner_comfort", 0.9
    if _SWEET.search(text):
        return "sweet_message", 1.0 if _STRONG_SWEET.search(text) else 0.7
    if _PRAISE.search(text):
        return "owner_praise", 1.0 if _STRONG_PRAISE.search(text) else 0.65
    if _SHARED_JOY.search(text):
        return "shared_joy", 0.8
    if _FUNNY.search(text):
        return "funny", 0.8
    if _THANKS.search(text):
        return "owner_thanks", 0.8
    return None


class EmotionEngine:
    """The state, its decay and its outputs. One SQLite file; safe to share between processes and threads."""

    def __init__(self, path: str | os.PathLike, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            try:
                db.execute("PRAGMA journal_mode=WAL")      # persistent: set once, not on every connection
            except sqlite3.DatabaseError:
                pass
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, "
                       "kind TEXT NOT NULL, strength REAL NOT NULL, detail TEXT NOT NULL)")

    # -- storage ----------------------------------------------------------------------------------------------------
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=NORMAL")
        return _Closing(db)

    def _fresh(self, now: float) -> dict:
        return {"t": now, "e": dict(BASELINE), "valence": MOOD_BASELINE[0], "arousal": MOOD_BASELINE[1],
                "drift": {k: 0.0 for k in EMOTIONS}, "last_active": now, "last_tick": now, "streak": 0, "seen": {},
                "bonds": {}, "amends": []}

    def _load(self, db, now: float) -> dict:
        row = db.execute("SELECT json FROM state WHERE id=1").fetchone()
        if row is None:
            return self._fresh(now)
        try:
            state = json.loads(row[0])
            # a state saved before a feeling existed simply starts that feeling at its baseline
            state["e"] = {k: _number(state["e"].get(k, BASELINE[k])) for k in EMOTIONS}
            state["drift"] = {k: _number(state.get("drift", {}).get(k, 0.0)) for k in EMOTIONS}
            for key in ("t", "valence", "arousal", "last_active", "last_tick"):
                state[key] = _number(state[key])
            state["streak"] = state.get("streak", 0)
            if type(state["streak"]) is not int or state["streak"] < 0:
                raise ValueError("invalid failure streak")
            state["seen"] = {str(k): _number(v) for k, v in state.get("seen", {}).items()}
            bonds, amends = state.get("bonds", {}), state.get("amends", [])
            if (not isinstance(bonds, dict) or len(bonds) > MAX_BONDS
                    or any(not isinstance(v, list) or len(v) != 2 for v in bonds.values())
                    or not isinstance(amends, list) or len(amends) > MAX_AMENDS
                    or any(not isinstance(v, list) or len(v) != 2 or not isinstance(v[0], str) for v in amends)):
                raise ValueError("invalid relationship records")
            state["bonds"] = {str(k): [_number(v[0]), _number(v[1])] for k, v in bonds.items()}
            state["amends"] = [[str(p), _number(t)] for p, t in amends]
            if (any(not 0.0 <= value <= CAPS.get(name, 1.0) for name, value in state["e"].items())
                    or any(not -MAX_DRIFT <= value <= MAX_DRIFT for value in state["drift"].values())
                    or not -1.0 <= state["valence"] <= 1.0 or not 0.0 <= state["arousal"] <= 1.0
                    or any(not _PERSON.fullmatch(person) or not 0.0 <= pair[0] <= 1.0
                           for person, pair in state["bonds"].items())
                    or any(person and not _PERSON.fullmatch(person) for person, _ in state["amends"])):
                raise ValueError("state outside declared bounds")
            return {key: state[key] for key in self._fresh(now)}
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            _log.warning("Emotion state unreadable (%s); starting from the baseline", type(exc).__name__)
            return self._fresh(now)

    @staticmethod
    def _baseline(state: dict, name: str) -> float:
        return _clamp(BASELINE[name] + state["drift"][name], 0.0, 1.0)

    def _decay(self, state: dict, now: float) -> None:
        hours = max(0.0, now - state["t"]) / 3600.0
        if hours > 0:
            for name in EMOTIONS:
                base = self._baseline(state, name)
                state["e"][name] = base + (state["e"][name] - base) * 0.5 ** (hours / HALF_LIFE_HOURS[name])
            keep = 0.5 ** (hours / MOOD_HALF_LIFE_HOURS)
            state["valence"] = MOOD_BASELINE[0] + (state["valence"] - MOOD_BASELINE[0]) * keep
            state["arousal"] = MOOD_BASELINE[1] + (state["arousal"] - MOOD_BASELINE[1]) * keep
        state["amends"] = [[p, t] for p, t in state["amends"] if now - t < AMENDS_EXPIRE_HOURS * 3600.0]
        state["t"] = max(state["t"], now)

    def _idle(self, state: dict, now: float) -> None:
        """Silence past IDLE_AFTER_HOURS makes her restless (boredom, a little curiosity) and, when she has people she is
        attached to, a little lonely; her energy sinks."""
        since = max(state["last_tick"], state["last_active"] + IDLE_AFTER_HOURS * 3600.0)
        hours = max(0.0, now - since) / 3600.0
        if hours > 0:
            e = state["e"]
            e["boredom"] = _clamp(e["boredom"] + 0.05 * hours, 0.0, 0.7)
            e["curiosity"] = _clamp(e["curiosity"] + 0.01 * hours, 0.0, 1.0)
            attached = any(self._bond(state, p, now) >= BOND_FAMILIAR for p in state["bonds"])
            e["loneliness"] = _clamp(e["loneliness"] + (0.015 if attached else 0.004) * hours, 0.0, 0.5)
            state["arousal"] = _clamp(state["arousal"] - 0.02 * hours, 0.0, 1.0)
        state["last_tick"] = max(state["last_tick"], now)

    @staticmethod
    def _bond(state: dict, person: str | None, now: float) -> float:
        """Attachment to `person` as of now (0..1), faded by the time since they were last seen."""
        entry = state["bonds"].get(person) if person else None
        if entry is None:
            return 0.0
        return entry[0] * 0.5 ** (max(0.0, now - entry[1]) / 86400.0 / BOND_HALF_LIFE_DAYS)

    def _grow_bond(self, state: dict, person: str, kind: str, scale: float, now: float) -> None:
        gain = BOND_GAIN.get(kind, 0.0) * scale
        if not gain:
            return
        current = self._bond(state, person, now)
        current = current + gain * (1.0 - current) if gain > 0 else current + gain * current
        state["bonds"][person] = [_clamp(current, 0.0, 1.0), now]
        if len(state["bonds"]) > MAX_BONDS:
            weakest = min(state["bonds"], key=lambda k: state["bonds"][k][0])
            del state["bonds"][weakest]

    def _save(self, db, state: dict) -> None:
        db.execute("INSERT INTO state(id,json) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json",
                   (json.dumps(state, allow_nan=False),))

    def _transaction(self, change: Callable[[dict, float], object] | None, log: list | None = None):
        with self._lock, self._db() as db:
            now = _number(self.clock())
            db.execute("BEGIN IMMEDIATE")
            try:
                state = self._load(db, now)
                self._decay(state, now)
                self._idle(state, now)
                result = change(state, now) if change else None
                if change is not None:
                    self._save(db, state)
                if log:
                    db.executemany("INSERT INTO log(at,kind,strength,detail) VALUES(?,?,?,?)", [(now, *row) for row in log])
                    db.execute("DELETE FROM log WHERE id <= (SELECT MAX(id) FROM log) - ?", (EVENT_LOG_LIMIT,))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            return state, result

    # -- input ------------------------------------------------------------------------------------------------------
    def on_event(self, kind: str, *, strength: float = 1.0, detail: str = "", hours: float = 0.0,
                 person: str | None = None, partner_adult: bool | None = None) -> dict:
        """Apply one real event (kinds: see emotion_model.KINDS, plus "idle" with `hours` of silence the host knows about).
        `person` is the friend id (never a name or contact detail) whose attachment this event moves and whose standing
        decides how it lands (an insult from a friend hurts, from a stranger it angers)."""
        return self._run([(kind, strength, detail, hours)], person, partner_adult)

    def _run(self, events: list[tuple], person: str | None, partner_adult: bool | None) -> dict:
        """Several events in one transaction (one disk round trip per turn)."""
        for kind, *_ in events:
            if kind != "idle" and kind not in KINDS:
                raise ValueError(f"unknown emotion event: {kind!r}")
        if person is not None and not _PERSON.match(person):
            raise ValueError("person must be a short opaque id")

        def change(state: dict, now: float) -> None:
            for kind, strength, _detail, hours in events:
                self._apply(state, now, kind, _clamp(float(strength), 0.0, 1.5), float(hours), person)

        log = [(k, _clamp(float(st), 0.0, 1.5), d[:80]) for k, st, d, _ in events if k != "idle"]
        state, _ = self._transaction(change, log)
        return self._describe(state, person, partner_adult, _number(self.clock()))

    def _apply(self, state: dict, now: float, kind: str, strength: float, hours: float, person: str | None) -> None:
        if kind == "idle":
            state["last_active"] = min(state["last_active"], now - max(0.0, hours) * 3600.0)
            state["last_tick"] = min(state["last_tick"], state["last_active"])
            self._idle(state, now)
            return
        liking = 0.35 if not person else 0.2 + 0.8 * self._bond(state, person, now)
        deltas, valence, arousal = effect(kind, liking)
        scale = strength
        if now - state["seen"].get(kind, -1e18) < REFRACTORY_SECONDS:
            scale *= REFRACTORY_FACTOR             # the same thing again right away lands softer
        state["seen"][kind] = now
        state["seen"] = {k: v for k, v in state["seen"].items() if now - v < 3600}
        if kind in _FAILS:
            scale *= 1.0 + 0.25 * min(state["streak"], 3)
            state["streak"] += 1
        elif kind in _WINS:
            scale *= 1.0 + 0.2 * min(state["streak"], 5)
            state["streak"] = 0
        e = state["e"]
        for name, delta in deltas.items():
            e[name] = _clamp(e[name] + delta * scale, 0.0, CAPS.get(name, 1.0))
            state["drift"][name] = _clamp(state["drift"][name] + DRIFT_RATE * delta * scale, -MAX_DRIFT, MAX_DRIFT)
        state["valence"] = _clamp(state["valence"] + valence * scale, -1.0, 1.0)
        state["arousal"] = _clamp(state["arousal"] + arousal * scale, 0.0, 1.0)
        if kind in ACTIVE:
            state["last_active"] = state["last_tick"] = now
        if person:
            self._grow_bond(state, person, kind, scale, now)
        if kind == "harmed_someone":                       # she wants to make it right, until she does (or it expires)
            state["amends"] = [a for a in state["amends"] if a[0] != (person or "")][-(MAX_AMENDS - 1):]
            state["amends"].append([person or "", now])
        elif kind == "amends_made":
            state["amends"] = [a for a in state["amends"] if a[0] != (person or "")] if person else state["amends"][1:]

    def on_message(self, text: str, *, person: str | None = None, also: tuple[str, ...] = ()) -> str | None:
        """Someone said something: it ends any silence, and what the words carry (praise, criticism, an insult, sweet
        words, a joke, sadness, goodbye ...) is felt. `also` names further events of the same moment (a voice turn).
        Returns the kind that was detected, if any."""
        found = appraise(text)
        events = [("owner_message", 1.0, "", 0.0), *[(kind, 1.0, "", 0.0) for kind in also]]
        if found is not None:
            events.append((found[0], found[1], "message", 0.0))
        self._run(events, person, None)
        return found[0] if found else None

    def tick(self) -> dict:
        """Let time pass: idle boredom is added up to now. Hosts that stay silent for hours call this now and then."""
        state, _ = self._transaction(None)
        return self._describe(state, None, None, _number(self.clock()))

    # -- output -----------------------------------------------------------------------------------------------------
    def snapshot(self, person: str | None = None, partner_adult: bool | None = None) -> dict:
        """The state as of now (decayed, including the silence so far); read-only. With `person`, their attachment
        shapes the directive; romance (light flirting) is only ever offered when partner_adult is True."""
        with self._lock, self._db() as db:
            now = _number(self.clock())
            state = self._load(db, now)
        self._decay(state, now)
        self._idle(state, now)
        return self._describe(state, person, partner_adult, now)

    def _deviations(self, state: dict) -> dict[str, float]:
        return {name: state["e"][name] - self._baseline(state, name) for name in EMOTIONS}

    def _describe(self, state: dict, person: str | None, partner_adult: bool | None, now: float) -> dict:
        dev = self._deviations(state)
        bond = self._bond(state, person, now)
        pending = bool(state["amends"])
        if pending:
            dev["guilt"] += 0.15                 # still wanting to make it right keeps it in her voice
        directive, picked = build_note(dev, bond, partner_adult)
        dev["affection"] += 0.3 * bond           # a person she is attached to warms her voice (not her words: the note has the bond)
        prosody = prosody_from(dev, state["arousal"])
        drives = drives_from(dev, pending)
        return {"emotions": {n: round(state["e"][n], 3) for n in EMOTIONS}, "bond": round(bond, 3),
                "valence": round(state["valence"], 3), "arousal": round(state["arousal"], 3),
                "dominant": picked[0] if picked else None, "directive": directive, "prosody": prosody,
                "avatar": avatar_from(picked, dev, prosody.energy), "drives": drives, "coping": drives["coping"],
                "amends_pending": pending}

    def history(self, limit: int = 20) -> list[dict]:
        with self._lock, self._db() as db:
            rows = db.execute("SELECT at,kind,strength,detail FROM log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"at": r[0], "kind": r[1], "strength": r[2], "detail": r[3]} for r in rows]

    def reset(self) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM state")
            db.execute("DELETE FROM log")


class _Closing:
    """A sqlite connection that is closed when the `with` block ends (sqlite3's own context manager only commits)."""
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, *exc) -> None:
        self.db.close()


# -- module level API (never raises) -------------------------------------------------------------------------------
_engines: dict[str, EmotionEngine] = {}
_engines_lock = threading.Lock()


def _home(home: str | os.PathLike | None) -> Path:
    if home is not None:
        return Path(home)
    from .desktop_core import app_data
    return app_data()


def default_engine(home: str | os.PathLike | None = None) -> EmotionEngine:
    """The shared engine for the app data folder (or `home`): <home>/emotion.sqlite3."""
    path = str(_home(home) / "emotion.sqlite3")
    with _engines_lock:
        if path not in _engines:
            _engines[path] = EmotionEngine(path)
        return _engines[path]


def enabled(home: str | os.PathLike | None = None) -> bool:
    """The `emotion_enabled` setting in <home>/settings.json (default off)."""
    try:
        raw = json.loads((_home(home) / "settings.json").read_text(encoding="utf-8"))
        return raw.get("emotion_enabled") is True
    except (OSError, ValueError, AttributeError):
        return False


def _safe(name: str, call: Callable[[], object], default: object = None) -> object:
    try:
        return call()
    except Exception as exc:                   # a mood problem must never break a chat, a call or a task
        _log.warning("emotion.%s failed (%s)", name, type(exc).__name__)
        return default


def on_event(kind: str, *, home=None, strength: float = 1.0, detail: str = "", hours: float = 0.0,
             person: str | None = None, only_if_enabled: bool = False):
    """Record a real event. With only_if_enabled, nothing is written unless the setting is on (for hooks that have no
    Settings object, such as the night school promoter)."""
    if only_if_enabled and not enabled(home):
        return None
    return _safe("on_event", lambda: default_engine(home).on_event(kind, strength=strength, detail=detail, hours=hours,
                                                                         person=person))


def on_message(text: str, *, home=None, person: str | None = None, also: tuple[str, ...] = ()) -> str | None:
    return _safe("on_message", lambda: default_engine(home).on_message(text, person=person, also=also))


def current(home=None, *, person: str | None = None, partner_adult: bool | None = None) -> dict | None:
    return _safe("current", lambda: default_engine(home).snapshot(person, partner_adult))


def directive(home=None, *, person: str | None = None, partner_adult: bool | None = None) -> str:
    """The style note for the persona prompt. Romantic/flirty wording only when partner_adult is True."""
    state = current(home, person=person, partner_adult=partner_adult)
    return state["directive"] if state else ""


def tick(home=None) -> dict | None:
    return _safe("tick", lambda: default_engine(home).tick())


def on_run_event(event: dict, *, home=None) -> None:
    """Map a desktop task event (run_task's on_event stream) to an emotion event. Only the ladder's verdict counts here:
    a verified answer is a success, one that needed two or more fix rounds is a bug fixed after many tries, an
    unverified one is a failure."""
    if event.get("event") != "verify_finished":
        return
    rounds = int(event.get("rounds") or 0)
    if event.get("verified") and event.get("fixed") and rounds >= 2:
        on_event("bug_fixed", home=home, strength=min(1.5, 0.5 + 0.25 * rounds), detail=f"ladder fixed in {rounds}")
    elif event.get("verified"):
        on_event("task_success", home=home, strength=0.7, detail="ladder passed")
    else:
        on_event("task_failure", home=home, strength=0.8, detail="ladder failed")


def prosody_of(state: dict | None) -> Prosody | None:
    return state["prosody"] if state else None


def prosody_dict(prosody: Prosody) -> dict:
    return asdict(prosody)
