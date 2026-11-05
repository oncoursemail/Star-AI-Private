# Hosting metallic.club

The site is plain files plus three JSON files that a timer rewrites. Nothing here is deployed by the build; this is the
plan for the owner's server. Layout on the host:

```
Cloudflare edge (HTTPS, metallic.club + www)
   └─ Cloudflare Tunnel (cloudflared dials out; no open ports, the home IP never appears in DNS)
        └─ Caddy on 127.0.0.1:8088, plain HTTP, root /srv/metallic/dist
             ├─ /                     the built site (HTML, CSS, JS, fonts, images)
             ├─ /live/*.json          revivals.json, news.json, projects.json, rewritten every 2 minutes
             └─ /releases/            latest.json (Tauri updater manifest) and the versioned installers
```

All files for the host are in `server/metallic-site/`: `Caddyfile`, `metallic-live.service`, `metallic-live.timer`,
`cloudflared-config.yml` (a template) and `deploy.sh`.

## 1. Build

```
python metallic-site/build.py --out dist --site-url https://metallic.club [--releases <folder>]
```

- `dist/` is the whole site. No server code, no database, no framework.
- `--releases <folder>` copies `latest.json`, `quest.json` and the installer files (`.exe`, `.msi`, `.sig`, `.zip`, `.AppImage`,
  `.deb`, `.apk`) from that folder
  into `dist/releases/`. Leave it out when releases are copied to the host separately.
- `--sample-live <folder>` copies sample `revivals.json`, `news.json`, `projects.json`, `metallic.json` and
  `downloads.json` into `dist/live/`. For local
  previews only; never use it for the real site (the timer writes the real files).
- Without any JSON the pages still look complete: the board, projects and news show an empty state, the download button
  falls back to the downloads page, and the downloads page says no build is published yet.

## 2. Deploy (on the server)

```
sudo bash server/metallic-site/deploy.sh <built dist folder>
```

It prints each step and is safe to repeat:

1. installs Caddy and cloudflared from their official apt repositories (only when missing);
2. creates the unprivileged system user `metallic` and `/srv/metallic/dist` (`live/` belongs to `metallic`);
3. copies the site with `rsync --delete`, keeping `live/` and `releases/`;
4. installs the Caddyfile, validates it and reloads Caddy, then checks `http://127.0.0.1:8088/`;
5. installs and enables `metallic-live.timer`, which runs `/opt/metallic/metallic-live --out /srv/metallic/dist/live`
   as `metallic` every 2 minutes (copy that program to `/opt/metallic/` first; until then the pages show empty states);
6. writes `/etc/cloudflared/config.yml` from the template if there is none and prints the one-time tunnel commands.

### The tunnel, once

```
cloudflared tunnel login
cloudflared tunnel create metallic                 # prints the tunnel id and writes ~/.cloudflared/<id>.json
sudo mv ~/.cloudflared/<id>.json /etc/cloudflared/ && sudo chmod 600 /etc/cloudflared/<id>.json
sudo sed -i 's/<TUNNEL-ID>/<id>/g' /etc/cloudflared/config.yml
cloudflared tunnel route dns metallic metallic.club
cloudflared tunnel route dns metallic www.metallic.club
sudo bash server/metallic-site/deploy.sh <dist>    # again: installs and starts the cloudflared service
```

The ingress sends `metallic.club` and `www.metallic.club` to `http://127.0.0.1:8088`; Caddy redirects `www` to the bare
domain. The credentials JSON stays on the server and is never committed.

### Cloudflare settings

- SSL/TLS: Always Use HTTPS on, minimum TLS 1.2. (Mode does not matter for a tunnel; there is no origin certificate.)
- DNS: only the two tunnel CNAME records. Delete any old `A` record that points at the home IP (also `mail`, `ftp`,
  `vpn` and similar).
- Caching: Cloudflare already respects the origin's `Cache-Control`. If you add a cache rule, bypass it for `/live/*`
  and `/releases/latest.json`, so new counts and a new release show at once.
- Check from outside: `nslookup metallic.club` must show only Cloudflare addresses, and `curl -I https://metallic.club`
  must answer with the headers below.

## 3. What Caddy sends

- `Content-Security-Policy: default-src 'self'; img-src 'self' data: https://cdn.discordapp.com; style-src 'self';
  script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`.
  The only outside host is Discord's image CDN, for the revivals' server icons and banners. Every request the pages make
  for data is same-origin (`connect-src 'self'`).
- `Cache-Control: no-store` on `/live/*` and `/releases/latest.json`; `public, max-age=31536000, immutable` on the
  installers (their names carry the version); one hour on `/assets/*`; `no-cache` on the pages, so a browser checks for a new page on every visit.
- Hidden files (for example metallic-live's `.revivals-history.json`) are not served. Errors show `/404.html`.
- Range requests work for the installers, so interrupted downloads resume.
- Only two access logs are kept, both read by metallic-live and neither with an address or a header:
  `/var/log/caddy/downloads.log` (installer requests and their user agent, for the download count) and
  `/var/log/caddy/beats.log` (people in Metallic now, below). Every other request is not logged.

### People in Metallic now

Each running launcher (also minimized or in the tray) asks for `/live/metallic.json` every 2 minutes with the header
`X-Metallic-Session: <32 hex>`, a random ID it makes at start, keeps only in memory and replaces on every start. Caddy
writes only those requests to `beats.log`, keeping the ID and the time and deleting the request (address, headers, path),
the response headers and the user agent; the log rolls at 1 MiB and keeps one older copy. Visitors' requests for the same
file carry no ID and are not logged. metallic-live counts the distinct IDs seen in the last 5 minutes and writes
`/live/metallic.json`: `{"at", "online", "peak_24h", "discord": {"online", "members", "icon"}}`. `discord` is the online
count of Metallic's own server (invite `discord.gg/yMytc2uAmj`), asked for by metallic-live, never by visitors'
browsers. The pages show "N people in Metallic right now" only when `online` is above 0 and the file is under 10
minutes old. Needs Caddy 2.9 or newer (`log_name`); `deploy.sh` validates the Caddyfile before reloading.

## 4. Publishing a release

Metallic Early Access updates itself with Tauri's updater, which reads `/releases/latest.json`:

```
{"version": "0.1.0", "notes": "...", "pub_date": "2026-11-01T12:00:00Z",
 "platforms": {"windows-x86_64": {"signature": "<minisign signature>", "url": "https://metallic.club/releases/Metallic_0.1.0_x64-setup.exe"}}}
```

1. Build and sign the installer on your PC (the Tauri signing key never leaves it; back it up offline, because installed
   launchers only trust that key).
2. Copy the versioned installer to `/srv/metallic/dist/releases/` first, then `latest.json` last, so the manifest never
   points at a file that is not there yet.
3. The downloads page and the home page's button read the same `latest.json`: version, date, notes, and the size when
   the installer is on this site.
4. Linux (when a Linux build is published): add `"linux-x86_64"` (the `.AppImage`, which the Linux updater replaces in
   place) and `"linux-x86_64-deb"` (the `.deb`) to `platforms`, each with its own `.sig`. Linux visitors then get the
   AppImage on the Download buttons and the downloads page lists both. Copy them before `latest.json`, as above.
5. Meta Quest: copy the versioned `.apk` first, then replace `/releases/quest.json` with
   `{"version": "0.2.8", "url": "/releases/Metallic_0.2.8_quest.apk"}`. Until then `deploy.sh` leaves an empty `{}` there
   (the page reads it as "not published", without a 404). A Quest headset's browser gets the APK on the Download
   buttons; its user agent says Linux, so it is never offered the AppImage.

## 5. What the site never does

It sets no cookies, has no forms or accounts, loads no scripts or fonts from other companies (fonts are self-hosted) and
no images except the revivals' own Discord artwork. Live numbers are shown as published: "in game" only where a revival
publishes its player count, and Discord's online count is always labelled "online in Discord", never players. "In
Metallic right now" counts open launchers, not people in a revival.

## 5. Two copies, switched automatically (failover)

metallic.club runs as two identical copies on two machines: the primary (`metallic` container on the first host) and a
standby (`metallic` container on server 2). Each has Caddy, the site, `/releases/`, metallic-live and a connector of the
same Cloudflare tunnel (same credentials file). Cloudflare sends visitors to whichever connectors are up, so when one copy
drops out the other carries everything with no error page.

`server/metallic-site/failover/` (install with `bash install.sh primary|standby http://<other host>:8089` inside each
container) adds a check every 15 s that switches only the tunnel connector:

- healthy = reaches the internet, Caddy answers, `live/revivals.json` has numbers and is under 5 minutes old (2 failed
  checks make a copy unhealthy, 3 good ones healthy again);
- the primary serves while healthy, and steps out only while the standby is healthy and connected;
- the standby serves while the primary is not healthy and connected;
- a copy steps out only after the other is connected (make-before-break), so there is never a moment with no connector.

Each copy publishes its state at `http://<host>:8089/health.json` (LXD proxy device `health` on the host -> the
container's `metallic-health.service`); the other copy reads it. While a host firewall blocks port 8089, each copy reads
the other over SSH instead (`PEER_SSH`), with a key that the other host's `authorized_keys` limits to printing that one
file (`restrict,from=...,command=...`; see `install.sh`). Without either link each copy keeps its own connector up (both
serve), which still covers a copy that goes away entirely but not one that stays connected with bad data.
Logs: `journalctl -t metallic-failover`. Drill: `touch /run/metallic-failover-drill` in the primary makes it report
itself unhealthy (the standby takes over within about 40 s); `rm` it to switch back.

Publishing and deploying go to BOTH copies: upload release files and switch `latest.json` / `quest.json` on each, and run
`deploy.sh` in each container. Each copy's metallic-live counts the downloads and "people in Metallic" it serves itself.
