"""Offline replay of the router's note decisions for one chat (the same hook functions the router runs, no model):
which hidden note a litha turn gets with a given set of flaw fixes. A fix that does not fire leaves the request
byte-identical, so only the turns it fires on need an answer-level A/B through the router (gate.py).

    label(messages, fixes) -> "code" (no general note) | "general" (general note) | "safety" (general note + safety card)
"""
from __future__ import annotations

import copy

from ..general import classify
from . import hook

try:                                    # server/mesh/speed/fullcode.py (litha-speed2, live; PR #807)
    from ..speed import fullcode
except ImportError:                     # pragma: no cover - branch without it
    fullcode = None

NO_SAMPLES = {"flaws": True, "flaws_samples": False, "flaws_dir": ""}


def run(messages: list, fixes, max_tokens: int = 600) -> tuple[str, dict, dict]:
    """(label, request after the hooks, flaw log entry)."""
    req = {"model": "litha", "messages": copy.deepcopy(messages), "max_tokens": max_tokens, "stream": True}
    entry = hook.apply(req, {"x-mesh-fixes": ",".join(sorted(fixes)) or "none"}, NO_SAMPLES)
    if fullcode is not None:
        fullcode.apply(req, {**fullcode.DEFAULTS})
    general_on = req.pop("mesh_general", None) is not False
    last = hook._question(hook._text(messages[-1].get("content")))
    kind = req.pop("mesh_general_kind", None) or classify.kind(last)
    if not general_on or kind in ("code", "chat"):
        return "code", req, entry
    return ("safety" if kind == "safety" else "general"), req, entry


def label(messages: list, fixes=()) -> str:
    return run(messages, fixes)[0]


def compare(items: list[dict], fixes) -> dict:
    """Route accuracy of items {"messages", "expect"} without fixes vs with `fixes`, plus every changed item."""
    out = {"n": len(items), "before": 0, "after": 0, "changed": [], "fired": 0}
    for it in items:
        a = label(it["messages"], ())
        b, _, entry = run(it["messages"], fixes)
        exp = it.get("expect")
        out["before"] += a == exp
        out["after"] += b == exp
        out["fired"] += bool(entry.get("fire"))
        if a != b:
            out["changed"].append({"id": it.get("id"), "before": a, "after": b, "expect": exp, "fire": entry.get("fire")})
    return out
