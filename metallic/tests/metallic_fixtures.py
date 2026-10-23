"""Fixtures: a throw-away git repo with a tiny Python project, an isolated cache and Metallic home."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the metallic package (standalone, no install)

CONFIG = """\
[project]
name = "demo"
target = "main"

[tests]
files = ["tests/test_*.py"]
cmd = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
full_on = ["metallic.toml"]

[checks]
generator_branches = ["star/chatgpt-*"]
protected_paths = ["evals/**"]

[eval_gate]
paths = ["pkg/prompts.py"]
blocking = true
"""

FILES = {
    "metallic.toml": CONFIG,
    ".gitignore": "__pycache__/\n",         # the tested files write .pyc: not a change
    "README.md": "demo\n",
    "pkg/__init__.py": "",
    "pkg/core.py": "def add(a, b):\n    return a + b\n",
    "pkg/other.py": "def name():\n    return 'x'\n",
    "pkg/loader.py": "from pathlib import Path\n\n\ndef load():\n    return (Path(__file__).parent / 'data.json')"
                     ".read_text()\n",
    "pkg/data.json": "{\"a\": 1}\n",
    "pkg/prompts.py": "SYSTEM = 'be brief'\n",
    "tests/test_core.py": "from pkg.core import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "tests/test_other.py": "from pkg import other\n\n\ndef test_name():\n    assert other.name() == 'x'\n",
    "tests/test_loader.py": "from pkg.loader import load\n\n\ndef test_load():\n    assert '\"a\"' in load()\n",
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text) if text.startswith("\n") else text, encoding="utf-8")


def commit(root: Path, msg: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)
    return git(root, "rev-parse", "HEAD").strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@example.invalid", "METALLIC_PYTHON": sys.executable,
                 "METALLIC_CACHE": str(tmp_path / "cache"), "METALLIC_HOME": str(tmp_path / "home"),
                 "METALLIC_PRIVATE_NAMES": ""}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("METALLIC_BRAIN_URL", raising=False)
    monkeypatch.delenv("STAR_BRAIN_URL", raising=False)
    return tmp_path


@pytest.fixture
def repo(env) -> Path:
    root = env / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for rel, text in FILES.items():
        write(root, rel, text)
    commit(root, "init")
    return root
