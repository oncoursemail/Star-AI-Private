"""Star's status in plain words for the owner's phone: one verdict, a few short fields, problems explained.

Pure functions over the facts awareness.py reads (star_gate `facts` per brain, the PC feed); no I/O, so every card is
tested from fixtures. Every number shown is one of those facts, or a sum or percentage of them.

Levels: "good" (fine / good news), "info" (neutral news), "warn" (worth a look), "bad" (something is broken). A card's
color and headline come from the worst level in it, never from "something changed".
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta, timezone

from .gate_client import RESTARTABLE

GOOD, INFO, WARN, BAD = "good", "info", "warn", "bad"
RANK = {GOOD: 0, INFO: 1, WARN: 2, BAD: 3}
ICON = {GOOD: "✅", INFO: "\U0001f4dd", WARN: "⚠️", BAD: "❌"}
STRUGGLING = 0.15               # fewer right answers than this today (with at least MIN_ANSWERS) is worth a look
MIN_ANSWERS = 30
KINDS = ("first", "lesson", "validation")

# What each service is, in words the owner uses (unknown units fall back to a cleaned-up name).
UNITS = {"star-brain": "my main brain", "star-knowledge": "knowledge search", "star-search-gateway": "web search",
         "searxng": "the web search engine", "star-night-school": "practice", "star-ns-brain": "the practice brain",
         "star-discord": "this Discord bot", "star-night-conductor": "my homework writer",
         "star-knowledge-watchdog": "the knowledge search watchdog", "star-knowledge-refresh": "the knowledge refresh",
         "star-studio-lab-nightly": "the Studio tests"}
_STATES = {"brain idle, working": "practising now",
           "quiet lock held, waiting": "waiting (a speed test has the server)",
           "HOLD file present, paused": "paused", "brain not reachable, waiting": "waiting (can't reach its brain)"}


def unit_name(unit: str) -> str:
    unit = unit.removesuffix(".service")
    return UNITS.get(unit, unit.removeprefix("star-").replace("-", " "))


def pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "-"


def answers(counts: dict | None) -> tuple[int, int]:
    """(answers, right) from night school's hourly counts: first tries, lesson retries and test questions."""
    counts = counts or {}
    return (sum(int(counts.get(k, 0)) for k in KINDS), sum(int(counts.get(k + "_pass", 0)) for k in KINDS))


def trend(today: dict, yesterday: dict | None) -> str:
    """'↑ from 35% yesterday' / '↓ from 47% yesterday' / 'same as yesterday (40%)', '' without a full yesterday."""
    tried, right = answers(today)
    if yesterday is None or not tried:
        return ""
    y_tried, y_right = answers(yesterday)
    if not y_tried:
        return ""
    now, before = 100 * right / tried, 100 * y_right / y_tried
    if abs(now - before) < 1:
        return f"same as yesterday ({pct(y_right, y_tried)})"
    return f"{'↑' if now > before else '↓'} from {pct(y_right, y_tried)} yesterday"


@dataclass
class Issue:
    level: str
    headline: str               # a few words for the card title
    text: str                   # what it means and what happens next


@dataclass
class Report:
    level: str = GOOD
    headline: str = ""
    note: str = ""              # one warm line when nothing needs him
    issues: list[Issue] = dc_field(default_factory=list)
    fields: list[dict] = dc_field(default_factory=list)


@dataclass
class BrainInput:
    name: str
    facts: dict | None          # None: no fresh answer
    today: dict = dc_field(default_factory=dict)
    yesterday: dict | None = None
    why_missing: str = ""


def _field(name: str, value: str, inline: bool = True) -> dict:
    return {"name": name, "value": value, "inline": inline}


class Clock:
    """Times in the owner's zone ('9:34 pm'), or UTC with the zone named when it is unknown."""

    def __init__(self, now: datetime, tz=None) -> None:
        self.now, self.tz = now, tz

    def local(self, moment: datetime) -> datetime:
        return moment.astimezone(self.tz or timezone.utc)

    def time(self, moment: datetime) -> str:
        if self.tz is None:
            return f"{moment.astimezone(timezone.utc):%H:%M} UTC"
        local = self.local(moment)
        return f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"

    def day(self, moment: datetime) -> str:
        days = (self.local(self.now).date() - self.local(moment).date()).days
        if days == 0:
            return "tonight" if self.tz is not None and self.local(moment).hour >= 18 else "today"
        return "yesterday" if days == 1 else f"{self.local(moment):%b} {self.local(moment).day}"

    def when(self, moment: datetime) -> str:
        return f"{self.day(moment)} {self.time(moment)}"


def parse(stamp: str) -> datetime | None:
    for pattern in ("%Y-%m-%dT%H:%M:%SZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(str(stamp or ""), pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ practice (night school)

def practice(brain: BrainInput) -> tuple[dict | None, list[Issue]]:
    """The brain's practice field and what is worth a look about it."""
    ns = (brain.facts or {}).get("night_school")
    if not ns:
        return None, []
    issues = []
    status = (ns.get("report") or {}).get("status", "")
    state = "paused" if ns.get("paused") else _STATES.get(status, "")
    tried, right = answers(brain.today)
    lines = [f"**{right}** of {tried} right ({pct(right, tried)})" if tried else "no practice yet today"]
    moved = trend(brain.today, brain.yesterday)
    if moved:
        lines.append(moved)
    errors = int(brain.today.get("error", 0))
    checker_down = errors >= 5 and errors > (tried + errors) // 10
    if checker_down:
        lines.append(f"{errors} couldn't be checked")
    if state and state != "practising now":
        lines.append(state)
    if state == "paused":
        issues.append(Issue(WARN, f"Practice is paused on brain {brain.name}",
                            f"Practice on brain {brain.name} is paused (someone switched it off for now). "
                            "Say \"resume night school\" and I'll start again."))
    if tried >= MIN_ANSWERS and right / tried < STRUGGLING:
        issues.append(Issue(WARN, f"Brain {brain.name} is struggling",
                            f"Brain {brain.name} got only {right} of {tried} practice answers right today "
                            f"({pct(right, tried)})" + (f", {moved}" if moved else "") +
                            ". It keeps practising and writes itself lessons from the mistakes."))
    if checker_down:
        issues.append(Issue(WARN, f"Practice checks failing on brain {brain.name}",
                            f"{errors} practice answers on brain {brain.name} couldn't be checked today (the checker "
                            "didn't run). They don't count as wrong, but they teach me nothing."))
    flag = ICON[WARN] + " " if any(i.level != GOOD for i in issues) else ""
    return _field(f"{flag}Brain {brain.name} · practice today", "\n".join(lines)), issues


# ------------------------------------------------------------------ lessons and homework

def lesson_sentence(event: str, lesson: str, text: str = "") -> tuple[str, str]:
    """(level, plain sentence) for one lesson-test event of night school's events log."""
    quote = f" “{text[:90].rstrip()}{'…' if len(text) > 90 else ''}”" if text else ""
    upper = event.upper()
    if "PROMOTE" in upper or upper.endswith("ACTIVE"):
        return GOOD, f"A new lesson ({lesson}) passed its test, so I use it from now on.{quote}"
    if "REJECT" in upper:
        return INFO, f"I tested a new lesson ({lesson}); it didn't help, so I set it aside.{quote}"
    if "RETIRED" in upper:
        return INFO, f"I stopped using lesson {lesson}: a recheck showed it made my answers worse.{quote}"
    return INFO, (f"I tested a new lesson ({lesson}); the test couldn't tell if it helps, so I'm not using it yet. "
                  f"I'll test it again after it fixes more tasks.{quote}")


def lessons(brain: BrainInput, clock: Clock) -> list[str]:
    """Lesson tests of the last 24 h and the homework writer's last night, one short line each."""
    out = []
    ns = (brain.facts or {}).get("night_school") or {}
    recent = [g for g in ns.get("gates") or [] if (parse(g.get("ts")) or clock.now) > clock.now - timedelta(hours=24)]
    if len(recent) == 1:
        gate = recent[0]
        out.append("🧪 " + lesson_sentence(gate.get("event", ""), gate.get("lesson", ""))[1])
    elif recent:
        verdicts = [str(g.get("event", "")).upper() for g in recent]
        adopted = sum(1 for v in verdicts if "PROMOTE" in v or v.endswith("ACTIVE"))
        unclear = sum(1 for v in verdicts if "INCONCLUSIVE" in v)
        others = len(recent) - adopted - unclear
        if unclear == len(recent):
            verdict = ("the tests couldn't tell if they help, so I'm not using them yet" if len(recent) > 2 else
                       "for both, the test couldn't tell if it helps, so I'm not using them yet")
        else:
            verdict = ", ".join(part for part in (f"{adopted} now in use" if adopted else "",
                                                  f"{unclear} too close to call" if unclear else "",
                                                  f"{others} set aside" if others else "") if part)
        out.append(f"🧪 Tested {len(recent)} new lessons in the last day: {verdict}.")
    conductor = (brain.facts or {}).get("conductor")
    if conductor:
        night = parse(f"{conductor.get('night', '')}T120000Z")
        label = f"night of {night:%b} {night.day}" if night else "last night"
        if conductor.get("off"):
            out.append(f"✍️ My homework writer is switched off ({label} was the last).")
        elif conductor.get("created") is not None:
            created, kept = int(conductor.get("created") or 0), int(conductor.get("accepted") or 0)
            out.append(f"✍️ Wrote {created} new practice questions for myself ({label}) and kept the {kept} that "
                       "passed my checks.")
    return out


# ------------------------------------------------------------------ Studio tests

def studio(lab: dict, clock: Clock) -> tuple[str, str, str]:
    """(level, short field value, plain sentence) for Studio Lab's last nightly run."""
    specs, ran, passed = int(lab.get("specs") or 0), int(lab.get("specs_ran") or 0), int(lab.get("passed") or 0)
    moment = parse(str(lab.get("run", "")).rsplit("-", 1)[-1])
    when = clock.when(moment) if moment else "last run"
    short = (("running now · last " if lab.get("running") else "") + when +
             f"\n**{passed}** of {specs} passed" + (f"\nonly {ran} got to run" if ran < specs else ""))
    skipped = specs - ran
    later = " The next run is tomorrow night" + (f", starting with the {skipped} that didn't run." if skipped else ".")
    if specs and ran == 0:
        return WARN, short, f"My Roblox Studio tests ({when}) didn't run at all: 0 of {specs} started.{later}"
    if ran and passed == 0:
        what = "it didn't pass" if ran == 1 else f"none of those {ran} passed"
        return WARN, short, (f"My Roblox Studio test run ({when}) went badly: only {ran} of {specs} tests got to run, "
                             f"and {what}.{later}" if skipped else
                             f"My Roblox Studio test run ({when}) went badly: all {specs} tests ran and none passed.")
    if skipped * 2 > specs:
        return WARN, short, (f"My Roblox Studio test run ({when}) only got through {ran} of {specs} tests "
                             f"({passed} passed).{later}")
    level = GOOD if passed == ran else INFO
    return level, short, f"Roblox Studio tests ({when}): {passed} of {ran} passed" + (
        f" ({skipped} didn't get to run)." if skipped else ".")


# ------------------------------------------------------------------ the whole card

def _practising(ns: dict | None) -> bool:
    return bool(ns) and not ns.get("paused") and _STATES.get((ns.get("report") or {}).get("status", "")) == "practising now"


def services(brain: BrainInput) -> tuple[list[str], list[Issue]]:
    """(failed unit names in plain words, issues) for one brain's systemd units."""
    facts = brain.facts or {}
    failed = [r.get("unit", "")[:-8] for r in facts.get("services", [])
              if r.get("unit", "").endswith(".service") and r.get("active") == "failed"]
    issues = []
    for unit in failed:
        fix = " You can ask me to restart it." if unit in RESTARTABLE else ""
        issues.append(Issue(BAD, f"{unit_name(unit).capitalize()} stopped on brain {brain.name}",
                            f"{unit_name(unit).capitalize()} on brain {brain.name} has stopped.{fix}"))
    return [unit_name(u) for u in failed], issues


def knowledge(facts: dict, clock: Clock) -> tuple[str, list[Issue]]:
    dog = facts.get("knowledge_watchdog")
    if not dog:
        return "", []
    if not dog.get("ok"):
        return "❌ knowledge search down", [Issue(BAD, "Knowledge search is down",
                                                  "My knowledge search isn't answering, so I can't look things up "
                                                  "in my library right now.")]
    recent = [r for r in dog.get("restarts") or [] if (parse(r.get("at")) or clock.now) > clock.now - timedelta(hours=24)]
    if recent:
        return f"🔎 search froze, restarted {clock.when(parse(recent[-1]['at']) or clock.now)}", []
    return "🔎 search ok", []


def build(brains: list[BrainInput], *, pc: dict | None, pc_age: float | None, pc_stale: float, jobs: list[dict],
          clock: Clock) -> Report:
    """The live status card's content: headline verdict, problems explained, and at most ~6 short fields."""
    report = Report()
    practice_fields, learned, system_lines, failed_any, labs = [], [], [], [], []
    for brain in brains:
        if brain.facts is None:
            report.issues.append(Issue(WARN, f"I can't reach brain {brain.name}",
                                       f"Brain {brain.name} didn't answer my status check"
                                       + (f" ({brain.why_missing})" if brain.why_missing else "")
                                       + ", so its numbers are missing from this card."))
            continue
        got, issues = practice(brain)
        if got:
            practice_fields.append(got)
        report.issues += issues
        lines = lessons(brain, clock)
        learned += [(brain.name, line) for line in lines]
        failed, issues = services(brain)
        failed_any += [f"{name} (brain {brain.name})" for name in failed]
        report.issues += issues
        line, issues = knowledge(brain.facts, clock)
        if line:
            system_lines.append(line)
        report.issues += issues
        if brain.facts.get("studio_lab"):
            labs.append((brain.name, brain.facts["studio_lab"]))
    report.fields += practice_fields
    if learned:
        both = len({name for name, _ in learned}) > 1
        report.fields.append(_field("📚 What I'm learning", "\n".join(
            (f"Brain {name}: " if both else "") + line for name, line in learned), inline=False))
    for name, lab in labs:
        level, short, sentence = studio(lab, clock)
        if level in {WARN, BAD}:
            report.issues.append(Issue(level, "Studio tests went badly", sentence))
        report.fields.append(_field(("⚠️" if level == WARN else "🎮") + " Studio tests", short))
    reached = [b for b in brains if b.facts is not None]
    head = ("❌ stopped: " + ", ".join(failed_any)) if failed_any else (
        "✅ everything running" if reached else "❔ no brain answered")
    report.fields.append(_field("🖥️ Systems", "\n".join([head] + system_lines)))
    if pc is not None and pc_age is not None and pc_age <= pc_stale:
        prs = pc.get("open_prs") or []
        failing = sum(1 for p in prs if p.get("checks") == "failing")
        bits = []
        if "open_prs" in pc:
            bits.append(f"{len(prs)} pull requests open" + (f" ({failing} need a fix)" if failing else ""))
            bits.append(f"{len(pc.get('merged_today') or [])} merged today")
        claims = len(pc.get("claims") or [])
        if claims:
            bits.append(f"{claims} tasks being worked on")
        report.fields.append(_field("💻 Your PC", "\n".join(bits) or "connected"))
    else:
        gone = "Not connected" if pc_age is None else f"No word from it for {round(pc_age / 60)} min"
        report.fields.append(_field("💻 Your PC", f"{gone}, so I can't see pull requests or the task "
                                    "board. Practice and chat don't need it. It reconnects when the STAR GPU worker "
                                    "runs on your PC.", inline=False))
    if jobs:
        report.fields.append(_field("Jobs you started", "\n".join(f"{j.get('label')}: {j.get('state')}"
                                                                  for j in jobs[-3:]), inline=False))
    report.issues.sort(key=lambda issue: -RANK[issue.level])
    if report.issues:
        top = report.issues[0]
        report.level = top.level
        more = len(report.issues) - 1
        report.headline = f"{ICON[top.level]} {top.headline}" + (f" (+{more} more)" if more else "")
    else:
        busy = [b.name for b in reached if _practising((b.facts or {}).get("night_school"))]
        report.headline = "✅ All good: I'm practising" if busy else "✅ All good"
        report.note = ((f"I'm practising Roblox coding on brain {' and brain '.join(busy)}. " if busy else "")
                       + "Nothing needs you.")
    return report
