#!/bin/bash
# Saved project memory (G0b) on the live brain: give star-fast a slot-save directory, or take it away again.
# Run from the PC in Git Bash, as a live change under the quiet lock:
#
#   STAR_SSH_HOST=user@brain1 ./star.cmd lock run --owner claude --holder g0-enable --server 1 --max-minutes 10 -- \
#       bash Star-AI/server/brain/kv_banks/live.sh enable
#   ... live.sh undo            # removes the line again (the bank files stay; add --purge to delete them)
#   ... live.sh status
#
# enable: backs up /opt/star/config/models.ini, adds `slot-save-path = /opt/star/kv-banks/` under [star-fast],
# asks the router to reload (it unloads star-fast only, because only its preset changed) and loads star-fast again
# with one short request. Nothing else changes. The desktop side stays off until the owner sets
# STAR_KV_BANKS=on and STAR_KV_BANK_MODEL_REVISION (star/cache_banks.py). The key is read on the server, never printed.
set -u
HOST=${STAR_SSH_HOST:?set STAR_SSH_HOST=user@brain-host}
MODE=${1:-status}
PURGE=${2:-}
ssh -o BatchMode=yes "$HOST" "lxc exec ${STAR_CONTAINER:-starai} -- env MODE=$MODE PURGE=$PURGE bash -s" <<'REMOTE'
set -u
INI=/opt/star/config/models.ini
DIR=/opt/star/kv-banks
LINE="slot-save-path = $DIR/"
KEY=$(head -1 /opt/star/secrets/api_keys)
api() { curl -s -m "${2:-30}" -H "Authorization: Bearer $KEY" "http://127.0.0.1:8080$1"; }
load_fast() {
  api /models?reload=1 >/dev/null
  curl -s -m 600 -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' http://127.0.0.1:8080/v1/chat/completions \
    -d '{"model":"star-fast","messages":[{"role":"user","content":"Say OK."}],"max_tokens":4}' | head -c 300; echo
}
case $MODE in
enable)
  if grep -q '^slot-save-path' "$INI"; then echo "already enabled"; exit 0; fi
  cp -p "$INI" "$INI.bak-kvbanks-$(date -u +%Y%m%d%H%M%S)"
  install -d -o star -g star -m 700 "$DIR"
  sed -i "/^\[star-fast\]$/a $LINE" "$INI"
  grep -n -A1 '^\[star-fast\]' "$INI"
  load_fast ;;
undo)
  sed -i '/^slot-save-path = /d' "$INI"
  [ "$PURGE" = "--purge" ] && rm -f "$DIR"/*.bin
  load_fast ;;
status)
  grep -n '^slot-save-path' "$INI" || echo "slot-save-path: not set"
  ls -la "$DIR" 2>/dev/null | tail -n +2; du -sh "$DIR" 2>/dev/null ;;
*) echo "usage: live.sh enable|undo [--purge]|status"; exit 2 ;;
esac
REMOTE
