"""PyInstaller for CI validation runs: analyse the third-party packages once, then only STAR's own code.

Almost all of a STAR PyInstaller run is spent analysing third-party packages (PySide6/Qt WebEngine hooks, av,
ctranslate2, the collect-all options): 6-7 minutes that are the same for every commit with the same requirements.
This wrapper runs the normal PyInstaller command line with one change:

* No base for this key yet: a normal full build. Afterwards the third-party part of the analysis (modules, binaries,
  data files, run-time hooks, and every module name the graph saw) is saved under --cache/<key>/base.json.
* A base exists: the analysis excludes the third-party top-level packages, so only STAR, the standard library and
  the scripts are analysed; the saved third-party part is merged back before the PYZ, EXE and COLLECT steps.
  If STAR imports any third-party module the full analysis never saw (a new dependency or a new submodule), the
  layered run is abandoned and a full build runs instead.

The key covers the Python base (sys.path entries), the PyInstaller version and every command-line option except the
STAR data folders (--add-data) and the entry script. Release builds do not use this wrapper (plain `python -m
PyInstaller --clean`), so a release is always a full analysis.

Usage: python scripts/ci/pyinstaller_layered.py --cache DIR -- <PyInstaller arguments>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

OWN_TOP_LEVEL = ("star", "star_desktop")
OWN_DATA_PREFIXES = ("star" + os.sep, "frontend" + os.sep)
VALUE_OPTIONS = {"--add-data"}


class FallBackToFullBuild(Exception):
    pass


def base_key(pyi_args: list[str], script: str) -> str:
    import PyInstaller

    digest = hashlib.sha256()
    digest.update(f"{PyInstaller.__version__}\n{sys.version}\n{sys.executable}\n".encode())
    for entry in sys.path:
        digest.update(entry.encode() + b"\0")
    skip = False
    for arg in pyi_args:
        if skip:
            skip = False
            continue
        if arg in VALUE_OPTIONS:
            skip = True
            continue
        if arg == script:
            continue
        digest.update(arg.encode() + b"\0")
    return digest.hexdigest()[:24]


def _site_dirs() -> list[str]:
    return [os.path.normcase(os.path.abspath(p)) + os.sep for p in sys.path if p.endswith("site-packages")]


def _is_own_module(name: str) -> bool:
    return name.split(".", 1)[0] in OWN_TOP_LEVEL


def _is_own_data(dest: str) -> bool:
    return os.path.normcase(dest).startswith(tuple(os.path.normcase(p) for p in OWN_DATA_PREFIXES))


def _toc(entries) -> list[list[str]]:
    return [list(entry) for entry in entries]


def run(pyi_args: list[str], cache: Path) -> str:
    import PyInstaller.__main__
    from PyInstaller.building import build_main
    from PyInstaller.building.datastruct import normalize_pyz_toc, normalize_toc
    from PyInstaller.config import CONF
    from PyInstaller.lib.modulegraph.modulegraph import ExcludedModule, MissingModule
    import PyInstaller.utils.hooks as hookutils

    script = next(arg for arg in reversed(pyi_args) if arg.endswith(".py"))
    program = Path(script).stem
    key = base_key(pyi_args, script)
    base_file = cache / key / "base.json"
    base = json.loads(base_file.read_text(encoding="utf-8")) if base_file.is_file() else None
    sites = _site_dirs()
    original = build_main.Analysis
    saved: dict = {}

    class FullAnalysis(original):
        def assemble(self):
            super().assemble()
            workpath = os.path.normcase(CONF["workpath"]) + os.sep
            names = sorted({str(node.identifier).strip("'")
                            for node in self.graph.iter_graph(start=self.graph._top_script_node)})
            saved.update(
                pure=_toc(e for e in self.pure if not _is_own_module(e[0])),
                binaries=_toc(self.binaries),
                datas=_toc(e for e in self.datas if not _is_own_data(e[0]) and e[0] != "base_library.zip"),
                rthooks=_toc(e for e in self.scripts if e[0] != program),
                names=names,
                workpath=workpath,
                toplevel=sorted({e[0].split(".", 1)[0] for e in self.pure if not _is_own_module(e[0])
                                 and os.path.normcase(os.path.abspath(e[1])).startswith(tuple(sites))}
                                | {e[0].split(os.sep, 1)[0] for e in self.binaries if e[2] == "EXTENSION"
                                   and os.path.normcase(os.path.abspath(e[1])).startswith(tuple(sites))}),
            )

    hook_names = ("collect_all", "collect_submodules", "collect_data_files", "collect_dynamic_libs", "copy_metadata")
    originals = {name: getattr(hookutils, name) for name in hook_names}

    class LayeredAnalysis(original):
        def __init__(self, *args, **kwargs):
            # The spec's collect_* calls (third-party only) ran with empty stubs; restore them for the hooks.
            for name, function in originals.items():
                setattr(hookutils, name, function)
            kwargs["excludes"] = list(kwargs.get("excludes") or []) + [t for t in base["toplevel"] if "." not in t]
            super().__init__(*args, **kwargs)

        def assemble(self):
            super().assemble()
            # `import PySide6.QtCharts` under an excluded PySide6 shows up as MissingModule('PySide6.QtCharts'), not as
            # an excluded node: so any excluded or missing node, or any node below an excluded package, must be one
            # the full analysis saw. Otherwise the saved analysis lacks it and a full build runs.
            known, excluded = set(base["names"]), set(base["toplevel"])
            unseen = sorted(
                name for node in self.graph.iter_graph(start=self.graph._top_script_node)
                if (name := str(node.identifier).strip("'")) not in known  # missing submodules come quoted
                and (isinstance(node, (ExcludedModule, MissingModule)) or name.split(".", 1)[0] in excluded))
            if unseen:
                raise FallBackToFullBuild(", ".join(unseen[:10]))
            # Saved entries first: where both name the same file (e.g. vcruntime140.dll), the full build's choice wins.
            self.pure[:] = normalize_pyz_toc([tuple(e) for e in base["pure"]] + self.pure)  # same list: keeps code cache
            self.binaries[:] = normalize_toc([tuple(e) for e in base["binaries"]] + self.binaries)
            self.datas[:] = normalize_toc([tuple(e) for e in base["datas"]] + self.datas)
            own = [e for e in self.scripts if e[0] == program]
            rthooks = [tuple(e) for e in base["rthooks"]]
            rthooks += [e for e in self.scripts if e[0] != program and e not in rthooks]
            self.scripts = normalize_toc(rthooks + own)

    def full_build(replace: bool = False) -> str:
        build_main.Analysis = FullAnalysis
        try:
            PyInstaller.__main__.run(pyi_args)
        finally:
            build_main.Analysis = original
        _save_base(cache, key, saved, replace)
        return "full"

    if base is None:
        return full_build()
    for name in hook_names:
        setattr(hookutils, name, (lambda *a, **k: ([], [], [])) if name == "collect_all" else (lambda *a, **k: []))
    build_main.Analysis = LayeredAnalysis
    try:
        PyInstaller.__main__.run(pyi_args)
        return "layered"
    except FallBackToFullBuild as missing:
        print(f"pyinstaller_layered: STAR imports modules the saved analysis never saw ({missing}); full build",
              flush=True)
    finally:
        build_main.Analysis = original
        for name, function in originals.items():
            setattr(hookutils, name, function)
    # The saved analysis is missing modules STAR now uses: replace it with this full build's analysis.
    return full_build(replace=True)


def _save_base(cache: Path, key: str, saved: dict, replace: bool = False) -> None:
    if not saved:
        return
    final = cache / key
    if (final / "base.json").is_file() and not replace:
        return
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.parent / f".tmp-{key}-{uuid.uuid4().hex[:8]}"
    (tmp / "files").mkdir(parents=True)
    workpath = saved.pop("workpath")
    for entry in saved["datas"] + saved["binaries"]:
        # Files PyInstaller generated in its work folder (compiled .pyc for some packages) do not outlive the job.
        if os.path.normcase(entry[1]).startswith(workpath):
            copy = tmp / "files" / uuid.uuid4().hex / os.path.basename(entry[1])
            copy.parent.mkdir()
            shutil.copy2(entry[1], copy)
            entry[1] = str(final / copy.relative_to(tmp))
    (tmp / "base.json").write_text(json.dumps(saved), encoding="utf-8")
    old = final.parent / f".old-{key}-{uuid.uuid4().hex[:8]}"
    if replace and final.exists():
        final.rename(old)
    try:
        tmp.rename(final)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv:
        raise SystemExit("usage: pyinstaller_layered.py --cache DIR -- <PyInstaller arguments>")
    split = argv.index("--")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args(argv[:split])
    mode = run(argv[split + 1:], args.cache.resolve())
    print(f"pyinstaller_layered: {mode} analysis", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
