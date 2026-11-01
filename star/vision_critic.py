"""Vision critic client: `score()`, `prefer()` and `issues()` for the visual pipelines.

The critic is a small vision-language model served by llama.cpp (OpenAI-compatible /v1/chat/completions) on a host
of its own (see docs/agents/vision-critic-20261029.md for the live endpoint). The design was chosen on an offline
benchmark built from blind Opus judging (pairs with a clear judge preference), not by taste:

* every verdict is read from log-probabilities, never from free text (reading an integer from text is what made
  the earlier critic pick the judge-preferred round only 8/15 times);
* `prefer()` (default method "pairwise") shows both arms and reads p(A) vs p(B), asked in both presentation orders
  and averaged, which cancels the model's position bias; `consistent` says whether both orders agreed (keep only
  consistent verdicts when you need certainty). Held-out test with Qwen3-VL-8B: 46/55 = 84% agreement with the
  judges (CI 72-91%); consistent-only 83% at 75% coverage;
* `score()` (one digit 1-9, expected value over the digit probabilities) is cheaper for ranking many candidates
  but agreed only 62% on the test split (4B; 94% on dev did not hold): use it for coarse filtering, not for picks;
* a short per-domain checklist (brief match, proportions, floating parts, silhouette, readability...) goes into the
  prompt, plus the caller's measured facts when given. Pixel facts ("almost blank") are off by default: on the
  benchmark's dev split they lowered agreement (85% -> 76%).

Configuration (environment): STAR_VISION_CRITIC_URL (base URL, no trailing /v1), STAR_VISION_CRITIC_KEY or the key
file STAR_VISION_CRITIC_KEY_FILE (default ~/.star/vision_critic_key), STAR_VISION_CRITIC_MODEL (default "critic").
Standard library + Pillow only. Raises CriticUnavailable quickly when the host is busy/off (connection refused,
503) so a pipeline can carry on without a critique.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from PIL import Image, ImageDraw, ImageStat

ImageLike = "str | Path | bytes | Image.Image"

CHECKLISTS: dict[str, list[str]] = {
    "generic": [
        "matches the brief: every named part or element is visible and recognisable",
        "readable silhouette and shape at a glance",
        "believable proportions",
        "no broken output: blank, black, cut-off, clipped or garbled images",
        "overall craft and finish",
    ],
    "blockbench": [
        "reads as the brief (the named object, its key parts present: e.g. basin, candle, liquid)",
        "silhouette recognisable from the front and side views",
        "proportions and part sizes believable for Minecraft-style models",
        "no floating or detached cubes, no parts poking through each other",
        "texture: clear pixel-art colours and detail, not flat or noisy",
    ],
    "3d-assets": [
        "reads as the brief object (a pistol looks like a pistol, not a box or stapler)",
        "proportions of the main parts are right (grip, barrel, legs, wheels...)",
        "no floating, detached or intersecting parts",
        "form detail: bevels, panel lines, sub-parts instead of plain boxes",
        "materials and colours match the brief",
    ],
    "roblox-build": [
        "the map shows what the brief asks for (the named buildings, props and landmarks)",
        "camera shots show the scene clearly (not inside walls, trees or black)",
        "layout reads as a playable, coherent place, not scattered boxes",
        "lighting and mood fit the brief; scene not murky or washed out",
        "detail and style consistency",
    ],
    "ui": [
        "an actual working UI is visible (not an empty frame, blank box or error)",
        "matches the brief: the asked screens, panels, items and labels",
        "clear hierarchy and readable text at desktop, tablet and phone sizes",
        "nothing clipped or overflowing on small screens",
        "themed, polished look rather than generic boxes",
    ],
    "lighting": [
        "the mood and time of day match the brief",
        "scene is readable: not too dark, not washed out",
        "light sources, colour and atmosphere feel intentional",
        "pleasing contrast and depth",
    ],
    "vfx": [
        "the effect is clearly visible in the frames (not empty or a tiny speck)",
        "it reads as the brief (fireball, slash, portal...) with the right colours",
        "shape and motion progress over the frames",
        "polish: layered particles, glow, no single flat blob",
    ],
}
DOMAIN_ALIASES = {"shapes": "3d-assets", "shapes-templates": "3d-assets", "props": "3d-assets", "asset3d": "3d-assets",
                  "roblox-scenes": "roblox-build", "roblox": "roblox-build", "map": "roblox-build",
                  "ui-vfx:ui": "ui", "ui-vfx:lighting": "lighting", "ui-vfx:vfx": "vfx", "minecraft": "blockbench"}


class CriticUnavailable(RuntimeError):
    """The critic host is off, busy (its owner is gaming) or overloaded; carry on without a critique."""


def checklist(domain: str) -> list[str]:
    d = DOMAIN_ALIASES.get(domain, domain)
    return CHECKLISTS.get(d, CHECKLISTS["generic"])


# ---------------------------------------------------------------- images
def load_image(x: Any) -> Image.Image:
    if isinstance(x, Image.Image):
        return x.convert("RGB")
    if isinstance(x, (bytes, bytearray)):
        return Image.open(io.BytesIO(x)).convert("RGB")
    return Image.open(Path(x)).convert("RGB")


def tile(images: Sequence[Any], max_side: int = 768) -> Image.Image:
    """One sheet per arm: up to 2 columns, scaled so the longest side is max_side."""
    ims = [load_image(i) for i in images]
    if not ims:
        raise ValueError("no images")
    if len(ims) == 1:
        sheet = ims[0]
    else:
        cols = 2 if len(ims) > 1 else 1
        rows = math.ceil(len(ims) / cols)
        w = max(i.width for i in ims); h = max(i.height for i in ims)
        sheet = Image.new("RGB", (cols * w, rows * h), (24, 24, 24))
        for k, im in enumerate(ims):
            sheet.paste(im, ((k % cols) * w, (k // cols) * h))
    s = max_side / max(sheet.size)
    if s < 1:
        sheet = sheet.resize((max(1, round(sheet.width * s)), max(1, round(sheet.height * s))), Image.LANCZOS)
    return sheet


def side_by_side(a: Image.Image, b: Image.Image, labels: tuple[str, str] = ("A", "B")) -> Image.Image:
    h = max(a.height, b.height); bar = 28
    out = Image.new("RGB", (a.width + b.width + 12, h + bar), (12, 12, 12))
    out.paste(a, (0, bar)); out.paste(b, (a.width + 12, bar))
    d = ImageDraw.Draw(out)
    d.text((8, 6), labels[0], fill=(255, 255, 255)); d.text((a.width + 20, 6), labels[1], fill=(255, 255, 255))
    return out


def data_url(im: Image.Image, quality: int = 88) -> str:
    buf = io.BytesIO(); im.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def pixel_facts(images: Sequence[Any]) -> str:
    """Measured facts a small model misses: near-blank or near-black renders, how much of the frame has content."""
    parts = []
    for k, x in enumerate(images):
        im = load_image(x); small = im.resize((96, max(1, round(96 * im.height / im.width))))
        raw = small.tobytes(); px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]; n = len(px)
        border = [small.getpixel((0, 0)), small.getpixel((small.width - 1, 0)), small.getpixel((0, small.height - 1)),
                  small.getpixel((small.width - 1, small.height - 1))]
        bg = tuple(sorted(c[i] for c in border)[1] for i in range(3))
        content = sum(1 for p in px if sum(abs(p[i] - bg[i]) for i in range(3)) > 40) / n
        lum = ImageStat.Stat(small.convert("L"))
        edges = small.convert("L").resize((48, max(1, small.height // 2)))
        e = list(edges.tobytes()); ew = edges.width
        edge = sum(1 for i in range(len(e) - 1) if (i + 1) % ew and abs(e[i] - e[i + 1]) > 24) / max(1, len(e))
        tags = []
        if content < 0.03:
            tags.append("almost blank")
        if lum.mean[0] < 25:
            tags.append("very dark")
        if lum.stddev[0] < 8:
            tags.append("nearly uniform")
        parts.append(f"image {k + 1}: content {content:.0%} of frame, detail {edge:.2f}, brightness {lum.mean[0]:.0f}/255"
                     + (f" ({', '.join(tags)})" if tags else ""))
    return "; ".join(parts)


# ---------------------------------------------------------------- transport
def _config() -> tuple[str, str, str]:
    url = os.environ.get("STAR_VISION_CRITIC_URL", "").rstrip("/")
    key = os.environ.get("STAR_VISION_CRITIC_KEY", "")
    if not key:
        f = Path(os.environ.get("STAR_VISION_CRITIC_KEY_FILE", Path.home() / ".star" / "vision_critic_key"))
        if f.exists():
            key = f.read_text(encoding="utf-8").strip()
    return url, key, os.environ.get("STAR_VISION_CRITIC_MODEL", "critic")


Transport = Callable[[dict], dict]


def http_transport(url: str | None = None, key: str | None = None, timeout: float = 180.0) -> Transport:
    cu, ck, _ = _config()
    url = (url or cu).rstrip("/"); key = key if key is not None else ck
    if not url:
        raise CriticUnavailable("STAR_VISION_CRITIC_URL is not set")

    def send(body: dict) -> dict:
        req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {key}"} if key else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504):
                raise CriticUnavailable(f"critic host busy (HTTP {e.code})") from e
            raise RuntimeError(f"critic HTTP {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            raise CriticUnavailable(f"critic host unreachable: {e}") from e
    return send


def _letter_probs(resp: dict, letters: Iterable[str]) -> dict[str, float]:
    """Probability mass on each answer letter in the first generated token (case/space-insensitive)."""
    letters = list(letters); out = {L: 0.0 for L in letters}
    try:
        top = resp["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    except (KeyError, IndexError, TypeError):
        top = []
    for t in top:
        tok = str(t.get("token", "")).strip().strip("*\"'([").upper()
        if tok in out:
            out[tok] += math.exp(float(t.get("logprob", -99)))
    if not any(out.values()):  # no logprobs: fall back to the text
        text = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        m = re.search(r"\b(" + "|".join(letters) + r")\b", text.upper())
        if m:
            out[m.group(1)] = 1.0
    return out


# ---------------------------------------------------------------- prompts
SYSTEM = ("You are a strict art director judging game assets and scenes for a professional marketplace. "
          "You compare two candidates for the same brief and pick the one a demanding expert would prefer.")


def _pair_prompt(brief: str, domain: str, facts: tuple[str, str] | None, layout: str) -> str:
    cl = "\n".join(f"- {c}" for c in checklist(domain))
    where = ("The image shows candidate A on the left and candidate B on the right." if layout == "side"
             else "The first image is candidate A, the second image is candidate B.")
    f = ""
    if facts and any(facts):
        f = f"\nMeasured facts (trust these):\nA: {facts[0] or 'none'}\nB: {facts[1] or 'none'}\n"
    return (f"Brief: {brief}\n\n{where}\nJudge with this checklist, most important first:\n{cl}\n{f}\n"
            "A broken or empty render always loses. Which candidate is better overall? Answer with one letter: A or B.")


def _pair_messages(a: Image.Image, b: Image.Image, brief: str, domain: str, facts, layout: str) -> list[dict]:
    text = _pair_prompt(brief, domain, facts, layout)
    if layout == "side":
        imgs = [{"type": "image_url", "image_url": {"url": data_url(side_by_side(a, b))}}]
    else:
        imgs = [{"type": "text", "text": "Candidate A:"}, {"type": "image_url", "image_url": {"url": data_url(a)}},
                {"type": "text", "text": "Candidate B:"}, {"type": "image_url", "image_url": {"url": data_url(b)}}]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": imgs + [{"type": "text", "text": text}]}]


# ---------------------------------------------------------------- public API
def score(images: Sequence[Any], brief: str, domain: str = "generic", *, facts: str = "",
          use_pixel_facts: bool = False, max_side: int = 768, transport: Transport | None = None,
          model: str | None = None) -> dict:
    """Quality score of one candidate for the brief: {"score": 1.0-9.0 (expected value), "mass": probability on
    digits (low = the model did not answer a digit), "seconds"}. Scores are comparable across candidates of one brief."""
    send = transport or http_transport()
    model = model or _config()[2]
    sheet = tile(images, max_side)
    if use_pixel_facts:
        facts = "; ".join(x for x in (facts, pixel_facts(images)) if x)
    cl = "\n".join(f"- {c}" for c in checklist(domain))
    text = (f"Brief: {brief}\n\nRate this render against the checklist:\n{cl}\n"
            + (f"Measured facts (trust these): {facts}\n" if facts else "")
            + "\nScore from 1 (unusable) to 9 (marketplace quality). Answer with one digit.")
    body = {"model": model, "temperature": 0, "max_tokens": 1, "logprobs": True, "top_logprobs": 20,
            "cache_prompt": True,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url(sheet)}},
                                                      {"type": "text", "text": text}]}]}
    t0 = time.monotonic()
    pr = _letter_probs(send(body), "123456789"); tot = sum(pr.values())
    ev = sum(int(k) * v for k, v in pr.items()) / tot if tot else 5.0
    return {"score": round(ev, 4), "mass": round(tot, 4), "seconds": round(time.monotonic() - t0, 2)}


def prefer(a_images: Sequence[Any], b_images: Sequence[Any], brief: str, domain: str = "generic", *,
           method: str = "pairwise", facts: tuple[str, str] | None = None, use_pixel_facts: bool = False,
           max_side: int = 768, transport: Transport | None = None, model: str | None = None, **pairwise_kw) -> dict:
    """Which of two candidates is better for the brief?

    Returns {"winner": "A"|"B"|None, "p_a": probability A is better (0..1), "confidence": |p_a-0.5|*2,
    "consistent", "seconds", plus "scores" (method "score") or "orders" (method "pairwise")}.
    winner is None only on an exact tie. facts = (facts about A, facts about B) from the caller's measured checks
    (e.g. "2 floating parts"). method "pairwise" (default, 84% on the held-out test) or "score" (62%).
    """
    if method == "pairwise":
        return _prefer_pairwise(a_images, b_images, brief, domain, facts=facts, use_pixel_facts=use_pixel_facts,
                                max_side=max_side, transport=transport, model=model, **pairwise_kw)
    if method != "score":
        raise ValueError(f"unknown method {method!r}")
    fa, fb = facts or ("", "")
    t0 = time.monotonic()
    sa = score(a_images, brief, domain, facts=fa, use_pixel_facts=use_pixel_facts, max_side=max_side,
               transport=transport, model=model)
    sb = score(b_images, brief, domain, facts=fb, use_pixel_facts=use_pixel_facts, max_side=max_side,
               transport=transport, model=model)
    d = sa["score"] - sb["score"]
    p_a = 1 / (1 + math.exp(-2 * d))       # display scale only (1 point = 88%); the sign decides
    return {"winner": None if d == 0 else ("A" if d > 0 else "B"), "p_a": round(p_a, 4), "consistent": True,
            "confidence": round(abs(p_a - 0.5) * 2, 4), "scores": [sa["score"], sb["score"]],
            "seconds": round(time.monotonic() - t0, 2)}


def _prefer_pairwise(a_images: Sequence[Any], b_images: Sequence[Any], brief: str, domain: str = "generic", *,
           swap: bool = True, facts: tuple[str, str] | None = None, use_pixel_facts: bool = False,
           layout: str = "separate", max_side: int = 768, transport: Transport | None = None,
           model: str | None = None) -> dict:
    """Pairwise verdict: both arms in one prompt, p(A) vs p(B), both orders averaged ("orders" = per-order p(A))."""
    send = transport or http_transport()
    model = model or _config()[2]
    a = tile(a_images, max_side); b = tile(b_images, max_side)
    fa, fb = (facts or ("", ""))
    if use_pixel_facts:
        fa = "; ".join(x for x in (fa, pixel_facts(a_images)) if x)
        fb = "; ".join(x for x in (fb, pixel_facts(b_images)) if x)
    t0 = time.monotonic(); orders = []
    for flip in ((False, True) if swap else (False,)):
        x, y = (b, a) if flip else (a, b)
        fx = (fb, fa) if flip else (fa, fb)
        body = {"model": model, "messages": _pair_messages(x, y, brief, domain, fx, layout), "max_tokens": 1,
                "temperature": 0, "logprobs": True, "top_logprobs": 20, "cache_prompt": True}
        p = _letter_probs(send(body), "AB")
        tot = p["A"] + p["B"]
        p_first = p["A"] / tot if tot else 0.5
        orders.append(1 - p_first if flip else p_first)   # always "p(original A is better)"
    p_a = sum(orders) / len(orders)
    consistent = len(orders) == 1 or (orders[0] - 0.5) * (orders[1] - 0.5) > 0
    winner = None if p_a == 0.5 else ("A" if p_a > 0.5 else "B")
    return {"winner": winner, "p_a": round(p_a, 4), "consistent": consistent, "confidence": round(abs(p_a - 0.5) * 2, 4),
            "orders": [round(o, 4) for o in orders], "seconds": round(time.monotonic() - t0, 2)}


def issues(images: Sequence[Any], brief: str, domain: str = "generic", *, max_issues: int = 5,
           facts: str = "", use_pixel_facts: bool = False, max_side: int = 768, transport: Transport | None = None,
           model: str | None = None, max_tokens: int = 400) -> dict:
    """Concrete problems to fix, most severe first: {"issues": [{"part", "problem", "fix", "severity"}], "seconds"}."""
    send = transport or http_transport()
    model = model or _config()[2]
    sheet = tile(images, max_side)
    if use_pixel_facts:
        facts = "; ".join(x for x in (facts, pixel_facts(images)) if x)
    cl = "\n".join(f"- {c}" for c in checklist(domain))
    text = (f"Brief: {brief}\n\nCheck the render against this checklist:\n{cl}\n"
            + (f"Measured facts (trust these): {facts}\n" if facts else "")
            + f"\nList at most {max_issues} concrete problems, most severe first, as JSON only:\n"
            '{"issues": [{"part": "...", "problem": "...", "fix": "...", "severity": 1-3}]}\n'
            'severity 3 = breaks the brief, 1 = polish. Return {"issues": []} if nothing is wrong.')
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "cache_prompt": True,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url(sheet)}},
                                                      {"type": "text", "text": text}]}]}
    t0 = time.monotonic()
    resp = send(body)
    content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return {"issues": parse_issues(content)[:max_issues], "seconds": round(time.monotonic() - t0, 2)}


def parse_issues(text: str) -> list[dict]:
    """Tolerant JSON extraction (code fences, trailing prose, truncated lists)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    candidates = []
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                candidates.append(text[start:i + 1]); break
    for c in candidates:
        try:
            data = json.loads(c)
            items = data.get("issues", []) if isinstance(data, dict) else data
            break
        except json.JSONDecodeError:
            continue
    else:  # truncated: salvage complete issue objects
        items = []
        for m in re.finditer(r"\{[^{}]*\"problem\"[^{}]*\}", text):
            try:
                items.append(json.loads(m.group(0)))
            except json.JSONDecodeError:
                pass
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not str(it.get("problem", "")).strip():
            continue
        try:
            sev = max(1, min(3, int(it.get("severity", 2))))
        except (TypeError, ValueError):
            sev = 2
        out.append({"part": str(it.get("part", ""))[:80], "problem": str(it["problem"])[:300],
                    "fix": str(it.get("fix", ""))[:300], "severity": sev})
    return sorted(out, key=lambda d: -d["severity"])
