"""Keep a model's own reasoning out of the chat, and stop a quick model that loops instead of answering.

A thinking model on the quick route (llama.cpp `reasoning = off`) can still write its chain of thought into the
reply text: "We need to solve ... Alternatively ... Could be ...". `strip_think` hides <think> blocks (also an
unfinished one), `starts_as_reasoning` recognises that opening, and `is_looping` recognises text that goes round in
circles. The stream reader (star.agent.read_stream) uses them for plain chat turns only.
"""
from __future__ import annotations

import re

_THINK = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
_OPEN_THINK = re.compile(r"<think>.*\Z", re.S | re.I)
_OPENER = re.compile(
    r"^\s*(?:we need to\b|we have to\b|let'?s (?:compute|calculate|parse|think|solve|see|figure|interpret)\b|"
    r"okay,? (?:so|let)\b|hmm\b|the user (?:is asking|wants|asks|wrote|says)\b|i need to (?:figure|compute|parse|solve|interpret)\b)", re.I)
_HEDGES = re.compile(r"\b(?:alternatively|could be|but maybe|maybe they|perhaps they|wait,|let'?s assume|or maybe)\b", re.I)
START_CHECK_CHARS = 24          # enough to see an opener; the first words of a normal answer are not held back
HEDGE_LIMIT = 3


class ReasoningLoop(Exception):
    """The quick model wrote its reasoning (or looped) before any answer text was shown."""


def strip_think(text: str) -> str:
    """The reply without <think> blocks. An unfinished block hides everything after it."""
    return _OPEN_THINK.sub("", _THINK.sub("", text))


def starts_as_reasoning(text: str) -> bool:
    return len(text.strip()) >= START_CHECK_CHARS and bool(_OPENER.match(text))


def is_looping(text: str) -> bool:
    """Reasoning that keeps hedging, or text whose last stretch has already appeared twice before."""
    if len(_HEDGES.findall(text)) >= HEDGE_LIMIT:
        return True
    tail = text[-60:]
    return len(text) >= 400 and len(tail.strip()) == 60 and text.count(tail) >= 3


def trim_loop(text: str) -> str:
    """The text up to where the repetition began, cut at a sentence end."""
    cut = text
    for match in list(_HEDGES.finditer(text))[:1]:
        cut = text[:match.start()]
    cut = cut.rstrip()
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("\n"))
    return cut[:end + 1].rstrip() if end > 40 else cut
