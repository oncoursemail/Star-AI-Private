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
    def __init__(self, target: Callable[[], tuple | None], *, clock: Callable[[], float] = time.monotonic,
                 allowed: Callable[[], bool] = lambda: True) -> None:
        """`target()` -> (tts, speaker, session or None), or None while no voice is available."""
        self._target, self._clock = target, clock
        self._thread: threading.Thread | None = None
        self.spoken: list[str] = []
        self._allowed = allowed
        self._lock = threading.RLock()
        self._play_lock = threading.Lock()
        self._generation = 0
        self._pending = False
        self._cancel = threading.Event()
        self._speaker = None

    def busy(self) -> bool:
        with self._lock:
            return self._pending or (self._thread is not None and self._thread.is_alive())

    def say(self, text: str) -> bool:
        line = speakable(str(text or ""))[:MAX_LINE_CHARS].strip()
        with self._lock:
            if not line or self.busy() or not self._allowed():
                return False
            self._pending = True
            generation = self._generation
        try:
            target = self._target()
            if target is None:
                return False
            tts, speaker, session = target
            if session is not None and (session.busy() or session.state in ("user_speaking", "thinking")):
                return False
            if speaker.pending_seconds() > 0.05:
                return False
            with self._lock:
                if generation != self._generation or not self._allowed():
                    return False
                cancel = self._cancel = threading.Event()
                self._speaker = speaker
                self._thread = threading.Thread(target=self._speak, args=(tts, speaker, line, cancel, session),
                                                name="star-home-line", daemon=True)
                self._thread.start()
                return True
        except Exception:
            return False
        finally:
            with self._lock:
                if generation == self._generation:
                    self._pending = False

    def cancel(self) -> None:
        """Invalidate pending work, then flush its old speaker before any handoff."""
        with self._lock:
            self._generation += 1
            self._pending = False
            self._cancel.set()
            speaker, self._speaker = self._speaker, None
            with self._play_lock:
                if speaker is not None:
                    try:
                        speaker.stop()
                    except Exception:
                        pass

    def _speak(self, tts, speaker, line: str, cancel: threading.Event, session) -> None:
        stream = None
        try:
            kwargs = {}
            try:
                if "prosody" in inspect.signature(tts.synthesize).parameters:
                    kwargs["prosody"] = _prosody()
            except (TypeError, ValueError):
                pass
            stream = iter(tts.synthesize(line, **kwargs))
            for pcm, rate in stream:
                with self._play_lock:
                    if (cancel.is_set() or not self._allowed() or
                            (session is not None and (session.busy() or session.state in ("user_speaking", "thinking")))):
                        return
                    speaker.play(pcm, rate)
            if not cancel.is_set() and self._allowed():
                self.spoken.append(line)
        except Exception:
            pass                                            # a voice problem must not stop the game
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


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
        self._close_lock = threading.Lock()
        self._session_lock = threading.Lock()
        self._closed = self._session_closed = False

    def start(self) -> "VoiceCall":
        if self._stop.is_set():
            raise RuntimeError("voice call was stopped before startup")
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            with self._session_lock:
                if self._stop.is_set():
                    return
                self.session.start()
            for frame in self.frames:
                if self._stop.is_set():
                    break
                self.session.feed(frame)
        except Exception:
            pass
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        with self._close_lock:
            closers = () if self._closed else self._closers
            self._closed = True
        with self._session_lock:
            if not self._session_closed:
                self._session_closed = True
                stop_speaker = getattr(getattr(self.session, "speaker", None), "stop", None)
                if callable(stop_speaker):
                    try:
                        stop_speaker()
                    except Exception:
                        pass
                try:
                    self.session.stop()
                except Exception:
                    pass
        # Cancel session speech before any native capture/output close can block.
        # Closing capture then wakes a generator waiting for the next frame.
        for close in closers:
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
        self._cleanup()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(0.5)


class HomeVoice:
    def __init__(self, *, call_factory: Callable[[dict], VoiceCall] | None = None,
                 voice_factory: Callable[[], tuple] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._call_factory, self._voice_factory, self._clock = call_factory, voice_factory, clock
        self.call: VoiceCall | None = None
        self.window: GameMomentWindow | None = None
        self._standalone: tuple | None = None
        self._lock = threading.RLock()
        self._epoch = 0
        self._starting = False
        self._stop_check: Callable[[], bool] = lambda: False
        self._line = VoiceLine(self._target, allowed=self._allowed)

    def set_stop_check(self, check: Callable[[], bool]) -> None:
        if not callable(check):
            raise TypeError("voice stop check must be callable")
        self._stop_check = check

    def _allowed(self) -> bool:
        try:
            return self._stop_check() is False
        except Exception:
            return False

    def stopped(self) -> bool:
        return not self._allowed()

    # ---- speaking -------------------------------------------------------------------------------------------
    def _target(self) -> tuple | None:
        with self._lock:
            if self._starting or not self._allowed():
                return None
            call, epoch = self.call, self._epoch
            if call is not None and call.alive():
                return call.session.tts, call.session.speaker, call.session
            if self._standalone is not None:
                return self._standalone
            factory = self._voice_factory
        if factory is not None:
            try:
                made = (*factory(), None)
            except Exception:
                return None
            with self._lock:
                if self._epoch == epoch and not self._starting and self._allowed():
                    self._standalone = made
                    return made
            try:
                close = getattr(made[1], "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
        return None

    def speak(self, text: str, prosody=None) -> bool:
        """The say-queue the play loop and the video watcher call: False when she is busy talking with someone."""
        return self._line.say(text)

    def window_for(self, game_id: str) -> GameMomentWindow:
        """A fresh moment window for one game session; when a call is live the call reads it."""
        window = GameMomentWindow(f"{game_id}-{next(_ids)}"[:60].replace(" ", "-"))
        with self._lock:
            self.window = window
            if self.call is not None and self.call.alive():
                self.call.attach_window(window)
        return window

    # ---- calls ----------------------------------------------------------------------------------------------
    def in_call(self) -> bool:
        with self._lock:
            return self._starting or (self.call is not None and self.call.alive())

    def start_call(self, friend: dict) -> VoiceCall:
        if self._call_factory is None:
            raise RuntimeError("no voice stack is set up on this PC (python -m star.senses.setup)")
        with self._lock:
            if not self._allowed() or self._starting:
                raise RuntimeError("voice call startup is stopped or already active")
            self._epoch += 1
            epoch = self._epoch
            old, self.call = self.call, None
            self._starting = True
            self._line.cancel()                            # flush before a new private-call speaker can be published
        candidate = None
        try:
            if old is not None:
                old.stop()
            with self._lock:
                if epoch != self._epoch or not self._allowed():
                    raise RuntimeError("voice call startup was cancelled")
            candidate = self._call_factory(friend)
            with self._lock:
                if epoch != self._epoch or not self._allowed():
                    raise RuntimeError("voice call startup was cancelled")
                if self.window is not None:
                    candidate.attach_window(self.window)
                candidate.start()
                self.call = candidate
                self._starting = False
                return candidate
        except Exception:
            if candidate is not None:
                try:
                    candidate.stop()
                except Exception:
                    pass
            with self._lock:
                if epoch == self._epoch:
                    self._starting = False
            raise

    def end_call(self, *, expected=None) -> None:
        with self._lock:
            if expected is not None and self.call is not expected:
                return
            self._epoch += 1
            call, self.call = self.call, None
            self._starting = False
            self._line.cancel()
        if call is not None:
            call.stop()

    def stop(self) -> None:
        """Host STOP: cancel game speech and calls without social/UI actions."""
        self.end_call()
