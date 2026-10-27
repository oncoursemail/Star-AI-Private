"""Signed webhook deliveries with retries and a delivery log.

Body: {"id": "evt_...", "type": "player.joined", "created": <unix>, "data": {...}}
Headers: Metallic-Event, Metallic-Delivery, Metallic-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>
Retries: attempt 1 at once, then after 10 s, 1 min, 5 min, 30 min, 2 h; then the delivery is marked failed. Any 2xx is
success. Redirects are not followed. Targets on private, loopback or link-local addresses are refused unless the host is
in `allow_hosts` (internal step 1 uses LAN game servers on purpose)."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import secrets
import socket
import threading
import urllib.parse

from .auth import ApiError, new_id

EVENTS = ("player.joined", "player.left", "release.published", "friend.added", "ping")
BACKOFF = (0, 10, 60, 300, 1800, 7200)
MAX_PER_OWNER = 10


def sign(secret: str, body: bytes, t: int) -> str:
    mac = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, header: str, body: bytes, now: float, tolerance: int = 300) -> bool:
    """Reference check for receivers (the SDKs do the same)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(now - t) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, t), f"t={t},v1={parts.get('v1', '')}")


def http_sender(url: str, headers: dict, body: bytes, timeout: float = 5.0) -> tuple[int | None, str | None]:
    u = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    try:
        conn = cls(u.hostname, u.port, timeout=timeout)
        try:
            conn.request("POST", (u.path or "/") + (f"?{u.query}" if u.query else ""), body, headers)
            resp = conn.getresponse()
            resp.read(4096)
            return resp.status, None
        finally:
            conn.close()
    except (OSError, http.client.HTTPException) as exc:
        return None, type(exc).__name__


class Webhooks:
    def __init__(self, store, sealer, clock, sender=http_sender, allow_hosts: tuple[str, ...] = (),
                 resolver=socket.getaddrinfo):
        self.s, self.sealer, self.clock, self.sender = store, sealer, clock, sender
        self.allow_hosts = {h.lower() for h in allow_hosts}
        self.resolver = resolver
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- target policy ----------
    def check_url(self, url: str) -> None:
        u = urllib.parse.urlsplit(url)
        host = (u.hostname or "").lower()
        if u.scheme not in ("https", "http") or not host or u.username or u.password:
            raise ApiError(400, "bad_url", "The webhook URL must be http(s)://host/path without a user name.")
        if host in self.allow_hosts:
            return
        if u.scheme != "https":
            raise ApiError(400, "bad_url", "Webhook URLs must use https.")
        try:
            addrs = {ai[4][0] for ai in self.resolver(host, u.port or 443, proto=socket.IPPROTO_TCP)}
        except (OSError, UnicodeError) as exc:
            raise ApiError(400, "bad_url", "The webhook host does not resolve.") from exc
        for a in addrs:
            ip = ipaddress.ip_address(a.split("%")[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise ApiError(400, "bad_url", "Webhook URLs may not point at private or local addresses.")

    # ---------- management ----------
    def create(self, owner: str, url: str, events: list[str], description: str | None) -> dict:
        self.check_url(url)
        if any(e not in EVENTS for e in events):
            raise ApiError(400, "bad_request", f"Events are {', '.join(EVENTS)}.")
        if self.s.one("SELECT COUNT(*) n FROM webhooks WHERE owner=? AND deleted IS NULL", (owner,))["n"] >= MAX_PER_OWNER:
            raise ApiError(409, "limit", f"At most {MAX_PER_OWNER} webhooks each.")
        wid, secret = new_id("wh_", 16), "whsec_" + secrets.token_urlsafe(32)
        now = self.clock()
        self.s.x("INSERT INTO webhooks (id, owner, url, events, description, secret_sealed, created) VALUES (?,?,?,?,?,?,?)",
                 (wid, owner, url, json.dumps(sorted(set(events))), description or "", self.sealer.seal(secret, wid), now))
        self.s.audit(now, "webhook_create", True, owner, None, webhook=wid, events=sorted(set(events)))
        return {**self._row(self._get(owner, wid)), "secret": secret}

    def _get(self, owner: str, wid: str):
        row = self.s.one("SELECT * FROM webhooks WHERE id=? AND owner=? AND deleted IS NULL", (wid, owner))
        if row is None:
            raise ApiError(404, "not_found", "No such webhook.")
        return row

    @staticmethod
    def _row(r) -> dict:
        return {"id": r["id"], "url": r["url"], "events": json.loads(r["events"]), "description": r["description"] or "",
                "created": r["created"], "active": r["deleted"] is None}

    def list(self, owner: str) -> list[dict]:
        return [self._row(r) for r in self.s.q("SELECT * FROM webhooks WHERE owner=? AND deleted IS NULL "
                                               "ORDER BY created", (owner,))]

    def delete(self, owner: str, wid: str) -> dict:
        self._get(owner, wid)
        now = self.clock()
        self.s.x("UPDATE webhooks SET deleted=? WHERE id=?", (now, wid))
        self.s.x("UPDATE deliveries SET status='failed', error='webhook deleted', next_attempt=NULL "
                 "WHERE webhook=? AND status IN ('pending','retrying')", (wid,))
        self.s.audit(now, "webhook_delete", True, owner, None, webhook=wid)
        return {"ok": True}

    def deliveries(self, owner: str, wid: str, limit: int = 50) -> list[dict]:
        self._get(owner, wid)
        rows = self.s.q("SELECT * FROM deliveries WHERE webhook=? ORDER BY created DESC, rowid DESC LIMIT ?",
                        (wid, max(1, min(200, limit))))
        return [{"id": r["id"], "event": r["event"], "event_id": r["event_id"], "attempt": r["attempt"],
                 "status": r["status"], "http_status": r["http_status"], "error": r["error"], "created": r["created"],
                 "next_attempt": r["next_attempt"], "delivered": r["delivered"]} for r in rows]

    # ---------- events ----------
    def emit(self, event: str, data: dict, *, only: str | None = None, games_of=None) -> tuple[str, int]:
        """Queue `event` for every subscribed webhook (or just webhook `only`). `games_of(owner)` -> allowed games or
        None (all); used so a key for RC never receives MC events. Returns (event id, deliveries queued)."""
        now = self.clock()
        eid = new_id("evt_", 16)
        body = json.dumps({"id": eid, "type": event, "created": now, "data": data}, separators=(",", ":"))
        rows = self.s.q("SELECT * FROM webhooks WHERE deleted IS NULL" + (" AND id=?" if only else ""),
                        (only,) if only else ())
        n = 0
        for r in rows:
            if not only and event not in json.loads(r["events"]):
                continue
            allowed = games_of(r["owner"]) if games_of else None
            if allowed is not None and data.get("game") and data["game"] not in allowed:
                continue
            self.s.x("INSERT INTO deliveries (id, webhook, event_id, event, body, status, created, next_attempt) "
                     "VALUES (?,?,?,?,?,'pending',?,?)", (new_id("dlv_", 16), r["id"], eid, event, body, now, now))
            n += 1
        return eid, n

    def run_due(self, limit: int = 20) -> int:
        """Send what is due now. Returns how many attempts were made."""
        now = self.clock()
        rows = self.s.q("SELECT d.*, w.url, w.secret_sealed, w.id wid FROM deliveries d JOIN webhooks w ON w.id=d.webhook "
                        "WHERE d.status IN ('pending','retrying') AND d.next_attempt<=? AND w.deleted IS NULL "
                        "ORDER BY d.next_attempt LIMIT ?", (now, limit))
        for r in rows:
            body = r["body"].encode()
            attempt = r["attempt"] + 1
            t = int(self.clock())
            headers = {"Content-Type": "application/json", "User-Agent": "Metallic-Webhooks/1",
                       "Metallic-Event": r["event"], "Metallic-Delivery": r["id"],
                       "Metallic-Signature": sign(self.sealer.open(r["secret_sealed"], r["wid"]), body, t)}
            try:
                self.check_url(r["url"])           # re-checked at send time (DNS may have changed)
                status, error = self.sender(r["url"], headers, body)
            except ApiError as exc:
                status, error = None, exc.code
            done = self.clock()
            if status is not None and 200 <= status < 300:
                self.s.x("UPDATE deliveries SET attempt=?, status='delivered', http_status=?, error=NULL, "
                         "next_attempt=NULL, delivered=? WHERE id=?", (attempt, status, done, r["id"]))
            elif attempt >= len(BACKOFF):
                self.s.x("UPDATE deliveries SET attempt=?, status='failed', http_status=?, error=?, next_attempt=NULL "
                         "WHERE id=?", (attempt, status, error or f"HTTP {status}", r["id"]))
            else:
                self.s.x("UPDATE deliveries SET attempt=?, status='retrying', http_status=?, error=?, next_attempt=? "
                         "WHERE id=?", (attempt, status, error or f"HTTP {status}", done + BACKOFF[attempt], r["id"]))
        if rows:
            self.s.x("DELETE FROM deliveries WHERE created<? AND status IN ('delivered','failed')", (now - 30 * 86400,))
        return len(rows)

    def start(self, interval: float = 1.0) -> None:
        def loop():
            while not self._stop.wait(interval):
                try:
                    self.run_due()
                except Exception:          # noqa: BLE001  (a bad row must not stop deliveries for everyone)
                    pass
        self._thread = threading.Thread(target=loop, daemon=True, name="webhooks")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
