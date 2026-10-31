# metallic-px-updater-site-20261026 (Claude sub-agent, board #277)

Branch `star/metallic-px-updater-site-20261026` from origin/star/next 0ee2701d, worktree `worktrees/metallic-px`.
Three pieces for the Metallic finish wave (docs/agents/WAVE-20261026-METALLIC.md). Nothing is published or deployed;
every test runs against a local folder or a local HTTP server.

## Files (all new; nothing of the launcher branch or of Codex's RC work was edited)
| Piece | Where |
|---|---|
| Update client, publisher, signing, server, CLI | `launcher/updates/` (`python -m launcher.updates -h`) |
| PX data builder + launcher service | `launcher/px/` (`build.py`, `service.py`, curated `roadmap.json`) |
| PX page (launcher view, site, standalone) | `launcher/web/px/` (`px.js`, `px.css`, `index.html`) |
| Public website, build script, hosting guide | `metallic-site/` (`src/`, `build.py`, `HOSTING.md`) |
| Tests | `tests/test_metallic_updates.py` (61), `tests/test_metallic_px.py`, `tests/test_metallic_site.py` |

`launcher/` has no `__init__.py` in this branch on purpose: the launcher branch owns it (namespace package until merged).

## 1. PX page
- Data = curated `launcher/px/roadmap.json` (five honest states: planned, implemented, tested, accepted, released, each with
  an evidence date, notes, blockers, dependencies) + the forge (milestones, releases, issue counts, weekly activity from
  real timestamps). No completion percentage anywhere; issue counts are labelled as tickets, not progress (spec section 18).
- Projects: RC, MC, RB, Litha, Launcher and site, STAR. **The roadmap states are my reading of the spec section 19, the RC
  `CURRENT-*.md` checkpoints and STATE.md; Codex/owner should correct `roadmap.json` when reality moves.**
- `python -m launcher.px --out px.json [--public] [--forge URL --token-file F]`. `--public` drops issue titles, release
  notes and private-repo numbers and scans the output for addresses, user names, tokens, keys and local paths (refuses to write).
- Charts: one stacked state bar per project (violet ramp, planned = hollow hatched, counts as direct labels, per-segment
  tooltip, keyboard focus), milestone bars, 12-week closed-issue bars with the busiest week and date axis, release list,
  changelog by month, definitions. Ramp checked with the dataviz validator (dark on #141419, light on #f4f4f7: pass).
  Seen in the browser at desktop and 390 px; no horizontal scroll.
- Text only enters through `textContent`; no inline style attributes (works under the site's strict CSP).

### Wiring into the launcher (the launcher agent owns app.py and the UI; I did not touch them)
1. `app.py` Bridge: `from .px.service import PxService`; in `__init__`: `self.px = PxService(store.root, self.settings)`;
   slot: `@Slot(bool, result=str) def pxData(self, refresh): return self.px.data(refresh)` (call it from a worker thread or
   accept the 15 s forge timeout; the cache makes repeat opens instant).
2. UI: add a view that loads `px/index.html` (it already detects QWebChannel and calls `bridge.pxData`), or call
   `MetallicPX.mount(el, async (refresh) => JSON.parse(await call("pxData", refresh)))` after loading `px/px.css` + `px/px.js`.
   Tokens `--ink --ink2 --ink3 --line --solid --hover --acc --warn --bad --ok` are picked up from the launcher CSS.
3. `games.py`: the `px` game currently opens a GitHub Pages URL; switch it to the internal view. Settings keys:
   `"px": {"forge": "", "tokenFile": "", "org": "metallic"}` (empty forge = roadmap only, page says so).
4. Updates (same pattern): `from .updates.service import UpdateService`; slots `updatesCheck() -> str`,
   `updatesInstall(name)`, `updatesRollback(name)` returning `json.dumps(service.check())` etc.; settings
   `"updates": {"url": "", "channel": "stable", "layout": "tree", "auto": "ask"}`. Empty url = "Updates are not set up yet".
   The service never raises. Progress events are plain dicts (stage checking/downloading/verifying/promoting/testing/done/failed,
   with done/total/percent from measured bytes) so they can be emitted through a Qt signal.

## 2. Update channel (`launcher/updates/`)
- **Signing:** Ed25519 (RFC 8032). `cryptography` is used when installed, else a pure-Python implementation (verifies in
  milliseconds, so the launcher needs no extra dependency); both are checked against the RFC 8032 vectors and each other.
  The signature covers a domain prefix + the exact manifest bytes (`channels/<name>.json` + `.sig`, detached).
- **Key location (owner):** `%USERPROFILE%\.metallic\release-signing-key.json` (env `METALLIC_RELEASE_KEY` overrides).
  `keygen` and every signing command refuse a path inside any git work tree, never overwrite a key, and restrict the file to
  the user (icacls). **I did NOT create the key**: the owner runs `python -m launcher.updates keygen --write-trust` once,
  backs the file up offline, and commits `launcher/updates/trust.json` (public key only; ships empty, so an unconfigured
  launcher refuses every update). Details in `metallic-site/HOSTING.md` section 5. Rotation: trust list holds several keys, any
  non-revoked one may sign; revoked keys are refused.
- **Manifest:** schema 1; per channel: `sequence` (monotonic), `issued`/`expires` (default 60 days), `blob_pattern`, components
  (`launcher`, `litha`, later rc/mc/rb) each with version, platform, `min_launcher`, `entry`, notes, files (path, size, sha256),
  optional `installer` (first-install file for the website), `revoked` versions. Paths are checked against traversal, absolute
  paths, backslashes, drive letters, Windows reserved names, case-insensitive duplicates.
- **Delta-friendly:** files are stored by hash (`blobs/aa/<sha256>` or flat `<sha256>`), so unchanged files are never
  downloaded again (measured in tests: a 1-file change fetches exactly that one blob). Files >= 8 MiB are split into 1 MiB
  hashed chunks; a changed chunk costs one chunk, unchanged chunks are read from the installed file. Downloads resume with
  HTTP Range (a server that ignores Range also works) and are cached/verified per blob.
- **Verify before install:** signature (trusted, not revoked) -> channel name matches -> not expired -> not dated in the
  future -> sequence not older than the newest seen (replay refused) -> each blob size + SHA-256 as it arrives (over-long
  streams refused, bad blobs never enter the cache) -> disk space check -> whole staged folder re-hashed -> one atomic
  `state.json` write promotes it. Previous version stays on disk.
- **Rollback:** any failure before promotion leaves the installed version untouched (staging removed). After promotion the
  version is on probation: optional health check at update time (failure or crash = automatic switch back, version marked
  failed and skipped until a newer one); `on_boot()` switches back after 2 launches that never called `confirm_healthy()`;
  `bootstrap.run_component` is a stub that starts the current version, treats an early crash as a failed boot and falls back;
  manual `rollback()` re-verifies the previous version first and refuses a damaged one. A withdrawn release (`--withdraw`) moves
  affected clients to the channel's version even though the number is lower. State survives corruption (`state.json.bak`),
  one updater at a time (lock file), no replacing of a running world (versions install side by side).
- **Channels:** stable/beta are separate signed manifests; `promote --from beta --to stable` re-signs components with a new sequence.
- **Hosting:** `HttpSource` (any static host) or `DirSource`; `layout flat` for forge release assets; `forge-upload` mirrors a flat
  folder into a Forgejo release (token read from a file, never printed; tested against a fake API only, **not run against the real forge**).
  The real forge requires sign-in to view, so it is an archive/internal channel; the public channel is the site host.
- Local server for trying it: `python -m launcher.updates serve --dir <release folder> --port 8099` (127.0.0.1 only).

Try it end to end (temp key, nothing leaves the PC):
```
set METALLIC_RELEASE_KEY=%TEMP%\mkey\k.json
python -m launcher.updates keygen --write-trust            (then use that trust.json: --trust FILE)
python -m launcher.updates publish --root out --channel beta --component launcher --version 0.2.0 --src DIR --entry Metallic.exe
python -m launcher.updates verify --root out --channel beta
python -m launcher.updates serve --dir out
python -m launcher.updates install --url http://127.0.0.1:8099/ --home %TEMP%\inst --channel beta --component launcher --trust FILE
```

## 3. Website (`metallic-site/`)
- Pages: home, games (roadmap lists generated from the same `roadmap.json`), Litha, downloads (JS reads
  `/releases/channels/<channel>.json`, the file the launcher verifies; installer button + SHA-256 when the component has one,
  otherwise "no release yet"), progress (same px.js/px.css as the launcher + public px.json), news (rendered at build time
  from `src/news.json`, escaped), 404, sitemap, robots. Brand: graphite, silver, violet, crow symbol only (assets copied from
  the launcher branch), Archivo + Hanken Grotesk served locally, concept art labelled as concept art. Litha green accent only on her page.
- No cookies, no third-party requests, no inline scripts/styles: strict CSP in HOSTING.md is safe (tests check it).
- `python metallic-site/build.py --out dist --site-url https://metallic.club [--releases DIR [--with-blobs]] [--forge URL --token-file F]`.
- `HOSTING.md`: build, Caddy and nginx configs, Let's Encrypt (automatic in Caddy, certbot for nginx), Cloudflare in front
  (proxied DNS, Full strict, origin firewall limited to Cloudflare ranges, or a cloudflared tunnel so no ports open), release
  publishing steps, signing-key backup and loss/leak handling. Not deployed.
- Seen in the browser: home, downloads (with a preview release), Litha band, progress at 390 px.

## Not done / owner decisions
- Signing key not created (owner step above). `trust.json` empty. No launcher or Litha release published; no real installer exists.
- Real forge not queried for `forge-upload`; PX forge numbers were read for real (read-only GET) and look right (RC 59 open / 5 closed issues etc.).
- The launcher branch had no `index.html` JS yet when I started; the PX view and update UI still need the wiring above.
- `roadmap.json` and news posts are my drafts for owner review before anything goes public. Domain `metallic.club` is only the default `--site-url`.
- Ed25519 pure-Python signing is not constant-time (fine on the owner's own PC; install `cryptography` there for the fast path).
- Metallic-PX forge repo (old Paintball pages) untouched.
- Test suite is slow on this PC (~3 min for the update tests: fsync + Windows file ops), not slow code.

## Log
- 23:47Z read brief/spec/launcher branch; claimed #277; posted plan to Codex (msg #504, no reply needed).
- ~00:20Z updater core + 61 tests green (59 on first run, 2 test bugs fixed); PX builder/page checked in browser; site built and viewed.
