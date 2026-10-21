#!/usr/bin/env bash
# G1 API lock on brain 1. Run from the repository root (Git Bash):
#
#   STAR_SERVER_SSH=<user@brain 1 LXD host> bash server/api_lock/deploy.sh --build    stage files + table, build the
#                                                     patched llama-server next to the live one (nice; nothing live changes)
#   STAR_SERVER_SSH=... bash server/api_lock/deploy.sh --enable   star-brain runs /opt/star/bin-apilock with the table
#                                                     (drop-in backed up, /opt/star/api_lock/undo.sh written, star-brain
#                                                     restarted: run it under `./star.cmd lock run --owner claude --holder g1
#                                                     --server 1 --max-minutes 10 -- bash server/api_lock/deploy.sh --enable`)
#   STAR_SERVER_SSH=... bash server/api_lock/deploy.sh --undo     runs /opt/star/api_lock/undo.sh (same lock rule)
#   STAR_SERVER_SSH=... bash server/api_lock/deploy.sh --status
#
# The enabled server still answers exactly as before unless a request carries "api_lock": true, which the app sends
# only with the setting api_lock_enabled (off by default). Addresses and user names are never stored in the repo.
set -euo pipefail

container="${STAR_LXC_CONTAINER:-starai}"
target="${STAR_SERVER_SSH:?set STAR_SERVER_SSH}"
root="$(git rev-parse --show-toplevel)"
cd "$root"
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- $*"; }

case "${1:-}" in
  --build)
    tmp="$(mktemp -d)"
    for f in 0004-api-lock-sampler.patch build.sh enable.sh cases.json; do
      git show "HEAD:server/api_lock/$f" > "$tmp/$f"      # the committed (LF) text, not a CRLF checkout
    done
    python -m star.api_lock table "$tmp/api-lock-table.json"
    remote install -d -o star -g star /opt/star/api_lock
    tar -C "$tmp" -c . | ssh -o BatchMode=yes "$target" "lxc exec $container -- tar -x --no-same-owner -C /opt/star/api_lock"
    rm -rf "$tmp"
    remote chown -R star:star /opt/star/api_lock
    remote runuser -u star -- bash /opt/star/api_lock/build.sh ;;
  --enable)
    remote bash /opt/star/api_lock/enable.sh ;;
  --undo)
    remote bash /opt/star/api_lock/undo.sh ;;
  --status)
    remote grep -h -e /opt/star/bin- -e LLAMA_API_LOCK /etc/systemd/system/star-brain.service.d/ramforge.conf || true
    remote systemctl is-active star-brain || true ;;
  *)
    echo "usage: deploy.sh --build|--enable|--undo|--status" >&2
    exit 2 ;;
esac
