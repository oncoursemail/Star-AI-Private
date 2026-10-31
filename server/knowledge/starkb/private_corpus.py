"""A PRIVATE corpus: the STAR brain vault (the team's own notes and code map) as its own index.

The public index (`kb.sqlite3`: Roblox and Luau docs, open textbooks) is rebuilt every night from Git
checkouts and may be exported; the notes of the team must never be in it. So they live in a SECOND SQLite
file with the same schema, built by this module from a folder of Markdown (see `star.brain_vault`):

    python -m starkb build-private --vault <folder>          # -> $STAR_KB_HOME/data/private.sqlite3
    python -m starkb --db <private.sqlite3> embed            # optional: vectors for the hybrid/vector modes
    python -m starkb --db <private.sqlite3> eval --questions eval/vault-questions.jsonl --modes bm25,hybrid

`serve` answers `POST /search {"corpus": "private", ...}` from that file when `STAR_KB_PRIVATE_DB` names it
(see serve.py); a request without `corpus` never sees it. The one source is marked `public_bundle: false`.
No network; the build walks `*.md` below the vault, skipping dot-folders.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from .chunking import chunk_markdown
from .store import build, now

SOURCE = "star-brain"
GROUP = "team"
SKIP_PARTS = {"node_modules"}
MAX_FILE_BYTES = 512 * 1024


def _kind(rel: str) -> str:
    top = rel.split("/", 1)[0]
    return {"code": "code-note", "daily": "daily-note"}.get(top, "note")


def vault_files(root: Path) -> list[Path]:
    files = []
    for file in sorted(root.rglob("*.md")):
        parts = file.relative_to(root).parts
        if (any(p.startswith(".") or p in SKIP_PARTS for p in parts) or file.is_symlink()
                or file.stat().st_size > MAX_FILE_BYTES):
            continue
        files.append(file)
    return files


def walker(root: Path, base: str):
    """Doc per note; the doc path is the vault-relative path, the URL `vault://<path>` (no web page exists)."""
    for file in vault_files(root):
        rel = file.relative_to(root).as_posix()
        yield chunk_markdown(file.read_text(encoding="utf-8", errors="replace"), path=rel,
                             url="vault://" + rel, kind=_kind(rel), fallback_title=file.stem)


def fingerprint(root: Path) -> str:
    """What the index was built from: a hash over every note's path and bytes."""
    digest = hashlib.sha256()
    for file in vault_files(root):
        digest.update(file.relative_to(root).as_posix().encode("utf-8"))
        digest.update(file.read_bytes())
    return digest.hexdigest()


def build_private(vault: Path, db_path: Path, *, force: bool = False, log=None) -> dict:
    """(Re)build the private index from the vault in one transaction; embeddings of unchanged notes are kept."""
    vault = vault.expanduser().resolve()
    if not vault.is_dir():
        raise FileNotFoundError(f"vault folder not found: {vault}")
    config = {"sources": [{
        "name": SOURCE, "group": GROUP, "repo": "local:" + SOURCE, "checkout": vault.name, "branch": "",
        "licence": "PRIVATE (the team's own notes; never in a public bundle)",
        "attribution": "STAR brain vault: the owner's and the team's notes",
        "public_bundle": False, "content_root": "", "public_base": "vault://"}]}
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "private-corpora.json"
        manifest.write_text(json.dumps(config), encoding="utf-8")
        return build(db_path, vault.parent, manifest, force=force, walkers={SOURCE: walker},
                     source_metadata={SOURCE: {"commit": fingerprint(vault), "commit_date": now()}}, log=log)
