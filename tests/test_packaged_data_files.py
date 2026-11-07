"""Every non-Python file the app reads at run time must be bundled by both Windows build paths.

The v0.9.0 and early v1.0 packages missed star/voice/voices.json, so Settings > Voice showed
"The voice list could not be shown" in the installed app (found in the v1.0 packaged acceptance).
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_TREES = ("star/skill_packs", "star/data", "star/studio_lab_specs", "star/player_twins/luau",
                 "star/player_twins/games")


def _runtime_data_files() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "star"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [name for name in listed.stdout.split() if not name.endswith(".py")
            and not name.startswith(tuple(tree + "/" for tree in BUNDLED_TREES))]


def test_voice_catalogue_is_a_runtime_data_file():
    assert "star/voice/voices.json" in _runtime_data_files()


def test_ci_build_and_local_build_bundle_every_runtime_data_file():
    workflow = (ROOT / ".github/workflows/windows-desktop.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts/build_windows.ps1").read_text(encoding="utf-8")
    for tree in BUNDLED_TREES:
        assert f"'{tree};{tree}'" in workflow and f"'{tree};{tree}'" in script, tree
    for name in _runtime_data_files():
        folder = name.rsplit("/", 1)[0]
        assert f"'{name};{folder}'" in workflow, name
        assert f"'{name};{folder}'" in script, name
