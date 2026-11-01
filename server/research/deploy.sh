#!/usr/bin/env bash
# STAR's research watch list on STAR Server 1 (the starai container): a nightly poll of release notes and changelogs
# (star/research_store.py DEFAULT_WATCH) into /opt/star/research/research-store.sqlite3, plus the re-check of stored
# facts. The search gateway (server/searxng/gateway.py, GET /watched) serves the snapshots to the desktop app.
# Run from the repository root on the PC (Git Bash):
#
#   STAR_SERVER_SSH=<user@address of the LXD host> bash server/research/deploy.sh <command>
#
#   install    copy the code (git HEAD: star/) to /opt/star/research/releases/<sha>, point current -> it (the old one
#              becomes previous), create the venv (httpx only), install and enable the timer. Never runs a poll.
#   run        one poll + re-check now (what the timer runs at 08:20 UTC)
#   status     timer state, last run's journal lines and the store's counts
#   rollback   current <-> previous release
#   remove     disable and delete the units (the store file is kept)
#
# The address is operator configuration and is never stored in the repository. Commands run as root inside the
# container through `lxc exec`; the poll itself runs as the unprivileged user star.
set -euo pipefail
target="${STAR_SERVER_SSH:?set STAR_SERVER_SSH to user@address of the LXD host}"
container="${STAR_LXC_CONTAINER:-starai}"
base=/opt/star/research
unit=star-research-watch
cmd="${1:-}"
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- bash -c $(printf '%q' "$*")"; }

case "$cmd" in
install)
  root="$(git rev-parse --show-toplevel)"; cd "$root"
  sha="$(git rev-parse --short=12 HEAD)"
  echo "== folders"
  remote "install -d -o root -g root -m 755 $base/releases && chown star:star $base && chmod 755 $base"
  echo "== code (git HEAD $sha)"
  remote "rm -rf $base/releases/$sha.tmp && install -d -m 755 $base/releases/$sha.tmp"
  git archive HEAD star | ssh -o BatchMode=yes "$target" "lxc exec $container -- tar -x --no-same-owner -C $base/releases/$sha.tmp"
  remote "rm -rf $base/releases/$sha && mv $base/releases/$sha.tmp $base/releases/$sha && chmod -R a+rX,go-w $base/releases/$sha"
  echo "== venv"
  remote "test -x $base/venv/bin/python || python3 -m venv $base/venv"
  remote "$base/venv/bin/python -m pip install -q --disable-pip-version-check 'httpx>=0.28.1,<1'"
  remote "cd /tmp && $base/venv/bin/python -I -c 'import sys; sys.path.insert(0, \"$base/releases/$sha\"); import star.research_store; print(\"imports ok\")'"
  echo "== switch current"
  remote "if [ -L $base/current ]; then ln -sfn \$(readlink $base/current) $base/previous; fi; ln -sfn $base/releases/$sha $base/current"
  echo "== units"
  tar -C server/research -cf - $unit.service $unit.timer |
    ssh -o BatchMode=yes "$target" "lxc exec $container -- tar -x --no-same-owner -C /etc/systemd/system"
  remote "chmod 644 /etc/systemd/system/$unit.service /etc/systemd/system/$unit.timer && systemctl daemon-reload && systemctl enable --now $unit.timer"
  remote "systemctl list-timers $unit.timer --no-pager | head -3"
  ;;
run)
  remote "systemctl start $unit.service; systemctl status $unit.service --no-pager -n 12 | tail -12"
  ;;
status)
  remote "systemctl list-timers $unit.timer --no-pager | head -3; journalctl -u $unit.service --no-pager -n 8; cd $base/current && runuser -u star -- $base/venv/bin/python -m star.research_store status --db $base/research-store.sqlite3"
  ;;
rollback)
  remote "test -L $base/previous && old=\$(readlink $base/current) && ln -sfn \$(readlink $base/previous) $base/current && ln -sfn \$old $base/previous && readlink $base/current"
  ;;
remove)
  remote "systemctl disable --now $unit.timer || true; rm -f /etc/systemd/system/$unit.service /etc/systemd/system/$unit.timer; systemctl daemon-reload"
  ;;
*)
  sed -n '2,17p' "$0"; exit 2 ;;
esac
