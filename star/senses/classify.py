"""A light "what is this audio?" for sound that is not (only) speech: silence, music, game sounds, steady noise.

Hand-made features on a 2 s window of 16 kHz mono audio, then a few rules. It is deliberately simple (no model, a
millisecond of numpy per call). The rules were tuned on synthetic music, game-effect and noise signals
(tests/test_senses_voice.py), not on recordings: expect "music" and "game sounds" to be right on clear cases and to
blur on mixed material (a game with a music bed reads as music). Speech is not detected here; the caller passes the
voice-activity share of the window.

Features
  level       RMS in dBFS
  active      share of 32 ms frames louder than 15 % of the loudest frame
  flatness    how noise-like the spectrum is (1 = white noise, near 0 = a few strong partials)
  tonal       share of spectral energy sitting in sharp peaks (notes, chords, tones)
  burstiness  crest factor of the frame-energy envelope (explosions and shots are bursty, music and noise are not)
  beat        strength of a regular pulse (autocorrelation of the spectral flux at 0.25 to 1 s)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .audio import RATE, rms

N_FFT, HOP = 1024, 512
LABELS = ("silence", "speech", "music", "game_sounds", "noise")


@dataclass
class AudioClass:
    label: str
    confidence: float
    level_db: float
    features: dict = field(default_factory=dict)


def _frames(x: np.ndarray) -> np.ndarray:
    if len(x) < N_FFT:
        x = np.pad(x, (0, N_FFT - len(x)))
    view = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::HOP]
    return view * np.hanning(N_FFT).astype(np.float32)


def features(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=np.float32)
    frames = _frames(x)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2 + 1e-12
    band = power[:, 6:384]                                   # about 100 Hz to 6 kHz
    energy = band.sum(axis=1)
    peak = float(energy.max())
    active = float(np.mean(energy > 0.15 * peak)) if peak > 1e-9 else 0.0
    loud = energy > 0.15 * peak
    sel = band[loud] if loud.any() else band
    flatness = float(np.mean(np.exp(np.mean(np.log(sel), axis=1)) / np.mean(sel, axis=1)))
    # sharp peaks: a bin that is the maximum of its +-6 neighbourhood and 8x above the local median
    padded = np.pad(sel, ((0, 0), (6, 6)), mode="edge")
    neigh = np.lib.stride_tricks.sliding_window_view(padded, 13, axis=1)
    is_peak = (sel >= neigh.max(axis=2)) & (sel > 8.0 * np.median(neigh, axis=2))
    tonal = float(np.mean((sel * is_peak).sum(axis=1) / sel.sum(axis=1)))
    env = np.sqrt(energy)
    burst = float(env.max() / (np.sqrt(np.mean(env ** 2)) + 1e-9))
    flux = np.maximum(0.0, np.diff(np.log(band + 1e-9), axis=0)).sum(axis=1)
    flux = flux - flux.mean()
    beat = 0.0
    lo, hi = int(0.25 * RATE / HOP), int(1.0 * RATE / HOP)
    if len(flux) > hi + 2 and float(np.dot(flux, flux)) > 1e-9:
        ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
        beat = float(np.max(ac[lo:hi + 1]) / ac[0])
    return {"active": active, "flatness": flatness, "tonal": tonal, "burstiness": burst, "beat": beat}


def classify(x: np.ndarray, speech_share: float = 0.0) -> AudioClass:
    """Label a window. `speech_share` is the fraction of it a voice-activity detector called speech."""
    x = np.asarray(x, dtype=np.float32)
    level = 20.0 * np.log10(max(rms(x), 1e-9))
    if level < -58.0:
        return AudioClass("silence", 1.0, level)
    f = features(x)
    if speech_share >= 0.4:
        return AudioClass("speech", min(1.0, speech_share), level, f)
    # sharp partials, or a spectrum so far from noise-like (flatness near 0) that it can only be sustained notes
    musical = f["active"] >= 0.8 and ((f["tonal"] >= 0.30 and f["flatness"] < 0.35) or f["flatness"] < 0.08)
    pulsed = f["beat"] >= 0.3
    if musical and (f["burstiness"] < 3.5 or pulsed):
        return AudioClass("music", min(1.0, 0.5 + f["tonal"]), level, f)
    if f["burstiness"] >= 3.0 or f["active"] < 0.65:
        return AudioClass("game_sounds", min(1.0, 0.4 + 0.1 * f["burstiness"]), level, f)
    if pulsed and f["tonal"] >= 0.15:
        return AudioClass("music", 0.5, level, f)
    return AudioClass("noise", min(1.0, 0.5 + f["flatness"]), level, f)
