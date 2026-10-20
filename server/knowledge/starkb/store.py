"""SQLite store: sources, docs, chunks, FTS5 index, embeddings keyed by content hash.

`build()` re-creates docs/chunks/FTS from the checked-out sources (seconds). The `embeddings`
table is keyed by the SHA-256 of the exact text sent to the embedding model, so a rebuild after a
docs update only needs to embed chunks whose text changed (see embed.py). Generated questions
(`chunk_questions`, study.py) are keyed the same way and survive a rebuild.

The rebuild is ONE transaction: the service keeps answering from the previous index until the
new one is committed, and any failure (a missing checkout, a parse error, far fewer chunks than
before) rolls back to the previous index untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from .quiet import wait_while_locked
from .chunking import Doc, chunk_markdown, chunk_reference_yaml

EMBED_MAX_CHARS = 1600   # embedding input cap in characters; the server rejects inputs over 512 tokens, see embed.py
REFERENCE_GROUPS = ("classes", "enums", "datatypes", "libraries", "globals")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  name TEXT PRIMARY KEY, repo TEXT NOT NULL, branch TEXT NOT NULL, commit_sha TEXT NOT NULL,
  commit_date TEXT NOT NULL, licence TEXT NOT NULL, attribution TEXT NOT NULL, indexed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS docs(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL, url TEXT NOT NULL, UNIQUE(source, path));
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES docs(id), ord INTEGER NOT NULL,
  kind TEXT NOT NULL, heading TEXT NOT NULL, anchor TEXT NOT NULL, text TEXT NOT NULL,
  idents TEXT NOT NULL, text_sha TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, ord);
CREATE INDEX IF NOT EXISTS idx_chunks_sha ON chunks(text_sha);
CREATE INDEX IF NOT EXISTS idx_chunks_heading ON chunks(heading);
CREATE TABLE IF NOT EXISTS embeddings(
  text_sha TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY(text_sha, model));
CREATE TABLE IF NOT EXISTS meta(name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunk_questions(
  id INTEGER PRIMARY KEY, text_sha TEXT NOT NULL, ord INTEGER NOT NULL, question TEXT NOT NULL,
  q_sha TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(text_sha, ord));
CREATE INDEX IF NOT EXISTS idx_questions_sha ON chunk_questions(text_sha);
CREATE TABLE IF NOT EXISTS study_log(
  text_sha TEXT PRIMARY KEY, status TEXT NOT NULL, questions INTEGER NOT NULL, model TEXT NOT NULL,
  seconds REAL NOT NULL, created_at TEXT NOT NULL);
"""
FTS = """CREATE VIRTUAL TABLE chunks_fts USING fts5(
  title, heading, idents, text, questions, content='', tokenize="porter unicode61 remove_diacritics 2")"""
MIN_REBUILD_RATIO = 0.8   # a rebuild that yields fewer than this share of the previous chunks is refused


class RebuildRefused(RuntimeError):
    """The new index would be much smaller than the working one; the working one was kept."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Writers queue behind each other; the longest writer is the nightly rebuild (one transaction,
    # about half a minute on a quiet server), so the embedding and study jobs wait up to 5 minutes.
    db = sqlite3.connect(path, timeout=300)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=300000")
    db.executescript(SCHEMA)
    return db


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Read-only connection for the HTTP service: it can never write the index or create a
    schema, and it does not compete for the write lock with a running embedding job."""
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA query_only=ON")
    return db


def questions_text(db, text_sha: str) -> str:
    """The generated questions of a chunk as one FTS field (one per line)."""
    return "\n".join(r[0] for r in db.execute(
        "SELECT question FROM chunk_questions WHERE text_sha=? ORDER BY ord", (text_sha,)))


def fts_has_questions(db) -> bool:
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='chunks_fts'").fetchone()
    return bool(row and "questions" in (row[0] or ""))


def rebuild_fts(db) -> int:
    """Re-create the FTS table from `chunks` (no sources needed), in one transaction. Used once
    to add the questions column to an index built before the study job existed."""
    wait_while_locked(log=lambda message: print(message, file=sys.stderr))
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DROP TABLE IF EXISTS chunks_fts")
        db.execute(FTS)
        questions: dict[str, list[str]] = {}
        for sha, question in db.execute("SELECT text_sha, question FROM chunk_questions ORDER BY text_sha, ord"):
            questions.setdefault(sha, []).append(question)
        n = 0
        for row in db.execute("""SELECT c.id, d.title, c.heading, c.idents, c.text, c.text_sha
                                 FROM chunks c JOIN docs d ON d.id=c.doc_id ORDER BY c.id""").fetchall():
            wait_while_locked(log=lambda message: print(message, file=sys.stderr))
            db.execute("INSERT INTO chunks_fts(rowid,title,heading,idents,text,questions) VALUES(?,?,?,?,?,?)",
                       (row[0], row[1], row[2], row[3], row[4], "\n".join(questions.get(row[5], ()))))
            n += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
    db.commit()
    return n


def set_fts_questions(db, text_sha: str, old: str, new: str) -> int:
    """Replace the questions field of every chunk with this text hash. A contentless FTS5 table
    is updated by deleting the row with its exact old values and inserting it again. The caller
    commits."""
    rows = db.execute("""SELECT c.id, d.title, c.heading, c.idents, c.text FROM chunks c JOIN docs d ON d.id=c.doc_id
                         WHERE c.text_sha=?""", (text_sha,)).fetchall()
    for row in rows:
        db.execute("INSERT INTO chunks_fts(chunks_fts,rowid,title,heading,idents,text,questions) VALUES('delete',?,?,?,?,?,?)",
                   (row[0], row[1], row[2], row[3], row[4], old))
        db.execute("INSERT INTO chunks_fts(rowid,title,heading,idents,text,questions) VALUES(?,?,?,?,?,?)",
                   (row[0], row[1], row[2], row[3], row[4], new))
    return len(rows)


def embed_input(title: str, heading: str, text: str) -> str:
    """EmbeddingGemma document prompt ("title: ... | text: ..."), bounded in size."""
    body = (heading + "\n" + text) if heading and heading != title else text
    return ("title: " + (title or "none") + " | text: " + body)[:EMBED_MAX_CHARS]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, timeout=60).stdout.strip()


_IMPORT = re.compile(r"^import\s+(\w+)\s+from\s+['\"]([^'\"]+\.md)['\"];?[ \t]*$", re.M)


def inline_includes(raw: str, file: Path, root: Path, depth: int = 0) -> str:
    """Creator Docs pages transclude partials: `import X from '../includes/x.md'` + `<X ... />`.

    Without this, pages such as players/disable-ui.md would be indexed as an empty shell.
    Only files inside the content root are read.
    """
    imports = _IMPORT.findall(raw)
    if not imports:
        return raw
    raw = _IMPORT.sub("", raw)
    from .chunking import frontmatter
    for name, rel in imports:
        target = (file.parent / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            continue
        if not target.is_file():
            continue
        body = frontmatter(target.read_text(encoding="utf-8", errors="replace"))[1]
        if depth < 2:
            body = inline_includes(body, target, root, depth + 1)
        raw = re.sub(r"<" + re.escape(name) + r"\b[^>]*/>", lambda _m: "\n\n" + body + "\n\n", raw)
    return raw


def _creator_docs(root: Path, base: str):
    """Yield Doc objects for Roblox/creator-docs (content/en-us)."""
    ref = root / "reference" / "engine"
    parents: dict[str, list[str]] = {}
    import yaml
    class_files = sorted((ref / "classes").glob("*.yaml"))
    raw_cache = {}
    for file in class_files:  # first pass: inheritance map for "Inherits: A > B > C"
        wait_while_locked(log=lambda message: print(message, file=sys.stderr))
        raw = file.read_text(encoding="utf-8")
        raw_cache[file] = raw
        try:
            data = yaml.safe_load(raw)
            parents[str(data["name"])] = [str(x) for x in (data.get("inherits") or [])]
        except Exception:
            continue
    for group in REFERENCE_GROUPS:
        for file in sorted((ref / group).glob("*.yaml")):
            wait_while_locked(log=lambda message: print(message, file=sys.stderr))
            rel = file.relative_to(root).as_posix()
            raw = raw_cache.get(file) or file.read_text(encoding="utf-8")
            url = f"{base}/reference/engine/{group}/{file.stem}"
            try:
                yield chunk_reference_yaml(raw, path=rel, url=url, parents=parents if group == "classes" else None)
            except Exception as exc:  # report, never silently drop
                print(f"SKIP {rel}: {type(exc).__name__}: {exc}")
    for file in sorted(root.rglob("*.md")):
        wait_while_locked(log=lambda message: print(message, file=sys.stderr))
        rel = file.relative_to(root).as_posix()
        if rel.startswith("includes/"):
            continue  # partials that are transcluded into other pages; no public URL of their own
        slug = rel[:-3]
        if slug.endswith("/index"):
            slug = slug[:-6]
        elif slug == "index":
            slug = ""
        url = base + ("/" + slug if slug else "")
        raw = inline_includes(file.read_text(encoding="utf-8", errors="replace"), file, root)
        yield chunk_markdown(raw, path=rel, url=url)


def _luau_site(root: Path, base: str):
    docs = root / "docs"
    for file in sorted(list(docs.rglob("*.md")) + list(docs.rglob("*.mdx"))):
        wait_while_locked(log=lambda message: print(message, file=sys.stderr))
        rel = file.relative_to(root).as_posix()
        raw = file.read_text(encoding="utf-8", errors="replace")
        from .chunking import frontmatter
        meta, _ = frontmatter(raw)
        slug = str(meta.get("slug") or file.relative_to(docs).with_suffix("").as_posix())
        if slug.endswith("/index") or slug == "index":
            slug = slug[:-5].rstrip("/")
        yield chunk_markdown(raw, path=rel, url=base + ("/" + slug if slug else ""))
    for file in sorted((root / "news").glob("*.md")):
        wait_while_locked(log=lambda message: print(message, file=sys.stderr))
        rel = file.relative_to(root).as_posix()
        yield chunk_markdown(file.read_text(encoding="utf-8", errors="replace"), path=rel,
                             url=f"{base}/news/{file.stem}", kind="news")


WALKERS = {"creator-docs": _creator_docs, "luau-site": _luau_site}


NON_COMMERCIAL = re.compile(r"(?:^|-)NC(?:-|$)")


def check_licences(config: dict) -> None:
    """A non-commercial licence (CC BY-NC-*) may be indexed for private use but must never reach a public bundle:
    its source must say `"public_bundle": false`, the flag any export to the app or the public site has to honour."""
    for source in config["sources"]:
        if NON_COMMERCIAL.search(source.get("licence", "")) and source.get("public_bundle") is not False:
            raise ValueError(f"{source['name']}: licence {source['licence']} needs \"public_bundle\": false")


def build(db_path: Path, sources_dir: Path, manifest: Path, *, force: bool = False,
          walkers: dict | None = None, source_metadata: dict | None = None,
          preserve_other_sources: bool = False, log=None) -> dict:
    """Rebuild docs/chunks/FTS from the checked-out repositories, as one transaction (see the
    module text). Embeddings and generated questions are preserved. Raises RebuildRefused, and
    keeps the working index, when the result would have under MIN_REBUILD_RATIO of the chunks it
    had before; force=True skips that check."""
    if log is None:
        log = lambda message: print(message, file=sys.stderr)

    def gate() -> None:
        wait_while_locked(log=log)

    gate()
    config = json.loads(manifest.read_text(encoding="utf-8"))
    check_licences(config)
    db = connect(db_path)
    before = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    old_shas = {r[0] for r in db.execute("SELECT DISTINCT text_sha FROM chunks")}
    db.execute("BEGIN IMMEDIATE")
    try:
        stats = _build_into(db, sources_dir, config, walkers=walkers,
                            source_metadata=source_metadata, preserve_other_sources=preserve_other_sources,
                            gate=gate)
        after = stats["_all"]["chunks"]
        if before and after < before * MIN_REBUILD_RATIO and not force:
            raise RebuildRefused(f"the rebuild has {after} chunks, the working index has {before}; kept the working index")
        new_shas = {r[0] for r in db.execute("SELECT DISTINCT text_sha FROM chunks")}
        stats["_all"]["chunks_before"] = before
        stats["_all"]["texts_added"] = len(new_shas - old_shas)
        stats["_all"]["texts_removed"] = len(old_shas - new_shas)
        db.execute("INSERT OR REPLACE INTO meta VALUES('built_at',?)", (now(),))
        db.commit()
    except BaseException:
        db.rollback()
        db.close()
        raise
    gate()
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
    db.commit()
    db.close()
    return stats


def _build_into(db, sources_dir: Path, config: dict, *, walkers: dict | None = None,
                source_metadata: dict | None = None, preserve_other_sources: bool = False,
                gate=None) -> dict:
    db.execute("DROP TABLE IF EXISTS chunks_fts")
    if preserve_other_sources:
        for source in config["sources"]:
            db.execute("DELETE FROM chunks WHERE doc_id IN (SELECT id FROM docs WHERE source=?)", (source["name"],))
            db.execute("DELETE FROM docs WHERE source=?", (source["name"],))
            db.execute("DELETE FROM sources WHERE name=?", (source["name"],))
    else:
        db.execute("DELETE FROM chunks")
        db.execute("DELETE FROM docs")
        db.execute("DELETE FROM sources")
    db.execute(FTS)
    questions: dict[str, list[str]] = {}
    for sha, question in db.execute("SELECT text_sha, question FROM chunk_questions ORDER BY text_sha, ord"):
        questions.setdefault(sha, []).append(question)
    stats = {}
    # Source groups ("roblox", "engines", "general", ...) let a search keep Roblox questions on the Roblox docs.
    db.execute("INSERT OR REPLACE INTO meta VALUES('source_groups',?)",
               (json.dumps({s["name"]: s.get("group", "roblox") for s in config["sources"]}),))
    for source in config["sources"]:
        if gate:
            gate()
        name = source["name"]
        repo = sources_dir / source.get("checkout", name)
        metadata = (source_metadata or {}).get(name)
        if metadata is None and not (repo / ".git").is_dir():
            from .walkers import snapshot_metadata
            # fetched pages (Wikipedia): SNAPSHOT.json instead of Git; not fetched yet: an empty source, not a failure
            metadata = snapshot_metadata(repo) or {"commit": "pending", "commit_date": ""}
            repo.mkdir(parents=True, exist_ok=True)
        commit = metadata["commit"] if metadata else _git(repo, "rev-parse", "HEAD")
        commit_date = metadata["commit_date"] if metadata else _git(repo, "log", "-1", "--format=%cI")
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                   (name, source["repo"], source.get("branch", ""), commit, commit_date,
                    source["licence"], source["attribution"], now()))
        n_docs = n_chunks = n_chars = 0
        table = WALKERS if walkers is None else walkers
        if name in table:
            walker = table[name]
        else:
            from .walkers import walker_for
            walker = walker_for(source)
        base = source["public_base"].replace("{commit}", commit)
        for doc in walker(repo / source["content_root"] if source.get("content_root") else repo, base):
            if gate:
                gate()
            if not doc.chunks:
                continue
            doc_id = db.execute("INSERT INTO docs(source,path,kind,title,url) VALUES(?,?,?,?,?)",
                                (name, "/".join(p for p in (source["content_root"], doc.path) if p), doc.kind, doc.title,
                                 doc.url)).lastrowid
            n_docs += 1
            for ord_, chunk in enumerate(doc.chunks):
                if gate:
                    gate()
                sha = hashlib.sha256(embed_input(doc.title, chunk.heading, chunk.text).encode("utf-8")).hexdigest()
                rowid = db.execute(
                    "INSERT INTO chunks(doc_id,ord,kind,heading,anchor,text,idents,text_sha) VALUES(?,?,?,?,?,?,?,?)",
                    (doc_id, ord_, chunk.kind, chunk.heading, chunk.anchor, chunk.text, chunk.idents, sha)).lastrowid
                n_chunks += 1
                n_chars += len(chunk.text)
        stats[name] = {"commit": commit, "commit_date": commit_date, "docs": n_docs,
                       "chunks": n_chunks, "chars": n_chars}
    for row in db.execute("SELECT c.id,d.title,c.heading,c.idents,c.text,c.text_sha FROM chunks c JOIN docs d ON d.id=c.doc_id"):
        if gate:
            gate()
        db.execute("INSERT INTO chunks_fts(rowid,title,heading,idents,text,questions) VALUES(?,?,?,?,?,?)",
                   (*row[:5], "\n".join(questions.get(row[5], ()))))
    kinds = dict(db.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind").fetchall())
    sizes = [r[0] for r in db.execute("SELECT length(text) FROM chunks ORDER BY 1")]
    stats["_all"] = {"chunks": len(sizes), "by_kind": kinds,
                     "chars_median": sizes[len(sizes) // 2] if sizes else 0,
                     "chars_p95": sizes[int(len(sizes) * 0.95)] if sizes else 0,
                     "chars_max": sizes[-1] if sizes else 0,
                     "distinct_embed_inputs": db.execute("SELECT COUNT(DISTINCT text_sha) FROM chunks").fetchone()[0]}
    return stats
