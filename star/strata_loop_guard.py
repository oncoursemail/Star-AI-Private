"""Bounded stream watchdog for Strata issue #728 (repeating whole passages).

Strata has opt-in engine-side recovery (0.1.40+); STAR adds a conservative
client-side circuit breaker. It does not retry model/tool calls or claim to
repair model weights. The checker retains at most 8 KiB of transient text per
channel in memory and never logs the generated text.
"""
from __future__ import annotations

from collections import Counter
import re

MAX_TAIL = 8192
_CHECK_EVERY_CHARS = 256
_MIN_CHARS = 1600
_MIN_WORDS = 125
_SHINGLE = 12
_WORDS = re.compile(r"[^\W_]+|[.!?]", re.UNICODE)


class StrataRepetitionError(RuntimeError):
    """Strata generated an extended repetitive passage; task must not be replayed."""

    def __init__(self, section: str):
        self.section = section
        super().__init__(
            "Strata repeatedly generated the same " + section +
            " passage. STAR stopped the response (Strata issue #728) "
            "without retrying any project actions. Check the Strata model "
            "quantization/sampling and enable reasoning_loop_recovery='recover' "
            "in the Strata server config."
        )


def _periodic_tail(text: str) -> bool:
    """Detect a repeated character motif, including a huge single numeric word."""
    recent = text[-1536:]
    if len(recent) < 1536:
        return False
    return any(recent[:-period] == recent[period:] for period in range(1, 129))


def _repeated_passages(text: str) -> bool:
    """Require 92% of the latest long word shingles to occur at least 3 times."""
    words = _WORDS.findall(text.casefold())
    if len(words) < _MIN_WORDS:
        return False
    grams = [tuple(words[i:i + _SHINGLE])
             for i in range(len(words) - _SHINGLE + 1)]
    counts = Counter(grams)
    recent = grams[-min(len(grams), 120):]
    # This tests *current* looping, not an earlier repetition that has ended.
    return sum(counts[gram] >= 3 for gram in recent) >= (len(recent) * 92 + 99) // 100


class StrataRepetitionGuard:
    """Binds work per channel so chunk boundaries do not defeat repetition checks.

    'reasoning' and 'answer' are checked independently. Tool arguments are
    excluded because repeating field names in JSON is normal, and STAR already
    enforces a strict tool-call budget.
    """

    def __init__(self):
        self._tails = {"reasoning": "", "answer": ""}
        self._sizes = {"reasoning": 0, "answer": 0}
        self._checked = {"reasoning": 0, "answer": 0}

    def feed(self, section: str, fragment: str) -> None:
        if section not in self._tails:
            raise ValueError("Unknown Strata stream section")
        if not isinstance(fragment, str) or not fragment:
            return
        self._sizes[section] += len(fragment)
        self._tails[section] = (self._tails[section] + fragment)[-MAX_TAIL:]
        total = self._sizes[section]
        if total < _MIN_CHARS or total - self._checked[section] < _CHECK_EVERY_CHARS:
            return
        self._checked[section] = total
        tail = self._tails[section]
        if _periodic_tail(tail) or _repeated_passages(tail):
            raise StrataRepetitionError(section)
