"""Real capture devices for the senses hub (Windows). Not exercised by the automated tests (they feed the hub
directly); needs `soundcard` for WASAPI loopback and `sounddevice` for the microphone (requirements-voice.txt).

LoopbackSource  everything the chosen output device plays, from any app (WASAPI loopback: games, music, Discord,
                a browser). By default the Windows default output; `device` picks one by name.
MicSource       a physical microphone (never the virtual "STAR Microphone": see routes.physical_microphone).

Both yield 512-sample, 16 kHz, mono PCM16 frames. WASAPI loopback delivers nothing while nothing is playing, so a
silent frame is produced whenever the device has been quiet for 40 ms: the stream's clock never stops, which the echo
canceller and the rolling buffer rely on.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Iterator

import numpy as np

from .audio import FRAME, RATE, Rechunker, StreamResampler


class LoopbackSource:
    def __init__(self, device: str = "", capture_rate: int = 48000, block: int = 960) -> None:
        try:
            import soundcard as sc
        except Exception as exc:
            raise RuntimeError("Hearing the PC's sound needs the 'soundcard' package: pip install soundcard") from exc
        speaker = next((s for s in sc.all_speakers() if device and device.lower() in s.name.lower()), None) \
            if device else sc.default_speaker()
        if speaker is None:
            raise RuntimeError(f'No output device matching "{device}" to listen to.')
        self.speaker_name = speaker.name
        self._mic = sc.get_microphone(speaker.id, include_loopback=True)
        self.rate, self.block = capture_rate, block
        self._blocks: queue.Queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read, name="star-loopback", daemon=True)

    def _read(self) -> None:
        try:
            with self._mic.recorder(samplerate=self.rate, channels=2, blocksize=self.block) as recorder:
                while not self._stop.is_set():
                    data = recorder.record(numframes=self.block)
                    try:
                        self._blocks.put_nowait(np.asarray(data, dtype=np.float32))
                    except queue.Full:
                        pass
        except Exception:
            self._stop.set()

    def frames(self) -> Iterator[bytes]:
        self._thread.start()
        resampler, chunker = StreamResampler(self.rate, 2), Rechunker()
        last = time.monotonic()
        while not self._stop.is_set():
            try:
                block = self._blocks.get(timeout=0.04)
                last = time.monotonic()
                samples = resampler.process(block)
            except queue.Empty:
                now = time.monotonic()
                samples = np.zeros(int((now - last) * RATE), dtype=np.float32)    # quiet device: keep the clock
                last = now
            yield from chunker.push(samples)

    def close(self) -> None:
        self._stop.set()


class MicSource:
    def __init__(self, device=None) -> None:
        from ..voice.devices import Microphone
        self._mic = Microphone(device)
        self._mic.__enter__()

    def frames(self) -> Iterator[bytes]:
        yield from self._mic

    def close(self) -> None:
        self._mic.close()


__all__ = ["LoopbackSource", "MicSource", "FRAME"]
