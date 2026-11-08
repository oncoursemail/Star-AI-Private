"""Host-only composer of verified quiet, game urgency, and stream event priority.

No microphones, models, PCM, OBS, game input, broadcasts or viewer chat are
accessed. An optional trusted resource governor gates optional speech using
fresh host-derived OBS/game telemetry. Decisions are advisory. Host must authenticate owner VAD, attest
actual playback, physically stop/flush PCM, and neutralize avatar motion.
Off by default, fail closed on stale VAD and unconfirmed physical stop.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
from typing import cast

from .stream_director import SpeechIntent, StreamDirector, StreamSignal
from .stream_load_governor import StreamLoadGovernor
from .stream_turntaking import TurnTakingGate, VoiceFrame


def _time(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host time must be a finite numeric millisecond clock")
    try:
        now = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid host clock") from exc
    if not math.isfinite(now) or not 0 <= now <= 1e13:
        raise ValueError("invalid host clock")
    return now


@dataclass(frozen=True)
class NaturalTurnDecision:
    action: str  # hold | prepare | stop_playback
    reason: str
    intent: SpeechIntent | None = None
    stop_token: int | None = None
    authorizes_playback: bool = False
    authorizes_broadcast: bool = False
    authorizes_game_input: bool = False


class NaturalTurnBridge:
    """Single host-owned non-executing boundary for one speech episode.

    A stop remains latched across disabled sessions until the host confirms
    both physical PCM draining and avatar neutralization using a fresh token.
    """

    def __init__(
        self, *, director: StreamDirector | None = None,
        turn_gate: TurnTakingGate | None = None,
        load_governor: StreamLoadGovernor | None = None,
    ) -> None:
        if director is not None and type(director) is not StreamDirector:
            raise TypeError("expected StreamDirector")
        if turn_gate is not None and type(turn_gate) is not TurnTakingGate:
            raise TypeError("expected TurnTakingGate")
        if load_governor is not None and type(load_governor) is not StreamLoadGovernor:
            raise TypeError("expected trusted StreamLoadGovernor")
        self._lock = RLock()
        self._director = director if director is not None else StreamDirector()
        self._turn = turn_gate if turn_gate is not None else TurnTakingGate()
        # Opt-in: bind the real producer, never accept model-supplied advice.
        # Its host-monotonic seconds must share this bridge's millisecond clock.
        self._load_governor = load_governor
        self._enabled = False
        self._last_now_ms: float | None = None
        self._last_playout_active = False
        self._pending_intent: SpeechIntent | None = None
        self._stop_token: int | None = None
        self._next_stop_token = 0
        self._counts = dict(prepared=0, stops_requested=0, stops_confirmed=0)

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required")
        with self._lock:
            if self._enabled or self._stop_token is not None:
                raise RuntimeError("session or physical stop already pending")
            self._director.enable(owner_approved=True)
            try:
                self._turn.enable(
                    owner_approved=True, require_verified_quiet=True,
                )
            except Exception:
                self._director.disable()
                raise
            self._enabled = True
            self._pending_intent = None
            self._last_playout_active = False
            self._last_now_ms = None

    def _request_stop(self) -> None:
        if self._stop_token is None:
            self._next_stop_token += 1
            self._stop_token = self._next_stop_token
            self._counts["stops_requested"] += 1
        self._pending_intent = None

    def disable(self, *, host_playout_active: bool) -> int | None:
        """Invalidate proposals; tell host if physical audio/rig stop is needed."""
        if type(host_playout_active) is not bool:
            raise ValueError("host_playout_active must be bool")
        with self._lock:
            if self._enabled:
                self._director.disable()
                self._turn.disable()
            self._enabled = False
            self._pending_intent = None
            if host_playout_active or self._last_playout_active:
                self._request_stop()
            return self._stop_token

    def acknowledge_stopped(
        self, token: int, *, pcm_drained: bool, avatar_neutral: bool,
    ) -> bool:
        """Only trusted host may report both finished audio and neutral rig."""
        if (type(token) is not int or type(pcm_drained) is not bool
                or type(avatar_neutral) is not bool):
            raise ValueError("invalid stop acknowledgment")
        with self._lock:
            if (self._stop_token is None or token != self._stop_token
                    or not pcm_drained or not avatar_neutral):
                return False
            self._stop_token = None
            self._last_playout_active = False
            self._counts["stops_confirmed"] += 1
            return True

    def observe_voice(self, frame: VoiceFrame) -> bool:
        with self._lock:
            if not self._enabled:
                return False
            admitted = self._turn.observe(frame)
            # An utterance prepared under silence cannot outlive new speech
            # activity while it is still waiting in the TTS generation queue.
            # Do not invalidate an already-playing utterance merely because
            # audio detection cannot separate STAR's own output.
            if admitted and not self._last_playout_active:
                if self._turn.advise(
                    now_ms=frame.at_ms, star_speaking=False,
                ).hold:
                    self._pending_intent = None
            return admitted

    def offer(self, signal: StreamSignal, *, now_ms: float) -> bool:
        """Offer host-moderated data. Does not authorize speech or tools."""
        now = _time(now_ms)
        with self._lock:
            if not self._enabled or self._stop_token is not None:
                return False
            if self._last_now_ms is not None and now < self._last_now_ms:
                return False
            self._last_now_ms = now
            accepted = self._director.offer(signal, now=now / 1000)
            if accepted and signal.kind in {"owner_interrupt", "game_danger"}:
                self._pending_intent = None
            return accepted

    def advise(
        self, *, now_ms: float, host_playout_active: bool,
        gameplay_critical: bool, output_healthy: bool,
    ) -> NaturalTurnDecision:
        """Compose without speaking; critical gameplay takes precedence."""
        now = _time(now_ms)
        if any(type(v) is not bool for v in (
            host_playout_active, gameplay_critical, output_healthy,
        )):
            raise ValueError("trusted host state requires explicit booleans")
        with self._lock:
            if self._last_now_ms is not None and now < self._last_now_ms:
                return NaturalTurnDecision("hold", "host_clock_reversed")
            self._last_now_ms = now
            self._last_playout_active = host_playout_active
            if self._stop_token is not None:
                return NaturalTurnDecision(
                    "stop_playback", "physical_stop_unconfirmed",
                    stop_token=self._stop_token,
                )
            if not self._enabled:
                return NaturalTurnDecision("hold", "owner_opt_in_missing")
            turn = self._turn.advise(
                now_ms=now, star_speaking=host_playout_active,
            )
            if turn.should_interrupt and host_playout_active:
                self._request_stop()
                return NaturalTurnDecision(
                    "stop_playback", "authenticated_owner_barge_in",
                    stop_token=self._stop_token,
                )
            if not output_healthy or gameplay_critical:
                self._pending_intent = None
                reason = ("output_unhealthy" if not output_healthy
                          else "critical_gameplay")
                if host_playout_active:
                    self._request_stop()
                    return NaturalTurnDecision(
                        "stop_playback", reason, stop_token=self._stop_token,
                    )
                return NaturalTurnDecision("hold", reason)
            if turn.hold or host_playout_active:
                if turn.hold and not host_playout_active:
                    self._pending_intent = None
                return NaturalTurnDecision(
                    "hold", "audio_turn_" + turn.reason if turn.hold
                    else "star_already_speaking",
                )
            # The old bridge omitted this already-supported director gate.
            # Reading the governor HERE (rather than caching a past healthy
            # profile) makes stale, disconnected or overloaded OBS telemetry
            # suppress optional speech BEFORE launching any TTS work.
            load_advice = None
            if self._load_governor is not None:
                try:
                    load_advice = self._load_governor.recommend(now_s=now / 1000)
                except ValueError:
                    self._pending_intent = None
                    return NaturalTurnDecision("hold", "resource_clock_invalid")
            intent = self._director.propose(
                now=now / 1000, voice_speaking=False,
                viewer_speaking=False, gameplay_critical=False,
                load_advice=load_advice,
            )
            if intent is None:
                self._pending_intent = None
                return NaturalTurnDecision("hold", "no_safe_event_due")
            self._pending_intent = intent
            self._counts["prepared"] += 1
            return NaturalTurnDecision(
                "prepare", "host_may_review_speech_intent", intent=intent,
            )

    def complete(
        self, intent: SpeechIntent, *, now_ms: float,
        host_confirmed_spoken: bool,
    ) -> bool:
        """Commit only the latest ticket after host-observed actual playback."""
        now = _time(now_ms)
        if type(host_confirmed_spoken) is not bool:
            raise ValueError("host speech observation must be bool")
        with self._lock:
            if self._last_now_ms is not None and now < self._last_now_ms:
                return False
            self._last_now_ms = now
            if (not self._enabled or self._stop_token is not None
                    or self._pending_intent is not intent):
                return False
            self._pending_intent = None
            return self._director.complete(
                intent, now=now / 1000, spoken=host_confirmed_spoken,
            )

    def metrics(self) -> dict[str, int | bool]:
        """Counts only; never return text, speaker identity or voice data."""
        with self._lock:
            return {
                **self._counts, "enabled": self._enabled,
                "stop_outstanding": self._stop_token is not None,
            }


__all__ = ["NaturalTurnBridge", "NaturalTurnDecision"]
