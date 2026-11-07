"""Run logic twins in parallel Luau worker processes (Lune or the official Luau CLI).

Each worker gets one bundle holding a slice of the twins and plays them one after another in fresh
engine worlds, so process start-up is paid once per worker, not per session.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import bundle as bundle_mod
from .personas import PERSONAS, assign

DEFAULT_SETTINGS = {
    "tickDt": 1.0,       # seconds of game time per Heartbeat step (live Roblox: ~1/60)
    "capMin": 180,       # hard cap on one session's game time
    "sampleSec": 30,     # progression timeline resolution
    "dsFailRate": 0.01,  # injected DataStore failure rate
    "fuzzMin": 60,       # exploiter starts fuzzing between these game-time seconds
    "fuzzMax": 240,
}


@dataclass
class RunResult:
    sessions: list[dict]
    meta: dict
    errors: list[str] = field(default_factory=list)


def find_runtime(preference: str = "auto") -> tuple[str, str]:
    """Return (kind, executable). Looks at STAR_LUNE / STAR_LUAU, then PATH."""
    order = {"auto": ["lune", "luau"], "lune": ["lune"], "luau": ["luau"]}.get(preference)
    if order is None:
        raise ValueError("runtime must be auto, lune or luau")
    for kind in order:
        candidate = os.environ.get(f"STAR_{kind.upper()}") or shutil.which(kind)
        if candidate and Path(candidate).is_file():
            return kind, candidate
    raise FileNotFoundError(
        "no Luau runtime found: install Lune v0.11.0 or Luau 0.691 and put it on PATH, "
        "or set STAR_LUNE / STAR_LUAU to the executable")


def runtime_command(kind: str, exe: str, script: Path) -> list[str]:
    return [exe, "run", str(script)] if kind == "lune" else [exe, str(script)]


def pc_load() -> float | None:
    """Current CPU load in percent (Windows: Win32_Processor.LoadPercentage), or None."""
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                capture_output=True, text=True, timeout=30, check=False).stdout.strip()
            return float(out) if out else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    try:
        return min(100.0, os.getloadavg()[0] / (os.cpu_count() or 1) * 100)
    except (AttributeError, OSError):
        return None


def choose_workers(requested: int | None, load: float | None, cpus: int) -> int:
    """Explicit request wins (capped at cpus); otherwise use about half of the idle cores, 1..4."""
    if requested:
        return max(1, min(requested, cpus))
    idle = cpus * (1 - (load if load is not None else 50) / 100)
    return max(1, min(4, int(idle / 2)))


def plan_twins(n: int, mix: dict[str, float], days: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    personas = assign(n, mix)
    rng.shuffle(personas)
    return [{"id": i + 1, "userId": 100000 + i, "persona": p, "seed": rng.randrange(1, 2**31 - 1), "days": days}
            for i, p in enumerate(personas)]


def _spawn(cmd: list[str]) -> subprocess.Popen:
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS: the PC stays responsive
    else:
        kwargs["preexec_fn"] = lambda: os.nice(10)
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **kwargs)


def make_shards(game: bundle_mod.Game, *, twins: int, mix: dict[str, float], days: int, seed: int, shards: int,
                settings: dict | None) -> tuple[list[bundle_mod.Bundle], dict]:
    """Split the twin plan into `shards` bundles; returns them plus the metadata every report needs."""
    cfg_settings = {**DEFAULT_SETTINGS, **(settings or {})}
    plan = plan_twins(twins, mix, days, seed)
    shards = max(1, min(shards, len(plan)))
    personas = {name: PERSONAS[name] for name in mix}
    bundles = [bundle_mod.build(game, {"settings": cfg_settings, "personas": personas, "twins": plan[i::shards]})
               for i in range(shards)]
    meta = {
        "game": game.name, "game_dir": str(game.root), "twins": twins, "days": days, "seed": seed,
        "settings": cfg_settings, "mix": mix, "skipped_files": game.skipped,
        "personas": {k: v["label"] for k, v in personas.items()},
        "exploiters": [k for k, v in personas.items() if v.get("fuzz")],
    }
    return bundles, meta


def parse_line(line: str, b: bundle_mod.Bundle):
    """('twin', record) or ('done', info) for driver output lines, else None. Maps error lines to sources."""
    if line.startswith("@@TWIN "):
        rec = json.loads(line[7:])
        if rec.get("harnessError"):
            rec["harnessError"] = bundle_mod.map_lines(rec["harnessError"], b)
        for e in rec.get("errors") or []:
            e["msg"] = bundle_mod.map_lines(e["msg"], b)
        return "twin", rec
    if line.startswith("@@DONE "):
        return "done", json.loads(line[7:])
    return None


def _finish_meta(meta: dict, sessions: list[dict], done_info: list[dict], elapsed: float | None) -> dict:
    cpu = round(sum(d.get("cpu", 0) for d in done_info), 2)
    meta.update({
        "sessions": len(sessions), "elapsed_s": round(elapsed, 2) if elapsed else None,
        "sessions_per_min": round(len(sessions) / elapsed * 60, 1) if elapsed else None, "cpu_s": cpu,
        "sessions_per_cpu_min": round(len(sessions) / cpu * 60, 1) if cpu else None,
    })
    return meta


def write_shards(out_dir: str | Path, game_dir: str | Path, *, twins: int, mix: dict[str, float], days: int = 1,
                 seed: int = 1, shards: int = 4, settings: dict | None = None) -> list[Path]:
    """Write self-contained bundles for other machines: run each with `lune run F > F.out` (or `luau F`)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bundles, meta = make_shards(bundle_mod.load_game(game_dir), twins=twins, mix=mix, days=days, seed=seed,
                                shards=shards, settings=settings)
    paths = []
    for i, b in enumerate(bundles):
        path = out / f"twins_bundle_{i}.luau"
        path.write_text(b.text, encoding="utf-8")
        paths.append(path)
    meta["spans"] = [b.spans for b in bundles]
    (out / "shards.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return paths


def collect(out_dir: str | Path) -> RunResult:
    """Read `twins_bundle_<i>.luau.out` files written next to `shards.json`."""
    out = Path(out_dir)
    meta = json.loads((out / "shards.json").read_text(encoding="utf-8"))
    spans = meta.pop("spans")
    sessions, done_info, errors = [], [], []
    for i, shard_spans in enumerate(spans):
        b = bundle_mod.Bundle()
        b.spans = [tuple(s) for s in shard_spans]
        path = out / f"twins_bundle_{i}.luau.out"
        if not path.is_file():
            errors.append(f"missing output {path.name}")
            continue
        got_done = False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = parse_line(line, b)
            if parsed and parsed[0] == "twin":
                sessions.append(parsed[1])
            elif parsed:
                done_info.append(parsed[1])
                got_done = True
        if not got_done:
            errors.append(f"{path.name} has no @@DONE line (worker crashed or still running)")
    meta.update({"runtime": "external", "workers": len(spans), "load_before": None, "load_after": None})
    return RunResult(sessions, _finish_meta(meta, sessions, done_info, None), errors)


def run(game_dir: str | Path, *, twins: int, mix: dict[str, float], days: int = 1, seed: int = 1,
        workers: int | None = None, runtime: str = "auto", settings: dict | None = None,
        timeout: float = 3600, progress=None) -> RunResult:
    game = bundle_mod.load_game(game_dir)
    kind, exe = find_runtime(runtime)
    load_before = pc_load()
    n_workers = choose_workers(workers, load_before, os.cpu_count() or 1)
    bundles, meta = make_shards(game, twins=twins, mix=mix, days=days, seed=seed, shards=n_workers, settings=settings)

    sessions: list[dict] = []
    errors: list[str] = []
    done_info: list[dict] = []
    lock = threading.Lock()
    tmp = Path(tempfile.mkdtemp(prefix="star-twins-"))
    started = time.perf_counter()
    try:
        procs = []
        for i, b in enumerate(bundles):
            path = tmp / f"twins_bundle_{i}.luau"
            path.write_text(b.text, encoding="utf-8")
            procs.append(_spawn(runtime_command(kind, exe, path)))

        def pump(i: int, proc: subprocess.Popen) -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                parsed = parse_line(line, bundles[i])
                if not parsed:
                    continue
                with lock:
                    if parsed[0] == "twin":
                        sessions.append(parsed[1])
                        if progress:
                            progress(len(sessions))
                    else:
                        done_info.append(parsed[1])

        threads = [threading.Thread(target=pump, args=(i, p), daemon=True) for i, p in enumerate(procs)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + timeout
        for i, (proc, t) in enumerate(zip(procs, threads)):
            try:
                proc.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
                errors.append(f"worker {i} killed after {timeout:.0f} s")
            t.join(timeout=10)
            err = proc.stderr.read() if proc.stderr else ""
            if proc.returncode not in (0, None):
                errors.append(f"worker {i} exit {proc.returncode}: {bundle_mod.map_lines(err.strip(), bundles[i])[-2000:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    elapsed = time.perf_counter() - started
    meta.update({"runtime": kind, "runtime_path": Path(exe).name, "workers": len(bundles),
                 "load_before": load_before, "load_after": pc_load()})
    return RunResult(sessions, _finish_meta(meta, sessions, done_info, elapsed), errors)
