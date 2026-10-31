"""Grounding: which thing on screen does "the Send button" mean? Cheapest exact source first.

  1. uia            the front window's UI Automation tree (exact names and rectangles, no model, ~50-300 ms)
  2. local-vision   a grounding model on her own GPU through an OpenAI-style endpoint (grounding.VlmGrounder:
                    UI-TARS-1.5-7B Q4, Holo1.5, Qwen3-VL ... served by llama.cpp on 127.0.0.1)
  3. remote-vision  STAR's image model on the brain (star.vision.ask, the "star-fast" vision role), when her GPU has
                    no grounder loaded or it found nothing
Each finder is pluggable (anything with `name` and `find(obs, query, role)`); the chain returns the first hit and keeps
what every finder said, for the action log. A vision point that lands inside a UIA control snaps to that control, so
the click aims at the real control and the gates see its real name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import time
from typing import Callable, Protocol

from .grounding import Grounded, encode_png, parse_point
from .screen import Element


@dataclass(frozen=True)
class Grounding:
    element: Element
    source: str               # uia | local-vision | remote-vision | ...
    score: float = 1.0
    seconds: float = 0.0


@dataclass
class ChainResult:
    hit: Grounding | None
    tried: list[tuple[str, str]] = field(default_factory=list)     # (finder, what it said)


class Finder(Protocol):
    name: str

    def find(self, obs, query: str, role: str = "") -> Grounding | None: ...


class UiaFinder:
    name = "uia"

    def __init__(self, min_score: float = 0.85) -> None:
        self.min_score = min_score

    def find(self, obs, query: str, role: str = "") -> Grounding | None:
        best = obs.screen.find(query, role=role, limit=1)
        if best and best[0][0] >= self.min_score:
            return Grounding(best[0][1], self.name, best[0][0])
        return None


class VisionFinder:
    """Wraps any grounding.Grounder (locate(image, query) -> Grounded | None)."""

    def __init__(self, grounder, name: str = "local-vision", box: int = 24) -> None:
        self.grounder, self.name, self.box = grounder, name, box

    def find(self, obs, query: str, role: str = "") -> Grounding | None:
        if obs.image is None:
            return None
        found = self.grounder.locate(obs.image, query)
        if found is None:
            return None
        w, h = obs.image.size
        if not (0 <= found.x < w and 0 <= found.y < h):
            return None
        inside = [e for e in obs.screen.elements
                  if e.rect[0] <= found.x < e.rect[2] and e.rect[1] <= found.y < e.rect[3] and e.role != "window"]
        if inside:                                          # the smallest UIA control under the point
            el = min(inside, key=lambda e: e.width * e.height)
            return Grounding(el, self.name + "+uia", 0.8, found.seconds)
        b = self.box
        el = Element(0, query, role or "custom", (found.x - b, found.y - b, found.x + b, found.y + b), "vision")
        return Grounding(el, self.name, 0.6, found.seconds)


REMOTE_PROMPT = ("This is a {w}x{h} pixel screenshot of a Windows desktop. Give the pixel coordinate of the centre of: "
                 "{query}. Reply with JSON only: {{\"x\": X, \"y\": Y}}, or {{}} if it is not visible.")


class StarVisionGrounder:
    """grounding.Grounder through STAR's image model (star.vision.ask): the remote fallback when her GPU has none."""

    def __init__(self, settings=None, *, ask: Callable | None = None, max_side: int = 1280, timeout_s: float = 60.0):
        self.settings, self._ask, self.max_side, self.timeout_s = settings, ask, max_side, timeout_s

    def locate(self, image, query: str) -> Grounded | None:
        import base64
        b64, sent = encode_png(image, self.max_side)
        ask = self._ask
        settings = self.settings
        if ask is None:                                     # pragma: no cover - the real brain
            from ..vision import ask
            if settings is None:
                from ..desktop_core import Settings, app_data
                settings = Settings.load(app_data() / "settings.json")
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "screen.png"
            png.write_bytes(base64.b64decode(b64))
            seen = ask(settings, REMOTE_PROMPT.format(w=sent[0], h=sent[1], query=query), [png], max_tokens=60,
                       timeout=self.timeout_s)
        text = getattr(seen, "text", seen)
        point = parse_point(str(text))
        if point is None:
            return None
        return Grounded(round(point[0] * image.size[0] / sent[0]), round(point[1] * image.size[1] / sent[1]),
                        str(text)[:120], time.perf_counter() - started)


class GroundingChain:
    def __init__(self, finders: list) -> None:
        self.finders = list(finders)

    def ground(self, obs, query: str, role: str = "") -> ChainResult:
        result = ChainResult(None)
        for finder in self.finders:
            try:
                hit = finder.find(obs, query, role)
            except Exception as why:                       # a model server down is a miss, not a crash
                result.tried.append((finder.name, f"error {type(why).__name__}"))
                continue
            if hit is not None:
                result.tried.append((finder.name, f"hit {hit.element.name[:40]!r}"))
                result.hit = hit
                return result
            result.tried.append((finder.name, "miss"))
        return result


def default_chain(cfg: dict, *, local=None, remote=None) -> GroundingChain:
    """UIA, then the GPU grounder if configured, then STAR's remote vision if computer.json "remote_vision" is on."""
    finders: list = [UiaFinder()]
    if local is not None:
        finders.append(VisionFinder(local, "local-vision"))
    if remote is not None or cfg.get("remote_vision"):
        finders.append(VisionFinder(remote or StarVisionGrounder(), "remote-vision"))
    return GroundingChain(finders)


def bench(cases: list[dict], grounders: dict, load_image: Callable | None = None) -> dict:
    """STAR's own grounding benchmark: each case {"image": path or PIL image, "query": "...", "rect": [l, t, r, b]}
    (screens of her real apps, recorded on her PC). A hit = the point lands inside rect. Per grounder: hits, cases,
    hit rate and the median seconds per question. Pick the grounder by this, not by published scores (they conflict)."""
    from statistics import median
    if load_image is None:
        from PIL import Image

        def _open(ref):
            return Image.open(ref).convert("RGB")
        load_image = _open
    loader = load_image
    images = [c["image"] if hasattr(c["image"], "size") else loader(c["image"]) for c in cases]
    out = {}
    for name, grounder in grounders.items():
        hits, times, misses = 0, [], []
        for case, image in zip(cases, images):
            started = time.perf_counter()
            try:
                found = grounder.locate(image, case["query"])
            except Exception as why:
                found, why_text = None, type(why).__name__
            else:
                why_text = "no point"
            times.append(time.perf_counter() - started)
            l, t, r, b = case["rect"]
            if found is not None and l <= found.x < r and t <= found.y < b:
                hits += 1
            else:
                misses.append(f"{case['query']}: " + (f"({found.x},{found.y})" if found is not None else why_text))
        out[name] = {"hits": hits, "cases": len(cases), "hit_rate": round(hits / max(1, len(cases)), 3),
                     "median_s": round(median(times), 3) if times else 0.0, "misses": misses[:20]}
    return out
