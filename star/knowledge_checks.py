"""Checks for answers that are not code (knowledge school, 2026-10-18).

A practice or evaluation task may carry `auto.answer`, a key the model's text is checked against. Six kinds:

  exact    {"accept": ["Paris"]}                        the final answer names one of the accepted strings
  numeric  {"value": 6, "tol": 0.05} or {"rel": 0.02}  a number in the final answer is within the tolerance
  choice   {"options": {"A": "...", ...}, "correct": "B"} the final answer picks exactly that option (letter or text)
  order    {"items": ["sketch", "model", "rig"]}         the items appear in this order (each item is a regex)
  match    {"pairs": [["hue", "colour family"], ...]}   each pair appears together in one sentence or line
  short    {"required": [["fact", "alt"], ...], "min_required": k, "forbidden": [...], "min_words": n}
           ("rubric" is the same kind under the name used for multi-step tasks)

The "final answer" is what follows the last `Answer:` / `Final answer:` marker; without a marker, the last
paragraph of the text. Prompts tell the model to end with `Answer: ...`. Everything here is pure text work and is
called from star.eval_checks.score_answer through the `answer` key, so night school and the evaluation runner score
these tasks with the same code and the same reference/trivial controls (tests/test_knowledge_checks.py).
"""
from __future__ import annotations

import re
from typing import Iterable

from .eval_checks import Check, prose_of, split_answer

KINDS = ("exact", "numeric", "choice", "order", "match", "short", "rubric")
_MARKER = re.compile(r"(?:^|\n)\s*\**\s*(?:final\s+answer|answer)\s*\**\s*[:\-]\s*\**", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])|(?<![\w.])[-+]?\.\d+")
_FRACTION = re.compile(r"(?<![\w/])(\d+)\s*/\s*(\d+)(?![\w/])")
_LETTER = re.compile(r"(?<![A-Za-z])\(?([A-H])(?:\)|\.|:|\b)")


def model_text(answer: str) -> str:
    """The model's own prose: no thinking block, no fenced code, no STAR footer."""
    body, _ = split_answer(answer or "")
    return prose_of(_THINK.sub(" ", body))


def final_answer(text: str) -> str:
    """What follows the last answer marker, else the last non-empty paragraph."""
    hits = list(_MARKER.finditer(text))
    if hits:
        return text[hits[-1].end():].strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs[-1] if paragraphs else text.strip()


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9%./+\- ]+", " ", text)
    return " ".join(text.split())


def numbers_in(text: str) -> list[float]:
    found: list[float] = []
    for whole, part in _FRACTION.findall(text):
        if int(part):
            found.append(int(whole) / int(part))
    text = _FRACTION.sub(" ", text)
    for raw in _NUMBER.findall(text):
        try:
            found.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return found


def _regex(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


def _found_any(text: str, alternatives: Iterable[str]) -> bool:
    return any(_regex(p).search(text) for p in alternatives)


def check_exact(key: dict, text: str) -> Check:
    region = normalize(final_answer(text))
    accepted = [normalize(a) for a in key.get("accept", []) if normalize(a)]
    if key.get("whole"):          # the final answer's first line is exactly one accepted value (guess lists fail)
        lines = final_answer(text).strip().splitlines()
        first_line = normalize(lines[0] if lines else "").strip("* ").rstrip(" .")
        ok = first_line in accepted
    else:
        ok = any(re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", region) for a in accepted)
    return Check("answer:exact", ok, "" if ok else f"final answer {region[:60]!r} is not one of {accepted[:3]}")


def check_numeric(key: dict, text: str) -> Check:
    region = final_answer(text)
    values = numbers_in(region)
    want = float(key["value"])
    tol = float(key.get("tol", 0.0))
    if "rel" in key:
        tol = max(tol, abs(want) * float(key["rel"]))
    if "unit" in key and key["unit"] and not _regex(key["unit"]).search(region):
        return Check("answer:numeric", False, f"the final answer does not state the unit /{key['unit']}/")
    if key.get("first"):          # only the first number of the final answer counts (a list of guesses fails)
        values = values[:1]
    ok = any(abs(v - want) <= tol + 1e-9 for v in values)
    return Check("answer:numeric", ok, "" if ok else f"no number within {tol:g} of {want:g} in {region[:60]!r}")


def check_choice(key: dict, text: str) -> Check:
    region = final_answer(text)
    correct = str(key["correct"]).strip().upper()
    options = {str(k).upper(): str(v) for k, v in (key.get("options") or {}).items()}
    letters = {m.group(1).upper() for m in _LETTER.finditer(region) if m.group(1).upper() in options}
    if letters:
        ok = letters == {correct}
        return Check("answer:choice", ok, "" if ok else f"chose {sorted(letters)}, correct is {correct}")
    norm = normalize(region)
    named = {k for k, v in options.items() if normalize(v) and normalize(v) in norm}
    ok = named == {correct}
    return Check("answer:choice", ok, "" if ok else "the final answer names no single option" if not named
                 else f"named {sorted(named)}, correct is {correct}")


def check_order(key: dict, text: str) -> Check:
    region = final_answer(text)
    items = key.get("items") or []
    positions = []
    for item in items:
        hit = _regex(item).search(region)
        if hit is None:
            return Check("answer:order", False, f"item /{item}/ is missing from the final answer")
        positions.append(hit.start())
    ok = all(a < b for a, b in zip(positions, positions[1:]))
    return Check("answer:order", ok, "" if ok else "the items are not in the required order")


def check_match(key: dict, text: str) -> Check:
    units = [u for u in re.split(r"\n|(?<=[.;!?])\s+", text) if u.strip()]
    missing = []
    for left, right in key.get("pairs") or []:
        if not any(_regex(left).search(u) and _regex(right).search(u) for u in units):
            missing.append(f"{left} -> {right}")
    ok = not missing
    return Check("answer:match", ok, "" if ok else "pairs not matched: " + "; ".join(missing[:3]))


def check_short(key: dict, text: str, name: str = "short") -> list[Check]:
    checks: list[Check] = []
    required = key.get("required") or []
    hits = [_found_any(text, alts if isinstance(alts, list) else [alts]) for alts in required]
    need = int(key.get("min_required", len(required)))
    ok = sum(hits) >= need
    missing = [str(alts[0] if isinstance(alts, list) else alts) for alts, hit in zip(required, hits) if not hit]
    checks.append(Check(f"answer:{name}", ok, "" if ok else f"{sum(hits)}/{len(required)} required facts (need {need}); "
                        "missing: " + "; ".join(missing[:4])))
    for pattern in key.get("forbidden") or []:
        hit = _regex(pattern).search(text)
        checks.append(Check(f"answer:{name}:forbidden", hit is None,
                            "" if hit is None else f"contains {hit.group(0)[:40]!r}"))
    min_words = int(key.get("min_words", 0))
    if min_words:
        count = len(re.findall(r"[A-Za-z0-9']+", text))
        checks.append(Check(f"answer:{name}:length", count >= min_words,
                            "" if count >= min_words else f"{count} words, need at least {min_words}"))
    return checks


def answer_checks(key: dict, answer: str) -> list[Check]:
    """All checks of one answer key against one answer. Unknown kinds fail loudly (a task bug, not a model failure)."""
    kind = str(key.get("type", "")).lower()
    if kind not in KINDS:
        return [Check("answer:key", False, f"unknown answer type {kind!r}")]
    text = model_text(answer)
    if not text.strip():
        return [Check("answer:" + kind, False, "no answer text")]
    if kind == "exact":
        return [check_exact(key, text)]
    if kind == "numeric":
        return [check_numeric(key, text)]
    if kind == "choice":
        return [check_choice(key, text)]
    if kind == "order":
        return [check_order(key, text)]
    if kind == "match":
        return [check_match(key, text)]
    return check_short(key, text, name=kind)


def validate_key(key: dict) -> list[str]:
    """Problems with an answer key (star.eval_runner.validate_tasks refuses the task): bad type, missing fields,
    regexes that do not compile."""
    if not isinstance(key, dict):
        return ["the answer key is not an object"]
    problems = []
    kind = str(key.get("type", "")).lower()
    if kind not in KINDS:
        return [f"unknown answer type {kind!r}"]
    try:
        if kind == "exact" and not key.get("accept"):
            problems.append("exact needs accept")
        if kind == "numeric":
            float(key["value"])
            if "tol" not in key and "rel" not in key:
                problems.append("numeric needs tol or rel")
        if kind == "choice" and (str(key.get("correct", "")).upper() not in {str(k).upper() for k in key.get("options", {})}):
            problems.append("choice: correct is not one of the options")
        if kind == "order":
            for item in key.get("items") or ["<missing>"]:
                _regex(item)
            if len(key.get("items") or []) < 2:
                problems.append("order needs at least two items")
        if kind == "match":
            for left, right in key.get("pairs") or []:
                _regex(left), _regex(right)
            if len(key.get("pairs") or []) < 2:
                problems.append("match needs at least two pairs")
        if kind in ("short", "rubric"):
            for alts in key.get("required") or []:
                for p in (alts if isinstance(alts, list) else [alts]):
                    _regex(p)
            for p in key.get("forbidden") or []:
                _regex(p)
            if not key.get("required"):
                problems.append(f"{kind} needs required facts")
    except (KeyError, ValueError, TypeError, re.error) as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    return problems
