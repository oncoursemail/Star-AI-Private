#!/usr/bin/env bash
# Install, check or remove STAR's priority proxy on brain 1. Run from the repository root on the PC (Git Bash):
#
#   STAR_SERVER_SSH=<user@brain 1 LXD host> bash server/priority/deploy.sh [--start]   install (+ start)
#   STAR_SERVER_SSH=... bash server/priority/deploy.sh --status
#   STAR_SERVER_SSH=... bash server/priority/deploy.sh --undo        stop + disable the proxy, put back what --start
#                                                                    replaced (clients on 8097 must go back to 8080)
#
# It copies star/priority_proxy.py (stdlib only) to /opt/star/priority, the settings to /opt/star/config/priority.json
# (an existing file is kept as priority.json.bak-<date>) and installs star-priority.service. It restarts nothing else:
# clients move to it one by one (their URL becomes http://<brain>:8097/p<class>), see docs/research/priority-scheduler-
# 20261020.md. Addresses and user names are operator configuration and never stored in the repository.
set -euo pipefail

container="${STAR_LXC_CONTAINER:-starai}"
target="${STAR_SERVER_SSH:?set STAR_SERVER_SSH}"
mode=install
case "${1:-}" in
  --start) mode=start ;;
  --status) mode=status ;;
  --undo) mode=undo ;;
  "") ;;
  *) echo "unknown option $1" >&2; exit 2 ;;
esac
root="$(git rev-parse --show-toplevel)"
cd "$root"
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- $*"; }

if [ "$mode" = status ]; then
  remote systemctl is-active star-priority || true
  remote curl -s --max-time 5 http://127.0.0.1:8097/priority/v1/status | head -c 4000 || true
  echo
  exit 0
fi

if [ "$mode" = undo ]; then
  remote systemctl disable --now star-priority || true
  remote rm -f /etc/systemd/system/star-priority.service
  remote systemctl daemon-reload
  echo "star-priority stopped and removed; /opt/star/priority and /opt/star/config/priority.json left in place"
  exit 0
fi

stamp="$(date -u +%Y%m%d-%H%M%S)"
remote install -d -o star -g star /opt/star/priority /opt/star/logs
remote bash -c "'test -f /opt/star/config/priority.json && cp -p /opt/star/config/priority.json /opt/star/config/priority.json.bak-$stamp || true'"
git archive HEAD star/priority_proxy.py | ssh -o BatchMode=yes "$target" "lxc exec $container -- runuser -u star -- tar -x --strip-components=1 -C /opt/star/priority"
git show HEAD:server/priority/priority.json | ssh -o BatchMode=yes "$target" "lxc exec $container -- bash -c 'cat > /opt/star/config/priority.json'"
git show HEAD:server/priority/star-priority.service | ssh -o BatchMode=yes "$target" "lxc exec $container -- bash -c 'cat > /etc/systemd/system/star-priority.service'"
remote systemctl daemon-reload
remote runuser -u star -- python3 -c "'import json, sys; sys.path.insert(0, \"/opt/star/priority\"); import priority_proxy as p; c = p.Config.load(\"/opt/star/config/priority.json\"); print(\"priority proxy code ok, models\", list(c.models))'"
if [ "$mode" = start ]; then
  remote systemctl enable --now star-priority
  remote systemctl restart star-priority
  sleep 2
  remote curl -s --max-time 5 http://127.0.0.1:8097/priority/v1/status | head -c 400
  echo
fi
