"""Bounded verifier-first reinforcement loop for Litha/STAR.

This module improves *task-time* answers without changing model weights. It is
designed to sit inside the agent harness: generate several candidates, verify
them with trusted host-owned checks, critique failures, re-explore, and return
only the best verified result.

The verifier is deliberately separate from the generator/critic. Model claims
such as "tests passed" are never promotion evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Iterable

Generator = Callable[[str, int], str]
Critic = Callable[[str, str, "Verification"], str]
Refiner = Callable[[str, str, str, int], str]
Verifier = Callable[[str, str], "Verification"]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Verification:
    """Independent verification result supplied by the trusted host."""

    score: float
    passed: bool
    evidence: str
    verifier: str
    trusted: bool = True

    def validate(self) -> "Verification":
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            raise TypeError("verification score must be numeric")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("verification score must be in [0, 1]")
        if type(self.passed) is not bool or type(self.trusted) is not bool:
            raise TypeError("passed/trusted must be bool")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("verification evidence is required")
        if not isinstance(self.verifier, str) or not self.verifier.strip():
            raise ValueError("verifier identity is required")
        if self.passed and not self.trusted:
            raise PermissionError("untrusted verification cannot promote a candidate")
        return self


@dataclass(frozen=True)
class Attempt:
    round: int
    candidate: str
    candidate_sha256: str
    verification: Verification
    critique: str = ""
    parent_sha256: str = ""

    @property
    def promotable(self) -> bool:
        return self.verification.trusted and self.verification.passed


@dataclass(frozen=True)
class LoopConfig:
    """Compute and stopping policy for one task."""

    initial_candidates: int = 4
    max_rounds: int = 3
    refinements_per_round: int = 2
    min_improvement: float = 0.02
    pass_score: float = 0.90
    max_candidate_chars: int = 120_000

    def validate(self) -> "LoopConfig":
        if not 1 <= self.initial_candidates <= 16:
            raise ValueError("initial_candidates must be 1..16")
        if not 1 <= self.max_rounds <= 8:
            raise ValueError("max_rounds must be 1..8")
        if not 1 <= self.refinements_per_round <= 8:
            raise ValueError("refinements_per_round must be 1..8")
        if not 0.0 <= self.min_improvement <= 1.0:
            raise ValueError("min_improvement must be in [0, 1]")
        if not 0.0 <= self.pass_score <= 1.0:
            raise ValueError("pass_score must be in [0, 1]")
        if not 256 <= self.max_candidate_chars <= 1_000_000:
            raise ValueError("max_candidate_chars out of range")
        return self


@dataclass(frozen=True)
class LoopResult:
    answer: str
    answer_sha256: str
    passed: bool
    best_score: float
    rounds_used: int
    attempts: tuple[Attempt, ...]
    stop_reason: str
    verifier: str

    @property
    def evidence(self) -> str:
        if not self.attempts:
            return ""
        best = max(self.attempts, key=_rank)
        return best.verification.evidence


def _rank(attempt: Attempt) -> tuple[int, float, str]:
    """Stable rank: trusted pass > score > digest.

    The digest tie-break avoids depending on generation arrival order, making
    parallel candidate evaluation reproducible.
    """
    return (
        int(attempt.promotable),
        float(attempt.verification.score),
        attempt.candidate_sha256,
    )


def _validate_candidate(text: str, *, limit: int) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("generator/refiner returned an empty candidate")
    if len(text) > limit:
        raise ValueError("candidate exceeds configured size limit")
    return text


def _verify(task: str, candidate: str, verifier: Verifier, *, round_no: int,
            parent_sha256: str = "") -> Attempt:
    verdict = verifier(task, candidate)
    if type(verdict) is not Verification:
        raise TypeError("verifier must return Verification")
    verdict.validate()
    # A pass must satisfy both the verifier's semantic pass bit and the loop's
    # configured score threshold; threshold application happens in run_loop.
    return Attempt(
        round=round_no,
        candidate=candidate,
        candidate_sha256=_digest(candidate),
        verification=verdict,
        parent_sha256=parent_sha256,
    )


def _dedupe(attempts: Iterable[Attempt]) -> list[Attempt]:
    best_by_digest: dict[str, Attempt] = {}
    for item in attempts:
        previous = best_by_digest.get(item.candidate_sha256)
        if previous is None or _rank(item) > _rank(previous):
            best_by_digest[item.candidate_sha256] = item
    return list(best_by_digest.values())


def run_loop(
    task: str,
    *,
    generate: Generator,
    verify: Verifier,
    critique: Critic,
    refine: Refiner,
    config: LoopConfig | None = None,
) -> LoopResult:
    """Run a bounded generate -> verify -> critique -> refine loop.

    The loop intentionally does not mutate lessons, prompts, evaluations, or
    weights. A caller may later feed the returned evidence into Litha's slower
    paired/held-out learning gate.
    """
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task is required")
    cfg = (config or LoopConfig()).validate()

    attempts: list[Attempt] = []
    seen: set[str] = set()

    # Best-of-N exploration. The seed index is exposed to the generator so a
    # backend can vary temperature, prompt strategy, model, or agent role.
    for seed in range(cfg.initial_candidates):
        candidate = _validate_candidate(generate(task, seed), limit=cfg.max_candidate_chars)
        digest = _digest(candidate)
        if digest in seen:
            continue
        seen.add(digest)
        attempts.append(_verify(task, candidate, verify, round_no=0))

    if not attempts:
        raise RuntimeError("all initial candidates collapsed to duplicates")

    def effective(a: Attempt) -> Attempt:
        v = a.verification
        # Promotion requires both the verifier's pass and configured score.
        if v.passed and v.score < cfg.pass_score:
            downgraded = Verification(
                score=v.score,
                passed=False,
                evidence=v.evidence + " | below loop pass_score",
                verifier=v.verifier,
                trusted=v.trusted,
            )
            return Attempt(
                round=a.round,
                candidate=a.candidate,
                candidate_sha256=a.candidate_sha256,
                verification=downgraded,
                critique=a.critique,
                parent_sha256=a.parent_sha256,
            )
        return a

    attempts = [effective(a) for a in attempts]
    best = max(attempts, key=_rank)
    if best.promotable:
        return LoopResult(
            answer=best.candidate,
            answer_sha256=best.candidate_sha256,
            passed=True,
            best_score=float(best.verification.score),
            rounds_used=0,
            attempts=tuple(sorted(attempts, key=lambda a: (a.round, a.candidate_sha256))),
            stop_reason="verified_initial_candidate",
            verifier=best.verification.verifier,
        )

    previous_best = float(best.verification.score)
    stagnant_rounds = 0

    for round_no in range(1, cfg.max_rounds + 1):
        # Critique the current strongest candidate, but ask for several
        # independent refinements. Refiners should re-derive the solution from
        # task + critique rather than merely patching text; this reduces
        # anchoring on the original failure.
        feedback = critique(task, best.candidate, best.verification)
        if not isinstance(feedback, str) or not feedback.strip():
            feedback = "Re-solve from first principles using the verifier evidence."

        generated: list[Attempt] = []
        for variant in range(cfg.refinements_per_round):
            candidate = _validate_candidate(
                refine(task, best.candidate, feedback, variant),
                limit=cfg.max_candidate_chars,
            )
            digest = _digest(candidate)
            if digest in seen:
                continue
            seen.add(digest)
            checked = _verify(
                task,
                candidate,
                verify,
                round_no=round_no,
                parent_sha256=best.candidate_sha256,
            )
            checked = effective(checked)
            generated.append(Attempt(
                round=checked.round,
                candidate=checked.candidate,
                candidate_sha256=checked.candidate_sha256,
                verification=checked.verification,
                critique=feedback,
                parent_sha256=checked.parent_sha256,
            ))

        if not generated:
            return LoopResult(
                answer=best.candidate,
                answer_sha256=best.candidate_sha256,
                passed=False,
                best_score=float(best.verification.score),
                rounds_used=round_no - 1,
                attempts=tuple(sorted(attempts, key=lambda a: (a.round, a.candidate_sha256))),
                stop_reason="no_novel_candidates",
                verifier=best.verification.verifier,
            )

        attempts.extend(generated)
        attempts = _dedupe(attempts)
        new_best = max(attempts, key=_rank)

        if new_best.promotable:
            return LoopResult(
                answer=new_best.candidate,
                answer_sha256=new_best.candidate_sha256,
                passed=True,
                best_score=float(new_best.verification.score),
                rounds_used=round_no,
                attempts=tuple(sorted(attempts, key=lambda a: (a.round, a.candidate_sha256))),
                stop_reason="verified_refinement",
                verifier=new_best.verification.verifier,
            )

        improvement = float(new_best.verification.score) - previous_best
        if improvement < cfg.min_improvement:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
        best = new_best
        previous_best = float(best.verification.score)

        # Two flat rounds are enough evidence to stop spending inference
        # budget. The slower outer learning loop can analyze this failure.
        if stagnant_rounds >= 2:
            return LoopResult(
                answer=best.candidate,
                answer_sha256=best.candidate_sha256,
                passed=False,
                best_score=float(best.verification.score),
                rounds_used=round_no,
                attempts=tuple(sorted(attempts, key=lambda a: (a.round, a.candidate_sha256))),
                stop_reason="stagnation",
                verifier=best.verification.verifier,
            )

    return LoopResult(
        answer=best.candidate,
        answer_sha256=best.candidate_sha256,
        passed=False,
        best_score=float(best.verification.score),
        rounds_used=cfg.max_rounds,
        attempts=tuple(sorted(attempts, key=lambda a: (a.round, a.candidate_sha256))),
        stop_reason="budget_exhausted",
        verifier=best.verification.verifier,
    )
