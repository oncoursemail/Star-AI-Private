#!/usr/bin/env bash
# Metallic Control deployment, run from the owner's PC (Git Bash) in a checkout of this repo.
#
#   MC_B1=<user>@<brain1>  MC_B2=<user>@<brain2>  bash server/control/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   container   create LXD container `metallic-control` on brain 1 (2 CPUs, CPU priority 0, 512 MiB, own dir pool on
#               /data, LAN NIC + starnat0 NIC to reach the host gate and the brain router), then `setup`
#   setup       inside the container: second NIC without a default route, service user, folders
#   secrets     tokens (owner-only on the PC: ~/.star/metallic-control-token, ~/.star/metallic-control-push-token),
#               brain key, a read-only forge token, the collector's own SSH key, a self-signed TLS certificate
#   config      push the private control.toml (MC_PRIVATE, default ~/.metallic/control)
#   gate        install server/control/metallic_control_gate.py + gate.json on both hosts and one authorized_keys line
#               (restrict, from=MC_FROM, forced command) per host for the collector's key
#   install     copy the metallic package + the built UI (metallic/control-ui/dist) and the unit; restart (keeps the
#               previous release for `rollback`)
#   agent       PC agent: copy of the package in %LOCALAPPDATA%\MetallicControl + a Startup-folder shortcut (no admin)
#   start | stop | status | rollback
#   remove      undo everything: PC task, authorized_keys lines (backup kept), gate files, the container and its pool
#
# No sudo anywhere: brain hosts use the lxd group; the container is configured as root inside itself only.
set -euo pipefail
cd "$(dirname "$0")/../.."
B1="${MC_B1:?set MC_B1=user@brain1}"
B2="${MC_B2:?set MC_B2=user@brain2}"
CT=metallic-control
POOL=control
POOL_DIR=/data/star-re/metallic-control
APP=/opt/metallic-control
ETC=/etc/metallic-control
STAR="$HOME/.star"
LOGIN_TOKEN="$STAR/metallic-control-token"
PUSH_TOKEN="$STAR/metallic-control-push-token"
PRIVATE="${MC_PRIVATE:-$HOME/.metallic/control}"
PY="${MC_PYTHON:-python}"
AGENT_LNK="Metallic Control PC agent.lnk"

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
b2() { ssh -o BatchMode=yes "$B2" "$@"; }
# ssh joins its arguments into one remote shell line: quote every word for the host shell, and send multi-line
# container scripts on stdin instead of through the command line.
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push_file() {   # push_file LOCAL REMOTE MODE [GID]  (through the brain 1 host; contents never printed)
  local tmp="/tmp/mc-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "chmod 600 $tmp && lxc file push $tmp $CT$2 --mode $3 --uid 0 --gid ${4:-0}; rm -f $tmp"
}
owner_only() {  # Windows ACL: only the current user may read the file
  icacls "$(cygpath -w "$1")" /inheritance:r /grant:r "$USERNAME:(R,W)" >/dev/null
}
mc_gid() { ct id -g mcontrol | tr -d '\r'; }

step_container() {
  if b1 lxc info "$CT" >/dev/null 2>&1; then echo "container exists"; else
    # the pool folder is made through starai's /data/star-re mount (its root owns /data/star-re; we have no sudo)
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
  ct_sh <<EOF
cat > /etc/netplan/60-metallic-control.yaml <<'NET'
network:
  version: 2
  ethernets:
    eth0: {dhcp4: true}
    eth1: {dhcp4: true, dhcp4-overrides: {use-routes: false, use-dns: false}}
NET
chmod 600 /etc/netplan/60-metallic-control.yaml
netplan apply 2>/dev/null
id mcontrol >/dev/null 2>&1 || useradd --system --home-dir /var/lib/metallic-control --create-home --shell /usr/sbin/nologin mcontrol
mkdir -p $APP $ETC/ssh $ETC/tls
chown root:mcontrol $ETC $ETC/ssh $ETC/tls
chmod 750 $ETC $ETC/ssh $ETC/tls
systemctl disable --now snapd.service snapd.socket unattended-upgrades.service >/dev/null 2>&1 || true
sleep 3
ip -4 -o addr show | awk '{print \$2, \$4}'
EOF
}

step_secrets() {
  mkdir -p "$STAR"
  for f in "$LOGIN_TOKEN" "$PUSH_TOKEN"; do
    if [ ! -f "$f" ]; then PYTHONPATH=metallic "$PY" -m metallic control token "$(cygpath -m "$f")"; owner_only "$f"; fi
  done
  local gid; gid=$(mc_gid)
  push_file "$LOGIN_TOKEN" "$ETC/login-token" 0640 "$gid"
  push_file "$PUSH_TOKEN" "$ETC/push-token" 0640 "$gid"
  push_file "$STAR/server_api_key" "$ETC/brain-key" 0640 "$gid"
  # a read-only forge token for the collector, written straight from the forge into the container (never shown)
  if ! b1 "lxc exec $CT -- test -s $ETC/forge-token"; then
    b1 "lxc exec metallic-forge -- su git -s /bin/sh -c 'cd /var/lib/forgejo && forgejo --config /etc/forgejo/app.ini admin user generate-access-token --username metallic-bot --token-name metallic-control-ro-$(date +%Y%m%d%H%M) --scopes read:repository,read:organization,read:issue,read:user,read:admin --raw' | lxc exec $CT -- sh -c 'umask 027; cat > $ETC/forge-token; chgrp mcontrol $ETC/forge-token'"
  fi
  ct_sh <<EOF
lan=\$(ip -4 -o addr show eth0 | awk '{print \$4}' | cut -d/ -f1)
[ -f $ETC/ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -C metallic-control -f $ETC/ssh/id_ed25519
chown root:mcontrol $ETC/ssh/id_ed25519 && chmod 640 $ETC/ssh/id_ed25519
[ -f $ETC/tls/cert.pem ] || openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 825 \
  -subj /CN=metallic-control -addext "subjectAltName=IP:\$lan" -keyout $ETC/tls/key.pem -out $ETC/tls/cert.pem 2>/dev/null
chown root:mcontrol $ETC/tls/key.pem && chmod 640 $ETC/tls/key.pem
openssl x509 -in $ETC/tls/cert.pem -noout -fingerprint -sha256
EOF
}

step_config() {
  [ -f "$PRIVATE/control.toml" ] || { echo "need $PRIVATE/control.toml (see server/control/control.example.toml)"; exit 2; }
  push_file "$PRIVATE/control.toml" "$ETC/control.toml" 0640 "$(mc_gid)"
}

gate_install() {   # gate_install HOST GATE_JSON_FILE
  local host="$1" home pub
  home=$(ssh -o BatchMode=yes "$host" 'echo $HOME')
  ssh -o BatchMode=yes "$host" "mkdir -p ~/.local/share/metallic-control ~/.local/bin"
  scp -q server/control/metallic_control_gate.py "$host:.local/share/metallic-control/metallic_control_gate.py"
  scp -q "$2" "$host:.local/share/metallic-control/gate.json"
  ssh -o BatchMode=yes "$host" "printf '#!/bin/sh\n# Metallic Control host gate: forced command for the collector key (server/control/deploy.sh gate)\nexec /usr/bin/python3 %s/.local/share/metallic-control/metallic_control_gate.py --config %s/.local/share/metallic-control/gate.json\n' $home $home > ~/.local/bin/metallic-control-gate && chmod 755 ~/.local/bin/metallic-control-gate"
  pub=$(ct cat "$ETC/ssh/id_ed25519.pub" | tr -d '\r')
  ssh -o BatchMode=yes "$host" "cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak-metallic-control && grep -v ' metallic-control\$' ~/.ssh/authorized_keys > ~/.ssh/ak.tmp; echo 'restrict,from=\"${MC_FROM:?set MC_FROM to the collector subnets}\",command=\"$home/.local/bin/metallic-control-gate\" $pub' >> ~/.ssh/ak.tmp && chmod 600 ~/.ssh/ak.tmp && mv ~/.ssh/ak.tmp ~/.ssh/authorized_keys"
}

step_gate() {
  [ -f "$PRIVATE/gate-brain1.json" ] && [ -f "$PRIVATE/gate-brain2.json" ] ||
    { echo "need $PRIVATE/gate-brain{1,2}.json (see server/control/gate.example.json)"; exit 2; }
  gate_install "$B1" "$PRIVATE/gate-brain1.json"
  gate_install "$B2" "$PRIVATE/gate-brain2.json"
  # host keys as the collector sees them (brain 1 through starnat0, brain 2 over the LAN)
  ct_sh <<EOF
ssh-keyscan -T 5 -t ed25519 ${MC_B1_GATE_ADDR:?set MC_B1_GATE_ADDR to brain 1 as the container sees it} ${B2#*@} 2>/dev/null > $ETC/ssh/known_hosts
chgrp mcontrol $ETC/ssh/known_hosts && chmod 640 $ETC/ssh/known_hosts
wc -l < $ETC/ssh/known_hosts
EOF
}

step_install() {
  [ -f metallic/control-ui/dist/index.html ] || { echo "build the UI first: npm run build in metallic/control-ui"; exit 2; }
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ -C metallic metallic -C control-ui dist -C ../../server/control metallic-control.service
  push_file "$tarball" /tmp/mc.tgz 0600
  rm -f "$tarball"
  ct_sh <<EOF
rm -rf $APP/new && mkdir -p $APP/new && tar --no-same-owner -xzf /tmp/mc.tgz -C $APP/new && rm /tmp/mc.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mkdir -p $APP/previous && mv $APP/app $APP/ui $APP/previous/; fi
mkdir -p $APP/app && mv $APP/new/metallic $APP/app/ && mv $APP/new/dist $APP/ui
install -m 644 $APP/new/metallic-control.service /etc/systemd/system/metallic-control.service && rm -rf $APP/new
systemctl daemon-reload && systemctl enable metallic-control.service >/dev/null 2>&1
systemctl restart metallic-control.service
EOF
  echo "installed (previous release kept in $APP/previous; undo: deploy.sh rollback)"
}

step_rollback() {
  ct_sh <<EOF
[ -d $APP/previous/app ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app $APP/ui && mv $APP/previous/app $APP/previous/ui $APP/ && systemctl restart metallic-control.service
EOF
  echo "rolled back"
}

step_agent() {
  local cfg="$HOME/.metallic/control-agent.toml"
  [ -f "$cfg" ] || { echo "need $cfg (url, push_token_file, star_ci_cmd, gh_repo)"; exit 2; }
  local dest="$LOCALAPPDATA/MetallicControl/app"
  agent_stop
  rm -rf "$dest.new" && mkdir -p "$dest.new" && cp -r metallic/metallic "$dest.new/"
  find "$dest.new" -name __pycache__ -prune -exec rm -rf {} +
  rm -rf "$dest" && mv "$dest.new" "$dest"
  # start at logon without admin rights (schtasks /sc onlogon needs admin): a shortcut in the user's Startup folder
  powershell -NoProfile -Command "\$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\\$AGENT_LNK'); \$s.TargetPath = '$(agent_pyw)'; \$s.Arguments = '-m metallic control agent'; \$s.WorkingDirectory = '$(cygpath -w "$dest")'; \$s.WindowStyle = 7; \$s.Description = 'Metallic Control PC agent (server/control/deploy.sh agent)'; \$s.Save()"
  agent_start
  echo "PC agent installed (Startup-folder shortcut) and started"
}

agent_pyw() { echo "$(dirname "$(cygpath -w "$(command -v "$PY")")")\\pythonw.exe"; }
agent_start() {
  local dest="$LOCALAPPDATA/MetallicControl/app"
  [ -d "$dest" ] || return 0
  powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -WorkingDirectory '$(cygpath -w "$dest")' -FilePath '$(agent_pyw)' -ArgumentList '-m','metallic','control','agent'"
}

agent_stop() {
  powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { \$_.CommandLine -like '*metallic control agent*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId }" || true
}

step_start() { ct systemctl start metallic-control.service; agent_start; }
step_stop() { ct systemctl stop metallic-control.service; agent_stop; }
step_status() {
  b1 lxc list "$CT" -c ns4 --format csv
  ct systemctl --no-pager --lines=5 status metallic-control.service || true
  echo "authorized_keys lines: brain1 $(b1 "grep -c ' metallic-control\$' ~/.ssh/authorized_keys"), brain2 $(b2 "grep -c ' metallic-control\$' ~/.ssh/authorized_keys")"
}

step_remove() {
  agent_stop
  powershell -NoProfile -Command "Remove-Item -ErrorAction SilentlyContinue ([Environment]::GetFolderPath('Startup') + '\\$AGENT_LNK')"
  for host in "$B1" "$B2"; do
    ssh -o BatchMode=yes "$host" "cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak-metallic-control-remove; grep -v ' metallic-control\$' ~/.ssh/authorized_keys > ~/.ssh/ak.tmp; chmod 600 ~/.ssh/ak.tmp; mv ~/.ssh/ak.tmp ~/.ssh/authorized_keys; rm -rf ~/.local/share/metallic-control ~/.local/bin/metallic-control-gate"
  done
  b1 "lxc delete --force $CT 2>/dev/null; lxc storage delete $POOL 2>/dev/null || true"
  echo "removed (owner-only tokens kept in ~/.star; delete them by hand if wanted)"
}

"step_${1:?usage: deploy.sh container|setup|secrets|config|gate|install|agent|start|stop|status|rollback|remove}"
