#!/usr/bin/env bash
# Litha agent mode deployment, run from the owner's PC (Git Bash) in a checkout of this repo. It never touches the
# router's or verifier's files (/opt/star-mesh, /opt/star-verify); the router only needs its `agent_url` default.
#
#   MESH_B1=<user>@<brain1> bash server/mesh/agent/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   install  copy server/mesh to /opt/star-agent/app in the star-mesh container (the agent imports the verifier and
#            router helpers), the unit, restart (keeps the previous release for `rollback`); 127.0.0.1:8104 only
#   front    real-server loads: loadfront.py + unit into the mc-plugins container (:8106, the javac service's token),
#            then /etc/star-agent/agent.json load_url = the jvm_url host of the verifier's config with port 8106
#   status | logs | rollback | remove
set -euo pipefail
cd "$(dirname "$0")/../../.."
B1="${MESH_B1:?set MESH_B1=user@brain1}"
CT=star-mesh
MC=mc-plugins
APP=/opt/star-agent

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
mc_sh() { b1 "lxc exec $MC -- sh -se"; }
push() {   # push CONTAINER LOCAL REMOTE MODE (through the brain 1 host)
  local tmp="/tmp/agent-$RANDOM-$$"
  scp -q "$2" "$B1:$tmp"
  b1 "lxc file push --quiet $tmp $1$3 --mode $4 --uid 0 --gid 0; rm -f $tmp"
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ --exclude=deploy.sh --exclude=mesh/mcdata/lab -C server mesh
  push "$CT" "$tarball" /tmp/agent.tgz 0600
  rm -f "$tarball"
  ct_sh <<SH
set -e
rm -rf $APP/new && mkdir -p $APP/new /etc/star-agent && tar --no-same-owner -xzf /tmp/agent.tgz -C $APP/new && rm /tmp/agent.tgz
PYTHONPATH=$APP/new PYTHONDONTWRITEBYTECODE=1 python3 -c 'import mesh.agent.service' || { echo 'new release does not import: live release kept'; rm -rf $APP/new; exit 3; }
if [ -d $APP/app ]; then rm -rf $APP/previous && mv $APP/app $APP/previous; fi
mv $APP/new $APP/app
chown -R root:root $APP/app
[ -f /etc/star-agent/agent.json ] || echo '{}' > /etc/star-agent/agent.json
chown root:starmesh /etc/star-agent/agent.json && chmod 640 /etc/star-agent/agent.json
install -m 644 $APP/app/mesh/agent/star-mesh-agent.service /etc/systemd/system/star-mesh-agent.service
systemctl daemon-reload && systemctl enable star-mesh-agent.service >/dev/null 2>&1
systemctl restart star-mesh-agent.service; sleep 2; systemctl is-active star-mesh-agent.service
curl -s -m 3 http://127.0.0.1:8104/health; echo
SH
}

step_front() {
  push "$MC" server/mesh/agent/loadfront.py /opt/mcp/loadfront.py 0644
  mc_sh <<'SH'
set -e
cat > /etc/systemd/system/star-load-front.service <<'UNIT'
[Unit]
Description=STAR real-server load front (loadfront.py -> loadtest.py) on :8106
After=network-online.target mc-compile.service

[Service]
Environment=LOAD_PORT=8106
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/opt/mcp
ExecStart=/usr/bin/python3 /opt/mcp/loadfront.py
Restart=always
RestartSec=3
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now star-load-front.service >/dev/null 2>&1
systemctl restart star-load-front.service; sleep 1; systemctl is-active star-load-front.service
SH
  ct_sh <<'SH'
set -e
python3 - <<'PY'
import json, urllib.parse
v = json.load(open("/var/lib/star-verify/verify.json"))
u = urllib.parse.urlsplit(v["jvm_url"])
path = "/etc/star-agent/agent.json"
cfg = json.load(open(path))
cfg["load_url"] = f"{u.scheme}://{u.hostname}:8106"
json.dump(cfg, open(path, "w"), indent=1)
print("load_url set")
PY
systemctl restart star-mesh-agent.service; sleep 2; systemctl is-active star-mesh-agent.service
SH
}

step_rollback() {
  ct_sh <<SH
[ -d $APP/previous ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous $APP/app && systemctl restart star-mesh-agent.service
SH
  echo "rolled back"
}
step_status() { ct systemctl --no-pager --lines=5 status star-mesh-agent.service || true; }
step_logs() { ct journalctl -u star-mesh-agent.service --no-pager -n "${MESH_LINES:-40}"; }
step_remove() {
  ct_sh <<SH
systemctl disable --now star-mesh-agent.service 2>/dev/null; rm -f /etc/systemd/system/star-mesh-agent.service
systemctl daemon-reload; rm -rf $APP /etc/star-agent
SH
  mc_sh <<'SH'
systemctl disable --now star-load-front.service 2>/dev/null; rm -f /etc/systemd/system/star-load-front.service /opt/mcp/loadfront.py
systemctl daemon-reload
SH
  echo "agent service + load front removed (the router serves litha-agent as plain litha while :8104 is down)"
}

step="${1:?usage: deploy.sh install|front|status|logs|rollback|remove}"
"step_${step//-/_}" "$@"
