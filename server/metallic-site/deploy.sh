#!/usr/bin/env bash
# metallic.club on one Debian/Ubuntu host: Caddy on 127.0.0.1:8088, a Cloudflare tunnel in front, metallic-live every 2 min.
# Run ON the server, from a checkout of this repo (or a copy of server/metallic-site/ next to a built dist/):
#
#   sudo bash server/metallic-site/deploy.sh <built dist folder>
#
# Safe to run again: it only installs what is missing, replaces the site files, and leaves live/, releases/ and an
# existing /etc/cloudflared/config.yml alone. Every step prints what it does. See metallic-site/HOSTING.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="${1:?usage: sudo bash deploy.sh <built dist folder>}"
ROOT=/srv/metallic/dist
LIVE_BIN=/opt/metallic/metallic-live

step() { printf '\n==> %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ -f "$DIST/index.html" ] || { echo "$DIST has no index.html; build it first: python metallic-site/build.py --out <dir>" >&2; exit 1; }

step "1/7 packages: curl, gpg, rsync"
apt-get update -qq
apt-get install -y -qq curl gpg rsync debian-keyring debian-archive-keyring apt-transport-https >/dev/null

step "2/7 Caddy from its official apt repository"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi
caddy version

step "3/7 cloudflared from Cloudflare's official apt repository"
if ! command -v cloudflared >/dev/null; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg > /usr/share/keyrings/cloudflare-main.gpg
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq && apt-get install -y -qq cloudflared >/dev/null
fi
cloudflared --version

step "4/7 user 'metallic' and folders"
id metallic >/dev/null 2>&1 || useradd --system --home-dir /var/lib/metallic --create-home --shell /usr/sbin/nologin metallic
mkdir -p "$ROOT/live" "$ROOT/releases" /opt/metallic
chown root:root "$ROOT" && chmod 755 "$ROOT"
chown metallic:metallic "$ROOT/live" && chmod 755 "$ROOT/live"
# no Quest APK yet: an empty manifest, so the downloads page reads "not published" instead of getting a 404
[ -e "$ROOT/releases/quest.json" ] || { echo '{}' > "$ROOT/releases/quest.json" && chmod 644 "$ROOT/releases/quest.json"; }

step "5/7 site files -> $ROOT (live/ and releases/ are kept)"
rsync -a --delete --exclude /live/ --exclude /releases/ --exclude /revivals/ "$DIST/" "$ROOT/"
chown -R root:root "$ROOT/assets" && find "$ROOT" -path "$ROOT/live" -prune -o -type f -exec chmod 644 {} +
echo "$(find "$ROOT" -type f | wc -l) files"

step "6/7 Caddy config (127.0.0.1:8088) and reload"
if ! cmp -s "$HERE/Caddyfile" /etc/caddy/Caddyfile; then
  [ -f /etc/caddy/Caddyfile ] && cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)"
  install -m 644 "$HERE/Caddyfile" /etc/caddy/Caddyfile
fi
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable --now caddy
systemctl reload caddy
curl -fsS -o /dev/null -w 'local check: HTTP %{http_code}\n' http://127.0.0.1:8088/

step "7/7 metallic-live timer and the tunnel"
install -m 644 "$HERE/metallic-live.service" "$HERE/metallic-live.timer" /etc/systemd/system/
systemctl daemon-reload
if [ -x "$LIVE_BIN" ]; then
  systemctl enable --now metallic-live.timer
  systemctl start metallic-live.service || echo "metallic-live failed once; see: journalctl -u metallic-live -n 50"
else
  systemctl enable metallic-live.timer
  echo "NOTE: $LIVE_BIN is missing. Copy it there (chmod 755), then: systemctl start metallic-live.timer"
  echo "      Until then the pages show their empty states."
fi
mkdir -p /etc/cloudflared
if [ ! -f /etc/cloudflared/config.yml ]; then
  install -m 644 "$HERE/cloudflared-config.yml" /etc/cloudflared/config.yml
  echo "Wrote the tunnel template to /etc/cloudflared/config.yml. One-time setup (needs the Cloudflare account):"
fi
if grep -q '<TUNNEL-ID>' /etc/cloudflared/config.yml; then
  cat <<'EOF'
  cloudflared tunnel login
  cloudflared tunnel create metallic        # prints the tunnel id, writes ~/.cloudflared/<id>.json
  sudo mv ~/.cloudflared/<id>.json /etc/cloudflared/ && sudo chmod 600 /etc/cloudflared/<id>.json
  sudo sed -i 's/<TUNNEL-ID>/<id>/g' /etc/cloudflared/config.yml
  cloudflared tunnel route dns metallic metallic.club
  cloudflared tunnel route dns metallic www.metallic.club
  sudo bash server/metallic-site/deploy.sh <dist>   # again: installs and starts the tunnel service
EOF
elif ! systemctl is-enabled --quiet cloudflared 2>/dev/null; then
  cloudflared service install
  systemctl enable --now cloudflared
else
  systemctl restart cloudflared
fi
systemctl --no-pager --lines=0 status caddy cloudflared metallic-live.timer 2>/dev/null | grep -E '^(●|  *Active)' || true
echo
echo "done"
