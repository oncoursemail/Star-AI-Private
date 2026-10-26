"""The instant, always-on voice on her own PC: the settings preset, keep-warm, and one function that assembles a call.

PC_PRESET     the VoiceSettings values for her PC (apply with apply_preset). Every key is an ordinary setting, so each can
              be undone one by one in the voice settings; nothing here is hard-wired.
KeepWarm      while no call turn is running, touches the voice, the speech recogniser and the brain every `interval`
              seconds so the GPU clocks, kernels and the server's prompt cache are never cold when she speaks.
build_pc_session
              speaker -> reference (her own voice is recorded for the echo canceller) -> optional hearing hub in the
              brain's context -> optional local fast model with the big brain for hard turns -> CallSession.
"""
from __future__ import annotations

import threading
import time

from ..voice.runtime import Engines, build_session, make_brain
from ..voice.settings import VoiceSettings
from .fastpath import RoutedBrain
from .hearing import ContextBrain, SensesHub
from .reference import PlaybackReference, ReferenceSpeaker

PC_PRESET = {
    "voice_id": "star-cute",          # then bridge._settings_for(entry) fills the recipe, speed and style
    "call_mode": "hands-free",
    "speculative_reply": True,        # start answering at the first pause (CallSession._start_spec_reply)
    "pause_ms": 192,
    "min_end_silence_ms": 384,        # the floor is cheap once the answer is already prepared (measured: bench.py)
    "first_clause_words": 3,
    "barge_in_ms": 160,               # she stops about 160 ms after you start talking over her (the default is 288)
    "backchannels": True,
    "acknowledgements": True,
    "partial_transcripts": True,
    "keep_warm": True,
    "voice_route": "virtual-mic",     # her voice only into the cable; Discord and games record "STAR Microphone"
    "hear_pc_audio": True,
    "fast_profile": "auto",
}


def apply_preset(base: VoiceSettings | None = None, overrides: dict | None = None) -> VoiceSettings:
    """VoiceSettings for her PC: the preset, the catalog voice it names, then any explicit overrides."""
    from ..voice.bridge import _settings_for
    from ..voice.catalog import find_voice
    values = dict(PC_PRESET)
    entry = find_voice(values["voice_id"])
    if entry is not None:
        values.update(_settings_for(entry))
    values.update(overrides or {})
    return VoiceSettings.from_mapping(values, base)


class KeepWarm:
    def __init__(self, *, tts=None, asr=None, brain=None, session=None, interval: float = 45.0,
                 clock=time.monotonic) -> None:
        self.tts, self.asr, self.brain, self.session = tts, asr, brain, session
        self.interval, self.clock = interval, clock
        self.touches = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="star-keep-warm", daemon=True)

    def start(self) -> "KeepWarm":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def touch(self) -> bool:
        """One round of warming. Skipped (False) while a turn is in progress: real work is the best warm-up."""
        if self.session is not None and (self.session.busy() or self.session.state in ("user_speaking", "thinking")):
            return False
        for engine, work in ((self.tts, lambda e: list(e.synthesize("Hm."))),
                             (self.asr, lambda e: e.transcribe(b"\x00\x00" * 8000, 16000)),
                             (self.brain, lambda e: e.prime([{"role": "system", "content": "Warm."}])
                              if hasattr(e, "prime") else None)):
            if engine is not None:
                try:
                    work(engine)
                except Exception:
                    pass                      # warming is only an optimisation
        self.touches += 1
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.touch()


def build_pc_session(settings: VoiceSettings, engines: Engines, speaker, *, hub: SensesHub | None = None,
                     big_brain=None, fast_brain=None, on_event=None):
    """A CallSession wired for her PC. Returns (session, keep_warm or None). The caller owns the hub, the speaker and
    the brains (it can build them from settings, see star.senses.routes.open_voice_output and fastpath)."""
    reference = hub.reference if hub is not None and hub.reference is not None else None
    if reference is None and hub is not None:
        raise ValueError("the hearing hub needs a PlaybackReference so her own voice can be excluded")
    if reference is not None:
        speaker = ReferenceSpeaker(speaker, reference)
    brain = big_brain or make_brain(settings)
    if hub is not None:                       # the hearing note goes inside the router: routing reads only her words
        brain = ContextBrain(brain, hub)
        fast_brain = ContextBrain(fast_brain, hub) if fast_brain is not None else None
    if fast_brain is not None and settings.fast_profile != "off":
        brain = RoutedBrain(fast_brain, brain, mode="auto")
    session = build_session(settings, engines, speaker, brain=brain, on_event=on_event)
    warm = None
    if settings.keep_warm:
        warm = KeepWarm(tts=engines.tts, asr=engines.asr, brain=fast_brain, session=session).start()   # not brain 1: it is shared
    return session, warm


def start_hearing(engines: Engines, settings: VoiceSettings, reference: PlaybackReference, *, devices=None,
                  on_event=None) -> SensesHub:
    """Open the capture devices and start listening: the PC's sound (WASAPI loopback of the default output) and the
    owner's physical microphone (never the virtual "STAR Microphone"). Returns the hub; ask it hub.describe()."""
    from ..voice import engines as voice_engines
    from . import routes
    from .capture import LoopbackSource, MicSource
    hub = SensesHub(vad_factory=lambda: voice_engines.make_vad(settings.vad), asr=engines.asr, reference=reference,
                    on_event=on_event)
    if settings.hear_pc_audio:
        hub.attach("loopback", LoopbackSource().frames())
    mic = routes.physical_microphone(devices or routes.query_devices(), settings.input_device)
    if mic is not None:
        hub.attach("mic", MicSource(mic["index"]).frames())
    return hub


__all__ = ["PC_PRESET", "apply_preset", "KeepWarm", "build_pc_session", "start_hearing", "PlaybackReference"]
