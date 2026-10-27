"""Opt-in, transcript-verified preemptive LLM response host for STAR's VTuber.

A trusted app may start *text-only* generation while an owner/viewer is finishing
a sentence, then reuse that draft only if the final, moderated transcript and the
final prompt context match byte-for-byte after bounded whitespace normalization.
Unlike early TTS, this can hide thinking latency without risking audible speech
for a misheard or unfinished question. See LiveKit's preemptive-generation docs.

This control plane does NOT listen to a microphone, run an LLM, moderate text,
play sound, enqueue TTS, expose a model tool, or broadcast. Actual GPU/CPU model
work MUST use the existing StreamBrainGovernor lease and be stopped by its
trusted host. Do not pass these methods to a model or a chat participant.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import re
from threading import RLock
import time
from typing import Callable

from .stream_brain_governor import BrainLease, StreamBrainGovernor
from .stream_qos import InferenceJob
from .stream_stage import StagePlan

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KINDS = frozenset({"viewer_question", "owner_interrupt"})


def _clock(read: Callable[[], float]) -> float:
    try:
        value = read()
        if type(value) not in (int, float):
            raise ValueError
        measured = float(value)
        if not math.isfinite(measured) or not 0 <= measured <= 1e13:
            raise ValueError
        return measured
    except Exception as exc:
        raise ValueError("trusted monotonic host clock is unavailable") from exc


def _text(value: object, *, limit: int) -> str:
    if type(value) is not str or not 1 <= len(value.strip()) <= limit:
        raise ValueError("invalid bounded transcript or response")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("control character in speech input")
    # ONLY whitespace is normalized: punctuation, casing, and word order matter.
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("blank utterance")
    return normalized


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def prompt_fingerprint(full_model_prompt: str) -> str:
    """Trusted host computes this from the ENTIRE finalized model input.

    Include persona version, public-knowledge/episode selection and tool/game
    scope. A hash is a consistency guard, not moderation or proof of provenance.
    """
    if type(full_model_prompt) is not str or not 1 <= len(full_model_prompt) <= 65536:
        raise ValueError("full model prompt must be 1..65536 characters")
    return _digest(full_model_prompt)


@dataclass(frozen=True)
class PreviewTicket:
    """Object-identity ticket, never a bearer credential or model capability."""

    generation: int
    serial: int
    signal_id: str
    revision: int
    transcript_digest: str
    prompt_digest: str
    governor_generation: int
    expires_ms: float


@dataclass
class _Slot:
    ticket: PreviewTicket
    lease: BrainLease | None
    answer: str | None = None
    final: bool = False
    revoked: bool = False


class StreamPreemptiveHost:
    """One speculative commentary worker at a time, with rigorous commit fence.

    The HOST must keep the raw moderated provisional transcript and exact model
    prompt outside this object. A preview ticket licenses neither speech nor
    TTS. Only claim() can hand a finished, moderated answer to the embedding
    application, and only against the exact still-prepared StagePlan.

    A revoked/expired worker remains reserved in the governor until the host
    actually stops it and acknowledges that stop. New previews cannot recycle
    the worker slot early.
    """

    def __init__(
        self, *, governor: StreamBrainGovernor,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        maximum_preview_ms: int = 3500,
    ) -> None:
        if not isinstance(governor, StreamBrainGovernor):
            raise TypeError("expected existing StreamBrainGovernor")
        if not callable(clock_ms):
            raise TypeError("trusted monotonic clock is required")
        if type(maximum_preview_ms) is not int or not 250 <= maximum_preview_ms <= 6000:
            raise ValueError("maximum_preview_ms must be 250..6000")
        self._governor, self._clock = governor, clock_ms
        self._maximum = maximum_preview_ms
        self._lock = RLock()
        self._enabled = False
        self._generation = 0
        self._serial = 0
        self._last_ms: float | None = None
        self._slot: _Slot | None = None
        self._counts = dict(
            previews=0, denied=0, reused=0, mismatched=0, expired=0,
            superseded=0, cancelled=0, worker_ack=0,
        )

    def _now(self) -> float:
        now = _clock(self._clock)
        if self._last_ms is not None and now < self._last_ms:
            raise ValueError("trusted monotonic clock moved backwards")
        self._last_ms = now
        return now

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must enable speculative inference")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable the previous preview session first")
            if self._slot is not None and self._slot.lease is not None:
                raise RuntimeError("stop and acknowledge the previous worker first")
            self._now()
            if self._governor.session_generation() < 0:
                raise RuntimeError("enable the realtime brain before previews")
            self._enabled = True
            self._generation += 1
            self._slot = None

    def disable(self) -> None:
        """Immediately revoke reuse; DOES NOT pretend to stop a model worker."""
        with self._lock:
            self._enabled = False
            self._generation += 1
            if self._slot is not None:
                self._discard(self._slot)
                self._counts["cancelled"] += 1

    def _discard(self, slot: _Slot) -> None:
        slot.revoked = True
        slot.answer = None
        slot.final = False
        # Keep the slot while a CPU/GPU model remains physically running.
        if slot.lease is None and self._slot is slot:
            self._slot = None

    def _fresh(self, slot: _Slot, now: float) -> bool:
        t = slot.ticket
        return (
            self._enabled and self._slot is slot and not slot.revoked
            and t.generation == self._generation
            and t.governor_generation == self._governor.session_generation()
            and now < t.expires_ms
        )

    def begin(
        self, *, signal_id: str, revision: int, provisional_transcript: str,
        prompt_digest: str, job: InferenceJob, moderated_by_host: bool = False,
    ) -> PreviewTicket | None:
        """Reserve a QoS-approved *commentary* LLM, never a TTS worker.

        A viewer's words cannot authorize this: moderation/consent happens
        separately. The host supplies a complete prompt digest constructed from
        every public/private context component, not just the STT transcript.
        """
        if type(signal_id) is not str or not _ID.fullmatch(signal_id):
            raise ValueError("invalid signal ID")
        if type(revision) is not int or not 0 <= revision <= 1_000_000:
            raise ValueError("invalid transcript revision")
        normalized = _text(provisional_transcript, limit=300)
        if type(prompt_digest) is not str or not _SHA.fullmatch(prompt_digest):
            raise ValueError("invalid full prompt digest")
        if not isinstance(job, InferenceJob) or job.kind != "commentary":
            raise ValueError("preemptive inference must be a commentary LLM job")
        with self._lock:
            if not self._enabled or moderated_by_host is not True:
                self._counts["denied"] += 1
                return None
            now = self._now()
            if self._governor.session_generation() < 0 or (
                self._governor.status()["stage_phase"] != "idle"
            ):
                self._counts["denied"] += 1
                return None
            if self._slot is not None:
                if self._slot.lease is not None:
                    self._counts["denied"] += 1
                    return None
                self._discard(self._slot)
                self._counts["superseded"] += 1
            admission = self._governor.admit(job)
            if not admission.admitted or admission.lease is None:
                self._counts["denied"] += 1
                return None
            lease = admission.lease
            expires = min(now + self._maximum, lease.expires_ms)
            self._serial += 1
            ticket = PreviewTicket(
                self._generation, self._serial, signal_id, revision,
                _digest(normalized), prompt_digest, lease.generation, expires,
            )
            self._slot = _Slot(ticket, lease)
            self._counts["previews"] += 1
            return ticket

    def finish_worker(
        self, ticket: PreviewTicket, *, worker_stopped: bool,
        succeeded: bool, moderated_answer: str | None = None,
        output_moderated: bool = False,
    ) -> bool:
        """Release the model lease ONLY after the actual worker has stopped.

        The host may present a bounded proposed answer once it has independently
        moderated the output. A model self-report cannot attest worker stop.
        """
        if type(worker_stopped) is not bool or type(succeeded) is not bool:
            raise TypeError("worker acknowledgements must be explicit booleans")
        with self._lock:
            slot = self._slot
            if (not isinstance(ticket, PreviewTicket) or slot is None
                    or slot.ticket is not ticket or slot.lease is None):
                return False
            if not worker_stopped:
                return False
            now = self._now()
            candidate: str | None = None
            if succeeded and output_moderated is True:
                try:
                    candidate = _text(moderated_answer, limit=400)
                except ValueError:
                    candidate = None
            valid = candidate is not None and self._fresh(slot, now)
            # Even a failed/expired run must be acknowledged, to prevent
            # ghost reservations from occupying Star's gaming resources.
            accepted = self._governor.acknowledge_worker_stopped(
                slot.lease, worker_stopped=True, succeeded=valid,
            )
            slot.lease = None
            self._counts["worker_ack"] += 1
            if not (valid and accepted):
                if now >= ticket.expires_ms:
                    self._counts["expired"] += 1
                self._discard(slot)
                return False
            slot.answer = candidate
            return True

    def confirm_final(
        self, ticket: PreviewTicket, *, final_transcript: str,
        final_prompt_digest: str, final_revision: int,
        finalized_by_host: bool = False,
        moderated_by_host: bool = False,
    ) -> bool:
        """Final STT+moderation+prompt fingerprint must match the draft exactly.

        Can be called BEFORE the model worker finishes; claim() will wait for
        both events. Any changed word, punctuation, prompt context, or final
        revision invalidates the speculative response.
        """
        final = _text(final_transcript, limit=300)
        if type(final_revision) is not int or not 0 <= final_revision <= 1_000_000:
            raise ValueError("invalid final transcript revision")
        if type(final_prompt_digest) is not str or not _SHA.fullmatch(
            final_prompt_digest
        ):
            raise ValueError("invalid final prompt digest")
        with self._lock:
            slot = self._slot
            if (not isinstance(ticket, PreviewTicket) or slot is None
                    or slot.ticket is not ticket):
                return False
            now = self._now()
            if not self._fresh(slot, now):
                self._discard(slot)
                return False
            if finalized_by_host is not True or moderated_by_host is not True:
                return False
            if (_digest(final) != ticket.transcript_digest
                    or final_revision != ticket.revision
                    or final_prompt_digest != ticket.prompt_digest):
                self._counts["mismatched"] += 1
                self._discard(slot)
                return False
            slot.final = True
            return True

    def claim(
        self, ticket: PreviewTicket, *, prepared_plan: StagePlan,
        final_prompt_digest: str,
    ) -> str | None:
        """Consume draft ONCE. Host may *then* request a separate speech lease.

        The StagePlan must still be the exact active prepared object. A draft
        must never bypass normal StarStage.queue_audio/acknowledge_audible,
        owner barge-in handling, host moderation or audible-output verification.
        """
        if type(final_prompt_digest) is not str or not _SHA.fullmatch(
            final_prompt_digest
        ):
            raise ValueError("invalid final prompt digest")
        with self._lock:
            slot = self._slot
            if (not isinstance(ticket, PreviewTicket) or slot is None
                    or slot.ticket is not ticket):
                return None
            now = self._now()
            if not self._fresh(slot, now):
                self._discard(slot)
                return None
            if (slot.lease is not None or not slot.final or slot.answer is None
                    or final_prompt_digest != ticket.prompt_digest
                    or not isinstance(prepared_plan, StagePlan)
                    or prepared_plan.signal_id != ticket.signal_id
                    or prepared_plan.kind not in _KINDS
                    or now >= prepared_plan.deadline_at * 1000
                    or not self._governor.prepared_plan(prepared_plan)):
                return None
            answer = slot.answer
            self._slot = None  # one-shot replay fence
            self._counts["reused"] += 1
            return answer

    def revoke(self, ticket: PreviewTicket | None = None) -> None:
        """Called on voice interruption, changed STT revision or scene switch."""
        with self._lock:
            if self._slot is not None and (
                ticket is None or self._slot.ticket is ticket
            ):
                self._discard(self._slot)
                self._counts["cancelled"] += 1

    def status(self) -> dict[str, int | bool]:
        """Anonymous aggregates only: no transcripts, answers or prompt hashes."""
        with self._lock:
            return {
                **self._counts, "enabled": self._enabled,
                "pending_worker": bool(
                    self._slot is not None and self._slot.lease is not None
                ),
                "ready_unspoken": bool(
                    self._slot is not None and self._slot.answer is not None
                ),
            }


__all__ = ["PreviewTicket", "StreamPreemptiveHost", "prompt_fingerprint"]
