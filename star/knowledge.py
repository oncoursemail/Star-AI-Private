"""Project-scoped, evidence-carrying knowledge and immutable local artifacts.

No vector database or model call is required for this first exact/keyword retrieval layer.
Entries are candidate knowledge unless an explicit trusted caller promotes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Literal

Kind = Literal["requirement", "reference", "decision", "fix", "observation", "unknown",
               "preference", "correction", "pitfall", "fact"]
# The last four are lesson kinds (star/lessons.py). A lesson is an ordinary note whose
# `status` column is set; `reviewed` stays the one flag that decides what is trusted.
LESSON_KINDS = ("preference", "correction", "pitfall", "fact")
VALID_KINDS = frozenset({"requirement", "reference", "decision", "fix", "observation", "unknown",
                         *LESSON_KINDS})
# Added to `notes` by ALTER TABLE on open (never dropped, never rewritten): the lesson lifecycle.
#   status         NULL for a plain note; candidate | accepted | rejected | superseded | merged
#   source_type    user | manual | chat-correction | feedback | retry | verified-fix | doc | summary
#   updated        last status or text change (ISO time)
#   supersedes_id  the older lesson this one replaced
#   subject        normalised subject words, used to find the lesson a newer one replaces
#   evidence       what the lesson was taken from (a redacted excerpt), shown at review
#   merged_into    the summarised candidate a raw capture was folded into
LESSON_COLUMNS = (("status", "TEXT"), ("source_type", "TEXT"), ("updated", "TEXT"),
                  ("supersedes_id", "INTEGER"), ("subject", "TEXT"), ("evidence", "TEXT"),
                  ("merged_into", "INTEGER"))
APPROVED_DECISION_SOURCE = "user:explicit-approved-decision"
MAX_ARTIFACT = 32 * 1024 * 1024
PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,95}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project(value: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not PROJECT.fullmatch(value):
        raise ValueError("Project identifier must contain 1-96 safe characters")
    return value


@dataclass(frozen=True)
class Note:
    id: int
    project: str
    kind: str
    text: str
    source: str
    revision: str
    reviewed: bool
    created: str


class KnowledgeStore:
    """Small, auditable memory for references, decisions, and checked results.

    Ordinary AI-written notes are *candidate*, not ground truth. Use review_note()
    only from an authorized human or independently verified acceptance workflow.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "knowledge.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
            source TEXT NOT NULL, revision TEXT NOT NULL,
            reviewed INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project,reviewed,created)")
        self._add_lesson_columns()
        self.db.execute("""CREATE TABLE IF NOT EXISTS artifacts (
            digest TEXT PRIMARY KEY, size INTEGER NOT NULL, media_type TEXT NOT NULL,
            created TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS project_artifacts (
            project TEXT NOT NULL, digest TEXT NOT NULL, origin TEXT NOT NULL,
            PRIMARY KEY(project,digest,origin),
            FOREIGN KEY(digest) REFERENCES artifacts(digest)
        )""")
        # FTS5 is optional on minimal system Python builds. The fallback is
        # parameterized LIKE; original notes are never dropped or migrated away.
        self._fts = False
        try:
            self.db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
                USING fts5(text, source, content='notes', content_rowid='id', tokenize='unicode61')""")
            self.db.executescript("""
                CREATE TRIGGER IF NOT EXISTS note_fts_add AFTER INSERT ON notes BEGIN
                  INSERT INTO notes_fts(rowid,text,source) VALUES(new.id,new.text,new.source);
                END;
                CREATE TRIGGER IF NOT EXISTS note_fts_delete AFTER DELETE ON notes BEGIN
                  INSERT INTO notes_fts(notes_fts,rowid,text,source)
                  VALUES('delete',old.id,old.text,old.source);
                END;
                CREATE TRIGGER IF NOT EXISTS note_fts_update AFTER UPDATE ON notes BEGIN
                  INSERT INTO notes_fts(notes_fts,rowid,text,source)
                  VALUES('delete',old.id,old.text,old.source);
                  INSERT INTO notes_fts(rowid,text,source) VALUES(new.id,new.text,new.source);
                END;
            """)
            self.db.execute("CREATE TABLE IF NOT EXISTS index_meta(name TEXT PRIMARY KEY, value TEXT)")
            if not self.db.execute(
                "SELECT 1 FROM index_meta WHERE name='fts5_initialized'"
            ).fetchone():
                # One-time safe backfill for old installations.
                self.db.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
                self.db.execute("INSERT INTO index_meta(name,value) VALUES('fts5_initialized','1')")
            self._fts = True
        except sqlite3.OperationalError:
            self._fts = False
        self.db.commit()

    def _add_lesson_columns(self) -> None:
        """Additive migration: lesson columns on `notes`, per-lesson use counts, one backfill.

        Existing rows keep every value they had. Decisions the owner approved before this
        version are labelled as accepted (or superseded) lessons so the review page lists
        them; nothing about what is trusted changes, because `reviewed` is left alone.
        """
        if self._lessons_ready():
            return   # the usual case: an open that writes nothing
        # The interface, a turn and the background steps can all open the store at the same
        # moment on the first run of a new version. One of them migrates inside a single
        # write transaction; the others wait for it (busy_timeout) and then find it done.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            present = {row[1] for row in self.db.execute("PRAGMA table_info(notes)")}
            for name, kind in LESSON_COLUMNS:
                if name not in present:
                    self.db.execute(f"ALTER TABLE notes ADD COLUMN {name} {kind}")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_notes_lessons ON notes(project,status,id)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS lesson_use (
                note_id INTEGER PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 0, last_used TEXT NOT NULL
            )""")
            self.db.execute("CREATE TABLE IF NOT EXISTS store_meta(name TEXT PRIMARY KEY, value TEXT)")
            if not self.db.execute("SELECT 1 FROM store_meta WHERE name='lessons_v1'").fetchone():
                self.db.execute(
                    "UPDATE notes SET status=CASE WHEN reviewed=1 THEN 'accepted' ELSE 'superseded' END, "
                    "source_type='manual', updated=created WHERE status IS NULL AND source=?",
                    (APPROVED_DECISION_SOURCE,))
                self.db.execute("INSERT OR IGNORE INTO store_meta(name,value) VALUES('lessons_v1','1')")
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def _lessons_ready(self) -> bool:
        """True when this database already has everything the lesson migration adds."""
        present = {row[1] for row in self.db.execute("PRAGMA table_info(notes)")}
        if any(name not in present for name, _ in LESSON_COLUMNS):
            return False
        tables = {row[0] for row in self.db.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('lesson_use','store_meta','idx_notes_lessons')")}
        if len(tables) != 3:
            return False
        return self.db.execute("SELECT 1 FROM store_meta WHERE name='lessons_v1'").fetchone() is not None

    def add_note(self, *, project: str, kind: str, text: str, source: str, revision: str = "unknown") -> int:
        project = _project(project)
        if kind not in VALID_KINDS:
            raise ValueError("Unknown note kind")
        if not isinstance(text, str) or not text.strip() or len(text) > 16_000:
            raise ValueError("Knowledge note must be 1–16000 nonempty characters")
        if not isinstance(source, str) or not source.strip() or len(source) > 2048:
            raise ValueError("A provenance reference is required")
        if not isinstance(revision, str) or not revision.strip() or len(revision) > 200:
            raise ValueError("A revision identifier is required")
        row = self.db.execute(
            "INSERT INTO notes(project,kind,text,source,revision,created) VALUES(?,?,?,?,?,?)",
            (project, kind, text, source, revision, now()),
        )
        self.db.commit()
        return int(row.lastrowid)

    def review_note(self, *, project: str, note_id: int, evidence: str) -> None:
        """Called only from a *trusted* review or test-acceptance path, not by model prose."""
        project = _project(project)
        if not evidence.strip() or len(evidence) > 2048:
            raise ValueError("Verified evidence identifier is required")
        # Append the review evidence as a separate immutable observation note.
        row = self.db.execute("SELECT id FROM notes WHERE project=? AND id=?", (project, note_id)).fetchone()
        if row is None:
            raise ValueError("Knowledge note doesn't belong to this project")
        self.add_note(project=project, kind="observation", text=f"Reviewed note {note_id}: {evidence}",
                      source=f"review:{note_id}", revision="accepted")
        self.db.execute("UPDATE notes SET reviewed=1 WHERE project=? AND id=?", (project, note_id))
        self.db.commit()

    def find(self, project: str, query: str = "", *, reviewed_only: bool = True,
             limit: int = 12, allowed_note_ids: frozenset[int] | None = None) -> list[Note]:
        """Retrieve relevant evidence first, not just the most recent matching note.

        Uses SQLite FTS5 BM25 with a reviewed/project filter. A robust
        parameterized LIKE fallback supports older SQLite builds without FTS5.
        Never promotes unreviewed notes to trusted context. When the caller
        supplies a bounded allowlist, filter inside SQL BEFORE ranking and
        limiting; post-retrieval filtering can starve approved evidence.
        """
        project = _project(project)
        if allowed_note_ids is not None and (
            type(allowed_note_ids) is not frozenset
            or len(allowed_note_ids) > 128
            or any(type(note_id) is not int or note_id < 1
                   for note_id in allowed_note_ids)
        ):
            raise ValueError("allowed_note_ids must be a bounded set of positive integers")
        if type(limit) is not int or not 1 <= limit <= (128 if allowed_note_ids is not None else 50):
            raise ValueError("limit must be 1..50 (or 1..128 with allowed_note_ids)")
        if not isinstance(query, str) or len(query) > 4000:
            raise ValueError("Search query must be text up to 4,000 characters")
        if allowed_note_ids is not None and not allowed_note_ids:
            return []
        allowed = tuple(sorted(allowed_note_ids)) if allowed_note_ids is not None else None
        tokens = re.findall(r"[A-Za-z0-9_]{2,}", query.lower())[:12]
        if tokens and self._fts and not any('_' in token for token in tokens):
            # Underscores are FTS token separators; use escaped LIKE to preserve
            # exact identifier semantics and avoid matching `hello_world` to `hello world`.
            # Quoted, regex-validated terms cannot inject FTS5 operators.
            match_query = " OR ".join('"' + token + '"' for token in tokens)
            sql = """SELECT notes.* FROM notes_fts
                JOIN notes ON notes.id=notes_fts.rowid
                WHERE notes_fts MATCH ? AND notes.project=?"""
            values: list[object] = [match_query, project]
            if reviewed_only:
                sql += " AND notes.reviewed=1"
            if allowed is not None:
                sql += " AND notes.id IN (" + ",".join("?" for _ in allowed) + ")"
                values.extend(allowed)
            sql += " ORDER BY notes_fts.rank ASC, notes.id DESC LIMIT ?"
            values.append(limit)
            try:
                rows = self.db.execute(sql, values).fetchall()
            except sqlite3.OperationalError:
                rows = self._find_like(project, tokens, reviewed_only, limit, allowed)
        else:
            rows = self._find_like(project, tokens, reviewed_only, limit, allowed)
        return [Note(id=int(row["id"]), project=row["project"], kind=row["kind"],
                     text=row["text"], source=row["source"], revision=row["revision"],
                     reviewed=bool(row["reviewed"]), created=row["created"])
                for row in rows]

    def find_ranked(self, project: str, query: str, *, reviewed_only: bool = True,
                    limit: int = 12) -> list[Note]:
        """Alias onto the already-ranked FTS5 retrieval from verified memory.

        Preserve v0.9's reviewed-only, project-scoped BM25/LIKE fallback rather
        than replacing its FTS tables with an incompatible older index format.
        """
        return self.find(project, query, reviewed_only=reviewed_only, limit=limit)

    def find_contextual(self, project: str, prompt: str, *, limit: int = 8) -> list[Note]:
        """Read only reviewed facts, with recall-intent fallback for implicit queries.

        "What did we decide last time?" may share zero lexical words with
        "Use warm gold accents". In those explicit recall requests, fill
        remaining slots from recent reviewed decisions. No model-generated
        candidate is promoted, and retrieval never crosses project scope.
        """
        found = self.find(project, prompt, reviewed_only=True, limit=limit)
        recall = re.search(
            r"\b(remember|recall|earlier|previous|before|last time|"
            r"decided|decision|chose|agreed|approved)\b",
            prompt.lower(),
        )
        if not recall or len(found) >= limit:
            return found
        known = {row.id for row in found}
        more = self.db.execute(
            """SELECT * FROM notes WHERE project=? AND reviewed=1
               AND kind IN ('requirement','decision','fix')
               ORDER BY id DESC LIMIT ?""",
            (_project(project), limit * 3),
        )
        for row in more:
            if int(row["id"]) in known:
                continue
            found.append(Note(id=int(row["id"]), project=row["project"],
                              kind=row["kind"], text=row["text"],
                              source=row["source"], revision=row["revision"],
                              reviewed=True, created=row["created"]))
            if len(found) >= limit:
                break
        return found

    def _find_like(self, project: str, tokens: list[str], reviewed_only: bool,
                   limit: int, allowed_note_ids: tuple[int, ...] | None = None):
        sql = "SELECT * FROM notes WHERE project=?"
        params: list[object] = [project]
        if reviewed_only:
            sql += " AND reviewed=1"
        if allowed_note_ids is not None:
            sql += " AND id IN (" + ",".join("?" for _ in allowed_note_ids) + ")"
            params.extend(allowed_note_ids)
        if tokens:
            sql += " AND (" + " OR ".join("lower(text) LIKE ? ESCAPE '\\'" for _ in tokens) + ")"
            params.extend("%" + t.replace("_", "\\_").replace("%", "\\%") + "%" for t in tokens)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self.db.execute(sql, params).fetchall()

    def ingest_artifact(self, *, project: str, path: Path, origin: str, media_type: str) -> tuple[str, Path]:
        """Store original bytes by SHA256; never treat file content as executable instructions."""
        project = _project(project)
        if not origin or len(origin) > 2048:
            raise ValueError("Artifact origin required")
        if not media_type or len(media_type) > 100:
            raise ValueError("Artifact MIME type required")
        if not path.is_file() or path.stat().st_size > MAX_ARTIFACT:
            raise ValueError("Artifact missing or too large")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        dest = self.root / "artifacts" / digest[:2] / digest
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as stream:
                name = Path(stream.name)
                try:
                    stream.write(raw)
                except BaseException:
                    name.unlink(missing_ok=True)
                    raise
            os.replace(name, dest)
        self.db.execute("INSERT OR IGNORE INTO artifacts(digest,size,media_type,created) VALUES(?,?,?,?)",
                        (digest, len(raw), media_type, now()))
        self.db.execute("INSERT OR IGNORE INTO project_artifacts(project,digest,origin) VALUES(?,?,?)",
                        (project, digest, origin))
        self.db.commit()
        return digest, dest

    def artifact(self, project: str, digest: str) -> Path:
        project = _project(project)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid sha256 digest")
        row = self.db.execute("SELECT 1 FROM project_artifacts WHERE project=? AND digest=?",
                              (project, digest)).fetchone()
        if not row:
            raise ValueError("Artifact isn't accessible in this project")
        path = self.root / "artifacts" / digest[:2] / digest
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Artifact missing or checksum failed")
        return path

    def close(self) -> None:
        self.db.close()
