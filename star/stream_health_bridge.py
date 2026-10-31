"""Safe join between OBS GetStats windows and host resource-admission advice.

Read-only, offline, owner-opt-in coordinator. OBS render/output counters and
VRAM/game/voice telemetry are produced by an authenticated Windows host, not
by an LLM or a viewer. This module does NOT connect to OBS, run work, change
system settings, publish chat, or grant game/device permissions.

A missing or non-progressing live OBS window, or a stream output that is not
independently confirmed active, must never count as healthy stream evidence. One distinct OBS window can contribute to at most
one admitted live resource sample; repeated polling cannot fake recovery.
"""
from __future__ import annotations

import math
from threading import RLock
from typing import Mapping, cast

from .obs_stats_window import ObsLagWindow, ObsStatsWindow
from .stream_admission import AdmissionAdvice, StreamAdmissionGate, StreamHealthSample
from .stream_budget import StreamTelemetry

_CRITICAL = frozenset({"gameplay", "speech"})
_MAX_CLOCK_MS = 1e13


def _host_clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host clock must be a finite nonnegative number")
    try:
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("host clock must be a finite nonnegative number") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK_MS:
        raise ValueError("host clock must be a finite nonnegative number")
    return number


class StreamHealthBridge:
    """Fail-closed *advice* joining independent, authenticated sensor streams.

    Windows host sequence (no network access from this class):
      enable -> offer_stream_status(GetStreamStatus) -> offer_obs(GetStats)
      twice -> offer_host(telemetry) -> advise
    Refresh both feeds for each OBS interval. Always call obs_reset on OBS
    reconnect or stream/recording transition; disable on host session end.

    OBS "output skipped" is output-thread pressure, not a network-drop metric.
    The trusted host must independently verify that OBS is running its intended
    output and that sensor data comes from the right machine/session.
    """

    def __init__(self, *, max_obs_age_ms: int = 1000) -> None:
        if type(max_obs_age_ms) is not int or not 250 <= max_obs_age_ms <= 1500:
            raise ValueError("max_obs_age_ms must be an integer in 250..1500")
        self._max_obs_age_ms = max_obs_age_ms
        self._lock = RLock()
        self._obs = ObsStatsWindow()
        self._gate = StreamAdmissionGate()
        self._enabled = False
        self._latest: ObsLagWindow | None = None
        self._used_obs_ms: float | None = None
        self._last_host_ms: float | None = None
        self._ready_host_ms: float | None = None
        self._last_live: bool | None = None
        self._stream_status_ms: float | None = None
        self._stream_active: bool | None = None
        # Busy until a trusted status explicitly confirms the output stopped.
        self._stream_output_busy = False
        self._counts = {
            "obs_windows": 0, "host_admitted": 0, "host_rejected": 0,
            "bridge_deferrals": 0, "obs_invalidated": 0,
            "output_verified": 0, "output_invalidated": 0,
            "output_mode_mismatch": 0,
        }

    def _reset(self) -> None:
        self._latest = None
        self._used_obs_ms = None
        self._last_host_ms = None
        self._ready_host_ms = None
        self._last_live = None
        self._stream_status_ms = None
        self._stream_active = None
        self._stream_output_busy = False
        self._obs.reset()

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("bridge requires authorized local host opt-in")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before starting another session")
            self._reset()
            self._gate.enable(owner_approved=True)
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._reset()
            self._gate.disable()

    def obs_reset(self) -> None:
        """Invalidate all OBS evidence immediately on reconnect/output change."""
        with self._lock:
            self._obs.reset()
            self._latest = None
            self._used_obs_ms = None
            self._ready_host_ms = None
            self._stream_status_ms = None
            self._stream_active = None
            # Reconnecting OBS does not prove the stream has stopped.
            # Retain _stream_output_busy until verified stopped status.
            self._counts["obs_invalidated"] += 1

    def offer_stream_status(self, data: Mapping[str, object], *, host_ms: float,
                            host_verified: bool = False) -> bool:
        """Require independently attested OBS GetStreamStatus for live work.

        GetStats counters can advance in preview without a live broadcast.
        A status needs strict outputActive and outputReconnecting booleans.
        Stop/reconnect/malformed trusted status invalidates previous evidence.
        The authenticated host must enforce source identity/session binding.
        """
        at = _host_clock(host_ms)
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be a strict boolean")
        with self._lock:
            if not self._enabled or not host_verified:
                return False
            if self._stream_status_ms is not None and at <= self._stream_status_ms:
                return False
            if not isinstance(data, Mapping):
                # Malformed trusted status invalidates readiness; unlike an
                # unverified packet it must never preserve old admissions.
                self._stream_status_ms = at
                self._stream_active = None
                self._stream_output_busy = True
                self._obs.reset()
                self._latest = None
                self._ready_host_ms = None
                self._counts["output_invalidated"] += 1
                raise TypeError("GetStreamStatus responseData must be a mapping")
            active = data.get("outputActive")
            reconnecting = data.get("outputReconnecting")
            if type(active) is not bool or type(reconnecting) is not bool:
                self._stream_status_ms = at
                self._stream_active = None
                self._stream_output_busy = True
                self._obs.reset()
                self._latest = None
                self._ready_host_ms = None
                self._counts["output_invalidated"] += 1
                raise ValueError("OBS stream status requires strict active/reconnecting flags")
            healthy = active and not reconnecting
            previously_healthy = self._stream_active is True
            self._stream_status_ms = at
            self._stream_active = healthy
            self._stream_output_busy = active or reconnecting
            self._counts["output_verified"] += 1
            if not healthy or not previously_healthy:
                self._obs.reset()
                self._latest = None
                self._ready_host_ms = None
                self._counts["output_invalidated"] += 1
            return healthy

    def offer_obs(self, data: Mapping[str, object], *, host_ms: float,
                  host_verified: bool = False) -> ObsLagWindow | None:
        """Consume only the four OBS counters; an incomplete window is unknown.

        A verified yet malformed, reset, idle, too-short or long-gap reading
        invalidates live readiness. Never silently convert missing output to
        0% skip rate.
        """
        with self._lock:
            if not self._enabled:
                return None
            try:
                window = self._obs.ingest(
                    data, host_ms=host_ms, host_verified=host_verified,
                )
            except (ValueError, TypeError):
                self._latest = None
                self._ready_host_ms = None
                self._counts["obs_invalidated"] += 1
                raise
            if host_verified is True:
                self._latest = window
                self._ready_host_ms = None
                if window is None:
                    self._counts["obs_invalidated"] += 1
                else:
                    self._counts["obs_windows"] += 1
            return window

    def offer_host(self, telemetry: StreamTelemetry, *, host_ms: float,
                   host_verified: bool = False) -> bool:
        """Join one host snapshot to one fresh, distinct OBS window if live."""
        at = _host_clock(host_ms)
        if not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be a validated StreamTelemetry")
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be a strict boolean")
        with self._lock:
            if not self._enabled:
                return False
            if (not host_verified or
                    (self._last_host_ms is not None and at <= self._last_host_ms)):
                self._counts["host_rejected"] += 1
                return False
            # A signed live transition may not reuse the previous *offline*
            # admission sample, even if OBS is disconnected at that instant.
            self._last_host_ms = at
            self._ready_host_ms = None
            if not telemetry.live and self._stream_output_busy:
                # Live=False cannot unlock offline jobs during an OBS output,
                # reconnect, or invalid previously-active output status.
                self._last_live = True
                self._counts["host_rejected"] += 1
                self._counts["output_mode_mismatch"] += 1
                return False
            self._last_live = telemetry.live
            render = output = 0.0
            window = self._latest
            if telemetry.live:
                # OBS preview counters alone do not prove an active stream.
                if (self._stream_active is not True
                        or self._stream_status_ms is None
                        or self._stream_status_ms > at
                        or at - self._stream_status_ms > self._max_obs_age_ms):
                    self._counts["host_rejected"] += 1
                    return False
                if (window is None
                        or window.observed_ms > at
                        or at - window.observed_ms > self._max_obs_age_ms
                        or (self._used_obs_ms is not None and
                            window.observed_ms <= self._used_obs_ms)):
                    self._counts["host_rejected"] += 1
                    return False
                render = window.render_lag_pct
                output = window.output_lag_pct
            accepted = self._gate.observe(
                StreamHealthSample(
                    observed_ms=at,
                    telemetry=telemetry,
                    obs_render_lag_pct=render,
                    obs_encode_lag_pct=output,
                    host_verified=True,
                )
            )
            if not accepted:
                self._counts["host_rejected"] += 1
                return False
            if telemetry.live and window is not None:
                self._used_obs_ms = window.observed_ms
            self._ready_host_ms = at
            self._counts["host_admitted"] += 1
            return True

    def advise(self, kind: str, *, now_ms: float) -> AdmissionAdvice:
        """Return bounded scheduling advice, never authority to execute work."""
        now = _host_clock(now_ms)
        with self._lock:
            advice = self._gate.advise(kind, now_ms=now)
            if kind in _CRITICAL or not advice.allowed:
                return advice
            # Even if the admission gate still has a healthy sample, a newer
            # live transition, missing OBS frame, or OBS reconnect invalidates
            # its provenance until a new, matched host sample arrives.
            live_window_missing = bool(
                self._last_live is True
                and (self._latest is None
                     or self._latest.observed_ms > now
                     or now - self._latest.observed_ms > self._max_obs_age_ms)
            )
            live_status_missing = bool(
                self._last_live is True
                and (self._stream_active is not True
                     or self._stream_status_ms is None
                     or self._stream_status_ms > now
                     or now - self._stream_status_ms > self._max_obs_age_ms)
            )
            if (not self._enabled or self._ready_host_ms is None
                    or self._ready_host_ms != self._last_host_ms
                    or live_window_missing or live_status_missing):
                self._counts["bridge_deferrals"] += 1
                return AdmissionAdvice(False, "deferred", 0.0,
                                       "obs_or_host_evidence_missing")
            return advice

    def metrics(self) -> dict[str, int | bool]:
        """Bounded numeric counters only: no OBS payloads, chat, or identities."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "live": self._last_live is True,
                    "overloaded": bool(self._gate.metrics()["overloaded"])}


__all__ = ["StreamHealthBridge"]
