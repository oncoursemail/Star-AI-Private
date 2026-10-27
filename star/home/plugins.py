"""Adapters that connect the packages built in their own branches to STAR Home's registry.

activities.default_registry() imports each module of PLUGIN_MODULES; a package with its own `register_home_activities`
(star.watch, star.computer) registers itself, the others are connected here:
  star.social  Discord (answer DMs and mentions in the real app), the handler for messages that arrive while she is busy
  star.play    Roblox and Minecraft play: the two-tier loop (star.play) with her voice, the friend chat of star.games
  star.senses  voice calls: answer a friend's ring, place a call herself, leave politely, start a game she was invited to
and wire_watch() joins star.watch (video watching) to her voice and to the scheduler's interrupt.
Everything reads the shared Runtime from `registry.runtime`; without one (a bare registry) the adapters add nothing.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable

from . import control


# ---- the shared step loop -------------------------------------------------------------------------------------
def run_steps(step: Callable, ctx, *, minutes: float, step_s: float, until_idle: int = 0,
              sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
              watch_interrupt: bool = True, max_failures: int = 3) -> dict:
    """Call `step() -> StepResult` every `step_s` for `minutes`. Stops early after `until_idle` quiet steps in a row, after
    `max_failures` failed steps, or (paused) when the scheduler's interrupt is set. Returns an activity outcome."""
    started = clock()
    deadline = started + minutes * 60.0
    notes: list[str] = []
    acted = failed = quiet = 0
    while clock() < deadline:
        if watch_interrupt and ctx.interrupt.is_set():
            return {"ok": True, "verified": False, "paused": True, "summary": "paused: someone needs her",
                    "evidence": notes[-5:], "resume_state": {"left_s": max(0.0, deadline - clock())}}
        result = step()
        if result.note and (result.acted or not result.ok):
            notes.append(result.note)
        if not result.ok:
            failed += 1
            if failed >= max_failures:
                break
        else:
            failed = 0
        acted += 1 if result.acted else 0
        quiet = 0 if result.acted else quiet + 1
        if until_idle and quiet >= until_idle:
            break
        sleep(step_s)
    ok = failed < max_failures
    return {"ok": ok, "verified": ok and clock() <= deadline + 1.0, "evidence": notes[-5:], "steps": acted,
            "minutes": (clock() - started) / 60.0,
            "summary": ("; ".join(notes[-4:]) if notes else "nothing needed her") if ok else
            f"stopped after {failed} failed steps: {notes[-1] if notes else 'no detail'}",
            "failures": [] if ok else [f"steps: {notes[-1] if notes else 'failed'}"]}


# ---- star.social ------------------------------------------------------------------------------------------------
def register_social(registry) -> None:
    rt = registry.runtime
    if rt is None or rt.discord is None:
        return
    discord = rt.discord
    pace = float((rt.config.get("play") or {}).get("step_s", 3.0))

    def check_discord(ctx) -> dict:
        minutes = float(ctx.resume_state.get("left_s", 300.0)) / 60.0
        return run_steps(discord.step, ctx, minutes=minutes, step_s=pace, until_idle=2,
                         sleep=rt.hooks.get("sleep", time.sleep))

    def message_handler(incoming, ctx) -> dict:
        """A message she decided to answer: open Discord and answer what is unread until nothing is left."""
        out = run_steps(discord.step, ctx, minutes=2.0, step_s=1.5, until_idle=1, watch_interrupt=False,
                        sleep=rt.hooks.get("sleep", time.sleep))
        if out["ok"] and out.get("steps"):
            rt.feel("talked_to_friend", incoming.platform, incoming.sender)       # an exchange with a friend settles her
        return {"ok": out["ok"], "summary": out["summary"]}

    registry.register("discord", "chat_with_friends", check_discord,
                      "answer unread DMs and mentions in her Discord app", needs_brain=True)
    registry.register_handler("discord:message", message_handler)


# ---- star.senses ------------------------------------------------------------------------------------------------
def register_senses(registry) -> None:
    rt = registry.runtime
    if rt is None or rt.discord is None:
        return
    if rt.voice._call_factory is None and rt.voice._voice_factory is None:      # the real stack (tests bring fakes)
        from . import voicestack
        rt.voice._call_factory = voicestack.call_factory(rt.config, rt.desk, sender_of=lambda: rt.calls.friend)
        if (rt.config.get("play") or {}).get("voice_in_games", True):
            rt.voice._voice_factory = voicestack.voice_factory(rt.config)
    calls = rt.calls

    def start_game(incoming, ctx) -> dict:
        result = calls.start_game(incoming, ctx)
        rt.attention.request(incoming.text)
        return result

    registry.register_handler("discord:call", calls.answer)
    registry.register_handler("discord:callout", calls.callout)
    registry.register_handler("discord:hangup", calls.hangup)
    registry.register_handler("discord:startgame", start_game)


# ---- star.play: Roblox and Minecraft ---------------------------------------------------------------------------
ROUND_START = {"round_started"}
ROUND_END = {"round_won", "round_lost", "match_finished", "death", "respawn", "checkpoint", "objective"}


def _moment_listener(situation):
    def listen(kind: str, now: float) -> None:
        if situation is None:
            return
        if kind in ROUND_START:
            situation.in_moment = True
        elif kind in ROUND_END:
            situation.in_moment = False
    return listen


class _Tee:
    """One Mineflayer process, two readers: her friend chat (star.games) and the skill loop (star.play) each get every
    event, instead of one of them taking them away from the other."""

    def __init__(self, transport) -> None:
        self.transport = transport
        self._queues = {"chat": deque(maxlen=500), "link": deque(maxlen=500)}

    def view(self, name: str):
        tee = self

        class View:
            def send(self, command: dict) -> None:
                tee.transport.send(command)

            def poll(self) -> list[dict]:
                for event in tee.transport.poll():
                    for queue in tee._queues.values():
                        queue.append(event)
                out = list(tee._queues[name])
                tee._queues[name].clear()
                return out

            def close(self) -> None:
                tee.transport.close()
        return View()


def register_play(registry) -> None:
    rt = registry.runtime
    if rt is None:
        return
    settings = rt.social_settings()
    play_cfg = rt.config.get("play") or {}
    minutes_cfg = float(play_cfg.get("session_minutes", 12))
    step_s = float(play_cfg.get("step_s", 3.0))
    sleep = rt.hooks.get("sleep", time.sleep)
    names = rt.my_names()

    def finish(out: dict, session) -> dict:
        if session is not None:
            session.stop()
        return out

    # -- Roblox
    roblox_cfg = settings.get("roblox") or {}
    if roblox_cfg.get("enabled") and roblox_cfg.get("experiences"):
        from ..games.roblox import Experience, RobloxPlay
        roblox = RobloxPlay(rt.host, rt.social, [Experience(**e) for e in roblox_cfg["experiences"]], my_names=names,
                            **rt.hooks.get("roblox_kwargs", {}))
        obby_places = {int(p) for p in play_cfg.get("obby_places", [])}

        def play_roblox(ctx) -> dict:
            minutes = float(ctx.resume_state.get("left_s", minutes_cfg * 60.0)) / 60.0
            if roblox.current is None:
                started = roblox.start()
                if not started.ok:
                    return {"ok": False, "verified": False, "summary": started.note, "evidence": [],
                            "failures": [f"roblox: {started.note}"]}
                sleep(float(play_cfg.get("load_wait_s", 20.0)))
            session = None
            current = roblox.current
            if current is not None and current.place_id in obby_places:
                from ..play.roblox import ObbyProfile
                if not rt.host.focus_window("Roblox"):
                    return {"ok": False, "verified": False, "summary": "Roblox is not in front", "evidence": [],
                            "failures": ["roblox: not in front"]}
                make = rt.hooks.get("roblox_session")
                if make is None:
                    from ..play.session import roblox_obby_session as make
                session = make(ObbyProfile(place_id=current.place_id), brain=rt.planner_brain(),
                               speak=rt.voice.speak, voice_window=rt.voice.window_for("roblox_obby"))
                session.fast.on_moment.append(_moment_listener(ctx.situation))
                session.start()
                steps = lambda: _Idle()                                    # the session plays; this loop only waits  # noqa: E731
            else:
                steps = roblox.step
            out = run_steps(steps, ctx, minutes=minutes, step_s=step_s, sleep=sleep, clock=rt.hooks.get("clock", time.monotonic))
            if session is not None:
                out["evidence"] = (out.get("evidence") or []) + [f"{session.report().get('ticks', 0)} play ticks"]
            finish(out, session)
            if not out.get("paused"):
                roblox.stop()
            return out

        registry.register("roblox", "play_games", play_roblox, "play Roblox on her own account", needs_brain=True)

    # -- Minecraft
    mc_cfg = settings.get("minecraft") or {}
    servers = mc_cfg.get("servers") or []
    if mc_cfg.get("enabled") and servers:
        from ..games.minecraft import MinecraftPlay, MinecraftServer, NodeTransport
        tee: dict = {}

        def factory(server):
            transport = rt.hooks.get("node_transport", NodeTransport)(server)
            tee["tee"] = _Tee(transport)
            return tee["tee"].view("chat")

        minecraft = MinecraftPlay(rt.social, MinecraftServer(**servers[0]), my_names=names, transport_factory=factory,
                                  **rt.hooks.get("minecraft_kwargs", {}))

        def play_minecraft(ctx) -> dict:
            minutes = float(ctx.resume_state.get("left_s", minutes_cfg * 60.0)) / 60.0
            if minecraft.transport is None:
                started = minecraft.start()
                if not started.ok:
                    return {"ok": False, "verified": False, "summary": started.note, "evidence": [],
                            "failures": [f"minecraft: {started.note}"]}
            make = rt.hooks.get("minecraft_session")
            if make is None:
                from ..play.session import minecraft_session as make
            session = make(tee["tee"].view("link"), brain=rt.planner_brain(), speak=rt.voice.speak,
                           voice_window=rt.voice.window_for("minecraft"))
            session.fast.on_moment.append(_moment_listener(ctx.situation))
            minecraft.busy_until = float("inf")             # the skill loop picks her goals now, not the idle chores
            session.start()
            out = run_steps(minecraft.step, ctx, minutes=minutes, step_s=step_s, sleep=sleep,
                            clock=rt.hooks.get("clock", time.monotonic))
            finish(out, session)
            if not out.get("paused"):
                minecraft.stop()
            else:
                minecraft.busy_until = 0.0
            return out

        registry.register("minecraft", "play_games", play_minecraft, "play Minecraft with friends on a server that allows bots",
                          needs_brain=True)


class _Idle:
    ok, acted, note = True, False, ""


# ---- star.watch -------------------------------------------------------------------------------------------------
def hearing_hub(rt):
    """The star.senses hearing hub (the PC's sound with her own voice excluded), started the first time a video needs
    it; None when hearing cannot start on this PC, and then star.watch keeps to captions and the picture."""
    try:
        hook = rt.hooks.get("hearing_hub")
        if hook is not None:
            return hook()
        from . import voicestack
        return voicestack.hearing_hub(rt.config)
    except Exception:
        return None


def wire_watch(registry) -> None:
    """Connect star.watch (video watching, PR #643) to her voice and to the scheduler. Skipped when it is not installed."""
    rt = registry.runtime
    if rt is None:
        return
    try:
        import importlib
        watch = importlib.import_module("star.watch")
    except ImportError:
        return
    try:
        watch.ensure_interest(rt.life)                      # existing installs have no watch_videos interest
        watch.configure(speak=rt.voice.speak,
                        chat=lambda text: control.log_action(rt.home, "watch", "reaction", text=str(text)[:200]))
    except Exception as why:
        registry.plugin_errors["star.watch"] = f"{type(why).__name__}: {why}"
        return
    activity = registry.items.get("watch_videos")
    if activity is None:
        return
    inner = activity.run

    def run(ctx) -> dict:
        """The watcher sleeps through `parts.sleep`; ending that sleep early when a friend needs her stops the video
        cleanly (paused with 'k'), and she comes back to a video afterwards."""
        browser_error: Any = getattr(importlib.import_module("star.watch.browser"), "BrowserError", RuntimeError)

        class Interrupted(browser_error):
            pass

        real_sleep = watch.configure().sleep

        def sleep(seconds: float) -> None:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if ctx.interrupt.is_set():                  # set only once the bounded wait for a moment is over
                    raise Interrupted("a friend needs her")
                real_sleep(min(0.5, max(0.0, end - time.monotonic())))

        watch.configure(hub=hearing_hub(rt), sleep=sleep)
        try:
            out = inner(ctx)
        finally:
            watch.configure(sleep=real_sleep)
        if ctx.interrupt.is_set():
            ctx.executor.do("key", {"keys": "k"})            # pause the video before she looks away
            if not out.get("ok"):
                return {"ok": True, "verified": False, "paused": True, "summary": "paused the video: someone needs her",
                        "evidence": [], "resume_state": {}}
        return out

    activity.run = run


ADAPTERS = {"star.social": register_social, "star.play": register_play, "star.senses": register_senses}
