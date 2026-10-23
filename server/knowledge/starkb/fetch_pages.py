"""Fetchers for sources that are not Git repositories (knowledge school, 2026-10-18).

    python -m starkb.fetch_pages wikipedia --topics topics/wikipedia-topics.json --out <sources>/wikipedia-topics
    python -m starkb.fetch_pages simplewiki --dump simplewiki-latest-pages-articles.xml.bz2 --out <sources>/simplewiki

Both write `<out>/*.jsonl` (one page per line: id, title, url, revid, text) and `<out>/SNAPSHOT.json`
(commit = a content hash, commit_date = fetch time) which store.build reads in place of a Git commit.
The pages are then walked by walkers.jsonl_pages. Text is CC BY-SA 4.0 (Wikimedia); every page keeps its
canonical URL and revision id so the attribution per chunk is exact.

Wikipedia is read through the MediaWiki API (TextExtracts, plain text, one page per request, a pause between
requests and a descriptive User-Agent, as the API etiquette asks). Nothing here calls a model.
"""
from __future__ import annotations

import argparse
import bz2
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote
from xml.etree import ElementTree

try:
    import requests
except ImportError:          # the unit tests on the PC exercise only the pure text functions
    requests = None

USER_AGENT = "STAR-knowledge/0.1 (private local research index; https://github.com/oncoursemail/Star-AI)"
API = "https://{lang}.wikipedia.org/w/api.php"
SKIP_SECTIONS = {"references", "external links", "see also", "further reading", "notes", "sources", "bibliography",
                 "footnotes", "citations", "other websites", "related pages", "gallery"}
_WIKI_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)


def extract_to_markdown(extract: str) -> str:
    """TextExtracts `exsectionformat=wiki` output -> Markdown headings; trailing reference sections dropped."""
    out: list[str] = []
    skipping = False
    for line in extract.replace("\r\n", "\n").split("\n"):
        heading = _WIKI_HEADING.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            skipping = title.lower() in SKIP_SECTIONS
            if not skipping:
                out.append("#" * min(level, 4) + " " + title)
            continue
        if not skipping:
            out.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return text


def _snapshot(out: Path, titles_hash: str, pages: int) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out.joinpath("SNAPSHOT.json").write_text(json.dumps({
        "commit": titles_hash, "commit_date": stamp, "pages": pages, "fetched_at": stamp}, indent=1), encoding="utf-8")


def fetch_wikipedia(topics: dict[str, list[str]], out: Path, *, lang: str = "en", pause: float = 0.6,
                    log=print, session=None, max_pages: int | None = None) -> dict:
    """One JSONL file per domain; a title that does not exist is reported, never invented."""
    if requests is None and session is None:
        raise RuntimeError("the requests package is needed to fetch pages")
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    missing: list[str] = []
    seen_ids: set[int] = set()
    total = 0
    for domain, titles in topics.items():
        rows = []
        for title in titles:
            if max_pages is not None and total >= max_pages:
                break
            params = {"action": "query", "prop": "extracts|info|revisions", "explaintext": 1, "exsectionformat": "wiki",
                      "redirects": 1, "inprop": "url", "rvprop": "ids|timestamp", "titles": title,
                      "format": "json", "formatversion": 2}
            try:
                reply = session.get(API.format(lang=lang), params=params, timeout=60)
                data = reply.json()
            except Exception as exc:          # noqa: BLE001 - one bad page must not stop the batch
                log(f"  {title}: {type(exc).__name__}")
                missing.append(title)
                time.sleep(pause)
                continue
            pages = (data.get("query") or {}).get("pages") or []
            page = pages[0] if pages else {}
            text = extract_to_markdown(page.get("extract") or "")
            if page.get("missing") or len(text) < 200 or page.get("pageid") in seen_ids:
                if not page.get("pageid") in seen_ids:
                    missing.append(title)
                time.sleep(pause)
                continue
            seen_ids.add(page["pageid"])
            revision = (page.get("revisions") or [{}])[0]
            rows.append({"id": page["pageid"], "title": page["title"], "url": page.get("canonicalurl")
                         or f"https://{lang}.wikipedia.org/wiki/" + quote(page["title"].replace(" ", "_")),
                         "revid": revision.get("revid"), "revised": revision.get("timestamp"),
                         "licence": "CC-BY-SA-4.0", "domain": domain, "text": text})
            total += 1
            time.sleep(pause)
        with out.joinpath(domain + ".jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        counts[domain] = len(rows)
        log(f"{domain}: {len(rows)} pages")
    digest = hashlib.sha256(json.dumps(topics, sort_keys=True).encode()).hexdigest()[:16]
    _snapshot(out, "wiki-" + digest, total)
    if missing:
        out.joinpath("missing.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
    return {"pages": total, "by_domain": counts, "missing": len(missing)}


# ---------------------------------------------------------------- Simple English Wikipedia dump

_TEMPLATE = re.compile(r"\{\{(?:[^{}]|\{[^{}]*\})*\}\}")
_TABLE = re.compile(r"\{\|.*?\|\}", re.S)
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_FILE_LINK = re.compile(r"\[\[(?:File|Image|Media|Category):[^\[\]]*(?:\[\[[^\[\]]*\]\][^\[\]]*)*\]\]", re.I)
_LINK_PIPE = re.compile(r"\[\[[^\[\]|]*\|([^\[\]]*)\]\]")
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_EXT_LINK = re.compile(r"\[https?://[^\s\]]+\s*([^\]]*)\]")
_BARE_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*=+\s*$", re.M)
_QUOTES = re.compile(r"'{2,5}")
_WS = re.compile(r"[ \t]+")


def wikitext_to_markdown(text: str) -> str:
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    for _ in range(4):
        new = _TEMPLATE.sub("", text)
        if new == text:
            break
        text = new
    text = _TABLE.sub("", text)
    text = _FILE_LINK.sub("", text)
    text = _LINK_PIPE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _EXT_LINK.sub(r"\1", text)
    text = _BARE_URL.sub("", text)
    text = _TAG.sub("", text)
    text = _QUOTES.sub("", text)
    out: list[str] = []
    skipping = False
    for line in text.split("\n"):
        heading = _HEADING.match(line)
        if heading:
            title = heading.group(2).strip()
            skipping = title.lower() in SKIP_SECTIONS
            if not skipping:
                if out and out[-1].strip():
                    out.append("")
                out.append("#" * min(len(heading.group(1)), 4) + " " + title)
            continue
        if skipping:
            continue
        line = _WS.sub(" ", line).strip()
        if line.startswith(("*", "#")):
            line = "- " + line.lstrip("*# ").strip()
        elif line.startswith((":", ";")):
            line = line.lstrip(":; ")
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def convert_simplewiki(dump: Path, out: Path, *, min_chars: int = 1200, max_pages: int = 80000,
                       per_file: int = 5000, log=print) -> dict:
    """Stream the bz2 XML dump, keep article pages (namespace 0, no redirect) whose stripped text is long enough."""
    out.mkdir(parents=True, exist_ok=True)
    kept = scanned = 0
    handle = None
    file_index = 0
    ns = ""
    with bz2.open(dump, "rb") as stream:
        for event, node in ElementTree.iterparse(stream, events=("end",)):
            tag = node.tag
            if tag.endswith("}page") or tag == "page":
                if not ns:
                    ns = tag[:-4]
                scanned += 1
                try:
                    if (node.findtext(ns + "ns") or "0") != "0" or node.find(ns + "redirect") is not None:
                        continue
                    title = node.findtext(ns + "title") or ""
                    revision = node.find(ns + "revision")
                    raw = revision.findtext(ns + "text") if revision is not None else ""
                    if not raw or len(raw) < min_chars // 2:
                        continue
                    text = wikitext_to_markdown(raw)
                    if len(text) < min_chars:
                        continue
                    page_id = node.findtext(ns + "id") or str(scanned)
                    rev_id = revision.findtext(ns + "id") if revision is not None else None
                    if handle is None or kept % per_file == 0:
                        if handle:
                            handle.close()
                        file_index += 1
                        handle = out.joinpath(f"simplewiki-{file_index:03d}.jsonl").open("w", encoding="utf-8")
                    handle.write(json.dumps({
                        "id": int(page_id), "title": title, "revid": int(rev_id) if rev_id else None,
                        "url": "https://simple.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                        "licence": "CC-BY-SA-4.0", "text": text}, ensure_ascii=False) + "\n")
                    kept += 1
                    if kept % 5000 == 0:
                        log(f"simplewiki: {kept} pages kept of {scanned} scanned")
                    if kept >= max_pages:
                        break
                finally:
                    node.clear()
    if handle:
        handle.close()
    _snapshot(out, "simplewiki-" + hashlib.sha256(dump.name.encode()).hexdigest()[:12], kept)
    log(f"simplewiki: done, {kept} pages kept of {scanned} scanned")
    return {"pages": kept, "scanned": scanned, "files": file_index}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starkb.fetch_pages")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("wikipedia", help="fetch the pages named in a topics file (domain -> titles) from Wikipedia")
    p.add_argument("--topics", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--pause", type=float, default=0.6)
    p.add_argument("--max-pages", type=int)
    p = sub.add_parser("simplewiki", help="convert a Simple English Wikipedia pages-articles dump (bz2) to JSONL")
    p.add_argument("--dump", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--min-chars", type=int, default=1200)
    p.add_argument("--max-pages", type=int, default=80000)
    args = parser.parse_args(argv)
    if args.cmd == "wikipedia":
        topics = json.loads(args.topics.read_text(encoding="utf-8"))
        topics = {k: v for k, v in topics.items() if not k.startswith("_")}
        print(json.dumps(fetch_wikipedia(topics, args.out, lang=args.lang, pause=args.pause, max_pages=args.max_pages,
                                         log=lambda m: print(m, flush=True)), indent=1))
        return 0
    if args.cmd == "simplewiki":
        print(json.dumps(convert_simplewiki(args.dump, args.out, min_chars=args.min_chars, max_pages=args.max_pages,
                                            log=lambda m: print(m, flush=True)), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
