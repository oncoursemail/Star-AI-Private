"""Clear owner commands in a DM, recognised without the model ("pause night school on brain 1", "PR 526?").

The quick model handled these unreliably in the sample conversations (it called a started job done, answered a PR
question from the wrong source, wrote its reasoning into the reply), so a plain command goes straight to
actions.parse_request; anything not matched here is still ordinary chat with the star_action tool.
"""
from __future__ import annotations

import re

_BRAIN = re.compile(r"\bbrain\s*([12])\b|\b(both)\b", re.I)
_NS = re.compile(r"^(?:star[, ]+)?(?:please\s+)?(start|stop|pause|resume|unpause|restart)\s+(?:the\s+)?night\s*school\b", re.I)
_RESTART = re.compile(r"^(?:star[, ]+)?(?:please\s+)?restart\s+(?:the\s+)?([a-z][a-z -]{2,40}?)(?:\s+service)?"
                      r"(?:\s+on\s+brain\s*[12])?\s*(?:please)?[.!]?$", re.I)
_PR = re.compile(r"\b(?:pr|pull request)\s*#?\s*(\d{1,6})\b|^#(\d{1,6})\??$", re.I)
_PR_ALL = re.compile(r"^(?:what(?:'s| is) the )?(?:pr|pull request|merge[- ]queue) status\??$|^(?:open )?prs\??$", re.I)
_IDEA = re.compile(r"^(?:star[, ]+)?(?:queue|add)\s+(?:a\s+)?practice\s+(?:idea|task)\s*[:\-]\s*(.{10,1500})$", re.I | re.S)
_RESEARCH = re.compile(r"^(?:star[, ]+)?research\s*[:\-]\s*(.{5,600})$", re.I | re.S)
_EVAL = re.compile(r"^(?:star[, ]+)?(?:please\s+)?run\s+(?:a\s+)?quick\s+eval\b", re.I)
_LAB = re.compile(r"^(?:star[, ]+)?(?:please\s+)?(?:start|run)\s+(?:a\s+)?studio\s*lab(?:\s+run)?\b", re.I)


def command(text: str) -> tuple[str, str, str] | None:
    """(action, brain, text) for a plain command, else None. Brain '' = the action's default."""
    text = " ".join(str(text or "").split())
    if not text or len(text) > 1600:
        return None
    brain_match = _BRAIN.search(text)
    brain = (brain_match.group(1) or "both") if brain_match else ""
    if match := _NS.match(text):
        verb = match.group(1).lower()
        if verb == "restart":
            return "restart_service", brain or "1", "star-night-school"
        verb = {"unpause": "resume"}.get(verb, verb)
        return f"night_school_{verb}", brain, ""
    if match := _IDEA.match(text):
        return "practice_idea", "", match.group(1)
    if match := _RESEARCH.match(text):
        return "research", "", match.group(1)
    if _EVAL.match(text):
        return "quick_eval", "", ""
    if _LAB.match(text):
        return "studio_lab_run", "", ""
    if match := _RESTART.match(text):
        return "restart_service", brain or "1", match.group(1)
    if match := _PR.search(text):
        if len(text) <= 80:
            return "pr_status", "", match.group(1) or match.group(2)
    if _PR_ALL.match(text):
        return "pr_status", "", ""
    return None


def started_text(label: str) -> str:
    return f"On it: {label}. I'll message you when it's done."
