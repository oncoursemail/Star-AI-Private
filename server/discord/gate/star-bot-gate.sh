#!/bin/sh
# star-bot-gate: the forced command for STAR's Discord bot key on a brain's LXD host (authorized_keys:
# restrict,command="<this file>"). The key can only name a verb of star_gate.py inside the container.
# Installed by server/discord/deploy.sh gate; @LXC@ and @CONTAINER@ are filled in there.
exec @LXC@ exec @CONTAINER@ -- /usr/bin/python3 /opt/star/discord-gate/star_gate.py "$SSH_ORIGINAL_COMMAND"
