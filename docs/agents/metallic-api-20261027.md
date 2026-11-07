# metallic-api-20261027 (board #279, Claude sub-agent): Metallic API v1, internal (step 1 of 2)

Branch `star/metallic-api-20261027` (app repo, worktree `worktrees/metallic-api`), based on
`star/metallic-px-updater-site-20261026` 3c2a09ff (it needs launcher/updates + launcher/px). Built ON Metallic accounts
(board #278): no accounts code is copied or edited; the API talks to accounts over HTTPS like any client.

## What it is
- Stdlib service `metallic-api` (`python -m metallic.api serve --config F`), code `metallic/metallic/api/`.
- `openapi.json` (OpenAPI 3.1) is the source of truth: routes, parameters, request schemas, required scopes
  (`security`), per-operation rate overrides (`x-metallic-rate`) and forwards to accounts (`x-metallic-upstream`) are
  read from it at start; the service refuses to start when the document and handlers disagree (`spec.check`).
- Resources: me/profile, friends (+ requests), presence, invites (forwarded to accounts as the player); news (accounts,
  cached 30 s); games RC/MC/RB/PX (roadmap state counts, live server heartbeats, optional health probe, release
  version); releases (signed PX channel files, Ed25519-verified with launcher/updates; a channel that fails verification
  is a 503, never "verified"); progress (launcher/px public mode + scrub); Litha/STAR status (roadmap + optional probe).
- Auth (`auth.py`): accounts sign-in JWT = first-party (all user scopes; owner/admin also keys:admin, webhooks:manage),
  checked with accounts `/v1/introspect` (cached 60 s, never past exp). Scoped tokens `mtk_` via
  `POST /v1/oauth/token` (RFC 8693-style exchange): only granted scopes, <= 15 min and <= the sign-in token, revocable;
  the sign-in token is stored AES-GCM-sealed so calls still reach accounts AS the player (sign-out, blocks and minors'
  rules stay accounts' job). Server keys `msk_<id>_<secret>` (SHA-256 digest stored): scopes servers:write /
  players:read / webhooks:manage, a games list, own rate limit.
- Minors private by default: scoped tokens for minors only `profile:read`; servers/webhooks never get a minor's
  username (account id + `minor: true` only); friend.added carries account ids only, for everyone.
- Rate limits: anonymous 60/min burst 30 per IP, user 120/min per account, keys per key; token exchange 10/min per IP;
  bad tokens are charged to the caller's IP. Headers RateLimit-Limit/-Remaining, 429 + Retry-After.
- Webhooks (`webhooks.py`): events player.joined, player.left, release.published, friend.added, ping. HMAC-SHA256
  `Metallic-Signature: t=..,v1=..` over "t.body"; retries 0/10 s/1 min/5 min/30 min/2 h then failed; delivery log per
  webhook; no redirects; private/loopback targets refused unless in `webhook_allow_hosts` (re-checked at send time).
- CORS: public GETs open to any origin; signed-in calls from web pages refused unless `allowed_origins`.
- SDKs generated from the spec (`python -m metallic.api.sdkgen`, `--check` in tests): `metallic/sdk/python/metallic_api.py`
  (stdlib, pinned-fingerprint TLS), `metallic/sdk/js/metallic-api.mjs` (fetch, WebCrypto verifyWebhook),
  `metallic/sdk/luau/MetallicApi.luau` (HttpService, server-only assert, key from `HttpService:GetSecret`, only
  public + server-key operations). Examples in each `examples/`. Static docs page `metallic/metallic/api/docs/index.html`
  (served at `/docs`, phone-width checked).

## Where it runs (LIVE test, since 2026-10-27 ~01:12Z)
- Same LXD container as accounts: `metallic-accounts-test` on brain 1, service `metallic-api.service` (user mapi,
  MemoryMax 96M, Nice 10, ProtectSystem=strict), HTTPS port 8476, self-signed cert (SAN LAN IP, metallic-api.local,
  127.0.0.1); fingerprint in `~/.star/metallic-api-fingerprint`. Accounts reached at https://127.0.0.1:8475 with its
  pinned fingerprint. Code /opt/metallic-api/app (+ previous), secrets /etc/metallic-api, db /var/lib/metallic-api.
- Idle: 21.6 MB RAM. Deploy/undo from the PC: `MA_B1=user@brain1 MA_CT=metallic-accounts-test bash server/api/deploy.sh
  setup|install|secrets|e2e|key NAME SCOPES [GAMES]|status|rollback|remove` (remove touches only the API's files).
- Relies on accounts' `rate_limit_exempt = ["127.0.0.1"]` (API applies its own limits) and introspect fields
  sub/name/role/minor/exp: told the accounts lane in msg #514.

## Verified (RAN)
- `metallic/tests/test_api_v1.py`: 32 passed (OpenAPI 3.1 meta-schema validation with jsonschema + spec/handler check,
  every response validated against its declared schema, auth/scopes, scoped token expiry/revoke, admin scopes not
  delegable, keys + games + revocation + forged secret, rate limits (key, anon, token exchange, bad tokens), minors,
  webhook signing/replay window/retries/failure/log/SSRF/game filter, friend.added ids only, releases verified/tampered/
  empty trust, release.published on sequence growth, progress/status, upstream client cache, Python SDK + JS SDK (node)
  + Luau SDK (Lune 0.11.1 with a HttpService shim; set LUNE_BIN, skipped otherwise) against a local server, launcher PX
  via API + fallback, website downloads path). Also tests/test_metallic_site.py + test_metallic_px.py still green.
- Container e2e (`deploy.sh e2e`, real accounts, throwaway e2e_api* accounts/keys/webhooks removed after): 33/33.
- From the PC over the LAN: health 142 ms incl. TLS, wrong pin refused, bad token 401.
- Website downloads page in a browser: with /api proxied (shows "Signature checked by the Metallic server") and without
  (falls back to the channel file); both list the test release correctly.

## Launcher + website: which modules use the API
Switched (safe, with fallbacks):
- `metallic-site/src/assets/downloads.js`: asks `/api/v1/releases/<ch>` first, falls back to the channel file
  (HOSTING.md has the Caddy `/api` proxy for the public read endpoints only).
- `launcher/px/service.py`: settings `"px": {"api": "<url>", "apiFingerprint": "<sha256>"}` -> GET /v1/progress (no
  forge token on PCs); falls back to the local roadmap build. Uses `launcher/metallic_api.py` (generated SDK copy).
To switch (launcher agent owns these files; uncommitted edits there now):
- `launcher/web/js/main.js` news widget (`data/news.json`) -> a bridge slot calling SDK `list_news()` (pinned TLS, so via
  Python, not page fetch).
- `launcher/games.py` PX `page_url` (GitHub Pages) -> internal PX view; game cards can show `/v1/games` players/servers.
Stay as they are on purpose: `launcher/updates` (installs must verify signatures locally; the API is display-only),
accounts sign-in/refresh/2FA (accounts' own native flow; API v1 has no login), `rb.py` (Roblox's public APIs),
`rc/backend.py` (local 127.0.0.1 backend).

## Not done / next (step 2 and owner)
- Public developer access: third-party app registration, consent screen, refresh for scoped tokens, per-app keys,
  developer portal hosting the docs page. Internet exposure: only the read endpoints via the site proxy for now.
- Real certificate + DNS name (same paths), promotion with accounts out of -test.
- No release is published yet (owner signing key step from the PX lane), so /v1/releases shows "missing" honestly.
- DNS-rebinding window between the webhook URL check and the connect (re-checked per attempt; pinning the resolved
  address is a step-2 hardening). Webhook secrets are sealed with the data key; key loss = re-create webhooks.
- RC backend (Codex) may use POST /v1/players/verify with a server key instead of verifying JWKS itself (optional).

## Log
- 00:39Z read brief/accounts/PX notes; claimed #279; msg #514 to all (plan + accounts dependencies).
- ~01:05Z service + spec + tests green locally (32); ~01:12Z deployed; e2e 33/33.
