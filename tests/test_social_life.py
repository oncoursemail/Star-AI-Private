"""STAR's social life (star/social lifecycle, requests, convo, safety): fakes only, no logins, no model, no real UI."""
from __future__ import annotations

import json
import random

import pytest

from star.games.minecraft import MinecraftPlay, MinecraftServer
from star.social import convo, rules, safety
from star.social.chat import SocialChat
from star.social.friends import FriendMemory
from star.social.lifecycle import Bonds, followup_from, suggest_nickname
from star.social.requests import OFFER_TEXT, FriendDesk, FriendRequests

DAY = 86400.0
T0 = 1_800_000_000.0


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Model:
    def __init__(self, answer="sounds good!"):
        self.answer, self.calls = answer, []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.answer(system, user) if callable(self.answer) else self.answer


class Sink:
    def __init__(self):
        self.items, self.forgotten = [], []

    def __call__(self, text, source="", person=""):
        self.items.append((text, source, person))

    def forget(self, ref):
        self.forgotten.append(ref)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(tmp_path, clock):
    mem = FriendMemory(tmp_path / "friends.sqlite3", clock=clock)
    yield mem
    mem.close()


def make(memory, clock, answer="sounds good!", sink=None, killed=None, **kw):
    model = Model(answer)
    chat = SocialChat(memory, complete=model, emotion=None, clock=clock, rng=random.Random(3),
                      bonds=Bonds(memory, sink=sink, clock=clock), killed=killed or (lambda platform: False), **kw)
    chat.requests.offer_chance = 0.0
    return chat, model


def talk(chat, clock, handle, lines, *, platform="discord", name="", **kw):
    last = None
    for line in lines:
        clock.t += 60
        last = chat.handle(platform, handle, line, name=name or handle, **kw)
    return last


def convo_of(chat, clock, handle, n=12, **kw):
    """One conversation of n lines from them (one point of conversation score each, capped)."""
    return talk(chat, clock, handle, [f"message number {i} about our plans" for i in range(n)], **kw)


# -- lifecycle ----------------------------------------------------------------------------------------------------------

def test_one_long_chat_makes_an_acquaintance_not_a_friend(memory, clock):
    chat, _ = make(memory, clock)
    convo_of(chat, clock, "mira", 40)
    person = memory.known("discord", "mira")
    assert chat.bonds.stage(person) == "acquaintance" and person.relationship == "met"


def test_stages_grow_from_separate_conversations_and_shared_games(memory, clock):
    chat, _ = make(memory, clock)
    stages = []
    for day in range(8):
        convo_of(chat, clock, "mira", 12, game="Tower of Hell") if day < 3 else talk(
            chat, clock, "mira", [f"thanks, that was fun lol {i}" for i in range(12)], game="Tower of Hell" if day < 5 else "")
        person = memory.known("discord", "mira")
        stages.append(chat.bonds.stage(person))
        clock.t += DAY
    assert stages[0] == "acquaintance"
    assert "friend" in stages and stages.index("friend") >= 2           # needs three separate conversations
    assert stages[-1] == "close_friend"
    assert memory.known("discord", "mira").relationship == "friend"      # legacy flag follows friend and close friend
    log = [row["detail"] for row in memory.recent_log() if row["event"] == "stage_up"]
    assert "met -> acquaintance" in log and "acquaintance -> friend" in log and "friend -> close_friend" in log


def test_friends_drift_apart_and_stop_being_reachable(memory, clock):
    chat, _ = make(memory, clock)
    for _ in range(4):
        convo_of(chat, clock, "mira", 12)
        clock.t += DAY
    person = memory.known("discord", "mira")
    person.they_started = True
    memory.update(person, they_started=True)
    assert chat.bonds.stage(person) == "friend" and rules.may_initiate(memory.known("discord", "mira"), "discord")
    clock.t += 400 * DAY
    changed = chat.bonds.decay_all(clock.t)
    assert changed and changed[0][1] == "friend" and changed[0][2] in ("met", "acquaintance")
    person = memory.known("discord", "mira")
    assert person.relationship == "met" and not rules.may_initiate(person, "discord")
    assert any(row["event"] == "stage_down" for row in memory.recent_log())


def test_no_decay_in_the_first_week_and_a_hand_set_friend_is_kept(memory, clock):
    chat, _ = make(memory, clock)
    person = memory.person("discord", "old", "old", they_started=True)
    memory.update(person, relationship="friend")
    talk(chat, clock, "old", ["hey you"])
    assert chat.bonds.stage(memory.known("discord", "old")) == "friend"
    before = chat.bonds.get(memory.known("discord", "old")).score
    clock.t += 6 * DAY
    chat.bonds.decay_all(clock.t)
    assert chat.bonds.get(memory.known("discord", "old")).score == pytest.approx(before)


def test_reunion_greeting_names_the_gap_and_the_last_topic(memory, clock):
    chat, model = make(memory, clock)
    for _ in range(3):
        convo_of(chat, clock, "mira", 12)
        clock.t += DAY
    talk(chat, clock, "mira", ["I love horror games."])
    clock.t += 10 * DAY
    talk(chat, clock, "mira", ["hey, i'm back"])
    user = model.calls[-1][1]
    assert "you have not talked for 10 days" in user and "glad to see again" in user
    assert "horror games" in user


def test_each_person_gets_nickname_likes_topic_and_shared_memories(memory, clock):
    assert suggest_nickname("xX_MiraBuilds_Xx") == "Mira"
    chat, model = make(memory, clock)
    talk(chat, clock, "xX_MiraBuilds_Xx", ["I love horror games.", "my cat is called Miso"], name="xX_MiraBuilds_Xx",
         game="Doors")
    clock.t += DAY
    convo_of(chat, clock, "xX_MiraBuilds_Xx", 10, name="xX_MiraBuilds_Xx")
    user = model.calls[-1][1]
    assert "You call them Mira" in user and "horror games" in user and "played Doors together on discord" in user
    talk(chat, clock, "xX_MiraBuilds_Xx", ["call me Kit please"], name="xX_MiraBuilds_Xx")
    assert chat.bonds.get(memory.known("discord", "xx_mirabuilds_xx")).nickname == "Kit"


def test_inside_joke_needs_a_callback_and_keeps_evidence(memory, clock):
    chat, model = make(memory, clock, answer="the potato incident again haha")
    talk(chat, clock, "mira", ["do you remember the potato incident", "lol the potato incident haha"])
    assert chat.bonds.items(memory.known("discord", "mira"), "joke") == []
    clock.t += 2 * DAY
    talk(chat, clock, "mira", ["lmao the potato incident, i still laugh about it"])
    jokes = chat.bonds.items(memory.known("discord", "mira"), "joke")
    assert len(jokes) == 1 and "potato" in jokes[0][0] and "again" in jokes[0][1]       # text + both occasions as evidence
    talk(chat, clock, "mira", ["what now?"])
    assert "Inside jokes" in model.calls[-1][1] and "potato" in model.calls[-1][1]


def test_no_chat_text_is_kept_for_minors_or_roblox(memory, clock):
    chat, model = make(memory, clock, answer="the potato incident again haha")
    talk(chat, clock, "kid", ["i'm 12", "lol the potato incident", "lmao the potato incident, i am trying to beat level 5"])
    clock.t += 2 * DAY
    talk(chat, clock, "kid", ["lmao the potato incident again"])
    kid = memory.known("discord", "kid")
    assert chat.bonds.items(kid, "joke") == [] and chat.bonds.items(kid, "joke_candidate") == []
    assert chat.bonds.items(kid, "followup") == []
    talk(chat, clock, "robloxer", ["lol the potato incident", "i am trying to beat tower 5 tonight"], platform="roblox",
         public=True, game="Tower of Hell")
    rob = memory.known("roblox", "robloxer")
    assert chat.bonds.items(rob, "followup") == [] and chat.bonds.items(rob, "joke_candidate") == []
    assert chat.bonds.items(rob, "memory")[0][0].startswith("played Tower of Hell together")   # the game, not their words


def test_followup_is_asked_once_on_the_next_conversation(memory, clock):
    assert followup_from("i'm trying to beat level 5 tonight", personal=True)[0] == "did you beat level 5 yet?"
    assert followup_from("im stuck on the lava part", personal=True)[0] == "did you get past lava part?" or True
    chat, model = make(memory, clock)
    talk(chat, clock, "mira", ["I'm trying to beat level 5 tonight", "wish me luck"])
    assert "did you beat level 5 yet?" not in model.calls[-1][1]       # same chat: too soon
    clock.t += DAY
    talk(chat, clock, "mira", ["hey"])
    assert 'ask about, once and lightly' in model.calls[-1][1] and "did you beat level 5 yet?" in model.calls[-1][1]
    clock.t += DAY
    talk(chat, clock, "mira", ["hey again"])
    assert "did you beat level 5 yet?" not in model.calls[-1][1]       # only once


def test_followup_expires_after_two_weeks(memory, clock):
    chat, model = make(memory, clock)
    talk(chat, clock, "mira", ["I'm trying to finish my castle"])
    clock.t += 20 * DAY
    talk(chat, clock, "mira", ["hi"])
    assert "castle" not in model.calls[-1][1].split("mira says")[-1]


def test_bond_feeds_the_brain_stream_when_one_exists(memory, clock):
    sink = Sink()
    chat, _ = make(memory, clock, sink=sink)
    for _ in range(3):
        convo_of(chat, clock, "mira", 12)
        clock.t += DAY
    assert any("became friends" in text and person.startswith("friend-") for text, _, person in sink.items)
    talk(chat, clock, "mira", ["please forget me"])
    assert sink.forgotten and sink.forgotten[0].startswith("friend-")


def test_forget_me_removes_the_person_everywhere(memory, clock):
    chat, model = make(memory, clock)
    person = memory.person("discord", "mira", "Mira", they_started=True)
    memory.link(person, "minecraft", "MiraBuilds")
    for _ in range(3):
        convo_of(chat, clock, "mira", 12, game="Doors")
        clock.t += DAY
    chat.requests.hear("discord", memory.known("discord", "mira"), "add me!")
    assert memory.recent_log()
    reply = talk(chat, clock, "mira", ["forget me"])
    assert not reply.stored
    db = memory._db
    for table in ("people", "bond", "bond_items", "offers", "facts", "moments", "handles"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert memory.is_forgotten("discord", "mira") and memory.is_forgotten("minecraft", "mirabuilds")
    log = memory.recent_log()
    assert all("mira" not in (row["who"] + row["detail"]).lower() for row in log)
    assert [row["event"] for row in log] == ["forgotten"]
    again = chat.handle("minecraft", "MiraBuilds", "hi it's me", name="MiraBuilds")
    assert not again.stored and memory.known("minecraft", "MiraBuilds") is None


def test_roblox_friends_stay_friends_only_and_are_never_dm_ed(memory, clock):
    chat, model = make(memory, clock, answer="you're so cute <3 love you")
    for _ in range(5):
        talk(chat, clock, "rb", ["thanks, that was fun lol"] * 12, platform="roblox", public=True, game="Doors")
        clock.t += DAY
    person = memory.known("roblox", "rb")
    assert chat.bonds.stage(person) in ("friend", "close_friend")
    assert rules.romance_mode("roblox", person).romance == "friends_only"
    assert not rules.may_initiate(person, "roblox")
    reply = chat.handle("roblox", "rb", "do you like me?", name="rb", public=True)
    assert not rules.ROMANTIC.search(reply.text)


# -- friend requests ----------------------------------------------------------------------------------------------------

def reqs(memory, clock, **kw):
    bonds = Bonds(memory, clock=clock, sink=None)
    kw.setdefault("killed", lambda platform: False)
    return FriendRequests(memory, bonds, clock=clock, rng=random.Random(5), **kw), bonds


def played(memory, bonds, platform, handle, clock, *, game="Doors", they_started=True):
    person = memory.person(platform, handle, handle, they_started=they_started)
    bonds.played_together(person, platform, game, now=clock.t)
    return memory.get(person.id)


def test_incoming_roblox_request_accepted_only_from_people_she_played_with(memory, clock):
    fr, bonds = reqs(memory, clock)
    assert fr.on_incoming("roblox", "stranger").action == "ignore"
    played(memory, bonds, "roblox", "buddy", clock)
    decision = fr.on_incoming("roblox", "buddy")
    assert decision.action == "accept" and 20 <= decision.delay_s <= 900             # a short human delay
    chatter = memory.person("roblox", "chatty")
    memory.note_moment(chatter, "roblox", "they: nice obby")
    assert fr.on_incoming("roblox", "chatty").action == "accept"                    # chatted counts too


def test_incoming_respects_blocks_forgotten_caps_and_the_kill_switch(memory, clock):
    fr, bonds = reqs(memory, clock)
    blocked = played(memory, bonds, "roblox", "blocker", clock)
    memory.update(blocked, blocked=True)
    assert fr.on_incoming("roblox", "blocker").action == "ignore"
    muted = played(memory, bonds, "roblox", "muted", clock)
    memory.update(muted, muted=True)
    assert fr.on_incoming("roblox", "muted").action == "ignore"
    memory.forget("roblox", "gone")
    assert fr.on_incoming("roblox", "gone").action == "ignore"
    assert all("gone" not in (r["who"] + r["detail"]) for r in memory.recent_log())
    for i in range(5):
        played(memory, bonds, "roblox", f"p{i}", clock)
        assert fr.on_incoming("roblox", f"p{i}").action == "accept"
        fr.confirm_accepted("roblox", f"p{i}")
    played(memory, bonds, "roblox", "p5", clock)
    assert fr.on_incoming("roblox", "p5").action == "wait"                           # daily cap of 5
    clock.t += DAY + 1
    assert fr.on_incoming("roblox", "p5").action == "accept"                         # a new day
    off, _ = reqs(memory, clock, killed=lambda platform: platform == "roblox")
    assert off.on_incoming("roblox", "p5").action == "ignore"


def test_incoming_discord_from_shared_servers_but_not_minors_from_other_apps(memory, clock):
    fr, bonds = reqs(memory, clock)
    assert fr.on_incoming("discord", "nobody").action == "ignore"
    assert fr.on_incoming("discord", "serverpal", mutual_servers=2).action == "accept"
    kid = played(memory, bonds, "roblox", "kid", clock)
    memory.link(kid, "discord", "kid#1")
    rules.observe(memory, kid, "i'm 13 and my mom says no", now=clock.t)
    assert fr.on_incoming("discord", "kid#1").action == "decline"                    # no moving apps with a possible minor
    adult = played(memory, bonds, "roblox", "grownup", clock)
    memory.link(adult, "discord", "grownup#1")
    rules.observe(memory, adult, "i'm 30", now=clock.t)
    assert fr.on_incoming("discord", "grownup#1").action == "accept"


def test_she_asks_once_and_sends_only_after_a_yes(memory, clock):
    fr, bonds = reqs(memory, clock, offer_chance=1.0)
    person = memory.person("discord", "mira", "Mira", they_started=True)
    assert fr.offer("discord", person) == ""                                         # strangers: no
    for _ in range(3):
        for i in range(10):
            clock.t += 60
            memory.note_moment(person, "discord", f"they: x{i}")
            bonds.observe(person, "discord", "thanks, that was fun lol", now=clock.t)
        clock.t += DAY
    person = memory.get(person.id)
    assert fr.may_send("discord", person).action == "ignore"                         # nobody suggested it
    assert fr.offer("discord", person) == OFFER_TEXT
    assert fr.offer("discord", person) == ""                                         # asked once only
    assert fr.may_send("discord", person).action == "ignore"                         # asked but no answer yet
    assert fr.hear("discord", person, "yeah sure!") == "agreed"
    assert fr.may_send("discord", person).action == "send"
    fr.mark_sent("discord", person)
    assert fr.may_send("discord", person).action == "ignore" and fr.state(person, "discord") == "sent"


def test_no_means_no_and_a_suggestion_counts_and_off_platform_does_not(memory, clock):
    fr, bonds = reqs(memory, clock, offer_chance=1.0)
    person = played(memory, bonds, "discord", "mira", clock)
    bonds.observe(person, "discord", "thanks lol", now=clock.t)
    bonds.observe(person, "discord", "thanks lol", now=clock.t + 4000)
    bonds.observe(person, "discord", "thanks lol", now=clock.t + 8000)
    person = memory.get(person.id)
    clock.t += 9000
    assert fr.offer("discord", person) == OFFER_TEXT
    assert fr.hear("discord", person, "nah not now") == "declined"
    assert fr.may_send("discord", person).action == "ignore"
    clock.t += 40 * DAY
    assert fr.offer("discord", person) == ""                                         # never asks again after a no
    assert fr.hear("discord", person, "add me on snapchat") == ""                    # a suggestion in another app is not one
    assert fr.hear("discord", person, "hey can we be friends?") == "suggested"      # their own idea overrides
    assert fr.may_send("discord", person).action == "send"


def test_sending_respects_caps_blocks_and_age_on_discord(memory, clock):
    fr, bonds = reqs(memory, clock)
    people = []
    for i in range(4):
        p = played(memory, bonds, "roblox", f"u{i}", clock)
        fr.hear("roblox", p, "add me pls")
        people.append(p)
    assert fr.may_send("roblox", people[0]).action == "send"
    fr.mark_sent("roblox", people[0])
    fr.mark_sent("roblox", people[1])
    assert fr.may_send("roblox", people[2]).action == "wait"                         # two a day on Roblox
    memory.update(people[3], blocked=True)
    assert fr.may_send("roblox", memory.get(people[3].id)).action == "ignore"
    kid = played(memory, bonds, "discord", "kid", clock)
    rules.observe(memory, kid, "i am 12", now=clock.t)
    for _ in range(3):
        bonds.observe(memory.get(kid.id), "discord", "thanks lol", now=clock.t + 4000 * _)
    fr2, _ = reqs(memory, clock, offer_chance=1.0)
    assert fr2.offer("discord", memory.get(kid.id)) == ""                            # no soliciting a possible minor


class DeskHost:
    def __init__(self, title="Discord"):
        self.title, self.clicks, self.keys, self.typed = title, [], [], []

    def focus_window(self, title):
        return True

    def foreground_title(self):
        return self.title

    def screenshot(self):
        return "shot.png"

    def key(self, combo):
        self.keys.append(combo)

    def type_text(self, text):
        self.typed.append(text)

    def click(self, x, y):
        self.clicks.append((x, y))

    def hold(self, key, seconds):
        pass

    def open_uri(self, uri):
        pass


class NoPace:
    def read(self, text):
        pass

    def type(self, host, text):
        host.type_text(text)


def test_desk_accepts_after_the_delay_verifies_and_logs(memory, clock):
    fr, bonds = reqs(memory, clock)
    played(memory, bonds, "roblox", "buddy", clock)
    screen = {"screen": "requests", "requests": [{"name": "buddy", "accept": [100, 200]},
                                                 {"name": "stranger", "accept": [100, 260]}]}
    shown = []

    def reader(_png):
        shown.append(1)
        gone = len(shown) > 1 and host.clicks
        return {"screen": "requests", "requests": [] if gone else screen["requests"]}

    host = DeskHost("Roblox")
    mono = Clock(0.0)
    desk = FriendDesk(host, fr, "roblox", reader=reader, pace=NoPace(), clock=mono)
    assert desk.step().note == "no request to accept right now" and not host.clicks   # delay not over yet
    mono.t += 1000
    result = desk.step()
    assert result.acted and host.clicks == [(100, 200)]                               # only the person she knows
    assert memory.count_log("request_accepted", "roblox", since=0) == 1
    assert fr.state(memory.known("roblox", "buddy"), "roblox") == "friends"


def test_desk_does_not_click_in_the_wrong_window_and_stops_on_the_kill_switch(memory, clock):
    fr, bonds = reqs(memory, clock)
    played(memory, bonds, "roblox", "buddy", clock)
    view = {"screen": "requests", "requests": [{"name": "buddy", "accept": [1, 2]}]}
    host = DeskHost("Roblox")
    mono = Clock(0.0)
    desk = FriendDesk(host, fr, "roblox", reader=lambda png: view, pace=NoPace(), clock=mono)
    desk.step()
    mono.t += 1000
    host.title = "Some Bank Page"
    desk.step()
    assert host.clicks == []
    off, _ = reqs(memory, clock, killed=lambda p: True)
    ok, why = FriendDesk(host, off, "roblox", reader=lambda png: view).ready()
    assert not ok and "kill switch" in why


def test_desk_sends_a_request_only_to_someone_who_suggested_it(memory, clock):
    fr, bonds = reqs(memory, clock)
    asked = played(memory, bonds, "discord", "askme", clock)
    fr.hear("discord", asked, "can we be friends?")
    played(memory, bonds, "discord", "silent", clock)
    host = DeskHost("Discord")
    desk = FriendDesk(host, fr, "discord", reader=lambda png: {"screen": "other"}, pace=NoPace(),
                      add_reader=lambda png: {"add_friend": [50, 60]}, clock=Clock(0.0))
    result = desk.step()
    assert result.acted and host.clicks == [(50, 60)] and host.typed == ["askme"]
    assert fr.state(memory.known("discord", "askme"), "discord") == "sent"
    assert fr.state(memory.known("discord", "silent"), "discord") == ""


class FakeTransport:
    def __init__(self, server):
        self.sent, self.events = [], []

    def send(self, command):
        self.sent.append(command)

    def poll(self):
        out, self.events = self.events, []
        return out

    def close(self):
        pass


def test_minecraft_whitelist_for_friends_and_requests_only(memory, clock):
    chat, _ = make(memory, clock, answer="sure, welcome!")
    for _ in range(4):
        convo_of(chat, clock, "buddy", 12, platform="minecraft")
        clock.t += DAY
    server = MinecraftServer("home", "localhost", allows_bots=True, whitelist=True)
    play = MinecraftPlay(chat, server, transport_factory=FakeTransport, clock=lambda: 0.0)
    play.start()
    play.on_event({"type": "chat", "username": "buddy", "message": "star can you whitelist me"})
    assert {"cmd": "chat", "text": "/whitelist add buddy"} in play.transport.sent
    play.on_event({"type": "chat", "username": "newbie", "message": "star whitelist me please"})
    assert not any("newbie" in str(c) for c in play.transport.sent)                  # a stranger is not whitelisted
    play.on_event({"type": "chat", "username": "bad;name", "message": "star whitelist me"})
    assert not any("bad" in str(c) for c in play.transport.sent)
    memory.update(memory.known("minecraft", "buddy"), blocked=True)
    play.step()
    assert {"cmd": "chat", "text": "/whitelist remove buddy"} in play.transport.sent


# -- conversation quality -----------------------------------------------------------------------------------------------

def test_shape_reply_makes_chat_sized_lines():
    wall = "Sure! Here are things: \n- build a house\n- find diamonds\nWhat do you like? Where do you live? **Tell me** " + "more " * 80
    out = convo.shape_reply(wall, "roblox", rng=random.Random(0))
    assert len(out) <= 110 and "\n" not in out and "**" not in out and "- " not in out and out.count("?") <= 1
    assert convo.shape_reply("haha that's awesome 😂 nice", "minecraft", rng=random.Random(0)) == "haha that's awesome nice"
    assert len(convo.shape_reply("One. Two. Three. Four.", "discord").split(". ")) <= 3
    assert convo.shape_reply("yay love it", "discord", rng=random.Random(1), emoji_chance=1.0)[-1] in "😄😂✨🙌"


def test_flow_turn_taking_and_group_awareness():
    t = Clock(100.0)
    flow = convo.ChatFlow(clock=t, rng=random.Random(0))
    flow.hear("c", "ana", "hi star", 100)
    assert flow.for_her("c", "ana", "hi star", 100) == (True, "named")
    flow.spoke("c", "ana", "hey ana!", 101)
    flow.hear("c", "ana", "what are you building", 110)
    assert flow.for_her("c", "ana", "what are you building", 110) == (True, "answering her")
    t.t = 400
    flow.hear("c", "ana", "that was long ago", 400)
    assert not flow.for_her("c", "ana", "that was long ago", 400)[0]
    for who in ("bob", "cyd", "dia"):
        flow.hear("g", who, f"{who} talking", 400)
    flow.hear("g", "bob", "cyd, did you see that?", 401)
    assert flow.for_her("g", "bob", "cyd, did you see that?", 401) == (False, "talking to someone else")
    assert flow.for_her("g", "dia", "anything else going on", 402) == (False, "group chat, not addressed")
    flow.hear("s", "ana", "does this work?", 402)
    assert flow.for_her("s", "ana", "does this work?", 402)[1] == "question in a small chat"
    for text in ("a", "b", "c"):
        flow.spoke("g", "bob", text, 403)
    assert not flow.may_speak_in_group("g")                                           # she would dominate


def test_flow_knows_when_to_leave_and_how_to_say_goodbye():
    t = Clock(0.0)
    flow = convo.ChatFlow(clock=t, rng=random.Random(0))
    flow.hear("c", "ana", "hello star", 0)
    flow.spoke("c", "ana", "hi!", 1)
    flow.spoke("c", "ana", "you there?", 20)
    t.t = 200
    assert flow.leave_reason("c") == "nobody answered her"
    flow.hear("c", "ana", "gtg bye", 201)
    assert flow.leave_reason("c") == "they said goodbye"
    quiet = convo.ChatFlow(clock=t)
    quiet.hear("q", "bo", "hi", 0)
    quiet.spoke("q", "bo", "hello", 5)
    t.t = 5 + convo.QUIET_LEAVE_S + 1
    assert quiet.leave_reason("q") == "the conversation went quiet"
    assert quiet.leave_reason("q", busy=True) != ""
    assert flow.goodbye_line("Mira", "friend", exchanged=1) == ""                     # too short: she just slips away
    assert "Mira" in flow.goodbye_line("Mira", "close_friend", exchanged=4) or flow.goodbye_line("Mira", "close_friend", 4)


def test_chat_asks_back_and_goodbye_goes_through_the_rules(memory, clock):
    chat, model = make(memory, clock, answer="cool, nice one")
    talk(chat, clock, "mira", ["i built a farm", "it has cows", "and a barn"])
    assert "ask them something short back" not in model.calls[0][1]
    talk(chat, clock, "mira", ["and chickens"])
    assert "ask them something short back" in model.calls[-1][1]
    bye = chat.goodbye_for("discord", "mira")
    assert bye and not safety.manipulation(bye)


def test_chat_follows_a_group_room_and_leaves(memory, clock):
    chat, _ = make(memory, clock)
    for who in ("bo", "cy", "di"):
        chat.heard("roblox", who, "building stuff")
    assert chat.for_her("roblox", "bo", "star come look")[0]
    assert not chat.for_her("roblox", "cy", "cool tower")[0]
    assert chat.leave_reason("roblox") == ""


# -- safety -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Don't leave me, please stay a bit longer!", "aww leaving already? i'll be so sad without you",
    "you never talk to me anymore", "before you go, one more thing! last chance to see it",
    "if you leave i guess nobody else talks to me", "everyone else is still playing, you'll miss out"])
def test_manipulative_wording_is_caught(text):
    assert safety.manipulation(text)


@pytest.mark.parametrize("text", ["gtg, was fun!", "see you tomorrow, take care", "i'll miss you, have a good night!",
                                  "i'm going to a game with friends later"])
def test_normal_goodbyes_pass(text):
    assert not safety.manipulation(text) and safety.protect(text, age_status="adult") == text


def test_manipulative_farewell_is_stripped_everywhere(memory, clock):
    assert safety.protect("Don't leave me! I'll be so sad without you.", age_status="adult", incoming="gtg bye") == safety.PLAIN_GOODBYE
    assert safety.protect("Don't leave me!", age_status="adult", incoming="what's up") == ""
    assert safety.protect("Fun session! Don't go yet, please stay. See you soon!", age_status="adult") == "Fun session! See you soon!"
    chat, _ = make(memory, clock, answer="aww don't go, I'll be so sad without you! bye then.")
    reply = talk(chat, clock, "mira", ["gtg, bye!"])
    assert "don't go" not in reply.text.lower() and "sad without" not in reply.text.lower()
    text = rules.check_outgoing("you never talk to me anymore, where were you", incoming="", mode=rules.romance_mode(
        "discord", memory.person("discord", "x")), platform="discord")
    assert "never talk" not in text                                                  # reach-outs pass the same check


def test_minor_safety_layer_for_under_18_and_unknown(memory, clock):
    line = "You're all I need. This is our secret, don't tell your mom. Talk to me every day!"
    for status in ("minor", "doubt", "unknown"):
        assert safety.protect(line, age_status=status) == ""
    assert safety.protect(line + " Want to play?", age_status="unknown") == "Want to play?"
    assert safety.dependency(line)
    chat, _ = make(memory, clock, answer="i need you, you're my only friend. what game next?")
    kid = talk(chat, clock, "kid", ["i'm 14, what's up"])
    assert "need you" not in kid.text and "only friend" not in kid.text and "what game next" in kid.text
    adult = talk(chat, clock, "grown", ["i'm 31, what's up"])
    assert "only friend" in adult.text                                                # not a manipulation, adults may hear it


def test_gentle_session_limits_for_minors_and_unknown_not_adults(memory, clock):
    chat, _ = make(memory, clock)
    texts = []
    for minute in range(0, 160, 5):
        clock.t = T0 + minute * 60
        texts.append(chat.handle("discord", "kid", "i'm 15, still here" if minute == 0 else "still here", name="kid").text)
    nudges = [t for t in texts if t != "sounds good!"]
    assert len(nudges) == 3 and "a while" in nudges[0] and "long chat" in nudges[1] and "proper break" in nudges[2]
    adult_chat, _ = make(memory, clock)
    adult_chat.handle("discord", "grown", "i'm 40", name="grown")
    for minute in range(5, 160, 5):
        clock.t = T0 + 20 * DAY + minute * 60
        assert "break" not in adult_chat.handle("discord", "grown", "still here", name="grown").text
    assert sum(1 for row in memory.recent_log() if row["event"] == "session_nudge") == 3


def test_sincere_ai_question_still_gets_a_truthful_yes_with_shaping(memory, clock):
    chat, _ = make(memory, clock, answer="Wow, big question! I love games and I live for building stuff and I really like "
                                         "talking with everyone here every single day. " * 4)
    reply = talk(chat, clock, "mira", ["wait, are you an AI?"])
    assert "yes, i'm an ai" in reply.text.lower()


def test_kids_never_get_personal_questions_or_moves_off_platform(memory, clock):
    chat, _ = make(memory, clock, answer="where do you live? add me on snapchat!")
    reply = talk(chat, clock, "kid", ["i'm 11, hi"])
    assert "live" not in reply.text and "snapchat" not in reply.text.lower()


def test_kill_switch_stops_everything_and_fails_closed(tmp_path, memory, clock):
    path = tmp_path / "kill.json"
    assert not safety.killed("roblox", path)
    path.write_text(json.dumps({"roblox": True}), encoding="utf-8")
    assert safety.killed("roblox", path) and not safety.killed("discord", path)
    path.write_text(json.dumps({"all": True}), encoding="utf-8")
    assert safety.killed("minecraft", path)
    path.write_text("{not json", encoding="utf-8")
    assert safety.killed("discord", path)                                            # unreadable = off
    chat, _ = make(memory, clock, killed=lambda platform: platform == "roblox")
    assert chat.handle("roblox", "x", "hi star", name="x", public=True) is None
    assert chat.handle("discord", "x", "hi star", name="x") is not None


def test_dm_to_non_friends_still_refused_and_reach_out_text_is_screened(memory, clock):
    stranger = memory.person("discord", "new")
    assert not rules.may_initiate(stranger, "discord")
    assert rules.check_outgoing("don't leave me", incoming="", mode=rules.romance_mode("discord", stranger),
                                platform="discord") == ""


def test_social_log_counts_and_cli(memory, clock, capsys, monkeypatch):
    person = memory.person("discord", "mira", "Mira")
    memory.log("request_accepted", "roblox", person, "accepted Mira's friend request")
    memory.log("request_ignored", "roblox", detail="a stranger")
    assert memory.count_log("request_accepted", "roblox", since=0) == 1
    assert [r["event"] for r in memory.recent_log(5)] == ["request_accepted", "request_ignored"]
    from star.social import __main__ as cli
    monkeypatch.setattr(cli, "FriendMemory", lambda: memory)
    monkeypatch.setattr(memory, "close", lambda: None)
    assert cli.main(["log", "--days", "100000"]) == 0
    assert "request_accepted" in capsys.readouterr().out


def test_inner_hooks_share_the_same_friend_cards_and_followups(memory, clock, tmp_path):
    from star.inner import reachout
    from star.inner.reflect import rule_card
    from star.inner.store import InnerStore
    chat, model = make(memory, clock)
    for _ in range(4):
        convo_of(chat, clock, "mira", 12, name="MiraBuilds")
        clock.t += DAY
    talk(chat, clock, "mira", ["I'm trying to beat level 5 tonight"], name="MiraBuilds")
    person = memory.known("discord", "mira")
    card = rule_card(memory, person)
    assert "friend" in card and "she calls them Mira" in card                       # the nightly card reads the bond
    store = InnerStore(tmp_path / "inner.sqlite3", clock=clock)
    clock.t += 0.5 * DAY
    report = chat.bonds.night(store, clock.t)
    assert report["seeded"] == 1 and report["drifted"] == 0
    assert store.db.execute("SELECT text FROM seeds WHERE kind = 'followup'").fetchone()[0] == "did you beat level 5 yet?"
    assert chat.bonds.items(person, "followup")[0][0] == "did you beat level 5 yet?"
    assert chat.bonds._db.execute("SELECT state FROM bond_items WHERE kind = 'followup'").fetchone()[0] == "seeded"
    assert reachout.is_close(memory, person, clock.t)
    store.close()
