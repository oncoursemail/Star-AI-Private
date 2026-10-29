#!/usr/bin/env bash
# star-polyglot: the many-language compile/type checker in its own throwaway LXD container on brain1 (a copy of the
# night-school judge container: python, node, gcc/clang, rustc, go, JDK 21, .NET 8 SDK, lua; no network device).
# Run from the owner's PC (Git Bash) in a checkout of this repo.
#
#   MESH_B1=<user>@<brain1> bash server/mesh/polyglot/deploy.sh <step>
#
# Steps (each is safe to repeat):
#   create   lxc copy star-judge -> star-polyglot, drop the judge queue mount (so it never takes night-school jobs),
#            caps (6 CPU, 6 GiB, 600 processes), runner disabled, user pgcheck (uid 1002, compilers only)
#   tools    adds a NIC for the duration, installs from official sources, removes the NIC again:
#            Ubuntu archive (shellcheck, sqlite3, lua-check, python3-venv, npm), PyPI (ruff, mypy), npm (pyright,
#            typescript@5, @types/node), rustup stable (rustup-init sha256 checked), Godot 4.x from GitHub releases
#            (sha256 = the digest GitHub publishes), the Unity scripting reference search index (current + 2022.3)
#   install  copies server/mesh/polyglot to /opt/pg/app, builds the C# (Roslyn) and Java checkers,
#            writes the token (container + star-mesh /etc/star-mesh/polyglot_token), the unit,
#            and the LXD proxy device (host starnat0 address :8110 -> 127.0.0.1:8110 in the container)
#   status | logs | remove
set -euo pipefail
cd "$(dirname "$0")/../../.."
B1="${MESH_B1:?set MESH_B1=user@brain1}"
CT=star-polyglot
MESH=star-mesh
PORT=8110
GODOT_TAG="${GODOT_TAG:-4.7.2-stable}"

b1() { ssh -o BatchMode=yes "$B1" "$@"; }
ct_sh() { b1 "lxc exec $CT -- bash -se"; }

step_create() {
  b1 "lxc info $CT >/dev/null 2>&1 || lxc copy star-judge $CT; lxc config device remove $CT queue 2>/dev/null || true;
      lxc config set $CT limits.cpu=6 limits.memory=6GiB limits.processes=600; lxc start $CT 2>/dev/null || true; sleep 3"
  ct_sh <<'SH'
set -e
systemctl disable --now judge-runner.service 2>/dev/null || true
id pgcheck >/dev/null 2>&1 || useradd -u 1002 -M -d /nonexistent -s /usr/sbin/nologin pgcheck
mkdir -p /var/cache/pg/go /var/cache/pg/work /opt/pg && chown -R pgcheck:pgcheck /var/cache/pg && chmod 700 /var/cache/pg/go
echo created
SH
}

step_tools() {
  b1 "lxc config device add $CT eth0 nic network=starnat0 name=eth0 >/dev/null; sleep 6"
  ct_sh <<SH || true
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq shellcheck sqlite3 lua-check python3-pip python3-venv npm >/dev/null
[ -x /opt/pg/venv/bin/ruff ] || python3 -m venv /opt/pg/venv
/opt/pg/venv/bin/pip install -q ruff mypy
mkdir -p /opt/pg/node && cd /opt/pg/node && [ -f package.json ] || npm init -y >/dev/null
cd /opt/pg/node && npm install -q pyright typescript@5 @types/node >/dev/null
cd /tmp && curl -fsSLO https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init \
  && curl -fsSLO https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init.sha256 \
  && echo "\$(cut -d' ' -f1 rustup-init.sha256)  rustup-init" | sha256sum -c && chmod +x rustup-init
export RUSTUP_HOME=/opt/pg/rustup CARGO_HOME=/opt/pg/cargo
[ -x /opt/pg/cargo/bin/rustup ] || ./rustup-init -y -q --profile minimal --default-toolchain none --no-modify-path
/opt/pg/cargo/bin/rustup toolchain install stable --profile minimal && /opt/pg/cargo/bin/rustup default stable
rm -f rustup-init rustup-init.sha256
want=\$(curl -fsSL https://api.github.com/repos/godotengine/godot/releases/tags/$GODOT_TAG | python3 -c 'import json,sys;d=json.load(sys.stdin);print([a["digest"] for a in d["assets"] if a["name"]=="Godot_v$GODOT_TAG""_linux.x86_64.zip"][0])')
curl -fsSL -o godot.zip https://github.com/godotengine/godot/releases/download/$GODOT_TAG/Godot_v${GODOT_TAG}_linux.x86_64.zip
[ "\$want" = "sha256:\$(sha256sum godot.zip | cut -d' ' -f1)" ] || { echo "godot checksum mismatch"; exit 3; }
rm -rf /opt/pg/godot && mkdir -p /opt/pg/godot && python3 -c 'import zipfile;zipfile.ZipFile("godot.zip").extractall("/opt/pg/godot")' && chmod 755 /opt/pg/godot/* && rm godot.zip
mkdir -p /opt/pg/data && cd /opt/pg/data
curl -fsSL -o unity-index.js https://docs.unity3d.com/ScriptReference/docdata/index.js
curl -fsSL -o unity-index-2022.3.js https://docs.unity3d.com/2022.3/Documentation/ScriptReference/docdata/index.js
date -u +%FT%TZ > fetched.txt
chmod -R a+rX /opt/pg
echo tools ok
SH
  b1 "lxc config device remove $CT eth0 >/dev/null; lxc exec $CT -- ip -4 -o addr | grep -v ' lo ' || echo 'no network (ok)'"
}

step_install() {
  local tarball; tarball="$(mktemp -u).tgz"
  tar -czf "$tarball" --exclude=__pycache__ --exclude=deploy.sh -C server/mesh polyglot
  scp -q "$tarball" "$B1:/tmp/polyglot.tgz" && rm -f "$tarball"
  b1 "lxc file push /tmp/polyglot.tgz $CT/tmp/polyglot.tgz --mode 0600 --uid 0 --gid 0; rm -f /tmp/polyglot.tgz"
  ct_sh <<'SH'
set -e
rm -rf /opt/pg/new && mkdir -p /opt/pg/new && tar --no-same-owner -xzf /tmp/polyglot.tgz -C /opt/pg/new && rm /tmp/polyglot.tgz
[ -d /opt/pg/app ] && rm -rf /opt/pg/previous && mv /opt/pg/app /opt/pg/previous
mv /opt/pg/new/polyglot /opt/pg/app && rmdir /opt/pg/new && chown -R root:root /opt/pg/app && chmod -R a+rX /opt/pg/app
# C# checker (Roslyn from the SDK)
BC=$(ls -d /usr/lib/dotnet/sdk/*/Roslyn/bincore | tail -1); REF=$(ls -d /usr/lib/dotnet/packs/Microsoft.NETCore.App.Ref/*/ref/net8.0 | tail -1)
RT=$(basename "$(ls -d /usr/lib/dotnet/shared/Microsoft.NETCore.App/* | tail -1)")
mkdir -p /opt/pg/cscheck && cd /opt/pg/cscheck
dotnet "$BC/csc.dll" -nologo -nullable:disable -out:CsCheck.dll $(for f in "$REF"/*.dll; do printf -- '-r:%s ' "$f"; done) \
  -r:"$BC/Microsoft.CodeAnalysis.dll" -r:"$BC/Microsoft.CodeAnalysis.CSharp.dll" /opt/pg/app/workers/CsCheck.cs
cp "$BC/Microsoft.CodeAnalysis.dll" "$BC/Microsoft.CodeAnalysis.CSharp.dll" .
printf '{"runtimeOptions":{"tfm":"net8.0","framework":{"name":"Microsoft.NETCore.App","version":"%s"}}}' "$RT" > CsCheck.runtimeconfig.json
# Java checker
mkdir -p /opt/pg/javacheck && /opt/jdk/bin/javac -d /opt/pg/javacheck /opt/pg/app/workers/JavaCheck.java
chmod -R a+rX /opt/pg/cscheck /opt/pg/javacheck
mkdir -p /etc/star-polyglot && [ -s /etc/star-polyglot/token ] || python3 -c 'import secrets;print(secrets.token_hex(24))' > /etc/star-polyglot/token
chmod 600 /etc/star-polyglot/token
cat > /etc/systemd/system/star-polyglot.service <<'UNIT'
[Unit]
Description=STAR polyglot code checker (no network; tools run as pgcheck/sandbox under limits)
After=network.target
[Service]
ExecStart=/usr/bin/python3 -I /opt/pg/app/runner.py
Restart=always
RestartSec=2
MemoryMax=5G
TasksMax=500
Nice=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable star-polyglot.service >/dev/null 2>&1 && systemctl restart star-polyglot.service
sleep 8 && curl -s -m 5 http://127.0.0.1:8110/health; echo
SH
  local gw; gw=$(b1 "lxc network get starnat0 ipv4.address" | cut -d/ -f1)
  b1 "lxc config device show $CT | grep -q '^api:' || lxc config device add $CT api proxy listen=tcp:$gw:$PORT connect=tcp:127.0.0.1:$PORT bind=host >/dev/null"
  b1 "lxc exec $CT -- cat /etc/star-polyglot/token | lxc exec $MESH -- sh -c 'umask 027; cat > /etc/star-mesh/polyglot_token; chgrp starmesh /etc/star-mesh/polyglot_token'"
  b1 "echo http://$gw:$PORT | lxc exec $MESH -- sh -c 'cat > /etc/star-mesh/polyglot_url; chmod 644 /etc/star-mesh/polyglot_url'"
  echo "proxy on the starnat0 gateway :$PORT (url + token in $MESH:/etc/star-mesh/polyglot_url, polyglot_token)"
}

case "${1:-}" in
  create) step_create ;;
  tools) step_tools ;;
  install) step_install ;;
  status) b1 "lxc list $CT -c ns --format csv; lxc exec $CT -- systemctl is-active star-polyglot.service; lxc exec $CT -- curl -s -m 5 http://127.0.0.1:$PORT/health; echo" ;;
  logs) b1 "lxc exec $CT -- journalctl -u star-polyglot.service -n 60 --no-pager" ;;
  remove) b1 "lxc stop $CT --force; lxc delete $CT; lxc exec $MESH -- rm -f /etc/star-mesh/polyglot_token /etc/star-mesh/polyglot_url" ;;
  *) echo "usage: deploy.sh create|tools|install|status|logs|remove"; exit 2 ;;
esac
