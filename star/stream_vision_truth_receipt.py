"""Versioned, host-attested ground-truth receipt for offline game vision.

The independent Roblox Studio/human observer must construct and HMAC-sign a
receipt in a separate, trusted process AFTER reviewing actual game state.
The model, viewer chat and untrusted tools must never possess the signing key.
A valid MAC establishes key-holder provenance, NOT the truth of an observation.

No pixels, prompts, private players, paths, model outputs, speech, or raw
gameplay evidence are included. This module cannot sign observations itself,
capture a game, grant game permissions, or promote a model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
import re

from .stream_visual_perception import VISUAL_KINDS, VISUAL_REGIONS

_DOMAIN = b"star.stream.vision.truth.v1\x00"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL_KINDS = VISUAL_KINDS - {"unknown"}


def _bounded_id(value: object, name: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded identifier")


def _digest(value: object, name: str) -> None:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class VisionTruthReceipt:
    """One independently observed categorical truth bound to one trace ticket.

    The trusted host creates session-specific signing keys and keeps them
    outside model-facing code. Its observer must sign the exact canonical
    bytes returned by canonical_bytes(). Neither observer_run_id nor an HMAC
    proves that a simulated game passed: engine or human validation is still
    necessary.
    """

    game_id: str
    game_version: str
    trace_epoch: int
    trace_serial: int
    frame_sequence: int
    frame_sha256: str
    captured_ms: float
    truth_source: str
    labels: tuple[tuple[str, str], ...]
    observer_run_id: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        for field in ("game_id", "game_version", "observer_run_id"):
            _bounded_id(getattr(self, field), field)
        for field in ("trace_epoch", "trace_serial", "frame_sequence"):
            number = getattr(self, field)
            if type(number) is not int or not 0 < number <= 2**63 - 1:
                raise ValueError(f"{field} must be a positive integer")
        _digest(self.frame_sha256, "frame_sha256")
        _digest(self.evidence_sha256, "evidence_sha256")
        if type(self.captured_ms) not in (int, float):
            raise ValueError("captured_ms must be a finite host clock")
        try:
            time_ms = float(self.captured_ms)
        except (OverflowError, ValueError) as exc:
            raise ValueError("captured_ms must be a finite host clock") from exc
        if not math.isfinite(time_ms) or not 0 <= time_ms <= 1e13:
            raise ValueError("captured_ms outside the host clock range")
        object.__setattr__(self, "captured_ms", time_ms)
        if self.truth_source not in ("studio_engine", "human_annotation"):
            raise ValueError("untrusted ground-truth source")
        if type(self.labels) is not tuple or len(self.labels) > 4:
            raise ValueError("truth labels must be a tuple of at most 4 cues")
        for pair in self.labels:
            if (type(pair) is not tuple or len(pair) != 2
                    or type(pair[0]) is not str or pair[0] not in _LABEL_KINDS
                    or type(pair[1]) is not str or pair[1] not in VISUAL_REGIONS):
                raise ValueError("invalid categorical truth label")
        if tuple(sorted(set(self.labels))) != self.labels:
            raise ValueError("truth labels must be unique and sorted")

    def canonical_bytes(self) -> bytes:
        """Stable domain-separated payload for a trusted external HMAC signer."""
        return _DOMAIN + json.dumps(
            asdict(self), sort_keys=True, ensure_ascii=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("ascii")


def verify_vision_truth_receipt(
    receipt: VisionTruthReceipt, signature: str, *,
    verification_key: bytes,
) -> None:
    """Reject mismatched MACs; never return keys, labels or receipt contents."""
    if type(receipt) is not VisionTruthReceipt:
        raise TypeError("expected a structured vision-truth receipt")
    if type(verification_key) is not bytes or len(verification_key) < 32:
        raise ValueError("trusted observer verification key must have 32+ bytes")
    if type(signature) is not str or _SHA.fullmatch(signature) is None:
        raise PermissionError("invalid independent truth signature")
    expected = hmac.new(
        verification_key, receipt.canonical_bytes(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("independent truth signature did not verify")


__all__ = ["VisionTruthReceipt", "verify_vision_truth_receipt"]
