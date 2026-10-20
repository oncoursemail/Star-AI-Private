#!/usr/bin/env bash
# Put STAR's priority proxy in front of brain 1, check it, or take it out. Run from the repository root (Git Bash):
#
#   STAR_SERVER_SSH=<user@brain 1 LXD host> bash server/priority/deploy.sh --start   stage + golive.sh (see there)
#   STAR_SERVER_SSH=... bash server/priority/deploy.sh --status
#   STAR_SERVER_SSH=... bash server/priority/deploy.sh --undo        runs /opt/star/priority/undo.sh (written by
#                                                                    golive.sh: router back on 8080, proxy off)
# Background clients on other machines are labelled by port: e.g. brain 2's playtest learning
# STAR_PLAYTEST_BRAIN_URL=http://<brain 1>:8083, evals STAR_EVAL_SERVER=http://<brain 1>:8083/v1, agents :8082.
# Addresses and user names are operator configuration and never stored in the repository.
set -euo pipefail

container="${STAR_LXC_CONTAINER:-starai}"
target="${STAR_SERVER_SSH:?set STAR_SERVER_SSH}"
case "${1:-}" in
  --start|--status|--undo) mode="$1" ;;
  *) echo "usage: deploy.sh --start|--status|--undo" >&2; exit 2 ;;
esac
root="$(git rev-parse --show-toplevel)"
cd "$root"
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- $*"; }

case "$mode" in
  --status)
    remote systemctl is-active star-priority star-brain || true
    remote curl -s --max-time 5 http://127.0.0.1:8080/priority/v1/status | head -c 4000 || true
    echo ;;
  --undo)
    remote bash /opt/star/priority/undo.sh ;;
  --start)
    remote install -d -o star -g star /opt/star/priority /opt/star/priority/stage
    {
      tmp="$(mktemp -d)"
      git show HEAD:star/priority_proxy.py > "$tmp/priority_proxy.py"
      git show HEAD:star/task_checkpoint.py > "$tmp/task_checkpoint.py"
      git show HEAD:server/priority/priority.json > "$tmp/priority.json"
      git show HEAD:server/priority/star-priority.service > "$tmp/star-priority.service"
      git show HEAD:server/priority/golive.sh > "$tmp/golive.sh"
      for f in __main__ conductor config idle; do
        git show "HEAD:server/night_school/nightschool/$f.py" > "$tmp/ns-$f.py"
      done
      tar -C "$tmp" -c . | ssh -o BatchMode=yes "$target" "lxc exec $container -- tar -x --no-same-owner -C /opt/star/priority/stage"
      rm -rf "$tmp"
    }
    remote bash /opt/star/priority/stage/golive.sh ;;
esac
