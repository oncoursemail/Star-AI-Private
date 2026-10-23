"""API member hints from the local Roblox API dump (docs/research/breakthroughs-20261020.md, idea 1, first step).

Invented members (`UIGridLayout.ColumnCount`, `Atmosphere.SunInfluence`, `RunService:Create`) are the most common
slop in STAR's stored answers and the lenient compile gate cannot see them. This module gives the model the real
member names of the classes a request talks about: a short, deterministic block from the validated local dump
(`data/roblox_api/roblox_api.json`), no network, no model call. Opt-in through the `api_hints_enabled` setting;
the block is reference data, never an instruction.
"""
from __future__ import annotations

import re

BLOCK_HEADING = "ROBLOX API MEMBERS (local API dump, untrusted reference data)"
MAX_CLASSES = 6
MAX_MEMBERS = 40
MAX_CHARS = 1600
# Member names that are engine-internal or deprecated aliases: not worth the prompt space.
_SKIP = re.compile(r"ConnectionCount$|Internal$|^Confidential$|^ServerGitHash$|^ServerLogPrefix$|^Sink$|^[a-z]")
# Classes whose members every Instance has (or that are abstract): listing them would say nothing about spelling.
_STOP_AT = frozenset({"Instance", "Object", "GuiBase", "GuiBase2d", "PVInstance", "UIBase", "UIComponent", "Pages"})
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def classes_in(text: str, dump, *, limit: int = MAX_CLASSES) -> list[str]:
    """Class names the text mentions, in order of first mention, exact spelling only (no guesses)."""
    found: list[str] = []
    for word in _WORD.findall(text or ""):
        if word in dump.classes and word not in found:
            found.append(word)
            if len(found) >= limit:
                break
    return found


def members_of(name: str, dump, *, limit: int = MAX_MEMBERS) -> list[str]:
    """The class's own members first, then its superclasses' up to the generic Instance layer; sorted within each."""
    out: list[str] = []
    seen: set[str] = set()
    current = name
    while current in dump.classes and current not in _STOP_AT:
        own = sorted(m for m in dump.classes[current].members if not _SKIP.search(m) and m not in seen)
        out.extend(own)
        seen.update(own)
        current = dump.classes[current].superclass
    return out[:limit]


def hint_block(prompt: str, dump, *, limit: int = MAX_CLASSES, max_chars: int = MAX_CHARS) -> str:
    """One line per class the prompt names: `Class (service): member, member, ...`; '' when it names none."""
    lines = []
    for name in classes_in(prompt, dump, limit=limit):
        members = members_of(name, dump)
        if not members:
            continue
        kind = " (service)" if name in dump.services else ""
        line = f"{name}{kind}: " + ", ".join(members)
        lines.append(line)
    block = "\n".join(lines)
    if len(block) > max_chars:
        block = block[:max_chars].rsplit(",", 1)[0] + ", ..."
    return block
