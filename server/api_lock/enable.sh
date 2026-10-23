#!/usr/bin/env bash
# Switch star-brain to the API-lock llama-server (patch 0004). Run as root in the starai container by
# `deploy.sh --enable`. Writes /opt/star/api_lock/undo.sh before changing anything.
set -euo pipefail
here=/opt/star/api_lock
dropin=/etc/systemd/system/star-brain.service.d/ramforge.conf
build=/opt/star/src/llama.cpp-apilock/build/bin
test -x "$build/llama-server" && grep -qa LLAMA_API_LOCK_TABLE "$build"/*
test -s "$here/api-lock-table.json"
current=$(grep -o '/opt/star/bin-[a-z]*' "$dropin" | head -1)
test -n "$current"

backup="$here/ramforge.conf.bak-$(date -u +%Y%m%d-%H%M%S)"
cp -p "$dropin" "$backup"
cat > "$here/undo.sh" <<UNDO
#!/usr/bin/env bash
# Undo of enable.sh: the star-brain drop-in from $backup ($current), star-brain restarted.
set -u
cp -p $backup $dropin
systemctl daemon-reload
systemctl restart star-brain
for i in \$(seq 1 300); do curl -sf http://127.0.0.1:8080/health >/dev/null && break; sleep 1; done
echo "api lock undone: binary \$(grep -o '/opt/star/bin-[a-z]*' $dropin | head -1), health \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health)"
UNDO
chmod 755 "$here/undo.sh"

rm -rf /opt/star/bin-apilock && install -d -o star -g star /opt/star/bin-apilock
cp -a "$build"/llama-server "$build"/lib*.so* /opt/star/bin-apilock/
sed -i "s#$current#/opt/star/bin-apilock#g" "$dropin"
grep -q LLAMA_API_LOCK_TABLE "$dropin" || sed -i "/^\[Service\]/a Environment=LLAMA_API_LOCK_TABLE=$here/api-lock-table.json" "$dropin"
systemctl daemon-reload
systemctl restart star-brain
for i in $(seq 1 300); do curl -sf http://127.0.0.1:8080/health >/dev/null && break; sleep 1; done
echo "api lock enabled: binary /opt/star/bin-apilock (was $current), health $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health); undo: $here/undo.sh"
