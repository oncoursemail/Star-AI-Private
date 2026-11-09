"""Fresh pre-playback witness for Star's opt-in, natural gaming VTuber.

The expensive reply/TTS preparation may have begun when chat was quiet, but
the *first audible PCM* can arrive after an owner speaks, a game becomes
critical, OBS loses headroom, or the game scene changes. Call this evaluator
from the trusted host immediately BEFORE issuing PCM to the physical device.

It is a deterministic, privacy-minimal adviser. No microphone, keys, game,
OBS, audio transport, or broadcast permissions are controlled. A host must
independently authenticate and timestamp its VAD, scene and load readings.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import cast

from .stream_turntaking import TurnAdvice

_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_ROUTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_CLOCK_S = 1e10


def _clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host time must be finite monotonic seconds")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("host time must be finite monotonic seconds") from exc
    if not math.isfinite(result):
        raise ValueError("host time must be finite monotonic seconds")
    if not 0 <= result <= _MAX_CLOCK_S:
        raise ValueError("host clock outside permitted range")
    return result


@dataclass(frozen=True)
class PreplayWitness:
    """One fresh trusted-host snapshot; never microphone samples or raw chat.

    This does not itself prove source authenticity. The caller must obtain
    TurnAdvice from a fresh independently supplied VAD observation, not an
    old cached decision or an LLM-generated claim.
    """
    observed_at_s: float
    turn: TurnAdvice
    game_scope: str = ""
    gameplay_critical: bool = False
    stream_pressure: bool = False
    pcm_output_ready: bool = False
    host_verified: bool = False
    voice_route_id: str = ""  # exact TTS/runtime/output route, never viewer supplied

    def __post_init__(self) -> None:
        _clock(self.observed_at_s)
        if not isinstance(self.turn, TurnAdvice):
            raise TypeError("typed turn advice required")
        if type(self.game_scope) is not str or (
            self.game_scope and _SCOPE.fullmatch(self.game_scope) is None
        ):
            raise ValueError("host-pinned game scope required")
        for field in ("gameplay_critical", "stream_pressure",
                      "pcm_output_ready", "host_verified"):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f"{field} must be an explicit boolean")
        if (type(self.voice_route_id) is not str
                or (self.voice_route_id and _ROUTE.fullmatch(self.voice_route_id) is None)):
            raise ValueError("voice_route_id must be a canonical host route or empty")


@dataclass(frozen=True)
class PreplayAdvice:
    eligible: bool
    reason: str
    authorizes_audio_output: bool = False
    authorizes_broadcast: bool = False


def assess_preplay(
    *, kind: str, evidence: str, game_scope: str,
    witness: PreplayWitness, now_s: float,
    max_witness_age_s: float = 0.075,
    expected_voice_route_id: str = "",
) -> PreplayAdvice:
    """Fail quiet when speech opportunity changed during TTS generation.

    A critical-game callout is permitted only for independently OBSERVED game
    danger; other commentary can wait. Owner interruptions *also* need a
    verified quiet turn before Star begins her next response.
    """
    now = _clock(now_s)
    age_limit = _clock(max_witness_age_s)
    if not 0.01 <= age_limit <= 0.25:
        raise ValueError("witness freshness bound must be 10..250ms")
    if not isinstance(witness, PreplayWitness):
        raise TypeError("trusted preplay snapshot required")
    if (type(expected_voice_route_id) is not str
            or (expected_voice_route_id
                and _ROUTE.fullmatch(expected_voice_route_id) is None)):
        raise ValueError("expected_voice_route_id must be a canonical host route or empty")
    if type(kind) is not str or kind not in {
        "owner_interrupt", "game_danger", "game_success", "viewer_question",
        "game_observation", "viewer_comment", "ambient",
    }:
        raise ValueError("unsupported event type")
    if evidence not in ("observed", "reported", "unknown"):
        raise ValueError("unknown evidence classification")
    if type(game_scope) is not str or (
        game_scope and _SCOPE.fullmatch(game_scope) is None
    ):
        raise ValueError("invalid game scope")

    if not witness.host_verified:
        return PreplayAdvice(False, "trusted_host_snapshot_missing")
    if witness.observed_at_s > now or now - witness.observed_at_s > age_limit:
        return PreplayAdvice(False, "snapshot_stale_or_future")
    if not witness.pcm_output_ready:
        return PreplayAdvice(False, "pcm_device_not_ready")
    if expected_voice_route_id and witness.voice_route_id != expected_voice_route_id:
        return PreplayAdvice(False, "voice_route_changed_or_unverified")
    if witness.turn.action == "yield_owner":
        return PreplayAdvice(False, "owner_barge_in_yield")
    if witness.turn.action != "speak" or witness.turn.should_interrupt:
        return PreplayAdvice(False, "another_speaker_or_uncertain_quiet")
    if kind.startswith("game_") and (
        not game_scope or witness.game_scope != game_scope
    ):
        return PreplayAdvice(False, "game_scene_changed_or_unpinned")
    if witness.stream_pressure and kind != "owner_interrupt":
        return PreplayAdvice(False, "stream_audio_or_render_pressure")
    if (witness.gameplay_critical
            and not (kind == "game_danger" and evidence == "observed")
            and kind != "owner_interrupt"):
        return PreplayAdvice(False, "critical_gameplay_requires_silence")
    return PreplayAdvice(True, "fresh_quiet_playback_candidate")


__all__ = ["PreplayWitness", "PreplayAdvice", "assess_preplay"]