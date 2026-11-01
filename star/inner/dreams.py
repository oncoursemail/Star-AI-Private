"""Her dreams: written at night from the day's leftovers, half-forgotten by the end of the morning.

Why it is built like this (sources and caveats in docs/agents/inner-life-20261026.md):
  * continuity hypothesis: dream content reflects waking life, though unevenly (Schredl & Hofmann 2003, Consciousness and
    Cognition 12:298-308), so the fragments are her own day: people she talked to, games and videos, curiosity items she has
    not resolved, and strong feelings;
  * dreaming of recent material goes with better sleep-dependent consolidation of it (Wamsley et al. 2010, Current Biology
    20:850-855), so recent, unfinished and emotional items get a higher weight (the weights are a design choice, not a result);
  * the dream-lag effect: day events return in dreams about 6 days later (Nielsen & Powell 1989; replications are mixed), so
    one older item may join;
  * dream logic: places merge, people swap, impossible things go unremarked, and the dream is mostly forgotten on waking.
The brain writes the narrative at night in the background (no chat latency). Vividness is computed here from the fragments
(emotion, unfinished business, a little chance), not asked from the model. On waking she remembers a vivid dream fully, a
middling one only as a gist ("something about a giant Minecraft cat..."), and the rest not at all; the memory fades over the
morning (`level`). A remembered dream nudges her mood once (emotion.on_event), can come up in chat ("how did you sleep?", or
when a close friend who is in it writes first) and can become a message to a close friend ("i had the weirdest dream about
you"), never romantic unless the age rules allow it with that person, and always labelled and worded as a dream: she never
says it happened.
"""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass

from ..persona import leaked_reasoning, strip_reasoning
from ..redact import redact_text
from ..social import rules
from . import structured
from . import reachout
from .recall import _FUTURE
from .store import InnerStore, resolve, wake_time_after

FULL_AT = 0.55            # remembered level (vividness faded by the morning) for a full memory
HALF_AT = 0.22            # a gist below FULL_AT, nothing below HALF_AT
FADE_HOURS = 3.0          # time constant of the morning fade
MAX_DREAM = 620
ASKED = re.compile(r"\b(?:dream\w*|nightmare|slept|sleep|last night|how did you sleep|wake up|woke up)\b", re.I)
CLAIMS_REAL = re.compile(r"\b(?:really|actually|truly)\s+happened\b|\bit\s+was\s+real\b|\bthis\s+(?:really\s+)?happened\b|"
                         r"\bi\s+(?:really|actually)\s+(?:met|saw|went)\b", re.I)
_FEELING = {"task_failure": "feeling stuck and frustrated", "bug_fixed": "the relief of a fix finally working",
            "creative_done": "pride in something she made", "owner_praise": "being praised",
            "owner_criticism": "being told off", "task_success": "something finally working",
            "owner_comfort": "being comforted", "promotion": "something she made going out into the world"}
# The mood nudge when she wakes remembering a dream: these are existing emotion event kinds (star/emotion.py has no dream
# kind); small strengths, because a dream is not an achievement or a failure.
NUDGE_PLEASANT, NUDGE_UNSETTLING = "learned_something", "task_failure"


@dataclass(frozen=True)
class Fragment:
    text: str
    kind: str                 # person | home | curiosity | feeling | old
    weight: float
    emotional: float          # 0-1
    unfinished: float         # 0-1
    pkey: str = ""


def _first(name: str) -> str:
    return (name.split() or ["someone"])[0][:20]


def gather(store: InnerStore, memory, now: float, *, history=(), curiosity_items=(), emotion_events=(),
           rng: random.Random | None = None) -> list[Fragment]:
    rng = rng or random.Random()
    out: list[Fragment] = []
    for ep in store.episodes(since=now - 36 * 3600, limit=300):
        if not ep.pkey or ep.kind not in ("fact", "moment"):
            continue
        person = resolve(memory, ep.pkey)
        if person is None:
            continue
        out.append(Fragment(f"{_first(person.name)}: {ep.text[:90]}", "person", 0.3 + ep.importance + ep.emotion,
                            ep.emotion, 1.0 if _FUTURE.search(ep.text) else 0.0, ep.pkey))
    for row in history:
        good = bool(row.get("verified"))
        out.append(Fragment(f"{str(row.get('interest') or 'something').replace('_', ' ')}: {str(row.get('summary') or '')[:90]}",
                            "home", 0.5 if good else 1.1, 0.35 if good else 0.6, 0.0 if good else 1.0))
    for item in curiosity_items:
        out.append(Fragment(f"something she could not work out: {str(getattr(item, 'topic', item))[:90]}", "curiosity", 0.9,
                            0.2, 1.0))
    for event in emotion_events:
        strength = float(event.get("strength", 0))
        if strength >= 0.7 and event.get("kind") in _FEELING:
            out.append(Fragment(_FEELING[event["kind"]], "feeling", 0.5 + strength, min(1.0, strength / 1.5),
                                1.0 if event["kind"] == "task_failure" else 0.0))
    old = [e for e in store.episodes(since=now - 9 * 86400, limit=300)
           if e.ts <= now - 5 * 86400 and e.importance >= 0.5 and e.pkey and resolve(memory, e.pkey) is not None]
    if old and rng.random() < 0.35:
        ep = rng.choice(old)
        person = resolve(memory, ep.pkey)
        if person is not None:
            out.append(Fragment(f"{_first(person.name)}: {ep.text[:90]}", "old", 0.4, ep.emotion, 0.0, ep.pkey))
    return out


def pick(fragments: list[Fragment], rng: random.Random, k: int) -> list[Fragment]:
    """Weighted sampling without replacement (Efraimidis-Spirakis keys): heavier, i.e. emotional and unfinished, more often."""
    keyed = sorted(fragments, key=lambda f: -(rng.random() ** (1.0 / max(f.weight, 1e-6))))
    return keyed[:k]


def vividness(picked: list[Fragment], rng: random.Random) -> float:
    if not picked:
        return 0.0
    emotional = sum(f.emotional for f in picked) / len(picked)
    unfinished = sum(f.unfinished for f in picked) / len(picked)
    return round(min(1.0, max(0.05, 0.2 + 0.45 * emotional + 0.25 * unfinished + (0.1 if len(picked) >= 4 else 0)
                               + rng.uniform(-0.1, 0.15))), 3)


SYSTEM = (
    "You are Star's sleeping mind. Write ONE short dream she had tonight from the fragments below. Dream logic: places "
    "merge into each other, people swap faces or roles, impossible things happen and nobody is surprised, time jumps, "
    "things change size. Concrete surreal images, no moral, no explanation. First person, past tense, 3 to 6 sentences, "
    "under 600 characters. Use the fragments as raw material and bend them; invent no real facts about real people. Never "
    "romantic or sexual. Never say it really happened. Reply with JSON only: {\"dream\": \"...\", \"gist\": \"at most five "
    "words naming the strangest image\", \"valence\": a number from -1 (nightmare) to 1 (lovely), \"tell\": \"one casual "
    "sentence she could send a friend who is in it, saying it was a dream, or an empty string\"}.")


def _romantic_ok(memory, pkeys: list[str]) -> bool:
    for pkey in pkeys:
        person = resolve(memory, pkey)
        if person is not None and rules.romance_mode("discord", person).romance != "allowed":
            return False
    return True


def _clean(raw: str, memory, pkeys: list[str]) -> dict | None:
    data = structured.parse(strip_reasoning(raw or ""))
    dream = redact_text(" ".join(str(data.get("dream") or "").split()))[:MAX_DREAM]
    if len(dream) < 40 or leaked_reasoning(dream) or CLAIMS_REAL.search(dream):
        return None
    tell = " ".join(str(data.get("tell") or "").split())
    if rules.ROMANTIC.search(dream + " " + tell) and not _romantic_ok(memory, pkeys):
        return None
    try:
        valence = min(1.0, max(-1.0, float(data.get("valence", 0))))
    except (TypeError, ValueError):
        valence = 0.0
    gist = " ".join(str(data.get("gist") or "").split())[:50] or " ".join(dream.split()[:5])
    return {"dream": dream, "gist": gist, "valence": valence, "tell": tell[:180]}


def generate(store: InnerStore, memory, complete, now: float, rng: random.Random, *, history=(), curiosity_items=(),
             emotion_events=()) -> dict | None:
    """Tonight's dream: stored with its vividness and the people in it. None on a blank night (nothing to dream from, or the
    model gave nothing usable twice). One dream a night."""
    from .store import night_of
    night = night_of(now)
    if store.db.execute("SELECT 1 FROM dreams WHERE night = ?", (night,)).fetchone():
        return None
    fragments = gather(store, memory, now, history=history, curiosity_items=curiosity_items,
                       emotion_events=emotion_events, rng=rng)
    if not fragments:
        return None
    picked = pick(fragments, rng, rng.randint(3, 5))
    pkeys = list(dict.fromkeys(f.pkey for f in picked if f.pkey))
    user = "Fragments from her day:\n" + "\n".join(f"- {f.text}" for f in picked)
    cleaned = None
    for attempt in range(2):
        try:
            prompt = user + ("\n(Keep it gentle and unromantic.)" if attempt else "")
            cleaned = _clean(structured.call(complete, SYSTEM, prompt, structured.DREAM_SCHEMA, "dream"), memory, pkeys)
        except Exception:
            cleaned = None
        if cleaned:
            break
    if cleaned is None:
        return None
    vivid = vividness(picked, rng)
    with store._lock:
        cur = store.db.execute(
            "INSERT INTO dreams (night, text, gist, valence, vividness, pkeys, created, woke_at) VALUES (?,?,?,?,?,?,?,?)",
            (night, cleaned["dream"], cleaned["gist"], cleaned["valence"], vivid, json.dumps(pkeys), now, wake_time_after(now)))
        store.db.commit()
    seed_id = None
    if cleaned["tell"] and pkeys and vivid >= HALF_AT:
        weights: dict[str, float] = {}
        for f in picked:
            if f.pkey:
                weights[f.pkey] = weights.get(f.pkey, 0) + f.weight
        for pkey in sorted(weights, key=lambda k: -weights[k]):
            person = resolve(memory, pkey)
            if person is not None:
                seed_id = reachout.add_seed(store, memory, person, cleaned["tell"], kind="dream", reason="dream about them",
                                            in_days=0.0, ttl_days=1.0, now=now)
                if seed_id:
                    break
    return {"id": cur.lastrowid, "vividness": vivid, "gist": cleaned["gist"], "people": len(pkeys), "seed": seed_id}


# -- waking -----------------------------------------------------------------------------------------------------------
def level(vivid: float, woke_at: float, now: float) -> str:
    """'asleep' before waking, then 'full', 'half' or 'gone' as the morning goes by (vividness x e^(-t/3h))."""
    if now < woke_at:
        return "asleep"
    remembered = vivid * math.exp(-(now - woke_at) / 3600.0 / FADE_HOURS)
    return "full" if remembered >= FULL_AT else "half" if remembered >= HALF_AT else "gone"


def remembered(store: InnerStore, now: float) -> tuple[dict, str] | None:
    """The dream she still has this morning, with how much of it ('full' or 'half'); None when it is gone or there is none."""
    row = store.db.execute("SELECT id, text, gist, valence, vividness, pkeys, woke_at, nudged FROM dreams "
                           "ORDER BY created DESC LIMIT 1").fetchone()
    if row is None:
        return None
    state = level(row[4], row[6], now)
    if state not in ("full", "half"):
        return None
    return ({"id": row[0], "text": row[1], "gist": row[2], "valence": row[3], "vividness": row[4],
             "pkeys": json.loads(row[5]), "nudged": bool(row[7])}, state)


def wake(store: InnerStore, now: float, *, emotion=None) -> dict | None:
    """Call in the morning (night.tick does): if she remembers the dream, her mood moves a little, once."""
    found = remembered(store, now)
    if found is None or found[0]["nudged"]:
        return None
    dream, state = found
    if emotion is None:
        from .. import emotion as emotion_module
        emotion = emotion_module
    kind = NUDGE_PLEASANT if dream["valence"] > 0.2 else NUDGE_UNSETTLING if dream["valence"] < -0.2 else None
    if kind is not None:
        strength = (0.25 + 0.4 * dream["vividness"]) * (1.0 if state == "full" else 0.5)
        if kind == NUDGE_UNSETTLING:
            strength *= 0.6
        try:
            emotion.on_event(kind, strength=round(strength, 3), detail="woke from a dream")
        except Exception:
            pass
    with store._lock:
        store.db.execute("UPDATE dreams SET nudged = 1 WHERE id = ?", (dream["id"],))
        store.db.commit()
    return {"id": dream["id"], "level": state, "nudge": kind}


def dream_line(store: InnerStore, memory, person, pkey: str, text: str, now: float, *, first_turn: bool = False) -> str:
    """The line about her dream for this message, or ''. When someone asks about sleep or dreams, any person gets it; the first
    message of a conversation gets it only from a close friend who is in the dream. Always labelled as a dream."""
    found = remembered(store, now)
    if found is None:
        return ""
    dream, state = found
    asked = bool(ASKED.search(text))
    if not asked and not (first_turn and pkey and pkey in dream["pkeys"] and person is not None
                          and reachout.is_close(memory, person, now)):
        return ""
    if state == "full":
        return f"dream last night, not real: {dream['text'][:90]}"
    return f"half-remembered dream, not real: something about {dream['gist']}..."
