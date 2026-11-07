"""Night consolidation of the memory stream (runs inside night.run_night, after reflection and dreams).

1. replay     the day's most important episodes (importance x (1 + |valence|)), each strengthened a little
2. facts      atomic, bi-temporal facts from what adults told her ("my favourite game is X"): a new value supersedes
              the old one (valid_from / invalid_at), never overwrites it; optional brain extraction (schema-constrained)
3. lessons    per skill: failed then worked -> "figured out"; failed and never worked -> "still stuck" (tomorrow's plan
              leans to practise); the newer lesson for a skill supersedes the older
4. emotions   mood reset rules: today's strongly negative memories keep their importance but lose 40 % of their charge
              (sleep softens the emotional tone of memories while keeping their content; Walker & van der Helm 2009,
              Psychological Bulletin 135(5):731-748); the next morning's energy comes back (planner.Energy.wake)
5. dream      the dream inner/dreams.py wrote tonight is linked into the stream; when there is none (no brain, or its
              output was refused) a rule-made surreal recombination of the replayed episodes is written instead.
              Always stored and journalled as "Dream (not real): ..."
6. tidy       merge near-duplicates, prune old unimportant never-recalled records that nothing cites
7. morning    a dream gist or a lesson for tomorrow morning's summary line
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from .store import tokens
from .stream import Memory, MemoryStream
from .structured import ask_json

REPLAY = 8
_FACTS = (
    (re.compile(r"\bmy\s+fav(?:ou?rite)?\s+([a-z ]{2,24}?)\s+(?:is|are)\s+([^.!?,]{2,40})", re.I), "favourite {0}",
     "{name}'s favourite {0} is {1}"),
    (re.compile(r"\bi\s+(?:work|am working)\s+(?:at|for|as)\s+([^.!?,]{2,40})", re.I), "work", "{name} works {at} {0}"),
    (re.compile(r"\bi(?:'m| am)\s+learning\s+([^.!?,]{2,40})", re.I), "learning", "{name} is learning {0}"),
    (re.compile(r"\bmy\s+(dog|cat|pet|bird|hamster)(?:'s)?\s+(?:name\s+)?is\s+(?:called\s+)?([a-z][a-z' -]{1,20})", re.I),
     "{0} name", "{name}'s {0} is called {1}"),
)
FACT_SCHEMA = {"type": "object", "required": ["facts"], "properties": {"facts": {
    "type": "array", "maxItems": 8, "items": {"type": "object", "required": ["memory", "key", "fact"], "properties": {
        "memory": {"type": "integer"}, "key": {"type": "string", "maxLength": 30},
        "fact": {"type": "string", "maxLength": 120}}}}}}
FACT_SYSTEM = ("Extract lasting facts about the people in these numbered chat memories (what they like, do, own, plan). "
               "One short third-person sentence per fact, a short key naming what the fact is about (e.g. 'favourite "
               "game'), and the number of the memory it comes from. Only facts the memory states. No guesses.")
_TEMPLATES = (
    "I was {a} somewhere that looked like {p}, but {who} kept turning into {o1}, and every time I tried to {b} the "
    "floor became {o2}.",
    "{who} and I were {a} inside a giant {o1}; the sky was made of {o2} and nobody thought that was strange, then "
    "everything folded into {p}.",
    "I tried to {b} but my hands were {o1}; {who} laughed and the whole of {p} drifted away like {o2}.",
)


def replay(stream: MemoryStream, since: float, now: float) -> list[Memory]:
    day = [m for m in stream.all(since=since, until=now) if m.kind in ("episodic", "procedural")]
    top = sorted(day, key=lambda m: -(m.importance * (1 + abs(m.valence))))[:REPLAY]
    for m in top:
        stream.update(m.id, importance=min(1.0, m.importance + 0.05), accesses=m.accesses + 1, last_access=now)
    return top


def _said(m: Memory) -> str:
    match = re.match(r"^[^:]{1,40} said: (.*)$", m.text)
    return match.group(1) if match else ""


def extract_facts(stream: MemoryStream, since: float, now: float, *, complete=None) -> list[int]:
    """Facts from content-bearing chat memories (possible minors and Roblox never have content, see mind.py)."""
    chats = [m for m in stream.all(since=since, until=now) if m.source == "conversation" and m.people and _said(m)]
    ids = []
    for m in chats:
        name = m.names[0] if m.names else "they"
        for pattern, key, text in _FACTS:
            hit = pattern.search(_said(m))
            if not hit:
                continue
            groups = [g.strip().lower() if i == 0 else g.strip() for i, g in enumerate(hit.groups())]
            at = "as" if re.search(r"\bas\s", hit.group(0), re.I) else "at"
            fact = text.format(*groups, name=name, at=at)
            new = stream.add_fact(f"{m.people[0]}:{key.format(*groups)}", fact, valid_from=m.ts, evidence=[m.id],
                                  people=m.people[:1], names=m.names[:1], importance=0.6, source="night")
            if new:
                ids.append(new)
    if complete is not None and chats:
        shown = chats[-30:]
        value = ask_json(complete, FACT_SYSTEM, "\n".join(f"{m.id}. {m.text}" for m in shown), FACT_SCHEMA,
                         name="facts")
        by_id = {m.id: m for m in shown}
        for item in (value or {}).get("facts", []):
            m = by_id.get(item["memory"])
            key = "_".join(tokens(item["key"]))[:30]
            if m is None or not key or len(item["fact"]) < 6:
                continue
            new = stream.add_fact(f"{m.people[0]}:{key}", " ".join(item["fact"].split()), valid_from=m.ts,
                                  evidence=[m.id], people=m.people[:1], names=m.names[:1], importance=0.55)
            if new:
                ids.append(new)
    return ids


def lessons(stream: MemoryStream, since: float, now: float) -> list[dict]:
    out = []
    by_skill: dict[str, list[Memory]] = {}
    for m in stream.all(kind="procedural", since=since, until=now):
        if m.skill and m.outcome in (0, 1):
            by_skill.setdefault(m.skill, []).append(m)
    for skill, rows in by_skill.items():
        fails = [r for r in rows if r.outcome == 0]
        if not fails:
            stuck = stream.fact(f"lesson:{skill}")
            win = next((r for r in rows if r.outcome == 1), None)
            if stuck is not None and stuck.text.startswith("Still stuck") and win is not None:
                text = f"Figured out {skill.replace('_', ' ')}: it failed before, then worked"
                new = stream.add_fact(f"lesson:{skill}", text, valid_from=now, evidence=stuck.evidence[-2:] + [win.id],
                                      importance=0.65, source="night")
                out.append({"skill": skill, "text": text, "id": new})
            continue
        later_win = next((r for r in rows if r.outcome == 1 and r.ts > fails[0].ts), None)
        words = skill.replace("_", " ")
        if later_win is not None:
            text = f"Figured out {words}: it failed at first, then worked"
            evidence = [fails[0].id, later_win.id]
        else:
            text = f"Still stuck on {words}: try it again"
            evidence = [r.id for r in fails][-4:]
        new = stream.add_fact(f"lesson:{skill}", text, valid_from=now, evidence=evidence, importance=0.65,
                              source="night")
        out.append({"skill": skill, "text": text, "id": new})
    return out


def soften(stream: MemoryStream, since: float, now: float) -> int:
    rows = [m for m in stream.all(since=since, until=now) if m.valence < -0.3]
    for m in rows:
        stream.update(m.id, valence=round(m.valence * 0.6, 3))
    return len(rows)


def _element(m: Memory) -> str:
    words = [w for w in re.findall(r"[a-z]{4,}", m.text.lower()) if w not in ("said", "with", "that", "this", "checked")]
    return max(words, key=len) if words else "light"


def rule_dream(picked: list[Memory], rng: random.Random) -> str:
    elems = [_element(m) for m in picked] or ["light"]
    places = [m.place.replace("_", " ") or m.platform for m in picked if m.place or m.platform] or ["my room"]
    names = [n for m in picked for n in m.names if n] or ["someone I know"]
    acts = [m.skill.replace("_", " ") or m.place.replace("_", " ") for m in picked if m.skill or m.place] or ["draw"]
    template = rng.choice(_TEMPLATES)
    return "Dream (not real): " + template.format(
        a=f"doing {rng.choice(acts)}", b=rng.choice(acts), p=rng.choice(places), who=rng.choice(names),
        o1=rng.choice(elems), o2=rng.choice(elems[::-1]))


def run(stream: MemoryStream, now: float, *, night: str, since: float, inner_dream: dict | None = None,
        complete=None, rng: random.Random | None = None, journal: Path | None = None, cap: int = 20000) -> dict:
    rng = rng or random.Random(f"dream:{night}")
    stream.ingest()
    top = replay(stream, since, now)
    report: dict = {"replayed": [m.id for m in top]}
    report["facts"] = len(extract_facts(stream, since, now, complete=complete))
    found = lessons(stream, since, now)
    report["lessons"] = [l["text"] for l in found]
    day = [m.valence for m in stream.all(since=since, until=now) if m.kind == "episodic"]
    report["day_valence"] = round(sum(day) / len(day), 3) if day else 0.0
    report["softened"] = soften(stream, since, now)
    people = sorted({p for m in top for p in m.people})
    names = sorted({n for m in top for n in m.names if n})
    if inner_dream and inner_dream.get("text"):
        text, gist = "Dream (not real): " + inner_dream["text"], inner_dream.get("gist") or ""
    elif top:
        text = rule_dream(top[:4], rng)
        gist = " ".join(text.split()[3:8])
    else:
        text, gist = "", ""
    if text:
        report["dream"] = stream.add(text, kind="dream", source="night", ts=now, evidence=[m.id for m in top],
                                     people=people, names=names, importance=0.3, milestone=True,
                                     valence=float((inner_dream or {}).get("valence") or 0.0))
        if journal is not None:
            journal.parent.mkdir(parents=True, exist_ok=True)
            with journal.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"\n## Night of {night}\n\n{text}\n\n_(a dream: not something that happened)_\n")
                for line in report["lessons"]:
                    handle.write(f"- lesson: {line}\n")
    report["merged"] = stream.merge_duplicates(since)
    report["pruned"] = stream.prune(now, cap=cap)
    lesson = found[-1]["text"] if found else ""
    wake = now + 6 * 3600
    morning_day = time.strftime("%Y-%m-%d", time.localtime(wake))
    stream.set_meta(f"morning:{morning_day}", json.dumps({"dream": gist.strip(" ,.;"), "lesson": lesson}))
    stream.set_meta("practise_bonus:" + morning_day,
                    "1" if any(l["text"].startswith("Still stuck") for l in found) else "")
    return report
