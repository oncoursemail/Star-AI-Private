"""STAR's emotion engine (star/emotion.py): the state, decay, persistence, reading praise and criticism, per-person
attachment, the age gate on romance, and the four places it is wired (desktop chat, verify ladder, voice call, promoter)."""
import json
import re
import sqlite3
import threading
from types import SimpleNamespace

import pytest

import star.desktop_core as core
from star import emotion
from star.emotion import BASELINE, EmotionEngine, Prosody, appraise
from star.voice.call import CallConfig, CallSession
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech, wait_for

HOUR = 3600.0


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


def step(clock, engine, kind, seconds=60, **kw):
    clock.advance(seconds)
    return engine.on_event(kind, **kw)


# -- state, events, decay ------------------------------------------------------------------------------------------

def test_a_fresh_state_sits_at_the_baseline_and_says_nothing(engine):
    state = engine.snapshot()
    assert state["emotions"] == BASELINE
    assert state["directive"] == "" and state["dominant"] is None
    assert state["prosody"].neutral and state["avatar"]["face"] == "idle"


def test_repeated_failure_builds_frustration_and_a_clipped_tone(engine, clock):
    after_one = step(clock, engine, "task_failure")
    after_four = after_one
    for _ in range(3):
        after_four = step(clock, engine, "task_failure")
    assert after_four["emotions"]["frustration"] > after_one["emotions"]["frustration"] + 0.3
    assert after_four["dominant"] == "frustration"
    assert "flat and short" in after_four["directive"]
    assert after_four["avatar"]["face"] == "oops"
    assert after_four["valence"] < 0


def test_a_fix_after_many_failures_is_a_bigger_relief_than_a_first_try_win(tmp_path, clock):
    a, b = EmotionEngine(tmp_path / "a.sqlite3", clock=clock), EmotionEngine(tmp_path / "b.sqlite3", clock=clock)
    for _ in range(4):
        step(clock, a, "task_failure")
    relieved = step(clock, a, "bug_fixed")
    plain = step(clock, b, "bug_fixed")
    assert relieved["emotions"]["pride"] > plain["emotions"]["pride"]
    assert relieved["emotions"]["frustration"] < 0.5
    assert relieved["dominant"] in {"pride", "joy"}


def test_feelings_fall_back_to_the_baseline_by_their_half_life(engine, clock):
    step(clock, engine, "owner_praise")
    peak = engine.snapshot()["emotions"]["joy"]
    clock.advance(emotion.HALF_LIFE_HOURS["joy"] * HOUR)
    halfway = engine.snapshot()["emotions"]["joy"]
    assert halfway == pytest.approx(BASELINE["joy"] + (peak - BASELINE["joy"]) / 2, abs=0.02)   # drift is tiny
    clock.advance(40 * HOUR)
    assert engine.snapshot()["emotions"]["joy"] == pytest.approx(BASELINE["joy"], abs=0.02)
    assert "good mood" not in engine.snapshot()["directive"]          # (forty hours of quiet make her restless instead)


def test_the_state_survives_a_restart_and_a_damaged_file_starts_over(tmp_path, clock):
    path = tmp_path / "e.sqlite3"
    first = EmotionEngine(path, clock=clock)
    step(clock, first, "creative_done")
    saved = first.snapshot()["emotions"]
    assert EmotionEngine(path, clock=clock).snapshot()["emotions"] == saved
    with sqlite3.connect(path) as db:
        db.execute("UPDATE state SET json='{broken'")
    assert EmotionEngine(path, clock=clock).snapshot()["emotions"] == BASELINE


def test_a_long_silence_makes_her_restless_and_a_message_ends_it(engine, clock):
    engine.on_event("owner_message")
    clock.advance(10 * HOUR)
    bored = engine.snapshot()
    assert bored["emotions"]["boredom"] > BASELINE["boredom"] + 0.2
    assert bored["dominant"] == "boredom" and "restless" in bored["directive"]
    assert bored["prosody"].rate < 1.0 and bored["prosody"].pause_ms > 0      # slower, longer pauses
    engine.on_message("hey you")
    assert engine.snapshot()["emotions"]["boredom"] < bored["emotions"]["boredom"] - 0.1


def test_the_host_can_report_idle_hours_it_knows_about(engine, clock):
    engine.on_event("owner_message")
    state = engine.on_event("idle", hours=6)
    assert state["emotions"]["boredom"] > BASELINE["boredom"] + 0.1


def test_the_same_event_again_at_once_counts_less(tmp_path, clock):
    def second_gain(gap):
        engine = EmotionEngine(tmp_path / f"gap{gap}.sqlite3", clock=clock)
        engine.on_event("creative_done")
        clock.advance(gap)
        before = engine.snapshot()["emotions"]["pride"]
        return engine.on_event("creative_done")["emotions"]["pride"] - before
    assert second_gain(1) < 0.6 * second_gain(600)


def test_unknown_events_and_bad_person_ids_are_refused_but_the_module_api_never_raises(engine, tmp_path):
    with pytest.raises(ValueError):
        engine.on_event("won_the_lottery")
    with pytest.raises(ValueError):
        engine.on_event("task_success", person="Alice Smith, alice@example.com")
    assert emotion.on_event("won_the_lottery", home=tmp_path) is None
    assert emotion.on_event("task_success", home=tmp_path)["emotions"]["joy"] >= BASELINE["joy"]


def test_concurrent_writers_do_not_lose_updates(engine):
    def work():
        for _ in range(10):
            engine.on_event("learned_something", strength=0.0)
    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(engine.history(100)) == 40


# -- reading the owner's words -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("nice work, that is exactly what I wanted", "owner_praise"),
    ("Amazing, you nailed it", "owner_praise"),
    ("thanks!", "owner_thanks"),
    ("that's wrong again", "owner_criticism"),
    ("it still doesn't work", "owner_criticism"),
    ("great, but it's still broken", "owner_criticism"),
    ("that is not good", "owner_criticism"),
    ("how many times do I have to say it", "owner_criticism"),
    ("hey, it is okay, you are doing great", "owner_comfort"),
    ("don't worry about it", "owner_comfort"),
])
def test_praise_criticism_and_thanks_are_recognised(text, kind):
    assert appraise(text)[0] == kind


@pytest.mark.parametrize("text", [
    "what's wrong with my script?", "add a part to the workspace", "", "make the door open when I touch it",
    "here is the log: " + "error: wrong value, terrible state, useless frame\n" * 20])
def test_ordinary_requests_and_pasted_logs_are_not_remarks_about_her(text):
    assert appraise(text) is None


def test_praise_warms_her_and_criticism_unsettles_her(tmp_path, clock):
    a, b = EmotionEngine(tmp_path / "a.sqlite3", clock=clock), EmotionEngine(tmp_path / "b.sqlite3", clock=clock)
    clock.advance(60)
    assert a.on_message("nice work, thank you") == "owner_praise"
    assert b.on_message("this is useless, you broke it") == "owner_criticism"
    happy, shaken = a.snapshot(), b.snapshot()
    assert happy["valence"] > shaken["valence"] + 0.3
    assert happy["emotions"]["joy"] > BASELINE["joy"] + 0.1 and happy["directive"]
    assert shaken["emotions"]["nervousness"] > BASELINE["nervousness"] + 0.1
    assert shaken["emotions"]["pride"] < BASELINE["pride"]


# -- expression ----------------------------------------------------------------------------------------------------

def test_the_directive_is_short_plain_words_with_no_numbers(engine, clock):
    for kind in ("owner_praise", "task_failure", "task_failure", "task_failure", "creative_done", "owner_criticism"):
        state = step(clock, engine, kind)
        assert not re.search(r"\d", state["directive"])
        assert len(state["directive"].split()) <= emotion.MAX_BOND_NOTE_WORDS      # ~12-16 tokens: each costs ~20 ms on brain 1


def test_conflicting_feelings_are_not_voiced_together(engine, clock):
    for _ in range(3):
        step(clock, engine, "task_failure")
    state = step(clock, engine, "owner_praise")
    directive = state["directive"]
    assert not ("clipped" in directive and "good mood" in directive)


def test_prosody_stays_subtle_and_inside_what_the_voice_accepts(engine, clock):
    for _ in range(8):
        state = step(clock, engine, "task_failure", seconds=30)
        p = state["prosody"]
        assert 0.92 <= p.rate <= 1.08 and abs(p.pitch_semitones) <= 0.8 and -40 <= p.pause_ms <= 60
    joyful = step(clock, engine, "owner_praise")
    assert joyful["prosody"].pitch_semitones > 0 or joyful["prosody"].rate > 1.0


def test_the_avatar_gets_a_face_and_a_cue_the_stage_accepts(engine, clock):
    from star.stream_motion import CUES, ExpressionCue
    state = step(clock, engine, "creative_done")
    assert state["avatar"]["face"] == "happy" and state["avatar"]["cue"] in CUES
    ExpressionCue(at_s=0.0, kind=state["avatar"]["cue"], strength=state["avatar"]["strength"])      # validates


# -- people: attachment and the age gate -----------------------------------------------------------------------------

def grow_bond(engine, clock, person, times=30, text="thanks, great job"):
    for _ in range(times):
        clock.advance(120)
        engine.on_message(text, person=person)


def test_attachment_grows_with_good_time_per_person_with_diminishing_returns(engine, clock):
    grow_bond(engine, clock, "friend-1", 10)
    early = engine.snapshot("friend-1")["bond"]
    grow_bond(engine, clock, "friend-1", 10)
    later = engine.snapshot("friend-1")["bond"]
    assert 0.2 < early < later < 1.0 and later - early < early        # still growing, slower
    assert engine.snapshot("friend-2")["bond"] == 0.0 and engine.snapshot()["bond"] == 0.0


def test_harsh_words_dent_attachment_a_little_and_weeks_of_silence_fade_it(engine, clock):
    grow_bond(engine, clock, "friend-1", 30)
    peak = engine.snapshot("friend-1")["bond"]
    clock.advance(60)
    engine.on_message("you are useless, how many times", person="friend-1")
    dented = engine.snapshot("friend-1")["bond"]
    assert peak - 0.1 < dented < peak
    clock.advance(emotion.BOND_HALF_LIFE_DAYS * 86400)
    assert engine.snapshot("friend-1")["bond"] == pytest.approx(dented / 2, abs=0.03)


def test_a_close_friend_gets_warmer_wording_but_romance_needs_a_verified_adult(engine, clock):
    grow_bond(engine, clock, "friend-1", 40)
    assert engine.snapshot("friend-1")["bond"] >= emotion.BOND_CLOSE
    for adult in (None, False):
        text = engine.snapshot("friend-1", adult)["directive"]
        assert "close to them" in text or "matter a lot" in text
        assert "flirt" not in text and "ador" not in text and "banter" not in text
    adult_text = engine.snapshot("friend-1", True)["directive"]
    assert "flirty banter" in adult_text and "tasteful" in adult_text and "follow their lead" in adult_text


def test_deep_attachment_may_say_it_adores_them_only_to_a_verified_adult(engine, clock):
    grow_bond(engine, clock, "friend-1", 120)
    assert engine.snapshot("friend-1")["bond"] >= emotion.BOND_DEVOTED
    assert "adoring" in engine.snapshot("friend-1", True)["directive"]
    assert "adoring" not in engine.snapshot("friend-1", None)["directive"]
    assert "adoring" not in engine.snapshot("friend-1", "yes")["directive"]      # only the real boolean True counts
    assert "flirt" not in emotion.directive(person="friend-1", partner_adult=None, home=engine.path.parent)


def test_a_stranger_never_gets_flirting_even_when_marked_adult(engine):
    assert "flirt" not in engine.snapshot("new-person", True)["directive"]


# -- the places it is wired ------------------------------------------------------------------------------------------

def test_the_setting_is_off_by_default_and_must_be_a_boolean():
    assert core.Settings().emotion_enabled is False
    with pytest.raises(ValueError):
        core.Settings(emotion_enabled="yes").validate()


def test_the_verify_ladder_verdict_becomes_an_emotion(tmp_path):
    emotion.on_run_event({"event": "verify_started"}, home=tmp_path)
    assert not (tmp_path / "emotion.sqlite3").exists()
    emotion.on_run_event({"event": "verify_finished", "verified": False, "fixed": False, "rounds": 2}, home=tmp_path)
    after_fail = emotion.current(tmp_path)["emotions"]["frustration"]
    assert after_fail > BASELINE["frustration"] + 0.1
    emotion.on_run_event({"event": "verify_finished", "verified": True, "fixed": True, "rounds": 3}, home=tmp_path)
    state = emotion.current(tmp_path)
    assert state["emotions"]["frustration"] < after_fail and state["emotions"]["pride"] > BASELINE["pride"] + 0.1
    assert [h["kind"] for h in emotion.default_engine(tmp_path).history(5)] == ["bug_fixed", "task_failure"]


def test_a_promotion_that_goes_live_pleases_her_only_when_the_setting_is_on(tmp_path):
    emotion.on_event("promotion", home=tmp_path, only_if_enabled=True)
    assert not (tmp_path / "emotion.sqlite3").exists()
    (tmp_path / "settings.json").write_text(json.dumps({"emotion_enabled": True}), encoding="utf-8")
    emotion.on_event("promotion", home=tmp_path, only_if_enabled=True)
    assert emotion.current(tmp_path)["emotions"]["pride"] > BASELINE["pride"]


class _Models:
    def __init__(self, sent, text="Sure, here you go.", fail=False):
        self.sent, self.text, self.fail = sent, text, fail

    async def create(self, **kwargs):
        self.sent.append(kwargs)
        if self.fail:
            raise RuntimeError("model down")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text, tool_calls=None))])


def _client(models):
    class Client:
        chat = SimpleNamespace(completions=models)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False
    return Client()


def _last_user_text(sent):
    content = sent[-1]["messages"][-1]["content"]
    return content if isinstance(content, str) else json.dumps(content)


def test_desktop_chat_feels_the_owners_praise_and_tells_the_model_the_tone(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    sent = []
    monkeypatch.setattr(core, "open_client", lambda settings, **_: _client(_Models(sent)))
    core.app_data().mkdir(parents=True, exist_ok=True)
    core.run_task(core.Settings(model="m", emotion_enabled=True), "amazing, you nailed it, thank you so much", mode="fast")
    sent_text = _last_user_text(sent)
    assert emotion.HEADING in sent_text
    assert emotion.current(core.app_data())["emotions"]["joy"] > BASELINE["joy"] + 0.1


def test_desktop_chat_is_untouched_when_the_setting_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    sent = []
    monkeypatch.setattr(core, "open_client", lambda settings, **_: _client(_Models(sent)))
    core.app_data().mkdir(parents=True, exist_ok=True)
    core.run_task(core.Settings(model="m"), "amazing, you nailed it, thank you so much", mode="fast")
    assert emotion.HEADING not in _last_user_text(sent)
    assert not (core.app_data() / "emotion.sqlite3").exists()


def test_a_failed_task_is_felt_but_a_stop_the_owner_asked_for_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    sent = []
    monkeypatch.setattr(core, "open_client", lambda settings, **_: _client(_Models(sent, fail=True)))
    core.app_data().mkdir(parents=True, exist_ok=True)
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(Exception):
        core.run_task(core.Settings(model="m", emotion_enabled=True), "build a door", mode="fast", cancel_event=stopped)
    assert "task_failure" not in [h["kind"] for h in emotion.default_engine(core.app_data()).history(10)]
    with pytest.raises(Exception):
        core.run_task(core.Settings(model="m", emotion_enabled=True), "build a door", mode="fast")
    assert "task_failure" in [h["kind"] for h in emotion.default_engine(core.app_data()).history(10)]


# -- voice call ------------------------------------------------------------------------------------------------------

TEXTS = {1: "nice work, thank you so much", 2: "do it again"}
END = quiet(40)


class ProsodyTTS(FakeTTS):
    def __init__(self):
        super().__init__()
        self.prosody = []

    def synthesize(self, text, prosody=None):
        self.prosody.append(prosody)
        return super().synthesize(text)


def call(tmp_path, clock, *, emotion_on, tts=None, adult=None):
    events, speaker, tts = Events(), FakeSpeaker(), tts or ProsodyTTS()
    brain = FakeBrain(["Oh, thank you. That means a lot."])
    engine = EmotionEngine(tmp_path / "voice.sqlite3", clock=clock) if emotion_on else None
    config = CallConfig(turn=TurnConfig(), partial_transcripts=False, emotion=emotion_on, emotion_partner_adult=adult)
    session = CallSession(vad=FakeVAD(), asr=FakeASR(TEXTS, 0.0), brain=brain, tts=tts, speaker=speaker,
                          config=config, on_event=events, emotion_engine=engine)
    session.start()
    for frame in speech(1, 20) + END:
        session.feed(frame)
    assert session.wait_idle(5)
    return session, events, brain, tts, engine


def test_a_voice_call_with_emotion_adds_the_tone_shifts_the_voice_and_signals_the_avatar(tmp_path, clock):
    session, events, brain, tts, engine = call(tmp_path, clock, emotion_on=True)
    sent = brain.requests[0][-1]["content"]
    assert sent.startswith(TEXTS[1]) and "(mood: " in sent
    assert session.history[0] == {"role": "user", "content": TEXTS[1]}          # history never holds the note
    assert any(p is not None and not p.neutral for p in tts.prosody)
    note = events.of("emotion")[0]
    assert note["avatar"]["face"] == "happy" and note["dominant"] in {"joy", "pride", "affection"}
    assert engine.snapshot()["emotions"]["joy"] > BASELINE["joy"]


def test_a_voice_call_without_emotion_is_exactly_as_before(tmp_path, clock):
    session, events, brain, tts, _ = call(tmp_path, clock, emotion_on=False)
    assert brain.requests[0][-1] == {"role": "user", "content": TEXTS[1]}
    assert all(p is None for p in tts.prosody) and not events.of("emotion")


def test_a_voice_engine_that_takes_no_prosody_still_speaks(tmp_path, clock):
    session, events, brain, tts, _ = call(tmp_path, clock, emotion_on=True, tts=FakeTTS())
    assert tts.spoken == ["Oh, thank you.", "That means a lot."]


def test_kokoro_applies_the_shifts_to_speed_pitch_and_pause():
    from star.voice.engines import KokoroTTS, pitch_ratio
    asked = []

    class Fake:
        def create(self, text, voice, speed, lang):
            import numpy as np
            asked.append(speed)
            return np.zeros(2400, dtype="float32"), 24000

    tts = KokoroTTS.__new__(KokoroTTS)
    tts._kokoro, tts._style, tts._lock = Fake(), None, threading.Lock()
    tts.speed, tts.lang, tts.gap_ms, tts.pitch_semitones = 0.8, "en-us", 120, 0.0
    plain = list(tts.synthesize("Hello."))
    shifted = list(tts.synthesize("Hello.", prosody=Prosody(rate=1.05, pitch_semitones=0.5, pause_ms=40)))
    assert asked[0] == pytest.approx(0.8)
    assert asked[1] == pytest.approx(0.8 * 1.05 / pitch_ratio(0.5))
    assert len(plain[1][0]) == 2 * int(24000 * 0.120) and len(shifted[1][0]) == 2 * int(24000 * 0.160)
