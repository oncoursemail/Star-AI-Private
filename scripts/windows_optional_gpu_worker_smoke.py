"""Private disposable Windows process-lifecycle smoke for STAR optional workers.

USAGE (only in a trusted, local clone):
    python -m scripts.windows_optional_gpu_worker_smoke --run-disposable

Starts only a disposable, sleeping copy of the currently running Python
interpreter, never the foreground model, a game, voice, OBS, or any user PID.
Uses SYNTHETIC GPU health samples to validate the software path. This does not
benchmark GPU memory, inference or stream quality and must not go live.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from star.stream_gpu_owned_worker_host import HostOwnedOptionalGPUWorkers
from star.stream_optional_gpu_launch_supervisor import (
    HostOptionalGPUWorkerLaunchSupervisor, HostOptionalWorkerPlan,
)
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases


def _clock() -> float:
    return time.monotonic() * 1000.0


def _health(now: float, *, free: int) -> StreamHealthSample:
    # Synthetic ONLY: this tests process lifecycle, not real GPU admission.
    return StreamHealthSample(
        now,
        StreamTelemetry(
            live=False, game_active=False, total_vram_mib=8192,
            free_vram_mib=free, game_fps=60, speech_backlog_ms=0,
        ),
        0, 0, True,
    )


def run_disposable() -> dict[str, bool | int | str]:
    if platform.system() != "Windows":
        raise RuntimeError("private disposable lifecycle smoke requires Windows")
    executable = Path(sys.executable)
    if executable.suffix.lower() != ".exe":
        raise RuntimeError("expected a real Windows Python executable")
    # Hard-coded owner-invoked child, no dynamic command, no arbitrary PID.
    plan = HostOptionalWorkerPlan(
        "disposable-lifecycle-smoke", "research", 500, executable,
        ("-c", "import time; time.sleep(20)"),
    )
    ledger = RealtimeGPUWorkLeases(lease_timeout_ms=5000)
    ledger.enable(owner_approved=True)
    start = _clock()
    if not ledger.observe(_health(start, free=6500)):
        raise RuntimeError("synthetic software-only telemetry was rejected")
    bridge = HostGPUWorkerLeaseBridge(ledger)
    workers = HostOwnedOptionalGPUWorkers(ledger, bridge)
    host = HostOptionalGPUWorkerLaunchSupervisor(ledger, workers, (plan,))
    host.enable(owner_approved=True)
    started = False
    requests = 0
    exits = 0
    try:
        result = host.launch(plan, now_ms=_clock(), owner_approved=True)
        started = result.outcome == "started"
        if not started:
            return {
                "passed": False, "stage": result.reason,
                "synthetic_gpu_evidence_only": True,
                "outstanding_claims": ledger.metrics()["outstanding_claims"],
            }
        if not ledger.observe(_health(_clock(), free=700)):
            raise RuntimeError("synthetic pressure sample was rejected")
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            tick = host.tick(now_ms=_clock())
            requests += tick.stop_requests_sent
            exits += tick.exits_confirmed
            if ledger.metrics()["outstanding_claims"] == 0:
                break
            time.sleep(0.06)
        pending = ledger.metrics()["outstanding_claims"]
        return {
            "passed": bool(started and requests == 1 and exits == 1 and pending == 0),
            "stage": "private_disposable_process_exit",
            "synthetic_gpu_evidence_only": True,
            "stop_requests": requests,
            "independently_confirmed_exits": exits,
            "outstanding_claims": pending,
        }
    finally:
        # The disabled host still owns the disposable Popen and will request
        # its exit. Never target an external OS PID or a real model process.
        host.disable()
        for _ in range(100):
            tick = host.tick(now_ms=_clock())
            if tick.owned_workers == 0:
                break
            time.sleep(0.06)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-disposable", action="store_true",
        help="explicitly start and stop one harmless local Python child",
    )
    args = parser.parse_args()
    if not args.run_disposable:
        parser.error("requires explicit --run-disposable; never starts by default")
    try:
        result = run_disposable()
    except Exception as exc:
        # No system path, PID, private log, or arbitrary exception text output.
        print(json.dumps({
            "passed": False, "stage": type(exc).__name__,
            "synthetic_gpu_evidence_only": True,
        }))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
