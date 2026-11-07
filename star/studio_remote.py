"""STAR's client for the STAR Studio server: a Roblox Studio that runs on another machine, signed in as STAR's
own Roblox account, driven through Roblox's official Studio MCP connector.

Transport. The connector is an MCP stdio command, for example carried over SSH with the key that already
exists (`ssh <host> <launcher script>`): no new network service is opened anywhere. Which command to run is
the operator's choice and never a model's: it comes from the process environment
(`STAR_STUDIO_MCP_COMMAND`, see star/studio.py) or from the small settings file this module keeps in STAR's
data folder (`studio/remote.json`: the target "pc" or "server", and the command). Nothing private is in
the repository; the command is never shown to a model and never part of an answer.

The sandbox rule for the server is narrower than the general one in star/studio_loop.py. There STAR may
change exactly one published place, STAR Test Place (experience 10770312935, place 128074805767678, both
checked; the name is never used), or a blank place that was never saved. `PinnedSession` enforces this
underneath the guarded session of studio_loop, independent of it:

  * every Luau call carries the check inside the same engine call (it cannot run anywhere else, even if
    another place is opened between a check and the call);
  * a script edit and a playtest start ask the place first and are refused on any other answer, on an
    error and on no answer;
  * reads and stopping a playtest pass through.

A freshly started connector answers its tool list at once but knows no Studio for about two seconds, until
Studio attaches to it: `wait_for_studio` waits for that instead of reporting "no Studio".
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any

from . import studio, studio_loop
from .policy import classify

TEST_UNIVERSE_ID = 10770312935
TEST_PLACE_ID = 128074805767678
TARGETS = {"pc": "Studio: this PC", "server": "Studio: STAR Studio server"}
PIN_OK = "STAR_PIN ok"
PIN_REFUSAL = "STAR pin: the open place is not STAR Test Place or a blank place; nothing was run"

# One line, so the line numbers of the code behind it stay the same. Reads only.
PIN_GUARD = (f"if not ((game.PlaceId == {TEST_PLACE_ID} and game.GameId == {TEST_UNIVERSE_ID}) "
             f"or (game.PlaceId == 0 and game.GameId == 0)) then error(\"{PIN_REFUSAL}\", 0) end; ")
PIN_QUESTION = PIN_GUARD + f'return "{PIN_OK} " .. tostring(game.PlaceId) .. " " .. tostring(game.GameId)'


# --------------------------------------------------------------------------- settings (target and command)

def settings_path(home) -> Path:
    return Path(home) / "studio" / "remote.json"


def validate_command(parts) -> list[str]:
    """The launcher as a list: the program, then its arguments. Same limits as star/studio.py."""
    if (not isinstance(parts, list) or not 1 <= len(parts) <= 40
            or any(not isinstance(part, str) or not part or "\x00" in part or len(part) > 500 for part in parts)):
        raise ValueError("The Studio server command must be a list of texts: the program, then its arguments")
    return list(parts)


def load(home) -> dict:
    """{"target": "pc" | "server", "command": [...] or []}. A missing or damaged file means this PC."""
    try:
        saved = json.loads(settings_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    target = saved.get("target") if isinstance(saved, dict) else None
    try:
        command = validate_command(saved.get("command")) if isinstance(saved, dict) and saved.get("command") else []
    except ValueError:
        command = []
    return {"target": target if target in TARGETS else "pc", "command": command}


def save(home, *, target: str | None = None, command: list[str] | None = None) -> dict:
    """Change the target and/or the command. Owner or operator action only: no model tool calls this."""
    current = load(home)
    if target is not None:
        if target not in TARGETS:
            raise ValueError("Choose this PC or the STAR Studio server")
        current["target"] = target
    if command is not None:
        current["command"] = validate_command(command) if command else []
    path = settings_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=1), encoding="utf-8")
    os.replace(temporary, path)
    return public(home)


def launch_command(home) -> list[str] | None:
    """The command for the server target. The process environment wins over the settings file."""
    custom = studio.custom_launcher()
    if custom:
        return [custom[0], *custom[1]]
    saved = load(home)
    return saved["command"] or None


def public(home) -> dict:
    """What the interface may show: never the command itself, only that one is stored and its program."""
    saved = load(home)
    command = launch_command(home) if saved["target"] == "server" else None
    return {"target": saved["target"], "label": TARGETS[saved["target"]],
            "targets": [{"id": key, "label": label} for key, label in TARGETS.items()],
            "server_configured": bool(launch_command(home)),
            "server_program": Path(command[0]).name if command else "",
            "test_place": {"universe_id": TEST_UNIVERSE_ID, "place_id": TEST_PLACE_ID}}


@asynccontextmanager
async def connect(home):
    """An MCP session with the Studio of the chosen target, through star/studio.py's own transport."""
    saved = load(home)
    if saved["target"] != "server":
        async with studio.connect() as session:
            yield session
        return
    command = launch_command(home)
    if not command:
        raise RuntimeError("The STAR Studio server is chosen but no command is stored for it")
    before = os.environ.get(studio.COMMAND_ENV)
    os.environ[studio.COMMAND_ENV] = json.dumps(command)
    try:
        async with studio.connect() as session:
            yield session
    finally:
        if before is None:
            os.environ.pop(studio.COMMAND_ENV, None)
        else:
            os.environ[studio.COMMAND_ENV] = before


# --------------------------------------------------------------------------- waiting for Studio, the pin

async def wait_for_studio(session, *, seconds: float = 20.0, pause: float = 0.5, sleep=asyncio.sleep,
                          clock=time.monotonic) -> list[dict]:
    """[{id, name}] once Studio has attached to the connector; [] when it did not within `seconds`."""
    end = clock() + seconds
    while True:
        listed = studio_loop.studios(await session.call_tool("list_roblox_studios", arguments={}))
        if listed or clock() >= end:
            return listed
        await sleep(pause)


class _Refused:
    def __init__(self, text: str):
        self._data = {"isError": True, "content": [{"type": "text", "text": text}]}

    def model_dump(self, **_):
        return self._data


def _starts_playtest(name: str, arguments: dict) -> bool:
    return name == "start_stop_play" and arguments.get("is_start") is not False


class PinnedSession:
    """The connector session of the Studio server, limited to STAR Test Place or a blank place.

    It sits under studio_loop.GuardedStudio (which keeps its own rule, journal and undo) and needs
    nothing from it: whatever calls `call_tool` gets the pin.
    """

    def __init__(self, session, planner: Any = None):
        self._session = session
        self.refusals = 0
        # STAR's resource planner (optional, star/planner_client.py): a playtest holds a "studio-test" lease on
        # brain 2, so two STAR processes never run tests in the same Studio and brain 2's RAM is checked first.
        # Not configured or unreachable: playtests start exactly as before.
        self.planner = planner
        self.place = None              # (universe, place) of the last pin answer
        self._play_grant = None

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def pinned(self, studio_id: str) -> bool:
        """Accept only the exact, freshly challenged reply from the chosen place.

        Connector output can contain diagnostic lines, echoed Luau source or
        previous responses. An embedded static success substring is not proof
        of a successful identity query: pin receipts must be single, exact and
        tied to this request. The challenge is not a credential or permission.
        """
        challenge = secrets.token_hex(16)
        result = await self._session.call_tool("execute_luau", arguments={
            "studio_id": studio_id, "datamodel_type": "Edit",
            "code": PIN_QUESTION + f' .. " {challenge}"',
        })
        if studio_loop.result_failed(result):
            return False
        text = studio_loop.result_text(result).strip()
        answers = {
            f"{PIN_OK} {TEST_PLACE_ID} {TEST_UNIVERSE_ID} {challenge}": (TEST_UNIVERSE_ID, TEST_PLACE_ID),
            f"{PIN_OK} 0 0 {challenge}": (0, 0),
        }
        place = answers.get(text)
        if place is None:
            return False
        self.place = place
        return True

    def _admit_playtest(self) -> str:
        """"" when the playtest may start (planner admitted it, or no planner), else the planner's reason."""
        if self.planner is None or not getattr(self.planner, "enabled", False):
            return ""
        from .planner_client import holding
        if holding("studio-test"):                # e.g. a Studio Lab run in this process already holds the Studio
            return ""
        universe, place = self.place or (0, 0)
        grant = self.planner.admit("studio-test", "studio-remote", "playtest", universe_id=universe, place_id=place,
                                   identity_verified=self.place is not None)
        if grant.action in ("wait", "yield", "refuse"):
            return grant.reason or grant.action
        self._play_grant = grant if grant.planned else None
        return ""

    def _end_playtest(self) -> None:
        if self._play_grant is not None:
            self.planner.release(self._play_grant)
            self._play_grant = None

    async def call_tool(self, name: str, arguments: dict | None = None):
        arguments = dict(arguments or {})
        if name == "execute_luau":
            code = arguments.get("code")
            if not isinstance(code, str):
                self.refusals += 1
                return _Refused("Refused: no Luau text")
            return await self._session.call_tool(name, arguments={**arguments, "code": PIN_GUARD + code})
        if name == "multi_edit" or _starts_playtest(name, arguments):
            try:
                allowed = await self.pinned(str(arguments.get("studio_id", "")))
            except Exception:
                allowed = False
            if not allowed:
                self.refusals += 1
                return _Refused("Refused: " + PIN_REFUSAL)
            if _starts_playtest(name, arguments):
                busy = self._admit_playtest()
                if busy:
                    return _Refused("Not started: the STAR Studio server is busy (" + busy + "); try again shortly")
        if name == "start_stop_play" and arguments.get("is_start") is False:
            try:
                return await self._session.call_tool(name, arguments=arguments)
            finally:
                self._end_playtest()
        if self._play_grant is not None and self._play_grant.planned:
            self._play_grant = self.planner.renew(self._play_grant)      # keep the lease of a long playtest alive
            if not self._play_grant.planned:
                self._play_grant = None
        return await self._session.call_tool(name, arguments=arguments)


def _planner():
    """The resource planner client when one is configured ($STAR_PLANNER_URL or ~/.star/planner_url), else None."""
    try:
        from .planner_client import PlannerClient
        client = PlannerClient(timeout=3.0)
    except Exception:
        return None
    return client if client.enabled else None


async def open_server(session, discovered: list[dict], *, home, opted_in: bool = True,
                      wait_seconds: float = 20.0) -> tuple[studio_loop.GuardedStudio | None, dict]:
    """The guarded session for the Studio server, or (None, why not). Exactly one Studio must be attached."""
    listed = await wait_for_studio(session, seconds=wait_seconds)
    facts = {"instances": listed}
    if len(listed) != 1:
        facts["problem"] = ("No Studio is attached to the connector (is the place open and Studio's MCP switch on?)"
                            if not listed else "More than one Studio is attached: STAR uses the server only with one")
        return None, facts
    pinned = PinnedSession(session, planner=_planner())
    guarded = await studio_loop.open_guarded(
        pinned, discovered, studio_id=listed[0]["id"], opted_in=opted_in, own_places=True,
        own_account_id=studio_loop.own_account_id(home))
    identity = guarded.verdict.identity
    facts["verdict"] = guarded.verdict.public()
    facts["is_test_place"] = bool(identity and (identity.place_id, identity.game_id) == (TEST_PLACE_ID, TEST_UNIVERSE_ID))
    if identity is None and guarded.verdict.kind == "unknown":
        # The identity question went through the pin too. Say which of the two it was: no answer at all,
        # or an answer from a place the server target does not allow (studio_loop alone would allow any
        # place of STAR's own account; the server allows one).
        try:
            answered = await pinned.pinned(listed[0]["id"])
        except Exception:
            answered = None
        if answered is False:
            guarded.verdict = studio_loop.Verdict(False, "published", "On the STAR Studio server STAR changes only "
                                                  "STAR Test Place or a blank place. Another place is open: STAR only reads it.")
            facts["verdict"] = guarded.verdict.public()
    return guarded, facts


# --------------------------------------------------------------------------- the Test action

async def test(home, *, connector=None, wait_seconds: float = 20.0) -> dict:
    """What the Test button of the Studio setting reports. Reads only; never raises; never shows the command."""
    saved = load(home)
    report = {"ok": False, "target": saved["target"], "label": TARGETS[saved["target"]], "tools": 0,
              "instances": [], "seconds": 0.0}
    started = time.monotonic()
    try:
        async with (connector or connect)(home) as session:
            discovered = await studio.list_tools(session)
            groups = classify(discovered)
            report["tools"] = len(discovered)
            report["new_tools"] = list(groups["unknown"])
            guarded, facts = await open_server(session, discovered, home=home, opted_in=False, wait_seconds=wait_seconds)
            report.update(facts)
            if guarded is not None:
                state = await session.call_tool("get_studio_state", arguments={"studio_id": guarded.studio_id})
                report["state"] = studio_loop.result_text(state)[:300]
                report["ok"] = not studio_loop.result_failed(state) and guarded.verdict.identity is not None
                if not report["ok"]:
                    report["problem"] = "Studio is attached but did not say which place is open"
    except Exception as error:  # the text of an error can hold the command: report its kind only
        report["problem"] = f"Could not reach Studio ({type(error).__name__})"
    report["seconds"] = round(time.monotonic() - started, 2)
    return report


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description="STAR's connection to the STAR Studio server")
    parser.add_argument("--home", required=True, help="STAR's data folder (the settings file lives in <home>/studio)")
    parser.add_argument("--set-target", choices=sorted(TARGETS), help="this PC or the STAR Studio server")
    parser.add_argument("--set-command", metavar="JSON", help='the launcher as a JSON list, e.g. ["ssh", "host", "script"]')
    parser.add_argument("--test", action="store_true", help="connect and report (reads only)")
    chosen = parser.parse_args(arguments)
    home = Path(chosen.home).expanduser()
    if chosen.set_command is not None:
        try:
            save(home, command=json.loads(chosen.set_command) if chosen.set_command else [])
        except ValueError as error:
            print(str(error)); return 2
    if chosen.set_target:
        save(home, target=chosen.set_target)
    print(json.dumps(public(home), indent=1))
    if chosen.test:
        report = asyncio.run(test(home))
        print(json.dumps(report, indent=1))
        return 0 if report["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
