"""The static Metallic site: builds, links resolve, nothing external, nothing private, downloads page matches the channel."""
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from launcher.updates import publish as pub
from launcher.updates.keys import PrivateKey
from launcher.px import build as px

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "metallic-site"
SITE_URL = "https://metallic.example"


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


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import importlib.util
    spec = importlib.util.spec_from_file_location("metallic_site_build", SITE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    work = tmp_path_factory.mktemp("site")
    key = PrivateKey(bytes(range(32)))
    src = work / "src"
    src.mkdir()
    (src / "launcher.py").write_text("print(1)\n")
    installer = work / "Setup.exe"
    installer.write_bytes(b"installer bytes")
    rel = work / "rel"
    comp = pub.build_component(rel, "launcher", "0.2.0", src, entry="launcher.py", notes="Test build.", platform="win-x64",
                               installer=installer)
    pub.publish(rel, "stable", {"launcher": comp}, key)
    out = work / "dist"
    res = mod.build(out, SITE_URL, None, rel)
    return out, res, rel, mod


def pages(out):
    return {p.relative_to(out).as_posix(): p for p in out.rglob("*.html")}


def parse(path: Path) -> Page:
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def test_every_page_has_title_description_one_h1_and_a_canonical_url(built):
    out, res, _, _ = built
    assert sorted(res["pages"]) == ["404.html", "downloads/index.html", "games/index.html", "index.html",
                                    "litha/index.html", "news/index.html", "progress/index.html"]
    for rel in res["pages"]:
        p = parse(out / rel)
        assert p.title.strip() and len(p.meta.get("description", "")) > 40, rel
        assert p.h1 == 1, rel
        text = (out / rel).read_text(encoding="utf-8")
        assert re.search(r'<link rel="canonical" href="https://metallic\.example/[^"]*">', text), rel
        assert "{{" not in text and "<!--news:" not in text and "<!--roadmap:" not in text, rel


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
    css = (out / "assets/site.css").read_text(encoding="utf-8")
    assert "http://" not in css and "https://" not in css and "@import" not in css
    for js in (out / "assets").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert "innerHTML" not in text and "eval(" not in text, js.name
        assert not re.search(r"\.setAttribute\(\s*['\"]style", text), js.name  # blocked by style-src 'self'


def test_progress_page_ships_public_data_only(built):
    out, _, _, _ = built
    data = json.loads((out / "progress/px.json").read_text())
    assert data["mode"] == "public" and len(data["projects"]) == 6
    assert not px.scrub(data)
    assert (out / "progress/px.js").read_bytes() == (REPO / "launcher/web/px/px.js").read_bytes()  # one page, two homes


def test_games_page_lists_roadmap_items_from_the_same_file(built):
    out, _, _, _ = built
    text = (out / "games/index.html").read_text(encoding="utf-8")
    for proj in px.load_roadmap()["projects"]:
        if proj["id"] in ("rc", "mc", "rb"):
            for item in proj["items"]:
                assert html.escape(item["title"], quote=True) in text, item["title"]
    assert text.count('class="rm"') == 3
    assert "concept art" in text
    litha = (out / "litha/index.html").read_text(encoding="utf-8")
    assert 'class="rm"' in litha


def test_news_is_rendered_and_escaped_at_build_time(built, tmp_path):
    out, _, _, mod = built
    news = (out / "news/index.html").read_text(encoding="utf-8")
    assert "How Metallic updates itself" in news and news.count('<article class="post"') == 2
    html = mod.render_news([{"date": "2026-01-02", "slug": "x", "title": "<script>alert(1)</script>", "body": "a & b\n\nsecond"}], None)
    assert "<script>" not in html and "&lt;script&gt;" in html and html.count("<p>") == 2


def test_release_folder_is_copied_without_blobs_unless_asked(built, tmp_path):
    out, _, rel, mod = built
    assert (out / "releases/channels/stable.json").is_file() and (out / "releases/channels/stable.json.sig").is_file()
    assert list((out / "releases/installers").glob("*.exe")) and not (out / "releases/blobs").exists()
    withb = tmp_path / "with"
    mod.build(withb, SITE_URL, None, rel, with_blobs=True)
    assert (withb / "releases/blobs").is_dir()
    assert "Disallow: /releases/blobs/" in (out / "robots.txt").read_text()


def test_downloads_page_reads_the_channel_path_the_publisher_writes(built):
    out, _, rel, _ = built
    js = (out / "assets/downloads.js").read_text(encoding="utf-8")
    assert '"/releases/channels/" + channel + ".json"' in js
    assert (rel / pub.manifest_rel("tree", "stable")).is_file()
    assert pub.manifest_rel("tree", "stable") == "channels/stable.json"
    m = json.loads((out / "releases/channels/stable.json").read_text())
    inst = m["components"]["launcher"]["installer"]
    assert (out / "releases" / inst["path"]).is_file()  # the button's target exists
    assert inst["size"] == len(b"installer bytes")


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
    assert f"<loc>{SITE_URL}/</loc>" in sm and f"<loc>{SITE_URL}/downloads/</loc>" in sm and "404" not in sm
    assert f"Sitemap: {SITE_URL}/sitemap.xml" in (out / "robots.txt").read_text()


def test_fonts_images_and_total_size_stay_modest(built):
    out, res, _, _ = built
    assert res["bytes"] < 3 * 1024 * 1024
    assert all(p.stat().st_size < 400 * 1024 for p in (out / "assets").rglob("*") if p.is_file())


def test_hosting_guide_covers_proxy_certificates_and_cloudflare():
    guide = (SITE / "HOSTING.md").read_text(encoding="utf-8")
    for needle in ("Caddy", "nginx", "certbot", "Let's Encrypt", "Cloudflare", "Full (strict)", "cloudflared",
                   "signing key", "Back the key file up"):
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
