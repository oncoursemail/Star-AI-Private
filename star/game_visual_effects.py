"""Offline-first visual action-effect probes for Star's game-playing research.

This is a *diagnostic*, not a causal inference engine or a success verifier.
After a separately authorized game-input host confirms all keys are released,
Star can pair a host-captured before image fingerprint with two distinct
post-action observations. A small visual difference suggests that something
changed; it NEVER proves the action caused the change or that the goal succeeded.

There is no screen capture, game control, model call, microphone, network I/O,
stream publishing, or persistent personal data here. The local trusted host
owns focus/consent verification, capture integrity and independent GameTrial
outcomes. Viewer/model text must never call this host API.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Sequence

from .frame_fingerprint import tone_distance
from .game_action_gate import GameFrame, GameScope
from .stream_observe import FrameCue

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_MS = 1e13


def _ms(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("trusted monotonic timestamp must be numeric")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid monotonic timestamp") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_MS:
        raise ValueError("invalid monotonic timestamp")
    return number


@dataclass(frozen=True)
class EffectTicket:
    """Opaque one-shot reservation. A copied ticket is never accepted."""

    generation: int
    serial: int
    expires_ms: float


@dataclass(frozen=True)
class ProbeAdmission:
    accepted: bool
    reason: str
    ticket: EffectTicket | None = None


@dataclass(frozen=True)
class EffectFinding:
    """Fingerprint-only outcome; never claim gameplay success or causality."""

    status: str
    reason: str
    comparisons: int = 0
    game_bits: int = 0
    hud_bits: int = 0
    changed_focus_regions: int = 0
    action_to_capture_ms: float | None = None
    independently_verified_success: bool = False
    authorized_to_play: bool = False


@dataclass
class _Pending:
    ticket: EffectTicket
    before: FrameCue
    before_frame: GameFrame
    released_ms: float
    checked: int = 0
    last_captured_ms: float = -1.0
    last_sequence: int = 0
    last_kind: bool | None = None
    consecutive: int = 0


class GameVisualEffectProbe:
    """One action at a time, bounded before/after observation, no OS I/O.

    Requires host attestations both for the already-released game action and
    for the captured images. It cannot *verify* these attestations itself.
    A separate signed GameTrial is mandatory before any learning system may
    credit practice success.
    """

    def __init__(
        self, *, window_ms: int = 1500, frame_age_ms: int = 300,
        min_post_delay_ms: int = 40, min_frame_spacing_ms: int = 50,
        confirmations: int = 2, game_novelty_bits: int = 8,
        hud_novelty_bits: int = 4, tone_novelty_bins: int = 4,
    ) -> None:
        for label, value, low, high in (
            ("window_ms", window_ms, 300, 3000),
            ("frame_age_ms", frame_age_ms, 50, 750),
            ("min_post_delay_ms", min_post_delay_ms, 0, 400),
            ("min_frame_spacing_ms", min_frame_spacing_ms, 10, 400),
            ("confirmations", confirmations, 2, 4),
            ("game_novelty_bits", game_novelty_bits, 1, 64),
            ("hud_novelty_bits", hud_novelty_bits, 1, 64),
            ("tone_novelty_bins", tone_novelty_bins, 1, 63),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{label} must be an integer in {low}..{high}")
        if min_post_delay_ms + (confirmations - 1) * min_frame_spacing_ms >= window_ms:
            raise ValueError("window too short for independent post-action frames")
        self.window_ms = window_ms
        self.frame_age_ms = frame_age_ms
        self.min_post_delay_ms = min_post_delay_ms
        self.min_frame_spacing_ms = min_frame_spacing_ms
        self.confirmations = confirmations
        self.game_novelty_bits = game_novelty_bits
        self.hud_novelty_bits = hud_novelty_bits
        self.tone_novelty_bins = tone_novelty_bins
        self._lock = RLock()
        self._scope: GameScope | None = None
        self._actions: frozenset[str] = frozenset()
        self._enabled = False
        self._generation = 0
        self._serial = 0
        self._clock: float | None = None
        self._last_before_seq = 0
        self._pending: _Pending | None = None
        self._stats = dict(armed=0, rejected=0, changed=0, unchanged=0,
                           inconclusive=0, expired=0, stopped=0)

    def start(
        self, scope: GameScope, action_ids: Sequence[str], *,
        owner_approved: bool = False, game_session_approved: bool = False,
    ) -> None:
        if owner_approved is not True or game_session_approved is not True:
            raise PermissionError("explicit owner and game-session approval required")
        if not isinstance(scope, GameScope):
            raise TypeError("host game scope required")
        if (type(action_ids) not in (list, tuple) or not 1 <= len(action_ids) <= 32
                or any(type(x) is not str or not _ID.fullmatch(x) for x in action_ids)
                or len(action_ids) != len(set(action_ids))):
            raise ValueError("owner-curated unique symbolic action IDs required")
        with self._lock:
            if self._enabled or self._pending is not None:
                raise RuntimeError("stop current probe session before restart")
            self._generation += 1
            self._scope = scope
            self._actions = frozenset(action_ids)
            self._enabled = True
            self._clock = None
            self._last_before_seq = 0

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            self._generation += 1
            self._pending = None
            self._scope = None
            self._actions = frozenset()
            self._stats["stopped"] += 1

    def _tick(self, now_ms: float) -> float:
        now = _ms(now_ms)
        if self._clock is not None and now < self._clock:
            raise ValueError("monotonic host clock moved backwards")
        self._clock = now
        return now

    @staticmethod
    def _bound(frame: GameFrame, cue: FrameCue) -> bool:
        return abs(frame.captured_ms - cue.captured_ms) <= 5

    def arm(
        self, before_frame: GameFrame, before_cue: FrameCue, *,
        action_id: str, released_ms: float, now_ms: float,
        host_input_released: bool = False,
        host_capture_verified: bool = False,
    ) -> ProbeAdmission:
        """Bind the pre-action frame to a physically *released* input event.

        Host must take 'before' prior to action dispatch, and only call after
        it has confirmed physical key-up. No model/permit alone is sufficient.
        """
        if not isinstance(before_frame, GameFrame) or not isinstance(before_cue, FrameCue):
            raise TypeError("trusted game frame and visual fingerprint required")
        if type(host_input_released) is not bool or type(host_capture_verified) is not bool:
            raise TypeError("explicit trusted host attestations required")
        ended = _ms(released_ms)
        with self._lock:
            now = self._tick(now_ms)

            def deny(reason: str) -> ProbeAdmission:
                self._stats["rejected"] += 1
                return ProbeAdmission(False, reason)

            if not self._enabled or self._scope is None:
                return deny("owner_opt_in_missing")
            if self._pending is not None:
                if now > self._pending.ticket.expires_ms:
                    self._pending = None
                    self._stats["expired"] += 1
                else:
                    return deny("prior_attempt_unresolved")
            if not host_input_released or not host_capture_verified:
                return deny("host_release_or_capture_missing")
            if type(action_id) is not str or action_id not in self._actions:
                return deny("action_not_owner_curated")
            if before_frame.scope != self._scope:
                return deny("game_version_or_episode_mismatch")
            if (not before_frame.focus_confirmed or not before_frame.playable
                    or before_frame.perception_confidence < 0.75):
                return deny("game_focus_or_perception_unavailable")
            if not self._bound(before_frame, before_cue):
                return deny("unpaired_before_capture")
            if before_frame.sequence <= self._last_before_seq:
                return deny("replayed_before_frame")
            if (ended < before_frame.captured_ms
                    or ended > now + 10 or now - ended > 400
                    or ended - before_frame.captured_ms > 500):
                return deny("input_release_not_fresh_or_before_capture")
            self._serial += 1
            ticket = EffectTicket(self._generation, self._serial,
                                  ended + self.window_ms)
            self._pending = _Pending(ticket, before_cue, before_frame, ended)
            self._last_before_seq = before_frame.sequence
            self._stats["armed"] += 1
            return ProbeAdmission(True, "awaiting_independent_post_frames", ticket)

    def observe(
        self, ticket: EffectTicket, after_frame: GameFrame, after_cue: FrameCue, *,
        now_ms: float, host_capture_verified: bool = False,
    ) -> EffectFinding:
        """Require consecutive independent post-action frames for a signal.

        HUD, focus and color changes are compared separately. Even a result
        called visual_change_detected is *never* signed gameplay truth.
        """
        if (not isinstance(ticket, EffectTicket)
                or not isinstance(after_frame, GameFrame)
                or not isinstance(after_cue, FrameCue)):
            raise TypeError("issued ticket, game frame and fingerprint required")
        if type(host_capture_verified) is not bool:
            raise TypeError("explicit trusted capture attestation required")
        with self._lock:
            now = self._tick(now_ms)
            pending = self._pending
            if (not self._enabled or pending is None
                    or pending.ticket is not ticket
                    or ticket.generation != self._generation):
                self._stats["rejected"] += 1
                return EffectFinding("rejected", "stale_or_foreign_ticket")

            def finish(status: str, reason: str, *,
                       game_bits: int = 0, hud_bits: int = 0,
                       focus_count: int = 0) -> EffectFinding:
                self._pending = None
                if status == "visual_change_detected":
                    self._stats["changed"] += 1
                elif status == "no_visible_change":
                    self._stats["unchanged"] += 1
                else:
                    self._stats["inconclusive"] += 1
                return EffectFinding(
                    status, reason, pending.checked, game_bits, hud_bits,
                    focus_count, max(0.0, after_frame.captured_ms - pending.released_ms),
                )

            if now > ticket.expires_ms:
                self._stats["expired"] += 1
                return finish("inconclusive", "action_effect_window_expired")
            if not host_capture_verified:
                return finish("inconclusive", "trusted_capture_missing")
            if (after_frame.scope != self._scope
                    or not after_frame.focus_confirmed or not after_frame.playable
                    or after_frame.perception_confidence < 0.75):
                return finish("inconclusive", "game_changed_or_unfocused")
            if not self._bound(after_frame, after_cue):
                return finish("inconclusive", "unpaired_post_capture")
            if (after_frame.sequence <= max(
                    pending.before_frame.sequence, pending.last_sequence)
                    or after_frame.captured_ms <= max(
                        pending.before_frame.captured_ms, pending.last_captured_ms)):
                return EffectFinding("awaiting_confirmation", "duplicate_or_reordered_frame",
                                     pending.checked)
            if (after_frame.captured_ms < pending.released_ms + self.min_post_delay_ms
                    or now - after_frame.captured_ms > self.frame_age_ms
                    or after_frame.captured_ms > now + 10
                    or after_frame.captured_ms > ticket.expires_ms):
                return EffectFinding("awaiting_confirmation", "post_frame_not_in_window",
                                     pending.checked)
            if (pending.checked > 0
                    and after_frame.captured_ms - pending.last_captured_ms
                    < self.min_frame_spacing_ms):
                return EffectFinding("awaiting_confirmation", "post_frames_too_close",
                                     pending.checked)
            before, after = pending.before, after_cue
            if (tuple(s.region for s in before.focus_samples) !=
                    tuple(s.region for s in after.focus_samples)
                    or (before.hud_hash is None) != (after.hud_hash is None)
                    or (before.tone_signature is None) != (after.tone_signature is None)
                    or (before.hud_tone_signature is None) != (
                        after.hud_tone_signature is None)):
                return finish("inconclusive", "capture_regions_or_sensor_scope_changed")
            game_bits = (before.perceptual_hash ^ after.perceptual_hash).bit_count()
            hud_bits = ((before.hud_hash ^ after.hud_hash).bit_count()
                        if before.hud_hash is not None and after.hud_hash is not None
                        else 0)
            focus_count = sum(
                (a.edge_hash ^ b.edge_hash).bit_count() >= self.hud_novelty_bits
                or tone_distance(a.tone_signature, b.tone_signature)
                >= self.tone_novelty_bins
                for a, b in zip(before.focus_samples, after.focus_samples)
            )
            game_tone = (
                tone_distance(before.tone_signature, after.tone_signature)
                if before.tone_signature is not None and after.tone_signature is not None
                else 0
            )
            hud_tone = (
                tone_distance(before.hud_tone_signature, after.hud_tone_signature)
                if before.hud_tone_signature is not None
                and after.hud_tone_signature is not None else 0
            )
            changed = (game_bits >= self.game_novelty_bits
                       or hud_bits >= self.hud_novelty_bits
                       or focus_count > 0
                       or game_tone >= self.tone_novelty_bins
                       or hud_tone >= self.tone_novelty_bins)
            pending.checked += 1
            pending.last_sequence = after_frame.sequence
            self._last_before_seq = max(self._last_before_seq, after_frame.sequence)
            pending.last_captured_ms = after_frame.captured_ms
            pending.consecutive = (pending.consecutive + 1
                                   if pending.last_kind is changed else 1)
            pending.last_kind = changed
            if pending.consecutive < self.confirmations:
                return EffectFinding(
                    "awaiting_confirmation", "require_multiple_independent_frames",
                    pending.checked, game_bits, hud_bits, focus_count,
                )
            return finish(
                "visual_change_detected" if changed else "no_visible_change",
                "visual_novelty_only_not_verified_gameplay_or_causality",
                game_bits=game_bits, hud_bits=hud_bits, focus_count=focus_count,
            )

    def status(self) -> dict[str, int | bool]:
        """Counters only; no frames, names, media, notes, or raw fingerprints."""
        with self._lock:
            return {**self._stats, "enabled": self._enabled,
                    "pending": self._pending is not None}


__all__ = [
    "EffectTicket", "ProbeAdmission", "EffectFinding", "GameVisualEffectProbe",
]
