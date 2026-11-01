"""Strict one-step observation/action protocol for owner-authorized game rehearsals.

Opt-in, pure in-memory, no game inputs, network, model, Studio, TTS or OBS.
An independently trusted game adapter observes the real game and owns controls;
this module only proposes a movement and checks the subsequent *host* frame.
`trusted_host` and `host_dispatched` are caller assertions, NOT authentication.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .game_navigation import GameFrame, NavigationAdvice, NavigationBelief

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


@dataclass(frozen=True)
class PracticeScope:
    """A caller-installed scope; the external host must authenticate the owner."""
    game: str
    session: str
    width: int
    height: int
    mode: str = "play"
    sandbox_approved: bool = False
    max_actions: int = 64
    max_frame_age_ms: int = 1_000
    ticket_ttl_ms: int = 500
    action_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        if any(type(s) is not str or not _ID.fullmatch(s)
               for s in (self.game, self.session)):
            raise ValueError("Invalid game/session identity")
        if (type(self.width) is not int or type(self.height) is not int
                or not 1 <= self.width <= 64 or not 1 <= self.height <= 64
                or self.width * self.height > 4096):
            raise ValueError("Invalid map dimensions")
        if self.mode not in ("play", "practice") or type(self.sandbox_approved) is not bool:
            raise ValueError("Invalid play/practice mode or approval")
        if self.mode == "practice" and self.sandbox_approved is not True:
            raise PermissionError("Practice requires separate owner-approved sandbox")
        for val, lo, hi in ((self.max_actions, 1, 512),
                            (self.max_frame_age_ms, 1, 10_000),
                            (self.ticket_ttl_ms, 1, 5_000),
                            (self.action_timeout_ms, 1, 30_000)):
            if type(val) is not int or not lo <= val <= hi:
                raise ValueError("Invalid bounded timing/action budget")


@dataclass(frozen=True)
class MotionTicket:
    """Advisory offer. A monotonically increasing ticket is NOT an auth token."""
    ticket: int
    observation_seq: int
    action: str
    destination: tuple[int, int]
    exploratory: bool
    expires_ms: int
    reason: str


@dataclass(frozen=True)
class ObservationReceipt:
    movement_verified: bool
    goal_reached: bool
    stopped_reason: str | None
    accepted_seq: int


class ClosedLoopPilot:
    """Never issue two actions without a fresh authoritative host observation.

    Offer -> separately authorized host dispatches -> ACK -> new observed frame.
    If an action missed its target, exceeds deadline, or player moves without
    authorization, the pilot *latches stopped*. Nothing auto-resets it. The host
    must independently verify that dispatch was allowed, not trust this class.
    """

    def __init__(self, scope: PracticeScope) -> None:
        if type(scope) is not PracticeScope:
            raise TypeError("Expected PracticeScope")
        self.scope = scope
        self.navigation = NavigationBelief()
        self._clock = -1
        self._observed_at = -1
        self._seq = 0
        self._player: tuple[int, int] | None = None
        self._pending: MotionTicket | None = None
        self._dispatched = False
        self._deadline = -1
        self._ticket_counter = 0
        self._dispatched_count = 0
        self._verified_count = 0
        self._halt_reason: str | None = None

    def _time(self, now_ms: int) -> None:
        if type(now_ms) is not int or not 0 <= now_ms <= 10**12:
            raise ValueError("Expected bounded monotonic timestamp in ms")
        if now_ms < self._clock:
            raise ValueError("Out-of-order monotonic time")
        self._clock = now_ms

    def stop(self, reason: str = "owner_stop") -> None:
        if reason not in ("owner_stop", "host_rejected", "adapter_disconnected"):
            raise ValueError("Unsupported stop reason")
        if self._halt_reason is None:
            self._halt_reason = reason
        self._pending = None
        self._dispatched = False

    @property
    def stopped_reason(self) -> str | None:
        return self._halt_reason

    def observe(self, frame: GameFrame, *, observed_ms: int,
                trusted_host: bool = False) -> ObservationReceipt:
        """Consume a host-observed frame and verify the effect of ONE action.

        Unauthorized callers must not be allowed to flip `trusted_host`. No
        action-driving callbacks are accepted in this module.
        """
        if trusted_host is not True:
            raise PermissionError("Only the trusted host may submit game observations")
        if type(frame) is not GameFrame:
            raise TypeError("Expected a validated host GameFrame")
        if (frame.game, frame.session, frame.width, frame.height) != (
                self.scope.game, self.scope.session, self.scope.width, self.scope.height):
            raise ValueError("Observation does not match approved scope")
        if self._halt_reason is not None:
            raise RuntimeError("Stopped pilot cannot resume within the same session")
        if frame.seq <= self._seq:
            raise ValueError("Stale/replayed observation")
        self._time(observed_ms)
        moved = False
        if self._pending is not None:
            if self._dispatched:
                if observed_ms > self._deadline:
                    self._halt_reason = "action_timeout"
                elif frame.player != self._pending.destination:
                    self._halt_reason = "movement_mismatch"
                else:
                    moved = True
                    self._verified_count += 1
            elif self._player != frame.player:
                self._halt_reason = "uncommanded_move"
            self._pending = None
            self._dispatched = False
        elif self._player is not None and frame.player != self._player:
            self._halt_reason = "uncommanded_move"
        # Even a mismatch is recorded as new host evidence; it does not allow
        # automatic recovery or further action in this session.
        self.navigation.observe(frame, trusted_host=True)
        self._seq = frame.seq
        self._player = frame.player
        self._observed_at = observed_ms
        if (self._halt_reason is None and any(
                t.cell == frame.player and t.kind == "goal" for t in frame.visible)):
            self._halt_reason = "goal_reached"
        return ObservationReceipt(moved, self._halt_reason == "goal_reached",
                                  self._halt_reason, frame.seq)

    def offer(self, *, now_ms: int) -> MotionTicket | None:
        """Make one bounded, non-executable suggestion from fresh host evidence."""
        self._time(now_ms)
        if self._halt_reason is not None or self._pending is not None or self._seq == 0:
            return None
        if now_ms - self._observed_at > self.scope.max_frame_age_ms:
            return None
        if self._dispatched_count >= self.scope.max_actions:
            self._halt_reason = "action_budget_exhausted"
            return None
        advice: NavigationAdvice = self.navigation.advise(
            mode=self.scope.mode, sandbox_approved=self.scope.sandbox_approved)
        if advice.action is None or advice.destination is None:
            return None
        assert self._player is not None
        dest = advice.destination
        # Defensive contract check: only one cardinal tile at a time.
        if abs(dest[0] - self._player[0]) + abs(dest[1] - self._player[1]) != 1:
            self._halt_reason = "invalid_planner_action"
            return None
        self._ticket_counter += 1
        self._pending = MotionTicket(self._ticket_counter, self._seq,
                                     advice.action, dest, advice.exploratory,
                                     now_ms + self.scope.ticket_ttl_ms,
                                     advice.reason)
        return self._pending

    def acknowledge_dispatched(self, ticket: int, *, now_ms: int,
                               host_dispatched: bool = False) -> bool:
        """Host says a permitted game input actually fired. Does NOT fire it."""
        if host_dispatched is not True:
            raise PermissionError("Only the authorized actuator may confirm dispatch")
        self._time(now_ms)
        pending = self._pending
        if (self._halt_reason is not None or pending is None or self._dispatched
                or type(ticket) is not int or ticket != pending.ticket):
            return False
        if now_ms > pending.expires_ms:
            self._pending = None
            return False
        self._dispatched = True
        self._dispatched_count += 1
        self._deadline = now_ms + self.scope.action_timeout_ms
        return True

    def summary(self) -> dict[str, int | bool | str | None]:
        """Metadata only, no video, speech, input records or private chat text."""
        return {"frames": self._seq, "actions_dispatched": self._dispatched_count,
                "movements_verified": self._verified_count,
                "awaiting_effect": self._pending is not None and self._dispatched,
                "stopped_reason": self._halt_reason}
