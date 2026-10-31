"""Acknowledgement clips: a short "okay" in Star's own voice the moment the user's turn is understood.

The brain's first spoken words arrive about 1.5-2 s after the user stops talking (first token, then a first clause,
then text-to-speech). A clip rendered once in the configured voice plays at once and bridges that gap
(docs/research/voice-and-web-20261023.md A5). Clips are rendered in memory with the call's own TextToSpeech at call
start, never shipped as files, so they always match the chosen voice, speed and pitch.

Rules: a clip is picked by a cheap reading of the transcript (question, task, feeling, other) and rotates within its
group; turns under MIN_WORDS words ("thanks", "hi") get none, because their answer is short and quick anyway.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

LINES: dict[str, tuple[str, ...]] = {
    "question": ("Hmm, let me think.", "Good question.", "Let me see."),
    "task": ("Sure, one moment.", "On it.", "Alright."),
    "feeling": ("Aw.", "I'm here.", "Mm, I'm listening."),
    "other": ("Mm-hm.", "Hmm.", "Right."),
}
# Small sounds of listening while the user is still talking (CallSession._maybe_backchannel). Rendered only when asked for.
BACKCHANNELS = ("Mm-hm.", "Yeah.", "I see.", "Right.", "Mm.")
# The voice persona often opens with "Oh, ..." or "Okay, ...": the clips avoid those words so the reply does not
# repeat them; a reply sentence that is exactly the clip's words is not spoken again (CallSession._speak).
MIN_WORDS = 4
_FEELING = re.compile(r"\b(sad|tired|stressed|upset|angry|lonely|scared|worried|anxious|hurt|crying|bad day|"
                      r"miss (?:you|her|him|them)|feel(?:ing)?)\b", re.I)
_TASK = re.compile(r"^\s*(?:please\s+)?(?:can you|could you|would you|make|write|build|create|fix|add|change|"
                   r"set|turn|open|play|find|show|tell me|remind|help me)\b", re.I)
_QUESTION = re.compile(r"\?\s*$|^\s*(?:what|why|how|when|where|who|which|is|are|do|does|did|should|would)\b", re.I)


def kind(text: str) -> str | None:
    """The clip group for a transcript, or None when no clip should play."""
    if len(re.findall(r"[A-Za-z0-9']+", text or "")) < MIN_WORDS:
        return None
    if _FEELING.search(text):
        return "feeling"
    if _TASK.search(text):
        return "task"
    if _QUESTION.search(text):
        return "question"
    return "other"


@dataclass(frozen=True)
class Clip:
    text: str
    chunks: tuple[tuple[bytes, int], ...]

    @property
    def seconds(self) -> float:
        return sum(len(pcm) / 2 / rate for pcm, rate in self.chunks)


class AckClips:
    """Renders every line once (render(), usually on a background thread) and hands out clips by transcript."""

    def __init__(self, tts, lines: dict[str, tuple[str, ...]] | None = None, backchannels: tuple[str, ...] = ()) -> None:
        self.tts = tts
        self.lines = lines or LINES
        self.backchannels = backchannels
        self._back: list[Clip] = []
        self._back_next = 0
        self._clips: dict[str, list[Clip]] = {}
        self._next: dict[str, int] = {}
        self._lock = threading.Lock()
        self.ready = threading.Event()

    def render(self) -> None:
        clips: dict[str, list[Clip]] = {}
        back: list[Clip] = []
        try:
            for group, texts in self.lines.items():
                for text in texts:
                    chunks = tuple((pcm, rate) for pcm, rate in self.tts.synthesize(text) if pcm)
                    if chunks:
                        clips.setdefault(group, []).append(Clip(text, chunks))
            for text in self.backchannels:
                chunks = tuple((pcm, rate) for pcm, rate in self.tts.synthesize(text) if pcm)
                if chunks:
                    back.append(Clip(text, chunks))
        finally:
            with self._lock:
                self._clips = clips
                self._back = back
            self.ready.set()

    def backchannel(self) -> Clip | None:
        """The next listening sound ("Mm-hm."), rotating, or None when none were rendered or not ready yet."""
        with self._lock:
            if not self._back or not self.ready.is_set():
                return None
            clip = self._back[self._back_next % len(self._back)]
            self._back_next += 1
            return clip

    def pick(self, transcript: str) -> Clip | None:
        group = kind(transcript)
        if group is None or not self.ready.is_set():
            return None
        with self._lock:
            options = self._clips.get(group) or []
            if not options:
                return None
            index = self._next.get(group, 0)
            self._next[group] = index + 1
            return options[index % len(options)]
