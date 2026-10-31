"""Owner-only Minecraft sign-in rehearsal. Preview creates no process or cache."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import stat
import sys
import time
from typing import Callable

from .minecraft import MinecraftServer, NodeTransport
from ..home import control
from ..home.onboarding import server_config

_LOGIN_URIS = frozenset(f"https://{host}/{path}" for host in ("microsoft.com", "www.microsoft.com")
                        for path in ("link", "devicelogin"))
_FIELDS = frozenset(MinecraftServer.__dataclass_fields__)


def validated_profile(value: MinecraftServer | dict) -> MinecraftServer:
    raw = asdict(value) if isinstance(value, MinecraftServer) else value
    if not isinstance(raw, dict) or set(raw) - _FIELDS:
        raise ValueError("Choose a configured Minecraft server profile without credential fields")
    try:
        row = server_config(raw["name"], raw["host"], raw.get("port", 25565), raw.get("username", "Star"),
                            raw.get("auth", "offline"), raw.get("allows_bots", False))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Choose a valid configured server explicitly marked as allowing bots") from None
    version = raw.get("version", "")
    if not isinstance(version, str) or (version and not re.fullmatch(r"[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?", version)):
        raise ValueError("Use a bounded Minecraft version or automatic detection")
    row["version"] = version
    return MinecraftServer(**row)


def configured_profile(home: Path, name: str) -> MinecraftServer:
    path = Path(home) / control.CONFIG_NAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Home needs a regular bounded configuration")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        minecraft = config["social"]["minecraft"]
        servers = minecraft["servers"]
        if minecraft.get("enabled") is not True or not isinstance(servers, list) or len(servers) > 100:
            raise ValueError
        rows = [row for row in servers if isinstance(row, dict) and row.get("name") == name]
        if len(rows) != 1:
            raise ValueError
        return validated_profile(rows[0])
    except (KeyError, TypeError, ValueError, OSError):
        raise ValueError("Choose one uniquely named enabled Minecraft server profile") from None


def validate_login(uri, code) -> tuple[str, str]:
    # Exact display endpoints: no credentials, redirects, queries, fragments,
    # alternate ports, Unicode hosts or prefix/suffix lookalikes are accepted.
    if (type(uri) is not str or uri not in _LOGIN_URIS or type(code) is not str or not 4 <= len(code) <= 24
            or not re.fullmatch(r"[A-Z0-9]{4,12}(?:-[A-Z0-9]{4,12})?", code)):
        raise ValueError("Minecraft returned an unsupported owner sign-in challenge")
    return uri, code


def _auth_cache(home: Path) -> Path:
    for path in (home / "auth", home / "auth" / "minecraft"):
        if path.is_symlink():
            raise ValueError("Minecraft cache must stay inside this Home folder")
        if path.exists():
            info = path.stat()
            if not path.is_dir() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("Minecraft cache must use ordinary local directories")
    return home / "auth" / "minecraft"


def run_setup(home: Path, profile: MinecraftServer | dict, *, connect: bool = False, timeout: float = 300.0,
              transport_factory=None, clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep, stopped: Callable[[], bool] | None = None,
              emit_auth: Callable[[str, str], None] | None = None) -> dict:
    """Connect only to an exact configured profile; never send commands or return auth material.

    emit_auth is a trusted owner-console callback, not an authenticated channel or
    model tool. It must not store or forward the short-lived code. Without it an
    auth challenge ends the rehearsal and closes the child.
    """
    if type(connect) is not bool or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 900:
        raise ValueError("Choose explicit connect and a timeout from one to nine hundred seconds")
    home = Path(home).resolve()
    server = validated_profile(profile)
    if configured_profile(home, server.name) != server:
        raise ValueError("The selected server must exactly match its saved Home profile")
    result = {"ok": True, "state": "preview", "connected": False, "autonomy_verified": False,
              "commands_sent": 0, "auth_prompts": 0, "child_closed": False,
              "summary": "Preview only; no process, sign-in or connection was started."}
    if not connect:
        return result
    host_stopped = stopped
    def is_stopped():
        return control.stopped(home) or (host_stopped is not None and host_stopped())
    child = None
    result.update(ok=False, state="unavailable", summary="Minecraft connection rehearsal could not start.")
    try:
        if is_stopped():
            result.update(state="stopped", summary="Minecraft connection rehearsal stopped.")
            return result
        cache = _auth_cache(home)
        factory = transport_factory or NodeTransport
        begin = clock()
        child = factory(server, auth_cache=cache)
        while True:
            if is_stopped():
                result.update(state="stopped", summary="Minecraft connection rehearsal stopped.")
                return result
            left = timeout - (clock() - begin)
            if left <= 0:
                result.update(state="timeout", summary="Minecraft connection rehearsal timed out.")
                return result
            events = child.poll()
            if not isinstance(events, (list, tuple)) or len(events) > 500:
                raise ValueError("Invalid bounded transport events")
            spawned = False
            for event in events:
                if is_stopped():
                    result.update(state="stopped", summary="Minecraft connection rehearsal stopped.")
                    return result
                if clock() - begin >= timeout:
                    result.update(state="timeout", summary="Minecraft connection rehearsal timed out.")
                    return result
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                if kind in ("kicked", "error", "end"):
                    result.update(state=kind, summary="Minecraft connection ended; review the server or account on the owner PC.")
                    return result
                if kind == "auth_code":
                    try:
                        uri, code = validate_login(event.get("uri"), event.get("code"))
                    except ValueError:
                        result.update(state="invalid_auth", summary="An unsupported owner sign-in challenge was refused.")
                        return result
                    if emit_auth is None:
                        result.update(state="owner_console_required", summary="Run in an owner console to see the temporary Microsoft sign-in code.")
                        return result
                    if result["auth_prompts"] >= 3:
                        result.update(state="auth_limit", summary="Too many sign-in challenges; restart when ready.")
                        return result
                    emit_auth(uri, code)
                    result["auth_prompts"] += 1
                elif kind == "spawn":
                    spawned = True
            if spawned and not is_stopped() and clock() - begin < timeout:
                result.update(ok=True, state="spawn_observed", connected=True,
                              summary="Observed Minecraft spawn; rehearsal ends here. Independent play is not verified.")
                return result
            sleep(min(0.1, left))
    except KeyboardInterrupt:
        result.update(state="interrupted", summary="Minecraft connection rehearsal interrupted.")
        return result
    except Exception:
        result.update(state="unavailable", summary="Minecraft connection rehearsal could not finish.")
        return result
    finally:
        if child is not None:
            try:
                child.close()
                result["child_closed"] = True
            except Exception:
                result.update(ok=False, state="cleanup_failed", summary="Minecraft child cleanup could not be confirmed.")


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--show-login-code", action="store_true",
                        help="Show the temporary sign-in code in this owner console even if stdout is redirected")
    args = parser.parse_args(argv)
    try:
        home = args.home or control.home_dir()
        profile = configured_profile(home, args.server)
        show = args.show_login_code or sys.stdout.isatty()
        def owner_console(uri, code):
            print(f"Open {uri} in your browser and enter: {code}", flush=True)
        result = run_setup(home, profile, connect=args.connect, timeout=args.timeout,
                           emit_auth=owner_console if show else None)
    except (ValueError, OSError):
        result = {"ok": False, "connected": False, "autonomy_verified": False,
                  "state": "configuration_required", "summary": "Choose a valid configured allowed server and owner setup options."}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(cli())
