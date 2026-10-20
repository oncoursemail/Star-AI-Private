#!/bin/bash
# Fine-tune pipeline on the PC GPU (docs/agents/finetune-20261020.md). Git Bash. Steps, in order:
#   pipeline.sh sft            QLoRA SFT of the 4B apprentice on $DATA/sft, export the adapter to GGUF
#   pipeline.sh kto            KTO from the SFT adapter on $DATA/kto, export to GGUF
#   pipeline.sh gate ARM...    run the gate suites for the arms (base, bank, sft, kto) on a temporary llama-server
#   pipeline.sh report CONTROL CANDIDATE   paired verdict per suite and combined
# Owner rules: refuses while Roblox Studio or another llama-server runs (GPU embedding job, night turbo); the trainers
# also stop on games / low RAM / STOP-TRAIN. Never replaces a live model: the server is local, on $PORT.
# Environment (no defaults for private values): STAR_EVAL_SSH (LXD host whose container runs the Luau VM tests and
# whose quiet lock is respected), STAR_EVAL_KNOWLEDGE (knowledge URL: brain 1, or kb_replica.py on this PC with
# OWN_LLAMA=1 so a gate does not wait for brain 1's quiet locks).
set -u
ROOT=${ROOT:-/c/Users/alexi/Documents/starai}
APP=${APP:-$ROOT/worktrees/finetune}
W=${W:-$ROOT/work/ft20}
DATA=${DATA:-$W/data}
PYT=${PYT:-$ROOT/tools-portable/train-venv/Scripts/python.exe}     # torch / peft / transformers
PYA=${PYA:-$ROOT/worktrees/pr39/.venv-audit/Scripts/python.exe}    # the app's test venv (eval runner)
HF=${HF:-$ROOT/work/apprentice/hf/models--Qwen--Qwen3-4B-Instruct-2507/snapshots/cdbee75f17c01a7cc42f958dc650907174af0554}
GGUF=${GGUF:-$ROOT/work/apprentice/gguf/q3-4b-2507/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}
LLAMA=${LLAMA:-$ROOT/work/gpu-test/cuda}
CONVERT=${CONVERT:-$ROOT/work/gpu/train/llamacpp-src/convert_lora_to_gguf.py}
PORT=${PORT:-8098}
SUITES=${SUITES:-"evals/roblox/golden-tasks-v2.json evals/roblox/golden-tasks-creation-v1.json"}
mkdir -p "$W/runs" "$W/lora" "$W/gate" "$W/logs"
best_epoch() { "$PYT" -c "import json,sys;print(json.load(open(sys.argv[1])).get('best_epoch') or '')" "$(cygpath -w "$1/train-log.json")"; }
log() { echo "$(date -u +%H:%M:%SZ) $*" | tee -a "$W/logs/pipeline.log"; }

blocked() {
  tasklist //FI "IMAGENAME eq RobloxStudioBeta.exe" 2>/dev/null | grep -qi robloxstudio && { echo "Roblox Studio is running"; return 0; }
  # OWN_LLAMA=1: the only other llama-server is our kb_replica.py embedding server (port 8095)
  [ "${OWN_LLAMA:-0}" = 1 ] || { tasklist //FI "IMAGENAME eq llama-server.exe" 2>/dev/null | grep -qi llama-server && { echo "another llama-server is running"; return 0; }; }
  local busy; busy=$(cd "$APP/server/training/apprentice" && "$PYT" -c "from train_qlora import owner_busy; print(owner_busy(6.0))")
  [ -n "$busy" ] && { echo "$busy"; return 0; }      # a game in use, or free RAM below 6 GB
  return 1
}

blocked_game() {   # the checks that also apply while our own server runs
  tasklist //FI "IMAGENAME eq RobloxStudioBeta.exe" 2>/dev/null | grep -qi robloxstudio && { echo "Roblox Studio is running"; return 0; }
  local busy; busy=$(cd "$APP/server/training/apprentice" && "$PYT" -c "from train_qlora import owner_busy; print(owner_busy(6.0))")
  [ -n "$busy" ] && { echo "$busy"; return 0; }
  return 1
}

export_lora() {   # run-dir epoch name
  "$PYT" "$CONVERT" --base "$HF" --outtype f16 --outfile "$W/lora/$3.gguf" "$1/epoch-$2" > "$W/logs/convert-$3.log" 2>&1
}

sft() {
  why=$(blocked) && { log "sft REFUSED: $why"; return 1; }
  log "sft: start ($(wc -l < "$DATA/sft/train.jsonl") train / $(wc -l < "$DATA/sft/val.jsonl") val, ${EPOCHS:-2} epochs)"
  (cd "$APP/server/training/apprentice" && "$PYT" train_qlora.py --model "$HF" --data "$DATA/sft" --out "$W/runs/sft" \
      --epochs "${EPOCHS:-2}" --stop-procs robloxstudio --ram-floor 6 > "$W/logs/train-sft.log" 2>&1)
  best=$(best_epoch "$W/runs/sft")
  [ -n "$best" ] || { log "sft: no finished epoch"; return 1; }
  export_lora "$W/runs/sft" "$best" sft && log "sft: exported lora/sft.gguf (epoch $best)"
}

kto() {
  why=$(blocked) && { log "kto REFUSED: $why"; return 1; }
  best=$(best_epoch "$W/runs/sft")
  log "kto: start from sft epoch $best"
  (cd "$APP/server/training/finetune" && "$PYT" train_kto.py --model "$HF" --adapter "$W/runs/sft/epoch-$best" \
      --data "$DATA/kto" --out "$W/runs/kto" --epochs 1 --lr "${KTO_LR:-5e-5}" --stop-procs robloxstudio > "$W/logs/train-kto.log" 2>&1)
  [ -d "$W/runs/kto/epoch-1" ] || { log "kto: no finished epoch"; return 1; }
  export_lora "$W/runs/kto" 1 kto && log "kto: exported lora/kto.gguf"
}

serve() {   # name [--lora file]
  local name=$1; shift
  "$LLAMA/llama-server.exe" -m "$GGUF" --alias "$name" --host 127.0.0.1 --port $PORT -ngl 99 -c 24576 -np 1 \
      -ctk q8_0 -ctv q8_0 -fa on --jinja --reasoning off "$@" > "$W/logs/server-$name.log" 2>&1 &
  SERVER=$!
  for i in $(seq 1 90); do curl -s "http://127.0.0.1:$PORT/health" | grep -q ok && return 0; sleep 2; done
  log "server $name did not start"; return 1
}

stop_server() {
  local wp; wp=$(ps -p "$SERVER" | awk 'NR==2{print $4}'); kill "$SERVER" 2>/dev/null; sleep 2
  [ -n "$wp" ] && taskkill //F //PID "$wp" >/dev/null 2>&1; return 0
}

gate() {   # arms...
  : "${STAR_EVAL_SSH:?set STAR_EVAL_SSH}" "${STAR_EVAL_KNOWLEDGE:?set STAR_EVAL_KNOWLEDGE}"
  for arm in "$@"; do
    why=$(blocked) && { log "gate $arm REFUSED: $why"; return 1; }
    case $arm in
      base|bank) model=q3-4b-base; serve $model || return 1 ;;
      *) model=apprentice-$arm; serve $model --lora "$W/lora/$arm.gguf" || return 1 ;;
    esac
    extra=(); [ "$arm" = bank ] && extra=(--bank "$DATA/bank.jsonl")
    for suite in $SUITES; do
      name=$(basename "$suite" .json | sed 's/golden-tasks-//')
      why=$(blocked_game) && { log "gate $arm REFUSED: $why"; stop_server; return 1; }
      log "gate: $arm on $name"
      (cd "$APP" && APPDATA=$(mktemp -d) "$PYA" server/training/finetune/gate_run.py --arm "$arm" --model "$model" \
          --server "http://127.0.0.1:$PORT/v1" --suite "$suite" --out "$W/gate/$arm-$name.json" "${extra[@]}" \
          >> "$W/logs/gate-$arm.log" 2>&1)
    done
    stop_server
  done
}

report() {   # control candidate
  local c=() k=()
  for suite in $SUITES; do name=$(basename "$suite" .json | sed 's/golden-tasks-//'); c+=("$W/gate/$1-$name.json"); k+=("$W/gate/$2-$name.json"); done
  (cd "$APP" && "$PYA" server/training/finetune/gate_report.py --control "${c[@]}" --candidate "${k[@]}" \
      --json "$W/gate/report-$2-vs-$1.json") | tee -a "$W/logs/pipeline.log"
}

step=${1:-}; shift || true
case $step in
  sft) sft ;;
  kto) kto ;;
  gate) gate "$@" ;;
  report) report "$@" ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
