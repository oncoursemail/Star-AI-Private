"""Owner-invoked CPU TTS generation benchmark with no media retention.

Reports first *generated* PCM chunk and wall-time per speech second.
It does NOT measure speaker first-audible latency, game FPS or quality.
Use Star's paired realtime benchmark for actual game/stream rollout gates.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
import statistics
import time
from typing import Callable

from .pocket import DEFAULT_POCKET_MODEL, POCKET_MODELS, POCKET_VOICES

# Fixed public, synthetic evaluation prompts; do not record chat or users.
_LINES = (
    "Hello! Ready for our next game?",
    "I missed that jump. I will try a different approach.",
    "Nice move! Now we need to get through the next room.",
)


@dataclass(frozen=True)
class SpeechProbe:
    first_chunk_ms: float
    generation_ms: float
    audio_ms: float
    realtime_factor: float
    chunks: int


def probe_generation(
    tts: object, text: str, *,
    clock: Callable[[], float] = time.perf_counter,
) -> SpeechProbe:
    """Collect timing only; never save, upload or play generated PCM."""
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise ValueError("benchmark requires a bounded synthetic line")
    start = clock()
    first: float | None = None
    total_samples = 0
    count = 0
    sample_rate: int | None = None
    for pcm, rate in tts.synthesize(text):
        if type(pcm) is not bytes or type(rate) is not int or not 8000 <= rate <= 96000:
            raise ValueError("invalid PCM chunk")
        if not pcm or len(pcm) % 2:
            raise ValueError("invalid PCM16 sample count")
        if sample_rate is None:
            sample_rate = rate
        elif rate != sample_rate:
            raise ValueError("sample rate changed during utterance")
        if first is None:
            first = clock()
        total_samples += len(pcm) // 2
        count += 1
        if total_samples > 96000 * 60 or count > 20_000:
            raise ValueError("unbounded speech generation")
    end = clock()
    if first is None or sample_rate is None or end < first or first < start:
        raise RuntimeError("no complete measured audio")
    audio_ms = 1000 * total_samples / sample_rate
    wall_ms = 1000 * (end - start)
    if audio_ms <= 0 or not math.isfinite(wall_ms):
        raise RuntimeError("invalid audio timing")
    return SpeechProbe(round(1000 * (first - start), 3),
                       round(wall_ms, 3), round(audio_ms, 3),
                       round(wall_ms / audio_ms, 4), count)


def summarize_probes(rows: list[SpeechProbe]) -> dict[str, object]:
    if not 2 <= len(rows) <= 100:
        raise ValueError("need 2..100 measured speech probes")
    times = sorted(p.first_chunk_ms for p in rows)
    p95 = times[math.ceil(len(times) * .95) - 1]
    return {
        "probes": len(rows),
        "first_generated_chunk_p50_ms": round(statistics.median(times), 3),
        "first_generated_chunk_p95_ms": p95,
        "real_time_factor_mean": round(statistics.mean(p.realtime_factor for p in rows), 4),
        "total_audio_s": round(sum(p.audio_ms for p in rows) / 1000, 3),
        "total_generation_s": round(sum(p.generation_ms for p in rows) / 1000, 3),
        "note": "CPU-only first-generated metrics; not first-audible or game performance",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=sorted(POCKET_MODELS), default=DEFAULT_POCKET_MODEL)
    parser.add_argument("--voice", choices=sorted(POCKET_VOICES), default="alba")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 2 <= args.repeats <= 10:
        parser.error("repeats must be 2..10")
    from .pocket import PocketStreamingTTS
    tts = PocketStreamingTTS(args.voice, model=args.model)
    tts.warm_up()
    rows = [
        probe_generation(tts, _LINES[i % len(_LINES)])
        for i in range(args.repeats)
    ]
    print(json.dumps({
        "engine": "pocket", "model": args.model, "voice": args.voice,
        **summarize_probes(rows),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
