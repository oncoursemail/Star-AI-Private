"""Minecraft's fast layer. Mineflayer already knows the world exactly, so "perception" is the 10 Hz state event
from skill_runner.js (health, food, nearby mobs and players, inventory) instead of pixels.

Reflexes (checked every tick, before the planner's goal): flee when a hostile is close and health is low, eat
when hungry and safe. Otherwise the goal from the slow layer names a skill from her library and the controller
starts it when the bot is free. Every reflex waits a human reaction time (ex-Gaussian, humanlike.py) before it
fires, and the skills themselves turn the view at human speed (h.look), so she does not react in one tick like
a bot. Moments (death, finished goal) go to the voice context and the emotion engine.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..humanlike import HumanProfile, reaction_delay
from ..planner import Goal
from .skills import MinecraftLink, SkillLibrary, SkillRunner

FLEE_DIST, FLEE_HEALTH = 6.0, 10
EAT_FOOD, SAFE_DIST = 14, 10.0


@dataclass
class MinecraftObs:
    t_capture: float
    state: dict
    events: list


class MinecraftObserver:
    def __init__(self, link: MinecraftLink) -> None:
        self.link = link

    def __call__(self) -> MinecraftObs | None:
        self.link.pump()
        if self.link.state is None:
            return None
        return MinecraftObs(self.link.state_t, self.link.state, self.link.take_events())


class MinecraftReflex:
    game = "minecraft"

    def __init__(self, library: SkillLibrary, runner: SkillRunner, *, rng: random.Random | None = None,
                 profile: HumanProfile | None = None) -> None:
        self.library, self.runner = library, runner
        self.rng, self.profile = rng or random.Random(), profile or HumanProfile()
        self.running: tuple[str, str] | None = None        # (run id, skill name)
        self.pending: tuple[float, str, dict] | None = None  # (fire at, skill, args): waiting out a reaction time
        self.finished: list[tuple[str, bool]] = []
        self._moments: list[str] = []

    @property
    def goals(self) -> dict[str, str]:
        found = {s.name: s.description for s in sorted(self.library.all(verified_only=True), key=lambda s: -s.successes)}
        found = dict(list(found.items())[:12])
        found.setdefault("explore_nearby", "walk somewhere new nearby and look around")
        found["learn_skill"] = "learn a new skill; put what to learn in target (e.g. 'craft a wooden pickaxe')"
        found["idle"] = "stand still and chat"
        return found

    def _reflex(self, state: dict) -> tuple[str, dict] | None:
        hostiles = state.get("hostiles") or []
        nearest = hostiles[0][1] if hostiles else 1e9
        if nearest <= FLEE_DIST and float(state.get("health") or 20) <= FLEE_HEALTH:
            return "flee_hostile", {}
        inventory = state.get("inventory") or {}
        foods = ("cooked_beef", "cooked_porkchop", "bread", "cooked_chicken", "baked_potato", "apple", "carrot")
        if float(state.get("food") or 20) <= EAT_FOOD and nearest > SAFE_DIST and any(inventory.get(f) for f in foods):
            return "eat_food", {}
        return None

    def decide(self, obs: MinecraftObs, goal: Goal, now: float) -> list:
        for event in obs.events:
            if event.get("type") == "death":
                self._moments.append("death")
                self.running = self.pending = None
            elif event.get("type") == "respawn":
                self._moments.append("respawn")
        if self.running is not None:
            run_id, name = self.running
            skill = self.library.get(name)
            result = self.runner.collect(run_id, skill) if skill is not None else None
            if result is None and skill is not None:
                reflex = self._reflex(obs.state)
                if reflex is None or reflex[0] == name:
                    return []                          # still busy with this skill
                self.runner.link.send({"cmd": "stop_skill"})   # danger beats the current job
            else:
                self.finished.append((name, bool(result and result.ok)))
                if result is not None and result.ok and name == goal.name:
                    self._moments.append("objective")
            self.running = None
        if self.pending is not None:
            fire_at, name, args = self.pending
            if now < fire_at:
                return []
            self.pending = None
            return [("skill", name, args)]
        reflex = self._reflex(obs.state)
        if reflex is not None:
            self.pending = (now + reaction_delay(self.rng, self.profile), *reflex)
            return []
        if goal.name in ("idle", "learn_skill"):
            return []                                    # learning runs in the slow layer; idle does nothing
        if self.library.get(goal.name) is not None:
            # starting her own next job is not a reflex: a person takes a moment before the next thing
            self.pending = (now + 2 * reaction_delay(self.rng, self.profile), goal.name, {})
        return []

    def act(self, actions: list, now: float) -> None:
        for kind, name, args in actions:
            skill = self.library.get(name)
            if kind == "skill" and skill is not None:
                self.running = (self.runner.start(skill, args), name)

    def moments(self, obs) -> list[str]:
        out, self._moments = self._moments, []
        return out

    def describe(self, obs: MinecraftObs) -> str:
        s = obs.state
        hostiles = ", ".join(f"{n} {d:.0f}m" for n, d in (s.get("hostiles") or [])[:3]) or "none"
        players = ", ".join(f"{n} {d:.0f}m" for n, d in (s.get("players") or [])[:3]) or "nobody"
        inventory = s.get("inventory") or {}
        top = ", ".join(f"{k} x{v}" for k, v in sorted(inventory.items(), key=lambda kv: -kv[1])[:6]) or "empty"
        doing = self.running[1] if self.running else (s.get("skill") or "nothing")
        return (f"health {s.get('health')}/20, food {s.get('food')}/20; hostiles: {hostiles}; players: {players}; "
                f"inventory: {top}; doing: {doing}")
