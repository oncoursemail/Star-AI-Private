"""Project configuration: `metallic.toml` at the repository root (versioned with the code, so a gate that lands in a
branch is enforced on the combined tree the queue tests), plus per-user settings in ~/.metallic/ (never committed:
private names, brain URL, runner probes).

Without a metallic.toml the built-in checks still run with defaults; tests run only when `[tests]` says how.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import os
from pathlib import Path
import re
import tomllib

DEFAULT_IGNORE_TESTS = ["*.md", "LICENSE", ".gitignore", ".gitattributes"]


@dataclass
class Gate:
    name: str
    cmd: list[str]
    inputs: list[str]                 # globs; the gate runs only when one of these changed, and its cache key is
    requires: list[str] = field(default_factory=list)   # their content. Paths that must exist, else "skip".
    blocking: bool = True
    timeout: int = 900


@dataclass
class Config:
    name: str = ""
    target: str = "origin/main"
    python: str = "python"
    py_roots: list[str] = field(default_factory=lambda: ["."])
    test_globs: list[str] = field(default_factory=list)
    test_cmd: list[str] = field(default_factory=list)
    test_env: dict[str, str] = field(default_factory=dict)
    full_on: list[str] = field(default_factory=list)
    no_tests: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_TESTS))
    generator_branches: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    max_file_mb: float = 5.0
    luau_api_dump: str = ""
    eval_paths: list[str] = field(default_factory=list)
    eval_blocking: bool = False
    gates: list[Gate] = field(default_factory=list)
    queue_identity: tuple[str, str] = ("metallic-queue", "metallic-queue@localhost")
    path: Path | None = None


def load(root: Path) -> Config:
    cfg = Config(name=root.name)
    path = root / "metallic.toml"
    if not path.exists():
        return cfg
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg.path = path
    proj = data.get("project", {})
    cfg.name = proj.get("name", cfg.name)
    cfg.target = proj.get("target", cfg.target)
    py = data.get("python", {})
    cfg.python = py.get("interpreter", cfg.python)
    cfg.py_roots = py.get("roots", cfg.py_roots)
    t = data.get("tests", {})
    cfg.test_globs = t.get("files", [])
    cfg.test_cmd = t.get("cmd", [])
    cfg.test_env = t.get("env", {})
    cfg.full_on = t.get("full_on", [])
    cfg.no_tests = t.get("no_tests", cfg.no_tests)
    c = data.get("checks", {})
    cfg.generator_branches = c.get("generator_branches", [])
    cfg.protected_paths = c.get("protected_paths", [])
    cfg.forbidden_files = c.get("forbidden_files", [])
    cfg.max_file_mb = float(c.get("max_file_mb", cfg.max_file_mb))
    cfg.luau_api_dump = c.get("luau_api_dump", "")
    e = data.get("eval_gate", {})
    cfg.eval_paths = e.get("paths", [])
    cfg.eval_blocking = bool(e.get("blocking", False))
    for g in data.get("gate", []):
        cfg.gates.append(Gate(name=g["name"], cmd=list(g["cmd"]), inputs=list(g.get("inputs", ["**"])),
                              requires=list(g.get("requires", [])), blocking=bool(g.get("blocking", True)),
                              timeout=int(g.get("timeout", 900))))
    q = data.get("queue", {})
    if "identity" in q:
        cfg.queue_identity = (q["identity"][0], q["identity"][1])
    return cfg


def interpreter(cfg: Config) -> str:
    """METALLIC_PYTHON overrides the configured interpreter (each machine has its own venv path)."""
    return os.environ.get("METALLIC_PYTHON") or cfg.python


_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_re(pattern: str) -> re.Pattern:
    """Git-style glob: `**` crosses directories, `*` and `?` do not. A pattern without '/' matches the basename."""
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        pat = pattern if "/" in pattern else "**/" + pattern
        out, i = [], 0
        while i < len(pat):
            if pat.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
            elif pat.startswith("**", i):
                out.append(".*")
                i += 2
            elif pat[i] == "*":
                out.append("[^/]*")
                i += 1
            elif pat[i] == "?":
                out.append("[^/]")
                i += 1
            else:
                out.append(re.escape(pat[i]))
                i += 1
        rx = _GLOB_CACHE[pattern] = re.compile("".join(out) + r"\Z", re.IGNORECASE)
    return rx


def matches(path: str, patterns: list[str]) -> str | None:
    for p in patterns:
        if glob_re(p).match(path):
            return p
    return None


def user_dir() -> Path:
    return Path(os.environ.get("METALLIC_HOME") or Path.home() / ".metallic")


def private_names() -> list[str]:
    """Server user names and host names that must never enter a public diff: METALLIC_PRIVATE_NAMES (comma list) and
    ~/.metallic/private_names.txt (one per line). Read here, never printed."""
    names = [n.strip() for n in os.environ.get("METALLIC_PRIVATE_NAMES", "").split(",") if n.strip()]
    f = user_dir() / "private_names.txt"
    if f.exists():
        names += [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                  if ln.strip() and not ln.startswith("#")]
    return names


def fnmatch_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)
