"""Dashboard data: projects (from ~/.metallic/projects.toml plus the current repo), their latest check and queue runs,
pending queue entries, latest tag, and runners (~/.metallic/runners.toml, each with an optional probe command).

Everything comes from files the CLI wrote or from a probe run now; nothing is estimated. Missing data is reported as
missing ("not connected", "no runs yet", "not reporting"), never filled in.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tomllib

from . import gitutil
from .config import load, user_dir


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _runs(root: Path, limit: int = 12) -> list[dict]:
    runs_dir = gitutil.state_dir(root) / "runs"
    out = []
    for p in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def project(entry: dict) -> dict:
    path = Path(entry.get("path", ""))
    info = {"name": entry.get("name") or path.name, "lang": entry.get("lang", ""), "repo": entry.get("repo", ""),
            "connected": False}
    if not entry.get("path") or not (path / ".git").exists():
        info["note"] = "no local clone connected"
        return info
    try:
        root = gitutil.repo_root(path)
        cfg = load(root)
        from . import queue as queue_mod
        info.update(connected=True, name=entry.get("name") or cfg.name, target=cfg.target,
                    branch=gitutil.current_branch(root), configured=cfg.path is not None,
                    head=gitutil.rev("HEAD", root)[:10], pending=queue_mod.pending(root))
        tag = gitutil.git(["describe", "--tags", "--abbrev=0"], root, check=False).strip()
        if tag:
            when = gitutil.git(["log", "-1", "--format=%cI", tag], root, check=False).strip()
            info["release"] = {"tag": tag, "date": when}
        runs = _runs(root)
        info["checks"] = [r for r in runs if r.get("kind") == "check"][:6]
        info["queue_runs"] = [r for r in runs if r.get("kind") == "queue"][:4]
    except (gitutil.GitError, OSError) as e:
        info["note"] = f"unreadable: {type(e).__name__}"
    return info


def runner(entry: dict) -> dict:
    r = {"name": entry.get("name", "?"), "role": entry.get("role", ""), "policy": entry.get("policy", ""),
         "status": "not reporting"}
    probe = entry.get("probe")
    if entry.get("local"):
        r.update(status="online", cores=os.cpu_count())
        return r
    if not probe:
        return r
    try:
        proc = subprocess.run(probe, capture_output=True, text=True, timeout=int(entry.get("timeout", 8)))
    except (OSError, subprocess.TimeoutExpired) as e:
        r["status"] = f"offline ({type(e).__name__})"
        return r
    if proc.returncode != 0:
        r["status"] = f"offline (exit {proc.returncode})"
        return r
    lines = proc.stdout.split()
    try:
        r.update(status="online", cores=int(lines[0]), load=float(lines[1]))
    except (IndexError, ValueError):
        r["status"] = "online (probe output not understood)"
    return r


def collect(current: Path | None = None) -> dict:
    home = user_dir()
    entries = list(_toml(home / "projects.toml").get("project", []))
    if current is not None:
        cur = str(current.resolve())
        if not any(os.path.normcase(str(Path(e.get("path", "")).resolve())) == os.path.normcase(cur)
                   for e in entries if e.get("path")):
            entries.insert(0, {"path": cur})
    runners = list(_toml(home / "runners.toml").get("runner", [])) or [{"name": "this machine", "local": True}]
    return {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "projects": [project(e) for e in entries], "runners": [runner(e) for e in runners]}
