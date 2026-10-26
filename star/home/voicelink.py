"""Her voice inside STAR Home: the speak() queue for the play loop, the Discord call session, the game-moment window.

VoiceLine   speak(text) for star.play's slow loop: one short line at a time, spoken through her voice (the call's own
            speaker while a call runs, else the standalone voice); False when she is busy talking with someone, so a
            game remark never talks over a friend.
VoiceCall   one running call: the senses-voice CallSession fed with the PC's sound (the friend's voice, WASAPI
            loopback) and speaking into STAR Microphone (the virtual cable). It knows how long it has been quiet, so
            she can leave politely, and it hands the voice context the GameMomentWindow of whatever she is playing.
HomeVoice   owns the current call and the standalone voice; the factories are injected (tests pass fakes; the real
            ones assemble star.senses + star.voice and need her PC's devices and models).
"""
from __future__ import annotations

import inspect
import itertools
import threading
import time
from typing import Callable, Iterable

from ..voice.chunker import speakable
from ..voice.game_context import GameMomentWindow

MAX_LINE_CHARS = 240
_ids = itertools.count(1)


def _prosody() -> object | None:
    """Her mood's small speech shifts, only when the emotion engine is on."""
    try:
        from .. import emotion
        return emotion.prosody_of(emotion.current()) if emotion.enabled() else None
    except Exception:
        return None


class VoiceLine:
    def __init__(self, target: Callable[[], tuple | None], *, clock: Callable[[], float] = time.monotonic) -> None:
        """`target()` -> (tts, speaker, session or None), or None while no voice is available."""
        self._target, self._clock = target, clock
        self._thread: threading.Thread | None = None
        self.spoken: list[str] = []

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def say(self, text: str) -> bool:
        line = speakable(str(text or ""))[:MAX_LINE_CHARS].strip()
        if not line or self.busy():
            return False
        target = self._target()
        if target is None:
            return False
        tts, speaker, session = target
        if session is not None and (session.busy() or session.state in ("user_speaking", "thinking")):
            return False                                    # she is talking with someone: no remark over them
        try:
            if speaker.pending_seconds() > 0.05:
                return False
        except Exception:
            pass
        self._thread = threading.Thread(target=self._speak, args=(tts, speaker, line), name="star-home-line", daemon=True)
        self._thread.start()
        return True

    def _speak(self, tts, speaker, line: str) -> None:
        try:
            kwargs = {}
            try:
                if "prosody" in inspect.signature(tts.synthesize).parameters:
                    kwargs["prosody"] = _prosody()
            except (TypeError, ValueError):
                pass
            for pcm, rate in tts.synthesize(line, **kwargs):
                speaker.play(pcm, rate)
            self.spoken.append(line)
        except Exception:
            pass                                            # a voice problem must not stop the game


class VoiceCall:
    def __init__(self, session, frames: Iterable[bytes], *, name: str = "", person: str = "",
                 closers: tuple[Callable[[], None], ...] = (), clock: Callable[[], float] = time.monotonic) -> None:
        self.session, self.frames, self.name, self.person = session, frames, name, person
        self._closers, self._clock = closers, clock
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="star-home-call", daemon=True)
        self.window: GameMomentWindow | None = None
        self.started = clock()
        self._last_active = clock()
        self._turns_seen = 0

    def start(self) -> "VoiceCall":
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            self.session.start()
            for frame in self.frames:
                if self._stop.is_set():
                    break
                self.session.feed(frame)
        except Exception:
            pass
        finally:
            try:
                self.session.stop()
            finally:
                for close in self._closers:
                    try:
                        close()
                    except Exception:
                        pass

    def alive(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def idle_s(self) -> float:
        """Seconds since anyone last said anything in the call (her or them)."""
        now = self._clock()
        turns = len(getattr(self.session, "turns", ()))
        if turns != self._turns_seen or getattr(self.session, "state", "listening") not in ("listening", "idle"):
            self._turns_seen, self._last_active = turns, now
        return now - self._last_active

    def minutes(self) -> float:
        return (self._clock() - self.started) / 60.0

    def attach_window(self, window: GameMomentWindow) -> None:
        """What she plays now is known to the call (typed, short-lived game moments; never control)."""
        self.window = window
        self.session.game_events = window
        self.session.config.game_context_for_voice = True

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5.0)


class HomeVoice:
    def __init__(self, *, call_factory: Callable[[dict], VoiceCall] | None = None,
                 voice_factory: Callable[[], tuple] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._call_factory, self._voice_factory, self._clock = call_factory, voice_factory, clock
        self.call: VoiceCall | None = None
        self.window: GameMomentWindow | None = None
        self._standalone: tuple | None = None
        self._line = VoiceLine(self._target)

    # ---- speaking -------------------------------------------------------------------------------------------
    def _target(self) -> tuple | None:
        call = self.call
        if call is not None and call.alive():
            return call.session.tts, call.session.speaker, call.session
        if self._standalone is None and self._voice_factory is not None:
            try:
                self._standalone = (*self._voice_factory(), None)
            except Exception:
                self._voice_factory = None                  # no voice stack on this PC: stay silent, keep playing
        return self._standalone

    def speak(self, text: str, prosody=None) -> bool:
        """The say-queue the play loop and the video watcher call: False when she is busy talking with someone."""
        return self._line.say(text)

    def window_for(self, game_id: str) -> GameMomentWindow:
        """A fresh moment window for one game session; when a call is live the call reads it."""
        window = GameMomentWindow(f"{game_id}-{next(_ids)}"[:60].replace(" ", "-"))
        self.window = window
        if self.call is not None and self.call.alive():
            self.call.attach_window(window)
        return window

    # ---- calls ----------------------------------------------------------------------------------------------
    def in_call(self) -> bool:
        return self.call is not None and self.call.alive()

    def start_call(self, friend: dict) -> VoiceCall:
        if self._call_factory is None:
            raise RuntimeError("no voice stack is set up on this PC (python -m star.senses.setup)")
        self.end_call()
        self.call = self._call_factory(friend).start()
        if self.window is not None:                         # she is already playing: the call knows about it
            self.call.attach_window(self.window)
        return self.call

    def end_call(self) -> None:
        call, self.call = self.call, None
        if call is not None:
            call.stop()
