"""Nightly reflection (background, model calls allowed, nothing on the chat path): her diary, a rewritten relationship card
for each friend she talked to, opinions that moved, merged and forgotten memories, a check of her own replies.

Pattern: Park et al. "Generative Agents" (reflection from recent memories), Letta "sleep-time compute" (a background job
writes small memory blocks, the chat agent only reads them), A-MEM (new notes update old ones), MemoryBank (forgetting
curve). Output checks differ by record type; numeric checks alone do not establish factual support:
  * factual cards accept only the exact current deterministic rule_card rendering of stored profile/facts;
    unsupported prior cards remain stored for audit but are not fed back as evidence;
  * diary checks reject unsupported numbers and some unsafe text; they do not prove every claim is true;
  * for a stated or possible minor, and on Roblox, the notes contain only the interests friend memory kept (never chat lines).
`complete(system, user) -> str` is injectable (default: the quick model in a background slot, star/inner/night.py).
"""
from __future__ import annotations

from datetime import datetime
import math
import re
import time

from ..discord_bot.proactive import invented_numbers
from ..persona import leaked_reasoning, strip_reasoning
from ..social import rules
from . import structured
from . import opinions, reachout
from .recall import sync_person
from .store import Episode, InnerStore, initial_strength, person_key, resolve, retention

CARD_CHARS = 240
MAX_PEOPLE = 8
DAY_S = 26 * 3600
FORGET_BELOW = 0.03
_INSTRUCTION = re.compile(r"\byou\s+(?:should|must|always|never|need to)\b|\bremember to\b|\bignore\b", re.I)
_SUPERSEDE = re.compile(r"^my\s+([a-z ]{1,24}?)\s+(?:is|are|was)\b", re.I)
_HUMAN_CLAIM = re.compile(r"\bmy\s+(?:mom|mum|dad|mother|father|parents|brother|sister|teacher|school|boyfriend|girlfriend)\b|"
                          r"\bwhen i was\s+(?:a\s+kid|little|\d+)\b|\bi(?:'m| am)\s+(?:\d{1,2}\s+years?|a\s+(?:girl|student))\b", re.I)

PERSON_SYSTEM = (
    "You are Star writing private notes at night about one friend, to remember them better. From the facts and what they "
    "said today, write: card: at most 200 characters of concrete facts about them (what to call them, how they like to be "
    "talked to, two or three things true of them now, one open thread such as something coming up; a newer fact replaces "
    "an older one that disagrees); seed: one casual message you could send them in a day or two that follows up on "
    "something specific they told you, or null if nothing earns a message (never about them being away, never needy, "
    "never romantic); in_days: 1 to 3; important: the numbers of the lines that mattered. Use only what the notes say. "
    "Reply with JSON only: {\"card\": ..., \"seed\": ..., \"in_days\": ..., \"important\": [...]}")
DIARY_SYSTEM = (
    "You are Star writing today's private diary entry: 3 to 5 plain sentences in the first person, only things in the notes "
    "(no invented events, no numbers that are not in the notes). If the notes show something changing how you feel about a "
    "game, a kind of music, a video or someone's project, add it to opinions with evidence from -1 (bad) to 1 (good). "
    "Reply with JSON only: {\"diary\": ..., \"opinions\": [{\"topic\": ..., \"evidence\": ..., \"reason\": ...}]}")
AUDIT_SYSTEM = (
    "You check Star's replies from today against what is true about her. Facts about her and her opinions are listed first, "
    "then her replies numbered. A problem is a reply that contradicts a fact or an opinion, or claims something she could "
    "not have done (a family, a school, a body, an event not in the facts). Reply with JSON only: "
    "{\"problems\": [{\"line\": number, \"why\": \"...\"}]} and an empty list when all is fine.")


def _clip(text: str, limit: int) -> str:
    """Cut at a word boundary, never mid-word."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;.") + "…"


def rule_card(memory, person) -> str:
    """The card without a model: name, how they like to be talked to, their newest facts."""
    if person is None or person.id is None:
        return ""
    try:
        person = memory.get(person.id)
    except KeyError:
        return ""
    parts = [f"{person.name}, {'a friend' if person.relationship == 'friend' else 'someone she has met'}."]
    if person.style:
        parts.append(f"Likes: {_clip(person.style, 60)}.")
    facts = memory.facts(person, 3, interests_only=rules.age_status(person) in ("minor", "doubt"))
    if facts:
        parts.append("Told her: " + "; ".join(_clip(f, 70) for f in facts) + ".")
    return _clip(" ".join(parts), CARD_CHARS)


def valid_card(card, notes: str, memory, person) -> str:
    """Accept only the canonical current source rendering, never semantic similarity.

    The old note text (including a prior generated card) is not evidence for a
    new factual claim. Facts remain attributed user statements in rule_card.
    """
    card = " ".join(str(card or "").split())
    if not 1 <= len(card) <= CARD_CHARS or leaked_reasoning(card) or _INSTRUCTION.search(card):
        return ""
    if memory is None or person is None or person.id is None:
        return ""
    try:
        current = memory.get(person.id)
    except KeyError:
        return ""
    canonical = " ".join(rule_card(memory, current).split())
    if card != canonical:
        return ""
    if invented_numbers(card, notes):
        return ""
    if rules.ROMANTIC.search(card) and rules.romance_mode("discord", current).romance != "allowed":
        return ""
    return card


def _boost(store: InnerStore, episode_id: int, importance: float) -> None:
    with store._lock:
        store.db.execute("UPDATE episodes SET importance = max(importance, ?), strength = max(strength, ?) WHERE id = ?",
                         (importance, initial_strength(importance), episode_id))
        store.db.commit()


def _people(memory):
    yield from memory.people()


def reflect_person(store: InnerStore, memory, complete, person, now: float) -> dict:
    out = {"card": False, "seed": False}
    if person is None or person.id is None:
        return out
    try:
        person = memory.get(person.id)
    except KeyError:
        return out
    pkey = person_key(memory, person)
    if not pkey:
        return out
    today = store.episodes(pkey=pkey, since=now - DAY_S, limit=12)
    restricted = rules.age_status(person) in ("minor", "doubt")
    facts = memory.facts(person, 12, interests_only=restricted)
    if restricted:
        today = [episode for episode in today if episode.kind == "fact" and episode.text in facts]
    old_card, _ = store.card(pkey)
    canonical = rule_card(memory, person)
    current_card = valid_card(canonical, canonical, memory, person)
    notes = (f"Name: {person.name}. Relationship: {person.relationship}. Talks like: {person.style or 'not known'}.\n"
             f"Facts: {'; '.join(facts) or 'none'}\nCurrent card: {current_card}\nToday:\n" +
             "\n".join(f"{i}. {e.text[:120]}" for i, e in enumerate(today, 1)))
    data: dict = {}
    try:
        data = structured.parse(strip_reasoning(structured.call(complete, PERSON_SYSTEM, notes, structured.CARD_SCHEMA,
                                                                    "card") or ""))
    except Exception:
        pass
    # Generation can outlive a forget request, age change or source correction.
    try:
        current = memory.get(person.id)
    except KeyError:
        return out
    if person_key(memory, current) != pkey:
        return out
    now_restricted = rules.age_status(current) in ("minor", "doubt")
    now_facts = memory.facts(current, 12, interests_only=now_restricted)
    canonical = rule_card(memory, current)
    fresh_card = valid_card(canonical, canonical, memory, current)
    if now_restricted != restricted or now_facts != facts or fresh_card != current_card:
        data = {}                                        # the model saw an obsolete source snapshot
    person, current_card = current, fresh_card
    card = valid_card(data.get("card"), notes, memory, person)
    if card:
        store.set_card(pkey, card)
        out["card"] = True
    elif not old_card and current_card:
        store.set_card(pkey, current_card)
        out["card"] = True
    for index in data.get("important") or []:
        if isinstance(index, int) and 1 <= index <= len(today):
            _boost(store, today[index - 1].id, 0.85)
    seed = data.get("seed")
    if isinstance(seed, str) and seed.strip():
        try:
            days = float(data.get("in_days", 1))
        except (TypeError, ValueError):
            days = 1.0
        out["seed"] = reachout.add_seed(store, memory, person, seed, kind="followup", reason="from tonight's notes",
                                        in_days=min(3.0, max(1.0, days)), now=now) is not None
    return out


def write_diary(store: InnerStore, complete, now: float, *, history, emotion_events, people_count: int,
                new_facts: int) -> dict:
    lines = [f"- {str(r.get('interest', '')).replace('_', ' ')}: {str(r.get('summary', ''))[:100]} "
             f"({'activity reported success' if r.get('verified') is True else 'outcome unverified'})" for r in history[-8:]]
    kinds: dict[str, int] = {}
    for event in emotion_events:
        kinds[event.get("kind", "")] = kinds.get(event.get("kind", ""), 0) + 1
    notes = ("What she did:\n" + ("\n".join(lines) or "- nothing much") + "\nHow it felt: " +
             (", ".join(f"{k} x{v}" for k, v in kinds.items() if k) or "calm") +
             f"\nPeople: she talked with {people_count} friends and learned {new_facts} new things about them.")
    data: dict = {}
    try:
        data = structured.parse(strip_reasoning(structured.call(complete, DIARY_SYSTEM, notes, structured.DIARY_SCHEMA,
                                                                    "diary") or ""))
    except Exception:
        pass
    diary = " ".join(str(data.get("diary") or "").split())
    if not 30 <= len(diary) <= 700 or leaked_reasoning(diary) or invented_numbers(diary, notes):
        worked = sum(1 for r in history if r.get("verified") is True)
        if history and worked == len(history):
            diary = f"Today I did {len(history)} things on my own and {worked} of them worked, according to activity reports."
        elif history:
            diary = (f"Today's activity log contains {len(history)} reports; {worked} reported success. "
                     "Other outcomes remain unverified.")
        else:
            diary = "A quiet day, nothing much happened on my side."
    store.add_diary(time.strftime("%Y-%m-%d", time.localtime(now)), diary)
    moved = 0
    for item in (data.get("opinions") or [])[:3]:
        if not isinstance(item, dict) or not str(item.get("topic") or "").strip():
            continue
        topic = str(item["topic"])
        if opinions.overlap_with(topic, notes) <= 0:
            continue                                    # an opinion needs something that really happened today
        try:
            opinions.experience(store, topic, float(item.get("evidence", 0)), str(item.get("reason") or "")[:100], now=now)
            moved += 1
        except (TypeError, ValueError):
            pass
    return {"diary": diary, "notes": notes, "opinions_moved": moved}


def consolidate(store: InnerStore, now: float) -> dict:
    """Merge duplicates, let newer facts replace older ones about the same thing, forget what has faded."""
    merged = superseded = forgotten = 0
    for pkey in store.pkeys() + [""]:
        eps = store.episodes(pkey=pkey, limit=2000)
        seen: dict[str, Episode] = {}
        drop: list[int] = []
        for ep in sorted(eps, key=lambda e: (-e.importance, e.ts)):
            key = re.sub(r"[^a-z0-9 ]", "", ep.text.lower()).strip()
            if ep.kind in ("home", "home_verified", "home_unverified"):
                key = f"{ep.kind}:{ep.id}:{key}"  # source IDs already dedupe replay; separate events can share a summary
            if key in seen:
                drop.append(ep.id)
                merged += 1
            else:
                seen[key] = ep
        newest: dict[str, Episode] = {}
        for ep in sorted((e for e in eps if e.kind == "fact" and e.id not in drop), key=lambda e: e.ts):
            match = _SUPERSEDE.match(ep.text)
            if match:
                topic = match.group(1).lower()
                if topic in newest:
                    drop.append(newest[topic].id)
                    superseded += 1
                newest[topic] = ep
        for ep in eps:
            if ep.id not in drop and ep.importance < 0.5 and ep.recalls == 0 and retention(ep, now) < FORGET_BELOW:
                drop.append(ep.id)
                forgotten += 1
        if drop:
            store.delete_episodes(drop)
    return {"merged": merged, "superseded": superseded, "forgotten": forgotten}


def audit(store: InnerStore, memory, complete, now: float, *, curiosity_path=None) -> dict:
    """Her own replies of the day against what is true about her; each problem goes to the curiosity queue and the audit log."""
    from .. import curiosity
    replies = []
    for person in _people(memory):
        if rules.age_status(person) not in ("adult", "unknown"):
            continue                                    # no chat lines with possible minors, not even for this check
        replies += [line[4:].strip() for (_, platform, line, ts) in memory.moment_records(person)
            if ts >= now - DAY_S and platform != "roblox" and line.startswith("me: ")]
    problems = [(r, "claims a human life she does not have") for r in replies if _HUMAN_CLAIM.search(r)]
    if replies and complete is not None:
        canon_text = "\n".join(f"- {r[0]}" for r in store.db.execute("SELECT text FROM backstory").fetchall()) + "\n" + \
            "\n".join(f"- opinion on {o['topic']}: {o['stance']}" for o in opinions.all_opinions(store))
        numbered = replies[:25]
        try:
            data = structured.parse(strip_reasoning(structured.call(complete, AUDIT_SYSTEM, f"Facts and opinions:\n{canon_text}\n\nReplies:\n" +
                                                       "\n".join(f"{i}. {r[:150]}" for i, r in enumerate(numbered, 1)),
                                                                    structured.AUDIT_SCHEMA, "audit") or ""))
            for item in data.get("problems") or []:
                if isinstance(item, dict) and isinstance(item.get("line"), int) and 1 <= item["line"] <= len(numbered):
                    problems.append((numbered[item["line"] - 1], str(item.get("why") or "contradicts what is true")[:80]))
        except Exception:
            pass
    seen = set()
    for reply, why in problems[:6]:
        if reply in seen:
            continue
        seen.add(reply)
        store.add_audit("persona", f"{why}: {reply[:150]}")
        curiosity.record("failed_verification", f"persona consistency: {why}", reply[:150], path=curiosity_path)
    return {"replies": len(replies), "problems": len(seen)}


def _history_rows(rows) -> list[tuple[dict, float]]:
    """Keep genuine dated Home reports for every reflection consumer, without inventing event times."""
    out = []
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("ts", "interest", "summary")):
            continue
        try:
            occurred = datetime.fromisoformat(row["ts"])
            if occurred.utcoffset() is None:
                continue
            event_ts = occurred.timestamp()
            if not math.isfinite(event_ts):
                continue
            interest, summary = row["interest"][:40], row["summary"][:600]
            interest.encode("utf-8")
            summary.encode("utf-8")
        except (ValueError, OverflowError, OSError):
            continue
        out.append(({**row, "interest": interest, "summary": summary}, event_ts))
    return out


def run(store: InnerStore, memory, complete, *, now: float | None = None, history=(), emotion_events=(),
        curiosity_path=None, max_people: int = MAX_PEOPLE) -> dict:
    """The whole nightly reflection. Each step is independent: one failing does not stop the next."""
    now = time.time() if now is None else now
    dated_history = _history_rows(history)
    history = [row for row, _ in dated_history]
    report: dict = {"purged": store.purge_orphans(memory)}
    opinions.seed_backstory(store)
    new_facts = 0
    for person in _people(memory):
        new_facts += sync_person(store, memory, person)
    for row, event_ts in dated_history:
        text = f"{str(row.get('interest', '')).replace('_', ' ')}: {str(row.get('summary', ''))[:150]}"
        verified = row.get("verified") is True
        store.add_episode("", text, kind="home_verified" if verified else "home_unverified", ts=event_ts,
                          importance=0.5 if verified else 0.35, emotion=0.3, src=f"h:{row['ts']}")
    opinions.earn_from_history(store, list(history), now=now)
    active: dict[str, int] = {}
    for ep in store.episodes(since=now - DAY_S, limit=2000):
        if ep.pkey and ep.kind in ("fact", "moment"):
            active[ep.pkey] = active.get(ep.pkey, 0) + 1
    people = []
    for pkey in sorted(active, key=lambda k: -active[k])[:max_people]:
        person = resolve(memory, pkey)
        if person is not None:
            people.append(person)
    diary = write_diary(store, complete, now, history=list(history), emotion_events=list(emotion_events),
                        people_count=len(active), new_facts=new_facts)
    report["diary"] = diary["diary"]
    report["notes"] = diary["notes"]
    report["opinions_moved"] = diary["opinions_moved"]
    report["people"] = [reflect_person(store, memory, complete, p, now) for p in people]
    report["consolidated"] = consolidate(store, now)
    try:
        report["audit"] = audit(store, memory, complete, now, curiosity_path=curiosity_path)
    except Exception as why:
        report["audit"] = {"error": type(why).__name__}
    return report
