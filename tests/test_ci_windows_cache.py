"""scripts/ci_windows_cache.py: content keys, atomic entries and the job venv layered over the base venv."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ci_windows_cache", ROOT / "scripts" / "ci_windows_cache.py")
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


def test_base_key_changes_with_any_requirement_or_extra(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("PySide6>=6.12\n")
    b.write_text("pytest\n")
    key = cache.python_base_key([a, b], ["pyinstaller>=6.10,<7"])
    assert key == cache.python_base_key([a, b], ["pyinstaller>=6.10,<7"])
    assert key != cache.python_base_key([a, b], ["pyinstaller>=6.11,<7"])
    b.write_text("pytest>=9\n")
    assert key != cache.python_base_key([a, b], ["pyinstaller>=6.10,<7"])


def test_restore_misses_until_a_complete_entry_is_saved(tmp_path):
    store, src, dest = tmp_path / "cache", tmp_path / "dist", tmp_path / "out" / "dist"
    (src / "assets").mkdir(parents=True)
    (src / "index.html").write_text("<html></html>")
    (src / "assets" / "app.js").write_text("x")
    assert cache.main(["restore", "--cache", str(store), "--kind", "frontend", "--key", "abc",
                       "--dest", str(dest)]) == cache.MISS
    # A leftover temporary folder from a cancelled job is never used as an entry.
    (store / "frontend" / ".tmp-abc-dead").mkdir(parents=True)
    assert not cache.restore(store, "frontend", "abc", dest)
    assert cache.save(store, "frontend", "abc", src)
    assert not cache.save(store, "frontend", "abc", src)  # first writer wins, entry unchanged
    dest.parent.mkdir()
    dest.mkdir()
    (dest / "stale.js").write_text("old")
    assert cache.restore(store, "frontend", "abc", dest)
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")) == ["assets", "assets/app.js", "index.html"]


def test_unsafe_keys_are_refused(tmp_path):
    for key in ("../x", "a/b", "", ".hidden"):
        try:
            cache.main(["restore", "--cache", str(tmp_path), "--kind", "frontend", "--key", key,
                        "--dest", str(tmp_path / "d")])
        except SystemExit as exc:
            assert "unsafe cache key" in str(exc)
        else:
            raise AssertionError(key)


def test_job_venv_sees_base_packages_and_keeps_its_own_installs_separate(tmp_path):
    base = tmp_path / "base"
    cache.venv.create(base, with_pip=False)
    base_site = cache.site_packages(base)
    (base_site / "star_base_probe.py").write_text("VALUE = 'from-base'\n")
    # .pth files inside the base run too (pywin32 and others depend on that).
    (base_site / "probe_extra").mkdir()
    (base_site / "probe_extra" / "star_pth_probe.py").write_text("VALUE = 'from-pth'\n")
    (base_site / "probe.pth").write_text("probe_extra\n")
    job = tmp_path / "job"
    cache.make_job_venv(job, base)
    (cache.site_packages(job) / "star_job_only.py").write_text("VALUE = 'job'\n")
    out = subprocess.run([str(cache.env_python(job)), "-c",
                          "import star_base_probe, star_pth_probe, star_job_only;"
                          "print(star_base_probe.VALUE, star_pth_probe.VALUE, star_job_only.VALUE)"],
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["from-base", "from-pth", "job"]
    assert not (base_site / "star_job_only.py").exists()
