"""STAR life extras (star/life): scrapbook + anniversaries, goals with proof, creative studio gallery, mood weather + API + widget.
Everything runs on fakes: a fake brain, fake makers, fake emotion states, temp folders. No model, no network beyond 127.0.0.1."""
import datetime as dt
import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import life
from star.life import api, goals, mood, scrapbook, studio, widget
from star.life.store import LifeStore

DAY = 86400.0


def at(year, month, day, hour=12):
    return time.mktime((year, month, day, hour, 0, 0, 0, 0, -1))


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock(at(2026, 10, 26))


@pytest.fixture
def store(tmp_path, clock):
    s = LifeStore(home=tmp_path, clock=clock)
    yield s
    s.close()


# ------------------------------------------------------------------------------------------------ scrapbook
def first_build(store, ts=at(2026, 9, 26), **kw):
    return scrapbook.add_moment(store, "first", "our first Minecraft build together", source="home-session:minecraft 2026-09-26",
                                feeling="Proud!", media="shots/build.png", ts=ts, first_key="minecraft_build", **kw)


def test_moment_needs_source_real_date_and_is_never_stored_twice(store, clock):
    assert scrapbook.add_moment(store, "first", "something we did", source="") is None
    assert scrapbook.add_moment(store, "first", "ok", source="owner-added") is None             # title too short
    assert scrapbook.add_moment(store, "nonsense", "something we did", source="owner-added") is None
    assert scrapbook.add_moment(store, "picture", "a picture of a lighthouse", source="owner-added",
                                ts=clock.now + 5 * DAY) is None                                   # the future
    assert first_build(store) is not None
    assert first_build(store) is None                                                              # same source
    assert scrapbook.add_moment(store, "first", "our first Minecraft build, again", source="home-session:other",
                                first_key="minecraft_build") is None                               # not the first
    saved = scrapbook.moments(store)[0]
    assert saved["feeling"] == "proud" and saved["media_kind"] == "screenshot"


def test_anniversary_only_from_a_real_dated_memory(store, clock):
    assert scrapbook.due(store, clock.now) is None                                                  # nothing stored: nothing said
    first_build(store)
    found = scrapbook.due(store, at(2026, 10, 26))
    assert found and found.label == "one month" and found.late_days == 0
    assert found.text == "One month ago today: the first time: our first Minecraft build together. I felt proud. I kept a screenshot."
    assert "our first Minecraft build together" in found.note and "only if it fits" in found.note
    assert scrapbook.due(store, at(2026, 10, 25)) is None                                           # the day before
    assert scrapbook.due(store, at(2026, 10, 28)).late_days == 2                                    # inside the grace
    assert scrapbook.due(store, at(2026, 10, 29)) is None                                           # too late


def test_anniversary_ignores_rows_without_a_source_and_future_rows(store, clock):
    store.run("INSERT INTO moments (ts, kind, title, source, created) VALUES (?,?,?,?,?)",
              (at(2026, 9, 26), "first", "an invented first", "", clock.now))
    store.run("INSERT INTO moments (ts, kind, title, source, created) VALUES (?,?,?,?,?)",
              (at(2026, 11, 26), "first", "a date in the future", "x-future", clock.now))
    assert scrapbook.due(store, at(2026, 10, 26)) is None


def test_anniversary_rate_limit_and_no_repeat(store, clock):
    for i, title in enumerate(["won the obby together", "drew a dragon together", "our first call", "built a castle"]):
        scrapbook.add_moment(store, "game_win", title, source=f"session-{i}", ts=at(2026, 9, 26) + i * 60)
    day = at(2026, 10, 26)
    first = scrapbook.due(store, day)
    scrapbook.mark_shown(store, first, day)
    assert scrapbook.due(store, day + 3600) is None                                                 # one a day
    nxt = scrapbook.due(store, at(2026, 10, 27))
    assert nxt and nxt.moment["id"] != first.moment["id"]                                           # the others are still inside the grace
    scrapbook.mark_shown(store, nxt, at(2026, 10, 27))
    assert scrapbook.due(store, at(2026, 10, 28)) is None                                           # two a week
    # a milestone is brought up once
    assert store.rows("SELECT count(*) FROM anniversaries")[0][0] == 2


def test_month_end_clamps(store):
    scrapbook.add_moment(store, "first", "our first call together", source="session-1", ts=at(2026, 1, 31))
    assert scrapbook.milestone_for(at(2026, 1, 31), dt.date(2026, 2, 28)) == ("one month", 0)
    assert scrapbook.due(store, at(2026, 2, 28)) is not None


def test_year_milestone(store):
    scrapbook.add_moment(store, "picture", "the first picture we made", source="session-1", ts=at(2025, 10, 26))
    assert scrapbook.due(store, at(2026, 10, 26)).label == "one year"


def test_chat_note_owner_only_and_marked_after_the_reply(tmp_path, clock):
    s = LifeStore(home=tmp_path, clock=clock)
    first_build(s)
    s.close()
    assert life.chat_note(tmp_path, owner=False, now=clock.now).text == ""                         # never in a friend's chat
    note = life.chat_note(tmp_path, now=clock.now)
    assert "anniversary" in note.text
    again = life.chat_note(tmp_path, now=clock.now)
    assert again.text == note.text                                                                  # not used up until done()
    note.done()
    assert life.chat_note(tmp_path, now=clock.now).text == ""
    (tmp_path / "settings.json").write_text(json.dumps({"life_scrapbook_enabled": False}))
    assert life.chat_note(tmp_path, now=clock.now).text == ""


def test_on_event_needs_the_owner(tmp_path, clock):
    ev = {"kind": "game_won", "title": "won the obby together", "source": "home-session:roblox 1", "with_owner": True}
    assert life.on_event({**ev, "with_owner": False}, tmp_path, now=clock.now) is None
    assert life.on_event({k: v for k, v in ev.items() if k != "source"}, tmp_path, now=clock.now) is None
    assert life.on_event(ev, tmp_path, now=clock.now) is not None


# ------------------------------------------------------------------------------------------------ what she wants to do
def idea(store, clock, *, interests=None, weak=None, mood_kind="", seen=None, friends=None, seed=1, **kw):
    """Make one wish happen (chance 1) with a fixed random stream."""
    return goals.form(store, interests or {}, weak if weak is not None else [], mood_kind=mood_kind, seen=seen, friends=friends,
                      now=kw.pop("now", clock.now), rng=random.Random(seed), chance=1.0, **kw)


def media_file(tmp_path, name="clip.mp4", size=10):
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return str(path)


def test_ideas_come_from_mood_interests_what_she_saw_friends_and_shaky_skills(store, clock):
    seen = idea(store, clock, seen=["a video about a dragon"])
    assert seen["origin"] == "seen" and seen["text"] == "ooh, I want to learn to draw dragons" and seen["domain"] == "drawing"
    friend = idea(store, clock, friends=["my friend keeps building a castle in minecraft"])
    assert friend["origin"] == "friend" and friend["text"].startswith("my friend makes this look fun, I want to")
    stormy = idea(store, clock, mood_kind="stormy", seed=3)
    assert stormy["origin"] == "mood" and stormy["text"].startswith("need to blow off some steam, I want to")
    weak = idea(store, clock, weak=["luau: tweens"])
    assert weak["origin"] == "weak" and weak["want"] == "learn tweens properly" and weak["interest"] == "practice"
    goals.finish(store, seen["id"], now=clock.now)                      # room for one more
    interest = idea(store, clock, interests={"music": {"weight": 1.0}})
    assert interest["origin"] == "interest" and interest["text"] == "I want to make a loop I would play for a friend"
    assert len(goals.goals(store, goals.LIVE)) == 4


def test_not_every_time_and_never_a_pile_and_no_instant_repeat(store, clock):
    assert goals.form(store, {"drawing": {"weight": 1}}, [], now=clock.now, rng=random.Random(1), chance=0.0) is None
    for want in ("dragon", "obby", "castle", "song"):
        assert idea(store, clock, seen=[want]) is not None
    assert idea(store, clock, seen=["pixel"]) is None                                          # four at a time is plenty
    g = goals.goals(store)[0]
    goals.drop(store, g["id"], now=clock.now)
    assert idea(store, clock, seen=["dragon"], now=clock.now + 2 * DAY) is None                # not the one she just let go of
    assert idea(store, clock, seen=["dragon"], now=clock.now + 20 * DAY) is not None           # but she can come back to it


def test_she_words_it_herself_when_the_brain_helps(store, clock):
    said = idea(store, clock, seen=["dragon"], complete=lambda s, u: "ok i'm drawing a dragon i love this week!")
    assert said["text"] == "ok i'm drawing a dragon i love this week!"
    junk = idea(store, clock, seen=["obby"], complete=lambda s, u: "Let me think step by step about this goal.")
    assert junk["text"] == "ooh, I want to beat a really hard obby"


def test_finishing_and_giving_up_are_just_her_decisions(store, clock):
    a = idea(store, clock, seen=["dragon"])
    b = idea(store, clock, seen=["obby"])
    done = goals.finish(store, a["id"], now=clock.now + 1)                  # no proof, no reason, no form
    assert done["status"] == "done" and done["words"] == ""
    gone = goals.drop(store, b["id"], "eh, I got bored of obbies", now=clock.now + 2)
    assert gone["status"] == "dropped" and gone["words"] == "eh, I got bored of obbies"
    c = idea(store, clock, seen=["castle"])
    assert goals.drop(store, c["id"], now=clock.now + 3)["status"] == "dropped"      # not even a word
    assert goals.practice(store, a["id"], "again", True)["status"] == "done"          # closed ones simply stay closed


def test_keenness_fades_a_bored_wish_is_put_aside_or_let_go_and_a_stirred_one_comes_back(store, clock):
    outcomes = set()
    for seed in range(12):
        s = LifeStore(path=":memory:", clock=clock)
        g = idea(s, clock, seen=["dragon"], seed=seed)
        goals._set(s, g["id"], keen=0.1)
        (event,) = goals.drift(s, clock.now + 2 * DAY, rng=random.Random(seed))
        outcomes.add(event["event"])
        assert goals.get(s, g["id"])["status"] in ("paused", "dropped")
        s.close()
    assert outcomes == {"paused", "dropped"}
    g = idea(store, clock, seen=["dragon"])
    goals.pause(store, g["id"], clock.now)
    goals._set(store, g["id"], keen=0.2)
    assert goals.drift(store, clock.now + 2 * DAY, rng=random.Random(1)) == []                        # nothing stirs it yet
    goals._set(store, g["id"], keen=0.3)
    events = goals.drift(store, clock.now + 4 * DAY, rng=random.Random(1), seen=["a video about a dragon"])
    assert events == [{"id": g["id"], "event": "resumed"}] and goals.get(store, g["id"])["status"] in ("open", "active")


class Fixed(random.Random):
    """A random stream that always rolls the same number (uniform() then returns its low end when 0)."""

    def __init__(self, value):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


def test_a_wish_she_forgot_for_a_month_quietly_fades_out(store, clock):
    g = idea(store, clock, seen=["dragon"])
    goals.pause(store, g["id"], clock.now)
    goals._set(store, g["id"], keen=0.2)
    assert goals.drift(store, clock.now + 40 * DAY, rng=Fixed(0.0)) == [{"id": g["id"], "event": "dropped"}]
    assert goals.get(store, g["id"])["status"] == "dropped"


def test_one_she_did_well_at_for_a_while_is_called_good_enough(store, clock):
    g = idea(store, clock, seen=["castle"])
    goals.practice(store, g["id"], "one", True, now=clock.now)
    goals.practice(store, g["id"], "two", True, now=clock.now)
    goals._set(store, g["id"], keen=0.31, updated=clock.now)
    assert goals.drift(store, clock.now + 3 * DAY, rng=Fixed(0.0)) == [{"id": g["id"], "event": "finished"}]
    done = goals.get(store, g["id"])
    assert done["status"] == "done" and done["words"] == "I'm happy with how far I got"


def test_some_days_she_does_not_feel_like_it_and_that_shows_in_her_diary(store, clock):
    g = idea(store, clock, seen=["dragon"])
    assert goals.p_put_off({**g, "keen": 0.9}) < goals.p_put_off({**g, "keen": 0.2})
    goals.procrastinate(store, g["id"], now=clock.now)
    assert "Didn't feel like working on learn to draw dragons today." in goals.diary_text(store, 3, clock.now)


def test_practice_moves_keenness_and_wakes_a_put_aside_wish(store, clock):
    g = idea(store, clock, seen=["dragon"])
    goals._set(store, g["id"], keen=0.5)
    assert goals.practice(store, g["id"], "fell", False, now=clock.now)["keen"] < 0.5
    assert goals.practice(store, g["id"], "nice", True, now=clock.now)["keen"] > 0.46
    goals.pause(store, g["id"], clock.now)
    back = goals.practice(store, g["id"], "bored, tried anyway", True, now=clock.now + 1)
    assert back["status"] == "active" and any(l["kind"] == "resumed" for l in goals.log(store, g["id"]))


class Roll:
    """A random stream that always rolls the same number."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_whether_it_counts_as_done_is_her_call(store, clock, tmp_path):
    a = idea(store, clock, seen=["obby"])
    assert goals.judge(store, a["id"], {"verified": False}, Roll(0.0)) is False
    assert goals.judge(store, a["id"], {"verified": True, "summary": "won"}, Roll(0.9)) is False          # a first win, not sure yet
    assert goals.judge(store, a["id"], {"verified": True, "summary": "won"}, Roll(0.1)) is True           # sometimes it just feels done
    b = idea(store, clock, seen=["dragon"])
    clip = media_file(tmp_path)
    assert goals.judge(store, b["id"], {"verified": True, "evidence": [clip]}, Roll(0.99)) is True        # clearly worked: done
    assert goals.get(store, b["id"])["status"] == "done"


def test_what_she_remembers_decides_how_sure_she_sounds(store, clock, tmp_path):
    g = idea(store, clock, seen=["obby"])
    assert goals.level_of(store, g) == "none"
    g = goals.practice(store, g["id"], "fell", False, now=clock.now)
    assert goals.level_of(store, g) == "tried"
    g = goals.practice(store, g["id"], "got further", True, now=clock.now)
    assert goals.level_of(store, g) == "think"
    clip = media_file(tmp_path, "win.mp4")
    g = goals.practice(store, g["id"], "won", True, ref=clip, sure=True, now=clock.now)
    assert goals.level_of(store, g) == "sure" and goals.shareable(g) == clip
    import os
    os.remove(clip)
    assert goals.level_of(store, g) == "think" and goals.shareable(g) == ""                      # the clip is gone: she says less


def test_announcements_are_honest_and_never_sound_like_a_form(store, clock, tmp_path):
    g = idea(store, clock, seen=["obby"])
    goals.finish(store, g["id"], now=clock.now)                          # she feels done, but nothing worked on record
    done = goals.get(store, g["id"])
    sentence, _ = goals.announcement(store, done)
    assert "not there yet" in sentence and "did it" not in sentence
    goals._set(store, g["id"], ok_tries=1)
    sentence, note = goals.announcement(store, goals.get(store, g["id"]))
    assert "I think" in sentence or "might" in sentence or "?" in sentence
    assert "not completely sure" in note
    clip = media_file(tmp_path)
    goals._set(store, g["id"], sure=1, evidence=json.dumps([{"ref": clip, "at": 1}]))
    sentence, note = goals.announcement(store, goals.get(store, g["id"]))
    assert "clip if you want to see it" in sentence and clip in note and "sure it worked" in note
    for text in (sentence, note):
        assert not re.search(r"proof|verified|status|ticket|required|checked", text, re.I)


def test_outgoing_claims_are_softened_to_what_she_can_honestly_say(store, clock):
    g = idea(store, clock, seen=["obby"])
    claim = "I finally beat that really hard obby! Anyway how was your day."
    assert goals.honest_text(store, claim) == "I've been trying to beat a really hard obby, not there yet. Anyway how was your day."
    goals.practice(store, g["id"], "got further", True, now=clock.now)
    assert goals.honest_text(store, claim).startswith("I think I'm getting somewhere with wanting to beat a really hard obby!")
    goals.practice(store, g["id"], "won", True, sure=True, now=clock.now)
    assert goals.honest_text(store, claim) == claim                       # it really happened: say it loud
    other = "I finally beat my own record at tic tac toe!"
    assert goals.honest_text(store, other) == other                       # not about any of her wishes
    assert goals.honest_text(store, "I want to beat that obby someday") == "I want to beat that obby someday"
    assert life.honest(claim, None) is not None


def test_a_finished_wish_is_told_once_and_only_as_much_as_she_can_honestly_say(tmp_path, clock):
    s = LifeStore(home=tmp_path, clock=clock)
    a = idea(s, clock, seen=["obby"])
    b = idea(s, clock, seen=["dragon"])
    goals.finish(s, a["id"], now=clock.now)                                 # nothing worked on record: nothing to brag about
    clip = media_file(tmp_path)
    goals.practice(s, b["id"], "drew it", True, ref=clip, sure=True, now=clock.now)
    goals.finish(s, b["id"], now=clock.now)
    s.close()
    note = life.chat_note(tmp_path, now=clock.now)
    assert "learn to draw dragons" in note.text and clip in note.text and "beat a really hard obby" not in note.text
    assert not re.search(r"proof|verified|required", note.text, re.I)
    note.done()
    assert life.chat_note(tmp_path, now=clock.now).text == ""
    assert goals.get(life.default_store(tmp_path), a["id"])["announced"] == 1


def test_her_diary_reads_like_a_diary_not_a_ticket_system(store, clock):
    a = idea(store, clock, seen=["dragon"])
    b = idea(store, clock, seen=["obby"])
    c = idea(store, clock, seen=["castle"])
    goals.practice(store, a["id"], "ok", False, now=clock.now)
    goals.practice(store, a["id"], "ok", True, now=clock.now)
    goals.pause(store, b["id"], clock.now)
    goals.drop(store, c["id"], "eh, I got bored of building", now=clock.now)
    goals.finish(store, a["id"], "that was really fun", now=clock.now)
    text = goals.diary_text(store, 3, clock.now)
    assert "New idea: ooh, I want to learn to draw dragons (I saw something about it)." in text
    assert "Tried to learn to draw dragons. Not working yet, a bit annoying." in text
    assert "Got distracted from wanting to beat a really hard obby. Maybe later." in text
    assert "Let go of wanting to build a castle: eh, I got bored of building." in text
    assert "that was really fun." in text
    assert not re.search(r"streak|proof|status|ticket|abandon|goal|complete|verified|reason", text, re.I)


def test_skill_confidence_moves_with_how_it_goes_and_feeds_the_review_text(store, clock):
    g = idea(store, clock, weak=["luau: tweens"])
    goals.practice(store, g["id"], "failed", False, now=clock.now)
    low = goals.skill_confidence(store)["luau:tweens"]
    assert low < 0.5 and "luau:tweens" in goals.weak_skills(store, below=0.5)
    goals.practice(store, g["id"], "passed", True, sure=True, now=clock.now + 1)
    goals.finish(store, g["id"], "finally", now=clock.now + 3)
    assert goals.skill_confidence(store)["luau:tweens"] > low
    text = goals.evidence_text(store, clock.now + 4)
    assert "learn tweens properly" in text and "luau:tweens" in text and "proof" not in text.lower()


def test_evidence_from_outcome_never_invents(store, clock, tmp_path):
    g = idea(store, clock, seen=["obby"])
    assert goals.evidence_from_outcome(g, {"evidence": ["won the round", "saved clip nowhere.mp4"]}) is None
    clip = media_file(tmp_path, "round.mp4")
    assert goals.evidence_from_outcome(g, {"evidence": [f"clip {clip}"]}) == {"kind": "clip", "ref": clip}
    assert goals.evidence_from_outcome(g, {"proof": {"kind": "test"}}) == {"kind": "test"}


def test_after_session_counts_an_attempt_and_her_judgement_decides(tmp_path, clock):
    s = LifeStore(home=tmp_path, clock=clock)
    g = idea(s, clock, seen=["obby"], now=time.time() - 60)
    s.close()
    out = life.after_session(tmp_path, "play_games", "roblox", {"verified": True, "summary": "won", "evidence": ["won"]}, rng=Roll(0.9))
    assert "goal_done" not in out and goals.get(life.default_store(tmp_path), g["id"])["tries"] == 1
    clip = media_file(tmp_path, "w.mp4")
    out = life.after_session(tmp_path, "play_games", "roblox", {"verified": True, "summary": "won", "evidence": [clip],
                                                                "moment": {"kind": "game_won", "title": "won the obby together",
                                                                           "with_owner": True}}, rng=Roll(0.5))
    assert out["goal_done"] == g["id"] and out["moment"] is True
    assert life.after_session(tmp_path, "play_games", "x", {"life_counted": True}) == {}
    # without any clip she can still feel it is done, but then she only says she thinks so
    s2 = life.default_store(tmp_path)
    h = idea(s2, clock, seen=["castle"], now=time.time() - 60)
    life.after_session(tmp_path, "game_making", "build", {"verified": True, "summary": "built it"}, rng=Roll(0.05))
    assert goals.get(s2, h["id"])["status"] == "done" and goals.level_of(s2, goals.get(s2, h["id"])) == "think"


def test_goal_activity_practises_through_a_home_activity_or_puts_it_off(tmp_path, monkeypatch):
    from star.home.activities import Context, Registry
    calls = []

    def play(ctx):
        calls.append(ctx.goal["text"])
        return {"ok": True, "verified": False, "summary": "fell off", "evidence": []}

    registry = Registry()
    registry.register("roblox", "play_games", play, "play")
    life.register_home_activities(registry)
    assert {"creative studio", "studio drawing", "pursue a goal", "personal style"} <= set(registry.items)
    s = life.default_store(tmp_path)
    g = goals.form(s, {}, [], seen=["obby"], now=time.time() - 5, rng=random.Random(1), chance=1.0)
    queue = tmp_path / "curiosity.jsonl"
    monkeypatch.setenv("STAR_CURIOSITY_FILE", str(queue))
    ctx = Context(home=tmp_path, config={}, executor=None, life=None, chat=None, interest="personal_goals", goal=None)
    monkeypatch.setattr(goals, "p_put_off", lambda goal: 1.0)
    out = registry.items["pursue a goal"].run(ctx)
    assert calls == [] and "did not feel like" in out["summary"] and goals.get(s, g["id"])["tries"] == 0
    assert "Didn't feel like" in goals.diary_text(s, 3, time.time())
    monkeypatch.setattr(goals, "p_put_off", lambda goal: 0.0)
    out = registry.items["pursue a goal"].run(ctx)
    assert calls == [g["want"]] and out["life_counted"] is True and out["verified"] is False
    assert goals.get(s, g["id"])["tries"] == 1 and goals.get(s, g["id"])["status"] == "active"
    assert queue.exists() and "star life goal" in queue.read_text(encoding="utf-8")


def test_tick_lets_wishes_drift_and_has_a_thought_every_few_hours(tmp_path, clock):
    life_obj = SimpleNamespace(interests=lambda: {"drawing": {"weight": 1.0}}, add_goal=lambda i, t: {"id": "g9"},
                               set_goal=lambda i, s: None, history=lambda n: [])
    formed = None
    for seed in range(20):
        home = tmp_path / f"h{seed}"
        out = life.tick(home, life=life_obj, now=clock.now, rng=random.Random(seed), mood_kind="starry")
        assert out["events"] == []
        if out["new_goals"]:
            formed = (home, out)
            break
    assert formed is not None
    home = formed[0]
    again = life.tick(home, life=life_obj, now=clock.now + 3600, rng=random.Random(1), mood_kind="starry")
    assert "new_goals" not in again and "events" in again                   # a thought only every six hours, drift every hour
    assert "error" not in life.tick(tmp_path / "none", life=None, now=clock.now, mood_kind="")


# ------------------------------------------------------------------------------------------------ studio
def fake_brain(ideas="a robot who learns to whistle"):
    def complete(system, user):
        if "Answer ONLY with JSON" in system:
            return json.dumps({"why": "I wanted to try something gentle after a hard day.",
                               "improve": "Make the shadows softer next time.", "feeling": "calm"})
        if "one idea" in system:
            return ideas
        if "Luau" in system:
            return "local part = Instance.new('Part')\npart.Parent = workspace"
        if "song" in system:
            return "Whistle Robot\nverse one words\nverse two words\nhook words"
        if "journal" in system:
            return "Today I fell off the obby twice and then I did not."
        return "The Robot Who Whistled\nOnce there was a robot."
    return complete


def fake_drawer(tmp_path):
    def generate(prompt):
        path = tmp_path / "pic.png"
        path.write_bytes(b"png")
        generate.prompts.append(prompt)
        return path
    generate.prompts = []
    return generate


def test_make_work_records_gallery_entry_with_her_commentary(store, tmp_path, clock):
    out = studio.make_work(store, kind="story", complete=fake_brain(), now=clock.now, rng=random.Random(1),
                           emotion=SimpleNamespace(on_event=lambda *a, **k: None))
    assert out["ok"] and out["verified"] and "The Robot Who Whistled" in out["summary"]
    (w,) = studio.works(store)
    assert w["kind"] == "story" and w["verified"] == 1 and w["why"].startswith("I wanted") and "shadows" in w["improve"]
    assert "robot who learns to whistle" in w["theme"]
    assert "next time:" in studio.gallery_text(store)


def test_no_brain_means_pending_commentary_never_a_made_up_one(store, tmp_path, clock):
    maker = {"drawing": studio.make_drawing}
    drawer = fake_drawer(tmp_path)
    out = studio.make_work(store, kind="drawing", complete=None, now=clock.now, makers=maker, generate=drawer,
                           emotion=SimpleNamespace(on_event=lambda *a, **k: None))
    assert out["verified"] and "commentary pending" in out["summary"]
    assert studio.works(store)[0]["why"] == ""
    assert studio.fill_commentary(store, fake_brain()) == 1
    assert studio.works(store)[0]["why"]


def test_drawing_uses_and_extends_her_style_notes(store, tmp_path, clock):
    drawer = fake_drawer(tmp_path)
    for i in range(2):
        studio.make_work(store, kind="drawing", complete=fake_brain(ideas=f"idea number {i} about moon bakeries"), now=clock.now + i * DAY,
                         makers={"drawing": studio.make_drawing}, generate=drawer, emotion=SimpleNamespace(on_event=lambda *a, **k: None))
    assert "shadows softer" in drawer.prompts[1] and "shadows softer" not in drawer.prompts[0]
    assert studio.style_notes(store).count("shadows softer") == 2


def test_unusable_pipeline_records_nothing(store, clock):
    def broken(store, theme, **kw):
        raise studio.MakerUnavailable("ComfyUI is not running")
    out = studio.make_work(store, kind="drawing", complete=fake_brain(), now=clock.now, makers={"drawing": broken})
    assert not out["ok"] and "ComfyUI" in out["summary"] and studio.works(store) == []


def test_missing_file_is_not_verified(store, clock):
    def liar(store, theme, **kw):
        return {"path": str(store.home / "never-made.png"), "title": "ghost", "status": "finished"}
    out = studio.make_work(store, kind="drawing", complete=fake_brain(), now=clock.now, makers={"drawing": liar},
                           emotion=SimpleNamespace(on_event=lambda *a, **k: pytest.fail("felt a creation that is not there")))
    assert out["ok"] and not out["verified"] and studio.works(store)[0]["verified"] == 0


def test_song_is_a_lyrics_draft_without_singing_and_finished_with_it(store, tmp_path, clock):
    quiet = studio.make_song(store, "a rainy-window song", complete=fake_brain(), now=clock.now, sing=None)
    # no singer module exists in this tree, so find_singer() found nothing either
    assert quiet["status"] == "lyrics_draft" and quiet["path"].endswith(".lyrics.md")

    def sing(lyrics, title, folder):
        path = folder / "song.wav"
        path.write_bytes(b"RIFF")
        return path
    sung = studio.make_song(store, "a rainy-window song", complete=fake_brain(), now=clock.now, sing=sing)
    assert sung["status"] == "finished" and sung["path"].endswith("song.wav")


def test_roblox_experiment_stays_a_draft_until_her_test_place_ran_it(store, clock):
    draft = studio.make_roblox(store, "a pad that changes colour", complete=fake_brain(), now=clock.now)
    assert draft["status"] == "draft" and draft["path"].endswith(".luau")
    ran = studio.make_roblox(store, "a pad that changes colour", complete=fake_brain(), now=clock.now,
                             studio_runner=lambda code, name: {"ok": True, "note": "ran in her test place"})
    failed = studio.make_roblox(store, "a pad that changes colour", complete=fake_brain(), now=clock.now,
                                studio_runner=lambda code, name: {"ok": False, "note": "error line 3"})
    assert ran["status"] == "finished" and failed["status"] == "draft" and "error line 3" in failed["note"]


def test_variety_novelty_and_schedule(store, tmp_path, clock):
    rng = random.Random(3)
    for i in range(6):
        studio.add_work(store, "drawing", f"drawing {i}", theme=f"a dragon number {i}", now=clock.now - (i + 1) * DAY)
    counts = {k: 0 for k in studio.KINDS}
    for _ in range(400):
        counts[studio.pick_kind(store, clock.now, rng)] += 1
    assert counts["drawing"] < min(counts["story"], counts["song"])                                 # she has drawn a lot lately
    assert studio.pick_kind(store, clock.now, rng, ("roblox",)) == "roblox"
    studio.add_work(store, "story", "s", theme="a cloud that wanted to be a boat", now=clock.now - 4 * 3600)
    theme = studio.pick_theme(store, "story", rng=random.Random(5), wanted="a cloud that wanted to be a boat")
    assert theme != "a cloud that wanted to be a boat"                                              # repeats are skipped
    assert studio.schedule_ok(store, clock.now) == ""
    studio.add_work(store, "story", "s2", now=clock.now - 3600)
    assert "pausing" in studio.schedule_ok(store, clock.now, per_day=5)
    studio.add_work(store, "story", "s3", now=clock.now - 60)
    assert "already" in studio.schedule_ok(store, clock.now)


def test_studio_activity_off_switch_and_run(tmp_path):
    from star.home.activities import Context, Registry
    registry = Registry()
    life.register_home_activities(registry)
    stories = registry.items["creative studio"]
    ctx = Context(home=tmp_path, config={}, executor=None, life=SimpleNamespace(history=lambda n: [{"interest": "drawing",
                  "summary": "drew a lighthouse", "verified": True}]), chat=lambda messages, tools: {"content": fake_brain()(
                      messages[0]["content"], messages[1]["content"])}, interest="creative_studio", goal=None)
    out = stories.run(ctx)
    assert out["ok"] and out["verified"] and studio.works(life.default_store(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"life_studio_enabled": False}))
    assert "switched off" in stories.run(ctx)["summary"]


# ------------------------------------------------------------------------------------------------ mood weather
BASE = {n: v for n, v in __import__("star.emotion_model", fromlist=["BASELINE"]).BASELINE.items()}


def state(**raised):
    emotions = dict(BASE)
    for name, level in raised.items():
        emotions[name] = level
    return {"emotions": emotions, "valence": 0.2, "arousal": 0.4}


@pytest.mark.parametrize("raised,hour,expected", [
    ({"joy": 0.7, "pride": 0.6}, 14, "sunny"),
    ({"anger": 0.5}, 14, "stormy"),
    ({"frustration": 0.4, "sadness": 0.3}, 14, "stormy"),
    ({"sadness": 0.4}, 14, "cloudy"),
    ({"loneliness": 0.3}, 3, "cloudy"),
    ({"nostalgia": 0.5}, 14, "starry"),
    ({"hope": 0.6, "joy": 0.35}, 14, "starry"),
    ({}, 14, "sunny"),
    ({}, 23, "starry"),
    ({}, 5, "starry"),
])
def test_weather_mapping(raised, hour, expected):
    assert mood.weather_from(state(**raised), [], hour=hour).kind == expected


def test_weather_is_off_without_emotion_state():
    w = mood.weather_from(None)
    assert w.kind == "off" and "switched off" in w.why


def test_why_line_is_a_fixed_phrase_for_the_latest_recent_event_and_never_the_detail():
    now = at(2026, 10, 26, 15)
    history = [{"at": now - 3600, "kind": "bug_fixed", "strength": 1, "detail": "secret friend name Sam password hunter2"},
               {"at": now - 7200, "kind": "task_failure", "strength": 1, "detail": "x"}]
    why = mood.weather_from(state(joy=0.7), history, hour=15, now=now).why
    assert why == "she fixed something that fought back" and "Sam" not in why
    old = [{"at": now - 30 * 3600, "kind": "bug_fixed", "strength": 1, "detail": ""}]
    assert mood.weather_from(state(joy=0.7), old, hour=15, now=now).why == mood.FALLBACK["sunny"]
    unknown = [{"at": now - 60, "kind": "some_new_kind", "strength": 1, "detail": "private"}]
    assert mood.weather_from(state(joy=0.7), unknown, hour=15, now=now).why == mood.FALLBACK["sunny"]


def test_payload_reads_emotion_only_through_its_api_and_respects_the_setting():
    class Emotion:
        def __init__(self, on):
            self.on = on

        def enabled(self, home=None):
            return self.on

        def current(self, home=None):
            return state(anger=0.6)

        def default_engine(self, home=None):
            return SimpleNamespace(history=lambda n: [{"at": time.time(), "kind": "insulted", "strength": 1, "detail": "d"}])

    on = mood.payload(emotion=Emotion(True))
    assert on["kind"] == "stormy" and on["why"] == "someone was unkind to her" and set(on) == {
        "kind", "label", "why", "icon", "dominant", "at"}
    assert mood.payload(emotion=Emotion(False))["kind"] == "off"
    assert mood.payload(emotion=object())["kind"] == "off"                                          # a broken engine shows "off"


# ------------------------------------------------------------------------------------------------ status API + widget
@pytest.fixture
def server(tmp_path, clock):
    (tmp_path / "settings.json").write_text(json.dumps({"life_api_enabled": True}))
    s = LifeStore(home=tmp_path, clock=clock)
    studio.add_work(s, "story", "The Robot Who Whistled", why="I wanted something gentle.", improve="Shorter sentences.",
                    now=clock.now)
    goals.form(s, {"drawing": {"weight": 1}}, [], now=clock.now, rng=random.Random(1), chance=1.0)
    emotion = SimpleNamespace(enabled=lambda home=None: True, current=lambda home=None: state(joy=0.7),
                              default_engine=lambda home=None: SimpleNamespace(history=lambda n: []))
    httpd = api.serve(tmp_path, host="127.0.0.1", port=0, emotion=emotion, store=s)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    token = api.read_token(tmp_path)
    yield SimpleNamespace(url=f"http://127.0.0.1:{httpd.server_address[1]}", token=token, home=tmp_path)
    httpd.shutdown()
    httpd.server_close()
    s.close()


def request(server, path, token="", method="GET"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(server.url + path, headers=headers, method=method, data=b"" if method != "GET" else None)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8")


def test_api_needs_the_token_and_is_read_only(server):
    assert request(server, "/life/mood")[0] == 401
    assert request(server, "/life/mood", "wrong")[0] == 401
    code, body = request(server, "/life/mood", server.token)
    assert code == 200 and json.loads(body)["kind"] == "sunny"
    assert request(server, "/life/mood", server.token, "POST")[0] == 405
    assert request(server, "/life/nothing", server.token)[0] == 404


def test_api_journal_holds_her_commentary_and_diary_but_no_token(server):
    code, text = request(server, "/life/journal", server.token)
    assert code == 200 and "The Robot Who Whistled" in text and "I wanted something gentle." in text and "WHAT I WANT TO DO" in text
    assert "New idea: I want to draw a dragon I'm proud of" in text
    assert server.token not in text


def test_api_is_off_by_default(tmp_path):
    with pytest.raises(RuntimeError):
        api.serve(tmp_path, port=0)


def test_token_is_created_once_and_never_empty(tmp_path):
    first = api.read_token(tmp_path)
    assert len(first) >= 32 and api.read_token(tmp_path) == first


def test_widget_states_and_offline_is_not_a_guess():
    assert widget.state_of({"kind": "starry", "why": "a calm, quiet stretch"})["icon"] == mood.ICONS["starry"]
    assert widget.state_of({"kind": "stormy", "why": "someone was unkind to her"})["kind"] == "stormy"
    assert widget.state_of({"kind": "volcano"})["kind"] == "offline"
    assert widget.state_of(None, "boom")["why"] == "boom"
    assert set(widget.COLORS) >= set(mood.ICONS) | {"offline"}


def test_widget_refresh_and_journal_with_a_fake_api(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("abc\n")
    config = widget.WidgetConfig("http://her-pc:8765", str(token_file), 60, False)
    seen = []

    def get(url, token):
        seen.append((url, token))
        if url.endswith("/life/mood"):
            return json.dumps({"kind": "cloudy", "why": "a slow, quiet stretch"})
        return "<script>alert(1)</script> my journal"

    w = widget.Widget(config, get=get)
    assert w.refresh()["kind"] == "cloudy" and seen[0] == ("http://her-pc:8765/life/mood", "abc")
    opened = []
    assert w.open_journal(opened.append) is True
    page = (Path(widget.tempfile.gettempdir()) / "star-journal.html").read_text(encoding="utf-8")
    assert opened[0].startswith("file:")
    assert "&lt;script&gt;" in page and "<script>" not in page
    w2 = widget.Widget(config, get=lambda u, t: (_ for _ in ()).throw(urllib.error.URLError("down")))
    assert w2.refresh()["kind"] == "offline" and w2.open_journal(opened.append) is False
    assert widget.Widget(widget.WidgetConfig("", "", 60, False)).refresh()["kind"] == "offline"


def test_widget_config_roundtrip_and_opt_in(tmp_path):
    widget.WidgetConfig("http://x:1", "t.txt", 5, True).save(tmp_path)
    loaded = widget.WidgetConfig.load(tmp_path)
    assert loaded.url == "http://x:1" and loaded.poll_s == widget.MIN_POLL_S and loaded.always_on_top is True
    assert life.flag("life_widget_enabled", tmp_path) is False and life.flag("life_api_enabled", tmp_path) is False
    assert life.flag("life_scrapbook_enabled", tmp_path) and life.flag("life_goals_enabled", tmp_path) and life.flag("life_studio_enabled", tmp_path)


def test_nightly_self_review_reads_her_diary_and_skills(tmp_path, clock):
    from star.inner import night
    assert night._life_evidence(None) == "" and night._life_evidence(tmp_path) == ""
    s = life.default_store(tmp_path)
    g = goals.form(s, {}, ["luau: tweens"], now=time.time(), rng=random.Random(1), chance=1.0)
    goals.practice(s, g["id"], "failed", False)
    assert "luau:tweens" in night._life_evidence(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"life_goals_enabled": False}))
    assert night._life_evidence(tmp_path) == ""
