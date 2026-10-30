"""Latest news from the Rec Room revivals (public GET /v1/revival-news). Same sources and rules as the launcher's
news.rs: public RSS/Atom feeds (YouTube channels included) and JSON news APIs read without signing in, each asked at
most every 15 minutes; a source that fails keeps its last items; links must be https and titles are plain text."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from datetime import datetime
import html
import json
import re
import threading

# revival id, label, url, kind ("feed" or "json"), and for json: items path, title, date, link, image keys, link base
SOURCES: tuple = (
    ("radium", "Blog", "https://blog.recroomarchive.org/rss/", "feed"),
    ("recflare", "Release", "https://github.com/recflare/client/releases.atom", "feed"),
    ("phoenix", "YouTube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCVL4rv82WsVzlZB4raB5kVw", "feed"),
    ("recquiem", "YouTube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCpSwNW2bQJyoqRmgSnkoBtg", "feed"),
    ("spookdux", "YouTube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCWUzuZiAl2K2ibkN2e6KByA", "feed"),
    ("stella", "YouTube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCIytQ_oFcsehw0Ygpa0lxFQ", "feed"),
    ("vanilla", "Event", "https://vanillarec.net/api.php?path=%2Fapi%2Fwebsite%2Fevents%2Fupcoming%3Fcount%3D10", "json", "results", "name", "startTime", "id", "imageUrl", "https://vanillarec.net/events/?id={}"),
    ("vanilla", "Launcher update", "https://api.vanillarec.net/launcher/manifest", "json", "", "notes", "pub_date", "", "", "https://vanillarec.net/"),
)
TTL, PER_SOURCE, MAX_ITEMS = 900.0, 4, 40
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="

_ENTRY = re.compile(r"<(item|entry)\b.*?</(?:item|entry)>", re.S)
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S)
_LINK_RSS = re.compile(r"<link>(.*?)</link>", re.S)
_LINK_ATOM = re.compile(r'<link\b[^>]*?href="([^"]+)"')
_DATE = re.compile(r"<(?:pubDate|published|updated|dc:date)>(.*?)</", re.S)
_IMAGE = re.compile(r'<(?:media:thumbnail|media:content|enclosure)\b[^>]*?url="([^"]+)"')
_YT = re.compile(r"<yt:videoId>([\w-]{6,20})</yt:videoId>")
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
_TAG = re.compile(r"<[^>]*>", re.S)


def text(s: str) -> str:
    s = _TAG.sub(" ", _CDATA.sub(r"\1", s))
    return " ".join(html.unescape(s).split())


def parse_date(s) -> int | None:
    s = str(s).strip()
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except (TypeError, ValueError, IndexError):
        pass
    return (int(s) // 1000 if int(s) > 100_000_000_000 else int(s)) if s.isdigit() else None


def _https(u: str | None) -> str | None:
    u = (u or "").strip()
    return u if u.startswith("https://") and not any(c.isspace() for c in u) else None


def parse_feed(body: str) -> list[dict]:
    out = []
    for m in list(_ENTRY.finditer(body))[:PER_SOURCE]:
        e = m.group(0)
        t = _TITLE.search(e)
        link = _LINK_RSS.search(e) or _LINK_ATOM.search(e)
        link = _https(text(link.group(1))) if link else None
        if not t or not link or not text(t.group(1)):
            continue
        d = _DATE.search(e)
        yt, img = _YT.search(e), _IMAGE.search(e)
        image = f"https://i.ytimg.com/vi/{yt.group(1)}/hqdefault.jpg" if yt else (_https(text(img.group(1))) if img else None)
        out.append({"title": text(t.group(1)), "date": parse_date(text(d.group(1))) if d else None, "link": link, "image": image})
    return out


_YT_TITLE = re.compile(r'"lockupMetadataViewModel":\{"title":\{"content":"((?:[^"\\]|\\.)*)"')
_YT_ID = re.compile(r"i\.ytimg\.com/vi/([\w-]{11})/")
_YT_AGE = re.compile(r'"content":"((?:(?:\d+|a|an) (?:second|minute|hour|day|week|month|year)s?|\d+(?:s|m|h|d|w|mo|y)) ago)"')
_UNITS = {"second": 1, "": 1, "minute": 60, "m": 60, "min": 60, "hour": 3600, "h": 3600, "hr": 3600, "day": 86400, "d": 86400,
          "week": 604800, "w": 604800, "wk": 604800, "month": 2592000, "mo": 2592000, "year": 31536000, "y": 31536000, "yr": 31536000}


def age_seconds(s: str) -> int | None:
    """"3 days ago", "an hour ago", or YouTube's short "9d ago" / "1mo ago" -> seconds (months 30 days, years 365)."""
    m = re.fullmatch(r"\s*(\d+|a|an)\s*([a-z]*?)s?\s+ago\s*", s)
    if not m or m.group(2) not in _UNITS:
        return None
    n = 1 if m.group(1) in ("a", "an") else int(m.group(1))
    return n * _UNITS[m.group(2)]


def parse_youtube_page(page: str, now: float) -> list[dict]:
    """A channel's public videos page -> items, for when its RSS feed fails (often). Dates come from "9d ago"."""
    out = []
    for block in page.split('"lockupViewModel":{')[1:]:
        t, vid = _YT_TITLE.search(block), _YT_ID.search(block)
        if not t or not vid:
            continue
        try:
            title = json.loads('"' + t.group(1) + '"')
        except ValueError:
            continue
        age = _YT_AGE.search(block)
        secs = age_seconds(age.group(1)) if age else None
        out.append({"title": text(title), "date": int(now - secs) if secs is not None else None,
                    "link": f"https://www.youtube.com/watch?v={vid.group(1)}",
                    "image": f"https://i.ytimg.com/vi/{vid.group(1)}/hqdefault.jpg"})
        if len(out) >= PER_SOURCE:
            break
    return out


def _dig(v, path: str):
    for part in [p for p in path.split(".") if p]:
        if isinstance(v, dict):
            v = v.get(part)
        elif isinstance(v, list) and part.isdigit() and int(part) < len(v):
            v = v[int(part)]
        else:
            return None
    return v


def parse_json(body: str, items: str, title: str, date: str, link: str, image: str, base: str) -> list[dict]:
    try:
        doc = json.loads(body)
    except ValueError:
        return []
    lst = _dig(doc, items) if items else doc
    if isinstance(lst, dict):                      # one object is one item (a launcher manifest's notes)
        lst = [lst]
    if not isinstance(lst, list):
        return []

    def s(it, p):
        v = _dig(it, p) if p else None
        return str(v) if isinstance(v, (str, int)) and not isinstance(v, bool) else None

    def absolute(u):
        if u and "{}" in base:
            return base.replace("{}", u)
        return base + u if u and u.startswith("/") and base else u
    out = []
    for it in lst[:PER_SOURCE]:
        t, ln = s(it, title), (_https(base) if not link else _https(absolute(s(it, link))))
        if not t or not ln or not text(t):
            continue
        d = s(it, date)
        out.append({"title": text(t), "date": parse_date(d) if d else None, "link": ln,
                    "image": _https(s(it, image)) if image else None})
    return out


class RevivalNews:
    def __init__(self, clock, fetch, sources=None):
        self.clock, self.fetch = clock, fetch
        self.sources = SOURCES if sources is None else sources
        self._cache: dict[int, tuple[float, list]] = {}
        self._lock = threading.Lock()

    def _get(self, url):
        try:
            code, body = self.fetch(url)
        except Exception:                   # noqa: BLE001  (try again next time)
            return None
        return body if 200 <= code < 300 else None

    def _ask(self, src) -> list | None:
        body = self._get(src[2])
        items = (parse_feed(body) if src[3] == "feed" else parse_json(body, *src[4:10])) if body is not None else None
        if not items and src[2].startswith(YT_FEED):        # YouTube's feeds fail often: read the channel's videos page
            page = self._get("https://www.youtube.com/channel/" + src[2][len(YT_FEED):] + "/videos")
            items = parse_youtube_page(page, self.clock()) if page else None
        return items

    def list(self) -> dict:
        now = self.clock()
        with self._lock:
            due = [i for i in range(len(self.sources)) if now - self._cache.get(i, (-1e18, None))[0] >= TTL]
            if due:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    got = list(zip(due, pool.map(lambda i: self._ask(self.sources[i]), due)))
                for i, items in got:
                    if items:
                        self._cache[i] = (now, items)
                    else:
                        self._cache[i] = (now, self._cache.get(i, (0, []))[1])     # keep the last items
            out = [{**it, "revival": self.sources[i][0], "source": self.sources[i][1]}
                   for i, (_, items) in self._cache.items() for it in items]
        out.sort(key=lambda it: -(it["date"] or 0))
        return {"items": out[:MAX_ITEMS], "sources": len(self.sources), "checked_at": int(now)}
