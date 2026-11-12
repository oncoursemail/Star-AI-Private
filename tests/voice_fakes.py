"""Fake engines for voice-call tests: no audio stack, no model, no network."""
from __future__ import annotations

import threading
import time

from star.voice.pcm import FRAME_BYTES, samples
from star.voice.playback import PlaybackSnapshot

SILENCE = b"\x00\x00" * (FRAME_BYTES // 2)


def speech(utterance: int, frames: int) -> list[bytes]:
    """`frames` frames of fake speech. The sample value encodes which utterance it is."""
    return [int(utterance * 1000).to_bytes(2, "little", signed=True) * (FRAME_BYTES // 2)] * frames


def quiet(frames: int) -> list[bytes]:
    return [SILENCE] * frames


class FakeVAD:
    def probability(self, frame: bytes) -> float:
        return 0.97 if frame[:2] != b"\x00\x00" else 0.01


class FakeASR:
    """Looks up the text for each utterance id found in the audio, in order of first appearance."""

    def __init__(self, texts: dict[int, str], delay: float = 0.0):
        self.texts, self.delay, self.calls = dict(texts), delay, 0

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        seen = []
        for value in samples(pcm)[::256]:
            uid = value // 1000
            if uid and uid not in seen:
                seen.append(uid)
        return " ".join(self.texts[u] for u in seen)


class FakeStream:
    def __init__(self, pieces, first_delay, delay, fail_after=None):
        self.pieces, self.first_delay, self.delay, self.fail_after = list(pieces), first_delay, delay, fail_after
        self.closed = threading.Event()
        self.sent = 0

    def __iter__(self):
        return self

    def __next__(self):
        wait = self.first_delay if self.sent == 0 else self.delay
        if self.closed.wait(wait) or self.sent >= len(self.pieces):
            raise StopIteration
        if self.fail_after is not None and self.sent >= self.fail_after:
            raise RuntimeError("The STAR Server did not answer in time.")
        piece = self.pieces[self.sent]
        self.sent += 1
        return piece

    def close(self):
        self.closed.set()


class FakeBrain:
    """Replies with scripted text, one word per token. Records the messages of every request."""

    def __init__(self, replies: list[str], first_delay: float = 0.0, delay: float = 0.0, fail_after=None):
        self.replies, self.first_delay, self.delay, self.fail_after = list(replies), first_delay, delay, fail_after
        self.requests: list[list[dict]] = []
        self.streams: list[FakeStream] = []

    def stream(self, messages):
        self.requests.append([dict(m) for m in messages])
        text = self.replies[min(len(self.requests), len(self.replies)) - 1]
        words = text.split(" ")
        pieces = [w if i == 0 else " " + w for i, w in enumerate(words)]
        stream = FakeStream(pieces, self.first_delay, self.delay, self.fail_after)
        self.streams.append(stream)
        return stream


class FakeTTS:
    """`seconds_per_word` of audio per word at 16 kHz, in two chunks so streaming paths are exercised."""

    def __init__(self, seconds_per_word: float = 0.1, delay: float = 0.0, fail: bool = False):
        self.seconds_per_word, self.delay, self.fail = seconds_per_word, delay, fail
        self.spoken: list[str] = []

    def synthesize(self, text: str):
        if self.fail:
            raise RuntimeError("voice engine crashed")
        self.spoken.append(text)
        if self.delay:
            time.sleep(self.delay)
        total = int(len(text.split()) * self.seconds_per_word * 16000)
        half = total // 2
        yield b"\x05\x00" * half, 16000
        yield b"\x05\x00" * (total - half), 16000


class FakeSpeaker:
    """Plays in real time against the wall clock, like a sound card, and logs every call."""

    def __init__(self):
        self.lock = threading.Lock()
        self.log: list[tuple[str, float]] = []
        self.queued = 0.0
        self.queue_end = 0.0
        self.stops = 0
        self.first_playback_at: float | None = None

    def play(self, pcm: bytes, sample_rate: int) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.queue_end)
            duration = len(pcm) / 2 / sample_rate
            if pcm and self.first_playback_at is None:
                self.first_playback_at = start
            self.queue_end = start + duration
            self.queued += duration
            self.log.append(("play", now))

    def stop(self) -> None:
        with self.lock:
            now = time.monotonic()
            self.queued -= max(0.0, self.queue_end - now)
            self.queue_end = now
            self.stops += 1
            self.log.append(("stop", now))

    def reset(self) -> None:
        with self.lock:
            self.queued = 0.0
            self.queue_end = time.monotonic()
            self.first_playback_at = None

    def playback_snapshot(self) -> PlaybackSnapshot:
        with self.lock:
            return PlaybackSnapshot(self.first_playback_at, None, None)

    def pending_seconds(self) -> float:
        with self.lock:
            return max(0.0, self.queue_end - time.monotonic())

    def played_seconds(self) -> float:
        with self.lock:
            return self.queued - max(0.0, self.queue_end - time.monotonic())

    def level(self) -> float:
        return 0.1 if self.pending_seconds() > 0 else 0.0


class Events:
    def __init__(self):
        self.items: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, event: dict) -> None:
        with self.lock:
            self.items.append(event)

    def of(self, kind: str) -> list[dict]:
        with self.lock:
            return [e for e in self.items if e["type"] == kind]

    def states(self) -> list[str]:
        return [e["state"] for e in self.of("state")]


def wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False
