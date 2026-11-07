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
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(?:\s+|$)|\n+")
_STREAM_END = re.compile(r"[.!?][\"')\]]*\s+|\n+")
START_CHECK_CHARS = 24          # enough to see an opener; the first words of a normal answer are not held back
HEDGE_LIMIT = 3
MAX_UNFINISHED_CHARS = 4096     # non-whitespace prose; fenced code is masked before this check
MAX_BUFFERED_CHARS = 65536      # also bound whitespace, think blocks and an unfinished code block


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


def prose_only(text: str) -> str:
    """The text with fenced code blocks (also an unfinished one) blanked out, same length, so offsets still match."""
    return _FENCE.sub(lambda m: " " * len(m.group()), text)


def plan_start(prose: str) -> int | None:
    """Offset of the first sentence in which the model talks about how it will answer (persona.leaked_reasoning),
    None when there is none. An unfinished last sentence counts too."""
    from .persona import leaked_reasoning
    start = 0
    for end in [m.end() for m in _SENTENCE_END.finditer(prose)] + [len(prose)]:
        if end > start and leaked_reasoning(prose[start:end]):
            return start
        start = max(start, end)
    return None


def safe_end(prose: str) -> int:
    """Only complete sentences may stream: later chunks can complete a rejected phrase."""
    ends = [m.start() + len(m.group().rstrip()) for m in _STREAM_END.finditer(prose)]   # require a following separator
    return ends[-1] if ends else 0


def unfinished_too_long(prose: str) -> bool:
    return sum(not char.isspace() for char in prose[safe_end(prose):]) > MAX_UNFINISHED_CHARS
