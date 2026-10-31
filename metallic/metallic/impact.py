"""Test-impact selection from a static dependency graph of the tree.

Edges (file -> file it depends on), all found by reading source, never by running it:
* Python imports anywhere in a file (top level and lazy imports inside functions), absolute and relative, including
  the parent packages an import executes (`import a.b.c` runs a/__init__.py and a/b/__init__.py);
* string constants that name a module (`importlib.import_module("star.slop")`, `[python, "-m", "star.slop"]`);
* string constants that name a non-Python file (by path or basename: "roblox_api.json") or a directory
  ("docs", "evals/roblox": every non-Python file under it);
* every test file depends on the conftest.py files of its folder and the folders above.

A test is affected when a changed file is in its dependency closure. The same closure, hashed by content, is the
test file's cache key, so selection and caching agree: an unaffected test file has an unchanged key.
What static reading cannot see (a path built at run time from pieces, a file found by globbing a folder named
nowhere) is the documented gap: a changed non-Python file nobody names makes the selection fall back to the full
suite, and the merge queue always runs the full suite.
"""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import re

from . import cache as cache_mod
from .config import Config, matches

PARSE_VERSION = 3
_PATHISH = re.compile(r"^[\w./\\-]{3,200}$")
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


@dataclass
class Graph:
    files: dict[str, str]                       # path -> blob
    deps: dict[str, set[str]]
    rdeps: dict[str, set[str]]
    tests: list[str]
    modules: dict[str, set[str]] = field(default_factory=dict)
    _closure: dict[str, frozenset] = field(default_factory=dict)
    global_inputs: frozenset | None = None      # files matching full_on: part of every test key

    def closure(self, f: str) -> frozenset:
        got = self._closure.get(f)
        if got is None:
            seen, todo = {f}, deque([f])
            while todo:
                for d in self.deps.get(todo.popleft(), ()):
                    if d not in seen:
                        seen.add(d)
                        todo.append(d)
            got = self._closure[f] = frozenset(seen)
        return got

    def dependents(self, f: str) -> dict[str, int]:
        """Every file whose closure contains f, with its distance in import hops (f itself: 0)."""
        dist, todo = {f: 0}, deque([f])
        while todo:
            x = todo.popleft()
            for d in self.rdeps.get(x, ()):
                if d not in dist:
                    dist[d] = dist[x] + 1
                    todo.append(d)
        return dist


def _parse(text: str) -> dict:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {"imports": [], "strings": [], "error": True}
    imports, strings = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append([0, a.name, []])
        elif isinstance(node, ast.ImportFrom):
            imports.append([node.level or 0, node.module or "", [a.name for a in node.names]])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _PATHISH.match(node.value):
            strings.add(node.value)
    return {"imports": imports, "strings": sorted(strings)}


def _module_names(path: str, roots: list[str]) -> list[str]:
    if not path.endswith(".py"):
        return []
    names = []
    for r in roots:
        r = r.strip("/").strip(".")
        if r and not path.startswith(r + "/"):
            continue
        rel = path[len(r) + 1:] if r else path
        parts = rel[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(_IDENT.match(p) for p in parts):
            names.append(".".join(parts))
    return names


def build(root: Path, files: dict[str, str], cfg: Config, cache: cache_mod.Cache) -> Graph:
    py = [p for p in files if p.endswith(".py")]
    modules: dict[str, set[str]] = {}
    names_of: dict[str, list[str]] = {}
    for p in py:
        names_of[p] = _module_names(p, cfg.py_roots)
        for n in names_of[p]:
            modules.setdefault(n, set()).add(p)
    nonpy = [p for p in files if not p.endswith(".py")]
    by_base: dict[str, list[str]] = {}
    dirs: dict[str, list[str]] = {}
    for p in nonpy:
        base = p.rsplit("/", 1)[-1]
        if len(base) >= 5 and "." in base:
            by_base.setdefault(base, []).append(p)
        parts = p.split("/")
        for i in range(1, len(parts)):
            dirs.setdefault("/".join(parts[:i]), []).append(p)
    deps: dict[str, set[str]] = {p: set() for p in files}

    def add_module(src: str, name: str) -> bool:
        hit = False
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            for target in modules.get(".".join(parts[:i]), ()):
                if target != src:
                    deps[src].add(target)
                hit = True
        return hit

    for p in py:
        k = cache_mod.key("py-parse", PARSE_VERSION, files[p])
        info = cache.peek(k)
        if info is None:
            try:
                text = (root / p).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            info = _parse(text)
            cache.put(k, info)
        for level, mod, names in info["imports"]:
            if level:
                for own in names_of[p] or [p[:-3].replace("/", ".")]:
                    pkg = own.split(".") if p.endswith("__init__.py") else own.split(".")[:-1]
                    pkg = pkg[:len(pkg) - (level - 1)] if level > 1 else pkg
                    base = ".".join(pkg + ([mod] if mod else []))
                    if base:
                        add_module(p, base)
                    for n in names:
                        add_module(p, (base + "." if base else "") + n)
            else:
                add_module(p, mod)
                for n in names:
                    if mod + "." + n in modules:
                        add_module(p, mod + "." + n)
        for s in info["strings"]:
            if s in modules:
                add_module(p, s)
                continue
            norm = s.replace("\\", "/").strip("/")
            while norm.startswith("./"):
                norm = norm[2:]
            if norm in files and norm != p:
                deps[p].add(norm)
            elif norm in dirs:
                deps[p].update(dirs[norm])
            else:
                deps[p].update(by_base.get(norm.rsplit("/", 1)[-1], ()))
    tests = sorted(p for p in files if cfg.test_globs and matches(p, cfg.test_globs))
    conftests = [p for p in py if p.rsplit("/", 1)[-1] == "conftest.py"]
    for t in tests:
        tdir = t.rsplit("/", 1)[0] if "/" in t else ""
        for c in conftests:
            cdir = c.rsplit("/", 1)[0] if "/" in c else ""
            if cdir == "" or tdir == cdir or tdir.startswith(cdir + "/"):
                deps[t].add(c)
    rdeps: dict[str, set[str]] = {p: set() for p in files}
    for src, ds in deps.items():
        for d in ds:
            rdeps.setdefault(d, set()).add(src)
    return Graph(files=files, deps=deps, rdeps=rdeps, tests=tests, modules=modules)


@dataclass
class Selection:
    tests: list[str]
    direct: list[str]                 # changed test files
    full_reason: str = ""             # non-empty: the whole suite was selected, and why
    untested: list[str] = field(default_factory=list)    # changed source files no test depends on
    distance: dict[str, int] = field(default_factory=dict)   # test -> import hops to the nearest changed file;
    #                                   run order: a changed test (0) and its direct importers (1) give the first signal


def select(graph: Graph, changed: list[str], cfg: Config) -> Selection:
    tests = set(graph.tests)
    chosen: dict[str, int] = {}
    direct, untested = [], []

    def take(t: str, d: int):
        chosen[t] = min(d, chosen.get(t, d))

    for f in changed:
        if cfg.full_on and matches(f, cfg.full_on):
            return Selection(sorted(tests), [], full_reason=f"{f} matches full_on")
        if f not in graph.files:                      # deleted
            if f in tests or matches(f, cfg.no_tests):
                continue
            if f.endswith(".py"):
                return Selection(sorted(tests), [], full_reason=f"deleted module {f}")
            continue
        if f in tests:
            direct.append(f)
            take(f, 0)
            continue
        hit = {t: d for t, d in graph.dependents(f).items() if t in tests}
        for t, d in hit.items():
            take(t, d)
        if hit:
            continue
        if f.endswith(".py"):
            untested.append(f)
        elif not matches(f, cfg.no_tests):
            return Selection(sorted(tests), [], full_reason=f"{f}: no test names or imports it (unknown impact)")
    return Selection(sorted(chosen), sorted(direct), untested=sorted(untested), distance=chosen)


def test_key(graph: Graph, test: str, cfg: Config, toolchain: str, extra=()) -> str:
    """Cache key of one test file: command, toolchain, and the content of its whole dependency closure plus the
    files that affect every test (full_on)."""
    if graph.global_inputs is None:
        graph.global_inputs = frozenset(p for p in graph.files if cfg.full_on and matches(p, cfg.full_on))
    inputs = graph.closure(test) | graph.global_inputs
    return cache_mod.key("test", cfg.test_cmd, sorted(cfg.test_env), toolchain, list(extra),
                         sorted((p, graph.files[p]) for p in inputs if p in graph.files))
