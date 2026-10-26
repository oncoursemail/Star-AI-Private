"""The real voice stack for STAR Home on her PC (needs the senses-voice setup: models, VB-CABLE, soundcard).

Hardware-free checks cover lifecycle contracts; actual devices/models still need native acceptance.
star.home.voicelink takes these as factories. `python -m star.home check` reports
whether this stack could be built (build_status).
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import threading
from typing import Callable

from .voicelink import VoiceCall


def attach_lipsync(speaker):
    """Her speaker wrapped by STAR Camera's lip-sync (star.vtuber.attach_speaker) when that package is installed; the
    original speaker otherwise, and also if the camera side is broken."""
    try:
        import importlib
        wrapped = importlib.import_module("star.vtuber").attach_speaker(speaker)
        return wrapped if wrapped is not None else speaker
    except Exception:
        return speaker


def _settings(config: dict):  # pragma: no cover - reads settings of the real PC
    from ..senses.instant import apply_preset
    from ..voice.settings import VoiceSettings
    from .. import emotion
    overrides = dict(config.get("voice") or {})
    overrides.setdefault("emotion", emotion.enabled())
    return apply_preset(VoiceSettings.from_env(), overrides)


_engines_cache: dict = {}
_engines_lock = threading.Lock()
_reference_lock = threading.Lock()


def _engines(settings):  # pragma: no cover - loads models
    with _engines_lock:
        if "engines" not in _engines_cache:
            from ..voice.runtime import Engines
            _engines_cache["engines"] = Engines.load(settings)
        return _engines_cache["engines"]


def _reference():
    return shared_reference()


def _speaker(speaker):
    return _recorded(attach_lipsync(speaker))


class _WatchHub:
    """A borrowed hub view whose availability follows the owned capture thread."""

    def __init__(self, hub, source, thread):
        self.hub, self.source, self.thread = hub, source, thread

    def available(self) -> bool:
        return self.thread.is_alive() and not self.source._stop.is_set()

    def __getattr__(self, name):
        return getattr(self.hub, name)


@contextmanager
def watch_hearing(config: dict, *, hub=None, on_unavailable=None):
    """Borrow an existing hub or hear loopback for one watch activity; never open a room microphone.

    Reuse the voice stack's ASR and playback reference. Only resources created
    here are stopped here. Missing audio dependencies leave captions available.
    """
    if hub is not None:
        yield hub
        return
    source = live = None
    threads = []
    try:
        settings = _settings(config)
        if settings.hear_pc_audio:
            from ..senses.capture import LoopbackSource
            from ..senses.hearing import SensesHub
            from ..voice import engines as voice_engines
            source = LoopbackSource()
            live = SensesHub(vad_factory=lambda: voice_engines.make_vad(settings.vad),
                             asr=_engines(settings).asr, reference=_reference())
            pump = live.attach("loopback", source.frames())
            threads = [pump, live._worker]
            hub = _WatchHub(live, source, pump)
    except Exception as why:
        if on_unavailable is not None:
            try:
                on_unavailable(type(why).__name__)
            except Exception:
                pass  # reporting must not skip the resource cleanup below
    try:
        yield hub
    finally:
        for resource, method in ((source, "close"), (live, "stop")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass  # still stop the other owned resource if one close fails
        for thread in threads:
            thread.join(timeout=0.5)


_hearing: dict = {}
HEARING_RETRY_S = 300.0


def shared_reference():  # pragma: no cover - needs numpy (installed with the senses stack)
    """One record of everything she plays, shared by her speakers and the hearing hub, so her own voice is not heard."""
    with _reference_lock:
        if "reference" not in _hearing:
            from ..senses.reference import PlaybackReference
            _hearing["reference"] = PlaybackReference()
        return _hearing["reference"]


def _recorded(speaker):  # pragma: no cover
    """`speaker` that also writes what it plays into the shared reference (never fails a voice line)."""
    try:
        from ..senses.reference import ReferenceSpeaker
        return ReferenceSpeaker(speaker, shared_reference())
    except Exception:
        return speaker


def hearing_hub(config: dict, *, start: bool = True):  # pragma: no cover - needs her devices and models
    """The hearing hub for star.watch: the PC's sound and the microphone, transcribed on her GPU, started once. None when
    it cannot start (no soundcard, no model); a failure is retried after a few minutes, never raised.
    `start=False` only borrows an existing hub; watch activities use their own
    loopback-only lifecycle when no background hub is already running."""
    import time
    if _hearing.get("hub") is not None:
        return _hearing["hub"]
    if not start:
        return None
    if time.monotonic() < _hearing.get("retry_at", 0.0):
        return None
    try:
        from ..senses.instant import start_hearing
        settings = _settings(config)
        _hearing["hub"] = start_hearing(_engines(settings), settings, shared_reference())
    except Exception:
        _hearing["retry_at"] = time.monotonic() + HEARING_RETRY_S
        return None
    return _hearing["hub"]


def _started_output(settings):
    """Acquire and start the owned output before publishing it to any voice path."""
    from ..senses import routes
    speaker = routes.open_voice_output(routes.query_devices(), monitor=settings.monitor_device)
    try:
        speaker.__enter__()                    # SoundOutput construction alone does not start PortAudio
    except BaseException:
        try:
            speaker.close()
        except Exception:
            pass
        raise
    return speaker


def voice_factory(config: dict) -> Callable[[], tuple]:  # pragma: no cover - needs her devices and models
    """() -> (tts, speaker): her voice into STAR Microphone, for game remarks outside a call."""
    def build():
        settings = _settings(config)
        engines = _engines(settings)
        with ExitStack() as cleanup:
            speaker = _started_output(settings)
            cleanup.callback(speaker.close)
            wrapped = _speaker(speaker)
            cleanup.pop_all()                   # the returned wrapper owns this output's close lifecycle
            return engines.tts, wrapped
    return build


def call_factory(config: dict, desk=None, sender_of: Callable[[], str] = lambda: "") -> Callable[[dict], VoiceCall]:  # pragma: no cover
    """friend dict (name, person id, partner_adult, context) -> a VoiceCall (not started)."""
    def build(friend: dict) -> VoiceCall:
        from ..senses.capture import LoopbackSource
        from ..senses.instant import build_pc_session
        from ..voice.runtime import make_brain
        from .invites import InviteBrain
        settings = _settings(config)
        if friend.get("context"):
            settings.system_extra = (settings.system_extra + "\n" + friend["context"]).strip()
        engines = _engines(settings)
        with ExitStack() as cleanup:
            speaker = _started_output(settings)
            cleanup.callback(speaker.close)
            if config.get("brain_url"):              # address/key stay on the trusted host
                from .runtime import home_brain
                brain = home_brain(config, max_tokens=int(settings.max_reply_tokens))
            else:
                brain = make_brain(settings)
            close_brain = getattr(brain, "close", None)
            brain_closers: tuple[Callable[[], None], ...] = ()
            if callable(close_brain):
                def release_brain() -> None:
                    close_brain()
                cleanup.callback(release_brain)
                brain_closers = (release_brain,)
            if desk is not None:
                brain = InviteBrain(brain, desk, sender=sender_of)
            session, warm = build_pc_session(settings, engines, _speaker(speaker), big_brain=brain)
            cleanup.callback(session.stop)
            if warm is not None:
                cleanup.callback(warm.stop)
            session.config.emotion_person = friend.get("person") or session.config.emotion_person
            session.config.emotion_partner_adult = True if friend.get("partner_adult") is True else None
            if session.config.emotion_partner_adult is True and callable(friend.get("partner_adult_check")):
                session.config.partner_adult_check = friend["partner_adult_check"]
            source = LoopbackSource()                # hear the default output, including the friend's voice
            cleanup.callback(source.close)
            closers = (source.close, speaker.close) + ((warm.stop,) if warm is not None else ())
            closers += brain_closers
            call = VoiceCall(session, source.frames(), name=friend.get("name", ""), person=friend.get("person", ""),
                             closers=closers)
            cleanup.pop_all()                       # VoiceCall now owns session, source, warm job and output
            return call
    return build


def build_status() -> dict:  # pragma: no cover - probes the real PC
    """What is missing for calls and spoken game lines (used by `python -m star.home check`)."""
    out = {}
    for label, module in (("soundcard (hearing the PC)", "soundcard"), ("sounddevice (her voice output)", "sounddevice"),
                          ("numpy", "numpy")):
        try:
            __import__(module)
            out[label] = "ok"
        except ImportError:
            out[label] = "missing"
    try:
        from ..senses import routes
        route = routes.find_route(routes.query_devices())
        out["STAR Microphone cable"] = "ok" if route.ready else route.describe()
    except Exception as why:
        out["STAR Microphone cable"] = f"cannot check: {type(why).__name__}"
    return out
