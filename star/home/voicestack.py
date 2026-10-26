"""The real voice stack for STAR Home on her PC (needs the senses-voice setup: models, VB-CABLE, soundcard).

Nothing here is covered by an automated test: it assembles star.senses and star.voice from their documented entry
points. star.home.voicelink takes these as factories, and its tests use fakes. `python -m star.home check` reports
whether this stack could be built (build_status).
"""
from __future__ import annotations

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


def _engines(settings):  # pragma: no cover - loads models
    if "engines" not in _engines_cache:
        from ..voice.runtime import Engines
        _engines_cache["engines"] = Engines.load(settings)
    return _engines_cache["engines"]


def voice_factory(config: dict) -> Callable[[], tuple]:  # pragma: no cover - needs her devices and models
    """() -> (tts, speaker): her voice into STAR Microphone, for game remarks outside a call."""
    def build():
        from ..senses import routes
        settings = _settings(config)
        engines = _engines(settings)
        return engines.tts, attach_lipsync(routes.open_voice_output(routes.query_devices(), monitor=settings.monitor_device))
    return build


def call_factory(config: dict, desk=None, sender_of: Callable[[], str] = lambda: "") -> Callable[[dict], VoiceCall]:  # pragma: no cover
    """friend dict (name, person id, partner_adult, context) -> a VoiceCall (not started)."""
    def build(friend: dict) -> VoiceCall:
        from ..senses import routes
        from ..senses.capture import LoopbackSource
        from ..senses.instant import build_pc_session
        from ..voice.runtime import make_brain
        from .invites import InviteBrain
        settings = _settings(config)
        if friend.get("context"):
            settings.system_extra = (settings.system_extra + "\n" + friend["context"]).strip()
        engines = _engines(settings)
        speaker = routes.open_voice_output(routes.query_devices(), monitor=settings.monitor_device)
        if config.get("brain_url"):                  # her own brain address and key file, like the rest of STAR Home
            from .runtime import home_brain
            brain = home_brain(config, max_tokens=int(settings.max_reply_tokens))
        else:
            brain = make_brain(settings)
        if desk is not None:
            brain = InviteBrain(brain, desk, sender=sender_of)
        session, warm = build_pc_session(settings, engines, attach_lipsync(speaker), big_brain=brain)
        session.config.emotion_person = friend.get("person") or session.config.emotion_person
        session.config.emotion_partner_adult = True if friend.get("partner_adult") is True else None
        source = LoopbackSource()                    # the friend's voice: whatever Discord plays on the default output
        closers = (source.close, speaker.close) + ((warm.stop,) if warm is not None else ())
        return VoiceCall(session, source.frames(), name=friend.get("name", ""), person=friend.get("person", ""),
                         closers=closers)
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
        out["STAR Microphone cable"] = "ok" if route.ready() else route.describe()
    except Exception as why:
        out["STAR Microphone cable"] = f"cannot check: {type(why).__name__}"
    return out
