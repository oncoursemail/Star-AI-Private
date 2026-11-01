"""Query side of the docs index (the SQLite file from build.py). Stdlib only.

    idx = DocsIndex("docs.db")
    idx.entry("Humanoid:LoadAnimation")       -> row (exact; members are found along the superclass chain)
    idx.names_in(text)                        -> API names written in a question, draft or code (exact matches only)
    idx.search(q, k, vec=None)                -> guide passages (BM25, + embeddings when a query vector is given)
    idx.block(question, history_text, vec)    -> {"text": compact "Docs" block or "", "entries", "passages", ...}

The block is for Roblox/Luau questions only (never chit-chat, Unity, Minecraft or safety questions), and has a hard
budget (default ~500 tokens, counted as chars / 3.6).
"""
from __future__ import annotations

import array
import json
import math
import operator
import re
import sqlite3
import threading
import time

CHARS_PER_TOKEN = 3.6
_dot = getattr(math, "sumprod", None) or (lambda a, b: sum(map(operator.mul, a, b)))

STOP = set("""a an and are as at be but by can could do does doing done for from get gets getting got have how i if in
into is it its it's like make makes making me my of on or so that the then there this to u up use using want was way
we what when where which who why will with without would you your im pls please help need know just also any some
all one more than them they their our out about after before over only very really thing things sure way much many
should something someone every everyone each other another new old let lets say says said give gives gets tell""".split())
ROBLOX_WORDS = set("""roblox luau lua studio robux obby script scripts localscript localscripts modulescript part parts
brick bricks humanoid leaderstats leaderboard datastore datastores remoteevent remotefunction remote remotes tween
tweens tweenservice gui screengui billboardgui surfacegui textbutton textlabel frame workspace serverscriptservice
replicatedstorage starterplayer startergui starterpack character npc proximityprompt clickdetector animation animator
raycast cframe vector3 touched spawnlocation teleport badge gamepass devproduct marketplaceservice playeradded
anchored cancollide attachment constraint hinge sound particle beam trail lighting terrain module server client
filteringenabled pcall coroutine task leaderstat checkpoint killbrick lava sword tool backpack""".split())
OTHER_PLATFORM = re.compile(r"\b(unity|c#|csharp|monobehaviour|unreal|godot|gdscript|minecraft|datapack|data pack|"
                            r"command block|mcfunction|spigot|bukkit|paper plugin|forge mod|fabric mod|metallic rc)\b",
                            re.I)
SKIP = re.compile(r"\b(password|log ?in(to)? my|free robux|executor|exploit|exploit scripts?|roast|mean (joke|roast|"
                  r"message))\b", re.I)
CODEY = re.compile(r"```|\b(script|code|function|error|attempt to|nil|local|end)\b", re.I)
IDENT = re.compile(r"\b(Enum\.[A-Za-z]\w*(?:\.[A-Za-z]\w*)?|[A-Za-z_]\w*(?:\s*[.:]\s*[A-Za-z_]\w*)*)(\s*\()?")
GETSERVICE = re.compile(r"""GetService\(\s*["']([A-Za-z]+)["']\s*\)""")
WORD = re.compile(r"[a-z0-9]+")
SECTION_HINT = {"remote": "remote", "datastore": "data store", "tween": "tween", "leaderstats": "leaderboard"}


def stem(w: str) -> str:
    for suf in ("ing", "es", "ed", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def content_words(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text.lower()):
        if w not in STOP and len(w) > 1 and not w.isdigit() and w not in out:
            out.append(w)
    return out


class DocsIndex:
    def __init__(self, path: str, load_vectors: bool = True):
        self.path = path
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.lock = threading.Lock()               # one connection, used by the service's request threads
        self.meta = json.loads(self.db.execute("SELECT value FROM meta WHERE key='meta'").fetchone()[0])
        cols = ("id", "name", "key", "kind", "owner", "member", "sig", "summary", "deprecated", "depmsg", "security",
                "tags", "url", "sample")
        self.rows: dict[int, dict] = {}
        self.by_key: dict[str, list[int]] = {}
        self.classes: dict[str, int] = {}          # class/datatype/library/enum name -> row id
        self.lower_types: dict[str, str] = {}      # humanoid -> Humanoid (for receivers written in lower case)
        for r in self.db.execute(f"SELECT {', '.join(cols)} FROM api"):
            row = dict(zip(cols, r))
            self.rows[row["id"]] = row
            self.by_key.setdefault(row["key"], []).append(row["id"])
            if row["kind"] in ("class", "datatype", "library", "enum"):
                self.classes[row["name"]] = row["id"]
                if row["kind"] in ("class", "datatype"):
                    self.lower_types.setdefault(row["name"].lower(), row["name"])
        self.supers = dict(self.db.execute("SELECT cls, super FROM supers"))
        self.vectors: list[tuple[int, array.array]] = []
        if load_vectors:
            for pid, blob in self.db.execute("SELECT id, emb FROM passages WHERE emb IS NOT NULL"):
                v = array.array("f")
                v.frombytes(blob)
                self.vectors.append((pid, v))

    # ---- exact lookup ------------------------------------------------------------------------------------------------
    def chain(self, cls: str) -> list[str]:
        out = []
        while cls and cls not in out:
            out.append(cls)
            cls = self.supers.get(cls)
        return out

    def _pick(self, ids: list[int], name: str) -> dict | None:
        rows = [self.rows[i] for i in ids]
        exact = [r for r in rows if r["name"].replace(":", ".") == name.replace(":", ".")]
        rows = exact or rows
        rows.sort(key=lambda r: (r["deprecated"], r["kind"] == "callback"))
        return rows[0] if rows else None

    def entry(self, name: str) -> dict | None:
        """Exact entry for Class.Member / Class:Method / Enum.X(.Y) / task.wait / Vector3.new / wait / a type name."""
        name = re.sub(r"\s+", "", name or "").rstrip("()")
        if not name:
            return None
        key = name.replace(":", ".").lower()
        ids = self.by_key.get(key)
        if ids:
            return self._pick(ids, name)
        owner, _, member = name.replace(":", ".").rpartition(".")
        if owner and member:
            owner = self.lower_types.get(owner.lower(), owner)
            for c in self.chain(owner)[1:]:          # inherited members (Part.Touched -> BasePart.Touched)
                ids = self.by_key.get(f"{c}.{member}".lower())
                if ids:
                    return self._pick(ids, f"{c}.{member}")
        return None

    def names_in(self, text: str, limit: int = 12) -> list[str]:
        """API names written in the text (question, draft or code), in order, each resolved to its exact entry."""
        found: list[str] = []

        def add(row):
            if row and row["name"] not in found:
                found.append(row["name"])
        for m in GETSERVICE.finditer(text):
            add(self.entry(m.group(1)) if m.group(1) in self.classes else None)
        for m in IDENT.finditer(text):
            tok, call = re.sub(r"\s+", "", m.group(1)), bool(m.group(2))
            if "." in tok or ":" in tok:
                parts = re.split(r"([.:])", tok)
                # try the longest dotted suffix pairs: a.b.c:d -> c:d, b.c, Enum.X.Y as a whole
                if tok.startswith("Enum."):
                    add(self.entry(tok) or self.entry(".".join(tok.split(".")[:2])))
                    continue
                for k in range(len(parts) - 2, 0, -2):
                    owner, sep, member = parts[k - 1], parts[k], parts[k + 1]
                    row = self.entry(f"{owner}{sep}{member}")
                    if row:
                        add(row)
                        break
                    if owner in ("game", "workspace") and member in self.classes:
                        add(self.entry(member))
                        break
                continue
            if tok in self.classes and tok[0].isupper() and len(tok) >= 4 and (
                    re.search(r"[a-z][A-Z]", tok) or in_code(text, m.start(1))):
                add(self.entry(tok))     # CamelCase type names; "Model", "Sound", "Studio" only inside code
            elif call and tok in ("wait", "spawn", "delay", "tick", "elapsedTime", "require", "pcall", "typeof"):
                add(self.entry(tok))
            if len(found) >= limit:
                break
        return found[:limit]

    # ---- search ------------------------------------------------------------------------------------------------------
    def bm25(self, q: str, k: int = 8) -> list[tuple[int, float]]:
        words = content_words(q)
        if not words:
            return []
        expr = " OR ".join(f'"{w}"' for w in words[:24])
        try:
            with self.lock:
                rows = self.db.execute("SELECT rowid, bm25(passages_fts, 3.0, 4.0, 1.0) FROM passages_fts WHERE "
                                       "passages_fts MATCH ? ORDER BY 2 LIMIT ?", (expr, k)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(r[0], -r[1]) for r in rows]

    def dense(self, vec, k: int = 8) -> list[tuple[int, float]]:
        if not self.vectors or not vec:
            return []
        n = math.sqrt(math.fsum(x * x for x in vec)) or 1.0
        q = array.array("f", (x / n for x in vec))
        scored = [(pid, _dot(q, v)) for pid, v in self.vectors]
        scored.sort(key=lambda t: -t[1])
        return scored[:k]

    def passage(self, pid: int) -> dict:
        with self.lock:
            r = self.db.execute("SELECT id, source, title, heading, url, body FROM passages WHERE id=?",
                                (pid,)).fetchone()
        return dict(zip(("id", "source", "title", "heading", "url", "body"), r))

    def search(self, q: str, k: int = 5, vec=None, rrf_k: int = 60) -> list[dict]:
        """Top passages: BM25, fused with embedding similarity (reciprocal rank fusion) when `vec` is given."""
        lex = self.bm25(q, 30)
        den = self.dense(vec, 30) if vec else []
        score: dict[int, float] = {}
        for rank, (pid, _) in enumerate(lex):
            score[pid] = score.get(pid, 0.0) + 1.0 / (rrf_k + rank)
        for rank, (pid, _) in enumerate(den):
            score[pid] = score.get(pid, 0.0) + 1.0 / (rrf_k + rank)
        lex_s, den_s = dict(lex), dict(den)
        out, seen = [], set()
        for pid in sorted(score, key=lambda p: -score[p]):
            p = self.passage(pid)
            sig = (p["url"], p["heading"], p["body"][:120])
            if sig in seen:                        # the same section published twice (e.g. a shared include)
                continue
            seen.add(sig)
            p.update(rrf=round(score[pid], 5), bm25=round(lex_s.get(pid, 0.0), 3),
                     cos=round(den_s[pid], 4) if pid in den_s else None, coverage=round(coverage(q, p), 2))
            out.append(p)
            if len(out) >= k:
                break
        return out

    # ---- the block for the model ------------------------------------------------------------------------------------
    def wants_docs(self, question: str, context: str = "") -> str:
        """'' when the request gets no docs, else why it does ('names', 'roblox')."""
        if SKIP.search(question):
            return ""
        names = self.names_in(question, 3)
        if OTHER_PLATFORM.search(question) and not names:
            return ""
        if names:
            return "names"
        words = set(WORD.findall(question.lower()))
        if words & ROBLOX_WORDS or ("roblox" in context.lower() and CODEY.search(question)):
            return "roblox"
        return ""

    def block(self, question: str, extra: str = "", vec=None, context: str = "", budget_tokens: int = 500,
              max_passages: int = 1, min_coverage: float = 0.75) -> dict:
        """Compact docs for one request: exact entries for the API names in the question (+ `extra`: earlier turns or
        a draft), entries for the APIs the best guide passage uses, and that passage when it covers the question."""
        t0 = time.perf_counter()
        why = self.wants_docs(question, context)
        if not why:
            return {"text": "", "why": "", "entries": [], "passages": [], "tokens": 0,
                    "ms": round((time.perf_counter() - t0) * 1e3, 1)}
        names = self.names_in(question + "\n" + extra)
        hits = self.search(question, 3, vec)
        good = [p for p in hits if p["coverage"] >= min_coverage][:max_passages]
        # APIs the shown passage names (exact only): what the guide would have the model use
        for p in good:
            for n in self.names_in(p["body"], 6):
                row = self.entry(n)
                if row and row["kind"] in ("method", "event", "property", "function", "constructor", "callback") \
                        and n not in names and len(names) < 8:
                    names.append(n)
        budget = int(budget_tokens * CHARS_PER_TOKEN)
        lines = [f"Docs (official Roblox Creator Docs, {self.meta.get('creator_docs', {}).get('date', '')[:10]}; "
                 "exact signatures, use them, ignore what does not fit):"]
        used, entries = len(lines[0]), []
        for n in names:
            row = self.entry(n)
            if not row:
                continue
            line = "- " + format_entry(row)
            if used + len(line) + 1 > budget * 0.7 and entries:
                break
            lines.append(line)
            used += len(line) + 1
            entries.append(row["name"])
        passages = []
        for p in good:
            room = budget - used - 40
            if room < 200:
                break
            body = shorten(p["body"], min(room, 900))
            head = f"Guide: {p['title']}" + (f" / {p['heading']}" if p["heading"] else "")
            lines.append(f"{head}\n{body}")
            used += len(head) + len(body) + 2
            passages.append({k: p[k] for k in ("id", "title", "heading", "url", "coverage", "bm25", "cos")})
        text = "\n".join(lines) if (entries or passages) else ""
        return {"text": text, "why": why, "entries": entries, "passages": passages,
                "tokens": round(len(text) / CHARS_PER_TOKEN), "ms": round((time.perf_counter() - t0) * 1e3, 1)}

    def entries_text(self, names, limit_chars: int = 1400) -> str:
        """Exact entries for a list of names (the verifier's fix loop): unknown names are skipped."""
        out, used = [], 0
        for n in names:
            row = self.entry(n)
            if not row:
                continue
            line = "- " + format_entry(row, with_sample=True)
            if used + len(line) > limit_chars and out:
                break
            if line not in out:
                out.append(line)
                used += len(line)
        return "\n".join(out)


def in_code(text: str, pos: int) -> bool:
    """Inside a fenced or inline code span."""
    if text.count("```", 0, pos) % 2:
        return True
    line_start = text.rfind("\n", 0, pos) + 1
    return text.count("`", line_start, pos) % 2 == 1


def coverage(q: str, p: dict) -> float:
    words = [stem(w) for w in content_words(q) if w not in ("roblox", "studio", "script", "game")]
    if not words:
        return 0.0
    hay = {stem(w) for w in WORD.findall((p["title"] + " " + p["heading"] + " " + p["body"]).lower())}
    return sum(w in hay for w in words) / len(words)


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if cut.count("```") % 2:                       # never leave a code fence open
        cut = cut[:cut.rfind("```")].rstrip()
    return cut.rsplit("\n", 1)[0].rstrip() + " ..." if "\n" in cut else cut.rsplit(" ", 1)[0] + " ..."


def format_entry(row: dict, with_sample: bool = False) -> str:
    s = row["sig"]
    if row["summary"]:
        s += f": {row['summary']}"
    if row["deprecated"]:
        s += f" DEPRECATED{(': ' + row['depmsg']) if row['depmsg'] else ''}"
    if row.get("security") and row["security"] not in ("None", ""):
        s += f" [security: {row['security']}]"
    if with_sample and row.get("sample"):
        s += f"\n  example:\n```lua\n{row['sample']}\n```"
    return s
