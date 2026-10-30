"""Fail-closed, host-verified full-game playthrough evidence for STAR.

A successful Luau build or one dispatched key does not prove an actual game can
be completed. This read-only gate requires a predeclared private-Studio test to
attest a full ordered launch -> spawn -> input -> objective -> exit -> rejoin ->
save-restored cycle for each required client.

Only a trusted, independent game observer may sign events. The verifier is an
injected host-owned callback: never pass its key or receipts to an LLM, game
scripts, streamer chat, or the candidate being tested. A signature authenticates
the observer's claim, not the underlying game truth. The host must inspect
actual engine/client state and physically delivered input before signing.

No Roblox, OBS, filesystem, network, gameplay control, auto-deployment,
training, or authentication-key storage occurs here. Default OFF.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import hashlib
import json
import math
import re
from threading import RLock
from typing import Callable

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PHASES = ("launch", "spawn", "input", "objective", "exit", "rejoin", "save_restored")
_SOURCE = {
    "launch": "engine", "spawn": "engine", "input": "input",
    "objective": "engine", "exit": "engine", "rejoin": "engine",
    "save_restored": "engine",
}
_DOMAIN = b"star.studio.playthrough.v1\x00"
_MAX_CLOCK_MS = 1e13


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return value


def _clock(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("trusted host monotonic clock missing")
    number = float(cast(int | float, value))
    if not math.isfinite(number):
        raise ValueError("trusted host monotonic clock missing")
    if not 0 <= number <= _MAX_CLOCK_MS:
        raise ValueError("invalid host monotonic clock")
    return number


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


@dataclass(frozen=True)
class PlaythroughContract:
    """Predeclared in trusted host code, not proposed by a model under test."""

    game_id: str
    game_version: str
    run_id: str
    client_slots: tuple[int, ...]
    started_ms: float
    max_duration_ms: int = 600_000
    evidence_max_age_ms: int = 1500

    def __post_init__(self) -> None:
        for field in ("game_id", "game_version", "run_id"):
            _id(getattr(self, field), field)
        if (type(self.client_slots) is not tuple
                or not 1 <= len(self.client_slots) <= 8
                or any(type(slot) is not int or not 1 <= slot <= 8
                       for slot in self.client_slots)
                or len(set(self.client_slots)) != len(self.client_slots)):
            raise ValueError("1..8 distinct, bounded opaque client slots required")
        _clock(self.started_ms)
        if (type(self.max_duration_ms) is not int
                or not 10_000 <= self.max_duration_ms <= 900_000):
            raise ValueError("invalid bounded playthrough duration")
        if (type(self.evidence_max_age_ms) is not int
                or not 100 <= self.evidence_max_age_ms <= 3000):
            raise ValueError("invalid evidence freshness bound")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_DOMAIN + _canonical({
            "game_id": self.game_id, "game_version": self.game_version,
            "run_id": self.run_id, "client_slots": self.client_slots,
            "started_ms": float(self.started_ms),
            "max_duration_ms": self.max_duration_ms,
            "evidence_max_age_ms": self.evidence_max_age_ms,
            "phases": _PHASES,
        })).hexdigest()


@dataclass(frozen=True)
class PlaythroughEvent:
    """A signed claim from a separate observer of the actual Studio runtime.

    The host must obtain witness_sha256 from independent input or engine evidence,
    not an AI guess, an on-screen caption, or a passed unit test.
    """

    contract_sha256: str
    client_slot: int
    step_index: int
    phase: str
    source: str  # engine | input, according to the fixed per-phase specification
    observed_ms: float
    witness_sha256: str

    def __post_init__(self) -> None:
        if (type(self.contract_sha256) is not str
                or _SHA.fullmatch(self.contract_sha256) is None
                or type(self.witness_sha256) is not str
                or _SHA.fullmatch(self.witness_sha256) is None):
            raise ValueError("event and witness require SHA-256 pins")
        if type(self.client_slot) is not int or not 1 <= self.client_slot <= 8:
            raise ValueError("invalid client slot")
        if type(self.step_index) is not int or not 0 <= self.step_index < len(_PHASES):
            raise ValueError("invalid playthrough step")
        if (self.phase != _PHASES[self.step_index]
                or self.source != _SOURCE[self.phase]):
            raise ValueError("event phase/source does not match contract")
        _clock(self.observed_ms)

    def canonical_bytes(self) -> bytes:
        """Domain-separated immutable bytes for the independent signer/verifier."""
        return _DOMAIN + _canonical({
            "contract_sha256": self.contract_sha256,
            "client_slot": self.client_slot, "step_index": self.step_index,
            "phase": self.phase, "source": self.source,
            "observed_ms": float(self.observed_ms),
            "witness_sha256": self.witness_sha256,
        })


@dataclass(frozen=True)
class PlaythroughReport:
    status: str  # disabled | collecting | invalid | incomplete | eligible_for_manual_review
    reason: str
    completed_clients: int
    required_clients: int
    accepted_events: int
    rejected_events: int
    next_phases: tuple[tuple[int, str], ...]
    automatically_certified: bool = False


# This callback lives in trusted host code and MUST check a separate observer's
# signature, using a key not exposed to STAR/model/game scripts. A callback that
# merely returns True is not independent validation.
IndependentVerifier = Callable[[bytes, str], bool]


class StudioPlaythroughGate:
    """Bounded, zero-inference completion witness for private Studio sessions."""

    def __init__(self, contract: PlaythroughContract, *,
                 verify_independent_receipt: IndependentVerifier) -> None:
        if not isinstance(contract, PlaythroughContract):
            raise TypeError("contract must be owner-registered")
        if not callable(verify_independent_receipt):
            raise TypeError("independent verifier callback required")
        self._spec = contract
        self._verifier = verify_independent_receipt
        self._lock = RLock()
        self._enabled = False
        self._invalid = False
        self._seen_proofs: set[str] = set()
        self._next = {slot: 0 for slot in contract.client_slots}
        self._last_time = {slot: contract.started_ms for slot in contract.client_slots}
        self._accepted = 0
        self._rejected = 0
        self._last_host_ms = contract.started_ms

    def enable(self, *, owner_approved: bool = False,
               private_studio_confirmed: bool = False) -> None:
        if owner_approved is not True or private_studio_confirmed is not True:
            raise PermissionError("owner opt-in and private Studio host required")
        with self._lock:
            if self._enabled or self._invalid or self._accepted:
                raise RuntimeError("one-shot test gate cannot be reset or replayed")
            self._enabled = True

    def submit(self, event: PlaythroughEvent, *, receipt: str,
               now_ms: float) -> bool:
        """Ingest one independently witnessed phase; fail CLOSED on ambiguity.

        Signature verification is the last gate before advancing. No candidate
        model may choose the receipt/verifier or an event's evidence source.
        """
        now = _clock(now_ms)
        with self._lock:
            if not self._enabled or self._invalid:
                self._rejected += 1
                return False
            if now < self._last_host_ms:
                self._invalid = True
                self._rejected += 1
                return False
            self._last_host_ms = now
            try:
                if not isinstance(event, PlaythroughEvent):
                    raise ValueError("unrecognized event")
                if type(receipt) is not str or _SHA.fullmatch(receipt) is None:
                    raise ValueError("missing independent signature")
                if (event.contract_sha256 != self._spec.digest
                        or event.client_slot not in self._next
                        or event.step_index != self._next[event.client_slot]):
                    raise ValueError("cross-run/client, duplicate or out-of-order event")
                if (event.observed_ms <= self._last_time[event.client_slot]
                        or event.observed_ms < self._spec.started_ms
                        or event.observed_ms > now
                        or now - event.observed_ms > self._spec.evidence_max_age_ms
                        or now - self._spec.started_ms > self._spec.max_duration_ms):
                    raise ValueError("expired or non-monotonic test witness")
                if event.witness_sha256 in self._seen_proofs:
                    raise ValueError("witness evidence reused across phases")
                # No unsigned event ever advances. Independent verifier must be
                # implemented and audited by the trusted host, not the agent.
                if self._verifier(event.canonical_bytes(), receipt) is not True:
                    raise ValueError("independent receipt rejected")
            except Exception:
                self._invalid = True
                self._rejected += 1
                return False
            self._seen_proofs.add(event.witness_sha256)
            self._last_time[event.client_slot] = event.observed_ms
            self._next[event.client_slot] += 1
            self._accepted += 1
            return True

    def report(self, *, now_ms: float) -> PlaythroughReport:
        now = _clock(now_ms)
        with self._lock:
            finished = sum(pos == len(_PHASES) for pos in self._next.values())
            reversed_clock = now < self._last_host_ms
            self._last_host_ms = max(now, self._last_host_ms)
            if not self._enabled:
                status, reason = "disabled", "private Studio test not enabled"
            elif self._invalid or reversed_clock:
                self._invalid = True
                status, reason = "invalid", "untrusted, inconsistent or stale evidence"
            elif now < self._spec.started_ms or now - self._spec.started_ms > self._spec.max_duration_ms:
                self._invalid = True
                status, reason = "invalid", "test window expired or host clock reversed"
            elif finished == len(self._next):
                status, reason = "eligible_for_manual_review", (
                    "all required host-attested phases present; runtime truth "
                    "and client save-state still require independent review")
            else:
                status, reason = "incomplete", "awaiting full host-attested playthrough"
            return PlaythroughReport(
                status, reason, finished, len(self._next), self._accepted,
                self._rejected,
                tuple((slot, _PHASES[pos]) for slot, pos in sorted(self._next.items())
                      if pos < len(_PHASES)),
            )

    def disable(self) -> None:
        """Stop accepting evidence; no game or external device is controlled."""
        with self._lock:
            self._enabled = False
            self._invalid = True
            self._seen_proofs.clear()


__all__ = [
    "PlaythroughContract", "PlaythroughEvent", "PlaythroughReport",
    "StudioPlaythroughGate",
]
