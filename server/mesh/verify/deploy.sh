#!/usr/bin/env bash
# Litha code verifier deployment into the existing star-mesh container (sibling service on :8101), run from the
# owner's PC (Git Bash) in a checkout of this repo. It never touches the router's files (/opt/star-mesh).
#
#   MESH_B1=<user>@<brain1> bash server/mesh/verify/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   tools    luau-analyze from the official Luau release (github.com/luau-lang/luau), sha256 checked against the
#            digest GitHub publishes for the asset; version pinned by LUAU_VERSION (default below)
#   install  copy server/mesh/{__init__,router,instant}.py + server/mesh/{loop,rules,verify,mcdata,polyglot,agent,...} to /opt/star-verify/app, the unit, ufw 8101
#            (LAN + starnat0 only), restart (keeps the previous release for `rollback`)
#   dump     download the current Roblox Full-API-Dump.json + version.txt (MaximumADHD/Roblox-Client-Tracker),
#            build the index (/var/lib/star-verify/roblox-api-index.json, with version + fetch date), restart
#   mc       copy the Minecraft index (server/mesh/mcdata/build.py output, Mojang data: never in git) from the lab
#            container (MC_LAB_CT, default mc-data-lab, /srv/mc/index) to /var/lib/star-verify/mc, restart
#            (first deployment order: tools, install, dump, mc)
#   status | logs | rollback | remove
set -euo pipefail
cd "$(dirname "$0")/../../.."
B1="${MESH_B1:?set MESH_B1=user@brain1}"
CT=star-mesh
APP=/opt/star-verify
VAR=/var/lib/star-verify
LUAU_VERSION="${LUAU_VERSION:-0.744}"

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct() { b1 "lxc exec $CT -- $(printf '%q ' "$@")"; }
ct_sh() { b1 "lxc exec $CT -- sh -se"; }

step_tools() {
  ct_sh <<SH
set -e
mkdir -p $APP/bin /tmp/luau-dl && cd /tmp/luau-dl
curl -fsSL -o release.json https://api.github.com/repos/luau-lang/luau/releases/tags/$LUAU_VERSION
curl -fsSL -o luau-ubuntu.zip https://github.com/luau-lang/luau/releases/download/$LUAU_VERSION/luau-ubuntu.zip
want=\$(python3 -c 'import json;d=json.load(open("release.json"));print([a.get("digest","") for a in d["assets"] if a["name"]=="luau-ubuntu.zip"][0])')
got="sha256:\$(sha256sum luau-ubuntu.zip | cut -d' ' -f1)"
[ -n "\$want" ] && [ "\$want" = "\$got" ] || { echo "checksum mismatch or missing: want \$want got \$got"; exit 3; }
python3 -c 'import zipfile;zipfile.ZipFile("luau-ubuntu.zip").extract("luau-analyze", "/opt/star-verify/bin")'
chmod 755 $APP/bin/luau-analyze
echo "$LUAU_VERSION \$got" > $APP/bin/luau-analyze.version
cd / && rm -rf /tmp/luau-dl
printf 'print("ok")\n' > /tmp/t.luau && $APP/bin/luau-analyze --formatter=plain /tmp/t.luau && rm /tmp/t.luau
echo "luau-analyze $LUAU_VERSION installed (checksum ok)"
SH
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ --exclude=deploy.sh --exclude=mesh/mcdata/lab -C server mesh/__init__.py mesh/router.py mesh/instant.py mesh/loop mesh/rules mesh/verify mesh/mcdata mesh/polyglot mesh/general mesh/selfmodel mesh/speed mesh/mcfacts mesh/agent
  scp -q "$tarball" "$B1:/tmp/verify.tgz"
  rm -f "$tarball"
  b1 "lxc file push /tmp/verify.tgz $CT/tmp/verify.tgz --mode 0600 --uid 0 --gid 0; rm -f /tmp/verify.tgz"
  ct_sh <<SH
set -e
rm -rf $APP/new && mkdir -p $APP/new $VAR && tar --no-same-owner -xzf /tmp/verify.tgz -C $APP/new && rm /tmp/verify.tgz
if [ -d $APP/app ]; then rm -rf $APP/previous && mv $APP/app $APP/previous; fi
mv $APP/new $APP/app
chown -R root:root $APP/app && chown root:starmesh $VAR && chmod 750 $VAR
install -m 644 $APP/app/mesh/verify/star-mesh-verify.service /etc/systemd/system/star-mesh-verify.service
subnet() { python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "\$(ip -4 -o addr show \$1 | awk '{print \$4}' | head -1)"; }
ufw allow from "\$(subnet eth0)" to any port 8101 proto tcp >/dev/null
ufw allow from "\$(subnet eth1)" to any port 8101 proto tcp >/dev/null
systemctl daemon-reload && systemctl enable star-mesh-verify.service >/dev/null 2>&1
if [ -f $VAR/roblox-api-index.json ]; then systemctl restart star-mesh-verify.service; sleep 2; systemctl is-active star-mesh-verify.service; curl -s -m 3 http://127.0.0.1:8101/health; echo; else echo "no index yet: run the dump step"; fi
SH
}

step_dump() {
  ct_sh <<SH
set -e
cd $VAR
curl -fsSL -o Full-API-Dump.json.new https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/Full-API-Dump.json
curl -fsSL -o version.txt.new https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/version.txt
mv Full-API-Dump.json.new Full-API-Dump.json && mv version.txt.new version.txt
PYTHONPATH=$APP/app python3 -m mesh.verify.apidump Full-API-Dump.json version.txt roblox-api-index.json.new
mv roblox-api-index.json.new roblox-api-index.json
chown root:starmesh Full-API-Dump.json version.txt roblox-api-index.json && chmod 640 roblox-api-index.json
systemctl restart star-mesh-verify.service; sleep 2; systemctl is-active star-mesh-verify.service
curl -s -m 3 http://127.0.0.1:8101/health; echo
SH
}

step_mc() {
  local lab="${MC_LAB_CT:-mc-data-lab}"
  b1 "lxc exec $CT -- sh -c 'rm -rf $VAR/mc.new && mkdir -p $VAR/mc.new' && lxc exec $lab -- tar -C /srv/mc/index -cf - . | lxc exec $CT -- tar --no-same-owner -C $VAR/mc.new -xf -"
  ct_sh <<SH
set -e
cd $VAR && rm -rf mc.old && { [ -d mc ] && mv mc mc.old || true; } && mv mc.new mc
chown -R root:starmesh mc && chmod 750 mc && chmod 640 mc/*
systemctl restart star-mesh-verify.service; sleep 8; systemctl is-active star-mesh-verify.service
curl -s -m 3 http://127.0.0.1:8101/health; echo
SH
}

step_rollback() {
  ct_sh <<SH
[ -d $APP/previous ] || { echo 'no previous release'; exit 2; }
rm -rf $APP/app && mv $APP/previous $APP/app && systemctl restart star-mesh-verify.service
SH
  echo "rolled back"
}
step_status() { ct systemctl --no-pager --lines=5 status star-mesh-verify.service || true; }
step_logs() { ct journalctl -u star-mesh-verify.service --no-pager -n "${MESH_LINES:-40}"; }
step_remove() {
  ct_sh <<SH
systemctl disable --now star-mesh-verify.service 2>/dev/null; rm -f /etc/systemd/system/star-mesh-verify.service
systemctl daemon-reload; rm -rf $APP $VAR
ufw delete allow 8101/tcp >/dev/null 2>&1 || true
for r in \$(ufw status numbered | grep 8101 | sed 's/^\[ *\([0-9]*\)\].*/\1/' | sort -rn); do ufw --force delete \$r >/dev/null; done
SH
  echo "verifier removed (router untouched)"
}

step="${1:?usage: deploy.sh tools|install|dump|mc|status|logs|rollback|remove}"
"step_${step//-/_}"
