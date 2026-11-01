"""End-to-end check of a deployed Metallic API next to Metallic accounts, run INSIDE the container.

    python3 e2e.py --api https://127.0.0.1:8476 --api-fingerprint <sha256> --accounts https://127.0.0.1:8475 \
                   --accounts-fingerprint <sha256> --config /etc/metallic-api/api.toml

Registers throwaway accounts e2e_api<random>_a/_b/_t (random passwords, never printed) in the real accounts service,
makes a throwaway server key with the CLI, and drives everything through the generated Python SDK: sign-in calls
forwarded to accounts, scoped tokens, minors' privacy, server keys, rate limits, signed webhooks + retries + delivery
log, CORS. deploy.sh e2e removes the throwaway accounts, keys, webhooks and heartbeats afterwards.
Exit 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
import secrets
import ssl
import subprocess
import sys
import threading
import time

from metallic_api import MetallicAPI, MetallicAPIError, verify_webhook

RESULTS: list[tuple[str, bool]] = []


def check(name: str, cond: bool, note: str = "") -> None:
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({note})" if note else ""), flush=True)


def raw(base: str, fp: str, method: str, path: str, body: dict | None = None, headers: dict | None = None):
    """Plain HTTPS call with a pinned certificate (for header checks the SDK hides)."""
    host, port = base.split("//")[1].split(":")
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, int(port), timeout=10, context=ctx)
    conn.connect()
    assert hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() == fp, "certificate mismatch"
    h = dict(headers or {})
    data = None
    if body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    conn.request(method, path, data, h)
    r = conn.getresponse()
    out = r.read()
    conn.close()
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    return r.status, hdrs, (json.loads(out) if out and hdrs.get("content-type", "").startswith("application/json") else out)


def refused(fn, status: int, code: str | None = None) -> bool:
    try:
        fn()
    except MetallicAPIError as e:
        return e.status == status and (code is None or e.code == code)
    return False


class Receiver:
    def __init__(self, fail_first: int = 0):
        self.got: list[tuple[dict, bytes]] = []
        self.fail_left = fail_first
        rec = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if rec.fail_left > 0:
                    rec.fail_left -= 1
                    self.send_response(500)
                else:
                    rec.got.append(({k.lower(): v for k, v in self.headers.items()}, body))
                    self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/hook"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def wait(self, n: int, seconds: float = 15) -> bool:
        end = time.time() + seconds
        while time.time() < end and len(self.got) < n:
            time.sleep(0.2)
        return len(self.got) >= n


def main() -> int:
    ap = argparse.ArgumentParser()
    for a in ("--api", "--api-fingerprint", "--accounts", "--accounts-fingerprint", "--config"):
        ap.add_argument(a, required=True)
    a = ap.parse_args()
    api_fp, acc_fp = a.api_fingerprint.lower(), a.accounts_fingerprint.lower()
    anon = MetallicAPI(a.api, fingerprint=api_fp)

    # ---- public ----
    h = anon.health()
    check("health: service up, accounts reachable", h["ok"] and h["accounts"] == "up")
    doc = anon.get_openapi()
    check("openapi 3.1 document served", doc["openapi"].startswith("3.1") and "/v1/friends" in doc["paths"])
    code, hdr, _ = raw(a.api, api_fp, "GET", "/docs")
    check("docs page served as HTML", code == 200 and hdr["content-type"].startswith("text/html"))
    games = anon.list_games()["games"]
    check("games: RC MC RB PX", [g["id"] for g in games] == ["RC", "MC", "RB", "PX"])
    rel = anon.list_releases()["channels"]
    check("releases: channels listed honestly", {c["channel"] for c in rel} == {"stable", "beta"},
          ", ".join(f"{c['channel']}={c['state']}" for c in rel))
    px = anon.get_progress()
    check("progress: public mode", px["mode"] == "public" and len(px["projects"]) >= 5)
    st = anon.get_project_status()["projects"]
    check("Litha/STAR status", [p["id"] for p in st] == ["litha", "star"])
    check("news via accounts", isinstance(anon.list_news(limit=3)["news"], list))
    code, hdr, _ = raw(a.api, api_fp, "GET", "/v1/games", headers={"Origin": "https://example.org"})
    check("public GET open to web pages (CORS *)", code == 200 and hdr.get("access-control-allow-origin") == "*")

    # ---- real accounts: three throwaway players ----
    tag = "e2e_api" + secrets.token_hex(3)
    tokens = {}
    for suffix, band in (("a", "adult"), ("b", "adult"), ("t", "teen")):
        code, _, out = raw(a.accounts, acc_fp, "POST", "/v1/register", {
            "username": f"{tag}_{suffix}", "password": secrets.token_urlsafe(18), "age_band": band})
        tokens[suffix] = out["access_token"] if code == 201 else None
    check("three e2e accounts registered", all(tokens.values()))
    A, B, T = (MetallicAPI(a.api, tokens[k], fingerprint=api_fp) for k in "abt")
    me = A.get_me()
    check("sign-in token forwarded: /v1/me", me["username"] == f"{tag}_a" and me["minor"] is False)
    code, _, body = raw(a.api, api_fp, "GET", "/v1/me", headers={"Authorization": "Bearer " + tokens["a"],
                                                                 "Origin": "https://evil.example"})
    check("signed-in call from a web page refused", code == 403 and body["error"] == "browser_refused")
    check("normal player cannot make server keys", refused(lambda: A.create_key({"name": "e2e x",
                                                                                 "scopes": ["servers:write"]}), 403))

    # ---- server key (CLI) + webhook receiver ----
    keyfile = f"/var/lib/metallic-api/e2e-key-{tag}"
    subprocess.run([sys.executable, "-m", "metallic.api", "key", "create", "--config", a.config, "--name",
                    f"e2e {tag}", "--scopes", "servers:write,players:read,webhooks:manage", "--games", "RC,RB",
                    "--rate", "30", "--out", keyfile], check=True, capture_output=True)
    with open(keyfile, encoding="utf-8") as fh:
        key = fh.read().strip()
    os.unlink(keyfile)
    S = MetallicAPI(a.api, key, fingerprint=api_fp)
    rx = Receiver()
    hook = S.create_webhook({"url": rx.url, "events": ["player.joined", "friend.added", "ping"],
                             "description": f"e2e {tag}"})
    check("webhook created, secret shown once", hook["secret"].startswith("whsec_")
          and "secret" not in json.dumps(S.list_webhooks()))
    S.ping_webhook(hook["id"])
    ok = rx.wait(1)
    hdrs, body = rx.got[0] if ok else ({}, b"")
    check("ping delivered with a valid HMAC signature", ok and verify_webhook(hook["secret"],
                                                                             hdrs.get("metallic-signature", ""), body))

    # ---- friends + presence through the API (real accounts) ----
    A.send_friend_request({"username": f"{tag}_b"})
    out = B.accept_friend_request(f"{tag}_a")
    check("friend request accepted through the API", out.get("state") == "friends")
    ok = rx.wait(2)
    ev = json.loads(rx.got[1][1]) if ok else {}
    check("friend.added webhook: account ids only", ok and ev.get("type") == "friend.added"
          and sorted(ev["data"]["accounts"]) == sorted([A.get_me()["id"], B.get_me()["id"]])
          and tag not in json.dumps(ev))
    B.set_presence({"status": "playing", "game": "RC"})
    seen = {f["username"]: f["presence"] for f in A.list_presence()["friends"]}
    check("presence: friend sees 'playing RC'", seen.get(f"{tag}_b", {}).get("game") == "RC")

    # ---- scoped tokens ----
    tok = anon.exchange_token({"subject_token": tokens["a"], "scope": "friends:read", "client_name": f"e2e {tag}"})
    SC = MetallicAPI(a.api, tok["access_token"], fingerprint=api_fp)
    check("scoped token reads friends", len(SC.list_friends()["friends"]) == 1)
    check("scoped token cannot set presence", refused(lambda: SC.set_presence({"status": "online"}), 403,
                                                      "insufficient_scope"))
    anon.revoke_token({"token": tok["access_token"]})
    check("revoked scoped token refused", refused(SC.list_friends, 401))
    check("admin scopes are never delegated", refused(lambda: anon.exchange_token(
        {"subject_token": tokens["a"], "scope": "keys:admin"}), 403))

    # ---- minors ----
    check("teen cannot give friends:read to another app", refused(lambda: anon.exchange_token(
        {"subject_token": tokens["t"], "scope": "friends:read", "client_name": f"e2e {tag}"}), 403, "minor_privacy"))
    tt = anon.exchange_token({"subject_token": tokens["t"], "scope": "profile:read", "client_name": f"e2e {tag}"})
    check("teen may give profile:read", MetallicAPI(a.api, tt["access_token"], fingerprint=api_fp).get_me()["minor"])
    who = S.verify_player({"player_token": tokens["t"]})
    check("server sees a teen without a name", who["active"] and who["minor"] is True and who["username"] is None)
    who_a = S.verify_player({"player_token": tokens["a"]})
    check("server sees an adult's username", who_a["username"] == f"{tag}_a")
    S.server_event({"type": "player.joined", "game": "RC", "server_id": f"e2e-{tag}", "player_token": tokens["t"],
                    "players": 1})
    ok = rx.wait(3)
    ev = json.loads(rx.got[2][1]) if ok else {}
    check("player.joined for a teen carries no name", ok and ev.get("type") == "player.joined"
          and ev["data"]["player"]["username"] is None and ev["data"]["player"]["minor"] is True
          and f"{tag}_t" not in json.dumps(ev))

    # ---- server key limits ----
    S.server_heartbeat({"game": "RC", "server_id": f"e2e-{tag}", "players": 5})
    rc = anon.get_game("RC")
    check("heartbeat counted in game status", rc["servers"]["online"] >= 1 and rc["servers"]["players"] >= 5)
    check("key refused for a game it is not for", refused(lambda: S.server_heartbeat(
        {"game": "MC", "server_id": f"e2e-{tag}", "players": 1}), 403, "wrong_game"))
    check("server key refused on player endpoints", refused(S.list_friends, 403, "wrong_credential"))
    hit, retry = None, None
    for i in range(25):
        try:
            S.server_heartbeat({"game": "RC", "server_id": f"e2e-{tag}", "players": 5})
        except MetallicAPIError as e:
            hit, retry = (i, e.retry_after) if e.status == 429 else (None, None)
            break
    check("per-key rate limit (30/min) answers 429 + Retry-After", hit is not None and retry and retry >= 1,
          f"after {hit} calls, retry {retry}s")

    # ---- retries + delivery log ----
    time.sleep(8)             # let the key's rate bucket refill (0.5 per second)
    rx2 = Receiver(fail_first=1)
    hook2 = S.create_webhook({"url": rx2.url, "events": ["ping"], "description": f"e2e {tag} retry"})
    S.ping_webhook(hook2["id"])
    time.sleep(3)
    log = S.list_deliveries(hook2["id"])["deliveries"]
    check("failed delivery is logged and scheduled for retry", log and log[0]["status"] == "retrying"
          and log[0]["http_status"] == 500, log[0]["status"] if log else "no log")
    ok = rx2.wait(1, seconds=20)
    log = S.list_deliveries(hook2["id"])["deliveries"]
    check("retry delivered 10 s later, same event id", ok and log[0]["status"] == "delivered"
          and log[0]["attempt"] == 2)
    for hid in (hook["id"], hook2["id"]):
        S.delete_webhook(hid)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
