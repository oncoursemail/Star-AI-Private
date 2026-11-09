"""Fail-closed paired speed evidence for STAR's existing local streaming benchmark.

Consume ONLY sanitized summaries from inference_stream_benchmark. The operator
must alternate baseline/candidate in private sessions on the SAME target model,
hardware, prompts and concurrency, and separately measure actual audio, game
FPS and OBS health. No prompts, generated words, secrets, game input, network,
devices or model processes are accessed or saved here.

This is an OFFLINE recommendation for a *private pilot*, never automatic model
routing, deployment, broadcasting, or an intelligence/VTuber quality score.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import re
from typing import Mapping, Sequence, cast

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_STATUSES = frozenset({
    "ok", "empty", "incomplete", "truncated", "canary_mismatch",
    "failed", "timeout",
})
_WORKLOADS = frozenset({"mixed", "canary", "repeat"})
# Only metrics affecting a speed comparison; notes, flags and arbitrary
# labels must not let duplicated run summaries masquerade as new evidence.
_REPLAY_FIELDS = (
    "requests", "completed", "failed", "parallel_limit", "workload",
    "workload_sha256", "wall_ms", "first_visible_p95_ms",
    "first_speakable_p95_ms", "complete_p95_ms", "speakable_ready",
    "speakable_missing", "canary_mismatches", "statuses",
)


def _sha(value: object) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _number(value: object, *, max_value: float = 600_000) -> float:
    if type(value) not in (int, float):
        raise ValueError("invalid finite benchmark measurement")
    value = float(cast(int | float, value))
    if not math.isfinite(value) or not 0 <= value <= max_value:
        raise ValueError("invalid bounded benchmark measurement")
    return value


def _integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid bounded benchmark count")
    return value


def _summary(row: object) -> Mapping[str, object]:
    """Validate counters against their own completion denominator.

    The CLI accepts summaries, not raw transcript/SSE chunks; this validation
    detects malformed and self-contradictory samples but cannot authenticate
    where the summaries came from.
    """
    if not isinstance(row, dict):
        raise ValueError("expected sanitized benchmark summary")
    expected = {
        "requests", "completed", "failed", "parallel_limit", "workload",
        "workload_sha256", "wall_ms", "first_visible_p95_ms",
        "first_speakable_p95_ms", "complete_p95_ms", "speakable_ready",
        "speakable_missing", "canary_mismatches", "statuses",
    }
    allowed = expected | {
        "first_visible_p50_ms", "first_speakable_p50_ms",
        "complete_p50_ms", "partial_visible_failures",
        "repeated_prompt_warning", "note",
    }
    if not expected.issubset(row) or not set(row).issubset(allowed):
        raise ValueError("expected only sanitized streaming benchmark fields")
    requests = _integer(row["requests"], 1, 8)
    completed = _integer(row["completed"], 0, requests)
    failed = _integer(row["failed"], 0, requests)
    parallel = _integer(row["parallel_limit"], 1, 2)
    ready = _integer(row["speakable_ready"], 0, completed)
    missing = _integer(row["speakable_missing"], 0, completed)
    canary_errors = _integer(row["canary_mismatches"], 0, requests)
    if (completed + failed != requests or ready + missing != completed
            or type(row["workload"]) is not str or row["workload"] not in _WORKLOADS
            or not _sha(row["workload_sha256"])):
        raise ValueError("contradictory benchmark summary")
    _number(row["wall_ms"])
    if row["wall_ms"] <= 0:
        raise ValueError("empty wall-clock measurement")
    statuses = row["statuses"]
    if not isinstance(statuses, dict) or set(statuses) != _STATUSES:
        raise ValueError("invalid streaming status breakdown")
    if any(type(x) is not int or not 0 <= x <= requests for x in statuses.values()):
        raise ValueError("invalid status counts")
    if (sum(statuses.values()) != requests or statuses["ok"] != completed
            or statuses["canary_mismatch"] != canary_errors):
        raise ValueError("status counts contradict completed responses")
    for name in ("first_visible_p95_ms", "first_speakable_p95_ms", "complete_p95_ms"):
        if row[name] is None:
            if name != "first_speakable_p95_ms" and completed:
                raise ValueError("completed responses have no timing")
            if name == "first_speakable_p95_ms" and ready:
                raise ValueError("speakable responses missing timing")
        else:
            _number(row[name])
    if ready and row["first_speakable_p95_ms"] is None:
        raise ValueError("missing first-speakable p95")
    if not ready and row["first_speakable_p95_ms"] is not None:
        raise ValueError("unexpected first-speakable p95")
    if completed and row["first_speakable_p95_ms"] is not None and (
        row["first_speakable_p95_ms"] > row["complete_p95_ms"] + 1
    ):
        raise ValueError("speakable time cannot exceed completion p95")
    if completed and row["first_visible_p95_ms"] is not None and (
        row["first_visible_p95_ms"] > row["complete_p95_ms"] + 1
    ):
        raise ValueError("visible text cannot arrive after completion")
    if row["workload"] == "canary" and parallel != 1:
        raise ValueError("canary must use sequential requests")
    return row


@dataclass(frozen=True)
class StreamSpeedPair:
    """One preselected A/B private experiment; no raw model text accepted."""

    pair_id: str
    target_model_sha256: str
    host_profile_sha256: str
    baseline: Mapping[str, object]
    candidate: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.pair_id) is not str or _ID.fullmatch(self.pair_id) is None:
            raise ValueError("pair ID must be an opaque bounded identifier")
        if not _sha(self.target_model_sha256) or not _sha(self.host_profile_sha256):
            raise ValueError("stable target-model and hardware-profile digests required")
        base = _summary(self.baseline)
        new = _summary(self.candidate)
        for field in ("workload", "workload_sha256", "requests", "parallel_limit"):
            if base[field] != new[field]:
                raise ValueError("baseline and candidate must run identical synthetic workload")

    @classmethod
    def from_dict(cls, item: object) -> StreamSpeedPair:
        fields = {"pair_id", "target_model_sha256", "host_profile_sha256",
                  "baseline", "candidate"}
        if type(item) is not dict or set(item) != fields:
            raise ValueError("only bounded paired benchmark evidence is accepted")
        return cls(**item)


@dataclass(frozen=True)
class StreamSpeedVerdict:
    verdict: str
    pairs: int
    complete_pairs: int
    baseline_speakable_p95_ms: float | None
    candidate_speakable_p95_ms: float | None
    baseline_complete_p95_ms: float | None
    candidate_complete_p95_ms: float | None
    paired_mean_speakable_gain_ms: float | None
    gain_ci95_ms: tuple[float, float] | None
    note: str = (
        "Summary-based matched private probe only. Host model/hardware hashes "
        "are operator supplied, not attested. Reused metric tuples are detected "
        "but independently performed runs cannot be proven by summaries. "
        "No automatic routing, speedup claim, humanlike speech, audible PCM, "
        "FPS, game skill, or OBS proof."
    )
    duplicate_summary_pairs: int = 0
    improved_speakable_pairs: int = 0
    non_tied_speakable_pairs: int = 0
    paired_sign_test_p: float | None = None


def _summary_pair_fingerprint(pair: StreamSpeedPair) -> str:
    """Detect byte-for-byte replayed measurement evidence, regardless of IDs.

    Excludes descriptive note and optional warning fields. This is a cheap
    duplication fence, NOT authentication: fabricated or slightly edited
    summaries still require trusted host experiment provenance.
    """
    measured = [
        {key: row[key] for key in _REPLAY_FIELDS}
        for row in (pair.baseline, pair.candidate)
    ]
    encoded = json.dumps(measured, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def _bootstrap_gain_ci(gains: list[float]) -> tuple[float, float]:
    # Deterministic resampling keeps the evaluation reproducible.
    seed = int.from_bytes(hashlib.sha256(b"star.paired.stream.speed.v1").digest()[:8], "big")
    rng = random.Random(seed)
    n = len(gains)
    means = sorted(sum(gains[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(2000))
    return round(means[49], 2), round(means[1949], 2)


def _paired_sign_test(gains: list[float]) -> tuple[int, int, float]:
    """Exact one-sided sign test: P(X >= observed positive gains), X~Bin(n,.5).

    Zero changes have no direction and are excluded. This checks consistency
    across paired sessions, not independence or authenticity of the sessions.
    """
    positives = sum(gain > 0 for gain in gains)
    non_tied = sum(gain != 0 for gain in gains)
    if not non_tied:
        return positives, non_tied, 1.0
    extreme_outcomes = sum(
        math.comb(non_tied, k) for k in range(positives, non_tied + 1)
    )
    p_value = extreme_outcomes / (2 ** non_tied)
    return positives, non_tied, p_value


def compare_stream_speed(
    pairs: Sequence[StreamSpeedPair], *, minimum_pairs: int = 6,
    min_speakable_gain_ms: float = 40, max_complete_regression_ms: float = 100,
) -> StreamSpeedVerdict:
    """Conservative A/B gate with success-coverage and per-pair tail checks.

    Do NOT select only favorable repeated trials. Candidate + baseline must be
    measured in alternating order (AB/BA randomized by the host) to reduce
    thermal or cache-order biases. This function cannot verify randomization.
    """
    _integer(minimum_pairs, 4, 30)
    gain_floor = _number(min_speakable_gain_ms, max_value=5000)
    complete_limit = _number(max_complete_regression_ms, max_value=5000)
    if type(pairs) not in (list, tuple) or not 1 <= len(pairs) <= 60:
        raise ValueError("expected a bounded pre-registered pair cohort")
    if any(type(p) is not StreamSpeedPair for p in pairs):
        raise TypeError("expected validated StreamSpeedPair observations")
    first = pairs[0]
    ids: set[str] = set()
    fingerprints: set[str] = set()
    replayed = 0
    for pair in pairs:
        # The frozen pair holds externally provided mappings, so a caller
        # could mutate them after construction. Validate at evaluation time.
        _summary(pair.baseline)
        _summary(pair.candidate)
        for field in ("workload", "workload_sha256", "requests", "parallel_limit"):
            if pair.baseline[field] != pair.candidate[field]:
                raise ValueError("post-construction paired workload mismatch")
        if pair.pair_id in ids:
            raise ValueError("duplicate pair ID: do not cherry-pick runs")
        ids.add(pair.pair_id)
        signature = _summary_pair_fingerprint(pair)
        if signature in fingerprints:
            replayed += 1
        fingerprints.add(signature)
        if (pair.target_model_sha256 != first.target_model_sha256
                or pair.host_profile_sha256 != first.host_profile_sha256):
            raise ValueError("mixed target model or host hardware profiles")
        for field in ("workload", "workload_sha256", "requests", "parallel_limit"):
            if pair.baseline[field] != first.baseline[field]:
                raise ValueError("mixed synthetic workload or concurrency in cohort")

    complete = [
        p for p in pairs if all(
            row["completed"] == row["requests"]
            and row["speakable_missing"] == 0
            and row["canary_mismatches"] == 0
            for row in (p.baseline, p.candidate)
        )
    ]
    if not complete:
        return StreamSpeedVerdict("inconclusive", len(pairs), 0,
                                  None, None, None, None, None, None,
                                  duplicate_summary_pairs=replayed)
    base_speech = [_number(p.baseline["first_speakable_p95_ms"]) for p in complete]
    new_speech = [_number(p.candidate["first_speakable_p95_ms"]) for p in complete]
    base_done = [_number(p.baseline["complete_p95_ms"]) for p in complete]
    new_done = [_number(p.candidate["complete_p95_ms"]) for p in complete]
    gains = [b - c for b, c in zip(base_speech, new_speech)]
    ci = _bootstrap_gain_ci(gains)
    improved, non_tied, sign_p = _paired_sign_test(gains)
    # Missing outputs never disappear from the paired denominator.
    degraded = any(
        cast(int, p.candidate["completed"]) < cast(int, p.baseline["completed"])
        or cast(int, p.candidate["speakable_missing"]) > cast(int, p.baseline["speakable_missing"])
        or cast(int, p.candidate["canary_mismatches"]) > cast(int, p.baseline["canary_mismatches"])
        for p in pairs
    )
    degraded = degraded or any(
        new - base > complete_limit or new_s - base_s > 150
        for new, base, new_s, base_s in zip(new_done, base_done, new_speech, base_speech)
    )
    if degraded:
        verdict = "regressed"
    elif (len(pairs) < minimum_pairs or len(complete) != len(pairs)
          or first.baseline["workload"] == "repeat"
          or replayed > 0):
        verdict = "inconclusive"
    elif (sign_p <= 0.05
          and ci[0] > gain_floor
          and _p95(new_speech) < _p95(base_speech)
          and _p95(new_done) <= _p95(base_done) + complete_limit):
        verdict = "eligible_for_private_pilot"
    else:
        verdict = "inconclusive"
    return StreamSpeedVerdict(
        verdict, len(pairs), len(complete),
        round(_p95(base_speech), 2), round(_p95(new_speech), 2),
        round(_p95(base_done), 2), round(_p95(new_done), 2),
        round(sum(gains) / len(gains), 2), ci,
        duplicate_summary_pairs=replayed,
        improved_speakable_pairs=improved,
        non_tied_speakable_pairs=non_tied,
        paired_sign_test_p=round(sign_p, 8),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline paired STAR inference speed evidence; never launches a model"
    )
    parser.add_argument("evidence_json", type=Path)
    parser.add_argument("--minimum-pairs", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        if args.evidence_json.stat().st_size > 131072:
            raise ValueError("oversized evidence")
        document = json.loads(args.evidence_json.read_text(encoding="utf-8"))
        if type(document) is not dict or set(document) != {"pairs"}:
            raise ValueError("expected only a paired evidence array")
        if type(document["pairs"]) is not list:
            raise ValueError("pairs must be an array")
        pairs = [StreamSpeedPair.from_dict(row) for row in document["pairs"]]
        report = compare_stream_speed(pairs, minimum_pairs=args.minimum_pairs)
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError):
        # Never leak a host path or private benchmark input into stdout/stderr.
        print(json.dumps({"verdict": "invalid_evidence"}))
        return 2
    print(json.dumps(asdict(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.verdict == "eligible_for_private_pilot" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["StreamSpeedPair", "StreamSpeedVerdict", "compare_stream_speed"]
