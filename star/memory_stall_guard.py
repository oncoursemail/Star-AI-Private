"""Linux PSI + swap-activity admission for STAR's background inference work.

A system may have gigabytes of swap *occupied* without currently thrashing.
Use actual memory stalls and swap page-in/out *rates*, never swap occupancy
alone, to preserve gaming, speech, and low-latency reasoning performance.

This host-side observer is opt-in. Its /proc readers run on a background
worker; admit() is pure in-memory and makes no kernel, network or GPU calls.
Missing/stale/broken observations defer EXPENSIVE work, never silence urgent
speech. It does not start/stop processes or authorize any task.

Kernel PSI: https://www.kernel.org/doc/html/latest/accounting/psi.html
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
from functools import wraps
import math
from threading import RLock
from pathlib import Path
import time

_OPTIONAL = frozenset({"vision", "research", "training", "render"})
_URGENT = frozenset({"speech", "commentary"})
_COUNTER_LIMIT = 2**63 - 1


def _number(value: object, maximum: float, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name}: numeric value required")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name}: invalid numeric value") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValueError(f"{name}: out of range")
    return result


def _synchronized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return run


@dataclass(frozen=True)
class MemoryStallSample:
    """Cumulative counters from the SAME trusted Linux host and clock."""

    sampled_ms: float
    some_avg10_pct: float
    full_avg10_pct: float
    some_total_us: int
    full_total_us: int
    swap_in_pages: int
    swap_out_pages: int

    def __post_init__(self) -> None:
        _number(self.sampled_ms, 1e13, "sampled_ms")
        _number(self.some_avg10_pct, 100, "some_avg10_pct")
        _number(self.full_avg10_pct, 100, "full_avg10_pct")
        for name in ("some_total_us", "full_total_us",
                     "swap_in_pages", "swap_out_pages"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= _COUNTER_LIMIT:
                raise ValueError(f"{name}: invalid kernel counter")
        if self.full_total_us > self.some_total_us:
            raise ValueError("full stall time cannot exceed some stall time")


def _read_psi(text: str) -> tuple[float, float, int, int]:
    rows = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 5 or parts[0] not in {"some", "full"}:
            raise ValueError("unexpected PSI record")
        key = parts[0]
        if key in rows:
            raise ValueError("duplicate PSI record")
        values = {}
        for fragment in parts[1:]:
            label, sep, value = fragment.partition("=")
            if not sep or label in values:
                raise ValueError("invalid PSI field")
            values[label] = value
        if set(values) != {"avg10", "avg60", "avg300", "total"}:
            raise ValueError("missing PSI fields")
        total = values["total"]
        if not total.isdigit():
            raise ValueError("invalid PSI counter")
        for avg_key in ("avg10", "avg60", "avg300"):
            _number(float(values[avg_key]), 100, avg_key)
        rows[key] = (
            float(values["avg10"]),
            int(total),
        )
    if set(rows) != {"some", "full"}:
        raise ValueError("missing PSI row")
    if rows["full"][0] > rows["some"][0] or rows["full"][1] > rows["some"][1]:
        raise ValueError("full pressure cannot exceed some pressure")
    return rows["some"][0], rows["full"][0], rows["some"][1], rows["full"][1]


def _read_swap(text: str) -> tuple[int, int]:
    found = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] in {"pswpin", "pswpout"}:
            if len(parts) != 2 or parts[0] in found or not parts[1].isdigit():
                raise ValueError("invalid swap counter")
            found[parts[0]] = int(parts[1])
    if set(found) != {"pswpin", "pswpout"}:
        raise ValueError("missing swap page counters")
    return found["pswpin"], found["pswpout"]


def read_linux_stall_sample(
    *, clock_ms=lambda: time.monotonic() * 1000,
    psi_path: str = "/proc/pressure/memory",
    vmstat_path: str = "/proc/vmstat",
) -> MemoryStallSample | None:
    """Read aggregate OS counters, no keys, process IDs or user content.

    Host-configured paths are accepted for isolated tests, not from model input.
    Return None on unsupported OS, incomplete /proc, or counter anomalies.
    """
    try:
        with Path(psi_path).open("r", encoding="ascii") as handle:
            psi = handle.read(4097)
        with Path(vmstat_path).open("r", encoding="ascii") as handle:
            swap = handle.read(131073)
        if len(psi) > 4096 or len(swap) > 131072:
            return None
        some, full, some_total, full_total = _read_psi(psi)
        pages_in, pages_out = _read_swap(swap)
        return MemoryStallSample(
            clock_ms(), some, full, some_total, full_total,
            pages_in, pages_out,
        )
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True)
class StallAdvice:
    allowed: bool
    reason: str
    some_avg10_pct: float | None = None
    full_avg10_pct: float | None = None
    swap_pages_per_second: float | None = None


class MemoryStallGuard:
    """Host-only, one-sample-at-a-time circuit breaker for optional work.

    A single critical stall blocks immediately; recovery requires three
    separately timed healthy samples. Counter regression, gaps and stale
    clocks invalidate the state rather than silently declaring headroom.
    Counters are NEVER interpreted as total swap occupied.
    """

    def __init__(
        self, *, max_age_ms: float = 2500,
        some_limit_pct: float = 6.0,
        full_limit_pct: float = 1.0,
        swap_rate_limit: float = 256.0,
        recovery_samples: int = 3,
    ) -> None:
        self.max_age_ms = _number(max_age_ms, 10000, "max_age_ms")
        self.some_limit_pct = _number(some_limit_pct, 100, "some_limit_pct")
        self.full_limit_pct = _number(full_limit_pct, 100, "full_limit_pct")
        self.swap_rate_limit = _number(swap_rate_limit, 100000, "swap_rate_limit")
        if (not 200 <= self.max_age_ms <= 10000 or
                not 0.1 <= self.some_limit_pct <= 40 or
                not 0.1 <= self.full_limit_pct <= 20 or
                not 1 <= self.swap_rate_limit <= 100000 or
                type(recovery_samples) is not int or
                not 2 <= recovery_samples <= 10):
            raise ValueError("invalid pressure hysteresis or thresholds")
        self._recovery_samples = recovery_samples
        self._lock = RLock()
        self._enabled = False
        self._previous: MemoryStallSample | None = None
        self._state = "disabled"
        self._good = 0
        self._swap_rate: float | None = None
        self._counts = dict(accepted=0, rejected=0, hot=0, deferred=0)

    @_synchronized
    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted host must opt into background pressure checks")
        if self._enabled:
            raise RuntimeError("already enabled")
        self._enabled = True
        self._previous = None
        self._state = "warming"
        self._good = 0
        self._swap_rate = None

    @_synchronized
    def disable(self) -> None:
        self._enabled = False
        self._previous = None
        self._state = "disabled"
        self._good = 0
        self._swap_rate = None

    @_synchronized
    def observe(self, sample: MemoryStallSample | None) -> bool:
        """Call on a worker from local kernel readings; not per-model token."""
        if not self._enabled:
            return False
        if not isinstance(sample, MemoryStallSample):
            self._previous = None
            self._state = "pressured" if self._state == "pressured" else "unavailable"
            self._swap_rate = None
            self._good = 0
            self._counts["rejected"] += 1
            return False
        before = self._previous
        self._previous = sample
        self._counts["accepted"] += 1
        self._swap_rate = None
        if before is not None:
            dt = sample.sampled_ms - before.sampled_ms
            deltas = tuple(
                getattr(sample, key) - getattr(before, key)
                for key in ("some_total_us", "full_total_us",
                            "swap_in_pages", "swap_out_pages")
            )
            if not 200 <= dt <= 15000 or min(deltas) < 0:
                # A boot/counter reset or implausible sample gap is not health.
                # Do not clear a previously detected dangerous stall.
                self._state = "pressured" if self._state == "pressured" else "warming"
                self._good = 0
                self._counts["rejected"] += 1
                return False
            some_window_pct = 100 * deltas[0] / (dt * 1000)
            full_window_pct = 100 * deltas[1] / (dt * 1000)
            self._swap_rate = (deltas[2] + deltas[3]) * 1000 / dt
            hot = (
                some_window_pct >= self.some_limit_pct or
                full_window_pct >= self.full_limit_pct or
                (self._swap_rate is not None and self._swap_rate >= self.swap_rate_limit
                 and sample.some_avg10_pct >= 0.5)
            )
        else:
            hot = False
        hot = hot or (
            sample.some_avg10_pct >= self.some_limit_pct or
            sample.full_avg10_pct >= self.full_limit_pct
        )
        if hot:
            self._state = "pressured"
            self._good = 0
            self._counts["hot"] += 1
        elif self._state == "pressured":
            # A new baseline cannot prove recovery until a valid delta exists.
            if before is not None:
                self._good += 1
                if self._good >= self._recovery_samples:
                    self._state = "healthy"
        elif before is not None:
            self._state = "healthy"
        else:
            self._state = "warming"
        return True

    def poll_linux(self, **host_paths: str) -> bool:
        """For trusted periodic worker only. Never called from admit()."""
        return self.observe(read_linux_stall_sample(**host_paths))

    @_synchronized
    def advise(self, kind: str, *, now_ms: float) -> StallAdvice:
        if kind not in _OPTIONAL | _URGENT:
            raise ValueError("unknown inference kind")
        now = _number(now_ms, 1e13, "now_ms")
        if kind in _URGENT:
            return StallAdvice(True, "urgent_voice_or_commentary_not_preempted")
        before = self._previous
        if not self._enabled or before is None:
            reason = "pressure_guard_unavailable"
        elif now < before.sampled_ms:
            reason = "pressure_clock_regression"
        elif now - before.sampled_ms > self.max_age_ms:
            reason = "pressure_sample_stale"
        elif self._state != "healthy":
            reason = f"memory_stall_{self._state}"
        else:
            return StallAdvice(
                True, "memory_stall_clear",
                before.some_avg10_pct, before.full_avg10_pct, self._swap_rate,
            )
        self._counts["deferred"] += 1
        return StallAdvice(
            False, reason,
            before.some_avg10_pct if before else None,
            before.full_avg10_pct if before else None,
            self._swap_rate,
        )

    @_synchronized
    def status(self) -> dict[str, object]:
        return {"enabled": self._enabled, "state": self._state,
                "healthy_samples": self._good, **self._counts}


__all__ = [
    "MemoryStallSample", "StallAdvice", "MemoryStallGuard",
    "read_linux_stall_sample",
]
