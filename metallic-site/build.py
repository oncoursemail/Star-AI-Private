"""Build the Metallic website into plain static files.

    python metallic-site/build.py --out dist [--site-url https://metallic.club]
                                  [--releases DIR]       a folder with latest.json (Tauri updater manifest) and installers
                                  [--sample-live DIR]    copy revivals/news/projects/metallic/downloads JSON into dist/live (previews only)

Nothing runs on a server: dist/ is HTML, CSS, a little JavaScript, fonts and images. The live data (/live/*.json) is
written on the server every 2 minutes by metallic-live; the newest build is /releases/latest.json. The pages read both
in the browser and still look complete when they are missing. See HOSTING.md.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
FRONT = re.compile(r"<!--\s*(\w+):\s*(.*?)\s*-->")
NAV = ("home", "downloads", "changelog", "news")
LIVE_FILES = ("revivals.json", "news.json", "projects.json", "metallic.json", "downloads.json")
RELEASE_SUFFIXES = (".exe", ".msi", ".sig", ".zip", ".appimage", ".deb", ".apk", ".dmg", ".app.tar.gz")  # compared lower-case
RELEASE_MANIFESTS = ("latest.json", "quest.json")  # desktop updater manifest; the Meta Quest APK {"version","url","notes"}


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def parse_page(text: str) -> tuple[dict, str]:
    meta, lines = {}, text.split("\n")
    i = 0
    while i < len(lines) and (m := FRONT.fullmatch(lines[i].strip())):
        meta[m[1]] = m[2]
        i += 1
    return meta, "\n".join(lines[i:]).strip()


def assets_version() -> str:
    """A short hash of every asset, added as ?v= to the CSS and script links so a new build never runs a cached old script."""
    h = hashlib.sha256()
    for p in sorted((SRC / "assets").rglob("*")):
        if p.is_file():
            h.update(p.relative_to(SRC).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:10]


def render_page(layout: str, rel: str, meta: dict, body: str, site_url: str, version: str = "") -> str:
    page = meta.get("page", "")
    path = "/" if rel == "index.html" else "/" + rel.removesuffix("index.html")
    v = f"?v={version}" if version else ""
    scripts = "".join(f'<script src="{esc(s if s.startswith("/") else "/assets/" + s)}{v}" defer></script>'
                      for s in (x.strip() for x in meta.get("scripts", "").split(",")) if s)
    values = {"title": esc(meta["title"]), "description": esc(meta["description"]), "page": esc(page),
              "canonical": esc(site_url.rstrip("/") + path), "content": body, "scripts": scripts, "v": v,
              "site": esc(site_url.rstrip("/")), "robots": '\n<meta name="robots" content="noindex">' if meta.get("noindex") else "",
              "year": str(datetime.now(timezone.utc).year)}
    for n in NAV:
        values[f"cur_{n}"] = ' aria-current="page"' if page == n else ""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m[1]], layout)


def copy_releases(src: Path, dest: Path) -> None:
    """latest.json, quest.json and the installers and APKs. Nothing else (no keys, no old channel files)."""
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.iterdir()):
        if p.is_file() and (p.name in RELEASE_MANIFESTS or p.name.lower().endswith(RELEASE_SUFFIXES)):
            shutil.copy2(p, dest / p.name)


def copy_sample_live(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in LIVE_FILES:
        if (src / name).is_file():
            shutil.copy2(src / name, dest / name)


def build(out: Path, site_url: str, releases: Path | None = None, sample_live: Path | None = None) -> dict:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    layout = (SRC / "_layout.html").read_text(encoding="utf-8")
    shutil.copytree(SRC / "assets", out / "assets")
    version = assets_version()
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
        dest.write_text(render_page(layout, rel, meta, body, site_url, version), encoding="utf-8")
        pages.append(rel)
    if releases:
        copy_releases(Path(releases), out / "releases")
    if sample_live:
        copy_sample_live(Path(sample_live), out / "live")
    base = site_url.rstrip("/")
    urls = [("/" if p == "index.html" else "/" + p.removesuffix("index.html")) for p in pages if p != "404.html"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{esc(base + u)}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
                                     + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /live/\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    return {"pages": pages, "bytes": sum(f.stat().st_size for f in out.rglob("*") if f.is_file())}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(HERE / "dist"))
    p.add_argument("--site-url", default="https://metallic.club")
    p.add_argument("--releases", help="folder holding latest.json and the installer files")
    p.add_argument("--sample-live", help="folder with sample revivals/news/projects/metallic/downloads .json, for previews only")
    a = p.parse_args(argv)
    res = build(Path(a.out), a.site_url, Path(a.releases) if a.releases else None,
                Path(a.sample_live) if a.sample_live else None)
    print(f"built {len(res['pages'])} pages, {res['bytes'] // 1024} KB -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
