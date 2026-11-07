"""Measured, fail-conservative inference admissions for STAR's gaming VTuber.

Pure-Python advisory state machine. It never runs models, moves game characters,
captures media, operates microphones, changes process priorities or grants access.
An authorized host supplies *same-clock* measurements, executes separately, and
enforces each proposed reservation itself. No personally identifying data, audio,
images, chat, prompts, model weights or secrets are stored.

Why this exists: GPU time and VRAM are scarce while a game is rendering. An
unbounded image/research queue can make even a good voice model feel inhuman.
This controller reserves headroom, uses recent measured p95 completion times,
backs away from repeatedly failing routes, and lets speech prefer CPU during
live gameplay. A recommendation is not an actual latency or FPS improvement.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from threading import RLock

from .stream_budget import StreamTelemetry

_CLOCK_CEILING = 1e13
_JOBS = frozenset({"speech", "vision", "commentary", "research", "training", "render"})
_BACKGROUND = frozenset({"research", "training", "render"})
_GPU_ONLY = frozenset({"vision", "render"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")


def _number(value: object, name: str, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result) or not 0 <= result <= upper:
        raise ValueError(f"{name} must be in 0..{upper}")
    return result


def _p95(samples: deque[tuple[float, float]], *, now_ms: float) -> float | None:
    """Measured p95 for this game-load regime, expiring after two minutes."""
    ordered = sorted(duration for sampled, duration in samples
                     if 0 <= now_ms - sampled <= 120_000)
    if len(ordered) < 5:
        return None
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _regime(snapshot: QoSSnapshot) -> str:
    """Never borrow idle latency measurements for an active game."""
    return "game_active" if snapshot.stream.game_active else "idle"


@dataclass(frozen=True)
class QoSSnapshot:
    """Trusted host telemetry sampled on the same monotonic clock as calls."""
    sampled_ms: float
    stream: StreamTelemetry
    free_ram_mib: float
    cpu_busy_percent: float
    cpu_slots: int = 2
    gpu_slots: int = 1

    def __post_init__(self) -> None:
        _number(self.sampled_ms, "sampled_ms", _CLOCK_CEILING)
        if not isinstance(self.stream, StreamTelemetry):
            raise TypeError("stream must be StreamTelemetry")
        _number(self.free_ram_mib, "free_ram_mib", 2_000_000)
        _number(self.cpu_busy_percent, "cpu_busy_percent", 100)
        for name in ("cpu_slots", "gpu_slots"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 16:
                raise ValueError(f"{name} must be an integer in 0..16")


@dataclass(frozen=True)
class InferenceJob:
    """Scoped task request; memory is a host estimate, never a model claim."""
    job_id: str
    kind: str
    created_ms: float
    deadline_ms: float
    ram_mib: float
    vram_mib: float
    device: str = "auto"  # cpu | gpu | auto

    def __post_init__(self) -> None:
        if type(self.job_id) is not str or not _ID.fullmatch(self.job_id):
            raise ValueError("job_id must be a short opaque identifier")
        if self.kind not in _JOBS:
            raise ValueError("unknown inference kind")
        if self.device not in {"cpu", "gpu", "auto"}:
            raise ValueError("device must be auto, cpu or gpu")
        created = _number(self.created_ms, "created_ms", _CLOCK_CEILING)
        deadline = _number(self.deadline_ms, "deadline_ms", _CLOCK_CEILING)
        if not created < deadline <= created + 120_000:
            raise ValueError("deadline must follow creation within two minutes")
        _number(self.ram_mib, "ram_mib", 200_000)
        _number(self.vram_mib, "vram_mib", 200_000)
        if self.kind in _GPU_ONLY and self.device == "cpu":
            raise ValueError("this workload requires GPU admission")


@dataclass(frozen=True)
class QoSDecision:
    admitted: bool
    reason: str
    device: str | None = None
    ticket: int | None = None
    predicted_p95_ms: float | None = None
    expires_ms: float | None = None


@dataclass(frozen=True)
class _Reservation:
    job: InferenceJob
    device: str
    regime: str
    started_ms: float
    expires_ms: float


class AdaptiveQoS:
    """Bounded, owner-enabled, thread-safe advisory scheduler.

    All jobs are one-shot; a caller cannot silently replay an already admitted
    job ID. A timed-out worker remains in an advisory quarantine consuming its
    reserved capacity until the host confirms it stopped. Timeouts never free
    space that a runaway GPU worker may still be using.
    """

    def __init__(self, *, minimum_headroom_mib: float = 1536,
                 lease_cap_ms: float = 10_000) -> None:
        reserve = _number(minimum_headroom_mib, "minimum_headroom_mib", 8192)
        cap = _number(lease_cap_ms, "lease_cap_ms", 120_000)
        if reserve < 512 or not 250 <= cap <= 30_000:
            raise ValueError("invalid realtime headroom or lease cap")
        self.minimum_headroom_mib = reserve
        self.lease_cap_ms = cap
        self._lock = RLock()
        self._enabled = False
        self._clock_ms: float | None = None
        self._serial = 0  # never reset across disable/enable: stale receipts stay stale
        self._inflight: dict[int, _Reservation] = {}
        self._expired: set[int] = set()
        self._ids: set[str] = set()
        self._samples: dict[tuple[str, str, str], deque[tuple[float, float]]] = {}
        self._consecutive_failures: dict[tuple[str, str], int] = {}
        self._last_vision_ms: float | None = None
        self._counts = dict(admitted=0, deferred=0, completed=0, failed=0, expired=0)

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("an authenticated owner must enable QoS")
        with self._lock:
            if not self._enabled:
                # Disabling admission does not stop an already running worker.
                # Never reset reservations while a trusted host may still be
                # using GPU/CPU capacity from the old session.
                if self._inflight:
                    raise RuntimeError(
                        "host must acknowledge all stopped workers before re-enabling QoS"
                    )
                self._reset()
            self._enabled = True

    def _reset(self) -> None:
        self._clock_ms = None
        self._inflight.clear()
        self._expired.clear()
        self._ids.clear()
        self._samples.clear()
        self._consecutive_failures.clear()
        self._last_vision_ms = None
        self._counts = dict(admitted=0, deferred=0, completed=0, failed=0, expired=0)

    def disable(self) -> None:
        """Stop new admissions without erasing possibly running workers.

        Existing tickets remain reserved until finish() acknowledges the host
        stopped each worker. Revoked completions never train latency estimates.
        """
        with self._lock:
            self._enabled = False
            if not self._inflight:
                self._reset()

    def _advance(self, now_ms: float) -> float:
        now = _number(now_ms, "now_ms", _CLOCK_CEILING)
        if self._clock_ms is not None and now < self._clock_ms:
            raise ValueError("the host monotonic clock cannot reverse")
        self._clock_ms = now
        for ticket, active in tuple(self._inflight.items()):
            if now >= active.expires_ms and ticket not in self._expired:
                self._expired.add(ticket)
                self._counts["expired"] += 1
                key = (active.job.kind, active.device)
                # A timed-out model is not a speed success. Quarantine its
                # memory and slot until a trusted host confirms it stopped.
                self._consecutive_failures[key] = self._consecutive_failures.get(key, 0) + 1
        return now

    def _reason(self, reason: str) -> QoSDecision:
        self._counts["deferred"] += 1
        return QoSDecision(False, reason)

    def _route(self, job: InferenceJob, snap: QoSSnapshot, now: float,
               device: str) -> tuple[float | None, str] | None:
        """Check a single device; return predicted latency and admission note."""
        stream = snap.stream
        key = (job.kind, device)
        if self._consecutive_failures.get(key, 0) >= 3:
            return None
        if sum(p.device == device for p in self._inflight.values()) >= (
                snap.cpu_slots if device == "cpu" else snap.gpu_slots):
            return None
        if snap.free_ram_mib - sum(p.job.ram_mib for p in self._inflight.values()) < job.ram_mib + 512:
            return None
        if device == "cpu":
            if snap.cpu_busy_percent > 90:
                return None
        else:
            reserved = sum(p.job.vram_mib for p in self._inflight.values()
                           if p.device == "gpu")
            floor = (self.minimum_headroom_mib if stream.live and stream.game_active
                     else 1024 if stream.live else 512)
            if stream.free_vram_mib - reserved < job.vram_mib + floor:
                return None
        estimate = _p95(
            self._samples.get((job.kind, device, _regime(snap)), deque()),
            now_ms=now,
        )
        slack = job.deadline_ms - now
        if estimate is not None:
            # Conservative 20% scheduling margin for unmeasured queuing and GC.
            if estimate * 1.2 > slack:
                return None
            return estimate, "measured_p95_with_headroom"
        # Do not speculate about how long a brand-new vision/model route takes
        # while live. Speech is the only essential exploratory admission.
        if stream.live and job.kind != "speech":
            return None
        if stream.live and slack < 250:
            return None
        return None, "unmeasured_host_must_verify"

    def admit(self, job: InferenceJob, snap: QoSSnapshot, *,
              now_ms: float) -> QoSDecision:
        if not isinstance(job, InferenceJob) or not isinstance(snap, QoSSnapshot):
            raise TypeError("expected InferenceJob and QoSSnapshot")
        with self._lock:
            now = self._advance(now_ms)
            if not self._enabled:
                return self._reason("owner_opt_in_missing")
            if snap.sampled_ms > now + 20 or now - snap.sampled_ms > (
                    250 if snap.stream.live else 2_000):
                return self._reason("host_telemetry_stale_or_future_dated")
            if job.created_ms > now + 20 or now > job.deadline_ms:
                return self._reason("job_clock_or_deadline_invalid")
            if now - job.created_ms > (1000 if snap.stream.live else 30000):
                return self._reason("job_stale")
            if job.job_id in self._ids:
                return self._reason("duplicate_one_shot_job_id")
            if len(self._ids) >= 4096:
                return self._reason("bounded_session_limit_reached")
            stream = snap.stream
            if stream.live and job.kind in _BACKGROUND:
                return self._reason("protect_live_stream_from_background_work")
            under_pressure = ((stream.game_active and stream.game_fps < 50)
                              or stream.speech_backlog_ms > 250)
            if under_pressure and (stream.live or stream.game_active) and job.kind != "speech":
                return self._reason("game_or_voice_backpressure")
            if (stream.live and job.kind == "vision" and
                    self._last_vision_ms is not None and
                    now - self._last_vision_ms < 1000):
                return self._reason("live_vision_at_most_one_hz")

            devices = ([job.device] if job.device != "auto" else
                       (["gpu"] if job.kind in _GPU_ONLY else
                        ["cpu", "gpu"] if job.kind == "speech" and stream.game_active
                        else ["gpu", "cpu"]))
            # When a game is visibly struggling, speech may still be useful,
            # but falling back to GPU inference can worsen rendering stalls.
            # Prefer a deadline-safe CPU speech worker or deliberate silence.
            # This is a host-sampled protection rule, not an actual FPS fix.
            low_game_fps = (
                stream.live and stream.game_active
                and stream.game_fps < 50.0 and job.kind == "speech"
            )
            if low_game_fps:
                devices = [device for device in devices if device == "cpu"]
                if not devices:
                    return self._reason("protect_low_fps_game_from_gpu_voice")
            offers = [(device, self._route(job, snap, now, device))
                      for device in devices]
            viable = [(device, result) for device, result in offers if result is not None]
            if not viable:
                return self._reason(
                    "low_fps_cpu_voice_unavailable" if low_game_fps
                    else "no_calibrated_deadline_safe_route_or_headroom"
                )
            # Prefer measured routes over unknown ones; during gameplay give a
            # deadline-compliant CPU speech route priority over the gaming GPU.
            if job.kind == "speech" and stream.live and stream.game_active:
                viable.sort(key=lambda row: (row[1][0] is None,
                                              row[0] != "cpu",
                                              row[1][0] or 0))
            else:
                viable.sort(key=lambda row: (row[1][0] is None,
                                              row[1][0] or 0,
                                              row[0] != "gpu"))
            device, (p95, label) = viable[0]
            self._serial += 1
            ticket = self._serial
            expires = min(job.deadline_ms, now + self.lease_cap_ms)
            self._inflight[ticket] = _Reservation(
                job, device, _regime(snap), now, expires)
            self._ids.add(job.job_id)
            if stream.live and job.kind == "vision":
                self._last_vision_ms = now
            self._counts["admitted"] += 1
            return QoSDecision(True, label, device, ticket, p95, expires)

    def finish(self, ticket: int, *, now_ms: float, succeeded: bool) -> bool:
        """Host acknowledges completion; only *successful* measured runs train p95."""
        if type(ticket) is not int or ticket <= 0 or type(succeeded) is not bool:
            raise ValueError("a positive ticket and explicit success boolean are required")
        with self._lock:
            now = self._advance(now_ms)
            pending = self._inflight.pop(ticket, None)
            was_expired = ticket in self._expired
            self._expired.discard(ticket)
            if pending is None:
                return False
            if not self._enabled:
                # A revoked ticket is solely an acknowledgement that the host
                # actually stopped a worker. It must not count as successful.
                if not self._inflight:
                    self._reset()
                return False
            if was_expired:
                return False
            elapsed = now - pending.started_ms
            key = (pending.job.kind, pending.device)
            if succeeded:
                self._samples.setdefault(
                    (pending.job.kind, pending.device, pending.regime),
                    deque(maxlen=32),
                ).append((now, elapsed))
                self._consecutive_failures[key] = 0
                self._counts["completed"] += 1
            else:
                self._consecutive_failures[key] = self._consecutive_failures.get(key, 0) + 1
                self._counts["failed"] += 1
            return True

    def status(self) -> dict:
        """Aggregates only; no utterance contents, job IDs, model paths or voices."""
        with self._lock:
            return {
                **self._counts,
                "enabled": self._enabled,
                "inflight": len(self._inflight),
                "expired_awaiting_host_stop": len(self._expired),
                "disabled_workers_awaiting_host_stop": (
                    len(self._inflight) if not self._enabled else 0
                ),
                "route_p95_ms": {
                    f"{kind}:{device}:{regime}": round(value, 2)
                    for (kind, device, regime), samples in sorted(self._samples.items())
                    if (value := _p95(samples, now_ms=self._clock_ms or 0)) is not None
                },
                "unhealthy_routes": sum(n >= 3 for n in self._consecutive_failures.values()),
                "basis": "host-provided same-clock elapsed times; advisory only",
            }


__all__ = ["QoSSnapshot", "InferenceJob", "QoSDecision", "AdaptiveQoS"]
