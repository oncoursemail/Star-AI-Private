"""Opt-in, independent feedback for Star's *completed* game input actions.

A successfully released key is not a game outcome. This host-only component
accepts only independently signed game-state transitions from the authenticated
telemetry path. A subsequent progress or loss event is merely OBSERVED after
an action; it never establishes causation, skill mastery, or permission to
claim a win to viewers. Silence means unknown, not failure.

Use the same monotonic clock as the private game-state witness. Never feed this
component raw screenshots, model reports, viewer chat, unsigned engine packets,
or unverifiable client events. The signing secret stays outside model workers.
There is no device, network, OBS, model, or game I/O in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
import time
from typing import Callable

from .game_action_gate import ActionPermit
from .game_actuation_rehearsal import ActuationResult
from .game_state_transition_witness import AttestedGameMoment
from .stream_moment_receipts import validate_receipt_key, verify_game_moment

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SESSION = re.compile(r"[0-9a-f]{32}\Z")


class ActionFeedbackUntrusted(RuntimeError):
    """The signed observation or trusted host clock lost continuity."""


@dataclass(frozen=True)
class ActionFeedback:
    """Anonymous host-only evidence; NO causal or learning authorization."""

    status: str
    ticket: int | None = None
    receipt_sequence: int | None = None
    observed_progress: bool = False
    authorizes_skill_credit: bool = False
    authorizes_broadcast_claim: bool = False


@dataclass(frozen=True)
class _Pending:
    ticket: int
    opened_s: float
    minimum_receipt_sequence: int


class GameActionOutcomeFeedback:
    """Bound one confirmed key-release to later signed engine transitions.

    Only one outstanding action may be evaluated. Every attested moment must
    be in strictly increasing signed sequence and host-clock order. Invalid
    evidence revokes the feedback channel, not the upstream source; the host
    embedding this class MUST stop its control session on a raised exception.

    Receipt verification authenticates the trusted game's signer; it does not
    independently establish that the game server or reader is honest.
    """

    def __init__(
        self, *, game_scope: str, session_id: str, receipt_key: bytes,
        clock: Callable[[], float] = time.monotonic,
        window_s: float = 2.0,
    ) -> None:
        if type(game_scope) is not str or _ID.fullmatch(game_scope) is None:
            raise ValueError("invalid approved game scope")
        if type(session_id) is not str or _SESSION.fullmatch(session_id) is None:
            raise ValueError("invalid signed telemetry session")
        if type(window_s) not in (int, float) or not math.isfinite(window_s):
            raise ValueError("invalid feedback observation window")
        if not 0.05 <= window_s <= 10:
            raise ValueError("window_s must be within 0.05..10 seconds")
        if not callable(clock):
            raise TypeError("trusted monotonic clock required")
        self._game_scope = game_scope
        self._session_id = session_id
        self._key = validate_receipt_key(receipt_key)
        self._clock = clock
        self._window = float(window_s)
        self._lock = RLock()
        self._revoked = False
        self._last_clock: float | None = None
        self._last_receipt_seq = 0
        self._last_event_s: float | None = None
        self._last_ticket = 0
        self._pending: _Pending | None = None
        self._feedback = ActionFeedback("idle")
        self._counts = dict(completed=0, progress=0, losses=0,
                            unresolved=0, revoked=0)

    @property
    def game_scope(self) -> str:
        return self._game_scope

    def _fail(self) -> None:
        self._revoked = True
        self._pending = None
        self._feedback = ActionFeedback("revoked")
        self._counts["revoked"] += 1
        raise ActionFeedbackUntrusted("signed action feedback continuity lost") from None

    def _now(self) -> float:
        try:
            raw = self._clock()
            if type(raw) not in (int, float):
                raise ValueError
            now = float(raw)
            if (not math.isfinite(now) or now < 0 or now > 1e13
                    or (self._last_clock is not None and now < self._last_clock)):
                raise ValueError
        except Exception:
            self._fail()
        self._last_clock = now
        return now

    def _expire(self, now: float) -> None:
        if self._pending is not None and now - self._pending.opened_s >= self._window:
            ticket = self._pending.ticket
            self._pending = None
            self._feedback = ActionFeedback("unverified_timeout", ticket=ticket)
            self._counts["unresolved"] += 1

    def ready(self) -> bool:
        """Only a trusted host may ask before attempting a new action."""
        with self._lock:
            if self._revoked:
                return False
            self._expire(self._now())
            return self._pending is None

    def begin(
        self, permit: ActionPermit, result: ActuationResult, *,
        host_confirmed: bool = False,
    ) -> ActionFeedback:
        """Start AFTER independently confirmed physical key release.

        The trusted action adapter must first claim the ORIGINAL permit. The
        host must never call begin based on a model's assertion of dispatch.
        """
        with self._lock:
            if self._revoked:
                raise ActionFeedbackUntrusted("feedback channel revoked")
            now = self._now()
            self._expire(now)
            if (host_confirmed is not True or type(permit) is not ActionPermit
                    or type(result) is not ActuationResult
                    or not permit.offered or type(permit.ticket) is not int
                    or permit.ticket <= self._last_ticket
                    or result.status != "released_verified"
                    or result.claimed is not True
                    or result.keys_up_verified is not True
                    or self._pending is not None):
                raise ValueError("only a new independently released action is admissible")
            self._last_ticket = permit.ticket
            self._pending = _Pending(
                permit.ticket, now, self._last_receipt_seq,
            )
            self._feedback = ActionFeedback("awaiting_evidence", ticket=permit.ticket)
            return self._feedback

    def observe(self, attested: AttestedGameMoment) -> ActionFeedback:
        """Consume one genuine output from the pinned signed telemetry bridge."""
        with self._lock:
            if self._revoked:
                raise ActionFeedbackUntrusted("feedback channel revoked")
            now = self._now()
            if type(attested) is not AttestedGameMoment:
                self._fail()
            event, receipt = attested.moment, attested.receipt
            try:
                if (event.game_scope != self._game_scope
                        or receipt.session_id != self._session_id
                        or receipt.sequence <= self._last_receipt_seq
                        or event.kind not in {"checkpoint", "win", "loss"}
                        or type(attested.now_s) not in (int, float)
                        or attested.now_s != event.at_s
                        or not math.isfinite(attested.now_s)
                        or event.at_s > now
                        or (self._last_event_s is not None
                            and event.at_s <= self._last_event_s)
                        or not verify_game_moment(
                            event, receipt, session_id=self._session_id, key=self._key
                        )):
                    self._fail()
            except ActionFeedbackUntrusted:
                raise
            except Exception:
                self._fail()
            self._last_receipt_seq = receipt.sequence
            self._last_event_s = event.at_s
            self._expire(now)
            pending = self._pending
            if (pending is not None and
                    receipt.sequence > pending.minimum_receipt_sequence and
                    event.at_s > pending.opened_s and
                    now - pending.opened_s < self._window):
                status = ("observed_loss_after_action" if event.kind == "loss"
                          else "observed_progress_after_action")
                self._feedback = ActionFeedback(
                    status, ticket=pending.ticket,
                    receipt_sequence=receipt.sequence,
                    observed_progress=event.kind != "loss",
                )
                self._counts["completed"] += 1
                self._counts["losses" if event.kind == "loss" else "progress"] += 1
                self._pending = None
            return self._feedback

    def snapshot(self) -> ActionFeedback:
        """Safe status; an elapsed window is NEVER scored as a failed skill."""
        with self._lock:
            if self._revoked:
                return ActionFeedback("revoked")
            self._expire(self._now())
            return self._feedback

    def revoke(self) -> None:
        """Drop pending credit permanently after any telemetry/input failure."""
        with self._lock:
            self._revoked = True
            self._pending = None
            self._feedback = ActionFeedback("revoked")

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._counts, "pending": self._pending is not None,
                    "active": not self._revoked}


__all__ = ["GameActionOutcomeFeedback", "ActionFeedback",
           "ActionFeedbackUntrusted"]
