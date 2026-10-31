"""Per-turn latency records for voice calls and the table that prints them."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import ceil, isfinite


@dataclass
class TurnMetrics:
    """Clock times (seconds, same clock) of each stage in one user turn and the reply to it."""
    turn: int = 0
    user_text: str = ""
    reply_text: str = ""            # what was actually spoken (cut short if interrupted)
    speech_end: float | None = None      # last voiced microphone frame
    turn_end: float | None = None        # end-of-turn decision
    transcript_at: float | None = None   # transcript ready
    first_token_at: float | None = None  # first text from the brain
    first_sentence_at: float | None = None   # first chunk handed to text-to-speech
    first_audio_at: float | None = None  # first audio handed to the speaker
    first_ack_at: float | None = None    # acknowledgement clip handed to the speaker (star/voice/acks.py)
    ack_text: str = ""
    last_token_at: float | None = None   # last text from the brain
    done_at: float | None = None
    end_reason: str = ""            # how the turn ended: model | silence | max_silence | max_turn
    asr_seconds: float = 0.0        # compute time of the transcription itself
    asr_speculative: bool = False   # transcript was already under way when the turn ended
    tokens: int = 0
    audio_seconds: float = 0.0      # reply audio synthesised
    tts_seconds: float = 0.0        # compute time spent synthesising
    interrupted: bool = False
    interrupt_reason: str = ""
    heard_seconds: float = 0.0      # reply audio played before the interruption
    error: str = ""

    @staticmethod
    def _gap(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else max(0.0, b - a)

    def stages(self) -> dict:
        """The latency breakdown in seconds. `total` is what the user feels: stop talking -> hear Star."""
        generation = self._gap(self.first_token_at, self.last_token_at)
        return {
            "endpoint": self._gap(self.speech_end, self.turn_end),
            "asr": self._gap(self.turn_end, self.transcript_at),
            "speech_end_to_transcript": self._gap(self.speech_end, self.transcript_at),
            "transcript_to_first_token": self._gap(self.transcript_at, self.first_token_at),
            "first_token_to_first_audio": self._gap(self.first_token_at, self.first_audio_at),
            "total": self._gap(self.speech_end, self.first_audio_at),
            # what the user waits for until Star makes a sound: the acknowledgement clip when one played
            "perceived": self._gap(self.speech_end, min((t for t in (self.first_ack_at, self.first_audio_at)
                                                         if t is not None), default=None)),
            "tokens_per_second": ((self.tokens - 1) / generation) if generation and self.tokens > 2 else None,
        }

    def to_dict(self) -> dict:
        data = asdict(self)
        data["stages"] = {k: (None if v is None else round(v, 3)) for k, v in self.stages().items()}
        return data


def latency_summary(turns: list[TurnMetrics]) -> dict:
    """Report tail latency from real voice-clock stamps without capturing user text.

    The first-audio stamp means a PCM chunk was *submitted* to the speaker; it
    cannot prove when the user physically heard it. An errored, missing, or
    clock-invalid turn must never silently improve p95. Nearest-rank percentiles
    are descriptive and are not a quality or deployment promotion gate.
    """
    if len(turns) > 10000 or any(not isinstance(t, TurnMetrics) for t in turns):
        raise ValueError("Expected at most 10000 voice turns")
    pairs = {
        "speech_end_to_audio_submitted": ("speech_end", "first_audio_at"),
        "endpointer": ("speech_end", "turn_end"),
        "transcription": ("turn_end", "transcript_at"),
        "brain_first_token": ("transcript_at", "first_token_at"),
        "tts_and_queue": ("first_token_at", "first_audio_at"),
    }
    samples: dict[str, list[float]] = {key: [] for key in pairs}
    failed = invalid = incomplete = 0

    def valid(value) -> bool:
        return type(value) in (float, int) and isfinite(value)

    for turn in turns:
        if turn.error:
            failed += 1
            continue
        a, b = turn.speech_end, turn.first_audio_at
        if a is None or b is None:
            incomplete += 1
            continue
        if not valid(a) or not valid(b) or b < a or (
            turn.first_token_at is not None and
            (not valid(turn.first_token_at) or turn.first_token_at > b)
        ):
            invalid += 1
            continue
        for key, (begin, end) in pairs.items():
            x, y = getattr(turn, begin), getattr(turn, end)
            if valid(x) and valid(y) and y >= x:
                samples[key].append((y - x) * 1000)

    def quantiles(values: list[float]) -> dict:
        if not values:
            return {"n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
        ordered = sorted(values)
        index = lambda percentile: ordered[ceil(percentile * len(ordered)) - 1]
        return {"n": len(ordered), "p50_ms": round(index(0.50), 1),
                "p95_ms": round(index(0.95), 1), "max_ms": round(ordered[-1], 1)}

    return {"total_turns": len(turns), "errored_turns": failed,
            "incomplete_turns": incomplete, "invalid_clock_turns": invalid,
            "interrupted_turns": sum(t.interrupted for t in turns),
            "latency": {key: quantiles(values) for key, values in samples.items()}}


def _cell(value: float | None, width: int, digits: int = 2) -> str:
    return ("-" if value is None else f"{value:.{digits}f}").rjust(width)


def latency_table(turns: list[TurnMetrics]) -> str:
    """Plain-text table, one row per turn, times in seconds."""
    head = (f"{'turn':>4}  {'end-of-turn':>11}  {'transcribe':>10}  {'speech end ->':>13}  {'transcript ->':>13}  "
            f"{'first token ->':>14}  {'TOTAL':>6}  {'tok/s':>5}  note")
    sub = (f"{'':>4}  {'wait':>11}  {'':>10}  {'transcript':>13}  {'first token':>13}  "
           f"{'first audio':>14}  {'':>6}  {'':>5}")
    rows = [head, sub, "-" * len(head)]
    for m in turns:
        s = m.stages()
        notes = []
        if m.end_reason:
            notes.append(f"end={m.end_reason}")
        if m.asr_speculative:
            notes.append("early transcript")
        if m.interrupted:
            notes.append(f"interrupted after {m.heard_seconds:.1f}s ({m.interrupt_reason})")
        if m.error:
            notes.append("ERROR " + m.error[:60])
        rows.append(f"{m.turn:>4}  {_cell(s['endpoint'], 11)}  {_cell(s['asr'], 10)}  "
                    f"{_cell(s['speech_end_to_transcript'], 13)}  {_cell(s['transcript_to_first_token'], 13)}  "
                    f"{_cell(s['first_token_to_first_audio'], 14)}  {_cell(s['total'], 6)}  "
                    f"{_cell(s['tokens_per_second'], 5, 1)}  {', '.join(notes)}")
    complete = [m.stages() for m in turns if m.stages()["total"] is not None]
    if len(complete) > 1:
        def mean(key: str) -> float | None:
            values = [s[key] for s in complete if s[key] is not None]
            return sum(values) / len(values) if values else None
        rows.append("-" * len(head))
        rows.append(f"{'mean':>4}  {_cell(mean('endpoint'), 11)}  {_cell(mean('asr'), 10)}  "
                    f"{_cell(mean('speech_end_to_transcript'), 13)}  {_cell(mean('transcript_to_first_token'), 13)}  "
                    f"{_cell(mean('first_token_to_first_audio'), 14)}  {_cell(mean('total'), 6)}  "
                    f"{_cell(mean('tokens_per_second'), 5, 1)}")
    return "\n".join(rows)
