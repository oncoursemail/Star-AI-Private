"""File-driven calls: run the whole call pipeline without a person, a microphone or a loudspeaker.

A scenario is a list of steps played against the wall clock, exactly as a caller would:

    {"steps": [
        {"say": "q1.wav"},                              the "user" speaks a recorded/synthesised question
        {"wait": "reply_done"},                         silence until Star has finished answering
        {"say": "q2.wav"},
        {"wait": "speaking", "then_seconds": 1.5},      wait until Star is audibly talking, then 1.5 s more
        {"say": "interrupt.wav"},                       ...and talk over her (barge-in test)
        {"say": "q3.wav", "ptt": false},                push-to-talk calls: speak without holding the key
        {"wait": "reply_done"}
    ]}

The virtual microphone feeds 32 ms frames in real time. The virtual speaker "plays" in real time too and
records what was audible, so an interruption cuts the recording where a listener would have heard it cut.
With echo_db set, the speaker's sound is mixed back into the microphone to imitate loudspeakers without
headphones (a simulation: no real room, no real device delay).

Pure Python (wave + array), so the runner itself is covered by unit tests with fake engines.
"""
from __future__ import annotations

import array
import json
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .call import CallSession
from .metrics import latency_table
from .pcm import FRAME_BYTES, FRAME_SAMPLES, SAMPLE_RATE, frames, rms, samples
from .turn import TurnDetector


def read_wav(path: str | Path) -> tuple[bytes, int]:
    """Read a PCM16 WAV as mono bytes."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"{path}: only 16-bit PCM WAV files are supported")
        rate, channels = handle.getframerate(), handle.getnchannels()
        data = handle.readframes(handle.getnframes())
    if channels > 1:
        mono = samples(data)[::channels]
        if sys.byteorder == "big":
            mono.byteswap()
        data = mono.tobytes()
    return data, rate


def write_wav(path: str | Path, pcm: bytes, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def nearest_resample(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """Crude nearest-sample rate change. Good enough for the echo simulation, not for listening."""
    if source_rate == target_rate or not pcm:
        return pcm
    data = samples(pcm)
    count = int(len(data) * target_rate / source_rate)
    step = source_rate / target_rate
    out = array.array("h", (data[min(len(data) - 1, int(i * step))] for i in range(count)))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


class VirtualSpeaker:
    """A loudspeaker that exists only on the clock: real-time playback, interruption, and a recording."""

    LEVEL_WINDOW = 0.032          # the loudness of the played audio is kept per 32 ms slice
    LEVEL_HOLD = 0.4              # level() reports the loudest slice of the last 0.4 s

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._segments: list[list] = []          # [start_time, pcm, sample_rate, loudness per slice]
        self._queue_end = 0.0
        self._queued = 0.0
        self.sample_rate = 0

    # -- Speaker interface --------------------------------------------------------------------
    def play(self, pcm: bytes, sample_rate: int) -> None:
        with self._lock:
            now = self.clock()
            start = max(now, self._queue_end)
            duration = len(pcm) / 2 / sample_rate
            step = int(self.LEVEL_WINDOW * sample_rate) * 2
            self._segments.append([start, pcm, sample_rate, [rms(pcm[i:i + step]) for i in range(0, len(pcm), step)]])
            self._queue_end = start + duration
            self._queued += duration
            self.sample_rate = sample_rate

    def stop(self) -> None:
        with self._lock:
            now = self.clock()
            self._queued -= max(0.0, self._queue_end - now)
            kept = []
            for start, pcm, rate, level in self._segments:
                if start >= now:
                    continue                                   # never started: drop
                heard = int((now - start) * rate) * 2
                kept.append([start, pcm[:heard] if heard < len(pcm) else pcm, rate, level])
            self._segments = kept
            self._queue_end = now

    def reset(self) -> None:
        with self._lock:
            self._queued = 0.0
            self._queue_end = max(self._queue_end, self.clock())

    def pending_seconds(self) -> float:
        with self._lock:
            return max(0.0, self._queue_end - self.clock())

    def played_seconds(self) -> float:
        with self._lock:
            return self._queued - max(0.0, self._queue_end - self.clock())

    def level(self) -> float:
        """Loudest 32 ms slice that was audible during the last 0.4 s (peak-held, for the echo gate)."""
        with self._lock:
            now = self.clock()
            best = 0.0
            for start, pcm, rate, levels in reversed(self._segments):
                heard_until = start + len(pcm) / 2 / rate          # stop() shortens pcm to what was heard
                if heard_until < now - self.LEVEL_HOLD:
                    break
                first = max(0, int((now - self.LEVEL_HOLD - start) / self.LEVEL_WINDOW))
                last = min(len(levels), int((min(now, heard_until) - start) / self.LEVEL_WINDOW) + 1)
                if last > first:
                    best = max(best, max(levels[first:last]))
            return best

    # -- test helpers -------------------------------------------------------------------------
    def audible(self, now: float, seconds: float, sample_rate: int) -> bytes:
        """What a microphone next to the speaker would have picked up during the last `seconds`."""
        want = int(seconds * sample_rate)
        begin = now - seconds
        with self._lock:
            for start, pcm, rate, _level in reversed(self._segments):
                if start <= begin < start + len(pcm) / 2 / rate:
                    offset = int((begin - start) * rate) * 2
                    piece = pcm[offset: offset + int(seconds * rate) * 2]
                    out = nearest_resample(piece, rate, sample_rate)
                    return out[: want * 2].ljust(want * 2, b"\x00")
        return b"\x00\x00" * want

    def recording(self, origin: float) -> tuple[bytes, int]:
        """Everything that was audible since `origin`, with real gaps, as one PCM16 track."""
        with self._lock:
            segments = [s for s in self._segments if s[1]]
            if not segments:
                return b"", self.sample_rate or 24000
            rate = segments[0][2]
            track = bytearray()
            for start, pcm, seg_rate, _level in segments:
                if seg_rate != rate:
                    pcm = nearest_resample(pcm, seg_rate, rate)
                offset = max(0, int((start - origin) * rate)) * 2
                if offset > len(track):
                    track.extend(b"\x00" * (offset - len(track)))
                track[offset:offset + len(pcm)] = pcm
            return bytes(track), rate


def mix(frame: bytes, echo: bytes, gain: float) -> bytes:
    """Add an attenuated echo to a microphone frame, with clipping."""
    a, b = samples(frame), samples(echo)
    out = array.array("h", (max(-32768, min(32767, int(x + gain * y))) for x, y in zip(a, b)))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


@dataclass
class FileCallResult:
    turns: list = field(default_factory=list)            # TurnMetrics
    events: list = field(default_factory=list)           # (seconds since start, event) without level events
    said: list = field(default_factory=list)             # (file, seconds when its last frame was fed)
    user_audio: bytes = b""                              # what the microphone "heard", 16 kHz
    star_audio: bytes = b""                              # what the speaker "played"
    star_rate: int = 24000
    timed_out: bool = False

    def table(self) -> str:
        return latency_table(self.turns)

    def save(self, out_dir: str | Path) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        write_wav(out / "user.wav", self.user_audio, SAMPLE_RATE)
        write_wav(out / "star.wav", self.star_audio, self.star_rate)
        (out / "latency.txt").write_text(self.table() + "\n", encoding="utf-8")
        (out / "turns.json").write_text(json.dumps({
            "turns": [m.to_dict() for m in self.turns],
            "said": [{"file": name, "ended_at": round(at, 3)} for name, at in self.said],
            "events": [{"t": round(at, 3), **event} for at, event in self.events],
            "timed_out": self.timed_out,
        }, indent=1), encoding="utf-8")


class FileCall:
    """Runs a scenario against a CallSession built by `make_session(speaker, on_event)`."""

    def __init__(self, make_session: Callable[[VirtualSpeaker, Callable[[dict], None]], CallSession], *,
                 echo_db: float | None = None, echo_delay: float = 0.08, realtime: bool = True,
                 step_timeout: float = 90.0, base_dir: str | Path = ".") -> None:
        self.speaker = VirtualSpeaker()
        self.result = FileCallResult()
        self._origin = 0.0
        self.session = make_session(self.speaker, self._on_event)
        self.echo_gain = None if echo_db is None else 10 ** (echo_db / 20.0)
        self.echo_delay = echo_delay          # the microphone hears the speaker this much later (device + room)
        self.realtime = realtime
        self.step_timeout = step_timeout
        self.base_dir = Path(base_dir)
        self._mic = bytearray()
        self._fed = 0

    def _on_event(self, event: dict) -> None:
        if event.get("type") != "level":
            self.result.events.append((time.monotonic() - self._origin, dict(event)))

    def _feed(self, frame: bytes) -> None:
        if self.realtime:                                   # keep to the wall clock like a real microphone
            due = self._origin + self._fed * FRAME_SAMPLES / SAMPLE_RATE
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        self._fed += 1
        if self.echo_gain:
            echo = self.speaker.audible(time.monotonic() - self.echo_delay, FRAME_SAMPLES / SAMPLE_RATE,
                                        SAMPLE_RATE)
            frame = mix(frame, echo, self.echo_gain)
        self._mic.extend(frame)
        self.session.feed(frame)

    def _silence_until(self, condition: Callable[[], bool], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        quiet = b"\x00" * FRAME_BYTES
        while time.monotonic() < deadline:
            if condition():
                return True
            self._feed(quiet)
        self.result.timed_out = True
        return False

    def _silence_for(self, seconds: float) -> None:
        quiet = b"\x00" * FRAME_BYTES
        for _ in range(max(0, round(seconds * SAMPLE_RATE / FRAME_SAMPLES))):
            self._feed(quiet)

    def run(self, scenario: dict) -> FileCallResult:
        session = self.session
        self._origin = time.monotonic()
        session.start()
        try:
            self._silence_for(0.3)                                        # a moment of room tone first
            for step in scenario["steps"]:
                if "say" in step:
                    pcm, rate = read_wav(self.base_dir / step["say"])
                    if rate != SAMPLE_RATE:
                        pcm = nearest_resample(pcm, rate, SAMPLE_RATE)
                    # Push-to-talk calls: the pretend caller holds the key for the whole file and lets go after
                    # its last frame ("ptt": false = talk without the key, e.g. talking over Star).
                    ptt = getattr(session.config, "push_to_talk", False) and step.get("ptt", True)
                    if ptt:
                        session.push_to_talk(True)
                    for frame in frames(pcm):
                        self._feed(frame)
                    if ptt:
                        session.push_to_talk(False)
                    self.result.said.append((step["say"], time.monotonic() - self._origin))
                elif step.get("wait") == "reply_done":
                    done_before = len(session.turns)
                    # The caller's own words must be fully heard too (turn detector idle): a barge-in finishes the
                    # interrupted reply while the interrupter is still talking, which is not "the reply is done".
                    self._silence_until(
                        lambda: len(session.turns) > done_before and not session.busy()
                        and self.speaker.pending_seconds() == 0
                        and session.detector.state == TurnDetector.IDLE, float(step.get("timeout", self.step_timeout)))
                    self._silence_for(float(step.get("then_seconds", 0.4)))
                elif step.get("wait") == "speaking":
                    self._silence_until(lambda: session.state == "speaking",
                                        float(step.get("timeout", self.step_timeout)))
                    self._silence_for(float(step.get("then_seconds", 1.0)))
                elif "pause" in step:
                    self._silence_for(float(step["pause"]))
                else:
                    raise ValueError(f"Unknown scenario step: {step}")
            session.wait_idle(self.step_timeout)
        finally:
            session.stop()
        self.result.turns = list(session.turns)
        self.result.user_audio = bytes(self._mic)
        self.result.star_audio, self.result.star_rate = self.speaker.recording(self._origin)
        return self.result
