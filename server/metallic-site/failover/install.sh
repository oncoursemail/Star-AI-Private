#!/usr/bin/env bash
# Installs the failover check on one copy of metallic.club. Run inside the container, as root:
#   bash install.sh primary http://<standby host>:8089      (the main copy)
#   bash install.sh standby http://<primary host>:8089      (the backup copy)
#   ... [<user>@<other host>]   optional: read the other copy over SSH while a firewall blocks port 8089
# Each host forwards its LAN port 8089 to the container (lxc config device add metallic health proxy ...).
# The SSH way needs /root/.ssh/metallic-health (ssh-keygen -t ed25519 -N ""), its .pub on the OTHER host in
# ~/.ssh/authorized_keys as: restrict,from="<this host>",command="lxc exec metallic --force-noninteractive -- cat
# /run/metallic-health/health.json" <key>   (that key can do nothing but print the status), and the other host's key in
# /root/.ssh/known_hosts.metallic-health (ssh-keyscan -t ed25519 <other host>).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROLE="${1:?primary or standby}"; PEER="${2:?http://<other host>:8089}"; PEER_SSH="${3:-}"
[ "$ROLE" = primary ] || [ "$ROLE" = standby ] || { echo "role must be primary or standby" >&2; exit 1; }
printf 'ROLE=%s\nPEER=%s\nPEER_SSH=%s\n' "$ROLE" "$PEER" "$PEER_SSH" > /etc/metallic-failover.conf
# the one copy of the script this replaces (keeps no others)
if [ -f /usr/local/bin/metallic-failover ]; then cp -p /usr/local/bin/metallic-failover /usr/local/bin/metallic-failover.bak; fi
install -m 755 "$HERE/metallic-failover" /usr/local/bin/metallic-failover
install -m 644 "$HERE/metallic-failover.service" "$HERE/metallic-failover.timer" "$HERE/metallic-health.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now metallic-health.service metallic-failover.timer
echo "installed as $ROLE, peer $PEER"
