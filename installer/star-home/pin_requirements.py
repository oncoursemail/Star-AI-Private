"""Pin every Python package STAR Home needs on her PC, with hashes, from PyPI's own metadata.

    python installer/star-home/pin_requirements.py            rewrite requirements-home.txt and requirements-home-torch.txt
    python installer/star-home/pin_requirements.py --check    do not write; fail if the written files are out of date

Reads requirements-home.in (the direct packages and the choices behind them), resolves the full dependency tree for her
machine (Windows x64, CPython 3.12) and writes exact versions with SHA-256 hashes of every file pip could pick there.
setup.ps1 installs the result with `pip install --no-deps --require-hashes`, so nothing outside the list gets in.
Needs `packaging` and network access to pypi.org and download.pytorch.org (read-only). Run it on any PC; the output is for
Windows whatever PC runs it. Resolution is "newest release that satisfies every requirement and is at least --min-age-days
old" without backtracking; the final pass re-checks every requirement of every pin and fails if one is violated.

Directives in requirements-home.in (comment lines that start with `#!`):
    #!skip NAME                 resolve and pin everything else, but leave NAME out of the file (installed another way)
    #!torch VERSION INDEX       torch VERSION+INDEX from https://download.pytorch.org/whl/INDEX goes to requirements-home-torch.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "requirements-home.in"
OUT = ROOT / "requirements-home.txt"
OUT_TORCH = ROOT / "requirements-home-torch.txt"
ENV = {"python_version": "3.12", "python_full_version": "3.12.10", "sys_platform": "win32", "platform_system": "Windows",
       "os_name": "nt", "platform_machine": "AMD64", "implementation_name": "cpython",
       "platform_python_implementation": "CPython", "platform_release": "", "platform_version": "", "extra": ""}
TAGS = set(cpython_tags(python_version=(3, 12), platforms=["win_amd64"])) | \
    set(compatible_tags(python_version=(3, 12), platforms=["win_amd64"]))
_cache: dict[str, dict] = {}
LOOKS_LIKE_ADDRESS = re.compile(r"(10|127)(\.\d+){3}|192\.168(\.\d+){2}|172\.(1[6-9]|2\d|3[01])(\.\d+){2}")


def fetch_json(url: str) -> dict:
    for attempt in range(4):
        if url in _cache:
            break
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                _cache[url] = json.load(response)
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    return _cache[url]


def project(name: str) -> dict:
    return fetch_json(f"https://pypi.org/pypi/{canonicalize_name(name)}/json")


def usable_files(files: list[dict]) -> list[dict]:
    """The files pip could install on cp312 win_amd64: matching wheels, else the source distribution."""
    live = [f for f in files if not f.get("yanked")]
    wheels = []
    for f in live:
        if f["filename"].endswith(".whl"):
            try:
                tags = set(parse_wheel_filename(f["filename"])[3])
            except Exception:
                continue
            if tags & TAGS:
                wheels.append(f)
    return wheels or [f for f in live if f["filename"].endswith((".tar.gz", ".zip"))]


def age_days(files: list[dict]) -> float:
    first = min(dt.datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in files)
    return (dt.datetime.now(dt.timezone.utc) - first).total_seconds() / 86400


def requires(name: str, version: str) -> list[Requirement]:
    meta = fetch_json(f"https://pypi.org/pypi/{canonicalize_name(name)}/{version}/json")["info"]
    return [Requirement(r) for r in (meta.get("requires_dist") or [])]


def read_source() -> tuple[list[Requirement], set[str], tuple[str, str] | None]:
    wanted, skip, torch = [], set(), None
    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#!skip "):
            skip.add(canonicalize_name(line.split()[1]))
        elif line.startswith("#!torch "):
            _, version, index = line.split()
            torch = (version, index)
        elif line and not line.startswith("#"):
            wanted.append(Requirement(line.split(" #")[0].strip()))
    return wanted, skip, torch


def applies(req: Requirement, extras: set[str]) -> bool:
    """Does this requirement of a package apply on her machine, given the extras asked of that package?"""
    if req.marker is None:
        return True
    if "extra" in str(req.marker):
        return any(req.marker.evaluate({**ENV, "extra": e}) for e in extras)
    return req.marker.evaluate(ENV)


def resolve(wanted: list[Requirement], min_age: float, torch: tuple[str, str] | None):
    """name -> (version, files); also name -> who asked for it. Newest-first; repeats until every constraint holds."""
    cons: dict[str, SpecifierSet] = {}
    extras: dict[str, set[str]] = {}
    who: dict[str, set[str]] = {}
    exact: set[str] = set()                      # asked for with == in requirements-home.in: age and pre-release rules do not apply

    def add(req: Requirement, parent: str) -> bool:
        name = canonicalize_name(req.name)
        fresh = name not in cons
        new_extras = set(req.extras) - extras.get(name, set())
        before = str(cons.get(name, SpecifierSet()))
        cons[name] = cons.get(name, SpecifierSet()) & req.specifier
        extras.setdefault(name, set()).update(new_extras)
        who.setdefault(name, set()).add(parent)
        if parent == "<root>" and any(s.operator == "==" for s in req.specifier):
            exact.add(name)
        return fresh or str(cons[name]) != before or bool(new_extras)

    for req in wanted:
        add(req, "<root>")
    if torch:                                    # only its dependencies are resolved here; the wheel comes from the CUDA index
        add(Requirement(f"torch=={torch[0]}"), "<root>")
    pins: dict[str, tuple[str, list[dict]]] = {}
    expanded: dict[str, tuple] = {}              # name -> (version, extras) whose own requirements were already added
    for _ in range(40):
        changed = False
        for name in sorted(cons):
            held = pins.get(name)
            if not (held and cons[name].contains(held[0], prereleases=True)):
                data = project(name)
                best = None
                for strict in (True, False):            # a release younger than --min-age-days only when nothing older fits
                    for text, files in data["releases"].items():
                        try:
                            version = Version(text)
                        except InvalidVersion:
                            continue
                        if (version.is_prerelease and name not in exact) or not cons[name].contains(version, prereleases=True):
                            continue
                        files = usable_files(files)
                        if not files or (strict and name not in exact and age_days(files) < min_age):
                            continue
                        if best is None or version > best[0]:
                            best = (version, text, files)
                    if best:
                        break
                if best is None:
                    raise SystemExit(f"no usable release of {name} satisfies {cons[name] or 'any version'}")
                pins[name] = held = (best[1], best[2])
                changed = True
            key = (held[0], frozenset(extras.get(name, set())))
            if expanded.get(name) != key:
                expanded[name] = key
                changed = True
                if all(f["filename"].endswith((".tar.gz", ".zip")) for f in held[1]):
                    print(f"note: {name}=={held[0]} is source-only; PyPI lists no dependencies for it, so list any it needs in "
                          f"requirements-home.in", file=sys.stderr)
                for req in requires(name, held[0]):
                    if applies(req, extras.get(name, set())):
                        add(req, name)
        if not changed:
            break
    else:
        raise SystemExit("resolution did not settle")
    for name, (version, _files) in pins.items():          # the last word: every requirement of every pin holds
        for req in requires(name, version):
            other = canonicalize_name(req.name)
            if applies(req, extras.get(name, set())) and (
                    other not in pins or not req.specifier.contains(pins[other][0], prereleases=True)):
                raise SystemExit(f"{name}=={version} needs {req} but the pin is {pins.get(other, ('missing',))[0]}")
    return pins, who


def torch_wheel(version: str, index: str) -> tuple[str, int | None, str]:
    """(filename, size, sha256) of torch VERSION+INDEX for cp312 win_amd64 from the official index page."""
    page = urllib.request.urlopen(f"https://download.pytorch.org/whl/{index}/torch/", timeout=60).read().decode()
    pattern = rf'href="([^"]*torch-{re.escape(version)}%2B{index}-cp312-cp312-win_amd64\.whl)#sha256=([0-9a-f]{{64}})"'
    match = re.search(pattern, page)
    if not match:
        raise SystemExit(f"torch {version}+{index} for cp312 win_amd64 is not on the official index")
    url = match.group(1)
    if url.startswith("/"):
        url = "https://download.pytorch.org" + url
    head = urllib.request.Request(url, method="HEAD")
    size = int(urllib.request.urlopen(head, timeout=60).headers.get("Content-Length") or 0) or None
    return url.rsplit("/", 1)[-1].replace("%2B", "+"), size, match.group(2)


def render(pins, who, skip, torch, min_age) -> tuple[str, str]:
    stamp = dt.date.today().isoformat()
    total = 0
    lines = []
    for name in sorted(pins):
        if name in skip or name == "torch":
            continue
        version, files = pins[name]
        chosen = [f for f in files if f["filename"].endswith(".whl")] or files
        total += max(f["size"] for f in chosen)
        via = ", ".join(sorted(w for w in who[name] if w != "<root>")) or "direct"
        young = age_days(files)
        note = f", released {young:.0f} days ago (an exact pin, or nothing older fits)" if young < min_age else ""
        allow = " star:allow" if LOOKS_LIKE_ADDRESS.fullmatch(version) else ""
        lines.append(f"# {name} {version}: {max(f['size'] for f in chosen) / 1e6:.1f} MB, via {via}{note}{allow}")
        # A version such as 10.3.10.19 reads like a private IP address to the repo commit scanner (star:allow); this harmless marker
        # (always true: `extra` is empty for a top-level requirement) carries the text it accepts.
        marker = ' ; extra != "star:allow"' if allow else ""
        lines.append(f"{name}=={version}{marker} \\")
        hashes = sorted({f["digests"]["sha256"] for f in files})
        lines += [f"    --hash=sha256:{h}" + (" \\" if i < len(hashes) - 1 else "") for i, h in enumerate(hashes)]
    head = (f"# GENERATED by installer/star-home/pin_requirements.py on {stamp} from requirements-home.in. Do not edit by hand.\n"
            f"# Target: Windows x64, CPython 3.12. Every package, its dependencies and the SHA-256 of every installable file.\n"
            f"# Releases are at least {min_age:g} days old on the day this was generated unless the line says otherwise. Download size of these wheels: "
            f"about {total / 1e6:.0f} MB (+ torch, see requirements-home-torch.txt).\n"
            f"# Install: pip install --no-deps --require-hashes -r requirements-home.txt   (setup.ps1 does this)\n"
            f"# Left out on purpose: {', '.join(sorted(skip)) or 'nothing'} (see requirements-home.in).\n")
    main_text = head + "\n".join(lines) + "\n"
    torch_text = ""
    if torch:
        filename, size, digest = torch_wheel(*torch)
        torch_text = (f"# GENERATED by installer/star-home/pin_requirements.py on {stamp}. CUDA build of PyTorch for her RTX 4060.\n"
                      f"# {filename}: {('%.0f MB' % (size / 1e6)) if size else 'size unknown'} from the official index; its own\n"
                      f"# dependencies are pinned in requirements-home.txt. Install:\n"
                      f"#   pip install --no-deps --require-hashes -r requirements-home-torch.txt   (setup.ps1 does this)\n"
                      f"--index-url https://download.pytorch.org/whl/{torch[1]}\n"
                      f"torch=={torch[0]}+{torch[1]} \\\n    --hash=sha256:{digest}\n")
    return main_text, torch_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="do not write; fail when the files are out of date")
    parser.add_argument("--min-age-days", type=float, default=7.0)
    args = parser.parse_args()
    wanted, skip, torch = read_source()
    pins, who = resolve(wanted, args.min_age_days, torch)
    main_text, torch_text = render(pins, who, skip, torch, args.min_age_days)
    if args.check:
        strip = lambda text: "\n".join(l for l in text.splitlines() if not l.startswith("# GENERATED"))  # noqa: E731
        stale = [p.name for p, t in ((OUT, main_text), (OUT_TORCH, torch_text)) if not p.exists() or strip(p.read_text(encoding="utf-8")) != strip(t)]
        print("up to date" if not stale else f"out of date: {', '.join(stale)} (run without --check)")
        return 1 if stale else 0
    OUT.write_text(main_text, encoding="utf-8", newline="\n")
    if torch_text:
        OUT_TORCH.write_text(torch_text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name} ({len([l for l in main_text.splitlines() if '==' in l])} packages) and {OUT_TORCH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
