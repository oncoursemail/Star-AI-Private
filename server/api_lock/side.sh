#!/bin/bash
# side.sh LABEL [ab|ba]: a temporary star-fast copy with the API-lock binary on 127.0.0.1:8096 (live weights, live env
# and spec flags, -np 2), bench.py on it, then stop. Live star-fast is not touched. Run as user star in the starai
# container, only under the quiet lock: ./star.cmd lock run --owner claude --holder g1 --server 1 --max-minutes 10 -- ...
set -u
L=$1; ORDER=${2:-ab}
HERE=/opt/star/api_lock
BIN=/opt/star/src/llama.cpp-apilock/build/bin
M=/opt/star/models/qwen3.6-35b-a3b
OUT=$HERE/bench; mkdir -p $OUT
stop() { kill "$(cat $OUT/side.pid 2>/dev/null)" 2>/dev/null; sleep 3; pkill -f -- "--port 8096"; }
trap stop EXIT
echo "start $(date -u +%H:%M:%SZ) $L order=$ORDER"
env LD_LIBRARY_PATH=$BIN GGML_NUMA_BLOCK=1 LLAMA_RAMFORGE_PLACE=1 LLAMA_API_LOCK_TABLE=$HERE/api-lock-table.json \
  numactl --interleave=all $BIN/llama-server --host 127.0.0.1 --port 8096 -m $M/Qwen3.6-35B-A3B-Q4_K_M.gguf \
  --alias star-fast --jinja --reasoning off -fa on -lm dio -c 65536 -np 2 --numa distribute -t 24 -tb 24 \
  --spec-type draft-dspark,ngram-mod --model-draft /opt/star/models/qwen3.6-35b-a3b-dspark/Qwen3.6-35B-A3B-DSpark-Q4_K_M.gguf \
  --spec-draft-n-max 2 > $OUT/$L.server.log 2>&1 &
echo $! > $OUT/side.pid
for i in $(seq 1 300); do curl -sf localhost:8096/health >/dev/null && break; sleep 1; done
echo "loaded after ${i}s"
python3 $HERE/bench.py http://127.0.0.1:8096 $OUT/$L.json "$ORDER"
echo "end $(date -u +%H:%M:%SZ)"
