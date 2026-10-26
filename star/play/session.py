"""Wiring for the two games: build a ready GameSession from the real parts (or fakes in tests).

roblox_obby_session      screen capture -> ColorDetector -> ObbyController -> human input (SendInput) + planner
minecraft_session        Mineflayer link -> MinecraftReflex -> skills; the planner can set goal "learn_skill",
                         which runs the Voyager-style learner on its own thread and switches to the new skill
Both take `brain` (a streaming chat model: the fast local voice model on her GPU, or brain 1), `speak` (the voice
loop's say-queue, returns False when it is busy talking with someone) and optionally the voice call's
GameMomentWindow, so her call conversation knows what just happened in the game.
"""
from __future__ import annotations

import threading
from typing import Callable

from .humanlike import Actuator, HumanInput, HumanProfile
from .loop import FastLoop, GameSession, InputActor, SlowLoop, emotion_listener, voice_context_listener
from .planner import Goal, LLMPlanner


def _mood() -> str:
    try:
        from .. import emotion                       # type: ignore[attr-defined]
    except ImportError:
        return ""
    return emotion.directive()


def _wire(fast: FastLoop, brain, speak, voice_window, game_id: str, actuator=None, session_id: str = "play"
          ) -> GameSession:
    if voice_window is not None:
        fast.on_moment.append(voice_context_listener(voice_window, session_id=voice_window.session_id or session_id,
                                                     game_id=game_id))
    fast.on_moment.append(emotion_listener())
    slow = SlowLoop(LLMPlanner(brain, fast.controller.goals), fast, speak=speak, mood=_mood) if brain else None
    return GameSession(fast, slow, actuator)


def roblox_obby_session(profile=None, *, brain=None, speak: Callable[[str], bool] | None = None, voice_window=None,
                        source=None, sink=None, chat_ocr=None, hz: float = 20.0,
                        human: HumanProfile | None = None) -> GameSession:
    from .roblox import ObbyController, ObbyProfile, ScreenObserver
    profile = profile or ObbyProfile()
    controller = ObbyController(profile)
    if source is None:                                # pragma: no cover - real screen
        from .capture import open_capture, window_rect
        source = open_capture(window_rect(profile.window))
    if sink is None:                                  # pragma: no cover - real input
        from .winput import SendInputSink, window_guard
        sink = SendInputSink(window_guard(profile.window))
    actuator = Actuator(sink)
    fast = FastLoop(ScreenObserver(source, controller.detector(), chat_ocr=chat_ocr), controller,
                    InputActor(HumanInput(human), actuator), hz=hz)
    return _wire(fast, brain, speak, voice_window, "roblox_obby", actuator)


def minecraft_session(transport, *, brain=None, speak: Callable[[str], bool] | None = None, voice_window=None,
                      library=None, hz: float = 10.0) -> GameSession:
    from .minecraft.learner import SkillLearner
    from .minecraft.reflex import MinecraftObserver, MinecraftReflex
    from .minecraft.skills import MinecraftLink, SkillLibrary, SkillRunner
    library = library if library is not None else SkillLibrary()
    library.install_seeds()
    link = MinecraftLink(transport)
    runner = SkillRunner(link, library)
    controller = MinecraftReflex(library, runner)
    fast = FastLoop(MinecraftObserver(link), controller, controller.act, hz=hz, goal=Goal("explore_nearby"))
    session = _wire(fast, brain, speak, voice_window, "minecraft")
    if session.slow is not None and brain is not None:
        learner = SkillLearner(brain, library, SkillRunner(link, library))
        _learn_on_goal(fast, learner)
    return session


def _learn_on_goal(fast: FastLoop, learner) -> None:
    """When the planner picks learn_skill, learn on a side thread (one at a time) and switch to the result."""
    busy = threading.Lock()
    original = fast.set_goal

    def set_goal(goal: Goal) -> None:
        original(goal)
        if goal.name != "learn_skill" or not goal.target or not busy.acquire(blocking=False):
            return

        def work() -> None:
            try:
                obs = fast.latest
                result = learner.learn(goal.target, fast.controller.describe(obs) if obs is not None else "")
                original(Goal(result.name, "", "learned") if result.ok else Goal("explore_nearby", "", "learn failed"))
            finally:
                busy.release()

        threading.Thread(target=work, name="play-learn", daemon=True).start()

    fast.set_goal = set_goal                          # type: ignore[method-assign]
