"""Embed the index on another machine (a GPU) and load the vectors back, resumably.

A bulk re-index (hundreds of thousands of new chunks) takes days on the brain's CPU and slows chat the whole time.
The same EmbeddingGemma GGUF on a graphics card gives the same vectors (same model file, the server's own pooling and
L2 normalisation, the same 512-token batch limit so the same inputs get shortened) in a fraction of the time:

    brain:  python -m starkb offload-export > pending.jsonl          one {"sha", "input"} line per text to embed
    GPU:    embed_file(url, pending.jsonl, vectors.bin)               resumable; appends fixed-size records
    brain:  python -m starkb offload-import < vectors.bin              INSERT OR IGNORE, a commit every batch

vectors.bin = records of 32 bytes (the text's SHA-256) + dim float32 (little-endian). A record cut short by a kill is
ignored and overwritten on the next run. The import never replaces a vector the brain already has, skips hashes that
are no longer in the index, refuses vectors that are not unit length, and pauses for the quiet lock between batches.
Searches keep running: the service reads with its own read-only connection and reloads the matrix when the count
changes (search.VectorCache).
"""
from __future__ import annotations

from array import array
import json
import math
from pathlib import Path
from typing import BinaryIO, Iterable, TextIO

from .embed import embed_batch, pending
from .quiet import wait_while_locked
from .store import connect, embed_input, now

DIM = 768                       # EmbeddingGemma 300M


def record_size(dim: int = DIM) -> int:
    return 32 + 4 * dim


def export_pending(db_path: Path, out: TextIO, model: str, *, limit: int | None = None) -> int:
    """Write every text that has no `model` vector yet as one JSON line {"sha", "input"} (the exact embedding input)."""
    db = connect(db_path)
    rows = pending(db, model)
    db.close()
    for sha, text in rows[:limit] if limit else rows:
        out.write(json.dumps({"sha": sha, "input": text}, ensure_ascii=False) + "\n")
    return len(rows[:limit] if limit else rows)


def read_records(stream: BinaryIO, dim: int = DIM) -> Iterable[tuple[str, bytes]]:
    """(sha hex, float32 bytes) per complete record; a short tail is ignored."""
    size = record_size(dim)
    while True:
        chunk = stream.read(size)
        if len(chunk) < size:
            return
        yield chunk[:32].hex(), chunk[32:]


def done_shas(path: Path, dim: int = DIM) -> set[str]:
    """Hashes already in a vectors file; cuts off a partial last record (a kill mid-write) so appends stay aligned."""
    if not path.exists():
        return set()
    size = record_size(dim)
    whole = path.stat().st_size // size * size
    if whole != path.stat().st_size:
        with path.open("r+b") as handle:
            handle.truncate(whole)
    with path.open("rb") as handle:
        return {sha for sha, _ in read_records(handle, dim)}


def unit_length(vec: bytes, tolerance: float = 0.01) -> bool:
    values = array("f", vec)
    total = sum(v * v for v in values)
    return math.isfinite(total) and abs(math.sqrt(total) - 1.0) <= tolerance


def embed_file(brain, pending_path: Path, out_path: Path, *, batch: int = 32, dim: int = DIM, gate=None,
               stop=lambda: False, log=print) -> dict:
    """Embed the lines of `pending_path` that are not in `out_path` yet; append one record per text.

    `brain` is a client.Brain pointed at the GPU server. `gate()` is called before every batch and may block (the PC
    is busy) or return False to end the run (it is resumable). Uses embed.embed_batch, so an input over the server's
    batch limit is shortened exactly as the brain's own job would shorten it."""
    have = done_shas(out_path, dim)
    todo = []
    with pending_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["sha"] not in have:
                todo.append((row["sha"], row["input"]))
    stats: dict = {}
    done = 0
    log(f"offload: {len(todo)} texts to embed, {len(have)} already in {out_path.name}")
    with out_path.open("ab") as out:
        for start in range(0, len(todo), batch):
            if stop() or (gate is not None and gate() is False):
                break
            part = todo[start:start + batch]
            vectors, _ = embed_batch(brain, [text for _, text in part], stats)
            for (sha, _), vec in zip(part, vectors):
                if len(vec) != dim:
                    raise RuntimeError(f"the server returned {len(vec)} dimensions, expected {dim}")
                out.write(bytes.fromhex(sha) + array("f", vec).tobytes())
            out.flush()
            done += len(part)
    return {"embedded_now": done, "left": len(todo) - done, "shortening_retries": stats.get("truncated", 0)}


def import_vectors(db_path: Path, stream: BinaryIO, model: str, *, dim: int = DIM, batch: int = 2000,
                   log=print, stop=lambda: False, wait=wait_while_locked) -> dict:
    """Load records into `embeddings` for `model`. Never replaces an existing vector; skips unknown hashes."""
    db = connect(db_path)
    known = {r[0] for r in db.execute("SELECT DISTINCT text_sha FROM chunks")}
    counts = {"read": 0, "inserted": 0, "already": 0, "unknown": 0, "bad": 0}
    rows: list[tuple] = []

    def flush() -> None:
        if not rows:
            return
        wait(log, stop)
        before = db.total_changes
        db.executemany("INSERT OR IGNORE INTO embeddings(text_sha,model,dim,vec,created_at) VALUES(?,?,?,?,?)", rows)
        db.commit()
        inserted = db.total_changes - before
        counts["inserted"] += inserted
        counts["already"] += len(rows) - inserted
        rows.clear()

    stamp = now()
    for sha, vec in read_records(stream, dim):
        counts["read"] += 1
        if sha not in known:
            counts["unknown"] += 1
        elif not unit_length(vec):
            counts["bad"] += 1
        else:
            rows.append((sha, model, dim, vec, stamp))
            if len(rows) >= batch:
                flush()
                if stop():
                    break
    flush()
    counts["embeddings_total"] = db.execute("SELECT COUNT(*) FROM embeddings WHERE model=?", (model,)).fetchone()[0]
    db.close()
    log(f"offload-import: {counts}")
    return counts


def sample_existing(db_path: Path, out: TextIO, model: str, n: int = 200) -> int:
    """Write n texts that already have a `model` vector, with that vector, spread over all sources (for checks)."""
    db = connect(db_path)
    rows = db.execute(
        """SELECT c.text_sha, d.title, c.heading, c.text, e.vec FROM chunks c JOIN docs d ON d.id=c.doc_id
           JOIN embeddings e ON e.text_sha=c.text_sha AND e.model=? GROUP BY c.text_sha
           ORDER BY substr(c.text_sha, 1, 8) LIMIT ?""", (model, n)).fetchall()
    db.close()
    for sha, title, heading, text, vec in rows:
        out.write(json.dumps({"sha": sha, "input": embed_input(title, heading, text),
                              "vec": list(array("f", vec))}) + "\n")
    return len(rows)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def compare_sample(brain, sample_path: Path, *, batch: int = 16) -> dict:
    """Embed a sample_existing() file with `brain` and compare to the stored vectors (cosine per text)."""
    rows = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sims: list[float] = []
    stats: dict = {}
    for start in range(0, len(rows), batch):
        part = rows[start:start + batch]
        vectors, _ = embed_batch(brain, [r["input"] for r in part], stats)
        sims += [cosine(r["vec"], v) for r, v in zip(part, vectors)]
    ordered = sorted(sims)
    return {"n": len(sims), "min": round(ordered[0], 6) if sims else None,
            "median": round(ordered[len(ordered) // 2], 6) if sims else None,
            "below_0.999": sum(s < 0.999 for s in sims), "shortening_retries": stats.get("truncated", 0)}
