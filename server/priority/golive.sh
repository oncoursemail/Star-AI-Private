#!/usr/bin/env bash
# Put STAR's priority proxy in front of every client of brain 1. Runs as root INSIDE the container (deploy.sh --start
# stages the files in /opt/star/priority/stage and calls it). Writes /opt/star/priority/undo.sh first: one command puts
# everything back.
#   router    0.0.0.0:8080 -> 127.0.0.1:8081 (same --api-key-file); the proxy takes 8080 (unlabelled = P0, the owner),
#             8082 (P2: agents, fleet) and 8083 (P3: night school, conductor, evals, Studio Lab, playtest, knowledge jobs)
#   star-fast parallel 3, ctx-size 98304 (background max 2 of 3 slots: priority.json bg_cap)
#   night school + conductor -> 127.0.0.1:8083 with STAR_NS_GATE=priority (code: idle.py/__main__.py/config.py/
#             conductor.py/star/task_checkpoint.py from the stage; the live MAX_REPAIRS_PER_CYCLE value is kept)
#   knowledge refresh -> 127.0.0.1:8083 (drop-in); the knowledge service itself stays on 8080
#   router binary -> /opt/star/bin-prio (llama.cpp with patch 0003, built by server/ramforge/build_prio.sh): background
#             requests marked low_priority read their prompt in 64-token chunks and wait while an owner request works
set -euo pipefail
stage=/opt/star/priority/stage
backup=/opt/star/config/backups/priority-$(date -u +%Y%m%d-%H%M%S)
app=/opt/star/learning/app
ns=$app/server/night_school/nightschool
dropin=/etc/systemd/system/star-brain.service.d/ramforge.conf
refresh_dropin=/etc/systemd/system/star-knowledge-refresh.service.d/priority.conf
mkdir -p "$backup"
cp -p /opt/star/config/models.ini "$backup/models.ini"
cp -p "$dropin" "$backup/ramforge.conf"
cp -p /opt/star/learning/env "$backup/learning.env"
for f in __main__ conductor config idle; do cp -p "$ns/$f.py" "$backup/ns-$f.py"; done

cat > /opt/star/priority/undo.sh <<UNDO
#!/usr/bin/env bash
# Undo of golive.sh ($backup). Router back on 0.0.0.0:8080, proxy off, models.ini/night school/refresh as before.
set -u
systemctl disable --now star-priority
rm -f /etc/systemd/system/star-priority.service $refresh_dropin
cp -p $backup/ramforge.conf $dropin
cp -p $backup/models.ini /opt/star/config/models.ini
cp -p $backup/learning.env /opt/star/learning/env
for f in __main__ conductor config idle; do cp -p $backup/ns-\$f.py $ns/\$f.py; done
rm -f $app/star/task_checkpoint.py
systemctl daemon-reload
systemctl restart star-brain
for i in \$(seq 1 300); do curl -sf http://127.0.0.1:8080/health >/dev/null && break; sleep 1; done
systemctl restart star-night-school
echo "undo done: router on 8080 again (\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health))"
UNDO
chmod 755 /opt/star/priority/undo.sh

python3 - <<'PY'
import re
p = "/opt/star/config/models.ini"
text = open(p, encoding="utf-8").read()
start = text.index("[star-fast]")
end = text.find("\n[", start + 1)
end = len(text) if end < 0 else end
section = text[start:end]
section = re.sub(r"(?m)^parallel\s*=.*$", "parallel = 3", section)
section = re.sub(r"(?m)^ctx-size\s*=.*$", "ctx-size = 98304", section)
assert "parallel = 3" in section and "ctx-size = 98304" in section
open(p, "w", encoding="utf-8").write(text[:start] + section + text[end:])
PY
grep -q -- "--host 0.0.0.0 --port 8080" "$dropin"
sed -i 's/--host 0.0.0.0 --port 8080/--host 127.0.0.1 --port 8081/' "$dropin"
prio_build=/opt/star/src/llama.cpp-prio/build/bin
test -x "$prio_build/llama-server" && grep -qa low_priority "$prio_build/libllama-server-impl.so"
rm -rf /opt/star/bin-prio && install -d -o star -g star /opt/star/bin-prio
cp -a "$prio_build"/llama-server "$prio_build"/lib*.so* /opt/star/bin-prio/
sed -i 's#/opt/star/bin-ramforge#/opt/star/bin-prio#g' "$dropin"
grep -q "/opt/star/bin-prio/llama-server" "$dropin"

install -d -o star -g star /opt/star/priority /opt/star/logs
install -o star -g star -m 644 "$stage/priority_proxy.py" /opt/star/priority/priority_proxy.py
install -m 644 "$stage/priority.json" /opt/star/config/priority.json
install -m 644 "$stage/star-priority.service" /etc/systemd/system/star-priority.service

repairs=$(grep -E '^MAX_REPAIRS_PER_CYCLE = ' "$ns/conductor.py" | head -1)
for f in __main__ conductor config idle; do install -o star -g star -m 644 "$stage/ns-$f.py" "$ns/$f.py"; done
sed -i "s/^MAX_REPAIRS_PER_CYCLE = .*/$repairs/" "$ns/conductor.py"
install -o star -g star -m 644 "$stage/task_checkpoint.py" "$app/star/task_checkpoint.py"
sed -i '/^STAR_NS_BRAIN_URL=/d; /^STAR_NS_GATE=/d' /opt/star/learning/env
printf 'STAR_NS_BRAIN_URL=http://127.0.0.1:8083\nSTAR_NS_GATE=priority\n' >> /opt/star/learning/env
mkdir -p "$(dirname "$refresh_dropin")"
printf '[Service]\nEnvironment=STAR_BRAIN_URL=http://127.0.0.1:8083\n' > "$refresh_dropin"

systemctl daemon-reload
systemctl restart star-brain
for i in $(seq 1 60); do ss -ltn | grep -q '127.0.0.1:8081 ' && break; sleep 1; done
systemctl enable --now star-priority
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8080/priority/v1/status >/dev/null && break; sleep 1; done
key=$(head -1 /opt/star/secrets/api_keys)
curl -s -o /dev/null -w "warm-up star-fast (P3 via 8083): %{http_code} in %{time_total}s\n" --max-time 400 \
  -H "Authorization: Bearer $key" -H "Content-Type: application/json" http://127.0.0.1:8083/v1/chat/completions \
  -d '{"model":"star-fast","messages":[{"role":"user","content":"hi"}],"max_tokens":4}'
unset key
systemctl restart star-night-school
echo "live: proxy $(systemctl is-active star-priority), router $(systemctl is-active star-brain); backup $backup; undo: bash /opt/star/priority/undo.sh"
