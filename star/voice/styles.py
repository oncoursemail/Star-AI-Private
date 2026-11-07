"""Expressive speech: the style and sound tags Star can put in her own words, and how her mood picks a tone.

Pure Python, no packages: the parser, the mood mapping and the policies are unit-tested in the plain test environment.

Tags (the persona prompt TAGS_PROMPT teaches them to her; unknown tags are left alone, so "<b>" or "[1]" are not eaten):
  styles     <whisper> <soft> <warm> <caring> <playful> <sleepy> <excited> <sad> <sarcastic> <sing-song> <calm>
             <serious> <happy> <nervous> <tender> <asmr> <neutral>, and <sing> (spoken while singing is paused)
             A style tag goes at the start of a sentence and lasts until its closing tag (<whisper>...</whisper>)
             or the end of the reply. Intensity: <excited:0.8> (0..1, default 0.6).
  sounds     <laugh> <giggle> <chuckle> <sigh> <gasp> <hum> <cough> <sneeze> <yawn> <sniff> <clear-throat>
             <breath-in> <breath-out> <mm-hm> <um> <uh>
  pauses     <pause> (300 ms) or <pause:600>
  emphasis   <emph>word</emph>
Square brackets work too ([laugh], [whisper]), because some models write them that way.

Continuity rule (natural prosody): a style never changes in the middle of a sentence. A style tag that appears
mid-sentence takes effect from the next sentence; a closing tag mid-sentence ends the style at the end of that
sentence. Sounds and pauses may sit anywhere.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field, replace

DEFAULT_INTENSITY = 0.6


@dataclass(frozen=True)
class StyleSpec:
    """How a style sounds. `instruct` is the natural-language instruction for engines that follow one (Star's designed
    voice, qwen3-design). The DSP numbers are no longer applied (v1 DSP styles were rated 1-2 by the owner,
    2026-10-27); `exaggeration` was Chatterbox's emotion knob."""
    name: str
    summary: str
    rate: float = 1.0               # speed multiplier
    pitch_st: float = 0.0           # mean pitch shift in semitones
    pitch_range: float = 1.0        # pitch movement: 1.0 unchanged, >1 livelier, <1 flatter
    breath: float = 0.0             # 0..1 breathiness (aperiodic share)
    whisper: bool = False           # fully unvoiced (no pitch at all)
    gain_db: float = 0.0            # loudness relative to the normal voice
    gap_ms: int = 0                 # extra pause after each sentence
    melody: float = 0.0             # sing-song: a slow pitch swing in semitones
    instruct: str = ""
    exaggeration: float = 0.5


STYLES: dict[str, StyleSpec] = {s.name: s for s in (
    StyleSpec("neutral", "her normal voice"),
    StyleSpec("warm", "warm and friendly", rate=0.97, pitch_st=-0.3, pitch_range=1.1, breath=0.08,
              instruct="Speak warmly and kindly, with a gentle smile in the voice.", exaggeration=0.55),
    StyleSpec("caring", "a soft, motherly, caring voice", rate=0.9, pitch_st=-0.6, pitch_range=0.95, breath=0.15,
              gain_db=-1.5, gap_ms=80,
              instruct="Speak like a loving, caring mother comforting someone: soft, slow, reassuring and tender.",
              exaggeration=0.5),
    StyleSpec("tender", "very gentle and affectionate", rate=0.88, pitch_st=-0.4, pitch_range=0.9, breath=0.2,
              gain_db=-2.5, gap_ms=90, instruct="Speak very tenderly and affectionately, softly and slowly.",
              exaggeration=0.45),
    StyleSpec("soft", "quiet and gentle", rate=0.92, pitch_st=-0.3, pitch_range=0.85, breath=0.18, gain_db=-4.0,
              gap_ms=60, instruct="Speak quietly and gently, in a soft, hushed voice.", exaggeration=0.4),
    StyleSpec("whisper", "a real whisper", rate=0.9, whisper=True, gain_db=-6.0, gap_ms=120,
              instruct="Whisper very softly and intimately, close to the microphone.", exaggeration=0.35),
    StyleSpec("asmr", "close-mic ASMR: soft whisper, slow, light breaths", rate=0.82, whisper=True, gain_db=-5.0,
              gap_ms=260, instruct="Whisper extremely softly and slowly, close to the microphone, in a soothing ASMR "
              "style with gentle breaths.", exaggeration=0.3),
    StyleSpec("playful", "teasing and playful", rate=1.04, pitch_st=0.6, pitch_range=1.35, breath=0.05,
              instruct="Speak in a playful, teasing, light-hearted way, as if trying not to laugh.", exaggeration=0.7),
    StyleSpec("happy", "bright and happy", rate=1.03, pitch_st=0.8, pitch_range=1.25,
              instruct="Speak in a happy, cheerful, bright tone.", exaggeration=0.65),
    StyleSpec("excited", "excited and energetic", rate=1.1, pitch_st=1.6, pitch_range=1.5, gain_db=1.5,
              instruct="Speak with lots of excitement and energy, fast and bright.", exaggeration=0.85),
    StyleSpec("sleepy", "drowsy and slow", rate=0.8, pitch_st=-1.2, pitch_range=0.6, breath=0.25, gain_db=-3.0,
              gap_ms=220, instruct="Speak in a sleepy, drowsy, slow voice, as if about to fall asleep.",
              exaggeration=0.35),
    StyleSpec("sad", "sad and subdued", rate=0.88, pitch_st=-1.0, pitch_range=0.65, breath=0.2, gain_db=-2.5,
              gap_ms=150, instruct="Speak sadly, quietly and slowly, with a heavy heart.", exaggeration=0.6),
    StyleSpec("sarcastic", "dry and sarcastic", rate=0.93, pitch_st=0.0, pitch_range=1.45, gap_ms=60,
              instruct="Speak in a dry, sarcastic, deadpan tone, drawing out the words a little.", exaggeration=0.6),
    StyleSpec("sing-song", "sing-song, like a nursery rhyme", rate=0.95, pitch_st=0.8, pitch_range=1.2, melody=2.0,
              instruct="Speak in a sing-song, melodic, lilting way, like reciting a nursery rhyme.", exaggeration=0.6),
    StyleSpec("calm", "calm and steady", rate=0.94, pitch_st=-0.4, pitch_range=0.85, gap_ms=80,
              instruct="Speak calmly and steadily, relaxed and reassuring.", exaggeration=0.4),
    StyleSpec("serious", "serious and firm", rate=0.95, pitch_st=-0.8, pitch_range=0.8, gap_ms=60,
              instruct="Speak seriously and firmly, clear and direct.", exaggeration=0.5),
    StyleSpec("sing", "sung to a little melody she makes up on the spot (star/voice/singing.py)",
              instruct="Sing these words softly to a simple, gentle melody.", exaggeration=0.6),
    StyleSpec("nervous", "a bit nervous", rate=1.06, pitch_st=0.8, pitch_range=1.15, breath=0.12,
              instruct="Speak a little nervously and hesitantly.", exaggeration=0.6),
)}
STYLE_ALIASES = {"mommy": "caring", "motherly": "caring", "singsong": "sing-song", "whispering": "whisper",
                 "quiet": "soft", "gentle": "soft", "tired": "sleepy", "drowsy": "sleepy", "cheerful": "happy",
                 "teasing": "playful", "firm": "serious"}


@dataclass(frozen=True)
class SoundSpec:
    """A non-verbal sound. `native` is the engine tag that makes it (Chatterbox-Turbo); `text` is how to fake it with
    plain words when neither a native tag nor a recorded clip exists (None: skip the sound instead of faking it);
    `level_db` is its loudness relative to the speech around it."""
    name: str
    native: str = ""
    text: str | None = None
    level_db: float = -3.0
    filler: bool = False


SOUNDS: dict[str, SoundSpec] = {s.name: s for s in (
    SoundSpec("laugh", "[laugh]", None, -1.0),          # a voice reading "Ha ha!" is worse than no laugh
    SoundSpec("giggle", "[chuckle]", None, -3.0),
    SoundSpec("chuckle", "[chuckle]", None, -4.0),
    SoundSpec("sigh", "[sigh]", None, -6.0),
    SoundSpec("gasp", "[gasp]", None, -4.0),
    SoundSpec("hum", "", "Hmm.", -5.0),
    SoundSpec("cough", "[cough]", None, -3.0),
    SoundSpec("sneeze", "", None, -1.0),
    SoundSpec("yawn", "", None, -5.0),
    SoundSpec("sniff", "[sniff]", None, -8.0),
    SoundSpec("clear-throat", "[clear throat]", None, -5.0),
    SoundSpec("breath-in", "", None, -14.0),
    SoundSpec("breath-out", "", None, -14.0),
    SoundSpec("mm-hm", "", "Mm-hm.", -3.0, filler=True),
    SoundSpec("um", "", "Um,", -2.0, filler=True),
    SoundSpec("uh", "", "Uh,", -2.0, filler=True),
)}
SOUND_ALIASES = {"laughs": "laugh", "laughing": "laugh", "giggles": "giggle", "chuckles": "chuckle", "sighs": "sigh",
                 "gasps": "gasp", "hums": "hum", "humming": "hum", "coughs": "cough", "sneezes": "sneeze",
                 "yawns": "yawn", "sniffs": "sniff", "clear throat": "clear-throat", "throat-clear": "clear-throat",
                 "inhale": "breath-in", "exhale": "breath-out", "breath": "breath-in", "mmhm": "mm-hm"}
DEFAULT_PAUSE_MS = 300
MAX_PAUSE_MS = 2000


@dataclass(frozen=True)
class Segment:
    kind: str                       # "speech" | "sound" | "pause"
    text: str = ""                  # speech: the words; sound: the sound name
    style: str = "neutral"
    intensity: float = DEFAULT_INTENSITY
    pause_ms: int = 0
    emphasis: tuple = ()            # speech: words to stress
    question: bool = False          # speech: a yes/no question (rising end); wh-questions fall like statements
    voice: str = ""                 # speech: character voice id for role-play ("" = Star)


_TAG = re.compile(r"<\s*(/?)\s*([a-z][a-z\- ]{0,20}?)\s*(?::\s*([0-9.]+))?\s*/?\s*>|\[\s*(/?)\s*([a-z][a-z\- ]{0,20}?)"
                  r"\s*(?::\s*([0-9.]+))?\s*\]", re.I)
_SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*(?=\s|$)")
_WH = re.compile(r"^\W*(?:what|why|how|when|where|who|whom|whose|which)\b", re.I)


def canonical(name: str) -> tuple[str, str] | None:
    """('style'|'sound'|'pause'|'emph', canonical name) for a tag name, or None when it is not one of ours."""
    key = re.sub(r"\s+", " ", name.strip().lower())
    key = STYLE_ALIASES.get(key, key)
    if key in STYLES:
        return "style", key
    key = SOUND_ALIASES.get(key, key)
    if key in SOUNDS:
        return "sound", key
    if key == "pause":
        return "pause", key
    if key in ("emph", "emphasis", "stress"):
        return "emph", "emph"
    return None


def strip_tags(text: str) -> str:
    """The words only, every known tag removed (for subtitles, transcripts and engines without tag support)."""
    def drop(match: re.Match) -> str:
        return " " if canonical(match.group(2) or match.group(5) or "") else match.group(0)
    return re.sub(r"\s{2,}", " ", _TAG.sub(drop, text)).strip()


def protect_tags(text: str) -> tuple[str, list[str]]:
    """Swap known tags for placeholders that markup cleaning will not touch; restore_tags puts them back."""
    found: list[str] = []

    def keep(match: re.Match) -> str:
        if not canonical(match.group(2) or match.group(5) or ""):
            return match.group(0)
        found.append(match.group(0))
        return f" \ue000{len(found) - 1}\ue001 "
    return _TAG.sub(keep, text), found


def restore_tags(text: str, found: list[str]) -> str:
    return re.sub("\ue000([0-9]+)\ue001", lambda m: found[int(m.group(1))] if int(m.group(1)) < len(found) else "", text)


def has_tags(text: str) -> bool:
    return any(canonical(m.group(2) or m.group(5) or "") for m in _TAG.finditer(text or ""))


def _intensity(raw: str | None, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(raw))) if raw else default
    except ValueError:
        return default


def is_yes_no_question(sentence: str) -> bool:
    words = strip_tags(sentence).strip()
    return words.endswith("?") and not _WH.match(words)


@dataclass
class _State:
    style: str
    intensity: float
    pending: tuple | None = None        # (style, intensity) waiting for the next sentence
    close_at_end: bool = False
    emph: bool = False
    emphasis: list = field(default_factory=list)


def parse(text: str, style: str = "neutral", intensity: float = DEFAULT_INTENSITY, voice: str = "") -> list[Segment]:
    """Split tagged text into speech, sound and pause segments, one speech segment per sentence at most.

    `style`/`intensity` are the defaults for untagged speech (from the mood mapping or the settings)."""
    return parse_carry(text, style, intensity, voice)[0]


def parse_carry(text: str, style: str = "neutral", intensity: float = DEFAULT_INTENSITY, voice: str = "",
                carry: tuple | None = None) -> tuple[list[Segment], tuple | None]:
    """parse() for text that arrives one sentence at a time (the call path): `carry` is the (style, intensity) left
    open by the previous sentence, and the second value returned is what this text leaves open (None = back to the
    default), to pass in with the next sentence of the same reply."""
    base = (style if style in STYLES else "neutral", intensity)
    open_style, open_intensity = carry or base
    state = _State(open_style, open_intensity)
    segments: list[Segment] = []
    words: list[str] = []
    sentence_open = False            # True once the current sentence has words

    def flush_words(end_of_sentence: bool) -> None:
        nonlocal sentence_open
        spoken = re.sub(r"\s+", " ", "".join(words)).strip()
        words.clear()
        if spoken and any(ch.isalnum() for ch in spoken):
            segments.append(Segment("speech", spoken, state.style, state.intensity, emphasis=tuple(state.emphasis),
                                    question=is_yes_no_question(spoken), voice=voice))
            state.emphasis.clear()
        if end_of_sentence:
            sentence_open = False
            if state.close_at_end:
                state.style, state.intensity, state.close_at_end = base[0], base[1], False
            if state.pending:
                state.style, state.intensity = state.pending
                state.pending = None

    def add_text(chunk: str) -> None:
        nonlocal sentence_open
        position = 0
        for match in _SENTENCE_END.finditer(chunk):
            piece = chunk[position:match.end()]
            words.append(piece)
            if any(ch.isalnum() for ch in piece) or sentence_open:
                flush_words(True)
            position = match.end()
        rest = chunk[position:]
        if rest:
            words.append(rest)
            if any(ch.isalnum() for ch in rest):
                sentence_open = True
        if state.emph:
            state.emphasis.extend(re.findall(r"[A-Za-z0-9']+", chunk))

    position = 0
    for match in _TAG.finditer(text or ""):
        closing = match.group(1) or match.group(4)
        name = match.group(2) or match.group(5) or ""
        known = canonical(name)
        if not known:
            continue
        add_text(text[position:match.start()])
        position = match.end()
        kind, key = known
        level = _intensity(match.group(3) or match.group(6), DEFAULT_INTENSITY)
        mid_sentence = sentence_open or bool("".join(words).strip())
        if kind == "style":
            if closing:
                if mid_sentence:
                    state.close_at_end = True
                else:
                    state.style, state.intensity = base
                    state.pending = None
            elif mid_sentence:
                state.pending, state.close_at_end = (key, level), False
            else:
                state.style, state.intensity, state.pending, state.close_at_end = key, level, None, False
        elif kind == "emph":
            state.emph = not closing
        elif not closing:
            if kind == "sound":
                flush_words(False)
                segments.append(Segment("sound", key, state.style, state.intensity))
                sentence_open = sentence_open and True
            else:
                flush_words(False)
                ms = int(float(match.group(3) or match.group(6) or DEFAULT_PAUSE_MS))
                segments.append(Segment("pause", pause_ms=max(0, min(MAX_PAUSE_MS, ms))))
    add_text(text[position:] if text else "")
    flush_words(True)
    left_open = (state.style, state.intensity)
    return segments, (None if left_open == base else left_open)


def restrict(segments: list[Segment], allowed_styles: frozenset | None = None, allowed_sounds: frozenset | None = None,
             fallback: str = "neutral") -> list[Segment]:
    """Apply the owner's settings: a style that is not allowed becomes `fallback`, a sound that is not allowed is
    dropped. None means everything is allowed."""
    out = []
    for seg in segments:
        if seg.kind == "speech" and allowed_styles is not None and seg.style not in allowed_styles:
            seg = replace(seg, style=fallback if fallback in allowed_styles or fallback == "neutral" else "neutral")
        if seg.kind == "sound" and allowed_sounds is not None and seg.text not in allowed_sounds:
            continue
        out.append(seg)
    return out


class SoundPolicy:
    """Keeps non-verbal sounds rare, the way people use them: at most `per_reply` per reply and `per_minute` across
    replies, never the same sound twice within `repeat_gap` seconds, and fillers (um, uh) at most one per reply.
    Sounds she wrote herself count too: a reply full of <laugh> keeps the first one only."""

    def __init__(self, per_reply: int = 2, per_minute: int = 4, repeat_gap: float = 45.0, clock=None) -> None:
        import time
        self.per_reply, self.per_minute, self.repeat_gap = per_reply, per_minute, repeat_gap
        self.clock = clock or time.monotonic
        self._recent: list[tuple[float, str]] = []

    def filter(self, segments: list[Segment]) -> list[Segment]:
        now = self.clock()
        self._recent = [(t, n) for t, n in self._recent if now - t < max(60.0, self.repeat_gap)]
        kept, used, fillers = [], 0, 0
        for seg in segments:
            if seg.kind == "sound":
                spec = SOUNDS[seg.text]
                last_minute = sum(1 for t, _ in self._recent if now - t < 60.0)
                repeated = any(n == seg.text and now - t < self.repeat_gap for t, n in self._recent)
                if used >= self.per_reply or last_minute >= self.per_minute or repeated or (spec.filler and fillers):
                    continue
                used += 1
                fillers += spec.filler
                self._recent.append((now, seg.text))
            kept.append(seg)
        return kept


# -- mood and conversation -> style -------------------------------------------------------------------------------
# dominant feeling (star.emotion) -> (style, intensity at full strength)
MOOD_STYLE = {
    "joy": ("happy", 0.6), "pride": ("warm", 0.6), "curiosity": ("warm", 0.4), "frustration": ("serious", 0.5),
    "boredom": ("sleepy", 0.4), "affection": ("caring", 0.6), "nervousness": ("nervous", 0.5),
    "sadness": ("sad", 0.6), "anger": ("serious", 0.7), "hurt": ("sad", 0.5), "loneliness": ("soft", 0.5),
    "fear": ("nervous", 0.6), "embarrassment": ("nervous", 0.4), "guilt": ("soft", 0.5), "jealousy": ("calm", 0.3),
    "disappointment": ("sad", 0.4), "gratitude": ("warm", 0.7), "excitement": ("excited", 0.7),
    "contentment": ("calm", 0.5), "love": ("tender", 0.6), "hope": ("warm", 0.5), "nostalgia": ("soft", 0.4),
    "surprise": ("excited", 0.5), "relief": ("calm", 0.5), "amusement": ("playful", 0.6),
}
# Feeling -> sounds that may slip out (sparingly: see suggest_sound), with a base chance at full strength.
MOOD_SOUNDS = {"amusement": (("giggle", "chuckle", "laugh"), 0.35), "joy": (("giggle",), 0.15),
               "relief": (("breath-out", "sigh"), 0.3), "surprise": (("gasp",), 0.3), "sadness": (("sigh",), 0.2),
               "disappointment": (("sigh",), 0.25), "boredom": (("yawn",), 0.2), "excitement": (("gasp",), 0.1),
               "frustration": (("sigh",), 0.2), "contentment": (("hum",), 0.1)}

_SAD_TALK = re.compile(r"\b(sad|upset|crying|lonely|hurt|bad day|depressed|miss (?:you|her|him)|grief|lost my)\b", re.I)
_SLEEP_TALK = re.compile(r"\b(can'?t sleep|bed ?time|going to bed|good ?night|sleepy|tired|lullaby|help me sleep|"
                         r"fall asleep|asmr|whisper)\b", re.I)
_JOKE_TALK = re.compile(r"\b(lol|lmao|haha+|joke|funny|kidding|tease)\b", re.I)
_HYPE_TALK = re.compile(r"\b(we won|i won|did it|passed|got the job|guess what|amazing news|so excited)\b|!{2,}", re.I)
_SCARED_TALK = re.compile(r"\b(scared|afraid|anxious|panic|nervous|worried)\b", re.I)


@dataclass(frozen=True)
class StyleChoice:
    style: str
    intensity: float
    reason: str


def style_for_mood(mood: dict | None, base: str = "warm") -> StyleChoice:
    """The tone her current feeling gives her voice (star.emotion.current() output). A mild or absent feeling keeps
    `base`; the intensity grows with how far the feeling is above its baseline and with arousal."""
    if not mood or not mood.get("dominant"):
        return StyleChoice(base, DEFAULT_INTENSITY * 0.7, "no strong feeling")
    name = mood["dominant"]
    style, strength = MOOD_STYLE.get(name, (base, 0.5))
    arousal = float(mood.get("arousal", 0.35) or 0.35)
    level = max(0.2, min(1.0, strength * (0.7 + 0.6 * arousal)))
    if style == "excited" and arousal < 0.35:
        style = "happy"                     # calm joy is happy, not bouncing
    return StyleChoice(style, round(level, 2), f"feeling {name}")


def style_for_context(user_text: str, mood: dict | None = None, base: str = "warm",
                      hour: int | None = None) -> StyleChoice:
    """Tone for this reply from what was just said, then her mood: comfort for sad news, soft at bedtime, playful
    for a joke, excited for big news. What the other person needs comes before her own feeling."""
    text = user_text or ""
    if _SAD_TALK.search(text):
        return StyleChoice("caring", 0.7, "they sound sad")
    if _SCARED_TALK.search(text):
        return StyleChoice("calm", 0.7, "they sound worried")
    if _SLEEP_TALK.search(text) or (hour is not None and (hour >= 23 or hour < 5)):
        return StyleChoice("soft", 0.7, "bedtime")
    if _HYPE_TALK.search(text):
        return StyleChoice("excited", 0.7, "big news")
    if _JOKE_TALK.search(text):
        return StyleChoice("playful", 0.6, "a joke")
    return style_for_mood(mood, base)


def suggest_sound(mood: dict | None, rng: random.Random | None = None) -> str | None:
    """Maybe a small sound that fits her feeling (a giggle when amused, a sigh of relief), or None. Rare by design;
    the SoundPolicy still caps it."""
    if not mood or not mood.get("dominant"):
        return None
    options = MOOD_SOUNDS.get(mood["dominant"])
    if not options:
        return None
    names, chance = options
    rng = rng or random.Random()
    strength = float(mood.get("arousal", 0.35) or 0.35)
    if rng.random() < chance * (0.5 + strength):
        return rng.choice(names)
    return None


_CLAUSE_START = re.compile(r"(?<=[.!?,]\s)(?=[A-Za-z])")


def add_fillers(text: str, rng: random.Random | None = None, chance: float = 0.15, style: str = "neutral") -> str:
    """At most one natural filler or micro-pause in a reply ("um," before a thought, a short pause after a comma),
    never in serious/whisper/asmr delivery and never in a reply that already has tags of its own."""
    if style in ("serious", "whisper", "asmr", "excited") or has_tags(text):
        return text
    rng = rng or random.Random()
    if rng.random() >= chance:
        return text
    spots = [m.start() for m in _CLAUSE_START.finditer(text)]
    if not spots:
        return text
    at = rng.choice(spots)
    insert = rng.choice(("<um> ", "<uh> ", "<pause:180> "))
    return text[:at] + insert + text[at:]


TAGS_PROMPT = """Your voice can do what a person's voice does. You may mark how a sentence sounds, sparingly, with tags the listener never sees:
- tone: <whisper> <soft> <warm> <caring> <tender> <playful> <happy> <excited> <sleepy> <sad> <sarcastic> <sing-song> <calm> <serious> <nervous>; put the tag at the start of a sentence; it lasts until you close it (</whisper>) or the reply ends. Add strength if you like: <excited:0.9>.
- do not sing for now (your singing voice is not ready); never other people's song lyrics: offer to write your own words instead.
- small sounds: <laugh> <giggle> <chuckle> <sigh> <gasp> <hum> <yawn> <sniff> <breath-out>; a pause: <pause>; stress a word: <emph>really</emph>.
Use them only when they fit what you feel and what is happening, at most one or two per reply, never in every reply. Plain sentences are fine."""


def known_tag_names() -> list[str]:
    return sorted(STYLES) + sorted(SOUNDS) + ["pause", "emph"]


__all__ = ["STYLES", "SOUNDS", "Segment", "protect_tags", "restore_tags", "StyleSpec", "SoundSpec", "StyleChoice", "SoundPolicy", "TAGS_PROMPT",
           "parse", "parse_carry", "restrict", "strip_tags", "has_tags", "canonical", "style_for_mood", "style_for_context",
           "suggest_sound", "add_fillers", "is_yes_no_question", "known_tag_names"]
