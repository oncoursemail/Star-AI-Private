"""Opt-in CPU-streaming Pocket TTS adapter for Star's existing voice pipeline.

No network/model loading on import. An owner explicitly selects this engine;
the stock Kokoro voice remains the default. A small model can produce chunks
while the gamer GPU stays available for Roblox, OBS, and Live2D.

Only named upstream stock voices are accepted. Never pass viewer/LLM-controlled
paths, URLs or custom voice biometrics to the TTS voice-state loader. Installing
pocket-tts and obtaining upstream weights is an explicit owner action.
"""
from __future__ import annotations

import math
import threading
from typing import Iterable

# Stock identities listed in the upstream Pocket TTS voice catalog.
POCKET_VOICES = frozenset({
    "alba", "anna", "azelma", "bill_boerst", "caro_davy", "charles",
    "cosette", "eponine", "eve", "fantine", "george", "jane", "jean",
    "javert", "marius", "mary", "michael", "paul", "peter_yearsley",
    "stuart_bell", "vera",
})
POCKET_MODELS = frozenset({
    "english_2026-10",
    "english_18m_2026-10", "english_18m_refl_2026-10",
    "english_7m_2026-10", "english_7m_refl_2026-10",
    "english_2m_2026-10", "english_2m_refl_2026-10",
})
DEFAULT_POCKET_MODEL = "english_18m_2026-10"


class PocketStreamingTTS:
    """Warm reusable voice state, serialized generation, epoch-scoped cancel.

    The upstream model is not thread-safe. This instance never overlaps its
    generation calls, and stop_generation() does not wait for the model lock.
    Its cancellation event is new for each utterance, so cancelling an old
    generation cannot poison the next sentence or the next call.
    """

    def __init__(
        self, voice: str = "alba", *,
        model: str = DEFAULT_POCKET_MODEL, gap_ms: int = 0,
        model_factory=None,
    ) -> None:
        if model not in POCKET_MODELS:
            raise ValueError("unsupported Pocket TTS model")
        if voice not in POCKET_VOICES:
            raise ValueError("choose a named, licensed Pocket TTS stock voice")
        if type(gap_ms) is not int or not 0 <= gap_ms <= 1500:
            raise ValueError("Pocket TTS gap must be 0..1500 ms")
        # The dependency is optional; nothing is installed or downloaded on
        # import of Star's normal voice engine or in repository-wide tests.
        if model_factory is None:
            try:
                from pocket_tts import TTSModel
            except ImportError as exc:
                raise RuntimeError(
                    "Pocket TTS is opt-in: install pocket-tts in the voice environment"
                ) from exc
            model_factory = TTSModel.load_model
        self._model = model_factory(language=model)
        sample_rate = getattr(self._model, "sample_rate", None)
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 96000:
            raise RuntimeError("Pocket TTS reported an invalid sample rate")
        self.sample_rate: int = sample_rate
        self.model_name = model
        self.device = "cpu"
        self.speed = 1.0  # Pocket does not expose an independent speed control.
        self.lang = "en-us"
        self.pitch_semitones = 0.0  # Do not falsely report pitch control.
        self.gap_ms = gap_ms
        self._generation_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active: threading.Event | None = None
        self._voice_state = None
        self.voice = ""
        self.set_voice(voice)

    def set_voice(self, voice: str) -> None:
        if voice not in POCKET_VOICES:
            raise ValueError("voice must be a named Pocket TTS stock voice")
        with self._generation_lock:
            if voice != self.voice:
                state = self._model.get_state_for_audio_prompt(voice)
                with self._state_lock:
                    self._voice_state, self.voice = state, voice

    def stop_generation(self) -> bool:
        """Called by a trusted host on barge-in; never blocks on inference."""
        with self._state_lock:
            active = self._active
            if active is None:
                return False
            active.set()
            return True

    def warm_up(self) -> None:
        for _ in self.synthesize("Hello."):
            pass

    def synthesize(self, text: str) -> Iterable[tuple[bytes, int]]:
        if type(text) is not str or not 1 <= len(text.strip()) <= 4000:
            raise ValueError("Pocket TTS utterance must be 1..4000 characters")
        import numpy as np
        from .engines import float_to_pcm16

        with self._generation_lock:
            stop = threading.Event()
            with self._state_lock:
                self._active = stop
                voice_state = self._voice_state
            stream = None
            try:
                stream = self._model.generate_audio_stream(
                    voice_state, text, copy_state=True, stop=stop
                )
                for frame in stream:
                    if stop.is_set():
                        break
                    # The model emits float PCM tensor chunks (normally 80 ms).
                    # Convert each chunk separately to enable first-chunk audio.
                    samples = np.asarray(
                        frame.detach().cpu().numpy(), dtype=np.float32
                    )
                    if samples.ndim != 1 or not 0 < samples.size <= 96000:
                        raise ValueError("invalid Pocket TTS audio chunk")
                    if not bool(np.isfinite(samples).all()):
                        raise ValueError("nonfinite Pocket TTS audio samples")
                    pcm = float_to_pcm16(samples)
                    if not stop.is_set():
                        yield pcm, self.sample_rate
                if not stop.is_set() and self.gap_ms:
                    frames = math.floor(self.sample_rate * self.gap_ms / 1000)
                    yield bytes(2) * frames, self.sample_rate
            finally:
                stop.set()
                # Close the backend iterator to release generation workers
                # after normal completion, exception or early interruption.
                try:
                    if stream is not None and hasattr(stream, "close"):
                        stream.close()
                finally:
                    # Cleanup must not be skipped if a backend iterator's
                    # close() fails. Otherwise future interrupts can target
                    # an abandoned generation epoch.
                    with self._state_lock:
                        if self._active is stop:
                            self._active = None


__all__ = [
    "PocketStreamingTTS", "POCKET_MODELS", "POCKET_VOICES",
    "DEFAULT_POCKET_MODEL",
]
