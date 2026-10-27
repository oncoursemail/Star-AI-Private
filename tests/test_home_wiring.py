"""STAR Home wiring: plug-ins, notifications, availability, invitations, Discord calls, voice link, social chat layout.

Fakes only: no screen, no Discord, no model, no sound device, no network.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from star.home import activities, attention, calls, control, invites, loop, notifications, runtime, voicelink
from star.home.attention import (Attention, AvailabilityModel, Inbox, Incoming, Situation,
                                 Standing)
from star.home.host import Executor
from star.home.hostagent import HostAdapter
from star.home.invites import Invite, Mind, decide, parse_invite
from star.home.life import Life
from star.social.chat import SocialChat
from star.social.friends import FriendMemory

NOW = 1_800_000_000.0           # a fixed epoch; clocks below start here


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeBackend:
    def __init__(self):
        self.calls, self.windows, self.front = [], {"Discord", "Roblox", "Minecraft"}, ""

    def run(self, argv, timeout):
        self.calls.append(("run", argv))
        return 0, "ok"

    def launch(self, target, args):
        self.calls.append(("launch", target))

    def screenshot(self, path):
        Path(path).write_bytes(b"\x89PNG")
        self.calls.append(("screenshot",))

    def click(self, x, y, button, clicks):
        self.calls.append(("click", x, y))

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def type_text(self, text):
        self.calls.append(("type", text))

    def key(self, keys):
        self.calls.append(("key", "+".join(keys)))

    def hold(self, key, seconds):
        self.calls.append(("hold", key))

    def foreground_title(self):
        return self.front

    def focus_window(self, title):
        if title in self.windows:
            self.front = title
            return True
        return False

    def of(self, kind):
        return [c[1:] for c in self.calls if c[0] == kind]


@pytest.fixture
def home(tmp_path):
    return tmp_path / "STAR" / "home"


@pytest.fixture
def memory(tmp_path):
    mem = FriendMemory(tmp_path / "friends.sqlite3")
    yield mem
    mem.close()


# ---- 1. social chat layout: mood and friend memory ride in the new user message ---------------------------------------
class Model:
    def __init__(self, answer="sounds fun!"):
        self.answer, self.calls = answer, []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.answer(system, user) if callable(self.answer) else self.answer


class FakeEmotion:
    def __init__(self, directive="a bit frustrated, plain and clipped", on=True):
        self.text, self.on, self.asked, self.messages, self.events = directive, on, [], [], []

    def enabled(self):
        return self.on

    def directive(self, *, person=None, partner_adult=None):
        self.asked.append((person, partner_adult))
        return self.text

    def note_line(self, text):
        return f"(mood: {text})" if text else ""

    def on_message(self, text, *, person=None):
        self.messages.append((text, person))

    def on_event(self, kind, **kw):
        self.events.append((kind, kw))

    def current(self):
        return {"emotions": {"joy": 0.3, "frustration": 0.03, "boredom": 0.08}, "valence": 0.15}


def test_chat_system_message_is_the_same_for_every_person_and_mood_goes_in_the_user_message(memory):
    emotion = FakeEmotion()
    model = Model()
    chat = SocialChat(memory, complete=model, emotion=emotion, clock=Clock())
    chat.handle("discord", "Mira", "I love horror games. My cat is called Miso.")
    chat.handle("discord", "Jon", "I build redstone farms.")
    chat.handle("discord", "mira", "what should we play tonight?")
    (system_a, _), (system_b, _), (system_c, user_c) = model.calls
    assert system_a == system_b == system_c                       # byte-identical: the server's prompt cache holds
    assert "Miso" not in system_c and "frustrated" not in system_c
    assert "I love horror games" in user_c and "(mood: a bit frustrated, plain and clipped)" in user_c
    assert user_c.rstrip().endswith("(mood: a bit frustrated, plain and clipped)")      # volatile part last
    assert "joy 0" not in user_c and "Your mood right now" not in user_c                # no raw numbers or dict dump


def test_chat_romance_is_only_offered_for_a_stated_adult_and_the_bond_uses_an_opaque_id(memory):
    emotion = FakeEmotion()
    chat = SocialChat(memory, complete=Model(), emotion=emotion, clock=Clock())
    chat.handle("discord", "Mira", "hi there")
    chat.handle("discord", "Mira", "I'm 25 by the way")
    chat.handle("discord", "Kid", "I'm 13")
    asked = {person: adult for person, adult in emotion.asked}
    assert all(person.startswith("friend-") for person in asked)          # never a name or a handle
    adults = [adult for (person, adult), name in zip(emotion.asked, ["Mira", "Mira", "Kid"]) if name == "Mira"]
    assert adults[0] is None and adults[-1] is True
    assert emotion.asked[-1][1] is None                                    # the minor: never True


def test_chat_leaves_the_mood_out_when_the_engine_is_off_and_feels_the_message_when_on(memory):
    model = Model()
    off = FakeEmotion(on=False)
    SocialChat(memory, complete=model, emotion=off, clock=Clock()).handle("discord", "Mira", "nice work!")
    assert "(mood" not in model.calls[0][1] and off.messages == [] and off.asked == []
    on = FakeEmotion()
    SocialChat(memory, complete=model, emotion=on, clock=Clock()).handle("discord", "Mira", "nice work!")
    assert on.messages and on.messages[0][0] == "nice work!" and on.messages[0][1].startswith("friend-")


def test_chat_intent_is_given_to_the_model_in_the_user_message(memory):
    model = Model()
    SocialChat(memory, complete=model, emotion=None, clock=Clock()).handle(
        "discord", "Mira", "wanna call?", intent="you decided yes: you will call them")
    system, user = model.calls[0]
    assert "(you decided yes: you will call them)" in user and "you decided" not in system


# ---- 2. plug-ins -----------------------------------------------------------------------------------------------------
def test_plugin_modules_include_the_new_packages_and_missing_ones_are_skipped():
    for name in ("star.play", "star.social", "star.senses", "star.computer", "star.watch"):
        assert name in activities.PLUGIN_MODULES
    registry = activities.default_registry(("star.not_installed_yet",))
    assert registry.plugin_errors == {} and "star.not_installed_yet" not in registry.items


def test_a_plugin_whose_own_dependency_is_missing_is_reported(monkeypatch):
    monkeypatch.setattr(activities.importlib, "import_module",
                        lambda name: (_ for _ in ()).throw(ImportError("no numpy", name="numpy")))
    registry = activities.default_registry(("star.fake_plugin_dep",))
    assert "numpy" in registry.plugin_errors["star.fake_plugin_dep"]


def test_adapters_add_nothing_without_a_runtime():
    registry = activities.default_registry(("star.social", "star.play", "star.senses"))
    assert registry.items.keys() == {"game_making", "drawing", "music", "research", "practice"}
    assert registry.handlers == {}


# ---- 3. the loop's emotion hook ---------------------------------------------------------------------------------------
def _simple_home(home, outcome, interest="research"):
    registry = activities.Registry()
    registry.register("only", interest, lambda ctx: dict(outcome), "only", needs_brain=False)
    life = Life(home, rng=random.Random(1))
    for name in list(life.interests()):
        if name != interest:
            life.set_interest(name, 0.1)
    return registry, life, Executor(home, FakeBackend())


def test_emotion_hook_passes_a_kind_string_not_a_dict(home, monkeypatch):
    from star import emotion
    import star.life
    seen = []
    monkeypatch.setattr(emotion, "on_event", lambda kind, **kw: seen.append((kind, kw)))
    monkeypatch.setattr(star.life, "flag", lambda name, home=None: False)   # her goals feel on their own (random); not under test here
    for outcome, interest, expected in (
            ({"ok": True, "verified": True, "summary": "drew it", "evidence": ["x"]}, "drawing", "creative_done"),
            ({"ok": True, "verified": True, "summary": "read it", "evidence": ["x"]}, "research", "learned_something"),
            ({"ok": True, "verified": True, "summary": "played", "evidence": ["x"]}, "play_games", "task_success"),
            ({"ok": False, "verified": False, "summary": "nope", "evidence": []}, "research", "task_failure")):
        seen.clear()
        registry, life, executor = _simple_home(home / interest / expected, outcome, interest)
        loop.cycle(home / interest / expected, {"pause_minutes": 0}, registry, life, executor, None)
        assert [k for k, _ in seen] == [expected] and isinstance(seen[0][0], str)
        assert seen[0][1]["only_if_enabled"] is True


def test_emotion_hook_never_breaks_the_loop(home, monkeypatch):
    from star import emotion

    def boom(*a, **k):
        raise RuntimeError("emotion is broken")
    monkeypatch.setattr(emotion, "on_event", boom)
    registry, life, executor = _simple_home(home, {"ok": True, "verified": True, "summary": "ok", "evidence": ["x"]})
    assert loop.cycle(home, {"pause_minutes": 0}, registry, life, executor, None)["state"] == "worked"


def test_history_records_how_long_a_session_took(home):
    registry, life, executor = _simple_home(home, {"ok": True, "verified": True, "summary": "ok", "evidence": ["x"],
                                                  "minutes": 12.34})
    loop.cycle(home, {"pause_minutes": 0}, registry, life, executor, None)
    assert life.history()[-1]["minutes"] == 12.3


# ---- 4. bot.js loads the skill runner ---------------------------------------------------------------------------------
NODE = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
BOT_JS = Path(__file__).resolve().parents[1] / "star" / "games" / "mineflayer" / "bot.js"


@pytest.mark.skipif(not Path(NODE).exists(), reason="Node.js not installed")
def test_bot_js_hands_run_skill_to_the_skill_runner_and_keeps_its_own_commands(tmp_path):
    modules = tmp_path / "node_modules"
    (modules / "mineflayer").mkdir(parents=True)
    (modules / "mineflayer" / "index.js").write_text(
        "const E = require('events')\n"
        "exports.createBot = () => { const b = new E(); b.loadPlugin = () => {}; b.players = {}; b.health = 20; b.food = 20;\n"
        "  b.inventory = { items: () => [] }; b.entities = {}; b.entity = { position: { x: 0, y: 64, z: 0, distanceTo: () => 0 }, yaw: 0, pitch: 0 };\n"
        "  b.registry = { blocksByName: {} }; b.quit = () => process.exit(0); b.chat = (t) => console.log(JSON.stringify({ type: 'said', t })); return b }\n",
        encoding="utf-8")
    (modules / "mineflayer-pathfinder").mkdir()
    (modules / "mineflayer-pathfinder" / "index.js").write_text(
        "exports.pathfinder = {}; exports.Movements = class {}; exports.goals = {}\n", encoding="utf-8")
    feed = (json.dumps({"cmd": "run_skill", "id": "s1", "name": "idle", "code": "return 1", "timeout_ms": 2000}) + "\n"
            + json.dumps({"cmd": "chat", "text": "hello"}) + "\n" + json.dumps({"cmd": "bogus"}) + "\n")
    done = subprocess.run([NODE, str(BOT_JS)], input=feed, capture_output=True, text=True, timeout=30,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), cwd=str(BOT_JS.parent),
                          env={**os.environ, "NODE_PATH": str(modules), "STAR_MC_CONFIG": "{}"})
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    assert any(e["type"] == "skill_result" and e["id"] == "s1" and e["ok"] for e in events), done.stderr
    assert {"type": "said", "t": "hello"} in events                       # bot.js's own chat command still works
    assert any(e["type"] == "error" and "bogus" in e["message"] for e in events)       # and unknown ones still fail


# ---- 5. availability --------------------------------------------------------------------------------------------------
FLAT = {"availability": {"message_delay_s": {"close": [10, 10], "friend": [60, 60], "met": [300, 300]},
                         "later_chance": {"close": 0, "friend": 0, "met": 0},
                         "call_pickup_s": [4, 4], "call_answer_chance": {"close": 1, "friend": 1}}}
CLOSE = Standing(True, "friend", 0.9)
FRIEND = Standing(True, "friend", 0.3)
MET = Standing(True, "met", 0.0)


def model(config=FLAT, seed=1):
    return AvailabilityModel(config, rng=random.Random(seed))


def dm(sender="Mira", at=NOW):
    return Incoming("dm", "discord", sender, "hi", at=at)


def test_close_friends_are_answered_sooner_than_friends_and_strangers():
    m, idle = model(), Situation()
    close, friend, met = (m.decide(dm(), s, idle, NOW) for s in (CLOSE, FRIEND, MET))
    assert (close.at - NOW, friend.at - NOW, met.at - NOW) == (10, 60, 300)
    assert close.action == friend.action == met.action == "answer"


def test_blocked_and_muted_people_get_no_answer_at_all():
    for standing in (Standing(True, "friend", 1.0, blocked=True), Standing(True, "friend", 1.0, muted=True)):
        assert model().decide(dm(), standing, Situation(), NOW).action == "ignore"
        call = Incoming("call", "discord", "Mira", at=NOW, ring_s=45)
        assert model().decide(call, standing, Situation(), NOW).action == "ignore"


def test_sometimes_she_gets_to_it_much_later():
    cfg = {"availability": {**FLAT["availability"], "later_chance": {"close": 1, "friend": 1, "met": 1},
                            "later_factor": [5, 5]}}
    assert model(cfg).decide(dm(), CLOSE, Situation(), NOW).at - NOW == 50


def test_mid_round_she_finishes_the_moment_first_but_only_up_to_a_bound():
    clock = Clock()
    situation = Situation(kind="game", in_moment=True)
    inbox = Inbox(model(), lambda i: CLOSE, situation, clock=clock)
    inbox.add(dm())
    clock.advance(30)                                  # past the 10 s delay, but the round is still going
    assert inbox.due() == []
    clock.advance(41)                                  # 71 s: the close-friend bound (60 s after the delay) has passed
    assert [p.incoming.sender for p in inbox.due()] == ["Mira"]
    situation.in_moment = False
    clock.t = NOW + 11
    assert inbox.due()                                 # the round ended: now


def test_quiet_hours_hold_messages_until_morning_and_refuse_calls():
    quiet = {"enabled": True, "start": "00:00", "end": "23:59"}                   # always quiet, for the test
    cfg = {"availability": {**FLAT["availability"], "quiet_hours": quiet}}
    answer = model(cfg).decide(dm(), CLOSE, Situation(), NOW)
    assert answer.action == "answer" and answer.at > NOW + 10 and "quiet" in answer.reason
    call = Incoming("call", "discord", "Mira", at=NOW, ring_s=45)
    assert model(cfg).decide(call, CLOSE, Situation(), NOW).action == "ignore"
    assert attention.in_quiet_hours(NOW, {"enabled": False}) is False


def test_calls_only_from_friends_only_while_they_ring_and_never_two_at_once():
    call = Incoming("call", "discord", "Mira", at=NOW, ring_s=45)
    assert model().decide(call, MET, Situation(), NOW).action == "ignore"             # a stranger
    taken = model().decide(call, CLOSE, Situation(), NOW)
    assert taken.action == "answer" and taken.at == NOW + 4
    assert model().decide(call, CLOSE, Situation(in_call=True), NOW).action == "ignore"
    short = Incoming("call", "discord", "Mira", at=NOW, ring_s=10)                    # would ring out before she gets to it
    assert model().decide(short, CLOSE, Situation(), NOW).action == "ignore"
    chance = {"availability": {**FLAT["availability"], "call_answer_chance": {"close": 0, "friend": 0}}}
    assert model(chance).decide(call, CLOSE, Situation(), NOW).action == "ignore"


def test_inbox_folds_repeats_serves_calls_first_and_turns_a_missed_call_into_a_follow_up():
    clock = Clock()
    inbox = Inbox(model(), lambda i: CLOSE, Situation(), clock=clock)
    inbox.add(dm())
    inbox.add(dm())
    assert len(inbox.waiting()) == 1 and inbox.waiting()[0].count == 2
    inbox.add(Incoming("call", "discord", "Jo", at=NOW, ring_s=45))
    clock.advance(20)
    assert [p.incoming.kind for p in inbox.due()] == ["call", "dm"]
    att = Attention(inbox, inbox.situation, clock=clock)
    clock.advance(60)                                  # the call stopped ringing before anyone served it
    att.watch_tick()
    kinds = sorted(p.incoming.kind for p in inbox.waiting())
    assert kinds == ["dm", "followup"]                 # Jo's missed call comes back as a message to answer


def test_messages_wait_while_she_is_on_a_call():
    clock = Clock()
    situation = Situation(in_call=True)
    inbox = Inbox(model(), lambda i: CLOSE, situation, clock=clock)
    inbox.add(dm())
    clock.advance(500)
    assert inbox.due() == []
    situation.in_call = False
    assert inbox.due()


# ---- 6. the scheduler interrupts an activity cleanly and resumes it ----------------------------------------------------
def test_an_activity_is_paused_for_a_friend_and_resumed_after(home):
    clock = Clock()
    life = Life(home, rng=random.Random(2))
    for name in list(life.interests()):
        life.set_interest(name, 0.1 if name != "play_games" else 5.0)
    served, runs = [], []
    registry = activities.Registry()

    def play(ctx):
        runs.append((ctx.resumed, dict(ctx.resume_state)))
        if not ctx.resumed:
            rt.inbox.add(dm("Mira", at=clock()))
            clock.advance(15)
            rt.attention.watch_tick()                         # the watcher: she is due now, stop the activity
            assert ctx.interrupt.is_set()
            return {"ok": True, "verified": False, "paused": True, "resume_state": {"level": 3}, "summary": "paused"}
        return {"ok": True, "verified": True, "summary": "finished the level", "evidence": ["done"]}

    registry.register("game", "play_games", play, "a game", needs_brain=False)
    registry.register_handler("discord:message", lambda inc, ctx: served.append(inc.sender) or {"ok": True, "summary": "answered"})
    rt = runtime.Runtime(home, {"pause_minutes": 0, **FLAT}, Executor(home, FakeBackend()), life, clock=clock,
                         rng=random.Random(3), memory=None, emotion=None)
    rt.standing = lambda platform, sender: CLOSE                                # friend memory is not the point here
    rt.inbox.standing_of = lambda incoming: CLOSE
    rt.attention.handlers.update(registry.handlers)
    config = {"pause_minutes": 0}
    first = loop.cycle(home, config, registry, life, rt.executor, None, attention=rt.attention)
    assert first["state"] == "paused" and life.history() == []                  # a pause is not an outcome
    assert rt.situation.kind == "idle"
    second = loop.cycle(home, config, registry, life, rt.executor, None, attention=rt.attention)
    assert second["state"] == "served" and served == ["Mira"]                  # the friend first
    third = loop.cycle(home, config, registry, life, rt.executor, None, attention=rt.attention)
    assert third["state"] == "worked" and runs[-1] == (True, {"level": 3})       # then back to the game, where it was
    assert len(life.history()) == 1 and life.history()[0]["verified"]


def test_a_brain_session_stops_between_steps_when_asked():
    from star.home import brain
    out = brain.run_session(lambda m, t: {"content": "x"}, types.SimpleNamespace(workspace=Path(".")),
                            types.SimpleNamespace(interests=lambda: {}),
                            interest="research", brief="b", goal=None, stop=lambda: True)
    assert out["paused"] is True and not out["verified"]


def test_served_items_run_their_handler_and_a_crash_is_a_result_not_a_crash():
    clock = Clock()
    inbox = Inbox(model(), lambda i: CLOSE, Situation(), clock=clock)
    handlers = {"discord:message": lambda inc, ctx: (_ for _ in ()).throw(RuntimeError("boom"))}
    att = Attention(inbox, inbox.situation, handlers, clock=clock)
    inbox.add(dm())
    inbox.add(Incoming("dm", "roblox", "Kid", "hi", at=NOW))
    clock.advance(400)
    out = att.serve(lambda platform: None)
    assert {o["route"] for o in out} == {"discord:message", "roblox:message"}
    assert all(not o["ok"] for o in out) and any("crashed" in o["summary"] for o in out)
    assert any("no handler" in o["summary"] for o in out)


# ---- 7. notifications -------------------------------------------------------------------------------------------------
def toast(app, title, body, ident="1", at=NOW):
    return notifications.Toast(ident, app, title, body, at)


def test_discord_toasts_become_dms_mentions_and_calls():
    parse = notifications.parse_toast
    assert parse(toast("Discord", "Alex", "hey star, wanna call?")) == Incoming("dm", "discord", "Alex", "hey star, wanna call?", at=NOW)
    mention = parse(toast("com.squirrel.Discord.Discord", "Alex (#general, Pals)", "@Star look"))
    assert mention.kind == "mention" and mention.sender == "Alex"
    ring = parse(toast("Discord", "Incoming Call", "Alex is calling you"))
    assert ring.kind == "call" and ring.sender == "Alex" and ring.ring_s > 0
    assert parse(toast("Discord", "Alex", "started a call")).kind == "call"
    roblox = parse(toast("Roblox", "Sam", "sent you a message"))
    assert roblox.platform == "roblox" and roblox.sender == "Sam"
    assert parse(toast("Mail", "Boss", "report")) is None and parse(toast("Discord", "", "")) is None


def _wpn_database(path, rows):
    Path(path).unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE NotificationHandler (RecordId INTEGER PRIMARY KEY, PrimaryId TEXT NOT NULL, HandlerType TEXT)")
    db.execute("CREATE TABLE Notification (\"Order\" INTEGER PRIMARY KEY, Id INTEGER NOT NULL, HandlerId INTEGER, Type TEXT NOT NULL, "
               "Payload BLOB, ArrivalTime INT64)")
    db.execute("INSERT INTO NotificationHandler VALUES (1, 'com.squirrel.Discord.Discord', 'app:desktop')")
    db.execute("INSERT INTO NotificationHandler VALUES (2, 'Microsoft.Mail', 'app:immersive')")
    for n, (handler, title, body) in enumerate(rows, 1):
        xml = f"<toast><visual><binding template=\"ToastGeneric\"><text>{title}</text><text>{body}</text></binding></visual></toast>"
        arrival = int((NOW + 11644473600) * 10_000_000) + n
        db.execute("INSERT INTO Notification (Id, HandlerId, Type, Payload, ArrivalTime) VALUES (?,?,?,?,?)",
                   (n, handler, "toast", xml.encode("utf-8"), arrival))
    db.commit()
    db.close()


def test_the_notification_database_source_reads_toasts_and_the_watcher_feeds_the_inbox(tmp_path):
    path = tmp_path / "wpndatabase.db"
    _wpn_database(path, [(1, "Old", "was already there")])
    source = notifications.WpnDatabaseSource(path)
    clock = Clock()
    inbox = Inbox(model(), lambda i: CLOSE, Situation(), clock=clock)
    watcher = notifications.NotificationWatcher(source, inbox, clock=clock)
    assert watcher.tick() == [] and inbox.waiting() == []                       # the first poll only learns what exists
    _wpn_database(path, [(1, "Old", "was already there"), (1, "Alex", "hey star, wanna call?"), (2, "Boss", "mail")])
    found = watcher.tick()
    assert [(i.kind, i.sender) for i in found] == [("dm", "Alex")]              # mail is not a watched app
    assert inbox.waiting()[0].incoming.text == "hey star, wanna call?"
    assert watcher.tick() == []                                                 # nothing is delivered twice
    toasts = source.poll()
    assert abs(toasts[0].at - NOW) < 5 and notifications.toast_from_xml("<toast><text>a</text><text>b</text></toast>") == ("a", "b")
    assert notifications.WpnDatabaseSource(tmp_path / "missing.db").poll() == []


# ---- 8. invitations: she decides, with reasons -----------------------------------------------------------------------
def test_invitations_are_read_from_dms_and_speech():
    assert parse_invite("hey star, wanna call?", "Alex") == Invite("call", "call", "Alex", "hey star, wanna call?")
    assert parse_invite("hop on vc?").kind == "call" and parse_invite("can you call me").kind == "call"
    play = parse_invite("do you wanna play minecraft?", "Alex")
    assert play.kind == "play" and play.what == "minecraft"
    assert parse_invite("let's play roblox tonight").what == "roblox"
    assert parse_invite("wanna play chess?") is None                       # not a game she can play
    assert parse_invite("the call was great yesterday") is None and parse_invite("hi!") is None


def mind(**kw):
    base = dict(standing=CLOSE, situation=Situation(), now=NOW, doing="", weights={}, mood=None)
    base.update(kw)
    return Mind(**base)


PLAY = Invite("play", "minecraft", "Alex")
CALL = Invite("call", "call", "Alex")
LOCAL_NOON = time.mktime(time.strptime("2026-10-26 14:00", "%Y-%m-%d %H:%M"))


def test_she_says_yes_when_nothing_stands_in_the_way():
    for invite in (CALL, PLAY):
        answer = decide(invite, mind(now=LOCAL_NOON))
        assert answer.say == "yes" and answer.score >= invites.THRESHOLD


def test_same_inputs_always_give_the_same_answer():
    runs = {(decide(PLAY, mind(now=LOCAL_NOON, played_today_min=200)).say,
             decide(PLAY, mind(now=LOCAL_NOON, played_today_min=200)).reason) for _ in range(20)}
    assert len(runs) == 1


def test_she_declines_for_reasons_not_for_luck(monkeypatch):
    from star import emotion
    monkeypatch.delattr(emotion, "invite_bias", raising=False)         # the seven-feeling engine: plain mood factors
    noon = {"now": LOCAL_NOON}
    tired = decide(PLAY, mind(played_today_min=420, **noon))
    assert tired.say == "no" and "played minecraft a lot" in tired.reason
    bored = decide(PLAY, mind(weights={"play_games": {"weight": 0.1}}, standing=FRIEND, **noon))
    assert bored.say in ("no", "later") and "likes it" in bored.reason
    grumpy = decide(CALL, mind(mood={"emotions": {"frustration": 0.7, "boredom": 0.08, "joy": 0.1}, "valence": -0.3},
                               standing=FRIEND, **noon))
    assert grumpy.say in ("no", "later") and "frustrated" in grumpy.reason
    lonely = decide(PLAY, mind(mood={"emotions": {"frustration": 0.03, "boredom": 0.5, "joy": 0.3}, "valence": 0.15},
                               weights={"play_games": {"weight": 0.5}}, standing=FRIEND, **noon))
    assert lonely.say == "yes"                                              # restless: company wins over a lukewarm game


def test_mid_round_or_mid_video_she_says_in_a_few_minutes_and_a_stranger_gets_no_call():
    round_ = decide(PLAY, mind(situation=Situation(kind="game", in_moment=True), now=LOCAL_NOON))
    assert round_.say == "later" and round_.delay_min == 5 and "round" in round_.reason
    video = decide(CALL, mind(situation=Situation(kind="video", in_moment=True), now=LOCAL_NOON))
    assert video.say == "later" and "video" in video.reason
    stranger = decide(CALL, mind(standing=MET, now=LOCAL_NOON))
    assert stranger.say == "no" and "know them" in stranger.reason
    assert decide(CALL, mind(situation=Situation(in_call=True), now=LOCAL_NOON)).say == "no"
    assert decide(CALL, mind(standing=Standing(True, "friend", 1.0, blocked=True), now=LOCAL_NOON)).say == "no"


def test_quiet_hours_and_late_nights_weigh_in():
    quiet = decide(CALL, mind(quiet_hours={"enabled": True, "start": "00:00", "end": "23:59"}, now=LOCAL_NOON))
    assert quiet.say == "no" and "quiet" in quiet.reason and quiet.tone == "sleepy"
    late = time.mktime(time.strptime("2026-10-26 23:30", "%Y-%m-%d %H:%M"))
    assert "it is late" in dict(decide(PLAY, mind(standing=FRIEND, now=late)).factors)
    assert "it is late" not in dict(decide(PLAY, mind(standing=CLOSE, now=late)).factors)       # close friends are worth it


def test_the_intent_names_the_decision_and_the_reason():
    yes = invites.intent_for(decide(CALL, mind(now=LOCAL_NOON)), CALL)
    assert "yes" in yes and "call them yourself" in yes
    later = invites.intent_for(decide(PLAY, mind(situation=Situation(kind="game", in_moment=True), now=LOCAL_NOON)), PLAY)
    assert "5 minutes" in later and "round" in later
    no = invites.intent_for(decide(PLAY, mind(played_today_min=420, now=LOCAL_NOON)), PLAY)
    assert "no" in no and "played minecraft a lot" in no


# ---- 9. the voice link ------------------------------------------------------------------------------------------------
class FakeTTS:
    sample_rate = 24000

    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        yield b"\x00\x00" * 160, 24000


class FakeSpeaker:
    def __init__(self):
        self.played, self.pending = [], 0.0

    def play(self, pcm, rate):
        self.played.append(len(pcm))

    def pending_seconds(self):
        return self.pending

    def stop(self):
        pass


class FakeSession:
    """The parts of CallSession that STAR Home touches."""

    def __init__(self):
        self.tts, self.speaker = FakeTTS(), FakeSpeaker()
        self.state, self.turns, self.fed, self.stopped = "listening", [], 0, False
        self.config = types.SimpleNamespace(game_context_for_voice=False, emotion_person="owner", emotion_partner_adult=None)
        self.game_events, self.brain, self._busy = None, None, False

    def busy(self):
        return self._busy

    def start(self):
        self.state = "listening"

    def feed(self, frame):
        self.fed += 1

    def stop(self):
        self.stopped = True


def blocking_frames(stop):
    while not stop.is_set():
        time.sleep(0.005)
        yield b"\x00" * 1024


def make_call(session=None, **kw):
    stop = threading.Event()
    session = session or FakeSession()
    call = voicelink.VoiceCall(session, blocking_frames(stop), closers=(stop.set,), **kw)
    return call


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_call_feeds_the_session_stops_cleanly_and_reports_how_quiet_it_is():
    clock = Clock(100.0)
    session = FakeSession()
    call = make_call(session, clock=clock, name="Alex").start()
    assert wait_for(lambda: session.fed > 2) and call.alive()
    clock.advance(200)
    assert call.idle_s() >= 199
    session.turns.append(object())                              # someone spoke
    assert call.idle_s() == 0
    call.stop()
    assert session.stopped and not call.alive()


def test_speak_refuses_while_she_is_talking_with_someone_and_speaks_otherwise():
    session = FakeSession()
    voice = voicelink.HomeVoice(call_factory=lambda friend: make_call(session, name=friend["name"]))
    voice.start_call({"name": "Alex"})
    session._busy = True
    assert voice.speak("nice jump!") is False and session.tts.said == []
    session._busy = False
    session.state = "user_speaking"
    assert voice.speak("nice jump!") is False
    session.state = "listening"
    assert voice.speak("nice jump! 😀") is True
    assert wait_for(lambda: session.tts.said) and session.tts.said[0] == "nice jump!"
    assert session.speaker.played
    voice.end_call()
    assert not voice.in_call()


def test_without_a_voice_stack_she_stays_silent_and_keeps_playing():
    voice = voicelink.HomeVoice()
    assert voice.speak("hi") is False
    with pytest.raises(RuntimeError, match="voice stack"):
        voice.start_call({"name": "Alex"})


def test_a_fresh_moment_window_per_game_reaches_the_call_before_or_after_it_starts():
    session = FakeSession()
    voice = voicelink.HomeVoice(call_factory=lambda friend: make_call(session))
    early = voice.window_for("minecraft")                       # playing first, the call comes later
    voice.start_call({"name": "Alex"})
    assert session.game_events is early and session.config.game_context_for_voice
    late = voice.window_for("roblox obby")                      # a new game while the call runs
    assert session.game_events is late and late is not early
    voice.end_call()


# ---- 10. Discord calls ------------------------------------------------------------------------------------------------
class Screen:
    """Scripted screen reads for DiscordCalls."""

    def __init__(self, *states):
        self.states = list(states)
        self.last = {}

    def __call__(self, png):
        self.last = self.states.pop(0) if self.states else self.last
        return self.last


def make_calls(tmp_path, backend, screen, *, standing=CLOSE, voice=None, locator=None, config=None, memory=None):
    executor = Executor(tmp_path / "home", backend)
    host = HostAdapter(executor)
    mem = memory or FriendMemory(tmp_path / "f.sqlite3")
    voice = voice or voicelink.HomeVoice(call_factory=lambda friend: make_call(name=friend["name"], person=friend["person"]))
    spots = []
    locate = locator or (lambda png, what: spots.append(what) or (120, 80))
    situation = Situation()
    c = calls.DiscordCalls(host, mem, voice, lambda platform, name: standing, reader=screen, locator=locate,
                           config=config, sleep=lambda s: None, clock=Clock(), say_goodbye=voice.speak, situation=situation)
    return c, voice, spots, situation


def test_she_answers_a_friends_ring_with_the_shortcut_and_starts_the_voice(tmp_path):
    backend = FakeBackend()
    screen = Screen({"incoming_call": True, "caller": "Alex"}, {"in_voice_call": True})
    c, voice, spots, situation = make_calls(tmp_path, backend, screen)
    out = c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))
    assert out["ok"] and voice.in_call() and situation.in_call
    assert ("ctrl+enter",) in backend.of("key") and spots == []         # the shortcut worked: no click needed
    voice.end_call()


def test_she_never_answers_strangers_wrong_callers_or_calls_that_stopped_ringing(tmp_path):
    for standing, state, why in ((MET, {"incoming_call": True, "caller": "Alex"}, "not a friend"),
                                 (CLOSE, {"incoming_call": True, "caller": "Someone Else"}, "not answered"),
                                 (CLOSE, {"incoming_call": False}, "no longer ringing")):
        backend = FakeBackend()
        c, voice, spots, _ = make_calls(tmp_path, backend, Screen(state), standing=standing)
        out = c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))
        assert not out["ok"] and why in out["summary"] and not voice.in_call()
        assert ("ctrl+enter",) not in backend.of("key")


def test_if_the_shortcut_does_nothing_she_clicks_accept_and_claims_nothing_the_screen_did_not_show(tmp_path):
    backend = FakeBackend()
    c, voice, spots, _ = make_calls(tmp_path, backend, Screen({"incoming_call": True, "caller": "Alex"}, {}, {"in_voice_call": True}))
    assert c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))["ok"] and "Accept" in spots[0]
    voice.end_call()
    backend = FakeBackend()
    c, voice, spots, _ = make_calls(tmp_path, backend, Screen({"incoming_call": True, "caller": "Alex"}, {}, {}))
    out = c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))
    assert not out["ok"] and "does not show" in out["summary"] and not voice.in_call()


def test_she_places_a_call_in_the_dm_and_waits_for_the_pickup(tmp_path):
    backend = FakeBackend()
    screen = Screen({"dm_with": "Alex"}, {"calling_out": True}, {"in_voice_call": True, "other_joined": True})
    c, voice, spots, situation = make_calls(tmp_path, backend, screen)
    out = c.callout(Incoming("callout", "discord", "Alex", "call", at=NOW))
    assert out["ok"] and voice.in_call() and situation.in_call
    keys = backend.of("key")
    assert keys[0] == ("ctrl+k",) and ("type", "Alex") in [("type", t[0]) for t in backend.of("type")]
    assert "Start Voice Call" in spots[0]
    assert backend.of("click") == [(120, 80)]
    voice.end_call()


def test_a_call_nobody_picks_up_is_cancelled(tmp_path):
    backend = FakeBackend()
    clock = Clock()
    screen = Screen({"dm_with": "Alex"}, {"calling_out": True})
    c, voice, spots, _ = make_calls(tmp_path, backend, screen)
    c._clock = clock
    c._sleep = lambda s: clock.advance(s + 10)                        # time passes while it rings
    out = c.callout(Incoming("callout", "discord", "Alex", "call", at=NOW))
    assert not out["ok"] and "did not pick up" in out["summary"] and not voice.in_call()
    assert "Disconnect" in spots[-1]


def test_she_does_not_call_strangers_or_the_wrong_conversation(tmp_path):
    c, voice, spots, _ = make_calls(tmp_path, FakeBackend(), Screen({"dm_with": "Alex"}), standing=MET)
    assert "not a friend" in c.callout(Incoming("callout", "discord", "Alex", "call", at=NOW))["summary"]
    backend = FakeBackend()
    c, voice, spots, _ = make_calls(tmp_path, backend, Screen({"dm_with": "Somebody"}))
    out = c.callout(Incoming("callout", "discord", "Alex", "call", at=NOW))
    assert not out["ok"] and spots == [] and backend.of("click") == []


def test_she_says_goodbye_before_hanging_up_and_leaves_when_the_friend_goes_quiet(tmp_path):
    backend = FakeBackend()
    session = FakeSession()
    voice = voicelink.HomeVoice(call_factory=lambda friend: make_call(session, name="Alex", clock=clock))
    clock = Clock(1000.0)
    c, voice, spots, situation = make_calls(tmp_path, backend, Screen({"incoming_call": True, "caller": "Alex"}, {"in_voice_call": True}),
                                            voice=voice, config={"call_idle_leave_minutes": 3})
    assert c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))["ok"]
    inbox = Inbox(model(), lambda i: CLOSE, situation, clock=Clock())
    c.tick(inbox)
    assert inbox.waiting() == []                                      # not quiet yet
    clock.advance(200)                                                # three minutes of nobody talking
    c.tick(inbox)
    c.tick(inbox)                                                     # asked once, not twice
    assert [p.incoming.kind for p in inbox.waiting()] == ["hangup"]
    out = c.hangup()
    assert out["ok"] and session.tts.said == [calls.FRIEND_LEAVE_LINE] and not voice.in_call() and not situation.in_call
    assert any("Disconnect" in s for s in spots)


def test_an_invited_game_becomes_the_requested_activity():
    clock = Clock()
    inbox = Inbox(model(), lambda i: CLOSE, Situation(), clock=clock)
    att = Attention(inbox, inbox.situation, clock=clock)
    c = calls.DiscordCalls(None, None, types.SimpleNamespace(speak=lambda t: True), lambda p, n: CLOSE,
                           reader=lambda p: {}, locator=lambda p, w: None)
    registry = activities.Registry()
    rt = types.SimpleNamespace(attention=att, calls=c)
    handler = lambda incoming, ctx: (c.start_game(incoming, ctx), att.request(incoming.text))[0]      # noqa: E731
    assert handler(Incoming("startgame", "discord", "Alex", "minecraft", at=NOW), None)["activity"] == "minecraft"
    assert att.take_request() == "minecraft" and att.take_request() == ""
    del registry, rt


# ---- 11. the host agent -----------------------------------------------------------------------------------------------
def test_executor_can_focus_windows_hold_keys_and_press_slash(home):
    backend = FakeBackend()
    ex = Executor(home, backend)
    host = HostAdapter(ex)
    assert host.focus_window("Discord") and host.foreground_title() == "Discord"
    assert not host.focus_window("Nothing Here")
    host.hold("w", 0.5)
    host.key("/")
    host.key("alt+shift+down")
    host.open_uri("roblox://experiences/start?placeId=1")
    assert backend.of("hold") == [("w",)] and ("/",) in backend.of("key")
    assert ex.do("hold", {"key": "ctrl+alt"}).ok is False and ex.do("hold", {"key": "w", "seconds": 99}).ok
    control.stop(home)
    assert not host.focus_window("Discord")                           # the owner's stop applies to every new action


def test_the_host_adapter_in_a_dry_run_remembers_the_focused_window(home):
    ex = Executor(home, FakeBackend(), dry_run=True)
    host = HostAdapter(ex)
    assert host.focus_window("Discord") and host.foreground_title() == "Discord"


# ---- 12. star.watch ---------------------------------------------------------------------------------------------------
def test_star_watch_is_wired_to_her_voice_her_interest_list_and_the_interrupt(home, monkeypatch):
    seen = {}
    parts = types.SimpleNamespace(sleep=lambda s: seen.setdefault("slept", s), speak=None, chat=None)

    def configure(**kw):
        for key, value in kw.items():
            setattr(parts, key, value)
        return parts

    browser = types.ModuleType("star.watch.browser")

    class BrowserError(Exception):
        pass
    browser.BrowserError = BrowserError
    watch = types.ModuleType("star.watch")
    watch.configure = configure
    watch.ensure_interest = lambda life: life.set_interest("watch_videos", 1.0, "watch videos")

    def inner(ctx):
        try:
            parts.sleep(30)                                           # the watcher waiting inside a video
        except BrowserError:
            return {"ok": False, "verified": False, "summary": "the browser step failed: a friend needs her"}
        return {"ok": True, "verified": True, "summary": "watched", "evidence": ["x"]}
    watch.register_home_activities = lambda registry: registry.register("watch_videos", "watch_videos", inner, "watch")
    monkeypatch.setitem(sys.modules, "star.watch", watch)
    monkeypatch.setitem(sys.modules, "star.watch.browser", browser)
    life = Life(home)
    backend = FakeBackend()
    registry, rt = runtime.build(home, {}, Executor(home, backend), life, None, plugins=("star.watch",), memory=None,
                                 emotion=None, social_settings={"discord": {"enabled": False}, "roblox": {}, "minecraft": {}})
    assert "watch_videos" in life.interests()                         # added for installs that predate it
    assert parts.speak == rt.voice.speak
    ctx = activities.Context(home=home, config={}, executor=rt.executor, life=life, chat=None, interest="watch_videos",
                             goal=None, interrupt=rt.interrupt, situation=rt.situation)
    run = registry.items["watch_videos"].run
    rt.interrupt.set("friend")
    out = run(ctx)
    assert out["paused"] is True and ("key", "k") in backend.calls    # the video is paused before she looks away
    rt.interrupt.clear()
    parts.sleep = lambda s: None
    assert run(ctx)["ok"] is True and parts.sleep is not None


# ---- 13. the first live test, end to end on fakes ---------------------------------------------------------------------
class FakeClockSleep:
    """Monotonic time for the play loops: sleeping moves it, so a twelve-minute session takes no real time."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class FakeTransport:
    def __init__(self, server):
        self.sent, self.events = [], [{"type": "spawn", "players": 2}]

    def send(self, command):
        self.sent.append(command)

    def poll(self):
        out, self.events = self.events, []
        return out

    def close(self):
        self.closed = True


class FakeGameSession:
    def __init__(self, kind, **kw):
        self.kind, self.kw, self.started, self.stopped = kind, kw, False, False
        self.fast = types.SimpleNamespace(on_moment=[])

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def report(self):
        return {"ticks": 7}


class FakeCallBrain:
    def __init__(self):
        self.seen = []

    def stream(self, messages):
        self.seen.append(messages)
        return iter(["ok!"])


def test_owner_dm_to_call_to_minecraft_end_to_end(home, tmp_path, memory):
    clock = Clock(LOCAL_NOON)
    mono = FakeClockSleep()
    backend = FakeBackend()
    executor = Executor(home, backend)
    life = Life(home, rng=random.Random(5))
    for name in list(life.interests()):
        life.set_interest(name, 0.1)
    sessions, game_sessions, call_brain = [], [], FakeCallBrain()

    # the Discord screen: her owner's unread DM; the call screens in the order the app shows them
    dm_view = {"channel": "Owner", "is_dm": True, "cannot_message": False,
               "messages": [{"author": "Owner", "text": "hey star, wanna call?"}]}
    screen = Screen({"dm_with": "Owner"}, {"calling_out": True}, {"in_voice_call": True, "other_joined": True})

    def make_session(friend):
        session = FakeSession()
        sessions.append(session)
        call = make_call(session, name=friend["name"], person=friend["person"])
        session.brain = invites.InviteBrain(call_brain, rt.desk, sender=lambda: rt.calls.friend)
        return call

    replies = Model(lambda system, user: "ok sure!" if "you decided yes" in user else "hm")
    config = {"close_friends": {"discord": ["Owner"]}, "pause_minutes": 0, "my_names": ["Star"], **FLAT,
              "play": {"session_minutes": 12, "step_s": 3.0, "load_wait_s": 0}}
    settings = {"my_names": ["Star"], "discord": {"enabled": True, "window_title": "Discord"},
                "roblox": {"enabled": False, "experiences": []},
                "minecraft": {"enabled": True, "servers": [{"name": "home", "host": "localhost", "allows_bots": True}]}}
    from star.social.activity import HumanPace
    registry, rt = runtime.build(
        home, config, executor, life, None, plugins=("star.social", "star.play", "star.senses"),
        memory=memory, social_chat=SocialChat(memory, complete=replies, emotion=None, clock=clock), clock=clock,
        rng=random.Random(7), emotion=FakeEmotion(on=False), social_settings=settings,
        voice=voicelink.HomeVoice(call_factory=make_session),
        discord_kwargs={"reader": lambda png: dm_view, "pace": HumanPace(sleep=lambda s: None)},
        call_kwargs={"reader": screen, "locator": lambda png, what: (120, 80), "sleep": lambda s: None},
        hooks={"sleep": mono.sleep, "clock": mono.now, "node_transport": FakeTransport,
               "minecraft_session": lambda transport, **kw: game_sessions.append(FakeGameSession("minecraft", **kw)) or game_sessions[-1],
               "planner_brain": lambda: None})
    assert {"discord", "minecraft"} <= set(registry.items)
    assert {"discord:message", "discord:call", "discord:callout", "discord:hangup", "discord:startgame"} <= set(registry.handlers)

    # (1)+(2) the owner's DM arrives as a notification; she is idle, he is a close friend: she gets to it in seconds
    source = types.SimpleNamespace(toasts=[], poll=lambda: list(source.toasts))
    watcher = notifications.NotificationWatcher(source, rt.inbox, clock=clock)
    watcher.tick()
    source.toasts.append(toast("Discord", "Owner", "hey star, wanna call?", ident="42", at=clock()))
    assert [i.kind for i in watcher.tick()] == ["dm"]
    assert rt.attention.watch_tick() is False                           # not yet: she answers like a person, not instantly
    clock.advance(20)
    assert rt.attention.watch_tick() is True and rt.interrupt.is_set()  # due: whatever she is doing would stop now

    # (2)+(3) she decides (yes), words it in her own voice, replies in the DM, and plans to call him
    out = loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)
    assert out["state"] == "served" and out["served"][0]["ok"]
    system, user = replies.calls[-1]
    assert "you decided yes to 'call'" in user and "you decided" not in system        # the decision is hers; the model only words it
    assert ("type", "ok sure!") in [("type", "".join(t[0] for t in backend.of("type")))]
    assert ("enter",) in backend.of("key")
    assert [p.incoming.kind for p in rt.inbox.waiting()] == ["callout"]

    # (3)+(4) the planned call: she clicks the call button herself, waits for the pickup, and the voice session starts
    clock.advance(5)
    rt.attention.watch_tick()
    out = loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)
    assert out["served"][0]["route"] == "discord:callout" and out["served"][0]["ok"], out
    assert rt.voice.in_call() and rt.situation.in_call and len(sessions) == 1
    assert backend.of("click") == [(120, 80)]
    assert wait_for(lambda: sessions[0].fed > 0)                        # the PC's sound is being fed to the call session

    # (5) in the call he asks about Minecraft: same decision, spoken answer follows it, then the activity switches
    sessions[0].brain.stream([{"role": "system", "content": "voice"}, {"role": "user", "content": "do you wanna play minecraft?"}])
    sent = call_brain.seen[-1][-1]["content"]
    assert "you decided yes to 'play Minecraft'" in sent and "stay in the call" in sent
    clock.advance(5)
    rt.attention.watch_tick()
    out = loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)
    assert out["served"][0]["route"] == "discord:startgame" and rt.attention.requested == "minecraft"
    out = loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)
    assert out["state"] == "worked" and out["activity"] == "minecraft"
    game = game_sessions[0]
    assert game.started and game.stopped
    assert game.kw["voice_window"] is rt.voice.window and game.kw["speak"] == rt.voice.speak
    assert sessions[0].game_events is rt.voice.window and sessions[0].config.game_context_for_voice   # the call knows the game
    assert rt.voice.in_call()                                           # she is still in the call, and talking
    assert life.history()[-1]["activity"] == "minecraft" and life.history()[-1]["minutes"] >= 12
    rt.voice.end_call()


def test_the_emotion_engines_invite_bias_is_used_when_it_exists(monkeypatch):
    from star import emotion
    seen = []
    monkeypatch.setattr(emotion, "invite_bias", lambda mood, kind: seen.append((mood, kind)) or (-0.35, "needs a moment"),
                        raising=False)
    answer = decide(CALL, mind(standing=FRIEND, now=LOCAL_NOON, mood={"emotions": {}}))
    assert seen == [({"emotions": {}}, "call")]
    assert ("her mood: needs a moment", -0.35) in answer.factors and answer.say in ("later", "no")
    assert "needs a moment" in answer.reason or answer.say == "later"
    monkeypatch.setattr(emotion, "invite_bias", lambda mood, kind: (0.2, "lonely, wants company"), raising=False)
    lifted = decide(PLAY, mind(standing=FRIEND, now=LOCAL_NOON, mood={"emotions": {}}, played_today_min=200))
    assert ("her mood: lonely, wants company", 0.2) in lifted.factors


# ---- 14. emotion events from the wiring -------------------------------------------------------------------------------
def test_the_wiring_reports_what_it_sees_to_the_emotion_engine_without_ever_breaking(home, memory, monkeypatch):
    from star import emotion
    seen = []
    monkeypatch.setattr(emotion, "on_event", lambda kind, **kw: seen.append((kind, kw)))
    rt = runtime.Runtime(home, {}, Executor(home, FakeBackend()), Life(home), memory=memory, emotion=None)
    rt.feel("friend_ignored", "discord", "Alex")
    assert seen[0][0] == "friend_ignored" and seen[0][1]["person"].startswith("friend-") and seen[0][1]["only_if_enabled"]
    monkeypatch.setattr(emotion, "on_event", lambda kind, **kw: (_ for _ in ()).throw(ValueError("unknown event")))
    rt.feel("something_new", "discord", "Alex")                          # a missing event kind is not an error


def test_calls_report_a_call_nobody_picked_up_and_a_conversation_that_ended(tmp_path):
    felt = []
    backend = FakeBackend()
    clock = Clock()
    c, voice, spots, _ = make_calls(tmp_path, backend, Screen({"dm_with": "Alex"}, {"calling_out": True}))
    c._feel = lambda kind, name: felt.append((kind, name))
    c._clock, c._sleep = clock, lambda s: clock.advance(s + 10)
    c.callout(Incoming("callout", "discord", "Alex", "call", at=NOW))
    assert felt == [("friend_ignored", "Alex")]
    felt.clear()
    c2, voice2, _, _ = make_calls(tmp_path, FakeBackend(), Screen({"incoming_call": True, "caller": "Alex"}, {"in_voice_call": True}))
    c2._feel = lambda kind, name: felt.append((kind, name))
    assert c2.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))["ok"]
    c2._sleep = lambda s: None
    c2.hangup()
    assert felt == [("talked_to_friend", "Alex")]


def test_a_break_between_sessions_is_reported_once(home, monkeypatch):
    from star import emotion
    seen = []
    monkeypatch.setattr(emotion, "on_event", lambda kind, **kw: seen.append(kind))
    registry, life, executor = _simple_home(home, {"ok": True, "verified": True, "summary": "ok", "evidence": ["x"]})
    rt = runtime.Runtime(home, {}, executor, life, emotion=None)
    config = {"pause_minutes": 30}
    assert loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)["state"] == "worked"
    seen.clear()
    assert loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)["state"] == "waiting"
    assert loop.cycle(home, config, registry, life, executor, None, attention=rt.attention)["state"] == "waiting"
    assert seen == ["took_a_break"]


# ---- 15. STAR Camera ---------------------------------------------------------------------------------------------------
def test_star_vtuber_is_a_plugin_and_her_speaker_is_wrapped_for_lip_sync(monkeypatch):
    from star.home import voicestack
    assert "star.vtuber" in activities.PLUGIN_MODULES
    vtuber = types.ModuleType("star.vtuber")
    vtuber.attach_speaker = lambda speaker: ("lipsync", speaker)
    monkeypatch.setitem(sys.modules, "star.vtuber", vtuber)
    assert voicestack.attach_lipsync("speaker") == ("lipsync", "speaker")
    vtuber.attach_speaker = lambda speaker: (_ for _ in ()).throw(RuntimeError("camera broken"))
    assert voicestack.attach_lipsync("speaker") == "speaker"               # a broken camera never silences her
    monkeypatch.setitem(sys.modules, "star.vtuber", None)                   # not installed
    assert voicestack.attach_lipsync("speaker") == "speaker"


def _camera_runtime(home, memory, config, registry_items=True):
    ran = []
    registry = activities.Registry()
    if registry_items:
        registry.register("camera on", "video_call", lambda ctx: ran.append(ctx.interest) or {"ok": True, "summary": "camera on"})
    rt = runtime.Runtime(home, config, Executor(home, FakeBackend()), Life(home), memory=memory, emotion=None)
    rt.registry = registry
    return rt, ran


def test_she_turns_the_camera_on_in_a_call_only_when_she_feels_like_it(home, memory, monkeypatch):
    from star import emotion
    monkeypatch.setattr(emotion, "enabled", lambda *a, **k: True)
    rt, ran = _camera_runtime(home, memory, {"close_friends": {"discord": ["Owner"]}})
    monkeypatch.setattr(emotion, "current", lambda *a, **k: {"valence": 0.3, "drives": {"needs_rest": 0.1}})
    assert rt.call_connected("Owner")["ok"] and ran == ["video_call"]
    ran.clear()
    assert rt.call_connected("Somebody Else") is None and ran == []                # not a close friend
    monkeypatch.setattr(emotion, "current", lambda *a, **k: {"valence": 0.3, "drives": {"needs_rest": 0.9}})
    assert rt.call_connected("Owner") is None and ran == []                        # worn out: voice only
    monkeypatch.setattr(emotion, "current", lambda *a, **k: {"valence": -0.4, "drives": {}})
    assert rt.call_connected("Owner") is None
    rt.config["calls"] = {"camera": "always"}
    assert rt.call_connected("Somebody Else")["ok"]
    rt.config["calls"] = {"camera": "never"}
    ran.clear()
    assert rt.call_connected("Owner") is None and ran == []
    bare, ran2 = _camera_runtime(home, memory, {"close_friends": {"discord": ["Owner"]}}, registry_items=False)
    assert bare.call_connected("Owner") is None                                    # star.vtuber is not installed


def test_a_camera_that_fails_never_ends_the_call(tmp_path):
    backend = FakeBackend()
    c, voice, spots, _ = make_calls(tmp_path, backend, Screen({"incoming_call": True, "caller": "Alex"}, {"in_voice_call": True}))
    c._on_connected = lambda name: (_ for _ in ()).throw(RuntimeError("no virtual camera"))
    assert c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))["ok"] and voice.in_call()
    voice.end_call()


# ---- 14. home gaps: adult persona text, left_out / friend_left / reunion, the watch hearing hub -----------------------------
ROMANCE_MARK = "You may flirt"          # the only wording in the system text that permits romance


def _system_after(memory, platform, handle, *lines):
    model = Model()
    chat = SocialChat(memory, complete=model, emotion=None, clock=Clock())
    for line in lines:
        chat.handle(platform, handle, line)
    return model.calls[-1][0]


def test_only_a_verified_adult_off_roblox_gets_the_romance_permitting_system_text(memory):
    adult = _system_after(memory, "discord", "noor", "hi", "I'm 27 years old", "hey again")
    assert ROMANCE_MARK in adult
    assert adult == _system_after(memory, "discord", "noor", "still here")                 # byte-identical for the same mode
    assert ROMANCE_MARK in _system_after(memory, "minecraft", "mc", "I'm 31 years old", "hello")   # allowed there too
    for platform, handle, lines in (("discord", "unknown", ("hi", "what's up")),
                                    ("discord", "kid", ("hi", "I'm 15", "hey")),
                                    ("discord", "doubt", ("I'm 19", "my mom says I have to do my homework", "hey")),
                                    ("roblox", "rbx", ("hi", "I'm 30 years old", "hey"))):
        assert ROMANCE_MARK not in _system_after(memory, platform, handle, *lines), handle
    assert "Never romantic or sexual" in _system_after(memory, "discord", "kid", "ok")


def test_a_casual_goodbye_from_a_friend_is_a_mild_friend_left_but_not_from_a_stranger(memory):
    emotion = FakeEmotion()
    chat = SocialChat(memory, complete=Model(), emotion=emotion, clock=Clock())
    chat.handle("discord", "Mira", "hello")
    memory.update(memory.person("discord", "Mira"), relationship="friend")
    chat.handle("discord", "Mira", "ok gtg, bye!")
    left = [kw for kind, kw in emotion.events if kind == "friend_left"]
    assert len(left) == 1 and left[0]["strength"] == 0.35 and left[0]["person"].startswith("friend-")
    emotion.events.clear()
    chat.handle("discord", "Stranger", "gtg bye")                                           # a person she just met
    chat.handle("discord", "Mira", "what game next?")
    assert [k for k, _ in emotion.events if k == "friend_left"] == []


def test_a_friend_who_messages_after_days_is_a_reunion_once(tmp_path):
    clock = Clock()
    mem = FriendMemory(tmp_path / "reunion.sqlite3", clock=clock)
    emotion = FakeEmotion()
    chat = SocialChat(mem, complete=Model(), emotion=emotion, clock=clock)
    try:
        chat.handle("discord", "Mira", "hello")                                             # first ever message
        mem.update(mem.person("discord", "Mira"), relationship="friend")
        chat.handle("discord", "Mira", "hello again")                                       # same hour: no reunion
        chat.handle("discord", "Stranger", "hi")
        clock.advance(5 * 86400)
        chat.handle("discord", "Stranger", "hi, it is me again")                            # met, not a friend
        assert [k for k, _ in emotion.events if k == "reunion"] == []
        chat.handle("discord", "Mira", "I am back!")
        chat.handle("discord", "Mira", "did you miss me")
        reunions = [kw for kind, kw in emotion.events if kind == "reunion"]
        assert len(reunions) == 1 and reunions[0]["person"].startswith("friend-") and 0.5 < reunions[0]["strength"] <= 1.0
        assert "Mira" not in reunions[0]["detail"] and "5 days" in reunions[0]["detail"]
    finally:
        mem.close()


def test_a_broken_emotion_engine_never_breaks_a_reply_that_has_a_reunion_or_goodbye(tmp_path):
    clock = Clock()
    mem = FriendMemory(tmp_path / "broken.sqlite3", clock=clock)

    class Broken(FakeEmotion):
        def on_event(self, kind, **kw):
            raise RuntimeError("engine down")

    try:
        chat = SocialChat(mem, complete=Model("hi!"), emotion=Broken(), clock=clock)
        chat.handle("discord", "Mira", "hello")
        mem.update(mem.person("discord", "Mira"), relationship="friend")
        clock.advance(4 * 86400)
        assert chat.handle("discord", "Mira", "back, but gtg bye").text == "hi!"
    finally:
        mem.close()


def test_left_out_watch_needs_several_unaddressed_messages_from_two_people_and_then_rests():
    clock = Clock()
    watch = attention.LeftOutWatch(clock=clock)
    assert not watch.note("#general", ["a", "b", "a"])
    assert not watch.note("#general", ["a", "a"])                    # five messages
    assert watch.note("#general", ["b"]) is True                     # six, two voices
    assert not watch.note("#general", ["a", "b"] * 5)                # rests for the cooldown
    clock.advance(3601)
    assert watch.note("#general", ["a", "b"] * 3) is True
    solo = attention.LeftOutWatch(clock=clock)
    assert not solo.note("#solo", ["a"] * 9)                         # one voice talking is not people leaving her out
    assert not watch.note("#other", ["a", "b", "a", "b", "a"]) and watch.note("#other", ["b"])
    watch.note("#other", ["a", "b", "a", "b"])
    watch.note("#other", [], addressed=True)                        # someone talked to her: the pile is gone
    assert not watch.note("#other", ["a", "b"])
    clock.advance(3 * 3600)                                          # a new conversation hours later
    assert not watch.note("#other", ["a", "b"]) and not watch.note("#other", ["a", "b"])


def _channel_view(authors, start=0, mention=False):
    messages = [{"author": a, "text": f"line {start + i} about the game"} for i, a in enumerate(authors)]
    if mention:
        messages.append({"author": authors[0], "text": "hey @Star come look", "mentions_me": True})
    return {"channel": "#general", "is_dm": False, "messages": messages}


def test_friends_chatting_in_a_server_channel_without_her_make_her_feel_left_out(home, memory):
    from star.social.discord_desktop import DiscordDesktop
    for name in ("Ann", "Bo"):
        memory.update(memory.person("discord", name, name), relationship="friend")
    emotion = FakeEmotion()
    chat = SocialChat(memory, complete=Model(), emotion=emotion, clock=Clock())
    view = {}
    host = HostAdapter(Executor(home, FakeBackend()))
    desk = DiscordDesktop(host, chat, reader=lambda png: view, left_out=attention.LeftOutWatch(clock=Clock()))
    view.update(_channel_view(["Ann", "Bo", "Ann"]))
    assert not desk.step().acted and emotion.events == []
    view.update(_channel_view(["Bo", "Ann", "Bo", "Ann", "Bo"], start=10))
    desk.step()
    assert [(k, kw["person"].startswith("friend-")) for k, kw in emotion.events] == [("left_out", True)]
    desk.step()                                                      # the same messages again: nothing new
    assert len(emotion.events) == 1
    view.update(_channel_view(["Ann", "Bo"], start=20, mention=True))
    desk.step()                                                      # she was spoken to: no new feeling from that read
    assert len(emotion.events) == 1


def test_strangers_chatting_do_not_hurt_and_leave_no_record(home, memory):
    from star.social.discord_desktop import DiscordDesktop
    emotion = FakeEmotion()
    chat = SocialChat(memory, complete=Model(), emotion=emotion, clock=Clock())
    view = _channel_view(["Zed", "Yan"] * 4)
    desk = DiscordDesktop(HostAdapter(Executor(home, FakeBackend())), chat, reader=lambda png: view,
                          left_out=attention.LeftOutWatch(clock=Clock()))
    desk.step()
    assert emotion.events == [] and memory.known("discord", "Zed") is None and memory.known("discord", "Yan") is None
    bare = DiscordDesktop(HostAdapter(Executor(home, FakeBackend())), chat, reader=lambda png: view)
    assert not bare.step().acted and emotion.events == []            # no watch plugged in: the old behaviour


def test_a_friend_saying_goodbye_in_the_call_is_felt_once_and_the_call_goes_on(tmp_path):
    backend = FakeBackend()
    c, voice, spots, _ = make_calls(tmp_path, backend, Screen({"incoming_call": True, "caller": "Alex"}, {"in_voice_call": True}))
    felt = []
    c._feel = lambda kind, name, **payload: felt.append((kind, name, payload.get("strength")))
    inbox = types.SimpleNamespace(add=lambda incoming: None)
    assert c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))["ok"]
    session = voice.call.session
    c.tick(inbox)                                                     # a session with no history: nothing happens
    session.history = [{"role": "user", "content": "this game is fun"}, {"role": "assistant", "content": "yes!"}]
    c.tick(inbox)
    assert felt == []
    session.history += [{"role": "assistant", "content": "bye bye bye"},                  # her own words do not count
                        {"role": "user", "content": "ok I gotta go now, bye!"}]
    c.tick(inbox)
    c.tick(inbox)
    session.history.append({"role": "user", "content": "bye again"})
    c.tick(inbox)
    assert felt == [("friend_left", "Alex", 0.35)] and voice.in_call()
    voice.end_call()


def test_a_session_that_trimmed_its_history_does_not_crash_the_goodbye_watch(tmp_path):
    c, voice, spots, _ = make_calls(tmp_path, FakeBackend(), Screen({"incoming_call": True, "caller": "Alex"}, {"in_voice_call": True}))
    c._feel = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine down"))
    inbox = types.SimpleNamespace(add=lambda incoming: None)
    c.answer(Incoming("call", "discord", "Alex", at=NOW, ring_s=45))
    session = voice.call.session
    session.history = [{"role": "user", "content": "hello"}] * 6
    c.tick(inbox)
    session.history = [{"role": "user", "content": "see you later"}]                        # shorter than before
    c.tick(inbox)                                                                          # engine failure is swallowed
    assert voice.in_call()
    voice.end_call()


def test_the_runtime_gives_the_discord_app_a_left_out_watch_and_calls_pass_a_strength(home, memory):
    rt = runtime.Runtime(home, {}, Executor(home, FakeBackend()), Life(home), memory=memory, emotion=None,
                         social_settings={"discord": {"enabled": True}, "roblox": {}, "minecraft": {}})
    assert isinstance(rt.discord.left_out, attention.LeftOutWatch)
    seen = []
    rt.feel = lambda kind, platform, sender, **payload: seen.append((kind, platform, sender, payload))
    rt.calls._feel("friend_left", "Alex", strength=0.35)
    assert seen == [("friend_left", "discord", "Alex", {"strength": 0.35})]


def _watch_module(monkeypatch):
    parts = types.SimpleNamespace(sleep=lambda s: None, speak=None, chat=None, hub=None)

    def configure(**kw):
        for key, value in kw.items():
            setattr(parts, key, value)
        return parts

    browser = types.ModuleType("star.watch.browser")
    browser.BrowserError = type("BrowserError", (Exception,), {})
    watch = types.ModuleType("star.watch")
    watch.configure = configure
    watch.ensure_interest = lambda life: life.set_interest("watch_videos", 1.0, "watch videos")
    seen = []
    watch.register_home_activities = lambda registry: registry.register(
        "watch_videos", "watch_videos",
        lambda ctx: seen.append(parts.hub) or {"ok": True, "verified": True, "summary": "w", "evidence": ["x"]}, "watch")
    monkeypatch.setitem(sys.modules, "star.watch", watch)
    monkeypatch.setitem(sys.modules, "star.watch.browser", browser)
    return parts, seen


def _watch_run(home, hooks):
    life = Life(home)
    registry, rt = runtime.build(home, {}, Executor(home, FakeBackend()), life, None, plugins=("star.watch",), memory=None,
                                 emotion=None, hooks=hooks,
                                 social_settings={"discord": {"enabled": False}, "roblox": {}, "minecraft": {}})
    ctx = activities.Context(home=home, config={}, executor=rt.executor, life=life, chat=None, interest="watch_videos",
                             goal=None, interrupt=rt.interrupt, situation=rt.situation)
    return registry.items["watch_videos"].run(ctx)


def test_star_watch_gets_the_hearing_hub_when_it_can_start_and_keeps_going_without_it(home, monkeypatch):
    parts, seen = _watch_module(monkeypatch)
    hub = object()
    assert _watch_run(home, {"hearing_hub": lambda: hub})["ok"] and seen == [hub]       # hearing it is, while she watches

    def cannot_start():
        raise RuntimeError("no sound card")
    seen[:] = []
    assert _watch_run(home, {"hearing_hub": cannot_start})["ok"] and seen == [None]     # captions and picture, no crash
    seen[:] = []
    assert _watch_run(home, {"hearing_hub": lambda: None})["ok"] and seen == [None]
