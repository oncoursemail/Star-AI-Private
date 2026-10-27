#!/usr/bin/env bash
# Metallic API v1 deployment, run from the owner's PC (Git Bash) in a checkout of this repo. It runs NEXT TO Metallic
# accounts in the same LXD container (accounts' own deploy.sh made it); this script never touches accounts' files.
#
#   MA_B1=<user>@<brain1> [MA_CT=metallic-accounts-test] bash server/api/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   setup     inside the container: service user mapi, folders (python3-cryptography is already there for accounts)
#   install   copy metallic/api + launcher/updates + launcher/px + the Python SDK, unit, config; restart
#             (keeps the previous release for `rollback`). First deployment order: setup, install, secrets, e2e
#   secrets   data key (AES-GCM) + self-signed TLS cert + accounts' certificate fingerprint; prints the API's
#             SHA-256 fingerprint (also saved to ~/.star/metallic-api-fingerprint)
#   e2e       server/api/e2e.py inside the container against https://127.0.0.1:8476 with throwaway e2e_ accounts,
#             keys and webhooks, which are removed afterwards
#   key NAME SCOPES [GAMES]   new server key; the secret goes to ~/.star/metallic-api-key-NAME (owner-only, never printed)
#   start | stop | status | rollback | remove (service + files only; the container belongs to accounts)
set -euo pipefail
cd "$(dirname "$0")/../.."
B1="${MA_B1:?set MA_B1=user@brain1}"
CT="${MA_CT:-metallic-accounts-test}"
APP=/opt/metallic-api
ETC=/etc/metallic-api
VAR=/var/lib/metallic-api
STAR="$HOME/.star"
PORT=8476

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }
push_file() {
  local tmp="/tmp/mapi-$RANDOM-$$"
  scp -q "$1" "$B1:$tmp"
  b1 "chmod 600 $tmp && lxc file push $tmp $CT$2 --mode $3 --uid 0 --gid 0; rm -f $tmp"
}
owner_only() { icacls "$(cygpath -w "$1")" /inheritance:r /grant:r "$USERNAME:(R,W)" >/dev/null; }

step_setup() {
  ct_sh <<EOF
id mapi >/dev/null 2>&1 || useradd --system --home-dir $VAR --create-home --shell /usr/sbin/nologin mapi
mkdir -p $APP $ETC/keys $ETC/tls $VAR/releases
chown root:mapi $ETC $ETC/keys $ETC/tls && chmod 750 $ETC $ETC/keys $ETC/tls
chown mapi:mapi $VAR $VAR/releases && chmod 700 $VAR
python3 -c "import cryptography; print('cryptography', cryptography.__version__)"
EOF
}

step_install() {
  local stage; stage="$(mktemp -d)"
  mkdir -p "$stage/app/metallic" "$stage/app/launcher"
  cp metallic/metallic/__init__.py "$stage/app/metallic/"
  cp -r metallic/metallic/api "$stage/app/metallic/api"
  cp -r launcher/updates launcher/px "$stage/app/launcher/"
  cp metallic/sdk/python/metallic_api.py "$stage/app/"
  cp server/api/metallic-api.service server/api/api.example.toml server/api/e2e.py "$stage/"
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ -C "$stage" .
  rm -rf "$stage"
  push_file "$tarball" /tmp/mapi.tgz 0600
  rm -f "$tarball"
  ct_sh <<EOF
rm -rf $APP/new && mkdir -p $APP/new && tar --no-same-owner -m -xzf /tmp/mapi.tgz -C $APP/new && rm /tmp/mapi.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mkdir -p $APP/previous && mv $APP/app $APP/previous/; fi
mv $APP/new/app $APP/app && mv $APP/new/e2e.py $APP/
[ -f $ETC/api.toml ] || install -m 640 -g mapi $APP/new/api.example.toml $ETC/api.toml
install -m 644 $APP/new/metallic-api.service /etc/systemd/system/metallic-api.service && rm -rf $APP/new
systemctl daemon-reload && systemctl enable metallic-api.service >/dev/null 2>&1
if [ -f $ETC/keys/data-key ]; then systemctl restart metallic-api.service; sleep 2; systemctl is-active metallic-api.service; fi
EOF
  echo "installed (previous release kept in $APP/previous; undo: deploy.sh rollback)"
}

step_secrets() {
  ct_sh <<EOF
cd $ETC
PYTHONPATH=$APP/app python3 -m metallic.api init $ETC/keys
chown root:mapi keys/* && chmod 640 keys/*
lan=\$(ip -4 -o addr show eth0 | awk '{print \$4}' | cut -d/ -f1)
[ -f tls/cert.pem ] || openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 825 \
  -subj /CN=metallic-api -addext "subjectAltName=IP:\$lan,DNS:metallic-api.local,IP:127.0.0.1" \
  -keyout tls/key.pem -out tls/cert.pem 2>/dev/null
chown root:mapi tls/key.pem && chmod 640 tls/key.pem
openssl x509 -in /etc/metallic-accounts/tls/cert.pem -noout -fingerprint -sha256 | cut -d= -f2 > accounts-fingerprint
chown root:mapi accounts-fingerprint && chmod 640 accounts-fingerprint
systemctl restart metallic-api.service; sleep 2; systemctl is-active metallic-api.service
EOF
  local fp; fp=$(fingerprint)
  mkdir -p "$STAR" && printf '%s\n' "$fp" > "$STAR/metallic-api-fingerprint"
  echo "TLS SHA-256 fingerprint: $fp (saved to ~/.star/metallic-api-fingerprint)"
}

fingerprint() { ct openssl x509 -in "$ETC/tls/cert.pem" -noout -fingerprint -sha256 | tr -d '\r' | cut -d= -f2; }

step_e2e() {
  local fp; fp=$(fingerprint | tr -d ':')
  local afp; afp=$(ct openssl x509 -in /etc/metallic-accounts/tls/cert.pem -noout -fingerprint -sha256 | tr -d '\r:' | cut -d= -f2)
  local rc=0
  b1 "lxc exec $CT -- sh -c 'cd /tmp && runuser -u mapi -- env PYTHONPATH=$APP/app python3 $APP/e2e.py --api https://127.0.0.1:$PORT --api-fingerprint $fp --accounts https://127.0.0.1:8475 --accounts-fingerprint $afp --config $ETC/api.toml'" || rc=$?
  # throwaway accounts go away again (same cleanup as accounts' own e2e; audit rows stay as the record)
  ct_sh <<'EOF'
runuser -u maccounts -- sqlite3 /var/lib/metallic-accounts/accounts.sqlite3 <<'SQL'
CREATE TEMP TABLE gone AS SELECT id FROM accounts WHERE uname LIKE 'e2e\_api%' ESCAPE '\';
DELETE FROM sessions WHERE account IN (SELECT id FROM gone);
DELETE FROM recovery_codes WHERE account IN (SELECT id FROM gone);
DELETE FROM friends WHERE a IN (SELECT id FROM gone) OR b IN (SELECT id FROM gone);
DELETE FROM friend_requests WHERE src IN (SELECT id FROM gone) OR dst IN (SELECT id FROM gone);
DELETE FROM blocks WHERE blocker IN (SELECT id FROM gone) OR blocked IN (SELECT id FROM gone);
DELETE FROM presence WHERE account IN (SELECT id FROM gone);
DELETE FROM invites WHERE src IN (SELECT id FROM gone) OR dst IN (SELECT id FROM gone);
DELETE FROM accounts WHERE id IN (SELECT id FROM gone);
SELECT 'e2e accounts left: ' || COUNT(*) FROM accounts WHERE uname LIKE 'e2e\_api%' ESCAPE '\';
SQL
runuser -u mapi -- sqlite3 /var/lib/metallic-api/api.sqlite3 <<'SQL'
DELETE FROM deliveries WHERE webhook IN (SELECT id FROM webhooks WHERE description LIKE 'e2e%');
DELETE FROM webhooks WHERE description LIKE 'e2e%';
DELETE FROM keys WHERE name LIKE 'e2e%';
DELETE FROM tokens WHERE client LIKE 'e2e%';
DELETE FROM heartbeats WHERE server_id LIKE 'e2e%';
SELECT 'e2e keys left: ' || COUNT(*) FROM keys WHERE name LIKE 'e2e%';
SQL
EOF
  return $rc
}

step_key() {
  local name="${2:?deploy.sh key NAME SCOPES [GAMES]}" scopes="${3:?scopes, e.g. servers:write,players:read}"
  local games="${4:-RC,MC,RB,PX}" out="$STAR/metallic-api-key-$name"
  [ -f "$out" ] && { echo "$out exists; delete it first"; exit 2; }
  b1 "lxc exec $CT -- sh -c 'cd /tmp && rm -f /tmp/k && runuser -u mapi -- env PYTHONPATH=$APP/app python3 -m metallic.api key create --config $ETC/api.toml --name $name --scopes $scopes --games $games --out /tmp/k >/dev/null && cat /tmp/k && rm -f /tmp/k'" > "$out"
  owner_only "$out"
  echo "server key saved to $out (never printed)"
}

step_rollback() {
  ct_sh <<EOF
[ -d $APP/previous/app ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous/app $APP/ && systemctl restart metallic-api.service
EOF
  echo "rolled back"
}

step_start() { ct systemctl start metallic-api.service; }
step_stop() { ct systemctl stop metallic-api.service; }
step_status() {
  b1 lxc list "$CT" -c ns4 --format csv
  ct systemctl --no-pager --lines=5 status metallic-api.service || true
}
step_remove() {
  ct_sh <<EOF
systemctl disable --now metallic-api.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/metallic-api.service && systemctl daemon-reload
rm -rf $APP $ETC $VAR && userdel mapi 2>/dev/null || true
EOF
  echo "removed the API service and its files (accounts untouched; ~/.star/metallic-api-* kept)"
}

step="${1:?usage: deploy.sh setup|install|secrets|e2e|key|start|stop|status|rollback|remove}"
"step_${step//-/_}" "$@"
