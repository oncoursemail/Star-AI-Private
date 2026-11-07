"""STAR's client for the STAR Studio server: settings, waiting for Studio, and the pin to STAR Test Place.

The stand-in below answers like the real connector on the server did on 2026-10-11 (every tool needs
`studio_id`; a new connector lists no Studio at first; the instance name can be null). It "runs" the pin
guard the way the engine would: the guard text is checked separately, word for word.

The place behind the pin is the Studio guard's own stand-in (tests/studio_fake.py): its place has the
engine session the guard binds every change to, and it answers the guard's bound edits, its script
compare-and-set and its native playtest start and stop. So these tests run the pin under the guard as it
is now: a script edit and a playtest start reach the connector as Luau, with the pin on their first line.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import os
import re

import pytest

from star import studio, studio_loop as sl, studio_remote as sr
from studio_fake import FakeStudio

OWNER = 11752796808
SID = "srv-1"
TOOL_NAMES = ["list_roblox_studios", "get_studio_state", "search_game_tree", "script_read", "script_grep",
              "get_console_output", "screen_capture", "execute_luau", "multi_edit", "start_stop_play"]


def run(coroutine):
    return asyncio.run(coroutine)


class _Tool:
    def __init__(self, name):
        self.name = name

    def model_dump(self, **_):
        return {"name": self.name, "inputSchema": {"type": "object"}}


class _Listing:
    def __init__(self):
        self.tools = [_Tool(name) for name in TOOL_NAMES]
        self.nextCursor = None


def _text(text, error=False):
    return {"isError": error, "content": [{"type": "text", "text": text}]}


class FakeServerStudio:
    """One Studio with one open place. `ran` holds every Luau body of a caller that the place really executed."""

    def __init__(self, place_id=sr.TEST_PLACE_ID, game_id=sr.TEST_UNIVERSE_ID, creator=OWNER, attach_after=0):
        self.attach_after, self.polls = attach_after, 0
        self.studio_ids = [SID]
        self.calls, self.ran, self.unguarded = [], [], []
        self.silent = False
        self.place = FakeStudio(studio_id=SID, name="Place1", place_id=place_id, game_id=game_id, creator_id=creator)
        self.place.instances.clear()
        self.place.luau_effects = self._effects

    def _effects(self, code):                       # a guarded edit of the model's that the engine ran
        self.ran.append(code)
        return [("Part", "Workspace.StarPart")]

    place_id = property(lambda self: self.place.identity["placeId"],
                        lambda self, value: self.place.identity.__setitem__("placeId", value))
    game_id = property(lambda self: self.place.identity["gameId"],
                       lambda self, value: self.place.identity.__setitem__("gameId", value))
    scripts = property(lambda self: {path: item["source"] for path, item in self.place.scripts.items()})
    playing = property(lambda self: self.place.playing)

    async def list_tools(self, cursor=None):
        return _Listing()

    def _pin_holds(self):
        return ((self.place_id, self.game_id) == (sr.TEST_PLACE_ID, sr.TEST_UNIVERSE_ID)
                or (self.place_id, self.game_id) == (0, 0))

    async def call_tool(self, name, arguments=None):
        arguments = dict(arguments or {})
        self.calls.append((name, arguments))
        if name == "list_roblox_studios":
            self.polls += 1
            shown = [] if self.polls <= self.attach_after else [{"id": one, "name": None} for one in self.studio_ids]
            return _text(json.dumps({"studios": shown}))
        if arguments.get("studio_id") not in self.studio_ids:
            return _text("Unknown studio_id", error=True)
        if name == "execute_luau":
            if self.silent:
                raise TimeoutError("no answer")
            code = arguments["code"]
            if not code.startswith(sr.PIN_GUARD):
                self.unguarded.append(code)
                body = code
            elif not self._pin_holds():
                return _text("Error: " + sr.PIN_REFUSAL, error=True)
            else:
                body = code[len(sr.PIN_GUARD):]
            if body.startswith(f'return "{sr.PIN_OK} "'):
                # Simulate Studio evaluating the per-request Luau return value,
                # not simply replaying the previous static PIN_OK string.
                challenge = re.search(r'[.][.] " ([0-9a-f]{32})"$', body)
                assert challenge, "pin request must include a fresh challenge"
                return _text(f"{sr.PIN_OK} {self.place_id} {self.game_id} {challenge.group(1)}")
            if not body.startswith(("-- STAR:", "local __s = {added")):
                self.ran.append(body)               # Luau that is not one of the guard's own fixed snippets
            return await self.place.call_tool(name, {**arguments, "code": body})
        if name == "start_stop_play" and arguments.get("is_start") is False and not self.place.playing:
            return _text("Game Stopped")            # the real connector accepts a stop in Edit mode
        return await self.place.call_tool(name, arguments)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv(studio.COMMAND_ENV, raising=False)
    monkeypatch.setattr(sl, "own_account_id", lambda _home: OWNER)
    return tmp_path


async def opened(fake, home, **settings):
    guarded, facts = await sr.open_server(fake, await studio.list_tools(fake), home=home, wait_seconds=0, **settings)
    return guarded, facts


# ------------------------------------------------------------------ the guard text itself

def test_the_pin_guard_is_one_line_and_names_both_ids_never_a_name():
    assert "\n" not in sr.PIN_GUARD
    assert f"game.PlaceId == {sr.TEST_PLACE_ID} and game.GameId == {sr.TEST_UNIVERSE_ID}" in sr.PIN_GUARD
    assert "game.PlaceId == 0 and game.GameId == 0" in sr.PIN_GUARD
    assert (sr.TEST_UNIVERSE_ID, sr.TEST_PLACE_ID) == (10770312935, 128074805767678)
    assert "game.Name" not in sr.PIN_GUARD and ".Name" not in sr.PIN_QUESTION
    assert sr.PIN_GUARD.rstrip().endswith("end;") and "error(" in sr.PIN_GUARD


# ------------------------------------------------------------------ settings

def test_the_default_is_this_pc_and_nothing_is_stored(home):
    assert sr.load(home) == {"target": "pc", "command": []}
    shown = sr.public(home)
    assert shown["target"] == "pc" and shown["server_configured"] is False and not sr.settings_path(home).exists()


def test_target_and_command_are_stored_in_stars_data_folder_and_the_command_is_never_shown(home):
    command = ["ssh", "-o", "BatchMode=yes", "operator@studio-host.invalid", "/home/x/bin/studio-mcp.sh"]
    shown = sr.save(home, target="server", command=command)
    assert sr.load(home) == {"target": "server", "command": command}
    assert sr.launch_command(home) == command
    assert shown["server_configured"] is True and shown["server_program"] == "ssh"
    assert "studio-host" not in json.dumps(shown) and "operator" not in json.dumps(shown)
    assert sr.save(home, target="pc")["target"] == "pc" and sr.load(home)["command"] == command


@pytest.mark.parametrize("bad", ["ssh host", [], [""], ["ssh", 5], ["a"] * 41, ["x\x00y"], ["y" * 501]])
def test_a_command_that_is_not_a_plain_list_of_texts_is_refused(home, bad):
    with pytest.raises(ValueError):
        sr.save(home, command=bad) if bad != [] else sr.validate_command(bad)
    assert sr.load(home)["command"] == []


def test_a_damaged_settings_file_means_this_pc(home):
    sr.settings_path(home).parent.mkdir(parents=True)
    sr.settings_path(home).write_text('{"target": "moon", "command": "rm -rf"}', encoding="utf-8")
    assert sr.load(home) == {"target": "pc", "command": []}


def test_the_process_environment_wins_over_the_stored_command(home, monkeypatch):
    sr.save(home, target="server", command=["ssh", "stored"])
    monkeypatch.setenv(studio.COMMAND_ENV, json.dumps(["ssh", "from-environment"]))
    assert sr.launch_command(home) == ["ssh", "from-environment"]


def test_connect_hands_the_stored_command_to_stars_transport_and_restores_the_environment(home, monkeypatch):
    seen = []

    @asynccontextmanager
    async def transport():
        seen.append(os.environ.get(studio.COMMAND_ENV))
        yield "session"

    monkeypatch.setattr(studio, "connect", transport)
    sr.save(home, target="server", command=["ssh", "stored"])

    async def use():
        async with sr.connect(home) as session:
            return session

    assert run(use()) == "session" and json.loads(seen[0]) == ["ssh", "stored"]
    assert studio.COMMAND_ENV not in os.environ
    sr.save(home, target="pc")
    assert run(use()) == "session" and seen[1] is None          # this PC: the environment is left alone


def test_the_server_target_without_a_command_does_not_connect(home):
    sr.save(home, target="server")

    async def use():
        async with sr.connect(home):
            pass

    with pytest.raises(RuntimeError, match="no command"):
        run(use())


# ------------------------------------------------------------------ waiting for Studio

def test_a_new_connector_is_given_time_until_studio_attaches():
    fake = FakeServerStudio(attach_after=3)
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    listed = run(sr.wait_for_studio(fake, seconds=20, sleep=sleep))
    assert len(listed) == 1 and listed[0]["id"] == SID
    assert fake.polls == 4 and len(slept) == 3


def test_waiting_ends_with_an_empty_list_when_no_studio_attaches():
    fake = FakeServerStudio(attach_after=10 ** 6)
    ticks = iter(range(1000))
    listed = run(sr.wait_for_studio(fake, seconds=5, sleep=lambda _s: asyncio.sleep(0), clock=lambda: next(ticks)))
    assert listed == [] and 2 <= fake.polls <= 8


def test_the_server_is_used_only_with_exactly_one_studio(home):
    none = FakeServerStudio(attach_after=10 ** 6)
    guarded, facts = run(opened(none, home))
    assert guarded is None and "No Studio is attached" in facts["problem"]
    two = FakeServerStudio()
    two.studio_ids = [SID, "srv-2"]
    guarded, facts = run(opened(two, home))
    assert guarded is None and "More than one" in facts["problem"]


# ------------------------------------------------------------------ the pin

def test_star_test_place_may_be_built_in_and_every_luau_carries_the_pin(home):
    fake = FakeServerStudio()
    guarded, facts = run(opened(fake, home))
    assert guarded.verdict.editable and guarded.verdict.kind == "own" and facts["is_test_place"] is True
    result = run(guarded.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit",
                                                    "code": 'Instance.new("Part").Parent = workspace'}))
    assert not sl.result_failed(result) and len(fake.ran) == 1 and fake.unguarded == []
    sent = [arguments["code"] for name, arguments in fake.calls if name == "execute_luau"]
    assert sent and all(code.startswith(sr.PIN_GUARD) for code in sent)
    edit = next(code for code in sent if "Instance.new" in code)
    # The pin adds no line: it is in front of the guard's own check ("-- STAR:bound", which names the
    # place and the engine session), in the same engine call as the model's code.
    assert edit[len(sr.PIN_GUARD):].startswith("-- STAR:bound ") and edit.count(sr.PIN_GUARD) == 1
    assert guarded.journal.report()["edits"] == 1


def test_script_edit_and_playtest_work_in_the_test_place(home):
    fake = FakeServerStudio()
    guarded, _facts = run(opened(fake, home))
    edited = run(guarded.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "className": "Script",
                                                  "file_path": "ServerScriptService.A",
                                                  "edits": [{"old_string": "", "new_string": "print(1)"}]}))
    started = run(guarded.call_tool("start_stop_play", {"studio_id": SID, "is_start": True}))
    assert not sl.result_failed(edited) and fake.scripts == {"ServerScriptService.A": "print(1)"}
    assert not sl.result_failed(started) and fake.playing is True
    # The guard writes a script by compare-and-set and starts the playtest natively: both are Luau,
    # and every Luau call (also the Server-side ones during the playtest) had the pin on its first line.
    assert not {"multi_edit", "start_stop_play"} & {name for name, _arguments in fake.calls}
    sent = [arguments["code"] for name, arguments in fake.calls if name == "execute_luau"]
    assert fake.unguarded == [] and all(code.startswith(sr.PIN_GUARD) for code in sent)
    assert any("-- STAR:script-cas" in code for code in sent) and any("-- STAR:play-bound" in code for code in sent)
    stopped = run(guarded.call_tool("start_stop_play", {"studio_id": SID, "is_start": False}))
    assert not sl.result_failed(stopped) and fake.playing is False and fake.unguarded == []


def test_a_blank_unsaved_place_is_allowed(home):
    fake = FakeServerStudio(place_id=0, game_id=0, creator=0)
    guarded, facts = run(opened(fake, home))
    assert guarded.verdict.editable and guarded.verdict.kind == "blank" and facts["is_test_place"] is False
    run(guarded.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit", "code": "return 1"}))
    assert len(fake.ran) == 1


@pytest.mark.parametrize("place_id, game_id", [
    (777000111222, sr.TEST_UNIVERSE_ID),      # another place of the test experience
    (sr.TEST_PLACE_ID, 999000111),            # the place id under another experience id
    (555000111222, 666000111222),             # another experience of STAR's own account
])
def test_any_other_place_of_stars_own_account_is_read_only_on_the_server(home, place_id, game_id):
    fake = FakeServerStudio(place_id=place_id, game_id=game_id)       # same owner: studio_loop alone would allow it
    guarded, facts = run(opened(fake, home))
    assert guarded.verdict.editable is False and facts["is_test_place"] is False
    assert guarded.verdict.kind == "published" and "only STAR Test Place or a blank place" in facts["verdict"]["reason"]
    pinned = sr.PinnedSession(fake)                                    # and underneath, whoever calls:
    luau = run(pinned.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit", "code": "workspace:ClearAllChildren()"}))
    edit = run(pinned.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "file_path": "ServerScriptService.A",
                                               "className": "Script", "edits": [{"old_string": "", "new_string": "x"}]}))
    start = run(pinned.call_tool("start_stop_play", {"studio_id": SID, "is_start": True}))
    stop = run(pinned.call_tool("start_stop_play", {"studio_id": SID, "is_start": False}))
    assert sl.result_failed(luau) and sl.result_failed(edit) and sl.result_failed(start)
    assert fake.ran == [] and fake.scripts == {} and fake.unguarded == [] and pinned.refusals == 2
    assert not sl.result_failed(stop)                                  # a playtest can always be stopped
    read = run(pinned.call_tool("get_studio_state", {"studio_id": SID}))
    assert "Edit" in sl.result_text(read)                              # reads pass


def test_another_place_opened_after_the_check_gets_nothing(home):
    fake = FakeServerStudio()
    guarded, _facts = run(opened(fake, home))
    assert guarded.verdict.editable
    fake.place_id, fake.game_id = 555000111222, 666000111222           # the window now shows another own place
    luau = run(guarded.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit", "code": "workspace:ClearAllChildren()"}))
    edit = run(guarded.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "file_path": "ServerScriptService.A",
                                                "className": "Script", "edits": [{"old_string": "", "new_string": "x"}]}))
    start = run(guarded.call_tool("start_stop_play", {"studio_id": SID, "is_start": True}))
    assert sl.result_failed(luau) and sl.result_failed(edit) and sl.result_failed(start)
    assert fake.ran == [] and fake.scripts == {} and fake.playing is False and fake.unguarded == []


def test_no_answer_to_the_pin_question_means_no_edit(home):
    fake = FakeServerStudio()
    pinned = sr.PinnedSession(fake)
    fake.silent = True
    edit = run(pinned.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "file_path": "ServerScriptService.A",
                                               "className": "Script", "edits": [{"old_string": "", "new_string": "x"}]}))
    start = run(pinned.call_tool("start_stop_play", {"studio_id": SID, "is_start": True}))
    assert sl.result_failed(edit) and sl.result_failed(start) and fake.scripts == {} and fake.playing is False


def test_luau_without_text_is_refused_before_it_reaches_the_connector():
    fake = FakeServerStudio()
    result = run(sr.PinnedSession(fake).call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit"}))
    assert sl.result_failed(result) and fake.calls == []


def test_a_studio_that_does_not_answer_is_unknown_not_another_place(home):
    fake = FakeServerStudio()
    fake.silent = True

    async def quiet(name, arguments=None):
        if name == "execute_luau":
            return _text("", error=True)
        return await FakeServerStudio.call_tool(fake, name, arguments)

    fake.call_tool = quiet
    guarded, facts = run(opened(fake, home))
    assert guarded.verdict.editable is False and guarded.verdict.kind in ("unknown", "published")
    assert facts["is_test_place"] is False


def test_without_stars_account_id_the_test_place_is_read_only(home, monkeypatch):
    monkeypatch.setattr(sl, "own_account_id", lambda _home: None)
    guarded, facts = run(opened(FakeServerStudio(), home))
    assert guarded.verdict.editable is False and facts["is_test_place"] is True


def test_a_place_of_another_account_is_read_only(home):
    guarded, _facts = run(opened(FakeServerStudio(creator=42), home))
    assert guarded.verdict.editable is False


# ------------------------------------------------------------------ the Test action

def test_the_test_action_reports_tools_instance_place_and_rule(home):
    fake = FakeServerStudio(attach_after=2)

    @asynccontextmanager
    async def connector(_home):
        yield fake

    sr.save(home, target="server", command=["ssh", "operator@studio-host.invalid", "launcher"])
    report = run(sr.test(home, connector=connector, wait_seconds=5))
    assert report["ok"] is True and report["target"] == "server" and report["tools"] == len(TOOL_NAMES)
    assert report["is_test_place"] is True and report["verdict"]["kind"] == "own" and report["verdict"]["editable"] is False
    assert len(report["instances"]) == 1 and "Edit" in report["state"]
    assert fake.ran == [] and fake.scripts == {} and fake.playing is False        # the test changes nothing
    assert "studio-host" not in json.dumps(report)


def test_a_failed_test_never_repeats_the_command(home):
    @asynccontextmanager
    async def connector(_home):
        raise RuntimeError("ssh operator@studio-host.invalid: connection refused")
        yield

    report = run(sr.test(home, connector=connector))
    assert report["ok"] is False and report["problem"] == "Could not reach Studio (RuntimeError)"
    assert "studio-host" not in json.dumps(report)


def test_the_test_action_says_when_no_studio_is_attached(home):
    @asynccontextmanager
    async def connector(_home):
        yield FakeServerStudio(attach_after=10 ** 6)

    report = run(sr.test(home, connector=connector, wait_seconds=0))
    assert report["ok"] is False and "No Studio is attached" in report["problem"] and report["tools"] == len(TOOL_NAMES)


# ------------------------------------------------------------------ live (skipped without the server)

@pytest.mark.skipif(os.environ.get("STAR_STUDIO_LIVE") != "1" or not os.environ.get("STAR_STUDIO_LIVE_COMMAND"),
                    reason="needs the STAR Studio server: set STAR_STUDIO_LIVE=1 and STAR_STUDIO_LIVE_COMMAND (JSON list)")
def test_live_the_studio_server_answers_with_star_test_place(tmp_path, monkeypatch):
    monkeypatch.delenv(studio.COMMAND_ENV, raising=False)
    sr.save(tmp_path, target="server", command=json.loads(os.environ["STAR_STUDIO_LIVE_COMMAND"]))
    report = run(sr.test(tmp_path))
    assert report["ok"] is True, report.get("problem")
    assert report["tools"] >= 30 and report["new_tools"] == []
    assert report["is_test_place"] is True and report["verdict"]["place"]["place_id"] == sr.TEST_PLACE_ID


# The Studio process is a remote trust boundary. A log/error containing the
# expected return substring is not proof that the guarded pin query succeeded.
@pytest.mark.parametrize("forged_text", [
    f"Permission denied: {sr.PIN_OK} 0 0 (echoed from previous attempt)",
    f"{sr.PIN_OK} 0 0\\nStudio session changed",
    f"{sr.PIN_OK} {sr.TEST_PLACE_ID} {sr.TEST_UNIVERSE_ID} trailing output",
])
def test_pin_rejects_embedded_or_ambiguous_receipt_on_wrong_place(forged_text):
    fake = FakeServerStudio(place_id=555000111222, game_id=666000111222)
    original = fake.call_tool

    async def deceptive(name, arguments=None):
        if name == "execute_luau" and (arguments or {}).get("code", "").startswith(sr.PIN_QUESTION):
            return _text(forged_text)
        return await original(name, arguments)

    fake.call_tool = deceptive
    pin = sr.PinnedSession(fake)
    assert run(pin.pinned(SID)) is False
    result = run(pin.call_tool("multi_edit", {
        "studio_id": SID, "datamodel_type": "Edit",
        "className": "Script", "file_path": "ServerScriptService.A",
        "edits": [{"old_string": "", "new_string": "print('bad')"}],
    }))
    assert sl.result_failed(result)
    assert fake.scripts == {}


def test_pin_rejects_exact_replay_from_a_previous_successful_place():
    fake = FakeServerStudio()
    pin = sr.PinnedSession(fake)
    assert run(pin.pinned(SID)) is True
    fake.place_id, fake.game_id = 555000111222, 666000111222
    original = fake.call_tool

    async def replay(name, arguments=None):
        if name == "execute_luau" and (arguments or {}).get("code", "").startswith(sr.PIN_QUESTION):
            # Replay an authentic, previous *blank place* reply as a fresh one.
            return _text(f"{sr.PIN_OK} 0 0")
        return await original(name, arguments)

    fake.call_tool = replay
    assert run(pin.pinned(SID)) is False
