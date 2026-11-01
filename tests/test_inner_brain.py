"""Her brain (star/inner additions of 10-26): memory stream retrieval, bi-temporal facts, insights with evidence,
planner + energy, night consolidation, privacy/forget, constrained JSON, MindLife wiring, the memory eval."""
from __future__ import annotations

import json
import random
import time

import pytest

from star.home.life import Life
from star.inner import consolidate, insights, journal_view, memeval, planner
from star.inner import settings as brain_settings
from star.inner import structured
from star.inner.embed import HashEmbedder
from star.inner.mind import Mind, MindLife
from star.inner.stream import MemoryStream
from star.social.friends import FriendMemory

ON = {**{k: True for k in brain_settings.FLAGS}, **brain_settings.NUMBERS, **brain_settings.LISTS, "profile": "own_pc"}
ON["remote_embed"] = False


def at(day: int, hour: int, minute: int = 0) -> float:
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    return Clock(at(20, 10))


@pytest.fixture
def stream(tmp_path, clock):
    s = MemoryStream(tmp_path / "inner", embedder=HashEmbedder(), clock=clock)
    yield s
    s.close()


class NoEmotion:
    def enabled(self):
        return False


def make_mind(tmp_path, clock, **kw):
    life_home = tmp_path / "home"
    life_home.mkdir(exist_ok=True)
    return Mind(tmp_path / "app", life_home=life_home, settings=dict(ON), clock=clock, emotion=NoEmotion(),
                rng=random.Random(1), embedder=HashEmbedder(), friend_memory=kw.pop("friends", None), **kw)


# -- retrieval ------------------------------------------------------------------------------------------------------
def test_retrieval_is_recency_times_importance_times_relevance(stream, clock):
    old = stream.add("built a lava obby with moving platforms", importance=0.5, ts=clock.t - 48 * 3600)
    new = stream.add("built a lava obby with moving platforms", importance=0.5, ts=clock.t - 3600)
    big = stream.add("built a lava obby with moving platforms", importance=0.9, ts=clock.t - 48 * 3600)
    stream.add("watched a cooking video about pancakes", importance=1.0, ts=clock.t)
    hits = stream.retrieve("lava obby platforms", k=5, touch=False)
    assert [h.id for h in hits] == [big, new, old]            # the irrelevant one is not returned at all
    m = stream.get(old)
    query = "lava obby platforms"
    model, vectors = HashEmbedder().embed([query])
    expected = 0.995 ** 48 * 0.5 * stream.relevance(m, query, (model, vectors[0]))
    assert hits[2].score == pytest.approx(expected, rel=1e-3)


def test_retrieval_touches_what_it_returns_and_skips_private(stream, clock):
    a = stream.add("drew a fox sprite", importance=0.5, ts=clock.t - 10 * 3600)
    stream.add("drew a fox sprite secretly for the owner", importance=0.9, ts=clock.t, private=True)
    hits = stream.retrieve("fox sprite")
    assert [h.id for h in hits] == [a]
    assert stream.get(a).last_access == clock.t and stream.get(a).accesses == 1
    assert len(stream.retrieve("fox sprite", include_private=True, touch=False)) == 2


def test_hot_path_only_appends_to_the_inbox(stream):
    stream.observe(text="Mia said: hi there friend", kind="episodic")
    assert stream.count() == 0 and stream.inbox.exists()
    assert stream.ingest() == 1 and stream.count() == 1 and not stream.inbox.exists()


def test_facts_are_bitemporal_superseded_not_overwritten(stream, clock):
    first = stream.add_fact("1.1:favourite game", "Mia's favourite game is Doors", valid_from=at(10, 12))
    again = stream.add_fact("1.1:favourite game", "Mia's favourite game is Doors", valid_from=at(11, 12), evidence=[7])
    second = stream.add_fact("1.1:favourite game", "Mia's favourite game is Terraria", valid_from=at(15, 12))
    assert again == first and 7 in stream.get(first).evidence
    old = stream.get(first)
    assert old.invalid_at == at(15, 12) and old.superseded_by == second
    assert stream.fact("1.1:favourite game").text.endswith("Terraria")
    assert stream.fact("1.1:favourite game", as_of=at(12, 0)).text.endswith("Doors")
    assert [h.text for h in stream.retrieve("Mia favourite game", kinds=("semantic",), touch=False)] == \
        ["Mia's favourite game is Terraria"]


# -- skills ---------------------------------------------------------------------------------------------------------
def test_skill_confidence_is_calibrated_from_real_outcomes(stream, clock):
    for i, outcome in enumerate([0, 0, 1, 1, 1, 1]):
        stream.add(f"tried obby {i}", kind="procedural", skill="obby", outcome=outcome, predicted=0.5,
                   ts=clock.t - (6 - i) * 3600)
    s = stream.skill_stats()["obby"]
    assert s["attempts"] == 6 and s["successes"] == 4
    assert 0.6 < s["confidence"] < 0.7 and s["lower_bound"] < s["confidence"]
    assert s["brier"] == 0.25


# -- insights -------------------------------------------------------------------------------------------------------
def test_insights_have_evidence_and_supersede(stream, clock):
    ids = [stream.add(f"tried obby {i}", kind="procedural", skill="obby", outcome=o, ts=clock.t - (8 - i) * 3600)
           for i, o in enumerate([0, 0, 1, 1])]
    for i in range(3):
        stream.add(f"played tag with Mia round {i}", people=["1.1"], names=["Mia"], valence=0.7, ts=clock.t - i * 60)
        stream.add(f"waited in a queue {i}", valence=-0.1, ts=clock.t - i * 60)
    made = insights.reflect(stream, clock.t)
    texts = {stream.get(i).text: stream.get(i) for i in made}
    assert "I'm getting better at obby" in texts and set(texts["I'm getting better at obby"].evidence) == set(ids)
    cheer = texts["Mia always cheers me up"]
    assert cheer.people == ["1.1"] and len(cheer.evidence) == 3
    for i in range(4):
        stream.add(f"tried obby again {i}", kind="procedural", skill="obby", outcome=0, ts=clock.t + i)
    clock.t += 7200
    insights.reflect(stream, clock.t)
    assert stream.fact("trend:obby").text == "I've been struggling with obby lately"
    assert stream.get(texts["I'm getting better at obby"].id).invalid_at > 0


def test_model_insights_need_real_evidence_and_get_a_schema(stream, clock):
    ids = [stream.add(f"drew a robot number {i}", ts=clock.t - i) for i in range(5)]
    seen = {}

    def complete(system, user, schema=None):
        seen["schema"] = schema
        return json.dumps({"insights": [{"text": "I like drawing robots", "evidence": ids[:2]},
                                        {"text": "made up", "evidence": [ids[0], 99999]}]})
    got = insights.model_insights(stream, complete, clock.t)
    assert [g["text"] for g in got] == ["I like drawing robots"]
    assert seen["schema"]["schema"] == insights.INSIGHT_SCHEMA


def test_structured_tolerates_bad_escapes_and_retries():
    assert structured.tolerant_loads('noise ```json\n{"dream": "Sam\\\'s lighthouse"}\n```') == {"dream": "Sam's lighthouse"}
    calls = []

    def complete(system, user):
        calls.append(user)
        return "not json" if len(calls) == 1 else '{"insights": []}'
    assert structured.ask_json(complete, "s", "u", insights.INSIGHT_SCHEMA) == {"insights": []}
    assert len(calls) == 2
    assert structured.parse("{\"a\": 1} trailing") == {"a": 1}


# -- planner --------------------------------------------------------------------------------------------------------
INTERESTS = {k: {"weight": 1.0} for k in ("research", "practice", "play_games", "chat_with_friends", "drawing", "music")}


def test_plan_is_stable_varied_and_has_rest():
    plan = planner.make_plan("2026-10-20", ON, INTERESTS, set(INTERESTS))
    again = planner.make_plan("2026-10-20", ON, INTERESTS, set(INTERESTS))
    cats = [b["category"] for b in plan["blocks"]]
    assert plan == again and len(cats) == 9 and "rest" in cats
    heavy = {**INTERESTS, "drawing": {"weight": 5.0}, "music": {"weight": 5.0}}      # creating would win every block
    for d in range(1, 29):
        cats = [b["category"] for b in planner.make_plan(f"2026-11-{d:02d}", ON, heavy, set(heavy))["blocks"]]
        assert all(a != b for a, b in zip(cats, cats[1:])) and "rest" in cats
        assert max(cats.count(c) for c in set(cats)) <= 3


def test_plan_leans_social_when_owner_is_free_and_comfort_when_low():
    days = [f"2026-11-{d:02d}" for d in range(1, 29)]
    def evening_social(**kw):
        return sum(b["category"] in ("social", "play") for d in days
                   for b in planner.make_plan(d, {**ON, **kw}, INTERESTS, set(INTERESTS))["blocks"] if b["start"] >= 18)
    assert evening_social(owner_free_hours=[[18, 23]]) > evening_social(owner_free_hours=[])
    low = sum(b["category"] == "practise" for d in days
              for b in planner.make_plan(d, ON, INTERESTS, set(INTERESTS), valence=-0.6)["blocks"])
    high = sum(b["category"] == "practise" for d in days
               for b in planner.make_plan(d, ON, INTERESTS, set(INTERESTS), valence=0.3)["blocks"])
    assert low < high


def test_choose_follows_block_energy_sleep_and_budget():
    plan = {"blocks": [{"start": 8, "end": 10, "category": "create", "why": "morning"},
                       {"start": 10, "end": 12, "category": "rest", "why": "break"},
                       {"start": 12, "end": 14, "category": "social", "why": "x"}]}
    scores = {"drawing": 1.0, "music": 1.0, "research": 3.0}
    rng = random.Random(3)
    got, why = planner.choose(plan, at(20, 9), {"drawing", "music", "research"}, scores, 0.9, ON, rng=rng)
    assert got in ("drawing", "music") and why.startswith("create block")
    assert planner.choose(plan, at(20, 11), set(scores), scores, 0.9, ON)[0] is None
    assert planner.choose(plan, at(20, 3), set(scores), scores, 0.9, ON) == (None, "sleeping")
    assert planner.choose(plan, at(20, 9), set(scores), scores, 0.2, ON)[0] is None
    assert planner.choose(plan, at(20, 9), set(scores), scores, 0.9, ON, active_minutes=601)[0] is None
    got, why = planner.choose(plan, at(20, 13), {"research"}, scores, 0.9, ON)
    assert got == "research" and "instead" in why


def test_energy_spends_recovers_and_resets(stream, clock):
    energy = planner.Energy(stream)
    energy.set(1.0, clock.t)
    assert energy.spend("create", 60, clock.t) == pytest.approx(0.73)
    assert energy.spend("create", 10, clock.t, valence=-0.5) == pytest.approx(0.73 - 0.054)
    assert energy.level(clock.t + 3600) == pytest.approx(0.776)
    assert energy.wake(clock.t, slept=True) == 1.0 and energy.wake(clock.t, slept=False) == 0.7


# -- night consolidation --------------------------------------------------------------------------------------------
def test_night_consolidation_is_deterministic(stream, tmp_path, clock):
    day = at(20, 9)
    stream.observe(text="Mia said: my favourite game is Doors", source="conversation", people=["1.1"], names=["Mia"],
                   importance=0.5, ts=day + 3600)
    stream.observe(text="tried obby: did not work", kind="procedural", skill="obby", outcome=0, ts=day + 7200)
    stream.observe(text="tried obby: worked", kind="procedural", skill="obby", outcome=1, ts=day + 9000)
    stream.observe(text="lost a round and got teased", valence=-0.8, importance=0.6, ts=day + 10000)
    stream.observe(text="lost a round and got teased", valence=-0.5, importance=0.3, ts=day + 10100)
    night = at(21, 2)
    journal = tmp_path / "journal.md"
    a = consolidate.run(stream, night, night="2026-10-20", since=day, journal=journal)
    assert a["facts"] == 1 and stream.fact("1.1:favourite game").text == "Mia's favourite game is Doors"
    assert a["lessons"] == ["Figured out obby: it failed at first, then worked"]
    assert a["softened"] == 2 and a["merged"] == 1
    sad = [m for m in stream.all() if m.text.startswith("lost a round")]
    assert len(sad) == 1 and sad[0].valence == pytest.approx(-0.48)
    dream = stream.get(a["dream"])
    assert dream.kind == "dream" and dream.text.startswith("Dream (not real): ") and "1.1" in dream.people
    assert "a dream: not something that happened" in journal.read_text(encoding="utf-8")
    note = json.loads(stream.meta("morning:2026-10-21"))
    assert note["lesson"].startswith("Figured out") and note["dream"]


def test_night_links_the_inner_dream_and_prunes(stream, clock):
    stream.add("noticed a cloud", importance=0.05, ts=at(1, 10))
    keep = stream.add("first verified drawing", importance=0.05, ts=at(1, 10), milestone=True)
    stream.add("played tag", importance=0.5, ts=at(20, 10))
    r = consolidate.run(stream, at(21, 2), night="n", since=at(20, 9),
                        inner_dream={"text": "I was a lighthouse made of cake.", "gist": "cake lighthouse",
                                     "valence": 0.3})
    assert stream.get(r["dream"]).text == "Dream (not real): I was a lighthouse made of cake."
    assert r["pruned"] == 1 and stream.get(keep) is not None
    assert json.loads(stream.meta("morning:2026-10-21"))["dream"] == "cake lighthouse"


# -- privacy --------------------------------------------------------------------------------------------------------
def test_forget_person_cascades_to_insights_facts_and_inbox(stream, clock):
    mia = [stream.add(f"tag with Mia {i}", people=["1.1"], names=["Mia"], valence=0.8, ts=clock.t - i) for i in range(3)]
    other = stream.add("drew a fox", ts=clock.t)
    insight = stream.add("good days lately", kind="reflection", evidence=[mia[0], other])
    stream.add_fact("1.1:dog name", "Mia's dog is called Biscuit", people=["1.1"], evidence=[mia[1]])
    stream.observe(text="Mia said: one more thing", people=["1.1"], names=["Mia"])
    removed = stream.forget_person("1.1")
    assert removed == 5 and stream.get(other) and stream.get(insight) is None
    assert not stream.inbox.read_text(encoding="utf-8").strip()
    stream.observe(text="Mia said: late line", people=["1.1"])
    stream.ingest()
    assert all("1.1" not in m.people for m in stream.all())
    assert stream.add("again", people=["1.1"]) is None


def test_conversations_from_minors_and_roblox_have_no_content_and_forget_me_reaches_the_stream(tmp_path, clock):
    friends = FriendMemory(tmp_path / "friends.sqlite3")
    mind = make_mind(tmp_path, clock, friends=friends)
    adult = friends.person("discord", "ann", "Ann")
    friends.update(adult, stated_age=30)
    adult = friends.person("discord", "ann", "Ann")
    kid = friends.person("discord", "tim", "Tim")
    friends.update(kid, stated_age=12)
    kid = friends.person("discord", "tim", "Tim")
    mind.observe_conversation(friends, adult, "discord", "my favourite band is Muse")
    mind.observe_conversation(friends, adult, "roblox", "I live on Elm street")
    mind.observe_conversation(friends, kid, "discord", "my school is Lincoln and I live on Oak road")
    mind.stream.ingest()
    texts = sorted(m.text for m in mind.stream.all())
    assert texts == ["Ann said: my favourite band is Muse", "Chatted with Ann on roblox", "Chatted with Tim on discord"]
    friends.forget("discord", "tim")
    assert mind.stream.purge_orphans(friends) == 1
    assert all("Tim" not in m.text for m in mind.stream.all())
    friends.close()


# -- wiring ---------------------------------------------------------------------------------------------------------
def test_mind_life_plans_records_and_stops(tmp_path, clock):
    clock.t = at(20, 9)
    mind = make_mind(tmp_path, clock)
    life = MindLife(Life(tmp_path / "home", rng=random.Random(2)), mind)
    pick = life.pick({"drawing", "research", "play_games", "chat_with_friends", "practice", "music"})
    plan = planner.load_plan(mind.stream, "2026-10-20")
    block = planner.block_at(plan, clock.t)
    assert plan and (pick is None) == (block["category"] == "rest")
    if pick:
        assert planner.category_of(pick) == block["category"]
    row = life.record("drawing", "drawing", {"ok": True, "verified": True, "summary": "drew a fox", "minutes": 30})
    assert row["verified"]
    mind.stream.ingest()
    kinds = sorted(m.kind for m in mind.stream.all() if m.source == "activity")
    assert kinds == ["episodic", "procedural"]
    assert mind.stream.skill_stats()["drawing"]["successes"] == 1
    assert mind.energy.level(clock.t) < 1.0
    assert mind.monologue() and "session_context" in dir(life)
    (tmp_path / "home" / "STOP").write_text("x")
    assert mind.tick(clock.t) == {"state": "stopped"}
    mind._settings["planner"] = False
    assert life.pick({"drawing"}) == "drawing"           # off: plain Life.pick


def test_tick_runs_the_night_once_and_writes_the_page(tmp_path, clock):
    mind = make_mind(tmp_path, clock, friends=FriendMemory(tmp_path / "f.sqlite3"))
    mind.stream.add("played tag", importance=0.6, ts=at(20, 15))
    clock.t = at(21, 2)
    first = mind.tick()
    assert "night" in first and "night" not in mind.tick()
    page = (tmp_path / "app" / "inner" / "journal.html").read_text(encoding="utf-8")
    assert "STAR journal" in page and "Dream (not real)" in page and "designed simulation" in page


def test_summary_and_session_context_leave_people_out(tmp_path, clock):
    mind = make_mind(tmp_path, clock)
    mind.stream.add("Mia always cheers me up", kind="reflection", people=["1.1"], names=["Mia"], importance=0.9)
    mind.stream.add("I'm getting better at obby", kind="reflection", importance=0.7)
    for o in (1, 1, 1):
        mind.stream.add("tried obby", kind="procedural", skill="obby", outcome=o)
    text = mind.summary()
    assert "Mia" not in text and "getting better at obby" in text and "Good at obby" in text
    assert len(text) <= ON["summary_tokens"] * 4
    ctx = mind.session_context("practice", {"text": "beat the obby"})
    assert "Mia" not in ctx and ctx.startswith("Who you are right now")


def test_home_brain_session_gets_the_context():
    from star.home import brain

    class FakeLife:
        def interests(self):
            return {"drawing": {"weight": 1.0}}

        def session_context(self, interest, goal):
            return "Who you are right now: Star."
    seen = []

    def chat(messages, tools):
        seen.append(messages[1]["content"])
        return {"tool_calls": [{"function": {"name": "finish", "arguments": json.dumps({"summary": "ok",
                                                                                         "success": False})}}]}

    class Ex:
        workspace = "w"
    brain.run_session(chat, Ex(), FakeLife(), interest="drawing", brief="draw", goal=None)
    assert seen[0].endswith("Who you are right now: Star.")


def test_settings_default_on_only_on_her_pc(tmp_path, monkeypatch):
    monkeypatch.delenv("STAR_ROOT", raising=False)
    assert brain_settings.load(tmp_path)["brain_enabled"] is False
    monkeypatch.setenv("STAR_ROOT", str(tmp_path))
    assert all(brain_settings.load(tmp_path)[f] for f in brain_settings.FLAGS)
    brain_settings.save(tmp_path, planner=False)
    assert brain_settings.load(tmp_path)["planner"] is False
    with pytest.raises(ValueError):
        brain_settings.save(tmp_path, nonsense=1)


def test_journal_view_escapes(tmp_path, clock):
    mind = make_mind(tmp_path, clock)
    mind.stream.add("<script>x</script> drew", importance=0.5)
    html = journal_view.page(journal_view.snapshot(mind))
    assert "<script>x" not in html and "&lt;script&gt;" in html


def test_memory_eval_score():
    result = memeval.run()
    assert result["score"] >= 0.9, result["misses"]
    assert result["by_ability"]["update"] == "2/2" and result["by_ability"]["temporal"] == "4/4"
