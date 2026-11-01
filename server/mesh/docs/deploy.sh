#!/usr/bin/env bash
# Official docs service deployment into the existing star-mesh container (sibling service on 127.0.0.1:8102; the
# router forwards /mesh/docs* to it). Run from the owner's PC (Git Bash) in a checkout of this repo. It never touches
# the router's or the verifier's files.
#
#   MESH_B1=<user>@<brain1> bash server/mesh/docs/deploy.sh <step> [index file]
#
# Steps (each is safe to repeat):
#   install        copy server/mesh/{__init__,router,instant}.py + server/mesh/docs to /opt/star-docs/app, the unit,
#                  restart (keeps the previous release for `rollback`)
#   index FILE     push a docs.db built with `python -m mesh.docs.build` (see build.py) to /var/lib/star-docs, restart
#                  (first deployment order: install, index)
#   status | logs | rollback | remove
set -euo pipefail
cd "$(dirname "$0")/../../.."
B1="${MESH_B1:?set MESH_B1=user@brain1}"
CT=star-mesh
APP=/opt/star-docs
VAR=/var/lib/star-docs

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push() {   # push LOCAL REMOTE MODE (through the brain 1 host)
  local tmp="/tmp/docs-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "lxc file push --quiet $tmp $CT$2 --mode $3 --uid 0 --gid 0; rm -f $tmp"
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ --exclude=deploy.sh -C server mesh/__init__.py mesh/router.py \
    mesh/instant.py mesh/docs
  push "$tarball" /tmp/docs.tgz 0600
  rm -f "$tarball"
  ct_sh <<SH
set -e
rm -rf $APP/new && mkdir -p $APP/new $VAR && tar --no-same-owner -xzf /tmp/docs.tgz -C $APP/new && rm /tmp/docs.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mv $APP/app $APP/previous; fi
mv $APP/new $APP/app
chown -R root:root $APP/app && chown root:starmesh $VAR && chmod 750 $VAR
install -m 644 $APP/app/mesh/docs/star-mesh-docs.service /etc/systemd/system/star-mesh-docs.service
systemctl daemon-reload && systemctl enable star-mesh-docs.service >/dev/null 2>&1
if [ -f $VAR/docs.db ]; then systemctl restart star-mesh-docs.service; sleep 3; systemctl is-active star-mesh-docs.service; curl -s -m 3 http://127.0.0.1:8102/health | head -c 600; echo; else echo "no index yet: run the index step"; fi
SH
}

step_index() {
  local file="${2:?usage: deploy.sh index <docs.db>}"
  push "$file" "$VAR/docs.db.new" 0640
  ct_sh <<SH
set -e
cd $VAR && chown root:starmesh docs.db.new && mv docs.db.new docs.db
systemctl restart star-mesh-docs.service; sleep 3; systemctl is-active star-mesh-docs.service
curl -s -m 3 http://127.0.0.1:8102/health | head -c 600; echo
SH
}

step_rollback() {
  ct_sh <<SH
[ -d $APP/previous ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous $APP/app && systemctl restart star-mesh-docs.service
SH
  echo "rolled back"
}
step_status() { ct systemctl --no-pager --lines=5 status star-mesh-docs.service || true; }
step_logs() { ct journalctl -u star-mesh-docs.service --no-pager -n "${MESH_LINES:-40}"; }
step_remove() {
  ct_sh <<SH
systemctl disable --now star-mesh-docs.service 2>/dev/null; rm -f /etc/systemd/system/star-mesh-docs.service
systemctl daemon-reload; rm -rf $APP $VAR
SH
  echo "docs service removed (router and verifier untouched)"
}

step="${1:?usage: deploy.sh install|index FILE|status|logs|rollback|remove}"
"step_${step//-/_}" "$@"
