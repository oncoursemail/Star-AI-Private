"""Paired evaluation for STAR latency gains without hidden quality regressions.

The evaluator consumes content-free, paired observations from a trusted host
and independent quality labels. It never runs models, captures media, chooses
a winner automatically, or promotes a model/configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import random
import re
from statistics import fmean, median
from typing import Callable, Sequence, cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\\Z")
_MAX_OBSERVATIONS = 20_000
_MAX_METRIC_MS = 1_000_000_000.0


class Variant(str, Enum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class QualityEvidence(str, Enum):
    """Allowed independent evidence sources; model self-grading is excluded."""

    HUMAN = "human"
    HELD_OUT_TEST = "held_out_test"
    TOOL_ASSERTION = "tool_assertion"


class LatencyMetric(str, Enum):
    FIRST_CONTENT = "first_content_ms"
    FIRST_AUDIBLE = "first_audible_ms"
    INTER_TOKEN = "inter_token_ms"
    REQUEST = "request_ms"
