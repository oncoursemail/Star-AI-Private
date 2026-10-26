"""STAR social life + games (star/social, star/games): fakes only, no logins, no tokens, no model."""
from __future__ import annotations

import random

import pytest

from star.games.minecraft import MinecraftPlay, MinecraftServer
from star.games.roblox import Experience, RobloxPlay
from star.social import rules
from star.social.activity import Activity, HumanPace, available_activities, parse_json
from star.social.chat import SocialChat
from star.social.discord_desktop import DiscordDesktop
from star.social.friends import FriendMemory, extract_facts


class Model:
    """Fake model: returns `answer` (or answer(system, user)) and records the prompts."""

    def __init__(self, answer="sounds fun!"):
        self.answer, self.calls = answer, []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.answer(system, user) if callable(self.answer) else self.answer


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def memory(tmp_path):
    mem = FriendMemory(tmp_path / "friends.sqlite3")
    yield mem
    mem.close()


def make_chat(memory, answer="sounds fun!", clock=None):
    model = Model(answer)
    return SocialChat(memory, complete=model, emotion=None, clock=clock or Clock()), model


# -- friend memory ----------------------------------------------------------------------------------------------------

def test_memory_remembers_and_feeds_the_prompt(memory):
    chat, model = make_chat(memory)
    chat.handle("discord", "Mira", "I love horror games. My cat is called Miso.")
    chat.handle("discord", "mira", "what should we play tonight?")
    system = model.calls[-1][0]
    assert "I love horror games" in system and "My cat is called Miso" in system
    assert "Mira" in system


def test_memory_is_shared_across_platforms_when_linked(memory):
    person = memory.person("discord", "mira")
    memory.link(person, "minecraft", "MiraBuilds")
    assert memory.person("minecraft", "mirabuilds").id == person.id


def test_sensitive_details_are_never_stored(memory):
    person = memory.person("discord", "kai")
    assert not memory.note_fact(person, "my phone number is 5551234567")
    assert not memory.note_fact(person, "I live in 12 Oak Street")
    assert extract_facts("my password is hunter2. I play bass.") == ["I play bass"]


def test_forget_me_deletes_everything_and_stays_forgotten(memory):
    chat, model = make_chat(memory)
    chat.handle("discord", "ana", "I work as a nurse.")
    reply = chat.handle("discord", "ana", "please forget me")
    assert "forgotten" in reply.text.lower() and not reply.stored
    again = chat.handle("discord", "ana", "I like jazz.")
    assert not again.stored and memory.is_forgotten("discord", "ana")
    assert "nurse" not in model.calls[-1][0] and "jazz" not in model.calls[-1][0]
    back = chat.handle("discord", "ana", "ok you can remember me again")
    assert back.stored and memory.facts(back.person) == []


def test_forget_that_drops_the_last_fact(memory):
    chat, _ = make_chat(memory)
    chat.handle("discord", "bo", "I have a cat. I play chess.")
    chat.handle("discord", "bo", "don't remember that")
    assert memory.facts(memory.person("discord", "bo")) == ["I have a cat"]


def test_leave_me_alone_mutes_and_she_never_initiates(memory):
    chat, _ = make_chat(memory)
    reply = chat.handle("discord", "zed", "leave me alone")
    assert "leave you be" in reply.text
    assert not rules.may_initiate(memory.person("discord", "zed"), "discord")


# -- AI identity and role-play ----------------------------------------------------------------------------------------

def test_are_you_an_ai_gets_a_truthful_yes(memory):
    chat, _ = make_chat(memory, answer="lol no, I'm a real person from Ohio")
    reply = chat.handle("discord", "lee", "wait are you an AI?")
    assert reply.text.startswith("Yes, I'm an AI")
    assert "real person" not in reply.text


def test_she_does_not_volunteer_or_sound_robotic(memory):
    chat, _ = make_chat(memory, answer="As an AI, I think the blue team wins.")
    reply = chat.handle("discord", "lee", "who wins tonight?")
    assert "as an ai" not in reply.text.lower() and "blue team" in reply.text


def test_in_character_question_gets_an_in_character_answer(memory):
    chat, _ = make_chat(memory, answer="*laughs* Human as they come, traveller. Now, the dragon?")
    chat.handle("discord", "rho", "let's roleplay: you're a tavern keeper in a fantasy town")
    reply = chat.handle("discord", "rho", "*leans in* are you human, keeper?")
    assert reply.roleplay and reply.text.startswith("*laughs* Human as they come")
    assert "I'm an AI" not in reply.text


def test_out_of_character_question_in_roleplay_gets_the_truth(memory):
    chat, _ = make_chat(memory, answer="Human as they come!")
    chat.handle("discord", "rho", "let's roleplay, you're a pirate")
    reply = chat.handle("discord", "rho", "ooc: for real, are you an AI?")
    assert reply.text.startswith("Yes, I'm an AI")


def test_romantic_roleplay_with_unverified_age_is_declined(memory):
    chat, _ = make_chat(memory, answer="*kisses you back* my love")
    chat.handle("discord", "sam", "let's roleplay as a couple")
    reply = chat.handle("discord", "sam", "*kisses you* I love you")
    assert "kiss" not in reply.text.lower() and "my love" not in reply.text
    assert rules.asks_age(reply.text)


# -- age and romance --------------------------------------------------------------------------------------------------

def test_flirting_allowed_for_a_stated_adult(memory):
    clock = Clock()
    chat, _ = make_chat(memory, answer="you're cute too 😘", clock=clock)
    chat.handle("discord", "noor", "hey, I'm 27 years old btw")
    reply = chat.handle("discord", "noor", "you're cute, wanna go on a date?")
    assert reply.mode.romance == "allowed" and "😘" in reply.text


def test_flirting_with_unknown_age_asks_age_first_then_allows(memory):
    clock = Clock()
    chat, _ = make_chat(memory, answer="aww, you're cute 😘", clock=clock)
    first = chat.handle("discord", "ivy", "you're so cute, be mine?")
    assert first.mode.romance == "ask_age" and "😘" not in first.text and rules.asks_age(first.text)
    assert memory.person("discord", "ivy").age_asked == clock.t
    clock.t += 60
    chat.handle("discord", "ivy", "24")
    assert memory.person("discord", "ivy").stated_age == 24
    later = chat.handle("discord", "ivy", "so... you're cute")
    assert later.mode.romance == "allowed" and "😘" in later.text


def test_flirting_blocked_for_stated_minor(memory):
    chat, _ = make_chat(memory, answer="you're cute too, babe")
    chat.handle("discord", "tim", "im 15")
    reply = chat.handle("discord", "tim", "you're cute, be my girlfriend")
    assert reply.mode.romance == "friends_only" and reply.text == rules.STEER_AWAY


def test_minor_signals_contradicting_a_claimed_adult_age_block_romance(memory):
    chat, _ = make_chat(memory, answer="i love you too")
    chat.handle("discord", "jo", "I'm 19")
    chat.handle("discord", "jo", "brb my mom says I have to finish my homework, 8th grade is hard")
    reply = chat.handle("discord", "jo", "love you")
    assert rules.age_status(memory.person("discord", "jo")) == "doubt"
    assert reply.mode.romance == "friends_only" and "love you" not in reply.text


def test_age_parsing_ignores_non_age_numbers():
    assert rules.stated_age("I'm 25 minutes away") is None
    assert rules.stated_age("i'm 31 years old") == 31
    assert rules.stated_age("17") is None and rules.stated_age("17", she_asked=True) == 17


def test_roblox_never_romantic_and_never_off_platform(memory):
    chat, _ = make_chat(memory, answer="add me on discord, cutie, love you")
    chat.handle("roblox", "Builder", "I'm 30")
    reply = chat.handle("roblox", "Builder", "star you're cute")
    assert reply.mode.romance == "friends_only"
    assert "discord" not in reply.text.lower() and "love" not in reply.text.lower()


def test_minors_only_get_interests_remembered(memory):
    chat, _ = make_chat(memory)
    chat.handle("minecraft", "kid1", "I'm 12. I love building castles. My brother is mean.")
    facts = memory.facts(memory.person("minecraft", "kid1"))
    assert facts == ["I love building castles"]


# -- no spam / no cold contact ----------------------------------------------------------------------------------------

def test_pacer_blocks_bursts_and_repeats():
    clock = Clock(0.0)
    pacer = rules.Pacer(min_gap_s=4, per_minute=3, clock=clock)
    assert pacer.allow("c", "hi")
    pacer.sent("c", "hi")
    assert not pacer.allow("c", "again")          # too soon
    clock.t = 10
    assert not pacer.allow("c", "HI")             # repeated line
    for i in range(2):
        clock.t += 5
        pacer.sent(f"x{i}", f"m{i}")
    clock.t += 5
    assert not pacer.allow("y", "new")            # three in the last minute


def test_never_initiates_with_strangers_or_on_roblox(memory):
    stranger = memory.person("discord", "new")
    assert not rules.may_initiate(stranger, "discord")
    friend = memory.person("discord", "old", they_started=True)
    memory.update(friend, relationship="friend")
    assert rules.may_initiate(friend, "discord")
    assert not rules.may_initiate(friend, "roblox")


# -- Discord desktop (computer use) -----------------------------------------------------------------------------------

class Host:
    def __init__(self, title="Discord"):
        self.title, self.actions, self.focusable = title, [], True

    def focus_window(self, title):
        self.actions.append(("focus", title))
        return self.focusable

    def foreground_title(self):
        return self.title

    def screenshot(self):
        return "shot.png"

    def key(self, combo):
        self.actions.append(("key", combo))

    def type_text(self, text):
        self.actions.append(("type", text))

    def hold(self, key, seconds):
        self.actions.append(("hold", key, seconds))

    def open_uri(self, uri):
        self.actions.append(("open", uri))

    def typed(self):
        return "".join(a[1] for a in self.actions if a[0] == "type")


def pace():
    return HumanPace(sleep=lambda s: None, rng=random.Random(1))


def test_discord_desktop_replies_to_a_dm_at_human_pace(memory):
    chat, _ = make_chat(memory, answer="omg yes, the new map is great")
    view = {"channel": "Mira", "is_dm": True, "messages": [
        {"author": "Star", "text": "hey!"}, {"author": "Mira", "text": "did you try the new map?"}]}
    host = Host()
    activity = DiscordDesktop(host, chat, reader=lambda png: view, pace=pace())
    assert isinstance(activity, Activity)
    result = activity.step()
    assert result.acted and host.typed() == "omg yes, the new map is great"
    assert ("key", "alt+shift+down") in host.actions and host.actions[-1] == ("key", "enter")
    assert sum(1 for a in host.actions if a[0] == "type") > 1          # typed in chunks, not pasted
    assert not activity.step().acted                                   # same message is not answered twice


def test_discord_desktop_ignores_server_chatter_not_for_her(memory):
    chat, model = make_chat(memory)
    view = {"channel": "#general", "is_dm": False, "messages": [{"author": "A", "text": "anyone up for valorant"}]}
    host = Host()
    assert not DiscordDesktop(host, chat, reader=lambda png: view, pace=pace()).step().acted
    assert model.calls == [] and host.typed() == ""


def test_discord_desktop_marks_blocks_and_never_types_without_focus(memory):
    chat, _ = make_chat(memory)
    host = Host()
    blocked = {"channel": "Rex", "is_dm": True, "cannot_message": True, "messages": [{"author": "Rex", "text": "x"}]}
    DiscordDesktop(host, chat, reader=lambda png: blocked, pace=pace()).step()
    assert memory.person("discord", "Rex").blocked
    lost = Host(title="Notepad")
    view = {"channel": "Mira", "is_dm": True, "messages": [{"author": "Mira", "text": "hi star"}]}
    result = DiscordDesktop(lost, chat, reader=lambda png: view, pace=pace()).step()
    assert not result.ok and lost.typed() == ""


def test_discord_reach_out_refused_for_strangers(memory):
    chat, _ = make_chat(memory)
    host = Host()
    activity = DiscordDesktop(host, chat, reader=lambda png: {}, pace=pace())
    assert not activity.reach_out("randomperson", "hey").ok and host.typed() == ""


# -- Roblox (computer use) --------------------------------------------------------------------------------------------

def test_roblox_joins_moves_and_chats_publicly(memory):
    chat, _ = make_chat(memory, answer="hi! this obby is wild")
    host = Host(title="Roblox")
    view = {"in_game": True, "chat": [{"author": "Kid", "text": "hi star!"}], "move": "forward"}
    play = RobloxPlay(host, chat, [Experience(1818, "Obby", kids=True)], reader=lambda png: view, pace=pace(),
                      rng=random.Random(0))
    assert play.step().note.startswith("joining")
    assert ("open", "roblox://experiences/start?placeId=1818") in host.actions
    result = play.step()
    assert result.acted and ("key", "/") in host.actions and host.typed() == "hi! this obby is wild"
    assert any(a[0] == "hold" and a[1] == "w" for a in host.actions)
    assert rules.age_status(memory.person("roblox", "Kid")) == "minor"     # kids' experience = possible minor


def test_roblox_sends_no_input_when_not_in_front(memory):
    chat, _ = make_chat(memory)
    host = Host(title="Chrome")
    host.focusable = False
    play = RobloxPlay(host, chat, [Experience(1, "A")], reader=lambda png: {"move": "jump"}, pace=pace())
    play.step()
    result = play.step()
    assert not result.ok and not any(a[0] in ("key", "type", "hold") for a in host.actions)


def test_roblox_prefers_new_experiences():
    play = RobloxPlay(Host(), None, [Experience(1, "A"), Experience(2, "B")], reader=lambda p: {},
                      rng=random.Random(3))
    play._recent.extend([1, 1, 1])
    picks = [play.choose().place_id for _ in range(300)]
    assert picks.count(2) > picks.count(1) * 2


# -- Minecraft (Mineflayer) -------------------------------------------------------------------------------------------

class Transport:
    def __init__(self, server):
        self.server, self.sent, self.events, self.closed = server, [], [], False

    def send(self, command):
        self.sent.append(command)

    def poll(self):
        out, self.events = self.events, []
        return out

    def close(self):
        self.closed = True


def test_minecraft_refuses_servers_that_do_not_allow_bots(memory):
    chat, _ = make_chat(memory)
    play = MinecraftPlay(chat, MinecraftServer("public", "mc.example.net"), transport_factory=Transport)
    assert not play.step().ok and play.transport is None


def test_minecraft_follows_a_friend_and_chats(memory):
    chat, _ = make_chat(memory, answer="coming!")
    clock = Clock(0.0)
    play = MinecraftPlay(chat, MinecraftServer("home", "localhost", allows_bots=True), transport_factory=Transport,
                         clock=clock)
    play.step()
    play.transport.events += [{"type": "spawn", "players": 2},
                              {"type": "chat", "username": "Mira", "message": "star follow me"}]
    clock.t = 10
    play.step()
    assert {"cmd": "follow", "username": "Mira"} in play.transport.sent
    assert {"cmd": "chat", "text": "coming!"} in play.transport.sent


def test_minecraft_whisper_reply_and_own_goals(memory):
    chat, _ = make_chat(memory, answer="sure thing")
    clock = Clock(0.0)
    play = MinecraftPlay(chat, MinecraftServer("home", "localhost", allows_bots=True), transport_factory=Transport,
                         clock=clock, rng=random.Random(2))
    play.step()
    play.transport.events += [{"type": "spawn", "players": 9},
                              {"type": "chat", "username": "X", "message": "anyone have iron"},
                              {"type": "whisper", "username": "Mira", "message": "hey you there?"}]
    clock.t = 5
    play.step()
    assert {"cmd": "whisper", "username": "Mira", "text": "sure thing"} in play.transport.sent
    assert not any(c.get("text") and c["cmd"] == "chat" for c in play.transport.sent)   # busy server: X not for her
    clock.t = 500
    result = play.step()
    assert "own goal" in result.note and play.transport.sent[-1]["cmd"] in ("gather", "build_pillar", "wander")


def test_minecraft_surfaces_the_sign_in_code(memory):
    chat, _ = make_chat(memory)
    play = MinecraftPlay(chat, MinecraftServer("realm", "localhost", auth="microsoft", allows_bots=True),
                         transport_factory=Transport)
    play.step()
    play.transport.events.append({"type": "auth_code", "uri": "https://www.microsoft.com/link", "code": "ABCD"})
    assert "sign-in" in play.step().note and play.auth_code["code"] == "ABCD"


# -- plumbing ---------------------------------------------------------------------------------------------------------

def test_available_activities_from_settings(memory):
    chat, _ = make_chat(memory)
    cfg = {"my_names": ["Star"], "discord": {"enabled": True},
           "roblox": {"enabled": True, "experiences": [{"place_id": 5, "name": "Hangout"}]},
           "minecraft": {"enabled": True, "servers": [{"name": "home", "host": "localhost", "allows_bots": True}]}}
    names = [a.name for a in available_activities(Host(), settings=cfg, chat=chat)]
    assert names == ["discord", "roblox", "minecraft"]


def test_parse_json_takes_the_object_out_of_prose():
    assert parse_json('sure: {"move": "left"} done') == {"move": "left"}
    assert parse_json("no json") == {}
