"""Local-only retrieval of automatically checked night-school worked examples.

These are unreviewed *reference data*, not lessons, permissions, training samples
or evidence that anything ran in Roblox Studio. No model or network dependency.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sqlite3

from .knowledge import _project, now
from .lessons import grants_permission, has_secret

HEADING = "DECLARED AUTOMATED-CHECK PRACTICE EXAMPLES (untrusted reference, unreviewed)"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 500
MAX_PROMPT_CHARS = 2400
MAX_REQUEST_CHARS = 1500
# Keep full checked implementations, including multi-function worked examples.
# Storage limits are separate from the unchanged per-turn retrieval budget.
MAX_ANSWER_CHARS = 64_000
# JSON can expand one Unicode character to a pair of six-character escapes.
# Allow that worst case plus metadata while retaining a bounded row/file size.
MAX_ROW_CHARS = 1024 * 1024
MIN_SCORE = 0.6
_ROW_KEYS = frozenset(("id", "group_id", "task_category", "instruction", "response", "evidence",
                       "source", "reviewed", "rights_confirmed", "lessons_in_context"))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\Z")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,59}")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+")
_API = re.compile(r"\b(?:[A-Z][A-Za-z0-9]{3,}|[A-Za-z_][A-Za-z0-9_]*[.:][A-Za-z_][A-Za-z0-9_]*)\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ROLE = re.compile(r"(?i)<\|(?:im_start|im_end|system|assistant)\|>|\[/?INST\]")
_STOP = frozenset("""a an and are as at be by can code create do does for from function functions game
give how i in into is it lua luau make me my of on or please roblox script scripts should
show simple some that the this to use using want we what when where which with write you your
example examples module local return get set new help""".split())


@dataclass(frozen=True)
class Example:
    id: str
    group_id: str
    category: str
    instruction: str
    response: str
    evidence: tuple[str, ...] = ()


def _safe_text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if (type(value) is not str or len(value) > maximum or (not empty and not value.strip())
            or _CONTROL.search(value) or _ROLE.search(value) or has_secret(value)
            or grants_permission(value)):
        raise ValueError("Invalid " + label)
    return value


def validate_row(row: object) -> Example:
    """Require the exact server outbox schema and explicit automatic-check provenance."""
    if type(row) is not dict or set(row) != _ROW_KEYS:
        raise ValueError("Invalid worked-example fields")
    group = _safe_text(row["group_id"], "task ID", 100)
    identifier = _safe_text(row["id"], "example ID", 113)
    if not _ID.fullmatch(group) or identifier != "night-school-" + group:
        raise ValueError("Invalid night-school example identity")
    category = _safe_text(row["task_category"], "category", 80, empty=True)
    instruction = _safe_text(row["instruction"], "instruction", MAX_REQUEST_CHARS)
    response = _safe_text(row["response"], "response", MAX_ANSWER_CHARS)
    if (row["source"] != "night-school-verified" or row["reviewed"] is not False
            or row["rights_confirmed"] is not False):
        raise ValueError("Only unreviewed automated-check exports are accepted")
    evidence = row["evidence"]
    if (type(evidence) is not list or not 1 <= len(evidence) <= 4
            or not all(type(item) is str and item.startswith("night-school automated checks: ")
                       and item.split(":", 1)[1].strip()
                       and len(item) <= 400 and not has_secret(item) and not _CONTROL.search(item)
                       for item in evidence)):
        raise ValueError("Missing automated-check evidence")
    lessons = row["lessons_in_context"]
    if (type(lessons) is not list or len(lessons) > 20
            or any(type(item) is not str or len(item) > 100 or not _ID.fullmatch(item)
                   for item in lessons)):
        raise ValueError("Invalid lesson references")
    return Example(identifier, group, category, instruction, response, tuple(evidence))


def parse_export(raw: bytes) -> list[Example]:
    """Validate the whole JSONL input before any database writes."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Empty or oversized worked-example export")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ValueError("Worked examples must be UTF-8") from exc
    if not lines or len(lines) > MAX_ROWS or any(not line.strip() or len(line) > MAX_ROW_CHARS for line in lines):
        raise ValueError("Invalid worked-example row count or length")
    found, seen = [], set()
    for line in lines:
        try:
            value = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise ValueError("Malformed worked-example JSONL") from exc
        entry = validate_row(value)
        if entry.id in seen:
            raise ValueError("Duplicate worked-example ID in export")
        found.append(entry)
        seen.add(entry.id)
    return found


def import_file(path: Path, *, home: Path, project: str) -> dict:
    """Import into a separate SQLite file; never touch owner notes or replace a row.

    Every row is validated before any database write.
    """
    project = _project(project)
    with Path(path).open("rb") as handle:
        rows = parse_export(handle.read(MAX_FILE_BYTES + 1))
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(home / "worked_examples.sqlite3")) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS worked_examples (
            project TEXT NOT NULL, id TEXT NOT NULL, group_id TEXT NOT NULL,
            category TEXT NOT NULL, instruction TEXT NOT NULL, response TEXT NOT NULL,
            PRIMARY KEY (project, id))""")
        # New table keeps the claimed evidence without changing the original
        # six-column schema used by older databases and reviewed learning bundles.
        # Older imports have no provenance row: their original evidence cannot
        # be reconstructed or implied by this migration.
        db.execute("""CREATE TABLE IF NOT EXISTS worked_example_provenance (
            project TEXT NOT NULL, id TEXT NOT NULL, source TEXT NOT NULL,
            evidence TEXT NOT NULL, reviewed INTEGER NOT NULL,
            rights_confirmed INTEGER NOT NULL, PRIMARY KEY (project, id))""")
        db.execute("BEGIN IMMEDIATE")
        current = {item[0] for item in db.execute(
            "SELECT id FROM worked_examples WHERE project=?", (project,))}
        if len(current | {row.id for row in rows}) > MAX_ROWS:
            raise ValueError(f"Worked-example project corpus cannot exceed {MAX_ROWS} records")
        count = 0
        for row in rows:
            cursor = db.execute(
                "INSERT OR IGNORE INTO worked_examples VALUES (?,?,?,?,?,?)",
                (project, row.id, row.group_id, row.category, row.instruction, row.response))
            if cursor.rowcount:
                db.execute(
                    "INSERT INTO worked_example_provenance VALUES (?,?,?,?,?,?)",
                    (project, row.id, "night-school-verified",
                     json.dumps(list(row.evidence)), 0, 0))
                count += 1
    return {"project": project, "imported": count, "skipped": len(rows) - count}


def terms(value: str) -> list[str]:
    """Whole identifiers plus camelCase pieces; no substring-only API matching."""
    result = []
    for match in _WORD.finditer(value[:MAX_REQUEST_CHARS]):
        word = match.group()
        pieces = [word.lower(), *(part.lower() for part in _CAMEL.findall(word))]
        result.extend(part for part in pieces if len(part) > 2 and part not in _STOP)
    return result


# Terms of each example, kept in memory: tokenizing all 500 examples on every turn was ~96% of the
# ~250 ms a retrieval took (docs/agents/instant-memory-presolve.md). Pure function of the text, so a cached
# value is always right; at most _DOCUMENT_CACHE entries (a few MB), cleared when full. Callers only read it.
_DOCUMENTS: dict[tuple[str, str], Counter[str]] = {}
_DOCUMENT_CACHE = 4 * MAX_ROWS


def _document(row: Example) -> Counter[str]:
    key = (row.instruction, row.response)
    found = _DOCUMENTS.get(key)
    if found is not None:
        return found
    # Original request dominates; the response contributes API names only.
    request = terms(row.instruction)
    api = [piece for match in list(_API.finditer(row.response))[:50]
           for piece in terms(match.group())]
    if len(_DOCUMENTS) >= _DOCUMENT_CACHE:
        _DOCUMENTS.clear()
    found = _DOCUMENTS[key] = Counter(request * 3 + api)
    return found


def rank(prompt: str, examples: list[Example], *, limit: int = 2) -> list[tuple[Example, float]]:
    """Small deterministic BM25 corpus; two distinctive words and coverage are required."""
    if type(prompt) is not str or not 1 <= limit <= 2:
        return []
    query = set(terms(prompt))
    if len(query) < 2 or not examples:
        return []
    docs = [_document(row) for row in examples]
    lengths = [sum(doc.values()) for doc in docs]
    average = max(1.0, sum(lengths) / len(lengths))
    frequency = Counter(token for doc in docs for token in doc)
    found = []
    for row, doc, length in zip(examples, docs, lengths):
        overlap = query & doc.keys()
        if len(overlap) < 2 or len(overlap) / len(query) < .40:
            continue
        value = sum(
            math.log1p((len(examples) - frequency[word] + .5) / (frequency[word] + .5))
            * doc[word] * 2.2 / (doc[word] + 1.2 * (.25 + .75 * length / average))
            for word in overlap)
        if value >= MIN_SCORE:
            found.append((row, value))
    found.sort(key=lambda item: (-item[1], item[0].id))
    return found[:limit]


def select(home: Path, project: str, prompt: str, *, max_chars: int = MAX_PROMPT_CHARS) -> tuple[str, list[Example]]:
    """Read-only retrieval; do not create a database or touch the app when unconfigured."""
    if type(max_chars) is not int or max_chars < 0 or max_chars > MAX_PROMPT_CHARS:
        raise ValueError("Invalid worked-example prompt budget")
    path = Path(home) / "worked_examples.sqlite3"
    if max_chars < 200 or not path.is_file():
        return "", []
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db, db:
        # Examples from a learning bundle (star/learned_week.py) stop being used when their 14 days are over.
        timed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='example_expiry'").fetchone()
        expiry = ("AND id NOT IN (SELECT id FROM example_expiry WHERE project=? AND expires_at<=?) " if timed else "")
        filters = (_project(project), *((_project(project), now()) if timed else ()))
        # Pre-cap databases can contain more than 500 usable records. Never silently
        # discard later IDs or change them in a read-only retrieval call. Expired
        # learning-bundle rows wait for the weekly sweep and are not usable, so they do not count.
        total = db.execute("SELECT COUNT(*) FROM worked_examples WHERE project=? " + expiry,
                           filters).fetchone()[0]
        if total > MAX_ROWS:
            raise ValueError(f"Worked-example project corpus exceeds {MAX_ROWS} records; "
                             "archive or review the legacy database before enabling retrieval")
        values = (*filters, MAX_ROWS)
        rows = db.execute(
            "SELECT id,group_id,category,instruction,response FROM worked_examples WHERE project=? " + expiry +
            "ORDER BY id LIMIT ?", values).fetchall()
    entries = [Example(*row) for row in rows]
    result, used = [], []
    for example, _score in rank(prompt, entries):
        line = (f"[checked practice {len(used) + 1}; claimed automated checks, unreviewed; not Studio verification]\n"
                f"Request: {example.instruction}\nExample response:\n{example.response}\n"
                "[end checked practice]\n")
        if len(line) + sum(map(len, result)) > max_chars:
            continue
        result.append(line)
        used.append(example)
    return "".join(result), used


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import automatically checked practice examples locally")
    parser.add_argument("command", choices=["import"])
    parser.add_argument("file", type=Path, help="Night-school worked-examples.jsonl export")
    parser.add_argument("--project", required=True)
    parser.add_argument("--home", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.home is None:
        from .desktop_core import app_data
        home = app_data()
    else:
        home = args.home
    result = import_file(args.file, home=home, project=args.project)
    print(f"Imported {result['imported']} worked examples; skipped {result['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
