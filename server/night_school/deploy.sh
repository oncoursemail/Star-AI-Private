#!/usr/bin/env bash
# Install or update STAR night school in the STAR server container. Run from the repository root on the PC:
#
#   STAR_SERVER_SSH=<user@address of the LXD host> bash server/night_school/deploy.sh --pool <folder> [--start]
#
#   --pool <folder>  practice tasks (*.json, with their tests/ folder) to copy to /opt/star/learning/pool
#   --start          enable and start the unit after the checks passed
#   --status         only show the unit state, the last log lines and the report
#   --pool-only      with --pool: copy and check the practice tasks, change nothing else (the running service
#                    picks new tasks up between batches)
#
# The address is operator configuration and is never stored in the repository. Nothing here stops or restarts any
# other service. The evaluation suites are not copied: only hashes of the two golden suites' prompts go to the
# server (so that a practice task copied from them is dropped), and the blind exam is never read.
set -euo pipefail

target="${STAR_SERVER_SSH:?set STAR_SERVER_SSH to user@address of the LXD host}"
container="${STAR_LXC_CONTAINER:-starai}"
python="${STAR_PYTHON:-python}"
home=/opt/star/learning
pool="" start=0 status=0 pool_only=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pool) pool="$2"; shift 2 ;;
    --start) start=1; shift ;;
    --status) status=1; shift ;;
    --pool-only) pool_only=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- $*"; }
as_star() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- runuser -u star -- $*"; }

if [ "$status" = 1 ]; then
  remote "systemctl is-enabled star-night-school" || true
  remote "systemctl is-active star-night-school" || true
  remote "journalctl -u star-night-school -n 15 --no-pager -o cat" || true
  as_star "cat $home/report/latest.md" || true
  exit 0
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"
# The checks read the service's own settings file (key file, knowledge address) when there is one.
run() { as_star "bash -c 'cd $home/app/server/night_school && if [ -f $home/env ]; then set -a; . $home/env; set +a; fi && HOME=$home/data/home STAR_NS_HOME=$home nice -n 19 $home/venv/bin/python -m nightschool $*'"; }
if [ "$pool_only" = 0 ]; then
  echo "== code (git HEAD $(git rev-parse --short HEAD))"
  remote "install -d -o star -g star $home $home/app $home/pool $home/data $home/data/home $home/report $home/outbox"
  git archive HEAD star server/night_school requirements.txt evals/roblox/prelude.luau |
    ssh -o BatchMode=yes "$target" "lxc exec $container -- runuser -u star -- tar -x -C $home/app"
  # Notes that changed in the last two days (public docs only; paintball notes are left out) for the night conductor.
  remote "install -d -o star -g star $home/docs-recent $home/conductor"
  recent="$(git log --since=2.days --name-only --pretty=format: -- 'docs/agents/*.md' | sort -u | grep -viE 'paintball|(^|/)pb-' | head -12 || true)"
  if [ -n "$recent" ]; then
    # shellcheck disable=SC2086
    git archive HEAD $recent | ssh -o BatchMode=yes "$target" "lxc exec $container -- runuser -u star -- bash -c 'rm -rf $home/docs-recent/* && tar -x -C $home/docs-recent --strip-components=2 && touch $home/docs-recent/*.md'"
  fi
fi

if [ -n "$pool" ]; then
  echo "== practice pool from $pool"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  cp -r "$pool"/. "$work"/
  rm -f "$work"/golden* "$work"/holdout* 2>/dev/null || true
  [ -f "$work/prelude.luau" ] || cp evals/roblox/prelude.luau "$work/prelude.luau"
  (cd server/night_school && "$python" -m nightschool guard --suite "$root/evals/roblox/golden-tasks-v2.json" \
      --suite "$root/evals/roblox/golden-tasks-creation-v1.json" --out "$work/forbidden-prompts.json")
  tar -c -C "$work" . | ssh -o BatchMode=yes "$target" "lxc exec $container -- runuser -u star -- tar -x -C $home/pool"
fi

if [ "$pool_only" = 1 ]; then
  run validate-pool
  exit 0
fi

echo "== python environment (the application's own requirements)"
as_star "bash -c 'test -x $home/venv/bin/python || python3 -m venv $home/venv'"
as_star "bash -c 'nice -n 19 $home/venv/bin/pip install --quiet --disable-pip-version-check -r $home/app/requirements.txt'"

echo "== unit"
remote "install -m 0644 $home/app/server/night_school/star-night-school.service /etc/systemd/system/star-night-school.service"
remote "install -m 0644 $home/app/server/night_school/star-night-conductor.service /etc/systemd/system/star-night-conductor.service"
remote "install -m 0644 $home/app/server/night_school/star-night-conductor.timer /etc/systemd/system/star-night-conductor.timer"
remote "systemctl daemon-reload"

echo "== practice pool, checked with the repository's loader"
run validate-pool
echo "== dry run with the fake brain (no request reaches the real brain)"
run dry-run --real-checks

if [ "$start" = 1 ]; then
  echo "== start"
  remote "systemctl enable star-night-school"
  remote "systemctl restart star-night-school"
  remote "systemctl enable --now star-night-conductor.timer"
  sleep 20
  remote "systemctl is-active star-night-school"
  remote "journalctl -u star-night-school -n 12 --no-pager -o cat"
fi
