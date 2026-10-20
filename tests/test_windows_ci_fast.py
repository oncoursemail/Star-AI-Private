"""Fast Windows CI: caches and fast packaging only for validation runs, never for main; the installer-test guard.

The PowerShell checks run the real script text with pwsh (skipped where pwsh is missing). Nothing is installed:
the smoke script is stopped by its own checks before it touches any file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/windows-desktop.yml").read_text(encoding="utf-8")
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is not installed or not on PATH")


def _job(name: str) -> str:
    return re.split(r"(?m)^  [\w-]+:\n", WORKFLOW.split("\n  " + name + ":\n", 1)[1], maxsplit=1)[0]


def _run_block(job: str, title: str) -> str:
    step = _job(job).split(f"      - name: {title}\n", 1)[1].split("      - ", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


@needs_pwsh
@pytest.mark.parametrize("job", ["windows-tests", "windows-build"])
@pytest.mark.parametrize(("ref", "preview", "cache", "fast", "cached"), [
    ("refs/heads/main", "", "C:/cache", False, False),               # release: clean, maximum compression
    ("refs/heads/fix/a", "setup", "C:/cache", False, False),         # a preview people download: clean
    ("refs/heads/fix/a", "portable", "C:/cache", False, False),
    ("refs/pull/7/merge", "", "C:/cache", True, True),               # PR validation: caches + fast packaging
    ("refs/heads/fix/a", "none", "C:/cache", True, True),
    ("refs/pull/7/merge", "", "", True, False),                      # a runner without a cache folder
])
def test_only_validation_runs_use_host_caches_and_fast_packaging(tmp_path, job, ref, preview, cache, fast, cached):
    env_file, summary = tmp_path / "env", tmp_path / "summary"
    env_file.write_text("")
    environment = {**os.environ, "GITHUB_REF": ref, "STAR_PREVIEW_FORMAT": preview, "STAR_CI_CACHE": cache,
                   "GITHUB_ENV": str(env_file), "GITHUB_STEP_SUMMARY": str(summary)}
    script = _run_block(job, "Choose a clean release build or a cached validation build")
    subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script], env=environment, check=True,
                   capture_output=True, text=True, timeout=60)
    lines = env_file.read_text(encoding="utf-8-sig").split()
    assert ("STAR_FAST_PACKAGE=1" in lines) is fast
    assert (f"STAR_CACHE_DIR={cache}" in lines) is cached


def test_cache_and_fast_compression_are_used_only_through_those_switches():
    build = _job("windows-build")
    assert "--cache $env:STAR_CACHE_DIR" in build and "if ($env:STAR_CACHE_DIR)" in build
    assert "if ($env:STAR_FAST_PACKAGE) { $defines += '/DStarFastCompression' }" in build
    iss = (ROOT / "installer/STAR.iss").read_text(encoding="utf-8")
    fast, release = iss.split("#ifdef StarFastCompression\n", 1)[1].split("#endif", 1)[0].split("#else\n")
    assert "Compression=lzma2\nSolidCompression=yes" in release
    assert re.search(r"(?m)^Compression=zip/1$", fast) and "SolidCompression=no" in fast
    for step in ("Zip portable build", "Create standalone SHA-256 file for manual preview downloads"):
        # Upload-only files: never made on fast validation runs, always on main and previews.
        assert f"      - name: {step}\n        if: env.STAR_FAST_PACKAGE != '1'\n" in build


def _smoke(environment: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if key not in ("GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_ENVIRONMENT", "STAR_DISPOSABLE_WINDOWS",
                          "STAR_EXPECTED_HEAD_SHA")}
    env.update({"RUNNER_TEMP": str(tmp_path)}, **environment)
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File",
                           str(ROOT / "scripts/smoke_windows_installer.ps1")],
                          env=env, capture_output=True, text=True, timeout=60)


@needs_pwsh
@pytest.mark.skipif(os.name != "nt", reason="the installer guard reads the Windows process token")
def test_installer_guard_refuses_a_spoofed_sandbox_on_a_normal_machine(tmp_path):
    if os.environ.get("USERNAME", "").lower() == "wdagutilityaccount":
        pytest.skip("running inside Windows Sandbox")
    spoofed = _smoke({"STAR_DISPOSABLE_WINDOWS": "1", "USERNAME": "WDAGUtilityAccount",
                      "USERPROFILE": r"C:\Users\WDAGUtilityAccount", "APPDATA": r"C:\Users\WDAGUtilityAccount\AppData\Roaming",
                      "GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows"}, tmp_path)
    assert spoofed.returncode != 0
    assert "require a disposable Windows" in spoofed.stderr + spoofed.stdout
    # The GitHub-hosted path still passes the guard; it then stops at the next check, before writing anything.
    hosted = _smoke({"GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows", "RUNNER_ENVIRONMENT": "github-hosted"}, tmp_path)
    assert hosted.returncode != 0
    assert "An exact expected source SHA is required" in hosted.stderr + hosted.stdout
    assert list(tmp_path.iterdir()) == []


def _layered():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pyinstaller_layered", ROOT / "scripts/ci/pyinstaller_layered.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_layered_key_ignores_star_data_and_script_but_not_analysis_options():
    pytest.importorskip("PyInstaller")
    layered = _layered()
    def key(data, collect):
        return layered.base_key(["--noconfirm", "--add-data", data, "--collect-all", collect, "star_desktop.py"],
                                "star_desktop.py")
    assert key("star/data;star/data", "av") == key("star/other;star/other", "av")
    assert key("star/data;star/data", "av") != key("star/data;star/data", "pptx")


def test_saved_analysis_keeps_work_folder_files_and_is_replaced_only_when_asked(tmp_path):
    layered = _layered()
    work = tmp_path / "build" / "STAR"
    work.mkdir(parents=True)
    (work / "mod.pyc").write_bytes(b"pyc")

    def saved(tag):
        return {"pure": [["pkg", str(tmp_path / "site" / "pkg.py"), "PYMODULE"]], "binaries": [],
                "datas": [["pkg/mod.pyc", str(work / "mod.pyc"), "DATA"]], "rthooks": [], "names": [tag],
                "toplevel": ["pkg"], "workpath": os.path.normcase(str(work)) + os.sep}

    def names():
        return json.loads((cache / "k" / "base.json").read_text(encoding="utf-8"))["names"]

    cache = tmp_path / "cache"
    layered._save_base(cache, "k", saved("first"))
    copied = Path(json.loads((cache / "k" / "base.json").read_text(encoding="utf-8"))["datas"][0][1])
    assert copied.read_bytes() == b"pyc" and cache in copied.parents  # outlives the job's work folder
    layered._save_base(cache, "k", saved("second"))
    assert names() == ["first"]  # an existing analysis is kept ...
    layered._save_base(cache, "k", saved("third"), replace=True)
    assert names() == ["third"]  # ... unless a fallback full build replaces it
    assert [p.name for p in cache.iterdir()] == ["k"]  # no temporary or old folders left behind
