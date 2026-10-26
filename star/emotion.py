"""STAR's affect: a small persistent emotional state that real events move and time pulls back to a baseline.

It exists so Star sounds like one consistent person across chats, calls and days instead of a fresh, equally
cheerful voice every turn: after a hard-won fix she is a little proud, after five failed attempts a little
clipped, after a long silence a little restless, after praise warm. Nothing here calls a model: the state is a few
numbers in a SQLite file, computed locally (about a millisecond), and the outputs are

    directive()   a short concrete style note for the persona prompt ("" when nothing stands out)
    prosody()     small speech changes for the TTS path (speed, pitch in semitones, pause after a sentence)
    avatar()      a face / expression-cue suggestion for the companion and stream stage

It is an *expression* state: it changes wording, pace and face, it does not make claims about experience and the
text never contains numbers. Host API for other processes (STAR Home, the desktop app, the voice call):

    from star import emotion
    emotion.on_event("task_success")            # also: task_failure, bug_fixed, creative_done, promotion, ...
    emotion.on_message("nice work, thanks")     # detects praise / criticism / thanks in the owner's words
    emotion.current()                           # dict: emotions, valence, arousal, dominant, directive, prosody, avatar
    emotion.tick()                              # call now and then while idle: boredom grows with the silence

The module level functions never raise (an emotion problem must not break a chat). Use `EmotionEngine` directly
in tests (injectable clock and path).
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
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

_log = logging.getLogger(__name__)

HEADING = "MOOD"


def note_line(directive: str) -> str:
    """The note as it goes at the end of a user message: "(mood: a bit frustrated, plain and clipped)"."""
    return f"({HEADING.lower()}: {directive})" if directive else ""

EMOTIONS = ("joy", "pride", "curiosity", "frustration", "boredom", "affection", "nervousness")

# Where each feeling rests when nothing happens (a personal baseline: curious and warm by character), and how
# fast it falls back (hours until half of the distance is gone). Anger and nerves fade fastest, fondness slowest.
BASELINE = {"joy": 0.30, "pride": 0.15, "curiosity": 0.40, "frustration": 0.03, "boredom": 0.08,
            "affection": 0.40, "nervousness": 0.05}
HALF_LIFE_HOURS = {"joy": 3.0, "pride": 6.0, "curiosity": 4.0, "frustration": 2.0, "boredom": 5.0,
                   "affection": 12.0, "nervousness": 1.5}
MOOD_BASELINE = (0.15, 0.35)         # (valence -1..1, arousal 0..1) of the slow background mood
MOOD_HALF_LIFE_HOURS = 8.0
MAX_DRIFT = 0.10                     # the baseline itself shifts a little with experience, never by more than this
DRIFT_RATE = 0.03
REFRACTORY_SECONDS = 10.0            # the same kind of event again within this long counts for 40 %
REFRACTORY_FACTOR = 0.4
# Attachment to one specific person (the friend id a host passes): grows with positive time together with
# diminishing returns, shrinks a little after harsh words, fades only over weeks of no contact.
BOND_GAIN = {"owner_praise": .05, "owner_comfort": .04, "owner_thanks": .04, "creative_done": .03, "bug_fixed": .03, "task_success": .02,
             "voice_turn": .01, "owner_message": .006, "owner_criticism": -.02}
BOND_HALF_LIFE_DAYS = 45.0
MAX_BONDS = 500
BOND_FAMILIAR, BOND_CLOSE, BOND_DEVOTED = 0.25, 0.55, 0.80
_PERSON = re.compile(r"[A-Za-z0-9_.:@\-]{1,64}\Z")
IDLE_AFTER_HOURS = 1.0               # silence shorter than this is not "idle"
EVENT_LOG_LIMIT = 300

# kind: ({emotion: change}, valence change, arousal change). Applied times `strength`.
EVENTS: dict[str, tuple[dict[str, float], float, float]] = {
    "task_success": ({"joy": .18, "pride": .14, "frustration": -.30, "nervousness": -.10, "boredom": -.10}, .12, .05),
    "task_failure": ({"frustration": .14, "joy": -.10, "nervousness": .04, "pride": -.06}, -.12, .08),
    "bug_fixed": ({"pride": .20, "joy": .15, "frustration": -.45, "nervousness": -.10}, .18, .0),
    "creative_done": ({"pride": .22, "joy": .15, "curiosity": .05, "boredom": -.20}, .15, .05),
    "promotion": ({"pride": .15, "joy": .08, "curiosity": .05}, .10, .03),
    "learned_something": ({"curiosity": .15, "joy": .05}, .06, .05),
    "owner_praise": ({"joy": .25, "pride": .20, "affection": .15, "nervousness": -.15, "frustration": -.35}, .25, .10),
    "owner_comfort": ({"frustration": -.35, "nervousness": -.25, "affection": .10, "joy": .05}, .12, -.05),
    "owner_thanks": ({"joy": .10, "affection": .10, "pride": .05}, .10, .03),
    "owner_criticism": ({"nervousness": .18, "pride": -.15, "joy": -.12, "frustration": .06}, -.20, .10),
    "owner_message": ({"boredom": -.12, "curiosity": .02}, 0.0, .03),
    "voice_turn": ({"affection": .03, "boredom": -.06, "curiosity": .01}, .02, .02),
}
# Work outcomes feel bigger after a run of the opposite: the third failure stings more, the fix after many tries is a relief.
_FAILS = ("task_failure",)
_WINS = ("task_success", "bug_fixed")
_ACTIVE = ("task_success", "task_failure", "bug_fixed", "creative_done", "owner_message", "owner_praise",
           "owner_comfort", "owner_thanks", "owner_criticism", "voice_turn")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# -- reading the owner's words -------------------------------------------------------------------------------------
_NOT_ABOUT_STAR = re.compile(r"\b(?:what(?:'s| is)|something|anything|whats) wrong\b|\bwrong with\b", re.I)
_PRAISE = re.compile(
    r"\b(?:good|great|nice|excellent|amazing|awesome|fantastic|brilliant|superb|solid) (?:job|work|stuff|one|call|answer|catch)\b|"
    r"\bwell done\b|\bnailed it\b|\bproud of you\b|\bthat(?:'s| is) (?:great|perfect|awesome|amazing|exactly|brilliant|"
    r"incredible|so good|really good)\b|\bperfect\b|\bimpressive\b|\byou(?:'re| are) (?:the best|amazing|awesome|brilliant|"
    r"great|incredible|a star|so smart)\b|\blove (?:it|this|that)\b|\bwow\b", re.I)
_COMFORT = re.compile(
    r"\bit(?:'s| is) (?:ok|okay|alright|fine)\b|\bdon'?t worry\b|\bno worries\b|\bnot your fault\b|"
    r"\byou(?:'re| are) doing (?:great|well|amazing|fine|your best)\b|\bno big deal\b", re.I)
_THANKS = re.compile(r"\bthank(?:s| you)\b|\bthx\b|\bcheers\b|\bappreciate (?:it|that|you)\b", re.I)
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
_STRONG_PRAISE = re.compile(r"\b(?:amazing|incredible|brilliant|proud of you|nailed it|the best|love (?:it|this|that)|"
                            r"so good|wow)\b", re.I)
MAX_APPRAISED_CHARS = 400            # a pasted log or file is not a remark about Star


def appraise(text: str) -> tuple[str, float] | None:
    """('owner_praise' | 'owner_comfort' | 'owner_criticism' | 'owner_thanks', strength) for a short remark, else None.
    Plain patterns, no model. Criticism wins over praise in the same message ("great, but it's still broken")."""
    text = (text or "").strip()
    if not text or len(text) > MAX_APPRAISED_CHARS:
        return None
    text = _NOT_ABOUT_STAR.sub(" ", text)
    if _NEGATED.search(text) or _CRITICISM.search(text):
        return "owner_criticism", 1.0 if _STRONG_CRITICISM.search(text) else 0.6
    if _COMFORT.search(text):
        return "owner_comfort", 0.9
    if _PRAISE.search(text):
        return "owner_praise", 1.0 if _STRONG_PRAISE.search(text) else 0.65
    if _THANKS.search(text):
        return "owner_thanks", 0.8
    return None


# -- outputs ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Prosody:
    """Changes to apply on top of the voice's own settings: rate multiplies the speed, pitch adds semitones, pause_ms
    adds to the silence after each sentence. All small: a person's voice shifts a little, it does not change character."""
    rate: float = 1.0
    pitch_semitones: float = 0.0
    pause_ms: int = 0
    energy: float = 0.35               # 0..1: how animated the delivery is (for mouth/avatar motion)

    @property
    def neutral(self) -> bool:
        return abs(self.rate - 1.0) < 0.01 and abs(self.pitch_semitones) < 0.05 and abs(self.pause_ms) < 5


_PHRASES = {   # emotion: (noticeable, strong). A state described in a few words, never a line to say, never a number.
    "joy": ("cheerful, a bit playful", "really happy, bright and playful"),
    "pride": ("quietly pleased with the work", "proud of the work, say so simply"),
    "curiosity": ("curious, ask one real question", "fascinated, follow the interesting part"),
    "frustration": ("a bit frustrated, plain and clipped", "annoyed at the problem, flat and short, no forced cheer"),
    "boredom": ("restless after the quiet, a bit wry", "very restless, loose and wry"),
    "affection": ("feeling warm and sweet", "tender, very warm wording"),
    "nervousness": ("a bit on edge, careful", "shaken, quiet and careful"),
}
_CONFLICTS = {frozenset(p) for p in (("joy", "frustration"), ("joy", "nervousness"), ("pride", "nervousness"),
                                     ("pride", "frustration"), ("boredom", "curiosity"), ("boredom", "joy"),
                                     ("affection", "frustration"))}
SALIENT = 0.15                       # how far above its baseline a feeling must be to colour the reply
STRONG = 0.35
MAX_NOTE_WORDS = 12                  # about 12-16 tokens; a bond or romance phrase may use up to MAX_BOND_NOTE_WORDS
MAX_BOND_NOTE_WORDS = 14
_BOND_PHRASES = {   # one per tier; the highest tier reached is used
    BOND_FAMILIAR: "easy and familiar with them",
    BOND_CLOSE: "close to them, affectionate, teasing",
    BOND_DEVOTED: "they matter a lot to you",
}
# Only for a partner the social module has verified as an adult (partner_adult is True): never for None or False.
_FLIRT = "playful flirty banter, tasteful, follow their lead"
_LOVE = "adoring, sweet and sincere"

_FACE = {"joy": "happy", "pride": "happy", "affection": "happy", "curiosity": "looking", "frustration": "oops",
         "nervousness": "oops", "boredom": "idle"}                       # frontend StarMood names (StarFace.tsx)
_CUE = {"joy": "joy", "pride": "joy", "curiosity": "focus", "affection": "nod"}   # star.stream_motion.CUES


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
                "bonds": {}}

    def _load(self, db, now: float) -> dict:
        row = db.execute("SELECT json FROM state WHERE id=1").fetchone()
        if row is None:
            return self._fresh(now)
        try:
            state = json.loads(row[0])
            state["e"] = {k: float(state["e"][k]) for k in EMOTIONS}
            state["drift"] = {k: float(state.get("drift", {}).get(k, 0.0)) for k in EMOTIONS}
            for key in ("t", "valence", "arousal", "last_active", "last_tick"):
                state[key] = float(state[key])
            state["streak"] = int(state.get("streak", 0))
            state["seen"] = {str(k): float(v) for k, v in state.get("seen", {}).items()}
            state["bonds"] = {str(k): [float(v[0]), float(v[1])] for k, v in state.get("bonds", {}).items()}
            if not all(map(math.isfinite, [*state["e"].values(), state["valence"], state["arousal"], state["t"]])):
                raise ValueError("not finite")
            return state
        except (ValueError, KeyError, TypeError) as exc:
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
        state["t"] = max(state["t"], now)

    def _idle(self, state: dict, now: float) -> None:
        """Silence past IDLE_AFTER_HOURS makes her restless: boredom (and a little curiosity) grows, energy sinks."""
        since = max(state["last_tick"], state["last_active"] + IDLE_AFTER_HOURS * 3600.0)
        hours = max(0.0, now - since) / 3600.0
        if hours > 0:
            e = state["e"]
            e["boredom"] = _clamp(e["boredom"] + 0.05 * hours, 0.0, 0.7)
            e["curiosity"] = _clamp(e["curiosity"] + 0.01 * hours, 0.0, 1.0)
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
                   (json.dumps(state),))

    def _transaction(self, change: Callable[[dict, float], object] | None, log: list | None = None):
        with self._lock, self._db() as db:
            now = self.clock()
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
        """Apply one real event (kinds: see EVENTS, plus "idle" with `hours` of silence the host knows about).
        `person` is the friend id (never a name or contact detail) whose attachment this event moves."""
        return self._run([(kind, strength, detail, hours)], person, partner_adult)

    def _run(self, events: list[tuple], person: str | None, partner_adult: bool | None) -> dict:
        """Several events in one transaction (one disk round trip per turn)."""
        for kind, *_ in events:
            if kind != "idle" and kind not in EVENTS:
                raise ValueError(f"unknown emotion event: {kind!r}")
        if person is not None and not _PERSON.match(person):
            raise ValueError("person must be a short opaque id")

        def change(state: dict, now: float) -> None:
            for kind, strength, _detail, hours in events:
                self._apply(state, now, kind, _clamp(float(strength), 0.0, 1.5), float(hours), person)

        log = [(k, _clamp(float(st), 0.0, 1.5), d[:80]) for k, st, d, _ in events if k != "idle"]
        state, _ = self._transaction(change, log)
        return self._describe(state, person, partner_adult, self.clock())

    def _apply(self, state: dict, now: float, kind: str, strength: float, hours: float, person: str | None) -> None:
        if kind == "idle":
            state["last_active"] = min(state["last_active"], now - max(0.0, hours) * 3600.0)
            state["last_tick"] = min(state["last_tick"], state["last_active"])
            self._idle(state, now)
            return
        deltas, valence, arousal = EVENTS[kind]
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
            e[name] = _clamp(e[name] + delta * scale, 0.0, 1.0)
            state["drift"][name] = _clamp(state["drift"][name] + DRIFT_RATE * delta * scale, -MAX_DRIFT, MAX_DRIFT)
        state["valence"] = _clamp(state["valence"] + valence * scale, -1.0, 1.0)
        state["arousal"] = _clamp(state["arousal"] + arousal * scale, 0.0, 1.0)
        if kind in _ACTIVE:
            state["last_active"] = state["last_tick"] = now
        if person:
            self._grow_bond(state, person, kind, scale, now)

    def on_message(self, text: str, *, person: str | None = None, also: tuple[str, ...] = ()) -> str | None:
        """The owner said something: it ends any silence, and praise / criticism / thanks in it is felt. `also` names
        further events of the same moment (a voice turn). Returns the kind that was detected, if any."""
        found = appraise(text)
        events = [("owner_message", 1.0, "", 0.0), *[(kind, 1.0, "", 0.0) for kind in also]]
        if found is not None:
            events.append((found[0], found[1], "message", 0.0))
        self._run(events, person, None)
        return found[0] if found else None

    def tick(self) -> dict:
        """Let time pass: idle boredom is added up to now. Hosts that stay silent for hours call this now and then."""
        state, _ = self._transaction(None)
        return self._describe(state, None, None, self.clock())

    # -- output -----------------------------------------------------------------------------------------------------
    def snapshot(self, person: str | None = None, partner_adult: bool | None = None) -> dict:
        """The state as of now (decayed, including the silence so far); read-only. With `person`, their attachment
        shapes the directive; romance (light flirting) is only ever offered when partner_adult is True."""
        with self._lock, self._db() as db:
            now = self.clock()
            state = self._load(db, now)
        self._decay(state, now)
        self._idle(state, now)
        return self._describe(state, person, partner_adult, now)

    def _deviations(self, state: dict) -> dict[str, float]:
        return {name: state["e"][name] - self._baseline(state, name) for name in EMOTIONS}

    def _describe(self, state: dict, person: str | None, partner_adult: bool | None, now: float) -> dict:
        dev = self._deviations(state)
        bond = self._bond(state, person, now)
        dev["affection"] += 0.3 * bond           # a person she is attached to warms her voice before anything happens
        ranked = sorted((n for n in EMOTIONS if dev[n] >= SALIENT), key=lambda n: -dev[n])
        picked: list[str] = []
        for name in ranked:
            if all(frozenset((name, other)) not in _CONFLICTS for other in picked):
                picked.append(name)
            if len(picked) == 2:
                break
        phrases = [_PHRASES[n][1 if dev[n] >= STRONG else 0] for n in picked]
        tier = max((t for t in _BOND_PHRASES if bond >= t), default=None)
        extra = []
        if partner_adult is True:                # the age gate is the social module's; None and False never get romance
            if bond >= BOND_DEVOTED:
                extra.append(_LOVE)
            if bond >= BOND_CLOSE or dev["affection"] >= STRONG:
                extra.append(_FLIRT)
        if tier is not None:
            extra.append(_BOND_PHRASES[tier])
        # priority: the lead feeling, then romance / bond wording, then the second feeling; stop at the word budget
        queue = phrases[:1] + extra + phrases[1:]
        note: list[str] = []
        for phrase in queue:
            limit = MAX_BOND_NOTE_WORDS if extra else MAX_NOTE_WORDS
            if len(" ".join(note + [phrase]).split()) <= limit or not note:
                note.append(phrase)
        directive = "; ".join(note)
        a = state["arousal"]
        prosody = Prosody(
            rate=round(_clamp(1.0 + 0.10 * (a - MOOD_BASELINE[1]) + 0.05 * dev["nervousness"] + 0.03 * dev["frustration"]
                              - 0.12 * max(0.0, dev["boredom"]) - 0.05 * dev["affection"], 0.92, 1.08), 3),
            pitch_semitones=round(_clamp(1.2 * dev["joy"] + 0.6 * dev["pride"] + 0.8 * dev["nervousness"]
                                         - 1.0 * dev["frustration"] - 0.8 * max(0.0, dev["boredom"])
                                         - 0.3 * dev["affection"], -0.8, 0.8), 2),
            pause_ms=int(_clamp(round(150 * max(0.0, dev["boredom"]) + 60 * dev["affection"] - 120 * dev["frustration"]
                                      - 60 * (a - MOOD_BASELINE[1])), -40, 60)),
            energy=round(_clamp(a + 0.3 * dev["joy"] + 0.2 * dev["curiosity"] - 0.3 * max(0.0, dev["boredom"]), 0.0, 1.0), 2))
        lead = picked[0] if picked else None
        avatar = {"face": _FACE.get(lead, "idle") if lead else "idle", "cue": _CUE.get(lead) if lead else None,
                  "strength": round(_clamp(dev[lead] * 1.6, 0.0, 1.0), 2) if lead else 0.0, "energy": prosody.energy}
        return {"emotions": {n: round(state["e"][n], 3) for n in EMOTIONS}, "bond": round(bond, 3),
                "valence": round(state["valence"], 3), "arousal": round(state["arousal"], 3),
                "dominant": lead, "directive": directive, "prosody": prosody, "avatar": avatar}

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
