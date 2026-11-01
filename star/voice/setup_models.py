"""Download the small model files voice calls need, from their official sources, with size and hash checks.

Run by `python -m star.voice setup`. Nothing here runs automatically: the owner starts it (or the demo
launcher does on first use). Files go to the folder in STAR_VOICE_MODELS (default
%LOCALAPPDATA%\\STAR\\voice-models). The speech-recognition model is fetched separately by faster-whisper
from Hugging Face the first time it is used.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .engines import models_dir


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    size: int
    sha256: str
    what: str


MODEL_FILES = (
    ModelFile("kokoro-v1.0.onnx",
              "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
              325532387, "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
              "Kokoro-82M voice model (Apache-2.0)"),
    ModelFile("voices-v1.0.bin",
              "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
              28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
              "Kokoro stock voices (Apache-2.0)"),
    ModelFile("silero_vad.onnx",
              "https://github.com/snakers4/silero-vad/raw/v6.0/src/silero_vad/data/silero_vad.onnx",
              2327524, "597d30b3ec076608d059477bb14cfeffdf951bf5cae370d38f65d33bbfe82004",
              "Silero VAD v6 voice activity detector (MIT)"),
    ModelFile("smart-turn-v3.2-cpu.onnx",
              "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx",
              8679182, "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
              "Pipecat Smart Turn v3.2 end-of-turn model (BSD-2-Clause)"),
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_ready(item: ModelFile, folder: Path) -> bool:
    path = folder / item.name
    return path.is_file() and path.stat().st_size == item.size


def missing(folder: Path | None = None, files: tuple | list | None = None) -> list[ModelFile]:
    folder = folder or models_dir()
    return [item for item in (MODEL_FILES if files is None else files) if not is_ready(item, folder)]


def download(folder: Path | None = None, report: Callable[[str], None] = print, opener=None,
             files: tuple | list | None = None) -> list[str]:
    """Fetch whatever is missing. A file only gets its final name after size and SHA-256 both match."""
    import httpx
    folder = folder or models_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fetched = []
    for item in missing(folder, files):
        report(f"Downloading {item.name} ({item.size / 1e6:.0f} MB): {item.what}")
        partial = folder / (item.name + ".part")
        with (opener or httpx.stream)("GET", item.url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for block in response.iter_bytes(1 << 20):
                    handle.write(block)
        if partial.stat().st_size != item.size or sha256_of(partial) != item.sha256:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"{item.name} did not match the expected size or SHA-256; nothing was installed")
        os.replace(partial, folder / item.name)
        fetched.append(item.name)
    report(f"Voice models ready in {folder}")
    return fetched
