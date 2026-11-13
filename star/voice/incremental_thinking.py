"""Causal gate for safe incremental thinking over streamed ASR hypotheses.

The coordinator lets a trusted voice host start or revise a background thinker
when a semantic prefix is stable across consecutive ASR hypotheses. It never
speaks, executes tools, changes permissions, or commits a partial transcript to
conversation history. Only an explicit final hypothesis can be committed.

Transcript text is held in memory for this utterance only. Metrics are
content-free. The host must keep this module off model-tool and public-event
surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from threading import RLock
from typing import cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_MAX_TEXT_CHARS = 4096
_MAX_UTTERANCE_MS = 60_000.0
_MAX_CLOCK_MS = 1e13
_MAX_SEEN_UTTERANCES = 4096
_ALLOWED_CANCEL_REASONS = frozenset({
    "barge_in", "call_end", "host_reset", "asr_error", "timeout", "user_resume",
})


class ThinkAction(str, Enum):
    WAIT = "wait"
    START = "start"
    UPDATE = "update"
    CANCEL = "cancel"
    FINALIZE = "finalize"
    REJECT = "reject"


@dataclass(frozen=True)
class PartialHypothesis:
    """One cumulative ASR snapshot; sequence is strictly increasing per utterance."""

    utterance_id: str
    sequence: int
    captured_ms: float
    text: str
    asr_confidence: float
    semantic_score: float
    final: bool = False

    def __post_init__(self) -> None:
        if type(self.utterance_id) is not str or _ID.fullmatch(self.utterance_id) is None:
            raise ValueError("utterance_id must be a bounded opaque identifier")
        if type(self.sequence) is not int or not 0 <= self.sequence <= 1_000_000:
            raise ValueError("sequence must be a bounded nonnegative integer")
        _finite(self.captured_ms, "captured_ms", 0.0, _MAX_CLOCK_MS)
        if type(self.text) is not str or len(self.text) > _MAX_TEXT_CHARS:
            raise ValueError("text must be a bounded string")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in self.text):
            raise ValueError("text contains unsupported control characters")
        _finite(self.asr_confidence, "asr_confidence", 0.0, 1.0)
        _finite(self.semantic_score, "semantic_score", 0.0, 1.0)
        if type(self.final) is not bool:
            raise ValueError("final must be boolean")


@dataclass(frozen=True)
class ThinkDirective:
    """Host-only control result. No directive grants speech or tool authority."""

    action: ThinkAction
    utterance_id: str
    revision: int
    stable_prefix: str = ""
    final_text: str = ""
    reason: str = ""
    cancel_previous: bool = False
    commit_final: bool = False

    @property
    def may_speak(self) -> bool:
        return False

    @property
    def may_execute_tools(self) -> bool:
        return False


def _finite(value: object, label: str, low: float, high: float) -> float:
    if type(value) is int:
        number = float(cast(int, value))
    elif type(value) is float:
        number = cast(float, value)
    else:
        raise ValueError(f"{label} must be a finite number")
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} is outside its supported range")
    return number


def _tokens(text: str) -> list[re.Match[str]]:
    return list(_TOKEN.finditer(text))


def _stable_prefix(previous: str, current: str) -> tuple[str, int]:
    """Return the common prefix whose last token is complete in the new snapshot."""
    old_tokens = _tokens(previous)
    new_tokens = _tokens(current)
    common = 0
    for old, new in zip(old_tokens, new_tokens):
        if old.group().casefold() != new.group().casefold():
            break
        common += 1
    if common == 0:
        return "", 0

    last = new_tokens[common - 1]
    token = last.group()
    # A trailing word may still be growing. Punctuation or a following
    # separator makes the boundary complete in the current ASR snapshot.
    if token[-1:].isalnum() or token.endswith("_"):
        if last.end() >= len(current):
            common -= 1
        elif not (current[last.end()].isspace() or current[last.end()] in ",;:!?." ):
            common -= 1
    if common <= 0:
        return "", 0
    end = new_tokens[common - 1].end()
    prefix = current[:end].strip()
    word_count = sum(1 for match in new_tokens[:common] if any(ch.isalnum() for ch in match.group()))
    return prefix, word_count


def _is_prefix(prefix: str, text: str) -> bool:
    return text.casefold().startswith(prefix.casefold())


class IncrementalThinkCoordinator:
    """Bounded Listen-Think-Speak policy for one live voice session.

    A START/UPDATE directive may feed a background, read-only reasoning job.
    The job must be cancellable and must not call tools, speak, write memory, or
    mutate external state. FINALIZE supplies the canonical final transcript;
    ordinary authorization and safety checks still happen downstream.
    """

    def __init__(
        self,
        *,
        min_stable_tokens: int = 5,
        min_asr_confidence: float = 0.78,
        min_semantic_score: float = 0.72,
        max_partial_age_ms: float = 900.0,
        max_utterance_ms: float = 30_000.0,
        max_seen_utterances: int = 4096,
    ) -> None:
        if type(min_stable_tokens) is not int or not 2 <= min_stable_tokens <= 64:
            raise ValueError("min_stable_tokens must be in 2..64")
        self._min_tokens = min_stable_tokens
        self._min_asr = _finite(min_asr_confidence, "min_asr_confidence", 0.0, 1.0)
        self._min_semantic = _finite(min_semantic_score, "min_semantic_score", 0.0, 1.0)
        self._max_age = _finite(max_partial_age_ms, "max_partial_age_ms", 100.0, 5000.0)
        self._max_duration = _finite(max_utterance_ms, "max_utterance_ms", 1000.0, _MAX_UTTERANCE_MS)
        if type(max_seen_utterances) is not int or not 1 <= max_seen_utterances <= _MAX_SEEN_UTTERANCES:
            raise ValueError("max_seen_utterances must be in 1..4096")
        self._max_seen = max_seen_utterances
        self._lock = RLock()
        self._seen: set[str] = set()
        self._active_id: str | None = None
        self._started_ms = 0.0
        self._last_ms = 0.0
        self._last_sequence = -1
        self._last_text = ""
        self._stable = ""
        self._revision = 0
        self._thinking = False
        self._fault = False
        self._counts = {
            "accepted": 0,
            "started": 0,
            "updated": 0,
            "cancelled": 0,
            "finalized": 0,
            "rejected": 0,
            "stale": 0,
            "expired": 0,
        }

    def _directive(
        self,
        action: ThinkAction,
        *,
        utterance_id: str = "",
        stable_prefix: str = "",
        final_text: str = "",
        reason: str,
        cancel_previous: bool = False,
        commit_final: bool = False,
    ) -> ThinkDirective:
        return ThinkDirective(
            action=action,
            utterance_id=utterance_id,
            revision=self._revision,
            stable_prefix=stable_prefix,
            final_text=final_text,
            reason=reason,
            cancel_previous=cancel_previous,
            commit_final=commit_final,
        )

    def _clear_active(self) -> None:
        self._active_id = None
        self._started_ms = 0.0
        self._last_ms = 0.0
        self._last_sequence = -1
        self._last_text = ""
        self._stable = ""
        self._thinking = False

    def _begin(self, utterance_id: str, captured_ms: float) -> None:
        if len(self._seen) >= self._max_seen:
            self._fault = True
            raise RuntimeError("utterance replay guard capacity exhausted")
        self._seen.add(utterance_id)
        self._active_id = utterance_id
        self._started_ms = captured_ms
        self._last_ms = captured_ms
        self._last_sequence = -1
        self._last_text = ""
        self._stable = ""
        self._revision = 0
        self._thinking = False

    def observe(self, item: PartialHypothesis, *, now_ms: float) -> ThinkDirective:
        """Observe one cumulative ASR snapshot and return a non-authorizing directive."""
        if type(item) is not PartialHypothesis:
            raise TypeError("item must be PartialHypothesis")
        now = _finite(now_ms, "now_ms", 0.0, _MAX_CLOCK_MS)
        captured = _finite(item.captured_ms, "captured_ms", 0.0, _MAX_CLOCK_MS)
        with self._lock:
            if self._fault:
                self._counts["rejected"] += 1
                return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                       reason="coordinator_faulted")
            if captured > now:
                self._counts["rejected"] += 1
                return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                       reason="future_hypothesis")
            if now - captured > self._max_age:
                self._counts["stale"] += 1
                if self._active_id == item.utterance_id:
                    old_id = self._active_id
                    cancel = self._thinking
                    self._clear_active()
                    self._counts["cancelled"] += int(cancel)
                    return self._directive(ThinkAction.CANCEL, utterance_id=old_id or "",
                                           reason="stale_hypothesis", cancel_previous=cancel)
                self._counts["rejected"] += 1
                return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                       reason="stale_hypothesis")

            cancel_previous = False
            if self._active_id is None:
                if item.utterance_id in self._seen:
                    self._counts["rejected"] += 1
                    return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                           reason="utterance_replay")
                try:
                    self._begin(item.utterance_id, captured)
                except RuntimeError:
                    self._counts["rejected"] += 1
                    return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                           reason="replay_guard_capacity")
            elif self._active_id != item.utterance_id:
                if item.utterance_id in self._seen:
                    self._counts["rejected"] += 1
                    return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                           reason="utterance_replay")
                old_id = self._active_id
                cancel_previous = self._thinking
                self._counts["cancelled"] += int(cancel_previous)
                self._clear_active()
                try:
                    self._begin(item.utterance_id, captured)
                except RuntimeError:
                    self._counts["rejected"] += 1
                    return self._directive(ThinkAction.REJECT, utterance_id=old_id or "",
                                           reason="replay_guard_capacity", cancel_previous=cancel_previous)
            else:
                if item.sequence <= self._last_sequence or captured < self._last_ms:
                    self._counts["rejected"] += 1
                    return self._directive(ThinkAction.REJECT, utterance_id=item.utterance_id,
                                           reason="out_of_order_hypothesis")
                if now - self._started_ms > self._max_duration:
                    old_id = self._active_id
                    cancel_previous = self._thinking
                    self._clear_active()
                    self._counts["expired"] += 1
                    self._counts["cancelled"] += int(cancel_previous)
                    return self._directive(ThinkAction.CANCEL, utterance_id=old_id or "",
                                           reason="utterance_duration_limit", cancel_previous=cancel_previous)

            self._last_sequence = item.sequence
            self._last_ms = captured
            self._counts["accepted"] += 1

            if item.final:
                final_text = item.text.strip()
                if not final_text:
                    old_id = self._active_id or item.utterance_id
                    cancel_previous = self._thinking
                    self._clear_active()
                    self._counts["cancelled"] += int(cancel_previous)
                    return self._directive(ThinkAction.CANCEL, utterance_id=old_id,
                                           reason="empty_final_transcript", cancel_previous=cancel_previous)
                if self._stable and not _is_prefix(self._stable, final_text):
                    cancel_previous = self._thinking
                utterance_id = self._active_id or item.utterance_id
                self._revision += int(final_text != self._last_text)
                self._counts["finalized"] += 1
                directive = self._directive(
                    ThinkAction.FINALIZE,
                    utterance_id=utterance_id,
                    stable_prefix=self._stable,
                    final_text=final_text,
                    reason="canonical_final_transcript",
                    cancel_previous=cancel_previous,
                    commit_final=True,
                )
                self._clear_active()
                return directive

            stable, stable_tokens = _stable_prefix(self._last_text, item.text)
            invalidated = bool(self._stable and stable and not _is_prefix(self._stable, stable))
            invalidated = invalidated or bool(self._stable and not stable)
            if invalidated:
                cancel_previous = self._thinking
                self._revision += 1
                self._thinking = False
                self._counts["cancelled"] += int(cancel_previous)

            previous_stable = self._stable
            self._last_text = item.text
            self._stable = stable

            ready = (
                stable_tokens >= self._min_tokens
                and item.asr_confidence >= self._min_asr
                and item.semantic_score >= self._min_semantic
            )
            if ready and not self._thinking:
                self._thinking = True
                self._counts["started"] += 1
                return self._directive(
                    ThinkAction.START,
                    utterance_id=item.utterance_id,
                    stable_prefix=stable,
                    reason="stable_semantic_prefix",
                    cancel_previous=cancel_previous,
                )
            if ready and self._thinking and stable != previous_stable:
                self._counts["updated"] += 1
                return self._directive(
                    ThinkAction.UPDATE,
                    utterance_id=item.utterance_id,
                    stable_prefix=stable,
                    reason="stable_prefix_extended",
                )
            if cancel_previous:
                return self._directive(
                    ThinkAction.CANCEL,
                    utterance_id=item.utterance_id,
                    stable_prefix=stable,
                    reason="asr_revision_invalidated_prefix",
                    cancel_previous=True,
                )
            return self._directive(
                ThinkAction.WAIT,
                utterance_id=item.utterance_id,
                stable_prefix=stable,
                reason="insufficient_stability_or_semantic_confidence",
            )

    def cancel(self, utterance_id: str, *, reason: str) -> ThinkDirective:
        """Cancel speculative thinking after barge-in, call end, or host invalidation."""
        if type(utterance_id) is not str or _ID.fullmatch(utterance_id) is None:
            raise ValueError("utterance_id must be a bounded opaque identifier")
        if reason not in _ALLOWED_CANCEL_REASONS:
            raise ValueError("unsupported cancellation reason")
        with self._lock:
            if self._active_id != utterance_id:
                self._counts["rejected"] += 1
                return self._directive(ThinkAction.REJECT, utterance_id=utterance_id,
                                       reason="not_active")
            cancel_previous = self._thinking
            self._clear_active()
            self._counts["cancelled"] += int(cancel_previous)
            return self._directive(ThinkAction.CANCEL, utterance_id=utterance_id,
                                   reason=reason, cancel_previous=cancel_previous)

    def expire(self, *, now_ms: float) -> ThinkDirective | None:
        """Cancel a thinker whose latest ASR evidence or utterance lifetime expired."""
        now = _finite(now_ms, "now_ms", 0.0, _MAX_CLOCK_MS)
        with self._lock:
            if self._active_id is None:
                return None
            stale = now - self._last_ms > self._max_age
            too_long = now - self._started_ms > self._max_duration
            if not stale and not too_long:
                return None
            utterance_id = self._active_id
            cancel_previous = self._thinking
            self._clear_active()
            self._counts["expired"] += 1
            self._counts["cancelled"] += int(cancel_previous)
            return self._directive(
                ThinkAction.CANCEL,
                utterance_id=utterance_id,
                reason="stale_or_overlong_utterance",
                cancel_previous=cancel_previous,
            )

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate diagnostics only; never returns transcript text or identifiers."""
        with self._lock:
            return {
                **self._counts,
                "active": self._active_id is not None,
                "thinking": self._thinking,
                "fault": self._fault,
            }


__all__ = [
    "IncrementalThinkCoordinator",
    "PartialHypothesis",
    "ThinkAction",
    "ThinkDirective",
]
