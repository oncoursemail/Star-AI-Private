"""STAR lives in time and takes initiative (star/social/felt_time.py, initiative.py, lifecycle hooks): fake clock, fake
friends, fake model, fake desktop. Nothing is sent anywhere."""
from __future__ import annotations

import random
import time
from datetime import datetime

import pytest

from star.social import felt_time as ft
from star.social.chat import SocialChat
from star.social.friends import FriendMemory
from star.social.initiative import Initiative
from star.social.lifecycle import Bonds

DAY = 86400.0
HOUR = 3600.0


def local(*args) -> float:
    return time.mktime(datetime(*args).timetuple())


T0 = local(2027, 1, 12, 14, 0)          # a Tuesday, 14:00 local (outside quiet hours)


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

    @property
    def last(self) -> str:
        return self.calls[-1][1]


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(tmp_path, clock):
    mem = FriendMemory(tmp_path / "friends.sqlite3", clock=clock)
    yield mem
    mem.close()


@pytest.fixture
def store(tmp_path, clock):
    from star.inner.store import InnerStore
    st = InnerStore(tmp_path / "inner.sqlite3", clock=clock)
    yield st
    st.close()


def make(memory, clock, answer="sounds good!", *, felt=True, initiative=None, rng_seed=3):
    model = Model(answer)
    chat = SocialChat(memory, complete=model, emotion=None, clock=clock, rng=random.Random(rng_seed),
                      bonds=Bonds(memory, sink=None, clock=clock, felt=felt, rng=random.Random(rng_seed)),
                      killed=lambda platform: False, initiative=initiative)
    chat.requests.offer_chance = 0.0
    return chat, model


def talk(chat, clock, handle, lines, *, platform="discord", step=60.0, **kw):
    last = None
    for line in lines:
        clock.t += step
        last = chat.handle(platform, handle, line, name=handle, **kw)
    return last


def befriend(chat, clock, handle="mira", convos=4):
    """Separate daily chats of 12 lines: a friend, and close enough for her reach-out rules (40+ lines, they started)."""
    for _ in range(convos):
        talk(chat, clock, handle, [f"message number {i} about our plans" for i in range(12)])
        clock.t += DAY - 12 * 60
    return chat.memory.known("discord", handle)


# -- felt_time: dates ---------------------------------------------------------------------------------------------------

def test_time_phrases_point_at_the_right_local_day():
    now = local(2027, 1, 12, 15, 0)                       # Tuesday
    day = lambda text: ft.when(text, now).day.date()
    assert day("i have it tomorrow") == datetime(2027, 1, 13).date()
    assert day("on friday") == datetime(2027, 1, 15).date()
    assert day("next wednesday") == datetime(2027, 1, 20).date()   # "next" the day after tomorrow is next week's
    assert day("next tuesday") == datetime(2027, 1, 19).date()
    assert day("in 3 days") == datetime(2027, 1, 15).date()
    assert day("this weekend") == datetime(2027, 1, 16).date()
    assert ft.when("tonight", now).evening and ft.when("next week", now).vague
    assert ft.when("i like cats", now) is None


def test_dated_events_from_how_people_really_text():
    now = local(2027, 1, 12, 15, 0)
    ev = ft.dated_event("i have my driving test on friday and i'm so nervous", now)
    assert ev.question == "how did your driving test go?" and datetime.fromtimestamp(ev.ask_after) == datetime(2027, 1, 15, 18)
    assert ft.dated_event("going to the dentist tomorrow ugh", now).question == "how was the dentist?"
    assert ft.dated_event("we have a big math exam tmrw", now).question == "how did your math exam go?"
    tonight = ft.dated_event("my recital is tonight", now)
    assert datetime.fromtimestamp(tonight.ask_after) == datetime(2027, 1, 13, 9)     # over late: ask the next morning
    bday = ft.dated_event("it's my birthday on saturday!", now)
    assert bday.birthday and datetime.fromtimestamp(bday.ask_after) == datetime(2027, 1, 16, 8)
    for text in ("my sister's birthday is friday", "i don't have a test tomorrow", "the game tomorrow will be fun",
                 "i like tests", "i'll play the game tomorrow"):
        assert ft.dated_event(text, now) is None, text


# -- follow-ups at the right moment ---------------------------------------------------------------------------------------

def test_test_on_friday_is_not_asked_before_it_happened_and_is_asked_after(memory, clock):
    chat, model = make(memory, clock)
    befriend(chat, clock)
    talk(chat, clock, "mira", ["i have my driving test on friday and i'm so nervous"])     # Saturday 14:xx -> next Friday
    clock.t += 2 * HOUR
    talk(chat, clock, "mira", ["back"])
    assert "driving test go" not in model.last                     # a new chat, but the test is days away
    friday = datetime.fromtimestamp(clock.t)
    while friday.weekday() != 4:
        friday = datetime.fromtimestamp(friday.timestamp() + DAY)
    clock.t = local(friday.year, friday.month, friday.day, 9, 0)
    talk(chat, clock, "mira", ["morning!"])
    assert "driving test is today" in model.last and "wish them luck" in model.last
    assert "driving test go" not in model.last                     # still ahead of it this morning
    clock.t = local(friday.year, friday.month, friday.day, 20, 0)
    talk(chat, clock, "mira", ["hiii"])
    assert '"how did your driving test go?"' in model.last
    clock.t += DAY
    talk(chat, clock, "mira", ["hey"])
    assert "driving test" not in model.last.split("mira says")[-1]     # once


def test_birthday_wish_on_the_day_and_nothing_for_possible_minors(memory, clock):
    chat, model = make(memory, clock)
    befriend(chat, clock)
    talk(chat, clock, "mira", ["it's my birthday tomorrow!!"])
    clock.t += DAY
    talk(chat, clock, "mira", ["hey star"])
    assert "today is their birthday" in model.last
    kid = memory.person("discord", "tim")
    memory.update(kid, stated_age=12)
    talk(chat, clock, "tim", ["i have a math test tomorrow"])
    assert chat.bonds.items(memory.known("discord", "tim"), "followup") == []      # no chat text kept about a minor


# -- felt gaps ------------------------------------------------------------------------------------------------------------

def test_a_new_chat_feels_the_gap(memory, clock):
    chat, model = make(memory, clock)
    befriend(chat, clock, convos=4)
    clock.t = local(2027, 1, 16, 10, 0)
    talk(chat, clock, "mira", ["hey"])
    assert "you last talked yesterday" in model.last
    talk(chat, clock, "mira", ["so anyway"])
    assert "you last talked" not in model.last and "earlier today" not in model.last     # same conversation
    clock.t += 4 * HOUR
    talk(chat, clock, "mira", ["back"])
    assert "already talked earlier today" in model.last
    clock.t += 2 * DAY
    talk(chat, clock, "mira", ["yo"])
    assert "two days ago" in model.last
    clock.t += 9 * DAY
    talk(chat, clock, "mira", ["hiii i'm back"])
    assert "glad to see again" in model.last and "missed them a bit" in model.last and "never as a complaint" in model.last


def test_felt_time_is_off_unless_the_setting_is_on(memory, clock):
    chat, model = make(memory, clock, felt=False)
    befriend(chat, clock)
    clock.t += 9 * DAY
    talk(chat, clock, "mira", ["hiii"])
    assert "glad to see again" in model.last and "missed them" not in model.last           # the old reunion line only
    stranger, model2 = make(memory, clock)
    talk(stranger, clock, "zed", ["hi"])
    clock.t += DAY
    talk(stranger, clock, "zed", ["hi again"])
    assert "you last talked" not in model2.last                                            # someone she just met


def test_settings_on_her_pc_off_elsewhere(tmp_path, monkeypatch):
    from star.inner import settings
    monkeypatch.setattr(settings, "own_pc", lambda: True)
    on = settings.load(tmp_path)
    assert settings.on(on, "felt_time") and settings.on(on, "initiative")
    monkeypatch.setattr(settings, "own_pc", lambda: False)
    off = settings.load(tmp_path)
    assert not settings.on(off, "felt_time") and not settings.on(off, "initiative")


# -- promises and shared moments -------------------------------------------------------------------------------------------

def test_her_promise_comes_back_when_due(memory, clock):
    chat, model = make(memory, clock, answer=lambda s, u: "omg yes i'll show you my castle tomorrow"
                       if "what did you build" in u.split("mira says")[-1] else "haha nice")
    befriend(chat, clock)
    talk(chat, clock, "mira", ["what did you build?"])
    clock.t += 3 * HOUR
    talk(chat, clock, "mira", ["hey"])
    assert "keep your word" not in model.last                       # not due yet
    clock.t += DAY
    talk(chat, clock, "mira", ["hey again"])
    assert "i'll show you my castle tomorrow" in model.last and "keep your word" in model.last


def test_inside_joke_comes_back_on_a_cue_then_rests(memory, clock):
    chat, model = make(memory, clock, answer="the haunted toaster strikes again")
    person = befriend(chat, clock)
    bonds = chat.bonds
    bonds._add_item(person, "joke", "the haunted toaster strikes again", "two days", clock.t, cap=8)
    talk(chat, clock, "mira", ["my toaster is making noises lol"])
    assert "An inside joke you two have" in model.last and "haunted toaster" in model.last
    talk(chat, clock, "mira", ["anyway how are you"])
    assert "haunted toaster" not in model.last.split("Recent chat")[0]          # no cue, mid-chat: not again
    clock.t += DAY
    talk(chat, clock, "mira", ["my toaster died"])
    assert "An inside joke" not in model.last                                     # one weak cue, still resting
    talk(chat, clock, "mira", ["the haunted toaster again"])
    assert "An inside joke" in model.last                                         # they bring it up themselves
    old = make(memory, clock, felt=False)[0]
    assert "Inside jokes:" in old.bonds.context(person, "discord", clock.t)       # the old behaviour without the setting


# -- initiative ------------------------------------------------------------------------------------------------------------

class Sent:
    def __init__(self, ok=True):
        self.ok, self.items = ok, []

    def __call__(self, platform, handle, text):
        self.items.append((platform, handle, text))
        return self.ok


def test_missing_a_close_friend_becomes_one_gentle_message(memory, clock, store):
    chat, _ = make(memory, clock)
    person = befriend(chat, clock)
    rng = random.Random(0)
    rng.random = lambda: 0.0                                                     # the "sometimes" always fires here
    ini = Initiative(memory, store, clock=clock, rng=rng)
    assert ini.missing() == []                                                   # heard from yesterday
    clock.t = local(2027, 1, 22, 14, 30)
    store.set_meta("initiative_miss_day", "")
    seeds = ini.missing()
    assert len(seeds) == 1 and ini.missing() == []                               # once a day
    sent = Sent()
    note = ini.deliver(sent)
    assert note.startswith("wrote first to mira") and len(sent.items) == 1
    platform, handle, text = sent.items[0]
    assert platform == "discord" and handle == "mira" and "miss you" not in text.lower()
    assert memory.moments(person, 1)[-1][1] == f"me: {text}"
    assert any(r["event"] == "reach_out" for r in memory.recent_log())
    clock.t += 4 * HOUR
    assert ini.deliver(Sent()) == ""                                             # unanswered: nothing more


def test_initiative_respects_quiet_hours_switch_and_guilt(memory, clock, store):
    chat, _ = make(memory, clock)
    person = befriend(chat, clock)
    off = Initiative(memory, store, clock=clock, enabled=False)
    assert off.missing() == [] and off.deliver(Sent()) == "" and off.on_promise(person, ft.Promise("x", clock.t, True)) is None
    needy = Initiative(memory, store, clock=clock, compose=lambda s, u: "i miss you so much, where did you go?")
    assert needy._seed("miss", person, needy.compose("miss", person), reason="t") is None      # guilt never stored
    ini = Initiative(memory, store, clock=clock)
    assert ini.on_promise(person, ft.Promise("i'll message you tomorrow", clock.t + 2 * HOUR, True)) is not None
    clock.t = local(2027, 1, 16, 23, 30)                                          # quiet hours
    assert ini.deliver(Sent()) == ""


def test_her_promise_to_message_becomes_a_seed_through_the_chat(memory, clock, store):
    ini = Initiative(memory, store, clock=clock)
    chat, _ = make(memory, clock, initiative=ini, answer=lambda s, u: "haha ok i'll message you tomorrow"
                   if "text me tomorrow" in u.split("mira says")[-1] else "lol same")
    befriend(chat, clock)
    talk(chat, clock, "mira", ["text me tomorrow ok?"])
    row = store.db.execute("SELECT kind, not_before FROM seeds").fetchone()
    assert row[0] == "promise" and row[1] > clock.t
    clock.t = row[1] + 1.5 * HOUR                                                  # noon, then her usual hour with Mira
    sent = Sent()
    assert ini.deliver(sent) and sent.items[0][2]


def test_something_she_did_reaches_the_friend_who_loves_it(memory, clock, store):
    chat, _ = make(memory, clock)
    befriend(chat, clock, "mira")
    befriend(chat, clock, "ana")
    talk(chat, clock, "mira", ["i love minecraft so much"])
    talk(chat, clock, "ana", ["i really like horror movies"])
    ini = Initiative(memory, store, clock=clock)
    assert ini.on_learned("minecraft building", "built a castle with a moat", verified=True) is not None
    assert ini.on_learned("minecraft building", "", verified=False) is None
    row = store.db.execute("SELECT pkey, kind, text FROM seeds").fetchone()
    assert row[1] == "share" and row[0].startswith(f"{memory.known('discord', 'mira').id}.")
    assert ini.on_learned("knitting", "a scarf", verified=True) is None                 # nobody likes it


def test_friend_online_seed_is_short_lived(memory, clock, store):
    chat, _ = make(memory, clock)
    person = befriend(chat, clock)
    ini = Initiative(memory, store, clock=clock, rng=random.Random(2))
    sid = ini.friend_online(person, "Minecraft")
    created, expires = store.db.execute("SELECT created, expires FROM seeds WHERE id = ?", (sid,)).fetchone()
    assert expires - created < 2 * HOUR


def test_discord_writes_first_only_when_nothing_is_unread(memory, clock, store):
    from star.social.activity import HumanPace
    from star.social.discord_desktop import DiscordDesktop
    chat, _ = make(memory, clock)
    befriend(chat, clock)
    ini = Initiative(memory, store, clock=clock)
    ini.on_promise(memory.known("discord", "mira"), ft.Promise("i'll message you tomorrow", clock.t + 600, True))
    clock.t += 20 * 60                                                            # 14:20, her usual hour with Mira

    class Host:
        def __init__(self):
            self.actions = []

        def focus_window(self, title):
            return True

        def foreground_title(self):
            return "Discord"

        def screenshot(self):
            return "shot.png"

        def key(self, combo):
            self.actions.append(("key", combo))

        def type_text(self, text):
            self.actions.append(("type", text))

    host = Host()
    unread = {"channel": "Ana", "is_dm": True, "messages": [{"author": "Ana", "text": "hey star"}]}
    view = {"value": unread}
    desk = DiscordDesktop(host, chat, reader=lambda png: view["value"], pace=HumanPace(sleep=lambda s: None),
                          initiative=ini)
    desk.step()
    assert store.db.execute("SELECT state FROM seeds").fetchone()[0] == "open"         # she answered Ana instead
    view["value"] = {"channel": "", "messages": []}
    clock.t += 5 * 60
    result = desk.step()
    assert result.acted and "wrote first to mira" in result.note and ("key", "ctrl+k") in host.actions
    assert store.db.execute("SELECT state FROM seeds").fetchone()[0] == "sent"


def test_a_cued_inside_joke_is_not_crowded_out_by_last_times_topic():
    from star.social.lifecycle import Touch
    touch = Touch("friend", "friend", True, 4.0, "friend", topic="finished my essay finally")
    assert "finished my essay" in touch.hint() and "finished my essay" not in touch.hint(skip_topic=True)
    assert "glad to see again" in touch.hint(skip_topic=True)
