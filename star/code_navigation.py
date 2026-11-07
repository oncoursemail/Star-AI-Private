"""Bounded, read-only code search for an explicitly selected local workspace.

A short symbol result helps a small local model choose which file to read next.
Python symbols use its AST; other language signatures are approximate. This
module does not run project code or spawn subprocesses.
"""
from __future__ import annotations

import ast
import json
import os
import re
import stat
from collections import OrderedDict
from pathlib import Path
from threading import RLock

SOURCE_TYPES = frozenset({'.py', '.lua', '.luau', '.ts', '.tsx', '.js', '.jsx', '.gd', '.cs'})
SKIP_DIRS = frozenset({'node_modules', '__pycache__', 'dist', 'build', '.git',
                       '.venv', 'venv', '.next', '.nuxt', 'target', 'coverage',
                       'site-packages', 'vendor', 'bin', 'obj'})
MAX_FILES = 3000
MAX_DIRS = 1500
MAX_RESULTS = 80
MAX_SYMBOLS_PER_FILE = 300
MAX_SOURCE_BYTES = 250_000
# Text search results go into the model's context. Above this many characters of JSON, hits are cut so that every
# file keeps its first hits (agent grep; the idea is from jcode, github.com/1jehuang/jcode, MIT, no code copied).
TEXT_RESULT_BUDGET = 6000
MAX_ENCLOSING_CHARS = 120
SENSITIVE_FILES = frozenset({'secrets.json', 'credentials.json', 'passwords.txt',
                             'service-account.json', 'service_account.json'})
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
# Conservative single-line declarations; signatures are hints, not parse-verified.
_BRIEF_DECLARATION = re.compile(
    r'^\s*(?:(?:export|default|declare|async|local|public|private|protected|static)\s+)*'
    r'(?:(?:function|class|interface|type|enum|func|class_name|signal)\s+([\w.:]+)'
    r'|(?:const|let|var)\s+([A-Za-z_]\w*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^;]*\)\s*=>|function\b))'
)
_METHOD_DECLARATION = re.compile(
    r'^\s*(?:(?:local|export|async)\s+)*function\s+([A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*)\s*\('
)
_CS_DECLARATION = re.compile(
    r'^\s*(?:(?:public|private|protected|internal|static|override|virtual|async|sealed|partial)\s+)+'
    r'(?:(?:class|interface|enum|struct)\s+(\w+)|[\w<>,\[\]?]+\s+(\w+)\s*\()'
)


# Experimental: repeat code investigations on the same workspace should not reread
# and re-casefold unchanged source files. The app still resolves and validates
# every file on EVERY query; this is only a bounded in-process content cache.
# Enabled only by STAR_CODE_SEARCH_CACHE=on until repeated on-device evaluation.
_CACHE_BYTES_LIMIT = 24 * 1024 * 1024
_CACHE_ENTRIES_LIMIT = 3072
_CACHE_FILE_LIMIT = 96_000
_cache_lock = RLock()
_cache: OrderedDict[str, tuple[tuple[int, ...], str, str, int, tuple | None]] = OrderedDict()
_cache_bytes = 0


def _stamp(info) -> tuple[int, ...]:
    """Require identical metadata and inode before reusing a text snapshot."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _cached_source(path: Path, info, *, enabled: bool) -> tuple[str, str]:
    """Return (source, casefold) with bounded LRU reuse and automatic invalidation.

    Call only AFTER Workspace.resolve, suffix/path checks and stat validation in
    _files. Never use cached text for paths not actually present in the workspace.
    File reads and casefolding happen outside the global lock.
    """
    global _cache_bytes
    if not enabled or info.st_size > _CACHE_FILE_LIMIT:
        source = path.read_text(encoding='utf-8')
        return source, source.casefold()
    key = str(path)
    signature = _stamp(info)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] == signature:
            _cache.move_to_end(key)
            return cached[1], cached[2]
    source = path.read_text(encoding='utf-8')
    folded = source.casefold()
    if '\x00' in source:
        return source, folded
    try:
        # If a file changes during reading, do not preserve a mixed snapshot.
        if _stamp(path.stat()) != signature:
            return source, folded
    except (OSError, ValueError):
        return source, folded
    # Count folded Unicode conservatively; do not cache huge entries.
    cost = info.st_size + 4 * len(folded) + 128
    if cost > _CACHE_BYTES_LIMIT:
        return source, folded
    with _cache_lock:
        old = _cache.pop(key, None)
        if old is not None:
            _cache_bytes -= old[3]
        _cache[key] = (signature, source, folded, cost, None)
        _cache_bytes += cost
        while _cache_bytes > _CACHE_BYTES_LIMIT or len(_cache) > _CACHE_ENTRIES_LIMIT:
            _, removed = _cache.popitem(last=False)
            _cache_bytes -= removed[3]
    return source, folded


def _cached_py_symbols(path: Path, info, content: str, *, enabled: bool):
    """Reuse parsed Python declarations only when the underlying source is unchanged.

    Symbol entries share the same byte/entry LRU as source text. No on-disk
    index or execution of project Python source is required.
    """
    global _cache_bytes
    if not enabled or info.st_size > _CACHE_FILE_LIMIT:
        return _py_symbols(content)
    key, signature = str(path), _stamp(info)
    with _cache_lock:
        existing = _cache.get(key)
        if existing is not None and existing[0] == signature and existing[4] is not None:
            _cache.move_to_end(key)
            return existing[4]
    symbols = tuple(_py_symbols(content))
    try:
        if _stamp(path.stat()) != signature:
            return symbols
    except (OSError, ValueError):
        return symbols
    extra = sum(64 + 4 * (len(name) + len(kind) + len(signature_text))
                for _, name, kind, signature_text in symbols)
    with _cache_lock:
        existing = _cache.get(key)
        if existing is not None and existing[0] == signature:
            if existing[4] is not None:
                _cache.move_to_end(key)
                return existing[4]
            cost = existing[3] + extra
            if cost <= _CACHE_BYTES_LIMIT:
                _cache_bytes -= existing[3]
                _cache[key] = (existing[0], existing[1], existing[2], cost, symbols)
                _cache_bytes += cost
                _cache.move_to_end(key)
                while _cache_bytes > _CACHE_BYTES_LIMIT or len(_cache) > _CACHE_ENTRIES_LIMIT:
                    _, removed = _cache.popitem(last=False)
                    _cache_bytes -= removed[3]
    return symbols


def clear_source_cache() -> None:
    """Clear in-process cache without touching files or on-disk metadata."""
    global _cache_bytes
    with _cache_lock:
        _cache.clear()
        _cache_bytes = 0


def source_cache_stats() -> dict:
    """Internal diagnostic: aggregate sizes only, never source text or paths."""
    with _cache_lock:
        return {'entries': len(_cache), 'bytes': _cache_bytes,
                'max_entries': _CACHE_ENTRIES_LIMIT, 'max_bytes': _CACHE_BYTES_LIMIT}


def _files(workspace, suffixes, scan, *, with_stat: bool = False):
    """Walk real files only, avoiding generated/hidden trees before descent."""
    seen = 0
    visited_dirs = 0
    for parent, dirs, files in os.walk(workspace.root, topdown=True, followlinks=False):
        visited_dirs += 1
        if visited_dirs > MAX_DIRS:
            scan['limited'] = True
            return
        dirs[:] = sorted((name for name in dirs
                          if not name.startswith('.') and name.lower() not in SKIP_DIRS
                          and not (Path(parent) / name).is_symlink()), key=str.casefold)
        for name in sorted(files, key=str.casefold):
            if (name.startswith('.') or name.lower() in SENSITIVE_FILES
                    or (suffixes is not None and Path(name).suffix.lower() not in suffixes)):
                continue
            path = Path(parent) / name
            if path.is_symlink():
                continue
            relative = path.relative_to(workspace.root).as_posix()
            try:
                resolved = workspace.resolve(relative)
                info = resolved.stat()
            except (OSError, PermissionError, ValueError):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
                continue
            yield (resolved, relative, info) if with_stat else (resolved, relative)
            seen += 1
            if seen >= MAX_FILES:
                scan['limited'] = True
                return


def _py_symbols(content: str):
    try:
        module = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError):
        return []
    output = []

    def append(node, name, kind):
        if len(output) >= MAX_SYMBOLS_PER_FILE:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {name}({ast.unparse(node.args)})"
            if node.returns:
                signature += f' -> {ast.unparse(node.returns)}'
        else:
            parents = ', '.join(ast.unparse(base) for base in node.bases)
            signature = f'class {name}' + (f'({parents})' if parents else '')
        output.append((node.lineno, name, kind, signature[:200]))

    for node in module.body:
        if isinstance(node, ast.ClassDef):
            append(node, node.name, 'class')
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    append(child, node.name + '.' + child.name, 'method')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            append(node, node.name, 'function')
    return output


def _py_spans(content: str):
    """(first line, last line, signature) of every Python function and class, nested ones included."""
    try:
        module = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError):
        return []
    spans = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}({ast.unparse(node.args)})"
            if node.returns:
                signature += f' -> {ast.unparse(node.returns)}'
        elif isinstance(node, ast.ClassDef):
            parents = ', '.join(ast.unparse(base) for base in node.bases)
            signature = f'class {node.name}' + (f'({parents})' if parents else '')
        else:
            continue
        spans.append((node.lineno, getattr(node, 'end_lineno', None) or node.lineno, signature))
    return spans


def _add_enclosing(hits: list[dict], content: str, suffix: str) -> None:
    """Name the function or class around each hit: exact for Python (the innermost span), the nearest
    declaration above the hit for other languages (their ends are not parsed)."""
    if suffix not in SOURCE_TYPES or not hits:
        return
    if suffix == '.py':
        spans = _py_spans(content)
        for hit in hits:
            inside = [span for span in spans if span[0] <= hit['line'] <= span[1]]
            if inside:
                start, _, signature = max(inside, key=lambda span: span[0])
                hit['in'], hit['in_line'] = signature[:MAX_ENCLOSING_CHARS], start
        return
    declarations = _other_symbols(content, suffix)
    for hit in hits:
        above = [d for d in declarations if d[0] <= hit['line']]
        if above:
            lineno, _, _, signature = above[-1]
            hit['in'], hit['in_line'] = signature[:MAX_ENCLOSING_CHARS], lineno


def _fit_budget(matches: list[dict], budget: int) -> tuple[list[dict], dict]:
    """Keep the first k hits of every file, k as large as fits the budget; then drop whole files from the end."""
    def size(rows):
        return len(json.dumps(rows, ensure_ascii=False))
    if size(matches) <= budget:
        return matches, {}
    by_file: dict[str, list[dict]] = {}
    for hit in matches:
        by_file.setdefault(hit['file'], []).append(hit)
    kept = matches
    for k in range(max(len(rows) for rows in by_file.values()), 0, -1):
        allowed = {id(hit) for rows in by_file.values() for hit in rows[:k]}
        kept = [hit for hit in matches if id(hit) in allowed]
        if size(kept) <= budget:
            break
    while kept and size(kept) > budget:
        last = kept[-1]['file']
        kept = [hit for hit in kept if hit['file'] != last]
    shown: dict[str, int] = {}
    for hit in kept:
        shown[hit['file']] = shown.get(hit['file'], 0) + 1
    omitted = {name: len(rows) - shown.get(name, 0) for name, rows in by_file.items() if len(rows) > shown.get(name, 0)}
    return kept, omitted


def _other_symbols(content: str, suffix: str):
    output = []
    for lineno, line in enumerate(content.splitlines(), 1):
        if len(output) >= MAX_SYMBOLS_PER_FILE:
            break
        if not line.strip() or line.lstrip().startswith(('--', '//', '#', '*')):
            continue
        matcher = _CS_DECLARATION if suffix == '.cs' else _BRIEF_DECLARATION
        match = matcher.match(line)
        if not match and suffix in ('.lua', '.luau'):
            match = _METHOD_DECLARATION.match(line)
        if match:
            name = next((value for value in match.groups() if value), None)
            if name:
                output.append((lineno, name, 'declaration', line.strip()[:200]))
    return output


def _rank(query: str, words: list[str], relative: str, name: str, signature: str):
    label, path, body = name.casefold(), relative.casefold(), signature.casefold()
    needle = query.casefold().strip()
    score = 45 if label == needle else (22 if needle in label else 0)
    for word in words:
        if word == label or word == label.rsplit('.', 1)[-1]:
            score += 14
        elif word in label:
            score += 9
        elif word in path:
            score += 4
        elif word in body:
            score += 1
    return score


def search_workspace(workspace, query: str, mode: str = 'text') -> dict:
    """Find bounded text lines or declaration signatures; no model-generated execution."""
    if not isinstance(query, str) or not 1 <= len(query) <= 300 or not query.strip():
        raise ValueError('Query must be between 1 and 300 characters')
    if mode not in ('text', 'symbols', 'map'):
        raise ValueError('Unknown workspace search mode')
    if mode == 'map':
        from .repo_map import code_map
        return code_map(workspace, query)
    words = list(dict.fromkeys(word.casefold() for word in _IDENTIFIER.findall(query) if len(word) > 1))[:10]
    if mode == 'symbols' and not words:
        raise ValueError('Symbol search needs an identifier')
    results = []
    scanned = 0
    scan = {'limited': False}
    folded_query = query.casefold()
    cache_on = os.environ.get('STAR_CODE_SEARCH_CACHE') == 'on'
    # Cache only a scan prefix whose estimated full index can fit in memory.
    # Full-project scans on projects larger than the budget must not churn
    # through and evict every file every turn; remaining files are read fresh.
    admitted_raw_bytes = 0
    # Text search reads every small UTF-8 file, whatever its type (C, Ruby, a Godot scene, a Makefile):
    # a list of known types would silently report "no match" for the rest. Symbols need a known language.
    extensions = SOURCE_TYPES if mode == 'symbols' else None
    for path, relative, info in _files(workspace, extensions, scan, with_stat=True):  # pyright: ignore[reportAssignmentType]
        scanned += 1
        if info.st_size <= _CACHE_FILE_LIMIT:
            admitted_raw_bytes += info.st_size
        cache_file = (cache_on and scanned <= _CACHE_ENTRIES_LIMIT
                      and admitted_raw_bytes <= _CACHE_BYTES_LIMIT // 6)
        try:
            content, folded = _cached_source(path, info, enabled=cache_file)
        except (OSError, UnicodeError):
            continue
        if '\x00' in content:
            continue
        if mode == 'text':
            if folded_query not in folded:
                continue
            found = []
            for lineno, line in enumerate(content.splitlines(), 1):
                if folded_query in line.casefold():
                    found.append({'file': relative, 'line': lineno, 'text': line[:200]})
                    if len(results) + len(found) >= MAX_RESULTS:
                        break
            _add_enclosing(found, content, path.suffix.lower())
            results.extend(found)
        else:
            if not any(word in folded or word in relative.casefold() for word in words):
                continue
            symbols = (_cached_py_symbols(path, info, content, enabled=cache_file)
                       if path.suffix.lower() == '.py' else _other_symbols(content, path.suffix.lower()))
            for lineno, name, kind, signature in symbols:
                score = _rank(query, words, relative, name, signature)
                if score:
                    results.append({'file': relative, 'line': lineno, 'name': name,
                                    'kind': kind, 'text': signature, '_score': score})
            if len(results) > MAX_RESULTS * 4:
                results.sort(key=lambda hit: (-hit['_score'], hit['file'], hit['line']))
                results = results[:MAX_RESULTS * 2]
        if mode == 'text' and len(results) >= MAX_RESULTS:
            break
    if mode == 'symbols':
        results.sort(key=lambda hit: (-hit['_score'], hit['file'], hit['line']))
        results = results[:MAX_RESULTS]
        for entry in results:
            del entry['_score']
    omitted = {}
    if mode == 'text':
        found_all = len(results)
        results, omitted = _fit_budget(results, TEXT_RESULT_BUDGET)
    output = {'query': query, 'mode': mode, 'matches': results, 'scanned_files': scanned,
              'incomplete': scan['limited'] or bool(omitted) or (mode == 'text' and found_all >= MAX_RESULTS)
              or (mode == 'symbols' and len(results) >= MAX_RESULTS)}
    if omitted:
        output.update(omitted=omitted, budget_chars=TEXT_RESULT_BUDGET)
    return output
