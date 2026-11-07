"""Line-level three-way merge inside one git conflict block, for the merges that need no judgement.

Git (xdiff) calls two edits a conflict as soon as they touch neighbouring lines. Most Studio conflicts are that and
nothing more: one side rewrote a comment, the other the line under it (Studio #255 task_lib.rs). Here each side's
edits are taken against the ancestor; edits whose ancestor lines do not overlap are both applied, the same edit made
on both sides is applied once, and only edits that really overlap stay a conflict, as a smaller block with the same
markers (her model then sees just that, with the merged lines around it as context)."""
from __future__ import annotations

import difflib
import re

Edit = tuple[int, int, list[str]]          # ancestor lines [i, j) become these lines


def _lines(s: str) -> list[str]:
    return (s if s.endswith("\n") or not s else s + "\n").splitlines(keepends=True)


def edits(base: list[str], side: list[str]) -> list[Edit]:
    return [(i1, i2, side[j1:j2]) for op, i1, i2, j1, j2 in
            difflib.SequenceMatcher(None, base, side, autojunk=False).get_opcodes() if op != "equal"]


def _clash(a: Edit, b: Edit) -> bool:
    """Two edits from different sides that cannot both be applied as written: their ancestor ranges overlap, both
    insert at the same place (their order is a judgement in code), or one inserts strictly inside the other's range."""
    if a[:2] == b[:2] and a[2] == b[2]:
        return False                                               # the same edit on both sides
    (i1, j1, _), (i2, j2, _) = a, b
    if i1 == j1 and i2 == j2:
        return i1 == i2
    if i1 == j1:
        return i2 < i1 < j2
    if i2 == j2:
        return i1 < i2 < j1
    return max(i1, i2) < min(j1, j2)


def merge(ours: str, base: str, theirs: str, split=_lines) -> list[str | tuple[str, str, str]] | None:
    """The block as pieces: merged text, or (ours, base, theirs) of a part that still conflicts. None when nothing
    could be merged on its own (then the block stays exactly as git wrote it). split: lines, or words for prose."""
    b, o, t = split(base), split(ours), split(theirs)
    eo, et = edits(b, o), edits(b, t)
    et = [e for e in et if e not in eo]                 # the same edit on both sides: applied once
    if not eo and not et:
        return ["".join(o)]
    es = [(e, 0) for e in eo] + [(e, 1) for e in et]
    group = list(range(len(es)))

    def root(k: int) -> int:
        while group[k] != k:
            k = group[k]
        return k
    changed = True
    while changed:                                      # clashing edits, and any edit inside a clash, are one conflict
        changed = False
        spans: dict[int, list[int]] = {}
        for k in range(len(es)):
            spans.setdefault(root(k), []).append(k)
        for ks in spans.values():
            if len({es[k][1] for k in ks}) < 2:
                continue
            lo, hi = min(es[k][0][0] for k in ks), max(es[k][0][1] for k in ks)
            for k in range(len(es)):
                if root(k) != root(ks[0]) and (lo < es[k][0][1] and es[k][0][0] < hi or lo < es[k][0][0] < hi):
                    group[root(k)] = root(ks[0])
                    changed = True
        for x in range(len(es)):
            for y in range(x + 1, len(es)):
                if es[x][1] != es[y][1] and root(x) != root(y) and _clash(es[x][0], es[y][0]):
                    group[root(y)] = root(x)
                    changed = True
    parts: dict[int, list[int]] = {}
    for k in range(len(es)):
        parts.setdefault(root(k), []).append(k)
    clashes = [ks for ks in parts.values() if len({es[k][1] for k in ks}) > 1]
    if len(clashes) == 1 and len(clashes[0]) == len(es):
        return None                                     # one conflict covering every edit: nothing to gain
    pieces: list[tuple[int, int, str | tuple[str, str, str]]] = []
    for ks in parts.values():
        lo, hi = min(es[k][0][0] for k in ks), max(es[k][0][1] for k in ks)
        mine = [es[k][0] for k in ks]
        if len({es[k][1] for k in ks}) == 1:
            pieces.append((lo, hi, "".join(_apply(b, lo, hi, mine))))
        else:
            pieces.append((lo, hi, ("".join(_apply(b, lo, hi, [es[k][0] for k in ks if es[k][1] == 0])),
                                    "".join(b[lo:hi]),
                                    "".join(_apply(b, lo, hi, [es[k][0] for k in ks if es[k][1] == 1])))))
    out: list[str | tuple[str, str, str]] = []
    pos = 0
    for lo, hi, piece in sorted(pieces, key=lambda p: (p[0], p[1])):
        out += ["".join(b[pos:lo]), piece]
        pos = hi
    out.append("".join(b[pos:]))
    return [p for p in out if p != ""]


def _apply(b: list[str], lo: int, hi: int, es: list[Edit]) -> list[str]:
    """Ancestor lines [lo, hi) with one side's edits applied."""
    out, pos = [], lo
    for i, j, new in sorted(es, key=lambda e: (e[0], e[1])):
        out += b[pos:i] + new
        pos = j
    return out + b[pos:hi]


WORDS = re.compile(r"\n|[^\S\n]+|\w+|[^\w\s]")


def _words(s: str) -> list[str]:
    return WORDS.findall("".join(_lines(s)))


def prose(ours: str, base: str, theirs: str) -> str | None:
    """Markdown and text merged word by word when that leaves nothing that overlaps: one side reworded the start of a
    line and the other added a clause at its end (Studio ARCHITECTURE.md: 6 of 18 blocks on its merge commits merged
    this way, 2 exactly as committed; the other 4, read by hand, look right and were rewrapped or rewritten)."""
    pieces = merge(ours, base, theirs, split=_words)
    return "".join(p for p in pieces if isinstance(p, str)) if pieces and all(isinstance(p, str) for p in pieces) \
        else None


W = re.compile(r"\s+")
# where indentation is meaning (a line moved into an `if`, a YAML key under another), only line ends may differ
INDENTED = re.compile(r"(\.(py|pyi|ya?ml|md|mk|nim|coffee|pug|sass|styl|haml)|(^|/)Makefile)$", re.I)
STRING = re.compile(r'r#*"[\s\S]*?"#*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\\n])\'|`(?:\\.|[^`\\])*`')


def _layout_free(s: str, path: str) -> str:
    """The text without what formatting may change: trailing spaces (indented languages), else every whitespace
    run outside string literals (whitespace inside a string is data)."""
    if INDENTED.search(path):
        return "\n".join(ln.rstrip() for ln in s.replace("\r\n", "\n").split("\n"))
    out, pos = [], 0
    for m in STRING.finditer(s):
        out += [W.sub("", s[pos:m.start()]), m.group(0)]
        pos = m.end()
    return "".join(out) + W.sub("", s[pos:])


def formatting_only(ours: str, base: str, theirs: str, path: str = "") -> str | None:
    """A side that differs from the ancestor (or from the other side) only in layout changed nothing: the other
    side's text. (Rust is put back in the repo's format by rustfmt afterwards.) Litha's review of #912: with all
    whitespace removed, a Python line moved into an `if` and a changed string literal counted as formatting."""
    o, b, t = (_layout_free(s, path) for s in (ours, base, theirs))
    if o == t:
        return ours
    if o == b:
        return theirs
    if t == b:
        return ours
    return None


USE = re.compile(r"^[ \t]*((?:pub(?:\([\w:]+\))?\s+)?)use\s+([^;]+);[ \t]*\n?", re.M)


def _flat(tree: str, prefix: str = "") -> list[str]:
    """`a::{b, c::{d, e as f}}` -> ['a::b', 'a::c::d', 'a::c::e as f'] (whitespace dropped)."""
    tree = re.sub(r"\s+", " ", tree).strip()
    head, brace, rest = tree.partition("{")
    if not brace:
        return [prefix + tree] if tree else []
    inner, depth, items, cur = rest.rsplit("}", 1)[0], 0, [], ""
    for ch in inner:
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    out = []
    for it in items:
        out += _flat(it.strip(), prefix + head.strip())
    return out


def _uses(side: str) -> dict[tuple[str, str], list[str]] | None:
    """{(visibility, statement root): [flattened items]} when the text is only `use` statements, else None."""
    if USE.sub("", side).strip():
        return None
    out: dict[tuple[str, str], list[str]] = {}
    for m in USE.finditer(side):
        tree = re.sub(r"\s+", " ", m.group(2)).strip()
        root = tree.split("{", 1)[0].rstrip(":").strip() if "{" in tree else tree.rsplit("::", 1)[0] if "::" in tree else ""
        for p in _flat(tree):
            out.setdefault((m.group(1).strip(), root), []).append(p)
    return out


def use_lists(ours: str, base: str, theirs: str) -> str | None:
    """Rust blocks that are nothing but `use` statements, merged per imported name: what each side added is added,
    what each side removed is removed (Studio #412: the PR imports PropDef while main swaps find_property & co. for
    the class registry). The names stay under the root a side wrote them with; rustfmt orders them afterwards."""
    o, b, t = _uses(ours), _uses(base), _uses(theirs)
    if o is None or b is None or t is None or not o or not t:
        return None
    names = [{(k[0], p) for k, ps in d.items() for p in ps} for d in (o, b, t)]
    so, sb, st = names
    keep = (sb & so & st) | (so - sb) | (st - sb)
    roots: dict[tuple[str, str], list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for d in (o, t, b):
        for k, ps in d.items():
            for p in ps:
                if (k[0], p) in keep and (k[0], p) not in seen:
                    seen.add((k[0], p))
                    roots.setdefault(k, []).append(p)
    indent = ours[:len(ours) - len(ours.lstrip(" \t"))]
    lines = []
    for (vis, root), ps in roots.items():
        rel = [p[len(root) + 2:] if root and p.startswith(root + "::") else p for p in ps]
        body = rel[0] if len(rel) == 1 and root and rel[0] != "self" else "{" + ", ".join(rel) + "}"
        lines.append(f"{indent}{vis + ' ' if vis else ''}use {root + '::' if root else ''}{body};\n")
    return "".join(lines)
