"""Regression checks for reviewed, no-execution Agent Skill imports."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from star.agent_skills import SkillLibrary
from star.skill_import import import_reviewed_skill, preview_skill, verify_skill


COMMIT = "ab" * 20
REPO = "https://github.com/example/reviewed-skills"
SKILL = """---
name: useful-review
description: Use when reviewing changes and checking verifiable evidence.
license: MIT
---
# Review
Check the actual evidence, run tests, and report unverified conditions.
"""


def source(tmp_path: Path) -> Path:
    root = tmp_path / "downloads" / "useful-review"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "method.md").write_text("# Method\nCompare before and after.", encoding="utf-8")
    return root


def kwargs() -> dict:
    return {"source_url": REPO, "commit": COMMIT, "license_id": "MIT"}


def test_preview_is_nonmutating_and_tracks_provenance(tmp_path):
    folder = source(tmp_path)
    result = preview_skill(folder, **kwargs())
    assert result["name"] == "useful-review"
    assert len(result["snapshot_sha256"]) == 64
    assert "references/method.md" in result["files"]
    assert result["tools_granted"] == []
    assert not (tmp_path / "skills").exists()


def test_approval_required(tmp_path):
    with pytest.raises(PermissionError, match="approval"):
        import_reviewed_skill(source(tmp_path), home=tmp_path / "profile", **kwargs())
    assert not (tmp_path / "profile").exists()


def test_import_is_visible_to_existing_library_and_integrity_check(tmp_path):
    folder = source(tmp_path)
    home = tmp_path / "profile"
    out = import_reviewed_skill(folder, home=home, approved=True, **kwargs())
    assert out["status"] == "imported-not-executed"
    library = SkillLibrary(workspace=None, home=home)
    assert "useful-review" in [x["name"] for x in library.list()["skills"]]
    assert "actual evidence" in library.load("useful-review")["instructions"]
    assert library.read_reference("useful-review", "references/method.md")["content"].startswith("# Method")
    assert verify_skill(home, "useful-review")["ok"] is True
    (home / "skills" / "useful-review" / "SKILL.md").write_text(SKILL + "\nChanged\n")
    assert verify_skill(home, "useful-review") == {
        "name": "useful-review", "ok": False, "reason": "content-drift"
    }


def test_no_overwriting_existing_skill(tmp_path):
    folder = source(tmp_path)
    home = tmp_path / "profile"
    import_reviewed_skill(folder, home=home, approved=True, **kwargs())
    with pytest.raises(FileExistsError):
        import_reviewed_skill(folder, home=home, approved=True, **kwargs())


def test_cannot_shadow_bundled_skills(tmp_path):
    folder = source(tmp_path)
    bundled_name = folder.parent / "roblox-vfx"
    folder.rename(bundled_name)
    (bundled_name / "SKILL.md").write_text(SKILL.replace("useful-review", "roblox-vfx"))
    with pytest.raises(FileExistsError, match="bundled"):
        import_reviewed_skill(bundled_name, home=tmp_path / "profile", approved=True, **kwargs())


@pytest.mark.parametrize("relative", ["scripts/run.py", "assets/evil.exe", "README.md"])
def test_reject_unreviewed_content(tmp_path, relative):
    folder = source(tmp_path)
    target = folder / relative
    target.parent.mkdir(exist_ok=True)
    target.write_text("print('bad')", encoding="utf-8")
    with pytest.raises(ValueError, match="Only SKILL|Unsupported"):
        preview_skill(folder, **kwargs())


def test_reject_symlink_escape(tmp_path):
    folder = source(tmp_path)
    (folder / "references" / "leak.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(ValueError, match="Symlinks"):
        preview_skill(folder, **kwargs())


def test_reject_disputed_license(tmp_path):
    folder = source(tmp_path)
    with pytest.raises(PermissionError, match="disagrees"):
        preview_skill(folder, **{**kwargs(), "license_id": "Apache-2.0"})


def test_reject_unpinned_revision(tmp_path):
    with pytest.raises(ValueError, match="Git commit SHA"):
        preview_skill(source(tmp_path), **{**kwargs(), "commit": "main"})


def test_reject_source_digest_changes(tmp_path):
    folder = source(tmp_path)
    original = preview_skill(folder, **kwargs())
    (folder / "references" / "method.md").write_text("# Updated")
    latest = preview_skill(folder, **kwargs())
    assert original["snapshot_sha256"] != latest["snapshot_sha256"]


def test_reject_hidden_file_in_source(tmp_path):
    folder = source(tmp_path)
    (folder / ".private").write_text("never import")
    with pytest.raises(ValueError, match="Hidden"):
        preview_skill(folder, **kwargs())


def test_reject_unknown_license(tmp_path):
    with pytest.raises(PermissionError, match="permissive"):
        preview_skill(source(tmp_path), **{**kwargs(), "license_id": "Unknown"})
