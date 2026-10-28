"""Offline, signed-evidence episodic recall checks for STAR's game-learning agent.

A trusted host supplies an ordered, sealed set of independently signed
PRACTICE GameTrials. The lab freezes that sequence and produces bounded
questions whose answers are kept outside the model-facing question object.
The host grades a single response, once, before the challenge expires.

This is a memory *evaluation*, not training, a game controller, a human memory
claim, a live stream integration, a proof of gameplay causality or an
independent verifier of the original game observer. It never reads VALIDATION
holdouts, accesses the OS, speaks, calls a model, or writes personal data.
Keep challenge_key and the bank's signing keys in the trusted host.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from threading import RLock, get_ident
from typing import Sequence

from .gameplay_skill_bank import GameTrial, GameplaySkillBank

_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_ANSWER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _unix(value: object) -> int:
    if type(value) is not int or not 0 < value <= 10**11:
        raise ValueError("trusted positive Unix seconds required")
    return value


@dataclass(frozen=True)
class RecallQuestion:
    """Safe, compact prompt. No answer, trial IDs, signatures, or evidence."""

    ticket: str
    prompt: str
    skill: str
    expires_unix_s: int
    authorized_to_play: bool = False
    authorized_to_broadcast: bool = False


@dataclass(frozen=True)
class RecallGrade:
    """Never return the correct answer or the private episode chronology."""

    status: str
    skill: str | None = None
    correct: bool | None = None


@dataclass(frozen=True)
class RecallSkillScore:
    """Conservative, anonymized offline recall accuracy for one skill."""

    skill: str
    attempts: int
    correct: int
    wilson_lower_95: float


@dataclass(frozen=True)
class _Case:
    key: str
    prompt: str
    answer: str
    skill: str


class GroundedGameRecallAudit:
    """One-flight offline memory quiz over an already recorded practice episode.

    The host must use the SAME worker thread as GameplaySkillBank's SQLite
    connection. No validation/holdout data enters the quiz, and all prompts
    contain only owner-curated symbolic action names. Re-running against the
    identical data is not a generalization benchmark; use independent unseen
    episodes for that claim.
    """

    def __init__(
        self, bank: GameplaySkillBank, *, challenge_key: bytes,
        public_action_ids: frozenset[str], max_questions: int = 12,
        question_ttl_s: int = 90,
    ) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("existing signed practice ledger required")
        if type(challenge_key) is not bytes or len(challenge_key) < 32:
            raise ValueError("independent host-only challenge key must have 32+ bytes")
        if (type(public_action_ids) is not frozenset
                or not 1 <= len(public_action_ids) <= 16
                or any(type(x) is not str or not _SYMBOL.fullmatch(x)
                       for x in public_action_ids)):
            raise ValueError("curate 1..16 short public symbolic action IDs")
        if type(max_questions) is not int or not 1 <= max_questions <= 24:
            raise ValueError("max_questions must be 1..24")
        if type(question_ttl_s) is not int or not 15 <= question_ttl_s <= 300:
            raise ValueError("question_ttl_s must be 15..300")
        self._bank = bank
        self._key = challenge_key
        self._actions = public_action_ids
        self._limit = max_questions
        self._ttl = question_ttl_s
        self._owner_thread = get_ident()
        self._lock = RLock()
        self._enabled = False
        self._clock: int | None = None
        self._generation = 0
        self._cases: tuple[_Case, ...] = ()
        self._cursor = 0
        self._pending: tuple[RecallQuestion, str] | None = None
        self._skill_counts: dict[str, list[int]] = {}
        self._episode_digest = b""
        self._stats = dict(sealed=0, issued=0, graded=0, correct=0,
                           incorrect=0, expired=0, rejected=0)

    def _thread(self) -> None:
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal recall audits to the ledger owner thread")

    def _time(self, now_unix_s: int) -> int:
        now = _unix(now_unix_s)
        if self._clock is not None and now < self._clock:
            raise ValueError("trusted recall clock went backwards")
        self._clock = now
        return now

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit trusted owner approval required")
        self._thread()
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before restarting recall audit")
            self._enabled = True
            self._clock = None
            self._generation += 1

    def disable(self) -> None:
        """Invalidate every issued question and clear the frozen event window."""
        self._thread()
        with self._lock:
            self._enabled = False
            self._generation += 1
            self._cases = ()
            self._cursor = 0
            self._pending = None
            self._clock = None
            self._episode_digest = b""
            self._skill_counts.clear()

    @staticmethod
    def _make_cases(trials: tuple[GameTrial, ...]) -> list[_Case]:
        by_action: dict[str, list[GameTrial]] = {}
        for trial in trials:
            by_action.setdefault(trial.action_id, []).append(trial)
        cases: list[_Case] = []
        for action, rows in sorted(by_action.items()):
            failures = sum(row.outcome == "failure" for row in rows)
            saw_failure = False
            recovered = False
            for row in rows:
                if row.outcome == "failure":
                    saw_failure = True
                elif saw_failure:
                    recovered = True
            streak = longest_streak = 0
            for row in rows:
                streak = streak + 1 if row.outcome == "failure" else 0
                longest_streak = max(longest_streak, streak)
            cases.extend((
                _Case(f"{action}:attempts",
                      f"In the sealed practice episode, how many times was action {action} attempted? "
                      "Reply with one integer.", str(len(rows)), "frequency"),
                _Case(f"{action}:failures",
                      f"In the sealed practice episode, how many attempts with {action} failed? "
                      "Reply with one integer.", str(failures), "frequency"),
                _Case(f"{action}:last",
                      f"What was the final recorded outcome for action {action} in that practice episode? "
                      "Reply success or failure.", rows[-1].outcome, "temporal"),
                _Case(f"{action}:recovery",
                      f"In that practice episode, did a successful {action} attempt occur AFTER an earlier "
                      "failed attempt of the same action? Reply yes or no.",
                      "yes" if recovered else "no", "temporal"),
                _Case(f"{action}:streak",
                      f"What was the longest streak of failures among recorded {action} attempts "
                      "in that practice episode? Reply with one integer.",
                      str(longest_streak), "induction"),
            ))
        actions = tuple(sorted(by_action))
        for i, a in enumerate(actions):
            for b in actions[i + 1:]:
                first_a = by_action[a][0].observed_unix_s
                first_b = by_action[b][0].observed_unix_s
                cases.append(_Case(
                    f"{a}:{b}:comparison",
                    f"In that practice episode, did {a} have strictly MORE failed attempts than {b}? "
                    "Reply yes or no.",
                    "yes" if sum(r.outcome == "failure" for r in by_action[a]) >
                    sum(r.outcome == "failure" for r in by_action[b]) else "no",
                    "comparison",
                ))
                cases.append(_Case(
                    f"{a}:{b}:order",
                    f"In that practice episode, was the FIRST {a} attempt before the FIRST {b} attempt? "
                    "Reply yes or no.",
                    "yes" if first_a < first_b else "no", "sequence",
                ))
        return cases

    def seal_episode(
        self, trials: Sequence[GameTrial], *, episode_id: str,
        now_unix_s: int, host_episode_sealed: bool = False,
    ) -> bool:
        """Freeze host-sealed, chronologically ordered, signed PRACTICE trials.

        This checks that the ledger really contains every exact outcome.
        It cannot prove independently that the supplied trials belong to one
        real episode: the host must attest that, not an LLM or viewer.
        """
        self._thread()
        with self._lock:
            now = self._time(now_unix_s)
            if not self._enabled or host_episode_sealed is not True or self._cases:
                self._stats["rejected"] += 1
                return False
            if type(episode_id) is not str or not _SYMBOL.fullmatch(episode_id):
                raise ValueError("bounded trusted host episode ID required")
            if type(trials) not in (tuple, list) or not 5 <= len(trials) <= 64:
                raise ValueError("five to 64 ordered practice trials required")
            if any(not isinstance(x, GameTrial) for x in trials):
                raise TypeError("expected actual host-signed GameTrial objects")
            rows = tuple(trials)
            scope = tuple(getattr(rows[0], k) for k in (
                "game_id", "game_version", "objective_id", "situation_id"))
            if (any(tuple(getattr(row, k) for k in (
                    "game_id", "game_version", "objective_id", "situation_id")) != scope
                    or row.action_id not in self._actions or row.split != "practice"
                    or row.observed_unix_s > now
                    for row in rows)
                    or len({row.trial_id for row in rows}) != len(rows)
                    or len({row.run_id for row in rows}) != len(rows)
                    or any(a.observed_unix_s >= b.observed_unix_s
                           for a, b in zip(rows, rows[1:]))):
                self._stats["rejected"] += 1
                return False
            # Do not ever read validation material; check exact signed outcomes
            # and abort atomically if one record is missing, forged, or stale.
            for trial in rows:
                if not self._bank.verify_practice_trial(trial, now_unix_s=now):
                    self._stats["rejected"] += 1
                    return False
            cases = self._make_cases(rows)
            # Host-keyed, episode-specific deterministic shuffle. Never use
            # model-provided randomness to pick easier evaluation questions.
            fingerprint = hashlib.sha256(
                b"\x00".join(t.trial_id.encode("ascii") for t in rows)
            ).digest()
            prefix = (b"star.game.recall.v1\x00" + episode_id.encode("ascii")
                      + b"\x00" + fingerprint)
            ordered = sorted(
                cases, key=lambda case: hmac.new(
                    self._key, prefix + case.key.encode("ascii"),
                    hashlib.sha256,
                ).digest(),
            )
            self._cases = tuple(ordered[:self._limit])
            self._episode_digest = fingerprint
            self._cursor = 0
            self._pending = None
            self._generation += 1
            self._stats["sealed"] += 1
            return True

    def issue(self, *, now_unix_s: int) -> RecallQuestion | None:
        """Offer a single question; never expose the answer to the model."""
        self._thread()
        with self._lock:
            now = self._time(now_unix_s)
            if not self._enabled or not self._cases:
                return None
            if self._pending is not None:
                question, _ = self._pending
                if now <= question.expires_unix_s:
                    return None
                self._pending = None
                self._stats["expired"] += 1
            if self._cursor >= len(self._cases):
                return None
            case = self._cases[self._cursor]
            self._cursor += 1
            payload = (self._episode_digest + b":" +
                       f"{self._generation}:{self._cursor}:{now}".encode("ascii"))
            ticket = hmac.new(self._key, b"star.game.recall.ticket.v1\x00" + payload,
                              hashlib.sha256).hexdigest()[:32]
            question = RecallQuestion(ticket, case.prompt, case.skill, now + self._ttl)
            self._pending = question, case.answer
            self._stats["issued"] += 1
            return question

    def grade(self, ticket: str, answer: str, *, now_unix_s: int) -> RecallGrade:
        """One answer per ticket. No correct answer is returned for memorization."""
        self._thread()
        with self._lock:
            now = self._time(now_unix_s)
            if (not self._enabled or self._pending is None or
                    type(ticket) is not str or
                    not hmac.compare_digest(ticket, self._pending[0].ticket)):
                self._stats["rejected"] += 1
                return RecallGrade("rejected")
            question, expected = self._pending
            self._pending = None  # Consume BEFORE checking input, no guessing oracle.
            if now > question.expires_unix_s:
                self._stats["expired"] += 1
                return RecallGrade("expired", question.skill)
            # Exact symbolic answer grading is intentional: no judge model
            # can hallucinate a match, and an injection is never interpreted.
            valid = type(answer) is str and bool(_ANSWER.fullmatch(answer.strip()))
            normalized = answer.strip().lower() if valid else ""
            correct = hmac.compare_digest(normalized, expected)
            self._stats["graded"] += 1
            counts = self._skill_counts.setdefault(question.skill, [0, 0])
            counts[0] += 1
            counts[1] += int(correct)
            self._stats["correct" if correct else "incorrect"] += 1
            return RecallGrade("graded", question.skill, correct)

    def skill_report(self, *, min_attempts: int = 2) -> tuple[RecallSkillScore, ...]:
        """Identify weak recall categories without disclosing model answers.

        A confidence lower bound is not a claim that the model has learned to
        play a game. Scores are evaluated on this fixed offline episode only.
        """
        from .gameplay_skill_bank import wilson_lower

        if type(min_attempts) is not int or not 2 <= min_attempts <= 24:
            raise ValueError("min_attempts must be 2..24")
        self._thread()
        with self._lock:
            return tuple(RecallSkillScore(name, count, right,
                                          round(wilson_lower(right, count), 4))
                         for name, (count, right) in sorted(self._skill_counts.items())
                         if count >= min_attempts)

    def status(self) -> dict[str, int | bool]:
        """No keys, quiz answers, evidence, game labels or private trial IDs."""
        self._thread()
        with self._lock:
            return {**self._stats, "enabled": self._enabled,
                    "ready": bool(self._cases), "pending": self._pending is not None,
                    "remaining": len(self._cases) - self._cursor}


__all__ = ["GroundedGameRecallAudit", "RecallQuestion", "RecallGrade", "RecallSkillScore"]
