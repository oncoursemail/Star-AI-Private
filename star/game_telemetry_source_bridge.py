"""Authenticated read-only telemetry boundary for authorized owned/test games.

This is an in-process receiver of *already signed* bounded messages, not a
network listener, engine plugin, model tool, gameplay controller or OBS output.
The independent game/server test host must keep SOURCE_KEY unavailable to Star,
chat, client scripts, plugins, and the process that performs language inference.

A receipt proves that a pinned source signed a telemetry state, not that an
untrusted client or game server is honest. Use only owner-controlled game
servers and Studio test harnesses with authoritative state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import hmac
import json
import re
from threading import RLock

from .game_state_transition_witness import (
    AttestedGameMoment, GameStateSample, VerifiedGameStateObserver,
)
from .stream_episode_journal import StreamEpisodeJournal
from .stream_moment_receipts import validate_receipt_key

_SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SESSION_RE = re.compile(r"[0-9a-f]{32}\Z")
_MAC_RE = re.compile(r"[0-9a-f]{64}\Z")
_KEYS = frozenset({
    "v", "source", "session", "seq", "frame", "round",
    "phase", "checkpoint", "mac",
})
_MAX_PACKET_BYTES = 512
_MAX_FRAMES = 4096


class GameTelemetryTransportError(RuntimeError):
    """Telemetry session was revoked. Details are deliberately hidden."""


@dataclass(frozen=True)
class SignedEngineFrame:
    """Restrained game facts with a per-frame source MAC; no arbitrary prose."""

    source: str
    session: str
    seq: int
    frame: int
    round: int
    phase: str
    checkpoint: int
    mac: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.source) is not str or _SOURCE_RE.fullmatch(self.source) is None:
            raise ValueError("invalid telemetry source")
        if type(self.session) is not str or _SESSION_RE.fullmatch(self.session) is None:
            raise ValueError("invalid telemetry session")
        if type(self.seq) is not int or not 1 <= self.seq <= _MAX_FRAMES:
            raise ValueError("invalid telemetry sequence")
        if type(self.mac) is not str or _MAC_RE.fullmatch(self.mac) is None:
            raise ValueError("invalid telemetry authentication tag")
        GameStateSample(self.frame, self.round, self.phase, self.checkpoint)

    @property
    def sample(self) -> GameStateSample:
        return GameStateSample(self.frame, self.round, self.phase, self.checkpoint)


def telemetry_mac_payload(frame: SignedEngineFrame) -> bytes:
    """Public canonical v1 format for a separately trusted engine-side signer.

    NOTE: This function does NOT sign, hold a credential, or grant authorization.
    Source hosts must authenticate the game process/round independently.
    """
    if type(frame) is not SignedEngineFrame:
        raise TypeError("signed engine frame required")
    return json.dumps(
        ("star.game.engine-telemetry.v1", frame.source, frame.session,
         frame.seq, frame.frame, frame.round, frame.phase, frame.checkpoint),
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate telemetry field")
        result[key] = value
    return result


def parse_telemetry_packet(packet: bytes) -> SignedEngineFrame:
    """Strict bounded wire parser. No JSON field may be omitted or repeated.

    Use on an isolated IPC channel after independently pinning the peer to the
    owner-approved game/server. A valid MAC never authenticates the IPC peer.
    """
    if type(packet) is not bytes or not 1 <= len(packet) <= _MAX_PACKET_BYTES:
        raise ValueError("invalid packet size or type")
    try:
        fields = json.loads(
            packet.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("invalid telemetry JSON") from exc
    if type(fields) is not dict or fields.keys() != _KEYS or fields["v"] != 1 or type(fields["v"]) is not int:
        raise ValueError("invalid telemetry schema or version")
    return SignedEngineFrame(
        source=fields["source"], session=fields["session"],
        seq=fields["seq"], frame=fields["frame"], round=fields["round"],
        phase=fields["phase"], checkpoint=fields["checkpoint"],
        mac=fields["mac"],
    )


class AuthenticatedGameTelemetryBridge:
    """Single owner-approved signed-source -> state witness -> private journal.

    The source key must be different from the moment-journal signing key.
    Neither belongs in an LLM worker, general-purpose API, or game client.
    The source and session are pinned, and every source frame must be exactly
    the next sequence. Any bad frame, gap, replay, MAC, witness, or journal
    error irreversibly disables both downstream objects. No auto-reconnect.
    """

    def __init__(
        self, *, source_id: str, session_id: str, source_key: bytes,
        observer: VerifiedGameStateObserver, journal: StreamEpisodeJournal,
    ) -> None:
        if type(source_id) is not str or _SOURCE_RE.fullmatch(source_id) is None:
            raise ValueError("invalid approved source ID")
        if type(session_id) is not str or _SESSION_RE.fullmatch(session_id) is None:
            raise ValueError("invalid pinned journal session")
        if not isinstance(observer, VerifiedGameStateObserver):
            raise TypeError("verified game observer required")
        if not isinstance(journal, StreamEpisodeJournal):
            raise TypeError("private stream journal required")
        if journal.session_id != session_id:
            raise ValueError("journal session does not match pinned source session")
        self._source_id = source_id
        self._session_id = session_id
        self._source_key = validate_receipt_key(source_key)
        self._observer = observer
        self._journal = journal
        self._lock = RLock()
        self._enabled = False
        self._revoked = False
        self._sequence = 0
        self._events = 0

    @property
    def game_scope(self) -> str:
        """Read-only identity of the trusted state witness."""
        return self._observer.game_scope

    @property
    def active(self) -> bool:
        with self._lock:
            return self._enabled and not self._revoked

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for game telemetry")
        with self._lock:
            if self._enabled or self._revoked or not self._observer.active or self._journal.session_id != self._session_id:
                raise GameTelemetryTransportError("telemetry session cannot be enabled")
            self._enabled = True

    def _revoke(self) -> None:
        self._enabled = False
        self._revoked = True
        self._observer.disable()
        # Memory suggestions from this session must never survive source
        # ambiguity; fail closed even if the downstream journal is still live.
        self._journal.disable()

    def disable(self) -> None:
        with self._lock:
            self._revoke()

    def accept(self, packet: bytes) -> AttestedGameMoment | None:
        """Host-only byte ingestion; models/viewers cannot call this method."""
        with self._lock:
            if not self._enabled or self._revoked:
                raise GameTelemetryTransportError("telemetry session is not active")
            try:
                frame = parse_telemetry_packet(packet)
                if (frame.source != self._source_id
                        or frame.session != self._session_id
                        or frame.seq != self._sequence + 1
                        or not self._observer.active
                        or self._journal.session_id != self._session_id):
                    raise ValueError("source, session or observation continuity changed")
                expected = hmac.new(
                    self._source_key, telemetry_mac_payload(frame), sha256,
                ).hexdigest()
                if not hmac.compare_digest(expected, frame.mac):
                    raise ValueError("source authentication failed")
                event = self._observer.ingest(frame.sample)
                if event is not None:
                    if not self._journal.record(
                        event.moment, now_s=event.now_s,
                        host_observed=True, receipt=event.receipt,
                    ):
                        raise ValueError("protected journal rejected event")
                    self._events += 1
                self._sequence = frame.seq
                return event
            except Exception:
                self._revoke()
                raise GameTelemetryTransportError(
                    "engine telemetry continuity lost: session revoked"
                ) from None

    def metrics(self) -> dict[str, int | bool]:
        """Non-sensitive counters: never include the source or either MAC/key."""
        with self._lock:
            return {
                "active": self._enabled and not self._revoked,
                "accepted_frames": self._sequence,
                "recorded_events": self._events,
            }


__all__ = [
    "SignedEngineFrame", "GameTelemetryTransportError",
    "AuthenticatedGameTelemetryBridge", "telemetry_mac_payload",
    "parse_telemetry_packet",
]
