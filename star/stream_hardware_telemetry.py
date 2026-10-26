"""Trusted, off-hot-path hardware telemetry for Star's gaming/VTuber controllers.

This turns existing read-only OS/NVIDIA probes and owner-owned frame/audio
callbacks into StreamTelemetry and QoSSnapshot. Poll hardware on a worker, NOT
the game/render/audio thread. The snapshot method performs no device I/O.

A game frame MUST come from the actual frame-present observer (e.g. PresentMon
or a host's game engine callback); model-produced FPS estimates are not data.
The audio backlog MUST come from the local speaker, never viewers/chat.
Missing, late or implausible measurements fail closed instead of inventing
free GPU memory, game FPS, or a healthy voice queue.

No audio, images, text, identities, window names, commands, or credentials
are collected. This adapter grants no permissions to broadcast, play, or run
model inference. The corresponding consumers remain responsible for policy.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import os
from threading import RLock
import time
from typing import Callable, Protocol

from . import resource_probes
from .stream_budget import StreamTelemetry
from .stream_qos import QoSSnapshot


class SpeakerBacklog(Protocol):
    def pending_seconds(self) -> float: ...


@dataclass(frozen=True)
class HardwareSnapshot:
    sampled_ms: float
    total_vram_mib: float
    free_vram_mib: float
    free_ram_mib: float
    cpu_busy_percent: float | None


@dataclass(frozen=True)
class LiveHostSample:
    """Immutable observation. qos=None if CPU or live telemetry is too old."""

    telemetry: StreamTelemetry
    qos: QoSSnapshot | None
    game_frame_intervals: int
    hardware_age_ms: float
    stream_live: bool


def _ms(value: object, name: str) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not math.isfinite(number) or not 0 <= number <= 1e13:
        raise ValueError(f"{name} must be finite and monotonic")
    return number


def _limited(value: object, name: str, limit: float) -> float:
    amount = _ms(value, name)
    if amount > limit:
        raise ValueError(f"{name} exceeds its limit")
    return amount


def _cpu_times(value: object) -> tuple[int, int] | None:
    if (type(value) is not tuple or len(value) != 2
            or any(type(v) is not int or v < 0 for v in value)
            or value[0] > value[1]):
        return None
    return value


class RealtimeTelemetryHost:
    """Thread-safe, opt-in adapter to real local resource and presentation data.

    One producer calls refresh_hardware() periodically on a background worker.
    A trusted presentation callback calls presented_frame(), and the voice
    owner calls report_audio_backlog() or sample_speaker(). The game thread
    reads snapshot() cheaply with no shell commands or inference.

    set_context is a host-owned operation: chat/LLM content has no access to
    it. All timings are on the same host monotonic millisecond clock.
    """

    def __init__(
        self, *,
        gpu_probe: Callable[[], dict | None] = resource_probes.nvidia_gpu,
        memory_probe: Callable[[], tuple[int, int] | None] | None = None,
        cpu_probe: Callable[[], tuple[int, int] | None] | None = None,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        cpu_slots: int = 1,
        gpu_slots: int = 1,
    ) -> None:
        if not all(callable(f) for f in (gpu_probe, clock_ms)):
            raise TypeError("trusted host probes must be callable")
        self._gpu_probe = gpu_probe
        self._memory_probe = memory_probe or (
            resource_probes.windows_memory if os.name == "nt"
            else resource_probes.proc_meminfo
        )
        self._cpu_probe = cpu_probe or (
            resource_probes.windows_cpu_times if os.name == "nt"
            else resource_probes.proc_cpu_times
        )
        if not callable(self._memory_probe) or not callable(self._cpu_probe):
            raise TypeError("memory and CPU probes must be callable")
        if (type(cpu_slots) is not int or not 1 <= cpu_slots <= 16
                or type(gpu_slots) is not int or not 0 <= gpu_slots <= 16):
            raise ValueError("host-selected concurrency slots are invalid")
        self._clock = clock_ms
        self._cpu_slots, self._gpu_slots = cpu_slots, gpu_slots
        self._lock = RLock()
        self._enabled = False
        self._live = False
        self._game_active = False
        self._generation = 0
        self._polling = False
        self._hardware: HardwareSnapshot | None = None
        self._last_cpu: tuple[int, int] | None = None
        self._last_frame_ms: float | None = None
        self._frame_intervals: deque[float] = deque(maxlen=120)
        self._audio: tuple[float, float] | None = None
        self._counts = {"poll_ok": 0, "poll_failed": 0, "frames": 0,
                        "audio_samples": 0, "snapshots_rejected": 0}

    def set_context(self, *, live: bool, game_active: bool,
                    owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("authorized host must enable telemetry")
        if type(live) is not bool or type(game_active) is not bool:
            raise ValueError("stream and game state must be explicit booleans")
        with self._lock:
            self._generation += 1
            self._enabled = True
            self._live, self._game_active = live, game_active
            # No old scene/audio/resource measurement may be reused after
            # a broadcast transition, game switch, or focus change.
            self._hardware = None
            self._last_cpu = None
            self._last_frame_ms = None
            self._frame_intervals.clear()
            self._audio = None

    def disable(self) -> None:
        with self._lock:
            self._generation += 1
            self._enabled = False
            self._hardware = None
            self._last_cpu = None
            self._frame_intervals.clear()
            self._last_frame_ms = None
            self._audio = None

    def _now(self) -> float:
        return _ms(self._clock(), "trusted clock")

    def refresh_hardware(self) -> bool:
        """Run blocking OS/NVIDIA probes on a separate worker; no game I/O.

        Concurrent/replaced probes are rejected. A failed probe discards
        previous resource data, preventing optimistic stale GPU admissions.
        The CPU load estimate needs at least two consecutive valid polls.
        """
        with self._lock:
            if not self._enabled or self._polling:
                return False
            self._polling = True
            generation = self._generation
        try:
            try:
                gpu = self._gpu_probe()
                mem = self._memory_probe()
                cpu = _cpu_times(self._cpu_probe())
                measured_ms = self._now()
                if (type(gpu) is not dict or
                        type(mem) is not tuple or len(mem) != 2 or
                        any(type(v) is not int or v <= 0 for v in mem) or
                        mem[1] > mem[0] or cpu is None):
                    raise ValueError("incomplete physical telemetry")
                total = _limited(gpu.get("vram_total_mib"), "vram", 262144)
                used = _limited(gpu.get("vram_used_mib"), "vram_used", 262144)
                if total < 512 or used > total:
                    raise ValueError("inconsistent VRAM telemetry")
            except Exception:
                with self._lock:
                    if self._enabled and self._generation == generation:
                        self._hardware = None
                        self._last_cpu = None
                        self._counts["poll_failed"] += 1
                return False

            with self._lock:
                if not self._enabled or self._generation != generation:
                    return False
                busy = None
                if self._last_cpu is not None and cpu[1] > self._last_cpu[1]:
                    if 0 <= cpu[0] - self._last_cpu[0] <= cpu[1] - self._last_cpu[1]:
                        busy = 100 * (cpu[0] - self._last_cpu[0]) / (
                            cpu[1] - self._last_cpu[1]
                        )
                self._last_cpu = cpu
                # Delayed device observations cannot roll back an already
                # accepted timestamp.
                if self._hardware is not None and measured_ms < self._hardware.sampled_ms:
                    self._hardware = None
                    self._counts["poll_failed"] += 1
                    return False
                self._hardware = HardwareSnapshot(
                    measured_ms, total, total - used, mem[1], busy
                )
                self._counts["poll_ok"] += 1
                return True
        finally:
            with self._lock:
                self._polling = False

    def presented_frame(self, at_ms: float) -> bool:
        """Host-verified actual frame-present event, NOT model-estimated FPS."""
        at = _ms(at_ms, "presented frame")
        with self._lock:
            now = self._now()
            if (not self._enabled or not self._game_active
                    or at > now + 15 or now - at > 100):
                return False
            if self._last_frame_ms is not None:
                gap = at - self._last_frame_ms
                if gap <= 0:
                    return False
                if gap > 250:
                    self._frame_intervals.clear()
                else:
                    self._frame_intervals.append(gap)
            self._last_frame_ms = at
            self._counts["frames"] += 1
            return True

    def report_audio_backlog(self, *, backlog_ms: float,
                             at_ms: float) -> bool:
        """Backlog must come from authorized local speaker device state."""
        backlog = _limited(backlog_ms, "backlog", 120000)
        at = _ms(at_ms, "audio timestamp")
        with self._lock:
            now = self._now()
            if (not self._enabled or at > now + 15 or now - at > 100
                    or self._audio is not None and at < self._audio[0]):
                return False
            self._audio = (at, backlog)
            self._counts["audio_samples"] += 1
            return True

    def sample_speaker(self, speaker: SpeakerBacklog) -> bool:
        """Read only pending duration; do not capture voice or private audio."""
        try:
            seconds = speaker.pending_seconds()
            if type(seconds) not in (float, int):
                return False
            ms = _limited(seconds * 1000, "speaker backlog", 120000)
            return self.report_audio_backlog(backlog_ms=ms, at_ms=self._now())
        except Exception:
            with self._lock:
                self._audio = None
            return False

    def snapshot(self) -> LiveHostSample | None:
        """Zero blocking I/O; never infer missing game/audio/hardware values."""
        with self._lock:
            now = self._now()
            hardware = self._hardware
            if (not self._enabled or hardware is None
                    or now < hardware.sampled_ms
                    or now - hardware.sampled_ms > 1200):
                self._counts["snapshots_rejected"] += 1
                return None

            fps = 0.0
            intervals = len(self._frame_intervals)
            if self._game_active:
                if (self._last_frame_ms is None
                        or now < self._last_frame_ms
                        or now - self._last_frame_ms > 200 or intervals < 8):
                    self._counts["snapshots_rejected"] += 1
                    return None
                durations = sorted(self._frame_intervals)
                # Lower-tail FPS, not best-case average: protect actual
                # low-FPS gameplay against heavy vision or GPU inference.
                p90 = durations[math.ceil(.9 * intervals) - 1]
                fps = min(1000 / p90, 1000 * intervals / sum(durations))

            backlog = 0.0
            if self._live or self._game_active:
                if (self._audio is None or now < self._audio[0]
                        or now - self._audio[0] > 500):
                    self._counts["snapshots_rejected"] += 1
                    return None
                backlog = self._audio[1]
            telemetry = StreamTelemetry(
                self._live, self._game_active,
                hardware.free_vram_mib, hardware.total_vram_mib,
                fps, backlog
            )
            # AdaptiveQoS's live sampling gate is <=250ms. Do not lie by
            # stamping the current time on older GPU/CPU readings.
            qos = None
            if (hardware.cpu_busy_percent is not None
                    and (not self._live or now - hardware.sampled_ms <= 250)):
                qos = QoSSnapshot(
                    hardware.sampled_ms, telemetry, hardware.free_ram_mib,
                    hardware.cpu_busy_percent, self._cpu_slots, self._gpu_slots
                )
            return LiveHostSample(
                telemetry, qos, intervals, now - hardware.sampled_ms,
                self._live
            )

    def status(self) -> dict:
        """Health counters only: no raw media, speech or process identifiers."""
        with self._lock:
            return dict(
                enabled=self._enabled, live=self._live,
                game_active=self._game_active,
                hardware_ready=self._hardware is not None,
                frame_intervals=len(self._frame_intervals),
                audio_ready=self._audio is not None,
                **self._counts
            )


__all__ = ["HardwareSnapshot", "LiveHostSample", "RealtimeTelemetryHost"]
