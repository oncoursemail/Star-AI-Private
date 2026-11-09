"""Two-phase, fail-quiet preplay gate for STAR's real-time gaming VTuber.

Composes the EXISTING stream director, owner/guest VAD gate and OBS/game load
governor. A plan is not a permission to speak: the host must revalidate just
before physical playout, separately hold broadcast authorization, and confirm
actual audible output before marking a director event spoken.

All inputs must originate from the trusted, same-monotonic-clock host.
This module does not read audio, start OBS, create speech, stop a device,
play games, authenticate VAD, or inspect untrusted viewer text.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock

from .stream_director import SpeechIntent, StreamDirector
from .stream_load_governor import StreamLoadGovernor
from .stream_turntaking import TurnTakingGate

_OPTIONAL_WHEN_CONSTRAINED = frozenset(
    {"ambient", "viewer_comment", "game_observation"}
)


@dataclass(frozen=True)
class PreplayDecision:
    status: str
    reason: str
    intent: SpeechIntent | None = None
    request_physical_stop: bool = False
    authorizes_playback: bool = False
    authorizes_broadcast: bool = False
    authorizes_game_input: bool = False


class StreamPreplayGate:
    """Owner-enabled speech preflight with an expiring single-use review lease.

    A successful recheck is an ADVISORY for an already authorized physical
    playout host; it is not itself a media/broadcast permission. The host must
    separately validate that its actual audio output and current epoch match.
    """

    def __init__(
        self,
        director: StreamDirector,
        turns: TurnTakingGate,
        load: StreamLoadGovernor,
        *,
        max_plan_age_ms: float = 250.0,
    ) -> None:
        if not isinstance(director, StreamDirector):
            raise TypeError("an existing StreamDirector is required")
        if not isinstance(turns, TurnTakingGate):
            raise TypeError("an existing TurnTakingGate is required")
        if not isinstance(load, StreamLoadGovernor):
            raise TypeError("an existing StreamLoadGovernor is required")
        if type(max_plan_age_ms) not in (int, float):
            raise ValueError("plan age must be a bounded number")
        if not math.isfinite(max_plan_age_ms) or not 20 <= max_plan_age_ms <= 500:
            raise ValueError("plan age must be 20..500 ms")
        self._director = director
        self._turns = turns
        self._load = load
        self._max_age_s = float(max_plan_age_ms) / 1000
        self._lock = RLock()
        self._enabled = False
        self._latest: float | None = None
        self._pending: SpeechIntent | None = None
        self._planned_at: float | None = None
        self._checked = False
        self._expired_unreviewed = 0
        # Once a candidate has been reviewed, PCM may already be queued.
        # Disabling planning cannot prove that the physical host is drained.
        self._quarantined: SpeechIntent | None = None

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("the trusted owner must enable the preplay gate")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before restarting the speech session")
            if self._quarantined is not None:
                raise RuntimeError("physical_audio_drain_receipt_required")
            self._enabled = True
            self._latest = None
            self._clear()

    def disable(self) -> None:
        """Stop planning; quarantine any reviewed turn until the output host drains.

        This deliberately does NOT stop a real audio device. The trusted host
        must stop/flush playback before acknowledging the quarantined intent.
        Re-enabling the planner cannot accidentally overlap leftover PCM.
        """
        with self._lock:
            self._enabled = False
            pending = self._pending
            if pending is not None:
                if self._checked:
                    self._quarantined = pending
                elif self._latest is not None:
                    # Never mark an unreviewed candidate as audible.
                    self._director.complete(pending, now=self._latest, spoken=False)
            self._clear()

    def acknowledge_host_drain(
        self, intent: SpeechIntent, *, now_s: float,
        host_verified: bool = False, audio_drained: bool = False,
    ) -> bool:
        """Trusted host receipt for STOP+FLUSH; never proof of audible speech.

        The host must authenticate its receipt and verify all queued/playing
        audio for this intent has stopped. Caller booleans alone are NOT
        cryptographic proof. This gate cannot independently inspect hardware.
        """
        if type(host_verified) is not bool or type(audio_drained) is not bool:
            raise ValueError("drain receipt flags must be trusted booleans")
        if type(now_s) not in (int, float):
            raise ValueError("invalid drain receipt clock")
        now = float(now_s)
        if not math.isfinite(now) or not 0 <= now <= 1e10:
            raise ValueError("invalid drain receipt clock")
        with self._lock:
            if self._latest is not None and now < self._latest:
                raise ValueError("monotonic clock reversed")
            if (self._enabled or self._quarantined is not intent
                    or not host_verified or not audio_drained):
                return False
            # Only after the external host has independently confirmed the
            # physical stop can the director abandon this pending response.
            self._director.complete(intent, now=now, spoken=False)
            self._quarantined = None
            self._latest = now
            return True

    def _clear(self) -> None:
        self._pending = None
        self._planned_at = None
        self._checked = False

    def _reap_unreviewed(self, now: float) -> bool:
        """Drop only a timed-out CANDIDATE, never a host-reviewed playout.

        A reviewed plan may already be queued or physically playing. Its
        output host MUST explicitly settle it after stop/PCM acknowledgement.
        Automatically unlocking that plan would risk overlapping two voices.
        """
        pending = self._pending
        planned = self._planned_at
        if pending is None or planned is None or self._checked:
            return False
        if now - planned <= self._max_age_s and now <= pending.deadline_at:
            return False
        # Clear first: the expiring event may have become invalid in the
        # director (scene reset/session change). Never retain a zombie lease.
        self._clear()
        self._director.complete(pending, now=now, spoken=False)
        self._expired_unreviewed += 1
        return True

    def lifecycle_metrics(self) -> dict[str, int]:
        """Non-sensitive watchdog counters, no event text or voice data."""
        with self._lock:
            return {
                "expired_unreviewed": self._expired_unreviewed,
                "restart_quarantined": int(self._quarantined is not None),
                "unreviewed_candidate": int(
                    self._pending is not None and not self._checked
                ),
                "awaiting_host_receipt": int(
                    self._pending is not None and self._checked
                ),
            }

    def _check(self, now_s: float, star_speaking: bool, gameplay_critical: bool) -> float:
        if type(now_s) not in (int, float):
            raise ValueError("a monotonic time in seconds is required")
        try:
            now = float(now_s)
        except (OverflowError, ValueError) as exc:
            raise ValueError("invalid monotonic time") from exc
        if not math.isfinite(now) or not 0 <= now <= 1e10:
            raise ValueError("monotonic seconds are out of range")
        if type(star_speaking) is not bool or type(gameplay_critical) is not bool:
            raise ValueError("speaking and critical flags must be trusted booleans")
        if self._latest is not None and now < self._latest:
            raise ValueError("monotonic clock reversed; reset the session")
        self._latest = now
        return now

    def _safety(self, now: float, star_speaking: bool):
        # Voice frames are milliseconds on the SAME host monotonic epoch.
        advice = self._turns.advise(now_ms=now * 1000, star_speaking=star_speaking)
        if advice.action == "yield_owner":
            return PreplayDecision(
                "yield_owner", advice.reason,
                request_physical_stop=advice.should_interrupt,
            ), None
        if advice.action != "speak":
            return PreplayDecision("hold", advice.reason), None
        if star_speaking:
            return PreplayDecision("hold", "star_is_already_speaking"), None
        load = self._load.recommend(now_s=now)
        if load.profile not in {"normal", "constrained"}:
            return PreplayDecision("hold", "live_load_" + load.profile), None
        return None, load

    def preflight(
        self, *, now_s: float, star_speaking: bool, gameplay_critical: bool
    ) -> PreplayDecision:
        with self._lock:
            now = self._check(now_s, star_speaking, gameplay_critical)
            if not self._enabled:
                return PreplayDecision("disabled", "owner_opt_in_missing")
            self._reap_unreviewed(now)
            blocked, load = self._safety(now, star_speaking)
            if blocked is not None:
                return blocked
            if self._pending is not None:
                return PreplayDecision("hold", "awaiting_previous_playout_receipt")
            intent = self._director.propose(
                now=now, voice_speaking=False, viewer_speaking=False,
                gameplay_critical=gameplay_critical, load_advice=load,
            )
            if intent is None:
                return PreplayDecision("quiet", "no_eligible_grounded_cue")
            self._pending = intent
            self._planned_at = now
            self._checked = False
            return PreplayDecision("candidate", "recheck_before_physical_playout", intent)

    def revalidate(
        self, intent: SpeechIntent, *, now_s: float,
        star_speaking: bool, gameplay_critical: bool,
    ) -> PreplayDecision:
        with self._lock:
            now = self._check(now_s, star_speaking, gameplay_critical)
            # Timed-out, never-reviewed candidates have never received a
            # successful play recommendation. Unblock future grounded turns.
            if self._enabled and self._pending is intent and self._reap_unreviewed(now):
                return PreplayDecision("denied", "speech_plan_timed_out")
            if not self._enabled or self._pending is not intent or self._planned_at is None:
                return PreplayDecision("denied", "unknown_or_stale_speech_plan")
            if self._checked:
                return PreplayDecision("denied", "speech_plan_already_checked")
            if now - self._planned_at > self._max_age_s or now > intent.deadline_at:
                return PreplayDecision("denied", "speech_plan_timed_out")
            blocked, load = self._safety(now, star_speaking)
            if blocked is not None:
                return blocked
            if load is None:
                # Do not let a changed or incomplete producer return a reviewed
                # speech plan without independent live resource measurements.
                return PreplayDecision("hold", "live_load_advice_missing")
            if gameplay_critical and intent.kind not in {"game_danger", "owner_interrupt"}:
                return PreplayDecision("hold", "critical_gameplay_focus")
            if load.profile == "constrained" and intent.kind in _OPTIONAL_WHEN_CONSTRAINED:
                return PreplayDecision("hold", "optional_commentary_suppressed")
            # This is a single-use recommendation only, never a physical gate.
            self._checked = True
            return PreplayDecision("reviewed", "host_must_separately_authorize_media", intent)

    def reviewed_for_host(self, intent: SpeechIntent, *,
                          now_s: float | None = None) -> bool:
        """Read-only review identity check; with clock also require freshness.

        Supply host monotonic time before first PCM admission. Omit only when
        checking the same already-admitted turn's ongoing PCM submissions.
        This does not authorize physical playback or prove quiet audio.
        """
        with self._lock:
            if not (self._enabled and self._checked
                    and self._pending is intent and self._quarantined is None):
                return False
            if now_s is None:
                return True
            if type(now_s) not in (int, float):
                raise ValueError("trusted monotonic time required")
            now = float(now_s)
            if not math.isfinite(now) or not 0 <= now <= 1e10:
                raise ValueError("invalid monotonic time")
            if self._latest is not None and now < self._latest:
                raise ValueError("monotonic clock reversed")
            if (self._planned_at is None or now - self._planned_at > self._max_age_s
                    or now > intent.deadline_at):
                return False
            self._latest = now
            return True

    def settle(
        self, intent: SpeechIntent, *, now_s: float,
        audible_confirmed: bool = False,
    ) -> bool:
        """Host-issued receipt; do NOT mark spoken without measured audible PCM."""
        if type(audible_confirmed) is not bool:
            raise ValueError("audible_confirmed must be a host-attested boolean")
        with self._lock:
            if type(now_s) not in (int, float):
                raise ValueError("invalid settle clock")
            now = float(now_s)
            if not math.isfinite(now) or not 0 <= now <= 1e10:
                raise ValueError("invalid settle clock")
            if self._latest is not None and now < self._latest:
                raise ValueError("monotonic clock reversed")
            self._latest = now
            if not self._enabled or self._pending is not intent:
                return False
            # Any attempt without a successful final recheck is abandoned.
            spoken = bool(audible_confirmed and self._checked)
            self._clear()
            return self._director.complete(intent, now=now, spoken=spoken)


__all__ = ["PreplayDecision", "StreamPreplayGate"]
