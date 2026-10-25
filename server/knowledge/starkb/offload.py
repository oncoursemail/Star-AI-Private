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

Automatic variant (`offload-run`, the star-knowledge-offload timer on the brain): the same thing in one process with no
files. It reads the pending texts from the index, embeds them on a worker over the LAN (the laptop's GPU), and writes
each batch straight into the index (INSERT OR IGNORE). The index is the resume state, so a stop at any point, a laptop
that goes away or a run cut by --max-seconds simply continues next time, and with nothing pending it exits at once.
A claim file (claim/release below) keeps this and the PC's gpu_embed.py from embedding the same texts.
"""
from __future__ import annotations

from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, tzinfo
import io
import json
import math
import os
from pathlib import Path
import time
from typing import BinaryIO, Iterable, TextIO
from zoneinfo import ZoneInfo

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


# ---- automatic embedding on a LAN worker (offload-run) -------------------------------------------------------------

CLAIM_TTL = 1200.0                    # seconds; offload-run renews it before every batch group, so a dead run frees it
MIN_MEDIAN_COSINE, MIN_EACH_COSINE = 0.9997, 0.999   # measured laptop vs brain 1: median 0.99982, min 0.99951 (n=1000)


def claim(path: Path, owner: str, ttl: float = CLAIM_TTL, *, clock=time.time) -> str:
    """Take or renew the claim on embedding the pending texts. Returns "" when `owner` holds it now, else the
    name of the holder. An expired claim is taken over (the rename lets only one contender win)."""
    path = Path(path)
    record = json.dumps({"owner": owner, "until": clock() + ttl})
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            if held.get("owner") == owner:
                tmp = path.with_name(f"{path.name}.{os.getpid()}")
                tmp.write_text(record, encoding="utf-8")
                os.replace(tmp, path)
                return ""
            if held.get("until", 0) > clock():
                return str(held.get("owner") or "?")
            stale = path.with_name(f"{path.name}.stale.{os.getpid()}")
            try:
                os.rename(path, stale)
            except OSError:
                continue                      # someone else took it over first
            stale.unlink(missing_ok=True)
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(record)
            return ""
    return "?"


def release(path: Path, owner: str) -> bool:
    """Give the claim back (only its owner can). True when a claim of `owner` was removed."""
    path = Path(path)
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("owner") != owner:
            return False
        path.unlink()
        return True
    except (OSError, ValueError):
        return False


def in_window(hours: tuple[int, int], tz: "tzinfo | str", at: datetime | None = None) -> bool:
    """Is the local hour in [start, end)? (Wraps past midnight when start > end.) `tz`: a name or a tzinfo."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    hour = (at or datetime.now(zone)).astimezone(zone).hour
    start, end = hours
    return start <= hour < end if start <= end else hour >= start or hour < end


def check_worker(db_path: Path, worker, model: str, n: int = 24) -> dict:
    """Embed n texts the brain already embedded on `worker` and compare with the stored vectors."""
    buffer = io.StringIO()
    sample_existing(db_path, buffer, model, n=n)
    rows = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    if not rows:
        return {"n": 0, "ok": True}
    vectors, _ = embed_batch(worker, [r["input"] for r in rows], {})
    sims = sorted(cosine(r["vec"], v) for r, v in zip(rows, vectors))
    median = sims[len(sims) // 2]
    return {"n": len(sims), "min": round(sims[0], 6), "median": round(median, 6),
            "ok": sims[0] >= MIN_EACH_COSINE and median >= MIN_MEDIAN_COSINE}


def run_on_worker(db_path: Path, worker, model: str, *, claim_path: Path, owner: str = "laptop", batch: int = 8,
                  in_flight: int = 2, max_seconds: float = 3300.0, small: int = 3000, hours: tuple[int, int] = (0, 8),
                  tz: "tzinfo | str" = "America/Chicago", log=print, stop=lambda: False, wait=wait_while_locked,
                  clock=time.monotonic, at: datetime | None = None, dim: int = DIM) -> dict:
    """Embed the pending texts on `worker` (client.Brain contract) and store them (see the module docstring).

    A run with more than `small` texts pending is a bulk change and only starts inside `hours` (local hours in `tz`),
    so the laptop's owner is not disturbed in the evening; a small delta runs at any time. Stops, resumably, when
    nothing is pending, someone else holds the claim, the worker is down or fails the parity check, a stop is
    requested, or `max_seconds` is used up."""
    db = connect(db_path)
    todo = pending(db, model)
    result = {"pending_before": len(todo), "embedded_now": 0, "pending_after": len(todo), "stopped": "", "ok": True}
    if not todo:
        result["stopped"] = "nothing pending"
    elif len(todo) > small and not in_window(hours, tz, at):
        result["stopped"] = f"{len(todo)} pending is a bulk change: waits for {hours[0]:02d}:00-{hours[1]:02d}:00 {getattr(tz, "key", tz)}"
    else:
        holder = claim(claim_path, owner)
        if holder:
            result["stopped"] = f"{holder} holds the claim"
    if result["stopped"]:
        db.close()
        log(f"offload-run: {result['stopped']}")
        return result
    try:
        started, stats, done = clock(), {}, 0
        try:
            parity = check_worker(db_path, worker, model)
            log(f"offload-run: worker parity {parity}")
            if not parity["ok"]:
                result["stopped"], result["ok"] = "parity check failed", False
        except Exception as exc:                  # noqa: BLE001 - worker off, asleep or erroring: nothing is lost
            result["stopped"] = f"worker not usable ({type(exc).__name__}: {str(exc)[:120]})"
        size = batch * in_flight
        with ThreadPoolExecutor(max_workers=in_flight) as pool:
            for first in range(0, 0 if result["stopped"] else len(todo), size):
                if wait(log, stop) is None or stop():
                    result["stopped"] = "stop requested"
                    break
                if clock() - started > max_seconds:
                    result["stopped"] = "time budget used"
                    break
                if claim(claim_path, owner):
                    result["stopped"] = "claim lost to another embedder"
                    break
                group = todo[first:first + size]
                parts = [group[i:i + batch] for i in range(0, len(group), batch)]
                try:
                    outputs = list(pool.map(lambda part: embed_batch(worker, [t for _, t in part], stats), parts))
                except Exception as exc:          # noqa: BLE001
                    result["stopped"] = f"worker failed ({type(exc).__name__}: {str(exc)[:120]})"
                    break
                stamp = now()
                rows = [(sha, model, dim, array("f", vec).tobytes(), stamp)
                        for part, (vectors, _) in zip(parts, outputs) for (sha, _), vec in zip(part, vectors)]
                if any(len(row[3]) != 4 * dim or not unit_length(row[3]) for row in rows):
                    result["stopped"], result["ok"] = "worker returned a bad vector", False
                    break
                db.executemany("INSERT OR IGNORE INTO embeddings(text_sha,model,dim,vec,created_at) VALUES(?,?,?,?,?)", rows)
                db.commit()
                done += len(rows)
        seconds = clock() - started
        result.update(embedded_now=done, pending_after=len(todo) - done, seconds=round(seconds, 1),
                      chunks_per_s=round(done / seconds, 2) if seconds and done else None,
                      shortening_retries=stats.get("truncated", 0))
        result["stopped"] = result["stopped"] or "done"
        result["embeddings_total"] = db.execute("SELECT COUNT(*) FROM embeddings WHERE model=?", (model,)).fetchone()[0]
    finally:
        db.close()
        release(claim_path, owner)
    log(f"offload-run: {json.dumps(result)}")
    return result
