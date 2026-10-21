"""Owner-local Discord configuration files (never part of the repository).

Two plain files in the owner's ``~/.star`` folder, both optional:

* ``discord.env``           the secret: ``DISCORD_BOT_TOKEN=...`` (the owner writes it himself)
* ``discord-settings.env``  nonsecret IDs and opt-in switches (``DISCORD_OWNER_ID=...`` etc.)

Process environment variables always win, so CI and the PowerShell helper keep working.
Only a fixed allowlist of keys is read; values are never logged or printed, and a
malformed line is reported by line number only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

TOKEN_FILE = "discord.env"
SETTINGS_FILE = "discord-settings.env"
MAX_FILE_BYTES = 16 * 1024

# Friendly owner-facing names -> the STAR_DISCORD_* names the bot uses internally.
ALIASES = {
    "DISCORD_BOT_TOKEN": "STAR_DISCORD_BOT_TOKEN",
    "DISCORD_TOKEN": "STAR_DISCORD_BOT_TOKEN",
    "DISCORD_OWNER_ID": "STAR_DISCORD_OWNER_IDS",
    "DISCORD_OWNER_IDS": "STAR_DISCORD_OWNER_IDS",
    "DISCORD_USER_ID": "STAR_DISCORD_OWNER_IDS",
    "DISCORD_GUILD_ID": "STAR_DISCORD_GUILD_IDS",
    "DISCORD_GUILD_IDS": "STAR_DISCORD_GUILD_IDS",
    "DISCORD_SERVER_ID": "STAR_DISCORD_GUILD_IDS",
    "DISCORD_CHANNEL_IDS": "STAR_DISCORD_CHANNEL_IDS",
}
ALLOWED = frozenset({
    "STAR_DISCORD_BOT_TOKEN", "STAR_DISCORD_OWNER_IDS", "STAR_DISCORD_GUILD_IDS",
    "STAR_DISCORD_CHANNEL_IDS", "STAR_DISCORD_SYNC_COMMANDS", "STAR_DISCORD_SYNC_GUILD_ID",
    "STAR_DISCORD_DM_CHAT", "STAR_DISCORD_DM_IMAGES", "STAR_DISCORD_DM_LEARNING_CANDIDATES",
    "STAR_DISCORD_DM_PROJECT", "STAR_DISCORD_SCREEN_CAPTURE", "STAR_DISCORD_RATE_LIMIT",
    "STAR_DISCORD_LEARNING_DM_OPT_IN", "STAR_DISCORD_LEARNING_DM_OWNER_ID",
    "STAR_DISCORD_LEARNING_REPORT", "STAR_DISCORD_LEARNING_REPORT_SSH",
    "STAR_DISCORD_LEARNING_STATE", "STAR_DISCORD_LEARNING_DM_COOLDOWN_HOURS",
    "STAR_DISCORD_LEARNING_CHECK_MINUTES",
    "STAR_DISCORD_LEARNING_VISUAL_MANIFEST", "STAR_DISCORD_LEARNING_VISUAL_DIRECTORY",
    "STAR_DISCORD_LAB_STATUS", "STAR_DISCORD_LAB_REPORT",
    "STAR_DISCORD_EVIDENCE_DIRECTORY", "STAR_DISCORD_EVIDENCE_REVIEWS",
    "STAR_DISCORD_WORK_STATUS", "STAR_DISCORD_WORK_REPORT",
    "STAR_DISCORD_PRESENCE", "STAR_DISCORD_PRESENCE_MINUTES",
    "STAR_DISCORD_DRAW", "STAR_DISCORD_DRAW_ANYONE", "STAR_DISCORD_DRAW_TIMEOUT", "STAR_DISCORD_MENTIONS",
    "STAR_DISCORD_HOST",
    "STAR_DISCORD_GATE_1", "STAR_DISCORD_GATE_2", "STAR_DISCORD_PROACTIVE", "STAR_DISCORD_DIGEST_TIMES",
    "STAR_DISCORD_EVENT_DMS_PER_HOUR", "STAR_DISCORD_OWNER_TZ",
})
# The token may only come from the secret file or the process environment.
_SECRET_KEYS = frozenset({"STAR_DISCORD_BOT_TOKEN"})


# Where the bot runs. 'server': a STAR server (server/discord/), which has no graphics card for drawing
# and no screen to capture, so those features say they need the PC instead of trying.
HOSTS = ("pc", "server")
# On the PC: this file in ~/.star means the bot runs on a server now, so the PC must not start a second copy.
SERVER_MARKER = "discord-runs-on-server"


def bot_host(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    value = str(source.get("STAR_DISCORD_HOST", "pc")).strip().lower() or "pc"
    if value not in HOSTS:
        raise ValueError("STAR_DISCORD_HOST must be pc or server")
    return value


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    override = str(source.get("STAR_DISCORD_CONFIG_DIR", "")).strip()
    return Path(override) if override else Path.home() / ".star"


def parse_env_text(text: str, *, origin: str) -> dict[str, str]:
    """KEY=VALUE lines; '#' comments; optional matching quotes. Unknown keys are refused."""
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"{origin} line {number}: expected NAME=value")
        name, value = line.split("=", 1)
        name = name.strip().upper()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        name = ALIASES.get(name, name)
        if name not in ALLOWED:
            raise ValueError(f"{origin} line {number}: unknown setting name")
        values[name] = value
    return values


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path.name} is unexpectedly large")
    return path.read_text(encoding="utf-8-sig")


def load_merged_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return process env overlaid on the local files (process env wins).

    The returned mapping holds the token in memory only; callers must not print it.
    """
    source = dict(os.environ if env is None else env)
    folder = config_dir(source)
    merged: dict[str, str] = {}
    settings = parse_env_text(_read(folder / SETTINGS_FILE), origin=SETTINGS_FILE)
    if any(key in _SECRET_KEYS for key in settings):
        raise ValueError(f"Keep the bot token in {TOKEN_FILE}, not {SETTINGS_FILE}")
    merged.update(settings)
    secret = parse_env_text(_read(folder / TOKEN_FILE), origin=TOKEN_FILE)
    merged.update(secret)
    for key, value in source.items():
        if key in ALLOWED and str(value).strip():
            merged[key] = str(value)
    # Keep unrelated process variables (APPDATA, PATH...) for the rest of STAR.
    for key, value in source.items():
        merged.setdefault(key, value)
    return merged


SETTINGS_TEMPLATE = """# STAR Discord bot: nonsecret local settings (never commit; the bot token goes in discord.env).
# Discord: User Settings > Advanced > Developer Mode, then right-click yourself / your server > Copy ID.
DISCORD_OWNER_ID=
DISCORD_GUILD_ID=
# Optional: only these text channels in your server (comma-separated). Empty = any channel in that server.
DISCORD_CHANNEL_IDS=
# 1 = register the slash commands in DISCORD_GUILD_ID on the next start (do it once, then set back to 0).
STAR_DISCORD_SYNC_COMMANDS=0
# Opt-in features (1 = on). Image/lesson switches need DM chat on.
STAR_DISCORD_DM_CHAT=1
STAR_DISCORD_DM_IMAGES=1
STAR_DISCORD_DM_LEARNING_CANDIDATES=0
# PC screenshots via /screen: each capture still needs a button press in Discord.
STAR_DISCORD_SCREEN_CAPTURE=0
# Read-only status/screenshot from a trusted locally staged Studio/Blender job receipt.
# Never accepts Discord-supplied file paths; the producer must supply SHA-matched evidence.
STAR_DISCORD_LAB_STATUS=0
STAR_DISCORD_LAB_REPORT=
# Optional native task events: still requires STAR_DISCORD_LEARNING_DM_OPT_IN=1.
# Operator-provisioned staging directory and SEPARATE operator-only review directory.
STAR_DISCORD_EVIDENCE_DIRECTORY=
STAR_DISCORD_EVIDENCE_REVIEWS=
# Optional: real worker activity feed (coding/studying/testing/research). Only a trusted host producer
# may write this local JSON; Discord users cannot choose a file path or start the jobs.
STAR_DISCORD_WORK_STATUS=0
STAR_DISCORD_WORK_REPORT=
# Make images ("draw a dragon" or /draw) on this PC's graphics card. ANYONE=1 also lets members of your
# approved server use /draw (never strangers' DMs). TIMEOUT: seconds before a picture is cancelled.
STAR_DISCORD_DRAW=1
STAR_DISCORD_DRAW_ANYONE=0
STAR_DISCORD_DRAW_TIMEOUT=240
# Where this bot runs: pc (default) or server (a STAR server: drawing and /screen then say they need the PC).
STAR_DISCORD_HOST=pc
# 1 = answer @STAR mentions in your approved server (Discord then sends the bot server message events;
# it still only sees the text of messages that mention it).
STAR_DISCORD_MENTIONS=0
# Requests per 10 minutes from the owner before STAR asks to slow down.
STAR_DISCORD_RATE_LIMIT=30
# Optional: bot-account activity (runtime status, not a channel message), fixed safe labels.
# Default off; updates no more often than every 10 minutes. Never put secrets in the labels.
STAR_DISCORD_PRESENCE=0
STAR_DISCORD_PRESENCE_MINUTES=15
# Night School digest DMs: 1 = send a short DM when practice numbers really change.
STAR_DISCORD_LEARNING_DM_OPT_IN=0
# Where the report comes from: an ssh login that can run 'lxc exec starai' (key login), or a local file path.
STAR_DISCORD_LEARNING_REPORT_SSH=
STAR_DISCORD_LEARNING_REPORT=
# Star's live status and allow-listed actions: one gate per brain (server/discord/deploy.sh gate sets them up).
# ssh:user@host (the bot's own key, forced to the gate command) or unix:/run/star-discord-gate.sock (same container).
STAR_DISCORD_GATE_1=
STAR_DISCORD_GATE_2=
# With LEARNING_DM_OPT_IN=1 and a gate: a morning and an evening note (owner-local times) and DMs for important
# events (at most this many an hour). /quiet holds them. PROACTIVE=0 switches only this part off.
STAR_DISCORD_PROACTIVE=1
STAR_DISCORD_DIGEST_TIMES=08:30,20:30
STAR_DISCORD_EVENT_DMS_PER_HOUR=3
# The owner's time zone (IANA, e.g. America/Chicago). Empty = the PC's offset, sent by the STAR GPU worker.
STAR_DISCORD_OWNER_TZ=
"""


def ensure_settings_file(env: Mapping[str, str] | None = None) -> bool:
    """Write SETTINGS_TEMPLATE if discord-settings.env is missing; never overwrite.

    Returns True only when a file was created. Holds no secrets; the token is never written here.
    """
    path = config_dir(env) / SETTINGS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(SETTINGS_TEMPLATE)
    except FileExistsError:
        return False
    except OSError:
        return False
    return True
