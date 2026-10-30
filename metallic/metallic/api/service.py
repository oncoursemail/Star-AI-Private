"""Request handling: route by the OpenAPI document, check auth + scopes + rate limits, validate input, then either
forward to accounts as the player (x-metallic-upstream) or run a handler named after the operationId."""
from __future__ import annotations

import json
import time
import urllib.parse

from . import spec as spec_mod
from .auth import ApiError, Auth, Principal, RateLimiter
from .upstream import UpstreamError

VERSION = "1.0.0"
DEFAULT_RATES = {"anonymous": (60, 30), "user": (120, 60)}
PUBLIC_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "RateLimit-Limit, "
               "RateLimit-Remaining, Retry-After"}


class Api:
    def __init__(self, store, accounts, content, webhooks, sealer, clock=time.time, spec: spec_mod.Spec | None = None,
                 allowed_origins: tuple[str, ...] = (), docs_html: bytes | None = None):
        self.s, self.accounts, self.content, self.webhooks, self.clock = store, accounts, content, webhooks, clock
        self.spec = spec or spec_mod.Spec()
        self.auth = Auth(store, accounts, sealer, clock)
        self.limiter = RateLimiter(clock)
        self.allowed_origins = set(allowed_origins)
        self.docs_html = docs_html
        self._spec_bytes = json.dumps(self.spec.doc, separators=(",", ":")).encode()
        self.handlers = {name[3:]: getattr(self, name) for name in dir(self) if name.startswith("op_")}

    # ---------- HTTP entry ----------
    def handle(self, method: str, path: str, headers: dict, body: bytes, ip: str) -> tuple[int, dict, bytes]:
        extra: dict = {}
        try:
            return self._handle(method, path, headers, body, ip, extra)
        except ApiError as e:
            if e.status == 429 and "retry_after" in e.extra:
                extra["Retry-After"] = str(max(1, int(round(e.extra["retry_after"]))))
            return e.status, {"Content-Type": "application/json", **extra, **e.headers}, \
                json.dumps(e.body(), separators=(",", ":")).encode()

    def _handle(self, method, path, headers, body, ip, extra):
        url = urllib.parse.urlsplit(path)
        route = url.path.rstrip("/") or "/"
        origin = headers.get("origin")
        if method == "GET" and route == "/docs" and self.docs_html is not None:
            return 200, {"Content-Type": "text/html; charset=utf-8", "Content-Security-Policy":
                         "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"}, \
                self.docs_html
        lookup = "GET" if method in ("OPTIONS", "HEAD") else method
        op, params, allowed = self.spec.match(lookup, route)
        if method == "OPTIONS":
            return self._preflight(route, origin, headers)
        if op is None:
            if allowed:
                raise ApiError(405, "method_not_allowed", f"Use {', '.join(sorted(set(allowed)))}.",
                               {"Allow": ", ".join(sorted(set(allowed)))})
            raise ApiError(404, "not_found", "No such endpoint.")
        if origin:
            if op.public and method == "GET":
                extra.update(PUBLIC_CORS)
            elif origin in self.allowed_origins:
                extra.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin"})
            else:
                raise ApiError(403, "browser_refused", "Signed-in calls from web pages are not allowed from this site.")

        try:
            p = self.auth.principal(headers.get("authorization"), ip)
        except ApiError:
            self._rate(Principal("anonymous", "ip:" + ip), op, ip, extra)    # bad tokens still cost the caller's IP
            raise
        self._rate(p, op, ip, extra)
        self.auth.require(p, op.security)

        typed = {k: self.spec.coerce_param(next(x for x in op.params if x["name"] == k), urllib.parse.unquote(v))
                 for k, v in params.items()}
        query = {}
        qs = urllib.parse.parse_qs(url.query)
        for prm in op.params:
            if prm["in"] == "query" and prm["name"] in qs:
                query[prm["name"]] = self.spec.coerce_param(prm, qs[prm["name"]][0])
        req = self._body(op, headers, body)
        ctx = {"p": p, "path": typed, "query": query, "body": req, "ip": ip, "op": op}
        if op.op_id in self.handlers:
            status, out = self.handlers[op.op_id](ctx)
        else:
            status, out = op.success, self._forward(op, ctx)
        data = out if isinstance(out, bytes) else json.dumps(out, separators=(",", ":")).encode()
        return status, {"Content-Type": "application/json", **extra}, data

    def _preflight(self, route, origin, headers):
        op, _, allowed = self.spec.match("GET", route)
        if not allowed:
            raise ApiError(404, "not_found", "No such endpoint.")
        if op is not None and op.public and (headers.get("access-control-request-method") or "GET") == "GET":
            return 204, {**PUBLIC_CORS, "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "600"}, b""
        if origin in self.allowed_origins:
            return 204, {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                         "Access-Control-Allow-Methods": ", ".join(sorted(set(allowed))),
                         "Access-Control-Allow-Headers": "Authorization, Content-Type",
                         "Access-Control-Max-Age": "600"}, b""
        raise ApiError(403, "browser_refused", "Signed-in calls from web pages are not allowed from this site.")

    def _rate(self, p: Principal, op, ip: str, extra: dict) -> None:
        if p.kind == "key":
            per, burst, key = p.rate, max(1, p.rate // 2), "key:" + p.id
        else:
            per, burst = DEFAULT_RATES[p.kind]
            key = p.owner_ref
        checks = [(key, per, burst)]
        if op.rate:      # per-operation bucket (e.g. token exchange), charged per client IP and per caller
            checks.append((f"op:{op.op_id}:ip:{ip}", op.rate["per_minute"], op.rate["burst"]))
        for k, per_min, b in checks:
            ok, remaining, wait = self.limiter.allow(k, per_min, b)
            extra["RateLimit-Limit"], extra["RateLimit-Remaining"] = str(per_min), str(remaining)
            if not ok:
                raise ApiError(429, "slow_down", "Too many requests. Wait a moment and try again.", retry_after=wait)

    def _body(self, op, headers, body: bytes):
        if op.body_schema is None:
            return None
        if not body and not op.body_required:
            return None
        if not (headers.get("content-type") or "").startswith("application/json"):
            raise ApiError(415, "bad_request", "Send JSON (Content-Type: application/json).")
        try:
            req = json.loads(body or b"null")
        except ValueError as exc:
            raise ApiError(400, "bad_request", "The request is not valid JSON.") from exc
        try:
            self.spec.validate(req, op.body_schema)
        except spec_mod.Invalid as exc:
            raise ApiError(400, "bad_request", str(exc).capitalize() + ".") from exc
        return req

    def _forward(self, op, ctx) -> dict:
        """Call accounts as the player, with the player's own sign-in token."""
        up = op.upstream
        path = up["path"].format(**{k: urllib.parse.quote(str(v), safe="") for k, v in ctx["path"].items()})
        body = dict(ctx["body"] or {}) if up["method"] == "POST" else None
        for name in up.get("body_from_path", []):
            body[name] = ctx["path"][name]
        try:
            return self.accounts.call(up["method"], path, body, token=ctx["p"].upstream_token)
        except UpstreamError as exc:
            status = exc.status if 400 <= exc.status < 600 else 502
            raise ApiError(status, exc.code, exc.text, **exc.extra) from exc

    # ---------- public ----------
    def op_health(self, ctx):
        return 200, {"ok": True, "service": "metallic-api", "version": VERSION,
                     "accounts": "up" if self.accounts.health() else "down"}

    def op_getOpenapi(self, ctx):
        return 200, self._spec_bytes

    def op_listScopes(self, ctx):
        return 200, {"scopes": [{"name": k, **{f: v[f] for f in ("kind", "minors", "description")}}
                                for k, v in self.spec.scopes.items()]}

    def op_listNews(self, ctx):
        q = ctx["query"]
        qs = urllib.parse.urlencode({k: v for k, v in (("game", q.get("game")), ("limit", q.get("limit"))) if v})
        key = "news?" + qs
        try:
            return 200, self.content.cache.get(key, 30, self.clock(),
                                               lambda: self.accounts.call("GET", "/v1/news" + (f"?{qs}" if qs else "")))
        except UpstreamError as exc:
            raise ApiError(502, "accounts_unreachable", "News is not available right now.") from exc

    def op_listGames(self, ctx):
        return 200, {"games": self.content.games()}

    def op_listRevivals(self, ctx):
        return 200, self.content.revivals.list()

    def op_getRevival(self, ctx):
        return 200, self.content.revivals.get(ctx["path"]["revival"])

    def op_getGame(self, ctx):
        return 200, self.content.game(ctx["path"]["game"])

    def op_listReleases(self, ctx):
        return 200, self.content.list_releases()

    def op_getRelease(self, ctx):
        return 200, self.content.release(ctx["path"]["channel"])

    def op_getProgress(self, ctx):
        return 200, self.content.progress()

    def op_getProjectProgress(self, ctx):
        return 200, self.content.project_progress(ctx["path"]["project"])

    def op_getProjectStatus(self, ctx):
        return 200, {"projects": self.content.project_status()}

    # ---------- auth ----------
    def op_exchangeToken(self, ctx):
        b = ctx["body"]
        return 200, self.auth.exchange(b["subject_token"], b["scope"], b.get("client_name"), ctx["ip"])

    def op_revokeToken(self, ctx):
        return 200, self.auth.revoke(ctx["body"]["token"], ctx["ip"])

    # ---------- account extras ----------
    def op_acceptFriendRequest(self, ctx):
        out = self._forward(ctx["op"], ctx)
        if out.get("state") == "friends":
            p, name = ctx["p"], ctx["path"]["username"].lower()
            try:
                friends = self.accounts.call("GET", "/v1/friends", token=p.upstream_token)["friends"]
                other = next((f["id"] for f in friends if f["username"].lower() == name), None)
            except (UpstreamError, KeyError):
                other = None
            if other:
                self.webhooks.emit("friend.added", {"accounts": sorted([p.id, other])})
        return 200, out

    # ---------- servers ----------
    def _games_of(self, owner: str):
        kind, _, oid = owner.partition(":")
        if kind != "key":
            return None
        row = self.s.one("SELECT games FROM keys WHERE id=?", (oid,))
        return json.loads(row["games"]) if row else []

    def op_serverHeartbeat(self, ctx):
        p = ctx["p"]
        return 200, self.content.heartbeat(p.id, p.games, ctx["body"])

    def _player(self, token: str | None) -> dict | None:
        if not token:
            return None
        try:
            info = self.accounts.introspect(token, now=self.clock())
        except UpstreamError:
            return None
        if not info.get("active"):
            return None
        minor = bool(info.get("minor"))
        return {"account_id": info["sub"], "username": None if minor else info.get("name"), "minor": minor}

    def op_serverEvent(self, ctx):
        p, b = ctx["p"], ctx["body"]
        if b["game"] not in p.games:
            raise ApiError(403, "wrong_game", f"This key is not for {b['game']}.")
        who = self._player(b.get("player_token"))
        if b.get("player_token") and who is None:
            raise ApiError(400, "bad_player_token", "The player's sign-in token is not valid.")
        player = {"account_id": None, "username": None, "minor": None, "ref": b.get("player_ref")}
        if who:
            player.update(who)
        eid, n = self.webhooks.emit(b["type"], {"game": b["game"], "server_id": b["server_id"],
                                                "players": b.get("players"), "player": player},
                                    games_of=self._games_of)
        self.s.audit(self.clock(), "server_event", True, p.owner_ref, ctx["ip"], type=b["type"], game=b["game"])
        return 202, {"ok": True, "event_id": eid, "deliveries": n}

    def op_verifyPlayer(self, ctx):
        who = self._player(ctx["body"]["player_token"])
        if who is None:
            return 200, {"active": False}
        return 200, {"active": True, "id": who["account_id"], "username": who["username"], "minor": who["minor"]}

    # ---------- webhooks ----------
    def op_listWebhooks(self, ctx):
        return 200, {"webhooks": self.webhooks.list(ctx["p"].owner_ref)}

    def op_createWebhook(self, ctx):
        b = ctx["body"]
        return 201, self.webhooks.create(ctx["p"].owner_ref, b["url"], b["events"], b.get("description"))

    def op_deleteWebhook(self, ctx):
        return 200, self.webhooks.delete(ctx["p"].owner_ref, ctx["path"]["webhook_id"])

    def op_listDeliveries(self, ctx):
        return 200, {"deliveries": self.webhooks.deliveries(ctx["p"].owner_ref, ctx["path"]["webhook_id"],
                                                            ctx["query"].get("limit", 50))}

    def op_pingWebhook(self, ctx):
        wid = ctx["path"]["webhook_id"]
        self.webhooks.deliveries(ctx["p"].owner_ref, wid, 1)          # 404 unless it is the caller's
        eid, n = self.webhooks.emit("ping", {"webhook": wid}, only=wid)
        return 202, {"ok": True, "event_id": eid, "deliveries": n}

    # ---------- keys ----------
    def op_listKeys(self, ctx):
        return 200, {"keys": self.auth.list_keys()}

    def op_createKey(self, ctx):
        b = ctx["body"]
        return 201, self.auth.create_key(b["name"], b["scopes"], b.get("games"), b.get("rate_per_minute"),
                                         ctx["p"].owner_ref)

    def op_revokeKey(self, ctx):
        return 200, self.auth.revoke_key(ctx["path"]["key_id"], ctx["p"].owner_ref)
