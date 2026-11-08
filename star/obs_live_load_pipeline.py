"""Opt-in end-to-end OBS live QoS admission for Star's gaming VTuber host.

The trusted Windows host obtains *authenticated*, read-only OBS WebSocket v5
GetStats and GetStreamStatus responses on the SAME pinned OBS process and
connection, captures both receipt times using ONE host monotonic clock, and
supplies host-measured game presentation, VRAM and speech latency data.

This component binds the paired OBS sampler to the existing resource governor.
It cannot authenticate model-supplied flags, open a socket, emit speech,
control games, or start/stop OBS. All downstream recommendations are advisory;
missing or contradictory evidence always prevents optional work.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Mapping

from .obs_aligned_live_sampler import ObsAlignedLiveSampler
from .stream_load_governor import StreamLoadAdvice, StreamLoadGovernor
from .stream_load_host_bridge import HostLoadReceipt, StreamLoadHostBridge


@dataclass(frozen=True)
class LiveLoadResult:
    """Sanitized observation result; never an action or broadcast permit."""

    status: str  # pending | accepted | rejected | disabled
    reason: str
    authorizes_broadcast: bool = False
    authorizes_game_input: bool = False
    authorizes_playback: bool = False


class ObsLiveLoadPipeline:
    """Session-bound, fail-closed OBS -> load governor pipeline.

    Two raw OBS snapshots are required for the first aligned interval, and
    three healthy accepted intervals before the existing governor may permit
    optional commentary. A failed/replayed/stale sample after acceptance
    invalidates the entire epoch rather than reusing a past green profile.

    The host MUST independently pin OBS PID + process creation time, websocket
    session and verified origin across every read and immediately stop this
    pipeline on identity change, event loss or any polling exception. These
    host requirements cannot be proven by the host_verified boolean alone.
    Live streaming observation is NOT private-recording attestation.
    """

    def __init__(
        self,
        *,
        governor: StreamLoadGovernor | None = None,
        max_response_span_ms: int = 250,
        max_age_ms: int = 750,
    ) -> None:
        if governor is not None and type(governor) is not StreamLoadGovernor:
            raise TypeError("governor must be a host-owned StreamLoadGovernor")
        self._governor = governor if governor is not None else StreamLoadGovernor()
        # A reused governor must never carry an earlier green profile into a
        # pipeline that has not yet been explicitly armed by the owner.
        self._governor.disable()
        self._sampler = ObsAlignedLiveSampler(
            max_response_span_ms=max_response_span_ms,
            max_age_ms=max_age_ms,
        )
        self._bridge = StreamLoadHostBridge(
            self._governor,
            max_receipt_skew_ms=max_response_span_ms,
            max_age_ms=max_age_ms,
            require_verified_stream_network=True,
        )
        self._lock = RLock()
        self._armed = False
        self._ever_accepted = False
        self._counts = dict(accepted=0, pending=0, rejected=0, disarmed=0)

    def arm(self, *, owner_approved: bool = False, obs_epoch: str) -> None:
        """Begin a new host-pinned OBS connection epoch without starting OBS."""
        with self._lock:
            if self._armed:
                raise RuntimeError("stop the current OBS epoch before rearming")
            # Arm sampler first. Bridge errors cannot leave sampler armed.
            self._sampler.arm(owner_approved=owner_approved, obs_epoch=obs_epoch)
            try:
                self._bridge.arm(
                    owner_approved=owner_approved,
                    obs_session_id=obs_epoch,
                )
            except Exception:
                self._sampler.stop()
                raise
            self._armed = True
            self._ever_accepted = False

    def _stop(self) -> None:
        self._sampler.stop()
        self._bridge.stop()
        if self._armed:
            self._counts["disarmed"] += 1
        self._armed = False
        self._ever_accepted = False

    def stop(self) -> None:
        """Invalidate all advice, even after disconnected OBS or host failure."""
        with self._lock:
            self._stop()

    def ingest(
        self,
        *,
        stats: Mapping[str, object],
        stream_status: Mapping[str, object],
        stats_received_ms: float,
        stream_received_ms: float,
        now_ms: float,
        receipt: HostLoadReceipt,
        host_verified: bool = False,
    ) -> LiveLoadResult:
        """Submit exactly one paired OBS read and independently measured load.

        The receipt's time and network drop percentage must match the aligned
        OBS interval. Do not synthesize any missing performance measurement.
        """
        with self._lock:
            if not self._armed:
                self._counts["rejected"] += 1
                return LiveLoadResult("disabled", "owner_approved_obs_epoch_missing")
            if host_verified is not True or type(receipt) is not HostLoadReceipt:
                self._counts["rejected"] += 1
                self._stop()
                return LiveLoadResult("rejected", "host_or_receipt_unverified")
            try:
                pair = self._sampler.ingest(
                    stats=stats,
                    stream_status=stream_status,
                    stats_received_ms=stats_received_ms,
                    stream_received_ms=stream_received_ms,
                    now_ms=now_ms,
                    host_verified=True,
                )
            except (ValueError, OverflowError, TypeError):
                pair = None
                self._sampler.stop()
            if pair is None:
                if not self._sampler.metrics()["armed"] or self._ever_accepted:
                    # Do not allow a previous green governor profile to live
                    # through an invalid sample, a reconnect, or lost frames.
                    self._counts["rejected"] += 1
                    self._stop()
                    return LiveLoadResult("rejected", "obs_continuity_not_proven")
                self._counts["pending"] += 1
                return LiveLoadResult("pending", "need_consecutive_obs_intervals")
            accepted = self._bridge.submit(
                obs=pair.render,
                stream_network=pair.network,
                receipt=receipt,
                now_ms=now_ms,
                host_verified=True,
            )
            if not accepted:
                self._counts["rejected"] += 1
                self._stop()
                return LiveLoadResult("rejected", "cross_source_load_mismatch")
            self._ever_accepted = True
            self._counts["accepted"] += 1
            return LiveLoadResult("accepted", "verified_load_interval")

    def recommend(self, *, now_ms: float) -> StreamLoadAdvice:
        """Query fresh admission at decision time, not a cached green result.

        Advice never grants a stream, game action, microphone or TTS permission.
        The caller's now_ms must share OBS response timestamps' monotonic clock.
        """
        with self._lock:
            return self._governor.recommend(now_s=now_ms / 1000.0)

    def metrics(self) -> dict[str, int | bool]:
        """No raw OBS data, filenames, game frames, or user-identifying fields."""
        with self._lock:
            return {**self._counts, "armed": self._armed}


__all__ = ["ObsLiveLoadPipeline", "LiveLoadResult"]
