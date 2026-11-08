"""Opt-in OBS/game/voice load receipts for the natural VTuber turn governor.

A trusted Windows host obtains OBS GetStats from an authenticated loopback
connection and derives intervals with ObsStatsWindow, separately measures
actual game presentation, GPU VRAM, network loss and first-audio latency,
then supplies this bounded, host-owned receipt. Missing sources are NOT zero.
The host must verify source identity and continuity outside this module.

This adapter never polls OBS, plays games, starts audio, publishes messages,
captures viewer identity, or authorizes broadcasting. It cannot authenticate
a caller: host_verified=True is a host assertion, NOT cryptographic proof.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import cast

from .obs_stats_window import ObsLagWindow
from .stream_load_governor import StreamLoadGovernor, StreamLoadSample

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_MAX_MS = 1e13


def _finite(value: object, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be host-measured numeric evidence")
    try:
        result = float(cast(float | int, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} outside host measurement bounds")
    return result


@dataclass(frozen=True)
class HostLoadReceipt:
    """Fresh synchronized host metrics, NOT model-generated estimates.

    network_dropped_pct must be derived from genuine GetStreamStatus network
    counters in the same session or be independently verified as not-applicable
    by an offline/nonbroadcast host. Never fill missing telemetry with zeros.
    """

    observed_at_ms: float
    game_p95_frame_ms: float
    game_target_fps: float
    gpu_vram_used_mb: float
    gpu_vram_total_mb: float
    tts_first_audio_p95_ms: float
    network_dropped_pct: float
    obs_connected: bool
    game_frame_count: int

    def __post_init__(self) -> None:
        _finite(self.observed_at_ms, "receipt time", 0, _MAX_MS)
        _finite(self.game_p95_frame_ms, "game p95 frame", 0.001, 10000)
        _finite(self.game_target_fps, "game target FPS", 1, 500)
        total = _finite(self.gpu_vram_total_mb, "VRAM total", 1, 1_000_000)
        _finite(self.gpu_vram_used_mb, "VRAM used", 0, total)
        _finite(self.tts_first_audio_p95_ms, "TTS first-audio p95", 0, 60000)
        _finite(self.network_dropped_pct, "OBS network loss", 0, 100)
        if type(self.obs_connected) is not bool:
            raise ValueError("OBS connected state must be a measured boolean")
        if type(self.game_frame_count) is not int or not 10 <= self.game_frame_count <= 100000:
            raise ValueError("host game presentation evidence requires >=10 real frames")


class StreamLoadHostBridge:
    """Strict host boundary between OBS intervals and StreamLoadGovernor.

    Only trusted host code may call arm/submit; chat and models cannot. A bad
    or unverified sample disarms the session immediately, even after a healthy
    reading. Re-arming requires an explicit, fresh owner-approved session with
    a different OBS epoch; a reboot/reconnect never inherits a healthy state.

    A passing receipt provides *advisory workload admission* only. It cannot
    attest continuous OBS status, game skill, actual spoken words or streams.
    """

    def __init__(
        self,
        governor: StreamLoadGovernor,
        *,
        max_receipt_skew_ms: int = 250,
        max_age_ms: int = 750,
    ) -> None:
        if type(governor) is not StreamLoadGovernor:
            raise TypeError("expected a host-owned StreamLoadGovernor")
        if type(max_receipt_skew_ms) is not int or not 50 <= max_receipt_skew_ms <= 1000:
            raise ValueError("receipt skew must be 50..1000 ms")
        if type(max_age_ms) is not int or not 100 <= max_age_ms <= 2000:
            raise ValueError("age limit must be 100..2000 ms")
        self._lock = RLock()
        self._governor = governor
        self._skew = max_receipt_skew_ms
        self._age = max_age_ms
        self._armed = False
        self._session_id: str | None = None
        self._used_sessions: set[str] = set()
        self._last_obs_end_ms: float | None = None
        self._last_now_ms: float | None = None
        self._seq = 0
        self._stats = dict(accepted=0, rejected=0, sessions=0, disarmed=0)

    def arm(self, *, owner_approved: bool = False, obs_session_id: str) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required before OBS observation")
        if type(obs_session_id) is not str or not _ID.fullmatch(obs_session_id):
            raise ValueError("bounded host OBS session ID required")
        with self._lock:
            if self._armed or obs_session_id in self._used_sessions:
                raise RuntimeError("OBS session already active or previously used")
            # A previously enabled/shared governor must never bring an old
            # green profile into a newly approved OBS process epoch.
            self._governor.disable()
            self._governor.enable(owner_approved=True)
            self._armed = True
            self._session_id = obs_session_id
            self._used_sessions.add(obs_session_id)
            self._last_obs_end_ms = None
            self._last_now_ms = None
            self._seq = 0
            self._stats["sessions"] += 1

    def _disarm(self) -> None:
        self._governor.disable()
        if self._armed:
            self._stats["disarmed"] += 1
        self._armed = False
        self._session_id = None
        self._last_obs_end_ms = None
        self._last_now_ms = None

    def stop(self) -> None:
        with self._lock:
            self._disarm()

    def submit(
        self,
        *,
        obs: ObsLagWindow,
        receipt: HostLoadReceipt,
        now_ms: float,
        host_verified: bool = False,
    ) -> bool:
        """Accept only a fresh, nonreplayed, continuous OBS/game interval.

        Trusted host must derive obs using ObsStatsWindow on verified GetStats
        transport. Failures immediately revoke the governor's prior healthy
        state; false never means permission to produce a stream or game input.
        """
        with self._lock:
            if not self._armed:
                self._stats["rejected"] += 1
                return False
            try:
                if host_verified is not True:
                    raise ValueError("host authentication missing")
                if type(obs) is not ObsLagWindow or type(receipt) is not HostLoadReceipt:
                    raise ValueError("typed host OBS and game receipts required")
                now = _finite(now_ms, "current host time", 0, _MAX_MS)
                end = _finite(obs.observed_ms, "OBS sample time", 0, _MAX_MS)
                duration = _finite(obs.window_ms, "OBS interval", 100, 5000)
                render = _finite(obs.render_lag_pct, "OBS render loss", 0, 100)
                encode = _finite(obs.output_lag_pct, "OBS output loss", 0, 100)
                source = receipt.observed_at_ms
                if (
                    end > now
                    or now - end > self._age
                    or abs(source - end) > self._skew
                    or source > now
                    or source < end - duration
                    or (self._last_obs_end_ms is not None and end - duration < self._last_obs_end_ms)
                    or (self._last_now_ms is not None and now < self._last_now_ms)
                ):
                    raise ValueError("OBS and game evidence not synchronized")
                # Avoid turning impossible fast/overlapping observations into a
                # healthy recovery streak. OBS must have progressed since last.
                if self._last_obs_end_ms is not None and end <= self._last_obs_end_ms:
                    raise ValueError("replayed or reversed OBS interval")
                sample = StreamLoadSample(
                    sample_id=f"host{self._stats['sessions']}:{self._seq + 1}",
                    measured_at_s=end / 1000.0,
                    game_p95_frame_ms=receipt.game_p95_frame_ms,
                    game_target_fps=receipt.game_target_fps,
                    obs_render_missed_pct=render,
                    # OBS output-skipped is an encoder/output pressure proxy,
                    # not an independently diagnosed hardware encode failure.
                    obs_encode_skipped_pct=encode,
                    obs_network_dropped_pct=receipt.network_dropped_pct,
                    gpu_vram_used_mb=receipt.gpu_vram_used_mb,
                    gpu_vram_total_mb=receipt.gpu_vram_total_mb,
                    tts_first_audio_p95_ms=receipt.tts_first_audio_p95_ms,
                    obs_connected=receipt.obs_connected,
                )
                if not self._governor.ingest(
                    sample,
                    now_s=now / 1000.0,
                    host_verified=True,
                ):
                    raise ValueError("resource governor rejected OBS/game evidence")
            except (ValueError, OverflowError):
                self._stats["rejected"] += 1
                self._disarm()
                return False
            self._seq += 1
            self._last_obs_end_ms = end
            self._last_now_ms = now
            self._stats["accepted"] += 1
            return True

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._stats, "armed": self._armed}


__all__ = ["HostLoadReceipt", "StreamLoadHostBridge"]
