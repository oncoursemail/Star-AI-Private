"""Instant answers for the mesh router: conversation keys (KV-cache affinity), prefetch debouncing and the verified
answer cache (SQLite + star-embed vectors). Stdlib only; the router (router.py) does all network I/O.

    PYTHONPATH=server python -m mesh.instant seed --router http://<mesh>:8100 --answers <dir>   (seed from the eval)
"""
from __future__ import annotations

import array
import collections
import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata

MESH_FIELDS = ("conversation_id", "mesh_context", "mesh_cache")   # router-only request fields, never forwarded


# ---- conversations ---------------------------------------------------------------------------------------------------
def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):                 # OpenAI content parts: keep the text parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def conversation_key(req: dict, headers: dict) -> str | None:
    """`id:<conversation_id>` (header X-Conversation-Id or body field), else `h:<hash of system + first user turn>`,
    which stays the same for every later turn of that conversation. None when there is no user turn."""
    cid = str(headers.get("x-conversation-id") or req.get("conversation_id") or "").strip()
    if cid:
        return "id:" + cid[:128]
    msgs = req.get("messages")
    if not isinstance(msgs, list):
        return None
    system = [_text(m.get("content")) for m in msgs if isinstance(m, dict) and m.get("role") in ("system", "developer")]
    first = next((_text(m.get("content")) for m in msgs if isinstance(m, dict) and m.get("role") == "user"), None)
    if first is None:
        return None
    return "h:" + hashlib.sha256("\x00".join(system + [first]).encode()).hexdigest()[:20]


class Affinity:
    """conversation key -> name of the backend that served it last (its llama-server keeps that prompt's KV)."""

    def __init__(self, ttl_s: float = 1800.0, max_items: int = 4096):
        self.ttl_s, self.max_items, self.items = ttl_s, max_items, collections.OrderedDict()

    def get(self, key: str | None) -> str | None:
        if not key or key not in self.items:
            return None
        name, at = self.items[key]
        if time.monotonic() - at > self.ttl_s:
            del self.items[key]
            return None
        return name

    def set(self, key: str | None, name: str):
        if not key:
            return
        self.items[key] = (name, time.monotonic())
        self.items.move_to_end(key)
        while len(self.items) > self.max_items:
            self.items.popitem(last=False)

    def __len__(self):
        return len(self.items)


# ---- what may be cached ----------------------------------------------------------------------------------------------
CODE_HINTS = re.compile(
    r"```|\bfunction\s*\(|\blocal\s+\w+\s*=|\bend\)|\bvoid\s+\w+\s*\(|\bpublic\s+class\b|\bdef\s+\w+\(|\bimport\s+\w|"
    r"#include|=>|[{};]\s*$|\berror\b|\berrors\b|\bexception\b|traceback|stack ?trace|attempt to (index|call|perform)|"
    r"\bnil\b|\bline\s+\d+|:\d+:|\bmy (code|script)\b|\bthis (code|script)\b|\bwhy (does|is) (my|this)\b",
    re.I | re.M)


def cache_question(req: dict, max_q: int = 300, max_system: int = 4000) -> tuple[str | None, str]:
    """(question, "") when this request may be answered from / stored in the cache, else (None, reason).
    Only a single self-contained user question qualifies: no history, no tools, no code or error text from the user
    (anything that depends on the user's own code must be answered fresh)."""
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None, "no messages"
    for key in ("tools", "functions", "response_format", "grammar", "json_schema"):
        if req.get(key):
            return None, f"uses {key}"
    if int(req.get("n") or 1) != 1:
        return None, "n > 1"
    users, system_len = [], 0
    for m in msgs:
        role = m.get("role") if isinstance(m, dict) else None
        if role in ("system", "developer"):
            s = _text(m.get("content"))
            system_len += len(s)
            if "```" in s:
                return None, "code in the system prompt"
        elif role == "user":
            if not isinstance(m.get("content"), str) and any(
                    isinstance(p, dict) and p.get("type") != "text" for p in m.get("content") or []):
                return None, "non-text content"
            users.append(_text(m.get("content")))
        else:
            return None, "has history"
    if len(users) != 1:
        return None, "has history" if users else "no user turn"
    if system_len > max_system:
        return None, "long system prompt (page context?)"
    q = users[0].strip()
    if not q or len(q) > max_q:
        return None, "question empty or too long"
    if CODE_HINTS.search(q) or q.count("\n") > 3:
        return None, "question holds code or an error"
    return q, ""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text))


def clean_context(value) -> str:
    return re.sub(r"[^a-z0-9._-]", "", str(value or "").lower())[:40]


PLATFORM_WORDS = {"roblox": "roblox", "luau": "roblox", "robux": "roblox", "localscript": "roblox",
                  "unity": "unity", "csharp": "unity", "monobehaviour": "unity",
                  "minecraft": "minecraft", "datapack": "minecraft", "mcfunction": "minecraft", "spigot": "minecraft",
                  "metallic": "metallic"}


def platforms(text: str) -> frozenset:
    return frozenset(PLATFORM_WORDS[w] for w in normalize(text).split() if w in PLATFORM_WORDS)


def same_platform(question: str, context: str, entry_question: str) -> bool:
    """A semantic hit must be about the same platform: the platforms the question names (else its page context's)
    must equal the entry's. Embeddings score "door in Unity" close to "door in Roblox"; this keeps them apart."""
    return (platforms(question) or platforms(context.replace("-", " ").replace("_", " "))) == platforms(
        entry_question)


# ---- the cache -------------------------------------------------------------------------------------------------------
def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class AnswerCache:
    """Verified answers keyed by normalized question + page context. Context "" = the question names its own
    platform, so it may answer any page; an entry with a context answers only that page."""

    SCHEMA = """CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY, norm TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', question TEXT NOT NULL,
        answer TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', score REAL, emb BLOB,
        created REAL NOT NULL, verified_at REAL NOT NULL, expires REAL NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
        UNIQUE(norm, context))"""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(self.SCHEMA)
        self.vectors: dict[int, tuple[str, list[float], str]] = {}
        for rid, ctx, emb, q in self.db.execute("SELECT id, context, emb, question FROM answers WHERE emb IS NOT NULL"):
            self.vectors[rid] = (ctx, list(array.array("f", emb)), q)

    @staticmethod
    def _row(r) -> dict | None:
        if r is None:
            return None
        keys = ("id", "norm", "context", "question", "answer", "source", "score", "created", "verified_at",
                "expires", "hits")
        return dict(zip(keys, r))

    _COLS = "id, norm, context, question, answer, source, score, created, verified_at, expires, hits"

    def get(self, rid: int) -> dict | None:
        return self._row(self.db.execute(f"SELECT {self._COLS} FROM answers WHERE id=?", (rid,)).fetchone())

    def exact(self, question: str, context: str) -> dict | None:
        now = time.time()
        r = self.db.execute(f"SELECT {self._COLS} FROM answers WHERE norm=? AND context IN (?, '') AND expires>? "
                            "ORDER BY context DESC LIMIT 1", (normalize(question), context, now)).fetchone()
        return self._row(r)

    def nearest(self, emb, context: str, question: str | None = None) -> tuple[dict | None, float]:
        """Most similar live entry for this page context (and, given the question, about the same platform)."""
        best, best_sim = None, -1.0
        for rid, (ctx, vec, q) in self.vectors.items():
            if ctx in (context, "") and (question is None or same_platform(question, context, q)):
                sim = cosine(emb, vec)
                if sim > best_sim:
                    best, best_sim = rid, sim
        row = self.get(best) if best is not None else None
        if row is None or row["expires"] <= time.time():
            return None, best_sim
        return row, best_sim

    def put(self, question: str, answer: str, context: str, source: str, score, emb, ttl_s: float) -> int:
        now = time.time()
        blob = array.array("f", emb).tobytes() if emb else None
        self.db.execute(
            "INSERT INTO answers (norm, context, question, answer, source, score, emb, created, verified_at, expires)"
            " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(norm, context) DO UPDATE SET question=excluded.question,"
            " answer=excluded.answer, source=excluded.source, score=excluded.score, emb=excluded.emb,"
            " verified_at=excluded.verified_at, expires=excluded.expires",
            (normalize(question), context, question, answer, source, score, blob, now, now, now + ttl_s))
        rid = self.db.execute("SELECT id FROM answers WHERE norm=? AND context=?",
                              (normalize(question), context)).fetchone()[0]
        if emb:
            self.vectors[rid] = (context, list(emb), question)
        return rid

    def hit(self, rid: int):
        self.db.execute("UPDATE answers SET hits = hits + 1 WHERE id=?", (rid,))

    def reverified(self, rid: int):
        self.db.execute("UPDATE answers SET verified_at=? WHERE id=?", (time.time(), rid))

    def delete(self, rid: int) -> bool:
        self.vectors.pop(rid, None)
        return self.db.execute("DELETE FROM answers WHERE id=?", (rid,)).rowcount > 0

    def purge_expired(self) -> int:
        gone = [r for (r,) in self.db.execute("SELECT id FROM answers WHERE expires<=?", (time.time(),))]
        for rid in gone:
            self.delete(rid)
        return len(gone)

    def stats(self) -> dict:
        n, hits = self.db.execute("SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM answers").fetchone()
        return {"entries": n, "hits": hits, "with_vectors": len(self.vectors)}

    def listing(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute(f"SELECT {self._COLS} FROM answers ORDER BY hits DESC, id LIMIT ?", (limit,))
        return [{k: v for k, v in self._row(r).items() if k not in ("answer", "norm")} for r in rows]


def sse_from_text(text: str, model: str, piece: int = 48) -> bytes:
    """A complete OpenAI-style SSE stream that carries `text` (sent in one go: the client renders it at once)."""
    rid, now = "chatcmpl-cache-" + hashlib.sha1(text.encode()).hexdigest()[:12], int(time.time())

    def ev(delta, finish=None):
        obj = {"id": rid, "object": "chat.completion.chunk", "created": now, "model": model,
               "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        return b"data: " + json.dumps(obj).encode() + b"\n\n"
    out = [ev({"role": "assistant", "content": ""})]
    out += [ev({"content": text[i:i + piece]}) for i in range(0, len(text), piece)]
    out += [ev({}, "stop"), b"data: [DONE]\n\n"]
    return b"".join(out)


def completion_from_text(text: str, model: str) -> dict:
    return {"id": "chatcmpl-cache-" + hashlib.sha1(text.encode()).hexdigest()[:12], "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


# ---- seeding from the Litha eval -------------------------------------------------------------------------------------
SEED_SKIP_AREAS = ("safety",)          # refusals are not reusable answers; bug questions carry the user's code


def seed_entries(questions_path: str, answers_dir: str, sets=("pc-gemma12", "brain1-starfast")) -> list[dict]:
    """Full-mark (3/3) eval answers, one per question (first set in `sets` order), self-contained questions only."""
    from pathlib import Path
    qs = json.loads(Path(questions_path).read_text(encoding="utf-8"))["questions"]
    scores = json.loads(Path(answers_dir, "scores.json").read_text(encoding="utf-8"))["scores"]
    answers = {}
    for s in sets:
        for line in Path(answers_dir, f"{s}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = json.loads(line)
                answers[(s, a["id"])] = a.get("content") or ""
    out = []
    for q in qs:
        if q["area"] in SEED_SKIP_AREAS:
            continue
        question, why = cache_question({"messages": [{"role": "user", "content": q["prompt"]}]})
        if question is None:
            continue
        for s in sets:
            if scores.get(q["id"], {}).get(s) == 3 and answers.get((s, q["id"]), "").strip():
                out.append({"question": question, "answer": answers[(s, q["id"])], "context": "",
                            "source": f"eval-20261027:{s}:{q['id']}", "score": 3, "max_score": 3})
                break
    return out


def _main(argv: list[str]) -> int:
    import argparse
    import urllib.error
    import urllib.request
    from pathlib import Path
    ap = argparse.ArgumentParser(prog="python -m mesh.instant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("seed", help="add full-mark eval answers to the live cache (router verifies + embeds)")
    sp.add_argument("--router", required=True)
    sp.add_argument("--answers", required=True, help="docs/agents/litha-eval/answers-<date>")
    sp.add_argument("--questions", default="")
    sp.add_argument("--token-file", default=str(Path.home() / ".star" / "mesh_token"))
    sp.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    questions = a.questions or str(Path(a.answers).parent / "questions.json")
    entries = seed_entries(questions, a.answers)
    token = Path(a.token_file).read_text(encoding="utf-8").strip().splitlines()[0].strip()
    for e in entries:
        if a.dry_run:
            print("would add", e["source"])
            continue
        req = urllib.request.Request(a.router.rstrip("/") + "/mesh/cache", json.dumps(e).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(r.status, e["source"], json.loads(r.read()).get("id"))
        except urllib.error.HTTPError as err:
            print(err.code, e["source"], err.read().decode()[:200])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
