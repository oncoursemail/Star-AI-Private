"""Fail-closed, host-mediated *advisory* action gate for STAR's game agent.

This module connects fresh, host-verified game observations to a narrow,
owner-curated symbolic-action interface. It cannot observe a game or execute
an input. A separate trusted host must validate focus, action mappings,
authorization, game rules, and key-up watchdogs immediately before dispatch.

All timestamps come from one host monotonic clock. No video, personal data,
key bindings, or success claims are retained. Actual learning still requires
an independent signed GameTrial in gameplay_skill_bank.
"""
from __future__ import annotations

from typing import cast

from collections import deque
from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Sequence

from .stream_budget import StreamTelemetry

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK = 1e13


def _ms(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite monotonic millisecond value")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK:
        raise ValueError(f"{label} must be a finite nonnegative millisecond value")
    return number


def _id(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded symbolic ID")
    return value


def _rank_ms(samples: deque[float], fraction: float) -> float | None:
    """Nearest-rank summary of at most 64 anonymous host-clock samples."""
    if not samples:
        return None
    ordered = sorted(samples)
    return round(ordered[math.ceil(fraction * len(ordered)) - 1], 2)


@dataclass(frozen=True)
class GameScope:
    game_id: str
    version_id: str
    episode_id: str

    def __post_init__(self) -> None:
        for label in ("game_id", "version_id", "episode_id"):
            _id(getattr(self, label), label)


@dataclass(frozen=True)
class GameFrame:
    """Trusted host's symbolic view; not a visual model or ground truth."""
    scope: GameScope
    sequence: int
    captured_ms: float
    evidence_sha256: str
    focus_confirmed: bool
    playable: bool
    perception_confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.scope, GameScope):
            raise TypeError("scope must be GameScope")
        if type(self.sequence) is not int or not 0 < self.sequence <= 2**63 - 1:
            raise ValueError("frame sequence must be a positive integer")
        _ms(self.captured_ms, "captured_ms")
        if type(self.evidence_sha256) is not str or not _DIGEST.fullmatch(
                self.evidence_sha256):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        if type(self.focus_confirmed) is not bool or type(self.playable) is not bool:
            raise ValueError("focus and playable must be trusted booleans")
        confidence = _ms(self.perception_confidence, "perception_confidence")
        if confidence > 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class GameActionHint:
    """UNTRUSTED model proposal: never an OS key or unrestricted command."""
    action_id: str
    frame_sequence: int
    frame_sha256: str
    proposed_ms: float
    hold_ms: int

    def __post_init__(self) -> None:
        _id(self.action_id, "action_id")
        if type(self.frame_sequence) is not int or self.frame_sequence <= 0:
            raise ValueError("frame_sequence must be positive")
        if type(self.frame_sha256) is not str or not _DIGEST.fullmatch(
                self.frame_sha256):
            raise ValueError("frame_sha256 must be a lowercase SHA-256 digest")
        _ms(self.proposed_ms, "proposed_ms")
        if type(self.hold_ms) is not int or not 1 <= self.hold_ms <= 500:
            raise ValueError("hold_ms must be 1..500")


@dataclass(frozen=True)
class ActionPermit:
    offered: bool
    reason: str
    ticket: int | None = None
    action_id: str | None = None
    hold_ms: int | None = None
    expires_ms: float | None = None
    authorized_to_press_keys: bool = False  # ALWAYS false: host checks separately


@dataclass
class _Pending:
    ticket: int
    expires_ms: float
    captured_ms: float
    claimed: bool = False
    expired: bool = False


class GameActionGate:
    """Thread-safe two-phase proposal gate: request -> claim -> release.

    A claim is one-time, even if the host fails to dispatch. A timed-out or
    disabled action still occupies the single action slot until the host
    explicitly confirms key release. A model cannot clear quarantine.

    Never automatically sends input. The host must recheck focus, the user
    consent, allowlist, process ownership, multiplayer restrictions and an
    independent maximum key-hold watchdog at the actual dispatch boundary.
    """

    def __init__(self, *, frame_max_age_ms: int = 350,
                 minimum_gap_ms: int = 200, ticket_window_ms: int = 120,
                 max_hold_ms: int = 180, max_per_minute: int = 45,
                 min_confidence: float = 0.75) -> None:
        for name, value, low, high in (
            ("frame_max_age_ms", frame_max_age_ms, 50, 1000),
            ("minimum_gap_ms", minimum_gap_ms, 50, 2000),
            ("ticket_window_ms", ticket_window_ms, 20, 300),
            ("max_hold_ms", max_hold_ms, 10, 300),
            ("max_per_minute", max_per_minute, 1, 120),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in {low}..{high}")
        if not 0.5 <= _ms(min_confidence, "min_confidence") <= 1:
            raise ValueError("min_confidence must be 0.5..1")
        self.frame_max_age_ms = frame_max_age_ms
        self.minimum_gap_ms = minimum_gap_ms
        self.ticket_window_ms = ticket_window_ms
        self.max_hold_ms = max_hold_ms
        self.max_per_minute = max_per_minute
        self.min_confidence = min_confidence
        self._lock = RLock()
        self._enabled = False
        self._scope: GameScope | None = None
        self._allowlist: frozenset[str] = frozenset()
        self._clock_ms: float | None = None
        self._last_sequence = 0
        self._last_capture_ms: float | None = None
        self._serial = 0
        self._pending: _Pending | None = None
        # Exact object identity is reserved for trusted-host dispatch adapters.
        # A model-supplied copied ticket/permit must never authorize input.
        self._offered_permit: ActionPermit | None = None
        self._offered_at: deque[float] = deque(maxlen=120)
        # Never store scenes, action names or identities in performance samples.
        # These timings are trusted-host acknowledgements, NOT physical input
        # timestamps. Bounded state keeps percentile summaries inexpensive.
        self._observation_to_offer_ms: deque[float] = deque(maxlen=64)
        self._observation_to_claim_ms: deque[float] = deque(maxlen=64)
        self._counts = dict(offered=0, denied=0, claimed=0, released=0,
                            expired=0, host_rechecks_failed=0)

    def start(self, scope: GameScope, action_ids: Sequence[str], *,
              owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must opt into this game and these actions")
        if not isinstance(scope, GameScope):
            raise TypeError("scope must be GameScope")
        if type(action_ids) not in (list, tuple) or not 1 <= len(action_ids) <= 32:
            raise ValueError("expected 1..32 owner-curated symbolic action IDs")
        if any(type(v) is not str or not _ID.fullmatch(v) for v in action_ids):
            raise ValueError("invalid action ID")
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("duplicate action IDs")
        with self._lock:
            if self._enabled or self._pending is not None:
                raise RuntimeError("revoke and confirm key release before a new session")
            self._scope = scope
            self._allowlist = frozenset(action_ids)
            self._clock_ms = None
            self._last_sequence = 0
            self._last_capture_ms = None
            self._offered_at.clear()
            self._observation_to_offer_ms.clear()
            self._observation_to_claim_ms.clear()
            self._offered_permit = None
            self._enabled = True

    def revoke(self) -> None:
        """Disable new permits; retain pending slot until explicit host release."""
        with self._lock:
            self._enabled = False
            self._scope = None
            self._allowlist = frozenset()
            self._offered_permit = None

    def _advance(self, now_ms: float) -> float:
        now = _ms(now_ms, "now_ms")
        if self._clock_ms is not None and now < self._clock_ms:
            raise ValueError("host monotonic clock reversed")
        self._clock_ms = now
        while self._offered_at and now - self._offered_at[0] >= 60_000:
            self._offered_at.popleft()
        if self._pending and now > self._pending.expires_ms and not self._pending.expired:
            self._pending.expired = True
            self._counts["expired"] += 1
        return now

    def request(self, frame: GameFrame, hint: GameActionHint, *,
                now_ms: float, host_verified: bool = False,
                telemetry: StreamTelemetry | None = None) -> ActionPermit:
        if not isinstance(frame, GameFrame) or not isinstance(hint, GameActionHint):
            raise TypeError("expected GameFrame and GameActionHint")
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be a trusted boolean")
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be StreamTelemetry")
        with self._lock:
            now = self._advance(now_ms)

            def deny(reason: str) -> ActionPermit:
                self._counts["denied"] += 1
                return ActionPermit(False, reason)

            if not self._enabled or self._scope is None:
                return deny("owner_consent_missing")
            if self._pending is not None:
                return deny("awaiting_host_key_release")
            if not host_verified:
                return deny("trusted_observation_missing")
            if frame.scope != self._scope:
                return deny("wrong_game_version_or_episode")
            if not frame.focus_confirmed or not frame.playable:
                return deny("game_unfocused_or_in_menu")
            if frame.perception_confidence < self.min_confidence:
                return deny("uncertain_observation")
            if frame.sequence <= self._last_sequence:
                return deny("stale_or_replayed_frame_sequence")
            # A larger sequence is insufficient if an asynchronous observer
            # delivers an OLDER scene after a newer one was already used.
            if (self._last_capture_ms is not None
                    and frame.captured_ms <= self._last_capture_ms):
                return deny("out_of_order_frame_capture")
            if frame.captured_ms > now + 15 or now - frame.captured_ms > self.frame_max_age_ms:
                return deny("frame_not_current")
            if hint.frame_sequence != frame.sequence or hint.frame_sha256 != (
                    frame.evidence_sha256):
                return deny("proposal_not_bound_to_frame")
            if hint.proposed_ms > now + 15 or hint.proposed_ms < frame.captured_ms - 15:
                return deny("proposal_time_not_bound_to_frame")
            if now - hint.proposed_ms > self.frame_max_age_ms:
                return deny("proposal_stale")
            if hint.action_id not in self._allowlist:
                return deny("action_not_in_host_allowlist")
            if hint.hold_ms > self.max_hold_ms:
                return deny("hold_exceeds_host_limit")
            if telemetry is None or not telemetry.game_active:
                return deny("game_telemetry_missing_or_inactive")
            if telemetry.game_fps < 30 or telemetry.speech_backlog_ms > 350:
                return deny("realtime_game_or_voice_pressure")
            if self._offered_at and now - self._offered_at[-1] < self.minimum_gap_ms:
                return deny("per_action_spacing")
            if len(self._offered_at) >= self.max_per_minute:
                return deny("minute_action_budget_exhausted")

            expiry = min(now + self.ticket_window_ms,
                         frame.captured_ms + self.frame_max_age_ms)
            if expiry - now < 20:
                return deny("too_little_time_to_claim")
            self._serial += 1
            self._pending = _Pending(self._serial, expiry, frame.captured_ms)
            self._last_sequence = frame.sequence
            self._last_capture_ms = frame.captured_ms
            self._offered_at.append(now)
            self._observation_to_offer_ms.append(max(0.0, now - frame.captured_ms))
            self._counts["offered"] += 1
            permit = ActionPermit(True, "host_must_recheck_before_dispatch",
                                  self._serial, hint.action_id, hint.hold_ms,
                                  expiry)
            self._offered_permit = permit
            return permit

    def claim(self, ticket: int, *, now_ms: float,
              host_focus_and_permission: bool = False) -> bool:
        """One-shot host acknowledgment; never actually presses an input."""
        if type(ticket) is not int or ticket <= 0:
            raise ValueError("ticket must be positive integer")
        if type(host_focus_and_permission) is not bool:
            raise ValueError("host_focus_and_permission must be boolean")
        with self._lock:
            now = self._advance(now_ms)
            pending = self._pending
            if not self._enabled or pending is None or pending.ticket != ticket:
                return False
            if pending.claimed or pending.expired or now > pending.expires_ms:
                return False
            if not host_focus_and_permission:
                self._counts["host_rechecks_failed"] += 1
                return False
            pending.claimed = True
            self._observation_to_claim_ms.append(
                max(0.0, now - pending.captured_ms),
            )
            self._counts["claimed"] += 1
            return True

    def claim_offered(self, permit: ActionPermit, *, now_ms: float,
                      host_focus_and_permission: bool = False) -> bool:
        """Host adapter claim: require the actual, unmodified issued object.

        Ordinary claim(ticket) remains advisory/backward compatible, but it
        MUST NOT be used as authorization by any input-producing adapter.
        """
        with self._lock:
            if not isinstance(permit, ActionPermit) or self._offered_permit is not permit:
                return False
            # An offered permit always has a ticket, but keep the claim API
            # fail-closed if a malformed internal permit reaches this path.
            if permit.ticket is None:
                return False
            accepted = self.claim(permit.ticket, now_ms=now_ms,
                                  host_focus_and_permission=host_focus_and_permission)
            if accepted:
                self._offered_permit = None
            return accepted

    def release(self, ticket: int, *, now_ms: float,
                host_confirmed_released: bool = False) -> bool:
        """Host confirms all input/key-up. Never trust a model's assertion."""
        if type(ticket) is not int or ticket <= 0:
            raise ValueError("ticket must be positive integer")
        if type(host_confirmed_released) is not bool:
            raise ValueError("host_confirmed_released must be boolean")
        with self._lock:
            self._advance(now_ms)
            if (self._pending is None or self._pending.ticket != ticket
                    or not host_confirmed_released):
                return False
            self._pending = None
            self._offered_permit = None
            self._counts["released"] += 1
            return True

    def metrics(self) -> dict[str, int | bool | str | float | None]:
        """Host-acknowledgement latency only, never real keypress/gameplay proof."""
        with self._lock:
            return {
                **self._counts, "enabled": self._enabled,
                "awaiting_host_release": self._pending is not None,
                "quarantined": bool(self._pending and self._pending.expired),
                "observation_to_offer_p50_ms": _rank_ms(
                    self._observation_to_offer_ms, 0.50,
                ),
                "observation_to_offer_p95_ms": _rank_ms(
                    self._observation_to_offer_ms, 0.95,
                ),
                "observation_to_host_claim_p50_ms": _rank_ms(
                    self._observation_to_claim_ms, 0.50,
                ),
                "observation_to_host_claim_p95_ms": _rank_ms(
                    self._observation_to_claim_ms, 0.95,
                ),
                "basis": "advisory; not dispatched game input or verified success",
            }


__all__ = [
    "GameScope", "GameFrame", "GameActionHint", "ActionPermit", "GameActionGate",
]
