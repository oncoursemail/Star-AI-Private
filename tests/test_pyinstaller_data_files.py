"""The Windows build packages every data file STAR reads at run time.

PyInstaller copies Python modules on its own but never a package's data files: each one needs an
--add-data entry. Both PyInstaller commands (the CI workflow that builds releases and the local
scripts/build_windows.ps1) are parsed here and must agree, carry the required data (star/data with
the design database, star/voice/voices.json, skill packs, React bundle, build stamp) and cover
every non-Python file under star/. Static and offline: nothing is built or executed.
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-desktop.yml"
LOCAL = ROOT / "scripts" / "build_windows.ps1"
FLAGS = ("--add-data", "--hidden-import", "--collect-all", "--collect-submodules")
GENERATED = {"frontend/dist", "star/build-info.json"}  # produced by the build itself
REQUIRED_DATA = {
    "frontend/dist;frontend/dist",
    "star/build-info.json;star",
    "star/skill_packs;star/skill_packs",
    "star/data;star/data",
    "star/blender_worker.py;star",
    "star/voice/voices.json;star/voice",
}
# star/documents.py loads these with importlib, which PyInstaller cannot see; python-docx and
# python-pptx also need their template files. --collect-all brings modules and data.
DOCUMENT_LIBRARIES = {"pypdf", "docx", "pptx", "openpyxl"}


def ci_argv() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    # Release runs call `python -m PyInstaller`, validation runs the layered wrapper: one argument list for both.
    found = re.search(r"(?ms)^\s*python @pyinstaller\s+(.*?)^\s*if \(\$LASTEXITCODE", text)
    assert found, "CI PyInstaller command not found in windows-desktop.yml"
    return shlex.split(found.group(1).replace("`", " "))


def local_argv() -> list[str]:
    text = LOCAL.read_text(encoding="utf-8")
    found = re.search(r"Invoke-CheckedNative \$python @\(('-m',\s*'PyInstaller'.*?)\) 'PyInstaller'", text, re.S)
    assert found, "PyInstaller command not found in scripts/build_windows.ps1"
    argv = re.findall(r"'([^']*)'", found.group(1))
    assert argv[:2] == ["-m", "PyInstaller"]
    return argv[2:]


def options(argv: list[str]) -> dict[str, list[str]]:
    selected: dict[str, list[str]] = {flag: [] for flag in FLAGS}
    for position, value in enumerate(argv):
        if value in selected:
            assert position + 1 < len(argv) and not argv[position + 1].startswith("--")
            selected[value].append(argv[position + 1])
    for flag, values in selected.items():
        assert len(values) == len(set(values)), f"duplicate {flag} entry"
    return selected


@pytest.fixture(scope="module", params=["ci", "local"])
def command(request):
    return options(ci_argv() if request.param == "ci" else local_argv())


def test_ci_release_build_and_local_build_package_the_same_things():
    ci, local = options(ci_argv()), options(local_argv())
    for flag in FLAGS:
        assert sorted(ci[flag]) == sorted(local[flag]), f"{flag} differs between CI and build_windows.ps1"


def test_required_data_and_document_libraries_are_packaged(command):
    assert REQUIRED_DATA <= set(command["--add-data"])
    assert DOCUMENT_LIBRARIES <= set(command["--collect-all"])


def test_each_data_entry_lands_where_the_code_looks_for_it(command):
    # Readers resolve files next to their module (Path(__file__)...), so the bundle path must equal
    # the source path: a directory keeps its own path, a single file goes into its parent folder.
    for entry in command["--add-data"]:
        source, target = entry.split(";")
        assert (ROOT / source).exists() or source in GENERATED, f"{source} does not exist"
        expected = source if (ROOT / source).is_dir() or source == "frontend/dist" else source.rsplit("/", 1)[0]
        assert target == expected, entry


def test_every_non_python_file_under_star_is_packaged(command):
    sources = [entry.split(";")[0] for entry in command["--add-data"]]
    missing = []
    for path in sorted((ROOT / "star").rglob("*")):
        if not path.is_file() or path.suffix in (".py", ".pyc") or "__pycache__" in path.parts:
            continue
        name = path.relative_to(ROOT).as_posix()
        if not any(name == source or name.startswith(source + "/") for source in sources):
            missing.append(name)
    assert not missing, f"data files that STAR.exe would not contain: {missing}"


def test_design_database_and_voice_catalogue_are_read_from_packaged_locations(command):
    from star import design_db
    from star.voice import catalog
    sources = [entry.split(";")[0] for entry in command["--add-data"]]
    design = design_db.DATA_DIR.relative_to(ROOT).as_posix()
    voices = catalog.CATALOG_PATH.relative_to(ROOT).as_posix()
    assert design == "star/data/design/ui-ux-pro-max" and voices == "star/voice/voices.json"
    assert sorted(p.name for p in design_db.DATA_DIR.glob("*.csv")), "design database CSVs missing"
    for name in (design, voices):
        assert any(name == source or name.startswith(source + "/") for source in sources), name


def test_parser_notices_a_dropped_entry():
    # The checks above are only as good as the parser: removing one real entry must be detected.
    argv = ci_argv()
    position = argv.index("star/voice/voices.json;star/voice")
    trimmed = options(argv[:position - 1] + argv[position + 1:])
    assert not REQUIRED_DATA <= set(trimmed["--add-data"])
