"""The merge queue tests the combined tree: the failures this team hit for real (docs/agents/integrator.md round 6
step 4: two PRs green alone, red together; the pyright/ruff gates landing mid-round) are rejected before landing."""
from __future__ import annotations

from metallic_fixtures import commit, git, write
import pytest

from metallic import cache as cache_mod
from metallic import engine, queue
from metallic.config import load


def _branch(root, name, files, base="main"):
    git(root, "checkout", "-q", "-b", name, base)
    for rel, text in files.items():
        write(root, rel, text)
    sha = commit(root, name)
    git(root, "checkout", "-q", "main")
    return sha


def _green_alone(root, branch):
    git(root, "checkout", "-q", branch)
    try:
        return engine.run_check(root, load(root), base="main", full=True, jobs=2,
                                cache=cache_mod.Cache(engine.default_cache_dir()))["verdict"] == "green"
    finally:
        git(root, "checkout", "-q", "main")


def _run(root, branches, **kw):
    return queue.run(root, "main", branches, jobs=2, cache=cache_mod.Cache(engine.default_cache_dir()), **kw)


@pytest.fixture
def rename_pair(repo):
    # A renames add -> plus and updates its own test; B adds a new caller of add. Each is green alone.
    _branch(repo, "a-rename", {"pkg/core.py": "def plus(a, b):\n    return a + b\n",
                               "tests/test_core.py": "from pkg.core import plus\n\n\ndef test_plus():\n"
                                                     "    assert plus(1, 2) == 3\n"})
    _branch(repo, "b-caller", {"pkg/total.py": "from pkg.core import add\n\n\ndef total(xs):\n"
                                               "    out = 0\n    for x in xs:\n        out = add(out, x)\n"
                                               "    return out\n",
                               "tests/test_total.py": "from pkg.total import total\n\n\ndef test_total():\n"
                                                      "    assert total([1, 2, 3]) == 6\n"})
    return repo


def test_green_alone_broken_together_is_rejected(rename_pair):
    repo = rename_pair
    assert _green_alone(repo, "a-rename") and _green_alone(repo, "b-caller")
    before = git(repo, "rev-parse", "main").strip()
    rep = _run(repo, ["a-rename", "b-caller"], apply=True)
    assert rep["batch"]["verdict"] == "red"
    assert [(e["branch"], e["status"]) for e in rep["entries"]] == [("a-rename", "merged"), ("b-caller", "rejected")]
    assert "tests" in rep["entries"][1]["reason"]
    assert rep["entries"][1]["check"]["failed"] == ["tests/test_total.py"]
    after = git(repo, "rev-parse", "main").strip()
    assert rep["applied"] and after == rep["result"] != before
    assert git(repo, "merge-base", "--is-ancestor", before, after) == ""            # fast-forward only
    assert "def plus" in git(repo, "show", "main:pkg/core.py")
    assert git(repo, "worktree", "list").count("\n") == 1                            # scratch worktree removed


def test_batch_green_lands_everything_in_one_run(repo):
    _branch(repo, "c1", {"pkg/c1.py": "X = 1\n", "tests/test_c1.py": "from pkg.c1 import X\n\n\n"
                                                                    "def test_x():\n    assert X == 1\n"})
    _branch(repo, "c2", {"pkg/other.py": "def name():\n    return 'x'\n\n\ndef other():\n    return 2\n"})
    rep = _run(repo, ["c1", "c2"])
    assert rep["batch"]["verdict"] == "green" and rep["merged"] == ["c1", "c2"]
    assert not rep["applied"] and git(repo, "rev-parse", "main").strip() == rep["target_before"]   # dry run


def test_conflict_drops_the_branch_and_the_queue_moves_on(repo):
    _branch(repo, "d1", {"pkg/other.py": "def name():\n    return 'd1'\n",
                         "tests/test_other.py": "from pkg import other\n\n\ndef test_name():\n"
                                                "    assert other.name() == 'd1'\n"})
    _branch(repo, "d2", {"pkg/other.py": "def name():\n    return 'd2'\n"})
    _branch(repo, "d3", {"pkg/d3.py": "Y = 3\n"})
    rep = _run(repo, ["d1", "d2", "d3"], batch=False)
    st = {e["branch"]: e["status"] for e in rep["entries"]}
    assert st == {"d1": "merged", "d2": "conflict", "d3": "merged"}
    assert "pkg/other.py" in next(e for e in rep["entries"] if e["branch"] == "d2")["reason"]


def test_gate_added_by_one_branch_is_enforced_on_the_next(repo):
    # The ruff/pyright lesson: a new gate lands mid-round; a branch tested before it would be merged unchecked.
    cfg = (repo / "metallic.toml").read_text()
    _branch(repo, "gate", {"metallic.toml": cfg + '\n[[gate]]\nname = "no-print"\ncmd = ["{python}", "-c", '
                                                  '"import sys,pathlib; sys.exit(any(\'print(\' in p.read_text() '
                                                  'for p in pathlib.Path(\'pkg\').glob(\'*.py\')))"]\n'
                                                  'inputs = ["pkg/**"]\n'})
    _branch(repo, "noisy", {"pkg/other.py": "def name():\n    print('debug')\n    return 'x'\n"})
    assert _green_alone(repo, "noisy")
    rep = _run(repo, ["gate", "noisy"])
    st = {e["branch"]: (e["status"], e["reason"]) for e in rep["entries"]}
    assert st["gate"][0] == "merged"
    assert st["noisy"] == ("rejected", "red on the combined tree: no-print")


def test_red_builtin_check_rejects_without_running_the_suite(repo):
    _branch(repo, "leak", {"deploy/.env": "A=1\n"})
    rep = _run(repo, ["leak"])
    entry = rep["entries"][0]
    assert entry["status"] == "rejected" and entry["reason"] == "red on the combined tree: files"
    tests = next(c for c in entry["check"]["checks"] if c["name"] == "tests")
    assert tests["status"] == "skip" and "files already failed" in tests["summary"]


def test_queue_lock_refuses_a_second_integrator(repo):
    from metallic import gitutil
    lock = gitutil.state_dir(repo) / "queue.lock"
    lock.write_text("other session")
    _branch(repo, "e1", {"pkg/e1.py": "Z = 1\n"})
    with pytest.raises(queue.QueueBusy):
        _run(repo, ["e1"])
    assert lock.read_text() == "other session"


def test_apply_refuses_when_target_moved(repo, monkeypatch):
    _branch(repo, "f1", {"pkg/f1.py": "W = 1\n"})
    real = queue._check

    def check_then_move(*a, **kw):
        rep = real(*a, **kw)
        write(repo, "pkg/moved.py", "M = 1\n")
        commit(repo, "someone else landed")                       # target moves while the queue tests
        return rep

    monkeypatch.setattr(queue, "_check", check_then_move)
    rep = _run(repo, ["f1"], apply=True)
    assert not rep["applied"] and "moved" in rep["apply_error"]
