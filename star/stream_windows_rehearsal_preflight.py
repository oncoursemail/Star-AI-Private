"""Read-only Windows preflight for Star's *nonbroadcast* game/VTuber lab.

This is a one-shot local *capability inventory*, NOT a model admission ticket,
permission to access a game window, proof of an actual frame/audio callback,
OBS state inspection, voice capture, or authorization to publish a stream.

Only process name, PID and OS creation-time are inspected transiently. The
report exports booleans and bounded GPU counters, not process identities,
command lines, window titles, transcripts, credentials, or network addresses.
No service is launched, stopped, configured, or contacted over a socket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import platform
import re
import subprocess
from typing import Callable, Iterable, cast


@dataclass(frozen=True)
class ProcessWitness:
    """Private ephemeral OS snapshot; never serialize these observations."""
    name: str
    pid: int
    created_unix_s: float


_GPU_UUID_RE = re.compile(r"GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)

# One authoritative, case-folded inventory of infrastructure processes.
# A model/OBS/avatar PID can never double as an independently pinned game.
_INFRA_ROLE_BY_BASENAME = {
    "obs64.exe": "obs", "obs.exe": "obs",
    "vtube studio.exe": "avatar", "vtubestudio.exe": "avatar",
    "llama-server.exe": "model", "llama-server": "model",
}


def _validated_gpu_uuid(value: str) -> str:
    """Bounded NVIDIA GPU UUID, normalized for comparisons; never emit in reports."""
    if type(value) is not str or _GPU_UUID_RE.fullmatch(value) is None:
        raise ValueError("invalid local GPU UUID evidence")
    return value.casefold()


@dataclass(frozen=True)
class GpuHeadroom:
    total_mib: int
    free_mib: int
    utilization_pct: int
    # Read in memory for device continuity; intentionally excluded from repr.
    device_uuid: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (type(self.total_mib) is not int
                or type(self.free_mib) is not int
                or type(self.utilization_pct) is not int
                or not 1024 <= self.total_mib <= 1048576
                or not 0 <= self.free_mib <= self.total_mib
                or not 0 <= self.utilization_pct <= 100):
            raise ValueError("invalid bounded local GPU evidence")
        if self.device_uuid is not None:
            _validated_gpu_uuid(self.device_uuid)


@dataclass(frozen=True)
class RehearsalPreflight:
    """Safe numeric/result projection; app presence != authorized host callbacks."""
    status: str  # candidate | deferred | unavailable
    reasons: tuple[str, ...]
    obs_process_seen: bool
    avatar_process_seen: bool
    model_process_seen: bool
    pinned_game_seen: bool
    gpu_total_mib: int | None
    gpu_free_mib: int | None
    gpu_utilization_pct: int | None
    authorized_to_play: bool = False
    authorized_to_broadcast: bool = False

    @property
    def candidate_for_nonbroadcast_rehearsal(self) -> bool:
        return self.status == "candidate"


def enumerate_windows_processes() -> Iterable[ProcessWitness]:
    """Read-only psutil process listing: NO paths, args, usernames, or handles."""
    import psutil

    for process in psutil.process_iter(["name", "pid", "create_time"], ad_value=None):
        info = process.info
        name = info.get("name")
        pid = info.get("pid")
        created = info.get("create_time")
        # Windows exposes special system processes with PID 0, empty names
        # or unknown creation times. They are not usable app witnesses; skip
        # them rather than letting ordinary OS metadata poison the snapshot.
        # psutil's typed process metadata can contain Incomplete/None. Narrow
        # the runtime value before converting it, rather than relying on
        # `type(...) in (...)` to convince static analysis it is numeric.
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            continue
        if type(pid) is not int or not 0 < cast(int, pid) <= 2**31 - 1:
            continue
        if not isinstance(created, (int, float)) or isinstance(created, bool):
            continue
        timestamp = float(created)
        if math.isfinite(timestamp) and 0 < timestamp <= 10**11:
            yield ProcessWitness(name, cast(int, pid), timestamp)


def query_nvidia_gpu(index: int = 0) -> GpuHeadroom:
    """One bounded, noninteractive nvidia-smi query on a pinned GPU index."""
    if type(index) is not int or not 0 <= index <= 7:
        raise ValueError("GPU index must be an integer 0..7")
    result = subprocess.run(
        ["nvidia-smi", "-i", str(index),
         "--query-gpu=uuid,memory.total,memory.free,utilization.gpu",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=3, check=False,
    )
    if result.returncode != 0 or len(result.stdout) > 256:
        raise RuntimeError("GPU sample unavailable")
    rows = result.stdout.strip().splitlines()
    parts = [part.strip() for part in rows[0].split(",")] if len(rows) == 1 else []
    if (len(parts) != 4
            or not all(re.fullmatch(r"\d+", part) for part in parts[1:])):
        raise ValueError("unexpected GPU counter format")
    device_uuid = _validated_gpu_uuid(parts[0])
    total, free, util = (int(part) for part in parts[1:])
    return GpuHeadroom(total, free, util, device_uuid=device_uuid)


def _game_identity(identity: tuple[int, float] | None) -> tuple[int, float] | None:
    if identity is None:
        return None
    if (type(identity) is not tuple or len(identity) != 2
            or type(identity[0]) is not int or not 1 <= identity[0] <= 2**31 - 1
            or type(identity[1]) not in (int, float)
            or not math.isfinite(float(identity[1]))
            or not 1 <= float(identity[1]) <= 10**11):
        raise ValueError("host must pin a positive PID and OS creation-time")
    return identity


def evaluate_preflight(
    processes: Iterable[ProcessWitness], gpu: GpuHeadroom | None, *,
    pinned_game_identity: tuple[int, float] | None,
    gpu_reserve_mib: int = 1536,
    max_gpu_utilization_pct: int = 90,
) -> RehearsalPreflight:
    """Pure, deterministic advisory. Unknown evidence always defers."""
    game = _game_identity(pinned_game_identity)
    if (type(gpu_reserve_mib) is not int or not 512 <= gpu_reserve_mib <= 16384
            or type(max_gpu_utilization_pct) is not int
            or not 60 <= max_gpu_utilization_pct <= 100):
        raise ValueError("invalid bounded GPU admission thresholds")
    if gpu is not None and not isinstance(gpu, GpuHeadroom):
        raise TypeError("GPU evidence must be GpuHeadroom or unavailable")
    role_counts = {"obs": 0, "avatar": 0, "model": 0}
    matched_game = False
    game_is_infrastructure = False
    seen_pids: set[int] = set()
    for i, row in enumerate(processes):
        if i >= 32768:
            raise ValueError("process snapshot unbounded")
        if not isinstance(row, ProcessWitness):
            raise TypeError("process snapshot must contain ProcessWitness entries")
        if (type(row.name) is not str or not 1 <= len(row.name) <= 256
                or type(row.pid) is not int or row.pid <= 0
                or type(row.created_unix_s) not in (int, float)
                or not math.isfinite(row.created_unix_s)
                or row.created_unix_s <= 0 or row.pid in seen_pids):
            raise ValueError("malformed or duplicated process snapshot")
        seen_pids.add(row.pid)
        name = row.name.casefold()
        # Count only process BASENAMES. Never retain the name in a report.
        role = _INFRA_ROLE_BY_BASENAME.get(name)
        if role is not None:
            role_counts[role] += 1
        if game is not None and row.pid == game[0] and abs(row.created_unix_s - game[1]) <= 0.001:
            matched_game = True
            # Without this, pinning llama-server (or OBS itself) produces a
            # false "game-ready" report with zero actual game processes.
            game_is_infrastructure = role is not None

    obs = role_counts["obs"] == 1
    avatar = role_counts["avatar"] == 1
    model = role_counts["model"] == 1
    reasons = []
    if not obs:
        reasons.append("obs_process_missing_or_ambiguous")
    if not avatar:
        reasons.append("avatar_process_missing_or_ambiguous")
    if not model:
        reasons.append("local_model_process_missing_or_ambiguous")
    if not matched_game:
        reasons.append("pinned_game_process_missing_or_restarted")
    if game_is_infrastructure:
        reasons.append("pinned_game_is_infrastructure_process")
    if gpu is None:
        reasons.append("gpu_sample_missing")
    else:
        if gpu.free_mib < gpu_reserve_mib:
            reasons.append("insufficient_free_gpu_memory")
        if gpu.utilization_pct > max_gpu_utilization_pct:
            reasons.append("gpu_utilization_high")
    return RehearsalPreflight(
        "candidate" if not reasons else "deferred", tuple(reasons),
        obs, avatar, model, matched_game,
        gpu.total_mib if gpu else None,
        gpu.free_mib if gpu else None,
        gpu.utilization_pct if gpu else None,
    )


def probe_windows_rehearsal(
    *, owner_approved: bool = False,
    pinned_game_identity: tuple[int, float] | None,
    gpu_index: int = 0,
    process_reader: Callable[[], Iterable[ProcessWitness]] = enumerate_windows_processes,
    gpu_reader: Callable[[int], GpuHeadroom] = query_nvidia_gpu,
    system_name: Callable[[], str] = platform.system,
) -> RehearsalPreflight:
    """Single opt-in local probe; errors are sanitized, never an authorization."""
    if owner_approved is not True:
        raise PermissionError("host opt-in required for local read-only inventory")
    game = _game_identity(pinned_game_identity)
    if type(gpu_index) is not int or not 0 <= gpu_index <= 7:
        raise ValueError("invalid GPU index")
    if not callable(process_reader) or not callable(gpu_reader) or not callable(system_name):
        raise TypeError("trusted preflight sources must be callables")
    if system_name() != "Windows":
        return RehearsalPreflight(
            "unavailable", ("windows_host_required",),
            False, False, False, False, None, None, None,
        )
    try:
        processes = tuple(process_reader())
    except Exception:
        return RehearsalPreflight(
            "unavailable", ("local_process_snapshot_unavailable",),
            False, False, False, False, None, None, None,
        )
    try:
        gpu: GpuHeadroom | None = gpu_reader(gpu_index)
    except Exception:
        gpu = None
    try:
        return evaluate_preflight(processes, gpu, pinned_game_identity=game)
    except (TypeError, ValueError):
        return RehearsalPreflight(
            "unavailable", ("local_process_snapshot_invalid",),
            False, False, False, False, None, None, None,
        )


__all__ = [
    "ProcessWitness", "GpuHeadroom", "RehearsalPreflight",
    "evaluate_preflight", "probe_windows_rehearsal",
    "query_nvidia_gpu", "enumerate_windows_processes",
]
