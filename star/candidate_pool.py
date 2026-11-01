"""M5 "generate once, select many": the candidate pool STAR writes while it answers, for offline replay.

Every candidate code block the check-fix ladder (star/verify_ladder.py) looks at, and every candidate best-of-N
(star/best_of_n.py) writes, can be appended to a JSON-lines file together with what the checks said and how long
it took. Any later change that only *selects, verifies, ranks or accepts* candidates is then scored from the file
(star/pool_replay.py) at zero model cost.

Off unless a flag is set. A run turns it on with `--pool DIR [--pool-tag NAME]` on `python -m star.evals run`
(the same as the environment variables STAR_CANDIDATE_POOL=DIR and STAR_CANDIDATE_POOL_TAG=NAME); the file is
DIR/pool-NAME.jsonl. The recorders never raise and never change an answer.

One JSON object per line, schema 1:
  {"kind": "answer", "answer_id", "prompt_sha256", "answer", "blocks": [[start, end], ...], "model"}
      the model's raw answer, before the ladder touched it (blocks = character spans of its fenced Luau blocks)
  {"kind": "candidate", "source": "ladder", "answer_id", "prompt_sha256", "block", "idx", "origin", "parent",
   "code", "code_sha256", "rungs": [{rung, status, detail?, line?}], "rank": [a, b], "ok", "accepted",
   "fix_seconds", "rung_seconds": {rung: s}}
      one code block version: origin "first" (as the model wrote it), "rewrite" (a self-written rule's rewrite)
      or "fix" (a model fix call); `parent` is the idx it was made from; `accepted` = the ladder kept it as the best
  {"kind": "block_final", "answer_id", "prompt_sha256", "block", "chosen", "ok", "rounds", "stopped", "seconds"}
  {"kind": "candidate", "source": "best_of_n", "prompt_sha256", "idx", "model", "temperature", "answer", "code",
   "checks": [{name, status, detail, hard}], "unit": [passed, counted] | null, "seconds", "chosen"}
Every line also has "schema", "tag" and "t" (UTC time). The true grade of a candidate is not known while STAR runs;
`python -m star.pool_replay grade` adds it afterwards (the task's own checks, run on a rebuilt answer).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any

SCHEMA = 1
ENV_DIR = "STAR_CANDIDATE_POOL"
ENV_TAG = "STAR_CANDIDATE_POOL_TAG"
MAX_TEXT = 200_000                    # one stored answer or code block is cut at this many characters
_PRIVATE = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
_LOCK = threading.Lock()
_WRITTEN: set = set()                 # (pool file, answer id) already written


def pool_dir() -> Path | None:
    value = os.environ.get(ENV_DIR, "").strip()
    return Path(value) if value else None


def active() -> bool:
    return pool_dir() is not None


def tag() -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", os.environ.get(ENV_TAG, "").strip())[:60] or "run"


def pool_path() -> Path | None:
    folder = pool_dir()
    return folder / f"pool-{tag()}.jsonl" if folder else None


def take_flags(args: list[str]) -> list[str]:
    """Remove `--pool DIR` / `--pool-tag NAME` (also `--flag=value`) from a command line, set the environment
    variables they stand for, and return the rest. Used by `python -m star.evals run`."""
    rest, index = [], 0
    names = {"--pool": ENV_DIR, "--pool-tag": ENV_TAG}
    while index < len(args):
        name, eq, value = args[index].partition("=")
        if name in names:
            if not eq:
                index += 1
                if index >= len(args):
                    raise SystemExit(f"{name} needs a value")
                value = args[index]
            os.environ[names[name]] = value
        else:
            rest.append(args[index])
        index += 1
    return rest


def prompt_key(prompt: str) -> str:
    """The same 16 characters the eval result files store as `prompt_sha256`."""
    return hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()[:16]


def text_key(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def _clip(text: str) -> str:
    text = _PRIVATE.sub("<private-address>", str(text))
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT]


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def write(record: dict) -> bool:
    """Append one line to the pool file. False (and nothing written) when the pool is off or the write failed."""
    path = pool_path()
    if path is None:
        return False
    line = {"schema": SCHEMA, "tag": tag(), "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **_clean(record)}
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


# --- recorders called by the answer path -------------------------------------------------------------------------

def record_answer(prompt: str, answer: str, blocks, model: str = "", origin: str = "model") -> str:
    """An answer before the ladder touches it (origin "resample": a fresh one asked for after a failed static
    rung); returns its id ("" when the pool is off). The same answer is written once per pool file."""
    if not active():
        return ""
    answer_id = text_key(prompt + "\0" + answer)
    marker = (str(pool_path()), answer_id)
    with _LOCK:
        if marker in _WRITTEN:
            return answer_id
        _WRITTEN.add(marker)
    write({"kind": "answer", "answer_id": answer_id, "prompt_sha256": prompt_key(prompt), "answer": answer,
           "blocks": [[start, end] for start, end, *_ in blocks], "model": model, "origin": origin})
    return answer_id


def record_ladder_candidate(prompt: str, answer_id: str, block: int, idx: int, origin: str, parent: int | None,
                            code: str, rungs: list[dict], rank, accepted: bool, fix_seconds: float | None = None,
                            rung_seconds: dict | None = None) -> None:
    if not active():
        return
    ok = bool(rungs) and not any(r.get("status") == "fail" for r in rungs)
    write({"kind": "candidate", "source": "ladder", "answer_id": answer_id, "prompt_sha256": prompt_key(prompt),
           "block": block, "idx": idx, "origin": origin, "parent": parent, "code": code, "code_sha256": text_key(code),
           "rungs": rungs, "rank": list(rank), "ok": ok, "accepted": accepted, "fix_seconds": fix_seconds,
           "rung_seconds": rung_seconds or {}})


def record_block_final(prompt: str, answer_id: str, block: int, chosen: int, ok: bool, rounds: int, stopped: str,
                       seconds: dict | None = None) -> None:
    if not active():
        return
    write({"kind": "block_final", "answer_id": answer_id, "prompt_sha256": prompt_key(prompt), "block": block,
           "chosen": chosen, "ok": bool(ok), "rounds": rounds, "stopped": stopped, "seconds": seconds or {}})


def record_best_of_n(prompt: str, outcome) -> None:
    """Every candidate of one best-of-N turn (star.best_of_n.Outcome) with its checks."""
    if not active():
        return
    for c in outcome.candidates:
        write({"kind": "candidate", "source": "best_of_n", "prompt_sha256": prompt_key(prompt), "idx": c.index,
               "model": c.model, "temperature": c.temperature, "answer": c.answer, "code": c.code,
               "answer_id": text_key(prompt + "\0" + c.answer),
               "checks": [{"name": k.name, "status": k.status, "detail": k.detail[:160], "hard": k.hard}
                          for k in c.checks],
               "unit": list(c.unit) if c.unit else None, "seconds": round(c.seconds, 1), "error": c.error[:160],
               "chosen": outcome.chosen is c})


# --- reading ---------------------------------------------------------------------------------------------------

def read_lines(path: Path) -> list[dict]:
    """The records of one pool file; a damaged or foreign line is skipped, a newer schema is refused."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or "kind" not in record:
            continue
        if record.get("schema", 0) > SCHEMA:
            raise ValueError(f"{path}: schema {record['schema']} is newer than this reader ({SCHEMA})")
        out.append(record)
    return out


def rebuild_answer(answer: str, blocks: list, block: int, code: str) -> str:
    """The raw answer with block number `block` (1-based, as in the ladder) replaced by `code`."""
    if not 1 <= block <= len(blocks):
        return answer
    start, end = blocks[block - 1][0], blocks[block - 1][1]
    return answer[:start] + (code if code.endswith("\n") else code + "\n") + answer[end:]
