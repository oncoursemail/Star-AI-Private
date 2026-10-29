"""Opt-in, LOCAL read-only OBS WebSocket sampler for Star's paired benchmark.

Provides the missing capture side of the offline GetStats/GetStreamStatus
quality gates. It neither starts a broadcast nor touches sources, microphones,
games, stream settings, viewer data or media. Every request is a read-only
OBS 5.x method; authentication is supplied only by an owner-approved host.

Polling cannot prove that a very short reconnect did not happen between
samples. Unless an *independent, trusted event monitor* explicitly attests to
an uninterrupted interval, resulting transport evidence is marked disrupted
and cannot qualify a proposed faster AI configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import secrets
import time
from threading import Lock
from typing import Callable

from .clips_obs import _obs_client
from .obs_stream_event_witness import ObsStreamContinuityWitness
from .stream_network_qos_gate import ObsStreamStatus, ObsTransportWindow
from .stream_obs_qos_gate import ObsFrameWindow, ObsStatsCounters, _id


class ObsProbeError(RuntimeError):
    """No trustworthy measurement; sanitized to avoid third-party secret leaks."""


def local_obs_process_identity() -> tuple[int, float]:
    """Locate exactly one local OBS process using PID AND OS creation time.

    psutil is installed with the opt-in desktop prerequisites. The identity
    must be rechecked throughout each test; a restart invalidates the window.
    """
    try:
        import psutil
    except ImportError as exc:
        raise ObsProbeError("OBS process identity requires desktop psutil") from exc
    found: list[tuple[int, float]] = []
    try:
        for process in psutil.process_iter(["name", "pid", "create_time"]):
            if (process.info["name"] or "").lower() in {"obs64.exe", "obs.exe", "obs"}:
                found.append((process.info["pid"], process.info["create_time"]))
    except (psutil.Error, OSError, KeyError, TypeError) as exc:
        raise ObsProbeError("OBS process identity unavailable") from exc
    if len(found) != 1:
        raise ObsProbeError("exactly one local OBS process is required")
    return found[0]


def _clock_ms(clock: Callable[[], float]) -> float:
    try:
        value = clock()
        if type(value) not in (int, float):
            raise ValueError("invalid monotonic clock type")
        result = float(value)
        if not math.isfinite(result) or not 0 <= result <= 1e13:
            raise ValueError("invalid monotonic clock value")
        return result
    except Exception as exc:
        raise ObsProbeError("trusted monotonic clock unavailable") from exc


def _snapshot(client: object) -> tuple[ObsStatsCounters, ObsStreamStatus]:
    """Read exactly two allowlisted OBS response projections.

    obsws-python exposes snake_case object attributes (not protocol camelCase).
    Never retain/log any other response attributes, websocket error text,
    stream key, endpoint, window title, chat, scene name or media.
    """
    stats = client.get_stats()
    status = client.get_stream_status()
    return (
        ObsStatsCounters(
            getattr(stats, "render_total_frames"),
            getattr(stats, "render_skipped_frames"),
            getattr(stats, "output_total_frames"),
            getattr(stats, "output_skipped_frames"),
        ),
        ObsStreamStatus(
            getattr(status, "output_active"),
            getattr(status, "output_reconnecting"),
            getattr(status, "output_duration"),
            getattr(status, "output_bytes"),
            getattr(status, "output_skipped_frames"),
            getattr(status, "output_total_frames"),
            getattr(status, "output_congestion"),
        ),
    )


@dataclass(frozen=True)
class CapturedObsEvidence:
    """One aligned observation pair, with no arbitrary source fields."""

    frames: ObsFrameWindow
    transport: ObsTransportWindow
    continuity_attested: bool

    def jsonl_rows(self) -> tuple[str, str]:
        """Return allowlisted JSONL for existing *offline* gate readers.

        Deliberately no file I/O, no credential/stream metadata. Consumers
        provide explicit storage policy and record both rows together.
        """
        frame = {
            "pair_id": self.frames.pair_id, "variant": self.frames.variant,
            "game_id": self.frames.game_id, "game_version": self.frames.game_version,
            "session_id": self.frames.session_id,
            "start_ms": self.frames.start_ms, "end_ms": self.frames.end_ms,
            "before": _frame_dict(self.frames.before),
            "after": _frame_dict(self.frames.after),
            "stream_active": self.frames.stream_active,
            "reconnect_observed": self.frames.reconnect_observed,
        }
        transport = {
            "pair_id": self.transport.pair_id, "variant": self.transport.variant,
            "game_id": self.transport.game_id, "game_version": self.transport.game_version,
            "session_id": self.transport.session_id,
            "start_ms": self.transport.start_ms, "end_ms": self.transport.end_ms,
            "before": _transport_dict(self.transport.before),
            "after": _transport_dict(self.transport.after),
            "reconnect_observed": self.transport.reconnect_observed,
        }
        return (json.dumps(frame, sort_keys=True), json.dumps(transport, sort_keys=True))


def _frame_dict(counters: ObsStatsCounters) -> dict[str, int]:
    return {
        "renderTotalFrames": counters.render_total,
        "renderSkippedFrames": counters.render_skipped,
        "outputTotalFrames": counters.output_total,
        "outputSkippedFrames": counters.output_skipped,
    }


def _transport_dict(status: ObsStreamStatus) -> dict[str, object]:
    # Translate only seven already-projected transport attributes.
    return {
        "outputActive": status.active,
        "outputReconnecting": status.reconnecting,
        "outputDuration": status.duration_ms,
        "outputBytes": status.bytes_sent,
        "outputSkippedFrames": status.skipped_frames,
        "outputTotalFrames": status.total_frames,
        "outputCongestion": status.congestion,
    }


class ObsReadOnlyProbe:
    """Owner-opted capture adapter; not an autonomous stream permission.

    The optional continuity_guard is a callable supplied by a trusted local
    OBS event observer which returns True ONLY if an uninterrupted event feed
    attested zero state changes throughout the exact capture interval. The
    caller owns arming/resetting that observer before capture. Without such
    proof the capture is valid descriptive telemetry but strictly ineligible
    for promotion in the downstream OBS transport gate.

    A successful capture is still not proof of better neural intelligence,
    viewer experience or a safe production model swap.
    """

    def __init__(
        self, *,
        client_factory: Callable[..., object] = _obs_client,
        process_identity: Callable[[], tuple[int, float]] = local_obs_process_identity,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not all(callable(fn) for fn in
                   (client_factory, process_identity, clock_ms, sleep)):
            raise TypeError("all OBS capture dependencies must be callables")
        self._client_factory = client_factory
        self._identity = process_identity
        self._clock = clock_ms
        self._sleep = sleep
        self._capture_lock = Lock()
        self._client: object | None = None
        self._process: tuple[int, float] | None = None
        self._session: str | None = None

    def connect(self, *, password: str, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("authorized owner must enable local OBS inspection")
        if type(password) is not str or not 1 <= len(password) <= 256:
            raise ValueError("provide OBS's authenticated WebSocket password")
        if self._client is not None:
            raise RuntimeError("disconnect before opening another OBS session")
        client = None
        try:
            identity = self._identity()
            if not (type(identity) is tuple and len(identity) == 2
                    and type(identity[0]) is int and identity[0] > 0
                    and type(identity[1]) in (int, float)
                    and math.isfinite(identity[1]) and identity[1] > 0):
                raise ValueError("invalid OS process identity")
            client = self._client_factory(
                host="127.0.0.1", port=4455, password=password, timeout=3
            )
            client.get_version()  # Does not alter OBS settings.
            if self._identity() != identity:
                raise ValueError("OBS restarted during connection")
        except Exception:
            # Some SDKs open a socket before the first request fails. Close it
            # without exposing the third-party exception or its credentials.
            if client is not None:
                disconnect = getattr(client, "disconnect", None)
                if callable(disconnect):
                    try:
                        disconnect()
                    except Exception:
                        pass
            raise ObsProbeError("cannot verify local authenticated OBS session") from None
        self._client = client
        self._process = identity
        self._session = "obs_" + secrets.token_hex(12)

    def disconnect(self) -> None:
        client = self._client
        self._client = None
        self._process = None
        self._session = None
        # No OBS stop/start methods are ever called. Only close the socket if
        # this SDK provides a public disconnect method.
        if client is not None:
            close = getattr(client, "disconnect", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def capture(
        self, *, pair_id: str, variant: str, game_id: str, game_version: str,
        duration_s: int = 10, poll_interval_s: float = 1.0,
        continuity_guard: Callable[[], bool] | None = None,
        event_witness: ObsStreamContinuityWitness | None = None,
    ) -> CapturedObsEvidence:
        """Non-reentrant measurement entry; host disconnect remains available."""
        if not self._capture_lock.acquire(blocking=False):
            raise ObsProbeError("another OBS capture is already active")
        try:
            return self._capture_once(
                pair_id=pair_id, variant=variant, game_id=game_id,
                game_version=game_version, duration_s=duration_s,
                poll_interval_s=poll_interval_s, continuity_guard=continuity_guard,
                event_witness=event_witness,
            )
        finally:
            self._capture_lock.release()

    def _capture_once(
        self, *, pair_id: str, variant: str, game_id: str, game_version: str,
        duration_s: int, poll_interval_s: float,
        continuity_guard: Callable[[], bool] | None,
        event_witness: ObsStreamContinuityWitness | None,
    ) -> CapturedObsEvidence:
        """Capture a bounded, already-running OBS stream; never start output.

        Must be called only on a non-hot-path benchmark worker. Process
        identity is checked around every RPC; missing, stale, reset,
        reconnecting or interrupted streams abort. This is deliberately
        stricter than the offline analysis's ability to report regressions.
        """
        for name, value in (
            ("pair_id", pair_id), ("game_id", game_id), ("game_version", game_version)
        ):
            _id(value, name)
        if variant not in ("baseline", "candidate"):
            raise ValueError("precommitted variant must be baseline or candidate")
        if type(duration_s) is not int or not 3 <= duration_s <= 300:
            raise ValueError("capture duration must be 3..300 seconds")
        if type(poll_interval_s) not in (int, float) or not (
            math.isfinite(poll_interval_s) and 0.25 <= poll_interval_s <= 2.0
        ):
            raise ValueError("poll interval must be 0.25..2 seconds")
        if continuity_guard is not None and not callable(continuity_guard):
            raise TypeError("continuity guard must be an independent host callback")
        if event_witness is not None and not isinstance(
            event_witness, ObsStreamContinuityWitness
        ):
            raise TypeError("event witness must use the verified OBS event protocol")
        if event_witness is not None and continuity_guard is not None:
            raise ValueError("choose one continuity source, not both")
        if self._client is None or self._process is None or self._session is None:
            raise PermissionError("connect an owner-approved OBS host first")
        session = self._session
        try:
            # Start the authenticated output-event interval BEFORE the first
            # telemetry sample and retain it past the final sample.
            if event_witness is not None:
                event_witness.begin(self._process)

            def observed() -> tuple[ObsStatsCounters, ObsStreamStatus]:
                if self._identity() != self._process or self._session != session:
                    raise ObsProbeError("OBS session changed during measurement")
                result = _snapshot(self._client)
                if self._identity() != self._process or self._session != session:
                    raise ObsProbeError("OBS session changed during measurement")
                if not result[1].active or result[1].reconnecting:
                    raise ObsProbeError("OBS output stopped or is reconnecting")
                return result

            start_frames, start_transport = observed()
            start = _clock_ms(self._clock)
            deadline = start + duration_s * 1000
            last_clock = start
            ticks = 0
            while last_clock < deadline:
                seconds = min(poll_interval_s, (deadline - last_clock) / 1000)
                self._sleep(seconds)
                now = _clock_ms(self._clock)
                if now <= last_clock or now - last_clock > 10000:
                    raise ObsProbeError("capture clock stalled or sampling interval too large")
                last_clock = now
                end_frames, end_transport = observed()
                if event_witness is not None:
                    event_witness.checkpoint(self._process)
                ticks += 1
                if ticks > 1200:
                    raise ObsProbeError("OBS polling limit exceeded")
            end = _clock_ms(self._clock)
            # A slow sample can make invalid A/B windows; fail before export.
            if not 2000 <= end - start <= 600000:
                raise ObsProbeError("OBS capture interval outside benchmark limits")
            if event_witness is not None:
                attested = event_witness.finish(self._process)
            else:
                # Legacy callback is for trusted host test plumbing only;
                # production comparisons should use the event witness.
                attested = continuity_guard is not None and continuity_guard() is True
            if self._session != session or self._client is None:
                raise ObsProbeError("OBS connection changed during measurement")
            # Polling alone cannot attest events between probes: pessimistic.
            interrupted = not attested
            frames = ObsFrameWindow(
                pair_id, variant, game_id, game_version, self._session,
                start, end, start_frames, end_frames, True, interrupted,
            )
            transport = ObsTransportWindow(
                pair_id, variant, game_id, game_version, self._session,
                start, end, start_transport, end_transport, interrupted,
            )
            return CapturedObsEvidence(frames, transport, attested)
        except Exception:
            # A failed acquisition invalidates both OBS observation channels.
            if event_witness is not None:
                event_witness.disconnect()
            self.disconnect()
            raise ObsProbeError("OBS capture interrupted or unverifiable") from None


__all__ = [
    "ObsProbeError", "CapturedObsEvidence", "ObsReadOnlyProbe",
    "local_obs_process_identity",
]
