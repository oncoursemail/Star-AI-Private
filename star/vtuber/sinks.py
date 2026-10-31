"""Frame sinks: where the rendered RGB frames go. The virtual camera is the real one; the others are for tests."""
from __future__ import annotations

from pathlib import Path

import numpy as np

CAMERA_NAME = "STAR Camera"


class SinkError(RuntimeError):
    pass


class PyVirtualCamSink:
    """A Windows virtual camera through pyvirtualcam (https://github.com/letmaik/pyvirtualcam).

    backend "unitycapture" (the default here): the DirectShow filter registered under the name "STAR Camera" by
      installer/star-camera/install-camera.cmd, so Discord and games list a camera called exactly that.
    backend "obs": OBS's own virtual camera. Its name is fixed ("OBS Virtual Camera"), so it is a fallback, and OBS
      must have started it first.
    Needs `pip install pyvirtualcam`; the import is lazy so nothing else in STAR depends on it.
    """

    def __init__(self, width: int = 1280, height: int = 720, fps: float = 30, *, name: str = CAMERA_NAME,
                 backend: str | None = "unitycapture", pyvirtualcam=None) -> None:
        if pyvirtualcam is None:
            try:
                import pyvirtualcam
            except ImportError as exc:
                raise SinkError("pyvirtualcam is not installed (pip install pyvirtualcam)") from exc
        kwargs = {"fmt": pyvirtualcam.PixelFormat.RGB}
        if backend:
            kwargs["backend"] = backend
        if backend == "unitycapture":
            kwargs["device"] = name
        try:
            self._cam = pyvirtualcam.Camera(width=width, height=height, fps=fps, **kwargs)
        except Exception as exc:     # RuntimeError from pyvirtualcam: driver missing, name not registered, device busy
            raise SinkError(f"no virtual camera named {name!r} ({backend or 'any backend'}): {exc}") from exc
        self.device = getattr(self._cam, "device", name)
        self.size = (width, height)

    def send(self, frame: np.ndarray) -> None:
        self._cam.send(frame)

    def close(self) -> None:
        try:
            self._cam.close()
        except Exception:
            pass


class MemorySink:
    """Keeps the last frames in memory (tests, previews)."""

    def __init__(self, keep: int = 0) -> None:
        self.keep, self.frames, self.count, self.closed = keep, [], 0, False

    def send(self, frame: np.ndarray) -> None:
        self.count += 1
        self.last = frame
        if self.keep:
            self.frames.append(frame.copy())
            del self.frames[:-self.keep]

    def close(self) -> None:
        self.closed = True


class PngSink:
    """Writes every n-th frame as frame_00000.png (the sample clip)."""

    def __init__(self, folder: str | Path, every: int = 1) -> None:
        self.folder, self.every, self.count = Path(folder), max(1, every), 0
        self.folder.mkdir(parents=True, exist_ok=True)

    def send(self, frame: np.ndarray) -> None:
        if self.count % self.every == 0:
            from PIL import Image
            Image.fromarray(frame).save(self.folder / f"frame_{self.count // self.every:05d}.png")
        self.count += 1

    def close(self) -> None:
        pass
