"""Host-controlled bridge from pinned recall cards to actual offline model practice.

This orchestrator does not supply a model, a grader, secrets, external access, or
an automatic learning claim. A trusted host must explicitly opt in, provide a
cancelable LOCAL inference callback, a separately trusted signing grader, a clock,
and fresh host-only hardware telemetry. Model-visible data is strictly a vetted
question prompt. Private answer keys and HMAC keys must not enter that callback.

One active practice attempt at a time. Raw prompts and answers are never written
to logs or returned in reports. The only accepted progress is the planner's
independently authenticated GradedRecall.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from time import monotonic
from typing import Awaitable, Callable, Sequence

from .knowledge_recall import GradedRecall, KnowledgeRecallPlanner
from .stream_budget import StreamTelemetry, advise_workload

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PROMPT = 2_048
_MAX_ANSWER = 4_096


@dataclass(frozen=True)
class PracticeQuestion:
    """Only public-to-the-model, owner-curated question text and a source pin."""

    question_id: str
    source_sha256: str
    prompt: str

    def __post_init__(self) -> None:
        if type(self.question_id) is not str or _ID.fullmatch(self.question_id) is None:
            raise ValueError("question_id must be a bounded opaque ID")
        if type(self.source_sha256) is not str or _HEX.fullmatch(self.source_sha256) is None:
            raise ValueError("source pin must be a SHA-256 digest")
        if type(self.prompt) is not str or not self.prompt.strip() or "\x00" in self.prompt:
            raise ValueError("question prompt must be bounded, nonempty UTF-8")
        try:
            prompt_bytes = self.prompt.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("question prompt must be valid UTF-8") from exc
        if len(prompt_bytes) > _MAX_PROMPT:
            raise ValueError("question prompt must be bounded, nonempty UTF-8")


@dataclass(frozen=True)
class PracticeReport:
    status: str
    reason: str
    question_id: str | None = None
    inference_ms: int | None = None
    # Intentionally no answer text, answer key, signature, or correctness label.


# The signer/grader is external. Its result is verified by the planner, not by
# the model or this bridge. DO NOT use a model self-judge as this callback.
LocalInference = Callable[[str], Awaitable[str]]
IndependentGrader = Callable[[str, str, str, str], Awaitable[GradedRecall]]
HostClock = Callable[[], int]
HostTelemetry = Callable[[], StreamTelemetry | None]


class KnowledgePracticeHost:
    """Disabled-by-default bridge; trusted service supplies all I/O.

    The host supplies the *prompt only* to inference. The independent grader
    receives (question ID, ticket, source SHA, candidate answer) and must sign
    with its own key outside this module. The planner alone accepts/rejects that
    signature. Neither signer nor private note body is passed to the model.

    An async callback must honor cancellation and perform all I/O within its
    owner-authorized local sandbox. This module cannot prove the callback's
    network isolation or prevent a malicious host from leaking private data.
    """

    def __init__(
        self,
        planner: KnowledgeRecallPlanner,
        *,
        questions: Sequence[PracticeQuestion],
        infer_local: LocalInference,
        grade_independently: IndependentGrader,
        host_clock: HostClock,
        host_telemetry: HostTelemetry,
        inference_timeout_s: int = 20,
        grading_timeout_s: int = 8,
    ) -> None:
        if not isinstance(planner, KnowledgeRecallPlanner):
            raise TypeError("expected KnowledgeRecallPlanner")
        if (type(questions) not in (tuple, list)
                or not 1 <= len(questions) <= 96
                or any(not isinstance(q, PracticeQuestion) for q in questions)
                or len({q.question_id for q in questions}) != len(questions)):
            raise ValueError("provide 1..96 unique approved public questions")
        if any(not callable(fn) for fn in
               (infer_local, grade_independently, host_clock, host_telemetry)):
            raise TypeError("host must provide inference, grader, clock and telemetry")
        if (type(inference_timeout_s) is not int or
                not 1 <= inference_timeout_s <= 90):
            raise ValueError("bounded inference timeout required")
        if type(grading_timeout_s) is not int or not 1 <= grading_timeout_s <= 30:
            raise ValueError("bounded grading timeout required")
        self._planner = planner
        self._questions = {q.question_id: q for q in questions}
        self._infer = infer_local
        self._grade = grade_independently
        self._clock = host_clock
        self._telemetry = host_telemetry
        self._inference_timeout_s = inference_timeout_s
        self._grading_timeout_s = grading_timeout_s
        self._enabled = False
        self._lock = asyncio.Lock()
        self._active_task: asyncio.Task | None = None
        self._counts = {
            "verified": 0, "deferred": 0, "aborted": 0,
            "failed": 0, "timeouts": 0, "reentrant": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted owner must enable local recall execution")
        if self._enabled:
            raise RuntimeError("recall execution is already enabled")
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        # Stop work started under a revoked host authorization. The caller must
        # invoke this on the same asyncio event loop / planner host thread.
        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()

    def metrics(self) -> dict[str, int | bool]:
        return {**self._counts, "enabled": self._enabled,
                "busy": self._lock.locked()}

    def _result(self, status: str, reason: str,
                question_id: str | None = None,
                inference_ms: int | None = None) -> PracticeReport:
        if status in self._counts:
            self._counts[status] += 1
        return PracticeReport(status, reason, question_id, inference_ms)

    def _safe_cancel(self, ticket: str) -> None:
        try:
            self._planner.cancel(ticket=ticket, now_unix_s=self._clock())
        except (ValueError, RuntimeError):
            # Host must address a broken clock separately; never self-grade.
            pass

    def _offline(self) -> bool:
        telemetry = self._telemetry()
        if not isinstance(telemetry, StreamTelemetry) or telemetry.live:
            return False
        if telemetry.game_active and telemetry.game_fps < 50:
            return False
        if telemetry.speech_backlog_ms > 250:
            return False
        # Workload headroom may have deteriorated since reservation.
        return advise_workload("training", telemetry).allowed

    async def run_once(self) -> PracticeReport:
        """Try one host-authorized practice, never a hidden test or live stream.

        An existing planner opt-in is independently required. Timeout, wrong
        source pin, invalid model output, grader failure, owner disable,
        reentrant call, and stream-start all fail closed without a grade.
        """
        if not self._enabled:
            return self._result("deferred", "host_opt_in_missing")
        if self._lock.locked():
            return self._result("reentrant", "one_practice_attempt_at_a_time")
        async with self._lock:
            self._active_task = asyncio.current_task()
            ticket: str | None = None
            try:
                if not self._enabled:
                    return self._result("deferred", "host_opt_in_revoked")
                advice = self._planner.reserve(
                    now_unix_s=self._clock(), telemetry=self._telemetry())
                if advice.status != "practice_candidate":
                    return self._result("deferred", advice.reason)
                ticket, qid = advice.ticket, advice.question_id
                if not ticket or not qid:
                    return self._result("failed", "invalid_planner_reservation")
                question = self._questions.get(qid)
                if (question is None or
                        self._planner.pinned_source_for(qid) != question.source_sha256):
                    return self._result("aborted", "vetted_prompt_pin_missing", qid)
                if not self._enabled or not self._offline():
                    return self._result("aborted", "offline_window_closed", qid)
                started = monotonic()
                try:
                    answer = await asyncio.wait_for(
                        self._infer(question.prompt), timeout=self._inference_timeout_s)
                except TimeoutError:
                    self._counts["timeouts"] += 1
                    return self._result("aborted", "local_inference_timeout", qid)
                inference_ms = max(0, round((monotonic() - started) * 1000))
                if (type(answer) is not str or
                        len(answer.encode("utf-8")) > _MAX_ANSWER or
                        not answer.strip() or "\x00" in answer):
                    return self._result("aborted", "invalid_model_response", qid,
                                        inference_ms)
                if not self._enabled or not self._offline():
                    return self._result("aborted", "offline_window_closed", qid,
                                        inference_ms)
                try:
                    graded = await asyncio.wait_for(
                        self._grade(qid, ticket, question.source_sha256, answer),
                        timeout=self._grading_timeout_s)
                except TimeoutError:
                    self._counts["timeouts"] += 1
                    return self._result("aborted", "independent_grader_timeout", qid,
                                        inference_ms)
                # A slow model or slow grader cannot complete after the host
                # moved to live mode, lost telemetry, or revoked permission.
                if not self._enabled or not self._offline():
                    return self._result("aborted", "offline_window_closed", qid,
                                        inference_ms)
                if (not isinstance(graded, GradedRecall) or
                        not self._planner.finish(graded, now_unix_s=self._clock())):
                    return self._result("aborted", "unsigned_or_stale_grade", qid,
                                        inference_ms)
                return self._result("verified", "authenticated_grade_accepted", qid,
                                    inference_ms)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not log exception text: provider exceptions can contain
                # prompts, answers, secrets, or URLs. Failure never counts as
                # successful learning.
                return self._result("failed", "host_callback_or_clock_failure")
            finally:
                if ticket is not None:
                    self._safe_cancel(ticket)
                self._active_task = None


__all__ = ["PracticeQuestion", "PracticeReport", "KnowledgePracticeHost"]
