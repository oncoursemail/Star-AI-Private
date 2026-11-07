"""Owner-only paired vision evidence collector for offline Roblox game evaluation.

Predictions are frozen for the ENTIRE cohort before independent ground-truth
labels become writable. This reduces hindsight leakage during model comparisons.
An external, authorized capture host must guarantee BOTH workers saw the exact
same frame and that the independent scorer saw the correct game state.

This module does NOT capture screens, run models, authenticate an engine, label
screenshots, sign outcomes, control games, or deploy model configurations.
Inputs are bounded categorical fields and host clock observations only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
from threading import RLock

from .stream_vision_eval import (
    VisionEvalCase, VisionEvalPrediction, compare_vision, prediction_from_packet,
)
from .stream_visual_perception import VISUAL_KINDS, VISUAL_REGIONS, VisualPacket

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_LABEL_KINDS = VISUAL_KINDS - {"unknown"}
_VARIANTS = frozenset(("baseline", "candidate"))


def _host_ms(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("trusted host time must be numeric")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid host time") from exc
    if not math.isfinite(result) or not 0 <= result <= 1e13:
        raise ValueError("invalid host time")
    return result


def _symbol(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded symbolic identifier")
    return value


@dataclass(frozen=True)
class HostFrameRef:
    """Host-attested frame identity, never pixels or a user-visible title."""

    sequence: int
    sha256: str
    captured_ms: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or not 0 < self.sequence <= 2**63 - 1:
            raise ValueError("frame sequence must be a positive integer")
        if type(self.sha256) is not str or _DIGEST.fullmatch(self.sha256) is None:
            raise ValueError("frame requires an exact SHA-256 digest")
        _host_ms(self.captured_ms)


@dataclass(frozen=True)
class VisionTraceTicket:
    """Opaque, session-bound entry; NOT an authorization or a model tool."""

    epoch: int
    serial: int


@dataclass
class _Trace:
    frame: HostFrameRef
    ticket: VisionTraceTicket
    predictions: dict[str, VisionEvalPrediction] = field(default_factory=dict)
    truth: tuple[tuple[str, str], ...] | None = None
    truth_source: str | None = None


class PairedVisionTraceHost:
    """Finite opt-in trace capture, blind truth collection and private export.

    The embedding host alone may call this API. It must ensure the game window
    belongs to an authorized sandbox/private session, capture once per case,
    and feed exactly the same captured pixels to both variant workers.

    A candidate sees no hidden labels through this class. Ground truth is
    recorded only AFTER every variant prediction in the cohort is frozen.
    Merely setting independent_scorer=True is not authentication of truth.
    """

    def __init__(self, *, game_id: str, game_version: str,
                 max_cases: int = 512) -> None:
        self._game_id = _symbol(game_id, "game_id")
        self._game_version = _symbol(game_version, "game_version")
        if type(max_cases) is not int or not 1 <= max_cases <= 4096:
            raise ValueError("max_cases must be 1..4096")
        self._max_cases = max_cases
        self._lock = RLock()
        self._enabled = False
        self._sealed = False
        self._epoch = 0
        self._entries: dict[int, _Trace] = {}
        self._digests: set[str] = set()
        self._last_seq = 0
        self._last_captured_ms = 0.0
        self._stats = dict(reserved=0, results=0, failed_workers=0,
                           truth_labels=0, exports=0)

    def enable(self, *, owner_approved: bool = False,
               offline_capture_approved: bool = False) -> None:
        if owner_approved is not True or offline_capture_approved is not True:
            raise PermissionError("owner and offline capture consent required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("finish the prior evaluation session first")
            self._epoch += 1
            self._entries.clear()
            self._digests.clear()
            self._last_seq = 0
            self._last_captured_ms = 0.0
            self._sealed = False
            self._enabled = True

    def disable(self) -> None:
        """Owner STOP destroys pending labels and predictions; no export."""
        with self._lock:
            self._enabled = False
            self._sealed = False
            self._epoch += 1
            self._entries.clear()
            self._digests.clear()
            self._last_seq = 0
            self._last_captured_ms = 0.0

    def reserve(self, frame: HostFrameRef, *,
                capture_approved: bool = False) -> VisionTraceTicket:
        if type(frame) is not HostFrameRef:
            raise TypeError("expected a host frame reference")
        if capture_approved is not True:
            raise PermissionError("host must recheck offline capture consent")
        with self._lock:
            if not self._enabled or self._sealed:
                raise RuntimeError("trace collection not active")
            if len(self._entries) >= self._max_cases:
                raise RuntimeError("bounded cohort full")
            if (frame.sequence <= self._last_seq
                    or frame.captured_ms < self._last_captured_ms):
                raise ValueError("replayed or out-of-order frame")
            if frame.sha256 in self._digests:
                raise ValueError("duplicate frame pixels could inflate holdout")
            self._last_seq = frame.sequence
            self._last_captured_ms = frame.captured_ms
            serial = len(self._entries) + 1
            ticket = VisionTraceTicket(self._epoch, serial)
            self._entries[serial] = _Trace(frame, ticket)
            self._digests.add(frame.sha256)
            self._stats["reserved"] += 1
            return ticket

    def _lookup(self, ticket: VisionTraceTicket) -> _Trace:
        if (not self._enabled or type(ticket) is not VisionTraceTicket
                or ticket.epoch != self._epoch
                or ticket.serial not in self._entries
                or ticket is not self._entries[ticket.serial].ticket):
            raise PermissionError("not an active trusted trace ticket")
        return self._entries[ticket.serial]

    def record_worker(
        self, ticket: VisionTraceTicket, *, variant: str,
        packet: VisualPacket | None, status: str,
        started_ms: float, finished_ms: float,
        worker_stopped: bool = False,
    ) -> None:
        """Freeze one worker observation after the authorized host joined it.

        An unjoined or timed-out physical worker may still consume resources;
        the host must first stop it. A failed response must be explicitly
        recorded as error/timeout, never silently omitted from evaluation.
        """
        with self._lock:
            entry = self._lookup(ticket)
            if self._sealed:
                raise RuntimeError("model predictions already frozen")
            if variant not in _VARIANTS or type(variant) is not str:
                raise ValueError("variant must be baseline or candidate")
            if variant in entry.predictions:
                raise ValueError("duplicate worker cannot rewrite prediction")
            if worker_stopped is not True:
                raise PermissionError("physical worker stop not confirmed")
            started, finished = _host_ms(started_ms), _host_ms(finished_ms)
            if (started < entry.frame.captured_ms or finished < started
                    or finished - entry.frame.captured_ms > 120000):
                raise ValueError("worker timestamps must match this frame")
            if status == "accepted" and packet is None:
                raise ValueError("accepted worker requires a concrete VisualPacket")
            prediction = prediction_from_packet(
                packet, status=status, captured_ms=entry.frame.captured_ms,
                started_ms=started, finished_ms=finished)
            entry.predictions[variant] = prediction
            self._stats["results"] += 1
            if prediction.status in {"timeout", "error"}:
                self._stats["failed_workers"] += 1

    def seal_predictions(self) -> None:
        """Permanently close model submissions before revealing ANY truth."""
        with self._lock:
            if not self._enabled or self._sealed or not self._entries:
                raise RuntimeError("no active unsealed trace cohort")
            if any(set(t.predictions) != _VARIANTS for t in self._entries.values()):
                raise RuntimeError("explicitly record both workers, including failures")
            self._sealed = True

    def record_truth(
        self, ticket: VisionTraceTicket, *,
        labels: tuple[tuple[str, str], ...],
        truth_source: str, independent_scorer: bool = False,
    ) -> None:
        """Isolated engine/human scorer writes categorical truth after freeze."""
        with self._lock:
            entry = self._lookup(ticket)
            if not self._sealed:
                raise PermissionError("freeze all worker predictions before scoring")
            if independent_scorer is not True:
                raise PermissionError("independent host scorer required")
            if entry.truth is not None:
                raise ValueError("cannot replace a sealed truth label")
            if (type(labels) is not tuple or len(labels) > 4
                    or any(type(pair) is not tuple or len(pair) != 2
                           or type(pair[0]) is not str or pair[0] not in _LABEL_KINDS
                           or type(pair[1]) is not str or pair[1] not in VISUAL_REGIONS
                           for pair in labels)
                    or len(set(labels)) != len(labels)):
                raise ValueError("truth must be unique bounded categorical cues")
            if truth_source not in ("studio_engine", "human_annotation"):
                raise ValueError("untrusted truth provenance")
            entry.truth = labels
            entry.truth_source = truth_source
            self._stats["truth_labels"] += 1

    def _cases(self) -> list[VisionEvalCase]:
        if not self._enabled or not self._sealed:
            raise RuntimeError("no sealed cohort")
        if any(t.truth is None for t in self._entries.values()):
            raise RuntimeError("all independent truth labels required")
        return [
            VisionEvalCase(
                f"case_{serial:05d}", self._game_id, self._game_version,
                t.truth_source, t.truth,
                t.predictions["baseline"], t.predictions["candidate"],
            )
            for serial, t in sorted(self._entries.items())
        ]

    @staticmethod
    def _prediction_dict(prediction: VisionEvalPrediction) -> dict[str, object]:
        return {
            "status": prediction.status,
            "findings": [
                {"kind": kind, "region": region, "confidence": 1.0}
                for kind, region in prediction.labels
            ],
            "latency_ms": prediction.latency_ms,
            "age_ms": prediction.age_ms,
        }

    def owner_report(self, *, owner_approved: bool = False) -> dict[str, object]:
        """Only aggregate scoring, never individual held-out truth labels."""
        if owner_approved is not True:
            raise PermissionError("sealed holdout scoring is owner-only")
        with self._lock:
            return compare_vision(self._cases()).to_dict()

    def export_jsonl(self, path: str | Path, *, owner_approved: bool = False) -> int:
        """Create private on-disk trace in the existing evaluation schema.

        Exports never overwrite an existing file, follow a symlink, or grant
        read access to other Unix users. The caller must keep this path out of
        Git repos and model-accessible directories.
        """
        if owner_approved is not True:
            raise PermissionError("owner approval required for private trace export")
        dest = Path(path)
        ancestors = (dest.parent, *dest.parent.parents)
        if (dest.suffix != ".jsonl" or not dest.parent.is_dir()
                or dest.is_symlink()
                or any(parent.is_symlink() or (parent / ".git").exists()
                       for parent in ancestors)):
            raise ValueError(
                "expected new .jsonl outside symlinks and Git workspaces")
        with self._lock:
            cases = self._cases()
            lines = []
            for item in cases:
                record = {
                    "case_id": item.case_id, "game_id": item.game_id,
                    "game_version": item.game_version, "partition": "holdout",
                    "truth_source": item.truth_source,
                    "truth": [
                        {"kind": kind, "region": region} for kind, region in item.truth
                    ],
                    "baseline": self._prediction_dict(item.baseline),
                    "candidate": self._prediction_dict(item.candidate),
                }
                encoded = json.dumps(
                    record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ) + "\n"
                if len(encoded.encode("ascii")) > 8192:
                    raise ValueError("evaluation row too large")
                lines.append(encoded)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            fd = os.open(dest, flags, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="ascii", newline="") as stream:
                    stream.writelines(lines)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                dest.unlink(missing_ok=True)
                raise
            self._stats["exports"] += 1
            return len(cases)

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                **self._stats, "enabled": self._enabled, "sealed": self._sealed,
                "cases": len(self._entries),
                "unlabelled": sum(t.truth is None for t in self._entries.values()),
            }


__all__ = ["HostFrameRef", "VisionTraceTicket", "PairedVisionTraceHost"]
