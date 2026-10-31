"""Adaptive thinking budget for llama.cpp brains (setting `thinking_budget`: auto | off | always).

star-fast runs with `reasoning = off` in models.ini, so by default no turn thinks. A llama.cpp server (build with
`reasoning_budget_tokens`, checked in tools/server/server-common.cpp) lets one request turn thinking on and cap it:

    chat_template_kwargs.enable_thinking = true      per-request override of `reasoning = off`
    reasoning_budget_tokens = N                      thinking stops after N tokens

`auto` (the default) picks the budget per turn from the request alone, with no model call:

  * no thinking: chat, short explanations, small edits, the quick model, vision/research turns;
  * a small to large budget: new systems, multi-file work, debugging with an error in hand, long specifications,
    and families of tasks whose historical pass rate is low (FAMILY_PASS_RATES, from work/eval-runs);
  * the check-fix loop (star/verify_ladder.py) asks its fix call with a budget that grows with every failed round
    (`rung_budget`).

`off` sends nothing (exactly the old behaviour). `always` uses the large budget on every non-quick turn.
Only llama.cpp servers get these fields (star/providers.py never sends them to a cloud vendor).

Recompute the table: `python -m star.thinking_budget rates --runs "work/eval-runs/**/*.json" --suites evals/roblox`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MODES = ("auto", "off", "always")
LEVELS = {"off": 0, "small": 256, "medium": 768, "large": 1536}
LADDER_BUDGETS = (512, 1024, 2048, 3072)        # fix round 1, 2, 3, 4: it grows with every failed rung
THINKING_PROFILES = frozenset({"roblox", "agent", "reasoning"})

# Pass rate (passed, scored) of the stored dev/holdout runs in work/eval-runs (2026-10-23), grouped by the first
# word of the task category; `economy` pools economy-* and server-authoritative-inventory. Noisy: runs of several
# code versions and pack experiments are pooled.
FAMILY_PASS_RATES = {
    "animation": (37, 98), "building": (28, 37), "datastore": (25, 77), "docs": (6, 10), "economy": (0, 21),
    "engineering": (39, 82), "luau": (46, 56), "performance": (7, 35), "remote": (57, 127), "tool": (5, 11),
    "ui": (47, 120), "vfx": (39, 66), "world": (6, 10),
}
LOW_RATE = 0.35
MIN_SCORED = 6

_FAMILIES = (
    ("ui", re.compile(r"\b(gui|ui|screen ?gui|frame|button|layout|hud|menu|textlabel|uilistlayout|scrolling)\b", re.I)),
    ("remote", re.compile(r"\b(remote(?:event|function)?s?|exploit|anti-?cheat|rate.?limit|validat\w+ (?:the )?client)\b", re.I)),
    ("datastore", re.compile(r"\b(data ?stores?|session lock|save (?:and load )?(?:player )?data|leaderboard)\b", re.I)),
    ("animation", re.compile(r"\b(animat\w+|tween\w*|ik|keyframe)\b", re.I)),
    ("performance", re.compile(r"\b(performance|streaming|lag|optimi[sz]e|memory leak)\b", re.I)),
    ("economy", re.compile(r"\b(economy|inventory|shop|currency|tycoon)\b", re.I)),
    ("vfx", re.compile(r"\b(vfx|particle\w*|beam|trail)\b", re.I)),
)
_HARD = re.compile(r"\b(system|framework|from scratch|full game|simulator|tycoon|matchmaking|state machine|architecture|"
                   r"round (?:loop|system|machine)|multi-?(?:script|file)|several scripts|server and client|"
                   r"client and server|pathfinding|npc)\b", re.I)
_DEBUG = re.compile(r"\b(error(?! handling)|exception|traceback|stack trace|bug|broken|not working|doesn'?t work|"
                    r"crash\w*|nil value|attempt to|why (?:does|is|isn'?t))\b", re.I)
_EASY = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|what is|what's|what does|how do i|explain|can you explain|"
                   r"tell me)\b", re.I)
_SMALL_EDIT = re.compile(r"\b(rename|typo|change the (?:name|color|colour|value|number)|add a (?:comment|print)|"
                         r"bump|tweak)\b", re.I)
_SCRIPT_WORDS = re.compile(r"\b(?:module ?scripts?|local ?scripts?|server ?scripts?|\w+\.luau?)\b", re.I)


@dataclass(frozen=True)
class Plan:
    level: str = "off"
    tokens: int = 0
    why: str = ""

    @property
    def active(self) -> bool:
        return self.tokens > 0


def family_of(prompt: str) -> str:
    for name, pattern in _FAMILIES:
        if pattern.search(prompt):
            return name
    return ""


def low_pass_family(prompt: str, rates: dict | None = None) -> str:
    """The prompt's task family when its historical pass rate is low (enough scored runs), else ''."""
    family = family_of(prompt)
    passed, scored = (FAMILY_PASS_RATES if rates is None else rates).get(family, (0, 0))
    return family if family and scored >= MIN_SCORED and passed / scored < LOW_RATE else ""


def score(prompt: str, *, rates: dict | None = None) -> tuple[int, str]:
    """(difficulty points, reason). 0 = easy."""
    text = prompt or ""
    points, why = 0, []
    if _HARD.search(text):
        points += 2
        why.append("new system / multi-part work")
    if _DEBUG.search(text) and (len(text) > 120 or "```" in text):
        points += 2
        why.append("debugging")
    if len(_SCRIPT_WORDS.findall(text)) >= 2:
        points += 1
        why.append("several scripts")
    if len(text) > 500:
        points += 1
        why.append("long specification")
    family = low_pass_family(text, rates)
    if family:
        points += 1
        why.append(f"low historical pass rate ({family})")
    return points, ", ".join(why)


def plan_turn(mode: str, prompt: str, *, profile: str = "roblox", quick: bool = False,
              rates: dict | None = None) -> Plan:
    """The thinking budget of one turn. `off` and the quick model never think."""
    if mode not in ("auto", "always") or quick:
        return Plan(why="off" if mode not in ("auto", "always") else "quick model")
    if mode == "always":
        return Plan("large", LEVELS["large"], "always")
    if profile not in THINKING_PROFILES:
        return Plan(why=f"{profile} turn")
    text = prompt or ""
    points, why = score(text, rates=rates)
    if _EASY.search(text) and points < 2:
        return Plan(why="plain question")
    if _SMALL_EDIT.search(text) and len(text) < 300 and points < 2:
        return Plan(why="small edit")
    if len(text) < 160 and points < 2:
        return Plan(why="short request")
    level = "off" if points == 0 else "small" if points == 1 else "medium" if points == 2 else "large"
    return Plan(level, LEVELS[level], why or "easy")


def rung_budget(round_no: int, mode: str = "auto") -> int:
    """Thinking tokens of the check-fix loop's fix call in round `round_no` (1-based). A failed rung means the
    first try was too hard for a no-think answer, so every further round thinks longer. 0 when thinking is off."""
    if mode not in ("auto", "always") or round_no < 1:
        return 0
    return LADDER_BUDGETS[min(round_no, len(LADDER_BUDGETS)) - 1]


def request_fields(tokens: int) -> dict:
    """The llama.cpp body fields for a thinking budget; {} for none."""
    if tokens <= 0:
        return {}
    return {"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget_tokens": int(tokens)}


def merge_fields(fields: dict | None, tokens: int) -> dict:
    """`fields` (llama_request_fields) with the thinking fields added; chat_template_kwargs are merged."""
    merged = dict(fields or {})
    extra = request_fields(tokens)
    if extra:
        kwargs = dict(merged.get("chat_template_kwargs") or {})
        kwargs.update(extra.pop("chat_template_kwargs"))
        merged.update(extra, chat_template_kwargs=kwargs)
    return merged


def rates_from_results(result_files: list, suites: list) -> dict:
    """{family: (passed, scored)} from stored eval result files (star.evals schema) and their task suites."""
    import json
    category: dict = {}
    for path in suites:
        try:
            data = json.loads(open(path, encoding="utf-8").read())
        except (OSError, ValueError):
            continue
        for task in (data if isinstance(data, list) else data.get("tasks", []) if isinstance(data, dict) else []):
            if isinstance(task, dict) and "id" in task and "category" in task:
                category.setdefault(task["id"], str(task["category"]))
    totals: dict = {}
    for path in result_files:
        try:
            data = json.loads(open(path, encoding="utf-8").read())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
            continue
        for task_id, row in data["tasks"].items():
            if task_id in category and isinstance(row, dict) and row.get("status") in ("pass", "fail"):
                family = category[task_id].split("-")[0]
                passed, scored = totals.get(family, (0, 0))
                totals[family] = (passed + (row["status"] == "pass"), scored + 1)
    return totals


def main(argv=None) -> int:
    import argparse
    import glob
    from pathlib import Path
    parser = argparse.ArgumentParser(prog="python -m star.thinking_budget")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rates = sub.add_parser("rates", help="recompute FAMILY_PASS_RATES from stored eval runs")
    rates.add_argument("--runs", required=True, help="glob of result json files")
    rates.add_argument("--suites", required=True, type=Path, help="folder of suite json files")
    show = sub.add_parser("plan", help="print the plan for a prompt")
    show.add_argument("prompt")
    show.add_argument("--mode", default="auto", choices=MODES)
    args = parser.parse_args(argv)
    if args.cmd == "rates":
        files = [f for f in glob.glob(args.runs, recursive=True) if "quick" not in f]
        for family, (passed, scored) in sorted(rates_from_results(files, sorted(args.suites.glob("*.json"))).items()):
            print(f'    "{family}": ({passed}, {scored}),')
    else:
        print(plan_turn(args.mode, args.prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
