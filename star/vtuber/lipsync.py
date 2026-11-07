"""Lip-sync from her own voice: audio chunk -> 20 ms mouth frames (opening + five vowel shapes) on an audible-time line.

Heuristic, not phoneme recognition (no model, no GPU, ~0.1 ms per 20 ms hop in numpy):
  opening   from the RMS level (a noise floor below which the mouth is shut)
  vowel     from where the first formant sits (E 500-900 Hz over E 200-900 Hz: high = open "aa", middle "oh",
            low "ou") and how much second-formant energy there is (E 1500-2800 Hz: front vowels "ee"/"ih");
            a sibilant (more than 40 % of the energy above 4 kHz) gets a small "ih" so s/sh/f show teeth.
The five names are the VRM viseme set (A I U E O), so the same weights feed a layered 2D model or a VRM over VMC.

Timing is what makes it look right: every frame carries the moment it will be AUDIBLE (the time the speaker will
reach it), the camera reads the frame for "now", and a frame older than 110 ms counts as silence, so a stalled
audio path never keeps the mouth moving (same rule as star.stream_motion). The sender can be in another process:
UdpFeed ships (delay, frames) and the camera process stamps the arrival time itself, so no clock is shared.
"""
from __future__ import annotations

import collections
import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

HOP_S = 0.02
VISEMES = ("aa", "ih", "ou", "ee", "oh")
NOISE_FLOOR = 0.012                 # RMS (full scale 1.0) below which the mouth is closed
FULL_OPEN_RMS = 0.18                # RMS at which the mouth is fully open
STALE_S = 0.11
KEEP_S = 3.0
MAX_UDP_FRAMES = 50
DEFAULT_PORT = 39541


@dataclass(frozen=True)
class MouthFrame:
    """One 20 ms analysis hop. `shape` is five weights in VISEMES order; all zero when silent or closed."""
    open: float
    shape: tuple[float, float, float, float, float]

    @property
    def viseme(self) -> str:
        return VISEMES[max(range(5), key=lambda i: self.shape[i])] if self.open > 0.02 else "sil"


SILENT = MouthFrame(0.0, (0.0, 0.0, 0.0, 0.0, 0.0))


def _vowel_weights(f1_high: float, f2_high: float) -> tuple[float, float, float, float, float]:
    """Soft weights in VISEMES order (aa ih ou ee oh) from two band ratios.
    f1_high = E(500-900 Hz) / E(200-900 Hz): where the first formant sits (open vowels high, closed ones low)
    f2_high = E(1500-2800 Hz) / E(200-2800 Hz): how much second-formant energy there is (front vowels i, e)."""
    clamp = lambda v: max(0.0, min(1.0, v))      # noqa: E731
    front = clamp(f2_high / 0.08)
    ee_share = clamp(f2_high / 0.15)
    aa = clamp((f1_high - 0.5) / 0.4)
    oh = clamp(1.0 - abs(f1_high - 0.45) / 0.25) * (1.0 - front)
    ou = clamp((0.4 - f1_high) / 0.3) * (1.0 - front)
    ee, ih = front * ee_share, front * (1.0 - ee_share)
    raw = [aa, ih, ou, ee, oh]
    total = sum(raw)
    if total < 1e-6:
        return (0.0, 0.0, 0.0, 0.0, 1.0)          # nothing stands out: a relaxed, half-round mouth
    return tuple(v / total for v in raw)  # type: ignore[return-value]


class Analyzer:
    """Cuts float audio into 20 ms hops and gives one MouthFrame per hop. The spectrum is taken over the hop plus the one
    before it (40 ms, so a low voice still shows several pitch periods); the tail shorter than a hop is carried."""

    def __init__(self) -> None:
        self._carry = np.zeros(0, dtype=np.float32)
        self._prev: np.ndarray | None = None

    def reset(self) -> None:
        self._carry = np.zeros(0, dtype=np.float32)
        self._prev = None

    def push(self, samples: np.ndarray, rate: int) -> list[MouthFrame]:
        x = np.concatenate([self._carry, np.asarray(samples, dtype=np.float32).reshape(-1)])
        hop = max(1, int(rate * HOP_S))
        count = len(x) // hop
        self._carry = x[count * hop:]
        if not count:
            return []
        if self._prev is None or len(self._prev) != hop:
            self._prev = np.zeros(hop, dtype=np.float32)
        window = np.hanning(2 * hop).astype(np.float32)
        freqs = np.fft.rfftfreq(2 * hop, 1.0 / rate)
        band = lambda lo, hi: (freqs >= lo) & (freqs < hi)      # noqa: E731
        low, f1_hi, f2_band, all_band, sib = band(200, 900), band(500, 900), band(1500, 2800), band(200, 2800), freqs >= 4000
        out: list[MouthFrame] = []
        for i in range(count):
            block = x[i * hop:(i + 1) * hop]
            both = np.concatenate([self._prev, block])
            self._prev = block
            level = float(np.sqrt(np.mean(np.square(block), dtype=np.float64)))
            if level < NOISE_FLOOR:
                out.append(SILENT)
                continue
            power = np.square(np.abs(np.fft.rfft(both * window)))
            total = float(power.sum()) + 1e-12
            opening = min(1.0, (level - NOISE_FLOOR) / (FULL_OPEN_RMS - NOISE_FLOOR))
            if float(power[sib].sum()) / total > 0.40:
                out.append(MouthFrame(0.25 * opening, (0.0, 1.0, 0.0, 0.0, 0.0)))
                continue
            e = lambda m: float(power[m].sum()) + 1e-12         # noqa: E731
            out.append(MouthFrame(opening, _vowel_weights(e(f1_hi) / e(low), e(f2_band) / e(all_band))))
        return out


class Timeline:
    """Frames keyed by the monotonic time they become audible; `at(t)` is what the mouth should show at t."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._frames: collections.deque[tuple[float, MouthFrame]] = collections.deque()

    def push(self, frames: list[MouthFrame], audible_at: float) -> None:
        with self._lock:
            # a new chunk never starts before the end of the one before it (the speaker plays them in order)
            if self._frames:
                audible_at = max(audible_at, self._frames[-1][0] + HOP_S)
            for i, frame in enumerate(frames):
                self._frames.append((audible_at + i * HOP_S, frame))
            cutoff = self.clock() - KEEP_S
            while self._frames and self._frames[0][0] < cutoff:
                self._frames.popleft()

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    def at(self, t: float | None = None) -> MouthFrame:
        t = self.clock() if t is None else t
        with self._lock:
            best = None
            for stamp, frame in self._frames:      # frames are in time order; stop at the first one in the future
                if stamp > t:
                    break
                best = (stamp, frame)
        if best is None or t - best[0] > STALE_S:
            return SILENT
        return best[1]

    def pending_s(self, t: float | None = None) -> float:
        t = self.clock() if t is None else t
        with self._lock:
            return max(0.0, self._frames[-1][0] - t) if self._frames else 0.0


class LocalFeed:
    """Where the sender lives in the camera's own process: frames go straight into the Timeline."""

    def __init__(self, timeline: Timeline, on_event: Callable[[str, float], None] | None = None) -> None:
        self.timeline = timeline
        self.on_event = on_event or (lambda kind, strength: None)     # the camera sets this to rig.react

    def push(self, frames: list[MouthFrame], delay_s: float) -> None:
        self.timeline.push(frames, self.timeline.clock() + max(0.0, delay_s))

    def clear(self) -> None:
        self.timeline.clear()
        self.on_event("owner_interrupt", 1.0)

    def event(self, kind: str, strength: float = 1.0) -> None:
        self.on_event(kind, strength)


class UdpFeed:
    """The same interface from another process (the voice call): JSON datagrams to 127.0.0.1 only."""

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.addr = ("127.0.0.1", int(port))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _send(self, message: dict) -> None:
        try:
            self._sock.sendto(json.dumps(message, separators=(",", ":")).encode(), self.addr)
        except OSError:
            pass                                   # no camera listening: the voice must never notice

    def push(self, frames: list[MouthFrame], delay_s: float) -> None:
        for start in range(0, len(frames), MAX_UDP_FRAMES):
            part = frames[start:start + MAX_UDP_FRAMES]
            self._send({"t": "m", "d": round(max(0.0, delay_s) + start * HOP_S, 4),
                        "f": [[round(f.open, 3), *[round(v, 3) for v in f.shape]] for f in part]})

    def clear(self) -> None:
        self._send({"t": "c"})

    def event(self, kind: str, strength: float = 1.0) -> None:
        self._send({"t": "e", "k": str(kind)[:40], "s": round(float(strength), 3)})

    def close(self) -> None:
        self._sock.close()


def parse_datagram(data: bytes) -> tuple[str, object] | None:
    """('mouth', (delay, frames)) | ('clear', None) | ('event', (kind, strength)) | None for anything malformed."""
    try:
        msg = json.loads(data.decode("utf-8"))
        kind = msg["t"]
        if kind == "m":
            delay = float(msg["d"])
            rows = msg["f"]
            if not 0 <= delay <= 60 or not isinstance(rows, list) or len(rows) > MAX_UDP_FRAMES:
                return None
            frames = []
            for row in rows:
                if len(row) != 6 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in row):
                    return None
                frames.append(MouthFrame(float(row[0]), tuple(float(v) for v in row[1:])))  # type: ignore[arg-type]
            return "mouth", (delay, frames)
        if kind == "c":
            return "clear", None
        if kind == "e":
            strength = float(msg.get("s", 1.0))
            return "event", (str(msg["k"])[:40], min(1.0, max(0.0, strength)))
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        return None
    return None


class UdpListener(threading.Thread):
    """Receives UdpFeed datagrams in the camera process and applies them to a LocalFeed."""

    def __init__(self, feed: LocalFeed, port: int = DEFAULT_PORT) -> None:
        super().__init__(daemon=True, name="star-camera-feed")
        self.feed = feed
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", int(port)))
        self._sock.settimeout(0.25)
        self.port = self._sock.getsockname()[1]
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            parsed = parse_datagram(data)
            if parsed is None:
                continue
            kind, value = parsed
            if kind == "mouth":
                delay, frames = value  # type: ignore[misc]
                self.feed.push(frames, delay)
            elif kind == "clear":
                self.feed.clear()
            else:
                self.feed.on_event(*value)  # type: ignore[misc]

    def close(self) -> None:
        self._halt.set()
        self._sock.close()


class LipSyncSpeaker:
    """Wraps her Speaker (play/stop/reset/pending_seconds/played_seconds/level): the audio that is about to be played
    is analysed and queued on the camera's timeline for the moment the speaker will actually reach it."""

    def __init__(self, speaker, feed, *, analyzer: Analyzer | None = None) -> None:
        self._speaker = speaker
        self.feed = feed
        self.analyzer = analyzer or Analyzer()

    def play(self, pcm: bytes, sample_rate: int) -> None:
        delay = float(self._speaker.pending_seconds())            # before the write: when this chunk starts
        try:
            samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
            frames = self.analyzer.push(samples, int(sample_rate))
            if frames:
                self.feed.push(frames, delay)
        except Exception:                                          # lip-sync trouble must never silence her voice
            pass
        self._speaker.play(pcm, sample_rate)

    def stop(self) -> None:
        self._speaker.stop()
        self.analyzer.reset()
        self.feed.clear()

    def reset(self) -> None:
        self._speaker.reset()

    def __getattr__(self, name):          # pending_seconds, played_seconds, level and anything else the speaker has
        return getattr(self._speaker, name)
