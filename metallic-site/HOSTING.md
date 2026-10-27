# Hosting the Metallic site yourself

The site is plain files. Nothing here is deployed; this is the plan for when you decide to put it online.

## 1. Build

```
python metallic-site/build.py --out dist --site-url https://metallic.club ^
    --releases <release folder> [--with-blobs] [--forge <forge url> --token-file <read-only token file>]
```

- `dist/` is the whole site: HTML, CSS, a little JavaScript, two fonts, images. No server code, no database.
- `--releases` copies `channels/`, `installers/` and `changelog.json` from the folder the publisher made
  (`python -m launcher.updates publish ...`). Add `--with-blobs` to serve the update files from the same host.
  Leave it out if the blobs live somewhere else (then point the launcher's update address there).
- `--forge` is optional. It adds milestone and issue counts for public repositories to the progress page. Issue titles,
  release notes and numbers for private repositories are never written, and the build refuses to write if it finds an
  address, a user name or a key. Use a read-only token, kept in a file outside the repo.

## 2. Serve it

Any static host works. Two self-hosted options:

**Caddy** (gets and renews the Let's Encrypt certificate by itself):

```
metallic.club {
    root * /srv/metallic/dist
    file_server
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    }
    @channels path /releases/channels/* /releases/*.json /releases/*.sig
    header @channels Cache-Control "no-store"
    @blobs path /releases/blobs/*
    header @blobs Cache-Control "public, max-age=31536000, immutable"
    handle_errors {
        rewrite * /404.html
        file_server
    }
}
```

**nginx** behind certbot (`certbot --nginx -d metallic.club -d www.metallic.club`):

```
server {
    server_name metallic.club www.metallic.club;
    root /srv/metallic/dist;
    index index.html;
    error_page 404 /404.html;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'" always;
    location /releases/channels/ { add_header Cache-Control "no-store"; }
    location /releases/blobs/   { add_header Cache-Control "public, max-age=31536000, immutable"; }
    location / { try_files $uri $uri/ =404; }
}
```

Both serve `Range` requests for files, which the launcher uses to resume interrupted downloads.

## 3. Cloudflare in front (hides the home IP)

1. Add the domain to Cloudflare and switch the registrar's name servers to the ones Cloudflare gives you.
2. DNS: an `A` record for `@` and `www` pointing at your home IP, with the orange cloud ON (proxied). Never create a
   DNS-only record that points at the home IP, and delete old records that do (also `mail`, `ftp`, `vpn` and similar).
3. SSL/TLS mode: **Full (strict)**. Keep the Let's Encrypt certificate on the origin so Cloudflare can verify it.
4. On the router, forward ports 80 and 443 to the host. In the host firewall, allow 80 and 443 **only from Cloudflare's
   published ranges** (https://www.cloudflare.com/ips/), so the origin ignores everyone else.
5. Stronger and simpler: run `cloudflared` (a Cloudflare Tunnel) on the host. It dials out, so no ports are open on the
   router and the home IP never appears in DNS. Point the tunnel at `http://localhost:80` (or the Caddy/nginx port).
6. Cloudflare settings: Always Use HTTPS on, minimum TLS 1.2, Bot Fight Mode on. Add a caching rule that bypasses cache
   for `/releases/channels/*`, so a new release shows up at once. Blobs can be cached for a year because their names are
   their hashes.
7. Do not send mail from the home IP, do not host anything else on it that names it, and do not link to the forge
   (`forge` stays on the LAN or a private tunnel).
8. Check from outside: `nslookup metallic.club` must show only Cloudflare addresses, and `curl -I https://metallic.club`
   must work.

## 4. Publishing a release

1. `python -m launcher.updates publish --root <release folder> --channel beta ...` (signs with your key, see below).
2. `python -m launcher.updates verify --root <release folder> --channel beta` checks the signature and every file.
3. Copy the release folder to the host (`rsync` or `scp`), or rebuild with `--releases` and sync `dist/`.
4. Try it from a test PC on the beta channel. Then `python -m launcher.updates promote --root <folder> --from beta --to stable`.
5. Pull a bad release with `publish ... --withdraw <bad version> --allow-downgrade` (clients on the bad version move back).

## 5. The signing key

- Create it once: `python -m launcher.updates keygen --write-trust`. It writes
  `%USERPROFILE%\.metallic\release-signing-key.json` (override with the `METALLIC_RELEASE_KEY` variable) and refuses any
  path inside a git repository. The command also adds the **public** key to `launcher/updates/trust.json`; commit that
  file, the launcher needs it.
- **Back the key file up offline** (a USB stick in a drawer). If it is lost, installed launchers can never be updated
  again, because they only trust that key. If it leaks, publish a new trust list in a launcher update signed with the old
  key, then retire the old key.
- Never put the key on the web host. Signing happens on your PC; the host only receives the signed files.

## 6. What the site never does

It sets no cookies, loads no scripts, fonts or images from other companies, and has no forms or accounts. The strict
Content-Security-Policy above is safe because of that. Adding analytics or an embed later means loosening it on purpose.
