"""Bounded, project-scoped code map for small local coding models.

Inspired by Aider's symbol maps, but intentionally smaller: Python AST
symbols plus explicitly heuristic Luau/TS/JS/GDScript/C# declarations, unique
identifier references, and a few deterministic graph-centrality iterations.
This is read-only, has no external imports or network, and never executes
workspace code. The result is a *navigation hint*, not a dependency proof.
"""
from __future__ import annotations

from collections import defaultdict
import json
import re

from .code_navigation import (_IDENTIFIER, SOURCE_TYPES, _files, _other_symbols,
                              _py_symbols, _rank)
from .redact import redact_text

MAX_MAP_FILES = 320
MAX_MAP_SOURCE_BYTES = 6_000_000
MAX_MAP_WORDS_PER_FILE = 5_000
MAX_MAP_DEFINITIONS = 48
MAX_MAP_RETURN_FILES = 12
MAX_MAP_LINES_PER_FILE = 7
MAX_MAP_RESULT_BYTES = 6_000
_IGNORE_GENERIC = frozenset({"main", "test", "data", "init", "self", "root",
                             "call", "run", "get", "set", "start", "update",
                             "new", "default", "props", "value", "state"})


def _bare_name(value: str) -> str:
    return re.split(r"[.:]", value)[-1]


def _read_map_rows(workspace):
    """Honor code_navigation's symlink, protected-name, file and scan limits."""
    scan = {"limited": False}
    rows = []
    total_bytes = 0
    for path, relative in _files(workspace, SOURCE_TYPES, scan):  # pyright: ignore[reportAssignmentType]
        if len(rows) >= MAX_MAP_FILES:
            scan["limited"] = True
            break
        try:
            size = path.stat().st_size
            if total_bytes + size > MAX_MAP_SOURCE_BYTES:
                scan["limited"] = True
                break
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "\x00" in content:
            continue
        total_bytes += size
        defs = (_py_symbols(content) if path.suffix.lower() == ".py"
                else _other_symbols(content, path.suffix.lower()))[:MAX_MAP_DEFINITIONS]
        words = set()
        for match in _IDENTIFIER.finditer(content):
            words.add(match.group(0))
            if len(words) >= MAX_MAP_WORDS_PER_FILE:
                scan["limited"] = True
                break
        rows.append((relative, defs, words))
    return rows, scan["limited"], total_bytes


def code_map(workspace, query: str) -> dict:
    """Summarize relevant project declarations within a strict output budget.

    Query relevance ranks highest; a small PageRank-like score biases ties
    toward files referenced by other files. Cross-file references are based
    solely on *unique* declaration identifiers, not a real language server.
    No raw source body, prompts, or credential-like file contents are returned.
    """
    if type(query) is not str or not 1 <= len(query) <= 300 or not query.strip():
        raise ValueError("Code map query must be 1-300 characters")
    words = list(dict.fromkeys(w.casefold() for w in _IDENTIFIER.findall(query)
                               if len(w) > 1))[:10]
    if not words:
        raise ValueError("Code map requires a code identifier or project topic")
    rows, limited, read_bytes = _read_map_rows(workspace)
    names = [name for name, _, _ in rows]
    definitions = defaultdict(set)
    for path, symbols, _ in rows:
        for _, name, _, _ in symbols:
            bare = _bare_name(name)
            if len(bare) >= 4 and bare.casefold() not in _IGNORE_GENERIC:
                definitions[bare].add(path)
    unique = {symbol: next(iter(paths)) for symbol, paths in definitions.items()
              if len(paths) == 1}

    neighbors = {path: set() for path in names}
    for path, _, tokens in rows:
        for token in tokens:
            target = unique.get(token)
            if target is not None and target != path:
                neighbors[path].add(target)

    # A few bounded, deterministic power iterations. Dangling nodes
    # redistribute mass evenly so a module with no imports is not special.
    n = len(names)
    ranks = {path: 1.0 / n for path in names} if n else {}
    if n:
        for _ in range(8):
            dangling = sum(ranks[path] for path, deps in neighbors.items() if not deps)
            updated = {path: (0.15 + 0.85 * dangling) / n for path in names}
            for path, deps in neighbors.items():
                if not deps:
                    continue
                contribution = 0.85 * ranks[path] / len(deps)
                for target in deps:
                    updated[target] += contribution
            ranks = updated
    max_rank = max(ranks.values(), default=1.0)
    ranked = []
    for path, symbols, tokens in rows:
        if not symbols:
            continue
        scored_symbols = sorted(
            symbols,
            key=lambda row: (-_rank(query, words, path, row[1], row[3]), row[0], row[1]),
        )
        best = max((_rank(query, words, path, row[1], row[3]) for row in symbols),
                   default=0)
        path_hits = sum(word in path.casefold() for word in words)
        referenced_topic = sum(word in {token.casefold() for token in tokens}
                               for word in words)
        relevance = best + path_hits * 8 + min(4, referenced_topic) * 2
        centrality = (ranks[path] / max_rank) if max_rank else 0
        ranked.append((relevance * 10 + centrality, path, scored_symbols))
    ranked.sort(key=lambda entry: (-entry[0], entry[1]))

    output = {
        "query": query, "mode": "map", "files": [],
        "scanned_files": len(rows), "source_bytes": read_bytes,
        "dependency_links": sum(len(v) for v in neighbors.values()),
        "incomplete": limited,
        "method": "python-ast-plus-heuristic-symbol-graph",
        "caveat": "Code-navigation hints, NOT verified references or build/test evidence.",
    }
    omitted = 0
    for _, path, symbols in ranked:
        if len(output["files"]) >= MAX_MAP_RETURN_FILES:
            omitted += 1
            continue
        item = {"file": path, "symbols": [
            {"line": line, "name": name, "kind": kind, "text": redact_text(signature)}
            for line, name, kind, signature in symbols[:MAX_MAP_LINES_PER_FILE]
        ]}
        preview = {**output, "files": output["files"] + [item], "incomplete": True}
        if len(json.dumps(preview, ensure_ascii=False)) > MAX_MAP_RESULT_BYTES:
            omitted += 1
            continue
        output["files"].append(item)
    output["incomplete"] = limited or omitted > 0
    return output
