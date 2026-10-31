"""Expressive voice with fake engines: tags, mood -> style, sounds, consent, character library, guard, streaming, songs."""
import json
import random
import wave

import pytest

from star.voice import styles as S
from star.voice.chunker import SentenceChunker, speakable
from star.voice.library import CharacterLibrary, ConsentRecord, Refused, kokoro_fallback, parse_script
from star.voice.persona import system_message
from star.voice.singing import can_sing, compose, midi, parse_melody, syllable_count

np = pytest.importorskip("numpy")

from star.voice import voicedsp  # noqa: E402
from star.voice.expressive import ExpressiveConfig, ExpressiveTTS  # noqa: E402
from star.voice.guard import ArtefactGuard, GuardedTTS, GuardStats, new_loops, wer  # noqa: E402
from star.voice.nonverbal import NonverbalBank, route, write_wav  # noqa: E402

SR = 24000


# -- fakes ----------------------------------------------------------------------------------------------------------
def voiced(seconds: float, f0: float = 190.0, level: float = 0.2, sr: int = SR):
    t = np.arange(int(seconds * sr)) / sr
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8))
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 3.0 * t) ** 2          # syllable-ish loudness movement
    return (level * x * envelope / 2.0).astype(np.float32)


class FakeBase:
    """A deterministic 'voice': 0.3 s of a harmonic tone per word, PCM16 chunks like KokoroTTS."""
    sample_rate = SR
    gap_ms = 0

    def __init__(self):
        self.calls = []

    def synthesize_float(self, text, voice=None, rate=1.0, pitch_semitones=0.0, seed=0, instruct=None):
        self.calls.append({"text": text, "voice": voice, "rate": rate})
        words = max(1, len(text.split()))
        return voiced(0.3 * words / rate), SR

    def synthesize(self, text, prosody=None):
        x, sr = self.synthesize_float(text)
        yield voicedsp.as_pcm(x), sr


class FakeASR:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def transcribe(self, pcm, sample_rate=16000):
        self.calls += 1
        return self.replies.pop(0) if self.replies else ""


class SeededEngine:
    """Returns good audio only for the seeds in `good`; other seeds give a clipped mess."""
    name = "fake-neural"

    def __init__(self, good=(1,)):
        self.good, self.seeds = set(good), []

    def synthesize_float(self, text, seed=0, instruct=None):
        self.seeds.append(seed)
        x = voiced(0.3 * len(text.split()))
        if seed not in self.good:
            x = np.clip(x * 40.0, -1.0, 1.0)
        return x, SR


# -- tags -----------------------------------------------------------------------------------------------------------
def test_parse_styles_sounds_pauses_and_intensity():
    segs = S.parse("<excited:0.9> We did it! <laugh> [sigh] Okay. <pause:450> Done.", "warm")
    kinds = [(s.kind, s.text, s.style) for s in segs]
    assert kinds[0] == ("speech", "We did it!", "excited") and segs[0].intensity == 0.9
    assert ("sound", "laugh", "excited") in kinds and any(s.kind == "sound" and s.text == "sigh" for s in segs)
    assert [s.pause_ms for s in segs if s.kind == "pause"] == [450]
    assert all(s.style == "excited" for s in segs if s.kind == "speech")      # lasts to the end of the reply


def test_unknown_tags_and_aliases():
    assert S.strip_tags("Use <b>bold</b> and [1] <laugh> here.") == "Use <b>bold</b> and [1] here."
    assert S.canonical("mommy") == ("style", "caring") and S.canonical("laughs") == ("sound", "laugh")
    assert S.canonical("clear throat") == ("sound", "clear-throat") and S.canonical("bold") is None
    assert S.parse("<pause:99999> Hi.")[0].pause_ms == S.MAX_PAUSE_MS


def test_style_never_changes_mid_sentence():
    segs = S.parse("And then, <whisper> a secret. Next one.", "warm")
    assert [(s.text, s.style) for s in segs] == [("And then, a secret.", "warm"), ("Next one.", "whisper")]
    segs = S.parse("<whisper> Come closer, </whisper> dear. Normal now.", "warm")
    assert [(s.text, s.style) for s in segs] == [("Come closer, dear.", "whisper"), ("Normal now.", "warm")]


def test_style_carries_across_sentences_of_one_reply():
    segs, carry = S.parse_carry("<sleepy> It's late.", "warm")
    assert carry == ("sleepy", S.DEFAULT_INTENSITY)
    segs, carry = S.parse_carry("Time for bed.", "warm", carry=carry)
    assert segs[0].style == "sleepy"
    segs, carry = S.parse_carry("Night.</sleepy> Bye.", "warm", carry=carry)
    assert [s.style for s in segs] == ["sleepy", "warm"] and carry is None


def test_questions_and_emphasis():
    yes_no, wh = S.parse("Is it done? Where is it?")
    assert yes_no.question and not wh.question
    seg = S.parse("I <emph>really</emph> mean it.")[0]
    assert seg.text == "I really mean it." and seg.emphasis == ("really",)


def test_chunker_keeps_tags_for_expressive_and_strips_them_otherwise():
    c = SentenceChunker(keep_tags=True)
    parts = c.feed("<excited:0.8> We did it! <laugh> Oh wow. <pause:600> Bye.") + c.flush()
    assert parts == ["<excited:0.8> We did it!", "<laugh> Oh wow.", "<pause:600> Bye."]
    assert speakable("Hi <laugh> there [whisper] ok.") == "Hi there ok."
    plain = SentenceChunker()
    assert plain.feed("<sigh> Okay then. ") + plain.flush() == ["Okay then."]


def test_restrict_and_sound_policy():
    segs = S.parse("<sarcastic> Great. <laugh> <sigh> Sure.", "warm")
    kept = S.restrict(segs, frozenset({"warm"}), frozenset({"laugh"}), fallback="warm")
    assert {s.style for s in kept if s.kind == "speech"} == {"warm"}
    assert [s.text for s in kept if s.kind == "sound"] == ["laugh"]
    now = [100.0]
    policy = S.SoundPolicy(per_reply=2, per_minute=3, repeat_gap=30.0, clock=lambda: now[0])
    out = policy.filter(S.parse("<laugh> <giggle> <gasp> Hi. <um> <uh>"))
    assert [s.text for s in out if s.kind == "sound"] == ["laugh", "giggle"]
    now[0] += 5
    assert [s.text for s in policy.filter(S.parse("<laugh> <sigh> Hi."))] == ["sigh", "Hi."]   # laugh repeats too soon
    now[0] += 120
    fillers = policy.filter(S.parse("<um> Well <uh> okay."))
    assert sum(1 for s in fillers if s.kind == "sound") == 1


# -- mood -> style ----------------------------------------------------------------------------------------------------
def test_style_follows_mood():
    assert S.style_for_mood(None, "warm").style == "warm"
    assert S.style_for_mood({"dominant": "sadness", "arousal": 0.3}).style == "sad"
    assert S.style_for_mood({"dominant": "excitement", "arousal": 0.8}).style == "excited"
    assert S.style_for_mood({"dominant": "excitement", "arousal": 0.2}).style == "happy"
    assert S.style_for_mood({"dominant": "love", "arousal": 0.4}).style == "tender"
    hi = S.style_for_mood({"dominant": "amusement", "arousal": 0.9}).intensity
    lo = S.style_for_mood({"dominant": "amusement", "arousal": 0.1}).intensity
    assert hi > lo


def test_conversation_comes_before_her_own_mood():
    happy = {"dominant": "joy", "arousal": 0.8}
    assert S.style_for_context("I had a really bad day", happy).style == "caring"
    assert S.style_for_context("I can't sleep", happy).style == "soft"
    assert S.style_for_context("haha that's funny", None).style == "playful"
    assert S.style_for_context("I got the job!!", None).style == "excited"
    assert S.style_for_context("ok", None, hour=23).style == "soft"
    assert S.style_for_context("ok", happy, hour=14).style == "happy"


def test_mood_sounds_are_rare_and_fitting():
    rng = random.Random(3)
    picks = [S.suggest_sound({"dominant": "amusement", "arousal": 0.6}, rng) for _ in range(400)]
    chosen = [p for p in picks if p]
    assert 0.1 < len(chosen) / 400 < 0.5 and set(chosen) <= {"giggle", "chuckle", "laugh"}
    assert S.suggest_sound({"dominant": "pride", "arousal": 0.6}, rng) is None


def test_fillers_at_most_one_and_never_in_serious_or_tagged_text():
    text = "Well, I think so. Then we try again, slowly."
    out = S.add_fillers(text, random.Random(1), chance=1.0)
    assert out != text and sum(out.count(t) for t in ("<um>", "<uh>", "<pause:180>")) == 1
    assert S.add_fillers(text, random.Random(1), chance=1.0, style="serious") == text
    assert S.add_fillers("<laugh> " + text, random.Random(1), chance=1.0) == "<laugh> " + text


def test_persona_teaches_tags_only_when_expressive():
    assert "<whisper>" not in system_message()["content"]
    assert "<whisper>" in system_message(expressive=True)["content"]


# -- character library and consent ------------------------------------------------------------------------------------
def test_library_crud(tmp_path):
    lib = CharacterLibrary(tmp_path / "chars.json")
    brine = lib.create_designed("Captain Brine", "A gruff old sea captain, deep gravelly man's voice, slow.")
    assert brine.kind == "designed" and brine.voice.startswith("am_") and brine.pitch_semitones < 0
    lib.create_own("Star calm", "af_heart:1.0", style="calm")
    assert [c.name for c in CharacterLibrary(tmp_path / "chars.json").list()] == ["Captain Brine", "Star calm"]
    assert lib.get("captain brine").id == brine.id
    with pytest.raises(ValueError):
        lib.create_designed("captain brine", "Another voice entirely.")
    updated = lib.update(brine.id, name="Old Brine", style="serious")
    assert updated.name == "Old Brine" and lib.get("Old Brine").style == "serious"
    with pytest.raises(ValueError):
        lib.update("Old Brine", kind="clone")
    assert lib.delete("Old Brine") and not lib.delete("Old Brine")
    assert [c.name for c in lib.list()] == ["Star calm"]


def test_designed_voices_refuse_real_people_and_children(tmp_path):
    lib = CharacterLibrary(tmp_path / "chars.json")
    for bad in ("Sound like Morgan Freeman, deep and calm.", "Taylor Swift's voice please",
                "Imitate Barack Obama", "A little girl, about 7 years old"):
        with pytest.raises(Refused):
            lib.create_designed("X", bad)
    assert lib.list() == []


def _wav(path, seconds=2.0):
    write_wav(path, voiced(seconds), SR)
    return path


def test_clone_needs_complete_recorded_consent(tmp_path):
    lib = CharacterLibrary(tmp_path / "chars.json")
    clip = _wav(tmp_path / "sam.wav")
    with pytest.raises(Refused):
        lib.create_clone("Sam", str(clip), None)
    missing_audio = ConsentRecord("Sam Lee", "I, Sam Lee, consent to Star using my voice.", str(tmp_path / "none.wav"))
    with pytest.raises(Refused, match="recording"):
        lib.create_clone("Sam", str(clip), missing_audio)
    vague = ConsentRecord("Sam Lee", "sure whatever", str(_wav(tmp_path / "c1.wav")))
    with pytest.raises(Refused, match="consent"):
        lib.create_clone("Sam", str(clip), vague)
    other = ConsentRecord("Sam Lee", "I, Alex, consent to Star using my voice.", str(_wav(tmp_path / "c2.wav")))
    with pytest.raises(Refused, match="name"):
        lib.create_clone("Sam", str(clip), other)
    good = ConsentRecord("Sam Lee", "I, Sam Lee, consent to Star using my voice for role-play.",
                         str(_wav(tmp_path / "c3.wav")))
    sam = lib.create_clone("Sam", str(clip), good)
    stored = json.loads((tmp_path / "chars.json").read_text())["characters"][0]
    assert sam.kind == "clone" and stored["consent"]["speaker_name"] == "Sam Lee"
    with pytest.raises(Refused):
        lib.update("Sam", reference_clip=str(clip))
    assert lib.revoke_consent("sam lee") == 1 and lib.list() == []
    assert assert_revoked(good)


def assert_revoked(record):
    record.revoked = True
    return "consent was revoked" in record.problems()


def test_kokoro_fallback_reads_the_description():
    assert kokoro_fallback("a posh British gentleman")[0].startswith("bm_")
    recipe, pitch, speed = kokoro_fallback("a bright, bubbly young woman, quick")
    assert recipe.startswith("af_") and pitch > 0 and speed > 1


def test_roleplay_script_parsing():
    lines = parse_script('Narrator: Night fell.\nBrine: Hold fast!\nNote: plain prose here.\n'
                         'She smiled. <voice name="Wren">Remarkable.</voice>', known={"Brine", "Wren"})
    assert [(l.speaker, l.text) for l in lines] == [
        ("narrator", "Night fell."), ("Brine", "Hold fast!"), ("narrator", "Note: plain prose here."),
        ("narrator", "She smiled."), ("Wren", "Remarkable.")]


# -- artefact guard (fake ASR) ----------------------------------------------------------------------------------------
def test_wer_and_loops():
    assert wer("I am so proud of you", "I am so proud of you") == 0.0
    assert wer("I am so proud of you", "I am proud you") == pytest.approx(2 / 6)
    assert "you did" in new_loops("the end", "you did it you did it you did it")
    assert new_loops("no, no, no, no", "no no no no") == []


def test_guard_catches_skipped_words_loops_clipping_and_silence():
    text = "You found that bug all by yourself."
    good = voiced(0.3 * 7)
    assert ArtefactGuard(FakeASR([text])).check(good, SR, text).ok
    skipped = ArtefactGuard(FakeASR(["you found yourself"])).check(good, SR, text)
    assert "asr" in skipped.problems
    looped = ArtefactGuard(FakeASR([text + " by yourself by yourself by yourself"])).check(good, SR, text)
    assert "loop" in looped.problems
    clipped = ArtefactGuard().check(np.clip(good * 50, -1, 1), SR, text)
    assert "clipping" in clipped.problems
    holed = np.concatenate([good[:SR], np.zeros(int(1.6 * SR), dtype=np.float32), good[SR:]])
    assert "silence" in ArtefactGuard().check(holed, SR, text).problems
    rambling = np.tile(good, 6)
    assert "length" in ArtefactGuard().check(rambling, SR, text).problems


def test_guard_speaker_similarity_for_clones():
    class Embed:
        def embed(self, x, sr):
            return np.array([1.0, 0.0]) if float(np.abs(x).mean()) < 0.2 else np.array([0.0, 1.0])
    guard = ArtefactGuard(embedder=Embed())
    assert guard.check(voiced(1.5), SR, "Hello there my friend.", reference=np.array([1.0, 0.0])).ok
    drifted = guard.check(voiced(1.5, level=0.9), SR, "Hello there my friend.", reference=np.array([1.0, 0.0]))
    assert "speaker" in drifted.problems


def test_guarded_tts_resynthesises_with_new_seed_and_logs(tmp_path):
    engine = SeededEngine(good=(2,))
    stats = GuardStats(tmp_path / "guard.jsonl")
    samples, sr, report = GuardedTTS(engine, ArtefactGuard(), attempts=3, stats=stats).render("One two three four.")
    assert engine.seeds == [0, 1, 2] and report.ok
    summary = stats.summary()
    assert summary["attempts"] == 3 and summary["rejected"] == 2 and summary["rejection_rate"] == pytest.approx(0.667, 0.01)
    assert summary["reasons"]["clipping"] == 2 and len((tmp_path / "guard.jsonl").read_text().splitlines()) == 2
    hopeless = SeededEngine(good=())
    _, _, report = GuardedTTS(hopeless, ArtefactGuard(), attempts=2, stats=stats).render("One two three.")
    assert not report.ok and stats.summary()["gave_up"] == 1


# -- non-verbal routing -----------------------------------------------------------------------------------------------
def test_sound_routing(tmp_path):
    bank_dir = tmp_path / "sounds"
    _wav(bank_dir / "sigh" / "0.wav", 0.5)
    _wav(bank_dir / "sigh" / "1.wav", 0.5)
    bank = NonverbalBank(bank_dir)
    assert route("laugh", "chatterbox-turbo", bank).how == "native"
    assert route("sigh", "kokoro", bank).how == "clip"
    assert route("mm-hm", "kokoro", bank) == route("mm-hm", "", None) and route("mm-hm", "", None).how == "text"
    assert route("sneeze", "kokoro", bank).how == "skip"                  # never read "achoo" aloud
    rng = random.Random(0)
    picks = [bank.pick("sigh", rng).name for _ in range(6)]
    assert all(a != b for a, b in zip(picks, picks[1:]))                  # no identical clip twice in a row
    assert bank.available() == ["sigh"]


# -- the engine: streaming chunks, splicing, loudness ---------------------------------------------------------------
def make_tts(tmp_path, **config):
    bank_dir = tmp_path / "sounds"
    write_wav(bank_dir / "laugh" / "0.wav", voiced(0.6, 300.0, 0.05), SR)
    lib = CharacterLibrary(tmp_path / "chars.json")
    lib.create_designed("Brine", "A gruff old sea captain, deep man's voice.")
    cfg = ExpressiveConfig(**config)
    tts = ExpressiveTTS(FakeBase(), bank=NonverbalBank(bank_dir), library=lib, config=cfg)
    tts.rng = random.Random(1)
    return tts


def test_one_chunk_per_segment_streams_in_order(tmp_path):
    tts = make_tts(tmp_path)
    chunks = list(tts.synthesize("Oh! <laugh> That's lovely."))
    kinds = [e.get("kind") for e in tts.last]
    assert kinds == ["speech", "sound", "speech"] and tts.last[1]["route"] == "clip"
    assert len(chunks) == 3 and all(rate == SR for _, rate in chunks)
    speech_levels = [voicedsp.loudness(voicedsp.as_float(pcm), SR) for pcm, _ in (chunks[0], chunks[2])]
    for level in speech_levels:
        assert level == pytest.approx(-18.0 + S.STYLES["warm"].gain_db * S.DEFAULT_INTENSITY, abs=1.0)
    laugh = voicedsp.loudness(voicedsp.as_float(chunks[1][0]), SR)
    assert laugh == pytest.approx(-18.0 + S.SOUNDS["laugh"].level_db, abs=1.5)
    assert all(voicedsp.peak_db(voicedsp.as_float(pcm)) <= -0.9 for pcm, _ in chunks)


def test_allowed_styles_asmr_and_sounds_off(tmp_path):
    tts = make_tts(tmp_path, allowed_styles=frozenset({"warm"}), sounds=False)
    list(tts.synthesize("<sarcastic> Oh great. <laugh>"))
    assert [e["style"] for e in tts.last if e["kind"] == "speech"] == ["warm"]
    assert not [e for e in tts.last if e["kind"] == "sound"]
    asmr = make_tts(tmp_path / "a", asmr=True)
    asmr.set_mood({"dominant": "excitement", "arousal": 0.9}, "great news!!")
    list(asmr.synthesize("You did so well. Rest now."))
    assert {e["style"] for e in asmr.last if e["kind"] == "speech"} == {"asmr"}


def test_set_mood_picks_tone_and_resets_carry(tmp_path):
    tts = make_tts(tmp_path)
    assert tts.set_mood({"dominant": "sadness", "arousal": 0.3}, "").style == "sad"
    list(tts.synthesize("<whisper> Psst."))
    list(tts.synthesize("Still quiet."))
    assert tts.last[0]["style"] == "whisper"
    tts.set_mood(None, "I had a bad day")
    list(tts.synthesize("Oh, love."))
    assert tts.last[0]["style"] == "caring"


def test_quality_mode_uses_neural_and_falls_back_when_guard_rejects(tmp_path):
    good = make_tts(tmp_path / "g", mode="quality")
    good.neural, good.guard = SeededEngine(good=(0,)), ArtefactGuard()
    list(good.synthesize("Hello there, my dear friend."))
    assert good.last[0]["engine"] == "fake-neural"
    bad = make_tts(tmp_path / "b", mode="quality")
    bad.neural, bad.guard = SeededEngine(good=()), ArtefactGuard()
    list(bad.synthesize("Hello there, my dear friend."))
    assert bad.last[0]["engine"] == "kokoro+dsp" and bad.neural.seeds == [0, 1, 2]
    assert bad.stats.summary()["gave_up"] == 1


def test_roleplay_uses_character_voices(tmp_path):
    tts = make_tts(tmp_path)
    chunks = list(tts.speak_script("Narrator: The sea was rough.\nBrine: Hold fast!\nStranger: Hello?"))
    assert chunks
    voices = [c["voice"] for c in tts.base.calls]
    assert any(v and v.startswith("am_") for v in voices)                 # Brine's stand-in Kokoro recipe
    assert any("Stranger" in c["text"] for c in tts.base.calls)          # unknown speakers are read by the narrator


# -- DSP -----------------------------------------------------------------------------------------------------------------
def test_loudness_normalise_and_whisper_has_no_pitch():
    x = voiced(2.0, level=0.02)
    y = voicedsp.normalize(x, SR, -18.0)
    assert voicedsp.loudness(y, SR) == pytest.approx(-18.0, abs=0.3)
    from star.voice.guard import pitch_track
    w = voicedsp.whisper(voicedsp.normalize(x, SR), SR, seed=1)
    assert (pitch_track(x, SR) > 0).mean() > 0.8 and (pitch_track(w, SR) > 0).mean() < 0.2
    assert voicedsp.room_tone(0.5, SR, -60.0).size == SR // 2


# -- singing ------------------------------------------------------------------------------------------------------------
def test_singing_policy_and_composer():
    assert can_sing("sing twinkle twinkle little star")[0]
    assert can_sing("make up a lullaby about the moon")[1] == "original"
    allowed, answer = can_sing("sing Shake It Off")
    assert not allowed and "my own" in answer
    assert midi("A4") == 69 and parse_melody("C4:1 R:0.5")[1] == (None, 0.5)
    assert syllable_count("twinkle") == 2 and syllable_count("star") == 1
    lines = ["Close your eyes now little one", "Until the morning sun"]
    song = compose("t", lines, mood="lullaby", seed=7)
    assert [len(m) for m in song.melody] == [sum(syllable_count(w) for w in l.split()) for l in lines]
    assert song.melody[-1][-1][0] == 60 and song.origin == "original"     # resolves home
    assert compose("t", lines, mood="lullaby", seed=7).melody == song.melody


# -- settings, VRAM gate, ratings ---------------------------------------------------------------------------------------
def test_settings_and_vram_gate():
    from star.senses.fastpath import expressive_allowed, vram_budget
    from star.voice.settings import VoiceSettings
    s = VoiceSettings.from_mapping({"expressive": "true", "allowed_styles": "whisper, warm", "asmr": "1"})
    assert s.expressive and s.asmr and s.call_config().expressive and s.voice_id == "star-mum"
    with pytest.raises(ValueError):
        VoiceSettings.from_mapping({"allowed_styles": "shouty"})
    assert not expressive_allowed("game", "qwen3-tts")[0] and not expressive_allowed("game-tight", "qwen3-tts")[0]
    assert expressive_allowed("off", "qwen3-tts", free_gb=4.0)[0]
    assert not expressive_allowed("off", "qwen3-tts", free_gb=1.0)[0]
    allowed, why = expressive_allowed("dedicated", "qwen3-tts", free_gb=7.0)      # 4B model + voice > 8 GB
    assert not allowed and "fast_profile off" in why
    assert vram_budget("dedicated", expressive="qwen3-tts")["used_gb"] > vram_budget("dedicated")["used_gb"]
    assert vram_budget("game", expressive="qwen3-tts")["used_gb"] == vram_budget("game")["used_gb"]


def test_ab_ratings_are_validated_and_stored(tmp_path):
    from star.voice.expressive_lab import record_rating, summarize_ratings
    path = tmp_path / "ratings.jsonl"
    record_rating(path, {"file": "style-whisper-kokoro.wav", "score": 4, "group": "style:whisper"})
    record_rating(path, {"file": "style-whisper-kokoro.wav", "score": 5})
    for bad in ({"file": "../x.wav", "score": 3}, {"file": "a.wav", "score": 9}, {"file": "a.txt", "score": 3}):
        with pytest.raises(ValueError):
            record_rating(path, bad)
    assert summarize_ratings(path) == {"files": {"style-whisper-kokoro.wav": 5}, "count": 1}


def test_write_wav_roundtrip(tmp_path):
    p = tmp_path / "x.wav"
    write_wav(p, voiced(0.2), SR)
    with wave.open(str(p)) as f:
        assert f.getframerate() == SR and f.getnchannels() == 1


def test_sing_tag_is_sung_or_falls_back_to_sing_song(tmp_path):
    tts = make_tts(tmp_path)
    chunks = list(tts.synthesize("<sing> Goodnight little star."))
    assert chunks and tts.last[-1]["style"] in ("sing", "sing-song")
    assert "<sing>" in S.TAGS_PROMPT and "never other people's song lyrics" in S.TAGS_PROMPT


def test_call_session_keeps_tags_for_the_voice_and_strips_them_for_the_screen():
    from star.voice.call import CallConfig, CallSession
    from star.voice.turn import TurnConfig
    from voice_fakes import Events, FakeASR as CallASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech

    class MoodTTS(FakeTTS):
        accepts_tags = True

        def __init__(self):
            super().__init__()
            self.moods = []

        def set_mood(self, mood, user_text=""):
            self.moods.append(user_text)

    events, tts = Events(), MoodTTS()
    brain = FakeBrain(["<laugh> Oh, well done. <whisper> I'm so proud of you."])
    session = CallSession(vad=FakeVAD(), asr=CallASR({1: "I finished my game today"}), brain=brain, tts=tts,
                          speaker=FakeSpeaker(), on_event=events,
                          config=CallConfig(turn=TurnConfig(), partial_transcripts=False, expressive=True))
    session.start()
    for frame in speech(1, 20) + quiet(40):
        session.feed(frame)
    assert session.wait_idle(5)
    assert tts.spoken == ["<laugh> Oh, well done.", "<whisper> I'm so proud of you."]
    assert [e["text"] for e in events.of("assistant_sentence")] == ["Oh, well done.", "I'm so proud of you."]
    assert tts.moods == ["I finished my game today"]
    assert "<whisper>" in brain.requests[0][0]["content"]


def test_pitch_spikes_ignore_tracker_octave_slips():
    from star.voice.guard import _pitch_spikes
    steady = np.concatenate([voiced(0.1, 190.0) for _ in range(12)])
    squeaky = np.concatenate([voiced(0.1, f) for f in (190, 330, 190, 330, 190, 330, 190, 330)])     # 9.6 st jumps
    octave = np.concatenate([voiced(0.1, f) for f in (190, 380, 190, 380, 190, 380, 190, 380)])
    assert _pitch_spikes(steady, SR) == 0
    assert _pitch_spikes(squeaky, SR) >= 3
    assert _pitch_spikes(octave, SR) < 3
