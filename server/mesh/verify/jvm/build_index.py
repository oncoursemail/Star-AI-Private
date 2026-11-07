"""Deprecation notes from the official javadoc jars -> /opt/mcp/index/deprecations.json (runs in the mc-plugins
container; stdlib only).

    python3 build_index.py /opt/mcp/javadoc /opt/mcp/index/deprecations.json

Reads deprecated-list.html of every *-javadoc.jar under the folder: each row links a class or member and carries the
@deprecated text ("use X instead"). Keys: "pkg.Class#member(" for members (overloads share one note) and "pkg.Class"
for classes, the same names javac prints in its [deprecation]/[removal] warnings.
"""
from __future__ import annotations

import html
import json
import re
import sys
import zipfile
from pathlib import Path

ROW = re.compile(r'<div class="col-summary-item-name[^"]*"><a href="([^"#]+)\.html(?:#([^"]+))?"[^>]*>.*?</a></div>\s*'
                 r'<div class="col-last[^"]*">(.*?)</div>\s*(?=<div class="col-summary-item-name|</div>\s*</div>)', re.S)
TAG = re.compile(r"<[^>]+>")


def notes_from(jar: Path) -> dict:
    out = {}
    with zipfile.ZipFile(jar) as z:
        names = [n for n in z.namelist() if n.endswith("deprecated-list.html")]
        for n in names:
            page = z.read(n).decode("utf-8", "replace")
            for href, anchor, body in ROW.findall(page):
                cls = href.replace("/", ".")
                text = re.sub(r"\s+", " ", html.unescape(TAG.sub("", body))).strip()
                if not text:
                    continue
                key = cls if not anchor else f"{cls}#{html.unescape(anchor).split('(')[0]}("
                out.setdefault(key, text[:300])
    return out


def main(argv: list[str]) -> int:
    src, dst = Path(argv[0]), Path(argv[1])
    notes = {}
    for jar in sorted(src.rglob("*-javadoc.jar")):
        got = notes_from(jar)
        print(f"{jar.name}: {len(got)} notes")
        for k, v in got.items():
            notes.setdefault(k, v)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(notes, indent=0, sort_keys=True), encoding="utf-8")
    print(f"{len(notes)} notes -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
