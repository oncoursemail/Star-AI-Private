"""Rec Room revivals: who is up and how many people are on (public GET /v1/revivals and /v1/revivals/{revival}).

Numbers come from each revival's public Discord invite (approximate_presence_count = people online in its Discord now,
approximate_member_count = members). No revival publishes players in game, so neither does this. Where a revival has
a public address that answers when its servers are up, it is checked as well. Discord is asked at most every 2 minutes,
the servers every minute; a failed ask keeps the last good numbers, marked stale. The runtime records one sample per
revival every 5 minutes (kept 7 days) for the 24-hour trend and peak. Same list as the launcher's revivals.rs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import urllib.error
import urllib.request

from .auth import ApiError

# id, name, blurb, era, platforms, Discord invite, website, server check, JSON key holding a version there
CATALOG = (
    ("vanilla", "Vanilla", "Relive the golden age of Rec Room for free.", "2021", "PC", "vanillarec", "",
     "https://api.vanillarec.net/launcher/manifest", "version"),
    ("radium", "Radium", "A fan-made revival and archive of classic Rec Room.", "Early 2021", "PC", "radium-rr", "", "", ""),
    ("meownet", "MeowNet", "meow.net, a community Rec Room revival.", "", "", "recnet", "", "", ""),
    ("stella", "Stella", "Early access. Emulates Rec Room's old servers, made by one developer.", "2023", "PC · Quest",
     "stella-rr", "", "", ""),
    ("phoenix", "Phoenix", "Rec Room rebuilt on rewritten source code.", "2023", "PC", "mNnhYjtq9u", "", "", ""),
    ("recflare", "RecFlare", "Open-source RecNet rewrite running in the cloud.", "2023 · 2026", "PC · Quest", "recflare",
     "https://www.recflare.net", "https://www.recflare.net/api/config", ""),
    ("recplace", "RecPlace", "A revival made in loving memory of Rec Room, 2016-2026.", "2023", "PC · PCVR", "recplace",
     "", "", ""),
    ("epicquest", "EpicQuest", "A private Rec Room server, public since 2021.", "2021", "", "s6e56prqWB", "", "", ""),
    ("rebornrec", "RebornRec", "Old Rec Room: the 2016, 2017, 2018 and 2020 builds.", "2016-2020", "", "CgJd7trbG9",
     "", "", ""),
    ("campus", "Campus", "A community revival of Rec Room, started through its own launcher.", "", "PC", "",
     "https://camprec.net", "https://camprec.net", ""),
    ("nexanet", "NexaNet", "A community revival with a modified client and its own launcher.", "", "PC", "", "", "", ""),
    ("studio8", "Studio 8", "A community revival.", "", "", "", "", "", ""),
)
IDS = tuple(c[0] for c in CATALOG)
DISCORD_TTL, CHECK_TTL, SAMPLE_KEEP = 120.0, 60.0, 7 * 86400
UA = "Metallic-API/1 (revival status)"


def _get(url: str, timeout: float = 6.0) -> tuple[int, str]:
    """GET -> (status, body). Raises only when nothing answered."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(1 << 20).decode("utf-8", "replace")
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


def parse_check(answer: tuple[int, str] | None, version_at: str) -> dict:
    if answer is None:
        return {"ok": False, "detail": "no answer"}
    code, body = answer
    if not 200 <= code < 300:
        return {"ok": False, "detail": f"answered {code}"}
    version = None
    if version_at:
        try:
            v = json.loads(body).get(version_at)
            version = v if isinstance(v, str) else None
        except (ValueError, AttributeError):
            pass
    return {"ok": True, "version": version}


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
        self._lock = threading.Lock()       # one refresh at a time; readers wait for it instead of asking again

    def _ask_discord(self, invite: str) -> dict:
        try:
            return parse_invite(*self.fetch(f"https://discord.com/api/v10/invites/{invite}?with_counts=true"))
        except Exception:                   # noqa: BLE001  (any network failure: try again next time)
            return {"ok": False}

    def _ask_check(self, url: str, version_at: str) -> dict:
        try:
            return parse_check(self.fetch(url), version_at)
        except Exception:                   # noqa: BLE001
            return parse_check(None, version_at)

    def refresh(self) -> None:
        now = self.clock()
        with self._lock:
            want_d = [c for c in CATALOG if c[5] and now - self._discord.get(c[0], (-1e18, None))[0] >= DISCORD_TTL]
            want_c = [c for c in CATALOG if c[7] and now - self._checks.get(c[0], (-1e18, None))[0] >= CHECK_TTL]
            if not want_d and not want_c:
                return
            with ThreadPoolExecutor(max_workers=8) as pool:
                got_d = list(zip([c[0] for c in want_d], pool.map(lambda c: self._ask_discord(c[5]), want_d)))
                got_c = list(zip([c[0] for c in want_c], pool.map(lambda c: self._ask_check(c[7], c[8]), want_c)))
            for rid, v in got_d:
                old = self._discord.get(rid)
                if not v["ok"] and "gone" not in v and old and old[1]["ok"]:
                    self._discord[rid] = (now, {**old[1], "stale": True})
                else:
                    self._discord[rid] = (now, v)
            for rid, v in got_c:
                self._checks[rid] = (now, v)

    def sample(self) -> int:
        """Record every revival's fresh online count (the runtime calls this every 5 minutes). Returns rows written."""
        self.refresh()
        now = self.clock()
        rows = [(rid, now, d["online"], d["members"]) for rid, (_, d) in self._discord.items() if d["ok"] and not d.get("stale")]
        for r in rows:
            self.s.x("INSERT INTO revival_samples (id, t, online, members) VALUES (?,?,?,?)", r)
        self.s.x("DELETE FROM revival_samples WHERE t < ?", (now - SAMPLE_KEEP,))
        return len(rows)

    def _item(self, c, now: float) -> dict:
        rid, name, blurb, era, platforms, invite, website, check, _ = c
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
        pts = [(r["t"], r["online"]) for r in self.s.q(
            "SELECT t, online FROM revival_samples WHERE id=? AND t>=? ORDER BY t", (rid, now - 86400))]
        points, peak = trend(pts, now)
        return {"id": rid, "name": name, "blurb": blurb, "era": era, "platforms": platforms,
                "invite": f"https://discord.gg/{invite}" if invite else None, "website": website or None,
                "status": status, "version": (chk or {}).get("version"),
                "discord": {k: v for k, v in live.items() if k != "ok"} if live else None,
                "trend": points, "peak_24h": peak}

    def list(self) -> dict:
        self.refresh()
        now = self.clock()
        items = sorted((self._item(c, now) for c in CATALOG), key=lambda i: -(i["discord"]["online"] if i["discord"] else -1))
        counted = [i for i in items if i["discord"]]
        return {"checked_at": int(now), "revivals": items, "totals": {
            "revivals": len(items), "with_numbers": len(counted), "online": sum(i["discord"]["online"] for i in counted),
            "members": sum(i["discord"]["members"] for i in counted),
            "answering": sum(1 for i in items if i["status"] == "answering")}}

    def get(self, rid: str) -> dict:
        if rid not in IDS:
            raise ApiError(404, "not_found", "No such revival.")
        return next(i for i in self.list()["revivals"] if i["id"] == rid)
