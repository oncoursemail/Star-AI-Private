"""Per-turn latency records for voice calls and the table that prints them."""
from __future__ import annotations

from dataclasses import dataclass, asdict


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
    heard_seconds: float = 0.0      # speaker callback-reported played audio (all turns, including non-interrupted)
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
            "tokens_per_second": ((self.tokens - 1) / generation) if generation and self.tokens > 2 else None,
        }

    def to_dict(self) -> dict:
        data = asdict(self)
        data["stages"] = {k: (None if v is None else round(v, 3)) for k, v in self.stages().items()}
        return data


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
