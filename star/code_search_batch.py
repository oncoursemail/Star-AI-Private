"""Bounded multi-query navigation in one pass over a selected workspace.

This is deterministic local search, not another model or an agent scheduler.
The public helper is pure; Workspace.call owns the opt-in tool switch. Existing
single-query search remains unchanged. Each file is read at most once per call,
and text hits share one enclosing-declaration inspection per file. Symbol queries
share parsed declarations. No project code is imported or executed.
"""
from __future__ import annotations

import json
import os

from . import code_navigation as navigation
from .redact import redact_text

MAX_BATCH_QUERIES = 8
MAX_BATCH_RESULT_BYTES = 16_000
MAX_BATCH_SOURCE_BYTES = 24_000_000


def _serialized_bytes(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _validated_queries(queries: list[dict]) -> list[dict]:
    if type(queries) is not list or not 1 <= len(queries) <= MAX_BATCH_QUERIES:
        raise ValueError("Batch search requires between 1 and 8 query objects")
    validated = []
    for item in queries:
        if (type(item) is not dict or "query" not in item
                or set(item) - {"query", "mode"}):
            raise ValueError("Each batch query requires query and an optional mode")
        query, mode = item["query"], item.get("mode", "text")
        if type(query) is not str or not 1 <= len(query) <= 300 or not query.strip():
            raise ValueError("Query must be between 1 and 300 characters")
        try:
            query.encode("utf-8")
        except UnicodeError:
            raise ValueError("Batch queries must contain valid UTF-8 text") from None
        if type(mode) is not str or mode not in ("text", "symbols"):
            raise ValueError("Batch mode must be text or symbols")
        words = list(dict.fromkeys(
            word.casefold() for word in navigation._IDENTIFIER.findall(query)
            if len(word) > 1
        ))[:10]
        if mode == "symbols" and not words:
            raise ValueError("Symbol search needs an identifier")
        validated.append({"query": query, "mode": mode, "words": words,
                          "folded": query.casefold(), "matches": [],
                          "limit_reached": False})
    return validated


def _empty_output(states: list[dict], *, scanned: int, source_bytes: int,
                  scan_limited: bool) -> dict:
    output = {
        "mode": "batch",
        "results": [{"query": state["query"], "mode": state["mode"], "matches": [],
                     "incomplete": False, "omitted_matches": len(state["matches"]),
                     "limit_reached": state["limit_reached"]} for state in states],
        "scanned_files": scanned, "source_bytes": source_bytes,
        "scan_limited": scan_limited, "incomplete": False,
        "budget_bytes": MAX_BATCH_RESULT_BYTES,
    }
    _set_incomplete(output)
    return output


def _set_incomplete(output: dict) -> None:
    for result in output["results"]:
        result["incomplete"] = bool(output["scan_limited"] or result["limit_reached"]
                                    or result["omitted_matches"])
    output["incomplete"] = bool(output["scan_limited"] or any(
        result["incomplete"] for result in output["results"]))


def _pack_results(states: list[dict], *, scanned: int, source_bytes: int,
                  scan_limited: bool) -> dict:
    """Admit ranked hits round-robin, counting the full UTF-8 JSON envelope.

    omitted_matches counts collected hits removed by the shared output budget;
    limit_reached reports a hit cap whose unscanned remainder is unknown. Neither
    field pretends to count every possible match beyond an inspection limit.
    """
    output = _empty_output(states, scanned=scanned, source_bytes=source_bytes,
                           scan_limited=scan_limited)
    if _serialized_bytes(output) > MAX_BATCH_RESULT_BYTES:
        raise ValueError("Batch query metadata exceeds the output budget")
    for index in range(max((len(state["matches"]) for state in states), default=0)):
        for state, result in zip(states, output["results"]):
            if index >= len(state["matches"]):
                continue
            result["matches"].append(state["matches"][index])
            result["omitted_matches"] -= 1
            _set_incomplete(output)
            if _serialized_bytes(output) > MAX_BATCH_RESULT_BYTES:
                result["matches"].pop()
                result["omitted_matches"] += 1
                _set_incomplete(output)
    return output


def batch_search_workspace(workspace, queries: list[dict]) -> dict:
    """Search 1–8 text/symbol queries with shared I/O and a 16,000-byte result.

    All query validation precedes filesystem access. Existing Workspace path,
    hidden/generated-file, symlink and per-file limits are checked on every scan.
    The batch adds a total source-byte ceiling and the existing per-query hit cap.
    source_bytes counts stat-reported bytes attempted, including unreadable or
    binary files; it is not a process-memory or token measurement. Cache reuse is
    controlled only by the existing STAR_CODE_SEARCH_CACHE=on switch.
    """
    states = _validated_queries(queries)
    # Ensure even the largest metadata envelope fits before touching the disk.
    metadata = _empty_output(states, scanned=navigation.MAX_FILES,
                             source_bytes=MAX_BATCH_SOURCE_BYTES, scan_limited=False)
    for result in metadata["results"]:
        result["omitted_matches"] = navigation.MAX_RESULTS
    if _serialized_bytes(metadata) > MAX_BATCH_RESULT_BYTES:
        raise ValueError("Batch query metadata exceeds the output budget")

    text_states = [state for state in states if state["mode"] == "text"]
    symbol_states = [state for state in states if state["mode"] == "symbols"]
    suffixes = None if text_states else navigation.SOURCE_TYPES
    scan = {"limited": False}
    scanned = source_bytes = admitted_raw_bytes = 0
    cache_on = os.environ.get("STAR_CODE_SEARCH_CACHE") == "on"

    # _files has an unannotated two/three-field return; with_stat=True always
    # yields three fields (the same contract used by single-query search).
    for path, relative, info in navigation._files(workspace, suffixes, scan, with_stat=True):  # pyright: ignore[reportAssignmentType]
        if source_bytes + info.st_size > MAX_BATCH_SOURCE_BYTES:
            scan["limited"] = True
            break
        scanned += 1
        source_bytes += info.st_size
        try:
            relative.encode("utf-8")
        except UnicodeError:
            scan["limited"] = True
            continue
        if info.st_size <= navigation._CACHE_FILE_LIMIT:
            admitted_raw_bytes += info.st_size
        cache_file = (cache_on and scanned <= navigation._CACHE_ENTRIES_LIMIT
                      and admitted_raw_bytes <= navigation._CACHE_BYTES_LIMIT // 6)
        try:
            content, folded = navigation._cached_source(path, info, enabled=cache_file)
        except (OSError, UnicodeError):
            scan["limited"] = True
            continue
        if "\x00" in content:
            continue

        active_text = [state for state in text_states
                       if not state["limit_reached"] and state["folded"] in folded]
        file_hits = []
        if active_text:
            for lineno, line in enumerate(content.splitlines(), 1):
                folded_line = line.casefold()
                for state in active_text:
                    if state["folded"] not in folded_line:
                        continue
                    hit = {"file": relative, "line": lineno, "text": line[:200]}
                    state["matches"].append(hit)
                    file_hits.append(hit)
                    if len(state["matches"]) >= navigation.MAX_RESULTS:
                        state["limit_reached"] = True
                active_text = [state for state in active_text if not state["limit_reached"]]
                if not active_text:
                    break
            navigation._add_enclosing(file_hits, content, path.suffix.lower())

        # A mixed batch scans every text file, but declaration search retains the
        # single-query scanner's explicit language set.
        active_symbols = []
        if path.suffix.lower() in navigation.SOURCE_TYPES:
            active_symbols = [state for state in symbol_states if any(
                word in folded or word in relative.casefold() for word in state["words"])]
        if active_symbols:
            symbols = (navigation._cached_py_symbols(path, info, content, enabled=cache_file)
                       if path.suffix.lower() == ".py"
                       else navigation._other_symbols(content, path.suffix.lower()))
            for state in active_symbols:
                for lineno, name, kind, signature in symbols:
                    score = navigation._rank(state["query"], state["words"], relative,
                                             name, signature)
                    if score:
                        state["matches"].append({"file": relative, "line": lineno,
                                                 "name": name, "kind": kind,
                                                 "text": signature, "_score": score})
                if len(state["matches"]) > navigation.MAX_RESULTS * 4:
                    state["matches"].sort(key=lambda hit: (-hit["_score"], hit["file"], hit["line"]))
                    del state["matches"][navigation.MAX_RESULTS * 2:]
                    state["limit_reached"] = True
        if not symbol_states and all(state["limit_reached"] for state in text_states):
            break

    for state in states:
        if state["mode"] == "symbols":
            state["matches"].sort(key=lambda hit: (-hit["_score"], hit["file"], hit["line"]))
            if len(state["matches"]) >= navigation.MAX_RESULTS:
                state["limit_reached"] = True
            del state["matches"][navigation.MAX_RESULTS:]
            for hit in state["matches"]:
                del hit["_score"]
        for hit in state["matches"]:
            hit["text"] = redact_text(hit["text"])
            if "in" in hit:
                hit["in"] = redact_text(hit["in"])
    return _pack_results(states, scanned=scanned, source_bytes=source_bytes,
                         scan_limited=scan["limited"])
