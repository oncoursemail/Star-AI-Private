"""Per-turn memory recall: only when the message calls for it, at most two short lines, honest when nothing is stored.

What failed before (docs/agents/human-voice-20261025.md): a block of counts that was always present made replies worse
and cost +1.4 s. So here: (1) nothing unless the message has a cue (a question about the past, "remember", a name or topic
she has stored something about, the first message of a conversation); (2) at most MAX_LINES lines of about MAX_LINE
characters, the whole note under MAX_CHARS (about 40 tokens); (3) a concrete line or nothing; (4) a question about
something she was never told gets an honest hint instead of an invented answer (LongMemEval's abstention case).

Ranking = how well the words match x forgetting curve (store.retention: e^(-age/S), S grows each time a memory is used)
x importance. Search is SQLite FTS5 over her episodes, which `sync_person` fills from friend memory (facts they told her,
what they said) without touching the chat path's own code. Nothing here calls a model: about 5 ms.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..social import rules
from .store import Episode, InnerStore, overlap, person_key, retention, tokens

MAX_LINES = 2
MAX_LINE = 100
MAX_CHARS = 190
MIN_RETENTION = 0.12            # a memory this faded is not brought up by itself
MIN_OVERLAP_ASKED = 0.34
MIN_OVERLAP_TWO_WORDS = 0.3
MIN_OVERLAP_VOLUNTEER = 0.6     # without a question: a strong single-word match, or at least two matching words
FIRST_TURN_DAYS = 14

# A question about the past or about what she knows of them.
ASK = re.compile(
    r"\b(?:remember|remind me|recall|told you|tell you before|did i (?:tell|say|mention)|do you know (?:my|what|who|where|when)|"
    r"what(?:'s| is| was| were) my|who(?:'s| is| was) my|last time|the other day|yesterday|last (?:week|night|month|year)|"
    r"earlier|a while ago|what did (?:i|we)|how did (?:it|that|the|my) \w+ ?\w* go|where were we|you know (?:my|that|about)|"
    r"(?:where|what|who|which|when) (?:do|did|am|was|have|are) i)\b",
    re.I)
# The part of ASK that is really "do you have this stored?": no result means an honest "I don't think you told me".
STRICT_ASK = re.compile(r"\b(?:remember|told you|did i (?:tell|say|mention)|do you know (?:my|what|who|where|when)|"
                        r"what(?:'s| is| was| were) my|who(?:'s| is| was) my|what did i)\b", re.I)
_CUE_WORDS = frozenset("remember recall told tell said say mention mentioned yesterday earlier ago week night month year "
                       "time remind know did again".split())
_FUTURE = re.compile(r"\b(?:tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|"
                     r"this weekend|exam|test|interview|appointment|birthday|trip|moving|surgery|match|tournament|"
                     r"presentation|deadline|going to|gonna|have to)\b", re.I)
_EMOTIVE = re.compile(r"\b(?:nervous|worried|scared|anxious|excited|sad|happy|angry|stressed|finally|proud|sorry|"
                      r"miss(?:ed)?|love|hate|cried|funeral|died|passed|failed|won|lost|promoted|fired|sick|hospital)\b", re.I)
ABSTAIN_NOTE = "(nothing stored about this: say honestly you don't think they told you)"


@dataclass
class Recalled:
    lines: list[str] = field(default_factory=list)
    ids: list[int] = field(default_factory=list)
    abstain: bool = False


def rate_importance(text: str) -> tuple[float, float]:
    """(importance, emotion) of one thing someone said, by rule: dated plans and feelings matter more, chit-chat less."""
    importance, emotion = 0.25, 0.0
    if _EMOTIVE.search(text):
        importance += 0.2
        emotion = 0.6
    if _FUTURE.search(text):
        importance += 0.2
    if re.search(r"\bremember\b", text, re.I):
        importance += 0.3
    if len(text) > 80:
        importance += 0.05
    return min(importance, 0.9), emotion


def sync_person(store: InnerStore, memory, person) -> int:
    """Reconcile retained source records, including deletion and changed age restrictions."""
    try:
        person = memory.get(person.id)
    except KeyError:
        return 0
    pkey = person_key(memory, person)
    if not pkey:
        return 0
    wanted = {}
    rows = memory.fact_records(person,
                               interests_only=rules.age_status(person) in ("minor", "doubt"))
    for fid, text, ts in rows:
        importance, emotion = rate_importance(text)
        wanted[f"f:{pkey}:{fid}"] = ("fact", text, ts, max(0.6, importance), emotion)
    if rules.age_status(person) in ("adult", "unknown"):
        rows = memory.moment_records(person)
        for mid, platform, line, ts in rows:
            if platform == "roblox" or not line.startswith("they: "):
                continue
            body = line[6:].strip()
            if len(body) >= 24:
                importance, emotion = rate_importance(body)
                wanted[f"m:{pkey}:{mid}"] = ("moment", body, ts, importance, emotion)
    added = 0
    with store._lock:
        existing = store.db.execute("SELECT id,src,kind,text,ts FROM episodes WHERE pkey = ?", (pkey,)).fetchall()
        stale = []
        for eid, src, kind, text, ts in existing:
            if not isinstance(src, str) or not src.startswith((f"f:{pkey}:", f"m:{pkey}:")):
                continue
            record = wanted.get(src)
            if (record is None or kind != record[0] or ts != record[2]
                    or text != " ".join(str(record[1]).split())[:300]):
                stale.append(eid)
        if stale:
            store.delete_episodes(stale)
        for src, (kind, text, ts, importance, emotion) in wanted.items():
            added += store.add_episode(pkey, text, kind=kind, ts=ts, importance=importance,
                                       emotion=emotion, src=src) is not None
    if person_key(memory, person) != pkey:
        store.delete_person(pkey)
        return 0
    return added


def ago(ts: float, now: float) -> str:
    days = int((now - ts) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{days // 7} weeks ago"
    return "months ago"


def line_for(episode: Episode, now: float) -> str:
    who = {"home_verified": "activity reported success", "home_unverified": "unverified activity report",
           "home": "legacy unverified report"}.get(episode.kind, "they said")
    prefix = f"{ago(episode.ts, now)} {who}: "
    room = MAX_LINE - len(prefix)
    text = episode.text if len(episode.text) <= room else episode.text[:room - 1].rstrip() + "…"
    return prefix + text


def _ranked(store: InnerStore, query: list[str], pkey: str, now: float, *, asked: bool) -> list[tuple[float, Episode]]:
    out = []
    for ep in store.search(query, pkey):
        rel = overlap(query, ep.text)
        matched = sum(1 for q in set(query) if q in set(tokens(ep.text)))
        need = MIN_OVERLAP_ASKED if asked else MIN_OVERLAP_TWO_WORDS if matched >= 2 else MIN_OVERLAP_VOLUNTEER   # unasked: two words or a strong match
        r = retention(ep, now)
        if rel < need or r < MIN_RETENTION:
            continue
        out.append((rel * r * (0.4 + 0.6 * ep.importance), ep))
    return sorted(out, key=lambda pair: -pair[0])


def open_thread(store: InnerStore, pkey: str, now: float) -> Episode | None:
    """First message of a conversation: the one dated or emotional thing from the last two weeks that is still open."""
    best, best_score = None, 0.0
    for ep in store.episodes(pkey=pkey, since=now - FIRST_TURN_DAYS * 86400, limit=200):
        if ep.importance < 0.45 or ep.ts > now - 3600 or not (_FUTURE.search(ep.text) or ep.emotion > 0.3):
            continue
        score = retention(ep, now) * ep.importance
        if score > best_score:
            best, best_score = ep, score
    return best


def recall(store: InnerStore, pkey: str, text: str, *, now: float | None = None, first_turn: bool = False,
           limit: int = MAX_LINES) -> Recalled:
    """The memory lines (and ids to strengthen) for one message; empty when the message has no cue. pkey '' is the owner's
    chat and her own life (home sessions)."""
    now = time.time() if now is None else now
    asked = bool(ASK.search(text))
    query = [t for t in tokens(text) if t not in _CUE_WORDS]
    picks = [ep for _, ep in _ranked(store, query, pkey, now, asked=asked)][:limit]
    if first_turn and len(picks) < limit:
        thread = open_thread(store, pkey, now)
        if thread is not None and thread.id not in {p.id for p in picks}:
            picks.append(thread)
    if not picks:
        return Recalled(abstain=bool(STRICT_ASK.search(text)))
    return Recalled([line_for(p, now) for p in picks], [p.id for p in picks])


def note(lines: list[str], *, abstain: bool = False, heading: str = "maybe useful, only if it fits") -> str:
    """The suffix for the user message: '(maybe useful, only if it fits: a; b)', capped at MAX_CHARS."""
    if not lines:
        return ABSTAIN_NOTE if abstain else ""
    out = f"({heading}: " + "; ".join(lines) + ")"
    if len(out) > MAX_CHARS:
        out = out[: MAX_CHARS - 2].rstrip(" ;,.") + "…)"
    return out
