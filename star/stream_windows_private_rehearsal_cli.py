"""One-command read-only Windows readiness survey for STAR's private gaming VTuber.

This is an *operational* CLI over the already-tested sustained GPU/process
resource window. It never starts a game, OBS, a TTS worker, or a broadcast.
No PID, executable name, GPU UUID, user path or viewer content is serialized.
Even a successful candidate is NOT a gameplay/recording/output authorization.

Run on the owner-controlled Windows machine:
    python -m star.stream_windows_private_rehearsal_cli --observe
    python -m star.stream_windows_private_rehearsal_cli --observe \
        --game-pid 1234 --game-exe MyGame.exe
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from itertools import islice
import json
import platform
import re
import time
from typing import Callable, Iterable

from .stream_recording_disk_guard import RecordingDiskGuard
from .stream_windows_rehearsal_preflight import (
    GpuHeadroom,
    ProcessWitness,
    _INFRA_ROLE_BY_BASENAME,
    enumerate_windows_processes,
    query_nvidia_gpu,
)
from .stream_windows_resource_window import (
    ResourceWindowReport,
    probe_windows_resource_window,
)

_GAME_EXE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,79}\.exe\Z", re.ASCII)
# These Windows shell/interpreter processes are not game identities. An arbitrary
# executable matching the syntax still requires separate genuine frame evidence.
_NON_GAME = frozenset({
    "explorer.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "python.exe", "pythonw.exe", "conhost.exe", "svchost.exe",
    "taskmgr.exe", "dwm.exe", "winlogon.exe", "services.exe",
})


@dataclass(frozen=True)
class PrivateRehearsalReadiness:
    status: str  # candidate | deferred | unavailable
    reasons: tuple[str, ...]
    samples: int
    window_ms: int | None
    min_free_gpu_mib: int | None
    peak_gpu_util_pct: int | None
    stable_processes: bool
    game_process_pinned: bool
    # These flags NEVER change in this module, even on a perfect result.
    game_frames_verified: bool = False
    voice_audible_verified: bool = False
    avatar_frames_verified: bool = False
    obs_recording_verified: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False
    # Readiness for an explicitly selected local recording volume. No file paths.
    recording_storage_checked: bool = False
    recording_storage_ready: bool = False
    recording_free_mib: int | None = None
    recording_required_mib: int | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _unavailable(reason: str) -> PrivateRehearsalReadiness:
    return PrivateRehearsalReadiness(
        "unavailable", (reason,), 0, None, None, None, False, False,
    )


def _wrap(report: ResourceWindowReport, *, game_pinned: bool) -> PrivateRehearsalReadiness:
    return PrivateRehearsalReadiness(
        report.status, report.reasons, report.sample_count,
        report.observed_span_ms, report.gpu_min_free_mib,
        report.gpu_max_utilization_pct, report.host_processes_stable,
        game_pinned,
    )


def _game_pin(
    processes: Iterable[ProcessWitness], *, pid: int, exe: str,
) -> tuple[int, float] | None:
    """Pin EXACT OS PID+creation timestamp and expected Windows basename."""
    for row in islice(processes, 32769):
        if not isinstance(row, ProcessWitness):
            raise ValueError("invalid OS process witness")
        if row.pid == pid and row.name.casefold() == exe.casefold():
            return (row.pid, row.created_unix_s)
    return None


def check_private_rehearsal_readiness(
    *,
    owner_approved: bool = False,
    game_pid: int | None = None,
    game_exe: str | None = None,
    gpu_index: int = 0,
    samples: int = 5,
    interval_s: float = 0.5,
    process_reader: Callable[[], Iterable[ProcessWitness]] = enumerate_windows_processes,
    gpu_reader: Callable[[int], GpuHeadroom] = query_nvidia_gpu,
    system_name: Callable[[], str] = platform.system,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> PrivateRehearsalReadiness:
    """Measure live host readiness, not performance or output success.

    The game PID must come from a trusted LOCAL operator, never viewer chat.
    Matching a process name is only identity corroboration; a real-game frame
    source, authorized controls and observable results are still mandatory.
    """
    if owner_approved is not True:
        raise PermissionError("explicit local read-only observation required")
    if not all(callable(fn) for fn in (
        process_reader, gpu_reader, system_name, clock, sleeper,
    )):
        raise TypeError("trusted Windows probe dependencies required")
    if (type(gpu_index) is not int or not 0 <= gpu_index <= 7
            or type(samples) is not int or not 3 <= samples <= 9
            or type(interval_s) not in (int, float)
            or not 0.25 <= interval_s <= 2):
        raise ValueError("invalid bounded probe configuration")
    if (game_pid is None) != (game_exe is None):
        raise ValueError("game PID and executable basename must be supplied together")
    if game_pid is not None:
        if (type(game_pid) is not int or not 0 < game_pid <= 2**31 - 1
                or type(game_exe) is not str or not _GAME_EXE.fullmatch(game_exe)):
            raise ValueError("expected positive PID and local game executable basename")
        if (game_exe.casefold() in _NON_GAME
                or game_exe.casefold() in _INFRA_ROLE_BY_BASENAME):
            raise ValueError("shell/infrastructure process cannot be pinned as game")
    if system_name() != "Windows":
        return _unavailable("windows_host_required")

    pinned: tuple[int, float] | None = None
    if game_pid is not None:
        assert game_exe is not None
        try:
            pinned = _game_pin(process_reader(), pid=game_pid, exe=game_exe)
        except Exception:
            return _unavailable("game_identity_probe_failed")
        if pinned is None:
            return _unavailable("game_pid_or_basename_not_running")
        # The same process must keep its expected executable NAME during every
        # sample; the underlying resource probe additionally checks birth time.
        ordinary_reader = process_reader

        def pinned_reader() -> Iterable[ProcessWitness]:
            rows = tuple(islice(ordinary_reader(), 32769))
            if _game_pin(rows, pid=game_pid, exe=game_exe) != pinned:
                raise ValueError("pinned game process changed")
            return rows

        process_reader = pinned_reader

    result = probe_windows_resource_window(
        owner_approved=True, pinned_game_identity=pinned,
        gpu_index=gpu_index, sample_count=samples,
        sample_spacing_s=interval_s, process_reader=process_reader,
        gpu_reader=gpu_reader, system_name=system_name,
        monotonic_clock=clock, sleeper=sleeper,
    )
    return _wrap(result, game_pinned=pinned is not None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "STAR private VTuber game+OBS readiness: READ-ONLY; never broadcasts."
    ))
    parser.add_argument("--observe", action="store_true",
                        help="opt into local process and NVIDIA GPU sampling")
    parser.add_argument("--game-pid", type=int)
    parser.add_argument("--game-exe", type=str,
                        help="exact basename, e.g. RobloxPlayerBeta.exe")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--recording-dir", type=str, default=None,
                        help="optional existing local OBS recording output folder; never logged")
    args = parser.parse_args(argv)
    if not args.observe:
        print(_unavailable("explicit_observe_flag_required").to_json())
        return 2
    try:
        result = check_private_rehearsal_readiness(
            owner_approved=True, game_pid=args.game_pid,
            game_exe=args.game_exe, gpu_index=args.gpu_index,
            samples=args.samples, interval_s=args.interval_ms / 1000,
        )
    except (PermissionError, TypeError, ValueError):
        result = _unavailable("invalid_probe_configuration")
    # A normal process/GPU candidate is NOT a recording candidate. Rehearsals
    # that save local output must explicitly probe their actual output volume.
    if args.recording_dir is not None and result.status != "unavailable":
        try:
            disk = RecordingDiskGuard(args.recording_dir).check(owner_approved=True)
        except (PermissionError, TypeError, ValueError):
            disk = None
        if disk is None:
            result = replace(result, status="unavailable",
                             reasons=result.reasons + ("recording_disk_probe_invalid",))
        else:
            reasons = result.reasons
            if disk.status != "candidate":
                reasons += (disk.reason,)
            result = replace(
                result,
                status=(result.status if disk.status == "candidate"
                        else "unavailable" if disk.status == "unavailable" else "deferred"),
                reasons=reasons,
                recording_storage_checked=True,
                recording_storage_ready=disk.status == "candidate",
                recording_free_mib=disk.free_mib,
                recording_required_mib=disk.required_mib,
            )
    print(result.to_json())
    return 0 if result.status == "candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
