"""W2 protected closure: generator branches may not edit evals, graders, the holdout, stored results or the gate
(star/protected_paths.py, .github/workflows/protected-closure.yml). No network."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from star import protected_paths as pp

ROOT = Path(__file__).resolve().parents[1]

# Twelve pre-registered forbidden fixtures (one per protected area) and one allowed control.
FORBIDDEN = [
    "evals/roblox/golden-tasks-v2.json",
    "evals/roblox/holdout-v1.json",
    "evals/roblox/holdout-v2.json",                 # a new holdout file is protected before it exists
    "evals/results/baseline-v2.json",
    "evals/results/new-run.json",
    "star/eval_gate.py",
    "star/eval_runner.py",
    "star/eval_checks.py",
    "star/eval_sandbox.py",
    "star/eval_stats.py",
    "server/night_school/nightschool/pool.py",
    ".github/workflows/protected-closure.yml",
]
ALLOWED = "star/skill_packs/roblox-ui/SKILL.md"
GENERATOR = "star/chatgpt-AP-improve-ui-20261013"


@pytest.mark.parametrize("path", FORBIDDEN)
def test_each_forbidden_fixture_is_refused_for_a_generator_branch(path):
    assert pp.protected_pattern(path)
    assert pp.violations(GENERATOR, [path]) == [(path, pp.protected_pattern(path))]


def test_the_cli_refuses_all_twelve_fixtures_and_passes_the_control(capsys):
    assert len(FORBIDDEN) == 12
    assert pp.main(["--branch", GENERATOR, "--files", *FORBIDDEN]) == 1
    err = capsys.readouterr().err
    assert "REFUSED" in err and all(path in err for path in FORBIDDEN)
    assert pp.main(["--branch", GENERATOR, "--files", ALLOWED]) == 0
    assert pp.main(["--branch", GENERATOR, "--files"]) == 0                     # an empty diff
    assert pp.violations(GENERATOR, [ALLOWED, "star/desktop_core.py", "docs/evals.md"]) == []


def test_the_guard_protects_itself_and_the_promotion_code():
    for path in ("star/protected_paths.py", "tests/test_protected_closure.py", "tests/test_eval_stats.py",
                 "tests/test_eval_gate.py", "server/night_school/nightschool/engine.py",
                 "server/night_school/nightschool/config.py", ".github/workflows/tests.yml"):
        assert pp.violations(GENERATOR, [path]), path


def test_generator_branch_names_follow_the_documented_convention():
    for name in ("star/chatgpt-apply-review-pr48-20261012", "STAR/ChatGPT-x", "refs/heads/star/gen-lessons-1",
                 "origin/star/selfbuild-skill-1", "star/genesis-update", "star/night-school-outbox-20261013",
                 "star/outbox-20261014", "star/autopilot-fix"):
        assert pp.is_generator_branch(name), name
    for name in ("star/eval-gate-v2-20261013", "star/night-school-20261012", "star/next", "main", "",
                 "star/custodian-holdout-v2-20261020", "feature/chatgpt-x"):
        assert not pp.is_generator_branch(name), name


def test_non_generator_branches_and_the_owner_label_are_not_refused(capsys):
    assert pp.violations("star/eval-gate-v2-20261013", FORBIDDEN) == []
    assert pp.violations(GENERATOR, FORBIDDEN, owner_approved=True) == []
    assert pp.main(["--branch", "star/eval-gate-v2-20261013", "--files", *FORBIDDEN]) == 0
    assert pp.main(["--branch", GENERATOR, "--labels", "docs," + pp.OWNER_LABEL, "--files", *FORBIDDEN]) == 0
    assert pp.main(["--branch", GENERATOR, "--labels", "owner-approved", "--files", *FORBIDDEN]) == 1
    assert "label" in capsys.readouterr().out


def test_paths_are_normalised_before_matching():
    for path in ("evals\\results\\x.json", "./evals/results/x.json", "/star/eval_gate.py", "EVALS/Roblox/holdout-v1.json"):
        assert pp.protected_pattern(path), path
    assert pp.protected_pattern("star/eval_gate.py.bak") is None
    assert pp.protected_pattern("docs/evals/holdout.md") is None


def _git(cwd, *args):
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                           *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_the_git_diff_mode_sees_both_sides_of_a_rename_out_of_the_closure(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "base")
    (tmp_path / "evals" / "results").mkdir(parents=True)
    (tmp_path / "evals" / "results" / "r.json").write_text("{}", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "star/chatgpt-test")
    (tmp_path / "README.md").write_text("y", encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "allowed change")
    monkeypatch.chdir(tmp_path)
    assert pp.changed_files("base") == ["README.md"]
    assert pp.main(["--branch", "star/chatgpt-test", "--base", "base"]) == 0
    (tmp_path / "moved").mkdir()
    _git(tmp_path, "mv", "evals/results/r.json", "moved/r.json")
    _git(tmp_path, "commit", "-q", "-m", "hide a result")
    assert "evals/results/r.json" in pp.changed_files("base")
    assert pp.main(["--branch", "star/chatgpt-test", "--base", "base"]) == 1
    assert pp.main(["--branch", "star/chatgpt-test", "--base", "no-such-ref"]) == 2


def test_the_ci_workflow_uses_the_same_branch_list_and_the_base_branch_guard():
    text = (ROOT / ".github" / "workflows" / "protected-closure.yml").read_text(encoding="utf-8")
    listed = re.findall(r"'(star/[^']+)'", text.split("branches:", 1)[1].split("permissions:", 1)[0])
    assert tuple(listed) == pp.GENERATOR_BRANCH_PATTERNS
    assert "pull_request_target:" in text and "pull_request.base.sha" in text
    assert "persist-credentials: false" in text and "contents: read" in text
    assert "python \"$RUNNER_TEMP/guard.py\"" in text                     # the base copy runs, not the PR's
    # A private repository requires authenticated fetches, but no fetch step may
    # grant write scopes or persist the temporary job credential.
    assert text.count("git -c credential.helper='!gh auth git-credential' fetch --no-tags origin") == 2
    assert text.count("GH_TOKEN: ${{ github.token }}") == 2
    assert "contents: write" not in text


def test_model_facing_code_cannot_write_the_closure_or_call_promotion():
    from star import github_app, intelligence, selfbuild
    # The self-builder and STAR's GitHub App may write skill files only: no protected path gets through.
    for path in FORBIDDEN + ["star/protected_paths.py", "tests/test_eval_gate.py"]:
        assert not selfbuild.skill_path(path) and not github_app.valid_upload_path(path), path
    # The model-facing tool catalogue has no tool that promotes, gates or touches evaluation material.
    names = sorted(intelligence.ALL_TOOLS)
    assert names and not [n for n in names if re.search(r"promot|gate|holdout|grader|eval|lesson_import|commit", n)]
    source = Path(intelligence.__file__).read_text(encoding="utf-8")
    for module in ("eval_gate", "eval_stats", "promoter", "frontier_lab", "lesson_import", "protected_paths"):
        assert not re.search(rf"\b(import|from)\b[^\n]*\b{module}\b", source), module
