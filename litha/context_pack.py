"""What Litha sees when she fixes Python, and how her edits land (docs/LITHA_AUTONOMY.md section 4i).

Her model answers in about a second, but its window is 4096 tokens for prompt + answer. The fixer's old prompt put up
to 6000 characters of test output, 5000 of diff and 9000 of code in it: more than the window, so the node answered
HTTP 400 and the round was lost as "not valid JSON", or the code she needed was cut off.

1. Context packer (`fixer_prompt`, `pack`): from the failing tracebacks, the test ids and the PR diff, Python's `ast`
   picks the code that matters: the changed hunks, the traceback frames, the failing test functions, the functions
   they call, and one hop of callees and callers. Each piece is ranked and packed into a token budget that leaves
   room for her answer. Every line carries its real line number in the file, so a `find` she copies is in the file.
2. Edit landing (`land`, `reask_prompt`): a `find` that is not in the file exactly is tried whitespace-tolerant, then
   by a unique fuzzy match of whole lines (two similar places: refused). Still nothing: one re-ask showing her the
   nearest real lines. Every rejected edit is noted with why (`note_reject`, `REJECTS`, `REJECT_LOG`).
3. Repo map (`repo_map`): module -> public symbols with one-line docstrings, cached per git tree hash, so she sees
   where the names around the failure live, and the packer can find a called function without reading every file.
"""
from __future__ import annotations

import ast
import keyword
from collections import deque
from dataclasses import dataclass, field
import difflib
import json
from pathlib import Path
import re
import subprocess
import textwrap
import threading
import time

WINDOW = 4096                   # litha-fast's context: prompt + answer
ANSWER = 700                    # tokens kept free for her JSON answer (a few edits; answers seen are 60-400 tokens)
ROOTS = ("star", "server", "metallic", "tools", "litha")      # source; tests/ is the spec, shown but never edited
MAP_DIR = Path.home() / ".star" / "pr-fixer" / "repomap"
REJECT_LOG: Path | None = None  # set by the live fixer / the bench; tests leave it off (no writes into ~)
REJECTS: deque = deque(maxlen=500)
_LOCK = threading.Lock()

FIX_PROMPT = """You are Litha, fixing a failing pull request in STAR's Python repository so its tests pass.
PR title: {title}
Failing tests and their output:
{failures}

What this PR changed (the cause is most likely in these lines):
{diff}

{missing}The code that matters, picked from the tracebacks, the tests and the change. Each line starts with its line number
in the file and ": "; the number is not part of the file:
{code}
{repo_map}{lessons}{feedback}
Fix the cause in the source code. The tests describe the wanted behaviour: never edit files under tests/.
Edit only files shown above, with exactly those paths. Make the smallest correct change. Answer only JSON:
{{"why": "<one sentence: the cause>", "edits": [{{"file": "<path>", "line": <number of the first line of find>,
"find": "<exact existing lines copied without their numbers, unique in the file>", "replace": "<new text>"}}]}}{insert}"""

INSERT = """
To ADD code (a new function, constant or branch) an edit may instead be {"file": "<path>", "after": "<one existing
line, copied>", "insert": "<the new lines>"}; after a "def" or "class" line it goes below that whole definition."""

REASK = """You are Litha. Your fix was: {why}
These edits did not apply because their "find" text is not in the file:
{missed}
The nearest real lines (each starts with its line number and ": "; the number is not part of the file):
{near}
Send those edits again with "find" copied exactly from these lines (whole lines, without the numbers) and the same
intended change in "replace". If none of these lines is what you meant, answer {{"edits": []}}. Answer only JSON:
{{"edits": [{{"file": "<path>", "line": <number of the first line of find>, "find": "<exact lines>",
"replace": "<new text>"}}]}}"""


def tokens(text: str) -> int:
    """Same estimate as star.asset3d.llm.estimate_tokens (gemma: a digit ~1 token, other text ~3.2 chars/token)."""
    digits = sum(c.isdigit() for c in text)
    return int(digits * 0.95 + (len(text) - digits) / 3.2) + 8


def clip(text: str, budget: int, keep: str = "head") -> str:
    """text cut to about `budget` tokens at line ends: keep 'head', 'tail' or 'both' (1/3 head, 2/3 tail)."""
    if tokens(text) <= budget:
        return text
    lines = text.split("\n")
    if keep == "both":
        head = clip(text, budget // 3, "head")
        tail = clip(text, budget - budget // 3 - 4, "tail")
        return head + "\n[...]\n" + tail
    out, used = [], 8
    for ln in (lines if keep == "head" else reversed(lines)):
        t = tokens(ln) - 7
        if used + t > budget:
            if not out:                                   # one huge line: cut it by characters
                n = max(0, int((budget - used) * 3))
                out.append(ln[:n] if keep == "head" else ln[-n:] if n else "")
            break
        out.append(ln)
        used += t
    return "\n".join(out if keep == "head" else reversed(out))


# ---------------------------------------------------------------- what the failure points at

PATH = re.compile(r"(?<![\w.-])((?:star|server|metallic|tools|litha|tests)[/\\][\w/\\.-]*?\.py)(?::(\d+)|\", line (\d+))")
TEST_ID = re.compile(r"(?<![\w.-])((?:[\w.-]+/)*tests/[\w/.-]*\.py)::([\w:.\[\]-]+)")


def frames(text: str, tree: Path) -> list[tuple[str, int]]:
    """(path, line) of every traceback frame inside the repository, in the order printed (deepest last)."""
    out = []
    for m in PATH.finditer(text):
        path = m.group(1).replace("\\", "/")
        no = int(m.group(2) or m.group(3))
        if (tree / path).is_file() and (path, no) not in out:
            out.append((path, no))
    return out


def test_ids(fails: list[dict], text: str = "") -> list[tuple[str, str]]:
    """(test file, function name) of the failing tests ('Class::test_x[param]' -> 'test_x')."""
    out = []
    for raw in [str(f.get("test", "")) for f in fails] + [f"{a}::{b}" for a, b in TEST_ID.findall(text)]:
        if "::" not in raw:
            continue
        path, _, rest = raw.partition("::")
        name = re.sub(r"\[.*$", "", rest.split("::")[-1])
        if (path, name) not in out:
            out.append((path, name))
    return out


def changed_lines(diff: str) -> dict[str, set[int]]:
    """{path: line numbers in the NEW file} that the diff adds or changes (a pure deletion marks where it was)."""
    out: dict[str, set[int]] = {}
    cur, no = None, 0
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = None if p == "/dev/null" else p[2:] if p.startswith("b/") else p
        elif ln.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", ln)
            no = int(m.group(1)) if m else 0
        elif cur and no and not ln.startswith(("--- ", "diff --git", "index ")):
            if ln.startswith("+"):
                out.setdefault(cur, set()).add(no)
                no += 1
            elif ln.startswith("-"):
                out.setdefault(cur, set()).add(no)
            elif ln.startswith(" ") or ln == "":
                no += 1
    return out


# ---------------------------------------------------------------- the code, as ast sees it

@dataclass
class Def:
    path: str
    name: str
    qual: str
    start: int                                  # first line, decorators included
    end: int
    calls: set[str] = field(default_factory=set)            # f(...) and x.f(...) -> "f"
    attrs: set[tuple[str, str]] = field(default_factory=set)  # m.f(...) -> ("m", "f")
    call_lines: dict[str, list[int]] = field(default_factory=dict)   # "f" -> the lines that call it


@dataclass
class Module:
    path: str
    lines: list[str]
    defs: list[Def]
    imports: dict[str, tuple[str, str]]         # local name -> (dotted module, attribute or "")
    doc: str = ""

    def enclosing(self, line: int) -> Def | None:
        best = None
        for d in self.defs:
            if d.start <= line <= d.end and (best is None or d.end - d.start < best.end - best.start):
                best = d
        return best

    def named(self, name: str) -> list[Def]:
        return [d for d in self.defs if d.name == name]


def _calls(node: ast.AST) -> tuple[set[str], set[tuple[str, str]], dict[str, list[int]]]:
    names, attrs, where = set(), set(), {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if not name:
                continue
            names.add(name)
            where.setdefault(name, []).append(sub.lineno)
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                attrs.add((fn.value.id, fn.attr))
    return names, attrs, where


def _package(path: str) -> list[str]:
    parts = path[:-3].split("/")
    return parts[:-1]                           # star/voice/voicedsp.py -> [star, voice]


def parse(tree: Path, path: str, cache: dict[str, Module | None]) -> Module | None:
    if path in cache:
        return cache[path]
    mod = None
    f = tree / path
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
        node = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        cache[path] = None
        return None
    defs: list[Def] = []

    def add(n: ast.AST, prefix: str) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([d.lineno for d in n.decorator_list] + [n.lineno])
            names, attrs, where = _calls(n) if not isinstance(n, ast.ClassDef) else (set(), set(), {})
            defs.append(Def(path, n.name, prefix + n.name, start, n.end_lineno or n.lineno, names, attrs, where))
            if isinstance(n, ast.ClassDef):
                for sub in n.body:
                    add(sub, prefix + n.name + ".")

    imports: dict[str, tuple[str, str]] = {}
    for n in node.body:
        add(n, "")
    for n in ast.walk(node):
        if isinstance(n, ast.Import):
            for a in n.names:
                imports[a.asname or a.name.split(".")[0]] = (a.name if a.asname else a.name.split(".")[0], "")
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = _package(path)[:len(_package(path)) - (n.level - 1)]
                base = ".".join([*pkg, *([base] if base else [])])
            for a in n.names:
                imports[a.asname or a.name] = (base, a.name)
    mod = Module(path, text.split("\n"), defs, imports, (ast.get_docstring(node) or "").strip().split("\n")[0])
    cache[path] = mod
    return mod


def module_file(tree: Path, dotted: str) -> str | None:
    """The file of a dotted module; `mesh.x` is server/mesh/x.py (the server tests put server/ on sys.path)."""
    base = dotted.replace(".", "/")
    for cand in (base + ".py", base + "/__init__.py", "server/" + base + ".py", "server/" + base + "/__init__.py"):
        if (tree / cand).is_file():
            return cand
    return None


@dataclass
class Unit:
    path: str
    start: int
    end: int
    score: int
    why: set[str] = field(default_factory=set)
    focus: set[int] = field(default_factory=set)


class Picker:
    """Collects ranked units (pieces of code) for one failure."""

    def __init__(self, tree: Path, symbols: dict[str, list[str]] | None = None):
        self.tree, self.mods, self.units = tree, {}, []
        self.symbols = symbols or {}

    def mod(self, path: str) -> Module | None:
        return parse(self.tree, path, self.mods)

    def add(self, path: str, start: int, end: int, score: int, why: str, focus: set[int] | None = None) -> None:
        self.units.append(Unit(path, start, end, score, {why}, set(focus or ())))

    def add_def(self, d: Def, score: int, why: str, focus: set[int] | None = None) -> None:
        m = self.mod(d.path)
        if m is not None and any(x.qual.startswith(d.qual + ".") for x in m.defs) and not focus:
            init = [x for x in m.defs if x.qual == d.qual + ".__init__"]   # a class called: its __init__
            if init:
                self.add(d.path, d.start, d.start, score, why)
                d = init[0]
            else:
                self.add(d.path, d.start, min(d.end, d.start + 6), score, why)
                return
        self.add(d.path, d.start, d.end, score, why, focus)

    def around(self, path: str, line: int, score: int, why: str) -> Def | None:
        """The function holding `line`, or a few lines around it at module level."""
        m = self.mod(path)
        if m is None:
            return None
        d = m.enclosing(line)
        if d is not None:
            self.add_def(d, score, why, {line})
        else:
            self.add(path, max(1, line - 4), min(len(m.lines), line + 4), score, why, {line})
        return d

    def resolve(self, m: Module, name: str, base: str = "", loose: bool = True) -> list[Def]:
        """Where a name called in module m is defined: m itself, its imports, then (loose) the repo map, when exactly
        one module defines that name."""
        if base:                                        # module.f(...): `import star.x as module` / `from star import x`
            if base not in m.imports:
                return []
            dotted, attr = m.imports[base]
            target = module_file(self.tree, f"{dotted}.{attr}" if attr else dotted)
            other = self.mod(target) if target else None
            return [d for d in other.named(name) if "." not in d.qual] if other else []
        own = [d for d in m.named(name) if "." not in d.qual]
        if own:
            return own
        if name in m.imports:
            dotted, attr = m.imports[name]
            target = module_file(self.tree, dotted)
            other = self.mod(target) if target and attr else None
            if other is not None:
                return [d for d in other.named(attr) if "." not in d.qual]
        where = self.symbols.get(name, []) if loose else []
        if len(where) == 1:
            other = self.mod(where[0])
            return [d for d in other.named(name) if "." not in d.qual] if other else []
        return []

    def callees(self, d: Def, score: int, why: str, limit: int = 6) -> list[Def]:
        m = self.mod(d.path)
        out: list[Def] = []
        if m is None:
            return out
        seen = set()
        for base, attr in sorted(d.attrs):
            for c in self.resolve(m, attr, base):
                if c.qual not in seen:
                    seen.add(c.qual)
                    out.append(c)
        for name in sorted(d.calls):
            if name == d.name or name in seen:
                continue
            found = self.resolve(m, name)
            if not found:                               # a method: one in the same class or module with that name
                found = [x for x in m.named(name) if x is not d][:1]
            for c in found:
                if c.qual not in seen and c is not d:
                    seen.add(c.qual)
                    out.append(c)
        for c in out[:limit] if why else []:            # why "": only look, add nothing
            self.add_def(c, score, why)
        return out[:limit]

    def callers(self, d: Def, score: int, why: str, limit: int = 3) -> None:
        m = self.mod(d.path)
        if m is None:
            return
        found = [x for x in m.defs if d.name in x.calls and x is not d and not (x.start <= d.start <= x.end)]
        for c in found[:limit]:
            self.add_def(c, score, why)


REACHED = 12                    # traced functions considered (fix_reach.trace), nearest to the test first


def constants_read(p: Picker, path: str, name: str, limit: int = 4) -> list[tuple[str, int, int, str]]:
    """(file, first, last line, name) of the module-level assignments the test `name` reads: `module.NAME` and
    names it imported (a test of a constant, e.g. `"never guess" in inject.GENERAL_NOTE`, calls nothing)."""
    m = p.mod(path)
    d = next((x for x in m.named(name)), None) if m is not None else None
    if m is None or d is None:
        return []
    try:
        node = ast.parse(textwrap.dedent("\n".join(m.lines[d.start - 1:d.end])))
    except SyntaxError:
        return []
    want: list[tuple[str, str]] = []                 # (dotted module, attribute)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in m.imports:
            dotted, attr = m.imports[sub.value.id]
            want.append((f"{dotted}.{attr}" if attr else dotted, sub.attr))
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id in m.imports:
            dotted, attr = m.imports[sub.id]
            if attr:
                want.append((dotted, attr))
    out: list[tuple[str, int, int, str]] = []
    for dotted, attr in dict.fromkeys(want):
        src = module_file(p.tree, dotted)
        if not src or src.startswith("tests/"):
            continue
        other = p.mod(src)
        try:
            body = ast.parse("\n".join(other.lines)).body if other is not None else []
        except SyntaxError:
            continue
        for n in body:
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and t.id == attr for t in targets):
                out.append((src, n.lineno, n.end_lineno or n.lineno, attr))
        if len(out) >= limit:
            break
    return out[:limit]


def pick(tree: Path, fails: list[dict], text: str, diff: str = "",
         symbols: dict[str, list[str]] | None = None, reached: list[dict] | None = None) -> list[Unit]:
    """The ranked units for a failure. Scores: changed by the PR 98, deepest source frame 95, failing test 90,
    function the test calls 80, other source frames 75, traced (`reached`) 84 / 76 / 68 / ... by calls from the
    test (+4 where it raised), callee 50, caller 40, other test frames 30."""
    p = Picker(tree, symbols)
    src_defs: list[Def] = []
    for path, lines in changed_lines(diff).items():
        if path.endswith(".py") and not path.startswith("tests/") and (tree / path).is_file():
            for line in sorted(lines):
                d = p.around(path, line, 98, "changed by the PR")
                if d is not None and d not in src_defs:
                    src_defs.append(d)
    fr = frames(text, tree)
    first = frames(str(fails[0].get("section", "")), tree)[::-1] if fails else []
    order = first + [x for x in fr[::-1] if x not in first]   # the first failure's frames deepest first, then others
    src = [(a, n) for a, n in order if not a.startswith("tests/") and "/tests/" not in a]
    for i, (path, line) in enumerate(src):               # deepest 95, its caller 91, ... never under 75
        d = p.around(path, line, max(75, 95 - 4 * i), "traceback")
        if d is not None and d not in src_defs:
            src_defs.append(d)
        if i == 0 and d is not None:                    # what the failing function called just before it failed
            m0 = p.mod(path)
            for name, at in sorted(d.call_lines.items()):
                before = [n for n in at if n <= line]
                if not before or name in SKIP or name == d.name or m0 is None:
                    continue
                for c in p.resolve(m0, name)[:1]:
                    p.add_def(c, 78 - min(10, (line - max(before)) // 2), f"called by {d.name} before line {line}")
    for i, (path, name) in enumerate(test_ids(fails, text)):
        m = p.mod(path)
        if m is None:
            continue
        for d in m.named(name)[:1]:
            focus = {n for a, n in fr if a == path and d.start <= n <= d.end}
            p.add_def(d, 90 if i == 0 else 70, "failing test", focus)
            for base, attr in sorted(d.attrs):          # module.function(...) in the test
                for c in p.resolve(m, attr, base):
                    gap = min((abs(a - b) for a in d.call_lines.get(attr, []) for b in focus), default=6)
                    p.add_def(c, 85 if gap <= 1 else 80 - min(8, gap // 2), f"called by {name}")
                    if c not in src_defs:
                        src_defs.append(c)
            under = [x for x in (p.mod(module_file(tree, dotted) or "") for dotted, _ in m.imports.values()
                                 if dotted.split(".")[0] in ROOTS) if x is not None]
            for call in sorted(d.calls):
                if call.startswith(("assert", "test_")) or call in SKIP:
                    continue
                gap = min((abs(a - b) for a in d.call_lines.get(call, []) for b in focus), default=6)
                score = 85 if gap <= 1 else 80 - min(8, gap // 2)       # the call on the failing line first
                found = p.resolve(m, call, loose=False)
                if not found:                           # obj.method(...): that name in the modules the test imports
                    found, score = [x for u in under for x in u.named(call)][:2], score - 8
                if not found:                           # the one module in the repo map that defines it
                    found, score = p.resolve(m, call), score - 20
                for c in found:
                    if c.path.startswith("tests/") or "/tests/" in c.path:
                        continue
                    p.add_def(c, score, f"called by {name}")
                    if c not in src_defs:
                        src_defs.append(c)
    for path, line in fr:
        if path.startswith("tests/"):
            p.around(path, line, 30, "traceback (test helper)")
    if reached is not None:                             # wide: the module-level values the failing tests read
        for i, (path, name) in enumerate(test_ids(fails, text)[:2]):
            for src, start, end, attr in constants_read(p, path, name):
                p.add(src, start, end, 83 if i == 0 else 66, f"read by {name} ({attr})")
    for r in (reached or [])[:REACHED]:                 # traced run: what the test really entered, nearest first
        m = p.mod(str(r.get("path", "")))
        start = int(r.get("start") or 0)
        d = m.enclosing(start) if m is not None else None
        if d is None or d.path.startswith("tests/"):
            continue
        depth = int(r.get("depth") or 9)
        raised = {int(r["raised"])} if r.get("raised") else set()
        score, why = max(55, 92 - 8 * depth) + (4 if raised else 0), \
            "the test reaches it" + (" directly" if depth == 1 else f", {depth} calls deep")
        if d.name != r.get("name"):                     # nested (a handler class inside a function): the lines it ran
            ran = [int(n) for n in r.get("lines") or []]
            p.add(d.path, start, min(d.end, max(ran + [start]) + 2), score, f"{why} ({r.get('qual')})", raised)
            continue
        p.add_def(d, score, why, raised)
        if d not in src_defs:
            src_defs.append(d)
    for d in src_defs[:6]:
        for c in p.callees(d, 50, f"called by {d.name}"):
            if reached is not None:                     # wide: one hop more, same file only (night() via jobs())
                for c2 in p.callees(c, 0, "")[:3]:
                    if c2.path == c.path:
                        p.add_def(c2, 42, f"called by {c.name}")
        p.callers(d, 40, f"calls {d.name}")
    relevance(p, text)
    return p.units


WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
COMMON = set(keyword.kwlist) | {"self", "cls", "assert", "assertionerror", "error", "test", "tests", "value", "data",
                                "line", "file", "none", "true", "false", "failed", "raise", "raises", "return", "str",
                                "int", "list", "dict", "len", "result", "out", "expected", "where", "def", "pytest"}


def failure_words(text: str) -> set[str]:
    """Names and words in the lines that say what went wrong: E lines, '>' lines and the locals pytest -l prints."""
    out = set()
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(("E ", ">", "FAILED")) or re.match(r"^\w+\s+= ", s):
            out |= {w for w in WORD.findall(s) if w.lower() not in COMMON}
    return out


def relevance(p: Picker, text: str) -> None:
    """Lines that use the failure's own words become the focus of units that have none, and a callee or caller full
    of them moves up (by at most 9 points: it never passes the code the test calls directly)."""
    words = failure_words(text)
    if not words:
        return
    rel: list[tuple[float, Unit]] = []
    for u in p.units:
        m = p.mod(u.path)
        if m is None or u.path.startswith("tests/"):
            continue
        seen: dict[str, int] = {}
        for ln in m.lines:
            for w in set(WORD.findall(ln)) & words:
                seen[w] = seen.get(w, 0) + 1
        scored = []
        for n in range(u.start, min(u.end, len(m.lines)) + 1):
            hit = set(WORD.findall(m.lines[n - 1])) & words
            if hit:
                scored.append((sum(1 / seen[w] for w in hit), n))
        scored.sort(reverse=True)
        if not u.focus:
            u.focus = {n for _, n in scored[:3]}
        rel.append((sum(s for s, _ in scored[:3]), u))
    top = max((r for r, _ in rel), default=0)
    for r, u in rel:
        if top > 0 and u.score < 80:
            u.score += round(9 * r / top)


SKIP = {"print", "len", "any", "all", "set", "dict", "list", "str", "int", "float", "bool", "tuple", "next", "iter",
        "sorted", "range", "open", "isinstance", "getattr", "setattr", "hasattr", "type", "super", "min", "max", "sum",
        "enumerate", "zip", "map", "filter", "repr", "round", "abs", "Path", "raises", "approx", "patch", "fixture",
        "parametrize", "mark", "monkeypatch", "setenv", "write_text", "read_text", "mkdir", "join", "get", "items",
        "keys", "values", "append", "extend", "update", "format", "strip", "split", "encode", "decode", "loads",
        "dumps", "Mock", "MagicMock", "object"}


# ---------------------------------------------------------------- packing into her window

def _merge(units: list[Unit]) -> list[Unit]:
    """Overlapping units of one file become one (best score, all reasons, all focus lines)."""
    out: list[Unit] = []
    for u in sorted(units, key=lambda u: -u.score):
        for o in out:
            if o.path == u.path and u.start <= o.end + 1 and o.start <= u.end + 1:
                o.start, o.end = min(o.start, u.start), max(o.end, u.end)
                o.why |= u.why
                o.focus |= u.focus
                break
        else:
            out.append(Unit(u.path, u.start, u.end, u.score, set(u.why), set(u.focus)))
    return out


def _render(path: str, lines: list[str], numbers: list[int], why: set[str], focus: set[int]) -> str:
    shown = ", ".join(sorted(why))
    marks = sorted(n for n in focus if n in numbers)
    head = f"--- {path} ({shown}" + (f"; look at line {', '.join(map(str, marks))}" if marks else "") + ")"
    return head + "\n" + "\n".join(f"{n}: {lines[n - 1]}" for n in numbers)


def _span(u: Unit, lines: list[str], budget: int) -> list[int] | None:
    """Line numbers of u to show within budget: all of it, else its first line plus windows around the focus."""
    nums = list(range(u.start, min(u.end, len(lines)) + 1))
    while nums and not lines[nums[-1] - 1].strip():
        nums.pop()
    cost = sum(tokens(f"{n}: {lines[n - 1]}") - 7 for n in nums) + 30
    if cost <= budget:
        return nums
    centre = sorted(u.focus) or [u.start]
    for radius in (15, 10, 6, 3, 1, 0):
        keep = {u.start} | {n for c in centre for n in range(c - radius, c + radius + 1) if u.start <= n <= u.end}
        pick_ = sorted(keep)
        cost = sum(tokens(f"{n}: {lines[n - 1]}") - 7 for n in pick_) + 30
        if cost <= budget:
            return pick_
    return None


def pack(tree: Path, units: list[Unit], budget: int, shown: str = "") -> tuple[str, list[str]]:
    """The units, best first, numbered as in their files, within `budget` tokens; no unit takes more than ~45% (the
    first 60%), and a test whose source the failure text already shows (`shown`) only its failing lines.
    Returns (text, paths shown)."""
    out, used, paths = [], 0, []
    cache: dict[str, list[str]] = {}
    for i, u in enumerate(sorted(_merge(units), key=lambda u: (-u.score, u.path, u.start))):
        if u.path not in cache:
            try:
                cache[u.path] = (tree / u.path).read_text(encoding="utf-8", errors="replace").split("\n")
            except OSError:
                continue
        lines = cache[u.path]
        cap = budget * (60 if i == 0 else 45) // 100
        if u.path.startswith("tests/") and u.focus and lines[u.start - 1].strip() in shown \
                and lines[min(u.end, len(lines)) - 1].strip() in shown:
            cap = 120                                   # the traceback already printed this whole test
        nums = _span(u, lines, min(cap, budget - used))
        if not nums:
            continue
        text = _render(u.path, lines, nums, u.why, u.focus)
        out.append(text)
        used += tokens(text)
        if u.path not in paths:
            paths.append(u.path)
        if budget - used < 60:
            break
    return "\n".join(out), paths


NOISE = re.compile(r"^(?:\S.*: (?:Syntax|Deprecation|User|Resource|Pending\w*)Warning: .*|\s*warnings\.warn\(.*|"
                   r"(?:tmp_path|tmp_path_factory|monkeypatch|capsys|capfd|caplog|request|recwarn)\s+= .*|"
                   r"-- Docs: https://docs\.pytest\.org.*|!{5,} .*)$")


def tidy(text: str) -> str:
    """Pytest output without what never helps a fix: the warnings summary, fixture objects among the locals."""
    out, skip = [], False
    for ln in text.splitlines():
        if re.match(r"^=+ warnings summary =+$", ln):
            skip = True
            continue
        if skip and re.match(r"^=+ .* =+$", ln):
            skip = False
        if skip or NOISE.match(ln):
            continue
        out.append(ln)
    return "\n".join(out)


def failed_at(out: str, test: str) -> int:
    """The line of `test`'s own file where it failed in this pytest output (0: not found); 10**6 once it passes.
    A later line is progress even when as many tests fail (a new function added: the test gets one assert further)."""
    if "::" not in test:
        return 0
    path, _, rest = test.partition("::")
    name = re.sub(r"\[.*$", "", rest.split("::")[-1])
    if not re.search(rf"^FAILED {re.escape(test)}\b", out, re.M) and f"ERROR {test}" not in out:
        return 10 ** 6
    m = re.search(rf"^_{{3,}} (?:\w+\.)?{re.escape(name)}(?:\[.*?\])? _{{3,}}$(.*?)(?=^_{{3,}} |^=+ |\Z)", out,
                  re.M | re.S)
    where = re.escape(path).replace("/", "[/\\\\]")      # Windows prints tests\test_x.py
    at = re.search(where + r":(\d+):", m.group(1) if m else "")
    return int(at.group(1)) if at else 0


def failure_text(fails: list[dict], out: str, budget: int = 1100) -> str:
    """The failing tests for the prompt: most of the budget for the first one (its head and its tail), a little for
    the others and for the tail of the latest local run."""
    parts = []
    for i, f in enumerate(fails):
        share = budget * 2 // 3 if i == 0 else budget // 8
        section = tidy(str(f.get("section", "")))
        errors = "\n".join(dict.fromkeys(ln[:300] for ln in section.splitlines() if ln.startswith("E ")))
        text = clip(f"{f.get('test', '')}\n{section}", share, "both")
        lost = clip("\n".join(ln for ln in errors.splitlines() if ln not in text), share // 3, "head")
        if lost.strip():                                # the E lines say what is wrong: never clipped away
            text = clip(f"{f.get('test', '')}\n{section}", share - tokens(lost), "both") + "\n" + lost
        parts.append(text)
    said = "\n".join(ln for ln in out.splitlines() if re.match(r"\s*(E |FAILED |\S+\.py:\d+)", ln))
    parts.append("local run now:\n" + clip(said or out, budget // 8, "tail"))
    return clip("\n\n".join(parts), budget, "head")


def fixer_prompt(tree: Path, *, title: str, fails: list[dict], out: str, diff: str, lessons: str = "",
                 feedback: str = "", proposed: str = "", window: int = WINDOW, symbols=None,
                 reached: list[dict] | None = None, wide: bool = False) -> str:
    """The fixer's prompt, every part clipped to its share of her window; the code listing gets the rest.
    wide (real fixes): the traced functions (`reached`), what the failure says is missing, the insert edit form, and
    the whole failing test even when the traceback printed its first lines."""
    from litha import fix_reach
    total = window - ANSWER
    grow = max(1.0, min(1.6, window / WINDOW))          # a wider window: a little more output, the rest is code
    sections = "\n\n".join(f"{f.get('test', '')}\n{f.get('section', '')}" for f in fails) + "\n\n" + out
    sections = tidy(sections) if wide else sections     # a warning's file:line is no frame of the failure
    parts = {"title": title[:200], "failures": failure_text(fails, out, int(1100 * grow)),
             "diff": clip(diff, int(450 * grow), "head") if diff.strip() else "(not available)",
             "lessons": clip(lessons, 200, "head"),
             "feedback": clip(feedback, int(450 * grow), "both") + clip(proposed, 300, "head"),
             "missing": "", "insert": INSERT if wide else ""}
    if wide:
        parts["missing"] = clip(fix_reach.missing_note(tree, sections, test_ids(fails, sections))[0], 350, "head")
    if symbols is None:
        symbols = symbol_index(tree)
    units = pick(tree, fails, sections, diff, symbols, reached if wide else None)
    fixed = tokens(FIX_PROMPT.format(code="", repo_map="", **parts))
    budget = total - fixed
    code, paths = pack(tree, units, max(200, budget - 150), parts["failures"] if wide else sections)
    rest = budget - tokens(code)
    where = map_text(tree, paths, max(0, min(150, rest - 10))) if rest > 60 else ""
    return FIX_PROMPT.format(code=code or "(no code found for these failures)", repo_map=where, **parts)


# ---------------------------------------------------------------- landing her edits

NUMBERED = re.compile(r"(?m)^ *\d+: ")
HEADER = re.compile(r"^\s*(?:@\w|(?:async\s+)?def\s|class\s)")


def _at_line(tree: Path, e: dict) -> dict:
    """{find: "", line: N, replace: new} (seen 5 of 5 times on a real fix that needed a new function: all refused as
    an empty find) as an {after, insert} edit: new top-level code goes below the top-level statement holding line N,
    anything else just above line N."""
    path = str(e.get("file", "")).replace("\\", "/").lstrip("./")
    new = NUMBERED.sub("", str(e["replace"])).strip("\n")
    try:
        no = int(str(e.get("line")))
        lines = (tree / path).read_text(encoding="utf-8").split("\n")
        body = ast.parse("\n".join(lines)).body
    except (TypeError, ValueError, OSError, SyntaxError):
        return e
    if not new.strip() or not 1 <= no <= len(lines) + 1:
        return e
    top = not new.lstrip("\n")[:1].isspace()
    if top:
        held = [n for n in body if min([d.lineno for d in getattr(n, "decorator_list", [])] + [n.lineno]) <= no
                <= (n.end_lineno or n.lineno)]
        last = held[0] if held else max((n for n in body if (n.end_lineno or n.lineno) < no),
                                        key=lambda n: n.lineno, default=None)
        if last is not None:                            # a def/class: its header line; else its last line
            at = last.lineno if HEADER.match(lines[last.lineno - 1]) else (last.end_lineno or last.lineno)
            return {"file": path, "after": lines[at - 1], "insert": new, "line": at}
    at = no if no <= len(lines) and lines[no - 1].strip() else next(
        (i for i in range(no, len(lines) + 1) if lines[i - 1].strip()), 0)
    if not at:
        return e
    return {"file": path, "find": lines[at - 1], "line": at,
            "replace": _reindent(new, new, lines[at - 1]) + "\n" + lines[at - 1]}


def inserts(tree: Path, edits) -> list:
    """Her edits with every {after, insert} turned into find/replace: `after` is one existing line (landed like a
    find); after a def/class/decorator line the new lines go below that whole definition, at its indentation."""
    out = []
    for e in mend(edits):
        if isinstance(e, dict) and "find" in e and not str(e["find"]).strip() and "replace" in e:
            e = _at_line(tree, e)                       # her own insert form: an empty find at a line number
        if not isinstance(e, dict) or "find" in e or "after" not in e or "insert" not in e:
            out.append(e)
            continue
        path = str(e.get("file", "")).replace("\\", "/").lstrip("./")
        after, new = NUMBERED.sub("", str(e["after"])).rstrip("\n"), NUMBERED.sub("", str(e["insert"])).strip("\n")
        try:
            text = (tree / path).read_text(encoding="utf-8")
        except OSError:
            out.append({"file": path, "find": after, "replace": after + "\n" + new})
            continue
        got = land(text, after, after, e.get("line"))
        if isinstance(got, str):                        # no such line: apply_edits reports it (and re-asks)
            out.append({"file": path, "find": after, "replace": after + "\n" + new, "line": e.get("line")})
            continue
        start, end = got[0], got[1]
        line_end = text.find("\n", end)
        end = len(text) if line_end < 0 else line_end
        first = text[start:end].split("\n")[0]
        if HEADER.match(first):                          # below the whole def / class
            try:
                tree_ = ast.parse(text)
            except SyntaxError:
                tree_ = None
            no = _line_of(text, start)
            for n in ast.walk(tree_) if tree_ else []:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and \
                        min([d.lineno for d in n.decorator_list] + [n.lineno]) <= no <= n.lineno:
                    lines = text.split("\n")
                    start = sum(len(h) + 1 for h in lines[:min([d.lineno for d in n.decorator_list] + [n.lineno]) - 1])
                    end = sum(len(h) + 1 for h in lines[:n.end_lineno or n.lineno]) - 1
                    new = _reindent(new, new, lines[n.lineno - 1])
                    new = ("\n\n\n" if not lines[n.lineno - 1].startswith((" ", "\t")) else "\n\n") + new
                    break
            else:
                new = "\n" + new
        elif not first[:1].isspace() and not new[:1].isspace() and not first.rstrip().endswith(":"):
            new = "\n\n\n" + new                         # top-level code below a top-level statement
        else:                                            # below that line, at its indentation (deeper after a ':')
            new = "\n" + _reindent(new, new, _indent(first) + ("    " if first.rstrip().endswith(":") else "") + "x")
        out.append({"file": path, "find": text[start:end], "replace": text[start:end] + new,
                    "line": _line_of(text, start)})
    return out


HALF_DOC = re.compile(r'^(\s*)("""|\'\'\')(.*?[^"\'])(["\'])\s*$')


def mend(edits) -> list:
    """`\"\"\"Doc."` -> `\"\"\"Doc.\"\"\"` in her new code: a one-line docstring closed with one quote (4 of her first 5 new
    functions on a real fix; each a syntax error). Only in a replace/insert whose triple quotes do not pair up."""
    out = []
    for e in edits if isinstance(edits, list) else []:
        if isinstance(e, dict):
            for key in ("replace", "insert"):
                text = e.get(key)
                if isinstance(text, str) and (text.count('"""') % 2 or text.count("'''") % 2):
                    lines = text.split("\n")
                    for i, ln in enumerate(lines):
                        m = HALF_DOC.match(ln)
                        if m and m.group(4) == m.group(2)[0] and text.count(m.group(2)) % 2:
                            lines[i] = m.group(1) + m.group(2) + m.group(3) + m.group(2)
                    e = {**e, key: "\n".join(lines)}
        out.append(e)
    return out


def check_syntax(tree: Path, edits) -> list[str]:
    """After her edits land: the exact syntax error of every edited .py file that no longer parses, so she does not
    get the tail of a collection error instead."""
    problems: list[str] = []
    for path in dict.fromkeys(str(e.get("file", "")).replace("\\", "/").lstrip("./") for e in edits or []
                              if isinstance(e, dict)):
        f = tree / path
        if not path.endswith(".py") or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(text)
            continue
        except SyntaxError as err:
            no = err.lineno or 0
            near = text.split("\n")[max(0, no - 2):no + 1]
            problems.append(f"{path}: your edit is not valid Python: {err.msg} at line {no}: " + " | ".join(near))
    return problems


def _indent(s: str) -> str:
    for ln in s.split("\n"):
        if ln.strip():
            return ln[:len(ln) - len(ln.lstrip())]
    return ""


def _reindent(replace: str, find: str, real: str) -> str:
    """Her replace shifted by the difference between her find's indentation and the file's."""
    fi, ri = _indent(find), _indent(real)
    if fi == ri:
        return replace
    out = []
    for ln in replace.split("\n"):
        if not ln.strip():
            out.append(ln)
        elif ln.startswith(fi):
            out.append(ri + ln[len(fi):])
        else:
            out.append(ln)
    return "\n".join(out)


def _cleaned(find: str) -> str:
    """Her find without what the prompt adds around code: listing numbers, or the diff's +/- markers."""
    lines = find.split("\n")
    if any(ln[:1] in "+-" for ln in lines if ln) and all(ln[:1] in "+- " for ln in lines if ln):
        plus = [ln[1:] for ln in lines if ln[:1] in "+ " and ln]
        lines = plus if any(p.strip() for p in plus) else [ln[1:] for ln in lines if ln[:1] in "- " and ln]
    elif NUMBERED.search(find):
        lines = [NUMBERED.sub("", ln) for ln in lines]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _near(text: str, spans: list[tuple[int, int]], line) -> list[tuple[int, int]]:
    """Of several equal matches, the one starting within 3 lines of the line she named (none or 2+: all of them)."""
    try:
        want = int(line)
    except (TypeError, ValueError):
        return spans
    close = [s for s in spans if abs(_line_of(text, s[0]) - want) <= 3]
    return close if len(close) == 1 else spans


def _to_line_start(text: str, start: int) -> int:
    """Back to the start of the line when only indentation precedes `start`."""
    i = text.rfind("\n", 0, start) + 1
    return i if not text[i:start].strip() else start


def land(text: str, find: str, replace: str, line=None) -> tuple[int, int, str, str] | str:
    """(start, end, replace, how) of the one place in `text` her `find` names, or why it names none.
    Tried in order: exact; without listing numbers / diff markers; whitespace-tolerant; a unique fuzzy match of
    whole lines. Two equal places are told apart only by the line number she gave; anything else ambiguous: refused."""
    if not find.strip():
        return "empty find"
    clean = _cleaned(find)
    if clean != find:
        if NUMBERED.search(find):
            replace = NUMBERED.sub("", replace)
        elif _cleaned(replace) != replace and not NUMBERED.search(replace):
            replace = _cleaned(replace)                  # '+new' lines copied from the diff
    for how, text_ in (("exact", find), ("without listing numbers / diff markers", clean)):
        if how != "exact" and clean == find:
            break
        hits = [(m.start(), m.end()) for m in re.finditer(re.escape(text_), text)]
        if len(hits) > 1:
            hits = _near(text, hits, line)
            if len(hits) == 1:
                return hits[0][0], hits[0][1], replace, how + ", told apart by its line number"
            return f"it is in the file {len(hits)} times; give more lines or the right line number"
        if len(hits) == 1:
            return hits[0][0], hits[0][1], replace, how
    chunks = clean.split()
    if not chunks:
        return "empty find"
    loose = [(m.start(), m.end()) for m in re.finditer(r"\s+".join(map(re.escape, chunks)), text)]
    loose = _near(text, loose, line) if len(loose) > 1 else loose
    if len(loose) == 1:
        start = _to_line_start(text, loose[0][0])
        real = text[start:loose[0][1]]
        return start, loose[0][1], _reindent(replace, clean, real) if start != loose[0][0] else replace, \
            "whitespace-tolerant"
    if len(loose) > 1:
        return f"it is in the file {len(loose)} times (ignoring spaces); give more lines or the right line number"
    return _fuzzy(text, clean, replace, line)


FUZZY = 0.88                    # whole-line similarity a fuzzy match needs
MARGIN = 0.06                   # ... and how far ahead of the next best place it must be


def _windows(text: str, want: list[str]) -> list[tuple[float, int]]:
    """(similarity, first line index) of every run of len(want) lines, best first (whitespace collapsed)."""
    have = text.split("\n")
    key = " ".join(" ".join(w.split()) for w in want)
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(key)
    out = []
    n = len(want)
    for i in range(0, max(0, len(have) - n) + 1):
        cand = " ".join(" ".join(h.split()) for h in have[i:i + n])
        if not cand:
            continue
        sm.set_seq1(cand)
        if sm.real_quick_ratio() < 0.5 or sm.quick_ratio() < 0.5:
            out.append((0.0, i))
            continue
        out.append((sm.ratio(), i))
    out.sort(key=lambda x: -x[0])
    return out


def _fuzzy(text: str, find: str, replace: str, line) -> tuple[int, int, str, str] | str:
    want = find.split("\n")
    if sum(len(w.strip()) for w in want) < 12:
        return "not in the file (too short to match loosely)"
    scored = _windows(text, want)
    if not scored or scored[0][0] < FUZZY:
        best = f"{scored[0][0]:.2f}" if scored else "0"
        return f"not in the file (closest lines are {best} similar)"
    best, i = scored[0]
    rivals = [s for s, j in scored[1:] if abs(j - i) >= len(want) and s > best - MARGIN]
    if rivals:
        try:
            near = [(s, j) for s, j in scored if s >= FUZZY and abs(j + 1 - int(line)) <= 3]
        except (TypeError, ValueError):
            near = []
        if len(near) != 1:
            return f"not in the file; {len(rivals) + 1} places look alike ({best:.2f}), refused as ambiguous"
        best, i = near[0]
    have = text.split("\n")
    start = sum(len(h) + 1 for h in have[:i])
    real = "\n".join(have[i:i + len(want)])
    return start, start + len(real), _reindent(replace, find, real), f"fuzzy {best:.2f}"


def nearest(text: str, find: str, n: int = 2, around: int = 2) -> list[tuple[int, int]]:
    """(first, last) 1-based line ranges of the n places most like `find`, with a little context."""
    clean = _cleaned(find) or find
    want = clean.split("\n")
    have = text.split("\n")
    out: list[tuple[int, int]] = []
    for score, i in _windows(text, want):
        if score <= 0 or len(out) == n:
            break
        if any(a - 1 <= i + 1 <= b + 1 for a, b in out):
            continue
        out.append((max(1, i + 1 - around), min(len(have), i + len(want) + around)))
    return out


def note_reject(path: str, find: str, reason: str) -> None:
    """Remember why an edit was refused: in memory (REJECTS) and, when set, one JSON line in REJECT_LOG."""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": path, "reason": reason[:200], "find": find[:300]}
    with _LOCK:
        REJECTS.append(row)
        if REJECT_LOG is not None:
            try:
                REJECT_LOG.parent.mkdir(parents=True, exist_ok=True)
                with REJECT_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass


def reask_prompt(tree: Path, why: str, misses: list[dict], budget: int = WINDOW - ANSWER) -> str:
    """One more question when her find is nowhere in the file: her edits and the nearest real lines, numbered."""
    shown, near = [], []
    for e in misses[:3]:
        path = str(e.get("file", ""))
        try:
            text = (tree / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        have = text.split("\n")
        shown.append(json.dumps({k: e.get(k) for k in ("file", "line", "find", "replace")}, ensure_ascii=False)[:900])
        for a, b in nearest(text, str(e.get("find", ""))):
            near.append(f"--- {path}\n" + "\n".join(f"{i}: {have[i - 1]}" for i in range(a, b + 1)))
    if not near:
        return ""
    body = REASK.format(why=why[:300], missed="\n".join(shown), near="{near}")
    return body.replace("{near}", clip("\n".join(near), budget - tokens(body), "head"))


def reask(tree: Path, why: str, misses: list[dict], asker) -> list:
    """Her answer to reask_prompt: the corrected edits ([] when there is nothing near, or she gives none)."""
    prompt = reask_prompt(tree, why, misses)
    if not prompt:
        return []
    try:
        answer = json.loads(asker(prompt))
    except (ValueError, TypeError):
        return []
    edits = answer.get("edits") if isinstance(answer, dict) else None
    return [e for e in edits if isinstance(e, dict)] if isinstance(edits, list) else []


# ---------------------------------------------------------------- repo map

def tree_hash(tree: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=tree, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", out) else None


def _blobs(tree: Path) -> dict[str, str]:
    """{path: blob sha} of the tracked .py files under the source roots."""
    try:
        r = subprocess.run(["git", "ls-files", "-s", "--", *ROOTS], cwd=tree, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for ln in r.stdout.splitlines():
        meta, _, path = ln.partition("\t")
        bits = meta.split()
        if path.endswith(".py") and len(bits) >= 2:
            out[path] = bits[1]
    return out


def _summary(path: Path) -> dict | None:
    """{doc, symbols: [[name, signature, doc line]], methods: [names]} of one module's public top level."""
    try:
        node = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    syms, methods = [], []
    for n in node.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_"):
            if isinstance(n, ast.ClassDef):
                sig = n.name
                methods += [m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and not m.name.startswith("_")]
            else:
                args = [a.arg for a in n.args.args if a.arg not in ("self", "cls")]
                sig = f"{n.name}({', '.join(args)[:60]})"
            doc = (ast.get_docstring(n) or "").strip().split("\n")[0][:90]
            syms.append([n.name, sig, doc])
    return {"doc": (ast.get_docstring(node) or "").strip().split("\n")[0][:120], "symbols": syms,
            "methods": sorted(set(methods))}


def repo_map(tree: Path, cache_dir: Path | None = None) -> dict[str, dict]:
    """{module path: summary} for every tracked source module, cached per git tree hash (unchanged files are
    reused from the newest earlier map by blob sha, so a new PR head parses only what it changed)."""
    cache_dir = cache_dir or MAP_DIR
    th = tree_hash(tree)
    if th is None:                                 # not a git checkout: no cache
        return {p.relative_to(tree).as_posix(): s for r in ROOTS if (tree / r).is_dir()
                for p in sorted((tree / r).rglob("*.py")) if (s := _summary(p)) is not None}
    f = cache_dir / f"{th}.json"
    if (str(f), th) in _MAPS:
        return _MAPS[(str(f), th)]
    try:
        _MAPS[(str(f), th)] = json.loads(f.read_text(encoding="utf-8"))["modules"]
        return _MAPS[(str(f), th)]
    except (OSError, ValueError, KeyError):
        pass
    old: dict[str, dict] = {}
    try:
        newest = max(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        old = {m["blob"]: m for m in json.loads(newest.read_text(encoding="utf-8"))["modules"].values()
               if "blob" in m}
    except (OSError, ValueError, KeyError):
        pass
    modules = {}
    for path, blob in sorted(_blobs(tree).items()):
        s = old.get(blob) or _summary(tree / path)
        if s is not None:
            modules[path] = {**s, "blob": blob}
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tree": th, "modules": modules}), encoding="utf-8")
        tmp.replace(f)
        for stale in sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-20]:
            stale.unlink(missing_ok=True)             # keep the 20 newest trees
    except OSError:
        pass
    _MAPS[(str(f), th)] = modules
    return modules


_MAPS: dict[tuple[str, str], dict[str, dict]] = {}
_SYMBOLS: dict[str, tuple[str | None, dict[str, list[str]]]] = {}


def symbol_index(tree: Path, cache_dir: Path | None = None) -> dict[str, list[str]]:
    """{public name: [module paths that define it]} from the repo map (top-level names and class methods)."""
    key = str(tree.resolve())
    th = tree_hash(tree)
    hit = _SYMBOLS.get(key)
    if hit and hit[0] == th and th is not None:
        return hit[1]
    out: dict[str, list[str]] = {}
    for path, s in repo_map(tree, cache_dir).items():
        for name in [x[0] for x in s.get("symbols", [])] + s.get("methods", []):
            out.setdefault(name, []).append(path)
    _SYMBOLS[key] = (th, out)
    return out


def map_text(tree: Path, paths: list[str], budget: int, cache_dir: Path | None = None) -> str:
    """'Where things live': for the files shown and the repo modules they import, one line each."""
    if budget < 40 or not paths:
        return ""
    mods = repo_map(tree, cache_dir) if tree_hash(tree) else {}
    if not mods:
        return ""
    want = list(paths)
    cache: dict[str, Module | None] = {}
    for p in paths:
        m = parse(tree, p, cache)
        for dotted, _ in (m.imports.values() if m else []):
            f = module_file(tree, dotted)
            if f and f not in want:
                want.append(f)
    rows = []
    for p in want:
        s = mods.get(p)
        if not s:
            continue
        names = ", ".join(x[1] for x in s["symbols"][:8])
        rows.append(f"{p}: {names}" + (f" - {s['doc']}" if s.get("doc") else ""))
    if not rows:
        return ""
    return clip("Where things live (module: public names):\n" + "\n".join(rows), budget, "head") + "\n"
