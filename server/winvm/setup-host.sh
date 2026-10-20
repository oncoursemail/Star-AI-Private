#!/bin/bash
# Create (or update) the LXD container that runs the throwaway Windows VMs with plain QEMU.
# Run on the server host as a member of the lxd group (no sudo):   bash setup-host.sh [pool] [cpus] [memory]
#
# Why a container around QEMU instead of LXD VMs: LXD refuses limits.cpu.priority for VMs, and without root the
# only storage on the big disk is a `dir` pool (full copies, no copy-on-write). Inside this container QEMU gets
# qcow2 copy-on-write clones of one golden disk, a saved running-memory state to resume from, and the container's
# cgroup limits (cpu set, cpu.weight, memory) apply to every VM in it.
set -euo pipefail
NAME=${WINVM_CONTAINER:-winvm-host}
POOL=${1:-winvm}
CPUS=${2:-8}
MEM=${3:-20GiB}
NET=${WINVM_NETWORK:-starnat0}
HERE=$(cd "$(dirname "$0")" && pwd)

if ! lxc info "$NAME" >/dev/null 2>&1; then
  lxc launch ubuntu:24.04 "$NAME" -s "$POOL" -n "$NET" -q
fi
lxc config set "$NAME" limits.cpu="$CPUS" limits.memory="$MEM" limits.cpu.priority=0 limits.disk.priority=0 \
  boot.autostart=true
lxc config device show "$NAME" | grep -q '^kvm:' || \
  lxc config device add "$NAME" kvm unix-char source=/dev/kvm mode=0666 -q
for _ in $(seq 1 30); do lxc exec "$NAME" -- systemctl is-system-running --wait >/dev/null 2>&1 && break; sleep 2; done
lxc exec "$NAME" -- bash -c 'export DEBIAN_FRONTEND=noninteractive
  command -v qemu-system-x86_64 >/dev/null && command -v xorriso >/dev/null && exit 0
  apt-get update -qq && apt-get install -y -qq --no-install-recommends qemu-system-x86 qemu-utils ovmf xorriso \
    python3 curl ca-certificates >/dev/null'
lxc exec "$NAME" -- mkdir -p /opt/winvm/guest /srv/winvm/iso /srv/winvm/golden /srv/winvm/clones /run/winvm
lxc file push -q "$HERE/winvm.py" "$HERE/tools.json" "$NAME/opt/winvm/"
lxc file push -q "$HERE"/guest/* "$NAME/opt/winvm/guest/"
lxc exec "$NAME" -- chmod 755 /opt/winvm/winvm.py

# Chat/lock gate: brain_watch.py inside the brain container publishes {chat, busy, lock}; the gate in this container
# freezes every VM while it says so. Shared folder: /data/star-re/winvm/shared (rw in starai, ro here).
BRAIN=${WINVM_BRAIN:-starai}
lxc exec "$BRAIN" -- mkdir -p /opt/star/winvm /data/star-re/winvm/shared
lxc file push -q "$HERE/brain_watch.py" "$BRAIN/opt/star/winvm/brain_watch.py"
lxc exec "$BRAIN" -- bash -c 'cat > /etc/systemd/system/star-winvm-watch.service <<EOF
[Unit]
Description=STAR brain state for the Windows CI VM gate (server/winvm/brain_watch.py)
[Service]
ExecStart=/usr/bin/python3 /opt/star/winvm/brain_watch.py /data/star-re/winvm/shared/brain-state.json
Nice=10
MemoryMax=64M
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload; systemctl stop star-winvm-watch 2>/dev/null; systemctl enable --now star-winvm-watch'
lxc config device show "$NAME" | grep -q '^shared:' || \
  lxc config device add "$NAME" shared disk source=/data/star-re/winvm/shared path=/srv/winvm/shared readonly=true -q
lxc exec "$NAME" -- bash -c 'cat > /etc/systemd/system/winvm-gate.service <<EOF
[Unit]
Description=Freeze the Windows CI VMs while STAR serves chat or a quiet lock is held (winvm.py gate)
[Service]
ExecStart=/usr/bin/python3 /opt/winvm/winvm.py gate
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload; systemctl stop winvm-gate 2>/dev/null; systemctl enable --now winvm-gate'
lxc exec "$NAME" -- test -r /dev/kvm && echo "$NAME ready: $(lxc exec "$NAME" -- qemu-system-x86_64 --version | head -1)"
