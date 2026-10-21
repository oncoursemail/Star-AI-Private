"""Star messages the owner first: a morning and an evening note, and a DM right away only when something matters.

Opt-in (STAR_DISCORD_LEARNING_DM_OPT_IN=1, the owner's switch) and only with a live status source (gates). Rules:
  * digests at STAR_DISCORD_DIGEST_TIMES (owner-local, default 08:30,20:30), written by the quick model in her voice
    from the live facts; a draft that uses a number not in the facts, or fails the persona check, is replaced by a
    plain template, so a digest never invents anything;
  * immediate DMs for awareness.events (service down/restarted/back, lesson gate result, Studio Lab run finished,
    a restart while someone holds the quiet lock is maintenance and only goes into the next note;
    knowledge watchdog restart, release); several at once become one DM; at most STAR_DISCORD_EVENT_DMS_PER_HOUR
    (default 3) and 12 a day, the same unit at most once per 30 minutes; each event once (SQLite ledger);
  * `/quiet` (or a DM "quiet for 3 hours") holds everything except replies and jobs he started; held events are
    counted in the next digest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import re
import sqlite3

_LOG = logging.getLogger(__name__)
SAME_UNIT_MINUTES = 30
DAY_LIMIT = 12
LATE_DIGEST_HOURS = 3           # a digest missed while the bot was down is still sent this long after its time
_TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


@dataclass(frozen=True)
class ProactiveConfig:
    enabled: bool
    times: tuple[tuple[int, int], ...] = ((8, 30), (20, 30))
    per_hour: int = 3
    state_path: Path | None = None

    @classmethod
    def from_env(cls, env=None, *, gates_configured: bool) -> "ProactiveConfig":
        source = os.environ if env is None else env
        if str(source.get("STAR_DISCORD_LEARNING_DM_OPT_IN", "0")).strip() != "1" or not gates_configured:
            return cls(False)
        if str(source.get("STAR_DISCORD_PROACTIVE", "1")).strip() == "0":
            return cls(False)
        raw = str(source.get("STAR_DISCORD_DIGEST_TIMES", "08:30,20:30")).strip()
        times = []
        for part in [p.strip() for p in raw.split(",") if p.strip()]:
            match = _TIME.fullmatch(part)
            if not match:
                raise ValueError("STAR_DISCORD_DIGEST_TIMES must look like 08:30,20:30")
            times.append((int(match.group(1)), int(match.group(2))))
        per_hour = str(source.get("STAR_DISCORD_EVENT_DMS_PER_HOUR", "3")).strip() or "3"
        if not per_hour.isdecimal() or not 0 <= int(per_hour) <= 20:
            raise ValueError("STAR_DISCORD_EVENT_DMS_PER_HOUR must be 0-20")
        state = str(source.get("STAR_DISCORD_LEARNING_STATE", "")).strip()
        folder = Path(state).parent if state else Path.home() / ".star" / "discord-state"
        return cls(True, tuple(sorted(times)), int(per_hour), folder / "proactive.sqlite3")


class Ledger:
    """What was sent (or held) and the quiet switch; one small SQLite file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                        "similar TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, "
                        "at TEXT NOT NULL, dm TEXT NOT NULL DEFAULT '')")
        self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def close(self) -> None:
        self.db.close()

    def known(self, event_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM outbox WHERE event_id=?", (event_id,)).fetchone() is not None

    def record(self, event_id: str, kind: str, state: str, now: datetime, *, similar: str = "", text: str = "",
               dm: str = "") -> bool:
        """False when the event was already recorded (at most once). `dm`: the message it went out in."""
        return self.db.execute("INSERT OR IGNORE INTO outbox(event_id,kind,similar,text,state,at,dm) "
                               "VALUES(?,?,?,?,?,?,?)", (event_id, kind, similar, text[:300], state, now.isoformat(),
                                                         dm or event_id)).rowcount == 1

    def mark(self, event_id: str, state: str) -> None:
        self.db.execute("UPDATE outbox SET state=? WHERE event_id=?", (state, event_id))

    def sent_since(self, kind: str, since: datetime) -> int:
        return self.db.execute("SELECT COUNT(DISTINCT dm) FROM outbox WHERE kind=? AND state='sent' AND at>=?",
                               (kind, since.isoformat())).fetchone()[0]

    def similar_since(self, similar: str, since: datetime) -> bool:
        return self.db.execute("SELECT 1 FROM outbox WHERE similar=? AND state='sent' AND at>=? LIMIT 1",
                               (similar, since.isoformat())).fetchone() is not None

    def held_since(self, since: datetime) -> list[str]:
        rows = self.db.execute("SELECT text FROM outbox WHERE kind='event' AND state='held' AND at>? ORDER BY at",
                               (since.isoformat(),)).fetchall()
        return [row[0] for row in rows]

    def last_digest(self) -> datetime | None:
        row = self.db.execute("SELECT at FROM outbox WHERE kind='digest' AND state='sent' ORDER BY at DESC LIMIT 1").fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def quiet_until(self) -> datetime | None:
        row = self.db.execute("SELECT value FROM settings WHERE key='quiet_until'").fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def set_quiet(self, until: datetime | None) -> None:
        self.db.execute("INSERT INTO settings(key,value) VALUES('quiet_until',?) ON CONFLICT(key) DO UPDATE SET "
                        "value=excluded.value", (until.isoformat() if until else "",))


_QUIET = re.compile(r"^(?:star[, ]+)?(?:(?:be |go )?quiet|shh+|mute|do not disturb|dnd)"
                    r"(?:\s+(?:for\s+)?(\d{1,2})\s*(?:h|hr|hrs|hours?))?[.!]?$", re.I)
_UNQUIET = re.compile(r"^(?:star[, ]+)?(?:unquiet|unmute|quiet off|you can (?:talk|message me) again|"
                      r"talk to me again)[.!]?$", re.I)


def quiet_request(text: str) -> int | None:
    """Hours of quiet asked for in a DM (0 = end quiet), or None when the message is not about quiet."""
    text = " ".join(str(text or "").split())
    if _UNQUIET.fullmatch(text):
        return 0
    match = _QUIET.fullmatch(text)
    if match:
        return min(72, int(match.group(1) or 8)) or 8
    return None


_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


def invented_numbers(text: str, facts: str) -> list[str]:
    """Numbers in a draft that do not occur in the facts it was written from (times count as their parts)."""
    known = set(_NUMBER.findall(facts.replace(":", " ")))
    known |= {str(int(n)) for n in known if n.isdigit()}
    return [n for n in _NUMBER.findall(text.replace(":", " ")) if n not in known and n.lstrip("0") not in known]


DIGEST_SYSTEM_TAIL = """
Now write your {when} note to him on Discord, in your own voice: what you did, learned and fixed since your last
note, what failed or worries you, and what's next. 3 to 6 short sentences, under 900 characters, no headings, no
greeting line on its own. Use ONLY the facts given; every number you write must appear in them. If a source is
missing, say you couldn't see it.
"""


def template_digest(when: str, facts: str) -> str:
    """The fallback when the model draft cannot be trusted: the facts themselves, briefly framed."""
    lines = [line[2:] for line in facts.splitlines() if line.startswith("- ")]
    opener = "Morning! Here's where I am:" if when == "morning" else "Evening update from me:"
    return (opener + "\n" + "\n".join(f"- {line[:300]}" for line in lines[:8]))[:1900]


class Proactive:
    def __init__(self, config: ProactiveConfig, awareness, send, *, writer=None, ledger: Ledger | None = None,
                 clock=lambda: datetime.now(timezone.utc)) -> None:
        """`send(text, picture, card)` DMs the owner (the card, or the text when there is none); `writer(system,
        user)` returns a model draft (None: templates only)."""
        self.config, self.awareness, self.send, self.writer = config, awareness, send, writer
        if ledger is None:
            if config.state_path is None:
                raise ValueError("The proactive ledger needs a state path")
            ledger = Ledger(config.state_path)
        self.ledger = ledger
        self._clock = clock
        self._previous = None

    # ------------------------------------------------------------------ quiet

    def quiet(self, now: datetime | None = None) -> datetime | None:
        until = self.ledger.quiet_until()
        return until if until and until > (now or self._clock()) else None

    def set_quiet(self, hours: int) -> str:
        now = self._clock()
        if hours <= 0:
            self.ledger.set_quiet(None)
            return "Okay, I'm back. I'll message you when something matters."
        until = now + timedelta(hours=hours)
        self.ledger.set_quiet(until)
        local = self.awareness.local(until)
        return (f"Quiet until {local:%H:%M} your time. I'll still answer you and report jobs you start; "
                "anything else waits for my next note.")

    # ------------------------------------------------------------------ the minute tick

    async def tick(self) -> dict:
        snap = self.awareness.snapshot()
        now = self._clock()
        result = {"events": 0, "digest": ""}
        if self._previous is not None:
            result["events"] = await self._events(self.awareness.events(self._previous, snap), now)
        self._previous = snap
        result["digest"] = await self._digest(snap, now)
        return result

    async def _events(self, events: list[tuple[str, str]], now: datetime) -> int:
        fresh = []
        for event_id, text in events:
            similar = ":".join(event_id.split(":")[:3])
            if self.ledger.known(event_id):
                continue
            if event_id.startswith("maint:") or self.ledger.similar_since(similar, now - timedelta(minutes=SAME_UNIT_MINUTES)):
                self.ledger.record(event_id, "event", "held", now, similar=similar, text=text)
                continue
            fresh.append((event_id, similar, text))
        if not fresh:
            return 0
        busy = (self.quiet(now) is not None
                or self.ledger.sent_since("event", now - timedelta(hours=1)) >= self.config.per_hour
                or self.ledger.sent_since("event", now - timedelta(days=1)) >= DAY_LIMIT)
        if busy:
            for event_id, similar, text in fresh:
                self.ledger.record(event_id, "event", "held", now, similar=similar, text=text)
            return 0
        for event_id, similar, text in fresh:
            self.ledger.record(event_id, "event", "pending", now, similar=similar, text=text, dm=fresh[0][0])
        if len(fresh) == 1:
            body = "Heads up: " + fresh[0][2]
        else:
            body = "Heads up, a few things just happened:\n" + "\n".join(f"- {t}" for _, _, t in fresh[:8])
        from .embeds import alert_card
        try:
            await self.send(body[:1900], None, alert_card([t for _, _, t in fresh[:20]], now=now))
        except BaseException:
            for event_id, _, _ in fresh:
                self.ledger.mark(event_id, "unknown")
            raise
        for event_id, _, _ in fresh:
            self.ledger.mark(event_id, "sent")
        return len(fresh)

    def _due(self, snap, now: datetime) -> tuple[str, str] | None:
        """(digest id, 'morning'|'evening') when a digest time has passed today and was not sent yet."""
        local = self.awareness.local(now, snap)
        for index, (hour, minute) in reversed(list(enumerate(self.config.times))):
            slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if slot <= local <= slot + timedelta(hours=LATE_DIGEST_HOURS):
                when = "morning" if hour < 15 else "evening"
                return f"digest:{local:%Y-%m-%d}:{index}", when
        return None

    def digest_facts(self, snap, now: datetime) -> str:
        since = self.ledger.last_digest() or now - timedelta(hours=12)
        facts = self.awareness.summary(snap)
        gates = self.awareness.detail("gates", snap)
        held = self.ledger.held_since(since)
        extra = ["- lesson gate results in the last 36 h: " + " | ".join(
            line.strip("- ") for line in gates.splitlines() if line.startswith("- ")) if "- " in gates else ""]
        if held:
            extra.append(f"- {len(held)} event(s) I held back since my last note: " + " | ".join(held[:6]))
        pc = snap.pc or {}
        if pc.get("state_next"):
            extra.append("- next on the owner's plan (STATE.md): " + " | ".join(pc["state_next"][:2]))
        return facts + "\n" + "\n".join(e for e in extra if e)

    async def _digest(self, snap, now: datetime) -> str:
        due = self._due(snap, now)
        if due is None or self.ledger.known(due[0]):
            return ""
        digest_id, when = due
        if self.quiet(now) is not None:
            self.ledger.record(digest_id, "digest", "held", now)
            return "held"
        facts = self.digest_facts(snap, now)
        text = await self.compose(when, facts)
        if not self.ledger.record(digest_id, "digest", "pending", now):
            return ""
        card = None
        fields_for = getattr(self.awareness, "status_fields", None)
        if fields_for is not None:
            from .embeds import digest_card
            card = digest_card(when, text, *fields_for(snap), now=now)
        try:
            await self.send(text, None, card)
        except BaseException:
            self.ledger.mark(digest_id, "unknown")
            raise
        self.ledger.mark(digest_id, "sent")
        return when

    async def compose(self, when: str, facts: str) -> str:
        """Her own words when the draft is clean and invents no number; otherwise the template."""
        if self.writer is not None:
            from ..persona import CORE, check_reply
            system = CORE + DIGEST_SYSTEM_TAIL.format(when=when)
            for attempt in range(2):
                try:
                    draft = (await self.writer(system, "FACTS:\n" + facts) or "").strip()
                except Exception as exc:
                    _LOG.info("Digest draft failed (%s)", type(exc).__name__)
                    break
                problems = check_reply(draft) + [f"invented number {n}" for n in invented_numbers(draft, facts)]
                if draft and len(draft) <= 1900 and not problems:
                    return draft
                _LOG.info("Digest draft %d rejected: %s", attempt + 1, "; ".join(problems)[:300])
        return template_digest(when, facts)
