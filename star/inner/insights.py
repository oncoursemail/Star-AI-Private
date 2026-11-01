"""Reflection: higher-level insights with evidence links ("I'm getting better at obbies", "Mia always cheers me up").

Due when the summed importance of memories since the last reflection passes `reflection_threshold` (Park et al. 2023
reflect on accumulated importance). Rule insights need no model and run any time:
  skill trend   >= 4 real outcomes of a skill; success rate of the later half vs the earlier half differs by >= 0.25
  person        >= 3 memories with someone; her mean valence with them >= 0.2 and >= her overall mean + 0.2
  enjoyment     >= 3 sessions of an interest; mean valence >= 0.3
Each rule insight has a `fact_key`, so a newer insight on the same thing supersedes the old one (bi-temporal, never a
contradiction). Model insights (night only, `mind_model_calls`) use schema-constrained output and are kept only when
every evidence id is one of the memories shown. An insight's people are its evidence's people, so forgetting a person
also removes what she concluded about them.
"""
from __future__ import annotations

from collections import defaultdict

from .stream import Memory, MemoryStream, _norm
from .structured import ask_json

MIN_TREND = 4
INSIGHT_SCHEMA = {"type": "object", "required": ["insights"], "properties": {"insights": {
    "type": "array", "maxItems": 3, "items": {"type": "object", "required": ["text", "evidence"], "properties": {
        "text": {"type": "string", "maxLength": 160},
        "evidence": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "integer"}}}}}}}
SYSTEM = ("You are Star looking back over your own recent memories. Write at most 3 short first-person insights "
          "(patterns about yourself, your skills or the people you know) that the numbered memories really support. "
          "Cite the memory numbers. No new events, no numbers that are not in the memories, nothing about being human.")


def due(stream: MemoryStream, now: float, threshold: float) -> bool:
    since = float(stream.meta("last_reflection", "0") or 0)
    if now - since < 3600:
        return False
    fresh = [m for m in stream.all(since=since) if m.kind not in ("reflection", "dream")]
    return len(fresh) >= 6 and sum(m.importance for m in fresh) >= threshold


def _words(name: str) -> str:
    return name.replace("_", " ").strip()


def _people(memories: list[Memory]) -> tuple[list, list]:
    keys, names = [], []
    for m in memories:
        for i, key in enumerate(m.people):
            if key not in keys:
                keys.append(key)
                names.append(m.names[i] if i < len(m.names) else "")
    return keys, names


def rule_insights(stream: MemoryStream) -> list[dict]:
    out: list[dict] = []
    by_skill: dict[str, list[Memory]] = defaultdict(list)
    for m in stream.all(kind="procedural"):
        if m.skill and m.outcome in (0, 1):
            by_skill[m.skill].append(m)
    for skill, rows in by_skill.items():
        if len(rows) < MIN_TREND:
            continue
        half = len(rows) // 2
        early = sum(r.outcome for r in rows[:half]) / half
        late = sum(r.outcome for r in rows[half:]) / (len(rows) - half)
        if late - early >= 0.25:
            text, direction = f"I'm getting better at {_words(skill)}", "up"
        elif early - late >= 0.25:
            text, direction = f"I've been struggling with {_words(skill)} lately", "down"
        else:
            continue
        out.append({"text": text, "key": f"trend:{skill}", "evidence": [r.id for r in rows][-12:], "people": [],
                    "names": [], "importance": 0.7, "direction": direction})
    social = [m for m in stream.all() if m.kind == "episodic" and m.people]
    feelings = [m.valence for m in stream.all() if m.kind == "episodic"]
    mean = sum(feelings) / len(feelings) if feelings else 0.0
    by_person: dict[str, list[Memory]] = defaultdict(list)
    for m in social:
        for key in m.people:
            by_person[key].append(m)
    for key, rows in by_person.items():
        if len(rows) < 3:
            continue
        avg = sum(r.valence for r in rows) / len(rows)
        if avg >= 0.2 and avg >= mean + 0.2:
            name = next((r.names[r.people.index(key)] for r in rows if key in r.people
                         and r.people.index(key) < len(r.names) and r.names[r.people.index(key)]), "they")
            out.append({"text": f"{name} always cheers me up", "key": f"cheer:{key}",
                        "evidence": [r.id for r in rows][-8:], "people": [key], "names": [name], "importance": 0.75})
    by_interest: dict[str, list[Memory]] = defaultdict(list)
    for m in stream.all(kind="episodic"):
        if m.source == "activity" and m.place:
            by_interest[m.place].append(m)
    for interest, rows in by_interest.items():
        if len(rows) >= 3 and sum(r.valence for r in rows) / len(rows) >= 0.3:
            out.append({"text": f"I really enjoy {_words(interest)}", "key": f"enjoy:{interest}",
                        "evidence": [r.id for r in rows][-8:], "people": [], "names": [], "importance": 0.6})
    return out


def model_insights(stream: MemoryStream, complete, now: float, limit: int = 40) -> list[dict]:
    shown = [m for m in stream.all(since=now - 3 * 86400) if not m.private and m.kind != "dream"][-limit:]
    if len(shown) < 4:
        return []
    lines = "\n".join(f"{m.id}. {m.text}" for m in shown)
    value = ask_json(complete, SYSTEM, f"Memories:\n{lines}", INSIGHT_SCHEMA, name="insights")
    if not value:
        return []
    ids = {m.id: m for m in shown}
    out = []
    for item in value["insights"]:
        evidence = [e for e in item["evidence"] if e in ids]
        text = " ".join(item["text"].split())
        if len(evidence) != len(item["evidence"]) or len(evidence) < 2 or len(text) < 8:
            continue
        keys, names = _people([ids[e] for e in evidence])
        out.append({"text": text, "key": "", "evidence": evidence, "people": keys, "names": names,
                    "importance": 0.6})
    return out


def reflect(stream: MemoryStream, now: float, *, complete=None) -> list[int]:
    """Store this round's insights; returns their ids. Same text as an existing reflection: evidence is merged."""
    insights = rule_insights(stream)
    if complete is not None:
        insights += model_insights(stream, complete, now)
    existing = {_norm(m.text): m for m in stream.all(kind="reflection") if not m.invalid_at}
    ids = []
    for item in insights:
        if item["key"]:
            new_id = stream.add_fact(item["key"], item["text"], valid_from=now, evidence=item["evidence"],
                                     people=item["people"], names=item["names"], importance=item["importance"],
                                     source="reflection", kind="reflection")
        elif _norm(item["text"]) in existing:
            old = existing[_norm(item["text"])]
            stream.update(old.id, evidence=sorted(set(old.evidence) | set(item["evidence"])))
            new_id = old.id
        else:
            new_id = stream.add(item["text"], kind="reflection", source="reflection", ts=now,
                                evidence=item["evidence"], people=item["people"], names=item["names"],
                                importance=item["importance"], milestone=True)
        if new_id:
            ids.append(new_id)
    stream.set_meta("last_reflection", now)
    return ids
