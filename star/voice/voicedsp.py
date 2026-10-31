"""Signal processing for expressive speech: loudness, whisper, breathiness, pitch contour, ASMR, splicing.

numpy only (pyworld is optional: with it the pitch contour can be reshaped for styles, questions and emphasis;
without it those steps are skipped and everything else still works). Every function takes and returns float32 mono
in -1..1 plus the sample rate; `as_float`/`as_pcm` convert from and to the PCM16 bytes the voice pipeline carries.

Loudness follows ITU-R BS.1770 (K-weighting, 400 ms blocks, absolute and relative gates). The K-weighting filter is
applied in the frequency domain, which gives the same magnitude response as the standard biquads at any sample rate.
"""
from __future__ import annotations

import math

import numpy as np

TARGET_LUFS = -18.0          # speech loudness for calls, read-aloud and samples (all chunks land here)
PEAK_DB = -1.0
SILENCE_LUFS = -70.0


def as_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def as_pcm(samples) -> bytes:
    return (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-9))


# -- loudness -----------------------------------------------------------------------------------------------------
def _biquad_response(b, a, w):
    z = np.exp(-1j * w)
    return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)


def _k_response(sr: int, n: int) -> np.ndarray:
    """|H| of the BS.1770 K-weighting (high shelf + high pass) at the rfft bins of an n-point FFT."""
    w = 2 * np.pi * np.fft.rfftfreq(n, 1.0 / sr) / sr
    # stage 1: high shelf, f0 1681.97 Hz, gain 3.99984 dB, Q 0.7071752 (pyloudnorm's parameterisation)
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / sr)
    vh = 10 ** (g / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    b1 = [(vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a1 = [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]
    # stage 2: high pass, f0 38.1355 Hz, Q 0.5003270
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + k / q + k * k
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]
    return np.abs(_biquad_response(b1, a1, w) * _biquad_response(b2, a2, w))


def k_weighted(x: np.ndarray, sr: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return x
    n = int(2 ** math.ceil(math.log2(max(x.size, 2))))
    spectrum = np.fft.rfft(x, n) * _k_response(sr, n)
    return np.fft.irfft(spectrum, n)[:x.size].astype(np.float32)


def block_loudness(x: np.ndarray, sr: int, block: float = 0.4, overlap: float = 0.75) -> np.ndarray:
    """Momentary loudness (LUFS) of each 400 ms block."""
    y = k_weighted(x, sr)
    size = max(1, int(block * sr))
    hop = max(1, int(size * (1.0 - overlap)))
    if y.size < size:
        y = np.pad(y, (0, size - y.size))
    frames = np.lib.stride_tricks.sliding_window_view(y, size)[::hop]
    power = np.mean(frames.astype(np.float64) ** 2, axis=1)
    return -0.691 + 10.0 * np.log10(np.maximum(power, 1e-12))


def loudness(x: np.ndarray, sr: int) -> float:
    """Integrated loudness in LUFS (gated). Silence returns SILENCE_LUFS."""
    if np.asarray(x).size == 0:
        return SILENCE_LUFS
    blocks = block_loudness(x, sr)
    gated = blocks[blocks > -70.0]
    if gated.size == 0:
        return SILENCE_LUFS
    relative = 10.0 * np.log10(np.mean(10.0 ** (gated / 10.0))) - 10.0
    final = gated[gated > relative]
    if final.size == 0:
        return SILENCE_LUFS
    return float(10.0 * np.log10(np.mean(10.0 ** (final / 10.0))))


def peak_db(x: np.ndarray) -> float:
    x = np.asarray(x)
    return db(float(np.max(np.abs(x)))) if x.size else -120.0


def normalize(x: np.ndarray, sr: int, target: float = TARGET_LUFS, peak: float = PEAK_DB,
              max_gain_db: float = 30.0) -> np.ndarray:
    """Gain to `target` LUFS, then a peak ceiling: a whisper is raised, a shout lowered, nothing clips."""
    x = np.asarray(x, dtype=np.float32)
    level = loudness(x, sr)
    if level <= SILENCE_LUFS:
        return x
    gain = min(max_gain_db, target - level)
    y = x * (10 ** (gain / 20.0))
    return limit(y, peak)


def limit(x: np.ndarray, peak: float = PEAK_DB) -> np.ndarray:
    """Soft peak limiter: samples above the knee are bent smoothly towards the ceiling instead of clipped."""
    ceiling = 10 ** (peak / 20.0)
    x = np.asarray(x, dtype=np.float32)
    knee = 0.8 * ceiling
    over = np.abs(x) > knee
    if not np.any(over):
        return x
    y = x.copy()
    span = ceiling - knee
    y[over] = np.sign(x[over]) * (knee + span * np.tanh((np.abs(x[over]) - knee) / span))
    return y


def frame_db(x: np.ndarray, sr: int, frame: float = 0.05) -> np.ndarray:
    """RMS level of consecutive frames in dBFS."""
    size = max(1, int(frame * sr))
    n = (np.asarray(x).size // size) * size
    if n == 0:
        return np.array([db(float(np.sqrt(np.mean(np.square(x))))) if np.asarray(x).size else -120.0])
    frames = np.asarray(x[:n], dtype=np.float64).reshape(-1, size)
    return 20.0 * np.log10(np.maximum(np.sqrt(np.mean(frames ** 2, axis=1)), 1e-9))


def trim(x: np.ndarray, sr: int, threshold_db: float = -45.0, keep_ms: float = 30.0) -> np.ndarray:
    """Cut leading and trailing silence (quieter than threshold below the clip's peak), keeping a short margin."""
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return x
    levels = frame_db(x, sr, 0.01)
    loud = np.where(levels > max(levels.max() + threshold_db, -70.0))[0]
    if loud.size == 0:
        return x[:0]
    size = int(0.01 * sr)
    keep = int(keep_ms / 1000 * sr)
    return x[max(0, loud[0] * size - keep): min(x.size, (loud[-1] + 1) * size + keep)]


# -- spectral tools -----------------------------------------------------------------------------------------------
def _stft(x: np.ndarray, size: int, hop: int):
    window = np.hanning(size).astype(np.float32)
    pad = np.pad(np.asarray(x, dtype=np.float32), (size, size))
    count = 1 + (pad.size - size) // hop
    frames = np.lib.stride_tricks.sliding_window_view(pad, size)[::hop][:count]
    return np.fft.rfft(frames * window, axis=1), window


def _istft(spec: np.ndarray, window: np.ndarray, hop: int, length: int) -> np.ndarray:
    size = window.size
    frames = np.fft.irfft(spec, size, axis=1) * window
    out = np.zeros(hop * (frames.shape[0] - 1) + size, dtype=np.float64)
    norm = np.zeros_like(out)
    for i, frame in enumerate(frames):
        out[i * hop:i * hop + size] += frame
        norm[i * hop:i * hop + size] += window ** 2
    out = out / np.maximum(norm, 1e-6)
    return out[size:size + length].astype(np.float32)


def spectral_envelope(mag: np.ndarray, lifter: int = 30) -> np.ndarray:
    """Formant envelope of each frame's magnitude spectrum by cepstral smoothing (removes the pitch harmonics)."""
    log = np.log(np.maximum(mag, 1e-7))
    cep = np.fft.irfft(log, axis=1)
    cep[:, lifter:cep.shape[1] - lifter] = 0.0
    return np.exp(np.fft.rfft(cep, axis=1).real)


def whisper(x: np.ndarray, sr: int, seed: int = 0, tilt_hz: float = 500.0) -> np.ndarray:
    """Turn voiced speech into a whisper in the same voice: keep each frame's formant envelope and loudness, replace
    the voice source with noise (no pitch), and thin the low end the way a real whisper has little bass."""
    x = np.asarray(x, dtype=np.float32)
    if x.size < 256:
        return x * 0.0
    size = int(2 ** round(math.log2(0.032 * sr)))
    hop = size // 4
    spec, window = _stft(x, size, hop)
    env = spectral_envelope(np.abs(spec), lifter=max(12, int(0.0015 * sr)))
    rng = np.random.default_rng(seed)
    phase = np.exp(1j * rng.uniform(0, 2 * np.pi, size=spec.shape))
    freqs = np.fft.rfftfreq(size, 1.0 / sr)
    tilt = (freqs / (freqs + tilt_hz)) ** 1.5                       # gentle high-pass shape
    noise = env * tilt * phase
    # keep frame energy equal to the voiced frame so word rhythm is unchanged
    voiced_energy = np.sqrt(np.sum(np.abs(spec) ** 2, axis=1, keepdims=True))
    noise_energy = np.sqrt(np.sum(np.abs(noise) ** 2, axis=1, keepdims=True))
    noise *= voiced_energy / np.maximum(noise_energy, 1e-9)
    out = _istft(noise, window, hop, x.size)
    return out * 0.9


def shelf(x: np.ndarray, sr: int, gain_db: float, corner_hz: float, low: bool = True) -> np.ndarray:
    """Smooth low (or high) shelf in the frequency domain."""
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0 or abs(gain_db) < 0.01:
        return x
    n = int(2 ** math.ceil(math.log2(max(x.size, 2))))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    blend = 1.0 / (1.0 + (freqs / corner_hz) ** 2) if low else (freqs / corner_hz) ** 2 / (1.0 + (freqs / corner_hz) ** 2)
    gain = 10 ** (gain_db * blend / 20.0)
    return np.fft.irfft(np.fft.rfft(x, n) * gain, n)[:x.size].astype(np.float32)


def compress(x: np.ndarray, sr: int, threshold_db: float = -24.0, ratio: float = 3.0, window: float = 0.02) -> np.ndarray:
    """Gentle RMS compressor (smoothed gain per 20 ms), the "close and even" sound of ASMR."""
    x = np.asarray(x, dtype=np.float32)
    size = max(1, int(window * sr))
    n = int(math.ceil(x.size / size)) * size
    frames = np.pad(x, (0, n - x.size)).reshape(-1, size)
    level = 20 * np.log10(np.maximum(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)), 1e-9))
    over = np.maximum(0.0, level - threshold_db)
    gain_db = -over * (1.0 - 1.0 / ratio)
    for i in range(1, gain_db.size):                                   # smooth release
        gain_db[i] = min(gain_db[i], gain_db[i - 1] * 0.7 + gain_db[i] * 0.3) if gain_db[i] > gain_db[i - 1] else gain_db[i]
    gain = np.repeat(10 ** (gain_db / 20.0), size)[:x.size]
    return (x * gain).astype(np.float32)


def room_tone(seconds: float, sr: int, level_db: float = -62.0, seed: int = 0) -> np.ndarray:
    """Quiet, slightly dark noise at `level_db` dBFS RMS: fills spliced gaps so cuts never drop to digital silence."""
    n = max(0, int(seconds * sr))
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n).astype(np.float32)
    dark = shelf(white, sr, -9.0, 3000.0, low=False)
    rms = float(np.sqrt(np.mean(dark ** 2))) or 1.0
    return dark * (10 ** (level_db / 20.0) / rms)


def noise_floor_db(x: np.ndarray, sr: int) -> float:
    levels = frame_db(x, sr, 0.02)
    return float(np.percentile(levels, 10)) if levels.size else -120.0


def crossfade_concat(parts: list, sr: int, fade_ms: float = 8.0) -> np.ndarray:
    """Join clips with a short equal-power crossfade so splices never click."""
    parts = [np.asarray(p, dtype=np.float32) for p in parts if np.asarray(p).size]
    if not parts:
        return np.zeros(0, dtype=np.float32)
    out = parts[0]
    fade = int(fade_ms / 1000 * sr)
    for part in parts[1:]:
        f = min(fade, out.size // 2, part.size // 2)
        if f <= 1:
            out = np.concatenate([out, part])
            continue
        t = np.linspace(0, np.pi / 2, f, dtype=np.float32)
        mixed = out[-f:] * np.cos(t) + part[:f] * np.sin(t)
        out = np.concatenate([out[:-f], mixed, part[f:]])
    return out


def match_level(clip: np.ndarray, sr: int, reference_lufs: float, offset_db: float = 0.0) -> np.ndarray:
    """Set a spliced clip (a laugh, a sigh) to the loudness of the speech around it plus `offset_db`."""
    level = loudness(clip, sr)
    if level <= SILENCE_LUFS:
        rms = float(np.sqrt(np.mean(np.square(clip)))) if np.asarray(clip).size else 0.0
        if rms <= 0:
            return np.asarray(clip, dtype=np.float32)
        level = db(rms) - 0.7
    return limit(np.asarray(clip, dtype=np.float32) * 10 ** ((reference_lufs + offset_db - level) / 20.0))


def fade(x: np.ndarray, sr: int, in_ms: float = 5.0, out_ms: float = 15.0) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32).copy()
    a, b = min(x.size, int(in_ms / 1000 * sr)), min(x.size, int(out_ms / 1000 * sr))
    if a > 1:
        x[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if b > 1:
        x[-b:] *= np.linspace(1, 0, b, dtype=np.float32)
    return x


# -- pitch contour (pyworld) --------------------------------------------------------------------------------------
def have_world() -> bool:
    try:
        import pyworld  # noqa: F401
        return True
    except Exception:
        return False


def world_analyse(x: np.ndarray, sr: int, frame_ms: float = 5.0):
    import pyworld as pw
    d = np.asarray(x, dtype=np.float64)
    f0, t = pw.dio(d, sr, f0_floor=70.0, f0_ceil=700.0, frame_period=frame_ms)
    f0 = pw.stonemask(d, f0, t, sr)
    sp = pw.cheaptrick(d, f0, t, sr)
    ap = pw.d4c(d, f0, t, sr)
    return f0, sp, ap


def world_synth(f0, sp, ap, sr: int, frame_ms: float = 5.0) -> np.ndarray:
    import pyworld as pw
    return pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp), np.ascontiguousarray(ap), sr,
                         frame_ms).astype(np.float32)


def reshape_f0(f0: np.ndarray, *, shift_st: float = 0.0, range_scale: float = 1.0, melody_st: float = 0.0,
               rise_st: float = 0.0, emphasis: list | None = None, frame_ms: float = 5.0) -> np.ndarray:
    """New pitch contour: shift the mean, widen or flatten the movement around it, add a slow sing-song swing, a
    rising end (yes/no question), and a lift on emphasised spans ((start, end) as fractions of the clip)."""
    f0 = np.asarray(f0, dtype=np.float64).copy()
    voiced = f0 > 0
    if not np.any(voiced):
        return f0
    log = np.zeros_like(f0)
    log[voiced] = np.log2(f0[voiced])
    centre = float(np.median(log[voiced]))
    log[voiced] = centre + (log[voiced] - centre) * range_scale + shift_st / 12.0
    n = f0.size
    t = np.arange(n) * frame_ms / 1000.0
    if melody_st:
        log[voiced] += (melody_st / 12.0) * np.sin(2 * np.pi * t[voiced] / 1.6)
    if rise_st:
        idx = np.where(voiced)[0]
        tail = idx[idx >= idx[-1] - int(350 / frame_ms)]
        if tail.size > 1:
            ramp = np.linspace(0.0, rise_st / 12.0, tail.size) ** 1.0
            log[tail] += ramp
    for start, end in emphasis or ():
        a, b = int(start * n), max(int(start * n) + 1, int(end * n))
        span = np.zeros(n)
        span[a:b] = np.hanning(max(2, b - a))[: b - a]
        log[voiced] += (2.0 / 12.0) * span[voiced]
    out = np.zeros_like(f0)
    out[voiced] = 2.0 ** log[voiced]
    return out


def emphasis_spans(text: str, words: tuple) -> list:
    """Rough position of stressed words as fractions of the sentence, by character offset (no forced alignment)."""
    spans, low = [], text.lower()
    total = max(1, len(text))
    for word in words:
        at = low.find(word.lower())
        if at >= 0:
            spans.append((at / total, (at + len(word)) / total))
    return spans
