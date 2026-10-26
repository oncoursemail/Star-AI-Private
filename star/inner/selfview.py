"""Her self-model as the mind sees it: one view over parts that already exist plus what the memory stream knows.

  identity, values, likes      star.inner.self_model (the persona she revises nightly within code-enforced bounds)
  interests                    star-home's Life interest weights (drift: verified x1.1 / failed x0.95 in Life.record,
                               and the mind's mood nudge x1.03 / x0.97 after a session that left her happy / low)
  skills                       memory stream procedural records: recency-weighted Beta posterior = calibrated
                               confidence, Wilson lower bound, Brier score of her own predictions
  relationships                episodic memories with people: count, mean valence, last time
  timeline                     milestone memories (firsts, insights, dreams) = autobiographical timeline
  insights                     current reflections

`summary()` is the "who I am right now" line for prompts, cut to a token budget (~4 chars per token). It leaves out
anything about a person (the same line goes to everyone she talks to), anything private and her mood (the emotion
directive carries mood per turn). It is re-rendered at most every 6 hours, so the prompt prefix stays cacheable.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

from .stream import MemoryStream

DEFAULT_IDENTITY = "sweet, funny, cute, curious and playful"


def skills(stream: MemoryStream, now: float) -> list[dict]:
    stats = stream.skill_stats(now)
    return sorted(({"skill": k, **v} for k, v in stats.items()), key=lambda s: (-s["confidence"], s["skill"]))


def relationships(stream: MemoryStream) -> list[dict]:
    rows: dict[str, dict] = defaultdict(lambda: {"name": "", "memories": 0, "valence": 0.0, "last": 0.0})
    for m in stream.all(kind="episodic"):
        for i, key in enumerate(m.people):
            r = rows[key]
            r["name"] = r["name"] or (m.names[i] if i < len(m.names) else "")
            r["memories"] += 1
            r["valence"] += m.valence
            r["last"] = max(r["last"], m.ts)
    out = [{"key": k, "name": v["name"], "memories": v["memories"], "mean_valence": round(v["valence"] / v["memories"], 3),
            "last": v["last"]} for k, v in rows.items()]
    return sorted(out, key=lambda r: -r["last"])


def timeline(stream: MemoryStream, limit: int = 30) -> list[dict]:
    rows = [m for m in stream.all() if m.milestone and not m.private]
    return [{"ts": m.ts, "day": time.strftime("%Y-%m-%d", time.localtime(m.ts)), "kind": m.kind, "text": m.text}
            for m in rows[-limit:]]


def insights(stream: MemoryStream, limit: int = 6, *, with_people: bool = True) -> list:
    rows = [m for m in stream.all(kind="reflection") if not m.invalid_at and not m.private
            and (with_people or not m.people)]
    return sorted(rows, key=lambda m: (-m.importance, -m.ts))[:limit]


def build(stream: MemoryStream, *, life=None, inner_model: dict | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    model = inner_model or {}
    interests = sorted(((k, float(v.get("weight", 1.0))) for k, v in (life.interests() if life else {}).items()),
                       key=lambda kv: -kv[1])
    return {"identity": model.get("identity") or DEFAULT_IDENTITY, "values": list(model.get("values") or [])[:4],
            "likes": list(model.get("likes") or [])[:5], "interests": [{"name": k, "weight": w} for k, w in interests],
            "skills": skills(stream, now), "relationships": relationships(stream), "timeline": timeline(stream),
            "insights": [{"id": m.id, "text": m.text, "evidence": m.evidence} for m in insights(stream)]}


def morning_note(stream: MemoryStream, day: str, now: float) -> str:
    """Before noon on `day`: a dream gist or a lesson from the night, to mention if it fits."""
    if time.localtime(now).tm_hour >= 12:
        return ""
    try:
        note = json.loads(stream.meta(f"morning:{day}") or "{}")
    except ValueError:
        return ""
    if note.get("dream"):
        return f"last night you dreamt about {note['dream']} (only a dream; mention it only if it fits)"
    if note.get("lesson"):
        return f"something you worked out yesterday: {note['lesson']}"
    return ""


def summary(view: dict, stream: MemoryStream, *, budget_tokens: int = 90, morning: str = "") -> str:
    """Priority order: identity, interests, skills, insights (no people), morning note; cut to the budget."""
    limit = max(60, int(budget_tokens) * 4)
    parts = [f"Who you are right now: Star; {view['identity']}."]
    if view["interests"]:
        parts.append("Into: " + ", ".join(i["name"].replace("_", " ") for i in view["interests"][:3]) + ".")
    good = [s["skill"] for s in view["skills"] if s["attempts"] >= 3 and s["confidence"] >= 0.7][:2]
    learning = [s["skill"] for s in view["skills"] if s["attempts"] >= 2 and s["confidence"] <= 0.4][:2]
    if good:
        parts.append("Good at " + ", ".join(good) + ".")
    if learning:
        parts.append("Still learning " + ", ".join(learning) + ".")
    lately = [m.text for m in insights(stream, 3, with_people=False)]
    if lately:
        parts.append("Lately: " + "; ".join(lately) + ".")
    if morning:
        parts.append("This morning: " + morning + ".")
    out = ""
    for part in parts:
        if len(out) + len(part) + 1 > limit:
            break
        out = f"{out} {part}".strip()
    return out
