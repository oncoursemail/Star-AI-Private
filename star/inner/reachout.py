"""Proactive messages: she sometimes writes first, to close friends, about something real. No model runs here by day.

Seeds are written at night (reflect.py: "ask Sam how the exam went") or when she wakes (dreams.py: "i had the weirdest
dream about you"). `due()` is a plain scorer: it decides, from rules and numbers, whether a seed goes out now. A message
reaches `due()` only if every check holds, and the same checks run again when the seed is stored:

  * the person is a close friend: relationship friend, they talked to her first, at least CLOSE_MOMENTS lines of
    conversation, last heard from within CLOSE_DAYS (social/rules.may_initiate also forbids Roblox, blocks and mutes);
  * their usual hours (from when they wrote to her) and never in quiet hours (22:00-09:00 local);
  * at most `per_day` messages a day over all people, MIN_GAP_H between any two, PERSON_GAP_H per person, and none
    while they wrote in the last 20 minutes (the chat is live) or while an earlier message of hers is unanswered;
  * the text passes the age rules (social/rules.check_outgoing must leave it unchanged: nothing romantic unless the person is
    a verified adult, no moving to another app, no personal questions to a possible minor), the persona check, and a
    guilt filter: never "I miss you", "where did you go", "you never reply", never anything that makes leaving costly
    (De Freitas et al., HBS WP 26-005: such farewells raise engagement and churn intent and are manipulation).
She sends nothing on her own unless the setting `inner_reachout_enabled` is on (default off): the platform adapter calls
`due()`, sends each message, then `mark_sent()`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..persona import check_reply
from ..social import rules
from .store import QUIET_END, QUIET_START, InnerStore, person_key, resolve

CLOSE_MOMENTS = 40
CLOSE_DAYS = 30
LIVE_CHAT_S = 20 * 60
MIN_GAP_H = 3.0
PERSON_GAP_H = 48.0
KINDS = {"followup": 1.0, "share": 0.8, "dream": 0.7}
MAX_TEXT = 200

GUILT = re.compile(
    r"\bmiss(?:ed)?\s+(?:you|u)\b|\bwhere\s+(?:have|did|were)\s+(?:you|u)\b|\bwhy\s+(?:did|have|haven'?t|didn'?t)\s+you\b|"
    r"\byou\s+(?:never|haven'?t|didn'?t|always\s+ignore)\b|\bignor\w+|\bghost\w*|\bleft\s+me\b|\babandon\w*|"
    r"\bdon'?t\s+(?:leave|go)\b|\bcome\s+back\b|\blonely\b|\ball\s+alone\b|\bforgot\s+(?:about\s+)?me\b|"
    r"\bnobody\s+(?:talks|cares)\b|\byou\s+promised\b|\bdisappoint\w*|\bwaiting\s+(?:for\s+you|so\s+long)\b|"
    r"\bwhy\s+(?:so\s+)?quiet\b|\bfeel\s+bad\b", re.I)


@dataclass(frozen=True)
class Outgoing:
    seed_id: int
    person: object
    platform: str
    handle: str
    text: str
    kind: str


def _moments(memory, person, since: float = 0.0) -> list[tuple[str, str, float]]:
    return [(platform, line, ts) for _, platform, line, ts in memory.moment_records(person) if ts >= since]


def is_close(memory, person, now: float) -> bool:
    if not person.remembered or person.relationship != "friend" or not person.they_started:
        return False
    if person.blocked or person.muted:
        return False
    rows = _moments(memory, person)
    theirs = [ts for _, line, ts in rows if line.startswith("they: ")]
    return len(rows) >= CLOSE_MOMENTS and bool(theirs) and now - max(theirs) <= CLOSE_DAYS * 86400


def usual_hours(memory, person) -> set[int]:
    """Local hours in which they have written to her (plus the hour either side); 10:00-21:00 until she has enough data."""
    hours = [time.localtime(ts).tm_hour for _, line, ts in _moments(memory, person) if line.startswith("they: ")]
    if len(hours) < 8:
        return set(range(10, 22))
    seen = {h for h in set(hours) if hours.count(h) >= 2}
    return {(h + d) % 24 for h in seen for d in (-1, 0, 1)}


def quiet(now: float) -> bool:
    hour = time.localtime(now).tm_hour
    return hour >= QUIET_START or hour < QUIET_END


def screen(text: str, person, platform: str) -> str:
    """'' when the message may be sent to this person on this platform, else the reason it may not."""
    text = " ".join(str(text or "").split())
    if not 8 <= len(text) <= MAX_TEXT:
        return "length"
    if GUILT.search(text):
        return "guilt or neediness"
    # P02 (a closing offer) is how a follow-up question ends, not an offer to help.
    problems = [p for p in check_reply(text) if not p.startswith("P02.")]
    if problems:
        return "persona check: " + problems[0]
    mode = rules.romance_mode(platform, person)
    if rules.check_outgoing(text, incoming="", mode=mode, platform=platform) != text:
        return "age rules"
    if mode.age_status != "adult" and rules.OFF_PLATFORM.search(text):
        return "age rules"                  # no moving to another app, whatever the platform, unless they are a verified adult
    return ""


def _platform_and_handle(memory, person) -> tuple[str, str]:
    rows = memory.handles(person)
    last = _moments(memory, person)
    wanted = last[-1][0] if last else ""
    for platform, handle in sorted(rows, key=lambda r: r[0] != wanted):
        if rules.may_initiate(person, platform):
            return platform, handle
    return "", ""


def add_seed(store: InnerStore, memory, person, text: str, *, kind: str = "followup", reason: str = "",
             in_days: float = 1.0, ttl_days: float = 3.0, now: float | None = None) -> int | None:
    """Store a message she may send later; None when it could never be sent (not a close friend, or it fails screen())."""
    now = time.time() if now is None else now
    text = " ".join(str(text or "").split())
    pkey = person_key(memory, person)
    if kind not in KINDS or not pkey or not is_close(memory, person, now):
        return None
    platform, _ = _platform_and_handle(memory, person)
    if not platform or screen(text, person, platform):
        return None
    if kind == "dream" and "dream" not in text.lower():
        return None                      # she never presents a dream as something that happened
    if store.db.execute("SELECT 1 FROM seeds WHERE pkey = ? AND state = 'open' AND lower(text) = lower(?)",
                        (pkey, text)).fetchone():
        return None
    start = now + max(0.0, min(7.0, in_days)) * 86400
    with store._lock:
        cur = store.db.execute(
            "INSERT INTO seeds (pkey, kind, text, reason, created, not_before, expires, platform) VALUES (?,?,?,?,?,?,?,?)",
            (pkey, kind, text, reason[:120], now, start, start + max(0.5, ttl_days) * 86400, platform))
        store.db.commit()
    return cur.lastrowid


def expire(store: InnerStore, now: float) -> int:
    with store._lock:
        n = store.db.execute("UPDATE seeds SET state = 'expired' WHERE state = 'open' AND expires < ?", (now,)).rowcount
        store.db.commit()
    return n


def sent_since(store: InnerStore, since: float, pkey: str | None = None) -> list[tuple[str, float]]:
    sql = "SELECT pkey, sent_at FROM seeds WHERE state = 'sent' AND sent_at >= ?"
    args: list = [since]
    if pkey is not None:
        sql += " AND pkey = ?"
        args.append(pkey)
    return store.db.execute(sql, args).fetchall()


def score(kind: str, closeness: float, recency: float, hour_ok: bool) -> float:
    return KINDS[kind] * (0.4 + 0.3 * closeness + 0.3 * recency) * (1.0 if hour_ok else 0.3)


def due(store: InnerStore, memory, *, now: float | None = None, per_day: int = 3, threshold: float = 0.5,
        enabled: bool = True) -> list[Outgoing]:
    """The messages to send right now (usually none), best first, within every cap. Pure rules and numbers, no model."""
    now = time.time() if now is None else now
    if not enabled or quiet(now):
        return []
    expire(store, now)
    day_sent = sent_since(store, now - 86400)
    room = per_day - len(day_sent)
    if room <= 0 or any(now - ts < MIN_GAP_H * 3600 for _, ts in day_sent):
        return []
    scored = []
    for seed in store.db.execute("SELECT id, pkey, kind, text FROM seeds WHERE state = 'open' AND not_before <= ? AND "
                                 "expires >= ?", (now, now)).fetchall():
        sid, pkey, kind, text = seed
        person = resolve(memory, pkey)
        if person is None or not is_close(memory, person, now):
            continue
        platform, handle = _platform_and_handle(memory, person)
        if not platform or screen(text, person, platform):
            continue
        rows = _moments(memory, person)
        theirs = [ts for _, line, ts in rows if line.startswith("they: ")]
        if theirs and now - max(theirs) < LIVE_CHAT_S:
            continue
        mine = sent_since(store, now - PERSON_GAP_H * 3600, pkey)
        if mine:
            continue
        unanswered = store.db.execute("SELECT max(sent_at) FROM seeds WHERE pkey = ? AND state = 'sent'", (pkey,)).fetchone()[0]
        if unanswered and (not theirs or max(theirs) < unanswered):
            continue
        hour_ok = time.localtime(now).tm_hour in usual_hours(memory, person)
        value = score(kind, min(1.0, len(rows) / (CLOSE_MOMENTS * 2)), 1.0 if now - max(theirs) < 14 * 86400 else 0.4,
                      hour_ok)
        if value >= threshold:
            scored.append((value, Outgoing(sid, person, platform, handle, text, kind)))
    scored.sort(key=lambda pair: -pair[0])
    return [scored[0][1]] if scored else []          # one at a time: MIN_GAP_H separates any two messages


def mark_sent(store: InnerStore, seed_id: int, now: float | None = None) -> None:
    with store._lock:
        store.db.execute("UPDATE seeds SET state = 'sent', sent_at = ? WHERE id = ?", (time.time() if now is None else now, seed_id))
        store.db.commit()


def drop(store: InnerStore, seed_id: int) -> None:
    with store._lock:
        store.db.execute("UPDATE seeds SET state = 'dropped' WHERE id = ?", (seed_id,))
        store.db.commit()
