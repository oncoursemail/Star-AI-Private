"""Bounded, read-only, real Studio MCP visual evidence for private game practice.

This is the missing observation side of GameActionGate/StudioPlaytestHost:
verified Studio instance -> actual play state -> screenshot bytes -> host-selected
visual assessor -> scoped, timed GameFrame. It never performs keyboard input,
writes files, broadcasts frames, or calls arbitrary model-selected MCP tools.

The signed gameplay evaluator is separate. A screenshot and a successful key
press do not prove an objective was accomplished. When an assessor times out or
caller cancels, its worker stays quarantined until the trusted host confirms
physical termination; cancelling a Python task alone cannot stop a GPU thread. GameFrame confidence is
assessor-reported, not a calibrated guarantee.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time
from typing import Awaitable, Callable, Protocol

from .game_action_gate import GameFrame, GameScope
from .studio import parse_studios

_MAX_IMAGE = 8 * 1024 * 1024
_MAX_PACKET = (_MAX_IMAGE * 4 // 3) + 16
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_DOMAIN = b"star.studio.visual.evidence.v1\0"


class ObservationRejected(RuntimeError):
    """A fixed, non-sensitive reason why no trusted observation was produced."""


class MCPReadSession(Protocol):
    async def call_tool(self, name: str, arguments: dict): ...


@dataclass(frozen=True)
class VisualAssessment:
    """Host-injected vision inference, NOT authenticated objective scoring."""
    playable: bool
    confidence: float
    summary: str = ""

    def __post_init__(self) -> None:
        if type(self.playable) is not bool:
            raise ValueError("playable must be boolean")
        if (type(self.confidence) not in (int, float)
                or not math.isfinite(float(self.confidence))
                or not 0 <= float(self.confidence) <= 1):
            raise ValueError("confidence must be a finite probability")
        if (type(self.summary) is not str or len(self.summary) > 350
                or any(ord(char) < 32 and char not in "\n\t"
                       for char in self.summary)):
            raise ValueError("summary must be short, plain text")


@dataclass(frozen=True)
class VisualEvidence:
    """No raw image is retained. Summary is untrusted, not tool instructions."""
    frame: GameFrame
    image_sha256: str
    image_bytes: int
    changed: bool
    summary: str
    actionable_when_captured: bool
    # Even actionable_when_captured NEVER grants input privileges; it is
    # only a timing indication. GameActionGate must recheck the clock.



@dataclass(frozen=True)
class VisualWorkerLease:
    """Opaque timeout/cancellation lease, not a model tool or game permission."""

    generation: int
    ticket: int



Clock = Callable[[], float]
FocusProbe = Callable[[str], bool]
VisualAssessor = Callable[[bytes], Awaitable[VisualAssessment]]


def _now(clock: Clock) -> float:
    value = clock()
    if (type(value) not in (int, float) or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1e13):
        raise ObservationRejected("invalid_host_clock")
    return float(value)


def _result(reply: object) -> dict:
    model_dump = getattr(reply, "model_dump", None)
    if callable(model_dump):
        reply = model_dump(by_alias=True, exclude_none=True)
    if type(reply) is not dict or reply.get("isError") is not False:
        raise ObservationRejected("studio_tool_failed")
    return reply


def _play_state(reply: object) -> bool:
    """Require one unambiguous, recognized play state; never guess from prose."""
    result = _result(reply)
    structured = result.get("structuredContent")
    text_parts = result.get("content", [])
    if type(text_parts) is not list or len(text_parts) > 12:
        raise ObservationRejected("invalid_studio_state")
    text = "\n".join(part["text"] for part in text_parts
                     if type(part) is dict and part.get("type") == "text"
                     and type(part.get("text")) is str)
    data = None
    if text and len(text) <= 8192:
        try:
            data = json.loads(text)
        except ValueError:
            pass
    states = []
    for obj in (structured, data):
        if obj is not None:
            if type(obj) is not dict or obj.get("playState") not in {"Edit", "Playing"}:
                raise ObservationRejected("invalid_studio_state")
            states.append(obj["playState"])
    if not states:
        # Older Studio releases expose this precise host-authored mode line.
        modes = re.findall(r"(?m)^- Current Studio Mode: (Edit|Play|Playing)\r?$", text)
        if len(modes) == 1:
            states.append("Edit" if modes[0] == "Edit" else "Playing")
    if not states or len(set(states)) != 1:
        raise ObservationRejected("invalid_studio_state")
    return states[0] == "Playing"


def _image(reply: object) -> bytes:
    result = _result(reply)
    parts = result.get("content")
    if type(parts) is not list or len(parts) > 12:
        raise ObservationRejected("invalid_studio_image")
    pictures = [part for part in parts
                if type(part) is dict and part.get("type") == "image"]
    if len(pictures) != 1:
        raise ObservationRejected("missing_or_ambiguous_image")
    picture = pictures[0]
    encoded = picture.get("data")
    kind = picture.get("mimeType")
    if (type(encoded) is not str or not encoded or len(encoded) > _MAX_PACKET
            or kind not in ("image/png", "image/jpeg")):
        raise ObservationRejected("invalid_studio_image")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ObservationRejected("invalid_base64_image") from None
    if not raw or len(raw) > _MAX_IMAGE:
        raise ObservationRejected("oversized_studio_image")
    if kind == "image/png":
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ObservationRejected("image_type_mismatch")
    elif not (raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")):
        raise ObservationRejected("image_type_mismatch")
    return raw


class StudioVisualObserver:
    """Owner-enabled MCP image sensor; no automatic Studio/game interaction.

    The embedding host alone must attest that focus belongs to a local
    private Studio playtest, and must supply the assessor. The model, game,
    chat, and screenshot content cannot choose those callbacks. The existing
    StudioPlaytestHost independently rechecks authorization at action time.
    """

    def __init__(self, *, session: MCPReadSession, studio_id: str,
                 scope: GameScope, focus_and_private: FocusProbe,
                 assessor: VisualAssessor,
                 clock_ms: Clock = lambda: time.monotonic() * 1000.0,
                 tool_timeout_s: float = 2.0,
                 assess_timeout_s: float = 3.0) -> None:
        if (type(studio_id) is not str or not _ID.fullmatch(studio_id)
                or not isinstance(scope, GameScope)
                or not callable(getattr(session, "call_tool", None))
                or not callable(focus_and_private) or not callable(assessor)):
            raise ValueError("invalid trusted Studio observer inputs")
        if (type(tool_timeout_s) not in (float, int) or type(assess_timeout_s) not in (float, int)
                or not math.isfinite(tool_timeout_s) or not math.isfinite(assess_timeout_s)
                or not 0.05 <= tool_timeout_s <= 15 or not 0.05 <= assess_timeout_s <= 30):
            raise ValueError("invalid bounded tool/vision deadlines")
        self._session, self._studio_id = session, studio_id
        self._scope, self._focus, self._assessor = scope, focus_and_private, assessor
        self._clock, self._tool_timeout, self._assess_timeout = clock_ms, tool_timeout_s, assess_timeout_s
        self._lock = asyncio.Lock()
        self._armed = False
        self._generation = 0
        self._sequence = 0
        self._last_image: str | None = None
        self._last_assessment: VisualAssessment | None = None
        self._last_assessed_ms: float = 0
        self._worker_ticket = 0
        self._quarantined: VisualWorkerLease | None = None
        self._quarantined_task: asyncio.Future[VisualAssessment] | None = None
        self._counts = {"observations": 0, "unchanged": 0, "rejected": 0,
                        "cache_hits": 0, "quarantines": 0,
                        "worker_releases": 0, "stale_worker_acks": 0}

    def _private(self) -> None:
        try:
            approved = self._focus(self._studio_id)
        except Exception:
            raise ObservationRejected("private_focus_unverified") from None
        if approved is not True:
            raise ObservationRejected("private_focus_unverified")

    async def _call(self, name: str, args: dict) -> object:
        try:
            return await asyncio.wait_for(self._session.call_tool(name, arguments=args),
                                          timeout=self._tool_timeout)
        except Exception:
            raise ObservationRejected("studio_tool_unavailable") from None

    async def arm(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner approval required for visual playtest")
        async with self._lock:
            if self._armed:
                raise RuntimeError("disarm before starting another observation session")
            if self._quarantined is not None:
                raise RuntimeError("previous visual worker must physically stop before rearming")
            self._private()
            generation = self._generation
            try:
                found = parse_studios(await self._call("list_roblox_studios", {}))
            except Exception:
                raise ObservationRejected("selected_studio_disconnected") from None
            if not any(item["id"] == self._studio_id for item in found):
                raise ObservationRejected("selected_studio_disconnected")
            if not _play_state(await self._call("get_studio_state",
                                                 {"studio_id": self._studio_id})):
                raise ObservationRejected("studio_not_playing")
            if generation != self._generation:
                raise ObservationRejected("authorization_revoked_during_arm")
            self._private()
            self._generation += 1
            self._armed = True
            self._sequence = 0
            self._last_image = None
            self._last_assessment = None

    async def observe(self) -> VisualEvidence:
        async with self._lock:
            if not self._armed:
                raise PermissionError("observer is not armed")
            generation = self._generation
            try:
                if self._quarantined is not None:
                    raise ObservationRejected("previous_visual_worker_not_stopped")
                self._private()
                if not _play_state(await self._call(
                        "get_studio_state", {"studio_id": self._studio_id})):
                    raise ObservationRejected("studio_not_playing")
                started = _now(self._clock)
                raw = _image(await self._call("screen_capture", {
                    "studio_id": self._studio_id,
                    "capture_id": f"StarVision_{self._sequence + 1}",
                }))
                captured = _now(self._clock)
                if captured < started:
                    raise ObservationRejected("host_clock_moved_backward")
                self._private()
                if self._sequence >= 2**63 - 1:
                    raise ObservationRejected("frame_counter_exhausted")
                picture_sha = hashlib.sha256(raw).hexdigest()
                # Hash scope/domain WITH the actual image; no fabricated frame ID.
                scoped = "\0".join((self._studio_id, self._scope.game_id,
                                    self._scope.version_id, self._scope.episode_id)).encode()
                digest = hashlib.sha256(_DOMAIN + len(scoped).to_bytes(4, "big")
                                        + scoped + raw).hexdigest()
                # Exact duplicate frames can reuse recent classification (no
                # large image cache or extra GPU pass). Duplicates are NEVER
                # new action evidence; their actionable confidence is zero.
                cached = (picture_sha == self._last_image
                          and self._last_assessment is not None
                          and 0 <= captured - self._last_assessed_ms <= 500)
                if cached:
                    assessment = self._last_assessment
                    self._counts["cache_hits"] += 1
                else:
                    assessment = await self._assess(raw)
                    if not isinstance(assessment, VisualAssessment):
                        raise ObservationRejected("invalid_visual_assessment")
                if not isinstance(assessment, VisualAssessment):
                    raise ObservationRejected("invalid_visual_assessment")
                if not self._armed or generation != self._generation:
                    raise ObservationRejected("observation_session_revoked")
                self._private()
                age = _now(self._clock) - started
                if age < 0:
                    raise ObservationRejected("host_clock_moved_backward")
                self._sequence += 1
                changed = self._last_image != picture_sha
                self._last_image = picture_sha
                if not cached:
                    self._last_assessment = assessment
                    self._last_assessed_ms = captured
                if not changed:
                    self._counts["unchanged"] += 1
                self._counts["observations"] += 1
                frame = GameFrame(
                    self._scope, self._sequence, started, digest, True,
                    assessment.playable, assessment.confidence if changed else 0.0)
                return VisualEvidence(frame, picture_sha, len(raw), changed,
                                      assessment.summary, changed and age <= 350)
            except ObservationRejected:
                self._counts["rejected"] += 1
                raise

    @staticmethod
    def _drain_worker(task: asyncio.Future[VisualAssessment]) -> None:
        """Consume delayed failures without treating cancellation as a GPU stop."""
        try:
            task.result()
        except BaseException:
            pass

    def _quarantine_worker(
        self, lease: VisualWorkerLease, task: asyncio.Future[VisualAssessment],
    ) -> None:
        # No follow-up vision is allowed while a cancelled coroutine, thread,
        # subprocess or GPU request might still be executing.
        self._quarantined = lease
        self._quarantined_task = task
        self._counts["quarantines"] += 1
        task.add_done_callback(self._drain_worker)
        task.cancel()

    async def _assess(self, raw: bytes) -> VisualAssessment:
        self._worker_ticket += 1
        lease = VisualWorkerLease(self._generation, self._worker_ticket)
        try:
            task = asyncio.ensure_future(self._assessor(raw))
        except Exception:
            raise ObservationRejected("visual_assessor_unavailable") from None
        try:
            done, _ = await asyncio.wait({task}, timeout=self._assess_timeout)
        except asyncio.CancelledError:
            if not task.done():
                self._quarantine_worker(lease, task)
            raise
        except Exception:
            if not task.done():
                self._quarantine_worker(lease, task)
            raise ObservationRejected("visual_assessor_unavailable") from None
        if not done:
            self._quarantine_worker(lease, task)
            raise ObservationRejected("visual_assessor_unavailable")
        try:
            return task.result()
        except BaseException:
            raise ObservationRejected("visual_assessor_unavailable") from None

    def quarantined_worker(self) -> VisualWorkerLease | None:
        """Trusted host obtains exact lease to acknowledge after joining worker."""
        return self._quarantined

    def acknowledge_worker_stopped(
        self, lease: VisualWorkerLease, *, worker_stopped: bool,
    ) -> bool:
        """Release quarantine only after independent physical worker stop.

        A cancelled asyncio task may wrap a still-running C/GPU worker.
        Merely calling task.cancel(), disabling the observer, or claiming the
        job timed out is NOT a termination acknowledgement. The trusted local
        host must join/terminate the actual worker before calling this.
        """
        if not isinstance(lease, VisualWorkerLease) or type(worker_stopped) is not bool:
            raise TypeError("exact worker lease and explicit host stop flag required")
        if self._quarantined is not lease:
            self._counts["stale_worker_acks"] += 1
            return False
        task = self._quarantined_task
        if not worker_stopped or task is None or not task.done():
            return False
        self._quarantined = None
        self._quarantined_task = None
        self._counts["worker_releases"] += 1
        return True

    def disarm(self) -> None:
        # Revocation must be effective even while the assessor is awaited.
        self._generation += 1
        self._armed = False
        self._last_image = None
        self._last_assessment = None

    def metrics(self) -> dict[str, int | bool]:
        return {**self._counts, "armed": self._armed,
                "worker_quarantined": self._quarantined is not None}


__all__ = ["ObservationRejected", "MCPReadSession", "VisualAssessment",
           "VisualEvidence", "VisualWorkerLease", "StudioVisualObserver"]
