#!/bin/bash
# Install or update the star-knowledge systemd service INSIDE the server's LXD container.
# Run from the PC (Git Bash):
#
#   bash server/knowledge/deploy.sh --install
#
# (that copies the code first and then pipes this file into a root shell in the container).
#
# What it does (and nothing else):
#   * copies the two Luau CLI tools the service needs (luau-compile, luau-analyze) from the
#     existing build in /opt/star/bench/tools/luau into /opt/star/knowledge/tools and records
#     the Luau source revision in tools/VERSION (no compiling, no downloads);
#   * installs /etc/systemd/system/star-knowledge.service and enables + (re)starts it.
#   * installs the nightly refresh: star-knowledge-refresh.service + .timer (timer enabled)
#     and the watchdog: star-knowledge-watchdog.service + .timer (every minute, enabled).
# It does not touch star-brain, /opt/star/config, /opt/star/models or the index.
# Uninstall: systemctl disable --now star-knowledge star-knowledge-refresh.timer star-knowledge-watchdog.timer
#            rm /etc/systemd/system/star-knowledge*.service /etc/systemd/system/star-knowledge-*.timer
set -eu
HOME_DIR=/opt/star/knowledge
LUAU_BUILD="${STAR_LUAU_BUILD:-/opt/star/bench/tools/luau}"
UNIT=star-knowledge.service

test -f "$HOME_DIR/app/$UNIT" || { echo "deploy first: $HOME_DIR/app/$UNIT is missing"; exit 1; }
test -f "$HOME_DIR/data/kb.sqlite3" || { echo "no index at $HOME_DIR/data/kb.sqlite3"; exit 1; }

install -d -o star -g star -m 0755 "$HOME_DIR/tools"
for tool in luau-compile luau-analyze; do
  src="$(readlink -f "$LUAU_BUILD/$tool" || true)"
  if [ -n "$src" ] && [ -x "$src" ]; then
    install -o star -g star -m 0755 "$src" "$HOME_DIR/tools/$tool"
  elif [ ! -x "$HOME_DIR/tools/$tool" ]; then
    echo "WARNING: $tool not found in $LUAU_BUILD; /luau/check will answer 503 until it is installed"
  fi
done
if [ -d "$LUAU_BUILD/.git" ]; then
  # git may refuse a repository owned by another user; the owner reads its own checkout
  runuser -u star -- git -C "$LUAU_BUILD" log -1 --format='luau %H %cs' > "$HOME_DIR/tools/VERSION" 2>/dev/null \
    || echo "luau (revision unknown)" > "$HOME_DIR/tools/VERSION"
  chown star:star "$HOME_DIR/tools/VERSION"
fi

install -o root -g root -m 0644 "$HOME_DIR/app/$UNIT" "/etc/systemd/system/$UNIT"
# The nightly refresh: installed and its timer enabled, never started here.
# The study job (star-knowledge-study.service) is NOT installed: measured on 2026-10-11 it did not
# improve retrieval (see starkb/study.py). To run the experiment further, copy that unit to
# /etc/systemd/system by hand and `systemctl start --no-block star-knowledge-study`.
for extra in star-knowledge-refresh.service star-knowledge-refresh.timer star-knowledge-watchdog.service star-knowledge-watchdog.timer; do
  install -o root -g root -m 0644 "$HOME_DIR/app/$extra" "/etc/systemd/system/$extra"
done
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null 2>&1
systemctl enable --now star-knowledge-refresh.timer >/dev/null 2>&1
# one real search a minute; restarts star-knowledge after 2 failures in a row (starkb/watchdog.py)
systemctl enable --now star-knowledge-watchdog.timer >/dev/null 2>&1
systemctl restart "$UNIT"
sleep 3
systemctl is-active "$UNIT"
systemctl --no-pager --lines=5 status "$UNIT" | sed -n '1,12p'
cat "$HOME_DIR/tools/VERSION" 2>/dev/null || true
ss -ltn | grep -E ':8091\b' || { echo "port 8091 is not listening"; journalctl -u "$UNIT" --no-pager -n 20; exit 1; }
