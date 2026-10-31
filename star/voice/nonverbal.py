"""Non-verbal sounds in Star's own voice: laughs, sighs, gasps, hums, coughs, sneezes, yawns, sniffs, breaths.

Routing for one <sound> tag (route()):
  1. "native"  the speech engine makes it itself (Chatterbox-Turbo's [laugh] [sigh] [cough] ...): best blend, but only
               when that engine is the one speaking the sentence.
  2. "clip"    a clip from the bank: pre-rendered once, in her voice, trimmed, loudness-matched at splice time and
               padded with room tone (star.voice.voicedsp.match_level / room_tone), so it sits in the speech.
  3. "text"    no clip and no native tag: say it with words when the sound has a natural spelling ("Mm-hm.", "Um,",
               "Hmm."); otherwise ("sneeze" with no clip) the sound is skipped, because a robot reading "achoo" is
               worse than nothing.

The bank is a folder: <bank>/<sound>/<n>.wav (16-bit mono) plus bank.json describing how each clip was made. Clips are
made by build_bank(): Chatterbox-Turbo native tags in her cloned voice (reference clip rendered by her own Kokoro
voice, so no real person is copied), and DSP-made sounds for the rest (breaths from her whispered voice, hums and
yawns from her voice with a new pitch contour). No outside recordings are needed.
"""
from __future__ import annotations

import json
import random
import wave
from dataclasses import dataclass
from pathlib import Path

from .styles import SOUNDS

NATIVE_ENGINES = frozenset({"chatterbox-turbo"})


@dataclass(frozen=True)
class Route:
    how: str                 # "native" | "clip" | "text" | "skip"
    value: str = ""          # native tag, clip path or spoken text


def route(sound: str, engine: str = "", bank: "NonverbalBank | None" = None, rng: random.Random | None = None) -> Route:
    spec = SOUNDS[sound]
    if engine in NATIVE_ENGINES and spec.native:
        return Route("native", spec.native)
    if bank is not None:
        clip = bank.pick(sound, rng)
        if clip:
            return Route("clip", str(clip))
    if spec.text:
        return Route("text", spec.text)
    return Route("skip")


class NonverbalBank:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self._cache: dict[str, list[Path]] = {}
        self._last: dict[str, Path] = {}

    def clips(self, sound: str) -> list[Path]:
        if sound not in self._cache:
            d = self.folder / sound
            self._cache[sound] = sorted(d.glob("*.wav")) if d.is_dir() else []
        return self._cache[sound]

    def pick(self, sound: str, rng: random.Random | None = None) -> Path | None:
        options = self.clips(sound)
        if not options:
            return None
        rng = rng or random.Random()
        choices = [p for p in options if p != self._last.get(sound)] or options     # no identical twice in a row
        choice = rng.choice(choices)
        self._last[sound] = choice
        return choice

    def available(self) -> list[str]:
        return [name for name in SOUNDS if self.clips(name)]


def read_wav(path: str | Path):
    import numpy as np
    with wave.open(str(path), "rb") as f:
        rate, frames, width, channels = f.getframerate(), f.readframes(f.getnframes()), f.getsampwidth(), f.getnchannels()
    if width != 2:
        raise ValueError(f"{path}: only 16-bit WAV is supported")
    x = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, rate


def write_wav(path: str | Path, samples, rate: int) -> None:
    from .voicedsp import as_pcm
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(int(rate))
        f.writeframes(as_pcm(samples))


# -- making clips -------------------------------------------------------------------------------------------------
# Chatterbox-Turbo prompts per sound: the native tag, sometimes with a breath of context so the model commits to it.
NATIVE_PROMPTS = {
    "laugh": ("[laugh]", "Oh! [laugh]"), "giggle": ("[chuckle]", "Hehe [chuckle]"), "chuckle": ("[chuckle]",),
    "sigh": ("[sigh]", "Mm. [sigh]"), "gasp": ("[gasp]", "Oh! [gasp]"), "cough": ("[cough]", "[cough] [cough]"),
    "sniff": ("[sniff]",), "clear-throat": ("[clear throat]",), "sneeze": ("Ah... ah... achoo!", "Ahh... choo!"),
}


def breath_out(voice_whisper, sr: int, seconds: float = 0.7):
    """An exhale from her own whispered voice: keep the noise colour, give it a breath's soft swell and fall."""
    import numpy as np
    from . import voicedsp
    x = voicedsp.trim(voice_whisper, sr)
    n = int(seconds * sr)
    if x.size < n:
        x = np.tile(x, int(np.ceil(n / max(1, x.size))))
    x = x[:n]
    t = np.linspace(0, 1, n, dtype=np.float32)
    envelope = np.minimum(1.0, t / 0.12) * np.exp(-3.2 * np.maximum(0.0, t - 0.12))
    return voicedsp.shelf(x * envelope, sr, -8.0, 400.0, low=True)


def breath_in(voice_whisper, sr: int, seconds: float = 0.5):
    """An inhale: brighter and rising, ending abruptly (the way air stops when the lungs are full)."""
    from . import voicedsp
    x = breath_out(voice_whisper, sr, seconds)[::-1].copy()
    x = voicedsp.shelf(x, sr, 5.0, 2500.0, low=False)
    return voicedsp.fade(x, sr, 30.0, 25.0)


def contour_voice(samples, sr: int, contour_st: list, stretch: float = 1.0, breath: float = 0.0):
    """Her voice saying a vowel ("Mmm", "Haaa") re-pitched along `contour_st` (semitones relative to her own pitch,
    spread evenly over the clip) and stretched in time: hums and yawns. Needs pyworld."""
    import numpy as np
    from . import voicedsp
    f0, sp, ap = voicedsp.world_analyse(samples, sr)
    if stretch != 1.0:
        idx = np.clip((np.arange(int(f0.size * stretch)) / stretch).astype(int), 0, f0.size - 1)
        f0, sp, ap = f0[idx], sp[idx], ap[idx]
    voiced = f0 > 0
    base = float(np.median(f0[voiced])) if np.any(voiced) else 200.0
    curve = np.interp(np.linspace(0, len(contour_st) - 1, f0.size), np.arange(len(contour_st)), contour_st)
    new_f0 = np.where(voiced, base * 2.0 ** (curve / 12.0), 0.0)
    if breath:
        ap = ap + (1.0 - ap) * breath
    return voicedsp.world_synth(new_f0, sp, ap, sr)


def build_bank(folder: str | Path, *, kokoro=None, chatterbox=None, variants: int = 3, report=print) -> dict:
    """Render the bank. `kokoro` has synthesize_float(text) -> (samples, sr) in her locked voice; `chatterbox` has
    synthesize_float(text, seed=) in her cloned voice (optional). Returns the manifest written to bank.json."""
    from . import voicedsp
    folder = Path(folder)
    manifest = {"version": 1, "clips": {}}

    def keep(name: str, i: int, samples, sr: int, how: str) -> None:
        samples = voicedsp.fade(voicedsp.trim(samples, sr, -40.0, 40.0), sr, 8.0, 40.0)
        if samples.size < int(0.12 * sr):
            report(f"  {name}: too short, dropped")
            return
        samples = voicedsp.normalize(samples, sr, voicedsp.TARGET_LUFS)
        path = folder / name / f"{i}.wav"
        write_wav(path, samples, sr)
        manifest["clips"].setdefault(name, []).append({"file": f"{name}/{i}.wav", "how": how,
                                                       "seconds": round(samples.size / sr, 2)})
        report(f"  {name} {i}: {how}, {samples.size / sr:.2f} s")

    if chatterbox is not None:
        for name, prompts in NATIVE_PROMPTS.items():
            for i in range(variants):
                prompt = prompts[i % len(prompts)]
                samples, sr = chatterbox.synthesize_float(prompt, seed=i)
                keep(name, i, samples, sr, f"chatterbox-turbo '{prompt}' seed {i}")
    if kokoro is not None:
        hah, sr = kokoro.synthesize_float("Haaah.")
        for i in range(variants):
            keep("breath-out", i, breath_out(voicedsp.whisper(hah, sr, seed=i + 2), sr, 0.6 + 0.15 * i), sr,
                 "her whispered voice shaped as an exhale")
            keep("breath-in", i, breath_in(voicedsp.whisper(hah, sr, seed=i + 7), sr, 0.4 + 0.1 * i), sr,
                 "her whispered voice shaped as an inhale")
        if voicedsp.have_world():
            mm, sr = kokoro.synthesize_float("Mmmm.")
            for i, tune in enumerate(([0, 2, 4, 2, 0], [0, 4, 7, 4], [4, 2, 0, -1, 0])[:variants]):
                keep("hum", i, contour_voice(mm, sr, tune, stretch=2.2), sr, f"her 'mmm' sung along {tune}")
            yawn, sr = kokoro.synthesize_float("Haaawm.")
            for i in range(variants):
                keep("yawn", i, contour_voice(yawn, sr, [0, 3 + i, 4 + i, -2, -6], stretch=2.6 + 0.3 * i,
                                              breath=0.45), sr, "her 'haaawm' stretched with a yawn's pitch arc")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bank.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
