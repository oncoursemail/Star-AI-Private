"""AST mutants for Litha's bug bench: one realistic bug per mutant, planted by editing the exact source bytes of one
AST node (the rest of the file stays byte-identical, so her diff shows only the bug).

Families (each mutant has a family `op` and an exact change `sub`):
  op-swap      a + b <-> a - b, * <-> /, and <-> or
  cmp-flip     == <-> !=, < <-> >=, > <-> <=, is <-> is not, in <-> not in
  off-by-one   < <-> <=, > <-> >=, an int constant n -> n + 1 (in a comparison, arithmetic, an index or range())
  drop-return  `return x` -> `x` (the function falls through)
  swap-args    f(a, b, ...) -> f(b, a, ...)
  drop-guard   an early-exit `if ...: return/raise/continue/break` removed
  bool-invert  `if c` -> `if not (c)`, `not c` -> `c`, True <-> False

sites(text) lists every mutant of a file in a fixed order; apply(text, site) plants one. A site is found again by
(line, col, sub), which is how the standard suite (litha/bench/standard_suite.json) records its 32 items: the same
file at the same sha always gives the same mutant.
"""
from __future__ import annotations

import ast
import re

FAMILIES = ("op-swap", "cmp-flip", "off-by-one", "drop-return", "swap-args", "drop-guard", "bool-invert")

BIN = {ast.Add: ("+", ast.Sub, "-"), ast.Sub: ("-", ast.Add, "+"), ast.Mult: ("*", ast.Div, "/"),
       ast.Div: ("/", ast.Mult, "*")}
CMP_SYM = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Is: "is",
           ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in"}
FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
        ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
EDGE = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt}
SIMPLE = (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.Constant)
NO_SWAP = {"isinstance", "issubclass", "getattr", "setattr", "hasattr", "print", "super"}
EXITS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _starts(raw: bytes) -> list[int]:
    """Byte offset where each line starts (ast counts lines by \\n and columns in UTF-8 bytes)."""
    return [0] + [i + 1 for i, b in enumerate(raw) if b == 10]


def _gap_op(raw: bytes, a: int, b: int, sym: str) -> tuple[int, int] | None:
    """The operator token between two operands: the gap may hold only spaces, newlines and brackets around it."""
    pat = r"\s+".join(re.escape(w) for w in sym.split())
    m = re.fullmatch(rb"([\s()\\]*)(" + pat.encode() + rb")([\s()\\]*)", raw[a:b])
    if not m:
        return None
    return a + m.start(2), a + m.end(2)


class _Sites:
    def __init__(self, raw: bytes):
        self.raw, self.at = raw, _starts(raw)
        self.out: list[dict] = []

    def off(self, line: int, col: int) -> int:
        return self.at[line - 1] + col

    def span(self, node: ast.AST) -> tuple[int, int]:
        return self.off(node.lineno, node.col_offset), self.off(node.end_lineno, node.end_col_offset)  # type: ignore[attr-defined]

    def text(self, node: ast.AST) -> bytes:
        a, b = self.span(node)
        return self.raw[a:b]

    def add(self, node: ast.AST, op: str, sub: str, edits: list[tuple[int, int, bytes]]) -> None:
        self.out.append({"line": node.lineno, "col": node.col_offset, "op": op, "sub": sub,  # type: ignore[attr-defined]
                         "edits": edits})

    def wrap(self, node: ast.AST) -> bytes:
        t = self.text(node)
        return t if isinstance(node, SIMPLE) else b"(" + t + b")"


def sites(text: str) -> list[dict]:
    """Every mutant of this file, in a fixed order, as {line, col, op, sub, edits}; only code inside functions
    (no module-level constants, nothing inside an f-string)."""
    raw = text.encode("utf-8")
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return []
    s = _Sites(raw)
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
    inside, skip = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside.update(id(n) for n in ast.walk(node) if n is not node)
        elif isinstance(node, ast.JoinedStr):
            skip.update(id(n) for n in ast.walk(node))
    elifs = {id(n.orelse[0]) for n in ast.walk(tree) if isinstance(n, ast.If) and len(n.orelse) == 1
             and isinstance(n.orelse[0], ast.If)
             and raw[s.off(n.orelse[0].lineno, n.orelse[0].col_offset):][:4] == b"elif"}
    for node in ast.walk(tree):
        if id(node) in inside and id(node) not in skip and hasattr(node, "lineno"):
            _node_sites(s, node, parent, elifs)
    seen, uniq = set(), []
    for site in s.out:
        key = (site["line"], site["col"], site["sub"])
        if key not in seen:
            seen.add(key)
            uniq.append(site)
    return uniq


def _node_sites(s: _Sites, node: ast.AST, parent: dict[int, ast.AST], elifs: set[int]) -> None:
    if isinstance(node, ast.BinOp) and type(node.op) in BIN:
        sym, new, nsym = BIN[type(node.op)]
        tok = _gap_op(s.raw, s.span(node.left)[1], s.span(node.right)[0], sym)
        if tok:
            s.add(node, "op-swap", f"{sym}->{nsym}", [(tok[0], tok[1], nsym.encode())])
    elif isinstance(node, ast.BoolOp):
        sym, nsym = ("and", "or") if isinstance(node.op, ast.And) else ("or", "and")
        edits = []
        for a, b in zip(node.values, node.values[1:]):
            tok = _gap_op(s.raw, s.span(a)[1], s.span(b)[0], sym)
            if not tok:
                return
            edits.append((tok[0], tok[1], nsym.encode()))
        s.add(node, "op-swap", f"{sym}->{nsym}", edits)
    elif isinstance(node, ast.Compare):
        left = node.left
        for op, right in zip(node.ops, node.comparators):
            tok = _gap_op(s.raw, s.span(left)[1], s.span(right)[0], CMP_SYM[type(op)])
            if tok:
                for fam, table in (("cmp-flip", FLIP), ("off-by-one", EDGE)):
                    if type(op) in table:
                        new = CMP_SYM[table[type(op)]]
                        s.add(node, fam, f"{CMP_SYM[type(op)]}->{new}", [(tok[0], tok[1], new.encode())])
            left = right
    elif isinstance(node, ast.Constant) and type(node.value) is bool:
        s.add(node, "bool-invert", f"{node.value}->{not node.value}", [(*s.span(node), str(not node.value).encode())])
    elif isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 1000:
        up = parent.get(id(node))
        in_range = (isinstance(up, ast.Call) and isinstance(up.func, ast.Name) and up.func.id == "range")
        if isinstance(up, (ast.Compare, ast.BinOp, ast.Subscript, ast.Slice)) or in_range:
            s.add(node, "off-by-one", f"{node.value}->{node.value + 1}", [(*s.span(node), str(node.value + 1).encode())])
    elif isinstance(node, ast.Return) and node.value is not None:
        a, _ = s.span(node)
        m = re.match(rb"return[ \t]+", s.raw[a:])
        if m:
            s.add(node, "drop-return", "return x->x", [(a, a + m.end(), b"")])
    elif isinstance(node, ast.Call) and len(node.args) >= 2:
        x, y = node.args[0], node.args[1]
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name not in NO_SWAP and not any(isinstance(a, ast.Starred) for a in (x, y)) and s.text(x) != s.text(y):
            s.add(node, "swap-args", "f(a, b)->f(b, a)", [(*s.span(x), s.text(y)), (*s.span(y), s.text(x))])
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        s.add(node, "bool-invert", "not c->c", [(*s.span(node), s.wrap(node.operand))])
    if isinstance(node, (ast.If, ast.While)) and not (isinstance(node.test, ast.UnaryOp)
                                                       and isinstance(node.test.op, ast.Not)):
        s.add(node.test, "bool-invert", "c->not c", [(*s.span(node.test), b"not " + s.wrap(node.test))])
    if (isinstance(node, ast.If) and id(node) not in elifs and not node.orelse and len(node.body) <= 2
            and isinstance(node.body[-1], EXITS)):
        a, b = s.span(node)
        s.add(node, "drop-guard", "if c: exit->pass", [(a, b, b"pass")])


def apply(text: str, site: dict) -> str | None:
    """The file with this one mutant planted; None when it would not parse or changes nothing."""
    raw = text.encode("utf-8")
    for a, b, new in sorted(site["edits"], key=lambda e: e[0], reverse=True):
        raw = raw[:a] + new + raw[b:]
    try:
        out = raw.decode("utf-8")
        if ast.dump(ast.parse(out)) == ast.dump(ast.parse(text)):
            return None
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None
    return out


def find(text: str, line: int, col: int, sub: str) -> dict | None:
    """The site recorded as (line, col, sub) in this file, or None when the file changed."""
    return next((x for x in sites(text) if (x["line"], x["col"], x["sub"]) == (line, col, sub)), None)


def changed_line(text: str, mutated: str, line: int) -> tuple[str, str]:
    """(original line, mutated line) at the site's first line, for the record and the lesson."""
    a, b = text.split("\n"), mutated.split("\n")
    return a[line - 1], b[line - 1] if line - 1 < len(b) else ""
