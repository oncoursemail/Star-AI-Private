"""Optional host-only pairing of OBS v5 live render and network QoS windows.

The trusted Windows host makes *authenticated* GetStats and GetStreamStatus
read-only calls, captures both response receipt times on one monotonic clock,
and passes ONLY the two responseData mappings. This does not open a socket,
turn on OBS, authenticate raw model inputs, or grant stream permission.

Live streaming and private nonbroadcast recording are separate modes: this
sampler ONLY accepts an already active, nonreconnecting live stream. Raw
responses, stream keys, window titles, and user information are never stored.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from threading import RLock
from typing import Mapping

from .obs_stats_window import ObsLagWindow, ObsStatsWindow, _valid_clock
from .obs_stream_loss_window import ObsStreamLossSampler, ObsStreamLossWindow

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z", re.ASCII)


@dataclass(frozen=True)
class ObsAlignedLiveWindow:
    """Two complete consecutive OBS intervals from the same host clock."""

    render: ObsLagWindow
    network: ObsStreamLossWindow
    authorizes_broadcast: bool = False
    authorizes_game_input: bool = False


class ObsAlignedLiveSampler:
    """Fail-closed OBS stream load evidence, explicitly owner-armed per epoch.

    Do not use this as an OBS transport client. An authenticated trusted host
    must pin OBS process/PID+creation time and websocket session identity, and
    must call stop when either changes. host_verified is a host assertion, not
    a signature. Two fresh valid observations are required after each arm.
    """

    def __init__(self, *, max_response_span_ms: int = 250, max_age_ms: int = 750) -> None:
        if type(max_response_span_ms) is not int or not 50 <= max_response_span_ms <= 500:
            raise ValueError("OBS cross-response span must be 50..500 ms")
        if type(max_age_ms) is not int or not 100 <= max_age_ms <= 2000:
            raise ValueError("OBS evidence age must be 100..2000 ms")
        self._span = max_response_span_ms
        self._age = max_age_ms
        self._render = ObsStatsWindow()
        self._network = ObsStreamLossSampler()
        self._lock = RLock()
        self._armed = False
        self._current_epoch: str | None = None
        self._used_epochs: set[str] = set()
        self._last_now: float | None = None
        self._counts = dict(accepted=0, rejected=0, pending=0, disarmed=0)

    def arm(self, *, owner_approved: bool = False, obs_epoch: str) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for live OBS observation")
        if type(obs_epoch) is not str or _EPOCH.fullmatch(obs_epoch) is None:
            raise ValueError("a bounded OBS host process/connection epoch is required")
        with self._lock:
            if self._armed or obs_epoch in self._used_epochs:
                raise RuntimeError("current or previous OBS epoch cannot be reused")
            self._render.reset()
            self._network.reset()
            self._last_now = None
            self._current_epoch = obs_epoch
            self._used_epochs.add(obs_epoch)
            self._armed = True

    def _stop(self) -> None:
        self._render.reset()
        self._network.reset()
        self._last_now = None
        self._current_epoch = None
        if self._armed:
            self._counts["disarmed"] += 1
        self._armed = False

    def stop(self) -> None:
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
        host_verified: bool = False,
    ) -> ObsAlignedLiveWindow | None:
        """Join only fresh, synchronized, monotonically progressing OBS reads.

        A broken source/clock/stream epoch disarms the whole sampler. A first
        valid observation or too few frames simply waits for more evidence.
        Host must separately verify the real origin/identity of both replies.
        """
        with self._lock:
            if not self._armed:
                self._counts["rejected"] += 1
                return None
            try:
                if host_verified is not True:
                    raise ValueError("trusted OBS connection required")
                at_stats = _valid_clock(stats_received_ms)
                at_stream = _valid_clock(stream_received_ms)
                now = _valid_clock(now_ms)
                if (
                    abs(at_stats - at_stream) > self._span
                    or max(at_stats, at_stream) > now
                    or now - min(at_stats, at_stream) > self._age
                    or (self._last_now is not None and now <= self._last_now)
                ):
                    raise ValueError("OBS response span, age or clock invalid")
                if not isinstance(stats, Mapping) or not isinstance(stream_status, Mapping):
                    raise ValueError("typed OBS responseData mappings required")
                # Samples are projected and checked independently. Any source
                # failure revokes both baselines, not just the failing one.
                before_r = self._render.metrics()["resets"]
                before_n = self._network.metrics()["resets"]
                render = self._render.ingest(stats, host_ms=at_stats, host_verified=True)
                network = self._network.ingest(stream_status, host_ms=at_stream, host_verified=True)
                if self._render.metrics()["resets"] != before_r or self._network.metrics()["resets"] != before_n:
                    raise ValueError("OBS counter epoch reset or stream reconnect")
            except (ValueError, OverflowError, TypeError):
                self._counts["rejected"] += 1
                self._stop()
                return None
            self._last_now = now
            if render is None or network is None:
                self._counts["pending"] += 1
                return None
            if (
                abs(render.observed_ms - network.observed_ms) > self._span
                or abs(render.window_ms - network.window_ms) > self._span
            ):
                self._counts["rejected"] += 1
                self._stop()
                return None
            self._counts["accepted"] += 1
            return ObsAlignedLiveWindow(render, network)

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._counts, "armed": self._armed}


__all__ = ["ObsAlignedLiveSampler", "ObsAlignedLiveWindow"]
