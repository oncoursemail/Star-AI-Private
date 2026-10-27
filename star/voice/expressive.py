"""ExpressiveTTS: Star's voice with tones, whispers, ASMR, little sounds, character voices and songs.

It wraps the voice the call already uses (the TextToSpeech interface: synthesize(text, prosody=None) yields PCM16
chunks), so calls, read-aloud, the STAR Microphone route and games get it with no other change (runtime.Engines.load
wraps engines.tts when VoiceSettings.expressive is on). One sentence in, its chunks out, as before:

  1. tags -> segments (star/voice/styles.py), the owner's allowed styles/sounds applied, sounds kept rare (SoundPolicy)
  2. each speech segment is rendered
       live     by the base voice (Kokoro "star-mum": 0.3 s per sentence) and shaped by DSP in that same voice:
                speed from the style, pitch level/movement/breathiness by WORLD (pyworld), whisper by spectral
                re-synthesis (voicedsp.whisper), question rise and word emphasis
       quality  by a neural engine when one is loaded (Qwen3-TTS cloned from her own voice, with the style's
                instruction), checked by the artefact guard and re-made with a new seed when bad; Kokoro+DSP when the
                guard gives up, so a sentence is never lost
  3. sounds come from the non-verbal bank in her voice (nonverbal.route), level-matched and padded with room tone
  4. ASMR: close-mic warmth (low shelf), gentle compression, slower pace, a soft breath before some sentences
  5. every chunk is loudness-normalised to TARGET_LUFS plus the style's level, with a peak ceiling

Role-play: speak_script() renders narrator + characters (star/voice/library.py) line by line. Songs: sing().
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field, replace

from . import styles as S

LIVE, QUALITY = "live", "quality"


@dataclass
class ExpressiveConfig:
    mode: str = LIVE                       # live (base voice + DSP) | quality (neural engine first)
    default_style: str = "warm"            # tone when nothing else decides (the mum voice's own warmth)
    intensity: float = S.DEFAULT_INTENSITY
    follow_mood: bool = True               # set_mood() picks the tone from the conversation and her feeling
    allowed_styles: frozenset | None = None
    allowed_sounds: frozenset | None = None
    sounds: bool = True                    # non-verbal sounds at all
    fillers: bool = False                  # an occasional "um," or micro-pause (styles.add_fillers)
    asmr: bool = False                     # whole reply in ASMR style
    target_lufs: float = -18.0
    guard: str = "signal"                  # off | signal | full (full adds the speech-recogniser round trip)
    guard_attempts: int = 3
    seed: int | None = None


@dataclass
class _Shift:                               # what KokoroTTS.synthesize accepts as `prosody`
    rate: float = 1.0
    pitch_semitones: float = 0.0
    pause_ms: int = 0
    energy: float = 0.35

    @property
    def neutral(self) -> bool:
        return abs(self.rate - 1.0) < 0.01 and abs(self.pitch_semitones) < 0.05 and abs(self.pause_ms) < 5


@dataclass
class Rendered:
    samples: object
    rate: int
    engine: str
    report: object = None
    extra: dict = field(default_factory=dict)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class ExpressiveTTS:
    accepts_tags = True

    def __init__(self, base, *, neural=None, bank=None, guard=None, library=None, designer=None,
                 config: ExpressiveConfig | None = None, stats=None) -> None:
        from .guard import GuardStats
        self.base, self.neural, self.bank, self.guard = base, neural, bank, guard
        self.library, self.designer = library, designer
        self.config = config or ExpressiveConfig()
        self.stats = stats or GuardStats()
        self.sample_rate = getattr(base, "sample_rate", 24000)
        self.policy = S.SoundPolicy()
        self.rng = random.Random(self.config.seed)
        self.choice = S.StyleChoice(self.config.default_style, self.config.intensity, "default")
        self._carry: tuple | None = None
        self._pending_sound: str | None = None
        self._sentences = 0
        self._lock = threading.Lock()
        self.last: list[dict] = []           # what the last synthesize() did, per segment (for tests and the A/B page)

    # -- tone for the next reply --------------------------------------------------------------------------------
    def set_mood(self, mood: dict | None = None, user_text: str = "", hour: int | None = None) -> S.StyleChoice:
        """Called once per reply (CallSession._tune_voice). Resets the carried style and picks this reply's tone."""
        with self._lock:
            self._carry = None
            self._sentences = 0
            if self.config.asmr:
                self.choice = S.StyleChoice("asmr", 0.8, "ASMR mode")
            elif self.config.follow_mood:
                self.choice = S.style_for_context(user_text, mood, self.config.default_style, hour)
            else:
                self.choice = S.StyleChoice(self.config.default_style, self.config.intensity, "settings")
            self._pending_sound = S.suggest_sound(mood, self.rng) if self.config.sounds else None
            return self.choice

    # -- TextToSpeech interface ---------------------------------------------------------------------------------
    def warm_up(self) -> None:
        """Base voice, then one pass of each DSP path (the first numpy FFT / WORLD call pays a one-off ~0.2 s)."""
        if hasattr(self.base, "warm_up"):
            self.base.warm_up()
        carry, choice = self._carry, self.choice
        for text in ("<whisper> Hm.", "<excited> Okay?"):
            for _ in self.render(text):
                pass
        self._carry, self.choice, self.last, self._sentences = carry, choice, [], 0

    def synthesize(self, text: str, prosody=None):
        """One sentence (may carry tags) -> PCM16 chunks, one per segment, each loudness-normalised."""
        from .voicedsp import as_pcm
        for rendered in self.render(text, prosody):
            if rendered.samples is not None and len(rendered.samples):
                yield as_pcm(rendered.samples), rendered.rate

    def render(self, text: str, prosody=None):
        with self._lock:
            style, intensity = self.choice.style, self.choice.intensity
            if self.config.fillers and self._sentences == 0:
                text = S.add_fillers(text, self.rng, style=style)
            segments, self._carry = S.parse_carry(text, style, intensity, carry=self._carry)
            if self._pending_sound and self._sentences == 0:
                segments = [S.Segment("sound", self._pending_sound, style, intensity)] + segments
                self._pending_sound = None
            self._sentences += 1
        segments = S.restrict(segments, self.config.allowed_styles,
                              self.config.allowed_sounds if self.config.sounds else frozenset(),
                              fallback=self.config.default_style)
        segments = self.policy.filter(segments)
        self.last = []
        for seg in segments:
            if seg.kind == "speech":
                if self.config.asmr and seg.style not in ("asmr", "whisper"):
                    seg = replace(seg, style="asmr", intensity=max(seg.intensity, 0.7))
                if seg.style == "asmr" and self.bank is not None and self._sentences % 2 == 1:
                    breath = self._sound("breath-in", seg)
                    if breath is not None:
                        yield breath
                yield self._speech(seg, prosody)
                gap = self._gap(seg, prosody)
                if gap is not None:
                    yield gap
            elif seg.kind == "sound":
                out = self._sound(seg.text, seg)
                if out is not None:
                    yield out
            elif seg.kind == "pause":
                yield self._silence(seg.pause_ms / 1000.0)

    # -- speech --------------------------------------------------------------------------------------------------
    def _speech(self, seg: S.Segment, prosody=None) -> Rendered:
        if seg.voice:
            return self._character(seg)
        if seg.style == "sing":
            return self._sung(seg)
        rendered = None
        if self.config.mode == QUALITY and self.neural is not None:
            rendered = self._neural(seg)
        if rendered is None:
            rendered = self._base(seg, prosody)
        rendered.samples = self._finish(rendered.samples, rendered.rate, seg)
        self.last.append({"kind": "speech", "text": seg.text, "style": seg.style, "engine": rendered.engine,
                          "problems": getattr(rendered.report, "problems", [])})
        return rendered

    def _base_float(self, text: str, shift: _Shift | None):
        """The base voice's speech for `text` without its trailing sentence gap (_gap adds the pause)."""
        import numpy as np
        from .voicedsp import as_float
        if hasattr(self.base, "synthesize_float"):
            return self.base.synthesize_float(text, rate=shift.rate if shift else 1.0,
                                              pitch_semitones=shift.pitch_semitones if shift else 0.0)
        rate, parts = self.sample_rate, []
        pieces = self.base.synthesize(text, prosody=shift) if shift is not None else self.base.synthesize(text)
        for pcm, rate in pieces:
            parts.append(as_float(pcm))
        return (np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)), rate

    def _base(self, seg: S.Segment, prosody=None) -> Rendered:
        from . import voicedsp
        spec = S.STYLES.get(seg.style, S.STYLES["neutral"])
        t = seg.intensity
        rate = lerp(1.0, spec.rate, t) * (prosody.rate if prosody is not None else 1.0)
        world = voicedsp.have_world()
        pitch = lerp(0.0, spec.pitch_st, t) + (prosody.pitch_semitones if prosody is not None else 0.0)
        # With WORLD the pitch is moved there (formants stay put); without it the base voice's resample does it.
        shift = _Shift(rate=rate, pitch_semitones=0.0 if world else pitch)
        samples, sr = self._base_float(seg.text, None if shift.neutral else shift)
        report = None
        if self.guard is not None and self.config.guard != "off" and samples.size:
            report = self.guard.check(samples, sr, seg.text)
            self.stats.record(seg.text, 0, report, "kokoro")
            with self.stats._lock:
                self.stats.chunks += 1
        samples = self._shape(samples, sr, seg, spec, pitch if world else 0.0)
        return Rendered(samples, sr, "kokoro+dsp", report)

    def _shape(self, x, sr: int, seg: S.Segment, spec: S.StyleSpec, pitch: float):
        """Style DSP in her own voice: pitch level and movement, sing-song swing, question rise, emphasis,
        breathiness (WORLD), then whisper (spectral)."""
        from . import voicedsp
        t = seg.intensity
        range_scale = lerp(1.0, spec.pitch_range, t)
        breath = spec.breath * t
        rise = 3.5 * (0.6 + 0.4 * t) if seg.question and not spec.whisper else 0.0
        emphasis = voicedsp.emphasis_spans(seg.text, seg.emphasis) if seg.emphasis else []
        reshape = (abs(pitch) > 0.05 or abs(range_scale - 1.0) > 0.02 or spec.melody or rise or emphasis or breath > 0.02)
        if reshape and not spec.whisper and voicedsp.have_world() and x.size > sr // 20:
            f0, sp, ap = voicedsp.world_analyse(x, sr)
            f0 = voicedsp.reshape_f0(f0, shift_st=pitch, range_scale=range_scale, melody_st=spec.melody * t,
                                     rise_st=rise, emphasis=emphasis)
            if breath > 0.02:                           # aspiration noise lives mostly above ~2 kHz
                import numpy as np
                weight = np.clip(np.linspace(0.0, 2.5, ap.shape[1]), 0.15, 1.0)
                ap = ap + (1.0 - ap) * breath * weight
            y = voicedsp.world_synth(f0, sp, ap, sr)
            x = y[:x.size] if y.size >= x.size else voicedsp.crossfade_concat([y], sr)
        if spec.whisper:
            mix = 0.55 + 0.45 * t                       # low intensity keeps a trace of voice ("half-whisper")
            x = voicedsp.whisper(x, sr, seed=self.rng.randrange(1 << 16)) * mix + x * (1.0 - mix) * 0.35
        return x

    def _neural(self, seg: S.Segment) -> Rendered | None:
        """Quality path: neural engine with the style instruction, guarded; None when every attempt failed."""
        from .guard import GuardedTTS
        spec = S.STYLES.get(seg.style, S.STYLES["neutral"])
        instruct = spec.instruct if seg.style != "neutral" else None
        try:
            if self.guard is not None and self.config.guard != "off":
                runner = GuardedTTS(self.neural, self.guard, self.config.guard_attempts, self.stats,
                                    reference=getattr(self.neural, "reference_embedding", None),
                                    name=getattr(self.neural, "name", "neural"))
                samples, sr, report = runner.render(seg.text, instruct=instruct)
                if not report.ok:
                    return None
            else:
                samples, sr = self.neural.synthesize_float(seg.text, seed=0, instruct=instruct)
                report = None
        except Exception:
            return None
        from . import voicedsp
        if spec.whisper and not getattr(self.neural, "follows_whisper", False):
            samples = voicedsp.whisper(samples, sr, seed=1)
        return Rendered(samples, sr, getattr(self.neural, "name", "neural"), report)

    def _finish(self, x, sr: int, seg: S.Segment):
        from . import voicedsp
        spec = S.STYLES.get(seg.style, S.STYLES["neutral"])
        if seg.style == "asmr" or self.config.asmr:
            x = voicedsp.shelf(x, sr, 4.0, 180.0, low=True)          # close-mic proximity warmth
            x = voicedsp.compress(x, sr, -30.0, 2.5)
        x = voicedsp.fade(x, sr, 3.0, 12.0)
        return voicedsp.normalize(x, sr, self.config.target_lufs + spec.gain_db * seg.intensity)

    def _gap(self, seg: S.Segment, prosody=None) -> Rendered | None:
        spec = S.STYLES.get(seg.style, S.STYLES["neutral"])
        ms = int(getattr(self.base, "gap_ms", 0) or 0) + int(spec.gap_ms * seg.intensity)
        if prosody is not None:
            ms += int(getattr(prosody, "pause_ms", 0))
        return self._silence(ms / 1000.0) if ms > 0 else None

    def _silence(self, seconds: float) -> Rendered:
        from . import voicedsp
        return Rendered(voicedsp.room_tone(seconds, self.sample_rate, -66.0, self.rng.randrange(1 << 16)),
                        self.sample_rate, "room-tone")

    # -- sounds --------------------------------------------------------------------------------------------------
    def _sound(self, name: str, seg: S.Segment) -> Rendered | None:
        from . import voicedsp
        from .nonverbal import read_wav, route
        how = route(name, getattr(self.neural, "name", "") if self.config.mode == QUALITY else "", self.bank, self.rng)
        self.last.append({"kind": "sound", "name": name, "route": how.how})
        if how.how == "clip":
            clip, sr = read_wav(how.value)
            if sr != self.sample_rate:
                from .engines import resample
                clip, sr = resample(clip, sr, self.sample_rate), self.sample_rate
            level = self.config.target_lufs + S.SOUNDS[name].level_db
            clip = voicedsp.match_level(clip, sr, level)
            pad = voicedsp.room_tone(0.04, sr, -66.0, self.rng.randrange(1 << 16))
            return Rendered(voicedsp.crossfade_concat([pad, clip, pad], sr, 6.0), sr, "bank")
        if how.how == "text":
            return self._speech(replace(seg, kind="speech", text=how.value, emphasis=(), question=False))
        if how.how == "native" and self.neural is not None:
            samples, sr = self.neural.synthesize_float(how.value, seed=0)
            return Rendered(voicedsp.normalize(samples, sr, self.config.target_lufs + S.SOUNDS[name].level_db), sr,
                            "native")
        return None

    # -- characters, role-play, songs ----------------------------------------------------------------------------
    def _character(self, seg: S.Segment) -> Rendered:
        character = self.library.get(seg.voice) if self.library is not None else None
        if character is None:
            return self._base(replace(seg, voice=""))
        spec = S.STYLES.get(seg.style, S.STYLES["neutral"])
        if character.kind == "designed" and self.designer is not None:
            instruct = character.description + (" " + spec.instruct if seg.style != "neutral" else "")
            try:
                samples, sr = self.designer.synthesize_float(seg.text, seed=0, instruct=instruct)
                samples = self._finish(samples, sr, seg)
                self.last.append({"kind": "speech", "text": seg.text, "voice": character.name, "engine": "voice-design"})
                return Rendered(samples, sr, "voice-design")
            except Exception:
                pass
        recipe = character.voice or "af_sarah:1.0"
        samples, sr = self.base.synthesize_float(seg.text, voice=recipe, rate=character.speed) \
            if hasattr(self.base, "synthesize_float") else self._base_float(seg.text, None)
        samples = self._shape(samples, sr, seg, spec, character.pitch_semitones + spec.pitch_st * seg.intensity)
        samples = self._finish(samples, sr, seg)
        self.last.append({"kind": "speech", "text": seg.text, "voice": character.name, "engine": "kokoro+dsp"})
        return Rendered(samples, sr, "kokoro+dsp")

    def _sung(self, seg: S.Segment) -> Rendered:
        """<sing>: her own words to a tune composed on the spot (a lullaby when the mood is soft). Without pyworld the
        line is spoken in the sing-song style instead."""
        from . import voicedsp
        from .singing import compose
        if not voicedsp.have_world():
            return self._speech(replace(seg, style="sing-song"))
        lullaby = self.choice.style in ("soft", "sleepy", "caring", "tender", "asmr", "calm")
        song = compose(seg.text[:40], [seg.text], mood="lullaby" if lullaby else "happy", seed=sum(map(ord, seg.text)))
        samples, sr = self.sing(song)
        self.last.append({"kind": "speech", "text": seg.text, "style": "sing", "engine": "kokoro+world-singing"})
        return Rendered(voicedsp.normalize(samples, sr, self.config.target_lufs - 1.0), sr, "singing")

    def speak_script(self, script: str, narrator_style: str = "calm"):
        """Role-play: narrator + characters, one line at a time. Lines by Star use her own voice and current tone;
        unknown speaker names are read by the narrator ("Bob says: ...") rather than guessed."""
        from .library import NARRATOR, parse_script
        from .voicedsp import as_pcm
        known = {c.name for c in self.library.list()} if self.library is not None else set()
        for line in parse_script(script, known):
            if line.speaker == NARRATOR:
                segs = S.parse(line.text, narrator_style, 0.5)
            elif line.speaker.lower() == "star":
                segs = S.parse(line.text, self.choice.style, self.choice.intensity)
            elif line.speaker in known or line.speaker.lower() in {k.lower() for k in known}:
                segs = S.parse(line.text, "neutral", 0.6, voice=line.speaker)
            else:
                segs = S.parse(f"{line.speaker} says: {line.text}", narrator_style, 0.5)
            for seg in segs:
                if seg.kind == "speech":
                    out = self._speech(seg)
                elif seg.kind == "sound":
                    out = self._sound(seg.text, seg)
                else:
                    out = self._silence(seg.pause_ms / 1000.0)
                if out is not None and len(out.samples):
                    yield as_pcm(out.samples), out.rate
            yield as_pcm(self._silence(0.35).samples), self.sample_rate

    def sing(self, song):
        """A song (singing.Song) in her own voice: (float samples, rate)."""
        from .singing import sing

        def word(w: str):
            return self._base_float(w + ".", None)
        return sing(song, word, self.sample_rate)


def build(base, settings, *, asr=None, report=print):
    """Wrap the call's TTS for VoiceSettings with expressive=True: bank, guard, library and (when the VRAM budget for
    the current profile allows and the setting asks for it) the neural engine. Never raises for a missing optional
    part: it is left out and the reason reported."""
    from pathlib import Path
    from .guard import ArtefactGuard, GuardStats
    from .library import CharacterLibrary
    from .nonverbal import NonverbalBank
    root = Path(settings.expressive_home) if settings.expressive_home else _default_home()
    allowed = frozenset(x.strip() for x in settings.allowed_styles.split(",") if x.strip()) or None
    config = ExpressiveConfig(mode=QUALITY if settings.expressive_engine != "kokoro" else LIVE,
                              default_style=settings.default_style, intensity=float(settings.style_intensity),
                              allowed_styles=allowed, sounds=bool(settings.voice_sounds), fillers=bool(settings.fillers),
                              asmr=bool(settings.asmr), guard=settings.artefact_guard)
    guard = None
    if config.guard != "off":
        guard = ArtefactGuard(asr=asr if config.guard == "full" else None)
    neural = None
    if settings.expressive_engine not in ("kokoro", ""):
        from ..senses.fastpath import expressive_allowed
        ok, why = expressive_allowed(settings.fast_profile, settings.expressive_engine)
        if ok:
            try:
                from ..voice_neural import make_neural
                neural = make_neural(settings.expressive_engine, root, base)
            except Exception as exc:              # missing package or weights: live path only
                report(f"expressive engine {settings.expressive_engine} not loaded: {exc}")
                config.mode = LIVE
        else:
            report(f"expressive engine off: {why}")
            config.mode = LIVE
    bank = NonverbalBank(root / "sounds") if (root / "sounds").is_dir() else None
    return ExpressiveTTS(base, neural=neural, bank=bank, guard=guard, library=CharacterLibrary(root / "characters.json"),
                         config=config, stats=GuardStats(root / "guard-log.jsonl"))


def _default_home():
    from pathlib import Path
    from .engines import models_dir
    return Path(models_dir()) / "expressive"
