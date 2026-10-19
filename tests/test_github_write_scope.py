"""What STAR's own GitHub App may write, and where its pull requests may point. No network."""
import asyncio

import pytest

from star.github_app import GitHubApp, valid_upload_path
from star.selfbuild import skill_path
from star.repository_roles import SOURCE_REPO as REPO, SOURCE_REPO_ID, RELEASE_REPO

ALLOWED = (
    "star/skills/tween_helpers.py",
    "star/skills/ui/layout_grid.py",
    "docs/skills/tween_helpers.md",
)

REFUSED = (
    "tests/test_star.py", "tests/conftest.py", "tests/fixtures/shared_brain_retrieval.json",
    "pyproject.toml", "requirements.txt", "README.md", "main.py",
    "star/agent.py", "star/policy.py", "star/github_app.py", "star/selfbuild.py", "star/frontier_lab.py",
    "star/evals.py", "star/eval_gate.py", "star/eval_runner.py", "star/updates.py", "star/__init__.py",
    "star/skills/__init__.py", "star/skills/notes.md", "star/skills/data.json", "star/skillsx/a.py",
    "evals/roblox_cases.json", "evals/roblox/golden-tasks-v2.json", "evals/results/baseline-v2.json",
    "docs/evals.md", "docs/SECURITY_AND_AUTONOMY.md", "docs/GITHUB_APP_SETUP.md", "docs/skills/run.py",
    "docs/skills/../evals.md", "docs/skills/.hidden.md", "docs/skillsx/a.md",
    ".github/workflows/windows-desktop.yml", ".github/workflows/tests.yml", ".env", ".gitattributes",
    "star/skills/../policy.py", "star/skills/./a.py", "star/skills//a.py", "/star/skills/a.py",
    "star\\skills\\a.py", "star/skills/.secret.py", "star/skills/" + "a" * 200 + ".py", "",
)


@pytest.mark.parametrize("path", ALLOWED)
def test_skill_modules_and_their_pages_may_be_uploaded(path):
    assert valid_upload_path(path)


@pytest.mark.parametrize("path", REFUSED)
def test_tests_gate_policy_build_files_and_workflows_may_not_be_uploaded(path):
    assert not valid_upload_path(path)


@pytest.mark.parametrize("path", ALLOWED + REFUSED)
def test_upload_rule_equals_the_self_builder_rule(path):
    assert valid_upload_path(path) == skill_path(path)


@pytest.mark.parametrize("path", [None, 7, b"star/skills/a.py", ["star/skills/a.py"]])
def test_upload_rule_refuses_values_that_are_not_text(path):
    assert not valid_upload_path(path)


class Recorder(GitHubApp):
    """A GitHubApp whose requests are recorded and answered from a table instead of being sent."""

    def __init__(self, tmp_path, repo=REPO, answers=None, **kwargs):
        key = tmp_path / "fixture.pem"
        key.write_text("not a key: test fixture", encoding="utf-8")
        super().__init__("123", "456", key, repo, **kwargs)
        self.calls = []
        self.answers = answers or {}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json")))
        return self.answers.get((method, path), {})


@pytest.mark.parametrize("path", ["tests/test_star.py", "pyproject.toml", "star/policy.py", "docs/evals.md",
                                  ".github/workflows/tests.yml", "star/skills/__init__.py"])
def test_write_branch_file_refuses_before_any_request(tmp_path, path):
    app = Recorder(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(app.write_branch_file("star/demo", path, b"x = 1\n", "test"))
    assert app.calls == []


def test_write_branch_file_still_writes_a_skill_module(tmp_path):
    app = Recorder(tmp_path, answers=answers(), base_branch=WORK)
    asyncio.run(app.write_branch_file("star/demo", "star/skills/tween_helpers.py", b"x = 1\n", "test"))
    assert [(m, p) for m, p, _ in app.calls] == [
        REPO_INFO,
        ("GET", f"/repos/{REPO}/contents/star/skills/tween_helpers.py"),
        ("PUT", f"/repos/{REPO}/contents/star/skills/tween_helpers.py")]
    payload = app.calls[-1][2]
    assert payload["branch"] == "star/demo"
    assert "AI-Actor: Star AI" in payload["message"]
    assert "AI-Run-ID: " + app.run_id in payload["message"]
    assert "AI-Tests: not-recorded" in payload["message"]
    assert app.last_activity["stage"] == "committed-proposal"


WORK = "star/work-branch"
REPO_INFO = ("GET", f"/repos/{REPO}")
WORK_REF = ("GET", f"/repos/{REPO}/git/ref/heads/{WORK}")


def answers(default_branch="main"):
    return {REPO_INFO: {"id": SOURCE_REPO_ID, "full_name": REPO, "private": True,
                        "default_branch": default_branch}, WORK_REF: {"object": {"sha": "b" * 40}},
            ("POST", f"/repos/{REPO}/pulls"): {"html_url": "https://example.invalid/pull/1"}}


def writes(app):
    return [(m, p, j) for m, p, j in app.calls if m != "GET"]


def test_new_branch_is_cut_from_the_work_branch_not_from_main(tmp_path):
    app = Recorder(tmp_path, answers=answers(), base_branch=WORK)
    assert asyncio.run(app.create_branch("star/skill-1")) == WORK
    assert [(m, p) for m, p, _ in app.calls] == [REPO_INFO, WORK_REF, ("POST", f"/repos/{REPO}/git/refs")]
    assert app.calls[-1][2] == {"ref": "refs/heads/star/skill-1", "sha": "b" * 40}
    assert not any("heads/main" in p for _, p, _ in app.calls)


def test_pull_request_points_at_the_work_branch_and_is_a_draft(tmp_path):
    app = Recorder(tmp_path, answers=answers(), base_branch=WORK)
    asyncio.run(app.open_pr(WORK, "star/skill-1", "title", "body"))
    observed = writes(app)
    assert len(observed) == 1 and observed[0][:2] == ("POST", f"/repos/{REPO}/pulls")
    payload = observed[0][2]
    assert {k: payload[k] for k in ("title", "base", "head", "draft")} == {
        "title": "title", "base": WORK, "head": "star/skill-1", "draft": True}
    assert payload["body"].startswith("body\n\n---\n")
    assert "<!-- star-ai-run:" + app.run_id + " -->" in payload["body"]
    assert "has not verified tests" in payload["body"]
    assert app.last_activity["stage"] == "pull-request-proposed"


@pytest.mark.parametrize("base", ["main", "master", "release", "develop", "", None, "refs/heads/main",
                                  "star/Other", "star/another-branch", "star/skill-1"])
def test_pull_request_against_main_or_any_other_branch_is_refused(tmp_path, base):
    app = Recorder(tmp_path, answers=answers(), base_branch=WORK)
    with pytest.raises(PermissionError):
        asyncio.run(app.open_pr(base, "star/skill-1", "title", "body"))
    assert writes(app) == []


def test_without_a_configured_work_branch_nothing_is_created(tmp_path):
    app = Recorder(tmp_path, answers=answers())
    with pytest.raises(PermissionError):
        asyncio.run(app.create_branch("star/skill-1"))
    with pytest.raises(PermissionError):
        asyncio.run(app.open_pr("main", "star/skill-1", "title", "body"))
    with pytest.raises(PermissionError):
        asyncio.run(app.open_pr(WORK, "star/skill-1", "title", "body"))
    assert app.calls == []


@pytest.mark.parametrize("default_branch", [WORK, "", None])
def test_work_branch_that_is_the_default_branch_is_refused(tmp_path, default_branch):
    app = Recorder(tmp_path, answers=answers(default_branch), base_branch=WORK)
    with pytest.raises(PermissionError):
        asyncio.run(app.create_branch("star/skill-1"))
    with pytest.raises(PermissionError):
        asyncio.run(app.open_pr(WORK, "star/skill-1", "title", "body"))
    assert writes(app) == []


@pytest.mark.parametrize("base", ["main", "master", "release/1.0", "Star/work", "star/", "star/UPPER", "feature/x"])
def test_only_a_star_work_branch_can_be_configured(tmp_path, base):
    with pytest.raises(ValueError):
        Recorder(tmp_path, base_branch=base)


def test_work_branch_comes_from_the_environment(tmp_path, monkeypatch):
    from star import github_app
    key = tmp_path / "fixture.pem"
    key.write_text("not a key: test fixture", encoding="utf-8")
    for name, value in (("STAR_GITHUB_PRIVATE_KEY_FILE", str(key)), ("STAR_GITHUB_APP_ID", "123"),
                        ("STAR_GITHUB_INSTALLATION_ID", "456"), ("STAR_GITHUB_REPO", REPO)):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("STAR_GITHUB_BASE_BRANCH", raising=False)
    assert github_app.from_env().base_branch == ""
    monkeypatch.setenv("STAR_GITHUB_BASE_BRANCH", f" {WORK} ")
    assert github_app.from_env().base_branch == WORK
    monkeypatch.setenv("STAR_GITHUB_BASE_BRANCH", "main")
    with pytest.raises(ValueError):
        github_app.from_env()


def test_files_are_not_written_straight_into_the_work_branch(tmp_path):
    app = Recorder(tmp_path, answers=answers(), base_branch=WORK)
    with pytest.raises(PermissionError):
        asyncio.run(app.write_branch_file(WORK, "star/skills/tween_helpers.py", b"x = 1\n", "test"))
    assert app.calls == []


def test_self_build_refuses_before_any_model_call_when_the_pull_request_would_target_main(tmp_path):
    import subprocess
    from star.selfbuild import develop

    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run([*git, "add", "note.txt"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "fixture"], cwd=repo, check=True)

    class NoModel:
        def __getattr__(self, name):
            raise AssertionError("the model must not be asked")

    app = Recorder(tmp_path, answers=answers())
    with pytest.raises(PermissionError):
        asyncio.run(develop(client=NoModel(), model="fixture", repository=repo, task="improve a skill", github=app))
    branches = subprocess.run(["git", "branch", "--list", "star/*"], cwd=repo, capture_output=True, text=True, check=True)
    assert branches.stdout.strip() == "" and app.calls == []


@pytest.mark.parametrize("operation", ["branch", "file", "pr"])
def test_developer_client_cannot_write_to_public_downloads(tmp_path, operation):
    app = Recorder(tmp_path, repo=RELEASE_REPO, base_branch=WORK)
    with pytest.raises(PermissionError):
        if operation == "branch":
            asyncio.run(app.create_branch("star/demo"))
        elif operation == "file":
            asyncio.run(app.write_branch_file("star/demo", ALLOWED[0], b"x=1", "test"))
        else:
            asyncio.run(app.open_pr(WORK, "star/demo", "test", "test"))
    assert app.calls == [] and app.last_activity is None


@pytest.mark.parametrize("change", [{"id": 1}, {"private": False}, {"full_name": RELEASE_REPO}])
def test_changed_source_identity_cannot_receive_a_proposal(tmp_path, change):
    data = answers()
    data[REPO_INFO].update(change)
    app = Recorder(tmp_path, answers=data, base_branch=WORK)
    with pytest.raises(PermissionError):
        asyncio.run(app.write_branch_file("star/demo", ALLOWED[0], b"x=1", "test"))
    assert writes(app) == [] and app.last_activity is None
