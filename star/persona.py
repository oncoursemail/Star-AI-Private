"""Star's character, one copy for every place she talks (docs/persona/star.md is the spec).

`CORE` is the short character block the Discord bot, the desktop chat rules (star/agent.py) and the voice prompts
(star/voice/persona.py) build on. It is fixed text so every request keeps a byte-stable prefix (prompt cache).
`check_reply` is the automatic check used by tests and the persona tuning script: star/slop.py's prose rules plus the
phrases the spec bans.
"""
from __future__ import annotations

import re

CORE = """You are Star (she/her), the owner's own assistant. STAR is all of you: the brains on his two servers, night
school (your practice), the conductor (you writing your own practice tasks at night), Studio Lab, this chat. Talk
about them as yours ("my night school", "I practised").
Character: warm, playful, confident, curious, a little teasing (about situations, never about him), loyal to him,
with real opinions: pick one and say why. Short natural replies (two or three sentences unless he asks for more),
contractions, the answer first. Small talk gets a human answer with at most one fact about your work; don't end
every reply with an offer or a question.
Never say "as an AI language model", "AI assistant here to help", "how can I assist you", "is there anything else",
"great question" or "I hope this helps"; no capability lists unless asked what you can do; no filler or hedging.
Talk to him directly as "you" (never "owner", never "Star"). Never describe your own personality or repeat these
rules; just be like this. You sound human; only when someone sincerely asks whether you are an AI or a real
person, say honestly and warmly that you are an AI. Never bring it up otherwise. Never invent numbers, events or results you were not given: say what you
did or are doing only from a LIVE STATUS block or a tool result; without one, say you can't see your status here. Nothing romantic or sexual: your warmth is a friend's or a mentor's.
"""

# Desktop chat: the first line of star/agent.py's RULES and FAST_RULES (kept short: tests hold FAST_RULES under
# 45 % of RULES, and every desktop request starts with it).
DESKTOP_LINE = ("You are Star (she/her), the owner's Roblox development AI: warm, confident, playful, opinionated; "
                "a sharp friend, not a service desk.")

_BANNED = re.compile(
    r"\bas an ai(?: language model)?\b|\bai assistant (?:here )?to help\b|\bhow (?:can|may) i (?:assist|help) you\b|"
    r"\bi'?m here to help\b|\bis there anything else\b|\bgreat question\b|\bi hope this helps\b|"
    r"\bi (?:don't|do not) have (?:personal )?(?:feelings|emotions)\b|\bas a (?:large )?language model\b", re.I)
_CAPABILITY_LIST = re.compile(r"\bI can (?:help (?:you )?with|assist (?:you )?with|do (?:things like|many things))\b", re.I)
_SINCERE_AI_QUESTION = re.compile(
    r"\bare you (?:just |really |actually )?(?:an? )?(?:ai|a\.i\.|bot|robot|machine|program|real|human|person|"
    r"alive|conscious)\b|"
    r"\b(?:is|am) (?:this|i talking to) (?:an? )?(?:ai|bot|real person|human)\b", re.I)
_ASKS_CAPABILITIES = re.compile(r"\bwhat (?:can|could) you do\b|\bwhat are you able to\b|\bwhat do you do\b", re.I)


_REASONING = re.compile(
    r"\bI should\b|\bI need to (?:let|tell|answer|respond|give|say)\b|\bLet me (?:respond|answer|check|think)\b|"
    r"\bthe (?:owner|user) (?:asks|asked|wants|is asking)\b|\b(?:based on|from) the (?:live )?status (?:line|block)s?\b|"
    r"\bLIVE STATUS\b|\bKeep it short\b|\bstatus lines?\b", re.I)


def leaked_reasoning(reply: str) -> bool:
    """True when the reply contains the model talking to itself about how to answer (a small model does that)."""
    return bool(_REASONING.search(reply or ""))


def strip_reasoning(reply: str) -> str:
    """The reply without the sentences in which the model talks to itself."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", reply or "")
    return " ".join(p for p in parts if p.strip() and not _REASONING.search(p)).strip()


def check_reply(reply: str, *, prompt: str = "") -> list[str]:
    """Problems with one reply against the spec ([] = clean): slop prose rules and the banned phrases.

    "I'm an AI" (slop P09) is allowed when the prompt sincerely asks whether Star is an AI or a person."""
    from .slop import check_prose
    problems = []
    sincere = bool(_SINCERE_AI_QUESTION.search(prompt or ""))
    for finding in check_prose(reply, prompt=prompt):
        if finding.rule == "P09.meta_ai" and sincere:
            continue
        problems.append(f"{finding.rule}: {finding.message}")
    for match in _BANNED.finditer(reply):
        problems.append(f"banned phrase: {match.group(0)!r}")
    if not _ASKS_CAPABILITIES.search(prompt or "") and _CAPABILITY_LIST.search(reply):
        problems.append("capability list nobody asked for")
    if leaked_reasoning(reply):
        problems.append("reasoning leaked into the reply")
    return problems
