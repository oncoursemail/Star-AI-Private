"""Renders the playback path with a jittery fake producer into WAV files and measures it: python -m star.senses.samples DIR

The signal is a synthetic voice-like tone sequence (a gliding harmonic source in five "sentences"), NOT Star's voice:
the point is to listen to and measure what the PlaybackBuffer does to audio that arrives late and in bursts. Each file
is the exact sample stream the sound card callback would have received. Metrics per file:
  max_step_ratio  largest sample-to-sample jump in the output divided by the largest jump in the source (1.0 = the
                  output is as smooth as the source; a click is far above 1)
  underruns       times the callback found the queue short; gaps_ms the silence of each one that later resumed
"""
from __future__ import annotations

import json
import random
import sys
import wave
from pathlib import Path

import numpy as np

from .audio import float_to_pcm
from .output import PlaybackBuffer

RATE = 24000


def voice_like(seconds: float, seed: int) -> np.ndarray:
    r = random.Random(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    f0 = 190 + 40 * np.sin(2 * np.pi * r.uniform(0.6, 1.3) * t) + 25 * t / seconds
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    x = sum(np.sin(h * phase) / h for h in range(1, 12))
    syllables = 0.55 + 0.45 * np.sin(2 * np.pi * r.uniform(3.0, 4.5) * t) ** 2
    edge = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)
    return (0.22 * x * syllables * edge).astype(np.float32)


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def render(streamed_chunk_ms: int, prefill_ms: int, jitter_ms: float, seed: int = 4) -> tuple[np.ndarray, np.ndarray, PlaybackBuffer]:
    """Five sentences; `streamed_chunk_ms` > 0 sends them in small chunks, 0 sends each whole. Chunks arrive up to
    jitter_ms late (in bursts: lateness is not cumulative)."""
    clock = _Clock()
    buffer = PlaybackBuffer(RATE, prefill_ms=prefill_ms, clock=clock)
    r = random.Random(seed)
    sentences = [voice_like(r.uniform(0.8, 1.6), 100 + i) for i in range(5)]
    source = np.concatenate(sentences)
    arrivals, ideal, last = [], 0.0, 0.0
    for sentence in sentences:
        step = int(RATE * streamed_chunk_ms / 1000) if streamed_chunk_ms else len(sentence)
        for k in range(0, len(sentence), step):
            chunk = sentence[k:k + step]
            last = max(last, ideal + r.uniform(0.0, jitter_ms / 1000))     # late, in bursts, but never out of order
            arrivals.append((last, chunk))
            ideal += len(chunk) / RATE
    out, now, i = [], 0.0, 0
    while now < ideal + 1.0:
        clock.t = now
        while i < len(arrivals) and arrivals[i][0] <= now:
            buffer.write(float_to_pcm(arrivals[i][1]), RATE)
            i += 1
        out.append(buffer.read(RATE // 100))
        now += 0.01
    return np.concatenate(out), source, buffer


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(float_to_pcm(x))


def main(argv: list[str] | None = None) -> int:
    folder = Path((argv or sys.argv[1:] or ["."])[0])
    folder.mkdir(parents=True, exist_ok=True)
    cases = {
        "streamed-20ms-chunks-prefill-80ms": (20, 80, 35.0),
        "streamed-20ms-chunks-no-prefill": (20, 0, 35.0),
        "whole-sentences-prefill-60ms": (0, 60, 250.0),
    }
    report = {}
    for name, (chunk, prefill, jitter) in cases.items():
        out, source, buffer = render(chunk, prefill, jitter)
        write_wav(folder / f"{name}.wav", out)
        step = lambda x: float(np.max(np.abs(np.diff(x))))
        report[name] = {"max_step_ratio": round(step(out) / step(source), 3), "underruns": buffer.underruns,
                        "gaps_ms": [round(g * 1000) for g in buffer.gaps], "joins_smoothed": buffer.joins_smoothed,
                        "seconds": round(len(out) / RATE, 2)}
    write_wav(folder / "source-first-sentence.wav", np.concatenate(
        [voice_like(random.Random(4).uniform(0.8, 1.6), 100)]))
    (folder / "glitch-metrics.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
