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
import operator
import re
import sqlite3
import time
import unicodedata
import uuid

MESH_FIELDS = ("conversation_id", "mesh_context", "mesh_cache", "mesh_ground")   # router-only, never forwarded


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


# ---- second stage for the grey zone: intent guard, the live model as judge ---------------------------------------
_DIR_S2C = re.compile(r"\bserver\b[\w ]{0,20}?\b(to|->|into)\b[\w ]{0,12}?\b(client|clients|player|players|"
                      r"local ?scripts?|everyone)\b|\bfireclient\b|\bfireallclients\b|\bonclientevent\b")
_DIR_C2S = re.compile(r"\b(client|local ?scripts?|player|gui|button)\b[\w ]{0,20}?\b(to|->|tell|tells|ask|asks)\b"
                      r"[\w ]{0,12}?\bserver\b|\bfireserver\b|\bonserverevent\b|\binvokeserver\b")
# (name, cues A, cues B): a question with an A cue and a candidate with a B cue (and no A cue) ask different things
INTENT_PAIRS = (
    ("language", re.compile(r"\b(luau|lua)\b"), re.compile(r"\b(csharp|python|javascript|js|java)\b")),
    ("language", re.compile(r"\bpython\b"), re.compile(r"\b(luau|lua|csharp|javascript|js|java)\b")),
    ("language", re.compile(r"\bcsharp\b"), re.compile(r"\b(luau|lua|python|javascript|js)\b")),
    ("edition", re.compile(r"\bbedrock\b"), re.compile(r"\bjava\b")),
    ("dimension", re.compile(r"\b2d\b"), re.compile(r"\b3d\b")),
)


def _cue_text(text: str) -> str:
    return " " + unicodedata.normalize("NFKC", text).lower().replace("c#", "csharp") + " "


def _direction(text: str) -> str:
    return "s2c" if _DIR_S2C.search(text) else ("c2s" if _DIR_C2S.search(text) else "")


def intent_conflict(question: str, entry_question: str) -> str | None:
    """Why a grey-zone candidate asks a different thing than the question (None = no conflict found). Embeddings
    score "server to client" ~0.97 to "client to server"; these cues are cheap and exact."""
    q, e = _cue_text(question), _cue_text(entry_question)
    qd, ed = _direction(q), _direction(e)
    if qd and ed and qd != ed:
        return "direction"
    for name, a, b in INTENT_PAIRS:
        for x, y in ((q, e), (e, q)):
            if a.search(x) and b.search(y) and not a.search(y):
                return name
    return None


JUDGE_SYSTEM = "You match a user's question to a list of questions that already have checked answers. Reply with one digit."


def judge_messages(question: str, candidates: list[str]) -> list[dict]:
    """A one-token multiple-choice prompt for the live model: which candidate asks for exactly the same thing (its
    answer fully answers the user), or 0."""
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(candidates, 1))
    return [{"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"User question: {question}\n\nAnswered questions:\n{listing}\n\nWhich answered "
             "question asks for exactly the same thing, so that its answer fully answers the user (same game or engine, "
             "same feature, same trigger such as touching vs pressing a key, same direction such as client to server vs "
             "server to client)? Reply with its number, or 0 if none is exactly the same."}]


def judge_pick(top_logprobs: list | None, n: int, min_p: float) -> tuple[int, float]:
    """(candidate number 1..n, probability) from the judge's first-token top logprobs, or (0, p) when the judge says
    none, is unsure (best digit below min_p) or answered something else."""
    probs: dict[int, float] = {}
    for t in top_logprobs or []:
        tok = str(t.get("token") or "").strip()
        if tok.isdigit() and int(tok) <= n:
            probs[int(tok)] = probs.get(int(tok), 0.0) + math.exp(float(t.get("logprob", -99)))
    if not probs:
        return 0, 0.0
    k = max(probs, key=probs.get)
    return (k, probs[k]) if probs[k] >= min_p else (0, probs[k])


# ---- grounding on verified answers (no cache hit) -------------------------------------------------------------------
GROUND_HEAD = ("Reference: checked answers to SIMILAR questions (not necessarily this one). Use only what really fits "
               "this question, check names and script places yourself, never copy blindly, do not mention them.")


def ground_question(req: dict, max_q: int = 300) -> str | None:
    """The user's question when this request may get reference answers: the first user turn of a chat (system/page
    context allowed), plain text, no code or error text from the user, no tools."""
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "user":
        return None
    if any(req.get(k) for k in ("tools", "functions", "response_format", "grammar", "json_schema")):
        return None
    roles = [m.get("role") if isinstance(m, dict) else None for m in msgs]
    if any(r not in ("system", "developer", "user") for r in roles) or roles.count("user") != 1:
        return None
    content = msgs[-1].get("content")
    if not isinstance(content, str):
        return None
    q = content.strip()
    if not q or len(q) > max_q or CODE_HINTS.search(q) or q.count("\n") > 3:
        return None
    return q


def grounded_messages(msgs: list[dict], refs: list[dict]) -> list[dict]:
    """The same messages with the reference answers put in front of the user's question (the system prompt and page
    context stay unchanged first, so the backend's cached prompt prefix still matches)."""
    block = "\n\n".join(f"[Q] {r['question']}\n[A] {r['answer'].strip()}" for r in refs)
    last = dict(msgs[-1])
    last["content"] = f"{GROUND_HEAD}\n\n{block}\n\n---\nQuestion: {last['content']}"
    return [*msgs[:-1], last]


# ---- the cache -------------------------------------------------------------------------------------------------------
def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def unit(v) -> list[float]:
    n = math.sqrt(math.fsum(x * x for x in v))
    return [x / n for x in v] if n else [float(x) for x in v]


# dot product of unit vectors = cosine; math.sumprod (3.12+) runs in C, ~10x faster than the generator in cosine()
_dot = getattr(math, "sumprod", None) or (lambda a, b: sum(map(operator.mul, a, b)))


class AnswerCache:
    """Verified answers keyed by normalized question + page context. Context "" = the question names its own
    platform, so it may answer any page; an entry with a context answers only that page."""

    SCHEMA = """CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY, norm TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', question TEXT NOT NULL,
        answer TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', score REAL, emb BLOB,
        created REAL NOT NULL, verified_at REAL NOT NULL, expires REAL NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
        revision TEXT NOT NULL DEFAULT '',
        UNIQUE(norm, context))"""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(self.SCHEMA)
        # Existing databases receive a generation marker before this router accepts requests.
        # Serialize schema discovery + migration with other cache constructors on the same database.
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if "revision" not in {row[1] for row in self.db.execute("PRAGMA table_info(answers)")}:
                    self.db.execute("ALTER TABLE answers ADD COLUMN revision TEXT NOT NULL DEFAULT ''")
        except BaseException:
            self.db.close()
            raise
        # id -> (context, unit vector, question, platform, answer group): the scan in candidates() stays cheap with
        # thousands of entries (it runs on the router's event loop). platform = the platforms the question names, else
        # its page context's (an entry seeded for the Roblox page is a Roblox answer). answer group = hash of the
        # answer: the paraphrases of one item share it, so candidates are items, not phrasings
        self.vectors: dict[int, tuple[str, list[float], str, frozenset, str]] = {}
        self.canon: dict[str, int] = {}       # answer group -> its first entry (the item's canonical question)
        for rid, ctx, emb, q, ans in self.db.execute(
                "SELECT id, context, emb, question, answer FROM answers WHERE emb IS NOT NULL ORDER BY id"):
            self._index(rid, ctx, array.array("f", emb), q, ans)

    @staticmethod
    def entry_platforms(question: str, context: str) -> frozenset:
        return platforms(question) or platforms(context.replace("-", " ").replace("_", " "))

    def _index(self, rid: int, ctx: str, emb, question: str, answer: str):
        group = hashlib.sha1(answer.strip().encode()).hexdigest()[:16]
        old = self.vectors.get(rid)
        self.vectors[rid] = (ctx, unit(emb), question, self.entry_platforms(question, ctx), group)
        if old and old[4] != group:
            self._recanon(old[4])
        if rid < self.canon.get(group, rid + 1):
            self.canon[group] = rid

    def _recanon(self, group: str):
        rest = [r for r, v in self.vectors.items() if v[4] == group]
        if rest:
            self.canon[group] = min(rest)
        else:
            self.canon.pop(group, None)

    @staticmethod
    def _row(r) -> dict | None:
        if r is None:
            return None
        keys = ("id", "norm", "context", "question", "answer", "source", "score", "created", "verified_at",
                "expires", "hits", "revision")
        return dict(zip(keys, r))

    _COLS = "id, norm, context, question, answer, source, score, created, verified_at, expires, hits, revision"

    def get(self, rid: int) -> dict | None:
        return self._row(self.db.execute(f"SELECT {self._COLS} FROM answers WHERE id=?", (rid,)).fetchone())

    def exact(self, question: str, context: str) -> dict | None:
        now = time.time()
        r = self.db.execute(f"SELECT {self._COLS} FROM answers WHERE norm=? AND context IN (?, '') AND expires>? "
                            "ORDER BY context DESC LIMIT 1", (normalize(question), context, now)).fetchone()
        return self._row(r)

    def candidates(self, emb, context: str, question: str | None = None, k: int = 4) -> list[dict]:
        """The k most similar answers (best phrasing per answer group) for this page context and, given the question,
        about the same platform: [{"id", "sim", "group", "question", "canon"}], best first."""
        want = None if question is None else self.entry_platforms(question, context)    # = same_platform()
        emb = unit(emb)
        best: dict[str, tuple[float, int]] = {}
        for rid, (ctx, vec, q, plat, group) in self.vectors.items():
            if ctx in (context, "") and (want is None or plat == want):
                sim = _dot(emb, vec)
                if sim > best.get(group, (-2.0, 0))[0]:
                    best[group] = (sim, rid)
        out = []
        for group, (sim, rid) in sorted(best.items(), key=lambda kv: -kv[1][0])[:k]:
            canon = self.vectors.get(self.canon.get(group, rid), self.vectors[rid])[2]
            out.append({"id": rid, "sim": sim, "group": group, "question": self.vectors[rid][2], "canon": canon})
        return out

    def nearest(self, emb, context: str, question: str | None = None) -> tuple[dict | None, float]:
        """Most similar live entry for this page context (and, given the question, about the same platform)."""
        cands = self.candidates(emb, context, question, k=1)
        if not cands:
            return None, -1.0
        row = self.get(cands[0]["id"])
        if row is None or row["expires"] <= time.time():
            return None, cands[0]["sim"]
        return row, cands[0]["sim"]

    def put(self, question: str, answer: str, context: str, source: str, score, emb, ttl_s: float) -> int:
        now = time.time()
        blob = array.array("f", emb).tobytes() if emb else None
        self.db.execute(
            "INSERT INTO answers (norm, context, question, answer, source, score, emb, created, verified_at, expires, revision)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(norm, context) DO UPDATE SET question=excluded.question,"
            " answer=excluded.answer, source=excluded.source, score=excluded.score, emb=excluded.emb,"
            " verified_at=excluded.verified_at, expires=excluded.expires, revision=excluded.revision",
            (normalize(question), context, question, answer, source, score, blob, now, now, now + ttl_s, uuid.uuid4().hex))
        rid = self.db.execute("SELECT id FROM answers WHERE norm=? AND context=?",
                              (normalize(question), context)).fetchone()[0]
        if emb:
            self._index(rid, context, emb, question, answer)
        return rid

    def hit(self, rid: int):
        self.db.execute("UPDATE answers SET hits = hits + 1 WHERE id=?", (rid,))

    def reverified(self, rid: int):
        self.db.execute("UPDATE answers SET verified_at=?, revision=? WHERE id=?", (time.time(), uuid.uuid4().hex, rid))

    @staticmethod
    def _snapshot_match(snapshot: dict) -> tuple[str, tuple]:
        # Hits may change while a check runs. The revision also rejects A -> B -> A replacements,
        # reused row IDs and accepted rechecks when the wall clock repeats or moves backwards.
        fields = ("id", "norm", "context", "question", "answer", "source", "score", "created", "verified_at", "expires",
                  "revision")
        return " AND ".join(f"{field} IS ?" for field in fields), tuple(snapshot[field] for field in fields)

    def reverified_if_current(self, snapshot: dict) -> bool:
        """Apply a background success only to the row that was checked, in one SQLite statement."""
        where, values = self._snapshot_match(snapshot)
        return self.db.execute(f"UPDATE answers SET verified_at=?, revision=? WHERE {where}",
                               (time.time(), uuid.uuid4().hex, *values)).rowcount > 0

    def delete_if_current(self, snapshot: dict) -> bool:
        """Discard a failed snapshot without removing a replacement's vector/canonical entry."""
        where, values = self._snapshot_match(snapshot)
        if not self.db.execute(f"DELETE FROM answers WHERE {where}", values).rowcount:
            return False
        rid = snapshot["id"]
        gone = self.vectors.pop(rid, None)
        if gone and self.canon.get(gone[4]) == rid:
            self._recanon(gone[4])
        return True

    def delete(self, rid: int) -> bool:
        gone = self.vectors.pop(rid, None)
        if gone and self.canon.get(gone[4]) == rid:          # the next phrasing of that answer becomes canonical
            self._recanon(gone[4])
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
