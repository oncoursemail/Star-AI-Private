"""AST-backed static package resource inventory and real Windows command parity."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import shlex

import pytest

from star.build_info import read_build_info
from star.react_shell import react_index

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_windows.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-desktop.yml"
FLAGS = ("--add-data", "--hidden-import", "--collect-all", "--collect-submodules")
LOCAL_EXTRA_COLLECTIONS: frozenset[str] = frozenset()  # CI collects the office libraries too since #319
GENERATED = frozenset({"frontend/dist", "star/build-info.json"})

# Every AST __file__ root anchor in the reviewed star/**/*.py modules.
# This catalogue is intentionally explicit: new resource readers demand review.
PACKAGE_DATA_SITES = {
    "star/blender_bridge.py": "star/blender_worker.py",
    "star/build_info.py": "star/build-info.json",
    "star/build_planner.py": "examples/roblox-templates",
    "star/business/console.py": "star/data/business/console_ui.html",  # commerce draft console page
    "star/business/opportunities.py": "star/data/business/candidate_catalog.json",  # PR #404 research catalogue
    "star/character_lifecycle_lessons.py": "docs/lessons/roblox-character-lifecycle.md",
    "star/design_db.py": "star/data/design/ui-ux-pro-max",
    "star/gold_bank.py": "data/gold_bank/bank.jsonl",  # opt-in gold examples (gold-bank-20261020)
    "star/learned_week.py": "star/skill_packs",
    "star/luau_record_type_lessons.py": "docs/lessons/luau-record-types.md",
    "star/lesson_import.py": "star/skill_packs",
    "star/player_twins/bundle.py": "star/player_twins/luau",  # Player Twins engine doubles + driver
    "star/verify_ladder.py": "star/player_twins/luau",  # check-fix loop runs blocks in the same engine doubles
    "star/mistake_memory.py": "star/data/mistake_memory",  # seed rows + validated fixers (star/data is bundled)
    "star/react_shell.py": "frontend/dist",
    "star/reverse_engineering.py": "star/re_scripts",  # Ghidra scripts (PR #344), not in the PyInstaller lists
    "star/roblox_api_confusions.py": "data/roblox_api_confusions.json",
    "star/roblox_api_dataset.py": "data/roblox_api/roblox_api.json",
    "star/roblox_cutscene_studio.py": "star/skill_packs",  # roblox-cutscenes pack luau/ (PR #351)
    "star/roblox_vfx_studio.py": "star/skill_packs",  # roblox-vfx-composer pack luau/ (PR #327)
    "star/skill_import.py": "star/skill_packs",  # SkillForge: refuses to shadow a bundled pack name
    "star/skill_packs/__init__.py": "star/skill_packs",
    "star/studio_milestones.py": "evals/studio",
    "star/voice/catalog.py": "star/voice/voices.json",
}
OTHER_FILE_ANCHORS = {
    "star/architecture_pipeline.py": "opt-in Blender export runs scripts/blender_building.py from a source checkout",
    "star/best_of_n.py": "developer-only evaluation prelude ('' in the packaged app)",
    "star/cli.py": "source-only CLI",
    "star/discord_supervisor.py": "source checkout of the Discord bot (STAR_CHECKOUT for the packaged app)",
    "star/discord_bot/gpu_worker.py": "source checkout that the PC GPU worker's logon task runs",
    "star/eval_gate.py": "developer-only evaluation result files",
    "star/eval_runner.py": "developer-only evaluation fixtures",
    "star/failure_ledger.py": "developer-only evaluation prelude",
    "star/general_knowledge_benchmark.py": "source-only benchmark",
    "star/gold_bank_verify.py": "developer-only gold bank build tool (needs STAR Server)",
    "star/github_app.py": "source-root check blocks credential files",
    "star/media_actions.py": "owner-installed external ComfyUI",
    "star/playtest_learning.py": "server-only playtest learning: robot + specs in server/studio_lab/playtest (brain 2)",
    "star/roblox_benchmark.py": "server-only Roblox benchmark: tasks + harness in benchmarks/roblox (repo checkout, brain 2)",
    "star/xray.py": "X-ray Eyes CLI (needs Lune or Studio MCP); its Luau is star/data/xray, bundled with star/data",
    "star/shared_brain/improve.py": "development verifier source hash",
}
PENDING_OWNER_REVIEW = frozenset({
    "star/re_scripts",
    "docs/lessons/roblox-character-lifecycle.md",
    "docs/lessons/luau-record-types.md",
    "examples/roblox-templates",
    "data/roblox_api_confusions.json",
    "data/roblox_api/roblox_api.json",  # bundled API dump (#331): not packaged yet
    "data/gold_bank/bank.jsonl",  # gold bank: not packaged yet (missing file = no examples)
    "evals/studio",  # do not bundle protected evaluation manifests blindly
})


def _commands(local_text: str, workflow_text: str) -> tuple[list[str], list[str]]:
    local = re.search(r"Invoke-CheckedNative \$python @\(('-m',\s*'PyInstaller'.*?)\) 'PyInstaller'",
                      local_text, flags=re.DOTALL)
    workflow = re.search(r"(?ms)^\s*python @pyinstaller\s+(.*?)^\s*if \(\$LASTEXITCODE",
                         workflow_text)
    assert local is not None and workflow is not None, "PyInstaller command changed"
    local_argv = re.findall(r"'([^']*)'", local.group(1))
    assert local_argv[:2] == ["-m", "PyInstaller"] and "pip" not in local_argv
    ci_argv = shlex.split(workflow.group(1).replace(chr(96), " "))
    assert "--noconfirm" in local_argv and "--noconfirm" in ci_argv
    return local_argv, ci_argv


def _sets(argv: list[str]) -> dict[str, frozenset[str]]:
    selections: dict[str, set[str]] = {name: set() for name in FLAGS}
    for i, value in enumerate(argv):
        if value not in selections:
            continue
        assert i + 1 < len(argv) and not argv[i + 1].startswith("--")
        assert argv[i + 1] not in selections[value], "Duplicate PyInstaller option"
        selections[value].add(argv[i + 1])
    return {name: frozenset(values) for name, values in selections.items()}


def _assert_parity(local: dict[str, frozenset[str]],
                   ci: dict[str, frozenset[str]]) -> None:
    assert local["--add-data"] == ci["--add-data"], "Local and CI data diverged"
    assert local["--hidden-import"] == ci["--hidden-import"], "Hidden imports diverged"
    assert local["--collect-submodules"] == ci["--collect-submodules"]
    assert local["--collect-all"] - ci["--collect-all"] == LOCAL_EXTRA_COLLECTIONS
    assert not ci["--collect-all"] - local["--collect-all"]


def _roots_in_python_ast() -> set[str]:
    found: set[str] = set()
    for file in (ROOT / "star").rglob("*.py"):
        syntax = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        if any(isinstance(node, ast.Name) and node.id == "__file__"
               for node in ast.walk(syntax)):
            found.add(file.relative_to(ROOT).as_posix())
    return found


def _bundle_has(resource: str, flags: frozenset[str]) -> bool:
    return any(resource == data.split(";", 1)[0]
               or resource.startswith(data.split(";", 1)[0] + "/")
               for data in flags)


def test_all_ast_package_anchors_are_explicitly_reviewed():
    discovered = _roots_in_python_ast()
    # Every reader is listed by name below (no separate count: it only made unrelated PRs collide).
    assert discovered == set(PACKAGE_DATA_SITES) | set(OTHER_FILE_ANCHORS)
    assert not set(PACKAGE_DATA_SITES) & set(OTHER_FILE_ANCHORS)
    for resource in PACKAGE_DATA_SITES.values():
        assert (ROOT / resource).exists() or resource in GENERATED


def test_local_and_ci_real_pyinstaller_commands_are_consistent():
    local, ci = _commands(SCRIPT.read_text(encoding="utf-8"),
                          WORKFLOW.read_text(encoding="utf-8"))
    _assert_parity(_sets(local), _sets(ci))
    assert "star/data;star/data" in _sets(local)["--add-data"]
    assert "star/data;star/data" in _sets(ci)["--add-data"]


@pytest.mark.parametrize(("removed", "category"), [
    ("star/data;star/data", "--add-data"),
    ("PySide6.QtWebChannel", "--hidden-import"),
    ("jwt", "--collect-submodules"),
    ("faster_whisper", "--collect-all"),
])
def test_comparison_fails_when_a_real_command_option_drifts(removed, category):
    local, ci = _commands(SCRIPT.read_text(encoding="utf-8"),
                          WORKFLOW.read_text(encoding="utf-8"))
    local_options, ci_options = _sets(local), _sets(ci)
    assert removed in ci_options[category]
    changed_ci = {key: (value - {removed} if key == category else value)
                  for key, value in ci_options.items()}
    with pytest.raises(AssertionError):
        _assert_parity(local_options, changed_ci)


def test_runtime_missing_resources_are_recorded_and_not_claimed_bundled():
    local, ci = _commands(SCRIPT.read_text(encoding="utf-8"),
                          WORKFLOW.read_text(encoding="utf-8"))
    local_data, ci_data = _sets(local)["--add-data"], _sets(ci)["--add-data"]
    assert local_data == ci_data
    missing = {resource for resource in PACKAGE_DATA_SITES.values()
               if not _bundle_has(resource, ci_data)}
    assert missing == PENDING_OWNER_REVIEW
    bundled = set(PACKAGE_DATA_SITES.values()) - missing
    assert all(_bundle_has(resource, local_data) for resource in bundled)
    assert len(bundled) == 10  # five readers share the skill-pack directory; star/data/mistake_memory (S2) rides star/data


def test_actual_packaged_root_readers_resolve_resources(tmp_path):
    bundle = tmp_path / "frontend" / "dist"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<html>star</html>", encoding="utf-8")
    assert react_index(tmp_path) == bundle / "index.html"
    assert read_build_info(tmp_path)["stamped"] is False
