"""Builds a ready-to-use CallSession from VoiceSettings: loads the engines once and warms them up."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .brain import ServerBrain
from .call import CallSession, Speaker
from .persona import system_message
from .settings import VoiceSettings


@dataclass
class Engines:
    """Loaded models. Loading takes seconds, so keep this object and reuse it between calls."""
    vad: object
    endpointer: object | None
    asr: object
    tts: object
    load_seconds: dict

    @classmethod
    def load(cls, settings: VoiceSettings, progress: Callable[[str], None] | None = None) -> "Engines":
        from . import engines
        say = progress or (lambda message: None)
        timings = {}

        def timed(label: str, build):
            say(label)
            started = time.perf_counter()
            value = build()
            timings[label] = round(time.perf_counter() - started, 2)
            return value

        vad = timed("Loading voice activity detector", lambda: engines.make_vad(settings.vad))
        endpointer = timed("Loading end-of-turn model", lambda: engines.make_endpointer(settings.endpointer))
        asr = timed("Loading speech recognition",
                    lambda: engines.make_asr(settings.asr_engine, settings.asr_model, settings.device,
                                             settings.asr_prompt))
        tts_kwargs = ({"pocket_model": settings.pocket_model}
                      if settings.tts_engine == "pocket" else {})
        tts = timed("Loading Star's voice",
                    lambda: engines.make_tts(settings.tts_engine, settings.voice, settings.speed, settings.device,
                                             lang=settings.tts_lang, gap_ms=settings.sentence_gap_ms,
                                             pitch_semitones=settings.pitch_semitones, **tts_kwargs))

        def warm() -> None:
            if hasattr(tts, "warm_up"):
                tts.warm_up()
            asr.transcribe(b"\x00\x00" * 16000, 16000)      # first call pays one-off set-up costs
            if endpointer is not None:
                endpointer.complete_probability(b"\x00\x00" * 16000)

        timed("Warming up", warm)
        return cls(vad, endpointer, asr, tts, timings)


def make_brain(settings: VoiceSettings):
    # Address and key from the app's Settings and keyring, the quick model by default;
    # STAR_SERVER_URL / STAR_SERVER_API_KEY / STAR_VOICE_MODEL override them.
    return ServerBrain.from_settings(max_tokens=int(settings.max_reply_tokens))


def build_session(settings: VoiceSettings, engines: Engines, speaker: Speaker, brain=None,
                  on_event: Callable[[dict], None] | None = None, prime: bool = True) -> CallSession:
    brain = brain or make_brain(settings)
    config = settings.call_config()
    if prime and hasattr(brain, "prime"):
        brain.prime([system_message(config.system_extra, config.style)])   # server reads the voice prompt before turn one
    if hasattr(engines.vad, "reset"):
        engines.vad.reset()
    return CallSession(vad=engines.vad, asr=engines.asr, brain=brain, tts=engines.tts, speaker=speaker,
                       endpointer=engines.endpointer, config=config, on_event=on_event)
