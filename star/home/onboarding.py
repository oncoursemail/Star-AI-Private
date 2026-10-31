"""Owner setup of social/game adapters. Preview by default; never signs in or connects."""
from __future__ import annotations

import argparse
from copy import deepcopy
import ipaddress
import json
from pathlib import Path
import re

from ..atomic_io import atomic_write_text
from ..social.activity import DEFAULT_SETTINGS, load_settings
from . import control


def social_config(value) -> dict:
    result = deepcopy(DEFAULT_SETTINGS)
    if value is not None and not isinstance(value, dict):
        raise ValueError("social settings must be an object")
    for key, item in (value or {}).items():
        if isinstance(result.get(key), dict) and isinstance(item, dict):
            result[key].update(deepcopy(item))
        else:
            result[key] = deepcopy(item)
    for key in ("discord", "roblox", "minecraft"):
        if not isinstance(result[key], dict) or type(result[key].get("enabled")) is not bool:
            raise ValueError("Adapter settings require explicit enabled booleans")
    if not isinstance(result["minecraft"].get("servers"), list) or len(result["minecraft"]["servers"]) > 16:
        raise ValueError("Minecraft needs a bounded server list")
    if any(not isinstance(row, dict) for row in result["minecraft"]["servers"]):
        raise ValueError("Minecraft server profiles must be objects")
    for row in result["minecraft"]["servers"]:
        if set(row) - {"name", "host", "port", "username", "auth", "version", "allows_bots"}:
            raise ValueError("Unrecognized Minecraft profile fields")
        if type(row.get("allows_bots", False)) is not bool:
            raise ValueError("Server permission must be a boolean")
        server_config(row.get("name"), row.get("host"), row.get("port", 25565), row.get("username", "Star"),
                      row.get("auth", "offline"), True)
        if not isinstance(row.get("version", ""), str) or not re.fullmatch(r"[A-Za-z0-9._-]{0,40}", row.get("version", "")):
            raise ValueError("Invalid Minecraft version")
    return result


def server_config(name: str, host: str, port: int, username: str, auth: str, allows_bots: bool) -> dict:
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name)
            or not isinstance(host, str) or not 1 <= len(host) <= 253 or host != host.strip()
            or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,120}", username)
            or auth not in ("microsoft", "offline") or allows_bots is not True):
        raise ValueError("Choose a named allowed server, valid port and Minecraft account label")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host) or any(not part or len(part) > 63 for part in host.split(".")):
            raise ValueError("Use a hostname or IP address without a URL, credentials or path") from None
    if auth == "offline" and not re.fullmatch(r"[A-Za-z0-9_]{3,16}", username):
        raise ValueError("Offline names must be 3–16 letters, digits or underscores")
    return {"name": name.strip(), "host": host, "port": port, "username": username, "auth": auth,
            "version": "", "allows_bots": True}


def configure(home: Path, *, discord: bool | None = None, server: dict | None = None, apply: bool = False,
              legacy_loader=load_settings) -> dict:
    if type(apply) is not bool:
        raise ValueError("Apply must be an explicit boolean")
    home = Path(home).resolve()
    path = home / "config.json"
    if path.is_symlink() or (path.exists() and path.stat().st_size > 262144):
        raise ValueError("Home settings must be a regular bounded configuration")
    raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("Home settings must be an object")
    social = social_config(legacy_loader() if raw.get("social") is None else raw["social"])
    if discord is not None:
        if type(discord) is not bool:
            raise ValueError("Choose Discord on or off")
        social["discord"]["enabled"] = discord
    if server is not None:
        server = server_config(server["name"], server["host"], server["port"], server["username"], server["auth"], server["allows_bots"])
        servers = list(social["minecraft"].get("servers") or [])
        matching = [i for i, row in enumerate(servers) if isinstance(row, dict) and row.get("name") == server["name"]]
        if len(matching) > 1:
            raise ValueError("Remove duplicate profile names before updating")
        if matching:
            servers.pop(matching[0])
        servers.insert(0, server)  # Existing Home plays the first configured profile.
        social["minecraft"].update(enabled=True, servers=servers)
    social_config(social)  # Validate the resulting list too, including an inserted seventeenth profile.
    if discord is None and server is None:
        raise ValueError("Choose a setting to preview")
    if apply:
        atomic_write_text(path, json.dumps({**raw, "social": social}, indent=2) + "\n")
    return {"applied": apply, "discord_enabled": social["discord"].get("enabled") is True,
            "minecraft_enabled": social["minecraft"].get("enabled") is True,
            "minecraft_profiles": len(social["minecraft"].get("servers") or []),
            "sign_in_performed": False, "live_use_verified": False,
            "next": "Restart Home after applying; authorize the Minecraft client separately before unattended play."}


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--discord", choices=("on", "off"))
    parser.add_argument("--minecraft-name", default="My server")
    parser.add_argument("--minecraft-host")
    parser.add_argument("--minecraft-port", type=int, default=25565)
    parser.add_argument("--minecraft-user", default="Star")
    parser.add_argument("--minecraft-auth", choices=("microsoft", "offline"), default="microsoft")
    parser.add_argument("--server-allows-bots", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        server = server_config(args.minecraft_name, args.minecraft_host, args.minecraft_port,
                               args.minecraft_user, args.minecraft_auth, args.server_allows_bots) if args.minecraft_host else None
        result = configure(args.home or control.home_dir(), discord=None if args.discord is None else args.discord == "on",
                           server=server, apply=args.apply)
    except (KeyError, ValueError, OSError):
        parser.error("Could not prepare configuration. Review selected settings; no sign-in or connection was performed.")
    print(json.dumps(result, indent=2))
    return 0
