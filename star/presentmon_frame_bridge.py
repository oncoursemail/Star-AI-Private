"""Opt-in Windows PresentMon frame events for Star's measured gaming QoS.

An owner-controlled host starts a pinned PresentMon executable, targets a single
game PID and ingests v1-metrics CSV from its *live stdout* on a worker thread.
The hot-path RealtimeTelemetryHost continues to do zero process/ETW I/O.
CSV fields are observations, NOT instructions. An AI prompt or chat must never
choose the executable, target PID, permission or swap-chain identity.

No uploads, screenshots, audio, chat, user accounts or game inputs. Nothing
starts automatically. The capture cannot elevate privileges or broadcast.
"""
from __future__ import annotations

import csv
import io
import math
import os
from pathlib import Path
import re
import subprocess
from threading import Event, RLock, Thread
import time
from typing import Callable

from .stream_hardware_telemetry import RealtimeTelemetryHost

_REQUIRED = frozenset({
    "application", "processid", "swapchainaddress",
    "timeinseconds", "msbetweenpresents", "dropped",
})
_CHAIN = re.compile(r"^(?:0x)?[0-9a-fA-F]{1,16}$")
_MAX_LINE = 4096
_MAX_HEADER_LINES = 32


def _chain(value: str) -> str:
    if not isinstance(value, str) or not _CHAIN.fullmatch(value.strip()):
        raise ValueError("invalid swap chain address")
    number = int(value.strip(), 16)
    if number == 0:
        raise ValueError("unknown swap chain address")
    return hex(number)


def _number(value: str, *, maximum: float) -> float:
    try:
        result = float(value)
    except (ValueError, OverflowError, TypeError) as exc:
        raise ValueError("bad PresentMon numeric metric") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValueError("out-of-range PresentMon metric")
    return result


class PresentMonFrameBridge:
    """Strict live CSV-to-actual-present observation adapter.

    TimeInSeconds is relative to the *freshly started* collection. Its first
    frame is anchored to a host monotonic timestamp; later frames preserve
    the collector's time deltas. Never use this with saved CSV or replays: an
    old recording cannot establish that a present is occurring *now*.

    Unless the owner pins a swap chain, the first nonzero one is provisionally
    selected. Any second chain from the selected PID poisons the stream and
    immediately invalidates collected FPS; silent mixing is forbidden.
    """

    def __init__(
        self, host: RealtimeTelemetryHost, *, game_pid: int,
        application: str | None = None, swap_chain: str | None = None,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
    ) -> None:
        if not isinstance(host, RealtimeTelemetryHost):
            raise TypeError("trusted telemetry host required")
        if type(game_pid) is not int or not 1 <= game_pid <= 2**31 - 1:
            raise ValueError("invalid game PID")
        if application is not None and (
            type(application) is not str or not application.lower().endswith(".exe")
            or len(application) > 150 or "/" in application or "\\" in application
        ):
            raise ValueError("expected application must be a bare executable name")
        if not callable(clock_ms):
            raise TypeError("clock is not callable")
        self._host = host
        self._epoch = host.context_epoch()
        self._pid = game_pid
        self._application = application.casefold() if application else None
        self._expected_chain = _chain(swap_chain) if swap_chain else None
        self._selected_chain = self._expected_chain
        self._clock = clock_ms
        self._columns: dict[str, int] | None = None
        self._header_lines = 0
        self._first_source_ms: float | None = None
        self._first_host_ms: float | None = None
        self._last_source_ms: float | None = None
        self._poisoned = False
        self._reason: str | None = None
        self._lock = RLock()
        self._accepted = 0
        self._rejected = 0
        self._skipped = 0

    def _fail(self, reason: str) -> bool:
        self._host.invalidate_game_frames(expected_epoch=self._epoch)
        self._poisoned = True
        if self._reason is None:
            self._reason = reason
        self._rejected += 1
        return False

    def invalidate(self, reason: str = "collector_stopped") -> None:
        with self._lock:
            self._fail(reason)

    def feed_line(self, line: str) -> bool:
        """Accept a *live, trusted* collector stdout line, never arbitrary text."""
        with self._lock:
            if self._poisoned:
                return False
            if self._host.context_epoch() != self._epoch:
                return self._fail("context_changed")
            if type(line) is not str or len(line) > _MAX_LINE:
                return self._fail("oversized_line")
            try:
                cells = next(csv.reader(io.StringIO(line.lstrip("\ufeff")), strict=True))
            except (csv.Error, StopIteration):
                return self._fail("malformed_csv")
            if self._columns is None:
                self._header_lines += 1
                names = [v.strip().lower() for v in cells]
                if "processid" not in names:
                    if self._header_lines >= _MAX_HEADER_LINES:
                        return self._fail("missing_header")
                    return False
                if (len(set(names)) != len(names)
                        or not _REQUIRED.issubset(names)):
                    return self._fail("invalid_schema")
                self._columns = {name: i for i, name in enumerate(names)}
                return False

            cols = self._columns
            if len(cells) != len(cols):
                return self._fail("wrong_column_count")
            data = {key: cells[index].strip() for key, index in cols.items()}
            if data["processid"] != str(self._pid):
                self._skipped += 1
                return False
            if self._application is not None and (
                data["application"].casefold() != self._application
            ):
                return self._fail("application_mismatch")
            try:
                chain = _chain(data["swapchainaddress"])
                source_ms = 1000 * _number(data["timeinseconds"], maximum=1e9)
                between = _number(data["msbetweenpresents"], maximum=30000)
                dropped = data["dropped"]
                if dropped not in ("0", "1"):
                    raise ValueError("invalid dropped flag")
                if between <= 0:
                    raise ValueError("nonpositive frame interval")
                now = float(self._clock())
                if not math.isfinite(now) or now < 0:
                    raise ValueError("invalid host clock")
            except (ValueError, TypeError, OverflowError):
                return self._fail("invalid_frame")

            if chain != self._selected_chain:
                if self._expected_chain is not None:
                    self._skipped += 1
                    return False
                if self._selected_chain is not None:
                    return self._fail("multiple_swapchains")
                self._selected_chain = chain
            if self._last_source_ms is not None and source_ms <= self._last_source_ms:
                return self._fail("nonmonotonic_source")
            self._last_source_ms = source_ms
            if dropped == "1":
                self._skipped += 1
                return False

            if self._first_source_ms is None:
                self._first_source_ms, self._first_host_ms = source_ms, now
            frame_host_ms = self._first_host_ms + source_ms - self._first_source_ms
            # The timestamp is never replaced with "now" for buffered frames.
            # A stalled or accelerated feed invalidates all previous FPS proof.
            if frame_host_ms > now + 15 or now - frame_host_ms > 100:
                return self._fail("nonlive_capture")
            if between > 250:
                self._host.invalidate_game_frames(expected_epoch=self._epoch)
            if not self._host.presented_frame(frame_host_ms, expected_epoch=self._epoch):
                return self._fail("host_rejected_frame")
            self._accepted += 1
            return True

    def status(self) -> dict[str, object]:
        """Privacy-reduced counters; no process IDs, file paths or game titles."""
        with self._lock:
            return {
                "healthy": not self._poisoned,
                "schema_ready": self._columns is not None,
                "chain_selected": self._selected_chain is not None,
                "accepted": self._accepted,
                "rejected": self._rejected,
                "skipped": self._skipped,
                "error": self._reason,
            }


class PresentMonCaptureWorker:
    """Owner-enabled subprocess lifecycle, always OFF by default.

    Only a local Windows host may call start; an explicit executable path,
    game process ID and owner authorization are required. Nothing downloads,
    installs, elevates or grants game-control/streaming permissions.
    """

    def __init__(
        self, host: RealtimeTelemetryHost, *, executable: str,
        game_pid: int, application: str | None = None,
        swap_chain: str | None = None,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        platform_name: str | None = None,
        popen_factory: Callable[..., object] = subprocess.Popen,
    ) -> None:
        self._bridge = PresentMonFrameBridge(
            host, game_pid=game_pid, application=application,
            swap_chain=swap_chain, clock_ms=clock_ms,
        )
        self._host = host
        self._exe = executable
        self._pid = game_pid
        self._platform = platform_name or os.name
        self._popen_factory = popen_factory
        self._lock = RLock()
        self._stop = Event()
        self._process = None
        self._thread: Thread | None = None
        self._ever_started = False

    def start(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must approve local ETW capture")
        if self._platform != "nt":
            raise OSError("PresentMon capture requires Windows")
        if (type(self._exe) is not str or not os.path.isabs(self._exe)
                or Path(self._exe).suffix.lower() != ".exe"
                or not Path(self._exe).is_file()):
            raise ValueError("pinned PresentMon executable path required")
        status = self._host.status()
        if not (status["enabled"] and status["game_active"]):
            raise RuntimeError("enable trusted game telemetry first")
        with self._lock:
            if self._ever_started:
                raise RuntimeError("create a new worker for a new capture")
            self._ever_started = True
            args = [
                self._exe, "--process_id", str(self._pid),
                "--v1_metrics", "--output_stdout", "--no_console_stats",
                "--exclude_dropped", "--terminate_on_proc_exit",
            ]
            # No shell, arbitrary arguments, hidden elevation or auto-download.
            try:
                proc = self._popen_factory(
                    args, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    shell=False, text=True, errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.stdout is None:
                    raise RuntimeError("missing PresentMon output stream")
            except Exception:
                self._bridge.invalidate("collector_start_failed")
                raise
            self._process = proc
            self._thread = Thread(
                target=self._run, name="star-presentmon-reader", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        try:
            assert self._process is not None
            for line in self._process.stdout:
                if self._stop.is_set():
                    break
                self._bridge.feed_line(line)
                if not self._bridge.status()["healthy"]:
                    break
        except Exception:
            self._bridge.invalidate("collector_read_failed")
        finally:
            self._bridge.invalidate("collector_stopped")
            self._stop.set()
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._bridge.invalidate("collector_stopped")

    def status(self) -> dict[str, object]:
        result = self._bridge.status()
        result["running"] = bool(
            self._process is not None and not self._stop.is_set()
            and self._process.poll() is None
        )
        return result


__all__ = ["PresentMonFrameBridge", "PresentMonCaptureWorker"]
