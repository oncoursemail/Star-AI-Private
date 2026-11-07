"""Keep the owner's own Git server (Forgejo on Brain One) in step with GitHub: step 1 of moving off GitHub.

Each run (her 10-minute loop) fetches the release branches from GitHub into her clone and pushes them to the forge
over SSH with her bot key. Fast-forward only: a branch that moved differently on the forge is reported, never
overwritten. The forge's address and key live in ~/.ssh/config (host alias), never in git.
Where STAR's repo goes: ~/.star/litha/forge_sync.json {"oncoursemail/Star-AI-Project": "<forge owner/name>"}."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

CONFIG = Path.home() / ".star" / "litha" / "forge_sync.json"
DEFAULT = {"oncoursemail/Star-AI-Project": "metallic/Star-AI-Project"}
HOST = "metallic-forge"                                   # ~/.ssh/config alias for the forge's SSH port
BRANCHES = ("main", "star/next")


def git(args: list[str], cwd: Path, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def repos() -> dict[str, str]:
    try:
        got = json.loads(CONFIG.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) and got else DEFAULT
    except (OSError, ValueError):
        return DEFAULT


def sync(clone: Path, target: str, branches=BRANCHES, origin: str = "origin", host: str = HOST) -> list[str]:
    """Push origin's branches to the forge repo `target` (a path or URL is used as is); one line per branch."""
    url = target if Path(target).exists() else f"{host}:{target}.git"
    have = [b for b in branches if git(["fetch", "-q", origin, f"{b}:refs/remotes/{origin}/{b}"], clone).returncode == 0]
    if not have:
        return [f"{target}: fetch from {origin} failed"]
    r = git(["push", "--porcelain", url, *[f"refs/remotes/{origin}/{b}:refs/heads/{b}" for b in have]], clone)
    out = []
    for b in have:
        flag = next((ln[:1] for ln in r.stdout.splitlines() if f":refs/heads/{b}\t" in ln), "")   # porcelain
        out.append(f"{target} {b}: " + ("up to date" if flag == "=" else "pushed" if flag in (" ", "+", "*")
                                       else "REFUSED (moved differently there; not overwritten)" if flag == "!"
                                       else "failed: " + (r.stderr.strip().splitlines() or ["?"])[-1][:160]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clone", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    bad = 0
    for line in sync(args.clone, repos().get("oncoursemail/Star-AI-Project", DEFAULT["oncoursemail/Star-AI-Project"])):
        print("forge_sync:", line)
        bad += "failed" in line or "REFUSED" in line
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
