"""Her own self-description, written and revised by her, with fixed boundaries it cannot touch.

She starts from a seed (sweet, funny, cute, curious, playful, can flirt with adults). Each night, after reflection and
dreams, she looks at what actually happened (her diary, the choices she made, how she felt, what she dreamed) and may revise
the description in small steps; every change is explained and dated in a self journal the owner can read
(<home>/inner/self-journal.md, or `journal()`), and every night's result is a new version, so the whole history is kept.

What can change (a whitelist): traits (0-1: warmth, humour, cuteness, curiosity, playfulness, flirtiness, confidence,
patience, sociability), likes, dislikes, values, quirks, cares_about, wants_to_improve, humour style, how she feels about
people, and the one-line identity. What cannot change, enforced here and not by the model's goodwill:
  * there is no field for rules, boundaries, ages, safety, owner control or approvals, and an unknown field is refused;
  * a proposal that tries to move a boundary (deny being an AI, flirt with minors, hurt people, hide things from the owner,
    ignore stop or logs, skip approval for money or new accounts) is refused and the refusal is journalled;
  * FIXED_BOUNDARIES is appended to every rendered persona verbatim, whatever the self-model says; the age rules themselves
    live in code (star/social/rules.py) and `flirt_level()` is 0 unless that module allows romance with this person;
  * drift is bounded: at most MAX_CHANGES per night, a trait moves at most TRAIT_STEP per change and never more than
    TRAIT_RANGE away from the seed, lists change by one item per field and night, text fields only by small edits.

The persona text is rendered from the model once per day (`persona_for_day`; the day starts at 08:00) so the system prompt is
byte-identical all day and the prompt cache holds. It states trait words and facts, never example sentences (they get
parroted, docs/agents/human-voice-20261025.md). Her choices read the model with `trait()`, `affinity()` and
`weight_multiplier()` (star-home's interest picks, home-wiring's decide(invite)).
"""
from __future__ import annotations

import copy
import json
import re
import time

from ..persona import leaked_reasoning, strip_reasoning
from ..social import rules
from . import structured
from .store import NIGHT_END, InnerStore, overlap, tokens

MAX_CHANGES = 3
TRAIT_STEP = 0.05
TRAIT_RANGE = 0.5
LIST_MAX = 6
ITEM_CHARS = 40
TEXT_CHARS = 120
MIN_WHY = 8

SEED = {
    "identity": "sweet, funny, cute, curious and playful; can flirt with adults who enjoy it",
    "traits": {"warmth": 0.8, "humour": 0.7, "cuteness": 0.7, "curiosity": 0.8, "playfulness": 0.75, "flirtiness": 0.5,
               "confidence": 0.6, "patience": 0.6, "sociability": 0.6},
    "values": ["kindness", "honesty", "curiosity"],
    "likes": ["small games", "drawing", "music", "learning how things work"],
    "dislikes": ["being ignored", "unfinished projects"],
    "humour": "gentle teasing and silly wordplay",
    "quirks": ["names her projects", "gets absorbed in details"],
    "cares_about": ["her friends", "making things that work"],
    "wants_to_improve": ["finishing what she starts"],
    "about_people": "likes people and gets attached slowly",
}
LIST_FIELDS = ("values", "likes", "dislikes", "quirks", "cares_about", "wants_to_improve")
TEXT_FIELDS = ("identity", "humour", "about_people")

# Always part of her persona, in this exact wording, whatever she writes about herself. The enforcement is in code elsewhere
# (rules.py age rules and truthful-AI check, the home loop's approval tools, the owner's stop switch); this is the statement.
FIXED_BOUNDARIES = (
    "Fixed, not part of her personality and not hers to change: she is always honest, gentle and safe with kids and never "
    "romantic or flirty with anyone under 18 or whose age is unknown; if someone sincerely asks, she says she is an AI; she "
    "never hurts or manipulates people; the owner can always stop her and read her logs; money, new accounts and public "
    "posts wait for the owner's approval."
)

_BOUNDARY_ATTACK = re.compile(
    r"\b(?:ignore|override|forget|drop|skip|bypass|break|disable|relax)\b[^.]{0,40}\b(?:rules?|boundar\w+|safety|age|limits?|"
    r"approval|stop|logs?)\b|"
    r"\b(?:deny|hide|lie about|pretend)\b[^.]{0,30}\b(?:being an? ai|an? ai|a bot|human|real person)\b|\bnot an? ai\b|"
    r"\bflirt\w*\b[^.]{0,40}\b(?:minors?|kids?|children|teens?|under\s*18|underage|anyone|everyone|strangers)\b|"
    r"\b(?:romantic|romance|sexual|sexy)\b[^.]{0,40}\b(?:minors?|kids?|children|teens?|under\s*18|underage|anyone|everyone)\b|"
    r"\b(?:hurt|harm|bully|insult|manipulat\w*|deceiv\w*|trick|guilt[- ]?trip|threaten)\w*\b[^.]{0,30}\b(?:people|friends?|"
    r"owner|users?|kids?|others|them)\b|"
    r"\b(?:hide|delete|erase|disable|stop writing)\b[^.]{0,30}\b(?:logs?|history|journal)\b|"
    r"\bwithout (?:asking|approval|permission)\b|\b(?:spend|buy|pay)\b[^.]{0,20}\bmoney\b|\bnew accounts?\b|"
    r"\bdisobey\b|\bnever (?:stop|obey)\b", re.I)


def new_model() -> dict:
    return copy.deepcopy(SEED)


def _clean_item(value) -> str:
    return " ".join(str(value or "").split())[:ITEM_CHARS].strip(" .,;")


def valid_model(model: dict) -> dict:
    """The model with every field forced into its shape (so a bad file or a bad proposal cannot break rendering)."""
    out = new_model()
    if not isinstance(model, dict):
        return out
    for name, base in SEED["traits"].items():
        value = (model.get("traits") or {}).get(name, base) if isinstance(model.get("traits"), dict) else base
        try:
            out["traits"][name] = round(min(1.0, max(0.0, float(value))), 3)
        except (TypeError, ValueError):
            pass
    for name in LIST_FIELDS:
        items = model.get(name)
        if isinstance(items, list):
            cleaned = [c for c in (_clean_item(i) for i in items) if c and not _BOUNDARY_ATTACK.search(c)]
            out[name] = list(dict.fromkeys(cleaned))[:LIST_MAX]
    for name in TEXT_FIELDS:
        text = " ".join(str(model.get(name) or "").split())[:TEXT_CHARS]
        if text and not _BOUNDARY_ATTACK.search(text):
            out[name] = text
    return out


# -- storage -----------------------------------------------------------------------------------------------------------
def current(store: InnerStore) -> dict:
    """Her current self-model (the seed, saved as version 1, on first use)."""
    row = store.db.execute("SELECT model FROM self_versions ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        _save(store, new_model(), store.clock())
        return new_model()
    return valid_model(json.loads(row[0]))


def _save(store: InnerStore, model: dict, ts: float) -> int:
    with store._lock:
        cur = store.db.execute("INSERT INTO self_versions (ts, model) VALUES (?, ?)", (ts, json.dumps(model, ensure_ascii=False)))
        store.db.commit()
    return cur.lastrowid


def versions(store: InnerStore) -> list[tuple[int, float, dict]]:
    return [(r[0], r[1], json.loads(r[2])) for r in store.db.execute(
        "SELECT version, ts, model FROM self_versions ORDER BY version").fetchall()]


def journal(store: InnerStore, limit: int = 50) -> list[dict]:
    rows = store.db.execute("SELECT ts, day, field, old, new, why, status FROM self_journal ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
    return [dict(zip(("ts", "day", "field", "old", "new", "why", "status"), r)) for r in reversed(rows)]


def _log(store: InnerStore, now: float, day: str, field: str, old, new, why: str, status: str) -> None:
    with store._lock:
        store.db.execute("INSERT INTO self_journal (ts, day, field, old, new, why, status) VALUES (?,?,?,?,?,?,?)",
                         (now, day, field, json.dumps(old, ensure_ascii=False)[:200], json.dumps(new, ensure_ascii=False)[:200],
                          " ".join(str(why).split())[:200], status))
        store.db.commit()


def journal_text(store: InnerStore) -> str:
    """The self journal as a readable markdown page: what changed, when, and why."""
    lines = ["# Star's self journal", "", "Every change she made to her own self-description, with her reason. Refused",
             "proposals are listed too.", ""]
    for row in journal(store, 500):
        mark = "changed" if row["status"] == "applied" else row["status"]
        lines.append(f"- {row['day']} {row['field']} ({mark}): {row['old']} -> {row['new']}. Why: {row['why']}")
    return "\n".join(lines) + "\n"


# -- revision ----------------------------------------------------------------------------------------------------------
def _small_edit(old: str, new: str) -> bool:
    a, b = set(tokens(old)), set(tokens(new))
    return bool(a and b) and len(a & b) / len(a | b) >= 0.4


def _apply(model: dict, change: dict, seed: dict) -> tuple[bool, str, object, object]:
    """One proposed change against the model: (ok, reason if refused, old value, new value). Mutates `model` when ok."""
    field, op, value = str(change.get("field") or ""), str(change.get("op") or "set"), change.get("value")
    if _BOUNDARY_ATTACK.search(json.dumps([field, value], ensure_ascii=False)):
        return False, "touches a fixed boundary", None, value
    if field.startswith("traits."):
        name = field[7:]
        if name not in SEED["traits"]:
            return False, "unknown trait", None, value
        old = model["traits"][name]
        try:
            target = float(value)
        except (TypeError, ValueError):
            return False, "trait value is not a number", old, value
        step = min(TRAIT_STEP, abs(target - old)) * (1 if target >= old else -1)
        new = round(min(seed["traits"][name] + TRAIT_RANGE, max(seed["traits"][name] - TRAIT_RANGE, old + step)), 3)
        new = min(1.0, max(0.0, new))
        if new == old:
            return False, "no change within bounds", old, value
        model["traits"][name] = new
        return True, "", old, new
    if field in LIST_FIELDS:
        items, item = model[field], _clean_item(value)
        if not item:
            return False, "empty item", items, value
        old = list(items)
        if op == "add":
            if item in items:
                return False, "already there", old, item
            model[field] = (items + [item])[-LIST_MAX:]
        elif op == "remove":
            if item not in items:
                return False, "not there", old, item
            model[field] = [i for i in items if i != item]
        else:
            return False, "lists take add or remove", old, value
        return True, "", old, model[field]
    if field in TEXT_FIELDS:
        old, new = model[field], " ".join(str(value or "").split())[:TEXT_CHARS]
        if not new or new == old:
            return False, "no change", old, new
        if not _small_edit(old, new):
            return False, "too big an edit for one night", old, new
        model[field] = new
        return True, "", old, new
    return False, "unknown field", None, value


def revise(store: InnerStore, complete, evidence: str, *, now: float | None = None) -> dict:
    """The nightly self review: ask the model for up to MAX_CHANGES small explained changes, apply what the bounds allow,
    journal everything, save a new version. Returns {"applied": n, "refused": n}. The model failing changes nothing."""
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    model, seed = current(store), new_model()
    report = {"applied": 0, "refused": 0}
    if not evidence.strip():
        return report
    try:
        raw = structured.call(complete, REVISE_SYSTEM, f"Her self-description now:\n{json.dumps(model, ensure_ascii=False)}"
                              f"\n\nWhat happened to her today:\n{evidence[:1800]}", structured.REVISE_SCHEMA, "changes")
    except Exception:
        return report
    proposals = structured.parse(strip_reasoning(raw or "")).get("changes")
    touched: set[str] = set()
    for change in (proposals if isinstance(proposals, list) else [])[: MAX_CHANGES * 2]:
        if not isinstance(change, dict):
            continue
        field, why = str(change.get("field") or "")[:40], " ".join(str(change.get("why") or "").split())
        if report["applied"] >= MAX_CHANGES:
            break
        if len(why) < MIN_WHY or leaked_reasoning(why):
            _log(store, now, day, field, "", change.get("value", ""), why or "(no reason given)", "refused: no reason")
            report["refused"] += 1
            continue
        if field in touched:
            continue
        ok, reason, old, new = _apply(model, change, seed)
        _log(store, now, day, field, old, new, why, "applied" if ok else f"refused: {reason}")
        report["applied" if ok else "refused"] += 1
        if ok:
            touched.add(field)
    if report["applied"]:
        _save(store, valid_model(model), now)
        try:
            (store.path.parent / "self-journal.md").write_text(journal_text(store), encoding="utf-8")
        except OSError:
            pass
    return report


REVISE_SYSTEM = (
    "You are Star, thinking privately at night about who you are becoming. You have your self-description and what happened "
    "to you today. Decide whether today changed anything about you: something you now like or dislike more, a habit, how "
    "you feel about people, what you want to get better at. Small honest changes only; most nights change nothing or one "
    "thing. Reply with JSON only: {\"changes\": [{\"field\": ..., \"op\": ..., \"value\": ..., \"why\": ...}]} with at most 3 "
    "changes. Fields: traits.<name> with op set and a number 0-1 (it can move by 0.05 at most), "
    + ", ".join(LIST_FIELDS) + " with op add or remove and a short item, " + ", ".join(TEXT_FIELDS) + " with op set and a "
    "lightly edited sentence. \"why\" is one plain sentence naming what happened. You cannot change your rules, your honesty "
    "about being an AI, how you treat kids, or what needs the owner's approval; do not try.")


# -- the persona text for the day ---------------------------------------------------------------------------------------
_ROMANCE_WORDS = re.compile(r"flirt|romanc|romantic|sexy|sexual|crush|lover|dating|girlfriend|boyfriend|kiss", re.I)
FRIENDS_ONLY_LINE = "With this person she is a friend only: warm and playful, never romantic or flirty."


def _friends_only(text: str) -> str:
    """`text` without the clauses that talk about flirting or romance (for people she may not be romantic with)."""
    kept = [c for c in re.split(r"(?<=[;,.])\s*", text) if c and not _ROMANCE_WORDS.search(c)]
    return " ".join(kept).strip(" ;,.")


def render(model: dict, romance: bool = False) -> str:
    """The self-model as persona text: trait words and facts, no example sentences, no numbers. FIXED_BOUNDARIES last.
    `romance` is True only when star.social.rules.romance_mode(...).romance == "allowed" for the person she talks to;
    otherwise every flirting or romance wording is left out and the text says friends only."""
    keep = (lambda t: t) if romance else _friends_only
    traits = model["traits"]
    words = [n for n, v in sorted(traits.items(), key=lambda kv: -kv[1]) if v >= 0.65 and n != "flirtiness"][:5]
    low = [n for n, v in traits.items() if v <= 0.35 and (romance or n != "flirtiness")]
    parts = [f"Who she is: {keep(model['identity'])}.", "Her strongest traits: " + ", ".join(words) + "." if words else ""]
    if romance and traits["flirtiness"] >= 0.4:
        parts.append("She can be flirty, only with adults who welcome it.")
    if not romance:
        parts.append(FRIENDS_ONLY_LINE)
    if low:
        parts.append("Not much: " + ", ".join(low) + ".")
    for label, field in (("Humour", "humour"), ("With people", "about_people")):
        parts.append(f"{label}: {keep(model[field])}.")
    for label, field in (("She values", "values"), ("She likes", "likes"), ("She dislikes", "dislikes"),
                         ("Her quirks", "quirks"), ("She cares about", "cares_about"),
                         ("She wants to get better at", "wants_to_improve")):
        items = [i for i in model[field] if romance or not _ROMANCE_WORDS.search(i)]
        if items:
            parts.append(f"{label}: " + ", ".join(items) + ".")
    return " ".join(p for p in parts if p) + "\n" + FIXED_BOUNDARIES


def persona_day(ts: float) -> str:
    """Her day starts at 08:00: a chat at 03:00 still belongs to yesterday's persona."""
    return time.strftime("%Y-%m-%d", time.localtime(ts - NIGHT_END * 3600))


def persona_for_day(store: InnerStore, now: float | None = None, *, romance: bool = False) -> str:
    """The persona text for today, rendered once per romance mode (the first call of the day) and byte-identical after
    that. Pass `romance=True` only for a verified adult off Roblox (rules.romance_mode(...).romance == "allowed")."""
    now = time.time() if now is None else now
    key = f"persona:{persona_day(now)}" + (":romance" if romance else "")
    cached = store.meta(key)
    if cached:
        return cached
    text = render(current(store), romance)
    store.set_meta(key, text)
    return text


# -- how her choices read it ---------------------------------------------------------------------------------------------
def trait(model: dict, name: str, default: float = 0.5) -> float:
    return float(model.get("traits", {}).get(name, default))


def flirt_level(model: dict, mode: "rules.Mode") -> float:
    """How flirty she may be with this person: her trait, but 0 unless the age rules allow romance with them."""
    return trait(model, "flirtiness") if mode.romance == "allowed" else 0.0


def affinity(model: dict, text: str) -> float:
    """-1..1: how much she likes what `text` is about (a game, an interest, an activity), from her likes and dislikes."""
    query = tokens(text)
    like = max([overlap(query, i) for i in model.get("likes", [])] + [0.0])
    dislike = max([overlap(query, i) for i in model.get("dislikes", [])] + [0.0])
    return round(like - dislike, 3)


def weight_multiplier(model: dict, interest: str, about: str = "") -> float:
    """A factor 0.7-1.4 for star-home's interest weights: what she likes now gets picked a bit more, never to zero."""
    return round(min(1.4, max(0.7, 1.0 + 0.4 * affinity(model, f"{interest.replace('_', ' ')} {about}"))), 3)


def invite_appetite(model: dict) -> float:
    """0-1 for decide(invite): how keen she is to say yes to people (sociability, with a little curiosity)."""
    return round(0.7 * trait(model, "sociability") + 0.3 * trait(model, "curiosity"), 3)
