#!/bin/bash
# star-fast speed while a VM is off / idle / building. Run on the server-1 host as the LXD user, under the quiet lock.
#   impact.sh <vm> <step>...   steps: novm | idle | build | frozen | cpus=<limits.cpu value>  (bench after each)
# frozen = build running, VM paused during the bench (what the chat gate does).
# cpus=... restarts the VM with that vCPU count or pin set. The VM needs /root/load.sh (endless parallel compile).
set -u
vm=$1; shift
bench() { lxc exec starai -- python3 /root/chatbench.py --tag "$1" | tee -a ~/winvm/bench-full.log | grep RESULT; }
agent() { for _ in $(seq 1 60); do lxc exec "$vm" -- true 2>/dev/null && return 0; sleep 2; done; return 1; }
noload() { lxc exec "$vm" -- bash -c 'pkill -f load.sh; pkill make; pkill cc1' >/dev/null 2>&1 || true; }
# Never leave the load running after the lock is gone (time limit kill, ssh hang-up, error).
trap 'noload; lxc stop -f "$vm" >/dev/null 2>&1' EXIT
trap 'exit 1' HUP INT TERM
for step in "$@"; do
  case $step in
    novm) lxc stop -f "$vm" 2>/dev/null; sleep 5; bench novm ;;
    idle) lxc start "$vm" 2>/dev/null; agent; noload; sleep 40; bench "idle[$(lxc config get "$vm" limits.cpu)]" ;;
    build) lxc start "$vm" 2>/dev/null; agent; lxc exec "$vm" -- bash -c 'nohup /root/load.sh >/dev/null 2>&1 &'; sleep 25
           bench "build[$(lxc config get "$vm" limits.cpu)]"; noload; tail -1 <(lxc exec "$vm" -- cat /root/load.log 2>/dev/null) ;;
    frozen) lxc start "$vm" 2>/dev/null; agent; lxc exec "$vm" -- bash -c 'nohup /root/load.sh >/dev/null 2>&1 &'; sleep 25
           lxc pause "$vm"; bench "frozen[$(lxc config get "$vm" limits.cpu)]"; lxc start "$vm"; noload ;;
    cpus=*) lxc stop -f "$vm" 2>/dev/null; lxc config set "$vm" limits.cpu="${step#cpus=}" ;;
  esac
done
