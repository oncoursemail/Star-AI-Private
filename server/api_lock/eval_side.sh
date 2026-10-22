#!/bin/bash
# eval_side.sh start|stop: the API-lock binary with a small model (Mellum 12B-A2.5B) on :8097 of the starai container,
# nice 19 and 12 threads, for the paired quality eval (evals do not take the quiet lock). Live star-fast is untouched.
# Key: the router's key file, so only STAR clients can use it. Run as user star.
set -u
HERE=/opt/star/api_lock
BIN=/opt/star/src/llama.cpp-apilock/build/bin
OUT=$HERE/bench; mkdir -p $OUT
case "${1:-}" in
start)
  setsid env LD_LIBRARY_PATH=$BIN LLAMA_API_LOCK_TABLE=$HERE/api-lock-table.json nice -n 19 $BIN/llama-server \
    --host 0.0.0.0 --port 8097 --api-key-file /opt/star/secrets/api_keys \
    -m /opt/star/models/mellum2.1-12b/Mellum2.1-12B-A2.5B-Thinking-Q4_K_M.gguf --jinja --reasoning off \
    -c 32768 -np 1 -t 12 -tb 12 --cache-ram 2048 --spec-type ngram-mod \
    --alias star-fast,star-code,star-vision,star-deep,star-quick,star-voice > $OUT/eval_side.server.log 2>&1 < /dev/null &
  pid=$!
  echo $pid > $OUT/eval_side.pid
  # pause while anyone holds the quiet lock (timing runs), like the other background jobs
  setsid bash -c "while kill -0 $pid 2>/dev/null; do if [ -d /opt/star/lock ]; then kill -STOP $pid; else kill -CONT $pid; fi; sleep 2; done" \
    > /dev/null 2>&1 < /dev/null &
  for i in $(seq 1 180); do curl -s localhost:8097/health | grep -q ok && break; sleep 1; done
  echo "eval side up after ${i}s pid $(cat $OUT/eval_side.pid)" ;;
stop)
  kill -CONT "$(cat $OUT/eval_side.pid 2>/dev/null)" 2>/dev/null
  kill "$(cat $OUT/eval_side.pid 2>/dev/null)" 2>/dev/null; sleep 2; pkill -f -- "--port 8097"; echo stopped ;;
*) echo "usage: eval_side.sh start|stop" >&2; exit 2 ;;
esac
