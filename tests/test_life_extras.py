"""STAR life extras (star/life): scrapbook + anniversaries, goals with proof, creative studio gallery, mood weather + API + widget.
Everything runs on fakes: a fake brain, fake makers, fake emotion states, temp folders. No model, no network beyond 127.0.0.1."""
import datetime as dt
import json
import random
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


# ------------------------------------------------------------------------------------------------ goals
def proof_file(tmp_path, name="clip.mp4", size=10, mtime=None):
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return str(path)


def test_propose_from_weak_skills_and_interests_with_novelty(store, clock):
    made = goals.propose(store, {"drawing": {"weight": 2.0}}, ["luau: tweens"], now=clock.now)
    assert len(made) == 1 and made[0]["domain"] == "luau" and made[0]["proof_kind"] == "test" and "tweens" in made[0]["text"]
    more = goals.propose(store, {"drawing": {"weight": 2.0}}, [], now=clock.now, max_new=5)
    assert [g["domain"] for g in more] == ["drawing"]
    assert goals.propose(store, {"play_games": {"weight": 1}}, ["obby: moving platforms"], now=clock.now, max_new=5)
    assert len(goals.goals(store, ("open", "active"))) == 3
    assert goals.propose(store, {"music": {"weight": 1}}, [], now=clock.now, max_new=5) == []        # MAX_OPEN


def test_dropped_goal_is_not_repeated_for_two_weeks(store, clock):
    (g,) = goals.propose(store, {"drawing": {"weight": 1}}, [], now=clock.now)
    goals.abandon(store, g["id"], "I do not feel like drawing dragons now", now=clock.now)
    assert goals.propose(store, {"drawing": {"weight": 1}}, [], now=clock.now + 2 * DAY) == []
    assert goals.propose(store, {"drawing": {"weight": 1}}, [], now=clock.now + 20 * DAY)


def test_rephrase_uses_her_words_only_when_usable(store, clock):
    said = goals.propose(store, {"drawing": {"weight": 1}}, [], complete=lambda s, u: "ok i'm drawing a dragon i love this week!",
                         now=clock.now)
    assert said[0]["text"] == "ok i'm drawing a dragon i love this week!"
    junk = goals.propose(store, {"play_games": {"weight": 1}}, [], complete=lambda s, u: "Let me think step by step about this goal.",
                         now=clock.now)
    assert junk[0]["text"].startswith("Beat the obby")


def test_goal_lifecycle_needs_proof(store, clock, tmp_path):
    (g,) = goals.propose(store, {"play_games": {"weight": 1}}, [], now=clock.now)
    assert g["status"] == "open" and g["proof_kind"] == "clip"
    with pytest.raises(goals.GoalError, match="screenshot, a clip"):
        goals.complete(store, g["id"], None, now=clock.now)
    with pytest.raises(goals.GoalError, match="does not exist"):
        goals.complete(store, g["id"], {"kind": "clip", "ref": str(tmp_path / "nope.mp4")}, now=clock.now)
    with pytest.raises(goals.GoalError, match="empty"):
        goals.complete(store, g["id"], {"kind": "clip", "ref": proof_file(tmp_path, "empty.mp4", 0)}, now=clock.now)
    with pytest.raises(goals.GoalError, match="older than the goal"):
        goals.complete(store, g["id"], {"kind": "clip", "ref": proof_file(tmp_path, "old.mp4", mtime=clock.now - DAY)}, now=clock.now)
    with pytest.raises(goals.GoalError, match="must be one of"):
        goals.complete(store, g["id"], {"kind": "clip", "ref": proof_file(tmp_path, "notes.txt")}, now=clock.now)
    with pytest.raises(goals.GoalError, match="needs a clip"):
        goals.complete(store, g["id"], {"kind": "test", "name": "t", "passed": True, "ran_at": clock.now}, now=clock.now)
    assert goals.get(store, g["id"])["status"] == "open"                                           # nothing above finished it
    goals.practice(store, g["id"], "fell off twice", False, now=clock.now)
    assert goals.get(store, g["id"])["status"] == "active"
    done = goals.complete(store, g["id"], {"kind": "clip", "ref": proof_file(tmp_path, "win.mp4", mtime=clock.now + 5)},
                          now=clock.now + 10)
    assert done["status"] == "done" and done["proof"].endswith("win.mp4")
    with pytest.raises(goals.GoalError):
        goals.practice(store, g["id"], "again", True)                                               # closed goals do not move


def test_test_proof_must_be_a_real_pass_after_the_goal(store, clock):
    (g,) = goals.propose(store, {}, ["luau: tweens"], now=clock.now)
    for bad in ({"kind": "test", "name": "t", "passed": "yes", "ran_at": clock.now},
                {"kind": "test", "name": "", "passed": True, "ran_at": clock.now},
                {"kind": "test", "name": "t", "passed": True, "ran_at": clock.now - 10},
                {"kind": "test", "name": "t", "passed": True},
                {"kind": "clip", "ref": "x.mp4"}):
        with pytest.raises(goals.GoalError):
            goals.complete(store, g["id"], bad, now=clock.now + 5)
    done = goals.complete(store, g["id"], {"kind": "test", "name": "tween_ease", "passed": True, "ran_at": clock.now + 1},
                          now=clock.now + 5)
    assert done["status"] == "done"


def test_one_file_never_proves_two_goals(store, clock, tmp_path):
    (a,) = goals.propose(store, {"play_games": {"weight": 1}}, [], now=clock.now)
    (b,) = goals.propose(store, {"music": {"weight": 1}}, [], now=clock.now)
    proof = {"kind": "clip", "ref": proof_file(tmp_path, "one.mp4", mtime=clock.now + 1)}
    goals.complete(store, a["id"], proof, now=clock.now + 2)
    with pytest.raises(goals.GoalError, match="already proved"):
        goals.complete(store, b["id"], proof, now=clock.now + 3)


def test_abandon_needs_a_reason_and_sweep_gives_up_untouched_goals(store, clock):
    (g,) = goals.propose(store, {"drawing": {"weight": 1}}, [], now=clock.now)
    with pytest.raises(goals.GoalError):
        goals.abandon(store, g["id"], "meh", now=clock.now)
    assert goals.sweep(store, clock.now + 9 * DAY) == []                                           # due + grace not reached
    swept = goals.sweep(store, clock.now + 15 * DAY)
    assert swept and swept[0]["status"] == "abandoned" and "ran out" in swept[0]["reason"]
    (h,) = goals.propose(store, {"music": {"weight": 1}}, [], now=clock.now + 20 * DAY)
    goals.practice(store, h["id"], "tried", False, now=clock.now + 26 * DAY)                        # touched near the end
    assert goals.sweep(store, clock.now + 30 * DAY) == []                                           # touched after its due day


def test_streak_counts_days_and_resets_after_a_gap(store, clock):
    (g,) = goals.propose(store, {"drawing": {"weight": 1}}, [], now=clock.now)
    for offset, expect in ((0, 1), (0, 1), (1, 2), (2, 3), (5, 1)):
        row = goals.practice(store, g["id"], "step", True, now=clock.now + offset * DAY + 100)
        assert row["streak"] == expect
    assert row["best_streak"] == 3 and row["tries"] == 5


def test_skill_confidence_moves_with_results_and_feeds_the_review_text(store, clock, tmp_path):
    (g,) = goals.propose(store, {}, ["luau: tweens"], now=clock.now)
    goals.practice(store, g["id"], "failed", False, now=clock.now)
    low = goals.skill_confidence(store)["luau:tweens"]
    assert low < 0.5 and "luau:tweens" in goals.weak_skills(store, below=0.5)
    goals.practice(store, g["id"], "passed", True, now=clock.now + 1)
    goals.complete(store, g["id"], {"kind": "test", "name": "t", "passed": True, "ran_at": clock.now + 2}, now=clock.now + 3)
    assert goals.skill_confidence(store)["luau:tweens"] > low
    text = goals.evidence_text(store, clock.now + 4)
    assert "finished with proof" in text and "luau:tweens" in text


def test_proof_from_outcome_never_invents(store, clock, tmp_path):
    (g,) = goals.propose(store, {"play_games": {"weight": 1}}, [], now=clock.now)
    assert goals.proof_from_outcome(g, {"evidence": ["won the round", "saved clip nowhere.mp4"]}) is None
    clip = proof_file(tmp_path, "round.mp4")
    assert goals.proof_from_outcome(g, {"evidence": [f"clip {clip}"]}) == {"kind": "clip", "ref": clip}
    assert goals.proof_from_outcome(g, {"proof": {"kind": "test"}}) == {"kind": "test"}


def test_after_session_counts_practice_and_finishes_only_with_real_proof(tmp_path, clock):
    s = LifeStore(home=tmp_path, clock=clock)
    (g,) = goals.propose(s, {"play_games": {"weight": 1}}, [], now=time.time() - 60)
    s.close()
    out = life.after_session(tmp_path, "play_games", "roblox", {"verified": True, "summary": "won", "evidence": ["won"]})
    assert "goal_done" not in out
    clip = proof_file(tmp_path, "w.mp4", mtime=time.time() + 5)
    out = life.after_session(tmp_path, "play_games", "roblox", {"verified": True, "summary": "won", "evidence": [clip],
                                                                "moment": {"kind": "game_won", "title": "won the obby together",
                                                                           "with_owner": True}})
    assert out["goal_done"] == g["id"] and out["moment"] is True
    assert life.after_session(tmp_path, "play_games", "x", {"life_counted": True})  == {}


def test_goal_announcement_has_the_proof_and_is_said_once(tmp_path, clock):
    s = LifeStore(home=tmp_path, clock=clock)
    (g,) = goals.propose(s, {"play_games": {"weight": 1}}, [], now=clock.now - 10)
    clip = proof_file(tmp_path, "w.mp4", mtime=clock.now + 1)
    goals.complete(s, g["id"], {"kind": "clip", "ref": clip}, now=clock.now)
    s.close()
    note = life.chat_note(tmp_path, now=clock.now)
    assert clip in note.text and "reached a goal" in note.text
    note.done()
    assert "reached a goal" not in life.chat_note(tmp_path, now=clock.now).text


def test_goal_activity_practises_through_a_home_activity_and_hands_failures_to_night_school(tmp_path, monkeypatch):
    from star.home.activities import Context, Registry
    calls = []

    def play(ctx):
        calls.append(ctx.goal["text"])
        return {"ok": True, "verified": False, "summary": "fell off", "evidence": []}

    registry = Registry()
    registry.register("roblox", "play_games", play, "play")
    life.register_home_activities(registry)
    assert {"creative studio", "studio drawing", "pursue a goal"} <= set(registry.items)
    s = life.default_store(tmp_path)
    (g,) = goals.propose(s, {"play_games": {"weight": 1}}, [], now=time.time() - 5)
    queue = tmp_path / "curiosity.jsonl"
    monkeypatch.setenv("STAR_CURIOSITY_FILE", str(queue))
    ctx = Context(home=tmp_path, config={}, executor=None, life=None, chat=None, interest="personal_goals", goal=None)
    out = registry.items["pursue a goal"].run(ctx)
    assert calls == [g["text"]] and out["life_counted"] is True and out["verified"] is False
    assert goals.get(s, g["id"])["tries"] == 1 and goals.get(s, g["id"])["status"] == "active"
    assert queue.exists() and "star life goal" in queue.read_text(encoding="utf-8")


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
    (g,) = goals.propose(s, {"drawing": {"weight": 1}}, [], now=clock.now)
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


def test_api_journal_holds_her_commentary_and_goals_but_no_token(server):
    code, text = request(server, "/life/journal", server.token)
    assert code == 200 and "The Robot Who Whistled" in text and "I wanted something gentle." in text and "MY GOALS" in text
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


def test_tick_sets_one_goal_a_day_and_never_raises(tmp_path, clock):
    life_obj = SimpleNamespace(interests=lambda: {"drawing": {"weight": 1.0}}, add_goal=lambda i, t: {"id": "g9"},
                               set_goal=lambda i, s: None)
    first = life.tick(tmp_path, life=life_obj, now=clock.now)
    assert len(first["new_goals"]) == 1
    assert life.tick(tmp_path, life=life_obj, now=clock.now + 3600).get("new_goals") is None       # once a day
    assert "error" not in life.tick(tmp_path, life=None, now=clock.now + 2 * DAY)


def test_nightly_self_review_reads_her_goals_and_skills(tmp_path, clock):
    from star.inner import night
    assert night._life_evidence(None) == "" and night._life_evidence(tmp_path) == ""
    s = life.default_store(tmp_path)
    (g,) = goals.propose(s, {}, ["luau: tweens"], now=time.time())
    goals.practice(s, g["id"], "failed", False)
    assert "luau:tweens" in night._life_evidence(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"life_goals_enabled": False}))
    assert night._life_evidence(tmp_path) == ""
