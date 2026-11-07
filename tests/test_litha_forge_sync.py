from __future__ import annotations

import shutil
import subprocess

import pytest

import litha.forge_sync as S

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="no git")
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]


def _run(*args, cwd):
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _setup(tmp_path):
    hub, forge, clone = tmp_path / "hub", tmp_path / "forge.git", tmp_path / "clone"
    hub.mkdir()
    _run("init", "-q", cwd=hub)
    (hub / "a.txt").write_text("1\n", encoding="utf-8")
    _run("add", ".", cwd=hub)
    _run("commit", "-qm", "one", cwd=hub)
    _run("branch", "star/next", cwd=hub)
    _run("init", "-q", "--bare", str(forge), cwd=tmp_path)
    _run("clone", "-q", str(hub), str(clone), cwd=tmp_path)
    return hub, forge, clone


def test_the_forge_gets_both_release_branches_then_stays_up_to_date(tmp_path):
    hub, forge, clone = _setup(tmp_path)
    assert S.sync(clone, str(forge)) == [f"{forge} main: pushed", f"{forge} star/next: pushed"]
    assert _run("rev-parse", "main", cwd=forge) == _run("rev-parse", "main", cwd=hub)
    assert S.sync(clone, str(forge)) == [f"{forge} main: up to date", f"{forge} star/next: up to date"]
    (hub / "a.txt").write_text("2\n", encoding="utf-8")
    _run("commit", "-qam", "two", cwd=hub)
    assert S.sync(clone, str(forge))[0] == f"{forge} main: pushed"
    assert _run("rev-parse", "main", cwd=forge) == _run("rev-parse", "main", cwd=hub)


def test_a_branch_that_moved_differently_on_the_forge_is_never_overwritten(tmp_path):
    hub, forge, clone = _setup(tmp_path)
    S.sync(clone, str(forge))
    other = tmp_path / "other"
    _run("clone", "-q", str(forge), str(other), cwd=tmp_path)
    (other / "b.txt").write_text("forge only\n", encoding="utf-8")
    _run("add", ".", cwd=other)
    _run("commit", "-qm", "forge only", cwd=other)
    _run("push", "-q", "origin", "main", cwd=other)
    forge_head = _run("rev-parse", "main", cwd=forge)
    (hub / "a.txt").write_text("2\n", encoding="utf-8")
    _run("commit", "-qam", "two", cwd=hub)
    got = S.sync(clone, str(forge))
    assert got[0].startswith(f"{forge} main: REFUSED") and got[1] == f"{forge} star/next: up to date"
    assert _run("rev-parse", "main", cwd=forge) == forge_head
