"""Real engines for voice calls. Everything here needs the optional packages in requirements-voice.txt.

Engines are picked by name through the small registries at the bottom (make_vad, make_asr, make_tts,
make_endpointer), so a new speech engine is one class plus one registry line. Heavy imports happen
inside constructors: importing this module is cheap and never loads a model.

Model files are looked up in the folder named by STAR_VOICE_MODELS (see docs/STAR_VOICE_CALLS.md):
  kokoro-v1.0.onnx, voices-v1.0.bin    Kokoro-82M text-to-speech (Apache-2.0)
  silero_vad.onnx                      Silero VAD v6 (MIT)
  smart-turn-v3.2-cpu.onnx             Pipecat Smart Turn v3.2 end-of-turn model (BSD-2-Clause)
"""
from __future__ import annotations

import glob
import math
import os
import site
import threading
from pathlib import Path
from typing import Iterable

from .pcm import FRAME_SAMPLES, SAMPLE_RATE, rms

_dll_dirs_added = False


def models_dir() -> Path:
    configured = os.environ.get("STAR_VOICE_MODELS", "").strip()
    if configured:
        return Path(configured)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "STAR" / "voice-models"


def model_file(name: str) -> Path:
    path = models_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"Voice model file missing: {path}. See docs/STAR_VOICE_CALLS.md (Setup).")
    return path


def add_nvidia_dll_dirs() -> None:
    """Make the CUDA and cuDNN DLLs from the nvidia-* wheels findable on Windows.

    cuDNN 9 loads its sub-libraries by name at run time. Without the wheel folders on PATH, onnxruntime's
    CUDA provider fails on the first convolution ("Failed to initialize CUDNN Frontend") and silently
    falls back to the CPU, and CTranslate2 (faster-whisper) cannot find cublas64_12.dll.
    """
    global _dll_dirs_added
    if _dll_dirs_added or os.name != "nt":
        return
    _dll_dirs_added = True
    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    for root in roots:
        for folder in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(folder)
            except OSError:
                pass


def gpu_available() -> bool:
    try:
        import onnxruntime as ort
        ort.set_default_logger_severity(3)          # keep provider warnings out of the console
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def pcm16_to_float(pcm: bytes):
    import numpy as np
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(samples) -> bytes:
    import numpy as np
    return (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def resample(samples, source_rate: int, target_rate: int):
    """Band-limited resampling of a whole clip (FFT method). For offline clips, not for live streams."""
    import numpy as np
    samples = np.asarray(samples, dtype=np.float32)
    if source_rate == target_rate or samples.size == 0:
        return samples
    target = int(round(samples.size * target_rate / source_rate))
    spectrum = np.fft.rfft(samples)
    bins = target // 2 + 1
    resized = np.zeros(bins, dtype=spectrum.dtype)
    keep = min(bins, spectrum.size)
    resized[:keep] = spectrum[:keep]
    return (np.fft.irfft(resized, n=target) * (target / samples.size)).astype(np.float32)


# -- voice activity ---------------------------------------------------------------------------
class EnergyVAD:
    """Loudness-based fallback with an adaptive noise floor. Pure Python; far less robust than Silero."""

    def __init__(self, ratio: float = 3.5, floor: float = 0.004) -> None:
        self.ratio, self.floor, self.noise = ratio, floor, floor

    def probability(self, frame: bytes) -> float:
        level = rms(frame)
        if level < self.noise * 1.5:
            self.noise += 0.05 * (level - self.noise)          # track the room quickly when it is quiet
        else:
            self.noise += 0.001 * (level - self.noise)         # and only creep up during speech
        threshold = max(self.floor, self.noise * self.ratio)
        return max(0.0, min(1.0, 0.5 * level / threshold))


class SileroVAD:
    """Silero VAD v5/v6 ONNX on one CPU thread (well under 1 ms per 32 ms frame)."""

    CONTEXT = 64

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        import numpy as np
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self._np = np
        self._session = ort.InferenceSession(str(path or model_file("silero_vad.onnx")), sess_options=options,
                                             providers=["CPUExecutionProvider"])
        self._rate = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        np = self._np
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def probability(self, frame: bytes) -> float:
        np = self._np
        audio = pcm16_to_float(frame)[None, :FRAME_SAMPLES]
        if audio.shape[1] < FRAME_SAMPLES:
            audio = np.pad(audio, ((0, 0), (0, FRAME_SAMPLES - audio.shape[1])))
        data = np.concatenate([self._context, audio], axis=1)
        out, self._state = self._session.run(None, {"input": data, "state": self._state, "sr": self._rate})
        self._context = data[:, -self.CONTEXT:]
        return float(out[0][0])


# -- end of turn ------------------------------------------------------------------------------
def _mel_filters(sample_rate: int = 16000, n_fft: int = 400, n_mels: int = 80):
    """Slaney-style mel filter bank, as used by Whisper."""
    import numpy as np
    fft_freqs = np.fft.rfftfreq(n=n_fft, d=1.0 / sample_rate)
    mels = np.linspace(0.0, 45.245640471924965, n_mels + 2)
    freqs = (200.0 / 3) * mels
    log_region = mels >= 15.0
    freqs[log_region] = 1000.0 * np.exp(np.log(6.4) / 27.0 * (mels[log_region] - 15.0))
    ramps = freqs.reshape(-1, 1) - fft_freqs.reshape(1, -1)
    diffs = np.diff(freqs)
    weights = np.maximum(0.0, np.minimum(-ramps[:-2] / diffs[:-1, None], ramps[2:] / diffs[1:, None]))
    return (weights * (2.0 / (freqs[2:n_mels + 2] - freqs[:n_mels]))[:, None]).astype(np.float32)


def whisper_log_mel(audio, n_fft: int = 400, hop: int = 160):
    """Whisper's log-mel features in numpy: [80, len(audio) // hop]."""
    import numpy as np
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    padded = np.pad(np.asarray(audio, dtype=np.float32), n_fft // 2, mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop][:-1]
    power = np.abs(np.fft.rfft(frames * window, axis=-1)) ** 2
    log = np.log10(np.maximum(power @ _mel_filters(n_fft=n_fft).T, 1e-10))
    log = np.maximum(log, log.max() - 8.0)
    return ((log + 4.0) / 4.0).T.astype(np.float32)


class SmartTurnEndpointer:
    """Pipecat Smart Turn v3: listens to the last 8 s of the turn and says whether the speaker has finished.

    Preprocessing follows the project's reference inference.py: keep the last 8 s (zero-pad at the
    front), normalise to zero mean and unit variance, Whisper log-mel features.
    """

    SECONDS = 8

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        import numpy as np
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self._np = np
        self._session = ort.InferenceSession(str(path or model_file("smart-turn-v3.2-cpu.onnx")),
                                             sess_options=options, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def complete_probability(self, pcm: bytes) -> float:
        np = self._np
        audio = pcm16_to_float(pcm)
        wanted = self.SECONDS * SAMPLE_RATE
        audio = audio[-wanted:] if audio.size >= wanted else np.pad(audio, (wanted - audio.size, 0))
        audio = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)
        features = whisper_log_mel(audio)[None, :, :]
        return float(np.ravel(self._session.run(None, {self._input: features})[0])[0])


# -- speech to text ---------------------------------------------------------------------------
# Measured on this project's PC (voice-lab/asr_bench.py): small.en is fast enough on the GPU, but takes
# seconds per sentence on the CPU, where base.en keeps the transcript inside the end-of-turn wait.
AUTO_ASR_MODEL = {"cuda": "small.en", "cpu": "base.en"}


def _letters(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


class FasterWhisperASR:
    """faster-whisper (CTranslate2). On the GPU: float16; on the CPU: int8."""

    def __init__(self, model: str = "auto", device: str = "auto", language: str | None = "en",
                 prompt: str = "") -> None:
        add_nvidia_dll_dirs()
        from faster_whisper import WhisperModel
        if device == "auto":
            device = "cuda" if gpu_available() else "cpu"
        if model in ("", "auto"):
            model = AUTO_ASR_MODEL[device]
        self.device, self.language, self.prompt = device, language, prompt
        self.model_name = model
        self._lock = threading.Lock()
        try:
            self._model = WhisperModel(model, device=device, compute_type="float16" if device == "cuda" else "int8")
        except Exception:
            if device != "cuda":
                raise
            self.device = "cpu"          # no usable CUDA runtime: carry on slower instead of failing the call
            self._model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        audio = pcm16_to_float(pcm)
        if sample_rate != SAMPLE_RATE:
            audio = resample(audio, sample_rate, SAMPLE_RATE)
        if audio.size < SAMPLE_RATE // 10:
            return ""
        with self._lock:
            segments, _ = self._model.transcribe(
                audio, language=self.language, beam_size=1, temperature=0.0, vad_filter=False,
                condition_on_previous_text=False, without_timestamps=True,
                initial_prompt=self.prompt or None, no_speech_threshold=0.6)
            text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
        # Given a short or unclear clip, Whisper sometimes "transcribes" its own hint text. That is not speech.
        said, hint = _letters(text), _letters(self.prompt)
        if hint and len(said) >= 0.6 * len(hint) and said in hint:
            return ""
        return text


# -- text to speech ---------------------------------------------------------------------------
# Voice ids as shown on the audition page (docs/voice-samples/ab, engine "kokoro"): stock Kokoro voices or
# weighted blends of them. No real person is copied.
KOKORO_VOICES = {
    "heart": [("af_heart", 1.0)],
    "bella": [("af_bella", 1.0)],
    "nicole": [("af_nicole", 1.0)],
    "sarah": [("af_sarah", 1.0)],
    "aoede": [("af_aoede", 1.0)],
    "kore": [("af_kore", 1.0)],
    "emma-uk": [("bf_emma", 1.0)],
    "isabella-uk": [("bf_isabella", 1.0)],
    "blend-heart-nicole": [("af_heart", 0.6), ("af_nicole", 0.4)],
    "blend-heart-emma": [("af_heart", 0.6), ("bf_emma", 0.4)],
    "blend-bella-sarah": [("af_bella", 0.5), ("af_sarah", 0.5)],
    "blend-heart-bella-nicole": [("af_heart", 0.5), ("af_bella", 0.3), ("af_nicole", 0.2)],
}


def pitch_ratio(semitones: float) -> float:
    """Frequency ratio of a pitch change in semitones: +12 doubles the pitch, -12 halves it."""
    return 2.0 ** (float(semitones) / 12.0)


def parse_kokoro_voice(voice: str) -> list[tuple[str, float]]:
    """'heart', 'af_heart', or a custom blend such as 'af_heart:0.7+af_nicole:0.3'."""
    voice = voice.strip()
    if voice in KOKORO_VOICES:
        return KOKORO_VOICES[voice]
    parts = []
    for piece in voice.split("+"):
        name, _, weight = piece.strip().partition(":")
        try:
            value = float(weight) if weight else 1.0
        except ValueError:
            raise ValueError(f"Unknown Kokoro voice: {voice!r}") from None
        parts.append((name.strip(), value))
    total = sum(w for _, w in parts)
    # "nan" and "inf" parse as floats but pass every comparison below (or make total infinite), which
    # turned the blend into NaN weights and Star's voice into silence or noise.
    if (not parts or not math.isfinite(total) or total <= 0
            or any(not math.isfinite(w) or w < 0 or not n for n, w in parts)):
        raise ValueError(f"Unknown Kokoro voice: {voice!r}")
    return [(n, w / total) for n, w in parts]


class KokoroTTS:
    """Kokoro-82M through kokoro-onnx. One sentence in, one chunk of 24 kHz audio out."""

    sample_rate = 24000

    def __init__(self, voice: str = "heart", speed: float = 0.92, device: str = "auto", lang: str = "en-us",
                 model: str | os.PathLike | None = None, voices: str | os.PathLike | None = None,
                 gap_ms: int = 0, pitch_semitones: float = 0.0) -> None:
        add_nvidia_dll_dirs()
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        if device == "auto":
            device = "cuda" if gpu_available() else "cpu"
        options = ort.SessionOptions()
        options.log_severity_level = 3
        # Every sentence has a new length. Measured on an RTX 3060 Ti with mixed-length sentences: about
        # 0.33 s per sentence with cuDNN algorithm search "HEURISTIC", 0.35 s with the exhaustive search
        # onnxruntime uses unless told otherwise (CPU: about 1.1 s). "DEFAULT" measured 0.32 s but made one
        # convolution drop to a slow fallback path on long sentences, so it is not used.
        providers = ([("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}), "CPUExecutionProvider"]
                     if device == "cuda" else ["CPUExecutionProvider"])
        session = ort.InferenceSession(str(model or model_file("kokoro-v1.0.onnx")), sess_options=options,
                                       providers=providers)
        self.device = "cuda" if session.get_providers()[0].startswith("CUDA") else "cpu"
        self._kokoro = Kokoro.from_session(session, str(voices or model_file("voices-v1.0.bin")))
        self._lock = threading.Lock()
        self.speed, self.lang = speed, lang
        self.gap_ms = gap_ms                  # silence after each sentence (commanding voices: a deliberate pace)
        self.pitch_semitones = pitch_semitones   # whole-voice pitch change; see pitch_ratio
        self.set_voice(voice)

    def set_voice(self, voice: str) -> None:
        recipe = parse_kokoro_voice(voice)
        self._style = sum(self._kokoro.get_voice_style(name) * weight for name, weight in recipe)
        self.voice = voice

    def warm_up(self) -> None:
        for text in ("Hello.", "Okay, I hear you, love."):
            for _ in self.synthesize(text):
                pass

    def synthesize(self, text: str, prosody=None) -> Iterable[tuple[bytes, int]]:
        """`prosody` (star.emotion.Prosody) shifts this one sentence a little: speed times rate, semitones added to the
        voice's pitch, milliseconds added to the pause after it. None leaves the voice exactly as configured."""
        speed, pitch, gap_ms = self.speed, self.pitch_semitones, self.gap_ms
        if prosody is not None:
            speed = speed * prosody.rate
            pitch = min(12.0, max(-12.0, pitch + prosody.pitch_semitones))
            gap_ms = max(0, gap_ms + int(prosody.pause_ms))
        ratio = pitch_ratio(pitch)
        with self._lock:
            # A pitch change is a resample (playing the clip back faster or slower), which also changes its length;
            # asking Kokoro for a speed divided by the same ratio makes the final pace the speed that was asked for.
            samples, rate = self._kokoro.create(text, voice=self._style, speed=min(2.0, max(0.5, speed / ratio)),
                                                lang=self.lang)
        if ratio != 1.0:
            samples = resample(samples, int(rate), int(round(rate / ratio)))
        yield float_to_pcm16(samples), int(rate)
        if gap_ms > 0:
            yield b"\x00\x00" * int(int(rate) * gap_ms / 1000), int(rate)


# -- registries -------------------------------------------------------------------------------
def make_vad(name: str = "silero"):
    if name == "silero":
        return SileroVAD()
    if name == "energy":
        return EnergyVAD()
    raise ValueError(f"Unknown voice activity detector: {name}")


def make_endpointer(name: str = "smart-turn"):
    if name in {"", "none", "silence"}:
        return None
    if name == "smart-turn":
        return SmartTurnEndpointer()
    raise ValueError(f"Unknown end-of-turn model: {name}")


def make_asr(name: str = "faster-whisper", model: str = "", device: str = "auto", prompt: str = ""):
    if name == "faster-whisper":
        return FasterWhisperASR(model or "auto", device=device, prompt=prompt)
    raise ValueError(f"Unknown speech-to-text engine: {name}")


def make_tts(name: str = "kokoro", voice: str = "", speed: float = 0.92, device: str = "auto", lang: str = "en-us",
             gap_ms: int = 0, pitch_semitones: float = 0.0):
    if name == "kokoro":
        return KokoroTTS(voice or "heart", speed=speed, device=device, lang=lang, gap_ms=gap_ms,
                         pitch_semitones=pitch_semitones)
    raise ValueError(f"Unknown text-to-speech engine: {name}")
