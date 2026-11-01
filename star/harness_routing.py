"""OMP-inspired model-routing policy helpers for Litha/STAR.

This module is intentionally transport-agnostic. It classifies failures and
selects a fallback only from a caller-provided, already-authorized chain.
It never grants cloud access or reads credentials itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable


class FailureKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    AUTH = "auth"
    CONTEXT = "context"
    CONFIG = "config"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RouteCandidate:
    provider: str
    model: str
    trust: str  # local | lan | cloud


@dataclass(frozen=True)
class RetryDecision:
    kind: FailureKind
    may_retry_same: bool
    may_fallback: bool


_CONTEXT = re.compile(
    r"context(?:_| )length|maximum context|prompt is too long|input is too long|too many tokens|exceed_context",
    re.I,
)
_RATE = re.compile(r"\b429\b|rate.?limit|quota|too many requests", re.I)
_AUTH = re.compile(r"\b40[13]\b|unauthori[sz]ed|forbidden|invalid api key|authentication", re.I)
_TRANSIENT = re.compile(r"\b50[0234]\b|timeout|timed out|temporar|connection reset|connection refused|overloaded", re.I)
_CONFIG = re.compile(r"unknown model|model not found|invalid endpoint|bad request|\b400\b", re.I)


def classify_failure(value: object) -> RetryDecision:
    """Classify a provider failure without depending on one SDK's exception types."""
    text = str(value or "")
    if _CONTEXT.search(text):
        return RetryDecision(FailureKind.CONTEXT, False, False)
    if _AUTH.search(text):
        return RetryDecision(FailureKind.AUTH, False, False)
    if _RATE.search(text):
        return RetryDecision(FailureKind.RATE_LIMIT, False, True)
    if _TRANSIENT.search(text):
        return RetryDecision(FailureKind.TRANSIENT, True, True)
    if _CONFIG.search(text):
        return RetryDecision(FailureKind.CONFIG, False, False)
    return RetryDecision(FailureKind.UNKNOWN, False, False)


def next_fallback(
    current: RouteCandidate,
    chain: Iterable[RouteCandidate],
    *,
    decision: RetryDecision,
    allow_trust_changes: bool = False,
) -> RouteCandidate | None:
    """Return the next authorized route.

    By default a fallback may not cross local/LAN/cloud trust boundaries.
    Callers must explicitly allow a trust change, and should only do so after
    owner configuration has authorized that boundary.
    """
    if not decision.may_fallback:
        return None

    candidates = list(chain)
    try:
        index = candidates.index(current)
    except ValueError:
        return None

    for candidate in candidates[index + 1 :]:
        if allow_trust_changes or candidate.trust == current.trust:
            return candidate
    return None
