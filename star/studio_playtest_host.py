"""Trusted-host adapter connecting STAR's action gate to private Studio playtests.

Unlike the advisory GameActionGate, this adapter can request an actual key
pulse THROUGH a trusted host-provided Studio port. It deliberately does not
connect to Roblox or the OS by itself: the host implements Studio MCP
user_keyboard_input for the discovered studio_id and checks session identity.
No live Roblox clients, public multiplayer, arbitrary tool commands, user
text, external processes, or synthetic claims of learning are supported.

The host MUST have its own hard key-up watchdog independent of Python sleep
and an authorized, authenticated way to produce StudioSnapshot. Neither the
model nor game contents may create snapshots, mappings, or input ports.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from threading import RLock
import time
from typing import Callable, Protocol, Sequence

from .game_action_gate import (
    ActionPermit, GameActionGate, GameActionHint, GameFrame, GameScope,
)
from .stream_budget import StreamTelemetry

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_KEYS = frozenset({
    "W", "A", "S", "D", "Q", "E", "F", "R", "SPACE", "LEFT",
    "RIGHT", "UP", "DOWN", "SHIFT",
})


@dataclass(frozen=True)
class StudioBinding:
    """Owner-selected action -> innocuous key; never supplied by the model."""
    action_id: str
    key: str

    def __post_init__(self) -> None:
        if type(self.action_id) is not str or not _ID.fullmatch(self.action_id):
            raise ValueError("invalid bounded symbolic action")
        if type(self.key) is not str or self.key not in _KEYS:
            raise ValueError("key not in restricted Studio-playtest allowlist")


@dataclass(frozen=True)
class StudioSnapshot:
    """Host-attested, current Studio state. This is NOT a model output."""
    studio_id: str
    scope: GameScope
    playtesting: bool
    focused: bool
    private_local_test: bool
    owner_authorized: bool

    def __post_init__(self) -> None:
        if type(self.studio_id) is not str or not _ID.fullmatch(self.studio_id):
            raise ValueError("invalid Studio ID")
        if not isinstance(self.scope, GameScope):
            raise TypeError("expected GameScope")
        for field in ("playtesting", "focused", "private_local_test",
                      "owner_authorized"):
            if type(getattr(self, field)) is not bool:
                raise ValueError("host snapshot fields must be explicit booleans")


class StudioInputPort(Protocol):
    """Trusted Studio MCP host facade. Must own connection and key-up watchdog."""
    def snapshot(self, studio_id: str) -> StudioSnapshot: ...
    def key_down(self, studio_id: str, key: str) -> None: ...
    def key_up(self, studio_id: str, key: str) -> None: ...


@dataclass(frozen=True)
class DispatchReport:
    sent: bool
    reason: str
    input_released: bool
    gameplay_success_verified: bool = False  # NEVER set from input dispatch


@dataclass(frozen=True)
class DeliveredAction:
    """A delivered *input*, not a verified objective or gameplay outcome.

    Available only from claim_delivery() with an exact in-process report.
    This value object is not independently an authorization capability.
    """
    studio_id: str
    scope: GameScope
    action_id: str
    frame_sequence: int
    before_sha256: str
    before_ms: float
    released_ms: float
    ticket: int


class StudioPlaytestHost:
    """Serial, host-only dispatch for an explicitly opted-in private playtest.

    Model proposals must first pass GameActionGate.request(), with fresh host
    evidence and telemetry. Only its SAME in-process ActionPermit object can
    be dispatched; a copied/dict permit never permits an actual key press.
    """

    def __init__(self, *, gate: GameActionGate | None = None,
                 clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self._gate = gate if gate is not None else GameActionGate()
        if not isinstance(self._gate, GameActionGate):
            raise TypeError("gate must be GameActionGate")
        self._clock = clock_ms
        self._sleep = sleeper
        self._lock = RLock()
        self._studio_id: str | None = None
        self._scope: GameScope | None = None
        self._bindings: dict[str, str] = {}
        self._held: tuple[int, str] | None = None
        self._unclaimed: ActionPermit | None = None
        self._unclaimed_frame: GameFrame | None = None
        self._last_report: DispatchReport | None = None
        self._last_delivery: DeliveredAction | None = None
        self._counts = dict(sent=0, denied=0, input_failed=0,
                            keyup_failed=0, recovered=0, deliveries_claimed=0,
                            deliveries_overwritten=0)

    def start(self, *, studio_id: str, scope: GameScope,
              bindings: Sequence[StudioBinding], owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner opt-in required")
        if type(studio_id) is not str or not _ID.fullmatch(studio_id):
            raise ValueError("invalid Studio ID")
        if type(bindings) not in (list, tuple) or not 1 <= len(bindings) <= 16:
            raise ValueError("expected 1..16 curated Studio action bindings")
        if any(not isinstance(item, StudioBinding) for item in bindings):
            raise TypeError("bindings must be StudioBinding instances")
        mapping = {item.action_id: item.key for item in bindings}
        if len(mapping) != len(bindings):
            raise ValueError("duplicate curated action IDs")
        with self._lock:
            if self._held is not None:
                raise RuntimeError("previous key-up not confirmed; recover first")
            self._gate.start(scope, tuple(mapping), owner_approved=True)
            self._studio_id = studio_id
            self._scope = scope
            self._bindings = mapping
            self._unclaimed = None
            self._unclaimed_frame = None
            self._last_report = None
            self._last_delivery = None

    def request(self, frame: GameFrame, hint: GameActionHint, *,
                now_ms: float, host_verified: bool,
                telemetry: StreamTelemetry | None) -> ActionPermit:
        """Advisory proposal; no physical input until dispatch()."""
        with self._lock:
            permit = self._gate.request(frame, hint, now_ms=now_ms,
                                        host_verified=host_verified,
                                        telemetry=telemetry)
            if permit.offered:
                self._unclaimed = permit
                self._unclaimed_frame = frame
            return permit

    def _valid_snapshot(self, snapshot: object) -> bool:
        return (isinstance(snapshot, StudioSnapshot)
                and snapshot.studio_id == self._studio_id
                and snapshot.scope == self._scope
                and snapshot.playtesting and snapshot.focused
                and snapshot.private_local_test and snapshot.owner_authorized)

    def dispatch(self, permit: ActionPermit, *, port: StudioInputPort) -> DispatchReport:
        """Synchronous bounded pulse. A failed key-up QUARANTINES future actions."""
        with self._lock:
            if (self._studio_id is None or self._scope is None
                    or self._held is not None or not isinstance(permit, ActionPermit)
                    or not permit.offered or permit.ticket is None
                    or permit.action_id not in self._bindings
                    or permit.hold_ms is None or not 1 <= permit.hold_ms <= 180):
                self._counts["denied"] += 1
                return DispatchReport(False, "missing_or_untrusted_permit", True)
            try:
                snapshot = port.snapshot(self._studio_id)
            except Exception:
                self._counts["denied"] += 1
                return DispatchReport(False, "studio_preflight_unavailable", True)
            if not self._valid_snapshot(snapshot):
                self._counts["denied"] += 1
                return DispatchReport(False, "not_authorized_private_studio_playtest", True)
            now = self._clock()
            if not self._gate.claim_offered(
                    permit, now_ms=now, host_focus_and_permission=True):
                self._counts["denied"] += 1
                return DispatchReport(False, "ticket_stale_or_not_host_issued", True)
            before = self._unclaimed_frame
            self._unclaimed = None
            self._unclaimed_frame = None
            ticket, key = permit.ticket, self._bindings[permit.action_id]
            self._held = (ticket, key)
            sent = False
            problem = "input_failed"
            released = False
            try:
                # Second preflight detects focus/session loss across claim().
                if not self._valid_snapshot(port.snapshot(self._studio_id)):
                    problem = "playtest_focus_changed"
                else:
                    port.key_down(self._studio_id, key)
                    self._sleep(permit.hold_ms / 1000)
                    sent = True
            except Exception:
                problem = "studio_input_port_failed"
            finally:
                # Always attempt key-up, even if down/hold failed. Never auto-
                # clear quarantine when the host cannot confirm key-up.
                try:
                    port.key_up(self._studio_id, key)
                    released = self._gate.release(
                        ticket, now_ms=self._clock(),
                        host_confirmed_released=True)
                except Exception:
                    released = False
                if released:
                    self._held = None
                else:
                    self._counts["keyup_failed"] += 1
            if not released:
                self._counts["input_failed"] += 1
                return DispatchReport(False, "key_up_not_confirmed_quarantined", False)
            if not sent:
                self._counts["input_failed"] += 1
                return DispatchReport(False, problem, True)
            self._counts["sent"] += 1
            report = DispatchReport(
                True, "studio_key_pulse_dispatched_not_game_success", True)
            # Nothing reaches the verifier until a REAL input was sent AND
            # independently confirmed released. A later delivery supersedes an
            # unclaimed one; at most one attempt can be linked at a time.
            assert before is not None and self._studio_id is not None
            if self._last_delivery is not None:
                self._counts["deliveries_overwritten"] += 1
            self._last_report = report
            self._last_delivery = DeliveredAction(
                self._studio_id, before.scope, permit.action_id,
                before.sequence, before.evidence_sha256,
                before.captured_ms, self._clock(), ticket)
            return report

    def inspect_delivery(self, report: DispatchReport) -> DeliveredAction | None:
        """Trusted host preview to calculate the post-transition digest.

        A mere preview NEVER registers success, consumes the claim or
        authorizes an input; only exact original reports can be inspected.
        """
        with self._lock:
            if (not isinstance(report, DispatchReport)
                    or self._last_report is not report):
                return None
            return self._last_delivery

    def claim_delivery(self, report: DispatchReport) -> DeliveredAction | None:
        """Consume exact, currently unclaimed host-issued dispatch once.

        Model-created or copied DispatchReport objects never work. This
        DOES NOT authenticate a success/failure claim or publish to a stream.
        """
        with self._lock:
            if (not isinstance(report, DispatchReport)
                    or self._last_report is not report
                    or self._last_delivery is None):
                return None
            result = self._last_delivery
            self._last_report = None
            self._last_delivery = None
            self._counts["deliveries_claimed"] += 1
            return result

    def recover_key_up(self, *, port: StudioInputPort) -> bool:
        """Operator/host attempts an unconditional cleanup after input failure."""
        with self._lock:
            if self._held is None or self._studio_id is None:
                return False
            ticket, key = self._held
            try:
                port.key_up(self._studio_id, key)
                ok = self._gate.release(ticket, now_ms=self._clock(),
                                        host_confirmed_released=True)
            except Exception:
                return False
            if ok:
                self._held = None
                self._counts["recovered"] += 1
            return ok

    def revoke(self, *, port: StudioInputPort | None = None) -> bool:
        """Stop accepting actions; return False if a stuck key remains."""
        with self._lock:
            self._gate.revoke()
            # An unclaimed advisory never issued physical input in this host.
            # Confirm that no key was pressed before clearing its gate slot.
            if self._held is None and self._unclaimed is not None:
                self._gate.release(self._unclaimed.ticket, now_ms=self._clock(),
                                   host_confirmed_released=True)
            self._unclaimed = None
            self._unclaimed_frame = None
            self._last_report = None
            self._last_delivery = None
            if self._held is not None and port is not None:
                self.recover_key_up(port=port)
            if self._held is not None:
                return False
            self._studio_id = None
            self._scope = None
            self._bindings.clear()
            return True

    def metrics(self) -> dict[str, object]:
        with self._lock:
            return {**self._counts, "enabled": self._studio_id is not None,
                    "key_release_pending": self._held is not None,
                    "delivery_unclaimed": self._last_delivery is not None,
                    "gate": self._gate.metrics()}


__all__ = [
    "StudioBinding", "StudioSnapshot", "StudioInputPort",
    "DispatchReport", "DeliveredAction", "StudioPlaytestHost",
]
