"""Execute trusted inline workflow Python against fake GitHub responses, never live APIs."""
import ast
import base64
import io
import json
from pathlib import Path
import textwrap
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "oncoursemail/Star-AI-Private"
PUBLIC = "oncoursemail/Star-AI"
SHA = "a" * 40


def inline(name):
    text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    code = textwrap.dedent(text.split("run: |\n", 1)[1])
    ast.parse(code)
    return text, code


def test_metadata_is_base_owned_and_cannot_execute_pr_code_or_publish():
    text, code = inline("star-activity.yml")
    assert "pull_request_target:" in text
    assert "contents: read" in text and "issues: write" in text
    assert "contents: write" not in text and "actions: write" not in text
    assert "uses: actions/checkout" not in text
    assert "STAR_PUBLIC_RELEASE_APP_PRIVATE_KEY" not in text
    calls = [n.func.id for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert not {"eval", "exec", "compile"} & set(calls)
    assert "performed_via_github_app" in code and "STAR_DEVELOPER_BOT_ID" in code
    assert "receipt is not None" in code


def test_codespaces_cannot_publish_or_start_models_implicitly():
    config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
    assert config["containerEnv"]["STAR_GITHUB_REPO"] == SOURCE
    extra = config["customizations"]["codespaces"]["repositories"]
    assert extra == {PUBLIC: {"permissions": {"contents": "read"}}}
    assert "postStartCommand" not in config
    assert "pip install" not in config["postCreateCommand"]
    assert not {"mounts", "privileged", "runArgs"} & config.keys()


def run_handoff(tmp_path, monkeypatch, *, before="1.0.1", after="1.0.2", current=SHA,
                producer=1412474221, source_private=True):
    _text, code = inline("auto-patch-release.yml")
    event = {"workflow_run": {"repository": {"id": producer}, "head_sha": SHA,
                              "path": ".github/workflows/windows-desktop.yml"}}
    location = tmp_path / "event.json"
    location.write_text(json.dumps(event))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(location))
    monkeypatch.setenv("GH_TOKEN", "test-only-not-a-real-token")
    calls = []

    class FakeOpener:
        def open(self, request, timeout):
            assert timeout <= 20
            url = request.full_url
            assert url.startswith("https://api.github.com/repos/")
            calls.append((request.get_method(), url))
            private_root = "https://api.github.com/repos/" + SOURCE
            public_root = "https://api.github.com/repos/" + PUBLIC
            if url == private_root:
                payload = {"id": 1412474221, "private": source_private}
            elif url == private_root + "/commits/main":
                payload = {"sha": current}
            elif url == private_root + "/contents/star/version.py?ref=" + SHA:
                version = f'__version__ = "{after}"\n'.encode()
                payload = {"encoding": "base64", "size": len(version),
                           "content": base64.b64encode(version).decode()}
            elif url == public_root:
                assert request.get_header("Authorization") is None
                payload = {"id": 1424898960, "private": False}
            elif url == public_root + "/releases/latest":
                assert request.get_header("Authorization") is None
                if before is None:
                    raise urllib.error.HTTPError(url, 404, "fixture", {}, None)
                payload = {"tag_name": "v" + before, "draft": False, "prerelease": False}
            elif url == private_root + "/actions/workflows/windows-desktop.yml/dispatches":
                assert request.get_method() == "POST"
                assert json.loads(request.data) == {"ref": "main"}
                payload = None
            else:
                raise AssertionError("Unexpected workflow request: " + url)
            return io.BytesIO(json.dumps(payload).encode() if payload is not None else b"")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: FakeOpener())
    try:
        exec(compile(code, "trusted-workflow-fixture", "exec"), {})
    except SystemExit as exc:
        assert exc.code == 0
    return calls


def test_only_exact_next_patch_dispatches_the_existing_trusted_workflow(tmp_path, monkeypatch):
    calls = run_handoff(tmp_path, monkeypatch)
    assert sum(method == "POST" for method, _ in calls) == 1
    assert calls[-1][1].endswith("windows-desktop.yml/dispatches")


@pytest.mark.parametrize("values", [
    {"before": None}, {"after": "1.0.1"}, {"after": "1.0.4"},
    {"after": "1.1.0"}, {"after": "2.0.0"}, {"current": "b" * 40},
])
def test_initial_duplicate_skipped_minor_major_and_stale_builds_do_not_dispatch(tmp_path, monkeypatch, values):
    calls = run_handoff(tmp_path, monkeypatch, **values)
    assert not any(method == "POST" for method, _ in calls)


@pytest.mark.parametrize("values", [{"producer": 999}, {"source_private": False}])
def test_foreign_or_public_source_cannot_trigger_release(tmp_path, monkeypatch, values):
    with pytest.raises(RuntimeError):
        run_handoff(tmp_path, monkeypatch, **values)


def test_automatic_handoff_is_opt_in_and_cannot_recurse_from_manual_builds():
    text, _code = inline("auto-patch-release.yml")
    assert "vars.STAR_AUTO_PATCH_RELEASE == 'true'" in text
    assert "workflow_run.event == 'push'" in text
    assert "workflow_run.head_branch == 'main'" in text
    assert "workflow_run.conclusion == 'success'" in text
    assert "STAR_PUBLIC_RELEASE_APP_PRIVATE_KEY" not in text
    assert "contents: write" not in text
