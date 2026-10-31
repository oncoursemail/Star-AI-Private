"""The numbers after every batch: plain text, at most 4000 characters, no addresses and no keys.
Another system on the owner's PC reads this file and hands it to ChatGPT, which writes fixes and new practice
tasks from it, so it says what failed and why in words, not only counts."""
from __future__ import annotations

import os
from pathlib import Path

from .engine import scrub, utc
from . import insights

LIMIT = 4000


def build(state: dict, *, status: str = "") -> str:
    c = state.get("counters", {})
    tried = c.get("tasks_tried", 0)
    distinct = len([t for t in state.get("tasks", {}).values() if t.get("tries")])
    answers = c.get("answers", 0)
    seconds = state.get("answer_seconds", 0.0)
    lessons = state.get("lessons", {})
    by_status: dict[str, list] = {}
    for lesson in lessons.values():
        by_status.setdefault(lesson["status"], []).append(lesson)
    latest: dict[str, int] = {}
    for task in state.get("tasks", {}).values():
        if task.get("status"):
            latest[task["status"]] = latest.get(task["status"], 0) + 1
    lines = [
        "# STAR night school: latest numbers",
        f"written {utc()} | started {state.get('started', '?')} | batches {state.get('batches', 0)}",
        ("status: " + status) if status else "",
        "",
        "What this is: STAR answers practice Roblox tasks by itself while the server is idle. Checks are automatic",
        "(static Luau check, unit tests in a Luau VM with stand-ins for Roblox classes, required patterns); nothing is",
        "run in Roblox Studio. The model's weights are not changed.",
        "",
        "## Practice",
        "pool: " + (state.get("pool") or "not loaded"),
        f"task attempts: {tried} on {distinct} different tasks",
        f"passed first time: {c.get('passed_first', 0)}",
        f"fixed by a lesson: {c.get('fixed_by_lesson', 0)}",
        f"still failing after the lesson step: {c.get('still_failing', 0)}",
        "tasks by their latest attempt: " + (", ".join(f"{name.replace('_', ' ')} {count}" for name, count in sorted(latest.items())) or "none yet"),
        f"checks could not run (not counted as failures): {c.get('infrastructure_errors', 0)}",
        f"backed off because another client appeared: {c.get('backed_off', 0)}",
        f"verified worked examples stored: {c.get('examples', 0)}",
        (f"speed: {answers} answers in {seconds / 3600:.2f} h of answer time = "
         f"{answers / (seconds / 3600):.1f} answers per active hour" if seconds > 0 else "speed: no answers yet"),
        "",
        "## Lessons",
        f"proposed by the model: {c.get('lessons_proposed', 0)} | kept as candidate (fixed its task): "
        f"{c.get('candidates_kept', 0)} | discarded (task still failed): {c.get('lessons_discarded', 0)}",
        f"promoted to active: {c.get('lessons_promoted', 0)} | held back by validation: "
        f"{c.get('lessons_held_back', 0)} | retired later: {c.get('lessons_retired', 0)}",
        f"paired gate inconclusive (below the noise floor, kept as candidate): {c.get('lessons_inconclusive', 0)}",
    ]
    lines.extend(["", *insights.build(state), ""])
    lesson_lines = []
    for lesson in sorted(by_status.get("active", []), key=lambda l: l.get("promoted", ""))[-6:]:
        proof = lesson.get("promotion", {})
        lesson_lines.append(f"- active {lesson['id']}: {lesson['text'][:170]} (fixed {len(set(lesson['fixed']))} tasks; "
                     f"validation {proof.get('validation_before', '?')} -> {proof.get('validation_with', '?')}"
                     + (f", p={proof['gate'].get('p_better')}" if isinstance(proof.get("gate"), dict) else ", old rule")
                     + ")")
    for lesson in sorted(by_status.get("candidate", []), key=lambda l: -len(l["fixed"]))[:4]:
        lesson_lines.append(f"- candidate {lesson['id']}: {lesson['text'][:140]} (fixed {len(set(lesson['fixed']))})")
    for lesson in by_status.get("retired", [])[-3:]:
        lesson_lines.append(f"- retired {lesson['id']}: {lesson['text'][:110]} ({lesson.get('retirement', {}).get('validation_now', '?')})")
    validation_lines = []
    history = state.get("validation", [])
    if history:
        for row in history[-8:]:
            validation_lines.append(f"- {row['ts']}: {row['passed']}/{row['total']} with {len(row.get('active_lessons', []))} "
                         f"lesson(s) ({row.get('why', '')})")
    else:
        validation_lines.append("- not measured yet")
    cause_lines = []
    causes = sorted(state.get("causes", {}).items(), key=lambda item: -item[1]["count"])[:10]
    if not causes:
        cause_lines.append("- none recorded yet")
    for name, entry in causes:
        cause_lines.append(f"- {entry['count']}x {name}. Example {entry.get('example', '')[:150]}"
                     + (f" Model's own explanation: {entry['model_says'][:110]}" if entry.get("model_says") else ""))
    shortened = False

    def render() -> str:
        sections = (lines + lesson_lines
                    + ["", "## Validation slice over time (tasks never used to write lessons)"] + validation_lines
                    + ["", "## Most common failure causes (first failed check; one example each)"] + cause_lines)
        if shortened:
            sections.append("(detail shortened to fit 4000 characters)")
        return scrub("\n".join(line for line in sections if line is not None)).strip() + "\n"

    text = render()
    # Trim optional detail before cutting diagnostics off. Retain an active lesson
    # when present, the latest validation row and the leading failure example.
    while len(text) > LIMIT and (len(lesson_lines) > 1 or len(validation_lines) > 1 or len(cause_lines) > 1):
        if len(lesson_lines) > 1:
            lesson_lines.pop()
        elif len(validation_lines) > 1:
            validation_lines.pop(0)
        else:
            cause_lines.pop()
        shortened = True
        text = render()
    if len(text) > LIMIT:
        text = text[:LIMIT - 30].rsplit("\n", 1)[0] + "\n(cut to 4000 characters)\n"
    return text


def write(path: Path, state: dict, *, status: str = "") -> str:
    text = build(state, status=status)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)
    return text
