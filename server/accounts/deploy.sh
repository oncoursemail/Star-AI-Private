#!/usr/bin/env bash
# Metallic accounts + social deployment, run from the owner's PC (Git Bash) in a checkout of this repo.
#
#   MA_B1=<user>@<brain1> [MA_CT=metallic-accounts-test] bash server/accounts/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   container  LXD container on brain 1 (1 CPU, CPU priority 0, 384 MiB, own dir pool on /data, LAN NIC), then setup
#   setup      inside: apt python3-argon2 python3-cryptography, service user, folders, nightly local DB snapshot timer
#   secrets    signing key (ES256) + data key (AES-GCM for TOTP secrets) + self-signed TLS cert; prints the SHA-256
#              fingerprint the launcher pins (also saved to ~/.star/metallic-accounts-fingerprint)
#   install    copy the metallic package + unit + config; restart (keeps the previous release for `rollback`)
#              (first deployment order: container, install, secrets, e2e)
#   e2e        run server/accounts/e2e.py inside the container against https://127.0.0.1, then delete its e2e_ accounts
#   providers  push ~/.metallic/accounts/providers.toml + *.secret (server/accounts/providers.md), restart
#   owner-code one-time owner sign-up code -> ~/.star/metallic-accounts-owner-code (owner-only; never printed)
#   start | stop | status | rollback | remove
#
# No sudo anywhere: the brain host uses the lxd group; the container is configured as root inside itself only.
set -euo pipefail
cd "$(dirname "$0")/../.."
B1="${MA_B1:?set MA_B1=user@brain1}"
CT="${MA_CT:-metallic-accounts}"
POOL="${MA_POOL:-accounts}"
POOL_DIR="/data/star-re/$CT"
APP=/opt/metallic-accounts
ETC=/etc/metallic-accounts
VAR=/var/lib/metallic-accounts
STAR="$HOME/.star"
PORT=8475

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push_file() {   # push_file LOCAL REMOTE MODE  (through the brain 1 host; contents never printed)
  local tmp="/tmp/ma-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "chmod 600 $tmp && lxc file push $tmp $CT$2 --mode $3 --uid 0 --gid 0; rm -f $tmp"
}
owner_only() { icacls "$(cygpath -w "$1")" /inheritance:r /grant:r "$USERNAME:(R,W)" >/dev/null; }

step_container() {
  if b1 lxc info "$CT" >/dev/null 2>&1; then echo "container exists"; else
    b1 "lxc storage show $POOL >/dev/null 2>&1 || { lxc exec starai -- mkdir -p $POOL_DIR && lxc storage create $POOL dir source=$POOL_DIR; }"
    local image
    image=$(b1 "lxc image list --format csv -c fd | grep 'ubuntu 24.04 LTS amd64' | grep -v VIRTUAL | head -1 | cut -d, -f1")
    b1 lxc init "${image:-ubuntu:24.04}" "$CT" -s "$POOL" \
      -c limits.cpu=1 -c limits.cpu.priority=0 -c limits.memory=384MiB -c limits.memory.swap=false \
      -c limits.disk.priority=0 -c limits.processes=200 -c boot.autostart=true -c security.idmap.isolated=true
    b1 lxc config device add "$CT" eth0 nic nictype=macvlan parent=eno2 name=eth0
    b1 lxc start "$CT"
    sleep 10
  fi
  step_setup
}

step_setup() {
  ct_sh <<EOF
export DEBIAN_FRONTEND=noninteractive
systemctl disable --now snapd.service snapd.socket >/dev/null 2>&1 || true
apt-get update -qq >/dev/null && apt-get install -y -qq python3-argon2 python3-cryptography sqlite3 >/dev/null
id maccounts >/dev/null 2>&1 || useradd --system --home-dir $VAR --create-home --shell /usr/sbin/nologin maccounts
mkdir -p $APP $ETC/keys $ETC/tls $VAR/backups
chown root:maccounts $ETC $ETC/keys $ETC/tls && chmod 750 $ETC $ETC/keys $ETC/tls
chown maccounts:maccounts $VAR $VAR/backups && chmod 700 $VAR
cat > /etc/systemd/system/metallic-accounts-backup.service <<'UNIT'
[Unit]
Description=Metallic accounts: consistent SQLite snapshot (keeps 14)
[Service]
Type=oneshot
User=maccounts
ExecStart=/bin/sh -c 'sqlite3 $VAR/accounts.sqlite3 ".backup $VAR/backups/accounts-\$(date -u +%%Y%%m%%dT%%H%%M%%SZ).sqlite3" && ls -1t $VAR/backups/accounts-*.sqlite3 | tail -n +15 | xargs -r rm -f'
UNIT
cat > /etc/systemd/system/metallic-accounts-backup.timer <<'UNIT'
[Unit]
Description=Metallic accounts nightly snapshot
[Timer]
OnCalendar=*-*-* 03:20:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload && systemctl enable --now metallic-accounts-backup.timer >/dev/null 2>&1
python3 -c "import argon2, cryptography; print('argon2-cffi', argon2.__version__ if hasattr(argon2, '__version__') else '?', 'cryptography', cryptography.__version__)" 2>/dev/null
ip -4 -o addr show eth0 | awk '{print \$4}'
EOF
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ -C metallic metallic -C ../server/accounts metallic-accounts.service \
    accounts.example.toml e2e.py
  push_file "$tarball" /tmp/ma.tgz 0600
  rm -f "$tarball"
  ct_sh <<EOF
rm -rf $APP/new && mkdir -p $APP/new && tar --no-same-owner -xzf /tmp/ma.tgz -C $APP/new && rm /tmp/ma.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mkdir -p $APP/previous && mv $APP/app $APP/previous/; fi
mkdir -p $APP/app && mv $APP/new/metallic $APP/app/ && mv $APP/new/e2e.py $APP/
[ -f $ETC/accounts.toml ] || install -m 640 -g maccounts $APP/new/accounts.example.toml $ETC/accounts.toml
install -m 644 $APP/new/metallic-accounts.service /etc/systemd/system/metallic-accounts.service && rm -rf $APP/new
systemctl daemon-reload && systemctl enable metallic-accounts.service >/dev/null 2>&1
systemctl restart metallic-accounts.service
sleep 2; systemctl is-active metallic-accounts.service
EOF
  echo "installed (previous release kept in $APP/previous; undo: deploy.sh rollback)"
}

step_secrets() {
  ct_sh <<EOF
cd $ETC
[ -d $APP/app/metallic ] || { echo 'run deploy.sh install first'; exit 2; }
PYTHONPATH=$APP/app python3 -m metallic accounts init $ETC/keys
chown root:maccounts keys/* && chmod 640 keys/*
lan=\$(ip -4 -o addr show eth0 | awk '{print \$4}' | cut -d/ -f1)
[ -f tls/cert.pem ] || openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 825 \
  -subj /CN=metallic-accounts -addext "subjectAltName=IP:\$lan,DNS:metallic-accounts.local,IP:127.0.0.1" \
  -keyout tls/key.pem -out tls/cert.pem 2>/dev/null
chown root:maccounts tls/key.pem && chmod 640 tls/key.pem
systemctl restart metallic-accounts.service; sleep 2; systemctl is-active metallic-accounts.service
EOF
  local fp; fp=$(fingerprint)
  mkdir -p "$STAR" && printf '%s\n' "$fp" > "$STAR/metallic-accounts-fingerprint"
  echo "TLS SHA-256 fingerprint: $fp (saved to ~/.star/metallic-accounts-fingerprint)"
}

fingerprint() { ct openssl x509 -in "$ETC/tls/cert.pem" -noout -fingerprint -sha256 | tr -d '\r' | cut -d= -f2; }

step_e2e() {
  local fp; fp=$(fingerprint | tr -d ':')
  local rc=0
  b1 "lxc exec $CT -- sh -c 'cd /tmp && runuser -u maccounts -- env PYTHONPATH=$APP/app python3 $APP/e2e.py --url https://127.0.0.1:$PORT --fingerprint $fp --config $ETC/accounts.toml'" || rc=$?
  # throwaway accounts and everything they made go away again (audit rows stay: they are the record)
  ct_sh <<EOF
runuser -u maccounts -- sqlite3 $VAR/accounts.sqlite3 <<'SQL'
CREATE TEMP TABLE gone AS SELECT id FROM accounts WHERE uname LIKE 'e2e\_%' ESCAPE '\';
DELETE FROM sessions WHERE account IN (SELECT id FROM gone);
DELETE FROM recovery_codes WHERE account IN (SELECT id FROM gone);
DELETE FROM friends WHERE a IN (SELECT id FROM gone) OR b IN (SELECT id FROM gone);
DELETE FROM friend_requests WHERE src IN (SELECT id FROM gone) OR dst IN (SELECT id FROM gone);
DELETE FROM blocks WHERE blocker IN (SELECT id FROM gone) OR blocked IN (SELECT id FROM gone);
DELETE FROM presence WHERE account IN (SELECT id FROM gone);
DELETE FROM invites WHERE src IN (SELECT id FROM gone) OR dst IN (SELECT id FROM gone);
DELETE FROM news WHERE author IN (SELECT id FROM gone);
DELETE FROM passkeys WHERE account IN (SELECT id FROM gone);
DELETE FROM identities WHERE account IN (SELECT id FROM gone);
DELETE FROM accounts WHERE id IN (SELECT id FROM gone);
SELECT 'e2e accounts left: ' || COUNT(*) FROM accounts WHERE uname LIKE 'e2e\_%' ESCAPE '\';
SQL
EOF
  return $rc
}

step_owner_code() {
  local out="$STAR/metallic-accounts-owner-code"
  [ -f "$out" ] && { echo "$out exists; delete it first for a new code"; exit 2; }
  b1 "lxc exec $CT -- sh -c 'cd /tmp && rm -f /tmp/oc && runuser -u maccounts -- env PYTHONPATH=$APP/app python3 -m metallic accounts owner-code --config $ETC/accounts.toml --out /tmp/oc >/dev/null && cat /tmp/oc && rm -f /tmp/oc'" > "$out"
  owner_only "$out"
  echo "one-time owner code saved to $out (24 hours; sign up in the launcher with it)"
}

step_providers() {   # ~/.metallic/accounts/providers.toml + *.secret -> container (see server/accounts/providers.md)
  local dir="$HOME/.metallic/accounts"
  [ -f "$dir/providers.toml" ] || { echo "need $dir/providers.toml (see server/accounts/providers.md)"; exit 2; }
  ct mkdir -p "$ETC/providers"
  ct chown root:maccounts "$ETC/providers"
  ct chmod 750 "$ETC/providers"
  push_file "$dir/providers.toml" "$ETC/providers.toml" 0640
  for f in "$dir"/*.secret; do [ -f "$f" ] && push_file "$f" "$ETC/providers/$(basename "$f")" 0640; done
  ct_sh <<EOF
chgrp maccounts $ETC/providers.toml $ETC/providers/* 2>/dev/null
grep -q '^providers_file' $ETC/accounts.toml || echo 'providers_file = "$ETC/providers.toml"' >> $ETC/accounts.toml
grep -q '^webauthn_rp_id' $ETC/accounts.toml || printf 'webauthn_rp_id = "localhost"
webauthn_origins = ["http://localhost:47615"]
' >> $ETC/accounts.toml
systemctl restart metallic-accounts.service; sleep 2; systemctl is-active metallic-accounts.service
EOF
}

step_rollback() {
  ct_sh <<EOF
[ -d $APP/previous/app ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous/app $APP/ && systemctl restart metallic-accounts.service
EOF
  echo "rolled back"
}

step_start() { ct systemctl start metallic-accounts.service; }
step_stop() { ct systemctl stop metallic-accounts.service; }
step_status() {
  b1 lxc list "$CT" -c ns4 --format csv
  ct systemctl --no-pager --lines=5 status metallic-accounts.service || true
  ct systemctl list-timers metallic-accounts-backup.timer --no-pager || true
}
step_remove() {
  b1 "lxc delete --force $CT 2>/dev/null; lxc storage delete $POOL 2>/dev/null || true"
  echo "removed container and pool (~/.star/metallic-accounts-* kept)"
}

step="${1:?usage: deploy.sh container|setup|secrets|install|e2e|providers|owner-code|start|stop|status|rollback|remove}"
"step_${step//-/_}"
