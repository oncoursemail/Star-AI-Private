"""Paired offline Star VTuber quality/latency gate for candidate *review*.

Using fewer replies can deceptively improve latency, so compare on the same
reviewed opportunities and require preserved useful speech, grounded statements
and no increased talk-over. This never broadcasts, asserts human review was
cryptographically authenticated, or promotes a model/config automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _duration(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(number) or not 0 <= number <= 120_000:
        raise ValueError(f"{label} must be 0..120000 ms")
    return number


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[math.ceil(.95 * len(values)) - 1], 2)


@dataclass(frozen=True)
class StreamAuditTurn:
    case_id: str                    # anonymous task case, not viewer identity
    context_sha256: str             # stable context-hash PIN; not independent attestation
    route: str                      # baseline or candidate
    should_reply: bool             # pre-specified human-reviewed opportunity
    result: str                     # spoken, silent, cancelled or failed
    grounding: str                  # supported, unsupported, not_applicable, unreviewed
    first_audible_ms: float | None  # same-clock host measurement, if spoken
    overlap_ms: float              # host-measured talking over real users
    game_stall_ms: float           # host-measured frame stalls linked to turn
    reviewed: bool                 # true only from independent host-held review

    def __post_init__(self) -> None:
        if type(self.case_id) is not str or not _ID.fullmatch(self.case_id):
            raise ValueError("invalid anonymous case_id")
        if type(self.context_sha256) is not str or not _SHA.fullmatch(self.context_sha256):
            raise ValueError("expected a lowercase 64-character context digest")
        if self.route not in {"baseline", "candidate"}:
            raise ValueError("unknown route")
        if type(self.should_reply) is not bool or type(self.reviewed) is not bool:
            raise ValueError("review metadata must be explicit booleans")
        if self.result not in {"spoken", "silent", "cancelled", "failed"}:
            raise ValueError("unknown outcome")
        if self.grounding not in {"supported", "unsupported", "not_applicable", "unreviewed"}:
            raise ValueError("unknown grounding grade")
        if self.first_audible_ms is not None:
            _duration(self.first_audible_ms, "first_audible_ms")
        if (self.result == "spoken") != (self.first_audible_ms is not None):
            raise ValueError("only spoken turns can have first-audible latency")
        _duration(self.overlap_ms, "overlap_ms")
        _duration(self.game_stall_ms, "game_stall_ms")
        if self.result != "spoken" and self.overlap_ms:
            raise ValueError("a non-spoken turn cannot overlap with speech")
        if self.result != "spoken" and self.grounding in {"supported", "unsupported"}:
            raise ValueError("a non-spoken turn cannot have a speech grounding grade")
        if self.result == "spoken" and self.grounding == "not_applicable":
            raise ValueError("spoken output must be reviewed for grounding")


def _summary(rows: list[StreamAuditTurn]) -> dict:
    needed = [r for r in rows if r.should_reply]
    audible = [r for r in rows if r.result == "spoken"]
    return {
        "cases": len(rows),
        "reply_opportunities": len(needed),
        "useful_replies": sum(r.result == "spoken" and r.grounding == "supported" for r in needed),
        "useful_reply_ratio": round(
            sum(r.result == "spoken" and r.grounding == "supported" for r in needed) / len(needed),
            4,
        ) if needed else 0.0,
        "failed_reply_opportunities": sum(r.result == "failed" for r in needed),
        "cancelled_reply_opportunities": sum(r.result == "cancelled" for r in needed),
        "unexpected_speech": sum(r.result == "spoken" for r in rows if not r.should_reply),
        "unsupported_speech": sum(r.grounding == "unsupported" for r in audible),
        "speech_overlaps": sum(r.overlap_ms > 0 for r in audible),
        "total_overlap_ms": round(sum(r.overlap_ms for r in audible), 2),
        "game_stalls_over_50ms": sum(r.game_stall_ms > 50 for r in rows),
        "first_audible_p95_ms": _p95([r.first_audible_ms for r in audible if r.first_audible_ms is not None]),
        "audible_turns": len(audible),
    }


def compare_stream_profiles(rows: tuple[StreamAuditTurn, ...], *,
                            min_cases: int = 20, min_spoken: int = 10,
                            min_relative_latency_gain: float = .05,
                            min_useful_reply_ratio: float = .90) -> dict:
    """Strict paired evaluation. Unreviewed/changed cases fail closed.

    A candidate may only be *recommended for human review*, never promoted.
    Exact binomial confidence intervals and repeated-trial studies should be
    added by the owning eval service before any release decision.
    """
    if type(rows) is not tuple or not all(isinstance(row, StreamAuditTurn) for row in rows):
        raise TypeError("expected a tuple of StreamAuditTurn")
    if type(min_cases) is not int or not 2 <= min_cases <= 10000:
        raise ValueError("min_cases must be 2..10000")
    if type(min_spoken) is not int or not 1 <= min_spoken <= min_cases:
        raise ValueError("min_spoken must be 1..min_cases")
    if (isinstance(min_relative_latency_gain, bool) or
            not isinstance(min_relative_latency_gain, (float, int)) or
            not math.isfinite(min_relative_latency_gain) or
            not 0 < min_relative_latency_gain <= .5):
        raise ValueError("gain must be within (0, .5]")
    if (type(min_useful_reply_ratio) not in (float, int)
            or not math.isfinite(float(min_useful_reply_ratio))
            or not 0.5 <= min_useful_reply_ratio <= 1):
        raise ValueError("min_useful_reply_ratio must be 0.5..1")
    if len(rows) > 20000:
        raise ValueError("bounded offline audit accepts at most 20000 turns")
    groups: dict[str, dict[str, StreamAuditTurn]] = {"baseline": {}, "candidate": {}}
    for row in rows:
        group = groups[row.route]
        if row.case_id in group:
            raise ValueError("duplicate case in a profile")
        group[row.case_id] = row
    baseline, candidate = groups["baseline"], groups["candidate"]
    if not baseline or set(baseline) != set(candidate):
        return {"decision": "insufficient_or_unpaired_evidence", "owner_review_required": True,
                "promoted": False, "reason": "identical paired cases are required"}
    if len(baseline) < min_cases:
        return {"decision": "insufficient_or_unpaired_evidence", "owner_review_required": True,
                "promoted": False, "reason": "not enough independent paired opportunities"}
    for ident in baseline:
        one, two = baseline[ident], candidate[ident]
        if (one.context_sha256 != two.context_sha256 or
                one.should_reply != two.should_reply or
                not one.reviewed or not two.reviewed or
                one.grounding == "unreviewed" or two.grounding == "unreviewed"):
            return {"decision": "insufficient_or_unpaired_evidence", "owner_review_required": True,
                    "promoted": False, "reason": "unreviewed or context-mismatched pair"}
    before = _summary(list(baseline.values()))
    after = _summary(list(candidate.values()))
    reasons: list[str] = []
    if before["audible_turns"] < min_spoken or after["audible_turns"] < min_spoken:
        reasons.append("insufficient_audible_samples")
    # A statistically faster stream that is helpful only half the time is not
    # a successful human-natural companion. Require an absolute floor, not
    # merely non-regression against an already-poor baseline.
    if after["useful_reply_ratio"] < min_useful_reply_ratio:
        reasons.append("useful_reply_coverage_below_target")
    # Comparing only aggregate reply counts lets a candidate replace a missed
    # important answer with a different reply. Protect each supported baseline
    # opportunity, not just the total number of utterances.
    missed_supported = sum(
        first.should_reply and first.result == "spoken" and first.grounding == "supported"
        and (candidate[case].result != "spoken" or candidate[case].grounding != "supported")
        for case, first in baseline.items()
    )
    if after["useful_replies"] < before["useful_replies"] or missed_supported:
        reasons.append("fewer_grounded_replies")
    for metric in ("unsupported_speech", "unexpected_speech", "speech_overlaps",
                   "total_overlap_ms", "game_stalls_over_50ms",
                   "failed_reply_opportunities", "cancelled_reply_opportunities"):
        if after[metric] > before[metric]:
            reasons.append("increased_" + metric)
    # A faster result obtained by silently dropping the slowest opportunities
    # is not a latency win. Score the exact same *audible* opportunities only.
    # "spoken" implies first_audible_ms (checked in StreamAuditTurn); the None checks only narrow the type.
    matched = [(old_ms, new_ms) for ident, base in baseline.items()
               if base.should_reply and base.result == "spoken" and candidate[ident].result == "spoken"
               for old_ms, new_ms in [(base.first_audible_ms, candidate[ident].first_audible_ms)]
               if old_ms is not None and new_ms is not None]
    if len(matched) < min_spoken:
        reasons.append("insufficient_matched_audible_samples")
    old, new = _p95([a for a, _ in matched]), _p95([b for _, b in matched])
    gain = None if old is None or new is None or old == 0 else round((old - new) / old, 4)
    if old is None or new is None or gain is None or gain < min_relative_latency_gain:
        reasons.append("no_measured_p95_latency_improvement")
    return {
        "decision": "candidate_for_independent_review" if not reasons else "do_not_promote",
        "owner_review_required": True, "promoted": False,
        "baseline": before, "candidate": after,
        "p95_relative_latency_gain": gain,
        "min_useful_reply_ratio": min_useful_reply_ratio,
        "matched_audible_cases": len(matched),
        "matched_baseline_p95_ms": old,
        "matched_candidate_p95_ms": new,
        "reasons": reasons,
        "basis": "Host-reported, independently reviewed, matched-case offline traces. "
                 "No authenticated referee or statistical significance claim; no live performance measured.",
    }
