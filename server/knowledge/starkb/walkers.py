"""Generic corpus walkers, chosen by the `walker` field of a source in corpora.json.

Until 2026-10-18 the index knew two sources, each with its own hand-written walker (store.WALKERS).
Every further source is described by data instead:

    {"name": "godot-guides", "checkout": "godot-docs", "walker": "rst-tree", "content_root": "",
     "include": ["getting_started/", "tutorials/"], "exclude": ["tutorials/assets_pipeline/"], ...}

Walkers (all pure text processing, no network, no model):
  markdown-tree  *.md / *.mdx under the content root (frontmatter title, URL from the path)
  rst-tree       Sphinx reStructuredText trees (Godot docs, Blender manual, CNP3): converted to a
                 Markdown-like text (headings, fenced code, admonitions kept, images/toctrees dropped)
  cnxml-tree     OpenStax books: modules/<id>/index.cnxml with the collection files for book and chapter titles
  jsonl-pages    pages fetched by fetch_pages.py (Wikipedia): one JSON object per line with title, url, text

`include` / `exclude` are path prefixes relative to the content root (POSIX, no wildcards).
Every walker yields `chunking.Doc` objects, exactly like the two original walkers.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree

from .chunking import Doc, chunk_markdown, frontmatter
from .quiet import wait_while_locked

MAX_FILE_BYTES = 2 * 1024 * 1024


def _gate() -> None:
    wait_while_locked(log=lambda message: print(message, file=sys.stderr))


def _selected(rel: str, include: list[str], exclude: list[str]) -> bool:
    if any(rel.startswith(prefix) for prefix in exclude):
        return False
    return not include or any(rel.startswith(prefix) for prefix in include)


def _slug_url(base: str, rel_no_ext: str, suffix: str = "") -> str:
    slug = rel_no_ext
    if slug.endswith("/index"):
        slug = slug[:-6]
    elif slug == "index":
        slug = ""
    return base.rstrip("/") + ("/" + slug if slug else "") + (suffix if slug else "")


# ---------------------------------------------------------------- Markdown trees

def markdown_tree(root: Path, base: str, *, include: list[str] = (), exclude: list[str] = (), kind: str = "guide"):
    files = sorted(list(root.rglob("*.md")) + list(root.rglob("*.mdx")))
    for file in files:
        rel = file.relative_to(root).as_posix()
        if not _selected(rel, list(include), list(exclude)) or file.stat().st_size > MAX_FILE_BYTES:
            continue
        _gate()
        raw = file.read_text(encoding="utf-8", errors="replace")
        yield chunk_markdown(raw, path=rel, url=_slug_url(base, rel.rsplit(".", 1)[0]), kind=kind)


# ---------------------------------------------------------------- reStructuredText -> Markdown-like text

_RST_UNDERLINE = re.compile(r"^([=\-~^\"'*+#`:.])\1{2,}\s*$")
_RST_DIRECTIVE = re.compile(r"^(\s*)\.\.\s+([a-zA-Z][\w-]*)::\s*(.*)$")
_RST_TARGET = re.compile(r"^\s*\.\.\s+_[^:]*:.*$")           # .. _label:
_RST_SUBST = re.compile(r"^\s*\.\.\s+\|[^|]*\|\s+\w+::.*$")   # .. |name| replace:: text
_RST_COMMENT = re.compile(r"^\s*\.\.(\s.*)?$")
_ROLE = re.compile(r":[a-zA-Z][\w:+-]*:`([^`]*)`")
_ROLE_TARGET = re.compile(r"^(.*?)\s*<[^<>]*>\s*$", re.S)
_INLINE_LITERAL = re.compile(r"``([^`]+)``")
_RST_LINK = re.compile(r"`([^`<]+?)\s*<([^`>]+)>`_{1,2}")
_RST_REF = re.compile(r"`([^`]+)`_{1,2}")
_FIELD_OPTION = re.compile(r"^\s+:[\w-]+:.*$")
_DROP_DIRECTIVES = {"image", "figure", "toctree", "only", "raw", "index", "highlight", "default-domain", "contents",
                    "rst-class", "container", "video", "youtube", "vimeo", "sectionauthor", "meta", "tabs", "tab",
                    "include", "literalinclude", "glossary", "graphviz", "math", "productionlist", "footer"}
_KEEP_FIGURE_CAPTION = {"figure"}
_ADMONITIONS = {"note", "warning", "tip", "hint", "important", "seealso", "attention", "caution", "danger", "error",
                "admonition", "todo", "versionadded", "versionchanged", "deprecated", "topic", "sidebar", "reference",
                "example", "exercise"}
_CODE_DIRECTIVES = {"code-block", "code", "sourcecode", "literal", "parsed-literal"}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block_end(lines: list[str], start: int, indent: int) -> int:
    """First index after `start` whose non-blank line is indented `indent` or less."""
    i = start
    while i < len(lines):
        line = lines[i]
        if line.strip() and _indent(line) <= indent:
            break
        i += 1
    return i


def _dedent(lines: list[str]) -> list[str]:
    widths = [_indent(line) for line in lines if line.strip()]
    cut = min(widths) if widths else 0
    return [line[cut:] if line.strip() else "" for line in lines]


def _inline(text: str) -> str:
    def role(match: re.Match) -> str:
        inner = match.group(1)
        target = _ROLE_TARGET.match(inner)
        inner = target.group(1) if target and target.group(1).strip() else inner
        return "`" + inner.strip().strip("<>") + "`"
    text = _INLINE_LITERAL.sub(lambda m: "\x00" + m.group(1) + "\x00", text)
    text = _ROLE.sub(role, text)
    text = _RST_LINK.sub(r"\1", text)
    text = _RST_REF.sub(r"\1", text)
    text = text.replace("\x00", "`")
    text = re.sub(r"(?<!\*)\*\*([^*]+)\*\*(?!\*)", r"**\1**", text)
    return text.replace("|", "|")


def rst_to_markdown(raw: str, *, levels: dict[str, int] | None = None) -> tuple[str, str]:
    """(title, markdown-like body). Heading levels follow the order the underline characters appear in."""
    levels = {} if levels is None else levels
    lines = raw.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    title = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # section titles: text + underline (optional overline)
        if (_RST_UNDERLINE.match(line) and i + 2 < len(lines) and lines[i + 1].strip()
                and _RST_UNDERLINE.match(lines[i + 2]) and lines[i + 2].strip()[0] == stripped[0]):
            text, char = lines[i + 1].strip(), stripped[0]
            level = levels.setdefault("over" + char, len(levels) + 1)
            out.append("#" * min(level, 4) + " " + _inline(text))
            title = title or text
            i += 3
            continue
        if (stripped and i + 1 < len(lines) and _RST_UNDERLINE.match(lines[i + 1])
                and len(lines[i + 1].strip()) >= len(stripped) and not stripped.startswith("..")
                and _indent(line) == 0):
            char = lines[i + 1].strip()[0]
            level = levels.setdefault(char, len(levels) + 1)
            out.append("#" * min(level, 4) + " " + _inline(stripped))
            title = title or stripped
            i += 2
            continue
        directive = _RST_DIRECTIVE.match(line)
        if directive:
            indent, name, arg = len(directive.group(1)), directive.group(2).lower(), directive.group(3).strip()
            end = _block_end(lines, i + 1, indent)
            body = lines[i + 1:end]
            # drop the option fields (":caption: x") at the top of the block
            while body and (_FIELD_OPTION.match(body[0]) or not body[0].strip()):
                if body[0].strip() and not _FIELD_OPTION.match(body[0]):
                    break
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            if name in _CODE_DIRECTIVES:
                lang = arg.split()[0] if arg else ""
                lang = {"gdscript": "gdscript", "csharp": "csharp", "c#": "csharp", "python": "python"}.get(lang.lower(), lang)
                out.extend(["", "```" + lang, *_dedent(body), "```", ""])
            elif name in _ADMONITIONS:
                # `.. note:: text` carries its text as the argument; `.. admonition:: Title` carries a title.
                titled = name in ("admonition", "topic", "sidebar", "versionadded", "versionchanged", "deprecated")
                label = (arg if titled and arg else name.capitalize()).strip()
                content = ([] if titled else ([arg] if arg else [])) + _dedent(body)
                out.append("")
                out.append(f"**{label}:**")
                sub_title, sub_body = rst_to_markdown("\n".join(content), levels=levels)
                out.extend(sub_body.split("\n"))
                out.append("")
            elif name in _KEEP_FIGURE_CAPTION:
                caption = [b.strip() for b in body if b.strip() and not _FIELD_OPTION.match(b)]
                if caption:
                    out.append("Figure: " + _inline(" ".join(caption)))
            elif name in _DROP_DIRECTIVES:
                pass
            else:                        # unknown directive: keep its text, it is often prose (e.g. "tabs")
                sub_title, sub_body = rst_to_markdown("\n".join(_dedent(body)), levels=levels)
                out.extend(sub_body.split("\n"))
            i = end
            continue
        if _RST_TARGET.match(line) or _RST_SUBST.match(line) or (_RST_COMMENT.match(line) and not stripped.startswith(".. |")):
            end = _block_end(lines, i + 1, _indent(line))
            i = end
            continue
        if stripped.endswith("::"):     # paragraph introducing a literal block
            text = stripped[:-2].rstrip()
            if text:
                out.append(_inline(text) + ":")
            end = _block_end(lines, i + 1, _indent(line))
            body = lines[i + 1:end]
            while body and not body[0].strip():
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            if body:
                out.extend(["", "```", *_dedent(body), "```", ""])
            i = end
            continue
        if _FIELD_OPTION.match(line) and out and out[-1].strip() == "":
            i += 1
            continue
        out.append(_inline(line) if stripped else "")
        i += 1
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")
    return title, text


def rst_tree(root: Path, base: str, *, include: list[str] = (), exclude: list[str] = (), kind: str = "guide",
             url_suffix: str = ".html"):
    for file in sorted(root.rglob("*.rst")):
        rel = file.relative_to(root).as_posix()
        if not _selected(rel, list(include), list(exclude)) or file.stat().st_size > MAX_FILE_BYTES:
            continue
        _gate()
        raw = file.read_text(encoding="utf-8", errors="replace")
        title, body = rst_to_markdown(raw)
        if not body.strip():
            continue
        if title and body.startswith("# " + title):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        yield chunk_markdown(body, path=rel, url=_slug_url(base, rel[:-4], url_suffix), kind=kind,
                             fallback_title=title or file.stem.replace("_", " "))


# ---------------------------------------------------------------- OpenStax CNXML

_NS = {"c": "http://cnx.rice.edu/cnxml", "md": "http://cnx.rice.edu/mdml", "m": "http://www.w3.org/1998/Math/MathML",
       "col": "http://cnx.rice.edu/collxml"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _math_text(node) -> str:
    parts = []
    for item in node.iter():
        if item.text and item.text.strip() and _local(item.tag) in ("mi", "mn", "mo", "mtext", "ms"):
            parts.append(item.text.strip())
    return " ".join(parts)


def _cnxml_text(node, out: list[str], depth: int = 1) -> None:
    """Flatten a CNXML element tree into Markdown-like lines (titles, paragraphs, lists, tables, exercises)."""
    tag = _local(node.tag)
    if tag in ("metadata", "media", "image", "video", "audio", "link-group", "footnote", "iframe", "object"):
        if node.tail and node.tail.strip():
            out.append(node.tail.strip())
        return
    if tag == "math":
        text = _math_text(node)
        if text:
            out.append(text)
        if node.tail and node.tail.strip():
            out.append(node.tail)
        return
    if tag == "title":
        text = "".join(node.itertext()).strip()
        if text:
            out.append("\n" + "#" * min(depth, 4) + " " + " ".join(text.split()) + "\n")
        return
    if tag in ("para", "caption", "commentary", "statement", "solution", "proof", "quote", "preformat", "code"):
        if tag in ("statement", "solution", "proof", "commentary"):
            out.append("\n**" + tag.capitalize() + ":**")
        inner: list[str] = []
        for child in node:
            if _local(child.tag) == "title":
                _cnxml_text(child, out, depth)
            else:
                _cnxml_text(child, inner, depth)
        text = (node.text or "") + " ".join(inner)
        if tag in ("preformat", "code") and "\n" in (node.text or ""):
            out.extend(["", "```", (node.text or "").strip("\n"), "```", ""])
        elif text.strip():
            out.append(" ".join(text.split()))
        if node.tail and node.tail.strip():
            out.append(node.tail.strip())
        return
    if tag == "item":
        inner: list[str] = []
        for child in node:
            _cnxml_text(child, inner, depth)
        out.append("- " + " ".join(((node.text or "") + " " + " ".join(inner)).split()))
        return
    if tag == "row":
        cells = []
        for entry in node:
            cells.append(" ".join("".join(entry.itertext()).split()))
        out.append("| " + " | ".join(cells) + " |")
        return
    if tag in ("emphasis", "term", "sub", "sup", "span", "foreign", "link", "cite", "newline"):
        out.append((node.text or "") + " ".join(c for c in ["".join(child.itertext()) + (child.tail or "") for child in node]))
        if node.tail:
            out.append(node.tail)
        return
    label = {"exercise": "Exercise", "example": "Example", "note": "Note", "definition": "Definition",
             "equation": "Equation", "figure": "Figure", "rule": "Rule"}.get(tag)
    if label:
        out.append("\n**" + label + ":**")
    if node.text and node.text.strip():
        out.append(node.text.strip())
    for child in node:
        _cnxml_text(child, out, depth + 1 if tag in ("section", "document", "content") else depth)
    if tag == "section" or label:
        out.append("")
    if node.tail and node.tail.strip():
        out.append(node.tail.strip())


def cnxml_to_markdown(raw: str) -> tuple[str, str]:
    root = ElementTree.fromstring(raw)
    title_node = root.find("c:title", _NS)
    title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else ""
    content = root.find("c:content", _NS)
    out: list[str] = []
    if content is not None:
        for child in content:
            _cnxml_text(child, out, 2)
    text = "\n".join(line.rstrip() for line in out)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return title, text


def _collections(root: Path) -> dict[str, tuple[str, str]]:
    """module id -> (book title, chapter title) from collections/*.collection.xml."""
    found: dict[str, tuple[str, str]] = {}
    for file in sorted((root / "collections").glob("*.collection.xml")):
        try:
            tree = ElementTree.fromstring(file.read_text(encoding="utf-8", errors="replace"))
        except ElementTree.ParseError:
            continue
        book_title = ""
        for node in tree.iter():
            if _local(node.tag) == "title" and node.text:
                book_title = " ".join(node.text.split())
                break

        def walk(node, chapter: str) -> None:
            for child in node:
                tag = _local(child.tag)
                if tag == "subcollection":
                    sub_title = next((" ".join(t.text.split()) for t in child.iter() if _local(t.tag) == "title" and t.text), chapter)
                    walk(child, sub_title)
                elif tag == "module":
                    found.setdefault(child.get("document", ""), (book_title, chapter))
                elif tag in ("content", "col"):
                    walk(child, chapter)
        walk(tree, "")
    return found


def cnxml_tree(root: Path, base: str, *, include: list[str] = (), exclude: list[str] = (), kind: str = "textbook"):
    books = _collections(root)
    for file in sorted((root / "modules").glob("*/index.cnxml")):
        rel = file.relative_to(root).as_posix()
        module = file.parent.name
        if not _selected(rel, list(include), list(exclude)) or file.stat().st_size > MAX_FILE_BYTES:
            continue
        _gate()
        try:
            title, body = cnxml_to_markdown(file.read_text(encoding="utf-8", errors="replace"))
        except ElementTree.ParseError as exc:
            print(f"SKIP {rel}: ParseError: {exc}")
            continue
        if not body.strip():
            continue
        book, chapter = books.get(module, ("", ""))
        full = " > ".join(part for part in (book, chapter, title) if part) or module
        yield chunk_markdown(body, path=rel, url=base.rstrip("/") + "/" + rel, kind=kind, fallback_title=full)


# ---------------------------------------------------------------- fetched pages (JSONL)

def jsonl_pages(root: Path, base: str, *, include: list[str] = (), exclude: list[str] = (), kind: str = "encyclopedia"):
    for file in sorted(root.rglob("*.jsonl")):
        rel = file.relative_to(root).as_posix()
        if not _selected(rel, list(include), list(exclude)):
            continue
        with file.open(encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                _gate()
                try:
                    page = json.loads(line)
                except ValueError:
                    continue
                text, title, url = page.get("text") or "", page.get("title") or "", page.get("url") or base
                if not isinstance(text, str) or len(text.strip()) < 80 or not isinstance(title, str):
                    continue
                key = str(page.get("id") or number)
                yield chunk_markdown(text, path=f"{rel}#{key}", url=url, kind=page.get("kind") or kind, fallback_title=title)


# ---------------------------------------------------------------- registry

WALKERS = {"markdown-tree": markdown_tree, "rst-tree": rst_tree, "cnxml-tree": cnxml_tree, "jsonl-pages": jsonl_pages}


def walker_for(source: dict):
    """A callable(root, base) -> Doc iterator for a corpora.json source with a `walker` field."""
    name = source.get("walker")
    if name not in WALKERS:
        raise KeyError(f"source {source.get('name')!r} has no walker (known: {', '.join(sorted(WALKERS))})")
    fn = WALKERS[name]
    options = {key: source[key] for key in ("include", "exclude", "kind", "url_suffix") if key in source}

    def walk(root: Path, base: str):
        return fn(root, base, **options)
    return walk


def snapshot_metadata(repo: Path) -> dict | None:
    """Commit-like metadata for a source that is not a Git checkout: SNAPSHOT.json written by its fetcher."""
    file = repo / "SNAPSHOT.json"
    if not file.is_file():
        return None
    data = json.loads(file.read_text(encoding="utf-8"))
    return {"commit": str(data.get("commit") or "files"), "commit_date": str(data.get("commit_date") or "")}
