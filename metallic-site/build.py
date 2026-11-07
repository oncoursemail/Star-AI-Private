"""Build the Metallic website into plain static files.

    python metallic-site/build.py --out dist [--site-url https://metallic.club]
                                  [--forge URL --token-file FILE]      PX tracker numbers (public-safe subset)
                                  [--releases DIR [--with-blobs]]      a release folder made by launcher.updates publish

Nothing runs on a server: dist/ is HTML, CSS, a little JavaScript, fonts and images. Host it anywhere (see HOSTING.md).
The progress page data is generated in --public mode, which strips issue titles, release notes and private-repo numbers,
and refuses to write if it finds an address, user name or key.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from launcher.px import build as px_build  # noqa: E402

SRC = HERE / "src"
FRONT = re.compile(r"<!--\s*(\w+):\s*(.*?)\s*-->")
PLACEHOLDER = re.compile(r"<!--(news|roadmap):(\w+)-->")
STATES = ("released", "accepted", "tested", "implemented", "planned")
NAV = ("games", "litha", "downloads", "progress", "news")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def parse_page(text: str) -> tuple[dict, str]:
    meta, lines = {}, text.split("\n")
    i = 0
    while i < len(lines) and (m := FRONT.fullmatch(lines[i].strip())):
        meta[m[1]] = m[2]
        i += 1
    return meta, "\n".join(lines[i:]).strip()


def fmt_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")


def render_news(posts: list[dict], limit: int | None) -> str:
    posts = sorted(posts, key=lambda p: p["date"], reverse=True)[:limit]
    out = []
    for p in posts:
        paras = "".join(f"<p>{esc(x)}</p>" for x in p["body"].split("\n\n"))
        out.append(f'<article class="post" id="{esc(p["slug"])}"><time datetime="{esc(p["date"])}">{esc(fmt_date(p["date"]))}</time>'
                   f'<div><h2>{esc(p["title"])}</h2>{paras}</div></article>')
    return "\n".join(out) or '<p class="empty">No posts yet.</p>'


def render_roadmap(project: dict) -> str:
    rows = []
    for state in STATES:
        for item in project["items"]:
            if item["state"] != state:
                continue
            note = f'<span class="note">{esc(item["note"])}</span>' if item.get("note") else ""
            block = "".join(f'<span class="note">Blocked: {esc(b)}</span>' for b in item.get("blockers", []))
            rows.append(f'<li><span class="chip" data-s="{state}"><i></i>{state.capitalize()}</span><span>{esc(item["title"])}</span>{note}{block}</li>')
    return f'<ul class="rm" aria-label="{esc(project["name"])} roadmap">' + "".join(rows) + "</ul>"


def render_page(layout: str, rel: str, meta: dict, body: str, site_url: str, news: list[dict], roadmap: dict) -> str:
    projects = {p["id"]: p for p in roadmap["projects"]}

    def fill(m: re.Match) -> str:
        kind, arg = m[1], m[2]
        if kind == "news":
            return render_news(news, 3 if arg == "latest" else None)
        if arg not in projects:
            raise SystemExit(f"{rel}: unknown roadmap project {arg!r}")
        return render_roadmap(projects[arg])

    body = PLACEHOLDER.sub(fill, body)
    page = meta.get("page", "")
    path = "/" if rel == "index.html" else "/" + rel.removesuffix("index.html")
    scripts = "".join(f'<script src="{esc(s if s.startswith("/") else "/assets/" + s)}" defer></script>'
                      for s in (x.strip() for x in meta.get("scripts", "").split(",")) if s)
    values = {"title": esc(meta["title"]), "description": esc(meta["description"]), "page": esc(page),
              "canonical": esc(site_url.rstrip("/") + path), "content": body, "scripts": scripts,
              "head_extra": meta.get("head_extra", "")}
    for n in NAV:
        values[f"cur_{n}"] = ' aria-current="page"' if page == n else ""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m[1]], layout)


def copy_releases(src: Path, dest: Path, with_blobs: bool) -> None:
    for name in ("channels", "installers", "changelog.json", "stable.json", "stable.json.sig", "beta.json", "beta.json.sig"):
        p = src / name
        if p.is_dir():
            shutil.copytree(p, dest / name, dirs_exist_ok=True)
        elif p.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / name)
    if with_blobs and (src / "blobs").is_dir():
        shutil.copytree(src / "blobs", dest / "blobs", dirs_exist_ok=True)


def build(out: Path, site_url: str, forge: px_build.Forge | None = None, releases: Path | None = None,
          with_blobs: bool = False) -> dict:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    layout = (SRC / "_layout.html").read_text(encoding="utf-8")
    news = json.loads((SRC / "news.json").read_text(encoding="utf-8"))["posts"]
    roadmap = px_build.load_roadmap()
    shutil.copytree(SRC / "assets", out / "assets")
    pages = []
    for page in sorted(SRC.rglob("*.html")):
        rel = page.relative_to(SRC).as_posix()
        if rel.startswith("_"):
            continue
        meta, body = parse_page(page.read_text(encoding="utf-8"))
        for key in ("title", "description"):
            if key not in meta:
                raise SystemExit(f"{rel}: missing '{key}' front matter")
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_page(layout, rel, meta, body, site_url, news, roadmap), encoding="utf-8")
        pages.append(rel)
    # progress page: the same page and script the launcher uses, plus public-mode data
    px_dir = out / "progress"
    for name in ("px.js", "px.css"):
        shutil.copy2(ROOT / "launcher" / "web" / "px" / name, px_dir / name)
    data = px_build.build(roadmap, forge, public=True)
    px_build.write(data, px_dir / "px.json")
    if releases:
        copy_releases(Path(releases), out / "releases", with_blobs)
    base = site_url.rstrip("/")
    urls = [("/" if p == "index.html" else "/" + p.removesuffix("index.html")) for p in pages if p != "404.html"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{esc(base + u)}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
                                     + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /releases/blobs/\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    return {"pages": pages, "px_forge": data["forge"]["state"], "bytes": sum(f.stat().st_size for f in out.rglob("*") if f.is_file())}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(HERE / "dist"))
    p.add_argument("--site-url", default="https://metallic.club")
    p.add_argument("--forge")
    p.add_argument("--token-file")
    p.add_argument("--releases")
    p.add_argument("--with-blobs", action="store_true")
    a = p.parse_args(argv)
    token = Path(a.token_file).read_text(encoding="utf-8").strip() if a.token_file else ""
    try:
        res = build(Path(a.out), a.site_url, px_build.Forge(a.forge, token) if a.forge else None,
                    Path(a.releases) if a.releases else None, a.with_blobs)
    except px_build.PxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"built {len(res['pages'])} pages, {res['bytes'] // 1024} KB, tracker data: {res['px_forge']} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
