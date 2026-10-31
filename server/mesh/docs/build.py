"""Build the docs index (one SQLite file) from local checkouts of the official docs. Runs on a PC; the index is then
copied to the docs service (server/mesh/docs/deploy.sh). PyYAML is needed here only, never by the service.

    python -m mesh.docs.build index --creator <creator-docs checkout> --luau <luau-lang/site checkout> --out docs.db
    python -m mesh.docs.build embed --db docs.db --url <brain or router base> --key-file <file> [--max-minutes 8]

Sources (licenses checked 2026-10-28):
  Roblox/creator-docs  prose CC-BY-4.0 (LICENSE), code samples MIT (LICENSE-CODE): content/en-us/**/*.md and the
                       engine API reference YAML (content/en-us/reference/engine/{classes,datatypes,enums,globals,
                       libraries}).
  luau-lang/site       MIT (LICENSE.md): src/content/docs/**/*.md (news posts are skipped).
Every row keeps its source URL; meta holds each checkout's commit, commit date and the build date (attribution).

`embed` fills passages.emb (unit vectors, float32) through an OpenAI-compatible /v1/embeddings (star-embed), in
batches, resumable, and stops after --max-minutes so it fits a short `star lock run` window.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CREATOR_URL = "https://create.roblox.com/docs/"
LUAU_URL = "https://luau.org/"
# guide folders that are not about making games (programs, legal, store listings)
SKIP_DIRS = {"creator-programs", "ip-licensing", "marketplace", "assistant", "includes"}
KIND = {"properties": "property", "methods": "method", "events": "event", "callbacks": "callback",
        "functions": "function", "constructors": "constructor", "constants": "constant"}
PASSAGE_WORDS = 170
EMBED_DOC_PREFIX = "title: {title} | text: "
EMBED_CHARS = 400          # what is embedded per passage (the head of it): keeps the brain job short

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE api(id INTEGER PRIMARY KEY, name TEXT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL, owner TEXT,
                 member TEXT, sig TEXT NOT NULL, summary TEXT, deprecated INTEGER DEFAULT 0, depmsg TEXT,
                 security TEXT, tags TEXT, url TEXT, sample TEXT);
CREATE INDEX api_key ON api(key);
CREATE INDEX api_member ON api(member);
CREATE TABLE supers(cls TEXT PRIMARY KEY, super TEXT);
CREATE TABLE passages(id INTEGER PRIMARY KEY, source TEXT, title TEXT, heading TEXT, url TEXT, body TEXT,
                      emb BLOB);
CREATE VIRTUAL TABLE passages_fts USING fts5(title, heading, body, content='passages', content_rowid='id',
                                             tokenize='porter unicode61');
CREATE VIRTUAL TABLE api_fts USING fts5(words, summary, content='', tokenize='porter unicode61');
"""


# ---- text cleaning ---------------------------------------------------------------------------------------------------
REF = re.compile(r"`(?:Class|Datatype|Enum|Library|Global)\.([^`|]+?)(?:\|([^`]+))?`")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
TAG = re.compile(r"</?[A-Za-z][^>\n]*>")


def clean(text: str) -> str:
    """Docs markdown -> plain text: `Class.Tween|Tweens` -> Tweens, `Class.X:Y()` -> X:Y(), links -> their text."""
    if not text:
        return ""

    def ref(m):
        target, label = m.group(1), m.group(2)
        if label:
            return label
        if m.group(0).startswith("`Global."):        # Global.LuaGlobals.print() -> print()
            target = target.split(".", 1)[-1]
        if m.group(0).startswith("`Enum."):
            target = "Enum." + target
        return target
    text = REF.sub(ref, text)
    text = LINK.sub(lambda m: m.group(1), text)
    text = TAG.sub("", text)
    return text.strip()


def one_line(text: str, limit: int = 220) -> str:
    t = re.sub(r"\s+", " ", clean(text)).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    dot = cut.rfind(". ")
    return (cut[:dot + 1] if dot > 80 else cut.rsplit(" ", 1)[0] + "...")


def camel_words(name: str) -> str:
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", name)
    return " ".join(p.lower() for p in parts)


FENCE_LUA = re.compile(r"```(?:lua|luau)[^\n]*\n(.*?)```", re.S)


def first_sample(text: str, limit: int = 700) -> str:
    m = FENCE_LUA.search(text or "")
    if not m:
        return ""
    code = m.group(1).strip()
    return code if len(code) <= limit else ""


def deprecated(item: dict) -> tuple[int, str]:
    tags = [t for t in item.get("tags") or [] if isinstance(t, str)]
    msg = one_line(item.get("deprecation_message") or "", 240)
    return int("Deprecated" in tags or bool(msg)), msg


def params_sig(params) -> str:
    out = []
    for p in params or []:
        n, t = p.get("name") or "", p.get("type") or ""
        d = p.get("default")
        s = f"{n}: {t}" if t else n
        if d not in (None, ""):
            s += f" = {d}"
        out.append(s)
    return ", ".join(out)


def returns_sig(rets) -> str:
    types = [r.get("type") for r in rets or [] if r.get("type") and r.get("type") != "()"]
    return f": {', '.join(types)}" if types else ""


# ---- engine reference --------------------------------------------------------------------------------------------
def api_rows(doc: dict, url: str) -> list[dict]:
    """One reference YAML file -> rows: the type itself and each member."""
    rows = []
    typ, name = doc.get("type"), doc.get("name") or ""
    dep, depmsg = deprecated(doc)
    tags = [t for t in doc.get("tags") or [] if isinstance(t, str)]
    if typ == "class":
        inh = doc.get("inherits") or []
        sig = f"class {name}" + (f" : {inh[0]}" if inh else "") + (f" [{', '.join(tags)}]" if tags else "")
        rows.append(dict(name=name, kind="class", owner=None, member=None, sig=sig, summary=one_line(doc.get("summary")),
                         deprecated=dep, depmsg=depmsg, tags=",".join(tags), url=url,
                         sample=first_sample(doc.get("description"))))
    elif typ == "datatype":
        rows.append(dict(name=name, kind="datatype", owner=None, member=None, sig=f"datatype {name}",
                         summary=one_line(doc.get("summary")), deprecated=dep, depmsg=depmsg, tags="", url=url,
                         sample=first_sample(doc.get("description"))))
    elif typ == "library":
        rows.append(dict(name=name, kind="library", owner=None, member=None, sig=f"library {name}",
                         summary=one_line(doc.get("summary")), deprecated=dep, depmsg=depmsg, tags="", url=url,
                         sample=""))
    elif typ == "enum":
        items = doc.get("items") or []
        live = [i["name"] for i in items if not deprecated(i)[0]]
        sig = f"Enum.{name} {{{', '.join(live[:14])}{', ...' if len(live) > 14 else ''}}}"
        rows.append(dict(name=f"Enum.{name}", kind="enum", owner=None, member=None, sig=sig,
                         summary=one_line(doc.get("summary")), deprecated=dep, depmsg=depmsg, tags="", url=url,
                         sample=""))
        for it in items:
            idep, imsg = deprecated(it)
            rows.append(dict(name=f"Enum.{name}.{it['name']}", kind="enumitem", owner=f"Enum.{name}",
                             member=it["name"], sig=f"Enum.{name}.{it['name']} = {it.get('value')}",
                             summary=one_line(it.get("summary"), 160), deprecated=idep, depmsg=imsg, tags="",
                             url=url, sample=""))
        return rows
    for section, kind in KIND.items():
        for m in doc.get(section) or []:
            full = m.get("name") or ""
            if not full:
                continue
            if typ == "global":          # globals are bare names (wait, print)
                owner, member, full = None, full, full
            else:
                member = re.split(r"[.:]", full)[-1]
                owner = name
            mdep, mmsg = deprecated(m)
            mtags = [t for t in m.get("tags") or [] if isinstance(t, str)]
            if kind in ("method", "function", "constructor"):
                sig = f"{full}({params_sig(m.get('parameters'))}){returns_sig(m.get('returns'))}"
            elif kind == "event":
                sig = f"{full}({params_sig(m.get('parameters'))}) [event]"
            elif kind == "callback":
                sig = f"{full} = function({params_sig(m.get('parameters'))}){returns_sig(m.get('returns'))} [callback]"
            else:
                t = (m.get("type") or "").strip()
                sig = f"{full}: {t}" if t else full
                if "ReadOnly" in mtags:
                    sig += " [read-only]"
            sec = m.get("security")
            if isinstance(sec, dict):
                sec = sec.get("read") or sec.get("Read") or ""
            rows.append(dict(name=full, kind=kind, owner=owner, member=member, sig=sig,
                             summary=one_line(m.get("summary") or m.get("description")), deprecated=mdep,
                             depmsg=mmsg, security=sec if sec not in ("None", None) else "",
                             tags=",".join(mtags), url=url + "#" + member, sample=first_sample(m.get("description"))))
    return rows


def norm_key(name: str) -> str:
    return name.replace(":", ".").lower()


# ---- guides ----------------------------------------------------------------------------------------------------------
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
HEAD = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)


def split_passages(text: str, words: int = PASSAGE_WORDS) -> list[tuple[str, str]]:
    """(heading, body) chunks of about `words` words; a code block is never cut in half."""
    out = []
    pos, heading = 0, ""
    marks = [(m.start(), m.end(), m.group(2)) for m in HEAD.finditer(text)]
    # headings inside code fences are not headings
    fences = [(m.start(), m.end()) for m in re.finditer(r"```.*?```", text, re.S)]
    marks = [mk for mk in marks if not any(a <= mk[0] < b for a, b in fences)]
    sections = []
    for s, e, h in marks:
        sections.append((heading, text[pos:s]))
        heading, pos = h, e
    sections.append((heading, text[pos:]))
    for h, body in sections:
        body = body.strip()
        if not body:
            continue
        pieces = re.split(r"(```.*?```)", body, flags=re.S)
        cur, n = [], 0
        for piece in pieces:
            if not piece.strip():
                continue
            units = [piece] if piece.startswith("```") else [p for p in re.split(r"\n\s*\n", piece) if p.strip()]
            for u in units:
                w = len(u.split())
                if cur and n + w > words:
                    out.append((h, "\n\n".join(cur)))
                    cur, n = [], 0
                cur.append(u.strip())
                n += w
        if cur:
            out.append((h, "\n\n".join(cur)))
    return out


def guide_docs(root: Path, base_url: str, source: str, skip=frozenset()) -> list[dict]:
    rows = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        if rel.split("/")[0] in skip or rel.startswith("reference/engine/"):
            continue
        raw = f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        title = rel.rsplit("/", 1)[-1][:-3]
        m = FRONT.match(raw)
        if m:
            t = re.search(r"^title:\s*(.+)$", m.group(1), re.M)
            if t:
                title = t.group(1).strip().strip("'\"")
            raw = raw[m.end():]
        url = base_url + re.sub(r"(/index)?\.md$", "", rel)
        for heading, body in split_passages(clean(raw)):
            if len(body.split()) < 12:
                continue
            rows.append(dict(source=source, title=title, heading=clean(heading), url=url, body=body))
    return rows


def git_meta(path: Path) -> dict:
    try:
        out = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%H %cI"], capture_output=True,
                             text=True, timeout=20).stdout.split()
        return {"commit": out[0], "date": out[1]}
    except (OSError, IndexError, subprocess.SubprocessError):
        return {}


def build(creator: Path, luau: Path | None, out: Path, load=None) -> dict:
    """`load(text) -> dict` parses one reference file (default PyYAML, needed at build time only)."""
    if load is None:
        import yaml
        load = yaml.safe_load
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    ref = creator / "content" / "en-us" / "reference" / "engine"
    rows, supers, api_passages = [], {}, []
    for sub in ("classes", "datatypes", "enums", "globals", "libraries"):
        for f in sorted((ref / sub).glob("*.yaml")):
            doc = load(f.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not doc.get("name"):
                continue
            url = f"{CREATOR_URL}reference/engine/{sub}/{f.stem}"
            rows.extend(api_rows(doc, url))
            if doc.get("type") == "class":
                inh = doc.get("inherits") or []
                supers[doc["name"]] = inh[0] if inh else None
            desc = clean(doc.get("description") or "")
            if doc.get("type") in ("class", "datatype", "library") and len(desc.split()) > 25:
                label = doc["name"] if doc.get("type") != "enum" else "Enum." + doc["name"]
                for heading, body in split_passages(desc):
                    api_passages.append(dict(source="creator-docs-api", title=f"{label} ({doc['type']})",
                                             heading=heading, url=url, body=body))
    for r in rows:
        r.setdefault("security", "")
        cur = db.execute("INSERT INTO api(name, key, kind, owner, member, sig, summary, deprecated, depmsg, security,"
                         " tags, url, sample) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (r["name"], norm_key(r["name"]), r["kind"], r["owner"], r["member"], r["sig"], r["summary"],
                          r["deprecated"], r["depmsg"], r["security"], r["tags"], r["url"], r["sample"]))
        words = camel_words(r["member"] or r["name"].split(".")[-1]) + " " + camel_words(r["owner"] or "")
        db.execute("INSERT INTO api_fts(rowid, words, summary) VALUES (?,?,?)", (cur.lastrowid, words, r["summary"]))
    db.executemany("INSERT INTO supers VALUES (?,?)", supers.items())
    guides = guide_docs(creator / "content" / "en-us", CREATOR_URL, "creator-docs", SKIP_DIRS)
    if luau is not None:
        guides += guide_docs(luau / "src" / "content" / "docs", LUAU_URL, "luau-docs")
    for p in guides + api_passages:
        cur = db.execute("INSERT INTO passages(source, title, heading, url, body) VALUES (?,?,?,?,?)",
                         (p["source"], p["title"], p["heading"], p["url"], p["body"]))
        db.execute("INSERT INTO passages_fts(rowid, title, heading, body) VALUES (?,?,?,?)",
                   (cur.lastrowid, p["title"], p["heading"], p["body"]))
    meta = {"built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "creator_docs": {"repo": "https://github.com/Roblox/creator-docs", **git_meta(creator),
                             "license": "CC-BY-4.0 (prose), MIT (code samples)"},
            "api_rows": len(rows), "classes": len(supers), "passages": len(guides) + len(api_passages)}
    if luau is not None:
        meta["luau_docs"] = {"repo": "https://github.com/luau-lang/site", **git_meta(luau), "license": "MIT"}
    db.execute("INSERT INTO meta VALUES ('meta', ?)", (json.dumps(meta),))
    db.commit()
    db.execute("INSERT INTO passages_fts(passages_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    return meta


# ---- embeddings ------------------------------------------------------------------------------------------------------
def unit_blob(vec) -> bytes:
    n = math.sqrt(math.fsum(x * x for x in vec)) or 1.0
    return array.array("f", (x / n for x in vec)).tobytes()


def embed_text(title: str, heading: str, body: str) -> str:
    head = f"{title} - {heading}" if heading else title
    return EMBED_DOC_PREFIX.format(title=head.replace("|", " ")) + body[:EMBED_CHARS]


def embed(db_path: Path, url: str, key: str, model: str = "star-embed", batch: int = 32,
          max_minutes: float = 8.0, sections: tuple[str, ...] | None = None) -> dict:
    """sections: URL prefixes after the docs base (e.g. "scripting", "reference", "luau-docs" for the Luau site);
    rows are embedded in that order (most useful first), None = everything."""
    db = sqlite3.connect(db_path)
    t0, done = time.monotonic(), 0
    likes = [f"{LUAU_URL}%" if s == "luau-docs" else f"{CREATOR_URL}{s}/%" for s in sections or ()]
    where = "emb IS NULL" + (f" AND ({' OR '.join('url LIKE ?' for _ in likes)})" if likes else "")
    order = "CASE " + " ".join(f"WHEN url LIKE ? THEN {k}" for k in range(len(likes))) + " END, id" if likes else "id"
    while time.monotonic() - t0 < max_minutes * 60:
        todo = db.execute(f"SELECT id, title, heading, body FROM passages WHERE {where} ORDER BY {order} LIMIT ?",
                          (*likes, *likes, batch)).fetchall()
        if not todo:
            break
        body = json.dumps({"model": model, "input": [embed_text(t, h, b) for _, t, h, b in todo]}).encode()
        req = urllib.request.Request(url.rstrip("/") + "/v1/embeddings", body,
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())["data"]
        data.sort(key=lambda d: d.get("index", 0))
        db.executemany("UPDATE passages SET emb=? WHERE id=?",
                       [(unit_blob(d["embedding"]), row[0]) for d, row in zip(data, todo)])
        db.commit()
        done += len(todo)
    left = db.execute(f"SELECT COUNT(*) FROM passages WHERE {where}", likes).fetchone()[0]
    db.close()
    return {"embedded": done, "left": left, "s": round(time.monotonic() - t0, 1)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m mesh.docs.build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("index")
    a.add_argument("--creator", required=True, type=Path)
    a.add_argument("--luau", type=Path)
    a.add_argument("--out", required=True, type=Path)
    e = sub.add_parser("embed")
    e.add_argument("--db", required=True, type=Path)
    e.add_argument("--url", required=True)
    e.add_argument("--key-file", required=True, type=Path)
    e.add_argument("--model", default="star-embed")
    e.add_argument("--batch", type=int, default=32)
    e.add_argument("--max-minutes", type=float, default=8.0)
    e.add_argument("--sections", default="", help="comma list of URL sections, most useful first")
    args = ap.parse_args(argv)
    if args.cmd == "index":
        print(json.dumps(build(args.creator, args.luau, args.out)))
    else:
        key = args.key_file.read_text(encoding="utf-8").strip()
        secs = tuple(s for s in args.sections.split(",") if s) or None
        print(json.dumps(embed(args.db, args.url, key, args.model, args.batch, args.max_minutes, secs)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
