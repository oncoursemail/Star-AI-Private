#!/bin/sh
# Same-user Desktop Commander recovery. Invoke with the existing account's home and Node path.
set -eu
umask 077
RECOVERY_HOME=$1
NODE=$2
STATE="$RECOVERY_HOME/.local/state/star-desktop-commander"
ENTRY="$RECOVERY_HOME/.local/share/star-desktop-commander/node_modules/@wonderwhy-er/desktop-commander/dist/index.js"
CHECK="$RECOVERY_HOME/.local/share/star-recovery/remote_agent_present.py"
mkdir -p "$STATE"
exec 9>"$STATE/supervisor.lock"
/usr/bin/flock -n 9 || exit 0
log() {
  if [ -f "$STATE/supervisor.log" ] && [ "$(wc -c < "$STATE/supervisor.log")" -gt 1048576 ]; then
    mv -f "$STATE/supervisor.log" "$STATE/supervisor.previous.log"
  fi
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$STATE/supervisor.log"
}
rotate_agent_log() {
  # The agent appends (>>), so truncating in place keeps a long-running agent's log bounded too.
  if [ -f "$STATE/agent.log" ] && [ "$(wc -c < "$STATE/agent.log")" -gt 4194304 ]; then
    cp -f "$STATE/agent.log" "$STATE/agent.previous.log"
    : > "$STATE/agent.log"
  fi
}
log "Recovery supervisor started (PID $$)"
waiting=0
while :; do
  if [ -e "$STATE/DISABLED" ]; then
    log "Disabled by owner; exiting"
    exit 0
  fi
  remote_status=0
  /usr/bin/python3 "$CHECK" --check || remote_status=$?
  case "$remote_status" in
    0)
      if [ "$waiting" -ne 1 ]; then log "Existing remote host found; standing by"; fi
      waiting=1
      rotate_agent_log
      sleep 10
      continue
      ;;
    1) waiting=0 ;;
    *)
      if [ "$waiting" -ne 2 ]; then log "Process inspection inconclusive; checking again shortly"; fi
      waiting=2
      sleep 10
      continue
      ;;
  esac
  if [ ! -x "$NODE" ] || [ ! -r "$ENTRY" ]; then
    log "Pinned runtime unavailable; retrying after 120 seconds"
    sleep 120
    continue
  fi
  rotate_agent_log
  log "Starting authenticated remote host"
  cd "$RECOVERY_HOME"
  # The agent must not inherit the supervisor lock across a supervisor replacement.
  "$NODE" "$ENTRY" remote 9>&- >> "$STATE/agent.log" 2>&1 &
  agent=$!
  while kill -0 "$agent" 2>/dev/null; do
    rotate_agent_log
    sleep 10
  done
  wait "$agent" && code=0 || code=$?
  log "Remote host exited with code $code; retrying after 20 seconds"
  sleep 20
done
