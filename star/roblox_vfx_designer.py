"""STAR VFX designer: brief -> design plan -> composer cues -> performance budget -> render -> critique -> one fix.

The local model only *chooses* (archetype, style profile, 2-3 colours, timing, scale, intensity, a few extras from a
fixed menu) in a small JSON plan; everything after that is deterministic Python that maps the plan onto cues of the
roblox-vfx-composer pack (star/skill_packs/roblox-vfx-composer). The model never writes emitter code.

  plan_prompt(brief)                -> messages for the model; normalize_plan(text, brief) -> validated plan
  compose(plan, textures)           -> spec for roblox_vfx_studio.VfxLab (style + timing override + cue list)
  curves: size_fast_in_slow_out, size_grow, alpha_fade, heat_ramp (NumberSequence / ColorSequence data)
  check_budget(cues, style, ...)    -> static live-particle / overdraw / emitter / light estimate per platform
  auto_reduce(...)                  -> scales counts, rates and lifetimes until the target platform fits
  vision_prompt / parse_vision / fixes_for / apply_fixes -> one deterministic fix pass from the critiques
  render_spec(lab, spec, ...)       -> one lab render (frames, contact sheet, metric critique, runtime census)
  make_effect(brief, chat, render)  -> the whole loop; the caller owns Studio turns and the model client.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import roblox_vfx_studio as vfx

ARCHETYPES: dict[str, str] = {
    "burst": "shards / particles explode outward from one point (ice shards, confetti, magic pop)",
    "impact": "a hit: flash, sparks and a small ring where something lands (punch, bullet hit)",
    "projectile": "a ball or bolt that flies to the target with a trail, then hits (fireball, arrow, magic missile)",
    "slash": "a sword / claw arc sweeping in front of the character with a crescent trail",
    "beam": "a continuous straight beam from a source to a target (laser, ray, drain beam)",
    "lightning": "a jagged bolt from the sky or between two points with a blinding flash",
    "explosion": "a fiery blast with smoke, debris and a shockwave (grenade, bomb)",
    "shockwave": "a ground slam: a ring expands along the floor, dust, rocks, camera shake",
    "aura": "a loop around the character: rising energy, glow outline (power up, buff, rage)",
    "heal": "a gentle loop of rising motes and pulsing ground rings (heal, regen, blessing)",
    "pickup": "a tiny quick pop of sparkles (coin, gem, item collect)",
    "pillar": "a tall column of light shooting up with rising sparkles (level up, summon, checkpoint)",
    "portal": "a looping vertical swirling ring with particles drawn into its centre",
    "cloud": "a lingering low cloud of gas or smoke (poison, fog, smoke bomb)",
    "weather": "ambient particles over the whole area (snow, rain, ash, leaves)",
}
STYLE_NAMES = tuple(vfx.STYLES)
LOOPS = ("aura", "heal", "portal", "cloud", "weather")
EXTRAS = ("sparks", "smoke", "ring", "debris", "shake", "flash", "light", "crack", "embers")
# Default timing per archetype: anticipation, impact window, follow-through (seconds).
TIMING = {
    "burst": (0.15, 0.1, 1.2), "impact": (0.05, 0.08, 0.7), "projectile": (0.6, 0.1, 1.1),
    "slash": (0.1, 0.18, 0.6), "beam": (0.3, 0.1, 1.6), "lightning": (0.25, 0.08, 0.9),
    "explosion": (0.05, 0.12, 2.2), "shockwave": (0.3, 0.12, 1.6), "aura": (0.4, 0.2, 3.0),
    "heal": (0.4, 0.2, 3.0), "pickup": (0.05, 0.08, 0.7), "pillar": (0.35, 0.15, 2.4),
    "portal": (0.35, 0.2, 3.2), "cloud": (0.2, 0.2, 3.4), "weather": (0.3, 0.2, 3.4),
}
KEYWORDS = {
    "projectile": ("fireball", "projectile", "missile", "arrow", "bolt fly", "flies", "shoot a", "orb"),
    "slash": ("slash", "sword", "blade", "claw", "katana", "swing", "crescent"),
    "lightning": ("lightning", "thunder", "electric bolt", "zap"),
    "beam": ("laser", "beam", "ray"),
    "explosion": ("explosion", "explode", "grenade", "bomb", "blast"),
    "shockwave": ("slam", "shockwave", "stomp", "quake", "ground pound"),
    "heal": ("heal", "regen", "bless", "restore"),
    "aura": ("aura", "power up", "rage", "buff"),
    "pickup": ("pickup", "pick up", "collect", "coin", "gem"),
    "pillar": ("level up", "level-up", "pillar", "summon", "column"),
    "portal": ("portal", "gate", "rift", "wormhole"),
    "cloud": ("cloud", "gas", "fog", "poison", "toxic"),
    "weather": ("snow", "rain", "ash fall", "weather", "ambient", "leaves"),
    "burst": ("burst", "shard", "explode outward", "confetti"),
    "impact": ("impact", "hit", "punch"),
}
# Lab geometry: the lab camera sits at origin + LAB_CAMERA looking at origin + (0, LAB_LOOK, 0), close enough that
# character-sized effects fill the frame. Sources of projectiles and beams start on the screen's left at FROM so the
# flight crosses the frame; sweeps face the camera at LAB_YAW.
LAB_CAMERA = [12.0, 5.0, 12.0]
LAB_LOOK = 4.0
LAB_CLOCK = 14.0    # client-side Lighting.ClockTime during the playtest, so other work on the place's lighting
                    # does not change the light between two renders
FROM = (-10.0, 4.0, 10.0)
LAB_YAW = 45.0
PERIOD = 4.5        # seconds per lab cycle (both eval arms use the same period and capture window)


# --------------------------------------------------------------------------- curves (timing shaping)

def _fmt(points) -> str:
    """Keypoints [(t, v), ...] -> the composer's curve string "t v t v ..." (t ascending, 0 and 1 present)."""
    pts = sorted((round(min(1.0, max(0.0, float(t))), 3), round(float(v), 3)) for t, v in points)
    if not pts or pts[0][0] != 0 or pts[-1][0] != 1 or len(pts) > 20:
        raise ValueError("a curve needs keypoints at t=0 and t=1 and at most 20 points")
    return " ".join(f"{t:g} {v:g}" for t, v in pts)


def size_fast_in_slow_out(start: float = 0.15, peak_at: float = 0.12, end: float = 0.0) -> str:
    """Size grows to full very fast (the pop), then shrinks slowly toward `end` (relative to `size`)."""
    rest = [(peak_at + (1 - peak_at) * u, 1 - (1 - end) * u * u) for u in (0.35, 0.7, 1.0)]
    return _fmt([(0, start), (peak_at, 1.0), *rest])


def size_grow(start: float = 0.3, end: float = 1.0) -> str:
    """Size expands with an ease-out (smoke, dust, rings): fast at first, settling at `end`."""
    return _fmt([(t, start + (end - start) * (1 - (1 - t) ** 3)) for t in (0, 0.25, 0.5, 1.0)])


def alpha_fade(fade_in: float = 0.1, fade_out_from: float = 0.6, low: float = 0.0) -> str:
    """Transparency: fade in over `fade_in`, hold at `low`, fade out from `fade_out_from` (no popping)."""
    points = [(0, 1.0 if fade_in > 0 else low), (fade_out_from, low), (1, 1.0)]
    if fade_in > 0:
        points.insert(1, (fade_in, low))
    return _fmt(points)


def heat_ramp(*keys: str) -> str:
    """Colour ramp over palette keys, evenly spaced: heat_ramp('core', 'glow', 'dark') = white-hot -> body -> cool."""
    keys = keys or ("core", "glow", "accent", "dark")
    if len(keys) < 2 or any(k not in ("core", "glow", "dark", "accent", "flash") for k in keys):
        raise ValueError("a ramp needs 2+ palette keys")
    return " ".join(f"{round(i / (len(keys) - 1), 3):g} {k}" for i, k in enumerate(keys))


def curve_points(text: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in text.split()]
    return list(zip(nums[0::2], nums[1::2]))


def curve_mean(text: str | None, default: float) -> float:
    """Mean value of a piecewise-linear curve over t = 0..1."""
    if not text:
        return default
    pts = curve_points(text)
    return sum((t1 - t0) * (v0 + v1) / 2 for (t0, v0), (t1, v1) in zip(pts, pts[1:]))


# --------------------------------------------------------------------------- the plan (model chooses)

def plan_prompt(brief: str) -> list[dict]:
    """Messages asking the local model for the small JSON design plan."""
    menu = "\n".join(f"- {name}: {text}" for name, text in ARCHETYPES.items())
    styles = ", ".join(f"{n} ({vfx.STYLES[n]['label']})" for n in STYLE_NAMES)
    colours = ", ".join(vfx.COLOUR_WORDS)
    system = ("You are a Roblox VFX art director. You only choose; code is written by a deterministic tool. "
              "Answer with ONE JSON object and nothing else.")
    user = f"""Brief: {brief.strip()[:600]}

Return JSON with exactly these keys:
{{"archetype": "<one of the archetypes>", "style": "<one style>", "palette": ["<main colour>", "<second colour>", "<optional third>"],
 "timing": {{"anticipation": <0-1.5 s>, "impact": <0.03-0.5 s>, "follow_through": <0.2-4 s>}},
 "scale": <0.5-2, 1 = about a character>, "intensity": <0.3-1.5>, "extras": [<zero or more of {list(EXTRAS)}>]}}

Archetypes (pick the one whose motion matches the brief):
{menu}
Styles: {styles}
Colours: a name from [{colours}] or "#rrggbb". The first colour is the effect's main body colour."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _json_object(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start = text.find("{")
    while start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        found = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    return found if isinstance(found, dict) else None
        start = text.find("{", start + 1)
    return None


def _colour(value) -> tuple[int, int, int] | None:
    if isinstance(value, str):
        word = value.strip().lower()
        if word in vfx.COLOUR_WORDS:
            return vfx.COLOUR_WORDS[word]
        if re.fullmatch(r"#?[0-9a-f]{6}", word):
            word = word.lstrip("#")
            return tuple(int(word[i:i + 2], 16) for i in (0, 2, 4))
        for name, rgb in vfx.COLOUR_WORDS.items():      # "electric blue" -> blue
            if re.search(r"\b" + name + r"\b", word):
                return rgb
    return None


def keyword_plan(brief: str) -> dict:
    """Deterministic fallback plan from the brief's words (used when the model's plan is missing or invalid)."""
    text = (brief or "").lower()
    archetype = "impact"
    best = 0
    for name, words in KEYWORDS.items():
        hits = sum(1 for w in words if w in text)
        if hits > best:
            archetype, best = name, hits
    style = vfx.choose_style(brief)["base"]
    colours = [w for w in vfx.COLOUR_WORDS if re.search(r"\b" + re.escape(w) + r"\b", text)][:3]
    a, i, f = TIMING[archetype]
    return {"archetype": archetype, "style": style, "palette": colours or ["gold"],
            "timing": {"anticipation": a, "impact": i, "follow_through": f}, "scale": 1.0, "intensity": 1.0,
            "extras": []}


def _num(value, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return float(min(high, max(low, value)))


def normalize_plan(raw, brief: str) -> tuple[dict, list[str]]:
    """Validate the model's plan (text or dict); clamp numbers, drop unknown values, fill gaps from keyword_plan.

    Returns (plan, problems). The plan is always usable."""
    fallback = keyword_plan(brief)
    data = raw if isinstance(raw, dict) else _json_object(raw if isinstance(raw, str) else "")
    problems: list[str] = []
    if not isinstance(data, dict):
        return {**fallback, "source": "keywords"}, ["no JSON plan from the model: keyword plan used"]
    plan: dict[str, Any] = {"source": "model"}
    archetype = str(data.get("archetype", "")).strip().lower().replace(" ", "_")
    archetype = {"laser": "beam", "trail": "projectile", "sparkle": "pickup", "loop": "aura", "ambient": "weather",
                 "aoe": "shockwave", "fog": "cloud"}.get(archetype, archetype)
    if archetype not in ARCHETYPES:
        problems.append(f"unknown archetype {archetype!r}: {fallback['archetype']}")
        archetype = fallback["archetype"]
    plan["archetype"] = archetype
    style = str(data.get("style", "")).strip().lower()
    if style not in vfx.STYLES:
        problems.append(f"unknown style {style!r}: {fallback['style']}")
        style = fallback["style"]
    plan["style"] = style
    colours = [c for c in (data.get("palette") or []) if _colour(c)][:3] if isinstance(data.get("palette"), list) else []
    if not colours:
        problems.append("no usable colours: brief colours used")
        colours = fallback["palette"]
    plan["palette"] = colours
    a, i, f = TIMING[archetype]
    timing = data.get("timing") if isinstance(data.get("timing"), dict) else {}
    plan["timing"] = {"anticipation": _num(timing.get("anticipation"), 0.0, 1.5, a),
                      "impact": _num(timing.get("impact"), 0.03, 0.5, i),
                      "follow_through": _num(timing.get("follow_through"), 0.2, 4.0, f)}
    if archetype == "projectile":       # the flight happens during the anticipation
        plan["timing"]["anticipation"] = max(plan["timing"]["anticipation"], 0.4)
    if archetype in LOOPS:              # loops must stay on screen long enough to read as a loop
        plan["timing"]["follow_through"] = max(plan["timing"]["follow_through"], 3.0)
    plan["scale"] = _num(data.get("scale"), 0.5, 2.0, 1.0)
    plan["intensity"] = _num(data.get("intensity"), 0.3, 1.5, 1.0)
    extras = data.get("extras") if isinstance(data.get("extras"), list) else []
    plan["extras"] = sorted({str(e).lower() for e in extras if str(e).lower() in EXTRAS})
    return plan, problems


# --------------------------------------------------------------------------- plan -> composer cues

def palette_for(base: str, colours: list) -> dict:
    """Composer palette from the plan's colours: 1st = glow (body), 2nd = accent, 3rd = dark (kept dark)."""
    rgb = [c for c in (_colour(x) for x in colours) if c]
    palette = vfx.palette_from_hue(base, rgb[0]) if rgb else dict(vfx.STYLES[base]["palette"])
    if len(rgb) > 1:
        palette["accent"] = rgb[1]
    if len(rgb) > 2:
        h, s, v = vfx._rgb_to_hsv(rgb[2])
        palette["dark"] = vfx._hsv_to_rgb(h, s, min(v, 0.35))
    return palette


def stage_lengths(timing: dict) -> dict:
    """Plan timing -> composer stage lengths. Follow-through F is split so that the time after the impact window
    is exactly F (shockwave overlaps half its length: 0.25F + linger 0.35F + dissipate 0.4F)."""
    f = timing["follow_through"]
    return {"charge": round(max(0.02, timing["anticipation"]), 3), "impact": round(timing["impact"], 3),
            "shockwave": round(0.5 * f, 3), "linger": round(0.35 * f, 3), "dissipate": round(0.4 * f, 3)}


def _c(stage: str, at: float, fx: str, **params) -> dict:
    params = {k: v for k, v in params.items() if v is not None}
    return {"stage": stage, "at": round(min(1.0, max(0.0, at)), 3), "fx": fx, "params": params or None}


SPARKLE = "0 0 0.15 1 0.6 0.7 1 0"


def _recipe(archetype: str, L: dict, total: float, yaw: float) -> list[dict]:
    """Cue list for one archetype. L = stage lengths; total = effect length; loops last the whole effect."""
    fx, fy, fz = FROM
    pop, grow = size_fast_in_slow_out(), size_grow()
    fade, soft = alpha_fade(0.05, 0.6), alpha_fade(0.2, 0.5, 0.35)
    hot, body = heat_ramp("core", "glow", "accent", "dark"), heat_ramp("core", "glow")
    after = L["shockwave"] * 0.25 + L["linger"] + L["dissipate"]          # seconds after the impact window
    smoke = dict(texture="smoke", flipbook="oneshot", color="dark", lightEmission=0, sizeCurve=grow, alphaCurve=soft,
                 spread=120, drag=2, gravity=-1.5, spin=30)
    if archetype == "projectile":
        flight = L["charge"] * 0.75
        return [
            _c("charge", 0, "particles", x=fx, y=fy, z=fz, shape="sphere", radius=2.5, surface=True, inward=True,
               count=16, life=0.3, size=0.5, speed=8, texture="spark", color="core", sizeCurve=pop),
            _c("charge", 0.25, "projectile", x0=fx, y0=fy, z0=fz, x1=0, y1=2, z1=0, dur=flight, size=1.6, arc=1.5,
               trailLife=0.3, widthCurve="0 1 0.5 0.6 1 0", trailAlpha="0 0 0.7 0.4 1 1", ramp=hot,
               rate=70, emitLife=0.45, emitSize=1.8, emitCurve=pop, rise=5),
            _c("impact", 0, "flash", strength=0.35, invert=False),
            _c("impact", 0, "light", dur=0.5, range=28),
            _c("impact", 0, "particles", y=2, count=26, life=0.45, size=4, speed=10, drag=6, sizeCurve=pop,
               alphaCurve=fade, ramp=hot, texture="glow", lightEmission=1),
            _c("impact", 0.2, "sparks", count=30, speed=50),
            _c("shockwave", 0, "ring", radius=9, y=0.4),
            _c("shockwave", 0.2, "particles", y=1.5, count=8, life=min(1.6, after), size=5, speed=4, **smoke),
            _c("linger", 0, "particles", y=1.5, count=14, life=0.9, size=0.35, speed=7, gravity=-6, spread=90,
               texture="spark", ramp=heat_ramp("core", "accent")),
        ]
    if archetype == "slash":
        swing = max(0.1, L["impact"])
        return [
            _c("charge", 0, "particles", y=3, count=6, life=0.2, size=1.2, speed=0, texture="spark", color="core",
               sizeCurve=pop, spin=200),
            _c("impact", 0, "sweep", radius=9, inner=0.45, arc=170, dur=swing, y=3, yaw=yaw, tilt=72, roll=-25,
               trailLife=0.22, ramp=heat_ramp("core", "glow", "accent")),
            _c("impact", 0.1, "sweep", radius=9.4, inner=0.85, arc=165, dur=swing, y=3, yaw=yaw, tilt=72, roll=-25,
               trailLife=0.14, ramp=heat_ramp("core", "core", "glow")),
            _c("impact", 0.5, "sparks", count=18, speed=40, y=3),
            _c("impact", 0.3, "light", dur=0.25, range=22),
            _c("impact", 0.3, "flash", strength=0.15, invert=False),
            _c("shockwave", 0, "particles", y=3, count=12, life=0.5, size=0.3, speed=6, spread=60, texture="spark",
               color="accent", gravity=4),
        ]
    if archetype in ("beam", "lightning"):
        held = L["impact"] + after * 0.6
        bolt = archetype == "lightning"
        src = (0.0, 45.0, 0.0) if bolt else FROM
        cues = [
            _c("charge", 0, "particles", x=src[0], y=min(src[1], 18), z=src[2], shape="sphere", radius=3, surface=True,
               inward=True, count=24, life=0.35, size=0.6, speed=10, texture="spark", color="core"),
            _c("impact", 0, "beam", x0=src[0], y0=src[1], z0=src[2], x1=0, y1=0.5 if bolt else 2, z1=0,
               width=2.2 if bolt else 1.4, layers=2, segments=1 if bolt else 8, textureSpeed=0 if bolt else 6,
               textureLength=4, ramp=body, dur=0.35 if bolt else held, zigzag=7 if bolt else 0, jitter=2.5,
               flicker=0.05, taper=0.7 if bolt else 1),
            _c("impact", 0, "flash", strength=0.9 if bolt else 0.3, invert=bolt),
            _c("impact", 0, "light", dur=0.6 if bolt else held, range=45 if bolt else 24, brightness=8 if bolt else 4),
            _c("impact", 0.1, "sparks", count=45 if bolt else 20, speed=60 if bolt else 35),
            _c("impact", 0, "particles", y=1, rate=0 if bolt else 50, count=24 if bolt else None,
               dur=held, life=0.3, size=3, speed=2, sizeCurve=pop, alphaCurve=fade, ramp=body, texture="glow",
               lightEmission=1),
            _c("shockwave", 0, "ring", radius=10 if bolt else 6, y=0.3),
            _c("dissipate", 0, "particles", y=1, count=6, life=1.0, size=3, speed=3, **smoke),
        ]
        if bolt:
            cues.append(_c("impact", 0.6, "beam", x0=2, y0=45, z0=-2, x1=0, y1=0.5, z1=0, width=1.4, layers=2,
                           segments=1, textureSpeed=0, ramp=body, dur=0.25, zigzag=6, jitter=2, flicker=0.05))
            cues.append(_c("charge", 0, "tint", dur=total * 0.6))
        return cues
    if archetype == "explosion":
        return [
            _c("impact", 0, "flash", strength=0.6, invert=False),
            _c("impact", 0, "light", dur=0.9, range=55, brightness=7),
            _c("impact", 0, "particles", y=3, count=22, life=0.55, size=7, speed=12, drag=5, sizeCurve=pop,
               alphaCurve=fade, ramp=hot, texture="glow", lightEmission=1),
            _c("impact", 0.15, "particles", y=3, count=26, life=0.8, size=5, speed=24, drag=4, gravity=-6,
               sizeCurve=pop, alphaCurve=fade, ramp=hot, texture="glow", lightEmission=0.8),
            _c("impact", 0, "sparks", count=60, speed=85),
            _c("impact", 0, "debris", count=14, speed=50),
            _c("impact", 0, "crack", radius=11),
            _c("impact", 0.2, "shake", amplitude=1.1, dur=0.6),
            _c("shockwave", 0, "ring", radius=24, color="accent"),
            _c("shockwave", 0.1, "particles", y=2, count=14, life=min(2.2, after), size=9, speed=10, **smoke),
            _c("dissipate", 0, "particles", y=3, count=16, life=1.2, size=0.35, speed=10, gravity=-4,
               texture="spark", ramp=heat_ramp("core", "accent")),
        ]
    if archetype == "shockwave":
        return [
            _c("charge", 0, "particles", y=0.5, shape="disc", radius=6, surface=True, inward=True, count=20, life=0.35,
               size=0.6, speed=12, texture="spark", color="accent"),
            _c("impact", 0, "flash", strength=0.3, invert=False),
            _c("impact", 0, "light", dur=0.4, range=30),
            _c("impact", 0, "crack", radius=13),
            _c("impact", 0, "debris", count=18, speed=48),
            _c("impact", 0, "shake", amplitude=1.3, dur=0.6),
            _c("shockwave", 0, "ringSegments", radius=18),
            _c("shockwave", 0, "ring", radius=24, color="glow"),
            _c("shockwave", 0.05, "particles", y=0.6, shape="disc", radius=2.5, surface=True, count=26,
               life=min(1.6, after), size=4.5, speed=32, **{**smoke, "spread": 10, "gravity": -1, "drag": 4}),
            _c("linger", 0, "particles", y=1, count=10, life=1.2, size=6, speed=4, **smoke),
        ]
    if archetype in ("aura", "heal"):
        heal = archetype == "heal"
        loop = total * 0.92
        cues = [
            _c("charge", 0, "aura", dur=total * 0.85, count=0 if heal else 40),
            _c("charge", 0, "particles", y=0.3, shape="disc", radius=3.2, rate=26 if heal else 34, dur=loop,
               life=1.3 if heal else 0.9, size=0.55 if heal else 1.1, speed=1.5, speedMin=0.5, gravity=-7 if heal else -14,
               spread=10, texture="spark" if heal else "glow", ramp=heat_ramp("core", "glow"),
               sizeCurve=SPARKLE, alphaCurve=alpha_fade(0.15, 0.6)),
            _c("impact", 0, "ring", radius=7, y=0.3, dur=after * 0.4),
            _c("impact", 0, "light", dur=loop * 0.8, range=18, brightness=2),
            _c("linger", 0, "ring", radius=7, y=0.3, dur=after * 0.4, color="accent"),
            _c("dissipate", 0, "particles", y=1, count=18, life=1.1, size=0.4, speed=6, gravity=-6, spread=40,
               texture="spark", color="core"),
        ]
        if heal:
            cues.append(_c("impact", 0, "particles", y=2.5, shape="sphere", radius=2.5, count=10, life=1.2, size=1.1,
                           speed=1, gravity=-3, texture="glow", color="core", sizeCurve=SPARKLE))
        return cues
    if archetype == "pickup":
        return [
            _c("impact", 0, "particles", y=2, count=22, life=0.55, size=0.6, speed=16, gravity=22, drag=2,
               texture="spark", ramp=heat_ramp("core", "glow"), sizeCurve=pop, spin=180),
            _c("impact", 0, "particles", y=2, count=6, life=0.45, size=1.6, speed=6, drag=3, texture="spark",
               color="core", sizeCurve=pop, spin=300, lightEmission=1),
            _c("impact", 0, "particles", y=2, count=1, life=0.25, size=4, speed=0, texture="glow", color="glow",
               sizeCurve=pop, lightEmission=1),
            _c("shockwave", 0, "ring", radius=3.5, y=2, dur=0.35),
            _c("impact", 0, "light", dur=0.35, range=12, brightness=3),
            _c("linger", 0, "particles", y=2.5, count=8, life=0.6, size=0.3, speed=3, gravity=-4, texture="spark",
               color="accent", sizeCurve=SPARKLE),
        ]
    if archetype == "pillar":
        return [
            _c("charge", 0, "particles", y=0.3, shape="disc", radius=6, surface=True, inward=True, count=24,
               life=0.4, size=0.5, speed=12, texture="spark", color="core"),
            _c("impact", 0, "pillar", height=60, width=5, dur=after * 0.75),
            _c("impact", 0, "flash", strength=0.3, invert=False),
            _c("impact", 0, "light", dur=after * 0.7, range=35, brightness=5),
            _c("impact", 0, "ring", radius=10, y=0.3),
            _c("impact", 0.1, "particles", y=0.5, shape="disc", radius=4, rate=45, dur=after * 0.7, life=1.4,
               size=0.5, speed=6, speedMin=3, gravity=-14, spread=8, texture="spark", ramp=heat_ramp("core", "glow"),
               sizeCurve=SPARKLE),
            _c("shockwave", 0, "aura", dur=after * 0.7, count=0),
            _c("dissipate", 0, "particles", y=6, count=20, life=1.0, size=0.4, speed=8, gravity=-6, texture="spark",
               color="accent"),
        ]
    if archetype == "portal":
        loop = total * 0.92
        portal = dict(y=5, pitch=90, yaw=yaw)
        return [
            _c("charge", 0, "particles", count=1, life=total * 0.95, size=11, speed=0, spin=0, texture="swirl",
               color="glow", sizeCurve="0 0.1 0.08 1 0.92 1 1 0", alphaCurve="0 1 0.06 0.1 0.9 0.1 1 1",
               lightEmission=1, **portal),
            _c("charge", 0.1, "particles", rate=3, dur=loop, life=1.6, size=8, speed=0, spin=160, texture="swirl",
               color="accent", alphaCurve=alpha_fade(0.25, 0.6, 0.3), lightEmission=1, **portal),
            _c("charge", 0, "particles", shape="disc", radius=4.2, surface=True, rate=55, dur=loop, life=0.8,
               size=0.45, speed=0.5, spread=0, texture="spark", color="core", sizeCurve=SPARKLE, **portal),
            _c("charge", 0.3, "particles", shape="sphere", radius=9, surface=True, inward=True, rate=22, dur=loop,
               life=0.8, size=0.4, speed=11, orient="velocity", texture="spark", ramp=heat_ramp("accent", "core"),
               **portal),
            _c("impact", 0, "light", dur=loop * 0.8, range=24, brightness=3),
            _c("impact", 0, "flash", strength=0.15, invert=False),
        ]
    if archetype == "cloud":
        loop = total * 0.85
        return [
            _c("charge", 0, "particles", y=1, shape="disc", radius=5, rate=9, dur=loop, life=2.4, size=8, speed=1.2,
               spread=30, texture="smoke", flipbook="loop", fps=8, ramp=heat_ramp("glow", "dark"),
               sizeCurve=size_grow(0.4, 1.0), alphaCurve=alpha_fade(0.25, 0.6, 0.35), lightEmission=0.15, spin=20,
               drag=1),
            _c("charge", 0.2, "particles", y=0.5, shape="disc", radius=4, rate=10, dur=loop, life=1.0, size=0.6,
               speed=3, gravity=-3, texture="glow", color="accent", sizeCurve=SPARKLE, lightEmission=0.6),
            _c("impact", 0, "light", dur=loop * 0.8, range=16, brightness=1),
            _c("impact", 0, "particles", y=0.2, count=1, life=loop * 0.9, size=14, speed=0, spin=0, orient="flat",
               texture="glow", color="glow", alphaCurve=alpha_fade(0.2, 0.7, 0.6), lightEmission=0.3),
        ]
    if archetype == "weather":
        # The emitter volume fills the view between the camera and the stage (not only a sky plane), so the weather
        # is on screen from the first second; particles fade in where they spawn.
        loop = total * 0.92
        area = dict(x=4, y=8, z=4, shape="box", height=16)
        return [
            _c("charge", 0, "particles", radius=14, rate=150, dur=loop, life=3.2, size=0.5, speed=1, speedMin=0.5,
               spread=20, gravity=5, drag=0.5, windX=1.5, spin=90, texture="glow", color="core",
               alphaCurve=alpha_fade(0.15, 0.8, 0.05), lightEmission=0.3, **area),
            _c("charge", 0.3, "particles", radius=12, rate=45, dur=loop, life=3.0, size=0.8, speed=1, spread=20,
               gravity=6, drag=0.5, windX=1, texture="spark", color="glow", alphaCurve=alpha_fade(0.15, 0.8, 0.15),
               lightEmission=0.4, **area),
        ]
    if archetype == "burst":
        return [
            _c("charge", 0, "particles", y=2, shape="sphere", radius=3, surface=True, inward=True, count=14, life=0.2,
               size=0.4, speed=14, texture="spark", color="core"),
            _c("impact", 0, "flash", strength=0.3, invert=False),
            _c("impact", 0, "light", dur=0.5, range=25),
            _c("impact", 0, "particles", y=2, count=26, life=0.7, size=2.2, speed=42, speedMin=20, drag=5,
               orient="velocity", texture="streak", ramp=heat_ramp("core", "glow", "accent"), sizeCurve=pop),
            _c("impact", 0, "spikes", count=7, radius=5, height=5, force=True),
            _c("impact", 0.1, "particles", y=2, count=10, life=min(1.4, after), size=6, speed=6,
               **{**smoke, "color": "glow", "lightEmission": 0.2}),
            _c("shockwave", 0, "ring", radius=12, y=0.5),
            _c("linger", 0, "particles", y=2, shape="sphere", radius=5, count=20, life=0.9, size=0.4, speed=1,
               texture="spark", color="core", sizeCurve=SPARKLE, spin=200),
        ]
    # impact (default)
    return [
        _c("impact", 0, "flash", strength=0.35, invert=False),
        _c("impact", 0, "light", dur=0.3, range=22),
        _c("impact", 0, "particles", y=2, count=1, life=0.2, size=7, speed=0, texture="glow", color="core",
           sizeCurve=pop, lightEmission=1),
        _c("impact", 0, "sparks", count=30, speed=55, y=2),
        _c("impact", 0.1, "shake", amplitude=0.4, dur=0.25),
        _c("shockwave", 0, "ring", radius=7, y=1.5),
        _c("shockwave", 0.2, "particles", y=1.5, count=6, life=0.9, size=3, speed=5, **smoke),
    ]


EXTRA_CUES = {
    "sparks": _c("impact", 0.1, "sparks", count=30, speed=55),
    "smoke": _c("shockwave", 0.2, "smoke", count=8, life=1.2),
    "ring": _c("shockwave", 0, "ring", radius=12),
    "debris": _c("impact", 0, "debris", count=12, speed=45),
    "shake": _c("impact", 0.1, "shake", amplitude=0.8, dur=0.45),
    "flash": _c("impact", 0, "flash", strength=0.4, invert=False),
    "light": _c("impact", 0, "light", dur=0.5, range=30),
    "crack": _c("impact", 0, "crack", radius=10),
    "embers": _c("linger", 0, "particles", y=2, count=16, life=1.2, size=0.3, speed=6, gravity=-5, texture="spark",
                 color="accent"),
}


def compose(plan: dict, *, textures: dict | None = None, yaw: float = LAB_YAW) -> dict:
    """Deterministic plan -> lab spec (roblox_vfx_studio): adapted style (palette, stage timing, size), cue list."""
    base = plan["style"]
    lengths = stage_lengths(plan["timing"])
    total = round(vfx.style_length(base, lengths), 3)
    cues = _recipe(plan["archetype"], lengths, total, yaw)
    have = {c["fx"] for c in cues}
    for extra in plan.get("extras", []):
        cue = EXTRA_CUES[extra]
        if cue["fx"] not in have or extra == "embers":
            cues.append(json.loads(json.dumps(cue)))
            have.add(cue["fx"])
    name = re.sub(r"[^a-z0-9_]", "_", f"star_{plan['archetype']}")[:40]
    style = {"base": base, "name": f"{name}_{base}"[:40], "palette": palette_for(base, plan["palette"]),
             "timing": lengths, "sizeScale": round(plan.get("scale", 1.0), 3)}
    ability = {"name": name, "builtin": False, "cues": cues}
    problems = vfx.validate_ability(ability)
    if problems:
        raise ValueError("; ".join(problems))
    return {"prompt": plan.get("brief", "")[:300], "style": style, "ability": ability,
            "intensity": round(plan.get("intensity", 1.0), 3), "effect_length": total,
            "textures": vfx.textures_for(base, textures), "origin": list(vfx.STAGE_ORIGIN), "camera": LAB_CAMERA,
            "speed": 1.0, "timer": False}


# --------------------------------------------------------------------------- performance budget (static)

REF_DISTANCE = 30.0                     # studs from the camera
SCREEN = (1920, 1080)
PX_PER_STUD = SCREEN[1] / (2 * REF_DISTANCE * math.tan(math.radians(35)))   # FOV 70 vertical
BUDGETS = {
    # live = peak concurrent particles; overdraw = transparent screens covered at the peak (alive x area x opacity);
    # additive = concurrent glow layers (LightEmission >= 0.8, mostly opaque) that wash out to white when stacked.
    "pc": {"quality": 1.0, "live": 1200, "overdraw": 4.0, "emitters": 24, "additive": 6, "lights": 4,
           "shadow_lights": 0, "rate_per_emitter": 400},
    "mobile": {"quality": 0.5, "live": 350, "overdraw": 1.5, "emitters": 12, "additive": 3, "lights": 2,
               "shadow_lights": 0, "rate_per_emitter": 100},
}
COMPOSER_BUDGET = 700                   # VfxComposer.PARTICLE_BUDGET per effect at quality 1
# Mirror of each VfxStyles profile's lightEmission (a test keeps it in step with the Luau).
STYLE_LIGHT = {"anime_energy": 1.0, "cartoon_soft": 0.25, "realistic_fire": 0.7, "scifi_neon": 1.0, "pixel_retro": 0.0}


def _p(cue: dict) -> dict:
    return cue.get("params") or {}


def _layers(cue: dict, start: float, style: dict, intensity: float, quality: float) -> dict:
    """Static estimate of what one cue creates: particle layers and other objects (mirrors the Luau primitives)."""
    p, fx = _p(cue), cue["fx"]
    base = vfx.STYLES[style["base"]]
    scale = float(style.get("sizeScale") or 1.0)
    timing = {**base["timing"], **(style.get("timing") or {})}
    k = intensity * quality
    style_light = STYLE_LIGHT[style["base"]]
    glow = style_light >= 0.8                                                 # additive styles
    out: dict[str, Any] = {"particles": [], "beams": 0, "trails": 0, "lights": 0, "shadow_lights": 0, "parts": 0,
                           "highlights": 0, "screen": 0, "surfaces": [], "requested": 0.0}

    def layer(count=0.0, rate=0.0, dur=0.0, life=0.6, size=1.0, mean=0.5, opacity=0.6, additive=None, t0=start):
        n = (rate * dur if rate else count) * k
        out["requested"] += n
        out["particles"].append({"t0": t0, "count": 0 if rate else n, "rate": (n / dur) if rate else 0.0,
                                 "dur": dur if rate else 0.0, "life": life * 0.85, "size": size * scale * mean,
                                 "opacity": opacity, "additive": glow if additive is None else additive})

    if fx == "particles":
        rate = float(p.get("rate", 0))
        le = float(p.get("lightEmission", style_light))
        layer(count=float(p.get("count", 20)), rate=rate, dur=float(p.get("dur", 1)), life=float(p.get("life", 0.8)),
              size=float(p.get("size", 1)), mean=curve_mean(p.get("sizeCurve"), 0.5),
              opacity=1 - curve_mean(p.get("alphaCurve"), 0.38), additive=le >= 0.8)
        out["parts"] += 1 if p.get("shape") in ("sphere", "disc", "box", "cylinder") else 0
    elif fx in ("burst", "sparks", "smoke"):
        d = {"burst": (30, 0.6, 1.0, 0.5, 0.6), "sparks": (40, 0.5, 0.6, 0.6, 0.7), "smoke": (18, 1.6, 5.0, 1.2, 0.45)}[fx]
        layer(count=float(p.get("count", d[0])), life=float(p.get("life", d[1])), size=float(p.get("size", d[2])),
              mean=d[3], opacity=d[4], additive=None if fx != "smoke" else False)
    elif fx == "ring":
        r = float(p.get("radius", 22))
        layer(count=1, life=float(p.get("dur", timing["shockwave"])), size=2 * r, mean=0.75, opacity=0.6)
    elif fx == "crack":
        r = float(p.get("radius", 16))
        layer(count=1, life=timing["linger"] + timing["dissipate"], size=1.6 * r, mean=0.9, opacity=0.8, additive=False)
        out["parts"] += 9 * 3
    elif fx == "aura":
        dur = float(p.get("dur", timing["charge"] + timing["impact"]))
        if float(p.get("count", 60)) > 0:
            layer(rate=float(p.get("count", 60)) / max(dur, 0.05), dur=dur, life=0.8, size=1.6, mean=0.5, opacity=0.6)
        layer(count=40, life=0.5, size=0.5, mean=0.5, opacity=0.6)
        out["highlights"] += 1
    elif fx == "vortex":
        r = float(p.get("radius", 9))
        layer(count=24, life=float(p.get("dur", timing["linger"])) * 0.8, size=0.9 * r, mean=0.5, opacity=0.5)
        out["trails"] += int(p.get("arms", 6))
        out["parts"] += 2
    elif fx == "dome":
        r = float(p.get("radius", 12)) * scale
        out["surfaces"].append({"t0": start, "dur": float(p.get("dur", timing["shockwave"])), "area": math.pi * r * r,
                                "opacity": 0.5})
        out["parts"] += 1
    elif fx == "pillar":
        h, w = float(p.get("height", 60)) * scale, float(p.get("width", 6)) * scale
        out["beams"] += 2
        out["parts"] += 2
        out["surfaces"].append({"t0": start, "dur": float(p.get("dur", timing["linger"])), "area": min(h, 40) * w * 2,
                                "opacity": 0.6})
    elif fx == "beam":
        layers = int(p.get("layers", 2))
        joints = int(p.get("zigzag", 0))
        out["beams"] += layers * (joints + 1)
        a = (float(p.get("x0", 0)), float(p.get("y0", 0)), float(p.get("z0", 0)))
        b = (float(p.get("x1", 0)), float(p.get("y1", 20)), float(p.get("z1", 0)))
        length = min(math.dist(a, b), 40)
        w = float(p.get("width", 1)) * scale
        out["surfaces"].append({"t0": start, "dur": float(p.get("dur", 0.6)), "area": length * w * 2.5, "opacity": 0.6})
    elif fx == "projectile":
        life = float(p.get("dur", 0.6))
        out["trails"] += 1
        out["parts"] += 1
        if float(p.get("rate", 0)) > 0:
            layer(rate=float(p["rate"]), dur=life, life=float(p.get("emitLife", 0.5)),
                  size=float(p.get("emitSize", p.get("size", 1.5))), mean=curve_mean(p.get("emitCurve"), 0.5),
                  opacity=0.6)
    elif fx == "sweep":
        out["trails"] += 1
        out["parts"] += 1
        r = float(p.get("radius", 8)) * scale
        out["surfaces"].append({"t0": start, "dur": float(p.get("trailLife", 0.2)) + float(p.get("dur", 0.18)),
                                "area": r * r * math.radians(float(p.get("arc", 160))) / 2 * 0.5, "opacity": 0.6})
    elif fx == "light":
        out["lights"] += 1
    elif fx in ("flash", "tint"):
        out["screen"] += 1
    elif fx in ("ringSegments", "slashes", "debris", "spikes"):
        out["parts"] += int(p.get("segments", p.get("count", 16)))
    return out


def check_budget(cues: list[dict], style: dict, *, intensity: float = 1.0, platform: str = "pc") -> dict:
    """Static budget of a cue list for one platform (deterministic; nothing is rendered).

    live_sum is the simple sum(rate*lifetime + bursts); live_peak / overdraw_peak sample the timeline
    (bursts alive for ~0.85 of their lifetime, loops ramp to rate*lifetime) and are what the budget checks."""
    limits = BUDGETS[platform]
    base = style["base"]
    timing = {**vfx.STYLES[base]["timing"], **(style.get("timing") or {})}
    starts = vfx.stage_times(base, style.get("timing"))
    stage_len = {s: timing[s] for s in vfx.STAGES}
    totals = {"beams": 0, "trails": 0, "lights": 0, "shadow_lights": 0, "parts": 0, "highlights": 0, "screen": 0}
    layers, surfaces, requested = [], [], 0.0
    for cue in cues:
        start = starts[cue["stage"]] + float(cue.get("at", 0)) * stage_len[cue["stage"]]
        got = _layers(cue, start, style, intensity, limits["quality"])
        layers += got["particles"]
        surfaces += got["surfaces"]
        requested += got["requested"]
        for key in totals:
            totals[key] += got[key]
    end = max([starts["finish"]] + [l["t0"] + l["dur"] + l["life"] for l in layers] + [0.0])
    area_screen = SCREEN[0] * SCREEN[1]
    peak = {"live": 0.0, "overdraw": 0.0, "emitters": 0, "additive": 0, "t_live": 0.0}
    t = 0.0
    while t <= end + 1e-9:
        live = over = 0.0
        emitters = additive = 0
        for l in layers:
            if l["rate"]:
                if l["t0"] <= t < l["t0"] + l["dur"] + l["life"]:
                    alive = l["rate"] * max(0.0, min(t - l["t0"], l["life"], l["t0"] + l["dur"] + l["life"] - t))
                else:
                    alive = 0.0
            else:
                alive = l["count"] if l["t0"] <= t < l["t0"] + l["life"] else 0.0
            if alive > 0:
                emitters += 1
                live += alive
                over += alive * (l["size"] * PX_PER_STUD) ** 2 * l["opacity"] / area_screen
                if l["additive"] and l["opacity"] >= 0.5:
                    additive += 1
        for s in surfaces:
            if s["t0"] <= t < s["t0"] + s["dur"]:
                over += s["area"] * PX_PER_STUD ** 2 * s["opacity"] / area_screen
        if live > peak["live"]:
            peak["live"], peak["t_live"] = live, t
        peak["overdraw"] = max(peak["overdraw"], over)
        peak["emitters"] = max(peak["emitters"], emitters)
        peak["additive"] = max(peak["additive"], additive)
        t += 0.05
    live_sum = sum(l["rate"] * l["life"] + l["count"] for l in layers)
    max_rate = max([l["rate"] for l in layers] + [0.0])
    findings = []
    if peak["live"] > limits["live"]:
        findings.append(f"live particles {peak['live']:.0f} > {limits['live']} ({platform})")
    if peak["overdraw"] > limits["overdraw"]:
        findings.append(f"overdraw {peak['overdraw']:.2f} screens > {limits['overdraw']} ({platform})")
    if peak["emitters"] > limits["emitters"]:
        findings.append(f"{peak['emitters']} emitters at once > {limits['emitters']}")
    if peak["additive"] > limits["additive"]:
        findings.append(f"{peak['additive']} additive glow layers stacked at once (> {limits['additive']}): whiteout risk")
    if totals["lights"] > limits["lights"]:
        findings.append(f"{totals['lights']} lights > {limits['lights']}")
    if totals["shadow_lights"] > limits["shadow_lights"]:
        findings.append("lights with Shadows on")
    if max_rate > limits["rate_per_emitter"]:
        findings.append(f"emitter rate {max_rate:.0f}/s > the {platform} cap {limits['rate_per_emitter']}/s")
    cap = COMPOSER_BUDGET * limits["quality"]
    if requested > cap:
        findings.append(f"requested {requested:.0f} particles > composer cap {cap:.0f}: later layers get starved")
    return {"platform": platform, "ok": not findings, "findings": findings,
            "live_peak": round(peak["live"]), "live_sum": round(live_sum), "t_live_peak": round(peak["t_live"], 2),
            "overdraw_peak": round(peak["overdraw"], 3), "emitters_peak": peak["emitters"],
            "additive_peak": peak["additive"], "requested_particles": round(requested), "composer_cap": round(cap),
            "max_rate": round(max_rate, 1), "layers": len(layers), **totals}


SCALABLE = ("particles", "burst", "sparks", "smoke", "aura", "projectile", "debris")


def _scale_cue(cue: dict, count_k: float, life_k: float) -> dict:
    cue = json.loads(json.dumps(cue))
    p = cue.get("params") or {}
    for key in ("count", "rate"):
        if isinstance(p.get(key), (int, float)) and p[key] > 0:
            p[key] = max(1, round(p[key] * count_k, 2)) if key == "rate" else max(1, round(p[key] * count_k))
    if cue["fx"] == "aura" and "count" not in p:
        p["count"] = round(60 * count_k)
    for key in ("life", "emitLife"):
        if isinstance(p.get(key), (int, float)):
            p[key] = round(max(0.1, p[key] * life_k), 3)
    cue["params"] = p or None
    return cue


def auto_reduce(cues: list[dict], style: dict, *, intensity: float = 1.0, platform: str = "pc",
                rounds: int = 4) -> tuple[list[dict], dict, list[str]]:
    """Scale particle counts / rates (and a little lifetime) until the platform budget's live, overdraw, additive and
    composer-cap checks pass. Returns (cues, final budget, actions)."""
    limits = BUDGETS[platform]
    actions = []
    report = check_budget(cues, style, intensity=intensity, platform=platform)
    for _ in range(rounds):
        ratios = [limits["live"] / max(1, report["live_peak"]), limits["overdraw"] / max(1e-6, report["overdraw_peak"]),
                  report["composer_cap"] / max(1, report["requested_particles"])]
        k = min(ratios)
        if k >= 1:
            break
        k = max(0.2, k * 0.95)
        count_k, life_k = k ** 0.75, k ** 0.25
        cues = [_scale_cue(c, count_k, life_k) if c["fx"] in SCALABLE else c for c in cues]
        actions.append(f"scaled counts/rates x{count_k:.2f}, lifetimes x{life_k:.2f}")
        report = check_budget(cues, style, intensity=intensity, platform=platform)
    return cues, report, actions


# --------------------------------------------------------------------------- critique -> one fix pass

VISION_PROBLEMS = ("too_small", "too_faint", "too_bright", "too_busy", "wrong_colour", "too_short", "static",
                   "not_visible", "fine")


def vision_prompt(brief: str) -> str:
    return (f"This contact sheet shows frames of a Roblox visual effect in time order (left to right, top to bottom; "
            f"labels are frame number and time). The effect should be: {brief.strip()[:400]}\n"
            "Judge how well it reads. Answer with ONE JSON object only: "
            '{"score": <1-5>, "problems": [<zero or more of ' + json.dumps(list(VISION_PROBLEMS)) + '>], '
            '"note": "<one short sentence>"}')


def facts_prompt(brief: str, render: dict, plan: dict) -> list[dict]:
    """Fallback critic when the vision model is unavailable: the local text model judges measured facts of the
    render (frame metrics, what the effect created) against the brief, in the same JSON vocabulary as the vision
    critique."""
    scores = (render.get("critique") or {}).get("scores") or {}
    census = (render.get("census") or {}).get("effect_peak") or {}
    facts = {"frames": render.get("frames"), "frames_with_visible_change": scores.get("visible_frames"),
             "largest_picture_change_0_to_1": scores.get("impact_change"),
             "share_of_pixels_in_main_colour": scores.get("palette_share"),
             "mean_change_between_frames": scores.get("motion"), "effect_objects_at_peak": census,
             "archetype": plan.get("archetype"), "scale": plan.get("scale"), "intensity": plan.get("intensity")}
    return [{"role": "user", "content": (
        f"A Roblox visual effect was rendered for this brief: {brief.strip()[:400]}\n"
        f"Measured facts of the render (camera 17 studs away, real time): {json.dumps(facts)}\n"
        "Rules of thumb: largest change < 0.06 means hard to see; main-colour share < 0.03 means the colour barely "
        "shows; visible change in under a third of the frames means too short or too small.\n"
        'Answer with ONE JSON object only: {"score": <1-5>, "problems": [<zero or more of '
        + json.dumps(list(VISION_PROBLEMS)) + '>], "note": "<one short sentence>"}')}]


def parse_vision(text: str) -> dict:
    data = _json_object(text) or {}
    problems = [p for p in data.get("problems", []) if p in VISION_PROBLEMS and p != "fine"] \
        if isinstance(data.get("problems"), list) else []
    score = data.get("score")
    return {"score": score if isinstance(score, (int, float)) else None, "problems": problems[:4],
            "note": str(data.get("note", ""))[:200], "parsed": bool(data)}


# Metric findings that compare stage time windows: at real-time capture (~0.6 s per frame, a capture lag of about a
# second) the windows do not line up with the frames, so these are not acted on unless the capture was slow motion.
TIMED_FINDINGS = ("weak impact", "impact does not stand out", "charge-up", "effect visible in few frames",
                  "the picture does not return")


def fixes_for(metric: dict | None, vision: dict | None, *, realtime: bool = True) -> dict:
    """Map the metric critique findings and the vision problems onto plan multipliers (deterministic)."""
    fix: dict[str, float] = {}

    def mul(key, value):
        fix[key] = round(fix.get(key, 1.0) * value, 3)

    for finding in (metric or {}).get("findings", []):
        if realtime and finding.startswith(TIMED_FINDINGS):
            continue
        if finding.startswith("weak impact"):
            mul("intensity", 1.25)
        elif finding.startswith("the style's main colour"):
            mul("intensity", 1.15)
        elif finding.startswith("effect visible in few frames"):
            mul("follow_through", 1.3)
        elif finding.startswith("little motion"):
            mul("scale", 1.2)
    for problem in (vision or {}).get("problems", []):
        if problem in ("too_small", "not_visible"):
            mul("scale", 1.35)
        if problem in ("too_faint", "not_visible"):
            mul("intensity", 1.3)
        if problem in ("too_bright", "too_busy"):
            mul("intensity", 0.75)
        if problem == "too_short":
            mul("follow_through", 1.4)
        if problem == "static":
            mul("scale", 1.15)
    return {k: v for k, v in fix.items() if abs(v - 1.0) > 0.01}


def apply_fixes(plan: dict, fix: dict) -> dict:
    plan = json.loads(json.dumps(plan))
    if "scale" in fix:
        plan["scale"] = _num(plan["scale"] * fix["scale"], 0.5, 2.0, 1.0)
    if "intensity" in fix:
        plan["intensity"] = _num(plan["intensity"] * fix["intensity"], 0.3, 1.5, 1.0)
    if "follow_through" in fix:
        plan["timing"]["follow_through"] = _num(plan["timing"]["follow_through"] * fix["follow_through"], 0.2, 4.0, 1.0)
    return plan


# --------------------------------------------------------------------------- rendering (one lab run)

CENSUS_CLIENT = r"""--!strict
-- STAR VFX lab census (Studio playtest only): counts what the effect creates on this client, the same for any
-- effect code. Particles from Emit() bursts are invisible to scripts, so live_rate counts continuous emitters only.
-- Only instances within RANGE studs of the lab stage count (other scripts in the place make their own parts).
local HttpService = game:GetService("HttpService")
local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local config = require(ReplicatedStorage:WaitForChild("StarVfxLab"):WaitForChild("VfxLabConfig")) :: any
local stage = Vector3.new(config.origin[1], config.origin[2], config.origin[3])
local RANGE = 80
local function near(inst: Instance): boolean
	local at: Instance? = inst
	while at and not at:IsA("BasePart") and not at:IsA("Attachment") do
		at = at.Parent
	end
	if at == nil then
		return true -- not placed in the world (e.g. a ScreenGui or a post effect): count it
	end
	local position = if at:IsA("BasePart") then at.Position else (at :: Attachment).WorldPosition
	return (position - stage).Magnitude <= RANGE
end
local tracked: { Instance } = {}
local created = { emitters = 0, beams = 0, trails = 0, lights = 0, parts = 0, highlights = 0, post = 0 }
workspace.DescendantAdded:Connect(function(inst)
	if inst:IsA("ParticleEmitter") then created.emitters += 1
	elseif inst:IsA("Beam") then created.beams += 1
	elseif inst:IsA("Trail") then created.trails += 1
	elseif inst:IsA("Light") then created.lights += 1
	elseif inst:IsA("Highlight") then created.highlights += 1
	elseif inst:IsA("BasePart") then created.parts += 1
	else return end
	table.insert(tracked, inst)
end)
Lighting.DescendantAdded:Connect(function(inst)
	if inst:IsA("PostEffect") then created.post += 1 end
end)
local peak = { emitters = 0, live_rate = 0, additive = 0, beams = 0, trails = 0, lights = 0, shadow_lights = 0, parts = 0 }
local tick = 0
local first = nil -- the first sample (before any effect plays) is the scene's own baseline
while true do
	task.wait(0.2)
	tick += 1
	local now = { emitters = 0, live_rate = 0, additive = 0, beams = 0, trails = 0, lights = 0, shadow_lights = 0, parts = 0 }
	local keep: { Instance } = {}
	for _, inst in tracked do
		local character = Players.LocalPlayer.Character
		if inst.Parent and not (character and inst:IsDescendantOf(character)) and near(inst) then
			table.insert(keep, inst)
			if inst:IsA("ParticleEmitter") then
				now.emitters += 1
				if inst.Enabled then now.live_rate += inst.Rate * (inst.Lifetime.Min + inst.Lifetime.Max) / 2 end
				if inst.LightEmission >= 0.8 then now.additive += 1 end
			elseif inst:IsA("Beam") then now.beams += 1
			elseif inst:IsA("Trail") then now.trails += 1
			elseif inst:IsA("Light") then
				now.lights += 1
				if (inst :: any).Shadows then now.shadow_lights += 1 end
			elseif inst:IsA("BasePart") then now.parts += 1 end
		end
	end
	tracked = keep
	if first == nil then
		first = table.clone(now)
	end
	for key, value in now do
		if value > (peak :: any)[key] then (peak :: any)[key] = value end
	end
	if tick % 10 == 0 then -- every 2 s: keep the console readable for the lab markers
		print("STARVFX census " .. HttpService:JSONEncode({ peak = peak, first = first, created = created }))
	end
end
"""


def with_census(apply_code: str) -> str:
    """Add the census LocalScript (inside the lab client, so the lab's remove step deletes it) to apply Luau."""
    head, _, last = apply_code.rpartition("\n")
    if not last.startswith("return ") or "local client = " not in head:
        raise ValueError("unexpected apply Luau")
    return "\n".join([head, 'local census = Instance.new("LocalScript") census.Name = "StarVfxLabCensus"',
                      f"census.Source = {vfx._long_string(CENSUS_CLIENT)}", "census.Parent = client", last])


def parse_census(console: str) -> dict | None:
    found = re.findall(r"STARVFX census (\{.*\})", console or "")
    if not found:
        return None
    try:
        census = json.loads(found[-1])
    except ValueError:
        return None
    first = census.get("first") or {}
    census["effect_peak"] = {k: round(max(0, v - first.get(k, 0)), 1) for k, v in (census.get("peak") or {}).items()}
    return census


def sheet_frames(frames: list[dict], lead: int = 1) -> list[dict]:
    """Frames for the contact sheet: from `lead` frames before the effect started to the end (drop the idle wait)."""
    first = next((i for i, f in enumerate(frames) if f.get("effect_t", -1) >= 0), 0)
    return frames[max(0, first - lead):] or frames


async def render_spec(lab, spec: dict, run: str, *, apply_code: str | None = None, title: str = "",
                      critique: bool = True) -> dict:
    """One lab render on a roblox_vfx_studio.VfxLab: apply (composer lab + census) -> playtest frames -> neutral
    contact sheet -> metric critique -> census. `apply_code` replaces the composer install (an eval baseline)."""
    started = time.monotonic()
    lab.out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"run": run}
    code = apply_code or with_census(vfx.apply_luau(spec, run))
    ok, text = await lab._luau(code)
    report["apply"] = {"ok": ok and f"{vfx.MARK}_APPLY {run}" in text, "detail": text[:300]}
    if report["apply"]["ok"]:
        play = await lab._playtest(spec, run)
        frames = play.pop("_frames", [])
        report["playtest"] = {k: v for k, v in play.items() if k != "frame_files"}
        console_file = lab.out / "playtest-output.txt"
        report["census"] = parse_census(console_file.read_text(encoding="utf-8")) if console_file.exists() else None
        if frames:
            picked = sheet_frames(frames)
            report["sheet"] = vfx.contact_sheet(picked, lab.out / "sheet.jpg", title=title)
            report["sheet_path"] = str(lab.out / "sheet.jpg")
            report["frames"] = len(frames)
            if critique:
                report["critique"] = vfx.critique(frames, spec["style"])
                report["critique"].pop("frames", None)
    report["render_s"] = round(time.monotonic() - started, 1)
    (lab.out / "render.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def lab_spec(spec: dict, cycles: int = 2) -> dict:
    """Lab timing shared by every eval arm: real time, PERIOD seconds per cycle, the same capture window."""
    return {**spec, "speed": 1.0, "length": PERIOD, "gap": 0.0, "cycles": cycles, "lead": 5, "timer": False,
            "camera": LAB_CAMERA, "lookHeight": LAB_LOOK, "clock": LAB_CLOCK}


# --------------------------------------------------------------------------- the whole loop

Chat = Callable[[list], tuple[str, float]]


def design(brief: str, chat: Chat, *, textures: dict | None = None, platform: str = "pc") -> dict:
    """brief -> plan (model) -> spec (deterministic) -> budget check + auto-reduce. Returns the design record."""
    t0 = time.monotonic()
    text, plan_s = chat(plan_prompt(brief))
    plan, problems = normalize_plan(text, brief)
    plan["brief"] = brief
    return _build(plan, problems, textures, platform, {"plan_s": plan_s, "raw_plan": text[:1500]}, t0)


def _build(plan: dict, problems: list, textures, platform: str, extra: dict, t0: float) -> dict:
    t1 = time.monotonic()
    spec = compose(plan, textures=textures)
    before = check_budget(spec["ability"]["cues"], spec["style"], intensity=spec["intensity"], platform=platform)
    cues, after, actions = auto_reduce(spec["ability"]["cues"], spec["style"], intensity=spec["intensity"],
                                       platform=platform)
    spec["ability"]["cues"] = cues
    mobile = check_budget(cues, spec["style"], intensity=spec["intensity"], platform="mobile")
    return {"plan": plan, "plan_problems": problems, "spec": spec, "budget_before": before, "budget": after,
            "budget_mobile": mobile, "reduce_actions": actions, "compose_ms": round((time.monotonic() - t1) * 1000, 1),
            **extra}


async def make_effect(brief: str, chat: Chat, render: Callable[[dict, str], Awaitable[dict]], *,
                      vision: Callable[[str, Path], tuple[str, float]] | None = None, textures: dict | None = None,
                      platform: str = "pc") -> dict:
    """The full STAR loop: design -> render -> metric + vision critique -> at most one fix -> final render.

    `render(spec, tag)` performs one lab render (the caller holds the Studio turn and returns render_spec's report);
    `vision(prompt, sheet_path)` asks the local vision model and returns (text, seconds)."""
    started = time.monotonic()
    record = design(brief, chat, textures=textures, platform=platform)
    first = await render(record["spec"], "r1")
    record["render1"] = first
    review: dict[str, Any] = {"metric": first.get("critique")}
    sheet = first.get("sheet_path")
    if vision and sheet:
        text, seconds = vision(vision_prompt(brief), Path(sheet))
        review["vision"] = parse_vision(text)
        review["vision_s"] = seconds
        review["vision_raw"] = text[:600]
        review["critic"] = "vision"
        if not review["vision"]["parsed"] and first.get("frames"):
            # vision model unavailable or unparseable: one text critique of the measured facts instead
            text, seconds = chat(facts_prompt(brief, first, record["plan"]))
            review["vision"] = parse_vision(text)
            review["vision_s"] = round(review["vision_s"] + seconds, 1)
            review["vision_raw"] = text[:600]
            review["critic"] = "text-facts"
    fix = fixes_for(review.get("metric"), review.get("vision"), realtime=record["spec"].get("speed", 1) >= 0.5)
    review["fix"] = fix
    record["review"] = review
    if fix:
        plan = apply_fixes(record["plan"], fix)
        rebuilt = _build(plan, record["plan_problems"], textures, platform, {}, time.monotonic())
        record["fixed"] = {k: rebuilt[k] for k in ("plan", "spec", "budget", "budget_mobile", "reduce_actions")}
        record["render2"] = await render(rebuilt["spec"], "r2")
    record["final"] = "render2" if fix else "render1"
    record["total_s"] = round(time.monotonic() - started, 1)
    return record
