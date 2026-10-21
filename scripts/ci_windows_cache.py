"""Host caches for the self-hosted Windows CI jobs (the PC runner today, a Windows Sandbox later).

Two caches, both keyed by content so a hit is the same input, never "something close":
* python-base: a venv with requirements-desktop.txt + requirements-dev.txt + the CI tools installed once per
  hash of those files and the Python version. A job gets its own fresh, empty venv whose star-base.pth adds the
  base site-packages, so anything the job installs lands in its own venv and the base stays as built.
* dir save/restore: a finished folder (the React bundle) stored under a key (the git tree hash of frontend/).

Usage (paths are absolute or relative to the current folder):
  python scripts/ci_windows_cache.py python-base --cache DIR --venv JOBVENV --requirements a.txt b.txt --extra pkg ...
  python scripts/ci_windows_cache.py restore --cache DIR --kind frontend --key KEY --dest frontend/dist
  python scripts/ci_windows_cache.py save    --cache DIR --kind frontend --key KEY --src  frontend/dist
`restore` exits 0 on a hit and 3 on a miss. Entries are written to a temporary folder and renamed into place, so a
cancelled job never leaves a half entry that a later job would use. Release builds must not call this (the workflow
passes no cache on main), so a release is always a clean build.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import venv

MISS = 3


def python_base_key(requirements: list[Path], extra: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{sys.version_info[:3]} {sys.platform} {sys.maxsize > 2**32}\n".encode())
    for path in requirements:
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    for item in extra:
        digest.update(item.encode() + b"\0")
    return digest.hexdigest()[:24]


def site_packages(env: Path) -> Path:
    return env / "Lib" / "site-packages" if os.name == "nt" else next((env / "lib").glob("python3*/site-packages"))


def env_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _publish(tmp: Path, final: Path) -> bool:
    """Rename a finished temporary entry into place; False if another job published the same key first."""
    try:
        tmp.rename(final)
        return True
    except OSError:
        if not final.exists():
            raise
        shutil.rmtree(tmp, ignore_errors=True)
        return False


def ensure_python_base(cache: Path, requirements: list[Path], extra: list[str]) -> tuple[Path, bool]:
    # Short paths: PySide6 installs files ~175 characters deep and this PC has no long-path support, so the venv
    # root must stay well under 85 characters (keep the cache folder itself short, e.g. %USERPROFILE%\ci-cache).
    key = python_base_key(requirements, extra)[:16]
    final = cache / "py" / key
    if (final / "star-base-complete").is_file():
        return final, True
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.parent / f"t{uuid.uuid4().hex[:8]}"
    venv.create(tmp, with_pip=True)
    command = [str(env_python(tmp)), "-m", "pip", "install", "--disable-pip-version-check"]
    for path in requirements:
        command += ["-r", str(path)]
    subprocess.run(command + extra, check=True)
    subprocess.run([str(env_python(tmp)), "-m", "pip", "check"], check=True)
    (tmp / "star-base-complete").write_text(key + "\n", encoding="utf-8")
    _publish(tmp, final)
    return final, False


def make_job_venv(job: Path, base: Path) -> None:
    """A fresh venv for this job that sees the base packages after its own (site.addsitedir runs their .pth files).

    No pip of its own (ensurepip costs ~13 s): `python -m pip` finds the base's pip and installs into this venv."""
    venv.create(job, with_pip=False, clear=True)
    line = f"import site; site.addsitedir({str(site_packages(base))!r})\n"
    (site_packages(job) / "star-base.pth").write_text(line, encoding="utf-8")


def restore(cache: Path, kind: str, key: str, dest: Path) -> bool:
    entry = cache / kind / key
    if not (entry / ".star-cache-complete").is_file():
        return False
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(entry, dest, ignore=shutil.ignore_patterns(".star-cache-complete"))
    return True


def save(cache: Path, kind: str, key: str, src: Path) -> bool:
    final = cache / kind / key
    if (final / ".star-cache-complete").is_file():
        return False
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.parent / f".tmp-{key}-{uuid.uuid4().hex[:8]}"
    shutil.copytree(src, tmp)
    (tmp / ".star-cache-complete").write_text(key + "\n", encoding="utf-8")
    return _publish(tmp, final)


def _safe_key(value: str) -> str:
    if not value or not all(c.isalnum() or c in "-_." for c in value) or value.startswith("."):
        raise SystemExit(f"unsafe cache key: {value!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    base = sub.add_parser("python-base")
    base.add_argument("--cache", type=Path, required=True)
    base.add_argument("--venv", type=Path, required=True)
    base.add_argument("--requirements", type=Path, nargs="+", required=True)
    base.add_argument("--extra", nargs="*", default=[])
    for name in ("restore", "save"):
        p = sub.add_parser(name)
        p.add_argument("--cache", type=Path, required=True)
        p.add_argument("--kind", required=True)
        p.add_argument("--key", required=True)
        p.add_argument("--dest" if name == "restore" else "--src", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "python-base":
        path, hit = ensure_python_base(args.cache.resolve(), args.requirements, args.extra)
        make_job_venv(args.venv.resolve(), path)
        print(f"python-base {'hit' if hit else 'built'}: {path.name}")
        return 0
    kind, key = _safe_key(args.kind), _safe_key(args.key)
    if args.command == "restore":
        hit = restore(args.cache.resolve(), kind, key, args.dest)
        print(f"{kind} cache {'hit' if hit else 'miss'}: {key}")
        return 0 if hit else MISS
    stored = save(args.cache.resolve(), kind, key, args.src)
    print(f"{kind} cache {'stored' if stored else 'already present'}: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
