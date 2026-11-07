"""Offline, evidence-gated whole-game journey checks for STAR-built games.

A successful build, attractive screenshot or one checkpoint is not a playable
game. The independent test host must actually launch a candidate, issue player
input, observe each objective, save, quit, reopen in a NEW process, verify the
restored game state, and reach the ending. Only signed, scope-bound host events
count. The model never supplies signing keys, observations or permissions.

This module performs NO game I/O, launches no software, reads no recordings,
stores no player identity and cannot authorize game publication. A valid HMAC
authenticates a host's assertion, NOT the truth of its underlying measurement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import hmac
import json
import re
from typing import Sequence

from .studio_multimodal_quality_gate import QualityReport

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_DOMAIN = b"star.game-completion-journey.v1\x00"
_DAY_MS = 86_400_000
_MAX_CLOCK_MS = 10**14


def _id(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label}: bounded opaque identifier required")
    return value


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label}: lowercase SHA256 required")
    return value


def _time(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value <= _MAX_CLOCK_MS:
        raise ValueError(f"{label}: positive integer Unix milliseconds required")
    return value


def _key(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        raise ValueError("independent host must supply a secret key of >=32 bytes")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class JourneyContract:
    """Owner-curated, externally sealed game specification, NOT model self-grading."""

    contract_id: str
    run_id: str
    game_id: str
    game_version: str
    build_sha256: str
    checkpoints: tuple[str, ...]
    registered_unix_ms: int
    max_duration_ms: int = 1_800_000

    def __post_init__(self) -> None:
        for name in ("contract_id", "run_id", "game_id", "game_version"):
            _id(getattr(self, name), name)
        _sha(self.build_sha256, "build_sha256")
        _time(self.registered_unix_ms, "registered_unix_ms")
        if (type(self.checkpoints) is not tuple
                or not 1 <= len(self.checkpoints) <= 20
                or any(type(c) is not str or not _ID.fullmatch(c)
                       for c in self.checkpoints)
                or len(set(self.checkpoints)) != len(self.checkpoints)):
            raise ValueError("1..20 unique owner-curated checkpoints required")
        if (type(self.max_duration_ms) is not int
                or not 30_000 <= self.max_duration_ms <= 7_200_000):
            raise ValueError("journey timeout must be 30 seconds..2 hours")

    def required_events(self) -> tuple[tuple[str, str], ...]:
        """Contract requires INPUT before EVERY objective and ending."""
        route: list[tuple[str, str]] = [("launch", "")]
        for checkpoint in self.checkpoints:
            route.extend([("input", ""), ("checkpoint", checkpoint)])
        route.extend([
            ("save", ""), ("quit", ""), ("relaunch", ""), ("restore", ""),
            ("input", ""), ("ending", ""),
        ])
        return tuple(route)


def contract_digest(contract: JourneyContract) -> str:
    """Commit this digest to a separate timestamped host ledger BEFORE play."""
    if not isinstance(contract, JourneyContract):
        raise TypeError("expected JourneyContract")
    return sha256(_DOMAIN + b"contract\x00" + _canonical(asdict(contract))).hexdigest()


@dataclass(frozen=True)
class JourneyEvent:
    """Metadata emitted by the independent game tester AFTER witnessing events."""

    contract_id: str
    run_id: str
    game_id: str
    game_version: str
    build_sha256: str
    kind: str
    checkpoint_id: str
    process_instance_id: str
    evidence_sha256: str
    state_sha256: str
    sequence: int
    observed_unix_ms: int

    def __post_init__(self) -> None:
        for name in ("contract_id", "run_id", "game_id", "game_version",
                     "process_instance_id"):
            _id(getattr(self, name), name)
        _sha(self.build_sha256, "build_sha256")
        _sha(self.evidence_sha256, "evidence_sha256")
        if type(self.kind) is not str or self.kind not in {
            "launch", "input", "checkpoint", "save", "quit",
            "relaunch", "restore", "ending",
        }:
            raise ValueError("invalid journey event kind")
        if self.kind == "checkpoint":
            _id(self.checkpoint_id, "checkpoint_id")
        elif self.checkpoint_id != "":
            raise ValueError("checkpoint_id is valid only on checkpoint events")
        if self.kind in {"save", "restore"}:
            _sha(self.state_sha256, "state_sha256")
        elif self.state_sha256 != "":
            raise ValueError("state_sha256 only permitted on save/restore")
        if type(self.sequence) is not int or not 1 <= self.sequence <= 64:
            raise ValueError("bounded positive event sequence required")
        _time(self.observed_unix_ms, "observed_unix_ms")


@dataclass(frozen=True)
class SignedJourneyEvent:
    event: JourneyEvent
    mac_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.event, JourneyEvent):
            raise TypeError("expected JourneyEvent")
        _sha(self.mac_sha256, "mac_sha256")


def sign_journey_event(event: JourneyEvent, *, host_key: bytes
                       ) -> SignedJourneyEvent:
    """Call ONLY on the authorized independent observer, never in STAR's model."""
    if not isinstance(event, JourneyEvent):
        raise TypeError("expected JourneyEvent")
    mac = hmac.new(_key(host_key), _DOMAIN + b"event\x00"
                   + _canonical(asdict(event)), sha256).hexdigest()
    return SignedJourneyEvent(event, mac)


@dataclass(frozen=True)
class JourneyReport:
    verdict: str  # eligible_for_review | incomplete | invalid_evidence
    observed_steps: int
    required_steps: int
    next_required: str | None
    concerns: tuple[str, ...] = ()
    authorized_to_publish: bool = False
    certified_general_game_skill: bool = False


def _report(verdict: str, observed: int, expected: tuple[tuple[str, str], ...],
            *concerns: str) -> JourneyReport:
    next_step = None
    if observed < len(expected):
        kind, checkpoint = expected[observed]
        next_step = kind + (":" + checkpoint if checkpoint else "")
    return JourneyReport(verdict, observed, len(expected), next_step, tuple(concerns))


def evaluate_journey(
    contract: JourneyContract,
    receipts: Sequence[SignedJourneyEvent],
    *,
    host_key: bytes,
    externally_sealed_sha256: str,
    now_unix_ms: int,
) -> JourneyReport:
    """Fail-closed readiness assessment; an execution HOST produces all facts.

    The game runner must verify real player input, game-state transitions and
    persistence outside STAR's model before signing. This method checks scope,
    replay, step order, process independence, state continuity and freshness.
    """
    if not isinstance(contract, JourneyContract):
        raise TypeError("expected JourneyContract")
    key = _key(host_key)
    _sha(externally_sealed_sha256, "externally_sealed_sha256")
    now = _time(now_unix_ms, "now_unix_ms")
    expected = contract.required_events()
    if (not hmac.compare_digest(externally_sealed_sha256, contract_digest(contract))
            or now < contract.registered_unix_ms
            or now - contract.registered_unix_ms > _DAY_MS):
        return _report("invalid_evidence", 0, expected, "missing_or_expired_contract_seal")
    if type(receipts) not in (list, tuple) or len(receipts) > len(expected):
        return _report("invalid_evidence", 0, expected, "invalid_event_count")

    start_process = reopen_process = None
    save_digest = None
    evidence_seen: set[str] = set()
    previous_ms = contract.registered_unix_ms
    for index, signed in enumerate(receipts):
        if not isinstance(signed, SignedJourneyEvent):
            return _report("invalid_evidence", index, expected, "missing_signed_host_event")
        item = signed.event
        mac = sign_journey_event(item, host_key=key).mac_sha256
        if not hmac.compare_digest(mac, signed.mac_sha256):
            return _report("invalid_evidence", index, expected, "tampered_host_event")
        if (item.contract_id != contract.contract_id
                or item.run_id != contract.run_id
                or item.game_id != contract.game_id
                or item.game_version != contract.game_version
                or item.build_sha256 != contract.build_sha256):
            return _report("invalid_evidence", index, expected, "wrong_game_or_build_scope")
        if (item.sequence != index + 1
                or item.evidence_sha256 in evidence_seen):
            return _report("invalid_evidence", index, expected, "replay_or_bad_event_sequence")
        evidence_seen.add(item.evidence_sha256)
        if (not previous_ms <= item.observed_unix_ms <= now
                or item.observed_unix_ms - contract.registered_unix_ms > contract.max_duration_ms
                or now - item.observed_unix_ms > _DAY_MS):
            return _report("invalid_evidence", index, expected, "stale_or_out_of_order_event")
        previous_ms = item.observed_unix_ms
        if (item.kind, item.checkpoint_id) != expected[index]:
            return _report("invalid_evidence", index, expected, "unexpected_journey_step")
        if item.kind == "launch":
            start_process = item.process_instance_id
        elif item.kind == "relaunch":
            if item.process_instance_id == start_process:
                return _report("invalid_evidence", index, expected,
                               "reopen_must_be_a_different_process")
            reopen_process = item.process_instance_id
        elif (reopen_process is None and item.process_instance_id != start_process
              or reopen_process is not None
              and item.process_instance_id != reopen_process):
            return _report("invalid_evidence", index, expected, "process_identity_changed")
        if item.kind == "save":
            save_digest = item.state_sha256
        elif item.kind == "restore" and item.state_sha256 != save_digest:
            return _report("invalid_evidence", index, expected,
                           "reopened_save_state_does_not_match")
    if len(receipts) < len(expected):
        return _report("incomplete", len(receipts), expected, "game_journey_not_finished")
    return _report("eligible_for_review", len(expected), expected)


@dataclass(frozen=True)
class GameReleaseReview:
    verdict: str  # candidate_for_human_review | blocked
    concerns: tuple[str, ...]
    authorized_to_publish: bool = False


def assess_game_release_review(journey: JourneyReport,
                               visual_quality: QualityReport) -> GameReleaseReview:
    """Compose journey and visual checks; neither grants deployment permissions."""
    if not isinstance(journey, JourneyReport):
        raise TypeError("expected independent JourneyReport")
    if not isinstance(visual_quality, QualityReport):
        raise TypeError("expected independent QualityReport")
    concerns = []
    if journey.verdict != "eligible_for_review":
        concerns.append("complete_launch_play_save_reopen_ending_path_not_verified")
    if visual_quality.verdict != "eligible_for_review":
        concerns.append("independent_scene_and_visual_quality_not_verified")
    return GameReleaseReview(
        "candidate_for_human_review" if not concerns else "blocked",
        tuple(concerns),
    )


__all__ = [
    "JourneyContract", "JourneyEvent", "SignedJourneyEvent", "JourneyReport",
    "contract_digest", "sign_journey_event", "evaluate_journey",
    "GameReleaseReview", "assess_game_release_review",
]
