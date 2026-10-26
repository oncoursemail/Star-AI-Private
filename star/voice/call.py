"""One voice call: microphone frames in, spoken replies out, with interruption.

    microphone -> voice activity -> end of turn -> transcript -> brain (streaming)
               -> sentence chunks -> text-to-speech -> speaker

Everything heavy is behind small interfaces (VoiceActivity, SpeechToText, Brain, TextToSpeech, Speaker), so
engines are swappable and the turn logic is tested with fakes. Threads: the caller feeds microphone frames
from one thread; each reply runs on its own worker thread plus one speech thread.

Two ways to take a turn:
  hands-free     voice activity + end-of-turn model decide when the user started and finished (TurnDetector);
  push-to-talk   the user holds a key or button while talking (push_to_talk(True/False)). Releasing it ends
                 the turn at once, so there is no end-of-turn wait and no risk of being cut off mid-thought.
                 Pressing it while Star talks interrupts her; talking over her (without the key) also stops
                 her speech when `ptt_voice_barge_in` is on, but only the key opens a new turn.

Barge-in: when the user starts talking while Star is thinking or speaking, the reply is cancelled at once
(the model request is closed, queued speech is dropped, the speaker is silenced). Only the words that were
actually played stay in the conversation history, so Star knows what the user did and did not hear.
"""
from __future__ import annotations

import inspect
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Protocol

from .chunker import SentenceChunker, speakable
from .game_context import GameMomentWindow
from .metrics import TurnMetrics
from .pcm import FRAME_MS, rms
from .. import emotion as emotion_state
from ..persona import leaked_reasoning
from .persona import system_message
from .turn import EchoGate, Endpointer, TurnConfig, TurnDetector, TurnEvent


# -- engine interfaces ------------------------------------------------------------------------
class VoiceActivity(Protocol):
    def probability(self, frame: bytes) -> float:
        """Speech probability (0..1) for one 512-sample, 16 kHz, PCM16 frame."""


class SpeechToText(Protocol):
    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str: ...


class Brain(Protocol):
    def stream(self, messages: list[dict]) -> Iterator[str]:
        """Return an iterator of text pieces that also has close(), callable from another thread."""


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> Iterable[tuple[bytes, int]]:
        """Yield (PCM16 mono bytes, sample rate) chunks for one sentence. Streaming engines yield several."""


class Speaker(Protocol):
    def play(self, pcm: bytes, sample_rate: int) -> None: ...     # queue audio, do not block
    def stop(self) -> None: ...                                   # silence now and drop the queue
    def reset(self) -> None: ...                                  # new reply: zero played_seconds
    def pending_seconds(self) -> float: ...                       # queued but not yet played
    def played_seconds(self) -> float: ...                        # played since reset()
    def level(self) -> float: ...                                 # loudest 32 ms played in the last 0.4 s, 0..1


@dataclass
class CallConfig:
    turn: TurnConfig = field(default_factory=TurnConfig)
    history_messages: int = 40            # most user+assistant messages sent as context (see _context)
    system_extra: str = ""                # optional extra context appended to the voice prompt
    style: str = "warm-caring"            # speaking manner (persona.STYLE_PROMPTS): warm-caring, confident-commanding, anime-bright
    speculative_asr: bool = True          # start transcribing at the first pause
    partial_transcripts: bool = True      # live transcript while the user is talking
    partial_interval: float = 0.9         # seconds between live transcripts
    level_interval: float = 0.08          # seconds between level events
    first_clause_words: int = 4           # see SentenceChunker
    use_echo_gate: bool = False           # True when playing through loudspeakers instead of headphones
    echo_margin_db: float = 4.0           # how much louder than the loudest echo the user must be to interrupt
    echo_tail: float = 0.5                # seconds the echo gate stays armed after playback ends
    push_to_talk: bool = False            # True: turns are opened and closed by push_to_talk(), not by the VAD
    ptt_tail_ms: int = 160                # keep recording this long after the key is released (trailing words)
    ptt_voice_barge_in: bool = True       # push-to-talk: talking over Star (without the key) still silences her
    acknowledgements: bool = False        # play a short pre-rendered "okay" in Star's voice once the turn is understood
    game_context_for_voice: bool = False  # opt-in ephemeral, typed game telemetry; never enables game control
    speculative_reply: bool = False       # start answering at the first pause, hold the sound until the turn really ends
    backchannels: bool = False            # say "mm-hm" in a long pause while the user is clearly not finished (no loudspeaker echo)
    backchannel_after: float = 3.0        # only once the user has spoken this many seconds
    backchannel_gap: float = 8.0          # and never twice within this many seconds
    emotion: bool = False                 # star/emotion.py: tone note in the prompt, small prosody shifts, avatar event
    emotion_person: str = "owner"         # attachment is kept per person; the social module passes a friend id here
    emotion_partner_adult: bool | None = None   # romance only when the social module says True


# Said when the model twice wrote its plan instead of an answer, and when asking again: see _generate_and_speak.
RETRY_NOTE = "\n\n(Say only the words you speak out loud: no plans, no notes to yourself.)"
FALLBACK_LINE = "Sorry, I lost my words for a second. Say that again for me?"


def _same_words(a: str, b: str) -> bool:
    return re.findall(r"\w+", a.lower()) == re.findall(r"\w+", b.lower())


@dataclass
class _Sentence:
    text: str
    start: float
    end: float


class _Reply:
    def __init__(self, turn: int, committed: bool = True) -> None:
        self.metrics = TurnMetrics(turn=turn)
        # A speculative reply (CallSession._start_spec_reply) is generated and spoken into these buffers while the
        # user may still be talking: nothing is played or emitted until committed is set, or all of it is dropped.
        self.committed = threading.Event()
        if committed:
            self.committed.set()
        self.settled = threading.Event()         # set once the speculative reply is committed or discarded
        self.discarded = False
        self.held_audio: list[tuple[bytes, int]] = []
        self.held_events: list[dict] = []
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.play_lock = threading.Lock()
        self.stream = None
        self.user_text = ""
        self.raw_text = ""
        self.sentences: list[_Sentence] = []
        self.audio_seconds = 0.0
        self.prosody = None
        self.heard_seconds: float | None = None
        self.error: Exception | None = None


class CallSession:
    """Drives one call. Feed 32 ms microphone frames with feed(); listen to on_event for everything else."""

    def __init__(self, *, vad: VoiceActivity, asr: SpeechToText, brain: Brain, tts: TextToSpeech,
                 speaker: Speaker, endpointer: Endpointer | None = None, config: CallConfig | None = None,
                 on_event: Callable[[dict], None] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 game_events: GameMomentWindow | None = None, emotion_engine=None) -> None:
        self.config = config or CallConfig()
        self.game_events = game_events
        self.vad, self.asr, self.brain, self.tts, self.speaker = vad, asr, brain, tts, speaker
        self.detector = TurnDetector(self.config.turn, endpointer)
        self.echo_gate = EchoGate(self.config.echo_margin_db) if self.config.use_echo_gate else None
        self.on_event = on_event or (lambda event: None)
        self.clock = clock
        self.emotion = emotion_engine if emotion_engine is not None else (
            emotion_state.default_engine() if self.config.emotion else None)
        try:
            self._tts_prosody = "prosody" in inspect.signature(tts.synthesize).parameters
        except (AttributeError, TypeError, ValueError):
            self._tts_prosody = False
        self.history: list[dict] = []
        self.turns: list[TurnMetrics] = []
        self.state = "idle"
        self.muted = False
        self._lock = threading.RLock()
        self._asr_lock = threading.Lock()
        self._reply: _Reply | None = None
        self._turn_count = 0
        self._carry = ""                     # user text from a reply that was cancelled before any audio
        self._speculative: dict | None = None
        self._partial_busy = threading.Event()
        self._last_partial = 0.0
        self._last_level = 0.0
        self._last_audible = float("-inf")
        self._stopped = False
        self._ptt_lock = threading.Lock()
        self._ptt_held = False
        self._ptt_frames: list[bytes] = []
        self._ptt_voiced_ms = 0
        self._ptt_released_at: float | None = None
        self._ptt_tail_frames = 0               # frames recorded since the key was released
        self._ptt_barge_ms = 0
        self.acks = None
        self._last_backchannel = float("-inf")
        if self.config.acknowledgements or self.config.backchannels:
            from .acks import BACKCHANNELS, AckClips
            self.acks = AckClips(tts, backchannels=BACKCHANNELS if self.config.backchannels else ())
            threading.Thread(target=self.acks.render, name="star-voice-acks", daemon=True).start()

    # -- lifecycle --------------------------------------------------------------------------
    def start(self) -> None:
        self._stopped = False
        self._set_state("listening")

    def stop(self) -> None:
        """End the call: cancel any reply and go quiet."""
        self._stopped = True
        self._drop_speculative()
        self._cancel_reply("call_ended")
        reply = self._reply
        if reply is not None:
            reply.done.wait(3.0)
        self.detector.reset()
        self._set_state("ended")

    def interrupt(self) -> None:
        """Manual interruption (for a "stop talking" button)."""
        self._cancel_reply("button")

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if self.muted:
            self._drop_speculative()
            self.detector.reset()
        self._emit({"type": "muted", "muted": self.muted})

    def push_to_talk(self, down: bool) -> None:
        """Push-to-talk key or button: True when pressed, False when released. Ignored in hands-free calls."""
        if not self.config.push_to_talk or self._stopped:
            return
        now = self.clock()
        if down:
            with self._ptt_lock:
                if self._ptt_held and self._ptt_released_at is None:
                    return                                   # key repeat
                if self._ptt_held:                           # pressed again during the release tail: keep going
                    self._ptt_released_at, self._ptt_tail_frames = None, 0
                    return
                self._ptt_held, self._ptt_frames, self._ptt_voiced_ms = True, [], 0
                self._ptt_released_at, self._ptt_tail_frames = None, 0
            was_busy = self.busy()
            if was_busy:
                self._cancel_reply("push_to_talk")
            self._last_partial = now
            self._emit({"type": "speech_started", "barge_in": bool(was_busy), "push_to_talk": True})
            self._set_state("user_speaking")
        else:
            with self._ptt_lock:
                if self._ptt_held and self._ptt_released_at is None:
                    self._ptt_released_at = now
            if self.config.ptt_tail_ms <= 0:
                self._ptt_finish(now)

    def _feed_ptt(self, frame: bytes, now: float) -> None:
        """Push-to-talk frame handling: record while the key is held; otherwise only watch for talking over Star.

        The release tail is counted in microphone frames, not wall time, so it is exact whatever the frame pacing."""
        cfg = self.config
        if self._ptt_held:
            probability = float(self.vad.probability(frame))
            with self._ptt_lock:
                self._ptt_frames.append(frame)
                if probability >= cfg.turn.end_threshold:
                    self._ptt_voiced_ms += FRAME_MS
                if self._ptt_released_at is not None:
                    self._ptt_tail_frames += 1
                tail_done = (self._ptt_released_at is not None
                             and self._ptt_tail_frames * FRAME_MS >= cfg.ptt_tail_ms)
                too_long = len(self._ptt_frames) * FRAME_MS >= cfg.turn.max_turn_ms
            if too_long or tail_done:
                self._ptt_finish(now)
            elif (cfg.partial_transcripts and now - self._last_partial >= cfg.partial_interval
                  and not self._partial_busy.is_set()):
                self._last_partial = now
                self._start_partial(b"".join(self._ptt_frames))
            return
        if not (cfg.ptt_voice_barge_in and self.busy() and self.speaker.pending_seconds() > 0):
            self._ptt_barge_ms = 0
            return
        probability = float(self.vad.probability(frame))
        gate_open = True
        if self.echo_gate is not None:
            gate_open = self.echo_gate.allows(rms(frame), self.speaker.level())
        voiced = probability >= cfg.turn.barge_in_threshold and gate_open
        self._ptt_barge_ms = self._ptt_barge_ms + FRAME_MS if voiced else max(0, self._ptt_barge_ms - FRAME_MS)
        if self._ptt_barge_ms >= cfg.turn.barge_in_ms:
            self._ptt_barge_ms = 0
            self._cancel_reply("barge_in")
            self._emit({"type": "speech_started", "barge_in": True, "push_to_talk": False})

    def _ptt_finish(self, now: float) -> None:
        with self._ptt_lock:
            if not self._ptt_held:
                return
            audio, voiced = b"".join(self._ptt_frames), self._ptt_voiced_ms
            released = self._ptt_released_at if self._ptt_released_at is not None else now
            self._ptt_held, self._ptt_frames, self._ptt_voiced_ms, self._ptt_released_at = False, [], 0, None
        if voiced < self.config.turn.min_turn_ms:
            self._emit({"type": "discarded", "reason": "too_short"})
            if not self.busy():
                self._set_state("listening")
            return
        self._begin_reply(TurnEvent("turn_end", now, audio=audio, speech_end=released, reason="push_to_talk"))

    def busy(self) -> bool:
        reply = self._reply
        return reply is not None and not reply.done.is_set()

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Block until no reply is in progress (used by the file-driven mode and tests)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.busy():
                return True
            time.sleep(0.01)
        return False

    # -- microphone ---------------------------------------------------------------------------
    def feed(self, frame: bytes) -> None:
        """Process one microphone frame (512 samples, 16 kHz, PCM16 mono)."""
        if self._stopped or self.state == "idle":
            return
        now = self.clock()
        mic_level = rms(frame)
        self._emit_levels(mic_level, now)
        if self.config.push_to_talk:
            self._feed_ptt(frame, now)
            return
        if self.muted:
            return
        probability = float(self.vad.probability(frame))
        audible = self.busy() and self.speaker.pending_seconds() > 0
        gate_open = True
        if self.echo_gate is not None:
            # Through loudspeakers the microphone keeps hearing the reply for a moment after the last
            # sample was queued (device buffers, room echo), so stay in "assistant is audible" mode a
            # little longer. Speaker.level() is peak-held, so the gate still knows how loud that was.
            if audible:
                self._last_audible = now
            audible = audible or now - self._last_audible < self.config.echo_tail
            if audible:
                gate_open = self.echo_gate.allows(mic_level, self.speaker.level())
        for event in self.detector.process(frame, probability, now, assistant_active=audible, gate_open=gate_open):
            self._on_turn_event(event)
        if (self.config.partial_transcripts and self.detector.state == TurnDetector.SPEECH
                and now - self._last_partial >= self.config.partial_interval and not self._partial_busy.is_set()):
            self._last_partial = now
            self._start_partial(self.detector.audio)

    def run(self, frames: Iterable[bytes]) -> None:
        """Convenience loop: start, feed every frame from an iterable, stop."""
        self.start()
        try:
            for frame in frames:
                if self._stopped:
                    break
                self.feed(frame)
        finally:
            if not self._stopped:
                self.wait_idle()
                self.stop()

    # -- turn events --------------------------------------------------------------------------
    def _on_turn_event(self, event: TurnEvent) -> None:
        if event.kind == "speech_start":
            was_busy = self.busy()
            if was_busy:
                self._cancel_reply("barge_in" if event.barge_in else "user_kept_talking")
            self._last_partial = event.at
            self._emit({"type": "speech_started", "barge_in": bool(was_busy)})
            self._set_state("user_speaking")
        elif event.kind == "pause":
            if self.config.speculative_asr:
                self._start_speculative(event.audio, event.speech_end)
            self._maybe_backchannel(event)
        elif event.kind == "resume":
            self._drop_speculative()
        elif event.kind == "discard":
            self._drop_speculative()
            if not self.busy():
                self._set_state("listening")
        elif event.kind == "turn_end":
            self._begin_reply(event)

    def _maybe_backchannel(self, event: TurnEvent) -> None:
        """A quiet "mm-hm" when the user pauses in the middle of a long thought (the end-of-turn model says they are not
        finished). Never over loudspeakers (the microphone would hear it), never while she is speaking, at most once
        per backchannel_gap seconds, and it never starts or ends a turn."""
        cfg = self.config
        if (not cfg.backchannels or self.acks is None or self.echo_gate is not None or self.busy()
                or event.complete_probability is None or event.complete_probability >= 0.3):
            return
        now = self.clock()
        if len(event.audio) / 2 / 16000 < cfg.backchannel_after or now - self._last_backchannel < cfg.backchannel_gap:
            return
        clip = self.acks.backchannel()
        if clip is None:
            return
        self._last_backchannel = now
        for pcm, sample_rate in clip.chunks:
            self.speaker.play(pcm, sample_rate)
        self._emit({"type": "backchannel", "text": clip.text})

    def _begin_reply(self, event: TurnEvent) -> None:
        with self._lock:
            previous = self._reply
            speculative, self._speculative = self._speculative, None
            early = speculative.get("reply") if speculative else None
            if speculative is not None:
                speculative["committed"] = True      # too late for the speculative thread to start one now
            if early is None:
                self._turn_count += 1
                reply = _Reply(self._turn_count)
                reply.metrics.speech_end = event.speech_end
                reply.metrics.turn_end = event.at
                reply.metrics.end_reason = event.reason
                self._reply = reply
        if early is not None:
            self._adopt_spec_reply(early, event)
            return
        self._set_state("thinking")
        threading.Thread(target=self._run_reply, args=(reply, event.audio, speculative, previous),
                         name=f"star-voice-reply-{reply.metrics.turn}", daemon=True).start()

    # -- transcription ------------------------------------------------------------------------
    def _transcribe(self, pcm: bytes) -> tuple[str, float]:
        with self._asr_lock:
            started = self.clock()
            text = self.asr.transcribe(pcm, 16000)
            return (text or "").strip(), self.clock() - started

    def _start_speculative(self, audio: bytes, speech_end: float | None = None) -> None:
        self._drop_speculative()
        job = {"done": threading.Event(), "text": "", "seconds": 0.0, "error": None, "committed": False,
               "reply": None, "speech_end": speech_end}
        self._speculative = job

        def work() -> None:
            try:
                job["text"], job["seconds"] = self._transcribe(audio)
            except Exception as exc:              # the final transcription will retry and report
                job["error"] = exc
            finally:
                job["done"].set()
            if self.config.speculative_reply and any(ch.isalnum() for ch in job["text"]):
                self._start_spec_reply(job)
            if self._speculative is job and job["text"]:
                self._emit({"type": "partial_transcript", "text": job["text"]})

        threading.Thread(target=work, name="star-voice-asr-early", daemon=True).start()

    def _start_partial(self, audio: bytes) -> None:
        self._partial_busy.set()

        def work() -> None:
            try:
                if self._asr_lock.acquire(blocking=False):      # never make the final transcript wait for a preview
                    try:
                        text = (self.asr.transcribe(audio, 16000) or "").strip()
                    finally:
                        self._asr_lock.release()
                    if text and (self.detector.state != TurnDetector.IDLE or self._ptt_held):
                        self._emit({"type": "partial_transcript", "text": text})
            except Exception:
                pass
            finally:
                self._partial_busy.clear()

        threading.Thread(target=work, name="star-voice-asr-partial", daemon=True).start()

    # -- reply worker -------------------------------------------------------------------------
    def _run_reply(self, reply: _Reply, audio: bytes, speculative: dict | None, previous: _Reply | None) -> None:
        metrics = reply.metrics
        try:
            if previous is not None:
                previous.done.wait(5.0)          # let the interrupted reply settle its history first
            text = ""
            if speculative is not None:
                speculative["done"].wait(20.0)
                if speculative["error"] is None and speculative["done"].is_set():
                    text, metrics.asr_seconds, metrics.asr_speculative = speculative["text"], speculative["seconds"], True
            if not metrics.asr_speculative:
                text, metrics.asr_seconds = self._transcribe(audio)
            metrics.transcript_at = self.clock()
            if not any(ch.isalnum() for ch in text):
                self._emit({"type": "final_transcript", "turn": metrics.turn, "text": ""})
                return
            with self._lock:
                reply.user_text = f"{self._carry} {text}".strip() if self._carry else text
                self._carry = ""
            metrics.user_text = reply.user_text
            if reply.cancel.is_set():
                return                           # the user kept talking: _finish_reply carries these words over
            self._emit({"type": "final_transcript", "turn": metrics.turn, "text": reply.user_text})
            self.speaker.reset()
            self._acknowledge(reply)
            self._generate_and_speak(reply, self._turn_messages(reply))
        except Exception as exc:
            reply.error = exc
        finally:
            self._finish_reply(reply)

    def _turn_messages(self, reply: _Reply) -> list[dict]:
        """This turn's request: system prompt, history, then the user's words plus the optional emotion note and
        game context.
        Only reply.user_text enters the history."""
        messages = self._context() + [{"role": "user", "content": reply.user_text}]
        extras = [self._feel(reply)]
        if self.config.game_context_for_voice and self.game_events is not None:
            extras.append(self.game_events.render(now=self.clock()))
        extras = [x for x in extras if x]
        if extras:
            messages[-1] = {"role": "user", "content": "\n\n".join([reply.user_text, *extras])}
        return messages

    # -- speculative reply --------------------------------------------------------------------
    # At the first pause (256 ms of silence) the words so far are transcribed; with speculative_reply on, the brain
    # starts answering them and the first sentences are synthesised at once, but kept in reply.held_audio. If the
    # user goes on talking the whole reply is dropped without a trace (no sound, no event, no history); if the
    # turn ends, the held sound is released in the same instant, so the model and voice time is already spent.
    def _start_spec_reply(self, job: dict) -> None:
        with self._lock:
            if self._speculative is not job or job["committed"] or self._stopped or job["reply"] is not None:
                return
            previous = self._reply
            reply = _Reply(self._turn_count + 1, committed=False)
            reply.metrics.transcript_at = self.clock()
            reply.metrics.asr_seconds, reply.metrics.asr_speculative = job["seconds"], True
            reply.metrics.speech_end = job["speech_end"]
            reply.user_text = f"{self._carry} {job['text']}".strip() if self._carry else job["text"]
            reply.metrics.user_text = reply.user_text
            job["reply"] = reply
        threading.Thread(target=self._run_spec_reply, args=(reply, previous),
                         name="star-voice-reply-early", daemon=True).start()

    def _run_spec_reply(self, reply: _Reply, previous: _Reply | None) -> None:
        try:
            if previous is not None:
                previous.done.wait(5.0)          # its history must be settled before this request is built
            if not reply.cancel.is_set():
                self._generate_and_speak(reply, self._turn_messages(reply))
                while not (reply.settled.is_set() or reply.cancel.is_set()):
                    time.sleep(0.005)            # a short answer can be ready before the turn has ended
                while not reply.cancel.is_set() and self.speaker.pending_seconds() > 0:
                    time.sleep(0.01)
        except Exception as exc:
            reply.error = exc
        finally:
            if reply.discarded:
                reply.done.set()
            else:
                self._finish_reply(reply)

    def _drop_speculative(self) -> None:
        """Forget the speculative transcript and throw away any reply started from it (the user went on talking)."""
        with self._lock:
            job, self._speculative = self._speculative, None
        reply = job.get("reply") if job else None
        if reply is not None and not reply.committed.is_set():
            reply.discarded = True
            reply.cancel.set()
            self._close_stream(reply)
            reply.settled.set()

    def _adopt_spec_reply(self, reply: _Reply, event: TurnEvent) -> None:
        """The turn really ended: make the speculative reply this turn's reply and release what it has ready."""
        metrics = reply.metrics
        with self._lock:
            self._turn_count += 1
            metrics.turn, metrics.turn_end, metrics.end_reason = self._turn_count, event.at, event.reason
            metrics.speech_end = event.speech_end
            self._carry = ""                     # reply.user_text already carries those words
            self._reply = reply
        self._set_state("thinking")
        self._emit({"type": "final_transcript", "turn": metrics.turn, "text": reply.user_text})
        self.speaker.reset()
        with reply.play_lock:
            ready = bool(reply.held_audio)
        if not ready:
            self._acknowledge(reply)             # the answer is not ready yet: bridge the gap as usual
        with reply.play_lock:
            reply.committed.set()
            for held in reply.held_events:
                self._emit({**held, "turn": metrics.turn} if "turn" in held else held)
            reply.held_events = []
            if reply.held_audio and not reply.cancel.is_set():
                metrics.first_audio_at = metrics.first_audio_at or self.clock()
                self._set_state("speaking")
                for pcm, sample_rate in reply.held_audio:
                    self.speaker.play(pcm, sample_rate)
            reply.held_audio = []
        reply.settled.set()

    def _feel(self, reply: _Reply) -> str:
        """Emotion for this turn: what the user said is felt, then the tone note (appended after the user's words, like
        the game context, so the cached prompt prefix is untouched) and the speech shifts for this reply are taken from
        the state. Local only; a failure here never touches the call. Returns the note, usually empty."""
        engine = self.emotion
        if engine is None:
            return ""
        try:
            person, adult = self.config.emotion_person, self.config.emotion_partner_adult
            engine.on_message(reply.user_text, person=person, also=("voice_turn",))
            state = engine.snapshot(person, adult)
            reply.prosody = state["prosody"] if not state["prosody"].neutral else None
            self._emit({"type": "emotion", "turn": reply.metrics.turn, "dominant": state["dominant"],
                        "avatar": state["avatar"], "valence": state["valence"], "arousal": state["arousal"]})
            return emotion_state.note_line(state["directive"])
        except Exception:
            return ""

    def _acknowledge(self, reply: _Reply) -> None:
        """Play the acknowledgement clip for this turn, if any. Its length is counted as reply audio, so the
        sentence offsets used for "what the user heard" after a barge-in stay right; it never enters the history."""
        clip = self.acks.pick(reply.user_text) if self.acks is not None and self.config.acknowledgements else None
        if clip is None:
            return
        with reply.play_lock:
            if reply.cancel.is_set():
                return
            reply.metrics.first_ack_at = self.clock()
            reply.metrics.ack_text = clip.text
            for pcm, sample_rate in clip.chunks:
                self.speaker.play(pcm, sample_rate)
            reply.audio_seconds += clip.seconds
        self._emit({"type": "acknowledgement", "turn": reply.metrics.turn, "text": clip.text})

    def _context(self) -> list[dict]:
        """System prompt plus history, trimmed in big blocks rather than a little every turn.

        The server caches the prompt prefix. A window that slides by one exchange per turn would change
        that prefix every time and make the server re-read the whole conversation before each reply;
        dropping the oldest half once in a while costs one slow turn instead of all of them.
        """
        limit = max(4, self.config.history_messages)
        with self._lock:
            if len(self.history) > limit:
                keep = (limit // 2) // 2 * 2
                del self.history[: len(self.history) - keep]
            return [system_message(self.config.system_extra, self.config.style)] + list(self.history)

    def _generate_and_speak(self, reply: _Reply, messages: list[dict]) -> None:
        metrics = reply.metrics
        sentences: queue.Queue = queue.Queue()
        speech = threading.Thread(target=self._speak, args=(reply, sentences),
                                  name=f"star-voice-tts-{metrics.turn}", daemon=True)
        speech.start()
        try:
            released = self._stream_sentences(reply, messages, sentences)
            if released is False and not reply.cancel.is_set():
                # The model wrote its plan instead of an answer (star/persona.leaked_reasoning); none of it was
                # spoken. Ask once more for the spoken words only, then fall back to one honest line.
                self._reply_emit(reply, {"type": "reasoning_dropped", "turn": metrics.turn, "retry": True})
                reply.raw_text = ""
                retry = messages[:-1] + [{"role": "user", "content": messages[-1]["content"] + RETRY_NOTE}]
                if self._stream_sentences(reply, retry, sentences) is False and not reply.cancel.is_set():
                    self._reply_emit(reply, {"type": "reasoning_dropped", "turn": metrics.turn, "retry": False})
                    reply.raw_text = ""
                    sentences.put(FALLBACK_LINE)
        finally:
            sentences.put(None)
            self._close_stream(reply)
            speech.join()
        while not reply.cancel.is_set() and self.speaker.pending_seconds() > 0:
            time.sleep(0.01)                    # let the last sentence finish playing

    def _stream_sentences(self, reply: _Reply, messages: list[dict], sentences: queue.Queue) -> bool | None:
        """Stream one model reply into the speech queue. A sentence in which the model talks to itself is never
        spoken and ends the reply (what follows is the same plan). Returns False when the reply was only such
        a plan (nothing spoken), True when something was queued, None when the call was cancelled first."""
        metrics = reply.metrics
        chunker = SentenceChunker(first_clause_words=self.config.first_clause_words)
        queued = 0
        leaked = False

        def release(parts: list[str]) -> None:
            nonlocal queued, leaked
            for sentence in parts:
                if leaked_reasoning(sentence):
                    leaked = True
                    return
                if metrics.first_sentence_at is None:
                    metrics.first_sentence_at = self.clock()
                sentences.put(sentence)
                queued += 1

        reply.stream = self.brain.stream(messages)
        if reply.cancel.is_set():
            return None
        for delta in reply.stream:
            if reply.cancel.is_set():
                return None
            if metrics.first_token_at is None:
                metrics.first_token_at = self.clock()
            metrics.tokens += 1
            metrics.last_token_at = self.clock()
            reply.raw_text += delta
            self._reply_emit(reply, {"type": "assistant_delta", "turn": metrics.turn, "text": delta})
            release(chunker.feed(delta))
            if leaked:
                self._close_stream(reply)       # stop generating the plan
                break
        if not leaked and not reply.cancel.is_set():
            release(chunker.flush())
        return not (leaked and not queued)

    def _speak(self, reply: _Reply, sentences: queue.Queue) -> None:
        metrics = reply.metrics
        while True:
            sentence = sentences.get()
            if sentence is None:
                return
            if reply.cancel.is_set() or reply.error is not None:
                continue                         # keep draining so the producer never blocks
            if not reply.sentences and metrics.ack_text and _same_words(sentence, metrics.ack_text):
                continue                         # the reply opens with the words the clip just said
            started = self.clock()
            begin = reply.audio_seconds
            try:
                pieces = (self.tts.synthesize(sentence, prosody=reply.prosody)
                          if reply.prosody is not None and self._tts_prosody else self.tts.synthesize(sentence))
                for pcm, sample_rate in pieces:
                    with reply.play_lock:        # stop() takes the same lock, so nothing plays after a barge-in
                        if reply.cancel.is_set():
                            break
                        if not reply.committed.is_set():
                            reply.held_audio.append((pcm, sample_rate))     # speculative: see _adopt_spec_reply
                        else:
                            if metrics.first_audio_at is None:
                                metrics.first_audio_at = self.clock()
                                self._set_state("speaking")
                            self.speaker.play(pcm, sample_rate)
                    reply.audio_seconds += len(pcm) / 2 / sample_rate
            except Exception as exc:
                reply.error = exc
                self._close_stream(reply)
                continue
            metrics.tts_seconds += self.clock() - started
            if reply.audio_seconds > begin:
                reply.sentences.append(_Sentence(sentence, begin, reply.audio_seconds))
                self._reply_emit(reply, {"type": "assistant_sentence", "turn": metrics.turn, "text": sentence})

    def _reply_emit(self, reply: _Reply, event: dict) -> None:
        """Emit a reply event now, or keep it until a speculative reply is committed (its turn number is then fixed)."""
        if not reply.committed.is_set():
            with reply.play_lock:
                if not reply.committed.is_set():
                    reply.held_events.append(event)
                    return
        self._emit(event)

    @staticmethod
    def _close_stream(reply: _Reply) -> None:
        stream = reply.stream
        if stream is not None and hasattr(stream, "close"):
            try:
                stream.close()
            except Exception:
                pass

    # -- interruption -------------------------------------------------------------------------
    def _cancel_reply(self, reason: str) -> None:
        with self._lock:
            reply = self._reply
            if reply is None or reply.done.is_set() or reply.cancel.is_set():
                return
            reply.metrics.interrupted = True
            reply.metrics.interrupt_reason = reason
            reply.cancel.set()
        with reply.play_lock:
            reply.heard_seconds = self.speaker.played_seconds() if reply.metrics.first_audio_at is not None else 0.0
            self.speaker.stop()
        self._close_stream(reply)

    @staticmethod
    def _heard_text(reply: _Reply) -> tuple[str, bool]:
        """The part of the reply that was actually played before the interruption, and whether it was cut mid-sentence."""
        heard = reply.heard_seconds or 0.0
        parts, cut = [], False
        for sentence in reply.sentences:
            if sentence.end <= heard:
                parts.append(sentence.text)
            elif sentence.start < heard:
                words = sentence.text.split()
                share = (heard - sentence.start) / max(1e-6, sentence.end - sentence.start)
                kept = words[: int(len(words) * share)]
                if kept:
                    parts.append(" ".join(kept).rstrip(",;:"))
                    cut = True
                break
        return " ".join(parts), cut

    def _finish_reply(self, reply: _Reply) -> None:
        metrics = reply.metrics
        metrics.done_at = self.clock()
        metrics.audio_seconds = reply.audio_seconds
        interrupted = reply.cancel.is_set()
        cut_mid_sentence = False
        if interrupted:
            metrics.heard_seconds = reply.heard_seconds or 0.0
            spoken, cut_mid_sentence = self._heard_text(reply)
        else:
            spoken = " ".join(s.text for s in reply.sentences) or speakable(reply.raw_text)
        # History gets the heard words with no "..." marker: with a marker the brain copies the trailing-off
        # style into its next reply (seen against the live server). The marker is for captions only.
        metrics.reply_text = spoken
        if reply.error is not None:
            metrics.error = f"{type(reply.error).__name__}: {str(reply.error)[:200]}"
        with self._lock:
            if reply.user_text:
                if spoken:
                    self.history.append({"role": "user", "content": reply.user_text})
                    self.history.append({"role": "assistant", "content": spoken})
                elif interrupted and metrics.interrupt_reason != "call_ended":
                    self._carry = reply.user_text        # nothing was heard: the next words continue this turn
            if reply.user_text:
                self.turns.append(metrics)
        if interrupted:
            self._emit({"type": "interrupted", "turn": metrics.turn, "reason": metrics.interrupt_reason,
                        "heard_text": spoken + ("…" if cut_mid_sentence else "")})
        if reply.error is not None:
            self._emit({"type": "error", "turn": metrics.turn, "message": _friendly(reply.error)})
        if reply.user_text:
            self._emit({"type": "turn_metrics", **metrics.to_dict()})
        reply.done.set()
        with self._lock:
            latest = self._reply is reply
        if latest and not self._stopped and self.detector.state == TurnDetector.IDLE and not self._ptt_held:
            self._set_state("listening")

    # -- events -------------------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        with self._lock:
            if state == self.state:
                return
            self.state = state
        self._emit({"type": "state", "state": state})

    def _emit_levels(self, mic_level: float, now: float) -> None:
        if now - self._last_level < self.config.level_interval:
            return
        self._last_level = now
        self._emit({"type": "level", "mic": round(min(1.0, mic_level * 4), 3),
                    "speaker": round(min(1.0, self.speaker.level() * 4), 3)})

    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:
            pass                 # a broken listener must never break the call


def _friendly(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:300]


__all__ = ["CallConfig", "CallSession", "FRAME_MS", "Speaker", "SpeechToText", "TextToSpeech", "VoiceActivity",
           "Brain"]
