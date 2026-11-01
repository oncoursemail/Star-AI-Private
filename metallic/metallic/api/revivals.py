"""Rec Room revivals: who is up and how many people are on (public GET /v1/revivals and /v1/revivals/{revival}).

Numbers come from each revival's public Discord invite (approximate_presence_count = people online in its Discord now,
approximate_member_count = members). Players in game are only reported where a revival publishes them without a sign-in
(Vanilla's /ws/getplrcount, RecFlare's /api/stats/online); a Discord number is never counted as players. Meta Quest
store pages give rating, ratings, build and release date (read every 6 hours). Where a revival has a public address
that answers when its servers are up, it is checked as well. Discord is asked at most every 2 minutes,
the servers every minute; a failed ask keeps the last good numbers, marked stale. The runtime records one sample per
revival every 5 minutes (kept 7 days) for the 24-hour trend and peak. Same list as the launcher's revivals.rs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
import urllib.error
import urllib.request

from .auth import ApiError

# id, name, blurb, era, platforms, Discord invite, website, server check, JSON key of a version there, path to players
# in game there (only RecFlare publishes one), launcher RC client key (unused here)
CATALOG = (
    ("vanilla", "Vanilla", "Relive the golden age of Rec Room for free. Publishes its live player count.", "2021", "PC", "vanillarec", "https://vanillarec.net", "https://api.vanillarec.net/launcher/manifest", "version", "https://api.vanillarec.net/ws/getplrcount", ".", "https://www.meta.com/experiences/1381979951661831/", ""),
    ("radium", "Radium", "A fan-made revival and archive of classic Rec Room, from the Rec Room Archive.", "Early 2021", "PC", "radium-rr", "https://www.recroomarchive.org", "", "", "", "", "", ""),
    ("meownet", "MeowNet", "meow.net, a community Rec Room revival with its own meowii.app site. Early access on Meta Quest.", "", "PC · Quest", "recnet", "https://meowii.app", "", "", "", "", "https://www.meta.com/experiences/meownet/1196298696890609/", "meownet"),
    ("stella", "Stella", "Early access. Emulates Rec Room's old servers, made by one developer.", "2023", "PC · Quest", "stella-rr", "", "", "", "", "", "https://www.meta.com/experiences/stella/9155565161163227/", ""),
    ("phoenix", "Phoenix", "Rec Room rebuilt on rewritten source code.", "2023", "PC", "mNnhYjtq9u", "", "", "", "", "", "", ""),
    ("recify", "Recify", "A 2021 Rec Room revival bringing OG Rec Room back, on PC and Quest.", "2021", "PC · Quest", "pQhWgQgCC", "", "", "", "", "", "", ""),
    ("recflare", "RecFlare", "Open-source RecNet rewrite running in the cloud. Publishes its live player count.", "2023 · 2026", "PC · Quest", "recflare", "https://www.recflare.net", "", "", "https://www.recflare.net/api/stats/online?range=24h", "online", "", ""),
    ("recplace", "RecPlace", "A revival made in loving memory of Rec Room, 2016-2026.", "2023", "PC · PCVR", "recplace", "", "", "", "", "", "", ""),
    ("studio87", "Studio 87", "A community tribute to Rec Room with its own recroom.network site.", "", "", "studio87", "https://recroom.network", "", "", "", "", "", ""),
    ("epicquest", "EpicQuest", "A private Rec Room server, public since 2021.", "2021", "", "s6e56prqWB", "", "", "", "", "", "", ""),
    ("rebornrec", "RebornRec", "Old Rec Room: the 2016, 2017, 2018 and 2020 builds.", "2016-2020", "", "CgJd7trbG9", "", "", "", "", "", "", ""),
    ("remix", "Remix", "A revival of the August 19, 2025 Rec Room build.", "2025", "", "remixrec", "", "", "", "", "", "", ""),
    ("spookdux", "Spookdux", "A 2021 Rec Room revival, formerly called Redux.", "2021", "", "pnetFyr6br", "https://reduxvr.net", "", "", "", "", "", ""),
    ("enum", "Enum", "A 2026 Rec Room revival.", "2026", "", "enum", "", "", "", "", "", "", ""),
    ("kittyrec", "KittyRec", "A 2018 decompilation with custom content and Quest support.", "2018", "PC · Quest", "kittyrec", "", "", "", "", "", "", ""),
    ("yanvar", "Yanvar", "January 2017 Rec Room, ported to Quest headsets.", "2017", "Quest", "XJjMy2fW5t", "", "", "", "", "", "", ""),
    ("recquiem", "Recquiem", "Rec Room builds from 2017 to 2023.", "2017-2023", "", "recquiem2019", "", "", "", "", "", "", ""),
    ("lithium", "Lithium", "The 2018, 2023 and 2025 Rec Room builds.", "2018 · 2023 · 2025", "", "ma53bPpmKE", "", "", "", "", "", "", ""),
    ("reczone", "RECZONE", "A from-scratch Rec Room remake with no original assets.", "", "", "reczone", "", "", "", "", "", "", ""),
    ("rebound", "Rebound", "A 2025 Rec Room revival.", "2025", "", "Sx7yBv48HA", "", "", "", "", "", "", ""),
    ("n3xi0m", "N3XI0M", "A work-in-progress 2020 and 2022 Rec Room revival.", "2020 · 2022", "", "9bFfM7Ppsz", "", "", "", "", "", "", ""),
    ("uranium", "Uranium", "A 2025 Rec Room revival for PC by Otisdub and Stungspore. No public Discord yet.", "2025", "PC", "", "https://uranium.rechatvr.com", "", "", "", "", "", ""),
    ("nexanet", "NexaNet", "A community revival with a modified client and its own launcher. Its Discord invite is gone.", "", "PC", "", "", "", "", "", "", "", "nexanet"),
)
IDS = tuple(c[0] for c in CATALOG)
DISCORD_TTL, CHECK_TTL, META_TTL, SAMPLE_KEEP = 120.0, 60.0, 6 * 3600.0, 7 * 86400
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9", "Sec-Fetch-Dest": "document",
           "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1", "Upgrade-Insecure-Requests": "1",
           "sec-ch-ua": '"Chromium";v="141", "Not?A_Brand";v="8"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"'}
UA = "Metallic-API/1 (revival status)"


def _get(url: str, timeout: float = 6.0) -> tuple[int, str]:
    """GET -> (status, body). Raises only when nothing answered."""
    store = url.startswith(("https://www.meta.com/", "https://www.youtube.com/channel/"))   # public pages that want a browser
    req = urllib.request.Request(url, headers=BROWSER if store else {"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read((4 if store else 1) << 20).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def _cdn(kind: str, gid: str, h: str | None, size: int) -> str | None:
    return f"https://cdn.discordapp.com/{kind}/{gid}/{h}.webp?size={size}" if h else None


def parse_invite(status: int, body: str) -> dict:
    if status == 404:
        return {"ok": False, "gone": True}
    try:
        d = json.loads(body)
        g, online, members = d["guild"], int(d["approximate_presence_count"]), int(d["approximate_member_count"])
    except (ValueError, KeyError, TypeError):
        return {"ok": False}
    gid = str(g.get("id", ""))
    return {"ok": True, "online": online, "members": members, "guild": g.get("name"), "description": g.get("description"),
            "icon": _cdn("icons", gid, g.get("icon"), 128), "banner": _cdn("banners", gid, g.get("banner"), 640),
            "splash": _cdn("splashes", gid, g.get("splash"), 640)}


def count_at(doc, path: str) -> int | None:
    """A number read by a dotted path: `a.b` walks objects, `*` sums the rest of the path over a list, and a path that
    ends on a list counts its items (same rules as the launcher's revivals.rs count_at)."""
    parts = [x for x in path.split(".") if x]
    cur = doc
    for i, part in enumerate(parts):
        if part == "*":
            rest = ".".join(parts[i + 1:])
            if not isinstance(cur, list):
                return None
            if not rest:
                return len(cur)
            return sum(n for n in (count_at(item, rest) for item in cur) if n is not None)
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
        if cur is None:
            return None
    if isinstance(cur, bool):
        return None
    if isinstance(cur, (int, float)):
        return int(cur) if cur >= 0 else None
    if isinstance(cur, list):
        return len(cur)
    return None


def parse_check(answer: tuple[int, str] | None, version_at: str, players_at: str = "") -> dict:
    if answer is None:
        return {"ok": False, "detail": "no answer"}
    code, body = answer
    if not 200 <= code < 300:
        return {"ok": False, "detail": f"answered {code}"}
    try:
        doc = json.loads(body)
    except ValueError:
        doc = None
    v = doc.get(version_at) if version_at and isinstance(doc, dict) else None
    return {"ok": True, "version": v if isinstance(v, str) else None,
            "players": count_at(doc, players_at) if players_at and doc is not None else None}


_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_AGG = re.compile(r'"quality_rating_aggregate":([0-9.]+)')
_CNT = re.compile(r'"quality_rating_count":(\d+)')
_VER = re.compile(r'"latest_supported_binary":\{"__typename":"AndroidBinary"[^}]*?"version":"([^"]{1,40})"')
_REL = re.compile(r'"release_info":\{"display_date":"([^"]{1,40})"')


def parse_meta(page: str) -> dict:
    """A Meta Quest store page -> rating (its JSON-LD), ratings, version and release date (first app record)."""
    out = {"rating": None, "ratings": None, "version": None, "released": None}
    for m in _LD.finditer(page):
        try:
            doc = json.loads(m.group(1))
        except ValueError:
            continue
        for n in doc.get("@graph", [doc]) if isinstance(doc, dict) else []:
            if "SoftwareApplication" in json.dumps(n.get("@type")):
                a = n.get("aggregateRating") or {}
                try:
                    out["rating"] = round(float(a["ratingValue"]), 2)
                    out["ratings"] = int(float(a["ratingCount"]))
                except (KeyError, TypeError, ValueError):
                    pass
    if out["rating"] is None and _AGG.search(page) and _CNT.search(page):
        out["rating"], out["ratings"] = round(float(_AGG.search(page).group(1)), 2), int(_CNT.search(page).group(1))
    for key, rx in (("version", _VER), ("released", _REL)):
        m = rx.search(page)
        out[key] = m.group(1) if m else None
    return out


def trend(points: list[tuple[float, int]], now: float, slots: int = 48) -> tuple[list[list[int]], int | None]:
    """The highest value in each of `slots` slices of the last 24 hours, and the 24-hour peak."""
    start = now - 86400
    recent = [(t, n) for t, n in points if t >= start]
    if not recent:
        return [], None
    best: dict[int, tuple[float, int]] = {}
    for t, n in recent:
        k = min(slots - 1, int((t - start) / (86400 / slots)))
        if k not in best or n > best[k][1]:
            best[k] = (t, n)
    return [[int(t), n] for t, n in (best[k] for k in sorted(best))], max(n for _, n in recent)


class Revivals:
    def __init__(self, store, clock, fetch=_get):
        self.s, self.clock, self.fetch = store, clock, fetch
        self._discord: dict[str, tuple[float, dict]] = {}
        self._checks: dict[str, tuple[float, dict]] = {}
        self._metas: dict[str, tuple[float, dict | None]] = {}
        self._lock = threading.Lock()       # one refresh at a time; readers wait for it instead of asking again

    def _ask_discord(self, invite: str) -> dict:
        try:
            return parse_invite(*self.fetch(f"https://discord.com/api/v10/invites/{invite}?with_counts=true"))
        except Exception:                   # noqa: BLE001  (any network failure: try again next time)
            return {"ok": False}

    def _get_or_none(self, url):
        try:
            return self.fetch(url)
        except Exception:                   # noqa: BLE001  (nothing answered)
            return None

    def _ask_check(self, c) -> dict:
        """Status and version from the check; players from the players address, or from the check itself."""
        check, version_at, players_url, players_at = c[7], c[8], c[9], c[10]
        out = parse_check(self._get_or_none(check), version_at, "" if players_url else players_at) if check else None
        if players_url:
            p = parse_check(self._get_or_none(players_url), "", players_at)
            out = out or {"ok": p["ok"], "version": None}
            out["players"] = p.get("players")
        return out

    def _ask_meta(self, url: str) -> dict | None:
        got = self._get_or_none(url)
        m = parse_meta(got[1]) if got and 200 <= got[0] < 300 else None
        return m if m and m["rating"] is not None else None     # Meta sometimes answers with an empty shell

    def refresh(self) -> None:
        now = self.clock()
        with self._lock:
            want_d = [c for c in CATALOG if c[5] and now - self._discord.get(c[0], (-1e18, None))[0] >= DISCORD_TTL]
            want_c = [c for c in CATALOG if (c[7] or c[9]) and now - self._checks.get(c[0], (-1e18, None))[0] >= CHECK_TTL]
            want_m = [c for c in CATALOG if c[11] and now - self._metas.get(c[0], (-1e18, None))[0] >= META_TTL]
            if not want_d and not want_c and not want_m:
                return
            with ThreadPoolExecutor(max_workers=8) as pool:
                got_d = list(zip([c[0] for c in want_d], pool.map(lambda c: self._ask_discord(c[5]), want_d)))
                got_c = list(zip([c[0] for c in want_c], pool.map(self._ask_check, want_c)))
                got_m = list(zip([c[0] for c in want_m], pool.map(lambda c: self._ask_meta(c[11]), want_m)))
            for rid, v in got_d:
                old = self._discord.get(rid)
                if not v["ok"] and "gone" not in v and old and old[1]["ok"]:
                    self._discord[rid] = (now, {**old[1], "stale": True})
                else:
                    self._discord[rid] = (now, v)
            for rid, v in got_c:
                self._checks[rid] = (now, v)
            for rid, v in got_m:      # a page that did not answer keeps its last numbers and is asked again in 5 minutes
                self._metas[rid] = (now if v else now - META_TTL + 300, v or self._metas.get(rid, (0, None))[1])

    def sample(self) -> int:
        """Record every revival's fresh online count (the runtime calls this every 5 minutes). Returns rows written."""
        self.refresh()
        now = self.clock()
        rows = [(rid, now, d["online"], d["members"]) for rid, (_, d) in self._discord.items() if d["ok"] and not d.get("stale")]
        rows += [(f"{rid}#players", now, c["players"], 0) for rid, (_, c) in self._checks.items() if c.get("players") is not None]
        for r in rows:
            self.s.x("INSERT INTO revival_samples (id, t, online, members) VALUES (?,?,?,?)", r)
        self.s.x("DELETE FROM revival_samples WHERE t < ?", (now - SAMPLE_KEEP,))
        return len(rows)

    def _item(self, c, now: float) -> dict:
        rid, name, blurb, era, platforms, invite, website = c[:7]
        d = self._discord.get(rid, (0, None))[1]
        chk = self._checks.get(rid, (0, None))[1]
        live = d if d and d["ok"] else None
        if chk is not None:
            status = "answering" if chk["ok"] else "not_answering"
        elif live:
            status = "community"
        elif d and d.get("gone"):
            status = "invite_gone"
        else:
            status = "unknown"
        def history(key):
            return trend([(r["t"], r["online"]) for r in self.s.q(
                "SELECT t, online FROM revival_samples WHERE id=? AND t>=? ORDER BY t", (key, now - 86400))], now)
        points, peak = history(rid)
        ppoints, ppeak = history(f"{rid}#players")
        return {"id": rid, "name": name, "blurb": blurb, "era": era, "platforms": platforms,
                "invite": f"https://discord.gg/{invite}" if invite else None, "website": website or None,
                "status": status, "version": (chk or {}).get("version"),
                "discord": {k: v for k, v in live.items() if k != "ok"} if live else None,
                "trend": points, "peak_24h": peak, "players": (chk or {}).get("players"),
                "players_trend": ppoints, "players_peak_24h": ppeak,
                "meta": {**(self._metas.get(rid, (0, None))[1] or {}), "url": c[11]} if c[11] else None}

    def list(self) -> dict:
        self.refresh()
        now = self.clock()
        items = sorted((self._item(c, now) for c in CATALOG), key=lambda i: -(i["discord"]["online"] if i["discord"] else -1))
        counted = [i for i in items if i["discord"]]
        return {"checked_at": int(now), "revivals": items, "totals": {
            "revivals": len(items), "with_numbers": len(counted), "online": sum(i["discord"]["online"] for i in counted),
            "members": sum(i["discord"]["members"] for i in counted),
            "answering": sum(1 for i in items if i["status"] == "answering"),
            "in_game": sum(i["players"] for i in items if i["players"] is not None),
            "with_players": sum(1 for i in items if i["players"] is not None)}}

    def get(self, rid: str) -> dict:
        if rid not in IDS:
            raise ApiError(404, "not_found", "No such revival.")
        return next(i for i in self.list()["revivals"] if i["id"] == rid)
