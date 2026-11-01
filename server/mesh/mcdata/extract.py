"""Pull Minecraft commands and pack files out of a markdown answer.

    cmds, files, tree = extract(answer)
    cmds  = [(block_index, line_no, command_without_slash)]
    files = [{"block": i, "path": "data/ns/recipe/x.json" | None, "code": "...", "lang": "json|mcfunction|..."}]
    tree  = paths named in a folder-tree block (├── data/ ...), for layout checks
"""
from __future__ import annotations

import re

FENCE = re.compile(r"^(?P<ind>[ \t]{0,3})(?P<f>`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n(?P<code>.*?)^(?P=ind)(?P=f)[ \t]*$",
                   re.M | re.S)
PATH = re.compile(r"(?:[\w.\-]+/)*(?:data|assets)/[\w.\-]+(?:/[\w.\-]+)*\.(?:json|mcfunction|mcmeta|png|ogg|nbt|fsh|vsh|"
                  r"glsl)|\bpack\.mcmeta\b|\bsounds\.json\b")
COMMENT_PATH = re.compile(r"^\s*(?:#|//|<!--)\s*(?:file:?\s*)?(?P<p>\S+\.(?:json|mcfunction|mcmeta))\b", re.I)
TREE_LINE = re.compile(r"^(?P<pre>[\s│|`├└─\-+*]*?)(?P<name>[\w.\-]+/?)\s*(?:#.*|\(.*\)|<-.*|//.*)?$")
COMMAND_LANGS = {"mcfunction", "minecraft", "mcf", "mc", ""}
INLINE_CMD = re.compile(r"`/([a-z][a-z-]*(?: [^`\n]+)?)`")


def norm_path(p: str) -> str:
    p = p.replace("\\", "/").strip("`*'\" ")
    for root in ("data/", "assets/"):
        k = p.find(root)
        if k >= 0 and (k == 0 or p[k - 1] == "/"):
            return p[k:]
    return p.rsplit("/", 1)[-1] if p.endswith("pack.mcmeta") else p


def _tree_paths(code: str) -> list[str]:
    """Folder tree (├── a/ └── b.json) -> full paths; also plain indented lists."""
    stack, out = [], []
    for raw in code.splitlines():
        if not raw.strip():
            continue
        m = TREE_LINE.match(raw.rstrip())
        if not m:
            continue
        depth = len(m.group("pre").replace("\t", "    "))
        name = m.group("name")
        while stack and stack[-1][0] >= depth:
            stack.pop()
        full = "/".join([s[1].rstrip("/") for s in stack] + [name])
        out.append(full)
        if name.endswith("/"):
            stack.append((depth, name))
    return out


def block_path(before: str, code: str) -> tuple[str | None, bool]:
    """The file a code block is meant to be: a path comment on its first line, else the last path named in the
    prose right before it -> (path or None, whether it came from a comment)."""
    first = code.lstrip().split("\n", 1)[0] if code.strip() else ""
    cm = COMMENT_PATH.match(first)
    if cm:
        return norm_path(cm.group("p")), True
    found = PATH.findall(before[-300:])
    if not found:
        return None, False
    path, body = norm_path(found[-1]), code.lstrip()
    if path.endswith((".json", ".mcmeta")) and not body.startswith(("{", "[", "//")):
        return None, False                     # the prose names a JSON file, but this block is commands or text
    if path.endswith(".mcfunction") and body.startswith(("{", "[")):
        return None, False
    return path, False


def looks_like_commands(code: str) -> bool:
    lines = [ln.strip() for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return False
    cmdish = sum(bool(re.match(r"^/?[a-z][a-z-]*( |$)", ln)) for ln in lines)
    return cmdish == len(lines) and not any(ln.startswith(("{", "[", "\"")) for ln in lines)


def extract(text: str) -> tuple[list[tuple[int, int, str]], list[dict], list[str]]:
    cmds, files, tree = [], [], []
    last_end = 0
    for i, m in enumerate(FENCE.finditer(text)):
        info = m.group("info").strip().split(" ")[0].lower()
        code = m.group("code")
        before = text[last_end:m.start()]
        last_end = m.end()
        if "├" in code or "└" in code or (info in ("text", "txt", "") and re.search(r"^\s*\S+/\s*$", code, re.M)
                                           and not looks_like_commands(code)):
            tree += [norm_path(p) for p in _tree_paths(code)]
            continue
        path, cm = block_path(before, code)
        lang = info
        if not lang:
            lang = "json" if code.lstrip().startswith(("{", "[")) else ("mcfunction" if looks_like_commands(code)
                                                                        else "")
        if lang in ("mcmeta",):
            lang = "json"
        if path and path.endswith(".mcfunction"):
            lang = "mcfunction"
        files.append({"block": i, "path": path, "code": code, "lang": lang,
                      "comment_path": cm})
        if lang in COMMAND_LANGS and (lang != "" or looks_like_commands(code)) and not code.lstrip().startswith("{"):
            for n, raw in enumerate(code.splitlines(), 1):
                s = raw.strip()
                if not s or s.startswith("#") or s.startswith("//") or s.startswith("$"):
                    continue
                cmds.append((i, n, s[1:] if s.startswith("/") else s))
    prose = FENCE.sub("", text)
    for m in INLINE_CMD.finditer(prose):          # `/give @p stick 1` written inline in the prose
        if " " in m.group(1):
            cmds.append((-1, prose.count("\n", 0, m.start()) + 1, m.group(1)))
    return cmds, files, tree
