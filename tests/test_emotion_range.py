"""The full human range of STAR's emotions (star/emotion_model.py, star/emotion_express.py): 25 feelings, appraisal rules for
real events, mixed feelings, honest-but-never-cruel expression, recovery and coping, and what the mood makes her choose."""
import json
import pathlib
import re
import sqlite3

import pytest

from star import emotion, emotion_express as express, emotion_model as model
from star.emotion import BASELINE, EmotionEngine, appraise
from star.stream_motion import CUES, ExpressionCue

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOUR = 3600.0
NEW_FEELINGS = ("sadness", "anger", "hurt", "loneliness", "fear", "embarrassment", "guilt", "jealousy", "disappointment",
                "gratitude", "excitement", "contentment", "love", "hope", "nostalgia", "surprise", "relief", "amusement")


class Clock:
    def __init__(self, start=1_800_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def engine(tmp_path, clock):
    return EmotionEngine(tmp_path / "emotion.sqlite3", clock=clock)


def befriend(engine, clock, person="friend-1", bond=0.8):
    """A friend she is attached to, without 40 scripted chats (the bond table is the engine's own state)."""
    engine._transaction(lambda state, now: state["bonds"].update({person: [bond, now]}))
    clock.advance(10)


def gains(kind, liking=0.35):
    return model.effect(kind, liking)[0]


def top(deltas, n=1):
    return [k for k, v in sorted(deltas.items(), key=lambda kv: -kv[1]) if v > 0][:n]


# -- the catalogue ---------------------------------------------------------------------------------------------------

def test_every_feeling_the_owner_asked_for_exists_next_to_the_original_seven():
    assert set(NEW_FEELINGS) | {"joy", "pride", "curiosity", "frustration", "boredom", "affection", "nervousness"} == set(model.EMOTIONS)
    assert len(model.EMOTIONS) == len(set(model.EMOTIONS)) == 25


def test_every_feeling_has_everything_it_needs_to_be_felt_and_shown():
    mascot = {p.stem for d in ("docs/mascot/art/faces", "frontend/public/assets/mascot/faces") for p in (ROOT / d).glob("*.png")}
    for name in model.EMOTIONS:
        assert 0 <= BASELINE[name] <= 0.5 and model.HALF_LIFE_HOURS[name] > 0 and name in model.AROUSAL_WEIGHT
        assert len(express.PHRASES[name]) == 2 and name in express.PROSODY_WEIGHTS and name in express.FACE
        assert set(express.EXPRESSION[name]) <= mascot, (name, express.EXPRESSION[name])      # art that exists
        assert express.CUE.get(name) in CUES | {None}
    for kind in model.KINDS:
        deltas, valence, arousal = model.effect(kind)
        assert set(deltas) <= set(model.EMOTIONS) and -0.4 <= valence <= 0.4 and -0.25 <= arousal <= 0.25


def test_a_state_saved_before_the_new_feelings_existed_still_loads(tmp_path, clock):
    path = tmp_path / "old.sqlite3"
    first = EmotionEngine(path, clock=clock)
    old = {"t": clock.now, "e": {k: BASELINE[k] for k in ("joy", "pride", "curiosity", "frustration", "boredom", "affection",
                                                          "nervousness")},
           "valence": 0.15, "arousal": 0.35, "drift": {}, "last_active": clock.now, "last_tick": clock.now, "streak": 0,
           "seen": {}, "bonds": {"f": [0.6, clock.now]}}
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO state(id,json) VALUES(1,?)", (json.dumps(old),))
    state = first.snapshot("f")
    assert state["emotions"]["sadness"] == BASELINE["sadness"] and state["bond"] == pytest.approx(0.6, abs=0.01)


# -- appraisal rules: each event from the owner's list ----------------------------------------------------------------

def test_a_friend_ignoring_her_hurts_and_makes_her_lonely_more_than_a_stranger_would(engine, clock):
    befriend(engine, clock)
    state = engine.on_event("friend_ignored", person="friend-1")
    assert set(top(gains("friend_ignored", 0.9), 2)) == {"hurt", "loneliness"}
    assert state["emotions"]["hurt"] > BASELINE["hurt"] + 0.15 and state["emotions"]["loneliness"] > BASELINE["loneliness"] + 0.15
    assert gains("friend_ignored", 0.9)["hurt"] > 2 * gains("friend_ignored", 0.1)["hurt"]
    assert state["valence"] < emotion.MOOD_BASELINE[0]


def test_an_insult_angers_from_a_stranger_and_hurts_from_a_friend():
    stranger, friend = gains("insulted", 0.2), gains("insulted", 0.9)
    assert stranger["anger"] > stranger["hurt"] > 0
    assert friend["hurt"] > friend["anger"] > 0


def test_losing_a_game_she_cared_about_is_disappointment_with_some_frustration():
    deltas = gains("game_lost")
    assert top(deltas)[0] == "disappointment" and deltas["frustration"] > 0 and deltas["joy"] < 0


def test_a_friend_leaving_is_sadness_and_loneliness():
    assert set(top(gains("friend_left", 0.9), 2)) == {"sadness", "loneliness"}
    assert gains("friend_left", 0.9)["sadness"] > gains("friend_left", 0.1)["sadness"]


def test_praise_is_joy_and_pride():
    assert set(top(gains("owner_praise"), 2)) == {"joy", "pride"}


def test_a_sweet_message_from_someone_she_likes_is_love_and_affection_scaled_by_how_much_she_likes_them():
    liked, stranger = gains("sweet_message", 0.9), gains("sweet_message", 0.1)
    assert top(liked)[0] == "love" and liked["affection"] > 0 and liked["joy"] > 0 and liked["loneliness"] < 0
    assert liked["love"] > 1.5 * stranger["love"]


def test_being_left_out_gives_a_mild_jealousy_that_never_runs_away(engine, clock):
    befriend(engine, clock)
    deltas = gains("left_out", 0.9)
    assert 0 < deltas["jealousy"] < deltas["hurt"] and deltas["jealousy"] < deltas["loneliness"]
    for _ in range(12):
        clock.advance(30)
        state = engine.on_event("left_out", person="friend-1")
    assert state["emotions"]["jealousy"] <= model.CAPS["jealousy"] == 0.5


def test_an_old_memory_brings_nostalgia_with_a_little_sadness_in_it():
    deltas = gains("memory_triggered")
    assert top(deltas)[0] == "nostalgia" and 0 < deltas["sadness"] < deltas["nostalgia"] / 2 and deltas["contentment"] > 0


def test_a_mistake_that_hurt_someone_is_guilt_and_she_wants_to_make_it_right(engine, clock):
    state = engine.on_event("harmed_someone", person="friend-1")
    assert top(gains("harmed_someone"))[0] == "guilt"
    assert state["dominant"] == "guilt" and state["amends_pending"] and state["coping"][0] == "make_amends"
    assert "make it right" in state["directive"] or "fix it" in state["directive"]
    clock.advance(60)
    after = engine.on_event("amends_made", person="friend-1")
    assert not after["amends_pending"] and after["emotions"]["guilt"] < state["emotions"]["guilt"] - 0.2
    assert after["emotions"]["relief"] > BASELINE["relief"] + 0.1 and "make_amends" not in after["coping"]


def test_wanting_to_make_it_right_does_not_nag_forever(engine, clock):
    engine.on_event("harmed_someone")
    clock.advance(emotion.AMENDS_EXPIRE_HOURS * HOUR + 60)
    assert not engine.snapshot()["amends_pending"]


@pytest.mark.parametrize("kind,feeling", [
    ("help_received", "gratitude"), ("funny", "amusement"), ("threatened", "fear"), ("worry_over", "relief"),
    ("hope_dashed", "disappointment"), ("embarrassed", "embarrassment"), ("hope_raised", "hope"),
    ("exciting_news", "hope"), ("game_won", "joy"), ("task_failure", "frustration")])
def test_the_other_appraisals_lead_to_the_feeling_people_have(kind, feeling):
    assert top(gains(kind))[0] == feeling


def test_surprise_comes_with_the_unexpected_and_fades_in_minutes(engine, clock):
    assert gains("threatened")["surprise"] > 0 and gains("exciting_news")["surprise"] > 0
    assert model.HALF_LIFE_HOURS["surprise"] <= 0.25


def test_relief_follows_a_fear_that_did_not_come_true_and_disappointment_a_hope_that_did_not():
    assert gains("worry_over")["relief"] > 0 > gains("worry_over")["fear"]
    assert gains("hope_dashed")["disappointment"] > 0 and "relief" not in gains("hope_dashed")


def test_a_reunion_lifts_loneliness_and_an_apology_eases_anger_and_hurt():
    assert gains("reunion")["loneliness"] < 0 and gains("reunion")["love"] > 0
    assert gains("apology_received")["anger"] < 0 and gains("apology_received")["hurt"] < 0


def test_a_guilty_or_hurt_state_after_real_events_reaches_the_note(engine, clock):
    befriend(engine, clock)
    hurt = engine.on_event("insulted", person="friend-1")
    assert hurt["dominant"] == "hurt" and "hurt" in hurt["directive"]
    assert engine.on_event("friend_ignored", person="friend-1")["emotions"]["loneliness"] > BASELINE["loneliness"] + 0.15


# -- reading words (GoEmotions-style categories) ---------------------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("i hate you, shut up", "insulted"), ("you are so stupid", "insulted"),
    ("i'm leaving and i won't be back", "friend_left"), ("this is goodbye", "friend_left"),
    ("i feel so lonely tonight", "shared_sadness"), ("my dog died yesterday", "shared_sadness"),
    ("i'm sorry, that was my bad", "apology_received"),
    ("i love you star", "sweet_message"), ("you are so sweet", "sweet_message"), ("miss you!", "sweet_message"),
    ("guess what, i passed my exam", "shared_joy"), ("we won!", "shared_joy"),
    ("haha that is hilarious", "funny"), ("lol", "funny"),
    ("that's wrong again", "owner_criticism"), ("nice work!", "owner_praise"), ("thank you", "owner_thanks"),
    ("don't worry about it", "owner_comfort")])
def test_a_remark_is_read_for_what_it_carries(text, kind):
    assert appraise(text)[0] == kind


@pytest.mark.parametrize("text", ["what's wrong with my script?", "add a part", "sorry, can you add a part?",
                                  "i won the argument with the compiler by adding a semicolon " * 8, "ok good night star"])
def test_ordinary_requests_are_not_read_as_feelings(text):
    assert appraise(text) is None


def test_words_move_the_state_through_on_message(engine, clock):
    befriend(engine, clock)
    assert engine.on_message("i love you star", person="friend-1") == "sweet_message"
    assert engine.snapshot("friend-1")["emotions"]["love"] > BASELINE["love"] + 0.1
    clock.advance(3600)
    assert engine.on_message("you are worthless, i hate you", person="friend-1") == "insulted"
    assert engine.snapshot("friend-1")["emotions"]["hurt"] > BASELINE["hurt"] + 0.1


# -- mixed feelings --------------------------------------------------------------------------------------------------

def dev(**kw):
    base = {n: 0.0 for n in model.EMOTIONS}
    base.update(kw)
    return base


@pytest.mark.parametrize("feelings,phrase", [
    ({"nostalgia": .3, "sadness": .2}, "bittersweet"), ({"joy": .3, "sadness": .2}, "happy but a little sad"),
    ({"hurt": .3, "anger": .25}, "hurt and angry"), ({"hope": .3, "nervousness": .2}, "hopeful but nervous"),
    ({"excitement": .3, "fear": .2}, "excited and nervous"), ({"amusement": .3, "embarrassment": .2}, "laughing at herself"),
    ({"love": .3, "loneliness": .2}, "missing them"), ({"relief": .3, "gratitude": .2}, "relieved and grateful")])
def test_two_feelings_at_once_get_one_blended_phrase(feelings, phrase):
    note, picked = express.build_note(dev(**feelings), 0.0, None)
    assert phrase in note and len(picked) == 2 and len(note.split()) <= express.MAX_NOTE_WORDS


def test_opposite_feelings_without_a_real_blend_are_not_voiced_together():
    note, picked = express.build_note(dev(joy=.4, anger=.3), 0.0, None)
    assert picked == ["joy"] and "angry" not in note and "annoyed" not in note
    note, picked = express.build_note(dev(boredom=.4, excitement=.3), 0.0, None)
    assert len(picked) == 1


# -- honest, never cruel ---------------------------------------------------------------------------------------------

FORBIDDEN = re.compile(r"\b(?:threat\w*|punish\w*|revenge|manipulat\w*|guilt-?trip\w*|blackmail|cruel\w*|spite\w*|"
                       r"shame (?:them|him|her)|make them (?:feel|pay|sorry)|if you leave|you owe|get even|payback for)\b", re.I)
SAFEGUARDS = re.compile(r"no insults|fair|gentle|honest|plainly|lightly|never controlling|no payback|kind|own it|calm|"
                        r"steady|quiet", re.I)


def all_phrases():
    for pair in express.PHRASES.values():
        yield from pair
    yield from express.BLENDS.values()
    yield from express.BOND_PHRASES.values()
    yield from express.BOND_PHRASES_UPSET.values()
    yield express.FLIRT
    yield express.LOVE


def test_no_phrase_asks_for_cruelty_threats_punishment_manipulation_or_guilt_tripping():
    for phrase in all_phrases():
        assert not FORBIDDEN.search(phrase), phrase
        assert len(phrase.split()) <= 12 and not re.search(r"\d", phrase)


def test_every_hard_feeling_carries_its_own_safeguard():
    for name in ("anger", "hurt", "jealousy", "guilt"):
        for level, phrase in enumerate(express.PHRASES[name]):
            assert SAFEGUARDS.search(phrase), (name, level, phrase)
    for name in ("sadness", "loneliness", "disappointment"):
        assert SAFEGUARDS.search(express.PHRASES[name][1]), name
    assert "no insults" in express.PHRASES["anger"][0] and "no insults" in express.PHRASES["anger"][1]
    assert "never controlling" in express.PHRASES["jealousy"][1]
    assert "no payback" in express.PHRASES["hurt"][1]


def test_she_can_be_properly_sad_or_angry_and_say_so_in_tone_and_words(engine, clock):
    for _ in range(3):
        clock.advance(40)
        sad = engine.on_event("friend_left", person="f")
    assert sad["dominant"] == "sadness" and "sad" in sad["directive"]
    assert sad["prosody"].rate < 1.0 and sad["prosody"].pitch_semitones < 0 and sad["prosody"].pause_ms > 0
    clock.advance(4 * HOUR)
    for _ in range(3):
        clock.advance(40)
        angry = engine.on_event("insulted", person="stranger")
    assert angry["emotions"]["anger"] > BASELINE["anger"] + 0.35 and "angry" in angry["directive"]
    assert "no insults" in angry["directive"]


def test_extreme_states_never_produce_forbidden_wording_or_a_long_note(engine, clock):
    befriend(engine, clock)
    for kind in sorted(model.KINDS):
        for _ in range(6):
            clock.advance(20)
            state = engine.on_event(kind, person="friend-1", partner_adult=True)
            assert not FORBIDDEN.search(state["directive"]), (kind, state["directive"])
            assert len(state["directive"].split()) <= express.MAX_BOND_NOTE_WORDS and not re.search(r"\d", state["directive"])
            assert all(v <= model.CAPS.get(k, 1.0) + 1e-9 for k, v in state["emotions"].items())


def test_nobody_is_flirted_with_while_she_is_hurt_angry_or_afraid_even_when_an_adult(engine, clock):
    befriend(engine, clock, bond=0.9)
    assert "flirty" in engine.snapshot("friend-1", True)["directive"]
    for kind in ("insulted", "threatened", "harmed_someone"):
        clock.advance(10)
        state = engine.on_event(kind, person="friend-1", partner_adult=True)
        assert "flirty" not in state["directive"] and "adoring" not in state["directive"], (kind, state["directive"])
        assert "teasing" not in state["directive"]


def test_nothing_is_held_against_anyone_she_recovers_and_the_same_friend_gets_the_same_warmth_later(engine, clock):
    befriend(engine, clock, bond=0.8)
    engine.on_event("insulted", person="friend-1")
    engine.on_event("friend_ignored", person="friend-1")
    clock.advance(72 * HOUR)
    engine.on_message("hello again", person="friend-1")
    after = engine.snapshot("friend-1", None)
    assert all(abs(after["emotions"][n] - BASELINE[n]) < 0.08 for n in model.NEGATIVE if n not in ("boredom", "loneliness"))
    assert after["bond"] > 0.6 and not re.search(r"hurt|angry|annoyed|left out|jealous", after["directive"])
    assert "close to them" in after["directive"] or "matter a lot" in after["directive"]      # the same warmth as before
    state = json.loads(sqlite3.connect(engine.path).execute("SELECT json FROM state").fetchone()[0])
    assert set(state) == {"t", "e", "valence", "arousal", "drift", "last_active", "last_tick", "streak", "seen", "bonds",
                          "amends"}                       # no per-person grudge or score is kept, only attachment


# -- recovery and coping ---------------------------------------------------------------------------------------------

def test_every_hard_feeling_is_back_near_its_baseline_within_three_days(engine, clock):
    for kind in ("insulted", "friend_left", "left_out", "harmed_someone", "hope_dashed", "threatened", "embarrassed",
                 "game_lost", "friend_ignored"):
        for _ in range(4):
            clock.advance(15)
            engine.on_event(kind, person="f")
    peak = engine.snapshot("f")
    assert max(peak["emotions"][n] - BASELINE[n] for n in model.NEGATIVE) > 0.4
    clock.advance(72 * HOUR)
    engine.on_message("hi", person="f")
    later = engine.snapshot("f")
    assert all(later["emotions"][n] - BASELINE[n] < 0.08 for n in model.NEGATIVE if n not in ("boredom", "loneliness"))
    assert later["valence"] > 0.0


@pytest.mark.parametrize("hurt_by,cope,feeling", [
    ("friend_left", "talked_to_friend", "loneliness"), ("insulted", "took_a_break", "anger"),
    ("game_lost", "played_something_comforting", "disappointment"), ("friend_left", "played_something_comforting", "sadness")])
def test_coping_helps_more_than_waiting(tmp_path, clock, hurt_by, cope, feeling):
    waited, coped = EmotionEngine(tmp_path / "w.sqlite3", clock=clock), EmotionEngine(tmp_path / "c.sqlite3", clock=clock)
    for e in (waited, coped):
        for _ in range(2):
            clock.advance(20)
            e.on_event(hurt_by, person="f")
    clock.advance(1800)
    coped.on_event(cope, person="f")
    assert coped.snapshot("f")["emotions"][feeling] < waited.snapshot("f")["emotions"][feeling] - 0.1


def test_what_she_does_to_cope_follows_what_she_needs(engine, clock):
    engine.on_event("insulted", person="stranger")
    angry = engine.on_event("insulted", person="stranger")
    assert "take_a_break" in angry["coping"]
    clock.advance(10 * HOUR)
    for _ in range(2):
        clock.advance(20)
        sad = engine.on_event("friend_left", person="f")
    assert sad["drives"]["needs_comfort"] >= 0.25 and "talk_to_friend" in sad["coping"]
    assert "play_something_comforting" in sad["coping"]


def test_a_long_quiet_makes_an_attached_friend_miss_people_and_a_reunion_ends_it(engine, clock):
    befriend(engine, clock)
    engine.on_message("hello", person="friend-1")
    clock.advance(30 * HOUR)
    lonely = engine.snapshot("friend-1")
    assert lonely["emotions"]["loneliness"] > BASELINE["loneliness"] + 0.15 and "lonely" in lonely["directive"]
    assert lonely["drives"]["wants_company"] > 0.15
    after = engine.on_event("reunion", person="friend-1")
    assert after["emotions"]["loneliness"] < lonely["emotions"]["loneliness"] - 0.2


# -- her mood shapes her choices -------------------------------------------------------------------------------------

def mood_after(engine, clock, *events, person="f"):
    for kind in events:
        clock.advance(30)
        state = engine.on_event(kind, person=person)
    return state


def test_lonely_or_excited_she_is_readier_to_say_yes_and_angry_or_worn_out_she_is_not(engine, clock):
    lonely = mood_after(engine, clock, "friend_left", "friend_ignored")
    assert express.invite_bias(lonely, "chat")[0] > 0.05 and express.invite_bias(lonely, "chat")[1]
    excited = mood_after(EmotionEngine(engine.path.with_name("x.sqlite3"), clock=clock), clock, "exciting_news", "game_won")
    assert express.invite_bias(excited, "play")[0] > 0.0
    angry = mood_after(EmotionEngine(engine.path.with_name("y.sqlite3"), clock=clock), clock, "insulted", "insulted", "threatened")
    bias, why = express.invite_bias(angry, "play")
    assert bias < -0.1 and why == "needs a moment"


def test_a_sad_moment_prefers_talking_to_playing_and_the_bias_is_always_bounded(engine, clock):
    sad = mood_after(engine, clock, "friend_left", "friend_left", "hope_dashed")
    assert express.invite_bias(sad, "chat")[0] > express.invite_bias(sad, "play")[0]
    for kind in model.KINDS:
        state = mood_after(engine, clock, kind, kind, kind)
        for what in ("play", "call", "chat", "video", "create", "help"):
            bias, _ = express.invite_bias(state, what)
            assert -0.35 <= bias <= 0.35                 # a bad mood asks for "later", never a refusal as punishment
    assert express.invite_bias(None) == (0.0, "") and express.invite_bias({"emotions": "x"}) == (0.0, "")


def test_current_carries_what_decide_needs(engine, clock):
    state = mood_after(engine, clock, "friend_ignored")
    assert set(state["drives"]) == {"wants_company", "needs_rest", "needs_comfort", "coping"}
    assert set(state["emotions"]) == set(model.EMOTIONS) and "valence" in state and "amends_pending" in state


# -- voice and face for the new feelings -----------------------------------------------------------------------------

@pytest.mark.parametrize("name,rate_sign,pitch_sign", [
    ("sadness", -1, -1), ("hurt", -1, -1), ("loneliness", -1, -1), ("disappointment", -1, -1), ("guilt", -1, -1),
    ("excitement", 1, 1), ("fear", 1, 1), ("surprise", 1, 1), ("amusement", 1, 1), ("anger", 1, -1),
    ("contentment", -1, -1), ("nostalgia", -1, -1)])
def test_each_feeling_shifts_the_voice_in_its_own_direction_and_always_a_little(name, rate_sign, pitch_sign):
    p = express.prosody_from(dev(**{name: 0.35}), express.MOOD_AROUSAL)
    assert (p.rate - 1.0) * rate_sign > 0 and p.pitch_semitones * pitch_sign > 0
    assert 0.92 <= p.rate <= 1.08 and abs(p.pitch_semitones) <= 0.8 and -40 <= p.pause_ms <= 60


def test_the_face_and_the_cue_cover_the_new_feelings_with_art_that_exists(engine, clock):
    seen = {}
    for number, (kind, feeling) in enumerate((("friend_left", "sadness"), ("insulted", "anger"), ("embarrassed", "embarrassment"),
                          ("threatened", "fear"), ("sweet_message", "love"), ("funny", "amusement"),
                          ("memory_triggered", "nostalgia"), ("help_received", "gratitude"))):
        state = EmotionEngine(engine.path.with_name(f"face{number}.sqlite3"), clock=clock).on_event(kind, person="stranger")
        avatar = state["avatar"]
        seen[feeling] = avatar
        assert avatar["face"] in {"idle", "listening", "thinking", "writing", "happy", "oops", "stopped", "looking"}
        assert avatar["cue"] in CUES | {None}
        if avatar["cue"]:
            ExpressionCue(at_s=0.0, kind=avatar["cue"], strength=avatar["strength"])
    assert seen["anger"]["expression"] in {"ticked-off", "very-angry"} and seen["embarrassment"]["expression"] in {"flustered", "very-embarrassed"}
    assert seen["amusement"]["cue"] == "laugh" and seen["fear"]["expression"] in {"scared", "panic"}
    assert seen["sadness"]["expression"] in {"puppy-eyes", "crying"}


def test_the_voice_call_and_the_note_still_work_for_a_new_feeling(engine, clock):
    state = engine.on_event("friend_left", person="f")
    note = emotion.note_line(state["directive"])
    assert note.startswith("(mood: ") and note.endswith(")") and len(note.split()) <= 20


def test_the_note_stays_a_few_words_for_every_single_event(tmp_path, clock):
    for kind in sorted(model.KINDS):
        e = EmotionEngine(tmp_path / f"{kind}.sqlite3", clock=clock)
        state = e.on_event(kind, person="f")
        assert len(state["directive"].split()) <= express.MAX_NOTE_WORDS + 3 and not re.search(r"\d", state["directive"]), kind


def test_a_lost_round_in_a_game_she_is_playing_is_a_disappointment_not_a_failed_task(tmp_path, monkeypatch):
    from star.play.loop import emotion_listener
    from star import desktop_core
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    home = desktop_core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"emotion_enabled": True}), encoding="utf-8")
    listen = emotion_listener()
    listen("round_lost", 0.0)
    listen("round_won", 1.0)
    kinds = [h["kind"] for h in emotion.default_engine(home).history(5)]
    assert kinds == ["game_won", "game_lost"]
