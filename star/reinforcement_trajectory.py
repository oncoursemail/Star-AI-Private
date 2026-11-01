"""Build training candidates from independently verified reinforcement trajectories.

This is a bridge, not an automatic trainer. Successful task-time trajectories
can become tightly-scoped SFT or preference-data candidates while evaluator
details remain outside model-facing training text.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .reinforcement_loop import Attempt, LoopResult

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_SECRET = re.compile(
    r"(?i)(?:-----BEGIN .*?PRIVATE KEY-----|"
    r"\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{12,}|"
    r"\b(?:github_pat_|ghp_|sk-)[A-Za-z0-9_-]{16,})"
)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TrajectoryFence:
    """Frozen fingerprints that may never be emitted as training data."""

    holdout_task_sha256: frozenset[str]
    evaluator_sha256: str

    def validate(self) -> "TrajectoryFence":
        if not isinstance(self.holdout_task_sha256, frozenset):
            raise TypeError("holdout_task_sha256 must be a frozenset")
        if any(not isinstance(x, str) or not _DIGEST.fullmatch(x) for x in self.holdout_task_sha256):
            raise ValueError("invalid holdout task digest")
        if not isinstance(self.evaluator_sha256, str) or not _DIGEST.fullmatch(self.evaluator_sha256):
            raise ValueError("evaluator_sha256 is required")
        return self


def _winner(result: LoopResult) -> Attempt:
    matches = [a for a in result.attempts if a.candidate_sha256 == result.answer_sha256]
    if len(matches) != 1:
        raise ValueError("result winner is missing or ambiguous")
    winner = matches[0]
    if not result.passed or not winner.promotable:
        raise PermissionError("only independently verified winners are eligible")
    return winner


def _validate_identity(task_id: str, domain: str) -> None:
    if not isinstance(task_id, str) or not _ID.fullmatch(task_id):
        raise ValueError("invalid task_id")
    if not isinstance(domain, str) or not _ID.fullmatch(domain):
        raise ValueError("invalid domain")


def _check_text(*values: str) -> None:
    if any(not isinstance(v, str) for v in values):
        raise TypeError("trajectory text must be strings")
    if any(_SECRET.search(v) for v in values):
        raise PermissionError("potential credential in trajectory")


def build_sft_candidate(
    task: str,
    result: LoopResult,
    *,
    task_id: str,
    domain: str,
    fence: TrajectoryFence,
) -> dict:
    """Create an SFT candidate from a verified winner."""
    _validate_identity(task_id, domain)
    fence.validate()
    winner = _winner(result)
    _check_text(task, winner.candidate)
    task_sha = sha256(task)
    if task_sha in fence.holdout_task_sha256:
        raise PermissionError("holdout task cannot enter reinforcement training")

    return {
        "format": "litha-verified-reinforcement-sft-v1",
        "task_id": task_id,
        "domain": domain,
        "task_sha256": task_sha,
        "answer_sha256": winner.candidate_sha256,
        "evaluator_sha256": fence.evaluator_sha256,
        "verification_evidence_sha256": sha256(winner.verification.evidence),
        "verifier": winner.verification.verifier,
        "score": float(winner.verification.score),
        "rounds": result.rounds_used,
        "attempts": len(result.attempts),
        "stop_reason": result.stop_reason,
        "messages": [
            {"role": "user", "content": task},
            {"role": "assistant", "content": winner.candidate},
        ],
        "training_started": False,
        "requires_outer_holdout_gate": True,
    }


def build_preference_candidate(
    task: str,
    result: LoopResult,
    *,
    task_id: str,
    domain: str,
    fence: TrajectoryFence,
    min_score_margin: float = 0.10,
) -> dict:
    """Create a DPO-style chosen/rejected pair from one verified loop."""
    if not isinstance(min_score_margin, (int, float)) or isinstance(min_score_margin, bool):
        raise TypeError("min_score_margin must be numeric")
    if not 0.0 <= float(min_score_margin) <= 1.0:
        raise ValueError("min_score_margin must be in [0, 1]")
    _validate_identity(task_id, domain)
    fence.validate()
    winner = _winner(result)
    failed = [a for a in result.attempts if not a.promotable and a.candidate_sha256 != winner.candidate_sha256]
    if not failed:
        raise ValueError("no failed candidate is available for a preference pair")
    loser = max(failed, key=lambda a: (float(a.verification.score), a.candidate_sha256))
    margin = float(winner.verification.score) - float(loser.verification.score)
    if margin < float(min_score_margin):
        raise ValueError("winner/loser verification margin is too small")

    _check_text(task, winner.candidate, loser.candidate)
    task_sha = sha256(task)
    if task_sha in fence.holdout_task_sha256:
        raise PermissionError("holdout task cannot enter reinforcement training")

    return {
        "format": "litha-verified-reinforcement-preference-v1",
        "task_id": task_id,
        "domain": domain,
        "task_sha256": task_sha,
        "evaluator_sha256": fence.evaluator_sha256,
        "prompt": task,
        "chosen": winner.candidate,
        "chosen_sha256": winner.candidate_sha256,
        "chosen_score": float(winner.verification.score),
        "chosen_evidence_sha256": sha256(winner.verification.evidence),
        "rejected": loser.candidate,
        "rejected_sha256": loser.candidate_sha256,
        "rejected_score": float(loser.verification.score),
        "rejected_evidence_sha256": sha256(loser.verification.evidence),
        "score_margin": margin,
        "verifier": winner.verification.verifier,
        "training_started": False,
        "requires_outer_holdout_gate": True,
    }
