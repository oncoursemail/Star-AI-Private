"""Parametric part templates: shared types, parameter clamping and the two small planner prompts.

A template is trusted code that builds a complete model spec from a handful of parameters. The planner (a small
model with a 4096-token context) never writes coordinates: it (1) picks a template from one-line summaries and
(2) fills that template's parameters, colours and material kinds. Every value is clamped here, so any answer
(even an empty one) still builds a well-proportioned, attached, symmetric model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

_HEX = re.compile(r"#?[0-9a-fA-F]{6}\Z")


@dataclass(frozen=True)
class Param:
    kind: str  # num | int | bool | enum
    default: Any
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    doc: str = ""

    def coerce(self, value: Any) -> Any:
        if value is None:
            return self.default
        try:
            if self.kind == "bool":
                if isinstance(value, str):
                    return value.strip().lower() in ("1", "true", "yes", "on")
                return bool(value)
            if self.kind == "enum":
                v = str(value).strip().lower().replace(" ", "_")
                if v in self.choices:
                    return v
                for c in self.choices:  # "pointy ears" -> pointy
                    if c in v or v in c:
                        return c
                return self.default
            x = float(value)
            if x != x:
                return self.default
            if self.lo is not None:
                x = max(self.lo, x)
            if self.hi is not None:
                x = min(self.hi, x)
            return int(round(x)) if self.kind == "int" else round(x, 3)
        except (TypeError, ValueError):
            return self.default

    def describe(self) -> str:
        if self.kind == "enum":
            rng = "|".join(self.choices)
        elif self.kind == "bool":
            rng = "true|false"
        else:
            rng = f"{_fmt(self.lo)}..{_fmt(self.hi)}"
        return f"{rng} (default {_fmt(self.default)})" + (f": {self.doc}" if self.doc else "")


@dataclass(frozen=True)
class Role:
    color: str
    kind: str
    doc: str = ""


@dataclass(frozen=True)
class Template:
    name: str
    summary: str
    category: str
    params: dict
    roles: dict
    build: Callable[..., dict]
    keywords: tuple = ()
    extra: dict = field(default_factory=dict)


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def resolve(t: Template, answer: dict | None, kinds: tuple) -> tuple[dict, dict, list]:
    """Clamp a planner answer to the template. Returns (params, roles {role: {kind, color}}, notes)."""
    ans: dict = answer if isinstance(answer, dict) else {}
    notes: list[str] = []
    raw_p = ans.get("params") if isinstance(ans.get("params"), dict) else {}
    assert isinstance(raw_p, dict)
    params = {}
    for k, p in t.params.items():
        v = p.coerce(raw_p.get(k))
        if k in raw_p and v != raw_p[k] and not (p.kind in ("num", "int") and _close(v, raw_p[k])):
            notes.append(f"{k}: {raw_p[k]!r} -> {v!r}")
        params[k] = v
    unknown = [k for k in raw_p if k not in t.params]
    if unknown:
        notes.append("ignored params: " + ", ".join(map(str, unknown[:8])))
    raw_c = ans.get("colors") if isinstance(ans.get("colors"), dict) else {}
    raw_k = ans.get("kinds") if isinstance(ans.get("kinds"), dict) else {}
    assert isinstance(raw_c, dict) and isinstance(raw_k, dict)
    roles = {}
    for r, d in t.roles.items():
        c = raw_c.get(r)
        color = ("#" + str(c).lstrip("#").lower()) if isinstance(c, str) and _HEX.match(c.strip()) else d.color
        k = str(raw_k.get(r, d.kind)).strip().lower()
        roles[r] = {"color": color, "kind": k if k in kinds else d.kind}
    return params, roles, notes


def _close(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def pick_by_keywords(templates: dict, brief: str) -> str:
    """Deterministic fallback: the template whose keywords match the brief best (first one on a tie)."""
    words = set(re.findall(r"[a-z]+", brief.lower()))
    best, score = next(iter(templates)), 0
    for name, t in templates.items():
        s = sum(2 if " " not in k and k in words else (1 if k in brief.lower() else 0) for k in t.keywords)
        if s > score:
            best, score = name, s
    return best


PICK_SYSTEM = """You choose which model template builds a brief best. Templates (name: what it builds):
{lines}
Pick the template whose SHAPE fits the object (a sheep is a quadruped, a penguin a bird, a golem a biped, a
birdbath or cauldron a vessel). Reply with JSON only: {{"template": "<name>"}}"""

FILL_SYSTEM = """You set the parameters of a trusted 3D model template so the result matches a brief.
Template "{name}": {summary}
Parameters (name: allowed values (default): meaning):
{params}
Colour roles (name: default colour, default material: meaning):
{roles}
Material kinds: {kinds}
Choose values that make the object read clearly at a glance: proportions typical for the real thing, options that
the brief names switched on, a small harmonious palette (muted to mid saturation, one accent; no pure black or
white). Omit anything you would leave at its default.
Reply with JSON only: {{"name": "snake_case_name", "params": {{...}}, "colors": {{"<role>": "#rrggbb"}},
"kinds": {{"<role>": "<kind>"}}}}"""


def pick_prompt(templates: dict, brief: str, extra: str = "") -> list:
    lines = "\n".join(f"- {n}: {t.summary}" for n, t in templates.items())
    user = f"Brief: {brief}" + (f"\n{extra}" if extra else "")
    return [{"role": "system", "content": PICK_SYSTEM.format(lines=lines)}, {"role": "user", "content": user}]


def fill_prompt(t: Template, brief: str, kinds: tuple, extra: str = "") -> list:
    params = "\n".join(f"- {k}: {p.describe()}" for k, p in t.params.items())
    roles = "\n".join(f"- {k}: {r.color}, {r.kind}" + (f": {r.doc}" if r.doc else "") for k, r in t.roles.items())
    sys = FILL_SYSTEM.format(name=t.name, summary=t.summary, params=params, roles=roles, kinds=", ".join(kinds))
    user = f"Brief: {brief}" + (f"\n{extra}" if extra else "")
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def extract_json(text: str) -> dict:
    """First JSON object in a reply (tolerates code fences and trailing commas)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = t[start:i + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    return json.loads(re.sub(r",\s*([}\]])", r"\1", chunk))
    raise ValueError("unterminated JSON object in reply")


def _variant_from_brief(t: Template, brief: str, answer: dict) -> dict:
    """When the fill answer gives no variant (a failed or truncated reply), use a variant the brief names, e.g.
    'revolver' -> firearm variant revolver, instead of silently building the default (an assault rifle)."""
    var = t.params.get("variant")
    params = answer.get("params")
    raw: dict = params if isinstance(params, dict) else {}
    if var is None or var.kind != "enum" or "variant" in raw:
        return answer
    words = set(re.findall(r"[a-z]+", brief.lower()))
    hit = next((c for c in var.choices if c in words), None)
    if hit is None:
        return answer
    return dict(answer, params=dict(raw, variant=hit))


def plan(llm, brief: str, templates: dict, kinds: tuple, *, extra: str = "", template: str | None = None,
         seed: int = 7) -> dict:
    """Two small calls: pick a template, then fill it. Network or parse failures fall back to keywords/defaults.

    `llm.chat(messages, max_tokens=, temperature=, seed=)` must return (text, seconds, usage)."""
    log: list = []
    name = template if template in templates else None
    if name is None:
        try:
            text, secs, _ = llm.chat(pick_prompt(templates, brief, extra), max_tokens=60, temperature=0.0, seed=seed)
            got = str(extract_json(text).get("template", "")).strip().lower()
            name = got if got in templates else None
            log.append({"step": "pick", "seconds": round(secs, 1), "answer": got})
        except Exception as exc:  # noqa: BLE001 - fall back to keywords, never lose the brief
            log.append({"step": "pick", "error": f"{type(exc).__name__}: {exc}"[:200]})
        if name is None:
            name = pick_by_keywords(templates, brief)
            log.append({"step": "pick", "fallback": name})
    t = templates[name]
    answer: dict = {}
    try:
        text, secs, _ = llm.chat(fill_prompt(t, brief, kinds, extra), max_tokens=700, temperature=0.3, seed=seed)
        answer = extract_json(text)
        log.append({"step": "fill", "seconds": round(secs, 1)})
    except Exception as exc:  # noqa: BLE001
        log.append({"step": "fill", "error": f"{type(exc).__name__}: {exc}"[:200]})
    answer = _variant_from_brief(t, brief, answer)
    params, roles, notes = resolve(t, answer, kinds)
    nm = re.sub(r"[^a-z0-9_]+", "_", str(answer.get("name") or name).lower()).strip("_")[:40] or name
    return {"template": name, "name": nm, "params": params, "roles": roles, "notes": notes, "log": log,
            "answer": answer}
