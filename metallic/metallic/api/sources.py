"""Read-only content: games status, release channels (signed PX updater files), PX progress, Litha/STAR status.

Release channels are verified with the launcher's own updater code (launcher/updates: Ed25519 trust list, manifest
validation); PX progress is built with launcher/px in public mode and scrubbed. Both packages ship next to this one
when deployed; without them those resources answer "not set up" instead of guessing.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import urllib.request

from .auth import ApiError

STATES = ("planned", "implemented", "tested", "accepted", "released")
GAME_CATALOG = {
    "RC": {"name": "Metallic RC", "project": "rc", "component": "rc"},
    "MC": {"name": "Metallic MC", "project": "mc", "component": "mc"},
    "RB": {"name": "Metallic RB", "project": "rb", "component": "rb"},
    "PX": {"name": "Metallic PX", "project": None, "component": None,
           "role": "Progress across every Metallic project"},
}
HEARTBEAT_TTL = 90


class _Cache:
    def __init__(self):
        self._d: dict = {}
        self._lock = threading.Lock()

    def get(self, key, ttl: float, now: float, make):
        with self._lock:
            hit = self._d.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = make()
        with self._lock:
            self._d[key] = (now, value)
        return value


def _probe(url: str, timeout: float = 3.0) -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Metallic-API/1"}),
                                    timeout=timeout) as r:
            return "up" if 200 <= r.status < 300 else "down"
    except Exception:              # noqa: BLE001  (any failure means "down" for a status probe)
        return "down"


class Content:
    def __init__(self, store, clock, conf: dict, probe=_probe):
        self.s, self.clock, self.conf, self.probe = store, clock, conf, probe
        self.cache = _Cache()
        self.channels = tuple(conf.get("channels", ("stable", "beta")))

    # ---------- roadmap / progress ----------
    def roadmap(self) -> dict:
        from launcher.px.build import load_roadmap
        path = self.conf.get("roadmap_file")
        return load_roadmap(Path(path) if path else None)

    def progress(self) -> dict:
        def make():
            try:
                from launcher.px import build as px
            except ImportError as exc:
                raise ApiError(503, "not_set_up", "Progress data is not set up on this server.") from exc
            forge = None
            if self.conf.get("forge_url"):
                token = ""
                if self.conf.get("forge_token_file"):
                    token = Path(self.conf["forge_token_file"]).read_text(encoding="utf-8").strip()
                forge = px.Forge(self.conf["forge_url"], token, self.conf.get("forge_org", "metallic"))
            data = px.build(self.roadmap(), forge, public=True,
                            now=datetime.fromtimestamp(self.clock(), timezone.utc))
            leaks = px.scrub(data)
            if leaks:
                raise ApiError(500, "scrub_failed", "Progress data held private-looking text; not served.")
            return data
        return self.cache.get("progress", float(self.conf.get("progress_ttl", 600)), self.clock(), make)

    def project_progress(self, pid: str) -> dict:
        for p in self.progress()["projects"]:
            if p["id"] == pid:
                return p
        raise ApiError(404, "not_found", "No project with that id.")

    # ---------- releases ----------
    def _read_channel(self, channel: str) -> dict:
        try:
            from launcher.updates.keys import TrustStore
            from launcher.updates.manifest import ManifestError, parse_time, validate_manifest
        except ImportError:
            return {"channel": channel, "state": "missing", "detail": "release channels are not set up here"}
        rel = f"channels/{channel}.json"
        try:
            if self.conf.get("releases_dir"):
                base = Path(self.conf["releases_dir"])
                data, sig = (base / rel).read_bytes(), (base / (rel + ".sig")).read_bytes()
            elif self.conf.get("releases_url"):
                from launcher.updates.sources import HttpSource
                src = HttpSource(self.conf["releases_url"], timeout=6.0, user_agent="Metallic-API/1")
                data, sig = src.read(rel), src.read(rel + ".sig")
            else:
                return {"channel": channel, "state": "missing", "detail": "no release source configured"}
        except OSError:
            return {"channel": channel, "state": "missing", "detail": "no manifest published"}
        try:
            trust = TrustStore.load(Path(self.conf["trust_file"]) if self.conf.get("trust_file") else None)
            signed_by = trust.verify(data, json.loads(sig))
            m = validate_manifest(json.loads(data), channel)
        except (ValueError, ManifestError) as exc:
            return {"channel": channel, "state": "unverified", "detail": str(exc)[:200]}
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        if parse_time(m["expires"]) <= now:
            return {"channel": channel, "state": "expired", "sequence": m["sequence"], "detail": "manifest expired"}
        comps = []
        for name, c in sorted(m["components"].items()):
            inst = c.get("installer")
            comps.append({"name": name, "version": c["version"], "platform": c.get("platform", ""),
                          "released": c.get("released", ""), "notes": c.get("notes", ""),
                          "min_launcher": c.get("min_launcher", ""),
                          "size": sum(int(f.get("size", 0)) for f in c.get("files", [])),
                          "installer": {k: inst[k] for k in ("path", "size", "sha256") if k in inst} if inst else None})
        return {"channel": channel, "state": "ok", "sequence": m["sequence"], "manifest": {
            "channel": channel, "sequence": m["sequence"], "issued": m["issued"], "expires": m["expires"],
            "verified": True, "signed_by": signed_by, "components": comps}}

    def channel_state(self, channel: str) -> dict:
        return self.cache.get(("ch", channel), float(self.conf.get("releases_ttl", 60)), self.clock(),
                              lambda: self._read_channel(channel))

    def list_releases(self) -> dict:
        out = []
        for ch in self.channels:
            st = self.channel_state(ch)
            out.append({k: st[k] for k in ("channel", "state", "sequence", "detail") if k in st})
        return {"channels": out}

    def release(self, channel: str) -> dict:
        if channel not in self.channels:
            raise ApiError(404, "not_found", "No such release channel.")
        st = self.channel_state(channel)
        if st["state"] == "ok":
            return st["manifest"]
        if st["state"] == "missing":
            raise ApiError(404, "not_published", f"Nothing is published on {channel} yet.")
        raise ApiError(503, "unverified", f"The {channel} channel failed verification and is not served "
                       f"({st.get('detail', '')}).")

    def watch_releases(self, emit) -> list[tuple[str, int]]:
        """Emit release.published for every channel whose verified sequence grew. First sight is recorded silently."""
        fired = []
        for ch in self.channels:
            st = self._read_channel(ch)
            self.cache.get(("ch", ch), 0, self.clock(), lambda st=st: st)
            if st["state"] != "ok":
                continue
            seq = st["sequence"]
            row = self.s.one("SELECT sequence FROM channels_seen WHERE channel=?", (ch,))
            if row is None or seq > row["sequence"]:
                self.s.x("INSERT INTO channels_seen VALUES (?,?,?) ON CONFLICT(channel) DO UPDATE SET "
                         "sequence=excluded.sequence, seen=excluded.seen", (ch, seq, self.clock()))
            if row is not None and seq > row["sequence"]:
                emit("release.published", {"channel": ch, "sequence": seq, "components": [
                    {"name": c["name"], "version": c["version"]} for c in st["manifest"]["components"]]})
                fired.append((ch, seq))
        return fired

    def _component_version(self, component: str | None) -> dict | None:
        if not component:
            return None
        for ch in self.channels:
            st = self.channel_state(ch)
            if st["state"] == "ok":
                for c in st["manifest"]["components"]:
                    if c["name"] == component:
                        return {"channel": ch, "component": component, "version": c["version"]}
        return None

    # ---------- games ----------
    def heartbeat(self, key_id: str, games: tuple, req: dict) -> dict:
        if req["game"] not in games:
            raise ApiError(403, "wrong_game", f"This key is not for {req['game']}.")
        self.s.x("INSERT INTO heartbeats VALUES (?,?,?,?,?,?,?) ON CONFLICT(game, server_id) DO UPDATE SET "
                 "key=excluded.key, players=excluded.players, max_players=excluded.max_players, "
                 "version=excluded.version, updated=excluded.updated",
                 (req["game"], req["server_id"], key_id, req["players"], req.get("max_players"), req.get("version"),
                  self.clock()))
        self.s.x("DELETE FROM heartbeats WHERE updated<?", (self.clock() - 86400,))
        return {"ok": True}

    def _service(self, game: str) -> dict:
        url = (self.conf.get("games", {}).get(game) or {}).get("health_url")
        if not url:
            return {"status": "unknown", "checked": None}
        now = self.clock()
        return self.cache.get(("svc", game), 60, now, lambda: {"status": self.probe(url), "checked": now})

    def games(self) -> list[dict]:
        try:
            projects = {p["id"]: p for p in self.roadmap()["projects"]}
        except Exception:          # noqa: BLE001  (no roadmap here: counts stay empty, never invented)
            projects = {}
        cutoff = self.clock() - HEARTBEAT_TTL
        live = {r["game"]: r for r in self.s.q(
            "SELECT game, COUNT(*) n, SUM(players) p, MAX(updated) u FROM heartbeats WHERE updated>=? GROUP BY game",
            (cutoff,))}
        out = []
        for gid, g in GAME_CATALOG.items():
            if g["project"]:
                items = projects.get(g["project"], {}).get("items", [])
                role = projects.get(g["project"], {}).get("role", "")
            else:
                items = [i for p in projects.values() for i in p["items"]]
                role = g["role"]
            counts = Counter(i["state"] for i in items)
            row = live.get(gid)
            out.append({"id": gid, "name": g["name"], "role": role,
                        "roadmap": {s: counts.get(s, 0) for s in STATES},
                        "servers": {"online": row["n"] if row else 0, "players": row["p"] if row else 0,
                                    "updated": row["u"] if row else None},
                        "service": self._service(gid), "release": self._component_version(g["component"])})
        return out

    def game(self, gid: str) -> dict:
        for g in self.games():
            if g["id"] == gid:
                return g
        raise ApiError(404, "not_found", "No such game.")

    # ---------- Litha / STAR ----------
    def project_status(self) -> list[dict]:
        projects = {p["id"]: p for p in self.roadmap()["projects"]}
        probes = self.conf.get("status_probes", {})
        out = []
        for pid in ("litha", "star"):
            p = projects.get(pid, {"name": pid.title(), "items": []})
            counts = Counter(i["state"] for i in p["items"])
            live = None
            if probes.get(pid):
                now = self.clock()
                live = self.cache.get(("live", pid), 60, now, lambda u=probes[pid], n=now: {"status": self.probe(u),
                                                                                              "checked": n})
            out.append({"id": pid, "name": p["name"], "states": {s: counts.get(s, 0) for s in STATES},
                        "next": [i["title"] for i in p["items"] if i["state"] in ("planned", "implemented")][:5],
                        "live": live, "release": (lambda r: {"channel": r["channel"], "version": r["version"]} if r
                                                  else None)(self._component_version("litha" if pid == "litha" else None))})
        return out
