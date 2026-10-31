"""Neural expressive engines for star.voice.expressive (optional; need torch + requirements-voice-expressive.txt).

Kept outside star/voice on purpose: the STAR Home installer (requirements-home.txt) does not install these packages,
and on her 8 GB card the VRAM gate (star.senses.fastpath.expressive_allowed) only allows them with fast_profile "off".
star.voice works without this module: the live expressive path is Kokoro + DSP.

  QwenCloneTTS     Qwen3-TTS 12Hz 0.6B Base (Apache-2.0): clones Star's OWN voice from a reference clip (her designed
                   voice when its clip exists, else her Kokoro voice; no real person). Streams (first chunk ~0.6-1.2 s
                   on an RTX 3060 Ti). The Base model ignores style instructions. ~2.5 GB download.
  QwenDesignTTS    Qwen3-TTS 12Hz 1.7B VoiceDesign (Apache-2.0): a voice from a written description, for role-play
                   characters. ~4.5 GB download.
  StarDesignTTS    the same model speaking as Star: one of STAR_VOICES (description + seed; in VoiceDesign the seed is
                   part of the voice) plus the style's instruction, so the emotion comes from the model itself. The
                   only voices the owner rated above 2 in the v1 round were VoiceDesign voices.
  ChatterboxTurbo  Chatterbox-Turbo 350M (MIT, Resemble AI): v1's non-verbal bank builder. Its sounds were rated 1-2 by
                   the owner (2026-10-27) and are no longer used in speech. PerTh watermark on every output (kept).
  SpeakerEmbedder  Chatterbox's voice encoder (MIT, ve.safetensors only) for the guard's speaker-similarity check.

Licences were checked on the Hugging Face model cards and PyPI on 2026-10-26 (docs/agents/voice-expressive-20261026.md).
All engines expose synthesize_float(text, seed=0, instruct=None) -> (float32 samples, sample_rate).
"""
from __future__ import annotations

import threading
from pathlib import Path

QWEN_CLONE = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
QWEN_DESIGN = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
REFERENCE_TEXT = ("Hi sweetheart, it's Star. I'm right here with you, and we've got all the time we need. "
                  "Tell me about your day, slowly, from the very beginning.")
VRAM_GB = {"qwen3-tts": 2.9, "qwen3-design": 4.7, "chatterbox-turbo": 3.2}      # torch peak, RTX 3060 Ti

# Star's designed voices (v2 round, docs/agents/voice-v2-20261027.md): key -> (description, seed). The owner's
# ratings pick DEFAULT_STAR_VOICE; seeds were chosen so her speaking pitch lands in an adult woman's range.
STAR_ADULT = (" She is an adult woman, about twenty-six, speaking at a natural medium-low pitch like an ordinary adult "
              "woman; never squeaky, never high-pitched, not a child and not a cartoon. Clear American English.")
STAR_VOICES = {
    "a-warm-smile": ("A warm, friendly woman with a smile in her voice, natural and gently playful, relaxed pace.",
                    5),
    "b-soft-breathy": ("A soft, slightly breathy, intimate woman's voice, calm and affectionate, a little playful.",
                      1),
    "c-lively": ("A lively, cheerful woman's voice with natural energy, expressive and playful, quick but clear.",
                7),
    "d-velvet": ("A warm, velvety, honeyed woman's voice, calm, caring and confident, with a hint of playfulness.",
                1),
    "e-gentle-cute": ("A gentle, tender, cute woman's voice with a light, soft touch, warm and sweet.",
                     4),
    "g-cozy-husky": ("A slightly husky, cozy, warm woman's voice, soft and comforting, with a gentle playful edge.",
                    3),
    "i-radio-warm": ("A smooth, warm woman's voice like a late-night radio host, close, calm and kind, "
                     "a little playful.", 2),
    "j-girlfriend": ("An affectionate, warm woman's voice, natural and cosy, a playful grin, soft but confident.",
                    5),
}
DEFAULT_STAR_VOICE = "j-girlfriend"     # provisional: most stable adult pitch (212-259 Hz) of the 8; the owner picks


def _rope_compat() -> None:
    """qwen-tts-hf 0.1.1's RoPE shim reads config.rope_theta, which newer transformers 5.x configs (Mimi codec) keep
    only in config.rope_parameters. Read it from either place (needed with transformers 5.19, the version in
    requirements-home)."""
    try:
        from qwen_tts import _transformers_compat as compat
    except Exception:
        return
    if getattr(compat, "_star_patched", False):
        return
    original = compat._default_rope_parameters

    def default_rope(config, device=None, seq_len=None, layer_type=None):
        if getattr(config, "rope_theta", None) is None:
            params = getattr(config, "rope_parameters", None) or {}
            if layer_type and isinstance(params.get(layer_type), dict):
                params = params[layer_type]
            theta = params.get("rope_theta", 10000.0) if isinstance(params, dict) else 10000.0
            object.__setattr__(config, "rope_theta", theta)
        return original(config, device, seq_len, layer_type)
    compat._default_rope_parameters = default_rope
    try:
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
        if ROPE_INIT_FUNCTIONS.get("default") is original:
            ROPE_INIT_FUNCTIONS["default"] = default_rope
    except Exception:
        pass
    compat._star_patched = True


def _seed(seed: int) -> None:
    import torch
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))


def _to_float(wav):
    import numpy as np
    if isinstance(wav, (list, tuple)):
        wav = wav[0]
    if hasattr(wav, "detach"):
        wav = wav.detach().float().cpu().numpy()
    return np.asarray(wav, dtype=np.float32).reshape(-1)


def reference_clip(base, folder: Path) -> Path:
    """Her own voice saying REFERENCE_TEXT (rendered once by the base engine, ~9 s), the clip clones are made from."""
    from .voice.nonverbal import write_wav
    from .voice import voicedsp
    path = Path(folder) / "reference" / "star-voice.wav"
    if not path.is_file():
        samples, sr = base.synthesize_float(REFERENCE_TEXT)
        write_wav(path, voicedsp.normalize(samples, sr), sr)
    return path


class QwenCloneTTS:
    name = "qwen3-tts"
    follows_instruct = False        # Base model: instructions are ignored (v1 "whisper" came out 61 % voiced)

    def __init__(self, ref_audio: str | Path, ref_text: str = REFERENCE_TEXT, model: str = QWEN_CLONE,
                 device: str = "cuda", language: str = "English") -> None:
        import torch
        from faster_qwen3_tts import FasterQwen3TTS
        _rope_compat()
        self.model = FasterQwen3TTS.from_pretrained(model, device=device, dtype=torch.bfloat16)
        self.ref_audio, self.ref_text, self.language = str(ref_audio), ref_text, language
        self._lock = threading.Lock()
        self.reference_embedding = None

    def synthesize_float(self, text: str, seed: int = 0, instruct: str | None = None):
        with self._lock:
            _seed(seed)
            wavs, sr = self.model.generate_voice_clone(text=text, language=self.language, ref_audio=self.ref_audio,
                                                       ref_text=self.ref_text, instruct=instruct or None)
        return _to_float(wavs), int(sr)

    def stream(self, text: str, seed: int = 0, instruct: str | None = None, chunk_size: int = 8):
        """Yield (float chunk, rate) every ~chunk_size/12 s of audio as it is generated (first audio fastest)."""
        with self._lock:
            _seed(seed)
            for chunk, sr, _timing in self.model.generate_voice_clone_streaming(
                    text=text, language=self.language, ref_audio=self.ref_audio, ref_text=self.ref_text,
                    instruct=instruct or None, chunk_size=chunk_size):
                yield _to_float(chunk), int(sr)


class QwenDesignTTS:
    name = "qwen3-tts-design"
    follows_instruct = True

    def __init__(self, model: str = QWEN_DESIGN, device: str = "cuda", language: str = "English") -> None:
        import torch
        from faster_qwen3_tts import FasterQwen3TTS
        _rope_compat()
        self.model = FasterQwen3TTS.from_pretrained(model, device=device, dtype=torch.bfloat16)
        self.language = language
        self._lock = threading.Lock()

    def synthesize_float(self, text: str, seed: int = 0, instruct: str | None = None):
        with self._lock:
            _seed(seed)
            wavs, sr = self.model.generate_voice_design(text=text, instruct=instruct or "A warm adult woman's voice.",
                                                        language=self.language)
        return _to_float(wavs), int(sr)


class StarDesignTTS(QwenDesignTTS):
    """Star's own designed voice with the emotion from the model: description + the style instruction. A guard retry
    (seed 1, 2) moves the voice seed far away, so a retried sentence may sound a little different; the first take
    (seed 0) is always her chosen voice."""
    name = "qwen3-design"

    def __init__(self, voice: str = "", **kwargs) -> None:
        key = voice or DEFAULT_STAR_VOICE
        if key not in STAR_VOICES:
            raise ValueError(f"Unknown Star voice: {key!r}")
        self.voice, (self.description, self.voice_seed) = key, STAR_VOICES[key]
        super().__init__(**kwargs)

    def prompt(self, instruct: str | None = None) -> str:
        return self.description + STAR_ADULT + (" " + instruct if instruct else "")

    def synthesize_float(self, text: str, seed: int = 0, instruct: str | None = None):
        return super().synthesize_float(text, seed=self.voice_seed + 1000 * int(seed), instruct=self.prompt(instruct))

    def stream(self, text: str, seed: int = 0, instruct: str | None = None, chunk_size: int = 8):
        with self._lock:
            _seed(self.voice_seed + 1000 * int(seed))
            for chunk, sr, _timing in self.model.generate_voice_design_streaming(
                    text=text, instruct=self.prompt(instruct), language=self.language, chunk_size=chunk_size):
                yield _to_float(chunk), int(sr)


class ChatterboxTurbo:
    name = "chatterbox-turbo"

    def __init__(self, ref_audio: str | Path, device: str = "cuda") -> None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        from .voice import voicedsp
        from .voice.nonverbal import read_wav, write_wav
        self.model = ChatterboxTurboTTS.from_pretrained(device=device)
        # Chatterbox normalises the reference to -27 LUFS with pyloudnorm, whose 0.2 release returns float64 and breaks
        # the float32 tokenizer; hand it a clip already at -27 LUFS instead.
        x, sr = read_wav(ref_audio)
        quiet = Path(ref_audio).with_name(Path(ref_audio).stem + "-27lufs.wav")
        write_wav(quiet, voicedsp.normalize(x, sr, -27.0), sr)
        self.model.prepare_conditionals(str(quiet), norm_loudness=False)
        self._lock = threading.Lock()

    def synthesize_float(self, text: str, seed: int = 0, instruct: str | None = None):
        with self._lock:
            _seed(seed)
            wav = self.model.generate(text)
        return _to_float(wav), int(self.model.sr)


class SpeakerEmbedder:
    """Chatterbox's voice encoder (a speaker-verification network, MIT): embed(samples, rate) -> 256-d vector."""

    def __init__(self, device: str = "cpu") -> None:
        import torch
        from chatterbox.models.voice_encoder import VoiceEncoder
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        self.ve = VoiceEncoder()
        self.ve.load_state_dict(load_file(hf_hub_download("ResembleAI/chatterbox-turbo", "ve.safetensors")))
        self.ve.to(device).eval()
        self._torch = torch

    def embed(self, samples, rate: int):
        from .voice.engines import resample
        x = resample(samples, rate, 16000) if rate != 16000 else samples
        return self.ve.embeds_from_wavs([x], sample_rate=16000).mean(axis=0)


def designed_reference(root: Path, voice: str = "") -> tuple[Path, str] | None:
    """(clip, its words) of her designed voice when it was rendered (lab: <root>/reference/star-<key>.wav + .txt)."""
    key = voice or DEFAULT_STAR_VOICE
    clip = Path(root) / "reference" / f"star-{key}.wav"
    words = clip.with_suffix(".txt")
    return (clip, words.read_text(encoding="utf-8").strip()) if key and clip.is_file() and words.is_file() else None


def make_neural(name: str, root: Path, base, star_voice: str = ""):
    """The engine VoiceSettings.expressive_engine names. qwen3-tts clones her designed voice when its reference clip
    exists (else her Kokoro voice); qwen3-design speaks as her designed voice directly."""
    if name == "qwen3-tts":
        designed = designed_reference(root, star_voice)
        if designed:
            return QwenCloneTTS(designed[0], ref_text=designed[1])
        return QwenCloneTTS(reference_clip(base, root))
    if name == "qwen3-design":
        return StarDesignTTS(star_voice)
    raise ValueError(f"Unknown expressive engine: {name}")
