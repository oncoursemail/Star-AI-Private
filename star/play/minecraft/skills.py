"""Her Minecraft skill library (Voyager-style): small Mineflayer functions she writes, runs, checks and keeps.

A skill is the body of `async function (bot, args, h)` (see skill_runner.js). It is saved only after a run in her
world met its written expectation (`expect`, checked here from the before/after snapshots the runner returns), so
the library holds things she has actually done, not things a model claimed. Seed skills shipped with STAR start
unverified and become verified the first time they work in her world.

Storage: <app data>/play/minecraft/skills/<name>.json (one file per skill: code, description, expectation, counts).
Retrieval: word-overlap cosine over name + description (no embedding model needed for a library of hundreds).
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

NAME = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
FORBIDDEN = re.compile(r"\b(require|process|import|eval|Function|globalThis|constructor|__proto__|prototype|"
                       r"child_process)\b")
DEP = re.compile(r"h\.skill\(\s*['\"]([a-z][a-z0-9_]{2,47})['\"]")
MAX_CODE = 6000
MAX_FAILS_UNVERIFIED = 3               # an unverified candidate that failed this often is dropped


@dataclass
class Skill:
    name: str
    description: str
    code: str
    expect: dict = field(default_factory=dict)
    verified: bool = False
    origin: str = "learned"            # learned | seed
    runs: int = 0
    successes: int = 0
    failures: int = 0
    last_error: str = ""
    created: float = 0.0
    verified_at: float = 0.0


def static_problems(code: str) -> list[str]:
    problems = []
    if not code.strip():
        problems.append("empty code")
    if len(code) > MAX_CODE:
        problems.append(f"code longer than {MAX_CODE} characters")
    bad = sorted(set(FORBIDDEN.findall(code)))
    if bad:
        problems.append("uses forbidden names: " + ", ".join(bad))
    if re.search(r"while\s*\(\s*true\s*\)", code) and "await" not in code:
        problems.append("busy loop without await would freeze the bot")
    return problems


def check_expect(expect: dict, before: dict, after: dict) -> tuple[bool, str]:
    """Mechanical check of a skill's promise. Supported: inventory_gain {item: n}, inventory_has {item: n},
    moved_at_least n (blocks), health_at_least n, food_at_least n, food_gain n. An empty expectation proves nothing."""
    if not expect:
        return False, "no expectation to check"
    inv_b, inv_a = before.get("inventory") or {}, after.get("inventory") or {}
    for item, n in (expect.get("inventory_gain") or {}).items():
        gain = int(inv_a.get(item, 0)) - int(inv_b.get(item, 0))
        if gain < int(n):
            return False, f"expected +{n} {item}, got {gain:+d}"
    for item, n in (expect.get("inventory_has") or {}).items():
        if int(inv_a.get(item, 0)) < int(n):
            return False, f"expected at least {n} {item}, have {inv_a.get(item, 0)}"
    if "moved_at_least" in expect:
        p0, p1 = before.get("pos"), after.get("pos")
        moved = math.dist(p0, p1) if p0 and p1 else 0.0
        if moved < float(expect["moved_at_least"]):
            return False, f"expected to move {expect['moved_at_least']} blocks, moved {moved:.1f}"
    if "food_gain" in expect and float(after.get("food") or 0) - float(before.get("food") or 0) < float(expect["food_gain"]):
        return False, f"expected food +{expect['food_gain']}, got {before.get('food')} -> {after.get('food')}"
    for key in ("health", "food"):
        want = expect.get(f"{key}_at_least")
        if want is not None and float(after.get(key) or 0) < float(want):
            return False, f"expected {key} >= {want}, have {after.get(key)}"
    known = {"inventory_gain", "inventory_has", "moved_at_least", "health_at_least", "food_at_least", "food_gain"}
    unknown = set(expect) - known
    if unknown:
        return False, "unknown expectation keys: " + ", ".join(sorted(unknown))
    return True, "expectation met"


def _words(text: str) -> Counter:
    return Counter(w for w in re.split(r"[^a-z0-9]+", text.lower().replace("_", " ")) if len(w) > 1)


class SkillLibrary:
    def __init__(self, root: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        if root is None:
            from ...desktop_core import app_data
            root = app_data() / "play" / "minecraft" / "skills"
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._lock = threading.Lock()
        self._skills: dict[str, Skill] = {}
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                skill = Skill(**{k: v for k, v in data.items() if k in Skill.__dataclass_fields__})
            except (OSError, ValueError, TypeError):
                continue
            if NAME.match(skill.name):
                self._skills[skill.name] = skill

    def __len__(self) -> int:
        return len(self._skills)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self, *, verified_only: bool = False) -> list[Skill]:
        return [s for s in self._skills.values() if s.verified or not verified_only]

    def _write(self, skill: Skill) -> None:
        path = self.root / f"{skill.name}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(skill), indent=1), encoding="utf-8")
        tmp.replace(path)

    def add_candidate(self, name: str, description: str, code: str, expect: dict, *, origin: str = "learned") -> Skill:
        if not NAME.match(name):
            raise ValueError("skill names are lower_snake_case, 3-48 characters")
        problems = static_problems(code)
        if problems:
            raise ValueError("; ".join(problems))
        with self._lock:
            old = self._skills.get(name)
            if old is not None and old.verified and old.code != code:
                raise ValueError(f"a verified skill named {name} exists; pick another name")
            skill = old if old is not None and old.code == code else Skill(name, description.strip()[:300], code,
                                                                             dict(expect), origin=origin,
                                                                             created=self.clock())
            self._skills[name] = skill
            self._write(skill)
            return skill

    def record(self, name: str, ok: bool, error: str = "") -> Skill | None:
        """A run's outcome (ok = ran AND met its expectation). Verifies on first success; drops a candidate that
        never worked after MAX_FAILS_UNVERIFIED tries."""
        with self._lock:
            skill = self._skills.get(name)
            if skill is None:
                return None
            skill.runs += 1
            if ok:
                skill.successes += 1
                if not skill.verified:
                    skill.verified, skill.verified_at = True, self.clock()
            else:
                skill.failures += 1
                skill.last_error = error[:300]
            if not skill.verified and skill.failures >= MAX_FAILS_UNVERIFIED and skill.origin != "seed":
                del self._skills[name]
                (self.root / f"{name}.json").unlink(missing_ok=True)
                return None
            self._write(skill)
            return skill

    def retrieve(self, query: str, k: int = 3, *, verified_only: bool = True) -> list[Skill]:
        q = _words(query)
        scored = []
        for skill in self.all(verified_only=verified_only):
            d = _words(skill.name + " " + skill.description)
            dot = sum(q[w] * d[w] for w in q)
            if dot:
                norm = math.sqrt(sum(v * v for v in q.values())) * math.sqrt(sum(v * v for v in d.values()))
                scored.append((dot / norm, skill.successes, skill.name))
        scored.sort(reverse=True)
        return [self._skills[name] for _, _, name in scored[:k]]

    def deps(self, code: str, _seen: set[str] | None = None) -> dict[str, str]:
        """Verified skills this code calls through h.skill('name'), recursively (sent along with a run)."""
        seen = _seen if _seen is not None else set()
        out: dict[str, str] = {}
        for name in DEP.findall(code):
            skill = self._skills.get(name)
            if skill is None or not skill.verified or name in seen:
                continue
            seen.add(name)
            out[name] = skill.code
            out.update(self.deps(skill.code, seen))
        return out

    def install_seeds(self) -> int:
        added = 0
        for name, (description, code, expect) in SEED_SKILLS.items():
            if name not in self._skills:
                self.add_candidate(name, description, code, expect, origin="seed")
                added += 1
        return added


# Hand-written starting skills. Unverified until they work in her world (the runner checks `expect`).
SEED_SKILLS: dict[str, tuple[str, str, dict]] = {
    "collect_oak_logs": (
        "walk to the nearest oak trees and chop logs (args.count, default 3)",
        """const want = args.count || 3
const id = bot.registry.blocksByName.oak_log.id
let got = 0
for (const pos of bot.findBlocks({ matching: id, maxDistance: 48, count: want })) {
  const block = bot.blockAt(pos)
  if (!block) continue
  await bot.pathfinder.goto(new h.goals.GoalLookAtBlock(pos, bot.world))
  await h.look(pos.offset(0.5, 0.5, 0.5))
  await bot.dig(block)
  await bot.pathfinder.goto(new h.goals.GoalNear(pos.x, pos.y, pos.z, 1)).catch(() => {})
  got += 1
  await h.sleep(200 + Math.random() * 400)
}
return got""",
        {"inventory_gain": {"oak_log": 1}}),
    "eat_food": (
        "eat something from the inventory when hungry",
        """const foods = ['cooked_beef', 'cooked_porkchop', 'bread', 'cooked_chicken', 'baked_potato', 'apple', 'carrot']
const item = bot.inventory.items().find((i) => foods.includes(i.name))
if (!item) throw new Error('no food in inventory')
await bot.equip(item, 'hand')
await bot.consume()""",
        {"food_gain": 1}),
    "flee_hostile": (
        "run away from the nearest hostile mob for a few seconds",
        """const me = bot.entity.position
const mob = bot.nearestEntity((e) => e.type === 'hostile' || e.kind === 'Hostile mobs')
if (!mob) return
const away = me.minus(mob.position).normalize().scaled(12).plus(me)
await bot.pathfinder.goto(new h.goals.GoalNear(away.x, away.y, away.z, 2)).catch(() => {})""",
        {"moved_at_least": 4}),
    "explore_nearby": (
        "walk somewhere new nearby and look around",
        """const p = bot.entity.position
const d = args.distance || 20
const angle = Math.random() * Math.PI * 2
await bot.pathfinder.goto(new h.goals.GoalNear(p.x + Math.cos(angle) * d, p.y, p.z + Math.sin(angle) * d, 2))
  .catch(() => {})
await h.sleep(400 + Math.random() * 800)""",
        {"moved_at_least": 6}),
}


@dataclass
class RunResult:
    ok: bool                           # ran without error AND met its expectation
    ran: bool
    error: str
    before: dict
    after: dict
    ms: float


class MinecraftLink:
    """One Mineflayer transport (star/games/minecraft.py Transport: send(dict), poll() -> [dict]) shared by the fast
    loop, the skill runner and chat: `pump()` reads events once and hands them out."""

    def __init__(self, transport, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.transport, self.clock = transport, clock
        self.state: dict | None = None
        self.state_t = 0.0
        self.results: dict[str, dict] = {}
        self.events: list[dict] = []              # death/respawn/chat for the controller and the slow loop
        self._lock = threading.Lock()

    def pump(self) -> None:
        with self._lock:
            for event in self.transport.poll():
                kind = event.get("type")
                if kind == "state":
                    self.state, self.state_t = event, self.clock()
                elif kind == "skill_result" and event.get("id"):
                    self.results[str(event["id"])] = event
                else:
                    self.events.append(event)
            del self.events[:-200]

    def take_events(self) -> list[dict]:
        with self._lock:
            out, self.events = self.events, []
            return out

    def send(self, command: dict) -> None:
        with self._lock:
            self.transport.send(command)


class SkillRunner:
    def __init__(self, link: MinecraftLink, library: SkillLibrary, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.link, self.library, self._sleep = link, library, sleep
        self._n = 0

    def start(self, skill: Skill, args: dict | None = None, timeout_s: float = 60.0) -> str:
        """Send the run and return its id at once (the fast loop does not wait)."""
        self._n += 1
        run_id = f"{skill.name}-{self._n}"
        self.link.send({"cmd": "run_skill", "id": run_id, "name": skill.name, "code": skill.code,
                        "args": args or {}, "deps": self.library.deps(skill.code), "timeout_ms": int(timeout_s * 1000)})
        return run_id

    def collect(self, run_id: str, skill: Skill) -> RunResult | None:
        """The finished run, checked and recorded in the library; None while it is still running."""
        self.link.pump()
        event = self.link.results.pop(run_id, None)
        if event is None:
            return None
        before, after = event.get("before") or {}, event.get("after") or {}
        ran = bool(event.get("ok"))
        met, why = check_expect(skill.expect, before, after) if ran else (False, str(event.get("error") or "failed"))
        self.library.record(skill.name, ran and met, "" if met else why)
        return RunResult(ran and met, ran, "" if met else why, before, after, float(event.get("ms") or 0))

    def run(self, skill: Skill, args: dict | None = None, timeout_s: float = 60.0) -> RunResult:
        run_id = self.start(skill, args, timeout_s)
        deadline = self.link.clock() + timeout_s + 5.0
        while self.link.clock() < deadline:
            result = self.collect(run_id, skill)
            if result is not None:
                return result
            self._sleep(0.05)
        self.library.record(skill.name, False, "no result from the bot")
        return RunResult(False, False, "no result from the bot", {}, {}, timeout_s * 1000)
