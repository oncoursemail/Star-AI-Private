#!/usr/bin/env bash
# System self-model deployment into the existing star-mesh container (sibling service on 127.0.0.1:8103; the router
# forwards /mesh/self* to it). Run from the owner's PC (Git Bash) in a checkout of this repo. It never touches the
# router's, verifier's or docs service's files (it only reads their deployed main files to report which code runs).
#
#   MESH_B1=<user>@<brain1> bash server/mesh/selfmodel/deploy.sh <step> [file]
#
# Steps (each is safe to repeat):
#   config FILE   push a self.json (private: machine facts + service URLs with LAN addresses; never in git) to
#                 /etc/star-self/self.json (see self.example.json)
#   install       copy server/mesh/__init__.py + server/mesh/{selfmodel,upgrade} to /opt/star-self/app, the unit,
#                 restart (keeps the previous release for `rollback`)
#   status | logs | rollback | remove
set -euo pipefail
cd "$(dirname "$0")/../../.."
B1="${MESH_B1:?set MESH_B1=user@brain1}"
CT=star-mesh
APP=/opt/star-self

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push() {   # push LOCAL REMOTE MODE (through the brain 1 host)
  local tmp="/tmp/self-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "lxc file push --quiet $tmp $CT$2 --mode $3 --uid 0 --gid 0; rm -f $tmp"
}

step_config() {
  local file="${2:?usage: deploy.sh config <self.json>}"
  python -c "import json,sys; json.load(open(sys.argv[1]))" "$file"
  ct mkdir -p /etc/star-self
  push "$file" /etc/star-self/self.json 0640
  ct chown root:starmesh /etc/star-self/self.json
  echo "config pushed"
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ --exclude=deploy.sh -C server mesh/__init__.py mesh/selfmodel mesh/upgrade
  push "$tarball" /tmp/self.tgz 0600
  rm -f "$tarball"
  ct_sh <<SH
set -e
rm -rf $APP/new && mkdir -p $APP/new && tar --no-same-owner -xzf /tmp/self.tgz -C $APP/new && rm /tmp/self.tgz
PYTHONPATH=$APP/new PYTHONDONTWRITEBYTECODE=1 python3 -c 'import mesh.selfmodel.service, mesh.upgrade.watch' || { echo 'new release does not import: live release kept'; rm -rf $APP/new; exit 3; }
if [ -d $APP/app ]; then rm -rf $APP/previous && mv $APP/app $APP/previous; fi
mv $APP/new $APP/app
chown -R root:root $APP/app
install -m 644 $APP/app/mesh/selfmodel/star-mesh-self.service /etc/systemd/system/star-mesh-self.service
systemctl daemon-reload && systemctl enable star-mesh-self.service >/dev/null 2>&1
systemctl restart star-mesh-self.service; sleep 4; systemctl is-active star-mesh-self.service
curl -s -m 3 http://127.0.0.1:8103/health; echo
SH
}

step_rollback() {
  ct_sh <<SH
[ -d $APP/previous ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous $APP/app && systemctl restart star-mesh-self.service
SH
  echo "rolled back"
}
step_status() { ct systemctl --no-pager --lines=5 status star-mesh-self.service || true; }
step_logs() { ct journalctl -u star-mesh-self.service --no-pager -n "${MESH_LINES:-40}"; }
step_remove() {
  ct_sh <<SH
systemctl disable --now star-mesh-self.service 2>/dev/null; rm -f /etc/systemd/system/star-mesh-self.service
systemctl daemon-reload; rm -rf $APP /etc/star-self /var/lib/star-self
SH
  echo "self-model service removed (router, verifier and docs untouched)"
}

step="${1:?usage: deploy.sh config FILE|install|status|logs|rollback|remove}"
"step_${step//-/_}" "$@"
