"""The running parts of STAR Home that plug-ins share: host agent, friend memory, social chat, voice, inbox, attention.

build() makes one Runtime and the registry that goes with it; `python -m star.home run` calls it once. Everything
heavy is lazy, and every outside edge (friend memory file, brain, voice stack, screen reader) can be handed in, so the
tests run the whole chain on fakes.
"""
from __future__ import annotations

from pathlib import Path
import random
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .streamchat import StreamChat

from . import control
from .activities import Registry, default_registry
from .attention import Attention, AvailabilityModel, Inbox, Incoming, Interrupt, LeftOutWatch, Situation, Standing
from .hostagent import HostAdapter
from .invites import InviteDesk, parse_invite
from .voicelink import HomeVoice

SOCIAL_PLATFORMS = ("discord", "minecraft", "roblox")


def home_brain(config: dict, *, model: str = "", max_tokens: int = 120):
    """A streaming ServerBrain on the brain at config['brain_url'], with the key file's key (memory only)."""
    from ..server_key_file import read_key_file
    from ..voice.brain import ServerBrain
    url = str(config.get("brain_url") or "").rstrip("/")
    if not url:
        raise RuntimeError("brain_url is not set in config.json")
    key_path = Path(config["key_file"]) if config.get("key_file") else None
    key = read_key_file(path=key_path) if key_path else read_key_file()
    return ServerBrain(url if url.endswith("/v1") else url + "/v1", key, model or config.get("voice_model", "star-voice"),
                       max_tokens=max_tokens)


class Runtime:
    def __init__(self, home: Path, config: dict, executor, life, *, chat=None, memory=None, social_chat=None,
                 voice: HomeVoice | None = None, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None, emotion=..., social_settings: dict | None = None,
                 discord_kwargs: dict | None = None, call_kwargs: dict | None = None, hooks: dict | None = None) -> None:
        self.home, self.config, self.executor, self.life, self.chat = Path(home), config, executor, life, chat
        self.clock = clock
        self.host = HostAdapter(executor)
        self._memory, self._social = memory, social_chat
        self._social_settings, self.discord_kwargs, self.call_kwargs = social_settings, discord_kwargs or {}, call_kwargs or {}
        self.hooks = hooks or {}      # replaceable edges for tests: roblox_session, minecraft_session, node_transport, planner_brain
        self._discord = None
        self._calls = None
        self.voice = voice or HomeVoice()
        self._activity_stops: dict[str, Callable[[], None]] = {}
        self._activity_lock = threading.RLock()
        self._cleanup_inflight: dict[tuple, str] = {}
        self._cleanup_failed: dict[tuple, tuple[str, Callable[[], None], str]] = {}
        self._owner_stopped = False
        self._closing = False
        bind_stop = getattr(self.voice, "set_stop_check", None)
        if callable(bind_stop):
            bind_stop(lambda: self.admission_blocked() or bool(getattr(self.executor, "dry_run", False)))
        if emotion is ...:
            try:
                from .. import emotion as emotion_module
                emotion = emotion_module
            except ImportError:
                emotion = None
        self.emotion = emotion
        self.situation = Situation()
        self.interrupt = Interrupt()
        self.model = AvailabilityModel(config, rng=rng)
        self.inbox = Inbox(self.model, self._standing_of_incoming, self.situation, clock=clock,
                           on_decision=self._log_decision)
        self.attention = Attention(self.inbox, self.situation, interrupt=self.interrupt, config=config, clock=clock,
                                   log=lambda phase, **fields: control.log_action(self.home, "attention", phase, **fields))
        self.desk = InviteDesk(standing_of=self.standing, situation=self.situation, life=life, emotion=self.emotion,
                               config=config, schedule=self.inbox.schedule, clock=clock,
                               log=lambda phase, **fields: control.log_action(self.home, "attention", phase, **fields))
        self.watcher = None
        self.registry: Registry | None = None
        self.stream_chat: StreamChat | None = None

    # ---- shared parts ---------------------------------------------------------------------------------------
    @property
    def memory(self):
        if self._memory is None:
            from ..social.friends import FriendMemory
            self._memory = FriendMemory()
        return self._memory

    @property
    def social(self):
        if self._social is None:
            from ..social.chat import SocialChat
            model = self.chat_model()
            self._social = SocialChat(self.memory, complete=(lambda system, user: str(model(
                [{"role": "system", "content": system}, {"role": "user", "content": user}], []).get("content") or ""))
                if model else None)
        return self._social

    def chat_model(self):
        """chat(messages, tools) -> message dict for her own replies: the brain's quick voice model."""
        if self.chat is None:
            return None
        if self.config.get("brain_url"):
            from .brain import http_chat
            return http_chat({**self.config, "model": self.config.get("social_model", "star-voice")})
        return self.chat

    def social_settings(self) -> dict:
        if self._social_settings is None:
            import json
            from ..social.activity import DEFAULT_SETTINGS, load_settings
            try:
                inline = self.config.get("social")
                if inline is not None:
                    from .onboarding import social_config
                    self._social_settings = social_config(inline)
                else:
                    self._social_settings = load_settings()
            except (OSError, ValueError):
                self._social_settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        return self._social_settings

    @property
    def discord(self):
        """Her Discord (the real desktop app), or None when it is not switched on in the social settings."""
        if self._discord is None and self.social_settings()["discord"].get("enabled"):
            from ..social.discord_desktop import DiscordDesktop
            cfg = self.social_settings()["discord"]
            self._discord = DiscordDesktop(self.host, self.social, my_names=self.my_names(),
                                           window_title=cfg.get("window_title", "Discord"), on_invite=self.on_invite,
                                           **{"left_out": LeftOutWatch(clock=self.clock), **self.discord_kwargs})
        return self._discord

    @property
    def calls(self):
        if self._calls is None:
            from .calls import DiscordCalls
            self._calls = DiscordCalls(self.host, self.memory, self.voice, self.standing,
                                       config=self.config.get("calls"), situation=self.situation,
                                       feel=lambda kind, name, **payload: self.feel(kind, "discord", name, **payload),
                                       on_connected=self.call_connected, **self.call_kwargs)
        return self._calls

    def planner_brain(self):
        """The streaming model for the slow game loop (one short line a second): the brain's quick voice model."""
        if "planner_brain" in self.hooks:
            return self.hooks["planner_brain"]()
        try:
            return home_brain(self.config, max_tokens=120)
        except Exception:
            return None

    def my_names(self) -> list[str]:
        return [str(n) for n in (self.config.get("my_names") or ["Star"])]

    # ---- who she is talking to --------------------------------------------------------------------------------
    def standing(self, platform: str, sender: str) -> Standing:
        name = str(sender or "").strip()
        if not name or platform not in SOCIAL_PLATFORMS:
            return Standing()
        close = [str(n).lower() for n in (self.config.get("close_friends") or {}).get(platform, [])]
        person = self.memory.known(platform, name)
        if person is None:
            try:
                if self.memory.is_forgotten(platform, name):
                    return Standing(blocked=True, muted=True)
            except ValueError:
                return Standing(blocked=True)
            return Standing(True, "friend", 1.0) if name.lower() in close else Standing()
        if name.lower() in close and not person.blocked and not person.muted:
            return Standing(True, "friend", 1.0)
        closeness = 0.0
        if person.remembered:
            from ..social.lifecycle import Bonds            # the friendship stage (met .. close friend), not just friend or not
            stage_bonus = {"acquaintance": 0.1, "friend": 0.35, "close_friend": 0.6}.get(Bonds(self.memory, sink=None).stage(person), 0.0)
            closeness = min(1.0, stage_bonus + len(self.memory.moments(person, 200)) / 150.0)
        return Standing(person.remembered, person.relationship, closeness, person.blocked, person.muted)

    def _standing_of_incoming(self, incoming: Incoming) -> Standing:
        return self.standing(incoming.platform, incoming.sender)

    def _log_decision(self, incoming: Incoming, decision) -> None:
        control.log_action(self.home, "attention", "decided", route=incoming.route, sender=incoming.sender,
                           verdict=decision.action, reason=decision.reason)

    def person_id(self, platform: str, sender: str) -> str | None:
        """The opaque emotion id of a friend (never a name), or None for someone she does not keep a record of."""
        person = self.memory.known(platform, str(sender))
        return f"friend-{person.id}" if person is not None and person.id is not None else None

    def feel(self, kind: str, platform: str, sender: str, **payload) -> None:
        """An emotion event about a friend (friend_ignored, talked_to_friend, ...). Only when the engine is on and knows
        the event; a missing or failing engine never reaches the caller."""
        try:
            from .. import emotion
            # An observed event may establish a minimal profile; a standing/ID lookup never does.
            # This grants no reciprocity, friendship or adult status and respects forget tombstones.
            if platform in SOCIAL_PLATFORMS and sender and self.person_id(platform, sender) is None:
                self.memory.person(platform, str(sender), str(sender))
            emotion.on_event(kind, person=self.person_id(platform, sender), only_if_enabled=True, **payload)
        except Exception:
            pass

    def call_connected(self, name: str) -> dict | None:
        """She is in a call with `name`: the avatar knows a friend joined, and she may turn her camera on (never required).
        Deterministic: `calls.camera` is never / sometimes / always; "sometimes" is close friends when she has the energy."""
        if control.stopped(self.home):
            return None
        try:
            from .. import vtuber
            vtuber.emit_event("friend_joined")
        except Exception:
            pass
        mode = str((self.config.get("calls") or {}).get("camera", "sometimes"))
        activity = self.registry.items.get("camera on") if self.registry is not None else None
        if mode == "never" or activity is None:
            return None
        if mode != "always":
            if self.standing("discord", name).tier(float(self.model.cfg["close_at"])) != "close":
                return None
            mood = None
            try:
                from .. import emotion
                mood = emotion.current() if emotion.enabled() else None
            except Exception:
                mood = None
            if mood and (float(mood.get("valence") or 0.0) < 0.0
                         or float((mood.get("drives") or {}).get("needs_rest") or 0.0) >= 0.5):
                return None                                 # she is down or worn out: voice only
        from .activities import Context
        ctx = Context(home=self.home, config=self.config, executor=self.executor, life=self.life, chat=self.chat,
                      interest="video_call", goal=None, situation=self.situation, interrupt=self.interrupt)
        result = activity.run(ctx)
        control.log_action(self.home, "attention", "camera", ok=bool(result.get("ok")),
                           summary=str(result.get("summary", ""))[:200])
        return result

    def on_invite(self, author: str, text: str):
        invite = parse_invite(text, author)
        return self.desk.plan(invite) if invite is not None else None

    # ---- background jobs --------------------------------------------------------------------------------------
    def track_activity(self, name: str, stop: Callable[[], None]) -> None:
        """Trusted built-in cleanup, available even while an activity's planner is blocked."""
        if not isinstance(name, str) or not name or not callable(stop):
            raise ValueError("activity cleanup requires a name and callable")
        with self._activity_lock:
            self._activity_stops[name] = stop

    def untrack_activity(self, name: str, stop: Callable[[], None]) -> None:
        with self._activity_lock:
            if self._activity_stops.get(name) is stop:
                self._activity_stops.pop(name)

    def stop(self) -> None:
        self.interrupt.set("owner STOP")
        self._owner_stopped = True
        callbacks = []
        if callable(getattr(self.voice, "stop", None)):
            callbacks.append(("voice", self.voice.stop))
        call_stop = getattr(self._calls, "stop", None)
        if callable(call_stop):
            callbacks.append(("calls", call_stop))
        if self.stream_chat is not None:
            callbacks.append(("stream_chat", self.stream_chat.reader.queue.clear))
        with self._activity_lock:
            callbacks.extend(self._activity_stops.items())
            callbacks.extend((name, callback) for name, callback, _ in self._cleanup_failed.values())
        for name, callback in callbacks:
            self._queue_cleanup(name, callback)

    def _queue_cleanup(self, name: str, callback: Callable[[], None]) -> None:
        # Bound methods are recreated by attribute access; identify their receiver and function.
        key = (name, id(getattr(callback, "__self__", None)), id(getattr(callback, "__func__", callback)))
        with self._activity_lock:
            if key in self._cleanup_inflight:
                return
            self._cleanup_inflight[key] = name

        def work() -> None:
            try:
                callback()
                with self._activity_lock:
                    self._cleanup_failed.pop(key, None)
            except Exception as error:
                with self._activity_lock:
                    self._cleanup_failed[key] = (name, callback, type(error).__name__)
                try:
                    control.log_action(self.home, "stop", "cleanup_error", channel=name, error=type(error).__name__)
                except Exception:
                    pass
            finally:
                with self._activity_lock:
                    self._cleanup_inflight.pop(key, None)

        try:
            threading.Thread(target=work, name="star-stop-cleanup", daemon=True).start()
        except Exception as error:
            with self._activity_lock:
                self._cleanup_inflight.pop(key, None)
                self._cleanup_failed[key] = (name, callback, type(error).__name__)

    def stop_status(self) -> dict:
        with self._activity_lock:
            return {"pending": list(self._cleanup_inflight.values()),
                    "errors": {name: error for name, _, error in self._cleanup_failed.values()}}

    def shutdown(self) -> None:
        """Permanently close admission for this instance before stopping active resources."""
        with self._activity_lock:
            self._closing = True
        self.stop()

    def admission_blocked(self) -> bool:
        with self._activity_lock:
            return bool(self._closing or control.stopped(self.home) or self._owner_stopped or self._cleanup_inflight or self._cleanup_failed)

    def watch_tick(self) -> None:
        if self._closing:
            return
        if control.stopped(self.home):
            self.stop()
            return
        if self._owner_stopped:
            with self._activity_lock:
                if self._cleanup_inflight:
                    return
                failed = list(self._cleanup_failed.values())
            if failed:
                for name, callback, _ in failed:
                    self._queue_cleanup(name, callback)
                return
            self._owner_stopped = False
            if self.interrupt.reason == "owner STOP":
                self.interrupt.clear()
        if self._calls is not None:
            self._calls.tick(self.inbox)
        self.attention.watch_tick()

    def watcher_job(self, interval_s: float = 1.5) -> Callable[[], None]:  # pragma: no cover - the long-running thread
        def run() -> None:
            while True:
                try:
                    self.watch_tick()
                except Exception as why:
                    control.log_action(self.home, "attention", "error", detail=f"{type(why).__name__}: {why}")
                time.sleep(interval_s)
        return run

    def notification_job(self) -> Callable[[], None] | None:  # pragma: no cover - reads the real notification history
        cfg = self.config.get("notifications") or {}
        if not cfg.get("enabled", True):
            return None
        from .notifications import NotificationWatcher, best_source
        apps = tuple(cfg.get("apps") or ("discord", "roblox"))
        watcher = NotificationWatcher(
            best_source(apps), self.inbox, apps=apps, ring_s=float(self.model.cfg["call_ring_s"]), clock=self.clock,
            on_toast=lambda toast, incoming: control.log_action(
                self.home, "notification", "seen", app=toast.app, parsed=incoming.route if incoming else ""))
        self.watcher = watcher
        return lambda: watcher.run(float(cfg.get("poll_s", 2.0)))

    def background(self) -> list[Callable[[], None]]:  # pragma: no cover
        jobs = [self.watcher_job()]
        note = self.notification_job()
        if note is not None:
            jobs.append(note)
        if self.stream_chat is not None:
            jobs.append(self.stream_chat.background)
        return jobs


def build(home: Path, config: dict, executor, life, chat, *, plugins: tuple[str, ...] | None = None,
          **runtime_kwargs) -> tuple[Registry, Runtime]:
    """The registry (activities and handlers from every plug-in) and the Runtime they share, wired to one Attention."""
    runtime = Runtime(home, config, executor, life, chat=chat, **runtime_kwargs)
    registry = default_registry(*([plugins] if plugins is not None else []), runtime=runtime)
    from . import plugins as plugin_adapters
    plugin_adapters.wire_watch(registry)
    runtime.registry = registry
    runtime.attention.handlers.update(registry.handlers)
    return registry, runtime
