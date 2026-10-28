"""Voice call settings: which engines, which voice, how patient the turn-taking is.

Kept apart from star.desktop_core.Settings on purpose (that class is being changed on another branch).
Values come from the bridge payload or from STAR_VOICE_* environment variables; every value is
validated here because the bridge payload is written by the web UI.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass

from .call import CallConfig
from .catalog import STYLE_IDS
from .turn import TurnConfig

TTS_ENGINES = ("kokoro", "pocket")
TTS_LANGS = ("en-us", "en-gb")
ASR_ENGINES = ("faster-whisper",)
ASR_MODELS = ("auto", "tiny.en", "base.en", "small.en", "medium.en", "distil-large-v3", "large-v3-turbo",
              "tiny", "base", "small", "medium", "large-v3")
VAD_ENGINES = ("silero", "energy")
ENDPOINTERS = ("smart-turn", "silence")
OUTPUT_MODES = ("headphones", "speakers")
CALL_MODES = ("push-to-talk", "hands-free")
# The default "Star" persona voice: a warm, nurturing, mum-like blend of Kokoro stock voices (no real person),
# chosen in the 2026-10-13 audition round (docs/STAR_VOICE_CALLS.md section 10, catalog id "star-mum").
STAR_VOICE_ID = "star-mum"
STAR_VOICE = "af_heart:0.5+af_bella:0.25+af_nicole:0.25"
STAR_SPEED = 0.80
STAR_PITCH = 0.0
STAR_GAP_MS = 120
_VOICE_ID = re.compile(r"^[A-Za-z0-9_.:+\-]{1,120}$")


@dataclass
class VoiceSettings:
    tts_engine: str = "kokoro"
    pocket_model: str = "english_18m_2026-10"  # opt-in CPU TTS candidate
    voice: str = STAR_VOICE              # id from the audition page, or an engine-specific recipe
    speed: float = STAR_SPEED            # slower than neutral: calmer, mum-like
    voice_style: str = "warm-caring"     # speaking manner: warm-caring | confident-commanding | anime-bright
    voice_id: str = STAR_VOICE_ID        # catalog id of the chosen voice (star/voice/voices.json); "" = custom `voice`
    tts_lang: str = "en-us"              # phonemiser language for the voice (en-gb for the British stock voices)
    sentence_gap_ms: int = STAR_GAP_MS   # extra silence after each sentence (the commanding voices use 400 to 450)
    pitch_semitones: float = STAR_PITCH  # whole-voice pitch change in semitones (anime voices up, commanding down)
    call_mode: str = "push-to-talk"      # push-to-talk (hold a key or button) | hands-free (voice activity)
    read_aloud_auto: bool = False        # read each new chat reply aloud in Star's voice (opt-in)
    asr_engine: str = "faster-whisper"
    asr_model: str = "auto"              # auto = small.en on an NVIDIA GPU, base.en on the CPU
    asr_prompt: str = "Star, Roblox, Luau, RemoteEvent."     # spellings the transcript should prefer
    device: str = "auto"                 # auto | cuda | cpu
    vad: str = "silero"
    endpointer: str = "smart-turn"
    output: str = "headphones"           # "speakers" turns the echo gate on
    end_silence_ms: int = 640            # silence that ends a turn when the end-of-turn model is off
    min_end_silence_ms: int = 608        # shortest wait after you stop talking, even when Star is sure you are done
    max_silence_ms: int = 2000           # silence that always ends a turn
    barge_in_ms: int = 288               # speech needed to interrupt Star
    max_reply_tokens: int = 220
    partial_transcripts: bool = True
    input_device: str = ""               # sounddevice name or index; empty = system default
    output_device: str = ""
    system_extra: str = ""

    def validate(self) -> "VoiceSettings":
        from .pocket import POCKET_MODELS, POCKET_VOICES

        if self.pocket_model not in POCKET_MODELS:
            raise ValueError("Unknown Pocket TTS model")
        if self.tts_engine == "pocket":
            if self.voice not in POCKET_VOICES or self.voice_id:
                raise ValueError("Pocket TTS requires a named stock voice and empty voice_id")
            if self.speed != 1.0 or self.pitch_semitones != 0.0 or self.tts_lang != "en-us":
                raise ValueError("Pocket TTS does not support independent speed, pitch or language settings")
            if self.device == "cuda":
                raise ValueError("Pocket TTS in Star's voice adapter is CPU-only")
        checks = [(self.tts_engine in TTS_ENGINES, "Unknown text-to-speech engine"),
                  (bool(_VOICE_ID.match(self.voice)), "Invalid voice id"),
                  (0.6 <= float(self.speed) <= 1.4, "Speed must be between 0.6 and 1.4"),
                  (self.voice_style in STYLE_IDS, "Unknown voice style"),
                  (self.voice_id == "" or bool(_VOICE_ID.match(self.voice_id)), "Invalid voice catalog id"),
                  (self.tts_lang in TTS_LANGS, "Unknown voice language"),
                  (0 <= int(self.sentence_gap_ms) <= 1500, "sentence_gap_ms must be 0-1500"),
                  (-6.0 <= float(self.pitch_semitones) <= 6.0, "pitch_semitones must be between -6 and 6"),
                  (self.asr_engine in ASR_ENGINES, "Unknown speech-to-text engine"),
                  (self.asr_model in ASR_MODELS, "Unknown speech-to-text model"),
                  (len(self.asr_prompt) <= 300, "Speech-to-text hint is too long"),
                  (self.device in {"auto", "cuda", "cpu"}, "Device must be auto, cuda or cpu"),
                  (self.vad in VAD_ENGINES, "Unknown voice activity detector"),
                  (self.endpointer in ENDPOINTERS, "Unknown end-of-turn setting"),
                  (self.output in OUTPUT_MODES, "Output must be headphones or speakers"),
                  (self.call_mode in CALL_MODES, "Call mode must be push-to-talk or hands-free"),
                  (300 <= int(self.end_silence_ms) <= 3000, "end_silence_ms must be 300-3000"),
                  (256 <= int(self.min_end_silence_ms) <= 2000, "min_end_silence_ms must be 256-2000"),
                  (int(self.end_silence_ms) <= int(self.max_silence_ms) <= 6000, "max_silence_ms must be up to 6000"),
                  (96 <= int(self.barge_in_ms) <= 2000, "barge_in_ms must be 96-2000"),
                  (16 <= int(self.max_reply_tokens) <= 800, "max_reply_tokens must be 16-800"),
                  (len(self.input_device) <= 120 and len(self.output_device) <= 120, "Device name is too long"),
                  (len(self.system_extra) <= 1200, "Extra context is too long")]
        for ok, message in checks:
            if not ok:
                raise ValueError(message)
        return self

    @classmethod
    def from_mapping(cls, data: dict | None, base: "VoiceSettings | None" = None) -> "VoiceSettings":
        """Overlay known keys from a dict (bridge payload). Unknown keys are ignored, types are coerced."""
        values = asdict(base or cls())
        for key, current in values.items():
            if data and key in data and data[key] is not None:
                raw = data[key]
                if isinstance(current, bool):
                    values[key] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
                elif isinstance(current, int):
                    values[key] = int(raw)
                elif isinstance(current, float):
                    values[key] = float(raw)
                else:
                    values[key] = str(raw).strip()
        return cls(**values).validate()

    @classmethod
    def from_env(cls) -> "VoiceSettings":
        """STAR_VOICE_VOICE=blend-heart-nicole, STAR_VOICE_ASR_MODEL=base.en, and so on."""
        data = {key: os.environ[f"STAR_VOICE_{key.upper()}"] for key in asdict(cls())
                if os.environ.get(f"STAR_VOICE_{key.upper()}", "").strip()}
        return cls.from_mapping(data)

    def call_config(self) -> CallConfig:
        turn = TurnConfig(end_silence_ms=int(self.end_silence_ms), max_silence_ms=int(self.max_silence_ms),
                          min_end_silence_ms=min(int(self.min_end_silence_ms), int(self.max_silence_ms)),
                          barge_in_ms=int(self.barge_in_ms))
        return CallConfig(turn=turn, system_extra=self.system_extra, partial_transcripts=self.partial_transcripts,
                          use_echo_gate=self.output == "speakers", style=self.voice_style,
                          push_to_talk=self.call_mode == "push-to-talk")
