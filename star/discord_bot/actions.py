"""What Star may actually DO when the owner asks from Discord: a fixed allow-list, nothing else.

Each action maps to an existing path: a gate verb on a brain (server/discord/gate/star_gate.py), the bot's own
research (service.research), drawing (the PC GPU worker) or the PC feed (PR status). Disruptive ones (restarts, a
Studio Lab run that occupies Studio) need the owner's button press first. Jobs run in the background, one per kind and
at most two at a time, so chat stays fast; every job reports back to the owner when it ends.
Merging and releasing are not here on purpose: those stay with the owner (STAR_EXECUTION_LEDGER standing rules).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import itertools
import json
import logging
import re

_LOG = logging.getLogger(__name__)
MAX_JOBS = 2
KEEP_JOBS = 12


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    disruptive: bool = False
    text: str = ""                  # what the free-text argument means ("" = none)
    brains: tuple[str, ...] = ()    # gate brains it can run on; () = runs in the bot


ACTIONS = {a.name: a for a in (
    Action("night_school_start", "start night school", brains=("1", "2")),
    Action("night_school_stop", "stop night school", brains=("1", "2")),
    Action("night_school_pause", "pause night school", brains=("1", "2")),
    Action("night_school_resume", "resume night school", brains=("1", "2")),
    Action("practice_idea", "queue a practice idea for tonight's conductor", text="the idea", brains=("1",)),
    Action("research", "research a question on the web", text="the question"),
    Action("quick_eval", "run the quick knowledge-search eval", brains=("1",)),
    Action("studio_lab_run", "start a Studio Lab run", disruptive=True, brains=("2",)),
    Action("draw", "draw a picture on the PC's GPU", text="what to draw"),
    Action("pr_status", "check PR / merge-queue status", text="a PR number, or empty for all"),
    Action("restart_service", "restart a service", disruptive=True, text="the service", brains=("1", "2")),
)}
_VERB = {"night_school_start": "ns-start", "night_school_stop": "ns-stop", "night_school_pause": "ns-pause",
         "night_school_resume": "ns-resume", "practice_idea": "idea", "quick_eval": "knowledge-eval",
         "studio_lab_run": "studio-lab-run"}
SERVICES = ("star-brain", "star-knowledge", "star-search-gateway", "star-night-school", "star-ns-brain",
            "star-discord", "searxng")

TOOL_SCHEMA = {"type": "function", "function": {
    "name": "star_action",
    "description": ("Do something for the owner (only when he asks you to). Actions: " +
                    "; ".join(f"{a.name} = {a.label}" + (" (asks him to confirm first)" if a.disruptive else "")
                              for a in ACTIONS.values()) +
                    ". Merges and releases are not possible from here."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "brain": {"type": "string", "enum": ["1", "2", "both"], "description": "which brain server (night school: both)"},
        "text": {"type": "string", "description": "idea, question, picture description, PR number or service name"},
    }, "required": ["action"]}}}


@dataclass
class Job:
    id: int
    label: str
    state: str = "running"          # running | done | failed
    started: str = ""
    result: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)

    def view(self) -> dict:
        return {"label": self.label, "state": self.state, "started": self.started, "result": self.result[:300]}


@dataclass(frozen=True)
class Request:
    action: Action
    brains: tuple[str, ...]
    text: str

    @property
    def label(self) -> str:
        where = f" on brain {' and '.join(self.brains)}" if self.brains else ""
        extra = f" ({self.text[:60]})" if self.text and self.action.name in {"restart_service", "pr_status"} else ""
        return self.action.label + extra + where


def parse_request(action: str, brain: str = "", text: str = "", *, gates=()) -> Request:
    """Check one action request; ValueError says what is wrong in plain words."""
    spec = ACTIONS.get(str(action or "").strip())
    if spec is None:
        raise ValueError("That isn't something I can do from Discord.")
    text = " ".join(str(text or "").split())[:1500]
    if spec.text and spec.name not in {"pr_status"} and not text:
        raise ValueError(f"I need {spec.text} for that.")
    brains: tuple[str, ...] = ()
    if spec.brains:
        wanted = str(brain or "").strip() or ("both" if len(spec.brains) > 1 and spec.name.startswith("night_school")
                                               else spec.brains[0])
        brains = spec.brains if wanted == "both" else (wanted,)
        if any(b not in spec.brains for b in brains):
            raise ValueError(f"{spec.label} only works on brain {' or '.join(spec.brains)}.")
        missing = [b for b in brains if b not in gates]
        if missing:
            raise ValueError(f"I have no control line to brain {', '.join(missing)} (STAR_DISCORD_GATE_"
                             f"{missing[0]} is not set).")
    if spec.name == "restart_service":
        name = text.lower().removesuffix(".service")
        name = name if name.startswith(("star-", "searxng")) else "star-" + name.replace(" ", "-")
        if name not in SERVICES:
            raise ValueError("I can restart: " + ", ".join(SERVICES) + ".")
        text = name
    if spec.name == "pr_status" and text:
        number = re.search(r"\d{1,6}", text)
        if not number:
            raise ValueError("Give me a PR number like #526, or nothing for all open PRs.")
        text = number.group(0)
    return Request(spec, brains, text)


def pr_status(feed: tuple[float, dict] | None, text: str) -> str:
    if feed is None or feed[0] > 600:
        return "My PC feed is missing or stale, so I can't see GitHub right now."
    age, pc = feed
    prs = pc.get("open_prs") or []
    if text:
        number = int(text.lstrip("#"))
        merged = [p for p in pc.get("merged_today", []) if p.get("number") == number]
        if merged:
            return f"#{number} was merged today: {merged[0].get('title')}."
        found = [p for p in prs if p.get("number") == number]
        if not found:
            return f"#{number} isn't among the {len(prs)} open PRs I can see (feed {int(age)} s old)."
        p = found[0]
        return (f"#{number} {p.get('title')}: {'draft' if p.get('draft') else 'ready'}, checks {p.get('checks')}, "
                f"merge state {p.get('merge') or 'unknown'} (feed {int(age)} s old).")
    counts = {}
    for p in prs:
        counts[p.get("checks")] = counts.get(p.get("checks"), 0) + 1
    ready = [p for p in prs if not p.get("draft") and p.get("checks") == "passing"]
    return (f"{len(prs)} open PRs: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) +
            (". Ready with green checks: " + ", ".join(f"#{p['number']}" for p in ready[:10]) if ready else "") +
            f". Merged today: {len(pc.get('merged_today', []))}.")


def _gate_text(brain: str, answer: dict, *, numbers: bool = True) -> str:
    text = str(answer.get("text", ""))[:400]
    if numbers and isinstance(answer.get("summary"), dict):
        text += " " + json.dumps(answer["summary"], separators=(",", ":"))[:900]
    return f"brain {brain}: {'ok' if answer.get('ok') else 'FAILED'}: {text}"


class ActionRunner:
    """Starts allow-listed jobs and reports back. `research(question)` and `draw(prompt)` are async callables the bot
    supplies (they return text / a Drawing); `feed()` returns the PC feed; `notify(text, file=None)` DMs the owner."""

    def __init__(self, gates: dict, *, notify=None, research=None, draw=None, feed=None, clock=None) -> None:
        self.gates = gates
        self.notify, self.research, self.draw, self.feed = notify, research, draw, feed
        self._ids = itertools.count(1)
        self.jobs: list[Job] = []
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def views(self) -> list[dict]:
        return [job.view() for job in self.jobs]

    def running(self) -> list[Job]:
        return [job for job in self.jobs if job.state == "running"]

    async def run_now(self, request: Request) -> str:
        """Quick, read-only actions answered in the same turn (no job)."""
        if request.action.name == "pr_status":
            return pr_status(self.feed() if self.feed else None, request.text)
        raise ValueError("not an instant action")

    def start(self, request: Request) -> Job:
        """A background job; the owner gets a DM when it ends. ValueError when it cannot start now."""
        if any(job.label == request.label for job in self.running()):
            raise ValueError(f"I'm already doing that ({request.label}).")
        if len(self.running()) >= MAX_JOBS:
            raise ValueError("I already have two jobs running; I'll take this when one finishes.")
        job = Job(next(self._ids), request.label, started=self._clock().strftime("%H:%M UTC"))
        self.jobs = (self.jobs + [job])[-KEEP_JOBS:]
        job.task = asyncio.ensure_future(self._run(job, request))
        return job

    async def _run(self, job: Job, request: Request) -> None:
        name, file, summary, card_parts = request.action.name, None, None, None
        try:
            if name in _VERB:
                payload = request.text if name == "practice_idea" else ""
                answers = await asyncio.gather(*(self.gates[b].call(_VERB[name], payload, timeout=900)
                                                 for b in request.brains), return_exceptions=True)
                parts, ok = [], True
                for brain, answer in zip(request.brains, answers):
                    if isinstance(answer, BaseException):
                        ok = False
                        parts.append(f"brain {brain}: FAILED: {str(answer)[:200] or type(answer).__name__}")
                    else:
                        ok = ok and answer.get("ok") is True
                        parts.append(_gate_text(brain, answer, numbers=False))
                        summary = answer.get("summary") if isinstance(answer.get("summary"), dict) else summary
                job.result, job.state = "; ".join(parts), "done" if ok else "failed"
                if summary:
                    from .embeds import _numbers
                    job.result += " | " + ", ".join(f"{k} {v}" for k, v in _numbers(summary)[:8])
                card_parts = parts
            elif name == "restart_service":
                answers = [await self.gates[b].call("restart:" + request.text, timeout=180) for b in request.brains]
                job.result = "; ".join(_gate_text(b, a) for b, a in zip(request.brains, answers))
                job.state = "done" if all(a.get("ok") for a in answers) else "failed"
            elif name == "research":
                if self.research is None:
                    raise ValueError("research is not connected")
                job.result, job.state = await self.research(request.text), "done"
            elif name == "draw":
                if self.draw is None:
                    raise ValueError("drawing is not connected")
                picture = await self.draw(request.text)
                file, job.result, job.state = picture, picture.caption(), "done"
            else:
                raise ValueError("not a background action")
        except asyncio.CancelledError:
            job.state, job.result = "failed", "cancelled"
            raise
        except Exception as exc:        # a failed job must still report back
            job.state, job.result = "failed", (str(exc)[:400] or type(exc).__name__)
            _LOG.info("Discord job %s failed (%s)", job.id, type(exc).__name__)
        if self.notify is not None:
            word = "Done" if job.state == "done" else "That didn't work"
            from .embeds import drawing_card, job_card
            if file is not None and hasattr(file, "png"):
                card = drawing_card(file.prompt, file.filename, seconds=getattr(file, "seconds", None))
            elif name == "research" and job.state == "done":
                card = None                     # a research answer is prose: plain text in her voice
            else:
                card = job_card(job.label, job.state == "done", card_parts or [job.result], summary=summary)
            try:
                await self.notify(f"{word}: {job.label}.\n{job.result}"[:1900], file, card)
            except Exception as exc:
                _LOG.warning("Job report DM failed (%s)", type(exc).__name__)
