"""Anti-slop rules for STAR's own answers (packs `antislop*`, from github.com/miqdadbadjuber/anti-slop, MIT).

The six packs live in star/skill_packs/antislop*/ (verbatim upstream SKILL.md plus a short `digest.md`). They are
not Roblox packs, so they do not go through `skill_packs.select`. This module picks them by topic for UI, web, copy
and code-generation turns; the core digest always comes with one specialised digest. Only the digests are added to
a turn (about 4 KB at most), never the 9 to 58 KB reference text. Roblox, Godot and named-engine prompts are left
alone (they have their own measured packs), and so is quick chat mode (the caller skips it).

Switch off with STAR_ANTISLOP=off. The packs are not measured by the evaluation gate (docs/evals.md) yet.
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re

from .agent_skills import _frontmatter
from .skill_packs import ENGINE_CONTEXTS, PACKS_DIR

ENV_VAR = "STAR_ANTISLOP"
CORE = "antislop"
HEADING = "ANTI-SLOP RULES (STAR's writing and design rules for this answer; not part of the request)"
MAX_BLOCK_CHARS = 5200

_SKIP = re.compile(r"\b(?:roblox|luau|roblox studio|godot|gdscript|instance\.new|screengui)\b", re.IGNORECASE)

# Specialised packs in tie-break order; each needs at least one hit.
TOPICS: dict[str, re.Pattern] = {
    "antislop-ui": re.compile(
        r"\b(?:ui|ux|user interface|landing pages?|web ?sites?|web ?pages?|home ?page|html|css|tailwind|react|vue|svelte|"
        r"front-?end|dashboards?|navbar|hero section|buttons?|modals?|components?|dark mode|themes?|gradients?|"
        r"mock-?ups?|figma|style guide|design system|web app)\b", re.IGNORECASE),
    "antislop-layoutmobile": re.compile(
        r"\b(?:mobile|responsive|breakpoints?|overflow|viewport|tap targets?|flexbox|css grid|media quer\w+|reflow|"
        r"phone|tablet|touch)\b", re.IGNORECASE),
    "antislop-human": re.compile(
        r"\b(?:accessib\w+|a11y|wcag|contrast|keyboard navigation|focus (?:ring|state|outline)s?|screen readers?|aria|"
        r"alt text|colou?r-?blind|tab order)\b", re.IGNORECASE),
    "antislop-copywriting": re.compile(
        r"\b(?:copy|copywriting|headlines?|taglines?|slogans?|microcopy|marketing|blog post|press release|"
        r"product description|ad copy|cta|call to action|sounds? like (?:an? )?(?:ai|chatbot)|ai[- ]sounding|"
        r"rewrite (?:this|my|the) (?:text|copy|email|post|paragraph)|proofread|em dash(?:es)?)\b", re.IGNORECASE),
    "antislop-code": re.compile(
        r"\b(?:code comments?|comments? (?:in|on|for) (?:the |my |this )?code|docstrings?|jsdoc|"
        r"(?:write|implement|create|generate|refactor|build|port|code up)\b[^.\n]{0,60}\b(?:function|class|method|script|"
        r"module|endpoint|api|cli|program|code|query|regex|hook|library|unit tests?)s?)\b", re.IGNORECASE),
}
_ORDER = tuple(TOPICS)


def enabled(environ=None) -> bool:
    raw = (os.environ if environ is None else environ).get(ENV_VAR, "").strip().lower()
    return raw not in {"off", "none", "no", "false", "0"}


@lru_cache(maxsize=16)
def _digest(name: str) -> str:
    """The pack's digest, '' when the pack folder is missing or broken (never fatal)."""
    folder = PACKS_DIR / name
    try:
        fields, _body = _frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
        if fields.get("name") != name:
            return ""
        return (folder / "digest.md").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError, ValueError):
        return ""


def select(prompt, *, environ=None) -> list[str]:
    """Pack names for this prompt: the core first, then the best specialised pack. [] for anything else."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000 or not enabled(environ):
        return []
    if _SKIP.search(prompt) or any(context.search(prompt) for context in ENGINE_CONTEXTS.values()):
        return []
    best, best_hits = None, 0
    for name in _ORDER:
        hits = len({m.group(0).lower() for m in TOPICS[name].finditer(prompt)})
        if hits > best_hits:
            best, best_hits = name, hits
    return [CORE, best] if best else []


def render(names) -> str:
    """The text added to the turn under HEADING, '' when nothing applies. Bounded by MAX_BLOCK_CHARS."""
    parts = [text for text in (_digest(name) for name in names) if text]
    if not parts:
        return ""
    return "\n\n".join(parts)[:MAX_BLOCK_CHARS].rstrip() + "\n"
