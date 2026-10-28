#!/usr/bin/env bash
# STAR compute-mesh router deployment, run from the owner's PC (Git Bash) in a checkout of this repo.
#
#   MESH_B1=<user>@<brain1> bash server/mesh/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   container  LXD container `star-mesh` on brain 1 (2 CPUs, CPU priority 0, 512 MiB, own dir pool on /data,
#              LAN NIC + starnat0 NIC to reach the brain router), then `setup`
#   setup      inside: second NIC without a default route, ufw (8100 only from the LAN and starnat0), service user
#   secrets    the brain's client key file (copied container to container, never shown) + ~/.star/mesh_token
#   config     /etc/star-mesh/mesh.json: brain_url = starai's starnat0 address, nodes from ~/.star/mesh-nodes.json
#              (private, not in git: {"nodes": [{"name": "owner-pc", "status_url": "http://<ip>:8099/status"}]})
#   install    copy server/mesh + the unit; restart (keeps the previous release for `rollback`)
#              (first deployment order: container, secrets, config, install)
#   start | stop | status | logs | rollback | remove
#
# No sudo anywhere: the brain host uses the lxd group. The starai container is only read (key file, address).
set -euo pipefail
cd "$(dirname "$0")/../.."
B1="${MESH_B1:?set MESH_B1=user@brain1}"
CT=star-mesh
POOL=mesh
POOL_DIR=/data/star-re/star-mesh
APP=/opt/star-mesh
ETC=/etc/star-mesh
STAR="$HOME/.star"
LAN="${MESH_LAN:-}"   # default: the subnet of the container's LAN NIC (eth0)

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push_file() {   # push_file LOCAL REMOTE MODE  (through the brain 1 host; contents never printed)
  local tmp="/tmp/mesh-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "chmod 600 $tmp && lxc file push $tmp $CT$2 --mode $3 --uid 0 --gid 0; rm -f $tmp"
}

step_container() {
  if b1 lxc info "$CT" >/dev/null 2>&1; then echo "container exists"; else
    b1 "lxc storage show $POOL >/dev/null 2>&1 || { lxc exec starai -- mkdir -p $POOL_DIR && lxc storage create $POOL dir source=$POOL_DIR; }"
    local image
    image=$(b1 "lxc image list --format csv -c fd | grep 'ubuntu 24.04 LTS amd64' | grep -v VIRTUAL | head -1 | cut -d, -f1")
    b1 lxc init "${image:-ubuntu:24.04}" "$CT" -s "$POOL" \
      -c limits.cpu=2 -c limits.cpu.priority=0 -c limits.memory=512MiB -c limits.memory.swap=false \
      -c limits.disk.priority=0 -c limits.processes=256 -c boot.autostart=true -c security.idmap.isolated=true
    b1 lxc config device add "$CT" eth0 nic nictype=macvlan parent=eno2 name=eth0
    b1 lxc config device add "$CT" eth1 nic network=starnat0 name=eth1
    b1 lxc start "$CT"
    sleep 8
  fi
  step_setup
}

step_setup() {
  ct_sh <<SH
cat > /etc/netplan/60-star-mesh.yaml <<'NET'
network:
  version: 2
  ethernets:
    eth0: {dhcp4: true}
    eth1: {dhcp4: true, dhcp4-overrides: {use-routes: false, use-dns: false}}
NET
chmod 600 /etc/netplan/60-star-mesh.yaml
netplan apply 2>/dev/null
systemctl disable --now snapd.service snapd.socket unattended-upgrades.service >/dev/null 2>&1 || true
export DEBIAN_FRONTEND=noninteractive
command -v ufw >/dev/null || { apt-get update -qq >/dev/null && apt-get install -y -qq ufw >/dev/null; }
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null && ufw default allow outgoing >/dev/null
subnet() { python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "\$(ip -4 -o addr show \$1 | awk '{print \$4}' | head -1)"; }
lan="$LAN"; [ -n "\$lan" ] || lan=\$(subnet eth0)
ufw allow from "\$lan" to any port 8100 proto tcp >/dev/null
ufw allow from "\$(subnet eth1)" to any port 8100 proto tcp >/dev/null
ufw --force enable >/dev/null
id starmesh >/dev/null 2>&1 || useradd --system --home-dir $APP --no-create-home --shell /usr/sbin/nologin starmesh
mkdir -p $APP $ETC && chown root:starmesh $ETC && chmod 750 $ETC
ip -4 -o addr show | awk '{print \$2, \$4}'
ufw status | sed -n '1,12p'
SH
}

step_secrets() {
  [ -f "$STAR/mesh_token" ] || { echo "need $STAR/mesh_token (32-byte hex, owner-only)"; exit 2; }
  b1 "t=/tmp/mesh-keys-\$RANDOM; lxc file pull starai/opt/star/secrets/api_keys \$t && chmod 600 \$t && lxc file push \$t $CT$ETC/api_keys --mode 0640 --uid 0 --gid 0; rm -f \$t"
  push_file "$STAR/mesh_token" "$ETC/mesh_token" 0640
  ct chgrp starmesh "$ETC/api_keys" "$ETC/mesh_token"
  echo "secrets in place ($(ct wc -l "$ETC/api_keys" | awk '{print $1}') client keys + mesh token)"
}

step_config() {
  local brain nodes="$STAR/mesh-nodes.json" tmp
  brain=$(b1 "lxc list starai --format csv -c 4" | tr -d '"' | tr '\n' ',' | tr ',' '\n' | grep eth1 | awk '{print $1}')
  [ -n "$brain" ] || { echo "could not find starai's starnat0 address"; exit 2; }
  tmp=$(mktemp)
  python - "$brain" "$nodes" > "$tmp" <<'PY'
import json, pathlib, sys
nodes = pathlib.Path(sys.argv[2])
cfg = {"port": 8100, "brain_url": f"http://{sys.argv[1]}:8080", "nodes": [], "hedge": False,
       "client_keys_file": "/etc/star-mesh/api_keys", "mesh_token_file": "/etc/star-mesh/mesh_token"}
if nodes.is_file():
    cfg.update(json.loads(nodes.read_text(encoding="utf-8")))
print(json.dumps(cfg, indent=2))
PY
  push_file "$tmp" "$ETC/mesh.json" 0640
  rm -f "$tmp"
  ct chgrp starmesh "$ETC/mesh.json"
  ct systemctl try-restart star-mesh.service || true
  echo "config pushed"
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ -C server mesh
  push_file "$tarball" /tmp/mesh.tgz 0600
  rm -f "$tarball"
  ct_sh <<SH
rm -rf $APP/new && mkdir -p $APP/new && tar --no-same-owner -xzf /tmp/mesh.tgz -C $APP/new && rm /tmp/mesh.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mv $APP/app $APP/previous; fi
mv $APP/new $APP/app
install -m 644 $APP/app/mesh/star-mesh.service /etc/systemd/system/star-mesh.service
systemctl daemon-reload && systemctl enable star-mesh.service >/dev/null 2>&1
systemctl restart star-mesh.service
sleep 2; systemctl is-active star-mesh.service
curl -s -m 3 http://127.0.0.1:8100/health; echo
SH
  echo "installed (previous release kept in $APP/previous; undo: deploy.sh rollback)"
}

step_rollback() {
  ct_sh <<SH
[ -d $APP/previous ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous $APP/app && systemctl restart star-mesh.service
SH
  echo "rolled back"
}

step_start() { ct systemctl start star-mesh.service; }
step_stop() { ct systemctl stop star-mesh.service; }
step_status() {
  b1 lxc list "$CT" -c ns4 --format csv
  ct systemctl --no-pager --lines=5 status star-mesh.service || true
}
step_logs() { ct journalctl -u star-mesh.service --no-pager -n "${MESH_LINES:-40}"; }
step_remove() {
  b1 "lxc delete --force $CT 2>/dev/null; lxc storage delete $POOL 2>/dev/null || true"
  echo "removed container and pool (~/.star/mesh_token and ~/.star/mesh-nodes.json kept)"
}

step="${1:?usage: deploy.sh container|setup|secrets|config|install|start|stop|status|logs|rollback|remove}"
"step_${step//-/_}"
