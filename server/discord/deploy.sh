#!/usr/bin/env bash
# Run STAR's Discord bot on a STAR server container (brain 2) instead of the owner's PC. Run from the repository
# root on the PC (Git Bash):
#
#   STAR_DISCORD_SSH=<user@address of the LXD host> bash server/discord/deploy.sh <command>
#
#   install    copy the code (git HEAD: star/, requirements*.txt, server/discord/) to /opt/star/discord/releases/<sha>,
#              point current -> it (the old one becomes previous), create/refresh the venv, install the unit, enable it
#              at boot. Restarts the bot only if it was already running. First install: set STAR_BRAIN_URL
#              (http://<brain 1 LAN address>:8080/v1) to write the bot's STAR settings (state/star-ai/settings.json).
#   secrets    copy ~/.star/discord.env, discord-settings.env, server_api_key and gpu-worker.key (created here
#              the first time, with ~/.star/gpu-worker.env for the PC GPU worker) from this PC to
#              /opt/star/discord/secrets (directory 0700, files 0600, owner star-discord). Contents never printed.
#              Restart the bot afterwards (stop, start) so it reads a new key.
#   doctor     offline readiness check as the service user (prints no token)
#   start      start the bot (stop the PC bot FIRST: two copies would both answer)
#   stop       stop the bot
#   status     service state, the running release and the last journal lines
#   rollback   current <-> previous release, then restart if it was running
#   gate       Star's live status + allow-listed actions (server/discord/gate/): installs star_gate.py in this
#              container with the star-discord-gate socket (only star-discord can open it), creates the bot's own
#              SSH key (secrets/gate_ed25519, never printed) and, with STAR_GATE1_SSH=<user@brain 1 LXD host>,
#              installs star_gate.py in brain 1's container plus ~/.local/bin/star-bot-gate on that host and adds
#              the bot's public key to its authorized_keys as restrict,command=star-bot-gate (the key can do nothing
#              else; known_hosts comes from this PC's). Then set STAR_DISCORD_GATE_1=ssh:<user@host> and
#              STAR_DISCORD_GATE_2=unix:/run/star-discord-gate.sock in discord-settings.env.
#              Undo: STAR_GATE1_SSH=... bash deploy.sh gate-remove
#
# The address is operator configuration and is never stored in the repository. Commands run as root inside the
# container through `lxc exec`; the bot itself runs as the unprivileged user star-discord.
set -euo pipefail
target="${STAR_DISCORD_SSH:?set STAR_DISCORD_SSH to user@address of the LXD host}"
container="${STAR_LXC_CONTAINER:-starai}"
base=/opt/star/discord
unit=star-discord.service
cmd="${1:-}"
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" "lxc exec $container -- bash -c $(printf '%q' "$*")"; }
# stdin -> a file inside the container, written with umask 077 and handed to star-discord (never echoed).
push_secret() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$target" \
  "lxc exec $container -- bash -c $(printf '%q' "umask 077; cat > $base/secrets/$1.tmp && chown star-discord:star-discord $base/secrets/$1.tmp && chmod 600 $base/secrets/$1.tmp && mv $base/secrets/$1.tmp $base/secrets/$1")"; }
running() { remote "systemctl is-active --quiet $unit"; }

case "$cmd" in
install)
  root="$(git rev-parse --show-toplevel)"; cd "$root"
  sha="$(git rev-parse --short=12 HEAD)"
  echo "== user and folders"
  remote "id star-discord >/dev/null 2>&1 || useradd --system --home-dir $base/state --shell /usr/sbin/nologin star-discord"
  remote "install -d -o root -g root -m 755 $base $base/releases && install -d -o star-discord -g star-discord -m 700 $base/secrets $base/state"
  echo "== code (git HEAD $sha)"
  remote "rm -rf $base/releases/$sha.tmp && install -d -m 755 $base/releases/$sha.tmp"
  git archive HEAD star requirements.txt requirements-discord.txt server/discord |
    ssh -o BatchMode=yes "$target" "lxc exec $container -- tar -x --no-same-owner -C $base/releases/$sha.tmp"
  remote "rm -rf $base/releases/$sha && mv $base/releases/$sha.tmp $base/releases/$sha && chmod -R a+rX,go-w $base/releases/$sha"
  echo "== venv"
  remote "test -x $base/venv/bin/python || python3 -m venv $base/venv"
  remote "$base/venv/bin/python -m pip install -q --disable-pip-version-check -r $base/releases/$sha/requirements.txt -r $base/releases/$sha/requirements-discord.txt"
  remote "cd /tmp && $base/venv/bin/python -c 'import sys; sys.path.insert(0, \"$base/releases/$sha\"); import discord, pillow_heif, star.discord_bot.bot; print(\"imports ok, discord.py\", discord.__version__)'"
  echo "== STAR settings"
  settings=$base/state/star-ai/settings.json
  if remote "test -f $settings"; then
    echo "kept existing $settings"
  else
    url="${STAR_BRAIN_URL:?first install: set STAR_BRAIN_URL=http://<brain 1 LAN address>:8080/v1}"
    case "$url" in http://*:*/v1) ;; *) echo "STAR_BRAIN_URL must look like http://<address>:8080/v1" >&2; exit 2;; esac
    # Model names are the brain's role names (GET /v1/models); the quick/vision roles are discovered at run time too.
    printf '{"provider": "star_server", "server_endpoint": "%s", "model": "star-fast", "vision_model": "star-vision"}\n' "$url" |
      ssh -o BatchMode=yes "$target" "lxc exec $container -- bash -c $(printf '%q' "install -d -o star-discord -g star-discord -m 700 $base/state/star-ai && umask 077 && cat > $settings && chown star-discord:star-discord $settings")"
    echo "wrote $settings"
  fi
  echo "== switch current -> $sha"
  was_running=0; running && was_running=1
  remote "cd $base && old=\$(readlink current || true); if [ -n \"\$old\" ] && [ \"\$old\" != releases/$sha ]; then ln -sfn \"\$old\" previous; fi; ln -sfn releases/$sha current"
  remote "install -m 644 $base/current/server/discord/$unit /etc/systemd/system/$unit && systemctl daemon-reload && systemctl enable $unit"
  # Keep the current, previous and two older releases.
  remote "cd $base/releases && keep=\"\$(readlink ../current | cut -d/ -f2) \$(readlink ../previous 2>/dev/null | cut -d/ -f2)\"; ls -1t | grep -v '\\.tmp\$' | tail -n +5 | while read -r r; do case \" \$keep \" in *\" \$r \"*) ;; *) rm -rf \"\$r\";; esac; done"
  if [ "$was_running" = 1 ]; then remote "systemctl restart $unit"; echo "restarted"; else echo "installed and enabled at boot; not started (bash $0 start)"; fi
  ;;
secrets)
  remote "install -d -o star-discord -g star-discord -m 700 $base/secrets"
  # The PC GPU worker's files (star/discord_bot/gpu_worker.py): a new signing key the first time (shared with
  # the bot, never printed) and the worker's own SSH target (this same STAR_DISCORD_SSH).
  mkdir -p "$HOME/.star"
  if [ ! -s "$HOME/.star/gpu-worker.key" ]; then
    (umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$HOME/.star/gpu-worker.key")
    echo "created ~/.star/gpu-worker.key"
  fi
  [ -s "$HOME/.star/gpu-worker.env" ] || printf 'STAR_GPU_WORKER_SSH=%s\nSTAR_GPU_WORKER_CONTAINER=%s\n' "$target" "$container" > "$HOME/.star/gpu-worker.env"
  for name in discord.env discord-settings.env server_api_key gpu-worker.key; do
    file="$HOME/.star/$name"
    [ -f "$file" ] || { echo "missing $file" >&2; exit 2; }
    push_secret "$name" < "$file"
    echo "copied $name"
  done
  remote "ls -l $base/secrets | awk 'NR>1{print \$1, \$3, \$NF}'"
  ;;
doctor)
  remote "cd $base/current && runuser -u star-discord -- env STAR_DISCORD_HOST=server STAR_DISCORD_CONFIG_DIR=$base/secrets XDG_DATA_HOME=$base/state HOME=$base/state $base/venv/bin/python -m star.discord_bot doctor"
  ;;
start|stop)
  remote "systemctl $cmd $unit"
  remote "systemctl is-active $unit" || true
  ;;
status)
  remote "systemctl status $unit --no-pager -n 0 | head -n 12" || true
  remote "echo current: \$(readlink $base/current); echo previous: \$(readlink $base/previous 2>/dev/null || echo none)"
  remote "journalctl -u $unit --no-pager -n 15 -o short-iso" || true
  ;;
rollback)
  remote "cd $base && test -L previous" || { echo "no previous release to roll back to" >&2; exit 2; }
  remote "cd $base && cur=\$(readlink current); prev=\$(readlink previous); ln -sfn \"\$prev\" current; ln -sfn \"\$cur\" previous; echo current: \$prev"
  remote "install -m 644 $base/current/server/discord/$unit /etc/systemd/system/$unit && systemctl daemon-reload"
  if running; then remote "systemctl restart $unit"; echo "restarted"; fi
  ;;
gate)
  root="$(git rev-parse --show-toplevel)"; cd "$root"
  g=server/discord/gate
  echo "== brain 2 (this container): star_gate.py + socket"
  remote "install -d -o root -g root -m 755 /opt/star/discord-gate"
  ssh -o BatchMode=yes "$target" "lxc exec $container -- bash -c 'cat > /opt/star/discord-gate/star_gate.py && chmod 755 /opt/star/discord-gate/star_gate.py'" < "$g/star_gate.py"
  ssh -o BatchMode=yes "$target" "lxc exec $container -- bash -c 'cat > /etc/systemd/system/star-discord-gate.socket'" < "$g/star-discord-gate.socket"
  ssh -o BatchMode=yes "$target" "lxc exec $container -- bash -c 'cat > /etc/systemd/system/star-discord-gate@.service'" < "$g/star-discord-gate@.service"
  remote "systemctl daemon-reload && systemctl enable --now star-discord-gate.socket && systemctl is-active star-discord-gate.socket"
  echo "== the bot's own SSH key (secrets/gate_ed25519)"
  remote "test -s $base/secrets/gate_ed25519 || runuser -u star-discord -- ssh-keygen -q -t ed25519 -N '' -C star-discord-gate -f $base/secrets/gate_ed25519"
  pub="$(remote "cat $base/secrets/gate_ed25519.pub")"
  case "$pub" in ssh-ed25519\ *\ star-discord-gate) ;; *) echo "no usable public key" >&2; exit 2;; esac
  if [ -n "${STAR_GATE1_SSH:-}" ]; then
    host1="${STAR_GATE1_SSH#*@}"
    echo "== brain 1: star_gate.py in its container, star-bot-gate on its host"
    ssh -o BatchMode=yes "$STAR_GATE1_SSH" "lxc exec $container -- install -d -m 755 /opt/star/discord-gate"
    ssh -o BatchMode=yes "$STAR_GATE1_SSH" "lxc exec $container -- bash -c 'cat > /opt/star/discord-gate/star_gate.py && chmod 755 /opt/star/discord-gate/star_gate.py'" < "$g/star_gate.py"
    lxc1="$(ssh -o BatchMode=yes "$STAR_GATE1_SSH" 'command -v lxc')"
    sed -e "s#@LXC@#$lxc1#" -e "s#@CONTAINER@#$container#" "$g/star-bot-gate.sh" |
      ssh -o BatchMode=yes "$STAR_GATE1_SSH" 'mkdir -p ~/.local/bin && cat > ~/.local/bin/star-bot-gate && chmod 755 ~/.local/bin/star-bot-gate'
    # One line per key comment: replace an older star-discord-gate line, keep every other key untouched.
    home1="$(ssh -o BatchMode=yes "$STAR_GATE1_SSH" 'printf %s "$HOME"')"
    printf 'restrict,command="%s/.local/bin/star-bot-gate" %s\n' "$home1" "$pub" |
      ssh -o BatchMode=yes "$STAR_GATE1_SSH" 'f=~/.ssh/authorized_keys; cp -p "$f" "$f.bak-star-gate"; { grep -v " star-discord-gate$" "$f.bak-star-gate"; cat; } > "$f.tmp" && chmod 600 "$f.tmp" && mv "$f.tmp" "$f"; grep -c . "$f"'
    echo "== brain 1 host key for the bot (from this PC's known_hosts)"
    ssh-keygen -F "$host1" | grep -v '^#' | push_secret gate_known_hosts
    remote "runuser -u star-discord -- install -d -m 700 $base/state/.ssh && printf 'Host %s\n  IdentityFile %s\n  IdentitiesOnly yes\n  UserKnownHostsFile %s\n' '$host1' $base/secrets/gate_ed25519 $base/secrets/gate_known_hosts > $base/state/.ssh/config && chown star-discord:star-discord $base/state/.ssh/config && chmod 600 $base/state/.ssh/config"
    echo "== check: the bot asks brain 1 for facts through its key"
    remote "cd /tmp && runuser -u star-discord -- ssh -T -o BatchMode=yes '$STAR_GATE1_SSH' facts | head -c 120; echo"
  fi
  echo "== check: the bot asks brain 2 for facts through the socket"
  remote "cd $base/current && runuser -u star-discord -- $base/venv/bin/python -c 'import asyncio; from star.discord_bot.gate_client import Gate; print(str(asyncio.run(Gate(\"brain 2\", \"unix\", \"/run/star-discord-gate.sock\").call(\"facts\")).get(\"ok\")))'"
  ;;
gate-remove)
  remote "systemctl disable --now star-discord-gate.socket; rm -f /etc/systemd/system/star-discord-gate.socket /etc/systemd/system/star-discord-gate@.service; systemctl daemon-reload; rm -rf /opt/star/discord-gate"
  if [ -n "${STAR_GATE1_SSH:-}" ]; then
    ssh -o BatchMode=yes "$STAR_GATE1_SSH" 'f=~/.ssh/authorized_keys; grep -v " star-discord-gate$" "$f" > "$f.tmp"; chmod 600 "$f.tmp"; mv "$f.tmp" "$f"; rm -f ~/.local/bin/star-bot-gate'
    ssh -o BatchMode=yes "$STAR_GATE1_SSH" "lxc exec $container -- rm -rf /opt/star/discord-gate"
  fi
  echo "gate removed (the bot's key stays in secrets/; delete gate_ed25519* there to drop it)"
  ;;
*)
  sed -n '2,32p' "$0"; exit 2
  ;;
esac
