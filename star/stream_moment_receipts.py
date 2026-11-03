"""Optional session-bound HMAC receipts for Star's game-moment journal.

The signer belongs ONLY in an independently trusted game-state host, never in
viewer chat, model prompts, tools exposed to a model, or a livestream client.
HMAC authenticates the host's claim; it cannot prove the game event was true.
No file, network, GPU, model, OBS, or device access happens here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import hmac
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .stream_episode_journal import GameMoment

_SESSION_RE = re.compile(r"[0-9a-f]{32}\Z")
_MAC_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SEQUENCE = (1 << 63) - 1


def validate_receipt_key(key: bytes) -> bytes:
    """Return a stable immutable key without logging or exposing its value."""
    if type(key) is not bytes or not 32 <= len(key) <= 4096:
        raise ValueError("receipt key must be 32..4096 private bytes")
    return key


@dataclass(frozen=True)
class SignedGameMoment:
    """Bound receipt. MAC excluded from repr and all journal telemetry."""
    session_id: str
    sequence: int
    mac: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.session_id) is not str or not _SESSION_RE.fullmatch(self.session_id):
            raise ValueError("invalid receipt session")
        if type(self.sequence) is not int or not 1 <= self.sequence <= _MAX_SEQUENCE:
            raise ValueError("invalid receipt sequence")
        if type(self.mac) is not str or not _MAC_RE.fullmatch(self.mac):
            raise ValueError("invalid receipt tag")


def _message(moment: GameMoment, session_id: str, sequence: int) -> bytes:
    # Late local import avoids a journal/receipt initialization cycle.
    from .stream_episode_journal import GameMoment

    if not isinstance(moment, GameMoment):
        raise TypeError("only structured GameMoment facts can be signed")
    if type(session_id) is not str or not _SESSION_RE.fullmatch(session_id):
        raise ValueError("invalid receipt session")
    if type(sequence) is not int or not 1 <= sequence <= _MAX_SEQUENCE:
        raise ValueError("invalid receipt sequence")
    # Canonical JSON array removes delimiter ambiguity. Encode the timestamp
    # exactly as its normalized binary64 value, even when a caller uses int.
    fields = (
        "star.game-moment.v1", session_id, sequence, moment.moment_id,
        moment.game_scope, moment.kind, float(moment.at_s).hex(), moment.stage_id,
    )
    return json.dumps(fields, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def sign_game_moment(
    moment: GameMoment, *, session_id: str, sequence: int, key: bytes,
) -> SignedGameMoment:
    """Trusted-host operation: sign a witnessed structured game-state event."""
    secret = validate_receipt_key(key)
    payload = _message(moment, session_id, sequence)
    return SignedGameMoment(session_id, sequence, hmac.new(secret, payload, sha256).hexdigest())


def verify_game_moment(
    moment: GameMoment, proof: SignedGameMoment, *, session_id: str, key: bytes,
) -> bool:
    """Return False on a forged, stale-session or mismatched receipt."""
    secret = validate_receipt_key(key)
    if not isinstance(proof, SignedGameMoment) or proof.session_id != session_id:
        return False
    expected = hmac.new(secret, _message(moment, session_id, proof.sequence), sha256).hexdigest()
    return hmac.compare_digest(expected, proof.mac)


__all__ = ["SignedGameMoment", "sign_game_moment", "verify_game_moment"]
