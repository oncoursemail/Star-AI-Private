"""End-to-end voice latency on fake engines with realistic delays: python -m star.senses.bench [--turns N] [--json F]

A scripted caller speaks into the real CallSession (real turn detector, real chunker, real threads, wall clock); only the
engines are fakes, each sleeping as long as the real one measured. The numbers show what the call logic itself adds
and removes (speculative reply, shorter pause, shorter first clause). They do NOT show model speed: that is the
`brain` row, set per arm, and the real models decide it.

Delays used (all from this project's own measurements, docs/STAR_VOICE_CALLS.md section 7):
  speech recognition   0.17 s per utterance (small.en on the GPU)
  text to speech       0.15 s + 0.03 s per word per sentence (about 0.33 s for a six-word sentence, Kokoro on the GPU)
  brain                local GPU model: first token 0.10 s, 70 tokens/s (estimate for a 4B Q4 on an RTX 4060)
                       scripted server brain: first token 0.9 s, 4.6 tokens/s (the figure used in section 7.1)
  end-of-turn model    answers "finished" at the pause (like Smart Turn after a full sentence)
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass

from ..voice.call import CallConfig, CallSession
from ..voice.metrics import latency_summary
from ..voice.pcm import FRAME_BYTES, FRAME_MS
from ..voice.turn import TurnConfig

REPLIES = ("Oh, nice one. That sounds like a fun idea, tell me more.",
           "Okay, I hear you. Let's take it one step at a time.",
           "Aw, that's lovely. What happened next?",
           "Hmm, good question. I think it depends on what you want.")
SPEECH = (b"\xe8\x03" * (FRAME_BYTES // 2))     # a voiced frame (value 1000)
SILENCE = b"\x00\x00" * (FRAME_BYTES // 2)


class _VAD:
    def probability(self, frame: bytes) -> float:
        return 0.97 if frame[:2] != b"\x00\x00" else 0.01


class _Endpointer:
    def complete_probability(self, pcm: bytes) -> float:
        return 0.9


class _ASR:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        time.sleep(self.delay)
        return "I made a little game today and I want to tell you about it"


class _Stream:
    def __init__(self, text: str, first: float, rate: float) -> None:
        words = text.split(" ")
        self.pieces = [w if i == 0 else " " + w for i, w in enumerate(words)]
        self.first, self.gap, self.i = first, 1.0 / rate, 0
        self.closed = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed.wait(self.first if self.i == 0 else self.gap) or self.i >= len(self.pieces):
            raise StopIteration
        self.i += 1
        return self.pieces[self.i - 1]

    def close(self) -> None:
        self.closed.set()


class _Brain:
    def __init__(self, first: float, rate: float) -> None:
        self.first, self.rate, self.n = first, rate, 0

    def stream(self, messages):
        self.n += 1
        return _Stream(REPLIES[self.n % len(REPLIES)], self.first, self.rate)


class _TTS:
    def synthesize(self, text: str):
        time.sleep(0.15 + 0.03 * len(text.split()))
        n = int(len(text.split()) * 0.3 * 16000)
        yield b"\x05\x00" * n, 16000


class _Speaker:
    def __init__(self) -> None:
        self.end = 0.0
        self.lock = threading.Lock()

    def play(self, pcm: bytes, rate: int) -> None:
        with self.lock:
            self.end = max(time.monotonic(), self.end) + len(pcm) / 2 / rate

    def stop(self) -> None:
        with self.lock:
            self.end = time.monotonic()

    def reset(self) -> None:
        pass

    def pending_seconds(self) -> float:
        return max(0.0, self.end - time.monotonic())

    def played_seconds(self) -> float:
        return 0.0

    def level(self) -> float:
        return 0.1 if self.pending_seconds() > 0 else 0.0


@dataclass
class Arm:
    name: str
    speculative: bool = False
    pause_ms: int = 256
    min_end_silence_ms: int = 608
    first_clause_words: int = 4
    acknowledgements: bool = True


ARMS = (
    Arm("baseline (shipped defaults)"),
    Arm("speculative reply", speculative=True),
    Arm("her-PC preset", speculative=True, pause_ms=192, min_end_silence_ms=384, first_clause_words=3),
)
BRAINS = {"local-gpu": (0.10, 70.0), "server-scripted": (0.9, 4.6)}


def run_arm(arm: Arm, brain: str = "local-gpu", turns: int = 10, asr_delay: float = 0.17) -> dict:
    first, rate = BRAINS[brain]
    config = CallConfig(
        turn=TurnConfig(pause_ms=arm.pause_ms, min_end_silence_ms=arm.min_end_silence_ms),
        partial_transcripts=False, speculative_reply=arm.speculative, first_clause_words=arm.first_clause_words,
        acknowledgements=arm.acknowledgements)
    session = CallSession(vad=_VAD(), asr=_ASR(asr_delay), brain=_Brain(first, rate), tts=_TTS(), speaker=_Speaker(),
                          endpointer=_Endpointer(), config=config)
    session.start()
    if session.acks is not None:
        session.acks.ready.wait(30)
    step = FRAME_MS / 1000.0
    t0 = time.monotonic()
    k = 0

    def frame(data: bytes) -> None:
        nonlocal k
        k += 1
        wait = t0 + k * step - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        session.feed(data)

    for _ in range(turns):
        for _ in range(40):                          # 1.3 s of speech
            frame(SPEECH)
        want = len(session.turns) + 1
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not (len(session.turns) >= want and not session.busy()):
            frame(SILENCE)
        for _ in range(25):                          # 0.8 s of quiet between turns
            frame(SILENCE)
    session.stop()
    good = [m for m in session.turns if not m.error and not m.interrupted]
    perceived = sorted(m.stages()["perceived"] for m in good if m.stages()["perceived"] is not None)
    summary = latency_summary(session.turns)

    def pct(values: list[float], q: float) -> float | None:
        return round(values[min(len(values) - 1, max(0, int(round(q * len(values) + 0.5)) - 1))] * 1000, 1) if values else None

    stages = {}
    for key in ("endpoint", "asr", "transcript_to_first_token", "first_token_to_first_audio", "total"):
        values = sorted(m.stages()[key] for m in good if m.stages()[key] is not None)
        stages[key] = {"p50_ms": pct(values, 0.5), "p95_ms": pct(values, 0.95)}
    return {"arm": arm.name, "brain": brain, "turns": len(good), "of": turns,
            "first_audio": summary["latency"]["speech_end_to_audio_submitted"],
            "perceived_p50_ms": pct(perceived, 0.5), "perceived_p95_ms": pct(perceived, 0.95), "stages": stages}


def table(results: list[dict]) -> str:
    rows = [f"{'arm':<30} {'brain':<16} {'n':>3}  {'first audio p50':>15} {'p95':>7}  {'perceived p50':>13} {'p95':>7}"]
    for r in results:
        fa = r["first_audio"]
        rows.append(f"{r['arm']:<30} {r['brain']:<16} {r['turns']:>3}  {fa['p50_ms']:>12.0f} ms {fa['p95_ms']:>4.0f} ms  "
                    f"{r['perceived_p50_ms']:>10.0f} ms {r['perceived_p95_ms']:>4.0f} ms")
    rows.append("")
    rows.append(f"{'where the time goes (p50, ms)':<48} " + "  ".join(f"{k[:14]:>14}" for k in
                                                                    ("endpoint", "asr", "transcript_to_first_token",
                                                                     "first_token_to_first_audio", "total")))
    for r in results:
        rows.append(f"{r['arm'] + ' / ' + r['brain']:<48} " + "  ".join(f"{r['stages'][k]['p50_ms']:>14.0f}"
                                                                      for k in r["stages"]))
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--brain", choices=[*BRAINS, "both"], default="both")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    brains = list(BRAINS) if args.brain == "both" else [args.brain]
    results = [run_arm(arm, brain, args.turns) for brain in brains for arm in ARMS]
    print(table(results))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
