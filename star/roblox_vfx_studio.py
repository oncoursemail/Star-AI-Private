"""STAR VFX Studio: design, build, play and visually check Roblox ability VFX in any art style.

The look of an effect is a *style profile* (palette, shape language, texture set, timing curves, intensity and
screen-effect use), the content of an effect is an *ability* (a list of cues on the timeline charge -> impact ->
shockwave -> linger -> dissipate). Both are data; the typed Luau modules of the skill pack
star/skill_packs/roblox-vfx-composer/luau/ (VfxStyles, VfxPrimitives, VfxComposer, VfxClient, VfxService) render them.

This module
  * picks or adapts a profile from a style description and/or a reference image (palette analysis with Pillow),
  * picks a built-in ability or writes a cue list for the prompt ("make a VFX for a healing aura"),
  * generates the Luau (one ModuleScript with the adapted style and the ability) and lints every module with
    STAR's Luau checks,
  * applies it in STAR Test Place through the guarded Studio path (studio_remote.PinnedSession ->
    studio_loop.GuardedStudio: sandbox rule, one undo step), starts a playtest in which a lab Script plays the effect
    in slow motion through the real RemoteEvent path (server validation -> every client renders), captures a frame
    sequence with the connector's screen_capture, stops, and
  * returns frame evidence: frames, a labelled contact sheet and a measured critique (impact flash, palette match,
    motion, layering, dissipation), all advisory.

Off by default: the STAR tool `star_roblox_vfx_make` is offered only with the setting `vfx_studio_enabled` or
STAR_VFX_STUDIO=1. Nothing is saved or published; textures default to Roblox's built-in rbxasset:// set.
CLI: python -m star.roblox_vfx_studio plan|run|remove ...
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import colorsys
import hashlib
import io
import json
import math
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

PACK_DIR = Path(__file__).resolve().parent / "skill_packs" / "roblox-vfx-composer"
LUAU_DIR = PACK_DIR / "luau"
SHARED_MODULES = ("VfxStyles", "VfxPrimitives", "VfxComposer", "VfxClient")
SERVER_MODULE = "VfxService"
LAB_FOLDER = "StarVfxLab"            # ReplicatedStorage.StarVfxLab (modules), ServerScriptService.StarVfxLab (Script)
LAB_CLIENT = "StarVfxLabClient"      # StarterPlayer.StarterPlayerScripts.StarVfxLabClient
MARK = "STARVFX"
STAGE_ORIGIN = (-300.0, 0.0, 300.0)  # empty baseplate in STAR Test Place, away from the lobby and map drafts
MAX_FRAMES = 60
STAGES = ("charge", "impact", "shockwave", "linger", "dissipate")
FX = ("burst", "sparks", "smoke", "ring", "ringSegments", "dome", "pillar", "slashes", "vortex", "crack", "debris",
      "spikes", "aura", "light", "flash", "tint", "shake", "particles", "beam", "projectile", "sweep")

# --------------------------------------------------------------------------- style profiles (mirror of VfxStyles)

# Python mirror of the built-in profiles in VfxStyles.luau (tests keep the two in step). `keywords` and `traits`
# are used to choose a profile from words or from a reference image.
STYLES: dict[str, dict] = {
    "anime_energy": {
        "label": "Anime energy", "shape": "jagged",
        "palette": {"core": (235, 255, 235), "glow": (40, 255, 90), "dark": (4, 30, 10), "accent": (170, 255, 120),
                    "flash": (225, 255, 225)},
        "timing": {"charge": 0.9, "impact": 0.18, "shockwave": 0.6, "linger": 1.1, "dissipate": 0.9},
        "screen": {"flash": 0.85, "invert": True, "tint": 0.45, "bloom": 1.4, "shake": 1.1, "fovPunch": 9},
        "keywords": ("anime", "manga", "energy", "aura", "ki", "chakra", "power up", "ultimate", "awakening", "shonen",
                     "jujutsu", "dragon ball", "beam", "blast", "electric", "lightning", "saturated", "glow"),
        "traits": {"saturation": "high", "value": "any", "hues": 1},
    },
    "cartoon_soft": {
        "label": "Stylized cartoon / soft", "shape": "round",
        "palette": {"core": (255, 255, 255), "glow": (255, 170, 215), "dark": (120, 90, 170),
                    "accent": (140, 220, 255), "flash": (255, 245, 250)},
        "timing": {"charge": 0.6, "impact": 0.22, "shockwave": 0.55, "linger": 0.5, "dissipate": 0.7},
        "screen": {"flash": 0.25, "invert": False, "tint": 0.15, "bloom": 0.0, "shake": 0.25, "fovPunch": 3},
        "keywords": ("cartoon", "cute", "soft", "toon", "pastel", "bubbly", "kawaii", "playful", "bouncy", "candy",
                     "friendly", "kids", "puffy", "cel"),
        "traits": {"saturation": "mid", "value": "high", "hues": 2},
    },
    "realistic_fire": {
        "label": "Realistic fire, smoke and magic", "shape": "wispy",
        "palette": {"core": (255, 236, 180), "glow": (255, 120, 30), "dark": (40, 34, 32), "accent": (255, 70, 20),
                    "flash": (255, 210, 160)},
        "timing": {"charge": 0.5, "impact": 0.15, "shockwave": 0.7, "linger": 0.9, "dissipate": 1.6},
        "screen": {"flash": 0.35, "invert": False, "tint": 0.12, "bloom": 0.4, "shake": 0.7, "fovPunch": 4},
        "keywords": ("realistic", "fire", "flame", "smoke", "explosion", "burn", "ember", "magic", "spell", "dust",
                     "grounded", "cinematic", "natural", "volcan", "lava", "torch"),
        "traits": {"saturation": "mid", "value": "mid", "hues": 1, "warm": True},
    },
    "scifi_neon": {
        "label": "Sci-fi / neon tech", "shape": "crisp",
        "palette": {"core": (230, 255, 255), "glow": (0, 220, 255), "dark": (10, 10, 40), "accent": (255, 40, 200),
                    "flash": (200, 250, 255)},
        "timing": {"charge": 0.7, "impact": 0.12, "shockwave": 0.45, "linger": 0.9, "dissipate": 0.5},
        "screen": {"flash": 0.5, "invert": False, "tint": 0.3, "bloom": 0.9, "shake": 0.5, "fovPunch": 5},
        "keywords": ("sci-fi", "scifi", "science fiction", "neon", "cyber", "tech", "hologram", "laser", "plasma",
                     "futuristic", "synthwave", "robot", "mech", "digital", "hex", "shield"),
        "traits": {"saturation": "high", "value": "any", "hues": 2, "cool": True},
    },
    "pixel_retro": {
        "label": "Pixel / retro", "shape": "blocky",
        "palette": {"core": (255, 255, 255), "glow": (255, 204, 0), "dark": (60, 30, 90), "accent": (255, 80, 80),
                    "flash": (255, 255, 255)},
        "timing": {"charge": 0.6, "impact": 0.2, "shockwave": 0.6, "linger": 0.6, "dissipate": 0.6},
        "screen": {"flash": 0.6, "invert": False, "tint": 0.0, "bloom": 0.0, "shake": 0.6, "fovPunch": 0},
        "keywords": ("pixel", "retro", "8-bit", "8 bit", "16-bit", "arcade", "voxel", "blocky", "minecraft", "nes",
                     "snes", "chiptune", "lo-fi", "low poly", "lowpoly"),
        "traits": {"saturation": "any", "value": "any", "hues": 3, "posterized": True},
    },
}
DEFAULT_STYLE = "anime_energy"

# Colour words -> RGB for "a purple anime blast" style recolouring.
COLOUR_WORDS = {
    "red": (255, 45, 45), "crimson": (220, 20, 60), "orange": (255, 140, 20), "gold": (255, 200, 40),
    "yellow": (255, 230, 40), "lime": (160, 255, 40), "green": (40, 255, 90), "emerald": (20, 220, 120),
    "teal": (20, 220, 200), "cyan": (0, 230, 255), "aqua": (60, 240, 240), "blue": (40, 110, 255),
    "navy": (30, 50, 160), "purple": (160, 60, 255), "violet": (140, 80, 255), "magenta": (255, 40, 220),
    "pink": (255, 110, 190), "white": (245, 245, 255), "black": (20, 20, 24), "silver": (200, 210, 225),
    "ice": (170, 230, 255), "frost": (180, 235, 255), "blood": (170, 10, 20), "shadow": (70, 30, 110),
    "holy": (255, 240, 170), "void": (90, 20, 140), "poison": (130, 230, 40), "water": (40, 150, 255),
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _rgb_to_hsv(rgb) -> tuple[float, float, float]:
    r, g, b = (_clamp(float(c), 0, 255) / 255 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, _clamp(s, 0, 1), _clamp(v, 0, 1))
    return (round(r * 255), round(g * 255), round(b * 255))


def palette_from_hue(base: str, rgb) -> dict:
    """Recolour a profile's palette around a new main colour, keeping the profile's value/saturation relations."""
    h, s, v = _rgb_to_hsv(rgb)
    old = {k: _rgb_to_hsv(c) for k, c in STYLES[base]["palette"].items()}
    out = {}
    for key, (oh, os_, ov) in old.items():
        if key == "glow":
            out[key] = tuple(int(c) for c in rgb)
        elif key == "accent":
            shift = 0.06 if base != "scifi_neon" else 0.5      # neighbour hue, or the complement for two-tone tech
            out[key] = _hsv_to_rgb(h + shift, max(os_, s * 0.8), max(ov, 0.8))
        else:
            out[key] = _hsv_to_rgb(h, min(os_, s), ov)
    return out


# --------------------------------------------------------------------------- reference image analysis

def _pixels(image) -> list:
    getter = getattr(image, "get_flattened_data", None)
    return list(getter() if getter else image.getdata())


def analyse_image(data: bytes, *, max_side: int = 160) -> dict:
    """Palette facts of a reference image: dominant colours, saturation/brightness, hue spread, posterization.

    Needs Pillow; reads only the given bytes. The facts drive the profile choice, never a copy of the image."""
    from PIL import Image
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.thumbnail((max_side, max_side))
    pixels = _pixels(image)
    if not pixels:
        raise ValueError("empty image")
    hsv = [_rgb_to_hsv(p) for p in pixels]
    sat = sum(s for _, s, _ in hsv) / len(hsv)
    val = sum(v for _, _, v in hsv) / len(hsv)
    bright = sorted(v for _, _, v in hsv)
    # hue histogram weighted by colourfulness (saturation * value): what the eye reads as "the colour"
    bins = [0.0] * 12
    for h, s, v in hsv:
        weight = s * v
        if weight > 0.15:
            bins[int(h * 12) % 12] += weight
    total = sum(bins) or 1.0
    ranked = sorted(range(12), key=lambda i: -bins[i])
    hues = [i for i in ranked if bins[i] / total >= 0.12]
    main_bin = ranked[0]
    members = [(p, h) for p, (h, s, v) in zip(pixels, hsv) if int(h * 12) % 12 == main_bin and s * v > 0.15]
    if members:
        strongest = sorted(members, key=lambda m: -(_rgb_to_hsv(m[0])[1] * _rgb_to_hsv(m[0])[2]))[: max(1, len(members) // 4)]
        main = tuple(round(sum(p[i] for p, _ in strongest) / len(strongest)) for i in range(3))
    else:
        main = tuple(round(sum(p[i] for p in pixels) / len(pixels)) for i in range(3))
    quantized = image.quantize(colors=64)
    used = [count for count, _ in (quantized.getcolors(64) or [])]
    used.sort(reverse=True)
    covered = sum(used[:8]) / max(1, sum(used))
    distinct = sum(1 for count in used if count / max(1, sum(used)) >= 0.02)
    return {
        "mean_saturation": round(sat, 3), "mean_value": round(val, 3),
        "dark_share": round(sum(1 for v in bright if v < 0.25) / len(bright), 3),
        "bright_share": round(sum(1 for v in bright if v > 0.85) / len(bright), 3),
        "hue_bins": len(hues), "main_rgb": main, "main_hue_deg": round(_rgb_to_hsv(main)[0] * 360),
        "top8_colour_share": round(covered, 3), "distinct_colours": distinct, "colourful_share": round(sum(1 for _, s, v in hsv if s * v > 0.15) / len(hsv), 3),
    }


def _image_scores(facts: dict) -> dict[str, float]:
    sat, val = facts["mean_saturation"], facts["mean_value"]
    hue = facts["main_hue_deg"]
    warm = hue <= 50 or hue >= 340
    cool = 170 <= hue <= 320
    scores = {name: 0.0 for name in STYLES}
    if facts["top8_colour_share"] >= 0.95 and facts.get("distinct_colours", 0) >= 3:
        scores["pixel_retro"] += 2.5     # a few flat colours and no gradients: palette-limited pixel art
    if sat >= 0.45 and facts["hue_bins"] <= 1 and facts["colourful_share"] >= 0.25:
        scores["anime_energy"] += 1.0 if warm else 2.0   # one saturated warm hue reads as fire first
    if facts["hue_bins"] >= 2 and cool and sat >= 0.35:
        scores["scifi_neon"] += 1.6
    if cool and facts["dark_share"] >= 0.3:
        scores["scifi_neon"] += 0.6
    if warm and sat >= 0.25:
        scores["realistic_fire"] += 1.6
    if val >= 0.65 and 0.08 <= sat <= 0.55:     # bright, gently coloured: pastel
        scores["cartoon_soft"] += 1.8
    if facts["dark_share"] >= 0.35 and sat >= 0.4:
        scores["anime_energy"] += 0.6
    return scores


# --------------------------------------------------------------------------- choosing a style

def choose_style(description: str = "", image: bytes | None = None) -> dict:
    """Pick (and adapt) a style profile from words and/or a reference image.

    Returns {base, name, palette, reasons, image?}. `palette` is set when a colour word or the image's main colour
    recolours the base profile; the shape language, timing and screen rules stay the base profile's."""
    text = (description or "").lower()
    scores = {name: 0.0 for name in STYLES}
    reasons: list[str] = []
    for name, profile in STYLES.items():
        hits = [k for k in profile["keywords"] if re.search(r"(?<![a-z])" + re.escape(k), text)]
        if hits:
            scores[name] += 1.0 * len(hits)
            reasons.append(f"{name}: words {', '.join(hits[:4])}")
    facts = None
    if image:
        facts = analyse_image(image)
        for name, value in _image_scores(facts).items():
            if value:
                scores[name] += value
                reasons.append(f"{name}: image +{value:.1f}")
    base = max(STYLES, key=lambda n: (scores[n], n == DEFAULT_STYLE))
    if scores[base] == 0:
        base = DEFAULT_STYLE
        reasons.append("no style words or image: default profile")
    palette = None
    colours = [w for w in COLOUR_WORDS if re.search(r"\b" + re.escape(w) + r"\b", text)]
    if colours:
        palette = palette_from_hue(base, COLOUR_WORDS[colours[0]])
        reasons.append(f"recoloured to '{colours[0]}'")
    elif facts and facts["colourful_share"] >= 0.08 and base != "pixel_retro":
        palette = palette_from_hue(base, facts["main_rgb"])
        reasons.append(f"recoloured to the image's main colour {facts['main_rgb']}")
    slug = re.sub(r"[^a-z0-9]+", "_", (colours[0] + "_" if colours else "") + base)[:40]
    choice = {"base": base, "name": slug if palette else base, "palette": palette, "reasons": reasons,
              "scores": {k: round(v, 2) for k, v in scores.items()}}
    if facts:
        choice["image"] = facts
    return choice


# --------------------------------------------------------------------------- abilities

def _cue(stage: str, at: float, fx: str, **params) -> dict:
    return {"stage": stage, "at": at, "fx": fx, "params": params or None}


GENERATED_ABILITIES: dict[str, dict] = {
    # Original, editable compositions inspired by user-supplied reference footage:
    # no copying another creator's models, textures, particles or source code.
    "frost_cyclone": {
        "keywords": ("ice vortex", "ice cyclone", "ice storm", "frost cyclone", "ice shards",
                     "crystal storm", "glacial", "blizzard", "frost", "ice blast", "ice spike"),
        "cues": [
            _cue("charge", 0, "aura", dur=0.9),
            _cue("charge", 0.18, "burst", count=20, inward=True, radius=8, speed=9, life=0.8,
                 size=0.35, color="accent", texture="spark", y=3),
            _cue("impact", 0, "flash", strength=0.32, dur=0.13, invert=False),
            _cue("impact", 0, "spikes", count=8, radius=7, height=6, dur=0.85, force=True),
            _cue("impact", 0.12, "light", dur=0.3, range=26, brightness=3),
            _cue("impact", 0.20, "sparks", count=36, speed=48),
            _cue("shockwave", 0, "ringSegments", radius=16, segments=10, height=0.9, thickness=0.3, dur=0.58),
            _cue("shockwave", 0.22, "ring", radius=21, dur=0.52),
            _cue("linger", 0, "vortex", radius=8, arms=5, dur=1.0),
            _cue("linger", 0.18, "burst", count=26, speed=8, life=1.0, size=0.5,
                 color="glow", texture="glow", spread=120, gravity=-5),
            _cue("dissipate", 0.08, "smoke", count=9, life=0.9, size=1.8, speed=4),
            _cue("dissipate", 0.25, "burst", count=12, speed=4, life=0.6, size=0.25,
                 color="accent", texture="spark", spread=180),
        ],
    },
    "cinematic_sword_arc": {
        "keywords": ("anime sword", "sword slash", "blade arc", "katana", "weapon swing",
                     "sword trail", "blade trail", "slash arc", "crescent slash", "slash"),
        "cues": [
            _cue("charge", 0, "aura", dur=0.32),
            _cue("charge", 0.30, "burst", count=9, speed=6, life=0.28, size=0.22,
                 color="accent", texture="spark", spread=25, y=2.5),
            _cue("impact", 0, "slashes", count=2, length=21, dur=0.24, gap=0.05, y=2.8),
            _cue("impact", 0, "flash", strength=0.24, dur=0.10, invert=False),
            _cue("impact", 0.12, "light", dur=0.20, range=24, brightness=3),
            _cue("impact", 0.16, "sparks", count=24, speed=44),
            _cue("impact", 0.32, "shake", amplitude=0.28, dur=0.16),
            _cue("shockwave", 0, "ringSegments", radius=10, segments=8, height=0.4,
                 thickness=0.2, dur=0.24),
            _cue("linger", 0, "slashes", count=1, length=23, dur=0.32, y=2.6),
            _cue("dissipate", 0, "burst", count=14, speed=6, life=0.52, size=0.2,
                 color="accent", texture="spark", spread=70, y=2.7),
        ],
    },
    "heal_aura": {"keywords": ("heal", "healing", "buff", "regen", "bless", "restore", "shield up", "aura"),
                  "cues": [
                      _cue("charge", 0, "aura", dur=2.2),
                      _cue("charge", 0.1, "tint", dur=2.5),
                      _cue("charge", 0.3, "burst", count=40, speed=8, life=1.2, size=0.6, texture="spark", color="core",
                           gravity=-14, y=0.5, spread=30),
                      _cue("impact", 0, "ring", radius=12, y=0.4),
                      _cue("impact", 0, "light", dur=1.0, range=30),
                      _cue("impact", 0.2, "flash", strength=0.3, invert=False),
                      _cue("shockwave", 0, "dome", radius=7),
                      _cue("linger", 0, "burst", count=50, speed=5, life=1.6, size=0.8, texture="glow", color="glow",
                           gravity=-10, y=0.2, spread=20),
                      _cue("dissipate", 0, "burst", count=24, speed=3, life=1.4, size=0.4, texture="spark", color="accent",
                           gravity=-8, y=3, spread=180),
                  ]},
    "explosion": {"keywords": ("explosion", "explode", "grenade", "bomb", "blast", "detonat", "nuke", "missile"),
                  "cues": [
                      _cue("impact", 0, "flash"),
                      _cue("impact", 0, "light", dur=0.8, range=60),
                      _cue("impact", 0, "burst", count=30, speed=14, life=0.45, size=5, texture="glow", color="core",
                           drag=5, y=3, spread=180, lightEmission=1),
                      _cue("impact", 0.1, "burst", count=40, speed=22, life=0.8, size=6, texture="glow", color="glow",
                           drag=4, gravity=-12, y=3, spread=180, lightEmission=1),
                      _cue("impact", 0, "dome", radius=14),
                      _cue("impact", 0, "sparks", count=80, speed=90),
                      _cue("impact", 0, "debris", count=22, speed=55),
                      _cue("impact", 0, "crack", radius=14),
                      _cue("impact", 0.1, "shake", amplitude=1.2, dur=0.7),
                      _cue("shockwave", 0, "ring", radius=34),
                      _cue("shockwave", 0.1, "smoke", count=26, size=7, life=2.2),
                      _cue("linger", 0, "smoke", count=14, size=9, life=2.6, speed=8),
                      _cue("dissipate", 0, "burst", count=30, speed=10, life=1.6, size=0.4, texture="spark",
                           color="accent", gravity=-6, y=3, spread=180),
                  ]},
}
BUILTIN_ABILITIES = {
    "energy_burst": ("burst", "ability", "ultimate", "slam", "ground", "power", "charge", "vortex", "pillar", "special",
                     "skill", "move", "attack", "nova"),
    "impact_hit": ("hit", "impact", "punch", "kick", "bullet", "projectile", "sword", "slash hit", "strike", "melee"),
}


def choose_ability(prompt: str) -> dict:
    """A built-in ability or a generated cue list for the prompt. Returns {name, builtin, cues?, reason}."""
    text = (prompt or "").lower()
    best, best_hits, best_builtin = "energy_burst", 0, True
    for name, words in BUILTIN_ABILITIES.items():
        hits = sum(1 for w in words if w in text)
        if hits > best_hits:
            best, best_hits, best_builtin = name, hits, True
    for name, spec in GENERATED_ABILITIES.items():
        hits = sum(1 for w in spec["keywords"] if w in text)
        if hits > best_hits:
            best, best_hits, best_builtin = name, hits, False
    out = {"name": best, "builtin": best_builtin,
           "reason": "matched words" if best_hits else "default ability (no specific words)"}
    if not best_builtin:
        out["cues"] = GENERATED_ABILITIES[best]["cues"]
    return out


def validate_ability(ability: dict) -> list[str]:
    """Problems with a generated ability (the Luau composer checks the same rules again at run time)."""
    problems = []
    cues = ability.get("cues")
    if not isinstance(ability.get("name"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", ability["name"]):
        problems.append("name must be lower_snake_case, 1..40 characters")
    if not isinstance(cues, list) or not 1 <= len(cues) <= 64:
        return problems + ["cues must be a list of 1..64 cues"]
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict) or cue.get("stage") not in STAGES:
            problems.append(f"cue {index}: unknown stage")
            continue
        if not isinstance(cue.get("at"), (int, float)) or not 0 <= cue["at"] <= 1:
            problems.append(f"cue {index}: 'at' must be 0..1")
        if cue.get("fx") not in FX:
            problems.append(f"cue {index}: unknown effect {cue.get('fx')!r}")
        params = cue.get("params")
        if params is not None and (not isinstance(params, dict) or len(params) > 24):
            problems.append(f"cue {index}: params must be a small table")
    return problems


# --------------------------------------------------------------------------- Luau rendering

def _luau_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return repr(round(float(value), 4)) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        if not re.fullmatch(r"[A-Za-z0-9_ .:/-]{0,120}", value):
            raise ValueError(f"unsafe string {value[:30]!r}")
        return json.dumps(value)
    if isinstance(value, (tuple, list)) and len(value) == 3 and all(isinstance(c, (int, float)) for c in value):
        return "Color3.fromRGB(%d, %d, %d)" % tuple(int(_clamp(c, 0, 255)) for c in value)
    raise ValueError(f"unsupported value {type(value).__name__}")


def _luau_table(params: dict | None) -> str:
    if not params:
        return "nil"
    parts = []
    for key, value in params.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", str(key)):
            raise ValueError(f"unsafe key {key!r}")
        parts.append(f"{key} = {_luau_value(value)}")
    return "{ " + ", ".join(parts) + " }"


TEXTURE_SLOTS = ("glow", "spark", "smoke", "ring", "crack", "streak", "swirl", "flipbook")
_TEXTURE_ID = re.compile(r"rbxassetid://[1-9][0-9]{0,18}|rbxasset://textures/[A-Za-z0-9_/.-]{1,80}")


def textures_for(base: str, textures: dict | None) -> dict:
    """The texture overrides that suit a profile: valid ids only; pixel styles keep their square particles."""
    out = {}
    for slot, value in (textures or {}).items():
        if slot in TEXTURE_SLOTS and isinstance(value, str) and _TEXTURE_ID.fullmatch(value):
            if STYLES.get(base, {}).get("shape") == "blocky" and slot not in ("ring", "crack"):
                continue
            out[slot] = value
    return out


def generated_module(style: dict, ability: dict, *, intensity: float | None = None, textures: dict | None = None) -> str:
    """Luau ModuleScript returning {style = <adapted profile>, ability = <cue list>} for VfxClient to register."""
    base = style["base"]
    if base not in STYLES:
        raise ValueError("unknown base style")
    fields = []
    if style.get("palette"):
        fields.append("palette = { " + ", ".join(f"{k} = {_luau_value(v)}" for k, v in style["palette"].items()) + " }")
    if intensity is not None:
        fields.append(f"intensity = {_luau_value(float(_clamp(intensity, 0.25, 1.5)))}")
    if isinstance(style.get("sizeScale"), (int, float)):
        fields.append(f"sizeScale = {_luau_value(float(_clamp(style['sizeScale'], 0.25, 3)))}")
    timing = style.get("timing")
    if isinstance(timing, dict) and timing:      # stage lengths from a design plan (roblox_vfx_designer)
        fields.append("timing = " + _luau_table({k: float(_clamp(v, 0.02, 10)) for k, v in timing.items()
                                                  if k in STAGES and isinstance(v, (int, float))}))
    screen = style.get("screen")
    if isinstance(screen, dict) and screen:
        fields.append("screen = " + _luau_table({k: v for k, v in screen.items()
                                                  if k in ("flash", "tint", "bloom", "shake", "fovPunch", "invert")}))
    name = re.sub(r"[^a-z0-9_]", "_", style.get("name") or base)[:40]
    lines = ["--!strict", "-- Generated by STAR (star/roblox_vfx_studio.py). Style and ability are data for VfxClient.",
             'local Styles = require(script.Parent:WaitForChild("VfxStyles"))', "",
             f'local style = Styles.custom("{base}", "{name}", {{ {", ".join(fields)} }})']
    own = textures_for(base, textures)
    if own:
        lines.append("style = Styles.withTextures(style, { " + ", ".join(f'{k} = "{v}"' for k, v in sorted(own.items()))
                     + " }) -- the project's own uploaded textures")
    if ability.get("builtin"):
        lines.append("local ability = nil -- built-in ability: " + json.dumps(ability["name"]))
    else:
        problems = validate_ability(ability)
        if problems:
            raise ValueError("; ".join(problems))
        lines.append("local ability = {")
        lines.append(f'\tname = "{ability["name"]}",')
        lines.append("\tcues = {")
        for cue in ability["cues"]:
            lines.append(f'\t\t{{ stage = "{cue["stage"]}", at = {_luau_value(float(cue["at"]))}, fx = "{cue["fx"]}", '
                         f'params = {_luau_table(cue.get("params"))} }},')
        lines.append("\t},")
        lines.append("}")
    lines += ["", f'return {{ style = style, ability = ability, abilityName = "{ability["name"]}" }}', ""]
    return "\n".join(lines)


def pack_sources() -> dict[str, str]:
    """The shipped Luau modules of the skill pack, by module name."""
    return {name: (LUAU_DIR / f"{name}.luau").read_text(encoding="utf-8") for name in (*SHARED_MODULES, SERVER_MODULE)}


def lint_sources(sources: dict[str, str]) -> dict[str, list[dict]]:
    """STAR's static Luau checks over every module (server-trust checks on the server module)."""
    from . import luau_lint
    out = {}
    for name, code in sources.items():
        findings = luau_lint.lint(code, safety_checks=True, server_security=(name == SERVER_MODULE or name.endswith("Server")))
        out[name] = [{"rule": f.rule_id, "line": f.line, "severity": f.severity, "message": f.message} for f in findings]
    return out


def _long_string(text: str) -> str:
    level = 1
    while ("]" + "=" * level + "]") in text:
        level += 1
    return "[" + "=" * level + "[" + text + "]" + "=" * level + "]"


LAB_SERVER = r"""--!strict
-- STAR VFX lab (Studio playtest only): starts VfxService and plays the lab effect on a loop at the lab stage,
-- through the same RemoteEvent path real gameplay uses. Remove with `python -m star.roblox_vfx_studio remove`.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local VfxService = require(script:WaitForChild("VfxService"))
local config = require(ReplicatedStorage:WaitForChild("__FOLDER__"):WaitForChild("VfxLabConfig"))
VfxService.config.abilities[config.ability] = 0.5
table.insert(VfxService.config.styles, config.style)
VfxService.start()
local stage = CFrame.new(config.origin[1], config.origin[2], config.origin[3])
local player = Players:GetPlayers()[1] or Players.PlayerAdded:Wait()
local character = player.Character or player.CharacterAdded:Wait()
task.wait(config.lead) -- time for the lab client to load (client-made instances do not replicate, so no handshake)
for cycle = 1, config.cycles do
	local root = character:FindFirstChild("HumanoidRootPart")
	if root and root:IsA("BasePart") then
		root.Anchored = true
		character:PivotTo(stage * CFrame.new(0, 3, 0) * CFrame.Angles(0, math.rad(config.facing), 0))
	end
	local shield = character:FindFirstChildOfClass("ForceField") -- the spawn bubble would sit over every frame
	if shield then
		shield:Destroy()
	end
	print("__MARK__ play " .. config.run .. " " .. cycle)
	VfxService.playAt(config.ability, config.style, stage, player.UserId, config.speed)
	task.wait(config.length / config.speed + config.gap)
end
print("__MARK__ finished " .. config.run)
"""

LAB_CLIENT_SRC = r"""--!strict
-- STAR VFX lab client (Studio playtest only): registers the generated style/ability, renders effects from the
-- server, holds a fixed lab camera, hides other screen UI for clean frames and shows the effect time in a corner.
local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local folder = ReplicatedStorage:WaitForChild("__FOLDER__")
local VfxClient = require(folder:WaitForChild("VfxClient"))
local generated = require(folder:WaitForChild("VfxGenerated"))
local config = require(folder:WaitForChild("VfxLabConfig"))
VfxClient.registerStyle(generated.style)
if generated.ability then
	VfxClient.registerAbility(generated.ability)
end
local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")
local function hide(gui: Instance)
	if gui:IsA("ScreenGui") and gui.Name ~= "StarVfxLabTimer" and gui.Name ~= "StarVfxFlash" then
		gui.Enabled = false
	end
end
for _, gui in playerGui:GetChildren() do
	hide(gui)
end
playerGui.ChildAdded:Connect(hide)
if config.clock then
	Lighting.ClockTime = config.clock
end
local camera = workspace.CurrentCamera
camera.CameraType = Enum.CameraType.Scriptable
local stage = Vector3.new(config.origin[1], config.origin[2], config.origin[3])
local eye = stage + Vector3.new(config.camera[1], config.camera[2], config.camera[3])
camera.CFrame = CFrame.lookAt(eye, stage + Vector3.new(0, config.lookHeight, 0))
camera.FieldOfView = 70
local label: TextLabel? = nil
if config.timer then
	local gui = Instance.new("ScreenGui")
	gui.Name = "StarVfxLabTimer"
	gui.ResetOnSpawn = false
	gui.DisplayOrder = 60
	local text = Instance.new("TextLabel")
	text.BackgroundTransparency = 0.4
	text.BackgroundColor3 = Color3.new(0, 0, 0)
	text.TextColor3 = Color3.new(1, 1, 1)
	text.Font = Enum.Font.Code
	text.TextSize = 14
	text.Size = UDim2.fromOffset(170, 22)
	text.Position = UDim2.fromOffset(8, 8)
	text.Text = "t=-.--s ready"
	text.Parent = gui
	gui.Parent = playerGui
	label = text
end
local started = 0
local stageName = "ready"
VfxClient.onPlay = function(_name, handle)
	started = os.clock()
	print("__MARK__ client-play " .. config.run .. " length " .. string.format("%.2f", handle.length))
end
VfxClient.start()
local labView = camera.CFrame
-- Hold the lab view every frame right after the default camera (Camera + 1); the composer's shake runs after that
-- (Camera + 2), so it shakes the lab view and never accumulates on a Scriptable camera.
game:GetService("RunService"):BindToRenderStep("StarVfxLabCamera", Enum.RenderPriority.Camera.Value + 1, function()
	camera.CameraType = Enum.CameraType.Scriptable
	camera.CFrame = labView
	local l = label
	if l and started > 0 then
		local t = (os.clock() - started) * config.speed
		l.Text = string.format("t=%.2fs %s", t, config.style)
	end
end)
local readyFlag = Instance.new("BoolValue")
readyFlag.Name = "LabClientReady"
readyFlag.Parent = folder
print("__MARK__ client-ready " .. config.run)
"""


def lab_config(spec: dict, run: str) -> str:
    style = spec["style"]
    length = float(spec.get("length") or style_length(style["base"], style.get("timing")))
    cam = spec.get("camera") or [20, 6, 20]
    values = {
        "run": run, "ability": spec["ability"]["name"], "style": style.get("name") or style["base"],
        "speed": float(_clamp(spec.get("speed", 0.25), 0.05, 1)), "length": float(length),
        "lead": float(spec.get("lead", 5)), "gap": float(spec.get("gap", 2)), "cycles": int(spec.get("cycles", 1)),
        "facing": float(spec.get("facing", 45)), "lookHeight": float(spec.get("lookHeight", 6)),
        "timer": bool(spec.get("timer", True)),
    }
    lines = ["--!strict", "return {"]
    for key, value in values.items():
        lines.append(f"\t{key} = {_luau_value(value)},")
    lines.append(f"\torigin = {{ {', '.join(_luau_value(float(c)) for c in spec.get('origin', STAGE_ORIGIN))} }},")
    lines.append(f"\tcamera = {{ {', '.join(_luau_value(float(c)) for c in cam)} }},")
    clock = spec.get("clock")
    lines.append(f"\tclock = {_luau_value(float(clock)) if isinstance(clock, (int, float)) else 'nil'},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def style_length(base: str, timing: dict | None = None) -> float:
    t = {**STYLES[base]["timing"], **(timing or {})}
    return t["charge"] + t["impact"] + t["shockwave"] * 0.5 + t["linger"] + t["dissipate"]


def apply_luau(spec: dict, run: str) -> str:
    """Edit-DataModel Luau that installs the lab (one undo step through GuardedStudio): the pack modules and the
    generated module in ReplicatedStorage.StarVfxLab, the lab Script (with VfxService inside) in
    ServerScriptService, the lab client in StarterPlayerScripts. Earlier lab copies are replaced; nothing else."""
    sources = pack_sources()
    generated = generated_module(spec["style"], spec["ability"], intensity=spec.get("intensity"),
                                 textures=spec.get("textures"))
    modules = {name: sources[name] for name in SHARED_MODULES}
    modules["VfxGenerated"] = generated
    modules["VfxLabConfig"] = lab_config(spec, run)
    server = LAB_SERVER.replace("__FOLDER__", LAB_FOLDER).replace("__MARK__", MARK)
    client = LAB_CLIENT_SRC.replace("__FOLDER__", LAB_FOLDER).replace("__MARK__", MARK)
    out = ['local RS = game:GetService("ReplicatedStorage")',
           'local SSS = game:GetService("ServerScriptService")',
           'local SPS = game:GetService("StarterPlayer"):WaitForChild("StarterPlayerScripts")',
           f'for _, parent in {{ RS, SSS, SPS }} do for _, name in {{ "{LAB_FOLDER}", "{LAB_CLIENT}" }} do',
           '\tlocal old = parent:FindFirstChild(name) if old then old:Destroy() end end end',
           f'local folder = Instance.new("Folder") folder.Name = "{LAB_FOLDER}"',
           'local function module(name, source) local m = Instance.new("ModuleScript") m.Name = name m.Source = source m.Parent = folder end']
    for name, code in modules.items():
        out.append(f'module("{name}", {_long_string(code)})')
    out += ['folder.Parent = RS',
            f'local lab = Instance.new("Script") lab.Name = "{LAB_FOLDER}" lab.Source = {_long_string(server)}',
            f'local svc = Instance.new("ModuleScript") svc.Name = "{SERVER_MODULE}" svc.Source = {_long_string(sources[SERVER_MODULE])} svc.Parent = lab',
            'lab.Parent = SSS',
            f'local client = Instance.new("LocalScript") client.Name = "{LAB_CLIENT}" client.Source = {_long_string(client)}',
            'client.Parent = SPS',
            f'return "{MARK}_APPLY {run} " .. #folder:GetChildren()']
    return "\n".join(out)


def check_luau(run: str) -> str:
    """Edit-DataModel Luau that requires every installed module once (real Luau parse + type of the returned
    table) and reports problems; the client-only modules are required for their shape only."""
    return (f'local folder = game:GetService("ReplicatedStorage"):FindFirstChild("{LAB_FOLDER}")\n'
            'if not folder then return "missing" end\n'
            'local out = {}\n'
            'for _, name in { "VfxStyles", "VfxPrimitives", "VfxComposer", "VfxGenerated", "VfxLabConfig" } do\n'
            '\tlocal m = folder:FindFirstChild(name)\n'
            '\tlocal ok, result = pcall(require, m)\n'
            '\ttable.insert(out, name .. "=" .. (ok and type(result) or ("ERR " .. string.sub(tostring(result), 1, 160))))\n'
            'end\n'
            'local okC, Composer = pcall(require, folder.VfxComposer)\n'
            'local okG, gen = pcall(require, folder.VfxGenerated)\n'
            'if okC and okG and gen.ability then local fine, why = Composer.validate(gen.ability) table.insert(out, "ability=" .. tostring(fine) .. " " .. tostring(why)) end\n'
            f'return "{MARK}_CHECK {run} " .. table.concat(out, "; ")')


def remove_luau() -> str:
    return ('local n = 0\n'
            'for _, parent in { game:GetService("ReplicatedStorage"), game:GetService("ServerScriptService"), '
            'game:GetService("StarterPlayer"):WaitForChild("StarterPlayerScripts") } do\n'
            f'\tfor _, name in {{ "{LAB_FOLDER}", "{LAB_CLIENT}" }} do local old = parent:FindFirstChild(name) '
            'if old then old:Destroy() n += 1 end end\nend\n'
            f'return "{MARK}_REMOVED " .. n')


# --------------------------------------------------------------------------- spec

def make_spec(prompt: str, *, style_description: str = "", image: bytes | None = None, speed: float = 0.25,
              camera=None, clock=None, intensity: float | None = None, textures: dict | None = None) -> dict:
    """Everything a lab run needs, decided offline from the prompt (and optional reference image)."""
    style = choose_style(" ".join(x for x in (style_description, prompt) if x), image)
    ability = choose_ability(prompt)
    spec = {"prompt": prompt[:300], "style": style, "ability": ability, "speed": speed, "origin": list(STAGE_ORIGIN),
            "camera": camera or [20, 6, 20], "clock": clock, "intensity": intensity,
            "textures": textures_for(style["base"], textures)}
    return spec


def plan(prompt: str, **kwargs) -> dict:
    """Offline: the chosen style and ability, the generated Luau and STAR's lint findings. Applies nothing."""
    spec = make_spec(prompt, **kwargs)
    generated = generated_module(spec["style"], spec["ability"], intensity=spec.get("intensity"),
                                 textures=spec.get("textures"))
    sources = {**pack_sources(), "VfxGenerated": generated}
    findings = lint_sources(sources)
    return {"spec": spec, "generated_luau": generated, "lint": findings,
            "lint_errors": sum(1 for items in findings.values() for f in items if f["severity"] == "error"),
            "modules": sorted(sources),
            "length_seconds": round(style_length(spec["style"]["base"], spec["style"].get("timing")), 2)}


# --------------------------------------------------------------------------- frame evidence

def _images(result) -> list[tuple[bytes, str]]:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    found = []
    for part in (data.get("content", []) if isinstance(data, dict) else []):
        if isinstance(part, dict) and part.get("type") == "image" and part.get("data"):
            try:
                found.append((base64.b64decode(part["data"]), str(part.get("mimeType") or "image/png")))
            except ValueError:
                continue
    return found


def frame_stats(data: bytes, palette: dict | None = None) -> dict:
    """Brightness, colourfulness and palette-hue share of one frame (Pillow)."""
    from PIL import Image, ImageStat
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.thumbnail((240, 240))
    stat = ImageStat.Stat(image)
    mean = sum(stat.mean) / 3 / 255
    pixels = _pixels(image)
    hsv = [_rgb_to_hsv(p) for p in pixels]
    colourful = sum(1 for _, s, v in hsv if s > 0.45 and v > 0.45) / len(hsv)
    bright = sum(1 for _, _, v in hsv if v > 0.92) / len(hsv)
    match = None
    if palette:
        target = _rgb_to_hsv(palette["glow"])[0]
        near = sum(1 for h, s, v in hsv if s > 0.2 and v > 0.35 and min(abs(h - target), 1 - abs(h - target)) < 0.07)
        match = near / len(hsv)
    return {"mean": round(mean, 4), "colourful": round(colourful, 4), "bright": round(bright, 4),
            "palette_share": None if match is None else round(match, 4), "image": image}


def _diff(a, b) -> float:
    from PIL import ImageChops, ImageStat
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3 / 255


def stage_times(base: str, timing: dict | None = None) -> dict:
    """Stage start times of a built-in profile, or of its plan timing override (mirror of Styles.stageTimes)."""
    t = {**STYLES[base]["timing"], **(timing or {})}
    impact = t["charge"]
    shockwave = impact + t["impact"]
    linger = shockwave + t["shockwave"] * 0.5
    dissipate = linger + t["linger"]
    return {"charge": 0.0, "impact": impact, "shockwave": shockwave, "linger": linger, "dissipate": dissipate,
            "finish": dissipate + t["dissipate"]}


def critique(frames: list[dict], style: dict) -> dict:
    """A measured, advisory critique of a frame sequence against the qualities of good ability VFX.

    Uses each frame's estimated effect time; frames before the effect are the baseline. Checks impact readability
    (the impact window changes the picture far more than the charge), palette (the style's main hue in effect
    frames), motion (consecutive frames differ during the effect), duration (visible across many frames, not one
    blip) and dissipation (after the end the picture returns to the baseline). It cannot judge taste; it catches
    flat, missing, unreadable or never-ending effects."""
    if len(frames) < 3:
        return {"ok": False, "findings": ["fewer than 3 frames captured"], "scores": {}}
    palette = STYLES[style["base"]]["palette"] if not style.get("palette") else style["palette"]
    times = stage_times(style["base"], style.get("timing"))
    stats = [frame_stats(f["data"], palette) for f in frames]
    ts = [float(f.get("effect_t", -1)) for f in frames]
    pre = [i for i, t in enumerate(ts) if t < 0] or [0]
    base = stats[pre[-1]]["image"]
    during = [i for i, t in enumerate(ts) if 0 <= t <= times["finish"]]
    after = [i for i, t in enumerate(ts) if t > times["finish"] + 0.2]
    charge = [i for i in during if ts[i] < times["impact"] - 0.02]
    impact = [i for i in during if times["impact"] - 0.02 <= ts[i] <= times["shockwave"] + 0.25]
    change = {i: _diff(base, stats[i]["image"]) for i in during}
    if impact:
        peak_i = max(impact, key=lambda i: change[i])
    elif during:
        peak_i = max(during, key=lambda i: change[i])
    else:
        peak_i = 0
    charge_level = max((change[i] for i in charge), default=0.0)
    motion = [_diff(stats[a]["image"], stats[b]["image"]) for a, b in zip(during, during[1:])]
    share = [stats[i]["palette_share"] for i in during if stats[i]["palette_share"] is not None]
    scores = {
        "frames_during": len(during),
        "impact_frame": peak_i,
        "impact_change": round(change.get(peak_i, 0.0), 4),
        "charge_change": round(charge_level, 4),
        "impact_over_charge": round(change.get(peak_i, 0.0) / max(0.005, charge_level), 2),
        "palette_share": round(sum(share) / len(share), 3) if share else 0.0,
        "motion": round(sum(motion) / len(motion), 4) if motion else 0.0,
        "visible_frames": sum(1 for i in during if change[i] > 0.02),
        "tail_change": round(_diff(base, stats[after[-1]]["image"]), 4) if after else None,
    }
    findings = []
    if not during:
        findings.append("no frame fell inside the effect: capture timing, or the effect never played")
    if scores["impact_change"] < 0.06:
        findings.append("weak impact: the impact frames change the picture little; raise flash, light or impact size")
    if charge and scores["impact_over_charge"] < 1.5:
        findings.append("impact does not stand out from the charge-up: keep the charge quieter or the hit louder")
    if charge and scores["charge_change"] < 0.01:
        findings.append("charge-up barely visible: anticipation reads poorly; add aura, inward motes or a ground glow")
    if share and scores["palette_share"] < 0.03:
        findings.append("the style's main colour is barely visible in effect frames")
    if motion and scores["motion"] < 0.01:
        findings.append("little motion between frames: the effect may be static or small on screen")
    if during and scores["visible_frames"] < max(3, len(during) // 3):
        findings.append("effect visible in few frames: layers end too early or are too small")
    if scores["tail_change"] is not None and scores["tail_change"] > 0.05:
        findings.append("the picture does not return to normal after the effect: check dissipation, cleanup, tint reset")
    for item in stats:
        item.pop("image", None)
    return {"ok": not findings, "findings": findings, "scores": scores, "frames": stats}


def contact_sheet(frames: list[dict], target: Path, *, columns: int = 4, width: int = 480, title: str = "") -> dict:
    """A labelled grid of frames (Pillow). Labels are the frame index and estimated effect time."""
    from PIL import Image, ImageDraw
    picked = frames
    if len(frames) > 16:
        step = (len(frames) - 1) / 15
        picked = [frames[round(i * step)] for i in range(16)]
    tiles = []
    for f in picked:
        image = Image.open(io.BytesIO(f["data"])).convert("RGB")
        h = round(image.height * width / image.width)
        tile = image.resize((width, h))
        draw = ImageDraw.Draw(tile)
        text = f"#{f['index']}  t~{f.get('effect_t', 0):.2f}s"
        draw.rectangle((0, h - 20, 9 * len(text) + 8, h), fill=(0, 0, 0))
        draw.text((4, h - 17), text, fill=(255, 255, 255))
        tiles.append(tile)
    rows = math.ceil(len(tiles) / columns)
    th = tiles[0].height
    header = 26 if title else 0
    sheet = Image.new("RGB", (columns * width, rows * th + header), (12, 12, 16))
    if title:
        ImageDraw.Draw(sheet).text((8, 6), title[:150], fill=(230, 230, 230))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % columns) * width, header + (i // columns) * th))
    sheet.save(target, quality=88)
    return {"file": target.name, "frames": [f["index"] for f in picked]}


# --------------------------------------------------------------------------- the Studio lab

def _text(result) -> str:
    from .studio_loop import result_text
    return result_text(result)


def _failed(result) -> bool:
    from .studio_loop import result_failed
    return result_failed(result)


class VfxLab:
    """Apply -> check -> playtest -> capture -> critique on an already opened GuardedStudio."""

    def __init__(self, guarded, out: Path, *, log=print, sleep=asyncio.sleep, clock=time.monotonic):
        self.guarded, self.out, self.log, self.sleep, self.clock = guarded, Path(out), log, sleep, clock

    async def _luau(self, code: str) -> tuple[bool, str]:
        from .studio_loop import EDIT_MARK, _marked_json
        result = await self.guarded.call_tool("execute_luau", {"studio_id": self.guarded.studio_id,
                                                               "datamodel_type": "Edit", "code": code})
        receipt = _marked_json(_text(result), EDIT_MARK) or {}
        got = receipt.get("result")
        answer = got if isinstance(got, str) else _text(result)
        return (not _failed(result) and receipt.get("ok") is True), answer

    async def _call(self, name: str, **arguments):
        return await self.guarded.call_tool(name, {"studio_id": self.guarded.studio_id, **arguments})

    async def remove(self) -> dict:
        ok, text = await self._luau(remove_luau())
        return {"ok": ok, "detail": text[:200]}

    async def run(self, spec: dict, *, run: str | None = None, label: str = "") -> dict:
        run = run or secrets.token_hex(4)
        self.out.mkdir(parents=True, exist_ok=True)
        report = {"run": run, "label": label, "prompt": spec.get("prompt"), "style": spec["style"],
                  "ability": {k: v for k, v in spec["ability"].items() if k != "cues"}, "speed": spec.get("speed"),
                  "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        generated = generated_module(spec["style"], spec["ability"], intensity=spec.get("intensity"),
                                     textures=spec.get("textures"))
        (self.out / "VfxGenerated.luau").write_text(generated, encoding="utf-8")
        report["lint"] = lint_sources({**pack_sources(), "VfxGenerated": generated})
        ok, text = await self._luau(apply_luau(spec, run))
        report["apply"] = {"ok": ok and f"{MARK}_APPLY {run}" in text, "detail": text[:200]}
        if not report["apply"]["ok"]:
            return self._finish(report)
        ok, text = await self._luau(check_luau(run))
        report["check"] = {"ok": ok and "ERR" not in text and "ability=false" not in text, "detail": text[:600]}
        self.log(f"check: {report['check']}")
        if not report["check"]["ok"]:
            return self._finish(report)
        report["playtest"] = await self._playtest(spec, run)
        frames = report["playtest"].pop("_frames", [])
        if frames:
            sheet = contact_sheet(frames, self.out / "sheet.jpg",
                                  title=f"{label or spec['style'].get('name')} | {spec['ability']['name']} | speed "
                                        f"{spec.get('speed')} | run {run}")
            report["sheet"] = sheet
            report["critique"] = critique(frames, spec["style"])
        return self._finish(report)

    def _finish(self, report: dict) -> dict:
        report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["changes"] = self.guarded.journal.report() if hasattr(self.guarded.journal, "report") else {}
        (self.out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        return report

    async def _console(self) -> str:
        return _text(await self._call("get_console_output"))

    async def _playtest(self, spec: dict, run: str) -> dict:
        speed = float(_clamp(spec.get("speed", 0.25), 0.05, 1))
        length = float(spec.get("length") or style_length(spec["style"]["base"], spec["style"].get("timing")))
        wall = length / speed
        started = await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id, "is_start": True})
        if _failed(started):
            return {"ok": False, "started": False, "detail": _text(started)[:300]}
        frames: list[dict] = []
        console = ""
        play_at = None
        info: dict[str, Any] = {"ok": False, "started": True}
        try:
            deadline = self.clock() + 40
            while self.clock() < deadline and f"{MARK} client-ready {run}" not in console:
                await self.sleep(0.5)
                console = await self._console()
            info["client_ready"] = f"{MARK} client-ready {run}" in console
            if not info["client_ready"]:
                info["detail"] = "the lab client did not start"
                return info
            stop_at = self.clock() + float(spec.get("lead", 5)) + wall + 6
            index = 0
            while self.clock() < stop_at and len(frames) < MAX_FRAMES:
                before = self.clock()
                shot = await self._call("screen_capture", capture_id=f"StarVfx_{run}_{index}")
                images = _images(shot)
                console = await self._console()
                if play_at is None and f"{MARK} client-play {run}" in console:
                    play_at = (before + self.clock()) / 2 if not frames else before
                if images:
                    data, mime = images[0]
                    t = self.clock()
                    frames.append({"index": index, "data": data, "mime": mime, "wall": t,
                                   "effect_t": ((t - play_at) * speed) if play_at else -1.0})
                    index += 1
                if play_at and self.clock() > play_at + wall + 2.5:
                    break
            info["errors"] = [line for line in console.splitlines()
                              if ("[StarVfx]" in line and "failed" in line) or "Script 'ReplicatedStorage.StarVfxLab" in line
                              or ("StarVfxLab" in line and "rror" in line)][:20]
        finally:
            stopped = await self.guarded.call_tool("start_stop_play", {"studio_id": self.guarded.studio_id,
                                                                       "is_start": False})
            info["stopped"] = not _failed(stopped)
        at = console.find(f"{MARK} client-ready {run}")
        (self.out / "playtest-output.txt").write_text(console[max(0, at - 2000):] if at >= 0 else console[-6000:],
                                                      encoding="utf-8")
        for f in frames:
            if f["effect_t"] < 0 and play_at:
                f["effect_t"] = (f["wall"] - play_at) * speed
            name = f"frame-{f['index']:02d}.{'jpg' if 'jpeg' in f['mime'] else 'png'}"
            (self.out / name).write_bytes(f["data"])
            f["file"] = name
            f["sha256"] = hashlib.sha256(f["data"]).hexdigest()
        info.update({"ok": bool(frames) and play_at is not None, "frames": len(frames), "played": play_at is not None,
                     "frame_files": [{"file": f["file"], "effect_t": round(f["effect_t"], 3), "sha256": f["sha256"]}
                                     for f in frames], "_frames": frames})
        return info


async def run_vfx_lab(home, specs: list[dict], out: Path, *, connector=None, log=print, keep: bool = False) -> dict:
    """Connect to the Studio target (STAR Test Place only), run each spec, remove the lab afterwards."""
    from . import studio, studio_remote
    results = []
    async with (connector or studio_remote.connect)(home) as session:
        discovered = await studio.list_tools(session)
        guarded, facts = await studio_remote.open_server(session, discovered, home=home, opted_in=True)
        if guarded is None:
            return {"ok": False, "problem": facts.get("problem")}
        if not (guarded.verdict.editable and facts.get("is_test_place")):
            return {"ok": False, "problem": "the open place is not STAR Test Place or edits are not allowed"}
        lab = VfxLab(guarded, out, log=log)
        for index, spec in enumerate(specs):
            lab.out = Path(out) / (spec.get("label") or f"run-{index + 1}")
            results.append(await lab.run(spec, label=spec.get("label", "")))
        if not keep:
            results.append({"removed": await lab.remove()})
    return {"ok": True, "results": results}


def run_vfx_lab_sync(home, specs: list[dict], out: Path, *, timeout: float = 600.0, **kwargs) -> dict:
    """run_vfx_lab in its own thread and event loop, for a synchronous caller (a STAR tool)."""
    box: dict = {}

    def target():
        try:
            box["report"] = asyncio.run(run_vfx_lab(home, specs, out, log=lambda *_: None, **kwargs))
        except Exception as error:
            box["report"] = {"ok": False, "problem": f"VFX lab run failed ({type(error).__name__})"}

    thread = threading.Thread(target=target, name="star-vfx-lab", daemon=True)
    thread.start()
    thread.join(timeout)
    return box.get("report") or {"ok": False, "problem": "the VFX lab run did not finish in time"}


def public_summary(report: dict) -> dict:
    """What a STAR tool returns: no frame bytes, only paths, scores and findings."""
    out = {"ok": report.get("ok"), "problem": report.get("problem"), "runs": []}
    for item in report.get("results", []):
        if "run" not in item:
            continue
        out["runs"].append({
            "label": item.get("label"), "style": item.get("style", {}).get("name"), "ability": item.get("ability"),
            "apply_ok": item.get("apply", {}).get("ok"), "check_ok": item.get("check", {}).get("ok"),
            "frames": item.get("playtest", {}).get("frames"), "sheet": item.get("sheet", {}).get("file"),
            "critique": {k: item.get("critique", {}).get(k) for k in ("ok", "findings", "scores")},
            "errors": item.get("playtest", {}).get("errors")})
    return out


# --------------------------------------------------------------------------- CLI

def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.roblox_vfx_studio", description=(__doc__ or "").split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("prompt")
        p.add_argument("--style", default="", help="style description, e.g. 'soft cartoon pastel'")
        p.add_argument("--image", help="reference image file (palette analysis only)")
        p.add_argument("--speed", type=float, default=0.25, help="playback speed for capture (1 = real time)")
        p.add_argument("--clock", type=float, help="Lighting.ClockTime during the playtest (client only)")
        p.add_argument("--intensity", type=float)
        p.add_argument("--label", default="")
        p.add_argument("--textures", help="JSON file {slot: rbxassetid://...} with the project's own textures")
        if name == "run":
            p.add_argument("--home", required=True)
            p.add_argument("--out", required=True)
            p.add_argument("--keep", action="store_true", help="leave the lab installed (unsaved) after the run")
    r = sub.add_parser("remove")
    r.add_argument("--home", required=True)
    args = parser.parse_args(arguments)
    if args.command == "remove":
        async def go():
            from . import studio, studio_remote
            async with studio_remote.connect(Path(args.home)) as session:
                discovered = await studio.list_tools(session)
                guarded, facts = await studio_remote.open_server(session, discovered, home=Path(args.home))
                if guarded is None or not facts.get("is_test_place"):
                    return {"ok": False, "problem": "not STAR Test Place"}
                return await VfxLab(guarded, Path(".")).remove()
        print(json.dumps(asyncio.run(go())))
        return 0
    image = Path(args.image).read_bytes() if args.image else None
    textures = json.loads(Path(args.textures).read_text(encoding="utf-8")) if args.textures else None
    kwargs = dict(style_description=args.style, image=image, speed=args.speed, clock=args.clock,
                  intensity=args.intensity, textures=textures)
    if args.command == "plan":
        result = plan(args.prompt, **kwargs)
        print(json.dumps({k: v for k, v in result.items() if k != "generated_luau"}, indent=1))
        print(result["generated_luau"])
        return 0
    spec = make_spec(args.prompt, **kwargs)
    spec["label"] = args.label
    report = asyncio.run(run_vfx_lab(Path(args.home), [spec], Path(args.out), keep=args.keep))
    print(json.dumps(public_summary(report), indent=1, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
