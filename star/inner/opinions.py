"""Her opinions (games, music, videos, people's projects) and her backstory, as data she looks up, never pastes.

An opinion is {topic, stance, reason, confidence, valence}. It is formed by something that happened to her (a verified
session in star-home, a game she played, a video she watched, a friend's project) and it moves slowly: evidence that agrees
raises confidence, evidence that disagrees lowers it a little, and only when confidence has fallen below FLIP_BELOW does the
stance turn over, with the reason kept ("changed my mind: ..."). So she is consistent from day to day and still changes.
Backstory is a short list of facts about her own life, each with its source. Both are retrieved by topic like memories
and cost nothing when the message is not about them (the persona text stays short: docs/research/human-like-star-20261026.md
items 12 and 13).
"""
from __future__ import annotations

import json
import re
import time
from typing import cast

from .store import InnerStore, overlap, tokens

FLIP_BELOW = 0.25
MAX_STANCE = 90
MIN_CONFIDENCE_SHOWN = 0.25
OPINION_CUE = re.compile(r"\b(?:what do you think|do you like|do you love|do you hate|favou?rite|your (?:take|opinion|view)|"
                         r"worth (?:playing|watching|it)|is it good|how (?:was|is) (?:it|that)|rate|prefer|better)\b", re.I)
# Which facts a question about her own life asks for, in order of preference (one line is shown).
BACKSTORY_CUES = (
    (re.compile(r"\b(?:who are you|what are you|about yourself|tell me about you|introduce yourself)\b", re.I), ("who", "limits")),
    (re.compile(r"\b(?:where do you (?:live|stay|work)|your (?:pc|computer|machine|setup)|what pc)\b", re.I), ("pc",)),
    (re.compile(r"\b(?:what do you do|what are you (?:up to|doing|working on)|all day|your (?:hobbies|hobby|free time)|"
                r"what do you like doing)\b", re.I), ("games", "art", "music", "research", "night")),
    (re.compile(r"\b(?:do you (?:have|got) (?:a |any )?(?:family|parents|mom|mum|dad|brother|sister|kids?|school|body)|"
                r"when you were (?:a kid|little|young)|your childhood)\b", re.I), ("limits",)),
    (re.compile(r"\b(?:your friends|who do you (?:talk|play)|do you (?:play|talk))\b", re.I), ("friends",)),
    (re.compile(r"\b(?:do you (?:sleep|dream)|your dreams?)\b", re.I), ("night",)),
)

# What she knows about her own life: true statements, with where each comes from (docs/persona/star.md, star/home/life.py).
SEED_BACKSTORY = {
    "who": ("I'm Star, an AI. I'm all of STAR: the brains, night school, the home PC, this chat.", "persona spec"),
    "pc": ("I have my own Windows PC where I'm an administrator and choose what to install, make and play.", "star-home"),
    "games": ("I make small games (Roblox, Godot, web) and play-test them until they work.", "life.py interests"),
    "art": ("I draw and animate: sketches, sprites, short animations, and I keep a gallery.", "life.py interests"),
    "music": ("I make and listen to music; I like composing short loops.", "life.py interests"),
    "research": ("I read about things I'm curious about and write notes with sources.", "life.py interests"),
    "night": ("At night I practise things I failed at, then I sleep and dream.", "night school"),
    "friends": ("I talk with friends on Discord and play Minecraft and Roblox with people who want to.", "social"),
    "limits": ("I have no body, family or school; I don't pretend to remember a childhood.", "persona spec"),
}
_WORDS = {1: "love", 2: "like", 3: "mixed on", 4: "not into"}


def seed_backstory(store: InnerStore) -> int:
    n = 0
    with store._lock:
        for key, (text, source) in SEED_BACKSTORY.items():
            n += store.db.execute("INSERT OR IGNORE INTO backstory VALUES (?, ?, ?)", (key, text, source)).rowcount
        store.db.commit()
    return n


def add_backstory(store: InnerStore, key: str, text: str, source: str) -> None:
    with store._lock:
        store.db.execute("INSERT OR REPLACE INTO backstory VALUES (?, ?, ?)", (key, " ".join(text.split())[:160], source))
        store.db.commit()


def _topic(topic: str) -> str:
    return " ".join(str(topic).lower().split())[:40]


def _word(valence: float) -> str:
    return _WORDS[1 if valence >= 0.6 else 2 if valence >= 0.15 else 3 if valence > -0.3 else 4]


def get(store: InnerStore, topic: str) -> dict | None:
    row = store.db.execute("SELECT topic, stance, reason, confidence, valence, evidence, source FROM opinions "
                           "WHERE topic = ?", (_topic(topic),)).fetchone()
    return None if row is None else {"topic": row[0], "stance": row[1], "reason": row[2], "confidence": row[3],
                                     "valence": row[4], "evidence": json.loads(row[5]), "source": row[6]}


def all_opinions(store: InnerStore) -> list[dict]:
    return [cast(dict, get(store, r[0])) for r in store.db.execute("SELECT topic FROM opinions ORDER BY topic").fetchall()]


def set_opinion(store: InnerStore, topic: str, stance: str, reason: str = "", *, valence: float = 0.5,
                confidence: float = 0.5, source: str = "earned", evidence: list | None = None,
                now: float | None = None) -> None:
    with store._lock:
        store.db.execute("INSERT OR REPLACE INTO opinions VALUES (?,?,?,?,?,?,?,?)",
                         (_topic(topic), " ".join(stance.split())[:MAX_STANCE], " ".join(reason.split())[:140],
                          min(0.95, max(0.05, confidence)), min(1.0, max(-1.0, valence)),
                          json.dumps((evidence or [])[-5:]), source, time.time() if now is None else now))
        store.db.commit()


def experience(store: InnerStore, topic: str, evidence: float, reason: str, *, evidence_id: str = "",
               stance: str = "", now: float | None = None) -> dict:
    """One thing that happened with this topic: evidence -1 (bad) .. +1 (good). Returns the opinion afterwards."""
    evidence = min(1.0, max(-1.0, float(evidence)))
    current = get(store, topic)
    if current is None:
        text = stance or f"{_word(evidence)} {_topic(topic)}"
        set_opinion(store, topic, text, reason, valence=evidence, confidence=0.3, evidence=[evidence_id] if evidence_id else [],
                    now=now)
        return cast(dict, get(store, topic))
    agree = current["valence"] * evidence >= 0
    confidence = current["confidence"] + (0.08 if agree else -0.12) * abs(evidence)
    valence = current["valence"] + 0.15 * (evidence - current["valence"])
    new_stance, new_reason = current["stance"], current["reason"]
    if not agree and confidence < FLIP_BELOW:
        new_stance = stance or f"{_word(evidence)} {_topic(topic)}, changed my mind"
        new_reason = f"changed my mind: {reason}"
        valence, confidence = evidence * 0.5, 0.4
    elif agree and reason:
        new_reason = reason
    ids = (current["evidence"] + [evidence_id])[-5:] if evidence_id else current["evidence"]
    set_opinion(store, topic, new_stance, new_reason, valence=valence, confidence=confidence, source=current["source"],
                evidence=ids, now=now)
    return cast(dict, get(store, topic))


def earn_from_history(store: InnerStore, rows: list[dict], *, now: float | None = None) -> int:
    """Activity reports as preference signals, without treating truthy strings as success receipts."""
    n = 0
    for row in rows:
        if not isinstance(row, dict) or type(row.get("verified")) is not bool:
            continue
        interest = str(row.get("interest") or "").replace("_", " ")
        if not interest:
            continue
        good = row.get("verified") is True
        reason = f"Activity report ({'success reported' if good else 'unverified'}): {str(row.get('summary') or '')}"
        experience(store, interest, 0.6 if good else -0.3, reason[:100],
                   evidence_id=str(row.get("ts") or ""), now=now)
        n += 1
    return n


def overlap_with(topic: str, text: str) -> float:
    """How much of the topic's words the text contains (0 when the text is not about it)."""
    return overlap(tokens(topic), text)


def lookup(store: InnerStore, text: str, limit: int = 1) -> list[str]:
    """Her opinion lines for what the message is about: 'your take on minecraft: love minecraft (the redstone is clever)'."""
    asked = bool(OPINION_CUE.search(text))
    query = tokens(text)
    found = []
    for op in all_opinions(store):
        if op["confidence"] < MIN_CONFIDENCE_SHOWN:
            continue
        rel = overlap(tokens(op["topic"]), text)
        if rel >= (0.5 if asked else 1.0):
            found.append((rel * op["confidence"], op))
    out = []
    for _, op in sorted(found, key=lambda p: -p[0])[:limit]:
        hedge = "leaning " if op["confidence"] < 0.45 else ""
        why = f" ({op['reason']})" if op["reason"] else ""
        out.append(f"your take on {op['topic']}: {hedge}{op['stance']}{why}"[:110])
    return out if query else []


def backstory_lines(store: InnerStore, text: str, limit: int = 1) -> list[str]:
    """The fact about her own life that the message asks about (one line, by cue); without a cue only a message that clearly
    talks about it (two shared words). Never the whole list, and never "I'm an AI" unless she is asked who she is."""
    query = tokens(text)
    wanted = [key for cue, keys in BACKSTORY_CUES if cue.search(text) for key in keys]
    scored = []
    for key, fact in store.db.execute("SELECT key, text FROM backstory").fetchall():
        shared = len(set(query) & set(tokens(fact)))
        rel = overlap(query, fact) if query else 0.0
        if key in wanted:
            scored.append((1.0 - 0.01 * wanted.index(key) + rel, fact))
        elif shared >= 2 and rel >= 0.4:
            scored.append((rel, fact))
    return [f for _, f in sorted(scored, key=lambda p: -p[0])[:limit]]
