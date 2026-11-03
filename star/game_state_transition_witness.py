"""Fail-closed, opt-in state-transition witness for *owner-controlled* games.

This is a host-side adapter, not an LLM tool and not an arbitrary-game reader.
Only an isolated game/Studio test host with authoritative, read-only gameplay
telemetry may call ingest(). The host MUST prevent prompts, chat, model tools,
and game client scripts from forging its input or reading the signing secret.

A game event is signed only after two ordered live-state samples corroborate a
real transition. A screenshot, heuristic description, or model claim is NEVER
accepted as a game fact. No device, stream, GPU, network or game I/O occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
import time
from typing import Callable

from .stream_episode_journal import GameMoment
from .stream_moment_receipts import (
    SignedGameMoment, sign_game_moment, validate_receipt_key,
)

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_PHASES = frozenset({"menu", "playing", "won", "lost"})
_MAX_COUNTER = 10**12
_MAX_EVENTS = 4096


class GameTelemetryError(RuntimeError):
    """State continuity was lost; re-authorize a new observing session."""


@dataclass(frozen=True)
class GameStateSample:
    """Restricted, host-read game facts; no freeform captions or player data.

    frame increments as the *game world runs*, not as the LLM thinks.
    round_id increments at every new round. checkpoint is nondecreasing within
    a round and resets only on a new round. phase reflects authoritative state.
    """

    frame: int
    round_id: int
    phase: str
    checkpoint: int

    def __post_init__(self) -> None:
        if (type(self.frame) is not int or not 0 <= self.frame <= _MAX_COUNTER
                or type(self.round_id) is not int
                or not 1 <= self.round_id <= _MAX_COUNTER
                or type(self.checkpoint) is not int
                or not 0 <= self.checkpoint <= _MAX_COUNTER
                or type(self.phase) is not str or self.phase not in _PHASES):
            raise ValueError("invalid authoritative game-state sample")


@dataclass(frozen=True)
class AttestedGameMoment:
    """A host-authenticated claim; does not prove the game source is honest."""

    moment: GameMoment
    receipt: SignedGameMoment
    now_s: float


@dataclass(frozen=True)
class _Candidate:
    kind: str
    round_id: int
    checkpoint: int


class VerifiedGameStateObserver:
    """Derive signed moments from corroborated source-owned state transitions.

    Disabled by default, scoped to one game and one journal session. A loss of
    frame/time continuity, round ordering, checkpoint consistency or any
    invalid sample latches the observer OFF. No auto-reconnect or restart.
    A host restarts it only after establishing a new authorized journal session.

    The game must expose trusted server/engine-side telemetry. This cannot
    independently authenticate an arbitrary third-party game or client.
    """

    def __init__(
        self,
        *,
        game_scope: str,
        session_id: str,
        receipt_key: bytes,
        clock: Callable[[], float] = time.monotonic,
        max_gap_s: float = 1.0,
        max_frame_step: int = 240,
    ) -> None:
        if type(game_scope) is not str or _NAME.fullmatch(game_scope) is None:
            raise ValueError("invalid game scope")
        if type(session_id) is not str or _SESSION.fullmatch(session_id) is None:
            raise ValueError("invalid journal session")
        if type(max_gap_s) not in (int, float) or not math.isfinite(max_gap_s):
            raise ValueError("invalid sample gap")
        if not 0.01 <= max_gap_s <= 10:
            raise ValueError("sample gap must be 0.01..10 seconds")
        if type(max_frame_step) is not int or not 1 <= max_frame_step <= 10000:
            raise ValueError("max frame step must be 1..10000")
        if not callable(clock):
            raise TypeError("trusted monotonic clock required")
        self._key = validate_receipt_key(receipt_key)
        self._scope = game_scope
        self._session = session_id
        self._clock = clock
        self._max_gap = float(max_gap_s)
        self._max_frame_step = max_frame_step
        self._lock = RLock()
        self._enabled = False
        self._revoked = False
        self._previous: GameStateSample | None = None
        self._previous_time: float | None = None
        self._pending: _Candidate | None = None
        self._sequence = 0

    @property
    def game_scope(self) -> str:
        """Immutable approved game identity for host-side composition."""
        return self._scope

    @property
    def active(self) -> bool:
        with self._lock:
            return self._enabled and not self._revoked

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for telemetry witness")
        with self._lock:
            if self._enabled or self._revoked:
                raise RuntimeError("already enabled or revoked; create a new session")
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._revoked = True
            self._previous = None
            self._previous_time = None
            self._pending = None

    def _fail(self) -> None:
        self.disable()
        raise GameTelemetryError("game-state evidence continuity lost")

    @staticmethod
    def _transition(a: GameStateSample, b: GameStateSample) -> _Candidate | None:
        if a.round_id != b.round_id or a.phase != "playing":
            return None
        if b.phase == "won":
            return _Candidate("win", b.round_id, b.checkpoint)
        if b.phase == "lost":
            return _Candidate("loss", b.round_id, b.checkpoint)
        if b.phase == "playing" and b.checkpoint > a.checkpoint:
            return _Candidate("checkpoint", b.round_id, b.checkpoint)
        return None

    @staticmethod
    def _confirmed(candidate: _Candidate, sample: GameStateSample) -> bool:
        if sample.round_id != candidate.round_id:
            return False
        if candidate.kind == "checkpoint":
            return sample.phase == "playing" and sample.checkpoint == candidate.checkpoint
        return sample.phase == ("won" if candidate.kind == "win" else "lost")

    def ingest(self, sample: GameStateSample) -> AttestedGameMoment | None:
        """Host-only: sample ordered engine state; sign only confirmed changes.

        The clock is independently sampled here, not supplied by model input.
        One initial playing sample establishes a baseline; a one-frame claim
        can never create a remembered win. No public stream action follows.
        """
        with self._lock:
            if not self._enabled or self._revoked:
                raise GameTelemetryError("game-state observer not enabled")
            if type(sample) is not GameStateSample:
                self._fail()
            try:
                now = self._clock()
            except Exception:
                self._fail()
            if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
                self._fail()
            now = float(now)
            prev, prev_time = self._previous, self._previous_time
            if prev is None:
                if sample.phase != "playing":
                    self._fail()  # No inferred victory from a terminal initial state.
                self._previous, self._previous_time = sample, now
                return None
            assert prev_time is not None
            if (sample.frame <= prev.frame
                    or sample.frame - prev.frame > self._max_frame_step
                    or now <= prev_time
                    or now - prev_time > self._max_gap
                    or sample.round_id < prev.round_id
                    or sample.round_id > prev.round_id + 1
                    or (sample.round_id == prev.round_id and
                        (sample.checkpoint < prev.checkpoint
                         or (prev.phase in {"won", "lost"} and
                             sample.phase != prev.phase)))
                    or (sample.round_id != prev.round_id and sample.phase != "playing")):
                self._fail()
            pending = self._pending
            self._previous, self._previous_time = sample, now
            self._pending = self._transition(prev, sample)
            if pending is None or not self._confirmed(pending, sample):
                return None
            self._pending = None
            if self._sequence >= _MAX_EVENTS:
                self._fail()
            self._sequence += 1
            suffix = (
                f"r{pending.round_id}.p{pending.checkpoint}"
                if pending.kind == "checkpoint" else f"r{pending.round_id}"
            )
            moment = GameMoment(
                moment_id=f"{pending.kind}.{suffix}",
                game_scope=self._scope,
                kind=pending.kind,
                at_s=now,
                stage_id=(f"cp{pending.checkpoint}" if pending.kind == "checkpoint" else ""),
            )
            proof = sign_game_moment(
                moment, session_id=self._session, sequence=self._sequence,
                key=self._key,
            )
            return AttestedGameMoment(moment, proof, now)


__all__ = [
    "GameStateSample", "AttestedGameMoment", "GameTelemetryError",
    "VerifiedGameStateObserver",
]
