"""Star's live picture of herself: what is running, practising, failing and finished, from real sources only.

Sources (each with its own age; a missing or stale one is reported as missing, never filled in):
  * brain 1 / brain 2: `facts` from server/discord/gate/star_gate.py (services, night school hourly counts and gate
    results, conductor report, knowledge watchdog, Studio Lab's last run, load);
  * the PC: the feed the STAR GPU worker sends over its link (pc_feed.py: STATE.md next actions, fresh board claims,
    PRs merged today, open PRs and their checks, releases);
  * this bot: jobs the owner started from Discord (actions.py) and the last reply's speed.

`summary()` is the compact block added to every owner turn; `detail(section)` answers the `star_lookup` tool;
`events(old, new)` lists what changed in a way worth an immediate DM (proactive.py decides whether to send).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import re
import time

_LOG = logging.getLogger(__name__)
REFRESH_SECONDS = 60
STALE_SECONDS = 5 * 60          # a brain answer older than this is reported as stale
PC_STALE_SECONDS = 10 * 60
SECTIONS = ("services", "night_school", "gates", "conductor", "studio_lab", "knowledge", "work", "prs",
            "jobs", "speed")
_BORING_SUB = {"exited"}


@dataclass
class Source:
    data: dict | None = None
    at: float = 0.0             # time.time() of the last good answer
    error: str = ""


@dataclass
class Snapshot:
    brains: dict[str, Source] = field(default_factory=dict)
    pc: dict | None = None
    pc_age: float | None = None
    jobs: list[dict] = field(default_factory=list)
    speed: dict = field(default_factory=dict)
    taken: float = 0.0


def _when(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


_STATES = {"brain idle, working": "practising (the brain was free)",
           "quiet lock held, waiting": "waiting (someone holds the quiet lock for a timing run)",
           "HOLD file present, paused": "paused (HOLD)", "brain not reachable, waiting": "waiting (brain unreachable)"}


def _plain_state(status: str) -> str:
    """Night school's report status in plain words (unknown statuses pass through)."""
    return _STATES.get(status, status or "state unknown")


_STATUS_QUESTION = re.compile(
    r"\bwhat (?:are|r) (?:you|u) (?:doing|up to|working on)\b|\bwhat(?:'s| is| have you been) (?:you )?(?:doing|up to)\b|"
    r"\bwhat did you (?:learn|do|practi[cs]e|fix)\b|\bhow(?:'s| is) (?:night school|the work|it going)\b|"
    r"\b(?:your|star'?s?) status\b|\bstatus (?:report|update)\b|\banything (?:i should know|new|broken)\b|"
    r"\bdid anything (?:break|fail)\b", re.I)


def status_question(text: str) -> bool:
    """A question about Star's own work: the DM answer gets the live status card under her words."""
    return bool(_STATUS_QUESTION.search(str(text or "")[:300]))


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{round(seconds / 86400)} days"


class Awareness:
    def __init__(self, gates: dict, *, pc_feed=None, jobs=None, speed=None, tz=None, clock=time.time) -> None:
        """`pc_feed()` -> (age seconds, feed dict) or None; `jobs()` -> list of job dicts; `speed()` -> dict."""
        self.gates = gates
        self._pc_feed = pc_feed
        self._jobs = jobs
        self._speed = speed
        self._tz = tz                   # STAR_DISCORD_OWNER_TZ (a tzinfo), else the PC feed's offset
        self._clock = clock
        self.brains: dict[str, Source] = {name: Source() for name in gates}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ collecting

    async def _fetch(self, name: str) -> None:
        source = self.brains[name]
        try:
            answer = await self.gates[name].call("facts", timeout=45)
            if answer.get("ok") is not True or not isinstance(answer.get("facts"), dict):
                raise ValueError("the gate refused facts")
            source.data, source.at, source.error = answer["facts"], self._clock(), ""
        except (ValueError, OSError, asyncio.TimeoutError) as exc:
            source.error = str(exc)[:160] or type(exc).__name__

    async def refresh(self) -> None:
        async with self._lock:
            await asyncio.gather(*(self._fetch(name) for name in self.gates))

    def snapshot(self) -> Snapshot:
        pc, age = None, None
        if self._pc_feed is not None:
            got = self._pc_feed()
            if got is not None:
                age, pc = got
        return Snapshot({k: Source(v.data, v.at, v.error) for k, v in self.brains.items()}, pc, age,
                        list(self._jobs() if self._jobs else []), dict(self._speed() if self._speed else {}),
                        self._clock())

    def owner_tz(self, snap: Snapshot | None = None):
        """The owner's zone: STAR_DISCORD_OWNER_TZ if set, else the PC feed's UTC offset, else None (unknown)."""
        if self._tz is not None:
            return self._tz
        pc = (snap or self.snapshot()).pc or {}
        value = pc.get("tz_offset_min")
        if isinstance(value, int) and -840 <= value <= 840:
            return timezone(timedelta(minutes=value))
        return None

    def local(self, moment: datetime, snap: Snapshot | None = None) -> datetime:
        """`moment` in the owner's zone (UTC when it is unknown)."""
        return moment.astimezone(self.owner_tz(snap) or timezone.utc)

    # ------------------------------------------------------------------ reading

    def _fresh(self, snap: Snapshot, name: str) -> dict | None:
        source = snap.brains.get(name)
        if source is None or source.data is None or snap.taken - source.at > STALE_SECONDS:
            return None
        return source.data

    def _today(self, snap: Snapshot, ns: dict) -> dict:
        """Practice counts for the owner's current local day and the last hour, from the hourly UTC buckets."""
        now = datetime.fromtimestamp(snap.taken, timezone.utc)
        today = self.local(now, snap).date()
        last_hour = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
        total, hour = {}, {}
        for key, counts in (ns.get("hours") or {}).items():
            moment = _when(key + ":00:00Z")
            if moment is None:
                continue
            if self.local(moment, snap).date() == today:
                for name, value in counts.items():
                    total[name] = total.get(name, 0) + int(value)
            if key >= last_hour:
                for name, value in counts.items():
                    hour[name] = hour.get(name, 0) + int(value)
        return {"today": total, "last_hour": hour}

    @staticmethod
    def _practice_line(counts: dict, *, full: bool = False) -> str:
        attempts = sum(counts.get(k, 0) for k in ("first", "lesson", "validation"))
        passed = sum(counts.get(k + "_pass", 0) for k in ("first", "lesson", "validation"))
        bits = [f"{attempts} tries, {passed} passed"]
        if full and counts.get("lesson"):
            bits.append(f"{counts.get('lesson_pass', 0)} of {counts['lesson']} lesson retries fixed the task")
        if full and counts.get("discarded"):
            bits.append(f"{counts['discarded']} lesson ideas discarded")
        if counts.get("error"):
            bits.append(f"{counts['error']} could not run")
        return ", ".join(bits)

    def _restarted(self, facts: dict, now: datetime) -> tuple[list[str], list[str]]:
        """(failed units, units (re)started in the last 3 hours), timer-run jobs left out."""
        rows = [r for r in facts.get("services", []) if r.get("unit", "").endswith(".service")]
        timers = {r["unit"][:-6] for r in facts.get("services", []) if r.get("unit", "").endswith(".timer")}
        failed = [r["unit"][:-8] for r in rows if r.get("active") == "failed"]
        recent = []
        for row in rows:
            since = _when(row.get("since", ""))
            if (row.get("active") == "active" and row.get("sub") not in _BORING_SUB and since
                    and now - since < timedelta(hours=3) and row["unit"][:-8] not in timers):
                recent.append(f"{row['unit'][:-8]} {_ago((now - since).total_seconds())} ago")
        return failed, recent

    def summary(self, snap: Snapshot | None = None) -> str:
        """The compact block for every owner turn (kept short: every token is read again each minute)."""
        snap = snap or self.snapshot()
        now = datetime.fromtimestamp(snap.taken, timezone.utc)
        zone = "owner-local" if self.owner_tz(snap) is not None else "UTC"
        lines = [f"LIVE STATUS ({self.local(now, snap):%H:%M} {zone}, real sources). This is ALL you know about "
                 "your own work right now: never add activities or numbers that are not here; star_lookup has detail."]
        missing = []
        for name in sorted(snap.brains):
            facts = self._fresh(snap, name)
            source = snap.brains[name]
            if facts is None:
                why = source.error or ("no answer yet" if not source.at else f"last answer {_ago(snap.taken - source.at)} old")
                missing.append(f"brain {name} ({why})")
                continue
            parts = []
            ns = facts.get("night_school")
            if ns:
                report = ns.get("report") or {}
                counts = self._today(snap, ns)
                state = "paused (HOLD)" if ns.get("paused") else _plain_state(report.get("status", ""))
                text = f"night school {state}; today {self._practice_line(counts['today'])}"
                if counts["last_hour"]:
                    text += f"; last hour {self._practice_line(counts['last_hour'])}"
                parts.append(text)
                if ns.get("gates"):
                    gate = ns["gates"][-1]
                    verdict = gate["event"].replace("lesson ", "").replace("gate ", "").lower()
                    parts.append(f"last lesson gate {gate['lesson']} {verdict} ({gate['ts'][5:10]})")
            conductor = facts.get("conductor")
            if conductor:
                parts.append(f"conductor night {conductor.get('night')}: {conductor.get('accepted')} of "
                             f"{conductor.get('created')} new practice tasks accepted"
                             + (" (switched off)" if conductor.get("off") else ""))
            watchdog = facts.get("knowledge_watchdog")
            if watchdog:
                restarts = [r for r in watchdog.get("restarts", [])
                            if (_when(r.get("at")) or now) > now - timedelta(hours=24)]
                parts.append("knowledge search " + ("ok" if watchdog.get("ok") else "FAILING") +
                             (f" (watchdog restarted it at {restarts[-1]['at'][11:16]} UTC)" if restarts else ""))
            lab = facts.get("studio_lab")
            if lab:
                parts.append(("Studio Lab running now; " if lab.get("running") else "") +
                             f"last Studio Lab run: {lab.get('specs_ran')} of {lab.get('specs')} specs ran, "
                             f"{lab.get('passed')} passed")
            failed, recent = self._restarted(facts, now)
            if failed:
                parts.append("FAILED: " + ", ".join(failed))
            if recent:
                parts.append("restarted lately: " + ", ".join(recent[:3]))
            lines.append(f"- brain {name}: " + ("; ".join(parts) or "services up, no reports"))
        pc = snap.pc
        if pc and snap.pc_age is not None and snap.pc_age <= PC_STALE_SECONDS:
            claims = pc.get("claims") or []
            bits = [f"{len(claims)} items claimed in 6 h" +
                    (" (" + ", ".join(c.get("item", "").split(":")[0][:30] for c in claims[:4]) + ")" if claims else "")]
            if "merged_today" in pc and "open_prs" in pc:
                prs = pc.get("open_prs") or []
                failing = [p for p in prs if p.get("checks") == "failing"]
                bits.append(f"{len(pc.get('merged_today') or [])} PRs merged today; {len(prs)} open, "
                            f"{len(failing)} with failing checks")
            else:
                missing.append("GitHub (the PC could not read PRs)")
            lines.append("- work: " + "; ".join(bits))
        else:
            missing.append("PC feed (" + ("never received" if snap.pc_age is None else f"{_ago(snap.pc_age)} old") + ")")
        if snap.jobs:
            lines.append("- jobs he started from Discord: " + "; ".join(
                f"{j.get('label')} {j.get('state')}" for j in snap.jobs[-3:]))
        if missing:
            lines.append("- MISSING (say you can't see these): " + "; ".join(missing))
        return "\n".join(lines)[:1600]

    def status_fields(self, snap: Snapshot | None = None) -> tuple[list[dict], list[str]]:
        """The same live facts as `summary`, as card fields (embeds.status_card) plus the missing sources."""
        from .embeds import field
        snap = snap or self.snapshot()
        now = datetime.fromtimestamp(snap.taken, timezone.utc)
        fields, missing = [], []
        for name in sorted(snap.brains):
            facts = self._fresh(snap, name)
            if facts is None:
                missing.append(f"brain {name}: " + (snap.brains[name].error or "no fresh answer"))
                continue
            ns = facts.get("night_school")
            if ns:
                counts = self._today(snap, ns)["today"]
                state = "paused (HOLD)" if ns.get("paused") else _plain_state((ns.get("report") or {}).get("status", ""))
                tries = sum(counts.get(k, 0) for k in ("first", "lesson", "validation"))
                passed = sum(counts.get(k + "_pass", 0) for k in ("first", "lesson", "validation"))
                value = f"{state}\n**{tries}** tries \u00b7 **{passed}** passed today"
                if counts.get("error"):
                    value += f"\n{counts['error']} couldn't run"
                fields.append(field(f"Brain {name} \u00b7 night school", value))
            lessons = []
            if ns and ns.get("gates"):
                gate = ns["gates"][-1]
                verdict = gate["event"].replace("lesson ", "").replace("gate ", "").lower()
                lessons.append(f"gate {gate['lesson']}: {verdict} ({gate['ts'][5:10]})")
            conductor = facts.get("conductor")
            if conductor:
                lessons.append(f"{conductor.get('accepted')}/{conductor.get('created')} new tasks accepted "
                               f"({conductor.get('night')})")
            if lessons:
                fields.append(field(f"Brain {name} \u00b7 lessons", "\n".join(lessons)))
            watchdog = facts.get("knowledge_watchdog")
            if watchdog:
                restarts = [r for r in watchdog.get("restarts", [])
                            if (_when(r.get("at")) or now) > now - timedelta(hours=24)]
                fields.append(field("Knowledge search", ("ok" if watchdog.get("ok") else "search FAILING") +
                                    (f"\nwatchdog restart {restarts[-1]['at'][11:16]} UTC" if restarts else "")))
            lab = facts.get("studio_lab")
            if lab:
                fields.append(field("Studio Lab", ("running now\n" if lab.get("running") else "") +
                                    f"last run: **{lab.get('specs_ran')}/{lab.get('specs')}** specs ran \u00b7 "
                                    f"**{lab.get('passed')}** passed"))
            failed, _recent = self._restarted(facts, now)
            if failed:
                fields.append(field(f"Brain {name} \u00b7 FAILED", ", ".join(failed)))
        pc = snap.pc
        if pc and snap.pc_age is not None and snap.pc_age <= PC_STALE_SECONDS:
            value = f"**{len(pc.get('claims') or [])}** items claimed (6 h)"
            if "merged_today" in pc and "open_prs" in pc:
                prs = pc.get("open_prs") or []
                failing = sum(1 for p in prs if p.get("checks") == "failing")
                value += (f"\n**{len(pc.get('merged_today') or [])}** PRs merged today\n**{len(prs)}** open "
                          f"\u00b7 {failing} failing checks")
            fields.append(field("Work", value))
        else:
            missing.append("PC feed (board, PRs)")
        if snap.jobs:
            fields.append(field("Jobs you started", "\n".join(f"{j.get('label')}: {j.get('state')}"
                                                               for j in snap.jobs[-3:]), inline=False))
        return fields, missing

    def detail(self, section: str, snap: Snapshot | None = None) -> str:
        """The star_lookup tool: one section in detail, from the same sources. Unknown section -> overview."""
        snap = snap or self.snapshot()
        if section not in SECTIONS:
            return self.summary(snap)
        now = datetime.fromtimestamp(snap.taken, timezone.utc)
        out: list[str] = []
        if section in {"work", "prs"}:
            pc = snap.pc
            if not pc or snap.pc_age is None or snap.pc_age > PC_STALE_SECONDS:
                return "The PC feed is missing or stale, so I can't see the board, STATE.md or PRs right now."
            out.append(f"(PC feed {_ago(snap.pc_age)} old)")
            if section == "work":
                out.append("STATE.md next actions:")
                out += [f"- {line}" for line in pc.get("state_next", [])[:6]]
                out.append("Board claims in the last 6 h:")
                out += [f"- {c.get('owner')}: {c.get('item')} (since {c.get('since')})" for c in pc.get("claims", [])]
                out.append("Merged today: " + (", ".join(f"#{p.get('number')} {p.get('title', '')[:60]}"
                                                         for p in pc.get("merged_today", [])) or "none"))
            else:
                for pr in pc.get("open_prs", [])[:25]:
                    out.append(f"- #{pr.get('number')} {pr.get('title', '')[:70]} | {'draft' if pr.get('draft') else 'ready'}"
                               f" | checks {pr.get('checks')} | {pr.get('merge', '')}")
                for rel in pc.get("releases", [])[:3]:
                    out.append(f"release {rel.get('tag')}: {'draft' if rel.get('draft') else 'published'} {rel.get('at', '')}")
            return "\n".join(out)[:3500]
        if section == "jobs":
            return "\n".join(f"- {j.get('label')}: {j.get('state')} (started {j.get('started')}) {j.get('result', '')}"
                             for j in snap.jobs) or "No jobs started from Discord since the bot started."
        if section == "speed":
            for name in sorted(snap.brains):
                facts = self._fresh(snap, name)
                ns = (facts or {}).get("night_school") or {}
                rate = (ns.get("report") or {}).get("answers_per_active_hour")
                out.append(f"brain {name}: night school {rate} answers per active hour; load {(facts or {}).get('load')}")
            out.append(f"last chat reply: {snap.speed or 'none yet'}")
            return "\n".join(out)
        for name in sorted(snap.brains):
            facts = self._fresh(snap, name)
            if facts is None:
                out.append(f"brain {name}: no fresh facts ({snap.brains[name].error or 'not reached yet'})")
                continue
            if section == "services":
                out.append(f"brain {name} (facts {_ago(snap.taken - snap.brains[name].at)} old):")
                timers = {r["unit"][:-6] for r in facts.get("services", []) if r["unit"].endswith(".timer")}
                for r in facts.get("services", []):
                    if r["unit"].endswith(".timer"):
                        continue
                    if r["unit"][:-8] in timers and r["active"] != "failed":
                        state = "runs on a timer" + (" (running now)" if r["active"] == "active" else ", idle between runs")
                    elif r["active"] == "active":
                        state = f"running since {r['since'] or '?'}" if r["sub"] != "exited" else "done (one-time setup)"
                    else:
                        state = "FAILED" if r["active"] == "failed" else "installed, not running"
                    out.append(f"- {r['unit'][:-8]}: {state}; restarts {r['restarts']}")
            elif section == "night_school" and facts.get("night_school"):
                ns = facts["night_school"]
                counts = self._today(snap, ns)
                out.append(f"brain {name}: status {ns['report'].get('status')}, paused {ns.get('paused')}; today "
                           f"{self._practice_line(counts['today'], full=True)}; last hour "
                           f"{self._practice_line(counts['last_hour'], full=True)}; all-time totals {ns['report']}")
                for key, value in list((ns.get("hours") or {}).items())[-8:]:
                    out.append(f"  {key}:00 UTC {value}")
            elif section == "gates" and facts.get("night_school"):
                out.append(f"brain {name} lesson gate results (last 36 h):")
                out += [f"- {g['ts']} {g['lesson']} {g['event']}: {g['text']}" for g in facts["night_school"].get("gates", [])]
            elif section == "conductor" and facts.get("conductor"):
                out.append(f"brain {name} conductor: {facts['conductor']}")
            elif section == "studio_lab" and facts.get("studio_lab"):
                out.append(f"brain {name} Studio Lab: {facts['studio_lab']}")
            elif section == "knowledge" and facts.get("knowledge_watchdog"):
                out.append(f"brain {name} knowledge watchdog: {facts['knowledge_watchdog']}")
        return ("\n".join(out) or f"No {section.replace('_', ' ')} report on any brain right now.")[:3500]

    # ------------------------------------------------------------------ changes worth a DM

    def events(self, old: Snapshot, new: Snapshot) -> list[tuple[str, str]]:
        """(event id, one-line text) for important changes between two snapshots. Ids are stable for dedupe."""
        out = []
        for name in sorted(new.brains):
            before, after = self._fresh(old, name), self._fresh(new, name)
            if before is None or after is None:
                continue
            timers = {r["unit"][:-6] for r in after.get("services", []) if r.get("unit", "").endswith(".timer")}
            prev = {r["unit"]: r for r in before.get("services", [])}
            status = ((after.get("night_school") or {}).get("report") or {}).get("status", "")
            maintenance = "quiet lock" in status
            for row in after.get("services", []):
                unit = row.get("unit", "")
                if not unit.endswith(".service") or unit[:-8] in timers or row.get("sub") in _BORING_SUB:
                    continue
                was = prev.get(unit)
                if was is None or was.get("active") != "active":
                    if was is not None and row.get("active") == "active":
                        out.append((f"up:{name}:{unit}:{row.get('since')}", f"{unit[:-8]} on brain {name} is back up."))
                    continue
                if row.get("active") != "active":
                    out.append((f"down:{name}:{unit}:{was.get('since')}",
                                f"{unit[:-8]} on brain {name} is DOWN ({row.get('active')}/{row.get('sub')})."))
                elif row.get("since") and row.get("since") != was.get("since"):
                    if maintenance:     # someone holds the quiet lock: a deliberate restart, kept for the next note
                        out.append((f"maint:{name}:{unit}:{row.get('since')}",
                                    f"{unit[:-8]} on brain {name} restarted at {row['since'][11:16]} UTC during a timing run."))
                    else:
                        out.append((f"restart:{name}:{unit}:{row.get('since')}",
                                    f"{unit[:-8]} on brain {name} restarted at {row['since'][11:16]} UTC."))
            seen = {(g["ts"], g["lesson"]) for g in ((before.get("night_school") or {}).get("gates") or [])}
            for gate in ((after.get("night_school") or {}).get("gates") or []):
                if (gate["ts"], gate["lesson"]) not in seen:
                    out.append((f"gate:{name}:{gate['ts']}:{gate['lesson']}",
                                f"Lesson gate on brain {name}: {gate['lesson']} {gate['event'].replace('lesson ', '')}."))
            old_lab, new_lab = before.get("studio_lab") or {}, after.get("studio_lab") or {}
            if new_lab.get("run") and new_lab.get("run") != old_lab.get("run"):
                out.append((f"lab:{name}:{new_lab['run']}",
                            f"Studio Lab run finished: {new_lab.get('specs_ran')} of {new_lab.get('specs')} specs ran, "
                            f"{new_lab.get('passed')} passed."))
            old_dog = {r.get("at") for r in ((before.get("knowledge_watchdog") or {}).get("restarts") or [])}
            for row in ((after.get("knowledge_watchdog") or {}).get("restarts") or []):
                if row.get("at") not in old_dog:
                    out.append((f"watchdog:{name}:{row.get('at')}",
                                f"My knowledge search hung and its watchdog restarted it at {str(row.get('at'))[11:16]} UTC"
                                + ("." if row.get("done") else ", but the restart FAILED.")))
        if old.pc and new.pc:
            known = {r.get("tag") for r in old.pc.get("releases", [])}
            for rel in new.pc.get("releases", []):
                if rel.get("tag") and rel.get("tag") not in known:
                    out.append((f"release:{rel['tag']}", f"Release {rel['tag']} is {'ready as a draft' if rel.get('draft') else 'published'}."))
        return out
