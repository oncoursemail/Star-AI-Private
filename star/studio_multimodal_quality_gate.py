"""Offline, reviewer-attested visual-quality regression gate for STAR-built games.

A functioning Studio scene is not necessarily a good-looking game. This module
pairs *independently captured and reviewed* baseline/candidate screenshots
on identical, owner-curated scenarios. It refuses a candidate if the scene,
playthrough or visual dimensions regress, even when code tests pass.

IMPORTANT: HMACs authenticate the supplied host observations, not the truth
of a screenshot or a human's score. The reviewing host MUST be independent of
the candidate model, and MUST seal the manifest digest before evaluation.
No captures, image bytes, transcripts, viewer identities or credentials are
stored. This component cannot inspect Studio, run models or deploy anything.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import hmac
import json
import math
import re
from typing import Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_RUBRIC = ("geometry", "composition", "readability", "animation", "effects")
_DOMAIN = b"star.studio.multimodal-quality.v1\x00"
_MAX_TIME = 10**11
_MAX_AGE_S = 14 * 86400


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a short opaque identifier")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA256 digest")
    return value


def _time(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_TIME:
        raise ValueError("expected trusted positive Unix seconds")
    return value


def _key(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        raise ValueError("independent reviewer host needs a secret 32-byte key")
    return value


def _json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True,
                      ensure_ascii=True, allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class QualityCase:
    """Host-curated scenario, with a seed/reference fingerprint hidden from Star."""

    case_id: str
    game_id: str
    game_version: str
    scenario_sha256: str

    def __post_init__(self) -> None:
        for name in ("case_id", "game_id", "game_version"):
            _id(getattr(self, name), name)
        _digest(self.scenario_sha256, "scenario_sha256")


@dataclass(frozen=True)
class QualityStudy:
    """Immutable evaluation roster; a pre-run external timestamp seal is REQUIRED."""

    study_id: str
    cases: tuple[QualityCase, ...]
    registered_unix_s: int

    def __post_init__(self) -> None:
        _id(self.study_id, "study_id")
        _time(self.registered_unix_s)
        if (type(self.cases) is not tuple
                or not 8 <= len(self.cases) <= 64
                or any(not isinstance(case, QualityCase) for case in self.cases)
                or len({c.case_id for c in self.cases}) != len(self.cases)
                or len({c.game_id for c in self.cases}) < 2):
            raise ValueError("8..64 unique cases across at least 2 games required")


def seal_digest(study: QualityStudy) -> str:
    """Commit this in a separate host-owned timestamped ledger BEFORE the runs."""
    if not isinstance(study, QualityStudy):
        raise TypeError("expected a QualityStudy")
    roster = [asdict(c) for c in sorted(study.cases, key=lambda item: item.case_id)]
    return sha256(_DOMAIN + _json({
        "study_id": study.study_id, "registered_unix_s": study.registered_unix_s,
        "cases": roster,
    })).hexdigest()


@dataclass(frozen=True)
class QualityObservation:
    """Only bounded review metadata; actual screenshots remain on the host."""

    study_id: str
    case_id: str
    variant: str                 # baseline | candidate
    game_id: str
    game_version: str
    scenario_sha256: str
    screenshot_sha256: str
    scores: tuple[int, ...]      # rubric order: geometry, composition, etc.
    scene_valid: bool            # independently verified engine audit
    playable: bool               # independently completed playthrough
    observed_unix_s: int

    def __post_init__(self) -> None:
        for name in ("study_id", "case_id", "game_id", "game_version"):
            _id(getattr(self, name), name)
        if self.variant not in {"baseline", "candidate"}:
            raise ValueError("variant must be baseline or candidate")
        _digest(self.scenario_sha256, "scenario_sha256")
        _digest(self.screenshot_sha256, "screenshot_sha256")
        if (type(self.scores) is not tuple or len(self.scores) != len(_RUBRIC)
                or any(type(score) is not int or not 0 <= score <= 5
                       for score in self.scores)):
            raise ValueError("expected five independent integer scores 0..5")
        if type(self.scene_valid) is not bool or type(self.playable) is not bool:
            raise ValueError("scene/playthrough attestations must be booleans")
        _time(self.observed_unix_s)


@dataclass(frozen=True)
class SignedQualityObservation:
    observation: QualityObservation
    mac_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation, QualityObservation):
            raise TypeError("expected QualityObservation")
        _digest(self.mac_sha256, "mac_sha256")


def sign_observation(observation: QualityObservation, *, reviewer_key: bytes
                     ) -> SignedQualityObservation:
    """ONLY the authorized independent evaluation host may call this."""
    if not isinstance(observation, QualityObservation):
        raise TypeError("expected QualityObservation")
    mac = hmac.new(_key(reviewer_key),
                   _DOMAIN + b"receipt\x00" + _json(asdict(observation)),
                   sha256).hexdigest()
    return SignedQualityObservation(observation, mac)


@dataclass(frozen=True)
class QualityPolicy:
    min_mean_gain: float = 0.30           # 0..5 mean rubric points
    min_positive_case_fraction: float = 0.60
    min_game_mean_gain: float = 0.15
    max_per_dimension_loss: int = 1

    def __post_init__(self) -> None:
        for name in ("min_mean_gain", "min_positive_case_fraction",
                     "min_game_mean_gain"):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 <= value <= 5):
                raise ValueError(f"invalid finite threshold {name}")
        if self.min_positive_case_fraction > 1:
            raise ValueError("positive case fraction must be 0..1")
        if (type(self.max_per_dimension_loss) is not int
                or not 0 <= self.max_per_dimension_loss <= 2):
            raise ValueError("invalid dimension-loss threshold")


@dataclass(frozen=True)
class QualityReport:
    verdict: str                 # eligible_for_review | regressed | inconclusive
    complete_pairs: int
    expected_pairs: int
    distinct_games: int
    mean_score_gain: float | None
    positive_case_fraction: float | None
    per_dimension_gains: tuple[tuple[str, float], ...] = ()
    concerns: tuple[str, ...] = ()
    authorized_to_publish: bool = False
    authorized_to_edit: bool = False


def evaluate_quality(
    study: QualityStudy,
    receipts: Sequence[SignedQualityObservation],
    *,
    reviewer_key: bytes,
    externally_sealed_sha256: str,
    now_unix_s: int,
    policy: QualityPolicy = QualityPolicy(),
) -> QualityReport:
    """Evaluate sealed matched screenshots, never automatically promote work.

    The key, independent reviewer and externally sealed digest must stay outside
    Star's model and self-builder. A signed bool is NOT engine proof; trusted
    Studio/playthrough and human-review hosts must produce the observations.
    """
    if not isinstance(study, QualityStudy) or not isinstance(policy, QualityPolicy):
        raise TypeError("expected validated study and quality policy")
    key = _key(reviewer_key)
    _digest(externally_sealed_sha256, "externally_sealed_sha256")
    now = _time(now_unix_s)
    if (not hmac.compare_digest(seal_digest(study), externally_sealed_sha256)
            or now < study.registered_unix_s
            or now - study.registered_unix_s > _MAX_AGE_S):
        return QualityReport("inconclusive", 0, len(study.cases), 0, None, None,
                             concerns=("study_seal_missing_or_stale",))
    if type(receipts) not in (tuple, list) or len(receipts) > 128:
        raise ValueError("expected at most 128 signed observations")

    scope = {case.case_id: case for case in study.cases}
    observations: dict[tuple[str, str], QualityObservation] = {}
    for signed in receipts:
        if not isinstance(signed, SignedQualityObservation):
            return QualityReport("inconclusive", 0, len(study.cases), 0, None,
                                 None, concerns=("invalid_receipt",))
        record = signed.observation
        expected = sign_observation(record, reviewer_key=key).mac_sha256
        case = scope.get(record.case_id)
        if (not hmac.compare_digest(signed.mac_sha256, expected)
                or case is None
                or record.study_id != study.study_id
                or record.game_id != case.game_id
                or record.game_version != case.game_version
                or record.scenario_sha256 != case.scenario_sha256
                or not study.registered_unix_s <= record.observed_unix_s <= now
                or now - record.observed_unix_s > _MAX_AGE_S):
            return QualityReport("inconclusive", 0, len(study.cases), 0, None,
                                 None, concerns=("untrusted_or_wrong_scope",))
        identity = (record.case_id, record.variant)
        if identity in observations:
            return QualityReport("inconclusive", 0, len(study.cases), 0, None,
                                 None, concerns=("duplicate_observation",))
        observations[identity] = record

    pairs = [
        (observations[(case.case_id, "baseline")],
         observations[(case.case_id, "candidate")], case)
        for case in study.cases
        if (case.case_id, "baseline") in observations
        and (case.case_id, "candidate") in observations
    ]
    if len(pairs) != len(study.cases):
        return QualityReport("inconclusive", len(pairs), len(study.cases), 0,
                             None, None, concerns=("incomplete_pairs",))
    concerns: list[str] = []
    deltas: list[tuple[float, ...]] = []
    game_deltas: dict[str, list[float]] = {}
    positives = 0
    for baseline, candidate, case in pairs:
        if not (baseline.scene_valid and baseline.playable
                and candidate.scene_valid and candidate.playable):
            concerns.append("unverified_engine_or_playthrough")
        if (baseline.screenshot_sha256 == candidate.screenshot_sha256
                and baseline.scores != candidate.scores):
            concerns.append("identical_image_conflicting_scores")
        diff = tuple(float(b - a) for a, b in zip(baseline.scores, candidate.scores))
        if any(change < -policy.max_per_dimension_loss for change in diff):
            concerns.append("severe_visual_regression")
        mean = sum(diff) / len(_RUBRIC)
        positives += mean > 0
        deltas.append(diff)
        game_deltas.setdefault(case.game_id, []).append(mean)

    dimension_gains = tuple(
        (name, round(sum(row[index] for row in deltas) / len(deltas), 4))
        for index, name in enumerate(_RUBRIC)
    )
    mean_gain = sum(sum(row) / len(_RUBRIC) for row in deltas) / len(deltas)
    positive_fraction = positives / len(deltas)
    if any(value < 0 for _, value in dimension_gains):
        concerns.append("mean_visual_dimension_regression")
    if (mean_gain < policy.min_mean_gain
            or positive_fraction < policy.min_positive_case_fraction
            or any(sum(values) / len(values) < policy.min_game_mean_gain
                   for values in game_deltas.values())):
        concerns.append("insufficient_cross_game_quality_gain")

    return QualityReport(
        "regressed" if concerns else "eligible_for_review",
        complete_pairs=len(pairs), expected_pairs=len(study.cases),
        distinct_games=len(game_deltas),
        mean_score_gain=round(mean_gain, 4),
        positive_case_fraction=round(positive_fraction, 4),
        per_dimension_gains=dimension_gains,
        concerns=tuple(sorted(set(concerns))),
    )


__all__ = [
    "QualityCase", "QualityStudy", "QualityObservation", "SignedQualityObservation",
    "QualityPolicy", "QualityReport", "seal_digest", "sign_observation",
    "evaluate_quality",
]
