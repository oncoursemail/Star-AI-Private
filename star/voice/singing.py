"""Star sings: short original melodies, lullabies and public-domain songs, in her own voice.

How it sounds like her: each word is spoken by her own voice engine (Kokoro "star-mum" or whichever voice is
active), analysed with the WORLD vocoder (pyworld, MIT), its vowels held for the note length and its pitch replaced
by the melody (with a little vibrato and a short glide between notes), then resynthesised and joined. Consonants keep
their spoken timing. It is a "speech-to-singing" voice, not a trained singing model: clearly melodic and clearly her,
but plainer than a studio singer. Licences: pyworld MIT, Kokoro Apache-2.0, melodies here are her own or public domain.

Copyright rule (can_sing): she sings only (a) songs she writes herself (compose) and (b) the public-domain songs listed
in PUBLIC_DOMAIN. Any other requested song gets a kind refusal plus an offer to write an original about the same
thing. She never reproduces copyrighted lyrics or melodies.

Notation: "C4:1 D4:0.5 R:1" = note name + octave (or R for a rest) : length in beats.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

NOTE_INDEX = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
              "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}


def midi(note: str) -> int | None:
    """'A4' -> 69, 'R' -> None."""
    m = re.fullmatch(r"([A-Ga-g][#bB]?)(-?\d)", note.strip())
    if not m:
        if note.strip().upper() == "R":
            return None
        raise ValueError(f"bad note {note!r}")
    return NOTE_INDEX[m.group(1).upper()] + 12 * (int(m.group(2)) + 1)


def hz(midi_note: float) -> float:
    return 440.0 * 2 ** ((midi_note - 69) / 12.0)


def parse_melody(text: str) -> list[tuple[int | None, float]]:
    out = []
    for token in text.split():
        name, _, beats = token.partition(":")
        out.append((midi(name), float(beats or 1)))
    return out


_VOWELS = re.compile(r"[aeiouy]+", re.I)


def syllable_count(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = len(_VOWELS.findall(w))
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and groups > 1:
        groups -= 1
    return max(1, groups)


@dataclass
class Song:
    title: str
    lyrics: list            # lines of words
    melody: list            # per line: list of (midi or None, beats); one note per syllable, rests allowed
    bpm: int = 84
    origin: str = "original"    # "original" (hers) or "public domain: <source>"

    def notes_for_line(self, i: int) -> list:
        return self.melody[i]


# Public domain only. "Twinkle, Twinkle, Little Star": lyrics Jane Taylor, "The Star" (1806); melody the French tune
# "Ah! vous dirai-je, maman" (18th century). Both long out of copyright.
_TWINKLE = "C4:1 C4:1 G4:1 G4:1 A4:1 A4:1 G4:2|F4:1 F4:1 E4:1 E4:1 D4:1 D4:1 C4:2|" \
           "G4:1 G4:1 F4:1 F4:1 E4:1 E4:1 D4:2|G4:1 G4:1 F4:1 F4:1 E4:1 E4:1 D4:2|" \
           "C4:1 C4:1 G4:1 G4:1 A4:1 A4:1 G4:2|F4:1 F4:1 E4:1 E4:1 D4:1 D4:1 C4:2"
PUBLIC_DOMAIN = {
    "twinkle twinkle little star": Song(
        "Twinkle, Twinkle, Little Star",
        ["Twinkle twinkle little star", "How I wonder what you are", "Up above the world so high",
         "Like a diamond in the sky", "Twinkle twinkle little star", "How I wonder what you are"],
        [parse_melody(part) for part in _TWINKLE.split("|")], 92,
        "public domain: Jane Taylor, The Star (1806); tune Ah! vous dirai-je, maman"),
}


def can_sing(request: str) -> tuple[bool, str]:
    """(allowed, what to do). Allowed: an original song (anything asking her to make one up) or a listed public-domain
    song. Otherwise she declines the cover and offers an original instead."""
    low = re.sub(r"[^a-z ]", "", (request or "").lower())
    for key, song in PUBLIC_DOMAIN.items():
        if key in low:
            return True, f"public domain: {song.title}"
    if re.search(r"\b(make up|write|compose|your own|original|improvise|a song about|a lullaby|lullaby|hum)\b", low):
        return True, "original"
    return False, ("I can't sing other people's songs, but I'd love to write you a little one of my own about it. "
                   "Want that?")


SCALES = {"major": (0, 2, 4, 5, 7, 9, 11), "pentatonic": (0, 2, 4, 7, 9), "minor": (0, 2, 3, 5, 7, 8, 10)}


def compose(title: str, lines: list[str], *, mood: str = "happy", seed: int | None = None, tonic: int = 60,
            bpm: int | None = None) -> Song:
    """An original tune for her own lyrics: one note per syllable, mostly stepwise, a held note at each line end,
    the last line resolving home. Lullabies are slower and calmer, sad songs minor."""
    rng = random.Random(seed if seed is not None else title)
    scale = SCALES["minor" if mood == "sad" else ("pentatonic" if mood in ("happy", "playful") else "major")]
    lullaby = mood in ("lullaby", "sleepy", "calm")
    pool = [tonic + s for s in scale] + [tonic + 12 + s for s in scale[:3]]
    melody = []
    position = 0
    for li, line in enumerate(lines):
        count = sum(syllable_count(w) for w in line.split())
        notes = []
        for si in range(count):
            last_of_line = si == count - 1
            if last_of_line:
                target = 0 if li == len(lines) - 1 else rng.choice((2, 4) if li % 2 == 0 else (1, 3))
                position = min(target, len(pool) - 1)
            else:
                step = rng.choice((-1, 0, 1, 1, 2, -2) if not lullaby else (-1, 0, 1, -1, 1))
                position = max(0, min(len(pool) - 1, position + step))
            beats = (2.0 if lullaby else 1.5) if last_of_line else (1.0 if lullaby or rng.random() < 0.7 else 0.5)
            notes.append((pool[position], beats))
        melody.append(notes)
    return Song(title, [l.split() for l in lines], melody, bpm or (66 if lullaby else 96), "original")


def sing(song: Song, speak_word, sr_hint: int = 24000, transpose_to_hz: float | None = None, vibrato_st: float = 0.3):
    """Render `song`. `speak_word(word)` returns (float samples, rate) of her voice saying one word. Returns
    (float samples, rate). The song is moved into her comfortable range around `transpose_to_hz` (default: the
    median pitch of her first sung word)."""
    import numpy as np
    from . import voicedsp
    beat = 60.0 / song.bpm
    frame_ms = 5.0
    pieces, rate = [], sr_hint
    shift = None
    for li, words in enumerate(song.lyrics):
        notes = list(song.melody[li])
        for word in words:
            n_syl = syllable_count(word)
            if n_syl == 0:
                continue
            while notes and notes[0][0] is None:            # rests before the word
                pieces.append(np.zeros(int(notes.pop(0)[1] * beat * rate), dtype=np.float32))
            mine, notes = notes[:n_syl], notes[n_syl:]
            if not mine:
                break
            samples, rate = speak_word(word)
            samples = voicedsp.trim(samples, rate, -40.0, 10.0)
            f0, sp, ap = voicedsp.world_analyse(samples, rate, frame_ms)
            voiced = f0 > 0
            if shift is None:
                centre = float(np.mean([m for m, _ in mine if m is not None]))
                target = transpose_to_hz or (float(np.median(f0[voiced])) if np.any(voiced) else 200.0)
                shift = 12 * np.log2(target / hz(centre))
            pieces.append(_sing_word(f0, sp, ap, rate, mine, beat, shift, vibrato_st, frame_ms))
        for m, beats in notes:                                 # trailing rests at the line end
            if m is None:
                pieces.append(np.zeros(int(beats * beat * rate), dtype=np.float32))
        pieces.append(np.zeros(int(0.25 * beat * rate), dtype=np.float32))
    out = voicedsp.crossfade_concat(pieces, rate, 12.0)
    return voicedsp.normalize(out, rate), rate


def _sing_word(f0, sp, ap, rate, notes, beat, shift, vibrato_st, frame_ms):
    """Split the word's voiced frames evenly across its notes; hold each vowel for its note; new pitch contour."""
    import numpy as np
    from . import voicedsp
    voiced_idx = np.where(f0 > 0)[0]
    n = f0.size
    if voiced_idx.size == 0:
        return voicedsp.world_synth(f0, sp, ap, rate, frame_ms)
    bounds = np.linspace(voiced_idx[0], voiced_idx[-1] + 1, len(notes) + 1).astype(int)
    frames, pitches = [], []
    frames.extend(range(0, bounds[0]))                         # onset consonant as spoken
    pitches.extend([0.0] * bounds[0])
    per_frame = frame_ms / 1000.0
    for k, (note, beats) in enumerate(notes):
        a, b = bounds[k], max(bounds[k] + 1, bounds[k + 1])
        want = max(b - a, int(beats * beat / per_frame))
        idx = np.clip(a + (np.arange(want) * (b - a) / want).astype(int), a, b - 1)
        frames.extend(idx.tolist())
        target = hz(note + shift) if note is not None else 0.0
        t = np.arange(want) * per_frame
        vib = np.where(t > 0.25, vibrato_st * np.sin(2 * np.pi * 5.5 * t), 0.0)
        pitches.extend((target * 2 ** (vib / 12.0)).tolist())
    tail = list(range(bounds[-1], n))                          # final consonant as spoken
    frames.extend(tail)
    pitches.extend([0.0] * len(tail))
    frames = np.asarray(frames)
    new_f0 = np.asarray(pitches)
    new_f0 = np.where(f0[frames] > 0, new_f0, 0.0)             # keep unvoiced frames unvoiced
    glide = int(0.03 / per_frame)                              # 30 ms glide between notes
    voiced = new_f0 > 0
    smooth = new_f0.copy()
    for i in range(1, new_f0.size):
        if voiced[i] and voiced[i - 1] and abs(new_f0[i] - smooth[i - 1]) > 1e-3:
            smooth[i] = smooth[i - 1] + (new_f0[i] - smooth[i - 1]) / max(1, glide)
    return voicedsp.world_synth(smooth, sp[frames], ap[frames], rate, frame_ms)
