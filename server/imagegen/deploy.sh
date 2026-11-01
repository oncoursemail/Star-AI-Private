#!/usr/bin/env bash
# STAR image service on brain 1: its own LXD container (star-images, LAN address by macvlan, ufw: :8095 from the
# LAN only), the engine files read-only from the host folder below, brain key auth. Run from the owner's PC
# (Git Bash) in a checkout of this repo. Never touches the brain container, the llama router or its models.
#
#   IMAGES_B1=<user>@<brain1> IMAGES_LAN=<lan cidr> bash server/imagegen/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   create     the container (low CPU priority, 32 GiB memory cap, autostart), the read-only host folder, user, ufw
#   install    copy engine.py + service.py + the unit + config to the container, restart
#   secrets    copy the brain key file (~/.star/server_api_key on this PC) to /etc/star-images/api_keys
#   status | logs | stop | start | remove
#
# Host folder (made by the bench, docs/agents/server-image-bench-20261028.md): $HOST_DIR with venv/ (Python 3.12,
# torch 2.14.1+cpu, diffusers 0.41.0, transformers 5.19.0, openvino 2026.4.1) and models/ (sana-sprint-0.6b,
# dc-ae-lite). It must be world-readable: the container maps the host user to nobody.
set -euo pipefail
cd "$(dirname "$0")/../.."
B1="${IMAGES_B1:?set IMAGES_B1=user@brain1}"
CT=star-images
APP=/opt/star-images
HOST_DIR=/data/star/imagegen
PARENT_NIC="${IMAGES_NIC:-eno2}"

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push() {   # push LOCAL REMOTE MODE (through the brain 1 host)
  local tmp="/tmp/images-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "lxc file push --quiet $tmp $CT$2 --mode $3 --uid 0 --gid 0; rm -f $tmp"
}

step_create() {
  local lan="${IMAGES_LAN:?set IMAGES_LAN=<lan cidr allowed to call the service>}"
  b1 sh -se <<SH
set -e
if ! lxc info $CT >/dev/null 2>&1; then
  lxc storage show images >/dev/null 2>&1 || { mkdir -p $HOST_DIR-pool; lxc storage create images dir source=$HOST_DIR-pool; }
  fp=\$(lxc image list --format csv -c ft | awk -F, '\$2=="CONTAINER" {print \$1; exit}')
  lxc init "\$fp" $CT -s images -c boot.autostart=true -c limits.memory=32GiB -c limits.memory.swap=false \
    -c limits.cpu.priority=0 -c limits.processes=512 -c security.idmap.isolated=true
  lxc config device add $CT eth0 nic nictype=macvlan parent=$PARENT_NIC name=eth0
  lxc config device add $CT engine disk source=$HOST_DIR path=$HOST_DIR readonly=true
  lxc start $CT
  sleep 8
fi
chmod -R o+rX $HOST_DIR/venv $HOST_DIR/models
SH
  ct_sh <<SH
set -e
id starimages >/dev/null 2>&1 || useradd --system --home /var/cache/star-images --shell /usr/sbin/nologin starimages
mkdir -p /etc/star-images /var/cache/star-images $APP
chown starimages:starimages /var/cache/star-images && chmod 750 /var/cache/star-images
chown root:starimages /etc/star-images && chmod 750 /etc/star-images
mkdir -p /var/cache/star-images/openvino && cp -n $HOST_DIR/ovcache/*.xml $HOST_DIR/ovcache/*.bin /var/cache/star-images/openvino/ 2>/dev/null || true
chown -R starimages:starimages /var/cache/star-images
if command -v ufw >/dev/null; then
  ufw --force reset >/dev/null; ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null
  ufw allow from $lan to any port 8095 proto tcp >/dev/null; ufw --force enable >/dev/null; ufw status | head -8
else
  echo "WARNING: no ufw in the container: the service still needs the brain key, but is reachable from any network"
fi
ip -4 -o addr show eth0 | awk '{print \$4}'
SH
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" -C server/imagegen engine.py service.py star-images.service
  push "$tarball" /tmp/images.tgz 0600
  rm -f "$tarball"
  ct_sh <<SH
set -e
rm -rf $APP/new && mkdir -p $APP/new && tar --no-same-owner -xzf /tmp/images.tgz -C $APP/new && rm /tmp/images.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mv $APP/app $APP/previous; fi
mv $APP/new $APP/app && chown -R root:root $APP/app
[ -f /etc/star-images/config.json ] || echo '{}' > /etc/star-images/config.json
chown root:starimages /etc/star-images/config.json && chmod 640 /etc/star-images/config.json
install -m 644 $APP/app/star-images.service /etc/systemd/system/star-images.service
systemctl daemon-reload && systemctl enable star-images.service >/dev/null 2>&1 && systemctl restart star-images.service
sleep 3; systemctl is-active star-images.service; curl -s -m 3 http://127.0.0.1:8095/health; echo
SH
}

step_secrets() {
  local key="${IMAGES_KEY_FILE:-$HOME/.star/server_api_key}"
  [ -s "$key" ] || { echo "no key file at $key"; exit 1; }
  push "$key" /etc/star-images/api_keys 0640
  ct_sh <<SH
chown root:starimages /etc/star-images/api_keys && chmod 640 /etc/star-images/api_keys && echo "key file in place"
SH
}

case "${1:-}" in
  create) step_create ;;
  install) step_install ;;
  secrets) step_secrets ;;
  status) b1 "lxc exec $CT -- sh -c 'systemctl is-active star-images; curl -s -m 3 http://127.0.0.1:8095/health; echo; ps -o rss=,etime= -C python3,python | head -3'" ;;
  logs) b1 "lxc exec $CT -- journalctl -u star-images -n 60 --no-pager" ;;
  stop) b1 "lxc exec $CT -- systemctl stop star-images" ;;
  start) b1 "lxc exec $CT -- systemctl start star-images" ;;
  remove) b1 "lxc stop $CT --force; lxc delete $CT" ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
