"""Prompt rewriter for image generation: a short request becomes a model-ready picture prompt.

Star's fast brain expands "a real cow" into subject, anatomy-correct pose, composition, lighting, style and
what to avoid, and decides whether the picture needs readable text. Text is never left to the image model:
the rewriter asks for a blank area and lists the exact words, which `star.image_post` draws afterwards.
Every failure (brain down, bad JSON, timeout) falls back to the owner's own words, so drawing never breaks here.
Results are cached per request in memory, so the repair round and a repeated request cost no brain call.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_PROMPT = 1400          # image_gen.generate accepts 1500
WHERES = ('top', 'center', 'bottom', 'top-left', 'top-right', 'bottom-left', 'bottom-right')
STYLES = ('pixel', 'bold', 'plain')

SYSTEM = """You write prompts for a text-to-image model (FLUX.2 klein / Z-Image Turbo). Answer with ONE JSON object only.
Fields:
"prompt": 45-80 words of plain English. Subject first, then the pose and action, composition and framing, setting,
  lighting, camera or art style. Positive phrasing only (the model ignores "no X"). For animals and people state the
  anatomy outright and the pose that shows it (for example "full-body side view of a Holstein cow standing on grass, four
  legs visible, one head, two ears, one tail"). Never put words in quotes or ask the model to write text.
"aspect": "square", "wide" (screens, scenes, landscapes) or "tall" (portraits, posters).
"overlays": a list of text the picture must show, exactly as the owner wants it, [] when none. Each item:
  {"text": "exact words", "where": one of top, center, bottom, top-left, top-right, bottom-left, bottom-right,
   "style": pixel (retro games, HUD, arcade), bold (titles, signs, posters) or plain}.
  When overlays exist, the "prompt" must describe the picture WITHOUT the text and say which area stays plain and empty
  (for example "the top band is an empty dark sky"). Game screenshots: draw the scene, put scores and labels in overlays.
"checks": exactly 3 short yes/no questions a careful viewer can answer from the picture alone (subject, key objects, setting,
  style). No questions about text.
Keep every fact the owner stated. Do not add people or animals they did not ask for. No explanations."""

_CACHE: OrderedDict[str, 'Plan'] = OrderedDict()
_CACHE_MAX = 64


@dataclass(frozen=True)
class Overlay:
    text: str
    where: str = 'bottom'
    style: str = 'bold'


@dataclass(frozen=True)
class Plan:
    request: str
    prompt: str
    aspect: str = ''
    overlays: tuple[Overlay, ...] = ()
    checks: tuple[str, ...] = ()
    rewritten: bool = False                 # False = the owner's own words (rewriter off or failed)
    notes: list[str] = field(default_factory=list, compare=False, hash=False)

    def as_note(self) -> dict:
        return {'rewritten': self.rewritten, 'prompt': self.prompt, 'aspect': self.aspect,
                'overlays': [o.__dict__ for o in self.overlays], 'checks': list(self.checks)}


def parse_json(text: str):
    """The first JSON object in a model's reply (code fences and chatter around it are ignored), or None."""
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r'```(?:json)?', '', text)
    start = cleaned.find('{')
    while start != -1:
        depth, in_text, escaped = 0, False, False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_text:
                escaped = (char == '\\') and not escaped
                if char == '"' and not escaped:
                    in_text = False
                continue
            if char == '"':
                in_text = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(cleaned[start:index + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
        start = cleaned.find('{', start + 1)
    return None


def _clean(value, limit: int) -> str:
    return re.sub(r'\s+', ' ', value).strip()[:limit] if isinstance(value, str) else ''


def parse_plan(request: str, reply: str) -> Plan | None:
    """A Plan from the brain's reply, or None when it is unusable (the caller then keeps the owner's words)."""
    data = parse_json(reply)
    if not data:
        return None
    prompt = _clean(data.get('prompt'), MAX_PROMPT)
    if len(prompt) < 20:
        return None
    overlays = []
    for item in data.get('overlays') or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get('text'), 60)
        if not text:
            continue
        where = _clean(item.get('where'), 20).lower()
        style = _clean(item.get('style'), 10).lower()
        overlays.append(Overlay(text, where if where in WHERES else 'bottom', style if style in STYLES else 'bold'))
    checks = tuple(q for q in (_clean(x, 160) for x in (data.get('checks') or [])[:6] if isinstance(x, str)) if q)
    aspect = _clean(data.get('aspect'), 10).lower()
    return Plan(request, prompt, aspect if aspect in ('square', 'wide', 'tall') else '', tuple(overlays[:6]),
                checks, rewritten=True)


def raw_plan(request: str, why: str = '') -> Plan:
    """The owner's words unchanged. Quoted words are drawn by STAR rather than asked of the image model."""
    quoted = [q for q in re.findall(r'"([^"\n]{1,40})"|“([^”\n]{1,40})”', request) for q in q if q]
    overlays = tuple(Overlay(q.strip(), 'bottom', 'bold') for q in quoted[:3] if q.strip())
    prompt = request.strip()
    for q in quoted:
        prompt = prompt.replace(f'"{q}"', '').replace(f'“{q}”', '')
    plan = Plan(request, re.sub(r'\s+', ' ', prompt).strip() or request.strip(), overlays=overlays)
    if why:
        plan.notes.append(why)
    return plan


def brain_text(settings, system: str, user: str, *, max_tokens: int = 400, timeout: float = 100.0) -> str:
    """One short, direct question to the fast brain (no chat history, no tools, no hidden reasoning)."""
    from . import server_roles
    from .providers import open_client, provider_kind
    model = server_roles.quick_model(server_roles.effective(settings), getattr(settings, 'model', ''))
    if not model:
        raise ValueError('No model is selected')

    async def run() -> str:
        own = provider_kind(settings) in ('lan', 'local')
        extra = {'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}} if own else {}
        async with open_client(settings, request_timeout=timeout) as client:
            reply = await asyncio.wait_for(client.chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=0.4,
                messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], **extra),
                timeout=timeout)
            return (reply.choices[0].message.content or '').strip()
    return asyncio.run(run())


def rewrite(settings, request: str, *, ask=brain_text, use_cache: bool = True) -> Plan:
    """The plan for `request`. `ask(settings, system, user)` is the brain call (a fake in tests)."""
    request = (request or '').strip()
    if not request:
        raise ValueError('Image request is empty')
    key = request.lower()
    if use_cache and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    try:
        plan = parse_plan(request, ask(settings, SYSTEM, f'Owner request: {request}'))
        if plan is None:
            plan = raw_plan(request, 'rewriter reply was not usable')
    except Exception as exc:        # brain down, timeout, no model: drawing must still work
        plan = raw_plan(request, f'rewriter unavailable ({type(exc).__name__})')
    if plan.rewritten:              # a fallback is not cached, so the next try asks the brain again
        _CACHE[key] = plan
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return plan


def repaired(plan: Plan, issues: list[str]) -> Plan:
    """The same plan with the judge's complaints turned into positive wording, for the one repair round."""
    fixes = '; '.join(dict.fromkeys(issues))[:300]
    extra = f' Correct anatomy and structure: {fixes}.' if fixes else ''
    from dataclasses import replace
    return replace(plan, prompt=(plan.prompt + extra)[:MAX_PROMPT])
