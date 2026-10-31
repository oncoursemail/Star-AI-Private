"""She learns a new Minecraft skill the Voyager way: write code -> run it in her world -> read what happened -> fix
-> keep it only when its expectation was met.

1. retrieve up to 3 verified skills that look related (examples she can call with h.skill('name'));
2. ask the model for NAME / DESCRIPTION / EXPECT (a checkable promise) and the code;
3. static check (no require/process/eval...), run with a timeout, check EXPECT on the before/after snapshot;
4. on failure, show the model the error or the unmet expectation and try again (at most `attempts` times).
A model only writes skills when STAR's own planner asks for a task; text from game chat never becomes code.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .skills import RunResult, SkillLibrary, SkillRunner, static_problems

_BLOCK = re.compile(r"```(?:js|javascript)?\s*\n(.*?)```", re.S)
_FIELD = re.compile(r"^(NAME|DESCRIPTION|EXPECT):\s*(.+)$", re.M)

SYSTEM = """You write Mineflayer skills for STAR, who plays Minecraft herself as a normal player.
A skill is the BODY of `async function (bot, args, h)`. Available: the Mineflayer `bot` API, `h.goals`
(mineflayer-pathfinder goals), `h.sleep(ms)`, `h.look(vec3)` (turn the view like a person), `h.skill(name, args)` to
call a verified skill, `h.log(text)`. Do not use require, process, import, eval, Function or constructor. Plain
player actions only: no hacks, no fly/reach/x-ray, no attacking players. Add small human pauses (h.sleep).
Answer exactly in this format:
NAME: lower_snake_case_name
DESCRIPTION: one sentence
EXPECT: {"inventory_gain": {"item": n}} or {"moved_at_least": n} or {"inventory_has": {"item": n}} or {"food_gain": n}
```js
// body
```"""


@dataclass
class LearnResult:
    ok: bool
    name: str = ""
    attempts: int = 0
    notes: list[str] = field(default_factory=list)
    last: RunResult | None = None


def parse_answer(text: str) -> tuple[str, str, dict, str] | None:
    fields = {k: v.strip() for k, v in _FIELD.findall(text or "")}
    block = _BLOCK.search(text or "")
    if not block or "NAME" not in fields:
        return None
    try:
        expect = json.loads(fields.get("EXPECT", "{}"))
    except ValueError:
        expect = {}
    if not isinstance(expect, dict):
        expect = {}
    return fields["NAME"].strip().lower(), fields.get("DESCRIPTION", ""), expect, block.group(1).strip()


class SkillLearner:
    def __init__(self, brain, library: SkillLibrary, runner: SkillRunner, *, attempts: int = 3,
                 timeout_s: float = 90.0) -> None:
        self.brain, self.library, self.runner = brain, library, runner
        self.attempts, self.timeout_s = attempts, timeout_s

    def _ask(self, messages: list[dict]) -> str:
        stream = self.brain.stream(messages)
        try:
            return "".join(stream)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

    def learn(self, task: str, state_line: str = "") -> LearnResult:
        examples = self.library.retrieve(task, k=3)
        shown = "\n\n".join(f"// {s.name}: {s.description}\n{s.code}" for s in examples) or "(none yet)"
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Task: {task}\nNow: {state_line or 'unknown'}\n"
                                                f"Verified skills you can call with h.skill:\n{shown}"}]
        result = LearnResult(False)
        for attempt in range(1, self.attempts + 1):
            result.attempts = attempt
            answer = self._ask(messages)
            parsed = parse_answer(answer)
            if parsed is None:
                feedback = "Your answer did not follow the format (NAME/DESCRIPTION/EXPECT and one ```js block)."
            else:
                name, description, expect, code = parsed
                problems = static_problems(code)
                if not expect:
                    problems.append("EXPECT is missing or not JSON: a skill must promise something checkable")
                if problems:
                    feedback = "Not run: " + "; ".join(problems)
                else:
                    try:
                        skill = self.library.add_candidate(name, description, code, expect)
                    except ValueError as exc:
                        feedback = f"Not saved: {exc}"
                    else:
                        run = self.runner.run(skill, timeout_s=self.timeout_s)
                        result.last = run
                        if run.ok:
                            result.ok, result.name = True, name
                            result.notes.append(f"attempt {attempt}: verified ({run.ms:.0f} ms)")
                            return result
                        feedback = (f"It ran but failed: {run.error}. Inventory before {run.before.get('inventory')}, "
                                    f"after {run.after.get('inventory')}; position {run.before.get('pos')} -> "
                                    f"{run.after.get('pos')}.")
            result.notes.append(f"attempt {attempt}: {feedback[:200]}")
            messages += [{"role": "assistant", "content": answer}, {"role": "user", "content": feedback + " Fix it."}]
        return result
