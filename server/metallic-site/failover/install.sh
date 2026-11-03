#!/usr/bin/env bash
# Installs the failover check on one copy of metallic.club. Run inside the container, as root:
#   bash install.sh primary http://<standby host>:8089      (the main copy)
#   bash install.sh standby http://<primary host>:8089      (the backup copy)
# Each host forwards its LAN port 8089 to the container (lxc config device add metallic health proxy ...).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROLE="${1:?primary or standby}"; PEER="${2:?http://<other host>:8089}"
[ "$ROLE" = primary ] || [ "$ROLE" = standby ] || { echo "role must be primary or standby" >&2; exit 1; }
printf 'ROLE=%s\nPEER=%s\n' "$ROLE" "$PEER" > /etc/metallic-failover.conf
install -m 755 "$HERE/metallic-failover" /usr/local/bin/metallic-failover
install -m 644 "$HERE/metallic-failover.service" "$HERE/metallic-failover.timer" "$HERE/metallic-health.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now metallic-health.service metallic-failover.timer
echo "installed as $ROLE, peer $PEER"
