"""Offline paired quality gate for STAR's authorized gaming vision.

An independent host labels held-out frame pairs after both predictions have
committed. No raw images, prompts, chat, audio or player identities enter this
module. It never selects models, starts a stream, trains or controls a game.
"""
from __future__ import annotations

from typing import cast

from dataclasses import asdict, dataclass
import argparse
import json
import math
from pathlib import Path
import random
import re
from typing import Iterable

from .stream_visual_perception import VISUAL_KINDS, VISUAL_REGIONS, VisualPacket

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_CASES = 4096
_MAX_LINE_BYTES = 8192
_LABEL_KINDS = VISUAL_KINDS - {"unknown"}
_STATUSES = frozenset({"accepted", "timeout", "error", "skipped"})


def _id(value: object, field: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{field} must be a bounded symbolic ID")
    return value


def _number(value: object, field: str, lo: float, hi: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result) or not lo <= result <= hi:
        raise ValueError(f"{field} outside allowed range")
    return result


def _label(value: object) -> tuple[str, str]:
    if type(value) is not dict or set(value) != {"kind", "region"}:
        raise ValueError("only kind and region allowed in a cue label")
    kind, region = value["kind"], value["region"]
    if type(kind) is not str or kind not in _LABEL_KINDS:
        raise ValueError("non-evaluable cue kind")
    if type(region) is not str or region not in VISUAL_REGIONS:
        raise ValueError("invalid visual region")
    return kind, region


def _labels(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) is not list or len(value) > 4:
        raise ValueError("expected 0..4 visual labels")
    result = tuple(_label(item) for item in value)
    if len(set(result)) != len(result):
        raise ValueError("duplicate visual cue")
    return result


@dataclass(frozen=True)
class VisionEvalPrediction:
    status: str
    labels: tuple[tuple[str, str], ...]
    latency_ms: float
    age_ms: float

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("invalid worker status")
        if type(self.labels) is not tuple or len(self.labels) > 4:
            raise ValueError("invalid model labels")
        for label in self.labels:
            if (type(label) is not tuple or len(label) != 2
                    or type(label[0]) is not str or label[0] not in _LABEL_KINDS
                    or type(label[1]) is not str or label[1] not in VISUAL_REGIONS):
                raise ValueError("invalid model label")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("duplicate model label")
        if self.status != "accepted" and self.labels:
            raise ValueError("failed worker cannot report model labels")
        _number(self.latency_ms, "latency_ms", 0, 120_000)
        _number(self.age_ms, "age_ms", 0, 120_000)

    @classmethod
    def from_dict(cls, value: object) -> "VisionEvalPrediction":
        if type(value) is not dict or set(value) != {
            "status", "findings", "latency_ms", "age_ms"
        }:
            raise ValueError("prediction requires exactly four fields")
        status = value["status"]
        if type(status) is not str or status not in _STATUSES:
            raise ValueError("invalid vision worker status")
        raw = value["findings"]
        if type(raw) is not list or len(raw) > 4:
            raise ValueError("expected 0..4 categorical model findings")
        if status != "accepted" and raw:
            raise ValueError("nonaccepted worker response cannot supply findings")
        labels = []
        for item in raw:
            if type(item) is not dict or set(item) != {"kind", "region", "confidence"}:
                raise ValueError("model finding contains extra or missing fields")
            confidence = _number(item["confidence"], "confidence", 0, 1)
            # The live model may legitimately answer "unknown"; that is silence,
            # not an evaluator failure or a positive gameplay assertion.
            if item["kind"] == "unknown":
                if type(item["region"]) is not str or item["region"] not in VISUAL_REGIONS:
                    raise ValueError("invalid visual region")
                continue
            label = _label({"kind": item["kind"], "region": item["region"]})
            if confidence >= .85:
                labels.append(label)
        if len(set(labels)) != len(labels):
            raise ValueError("duplicate high-confidence cue")
        return cls(
            status, tuple(labels),
            _number(value["latency_ms"], "latency_ms", 0, 120_000),
            _number(value["age_ms"], "age_ms", 0, 120_000),
        )

    def usable(self, max_age_ms: int) -> bool:
        return self.status == "accepted" and self.age_ms <= max_age_ms


def prediction_from_packet(
    packet: VisualPacket | None, *, status: str,
    captured_ms: float, started_ms: float, finished_ms: float,
) -> VisionEvalPrediction:
    """Convert the accepted bounded live-vision schema without raw frame data.

    Call from the trusted capture host only after checking the worker's stop,
    frame identity and permission epoch. A packet here is not itself ground
    truth. The host timestamps are one monotonic clock, not model claims.
    """
    captured = _number(captured_ms, "captured_ms", 0, 1e13)
    started = _number(started_ms, "started_ms", 0, 1e13)
    finished = _number(finished_ms, "finished_ms", 0, 1e13)
    if not captured <= started <= finished:
        raise ValueError("host timestamps are out of order")
    if status not in _STATUSES:
        raise ValueError("unknown vision completion status")
    if packet is not None and (
        type(packet) is not VisualPacket or status != "accepted"
        or packet.captured_ms != captured
    ):
        raise ValueError("packet and trusted host completion do not match")
    findings = () if packet is None else tuple(
        (finding.kind, finding.region) for finding in packet.findings
        if finding.kind in _LABEL_KINDS and finding.confidence >= .85
    )
    return VisionEvalPrediction(status, findings, finished - started, finished - captured)


@dataclass(frozen=True)
class VisionEvalCase:
    case_id: str
    game_id: str
    game_version: str
    truth_source: str
    truth: tuple[tuple[str, str], ...]
    baseline: VisionEvalPrediction
    candidate: VisionEvalPrediction

    def __post_init__(self) -> None:
        for field in ("case_id", "game_id", "game_version"):
            _id(getattr(self, field), field)
        if self.truth_source not in ("studio_engine", "human_annotation"):
            raise ValueError("untrusted truth provenance")
        if type(self.truth) is not tuple or len(self.truth) > 4:
            raise ValueError("invalid truth labels")
        for label in self.truth:
            if (type(label) is not tuple or len(label) != 2
                    or type(label[0]) is not str or label[0] not in _LABEL_KINDS
                    or type(label[1]) is not str or label[1] not in VISUAL_REGIONS):
                raise ValueError("invalid truth label")
        if len(set(self.truth)) != len(self.truth):
            raise ValueError("duplicate truth labels")
        if not isinstance(self.baseline, VisionEvalPrediction) or not isinstance(
            self.candidate, VisionEvalPrediction
        ):
            raise TypeError("both paired predictions are required")

    @classmethod
    def from_dict(cls, value: object) -> "VisionEvalCase":
        if type(value) is not dict or set(value) != {
            "case_id", "game_id", "game_version", "partition",
            "truth_source", "truth", "baseline", "candidate"
        }:
            raise ValueError("unexpected evaluation case fields")
        if value["partition"] != "holdout":
            raise ValueError("training/practice traces cannot score a holdout")
        if type(value["truth_source"]) is not str or value["truth_source"] not in (
            "studio_engine", "human_annotation"
        ):
            raise ValueError("truth must have a separately curated source")
        return cls(
            _id(value["case_id"], "case_id"),
            _id(value["game_id"], "game_id"),
            _id(value["game_version"], "game_version"),
            value["truth_source"], _labels(value["truth"]),
            VisionEvalPrediction.from_dict(value["baseline"]),
            VisionEvalPrediction.from_dict(value["candidate"]),
        )


@dataclass(frozen=True)
class VariantScores:
    f1: float
    precision: float
    recall: float
    false_alert_rate: float
    stale_rate: float
    failed_rate: float
    p95_latency_ms: float


@dataclass(frozen=True)
class VisionEvalReport:
    scope: str
    cases: int
    positive_cases: int
    negative_cases: int
    baseline: VariantScores
    candidate: VariantScores
    f1_gain_ci95: tuple[float, float] | None
    verdict: str
    note: str = ("Only trusted host labels can establish ground truth; "
                 "this report cannot verify their provenance or authorize deployment.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _score(
    cases: list[VisionEvalCase], variant: str, max_age_ms: int,
) -> VariantScores:
    tp = fp = fn = false_alerts = negatives = stale = failed = 0
    latencies: list[float] = []
    for case in cases:
        prediction = getattr(case, variant)
        expected = set(case.truth)
        usable = prediction.usable(max_age_ms)
        found = set(prediction.labels) if usable else set()
        tp += len(expected & found)
        fp += len(found - expected)
        fn += len(expected - found)
        negatives += not expected
        false_alerts += bool(not expected and found)
        stale += prediction.status == "accepted" and not usable
        failed += prediction.status in {"timeout", "error"}
        latencies.append(prediction.latency_ms)
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.0
    latencies.sort()
    p95 = latencies[math.ceil(.95 * len(latencies)) - 1]
    return VariantScores(
        round(f1, 5), round(precision, 5), round(recall, 5),
        round(false_alerts / negatives, 5) if negatives else 0.0,
        round(stale / len(cases), 5), round(failed / len(cases), 5),
        round(p95, 3),
    )


def compare_vision(
    rows: Iterable[VisionEvalCase], *, max_age_ms: int = 1500,
    bootstrap_samples: int = 600,
) -> VisionEvalReport:
    """Compare two committed runs on exactly the same trusted, heldout frames.

    No per-frame results/labels escape from the aggregate report.
    """
    if type(max_age_ms) is not int or not 200 <= max_age_ms <= 5000:
        raise ValueError("invalid maximum visual age")
    if type(bootstrap_samples) is not int or not 100 <= bootstrap_samples <= 2000:
        raise ValueError("invalid bootstrap count")
    cases: list[VisionEvalCase] = []
    seen: set[str] = set()
    scope: tuple[str, str] | None = None
    for case in rows:
        if type(case) is not VisionEvalCase:
            raise TypeError("expected trusted VisionEvalCase objects")
        if case.case_id in seen:
            raise ValueError("duplicate holdout case ID")
        seen.add(case.case_id)
        if scope is None:
            scope = case.game_id, case.game_version
        if scope != (case.game_id, case.game_version):
            raise ValueError("evaluate one exact game version at a time")
        cases.append(case)
        if len(cases) > _MAX_CASES:
            raise ValueError("too many holdout cases")
    if not cases or scope is None:
        raise ValueError("cannot score an empty holdout")
    cases.sort(key=lambda row: row.case_id)
    baseline = _score(cases, "baseline", max_age_ms)
    candidate = _score(cases, "candidate", max_age_ms)
    positives = sum(bool(row.truth) for row in cases)
    negatives = len(cases) - positives
    ci: tuple[float, float] | None = None
    if len(cases) >= 20 and positives >= 5 and negatives >= 5:
        rng = random.Random(20261028)
        differences: list[float] = []
        for _ in range(bootstrap_samples):
            sample = [cases[rng.randrange(len(cases))] for _ in range(len(cases))]
            differences.append(_score(sample, "candidate", max_age_ms).f1 -
                               _score(sample, "baseline", max_age_ms).f1)
        differences.sort()
        ci = (round(differences[math.floor(.025 * (len(differences) - 1))], 4),
              round(differences[math.ceil(.975 * (len(differences) - 1))], 4))
    if len(cases) < 60 or positives < 12 or negatives < 12 or ci is None:
        verdict = "inconclusive"
    elif (ci[1] < -.03
          or candidate.false_alert_rate > baseline.false_alert_rate + .05
          or candidate.stale_rate > baseline.stale_rate + .05
          or candidate.failed_rate > baseline.failed_rate + .05
          or candidate.p95_latency_ms > baseline.p95_latency_ms * 1.10):
        verdict = "regressed"
    elif (ci[0] >= -.03
          # Noninferiority to a broken baseline must never pass. These are
          # conservative default manual-pilot floors, not model certifications.
          and candidate.f1 >= .80
          and candidate.precision >= .85
          and candidate.recall >= .75
          and candidate.false_alert_rate <= .10
          and candidate.stale_rate <= .05
          and candidate.failed_rate <= .05
          and baseline.p95_latency_ms > 0
          and candidate.false_alert_rate <= baseline.false_alert_rate
          and candidate.stale_rate <= baseline.stale_rate
          and candidate.failed_rate <= baseline.failed_rate
          and candidate.p95_latency_ms <= baseline.p95_latency_ms * .90):
        verdict = "eligible_for_manual_pilot"
    else:
        verdict = "inconclusive"
    return VisionEvalReport(
        f"{scope[0]}:{scope[1]}", len(cases), positives, negatives,
        baseline, candidate, ci, verdict,
    )


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    obj: dict[str, object] = {}
    for key, item in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = item
    return obj


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def read_jsonl(path: str | Path) -> list[VisionEvalCase]:
    """Read bounded, strictly categorical records from an authorized host."""
    source = Path(path)
    if source.suffix != ".jsonl" or source.is_symlink() or not source.is_file():
        raise ValueError("expected regular host-generated .jsonl file")
    if source.stat().st_size > _MAX_CASES * _MAX_LINE_BYTES:
        raise ValueError("holdout file size exceeded")
    rows: list[VisionEvalCase] = []
    with source.open("rb") as stream:
        for line in stream:
            if len(line) > _MAX_LINE_BYTES:
                raise ValueError("evaluation row byte bound exceeded")
            if not line.strip():
                continue
            if len(rows) >= _MAX_CASES:
                raise ValueError("too many holdout rows")
            record = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_keys,
                                parse_constant=_reject_constant)
            rows.append(VisionEvalCase.from_dict(record))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Paired offline gaming vision evaluation")
    parser.add_argument("trace", help="trusted categorical heldout .jsonl")
    args = parser.parse_args()
    print(json.dumps(compare_vision(read_jsonl(args.trace)).to_dict(),
                     sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
