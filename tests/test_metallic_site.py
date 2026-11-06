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
PAGES = ["404.html", "changelog/index.html", "downloads/index.html", "index.html", "news/index.html"]
DISCORD = "https://discord.gg/yMytc2uAmj"  # Metallic's own Discord server: the one outside link a page may carry


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
    path = path.split("?")[0]
    if path:
        t = out / path.lstrip("/")
        if t.is_dir():
            t = t / "index.html"
        if not t.is_file():
            return False
    else:
        t = src_page
    return not frag or (t.suffix == ".html" and frag in parse(t).ids)


def test_css_and_scripts_carry_the_assets_version(built):
    out, _, _, mod = built
    v = mod.assets_version()
    text = (out / "index.html").read_text(encoding="utf-8")
    for ref in ("/assets/site.css", "/assets/site.js", "/assets/home.js"):
        assert f'{ref}?v={v}"' in text, ref


def test_internal_links_assets_and_anchors_resolve(built):
    out, res, _, _ = built
    for rel in res["pages"]:
        page = out / rel
        p = parse(page)
        for href in p.links + p.assets:
            if not href or href.startswith(("mailto:", "data:")):
                continue
            if href == DISCORD:
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
    assert '"/live/downloads.json"' in site and "M.downloads" in dl and 'data-f="downloads"' in (out / "downloads" / "index.html").read_text(encoding="utf-8")
    assert "60000" in home  # the board refreshes every minute
    assert "M.cdn(" in home and "M.cdn(" in news  # images only through the CDN check


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.found.append(dict(attrs))


def test_the_official_discord_is_linked_from_every_page(built):
    out, res, _, _ = built
    for rel in res["pages"]:
        a = Anchors()
        a.feed((out / rel).read_text(encoding="utf-8"))
        dc = [x for x in a.found if x.get("href") == DISCORD]
        assert len(dc) >= 2, f"{rel}: header and footer"
        assert all(x.get("rel") == "noopener" for x in dc), rel
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="discord-h"' in home and "Join the Discord" in home
    assert "data-discord-online" in home  # live count, filled from /live/metallic.json


def test_people_in_metallic_and_the_discord_count_come_from_metallic_json(built):
    out, _, _, _ = built
    site = js(out, "site.js")
    assert '"/live/metallic.json"' in site and "M.live" in site
    assert "discord.com" not in site  # metallic-live asks Discord; visitors' browsers never do
    for page in ("index.html", "downloads/index.html"):
        text = (out / page).read_text(encoding="utf-8")
        assert "data-presence hidden" in text, page  # shown only once launchers report
    assert "in Metallic right now" in site and "online in the Metallic Discord" in site
    assert "online > 0" in site  # hidden at 0, before launchers send the beat
    assert "STALE" in site  # a stopped metallic-live leaves an old file: not shown as "right now"


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


def test_revivals_are_ordered_most_online_first_like_the_launcher():
    home = (SITE / "src" / "assets" / "home.js").read_text(encoding="utf-8")
    # in game first (only revivals that publish it), then online in Discord, unknown last, ties by name
    assert ("(players(b) ?? -1) - (players(a) ?? -1) || (online(b) ?? -1) - (online(a) ?? -1) || name(a).localeCompare(name(b))"
            in home)
    assert "newest(" not in home and "era year" not in home
    page = (SITE / "src" / "index.html").read_text(encoding="utf-8")
    assert "most online first" in page and "newest first" not in page


def test_pages_carry_open_graph_tags_and_the_404_is_not_indexed(built):
    out, res, _, _ = built
    for rel in res["pages"]:
        text = (out / rel).read_text(encoding="utf-8")
        for prop in ("og:title", "og:description", "og:url", "og:image", "og:type"):
            assert f'<meta property="{prop}" content="' in text, (rel, prop)
        assert 'content="https://metallic.example/assets/art/scenes/violet-nebula.jpg"' in text, rel
        assert ('<meta name="robots" content="noindex">' in text) == (rel == "404.html"), rel
    assert (out / "assets/art/scenes/violet-nebula.jpg").is_file()
    assert not (out / "assets/art/scenes/night-city.jpg").exists(), "the old hero picture stays off the site (owner, 11-04)"


def test_linux_builds_are_offered_to_linux_visitors_when_published():
    site = (SITE / "src" / "assets" / "site.js").read_text(encoding="utf-8")
    dl = (SITE / "src" / "assets" / "downloads.js").read_text(encoding="utf-8")
    page = (SITE / "src" / "downloads" / "index.html").read_text(encoding="utf-8")
    assert '"linux-x86_64"' in site and '"linux-x86_64-deb"' in site and "M.onLinux" in site and "!/Android/" in site
    # disabled until published
    assert 'data-get="linux" aria-disabled="true"' in page and 'data-get="deb" hidden' in page
    assert "if (r.linux)" in dl and """arm($('[data-get="linux"]'), r.linux.appimage""" in dl and """arm($('[data-get="deb"]'), r.linux.deb""" in dl
    caddy = (SERVER / "Caddyfile").read_text(encoding="utf-8")
    assert "/releases/*.AppImage /releases/*.deb" in caddy and "\t\tnot path /releases/*.exe /releases/*.dmg /releases/*.AppImage /releases/*.deb\n" in caddy
    build = (SITE / "build.py").read_text(encoding="utf-8")
    assert '".appimage", ".deb"' in build


def test_android_app_stays_hidden_until_published_and_says_what_it_does():
    site = (SITE / "src" / "assets" / "site.js").read_text(encoding="utf-8")
    dl = (SITE / "src" / "assets" / "downloads.js").read_text(encoding="utf-8")
    page = (SITE / "src" / "downloads" / "index.html").read_text(encoding="utf-8")
    assert '"/releases/android.json"' in site and '"/downloads/#android"' in site
    assert 'data-plat="android" aria-pressed="false" aria-controls="android" hidden' in page and 'data-pane="android" aria-labelledby="p-android" hidden' in page
    assert """$('[data-plat="android"]').hidden = false""" in dl
    assert "Metallic does not install revivals on a phone" in page
    # a Quest's browser is not an Android phone
    assert "M.onAndroid = /Android/.test(UA) && !M.onQuest;" in site


def test_mac_builds_stay_hidden_until_published_and_warn_plainly():
    site = (SITE / "src" / "assets" / "site.js").read_text(encoding="utf-8")
    dl = (SITE / "src" / "assets" / "downloads.js").read_text(encoding="utf-8")
    page = (SITE / "src" / "downloads" / "index.html").read_text(encoding="utf-8")
    assert '"darwin-aarch64-dmg"' in site and '"darwin-x86_64-dmg"' in site and '"/downloads/#mac"' in site
    # no release with a .dmg: no tile, no panel, no dead button
    assert 'data-plat="mac" aria-pressed="false" aria-controls="mac" hidden' in page and 'data-pane="mac" aria-labelledby="p-mac" hidden' in page
    assert 'data-get="mac-arm" hidden' in page and 'data-get="mac-intel" hidden' in page
    assert "if (r.mac) {" in dl and """$('[data-plat="mac"]').hidden = false""" in dl
    assert "Metallic does not run on macOS yet" in dl  # still what a Mac visitor reads until then
    assert "Open Anyway" in page and "none has been seen running on a Mac yet" in page and "no VR" in page
    caddy = (SERVER / "Caddyfile").read_text(encoding="utf-8")
    assert "/releases/*.tar.gz /releases/*.dmg" in caddy


def test_mac_files_are_copied_with_a_release(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    for name in ("latest.json", "Metallic_1_aarch64.dmg", "Metallic_1_aarch64.app.tar.gz", "Metallic_1_aarch64.app.tar.gz.sig", "other.tar.gz", "key.pem"):
        (src / name).write_text("x", encoding="utf-8")
    load_build().copy_releases(src, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["Metallic_1_aarch64.app.tar.gz", "Metallic_1_aarch64.app.tar.gz.sig", "Metallic_1_aarch64.dmg", "latest.json"]


def test_downloads_page_picks_the_visitors_device():
    dl = (SITE / "src" / "assets" / "downloads.js").read_text(encoding="utf-8")
    page = (SITE / "src" / "downloads" / "index.html").read_text(encoding="utf-8")
    for plat in ("windows", "linux", "quest"):
        assert f'data-plat="{plat}"' in page and f'id="{plat}" data-pane="{plat}"' in page, plat
    # a Quest's browser says Linux and an iPhone's says Mac OS X: Quest and phones are told apart first
    assert 'const device = M.onQuest ? "quest" : M.onLinux ? "linux" : onMac || onPhone ? null : "windows";' in dl
    site = (SITE / "src" / "assets" / "site.js").read_text(encoding="utf-8")
    assert site.index("M.onPhone =") < site.index("M.onMac =") and "!M.onPhone" in site
    assert '["windows", "linux", "quest"].find((id) => location.hash === "#" + id)' in dl  # a link can pick one


def test_release_folder_copies_only_the_manifest_and_installers(built):
    out, _, _, _ = built
    assert sorted(p.name for p in (out / "releases").iterdir()) == ["Metallic_0.1.0_x64-setup.exe", "latest.json"]
    m = json.loads((out / "releases/latest.json").read_text())
    assert m["platforms"]["windows-x86_64"]["url"].endswith("/releases/Metallic_0.1.0_x64-setup.exe")


def test_quest_apk_and_its_manifest_are_copied_and_shown(tmp_path):
    mod = load_build()
    rel = tmp_path / "rel"
    rel.mkdir()
    (rel / "Metallic_0.2.8_quest.apk").write_bytes(b"apk bytes")
    (rel / "quest.json").write_text(json.dumps({"version": "0.2.8", "url": "/releases/Metallic_0.2.8_quest.apk"}))
    (rel / "metallic-quest.jks").write_bytes(b"keystore")  # the signing key is never copied
    out = tmp_path / "dist"
    mod.build(out, SITE_URL, rel)
    assert sorted(p.name for p in (out / "releases").iterdir()) == ["Metallic_0.2.8_quest.apk", "quest.json"]
    dl, site = js(out, "downloads.js"), js(out, "site.js")
    assert '"/releases/quest.json"' in site and "M.quest" in dl and "data-quest-dl" in dl
    # a Quest headset's browser says "Linux" in its user agent: it must never be offered the Linux AppImage
    assert "M.onQuest = /OculusBrowser|Quest/.test(UA);" in site and "!M.onQuest" in site
    page = (out / "downloads" / "index.html").read_text(encoding="utf-8")
    assert 'id="quest"' in page and "data-quest-dl" in page and "SideQuest" in page


def test_sample_live_data_is_copied_only_when_asked(built, tmp_path):
    out, _, _, mod = built
    assert not (out / "live").exists()
    sample = tmp_path / "sample"
    sample.mkdir()
    for name in ("revivals.json", "news.json", "projects.json", "metallic.json", "downloads.json", ".revivals-history.json",
                 ".metallic-history.json", "other.json"):
        (sample / name).write_text("{}")
    dest = tmp_path / "with"
    mod.build(dest, SITE_URL, None, sample)
    assert sorted(p.name for p in (dest / "live").iterdir()) == ["downloads.json", "metallic.json", "news.json", "projects.json", "revivals.json"]


def test_cli_build_works(tmp_path, capsys):
    mod = load_build()
    assert mod.main(["--out", str(tmp_path / "d"), "--site-url", "https://metallic.club"]) == 0
    assert "built 5 pages" in capsys.readouterr().out
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
    assert '@fresh path /live/* /releases/latest.json /releases/quest.json /releases/android.json\n\theader @fresh Cache-Control "no-store"' in caddy
    assert "/releases/*.deb /releases/*.apk\n" in caddy  # the Quest APK is versioned in its name too: cached for good
    assert 'header @installers Cache-Control "public, max-age=31536000, immutable"' in caddy
    # download count: only installer requests are logged, without addresses or headers, readable by metallic-live
    assert "@unlogged {\n\t\tnot path /releases/*.exe /releases/*.dmg /releases/*.AppImage /releases/*.deb\n" in caddy and "log_skip @unlogged" in caddy
    assert "output file /var/log/caddy/downloads.log" in caddy and "mode 0644" in caddy
    assert "request>headers delete" in caddy and "request>remote_ip delete" in caddy and "request>client_ip delete" in caddy
    assert "log_append ua {http.request.header.User-Agent}" in caddy
    # people in Metallic now: only launcher beats (metallic.json asked for with the session header) reach beats.log,
    # carrying the random session ID and the time; no address, headers, user agent or path
    assert "@beat {\n\t\tpath /live/metallic.json\n\t\theader X-Metallic-Session *\n\t}" in caddy
    assert "\tnot {\n\t\t\tpath /live/metallic.json\n\t\t\theader X-Metallic-Session *\n\t\t}" in caddy  # beats not skipped
    assert "log_name @beat beats" in caddy and "log_append @beat session {http.request.header.X-Metallic-Session}" in caddy
    beats = caddy[caddy.index("log beats {"):]
    beats = beats[:beats.index("\n\t}\n")]
    assert "no_hostname" in beats and "output file /var/log/caddy/beats.log" in beats and "mode 0644" in beats
    assert "roll_size 1MiB" in beats and "roll_keep 1" in beats and "roll_uncompressed" in beats
    for field in ("request", "resp_headers", "ua", "user_id"):
        assert f"\t\t\t{field} delete" in beats, field
    assert caddy.count("/var/log/caddy/downloads.log") == 1
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
    assert "--exclude /live/ --exclude /releases/ --exclude /revivals/" in deploy  # Metallic-hosted revival files (Stella)
    for text in (caddy, svc, timer, cf, deploy):
        assert not px.scrub({"mode": "public", "x": text})


def test_hosting_guide_covers_the_tunnel_setup():
    guide = (SITE / "HOSTING.md").read_text(encoding="utf-8")
    for needle in ("Caddy", "127.0.0.1:8088", "cloudflared", "Cloudflare Tunnel", "metallic-live", "every 2 minutes",
                   "img-src 'self' data: https://cdn.discordapp.com", "no-store", "immutable", "latest.json",
                   "windows-x86_64", "deploy.sh", "online in Discord", "X-Metallic-Session", "beats.log",
                   "metallic.json", "discord.gg/yMytc2uAmj"):
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


# ---- two copies: both connectors up, one writer, the other an exact mirror (server/metallic-site/failover/metallic-failover)

def _failover():
    import importlib.machinery
    import importlib.util
    path = str(Path(__file__).resolve().parent.parent / "server" / "metallic-site" / "failover" / "metallic-failover")
    loader = importlib.machinery.SourceFileLoader("metallic_failover", path)
    spec = importlib.util.spec_from_loader("metallic_failover", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _live_dir(folder, stamp_ns, text="a"):
    import os
    fo = _failover()
    folder.mkdir(parents=True, exist_ok=True)
    for name in fo.MIRRORED:
        f = folder / name
        f.write_text(json.dumps({"name": name, "v": text, "totals": {"withNumbers": 3}}), encoding="utf-8")
        os.utime(f, ns=(stamp_ns, stamp_ns))
    for name in (".downloads-own.json", ".downloads-peer.json"):
        (folder / name).write_text('{"downloads": %d, "updates": 0}' % len(text), encoding="utf-8")


def test_failover_a_healthy_peer_never_makes_a_copy_step_out():
    fo = _failover()
    now = 1000.0
    up = {"ok": True, "serving": True, "at": now}
    for peer in (up, {}, {"ok": False, "serving": False, "at": now}, {**up, "at": now - 61}):
        assert fo.want_connector(True, peer, now), "a healthy copy keeps its connector, whatever the other does"
    assert fo.want_connector(False, up, now) is False, "unhealthy with the other serving: step out"
    assert fo.want_connector(False, {}, now), "unhealthy and alone: better than nothing"
    assert fo.want_connector(False, {**up, "at": now - 61}, now), "the other's word is old: it may be gone"
    assert fo.want_connector(False, {**up, "serving": False}, now), "make before break"


def test_failover_one_copy_writes_the_primary_when_it_has_internet():
    fo = _failover()
    now = 1000.0
    leading = {"leading": True, "at": now}
    following = {"leading": False, "at": now}
    assert fo.want_lead("primary", True, following, now) and fo.want_lead("primary", True, leading, now)
    assert not fo.want_lead("primary", False, leading, now), "no internet: the standby writes, the primary mirrors it"
    assert fo.want_lead("primary", False, {}, now), "alone: someone has to keep the download count going"
    assert not fo.want_lead("standby", True, leading, now)
    assert fo.want_lead("standby", True, following, now) and fo.want_lead("standby", True, {}, now)
    assert fo.want_lead("standby", True, {**leading, "at": now - 61}, now), "the primary went quiet: take over at once"


def test_failover_mirror_makes_the_copies_identical_and_keeps_each_copys_own_count(tmp_path):
    import os
    fo = _failover()
    a, b, work = tmp_path / "a", tmp_path / "b", tmp_path / "work"
    _live_dir(a, 2_000_000_000_000, "leader")
    _live_dir(b, 1_000_000_000_000, "old")
    before = sorted(p.name for p in b.iterdir())
    state = fo.build_state(a, work)
    assert fo.apply_state(b, state) is True
    for name in fo.MIRRORED:
        assert (b / name).read_bytes() == (a / name).read_bytes(), name
        assert os.stat(b / name).st_mtime_ns == os.stat(a / name).st_mtime_ns, "age checks see the writer's time"
    assert (b / ".downloads-own.json").read_text(encoding="utf-8") == '{"downloads": 3, "updates": 0}', "not double counted"
    assert sorted(p.name for p in b.iterdir()) == before, "replaced in place: no new files, nothing left behind"
    assert fo.apply_state(b, state) is False, "the same state again changes nothing"
    assert not {".downloads-own.json", ".downloads-peer.json"} & set(fo.MIRRORED)


def test_failover_mirror_refuses_old_or_damaged_data_and_files_it_does_not_know(tmp_path):
    import base64
    import gzip
    fo = _failover()
    a, b, work = tmp_path / "a", tmp_path / "b", tmp_path / "work"
    _live_dir(a, 1_000_000_000_000, "older")
    _live_dir(b, 2_000_000_000_000, "newer")
    assert fo.apply_state(b, fo.build_state(a, work)) is False, "a copy never goes back in time"
    assert "newer" in (b / "revivals.json").read_text(encoding="utf-8")
    pack = lambda files: {"id": 3_000_000_000_000, "gz": base64.b64encode(gzip.compress(json.dumps(files).encode())).decode()}
    good = {n: {"mtime_ns": 3_000_000_000_000, "text": json.dumps({"totals": {"withNumbers": 1}})} for n in fo.MIRRORED}
    for bad in ({**good, "../evil.json": good["revivals.json"]}, {**good, "revivals.json": {"mtime_ns": 3, "text": "{half"}},
                {"revivals.json": good["revivals.json"]},
                {**good, "revivals.json": {"mtime_ns": 3, "text": json.dumps({"totals": {"withNumbers": 0}})}}):
        assert fo.apply_state(b, pack(bad)) is False, str(list(bad))[:60]
    for broken in ({}, None, {"id": 3_000_000_000_000}, {"id": 3_000_000_000_000, "gz": "not base64"}):
        assert fo.apply_state(b, broken) is False
    assert not (tmp_path / "evil.json").exists() and "newer" in (b / "revivals.json").read_text(encoding="utf-8")


def test_failover_people_online_on_either_copy_count_once_and_the_file_never_grows(tmp_path):
    fo = _failover()
    logs = tmp_path / "caddy"
    logs.mkdir()
    a_id, b_id, gone = "a" * 32, "b" * 32, "c" * 32
    now = 10_000.0
    line = lambda ts, s: json.dumps({"level": "info", "ts": ts, "logger": "http.log.access.beats", "status": 200, "session": s})
    (logs / "beats.log").write_text("\n".join([line(now - 10, a_id), line(now - 200, a_id), line(now - 301, gone), line(now - 5, "not-an-id"), "junk"]), encoding="utf-8")
    (logs / "beats-2026-11-05T23-59-41.893-size.log").write_text(line(now - 100, b_id), encoding="utf-8")
    assert fo.recent_sessions(logs, now) == {a_id: now - 10, b_id: now - 100}
    fo.write_peer_beats(logs, {gone: now - 20, "x" * 32: now - 20, "bad": now}, now)
    fo.write_peer_beats(logs, {gone: now - 20, a_id: now - 400}, now)
    peer_log = logs / fo.PEER_BEATS
    lines = [json.loads(x) for x in peer_log.read_text(encoding="utf-8").splitlines()]
    assert lines == [{"ts": now - 20, "session": gone}], "replaced each time, only what is still online"
    assert peer_log.name.startswith("beats") and peer_log.name.endswith(".log") and not peer_log.name.startswith("beats-"), \
        "metallic-live reads it; Caddy's log rolling does not take it for one of its own"
    assert gone not in fo.recent_sessions(logs, now), "the other copy's visitors are not sent back to it as this copy's"


def test_failover_counts_downloads_as_metallic_live_does(tmp_path):
    fo = _failover()
    line = lambda method, uri, status, size, length, ua: json.dumps({"request": {"method": method, "uri": uri}, "status": status, "size": size,
                                                                       "resp_headers": {"Content-Length": [length]}, "ua": ua})
    log = tmp_path / "downloads.log"
    # the same lines as count_downloads' own test in metallic-rc's live.rs: the two must agree, or a change of writer moves the number
    log.write_text("\n".join([
        line("GET", "/releases/Metallic_0.2.6_x64-setup.exe", 200, 9000, "9000", "Mozilla/5.0"),
        line("GET", "/releases/Metallic_0.2.5_x64-setup.exe?x=1", 200, 8000, "8000", "Mozilla/5.0"),
        line("GET", "/releases/Metallic_0.2.6_x64-setup.exe", 200, 9000, "9000", "tauri-plugin-updater/2.14.1"),
        line("GET", "/releases/Metallic_0.2.6_x64-setup.exe", 200, 4000, "9000", "Mozilla/5.0"),
        line("HEAD", "/releases/Metallic_0.2.6_x64-setup.exe", 200, 0, "9000", "Mozilla/5.0"),
        line("GET", "/releases/Metallic_0.2.6_x64-setup.exe", 304, 0, "", "Mozilla/5.0"),
        line("GET", "/releases/Metallic_0.2.6_x64-setup.exe.sig", 200, 400, "400", "Mozilla/5.0"),
        line("GET", "/releases/Metallic_0.2.8_amd64.AppImage", 200, 9000, "9000", "Mozilla/5.0"),
        line("GET", "/releases/Metallic_0.2.8_amd64.deb", 200, 900, "900", "Mozilla/5.0"),
        line("GET", "/revivals/nodenet/NodeNetLauncherSetup.exe", 200, 900, "900", "Metallic-Launcher/0.2.11"),
        line("GET", "/releases/Metallic_0.2.8_aarch64.dmg", 200, 9000, "9000", "Mozilla/5.0"),
        "not json",
    ]), encoding="utf-8")
    assert fo.count_downloads(log) == {"downloads": 5, "updates": 1}
    assert fo.count_downloads(tmp_path / "missing.log") is None


def test_failover_install_keeps_one_backup_only():
    text = (Path(__file__).resolve().parent.parent / "server" / "metallic-site" / "failover" / "install.sh").read_text(encoding="utf-8")
    assert re.search(r"cp [^\n]*/usr/local/bin/metallic-failover /usr/local/bin/metallic-failover\.bak", text)
    assert "$(date" not in text, "a dated copy per install would pile up"


class _Copy:
    """One copy of the site in a folder: the real check, with the network, systemd and the clock answered here."""

    def __init__(self, base, role, clock):
        import types
        self.fo, self.role, self.clock, self.peer, self.internet = _failover(), role, clock, None, True
        self.link_up, self.units, self.stops = True, {"cloudflared", "metallic-live.timer"}, []
        root = base / role
        for name, attr in (("state", "STATE"), ("out", "OUT"), ("work", "WORK"), ("live", "LIVE_DIR"), ("logs", "CADDY_LOGS")):
            (root / name).mkdir(parents=True)
            setattr(self.fo, attr, root / name)
        self.fo.CONF = root / "conf"
        self.fo.CONF.write_text(f"ROLE={role}\nPEER=http://other:8089\n")
        self.fo.DRILL = root / "no-drill"
        self.fo.time = types.SimpleNamespace(time=lambda: self.clock[0])
        self.fo._get, self.fo._run = self._get, self._run
        (root / "logs" / "beats.log").write_text("", encoding="utf-8")
        (root / "logs" / "downloads.log").write_text("", encoding="utf-8")

    def _get(self, url, seconds):
        if "cloudflare.com" in url or "discord.com" in url:
            return "ok" if self.internet else None
        if "8088" in url:
            return "ok"
        if "20241" in url:
            return '{"readyConnections":4}' if self.internet and "cloudflared" in self.units else None
        if not self.link_up or not self.peer.link_up:
            return None
        health = self.peer.fo.OUT / "health.json"
        return health.read_text(encoding="utf-8") if health.exists() else None

    def _run(self, *cmd, timeout):
        import types
        code = 0
        if cmd[:2] == ("systemctl", "is-active"):
            code = 0 if cmd[-1] in self.units else 3
        elif cmd[:2] == ("systemctl", "stop"):
            self.units.discard(cmd[-1])
            self.stops.append(cmd[-1])
        elif cmd[:2] == ("systemctl", "start") and cmd[-1] != "metallic-live.service":
            self.units.add(cmd[-1])
        return types.SimpleNamespace(returncode=code, stdout="")

    def live_run(self):
        """metallic-live, when its timer is on: adds one sample to the history it finds and writes everything."""
        import os
        if "metallic-live.timer" not in self.units:
            return
        live = self.fo.LIVE_DIR
        try:
            samples = json.loads((live / ".revivals-history.json").read_text(encoding="utf-8"))["samples"]
        except OSError:
            samples = []
        samples = samples + [self.clock[0]] if self.internet else samples  # no internet, no new number
        doc = json.dumps({"samples": samples, "totals": {"withNumbers": 3}})
        for name in self.fo.MIRRORED:
            (live / name).write_text(doc, encoding="utf-8")
            os.utime(live / name, ns=(int(self.clock[0] * 1e9), int(self.clock[0] * 1e9)))

    def text(self, name=".revivals-history.json"):
        return (self.fo.LIVE_DIR / name).read_text(encoding="utf-8")


def test_failover_a_whole_outage_and_return_shows_one_history_and_no_copy_steps_out_for_a_healthy_peer(tmp_path):
    clock = [1_800_000_000.0]
    a, b = _Copy(tmp_path, "primary", clock), _Copy(tmp_path, "standby", clock)
    a.peer, b.peer = b, a

    def minutes(n):
        for _ in range(n * 4):  # every 15 s; metallic-live every 2 minutes
            clock[0] += 15
            if int(clock[0] - 1_800_000_000) % 120 == 0:
                a.live_run()
                b.live_run()
            a.fo.main()
            b.fo.main()
        for copy in (a, b, a):  # a mirror is at most one check behind
            copy.fo.main()

    a.live_run()
    a.fo.main()
    b.fo.main()
    minutes(6)
    assert "metallic-live.timer" not in b.units, "one writer while the primary is well"
    assert a.text() == b.text(), "the standby mirrors everything, history included"
    assert {"cloudflared"} <= a.units and {"cloudflared"} <= b.units and not a.stops.count("cloudflared") and not b.stops.count("cloudflared"), \
        "both connectors stay up"

    # the primary's link dies; the LAN still works, as it did on 11-05 and 11-06
    a.internet = False
    before = json.loads(a.text())["samples"]
    minutes(6)
    assert "metallic-live.timer" in b.units and "metallic-live.timer" not in a.units, "the standby writes, the primary mirrors"
    assert "cloudflared" in b.units, "the standby never stopped"
    assert a.text() == b.text(), "the primary keeps up over the LAN"
    assert len(json.loads(b.text())["samples"]) >= len(before) + 2

    # the link comes back: the primary is up to date already and takes the writing back
    a.internet = True
    minutes(6)
    assert "metallic-live.timer" in a.units and "metallic-live.timer" not in b.units
    assert "cloudflared" in a.units and "cloudflared" in b.units and "cloudflared" not in b.stops
    assert a.text() == b.text()
    samples = json.loads(a.text())["samples"]
    assert samples == sorted(samples) and max(y - x for x, y in zip(samples, samples[1:])) <= 240, "no hole in the history"
    assert all(a.text(n) == b.text(n) for n in a.fo.MIRRORED)

    # the primary is gone altogether, LAN too: the standby has it all and goes on
    a.link_up = False
    last = samples[-1]
    minutes(3)
    assert "metallic-live.timer" in b.units and "cloudflared" in b.units
    assert json.loads(b.text())["samples"][-1] > last
