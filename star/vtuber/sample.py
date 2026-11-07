"""Offline sample: the avatar lip-syncing to a spoken sentence, rendered in virtual time to PNG frames + a GIF.

No camera device, no audio device and no GPU. The sentence is spoken by Windows' own built-in voice (System.Speech,
a few hundred ms of CPU) unless a WAV is given; it goes through the same Analyzer -> Timeline -> LiveRig -> model path as
the live camera, with a fake clock so the result is the same on any PC.
"""
from __future__ import annotations

import collections
import subprocess
import wave
from pathlib import Path

import numpy as np

from .camera import StarCamera
from .lipsync import Analyzer, LocalFeed, Timeline
from .model import load_model
from .rig import LiveRig
from .sinks import PngSink

SENTENCE = "Hi, I'm Star. It's so nice to see you! Do you want to play something together?"


def speak_to_wav(text: str, path: Path) -> bool:
    """Windows' System.Speech to a WAV file; False when it is not available (not Windows, voices removed)."""
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text.replace(chr(39), chr(39) * 2)}'); $s.Dispose()")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and path.is_file() and path.stat().st_size > 1000


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("a 16-bit PCM WAV is needed")
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def render_sample(out: str | Path, *, model_source: str = "placeholder", wav: str | Path | None = None,
                  fps: int = 15, text: str = SENTENCE, events: tuple = ((1.0, "video_funny"),)) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    wav_path = Path(wav) if wav else out / "sentence.wav"
    if wav is None and not speak_to_wav(text, wav_path):
        return {"rendered": False, "why": "no speech WAV given and Windows speech is not available here"}
    samples, rate = read_wav(wav_path)
    duration = len(samples) / rate
    seconds = duration + 0.8                                   # a beat of silence after the sentence

    clock = [0.0]
    timeline = Timeline(lambda: clock[0])
    LocalFeed(timeline).push(Analyzer().push(samples, rate), 0.0)   # audible from t = 0
    model = load_model(model_source)
    sink = PngSink(out / "frames")
    camera = StarCamera(model, [sink], timeline=timeline, rig=LiveRig(), fps=float(fps), clock=lambda: clock[0],
                        adaptive=False)
    seen: collections.Counter = collections.Counter()
    pending = list(events)
    for index in range(int(seconds * fps)):
        clock[0] = index / fps
        while pending and pending[0][0] <= clock[0]:
            camera.rig.react(pending.pop(0)[1], 1.0, now=clock[0])
        pose = camera.tick(clock[0])
        seen[pose.viseme] += 1
    frames = sorted((out / "frames").glob("frame_*.png"))
    from PIL import Image
    images = [Image.open(f).convert("P", palette=Image.Palette.ADAPTIVE, colors=128) for f in frames[::1]]
    gif = out / "sample.gif"
    images[0].save(gif, save_all=True, append_images=images[1:], duration=int(1000 / fps), loop=0)
    return {"rendered": True, "frames": len(frames), "seconds": round(seconds, 2), "fps": fps, "wav": str(wav_path),
            "gif": str(gif), "visemes": dict(seen), "model": model.name}
