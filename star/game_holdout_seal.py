"""Independent, pre-run holdout seal for STAR's game-skill transfer audits.

This is an owner/evaluator-only boundary, NOT an agent-facing curriculum API.
A separate coordinator stores its own signing key and immutable timestamped
seal before either candidate runs. The model must never see holdout cases,
signatures, scoring keys, or per-case outcomes.

HMAC authenticates the coordinator's *claim*, not wall-clock truth, game
provenance, code identity, or the independence of the human/host scorer.
A real host must verify those separately and keep an append-only audit log.
No game control, training, network access or stream authority is provided.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import re
from typing import Sequence

from .game_transfer_eval import (
    HoldoutCase, SignedHoldoutTrial, TransferReport,
    evaluate_transfer, roster_digest,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = b"star.game-transfer.precommit.v1\x00"
_MAX_WINDOW_S = 7 * 86400
_REVIEW_GRACE_S = 86400


def _id(value: object, label: str) -> None:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded opaque ID")


def _sha(value: object, label: str) -> None:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class GameHoldoutPrecommit:
    """Immutable signed manifest prepared and sealed *before* any playtest."""

    evaluation_id: str
    roster_sha256: str
    baseline_action_id: str
    candidate_action_id: str
    baseline_revision_sha256: str
    candidate_revision_sha256: str
    sealed_unix_s: int
    expires_unix_s: int

    def __post_init__(self) -> None:
        for field in ("evaluation_id", "baseline_action_id", "candidate_action_id"):
            _id(getattr(self, field), field)
        for field in ("roster_sha256", "baseline_revision_sha256",
                      "candidate_revision_sha256"):
            _sha(getattr(self, field), field)
        if self.baseline_action_id == self.candidate_action_id:
            raise ValueError("baseline and candidate action IDs must differ")
        if self.baseline_revision_sha256 == self.candidate_revision_sha256:
            raise ValueError("cannot claim a changed policy with identical revision digests")
        if (type(self.sealed_unix_s) is not int
                or type(self.expires_unix_s) is not int
                or not 0 < self.sealed_unix_s < self.expires_unix_s <= 10**11
                or not 60 <= self.expires_unix_s - self.sealed_unix_s <= _MAX_WINDOW_S):
            raise ValueError("holdout window must be 60 seconds to 7 days")

    def canonical_bytes(self) -> bytes:
        """Domain-separated deterministic representation for host HMAC-SHA256."""
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
        return _DOMAIN + payload


def evaluate_precommitted_transfer(
    seal: GameHoldoutPrecommit,
    *, seal_receipt: str,
    coordinator_key: bytes,
    validation_key: bytes,
    expected_evaluation_id: str,
    observed_baseline_revision_sha256: str,
    observed_candidate_revision_sha256: str,
    cases: Sequence[HoldoutCase],
    signed_trials: Sequence[SignedHoldoutTrial],
    now_unix_s: int,
    minimum_pairs: int = 40,
    minimum_games: int = 5,
    min_cases_per_game: int = 3,
) -> TransferReport:
    """Verify independent sealed roster and model revisions, then score pairs.

    The coordinator signs the manifest and logs its timestamp before the games.
    The evaluator signs each *actual observed* validation result with a different
    key. Every trial must have been observed strictly AFTER the seal and within
    its frozen window. No missing pair can be promoted as a victory.

    This does not make a late/fabricated HMAC timestamp trustworthy by itself.
    The actual host needs trusted time, key custody and immutable audit history.
    """
    if not isinstance(seal, GameHoldoutPrecommit):
        raise TypeError("expected immutable GameHoldoutPrecommit")
    if (type(coordinator_key) is not bytes or len(coordinator_key) < 32
            or type(validation_key) is not bytes or len(validation_key) < 32):
        raise ValueError("independent coordinator and evaluator keys required")
    if hmac.compare_digest(coordinator_key, validation_key):
        raise ValueError("coordinator and evaluator keys must not be the same")
    if type(seal_receipt) is not str or not _SHA.fullmatch(seal_receipt):
        raise PermissionError("invalid coordinator seal receipt")
    expected_receipt = hmac.new(
        coordinator_key, seal.canonical_bytes(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_receipt, seal_receipt):
        raise PermissionError("precommitted holdout seal signature mismatch")

    _id(expected_evaluation_id, "expected_evaluation_id")
    _sha(observed_baseline_revision_sha256, "observed_baseline_revision_sha256")
    _sha(observed_candidate_revision_sha256, "observed_candidate_revision_sha256")
    if expected_evaluation_id != seal.evaluation_id:
        raise PermissionError("wrong evaluation campaign")
    if (not hmac.compare_digest(
                observed_baseline_revision_sha256, seal.baseline_revision_sha256)
            or not hmac.compare_digest(
                observed_candidate_revision_sha256, seal.candidate_revision_sha256)):
        raise PermissionError("evaluated game policies differ from sealed revisions")
    if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
        raise ValueError("invalid evaluation time")
    if not seal.sealed_unix_s < now_unix_s <= seal.expires_unix_s + _REVIEW_GRACE_S:
        raise ValueError("evaluation is outside sealed review window")
    # Domain-separated roster digest is reproducible, but the independent
    # coordinator must have logged its receipt before any game run began.
    if not hmac.compare_digest(roster_digest(cases), seal.roster_sha256):
        raise PermissionError("holdout roster changed after preregistration")
    if type(signed_trials) not in (tuple, list) or len(signed_trials) > 1024:
        raise ValueError("invalid or unbounded holdout trial collection")
    for signed in signed_trials:
        if not isinstance(signed, SignedHoldoutTrial):
            raise TypeError("expected signed validation observations")
        trial = signed.trial
        if (not hasattr(trial, "observed_unix_s")
                or type(trial.observed_unix_s) is not int
                or not seal.sealed_unix_s < trial.observed_unix_s <= seal.expires_unix_s
                or trial.observed_unix_s > now_unix_s):
            raise PermissionError("validation observation outside precommitted window")

    return evaluate_transfer(
        cases, signed_trials, validation_key=validation_key,
        expected_roster_sha256=seal.roster_sha256,
        baseline_action_id=seal.baseline_action_id,
        candidate_action_id=seal.candidate_action_id,
        now_unix_s=now_unix_s,
        minimum_pairs=minimum_pairs, minimum_games=minimum_games,
        min_cases_per_game=min_cases_per_game,
    )


__all__ = ["GameHoldoutPrecommit", "evaluate_precommitted_transfer"]
