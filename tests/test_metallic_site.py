"""The static metallic.club site: builds, links resolve, nothing external but Discord images, nothing private, live data
and releases are read from the same origin, and the server files match the hosting plan."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from launcher.px import build as px

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "metallic-site"
SERVER = REPO / "server" / "metallic-site"
SITE_URL = "https://metallic.example"
PAGES = ["404.html", "downloads/index.html", "index.html", "news/index.html"]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.in_title, self.h1, self.meta, self.ids = "", False, 0, {}, set()
        self.links, self.assets, self.imgs, self.inline, self.handlers = [], [], [], 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for k in a:
            if k.startswith("on"):
                self.handlers.append((tag, k))
        if "style" in a:
            self.handlers.append((tag, "style"))
        if tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.h1 += 1
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content", "")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "link" and a.get("href") and a.get("rel") != "canonical":
            self.assets.append(a["href"])
        elif tag == "script":
            if a.get("src"):
                self.assets.append(a["src"])
            else:
                self.inline += 1
        elif tag == "img":
            self.imgs.append(a)
            self.assets.append(a.get("src", ""))
        elif tag == "style":
            self.inline += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def load_build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("metallic_site_build", SITE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mod = load_build()
    work = tmp_path_factory.mktemp("site")
    rel = work / "rel"
    rel.mkdir()
    (rel / "Metallic_0.1.0_x64-setup.exe").write_bytes(b"installer bytes")
    (rel / "latest.json").write_text(json.dumps({
        "version": "0.1.0", "notes": "First build.", "pub_date": "2026-11-01T12:00:00Z",
        "platforms": {"windows-x86_64": {"signature": "c2ln", "url": SITE_URL + "/releases/Metallic_0.1.0_x64-setup.exe"}}}))
    (rel / "release-signing-key.json").write_text("{}")  # never copied
    out = work / "dist"
    res = mod.build(out, SITE_URL, rel)
    return out, res, rel, mod


def parse(path: Path) -> Page:
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def js(out: Path, name: str) -> str:
    return (out / "assets" / name).read_text(encoding="utf-8")


def test_every_page_has_title_description_one_h1_and_a_canonical_url(built):
    out, res, _, _ = built
    assert sorted(res["pages"]) == PAGES
    for rel in res["pages"]:
        p = parse(out / rel)
        assert p.title.strip() and len(p.meta.get("description", "")) > 40, rel
        assert p.h1 == 1, rel
        text = (out / rel).read_text(encoding="utf-8")
        assert re.search(r'<link rel="canonical" href="https://metallic\.example/[^"]*">', text), rel
        assert "{{" not in text, rel


def test_old_pages_and_formats_are_gone(built):
    out, _, _, _ = built
    for gone in ("games", "litha", "progress"):
        assert not (out / gone).exists() and not (SITE / "src" / gone).exists()
    everything = "".join(p.read_text(encoding="utf-8") for p in (out / "assets").glob("*.js"))
    assert "/api/" not in everything and "/releases/channels/" not in everything and "blobs" not in everything


def target_exists(out: Path, href: str, src_page: Path) -> bool:
    path, _, frag = href.partition("#")
    if path:
        t = out / path.lstrip("/")
        if t.is_dir():
            t = t / "index.html"
        if not t.is_file():
            return False
    else:
        t = src_page
    return not frag or (t.suffix == ".html" and frag in parse(t).ids)


def test_internal_links_assets_and_anchors_resolve(built):
    out, res, _, _ = built
    for rel in res["pages"]:
        page = out / rel
        p = parse(page)
        for href in p.links + p.assets:
            if not href or href.startswith(("mailto:", "data:")):
                continue
            assert not href.startswith(("http://", "https://", "//")), f"{rel}: external reference {href}"
            assert target_exists(out, href, page), f"{rel}: broken {href}"
        for img in p.imgs:
            assert "alt" in img, f"{rel}: image without alt attribute {img.get('src')}"
            assert img.get("width") and img.get("height"), f"{rel}: image without size {img.get('src')}"


def test_pages_work_under_a_strict_content_security_policy(built):
    out, res, _, _ = built
    for rel in res["pages"]:
        p = parse(out / rel)
        assert p.inline == 0 and not p.handlers, f"{rel}: inline script, style or handler {p.handlers}"
    css = js(out, "site.css")
    assert "http://" not in css and "https://" not in css and "@import" not in css
    for f in (out / "assets").glob("*.js"):
        text = f.read_text(encoding="utf-8")
        assert "innerHTML" not in text and "outerHTML" not in text and "eval(" not in text, f.name
        assert not re.search(r"\.setAttribute\(\s*['\"]style", text), f.name  # blocked by style-src 'self'
        # the only outside address in any script is Discord's image CDN, the one host img-src allows
        assert set(re.findall(r"https?://[^\s\"'`)]+", text)) <= {"https://cdn.discordapp.com/"}, f.name


def test_live_data_and_release_are_read_same_origin(built):
    out, _, _, _ = built
    home, site, news, dl = js(out, "home.js"), js(out, "site.js"), js(out, "news.js"), js(out, "downloads.js")
    for path in ('"/live/revivals.json"', '"/live/projects.json"', '"/live/news.json"'):
        assert path in home, path
    assert '"/live/news.json"' in news and '"/live/revivals.json"' in news
    assert '"/releases/latest.json"' in site and '"windows-x86_64"' in site
    assert "M.release" in dl and "location.origin" in dl  # size only asked for on the same origin
    assert "60000" in home  # the board refreshes every minute
    assert "M.cdn(" in home and "M.cdn(" in news  # images only through the CDN check


def test_counts_are_labelled_truthfully():
    home = (SITE / "src" / "assets" / "home.js").read_text(encoding="utf-8")
    assert 'const players = (r) => (typeof r.players === "number" ? r.players : null);' in home
    assert 'r.discord.online' in home and "online in Discord" in home
    # the Discord online number is never labelled as players or in game
    for line in home.splitlines():
        if "online(" in line and "in game" in line:
            pytest.fail("Discord online count next to an 'in game' label: " + line.strip())
    page = (SITE / "src" / "index.html").read_text(encoding="utf-8")
    assert "it is not a player count" in page


def test_release_folder_copies_only_the_manifest_and_installers(built):
    out, _, _, _ = built
    assert sorted(p.name for p in (out / "releases").iterdir()) == ["Metallic_0.1.0_x64-setup.exe", "latest.json"]
    m = json.loads((out / "releases/latest.json").read_text())
    assert m["platforms"]["windows-x86_64"]["url"].endswith("/releases/Metallic_0.1.0_x64-setup.exe")


def test_sample_live_data_is_copied_only_when_asked(built, tmp_path):
    out, _, _, mod = built
    assert not (out / "live").exists()
    sample = tmp_path / "sample"
    sample.mkdir()
    for name in ("revivals.json", "news.json", "projects.json", ".revivals-history.json", "other.json"):
        (sample / name).write_text("{}")
    dest = tmp_path / "with"
    mod.build(dest, SITE_URL, None, sample)
    assert sorted(p.name for p in (dest / "live").iterdir()) == ["news.json", "projects.json", "revivals.json"]


def test_cli_build_works(tmp_path, capsys):
    mod = load_build()
    assert mod.main(["--out", str(tmp_path / "d"), "--site-url", "https://metallic.club"]) == 0
    assert "built 4 pages" in capsys.readouterr().out
    assert '<link rel="canonical" href="https://metallic.club/">' in (tmp_path / "d/index.html").read_text(encoding="utf-8")


def test_nothing_private_is_in_the_built_site(built):
    out, _, _, _ = built
    leaks = {}
    for p in out.rglob("*"):
        if p.is_file() and p.suffix in {".html", ".js", ".css", ".json", ".txt", ".xml"}:
            found = px.scrub({"mode": "public", "x": p.read_text(encoding="utf-8", errors="ignore")})
            if found:
                leaks[p.name] = found
    assert not leaks
    assert not list(out.rglob("*.pem")) and not list(out.rglob("*key*.json"))


def test_sitemap_and_robots_use_the_given_site_url(built):
    out, _, _, _ = built
    sm = (out / "sitemap.xml").read_text()
    assert f"<loc>{SITE_URL}/</loc>" in sm and f"<loc>{SITE_URL}/downloads/</loc>" in sm and f"<loc>{SITE_URL}/news/</loc>" in sm
    assert "404" not in sm
    robots = (out / "robots.txt").read_text()
    assert f"Sitemap: {SITE_URL}/sitemap.xml" in robots and "Disallow: /live/" in robots


def test_fonts_images_and_total_size_stay_modest(built):
    out, res, _, _ = built
    assert res["bytes"] < 2 * 1024 * 1024
    assert all(p.stat().st_size < 400 * 1024 for p in (out / "assets").rglob("*") if p.is_file())
    assert sorted(p.name for p in (out / "assets/fonts").iterdir()) == ["archivo-var.woff2", "hanken-grotesk-var.woff2"]


def test_server_files_match_the_hosting_plan():
    caddy = (SERVER / "Caddyfile").read_text(encoding="utf-8")
    assert ":8088" in caddy and "bind 127.0.0.1" in caddy and "root * /srv/metallic/dist" in caddy
    assert "img-src 'self' data: https://cdn.discordapp.com;" in caddy and "connect-src 'self'" in caddy
    assert '@fresh path /live/* /releases/latest.json\n\theader @fresh Cache-Control "no-store"' in caddy
    assert 'header @installers Cache-Control "public, max-age=31536000, immutable"' in caddy
    svc = (SERVER / "metallic-live.service").read_text(encoding="utf-8")
    assert "User=metallic" in svc and "ExecStart=/opt/metallic/metallic-live --out /srv/metallic/dist/live" in svc
    assert "ReadWritePaths=/srv/metallic/dist/live" in svc
    timer = (SERVER / "metallic-live.timer").read_text(encoding="utf-8")
    assert "OnUnitActiveSec=2min" in timer and "WantedBy=timers.target" in timer
    cf = (SERVER / "cloudflared-config.yml").read_text(encoding="utf-8")
    assert "<TUNNEL-ID>" in cf and cf.count("service: http://127.0.0.1:8088") == 2
    assert "hostname: metallic.club" in cf and "hostname: www.metallic.club" in cf and "http_status:404" in cf
    deploy = (SERVER / "deploy.sh").read_text(encoding="utf-8")
    assert deploy.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in deploy
    assert "dl.cloudsmith.io/public/caddy/stable" in deploy and "pkg.cloudflare.com/cloudflared" in deploy
    assert "--exclude /live/ --exclude /releases/" in deploy
    for text in (caddy, svc, timer, cf, deploy):
        assert not px.scrub({"mode": "public", "x": text})


def test_hosting_guide_covers_the_tunnel_setup():
    guide = (SITE / "HOSTING.md").read_text(encoding="utf-8")
    for needle in ("Caddy", "127.0.0.1:8088", "cloudflared", "Cloudflare Tunnel", "metallic-live", "every 2 minutes",
                   "img-src 'self' data: https://cdn.discordapp.com", "no-store", "immutable", "latest.json",
                   "windows-x86_64", "deploy.sh", "online in Discord"):
        assert needle in guide, needle
    assert not px.scrub({"mode": "public", "x": guide})


def test_build_refuses_a_page_without_front_matter(tmp_path, built, monkeypatch):
    import shutil
    _, _, _, mod = built
    meta, body = mod.parse_page("<!-- title: T -->\n<!-- description: D -->\n<p>x</p>")
    assert meta == {"title": "T", "description": "D"} and body == "<p>x</p>"
    fake_src = tmp_path / "src"
    shutil.copytree(mod.SRC, fake_src)
    (fake_src / "zz.html").write_text("<p>no front matter</p>", encoding="utf-8")
    monkeypatch.setattr(mod, "SRC", fake_src)
    with pytest.raises(SystemExit, match="missing 'title'"):
        mod.build(tmp_path / "x", SITE_URL)
