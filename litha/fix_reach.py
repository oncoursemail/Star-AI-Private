"""What a failing test reaches, for fixes no diff points at (real fixes; docs/LITHA_AUTONOMY.md section 4j).

Planted one-token bugs sit on a traceback line or one call from the test; real fixes mostly do not: a new function,
a new branch, or a change two or more calls away (0/12 real-fix items solved with the packer alone).

1. `trace`: the first failing test run once more under a tracer (a pytest plugin written to a temp dir): every repo
   function it entered (tests/ excluded), its distance in calls from the test (1 = the test called it), the lines
   that ran and the line that raised. The packer ranks those functions by distance instead of guessing callees.
2. `missing`: the names the failure says do not exist (no attribute / cannot import / unexpected keyword /
   NameError). She has to ADD code there, so she is told what is missing, in which file, and what it has instead.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from litha.context_pack import module_file

ROOTS = ("star", "server", "metallic", "tools", "litha")
LIMIT = 400_000                 # traced events per run; past it no new frames are traced (a slow test stays bounded)

PLUGIN = r'''
import json, os, sys, threading
import pytest

_ROOT = os.path.normcase(os.path.realpath(os.environ["LITHA_REACH_ROOT"]))
_SRC = tuple(os.path.join(_ROOT, r, "") for r in os.environ["LITHA_REACH_SRC"].split(","))
_TESTS = os.path.join(_ROOT, "tests", "")
_LIMIT = int(os.environ.get("LITHA_REACH_LIMIT", "400000"))
_paths, _seen, _n = {}, {}, [0]


def _path(code):
    p = _paths.get(code.co_filename)
    if p is None:
        f = os.path.normcase(os.path.realpath(code.co_filename))
        p = ("" if not f.startswith(_SRC) or os.sep + "tests" + os.sep in f[len(_ROOT):] else
             os.path.relpath(f, _ROOT).replace(os.sep, "/"))
        _paths[code.co_filename] = p
    return p


def _depth(frame):
    """1 + the repo frames between this one and the nearest test frame."""
    n, f = 1, frame.f_back
    while f is not None:
        fn = os.path.normcase(os.path.realpath(f.f_code.co_filename))
        if fn.startswith(_TESTS):
            break
        if _path(f.f_code) and not f.f_code.co_name.startswith("<"):
            n += 1
        f = f.f_back
    return n


def _local(frame, event, arg):
    rec = _seen.get(frame.f_code)
    if rec is None:
        return None
    _n[0] += 1
    if event == "line" and len(rec["lines"]) < 600:
        rec["lines"].add(frame.f_lineno)
    elif event == "exception" and rec["raised"] is None and arg and arg[0] is not StopIteration:
        rec["raised"] = frame.f_lineno
    return _local if _n[0] < _LIMIT else None


def _global(frame, event, arg):
    if event != "call" or _n[0] >= _LIMIT:
        return None
    code = frame.f_code
    rel = _path(code) if not code.co_name.startswith("<") else ""     # no genexpr / lambda / module body
    if not rel:
        return None
    _n[0] += 1
    rec = _seen.get(code)
    if rec is None:
        rec = _seen[code] = {"path": rel, "name": code.co_name, "qual": getattr(code, "co_qualname", code.co_name),
                             "start": code.co_firstlineno, "depth": _depth(frame), "order": len(_seen),
                             "calls": 0, "lines": set(), "raised": None}
    rec["calls"] += 1
    return _local


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    sys.settrace(_global)
    threading.settrace(_global)
    try:
        yield
    finally:
        sys.settrace(None)
        threading.settrace(None)


def pytest_sessionfinish(session):
    rows = [{**r, "lines": sorted(r["lines"])} for r in _seen.values()]
    with open(os.environ["LITHA_REACH_OUT"], "w", encoding="utf-8") as fh:
        json.dump({"events": _n[0], "functions": rows}, fh)
'''


def trace(tree: Path, test: str, python: str, timeout: float = 120) -> list[dict]:
    """[{path, name, qual, start, depth, order, calls, lines, raised}] of the repo functions `test` (a pytest id)
    entered, nearest first; [] when it cannot be traced (no id, timeout, no output)."""
    if "::" not in test:
        return []
    tmp = Path(tempfile.mkdtemp(prefix="litha-reach-"))
    (tmp / "litha_reach_plugin.py").write_text(PLUGIN, encoding="utf-8")
    out = tmp / "reach.json"
    env = dict(os.environ, APPDATA=str(tmp), PYTHONPATH=os.pathsep.join([str(tree), str(tmp)]),
               LITHA_REACH_ROOT=str(tree), LITHA_REACH_SRC=",".join(ROOTS), LITHA_REACH_OUT=str(out),
               LITHA_REACH_LIMIT=str(LIMIT))
    try:
        subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "litha_reach_plugin", "-x",
                        test], cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=env)
        rows = json.loads(out.read_text(encoding="utf-8"))["functions"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return []
    return sorted((r for r in rows if isinstance(r, dict)), key=lambda r: (r["depth"], r["order"]))


# ---------------------------------------------------------------- how wide her window is

WIDE = 8192                     # star-pc's litha-fast context (owner-pc: 4096); real fixes 3/12 twice vs 2/12 at 4096
_WINDOW: dict[str, tuple[float, int]] = {}


def window(default: int, ttl: float = 300) -> int:
    """The fixer's window: LITHA_FIX_WINDOW if set; else WIDE when the node her calls go to first (the fastest usable
    one, as llm.node_chat picks) has that context, else `default`. Never probed under pytest (no network in tests)."""
    if os.environ.get("LITHA_FIX_WINDOW"):
        return int(os.environ["LITHA_FIX_WINDOW"])
    if "PYTEST_CURRENT_TEST" in os.environ:
        return default
    hit = _WINDOW.get("now")
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    got = default
    try:
        from star.asset3d import llm
        st = llm._get(llm._router() + "/mesh/status", {"Authorization": "Bearer " + llm._key()}, timeout=5)
        for n in sorted((n for n in st.get("nodes", []) if n.get("usable") and n.get("status_url")),
                        key=lambda n: -float(n.get("tok_s") or 0)):
            try:
                models = llm._get(n["status_url"], timeout=5).get("models", [])
            except OSError:
                continue
            ctx = max((int(m.get("ctx") or 0) for m in models if m.get("loaded")), default=0)
            got = WIDE if ctx >= WIDE else default
            break
    except Exception:  # noqa: BLE001 - no router, no key, odd status: the narrow window is always safe
        got = default
    _WINDOW["now"] = (time.time(), got)
    return got


# ---------------------------------------------------------------- names the failure says are missing

MISSING = [
    (re.compile(r"<module '([\w.]+)'[^>]*> has no attribute '(\w+)'"), "module"),
    (re.compile(r"\bmodule '([\w.]+)' has no attribute '(\w+)'"), "module"),
    (re.compile(r"cannot import name '(\w+)' from '([\w.]+)'"), "import"),
    (re.compile(r"'(\w+)' object has no attribute '(\w+)'"), "object"),
    (re.compile(r"\b([\w.]+)\(\) got an unexpected keyword argument '(\w+)'"), "keyword"),
    (re.compile(r"\bNameError: name '(\w+)' is not defined"), "name"),
]


def missing(text: str) -> list[dict]:
    """[{kind, module, name, owner}] the failure says do not exist, first seen first (at most 4)."""
    out: list[dict] = []
    for ln in text.splitlines():
        for pat, kind in MISSING:
            for m in pat.finditer(ln):
                if kind == "module":
                    row = {"kind": kind, "module": m.group(1), "name": m.group(2), "owner": ""}
                elif kind == "import":
                    row = {"kind": kind, "module": m.group(2), "name": m.group(1), "owner": ""}
                elif kind in ("object", "keyword"):
                    row = {"kind": kind, "module": "", "name": m.group(2), "owner": m.group(1)}
                else:
                    row = {"kind": kind, "module": "", "name": m.group(1), "owner": ""}
                if row not in out:
                    out.append(row)
    return out[:4]


TOP = re.compile(r"^(?:async\s+)?(?:def|class)\s+(\w+)|^([A-Za-z_]\w*)\s*(?::[^=\n]*)?=(?!=)", re.M)


def _top_names(text: str) -> list[str]:
    """The module's top-level functions, classes and assigned names."""
    return list(dict.fromkeys(a or b for a, b in TOP.findall(text)))


def missing_note(tree: Path, text: str, tests: list[tuple[str, str]] | None = None) -> tuple[str, list[str]]:
    """(note for the prompt, source files it names) for what the failure says is missing; ('', []) when nothing."""
    rows, paths = [], []
    test_src = ""
    for path, _ in tests or []:
        try:
            test_src += (tree / path).read_text(encoding="utf-8", errors="replace") + "\n"
        except OSError:
            pass
    for r in missing(text):
        name = r["name"]
        uses = [ln.strip() for ln in test_src.splitlines() if re.search(rf"\b{re.escape(name)}\b", ln)][:3]
        use = f" The test uses it: {' | '.join(u[:110] for u in uses)}." if uses else ""
        path = module_file(tree, r["module"]) if r["module"] else None
        if r["kind"] == "keyword":
            rows.append(f"- `{r['owner']}()` takes no keyword `{name}`, but the test passes it: add that parameter "
                        f"(and use it).{use}")
            continue
        if path is None:
            rows.append(f"- `{name}` does not exist yet ({r['kind']}{': ' + r['owner'] if r['owner'] else ''}); "
                        f"the test needs it: add it.{use}")
            continue
        src = (tree / path).read_text(encoding="utf-8", errors="replace")
        names = _top_names(src)
        like = difflib.get_close_matches(name, names, n=3, cutoff=0.5)
        rows.append(f"- {path} has no `{name}`, but the test needs `{r['module']}.{name}`: ADD it to {path} (a new "
                    f"function or constant; or rename the old one it replaces and update its callers)."
                    + (f" Names there like it: {', '.join(like)}." if like else "") + use)
        paths += [path] if path not in paths else []
    if not rows:
        return "", []
    return "What the failure says is missing (new code is needed, not a one-token change):\n" + "\n".join(rows) + \
        "\n", paths
