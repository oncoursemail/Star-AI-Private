#!/bin/bash
# srv.sh start|stop|rss : side star-fast for the G0 bench on 127.0.0.1:8095, never the live brain. Live binary, env
# and star-fast flags (DSpark draft + ngram-mod, -np 2, mmproj), plus --slot-save-path; no RAM prompt cache, so a
# "cold" turn is really cold. Run inside the starai container as user star, only under the quiet lock (star lock run).
# Env: DIR (bench dir, default /opt/star/bench/g0), NOSPEC=1 (no speculative decoding).
set -u
DIR=${DIR:-/opt/star/bench/g0}
M=/opt/star/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-Q4_K_M.gguf
MM=/opt/star/models/qwen3.6-35b-a3b/mmproj-Qwen3.6-35B-A3B-Q8_0.gguf
DRAFT=/opt/star/models/qwen3.6-35b-a3b-dspark/Qwen3.6-35B-A3B-DSpark-Q4_K_M.gguf
BIN=/opt/star/bin-ramforge
mkdir -p "$DIR/kv"
case ${1:-} in
start)
  SPEC="--spec-type draft-dspark,ngram-mod --model-draft $DRAFT --spec-draft-n-max 2"
  [ -n "${NOSPEC:-}" ] && SPEC=""
  # shellcheck disable=SC2086
  env LD_LIBRARY_PATH=$BIN GGML_NUMA_BLOCK=1 LLAMA_RAMFORGE_PLACE=1 numactl --interleave=all $BIN/llama-server \
    --host 127.0.0.1 --port 8095 -m "$M" --mmproj "$MM" --alias star-fast --jinja --reasoning off -fa on -lm dio \
    -c 65536 -np 2 --numa distribute -t 24 -tb 24 --cache-ram 0 --slot-save-path "$DIR/kv/" $SPEC \
    > "$DIR/server.log" 2>&1 &
  echo $! > "$DIR/srv.pid"
  for i in $(seq 1 300); do curl -sf 127.0.0.1:8095/health >/dev/null && break; sleep 1; done
  echo "loaded after ${i}s rss_mb $(( $(ps -o rss= -p "$(cat "$DIR/srv.pid")") / 1024 ))" ;;
rss) echo "rss_mb $(( $(ps -o rss= -p "$(cat "$DIR/srv.pid")") / 1024 ))" ;;
stop) kill "$(cat "$DIR/srv.pid")" 2>/dev/null; sleep 3; pkill -f -- "--port 8095"; echo stopped ;;
*) echo "usage: srv.sh start|stop|rss"; exit 2 ;;
esac
