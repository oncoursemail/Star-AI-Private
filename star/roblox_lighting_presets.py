"""Cinematic Roblox lighting/post presets compiled to Luau. Standard library only; Pillow only for render checks.

Flow: plan_prompt(brief) -> local model picks a preset + a few -1..1 knobs as JSON -> parse_plan -> apply_plan
(clamped, deterministic) -> lighting_luau(resolved) -> render -> analyze_render + suggest_fix (one fix at most)
-> lighting_luau(resolved, overrides). restore_luau() puts the previous Lighting back. The model never writes
Lighting code. Practical lights go on parts that carry the attribute StarPractical = <role> (see ROLES).
"""
from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

ROLES = ("pendant", "sconce", "lamp", "window", "neon", "street", "lantern")
BACKUP_NAME = "StarLightingBackup"
_LIGHTING_PROPS = ("Ambient", "OutdoorAmbient", "Brightness", "ClockTime", "GeographicLatitude",
                   "EnvironmentDiffuseScale", "EnvironmentSpecularScale", "ExposureCompensation", "ShadowSoftness",
                   "GlobalShadows", "ColorShift_Top", "ColorShift_Bottom")
# Allowed properties and their clamps. "color" = [r, g, b] 0..255, "bool" = bool.
_RANGES: dict[str, dict[str, Any]] = {
    "lighting": {"Ambient": "color", "OutdoorAmbient": "color", "ColorShift_Top": "color", "ColorShift_Bottom": "color",
                 "Brightness": (0, 10), "ClockTime": (0, 24), "GeographicLatitude": (-90, 90),
                 "EnvironmentDiffuseScale": (0, 1), "EnvironmentSpecularScale": (0, 1),
                 "ExposureCompensation": (-3, 3), "ShadowSoftness": (0, 1), "GlobalShadows": "bool"},
    "atmosphere": {"Density": (0, 0.7), "Offset": (0, 1), "Glare": (0, 10), "Haze": (0, 10),
                   "Color": "color", "Decay": "color"},
    "sky": {"CelestialBodiesShown": "bool", "StarCount": (0, 5000), "SunAngularSize": (0, 60),
            "MoonAngularSize": (0, 60)},
    "Bloom": {"Intensity": (0, 1), "Size": (0, 56), "Threshold": (0, 4)},
    "ColorCorrection": {"Brightness": (-0.5, 0.5), "Contrast": (-1, 1), "Saturation": (-1, 1), "TintColor": "color"},
    "DepthOfField": {"FarIntensity": (0, 1), "NearIntensity": (0, 1), "FocusDistance": (0, 200),
                     "InFocusRadius": (0, 50)},
    "SunRays": {"Intensity": (0, 1), "Spread": (0, 1)},
    "practical": {"brightness": (0, 10), "range": (0, 60), "angle": (0, 180), "kelvin": (1000, 12000)},
}
_POST_CLASS = {"Bloom": "BloomEffect", "ColorCorrection": "ColorCorrectionEffect",
               "DepthOfField": "DepthOfFieldEffect", "SunRays": "SunRaysEffect"}
_LIGHT_CLASSES = ("PointLight", "SpotLight", "SurfaceLight")
_FACES = ("Top", "Bottom", "Front", "Back", "Left", "Right")


# Roblox has no camera white balance: a raw 2700 K blackbody colour renders burnt orange. Practical colours are
# balanced against a 3800 K reference (a tungsten-leaning camera), so 2700 K reads warm and 9000 K reads cool.
WHITE_BALANCE_K = 3800


def kelvin_to_rgb(kelvin: float, white: float | None = None) -> list[int]:
    """Blackbody colour temperature to sRGB 0..255 (Tanner Helland fit, good to ~1% for 1000-40000 K).
    With white=K the colour is white-balanced to that reference (channel ratio, brightest channel 255)."""
    if white:
        c, w = kelvin_to_rgb(kelvin), kelvin_to_rgb(white)
        ratio = [a / max(b, 1) for a, b in zip(c, w)]
        top = max(ratio)
        return [int(round(min(255.0, 255.0 * r / top))) for r in ratio]
    t = min(max(float(kelvin), 1000.0), 40000.0) / 100.0
    if t <= 66:
        r, g = 255.0, 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r, g = 329.698727446 * (t - 60) ** -0.1332047592, 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    return [int(round(min(max(c, 0.0), 255.0))) for c in (r, g, b)]


def _off(why: str) -> dict:
    return {"enabled": False, "why": why}


# --------------------------------------------------------------------------- presets
# Each value choice that matters carries a rationale in "why" (dotted path -> reason) or in the practical's "why".
PRESETS: dict[str, dict[str, Any]] = {
    "warm_luxury_interior": {
        "description": "Warm luxury interior at night: low ambient, many warm practicals, deep shadows, warm grade.",
        "scene": "interior", "lighting_style": "Realistic", "technology": "Future", "clock_range": [19, 23.5],
        "lighting": {"Ambient": [80, 68, 58], "OutdoorAmbient": [38, 44, 60], "Brightness": 0.4, "ClockTime": 21,
                     "GeographicLatitude": 40, "EnvironmentDiffuseScale": 0.35, "EnvironmentSpecularScale": 0.7,
                     "ExposureCompensation": 0.5, "ShadowSoftness": 0.25, "GlobalShadows": True,
                     "ColorShift_Top": [0, 0, 0], "ColorShift_Bottom": [20, 12, 6]},
        "atmosphere": {"Density": 0.28, "Offset": 0.1, "Color": [70, 56, 46], "Decay": [40, 36, 44], "Glare": 0,
                       "Haze": 0.6},
        "sky": {"CelestialBodiesShown": True, "StarCount": 1500, "SunAngularSize": 12, "MoonAngularSize": 10},
        "post": {"Bloom": {"Intensity": 0.55, "Size": 26, "Threshold": 1.0},
                 "ColorCorrection": {"Brightness": 0.02, "Contrast": 0.16, "Saturation": 0.06,
                                     "TintColor": [255, 242, 226]},
                 "DepthOfField": {"FarIntensity": 0.12, "NearIntensity": 0, "FocusDistance": 24, "InFocusRadius": 30},
                 "SunRays": None},
        "practicals": {
            "pendant": {"class": "PointLight", "kelvin": 2700, "brightness": 2.2, "range": 24, "shadows": True,
                        "why": "2700K incandescent warmth; shadows on so each pendant carves its own pool"},
            "sconce": {"class": "SpotLight", "kelvin": 2400, "brightness": 1.8, "range": 14, "shadows": False,
                       "face": "Top", "angle": 110, "why": "upward wall-wash scallops; 2400K reads older/richer; no "
                                                           "shadows to stay under the shadow-light budget"},
            "lamp": {"class": "PointLight", "kelvin": 2600, "brightness": 2.0, "range": 18, "shadows": True,
                     "why": "table/floor lamps lift the seating zone, keep a falloff into dark corners"},
            "window": {"class": "SurfaceLight", "kelvin": 7500, "brightness": 0.35, "range": 14, "shadows": False,
                       "face": "Front", "angle": 70, "why": "faint cool night spill gives warm/cool separation"},
            "neon": {"class": "PointLight", "color": [255, 170, 90], "brightness": 0.8, "range": 8, "shadows": False,
                     "why": "signage dimmed to amber so it does not fight the warm palette"},
            "street": {"class": "PointLight", "kelvin": 2700, "brightness": 1.5, "range": 18, "shadows": False,
                       "why": "exterior lamps match interior warmth"},
            "lantern": {"class": "PointLight", "kelvin": 2200, "brightness": 1.2, "range": 12, "shadows": False,
                        "why": "flame-coloured accents"},
        },
        "targets": {"mean_luma": [45, 90], "crushed_max": 25, "clipped_max": 3, "contrast": [110, 215],
                    "warmth": [0.08, 0.35], "saturation": [0.3, 0.8]},
        "why": {"lighting.Ambient": "low warm fill: shadows stay deep but never pure black",
                "lighting.Brightness": "night: moon only, the practicals carry the frame",
                "lighting.ClockTime": "evening so the window reads dark blue",
                "lighting.ExposureCompensation": "+0.5 stop lifts practical pools to a readable mid level",
                "lighting.EnvironmentDiffuseScale": "low so the night sky does not tint walls blue",
                "atmosphere.Density": "light density only adds depth through the window",
                "post.ColorCorrection": "warm tint + mild contrast = the gold luxury grade",
                "post.Bloom": "threshold 1.0 blooms only bulbs and hot spots"},
        "key_role": "pendant",
    },
    "moody_night_diner": {
        "description": "Near-black diner at night; warm pendant practicals are the focal points; warm-neutral grade.",
        "scene": "interior", "lighting_style": "Realistic", "technology": "Future", "clock_range": [0, 4],
        "lighting": {"Ambient": [46, 46, 52], "OutdoorAmbient": [40, 46, 58], "Brightness": 0.3, "ClockTime": 2,
                     "GeographicLatitude": 40, "EnvironmentDiffuseScale": 0.2, "EnvironmentSpecularScale": 0.8,
                     "ExposureCompensation": 0.6, "ShadowSoftness": 0.18, "GlobalShadows": True,
                     "ColorShift_Top": [0, 0, 0], "ColorShift_Bottom": [0, 0, 0]},
        "atmosphere": {"Density": 0.34, "Offset": 0.05, "Color": [44, 52, 62], "Decay": [26, 30, 40], "Glare": 0,
                       "Haze": 1.2},
        "sky": {"CelestialBodiesShown": False, "StarCount": 0, "SunAngularSize": 12, "MoonAngularSize": 10},
        "post": {"Bloom": {"Intensity": 0.65, "Size": 28, "Threshold": 0.95},
                 "ColorCorrection": {"Brightness": 0.0, "Contrast": 0.24, "Saturation": -0.08,
                                     "TintColor": [255, 243, 230]},
                 "DepthOfField": {"FarIntensity": 0.18, "NearIntensity": 0, "FocusDistance": 18, "InFocusRadius": 22},
                 "SunRays": None},
        "practicals": {
            "pendant": {"class": "PointLight", "kelvin": 2400, "brightness": 3.0, "range": 17, "shadows": True,
                        "why": "hot, small warm pools are the focal points; short range keeps the room black"},
            "sconce": {"class": "PointLight", "kelvin": 2700, "brightness": 0.9, "range": 9, "shadows": False,
                       "why": "barely-on wall glow just separates walls from the void"},
            "lamp": {"class": "SpotLight", "kelvin": 2700, "brightness": 1.4, "range": 10, "shadows": True,
                     "face": "Bottom", "angle": 70, "why": "task light pooled on the counter"},
            "window": {"class": "SurfaceLight", "kelvin": 9500, "brightness": 0.7, "range": 16, "shadows": False,
                       "face": "Front", "angle": 75, "why": "cold city/rain glow through the window = cool rim"},
            "neon": {"class": "PointLight", "color": [255, 60, 50], "brightness": 1.8, "range": 10, "shadows": False,
                     "why": "red sign as the single saturated accent"},
            "street": {"class": "PointLight", "kelvin": 3200, "brightness": 1.2, "range": 16, "shadows": False,
                       "why": "sodium-ish exterior spill"},
            "lantern": {"class": "PointLight", "kelvin": 2200, "brightness": 0.8, "range": 9, "shadows": False,
                        "why": "dim warm accent"},
        },
        "targets": {"mean_luma": [24, 60], "crushed_max": 55, "clipped_max": 3, "contrast": [90, 220],
                    "warmth": [0.0, 0.3], "saturation": [0.2, 0.85]},
        "why": {"lighting.Ambient": "dark neutral fill (46): Future ambient is weak, shapes must still read",
                "lighting.Brightness": "2am: almost no moonlight",
                "lighting.ClockTime": "2am per the reference",
                "lighting.ExposureCompensation": "+0.6 so the practical pools read, the rest stays dark",
                "lighting.EnvironmentDiffuseScale": "low: no sky fill indoors",
                "atmosphere.Density": "medium so the window view fogs like rain",
                "post.ColorCorrection": "strong contrast, slight desaturation, warm-neutral tint",
                "post.Bloom": "low threshold so bulbs glow like the reference"},
        "key_role": "pendant",
    },
    "bright_stylized_day": {
        "description": "Bright stylized daytime map: high ambient, soft shadows, saturated sky, pale haze.",
        "scene": "exterior", "lighting_style": "Soft", "technology": "ShadowMap", "clock_range": [9, 16],
        "lighting": {"Ambient": [120, 122, 135], "OutdoorAmbient": [150, 150, 165], "Brightness": 3.0,
                     "ClockTime": 13.5, "GeographicLatitude": 25, "EnvironmentDiffuseScale": 0.8,
                     "EnvironmentSpecularScale": 0.4, "ExposureCompensation": 0.0, "ShadowSoftness": 0.45,
                     "GlobalShadows": True, "ColorShift_Top": [255, 248, 235], "ColorShift_Bottom": [0, 0, 0]},
        "atmosphere": {"Density": 0.3, "Offset": 0.25, "Color": [205, 220, 235], "Decay": [120, 160, 205],
                       "Glare": 0.2, "Haze": 1.0},
        "sky": {"CelestialBodiesShown": True, "StarCount": 0, "SunAngularSize": 18, "MoonAngularSize": 10},
        "post": {"Bloom": {"Intensity": 0.35, "Size": 24, "Threshold": 1.6},
                 "ColorCorrection": {"Brightness": 0.0, "Contrast": 0.06, "Saturation": 0.18,
                                     "TintColor": [255, 252, 246]},
                 "DepthOfField": None,
                 "SunRays": {"Intensity": 0.05, "Spread": 0.7}},
        "practicals": {r: _off("daylight carries the scene; lamps off") for r in ROLES},
        "targets": {"mean_luma": [125, 185], "crushed_max": 2, "clipped_max": 4, "contrast": [90, 200],
                    "warmth": [-0.3, 0.1], "saturation": [0.3, 0.7]},
        "why": {"lighting.Ambient": "high fill: stylized maps keep shadow sides readable",
                "lighting.Brightness": "3 = strong sun without washing out (>3.5 bleaches)",
                "lighting.ClockTime": "early afternoon: short shadows, blue sky",
                "lighting.ExposureCompensation": "0: the sun alone already lands mid-high",
                "lighting.EnvironmentDiffuseScale": "sky bounce adds blue fill on top faces",
                "atmosphere.Density": "pale haze separates distance layers like the reference",
                "post.ColorCorrection": "+saturation for toy-like colour, tiny contrast",
                "post.Bloom": "high threshold: only highlights glow, no milky veil"},
        "key_role": None,
    },
    "golden_hour_exterior": {
        "description": "Golden hour exterior: low warm sun, long shadows, warm haze, sun rays.",
        "scene": "exterior", "lighting_style": "Realistic", "technology": "Future", "clock_range": [16.5, 18.2],
        "lighting": {"Ambient": [90, 70, 62], "OutdoorAmbient": [150, 112, 92], "Brightness": 3.0,
                     "ClockTime": 17.7, "GeographicLatitude": 35, "EnvironmentDiffuseScale": 0.7,
                     "EnvironmentSpecularScale": 0.6, "ExposureCompensation": 0.4, "ShadowSoftness": 0.3,
                     "GlobalShadows": True, "ColorShift_Top": [255, 165, 90], "ColorShift_Bottom": [50, 24, 12]},
        "atmosphere": {"Density": 0.36, "Offset": 0.2, "Color": [255, 196, 150], "Decay": [190, 110, 80],
                       "Glare": 1.4, "Haze": 1.8},
        "sky": {"CelestialBodiesShown": True, "StarCount": 0, "SunAngularSize": 24, "MoonAngularSize": 10},
        "post": {"Bloom": {"Intensity": 0.5, "Size": 28, "Threshold": 1.2},
                 "ColorCorrection": {"Brightness": 0.0, "Contrast": 0.14, "Saturation": 0.12,
                                     "TintColor": [255, 230, 200]},
                 "DepthOfField": {"FarIntensity": 0.08, "NearIntensity": 0, "FocusDistance": 60, "InFocusRadius": 50},
                 "SunRays": {"Intensity": 0.2, "Spread": 0.8}},
        "practicals": {
            "pendant": _off("not used outdoors"), "sconce": _off("not used outdoors"),
            "lamp": _off("not used outdoors"),
            "window": {"class": "SurfaceLight", "kelvin": 2700, "brightness": 0.8, "range": 10, "shadows": False,
                       "face": "Front", "angle": 80, "why": "windows just switching on: warm life in the buildings"},
            "neon": {"class": "PointLight", "color": [255, 140, 70], "brightness": 0.6, "range": 8, "shadows": False,
                     "why": "signs barely visible against the sun"},
            "street": {"class": "PointLight", "kelvin": 2400, "brightness": 0.8, "range": 14, "shadows": False,
                       "why": "lamps warming up before dusk; low so the sun stays the key"},
            "lantern": {"class": "PointLight", "kelvin": 2000, "brightness": 1.0, "range": 10, "shadows": False,
                        "why": "torch/lantern flicker colour as warm accents"},
        },
        "targets": {"mean_luma": [90, 160], "crushed_max": 8, "clipped_max": 5, "contrast": [110, 220],
                    "warmth": [-0.05, 0.4], "saturation": [0.3, 0.8]},
        "why": {"lighting.Ambient": "warm, mid fill: shadows lean violet-brown, not blue",
                "lighting.Brightness": "3.0: low sun still bright enough for long crisp shadows",
                "lighting.ClockTime": "17.7 = sun low but above the horizon",
                "lighting.ExposureCompensation": "+0.4 keeps faces turned away from the low sun readable",
                "lighting.EnvironmentDiffuseScale": "orange sky bounce helps the warm wash",
                "atmosphere.Density": "warm haze + glare gives the sunset bloom around the sun",
                "post.ColorCorrection": "warm tint, + contrast and saturation",
                "post.Bloom": "moderate: sun-lit edges glow"},
        "key_role": None,
    },
    "overcast_horror": {
        "description": "Horror: foggy overcast night, desaturated cold grade, a few warm lanterns as the only safety.",
        "scene": "exterior", "lighting_style": "Realistic", "technology": "Future", "clock_range": [20, 24],
        "lighting": {"Ambient": [38, 42, 48], "OutdoorAmbient": [84, 94, 104], "Brightness": 0.7, "ClockTime": 23,
                     "GeographicLatitude": 50, "EnvironmentDiffuseScale": 0.3, "EnvironmentSpecularScale": 0.3,
                     "ExposureCompensation": 0.5, "ShadowSoftness": 0.15, "GlobalShadows": True,
                     "ColorShift_Top": [0, 0, 0], "ColorShift_Bottom": [0, 0, 0]},
        "atmosphere": {"Density": 0.56, "Offset": 0.0, "Color": [120, 128, 134], "Decay": [60, 66, 72], "Glare": 0,
                       "Haze": 4.0},
        "sky": {"CelestialBodiesShown": False, "StarCount": 0, "SunAngularSize": 12, "MoonAngularSize": 10},
        "post": {"Bloom": {"Intensity": 0.4, "Size": 30, "Threshold": 1.0},
                 "ColorCorrection": {"Brightness": 0.0, "Contrast": 0.16, "Saturation": -0.38,
                                     "TintColor": [226, 236, 240]},
                 "DepthOfField": None, "SunRays": None},
        "practicals": {
            "pendant": {"class": "PointLight", "kelvin": 2200, "brightness": 1.0, "range": 10, "shadows": True,
                        "why": "weak warm bulbs: a safe island in the dark"},
            "sconce": {"class": "PointLight", "kelvin": 2200, "brightness": 0.5, "range": 7, "shadows": False,
                       "why": "dying light"},
            "lamp": {"class": "PointLight", "kelvin": 2200, "brightness": 0.8, "range": 9, "shadows": True,
                     "why": "dying light"},
            "window": {"class": "SurfaceLight", "kelvin": 2400, "brightness": 0.6, "range": 10, "shadows": False,
                       "face": "Front", "angle": 70, "why": "one lit window = someone is there"},
            "neon": {"class": "PointLight", "color": [120, 255, 160], "brightness": 0.6, "range": 8,
                     "shadows": False, "why": "sickly green accent"},
            "street": {"class": "PointLight", "kelvin": 2000, "brightness": 1.6, "range": 16, "shadows": True,
                       "why": "isolated sodium pools; shadows on for sharp silhouettes in the fog"},
            "lantern": {"class": "PointLight", "kelvin": 1900, "brightness": 1.8, "range": 15, "shadows": True,
                        "why": "flame lanterns: warm contrast against the cold fog"},
        },
        "targets": {"mean_luma": [35, 85], "crushed_max": 25, "clipped_max": 3, "contrast": [60, 190],
                    "warmth": [-0.15, 0.12], "saturation": [0.05, 0.6]},
        "why": {"lighting.Ambient": "dim cold fill so silhouettes still read in the fog",
                "lighting.Brightness": "faint moon through cloud",
                "lighting.ClockTime": "late night",
                "lighting.ExposureCompensation": "+0.5: dark but not unreadable",
                "lighting.EnvironmentDiffuseScale": "low: overcast sky gives little fill",
                "atmosphere.Density": "0.56 with offset 0 and haze 4: a grey fog wall hides the distance",
                "post.ColorCorrection": "strong desaturation + cold tint = dread",
                "post.Bloom": "lanterns halo in the fog"},
        "key_role": "lantern",
    },
    "moonlit_night_exterior": {
        "description": "Clear moonlit night exterior: cool blue moonlight, stars, warm practicals for contrast.",
        "scene": "exterior", "lighting_style": "Realistic", "technology": "Future", "clock_range": [21, 24],
        "lighting": {"Ambient": [40, 46, 66], "OutdoorAmbient": [92, 106, 146], "Brightness": 1.0, "ClockTime": 0,
                     "GeographicLatitude": 30, "EnvironmentDiffuseScale": 0.5, "EnvironmentSpecularScale": 0.6,
                     "ExposureCompensation": 0.5, "ShadowSoftness": 0.2, "GlobalShadows": True,
                     "ColorShift_Top": [150, 170, 220], "ColorShift_Bottom": [0, 0, 0]},
        "atmosphere": {"Density": 0.3, "Offset": 0.1, "Color": [80, 96, 132], "Decay": [40, 50, 84], "Glare": 0,
                       "Haze": 1.0},
        "sky": {"CelestialBodiesShown": True, "StarCount": 3000, "SunAngularSize": 12, "MoonAngularSize": 16},
        "post": {"Bloom": {"Intensity": 0.5, "Size": 28, "Threshold": 1.0},
                 "ColorCorrection": {"Brightness": 0.0, "Contrast": 0.12, "Saturation": -0.12,
                                     "TintColor": [218, 228, 255]},
                 "DepthOfField": None, "SunRays": None},
        "practicals": {
            "pendant": {"class": "PointLight", "kelvin": 2400, "brightness": 1.4, "range": 12, "shadows": True,
                        "why": "warm against cool moonlight"},
            "sconce": {"class": "PointLight", "kelvin": 2400, "brightness": 0.8, "range": 8, "shadows": False,
                       "why": "small warm accents"},
            "lamp": {"class": "PointLight", "kelvin": 2400, "brightness": 1.0, "range": 10, "shadows": False,
                     "why": "small warm accents"},
            "window": {"class": "SurfaceLight", "kelvin": 2700, "brightness": 1.0, "range": 12, "shadows": False,
                       "face": "Front", "angle": 80, "why": "warm windows: the classic warm/cool night contrast"},
            "neon": {"class": "PointLight", "color": [120, 180, 255], "brightness": 0.8, "range": 8,
                     "shadows": False, "why": "cool sign blends with the moonlit palette"},
            "street": {"class": "PointLight", "kelvin": 2700, "brightness": 1.8, "range": 18, "shadows": True,
                       "why": "lamp pools are the key lights at ground level"},
            "lantern": {"class": "PointLight", "kelvin": 2100, "brightness": 1.4, "range": 12, "shadows": False,
                        "why": "flame accents"},
        },
        "targets": {"mean_luma": [35, 90], "crushed_max": 25, "clipped_max": 3, "contrast": [70, 200],
                    "warmth": [-0.3, 0.05], "saturation": [0.3, 0.92]},
        "why": {"lighting.Ambient": "cool blue fill: night reads blue, not grey",
                "lighting.Brightness": "1.0: the moon casts real shadows",
                "lighting.ClockTime": "midnight, moon high",
                "lighting.ExposureCompensation": "+0.5 so the night is legible",
                "lighting.EnvironmentDiffuseScale": "some sky fill keeps tops blue",
                "atmosphere.Density": "thin blue haze for depth",
                "post.ColorCorrection": "cool tint, slight desaturation",
                "post.Bloom": "lamps glow"},
        "key_role": "street",
    },
    "neon_cyber_night": {
        "description": "Cyberpunk night: dark purple base, saturated magenta/cyan neon, dense haze, strong bloom.",
        "scene": "exterior", "lighting_style": "Realistic", "technology": "Future", "clock_range": [21, 24],
        "lighting": {"Ambient": [50, 38, 70], "OutdoorAmbient": [92, 72, 124], "Brightness": 0.4, "ClockTime": 23,
                     "GeographicLatitude": 35, "EnvironmentDiffuseScale": 0.3, "EnvironmentSpecularScale": 1.0,
                     "ExposureCompensation": 0.9, "ShadowSoftness": 0.2, "GlobalShadows": True,
                     "ColorShift_Top": [0, 0, 0], "ColorShift_Bottom": [0, 0, 0]},
        "atmosphere": {"Density": 0.45, "Offset": 0.08, "Color": [118, 62, 126], "Decay": [52, 26, 70], "Glare": 0,
                       "Haze": 2.6},
        "sky": {"CelestialBodiesShown": False, "StarCount": 0, "SunAngularSize": 12, "MoonAngularSize": 10},
        "post": {"Bloom": {"Intensity": 0.85, "Size": 34, "Threshold": 0.9},
                 "ColorCorrection": {"Brightness": 0.0, "Contrast": 0.18, "Saturation": 0.12,
                                     "TintColor": [255, 222, 248]},
                 "DepthOfField": {"FarIntensity": 0.12, "NearIntensity": 0, "FocusDistance": 40, "InFocusRadius": 40},
                 "SunRays": None},
        "practicals": {
            "pendant": {"class": "PointLight", "color": [255, 60, 200], "brightness": 2.5, "range": 14,
                        "shadows": True, "why": "magenta overheads"},
            "sconce": {"class": "PointLight", "color": [60, 220, 255], "brightness": 1.5, "range": 9,
                       "shadows": False, "why": "cyan accents: complementary to magenta"},
            "lamp": {"class": "PointLight", "color": [60, 220, 255], "brightness": 1.5, "range": 10,
                     "shadows": False, "why": "cyan accents"},
            "window": {"class": "SurfaceLight", "kelvin": 6500, "brightness": 1.2, "range": 12, "shadows": False,
                       "face": "Front", "angle": 80, "why": "screen-white windows add a neutral reference"},
            "neon": {"class": "PointLight", "color": [255, 40, 180], "brightness": 4.0, "range": 22,
                     "shadows": False, "why": "big magenta sign is the hero light; reflections on specular 1.0"},
            "street": {"class": "PointLight", "color": [60, 220, 255], "brightness": 3.0, "range": 20,
                       "shadows": True, "why": "cyan street pools, shadows for silhouettes"},
            "lantern": {"class": "PointLight", "color": [255, 120, 40], "brightness": 1.6, "range": 12,
                        "shadows": False, "why": "orange paper lanterns: third accent hue"},
        },
        "targets": {"mean_luma": [30, 85], "crushed_max": 30, "clipped_max": 5, "contrast": [90, 230],
                    "warmth": [-0.25, 0.25], "saturation": [0.4, 0.95]},
        "why": {"lighting.Ambient": "dark violet fill: the base the neon sits on",
                "lighting.Brightness": "0.4: no real moon, the city lights the scene",
                "lighting.ClockTime": "late night",
                "lighting.ExposureCompensation": "+0.9 keeps the dark base legible under the neon",
                "lighting.EnvironmentDiffuseScale": "low: no sky fill",
                "atmosphere.Density": "dense magenta-violet haze catches the neon and kills the flat blue night sky",
                "post.ColorCorrection": "magenta-leaning tint and contrast; saturation modest since the night sky is already saturated",
                "post.Bloom": "strong bloom, low threshold: signs glow"},
        "key_role": "neon",
    },
}
PRESETS["moody_night_diner_teal"] = copy.deepcopy(PRESETS["moody_night_diner"])
PRESETS["moody_night_diner_teal"].update({
    "description": "Moody night diner, teal-shifted grade (cinematic teal shadows, warm pendants kept)."})
PRESETS["moody_night_diner_teal"]["lighting"]["Ambient"] = [34, 52, 54]
PRESETS["moody_night_diner_teal"]["post"]["ColorCorrection"].update({"Saturation": -0.16, "TintColor": [212, 240, 238]})
PRESETS["moody_night_diner_teal"]["practicals"]["window"]["kelvin"] = 11000
PRESETS["moody_night_diner_teal"]["targets"]["warmth"] = [-0.2, 0.12]
PRESETS["moody_night_diner_teal"]["why"].update({
    "lighting.Ambient": "teal-black fill: shadows go teal, pendants stay warm (orange/teal split)",
    "post.ColorCorrection": "teal tint + desaturation = the second reference grade"})

PRESET_NAMES = tuple(PRESETS)
_KEYWORDS = (("cyber", "neon_cyber_night"), ("neon", "neon_cyber_night"), ("horror", "overcast_horror"),
             ("fog", "overcast_horror"), ("grave", "overcast_horror"), ("haunt", "overcast_horror"),
             ("teal", "moody_night_diner_teal"), ("diner", "moody_night_diner"), ("2am", "moody_night_diner"),
             ("bar", "moody_night_diner"), ("sunset", "golden_hour_exterior"), ("golden", "golden_hour_exterior"),
             ("dusk", "golden_hour_exterior"), ("moon", "moonlit_night_exterior"), ("night", "moonlit_night_exterior"),
             ("lobby", "warm_luxury_interior"), ("hotel", "warm_luxury_interior"), ("cozy", "warm_luxury_interior"),
             ("candle", "warm_luxury_interior"), ("interior", "warm_luxury_interior"))


def choose_preset(brief: str) -> str:
    """Keyword fallback when the model's choice is missing or unknown."""
    low = (brief or "").lower()
    for word, name in _KEYWORDS:
        if word in low:
            return name
    return "bright_stylized_day"


# --------------------------------------------------------------------------- resolving + clamping
def _num(value: Any, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"not a number: {value!r}")
    return float(min(max(value, lo), hi))


def _color(value: Any) -> list[int]:
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise ValueError(f"not a colour: {value!r}")
    return [int(round(_num(c, 0, 255))) for c in value]


def _clean(section: str, props: dict) -> dict:
    rules, out = _RANGES[section], {}
    for key, value in props.items():
        rule = rules.get(key)
        if rule is None:
            raise ValueError(f"unknown property {section}.{key}")
        out[key] = _color(value) if rule == "color" else bool(value) if rule == "bool" else _num(value, *rule)
    return out


def _clean_practical(role: str, recipe: dict) -> dict | None:
    if not recipe or recipe.get("enabled") is False:
        return None
    cls = recipe.get("class", "PointLight")
    if cls not in _LIGHT_CLASSES:
        raise ValueError(f"practical {role}: bad class {cls!r}")
    rng = _RANGES["practical"]
    color = _color(recipe["color"]) if "color" in recipe else kelvin_to_rgb(_num(recipe.get("kelvin", 2700),
                                                                                *rng["kelvin"]), WHITE_BALANCE_K)
    out = {"class": cls, "color": color, "brightness": _num(recipe.get("brightness", 1), *rng["brightness"]),
           "range": _num(recipe.get("range", 12), *rng["range"]), "shadows": bool(recipe.get("shadows", False))}
    if cls != "PointLight":
        face = recipe.get("face", "Bottom" if cls == "SpotLight" else "Front")
        if face not in _FACES:
            raise ValueError(f"practical {role}: bad face {face!r}")
        out["face"], out["angle"] = face, _num(recipe.get("angle", 90), *rng["angle"])
    return out


def get_path(preset: dict, path: str) -> Any:
    node: Any = preset
    for part in path.split("."):
        node = node[part]
    return node


def resolve(preset: str | dict, overrides: dict | None = None) -> dict:
    """Deep copy of a preset (by name or dict) with dotted-path overrides applied, e.g.
    {"lighting.ExposureCompensation": 0.5, "post.ColorCorrection.Contrast": 0.2}. Unknown paths raise."""
    if isinstance(preset, str):
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}")
        base = copy.deepcopy(PRESETS[preset])
        base.setdefault("name", preset)
    else:
        base = copy.deepcopy(preset)
    for path, value in (overrides or {}).items():
        parts = path.split(".")
        node = base
        for part in parts[:-1]:
            if not isinstance(node, dict) or not isinstance(node.get(part), dict):
                raise ValueError(f"override path not in preset: {path}")
            node = node[part]
        if parts[-1] not in node and not (len(parts) == 2 and parts[0] in ("lighting", "atmosphere", "sky")):
            raise ValueError(f"override path not in preset: {path}")
        node[parts[-1]] = value
    return base


# --------------------------------------------------------------------------- Luau
def _lua_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "Color3.fromRGB(%d, %d, %d)" % tuple(value)
    if isinstance(value, str):
        return json.dumps(value)
    return repr(round(float(value), 4))


def _lua_props(props: dict) -> str:
    return "{" + ", ".join(f"{k} = {_lua_value(v)}" for k, v in props.items()) + "}"


_ROOT = re.compile(r"workspace(\.[A-Za-z_][A-Za-z0-9_]{0,63}){0,6}")

_SAVE_AND_CLEAR = """local Lighting = game:GetService("Lighting")
local ServerStorage = game:GetService("ServerStorage")
local PROPS = {%(props)s}
local backup = ServerStorage:FindFirstChild("%(backup)s")
if not backup then
	-- First apply: remember every Lighting property and park the original children so they can come back.
	backup = Instance.new("Folder")
	backup.Name = "%(backup)s"
	for _, p in ipairs(PROPS) do backup:SetAttribute(p, Lighting[p]) end
	pcall(function() backup:SetAttribute("LightingStyle", Lighting.LightingStyle.Name) end)
	local kept = Instance.new("Folder")
	kept.Name = "Children"
	kept.Parent = backup
	for _, child in ipairs(Lighting:GetChildren()) do child.Parent = kept end
	backup.Parent = ServerStorage
end
for _, child in ipairs(Lighting:GetChildren()) do
	if child:GetAttribute("StarLighting") then
		child:Destroy()
	elseif child:IsA("PostEffect") or child:IsA("Atmosphere") or child:IsA("Sky") or child:IsA("Clouds") then
		child.Parent = backup.Children -- never stack effects; restore_luau brings it back
	end
end
local function root()
	local node = workspace
	for _, name in ipairs({%(root)s}) do node = node and node:FindFirstChild(name) end
	return node
end
"""


def lighting_luau(preset: str | dict, overrides: dict | None = None, root: str = "workspace") -> str:
    """Luau that applies a preset (name or resolved dict). Saves the previous Lighting into
    ServerStorage.StarLightingBackup on the first apply; restore_luau() undoes it. Returns a status string."""
    p = resolve(preset, overrides)
    if not _ROOT.fullmatch(root):
        raise ValueError("root must look like workspace.Folder.Sub")
    name = str(p.get("name", "custom"))[:64]
    lighting = _clean("lighting", p.get("lighting", {}))
    lines = [f"-- STAR lighting preset {name} (generated by star.roblox_lighting_presets; deterministic)",
             _SAVE_AND_CLEAR % {"props": ", ".join(json.dumps(x) for x in _LIGHTING_PROPS), "backup": BACKUP_NAME,
                                "root": ", ".join(json.dumps(x) for x in root.split(".")[1:])}]
    for key, value in lighting.items():
        lines.append(f"Lighting.{key} = {_lua_value(value)}")
    style = p.get("lighting_style")
    if style in ("Realistic", "Soft"):
        lines.append(f'pcall(function() Lighting.LightingStyle = Enum.LightingStyle.{style} end)')
    lines.append("local function make(class, name, props)\n\tlocal o = Instance.new(class)\n\to.Name = \"Star_\" .. "
                 "name\n\tfor k, v in pairs(props) do o[k] = v end\n\to:SetAttribute(\"StarLighting\", true)\n"
                 "\to.Parent = Lighting\n\treturn o\nend")
    if p.get("atmosphere"):
        lines.append(f'make("Atmosphere", "Atmosphere", {_lua_props(_clean("atmosphere", p["atmosphere"]))})')
    if p.get("sky"):
        lines.append(f'make("Sky", "Sky", {_lua_props(_clean("sky", p["sky"]))})')
    for effect, props in (p.get("post") or {}).items():
        if props:
            lines.append(f'make("{_POST_CLASS[effect]}", "{effect}", {_lua_props(_clean(effect, props))})')
    recipes = []
    for role in ROLES:
        r = _clean_practical(role, (p.get("practicals") or {}).get(role))
        if r:
            extra = f', face = "{r["face"]}", angle = {_lua_value(r["angle"])}' if "face" in r else ""
            recipes.append(f'\t{role} = {{class = "{r["class"]}", color = {_lua_value(r["color"])}, brightness = '
                           f'{_lua_value(r["brightness"])}, range = {_lua_value(r["range"])}, shadows = '
                           f'{_lua_value(r["shadows"])}{extra}}},')
    lines.append("local RECIPES = {\n" + "\n".join(recipes) + "\n}")
    lines.append(_PRACTICALS % {"name": json.dumps(name)})
    return "\n".join(lines) + "\n"


_PRACTICALS = """local lit, off = 0, 0
local scope = root()
if scope then
	for _, part in ipairs(scope:GetDescendants()) do
		local role = part:IsA("BasePart") and part:GetAttribute("StarPractical")
		if role then
			for _, old in ipairs(part:GetChildren()) do
				if old:GetAttribute("StarPracticalLight") then old:Destroy() end
			end
			local r = RECIPES[role]
			if part.Material == Enum.Material.Neon and part:GetAttribute("StarPrevColor") == nil then
				part:SetAttribute("StarPrevColor", part.Color)
			end
			if r then
				local light = Instance.new(r.class)
				light.Name = "StarPracticalLight"
				light.Color, light.Brightness, light.Range, light.Shadows = r.color, r.brightness, r.range, r.shadows
				if r.face then light.Face = Enum.NormalId[r.face]; light.Angle = r.angle end
				light:SetAttribute("StarPracticalLight", true)
				light.Parent = part
				if part.Material == Enum.Material.Neon then part.Color = r.color end
				lit += 1
			else
				if part.Material == Enum.Material.Neon then part.Color = Color3.fromRGB(70, 68, 66) end
				off += 1
			end
		end
	end
end
return string.format("STAR lighting %%s applied: %%d practical lights, %%d off", %(name)s, lit, off)
"""

_RESTORE = """local Lighting = game:GetService("Lighting")
local ServerStorage = game:GetService("ServerStorage")
local PROPS = {%(props)s}
local node = workspace
for _, name in ipairs({%(root)s}) do node = node and node:FindFirstChild(name) end
if node then
	for _, d in ipairs(node:GetDescendants()) do
		if d:GetAttribute("StarPracticalLight") then
			d:Destroy()
		elseif d:IsA("BasePart") and d:GetAttribute("StarPrevColor") ~= nil then
			d.Color = d:GetAttribute("StarPrevColor")
			d:SetAttribute("StarPrevColor", nil)
		end
	end
end
local backup = ServerStorage:FindFirstChild("%(backup)s")
if not backup then return "STAR lighting: nothing to restore" end
for _, child in ipairs(Lighting:GetChildren()) do
	if child:GetAttribute("StarLighting") then child:Destroy() end
end
for _, p in ipairs(PROPS) do
	local v = backup:GetAttribute(p)
	if v ~= nil then Lighting[p] = v end
end
local style = backup:GetAttribute("LightingStyle")
if style then pcall(function() Lighting.LightingStyle = Enum.LightingStyle[style] end) end
local kept = backup:FindFirstChild("Children")
if kept then
	for _, child in ipairs(kept:GetChildren()) do child.Parent = Lighting end
end
backup:Destroy()
return "STAR lighting restored"
"""


def restore_luau(root: str = "workspace") -> str:
    """Luau that removes STAR's lights/effects and puts the saved Lighting state back."""
    if not _ROOT.fullmatch(root):
        raise ValueError("root must look like workspace.Folder.Sub")
    return _RESTORE % {"props": ", ".join(json.dumps(x) for x in _LIGHTING_PROPS), "backup": BACKUP_NAME,
                       "root": ", ".join(json.dumps(x) for x in root.split(".")[1:])}


# --------------------------------------------------------------------------- brief -> plan -> preset
def plan_prompt(brief: str) -> str:
    """Prompt for the local model: choose a preset and a few knobs; JSON only, never Luau."""
    menu = "\n".join(f"- {n}: {PRESETS[n]['description']}" for n in PRESET_NAMES)
    return (
        "You pick the lighting look for a Roblox scene. Reply with ONE JSON object and nothing else.\n"
        f"Brief: {json.dumps(str(brief)[:300])}\n\nPresets:\n{menu}\n\n"
        "Keys:\n"
        '  "preset": one preset name from the list (required)\n'
        '  "time_of_day": number 0-24, only if the brief implies a time\n'
        '  "warmth": -1..1 (negative = cooler/bluer, positive = warmer)\n'
        '  "contrast": -1..1 (positive = deeper shadows, punchier)\n'
        '  "saturation": -1..1\n'
        '  "fog": -1..1 (positive = more fog/haze)\n'
        '  "key_light_color": optional "#RRGGBB" for the main light, only if the brief names a colour\n'
        "Use 0 for anything the brief does not ask to change.\n"
        'Example: {"preset": "golden_hour_exterior", "time_of_day": 17.5, "warmth": 0.3, "contrast": 0.1, '
        '"saturation": 0, "fog": -0.2}'
    )


def parse_plan(text: str) -> dict:
    """First JSON object in the model's reply (code fences and prose tolerated); {} if none."""
    text = text or ""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc, in_str = (False, in_str) if esc else (ch == "\\", ch != '"')
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        got = json.loads(text[start:i + 1])
                        if isinstance(got, dict):
                            return got
                    except ValueError:
                        pass
                    break
        start = text.find("{", start + 1)
    return {}


def _knob(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, -1.0), 1.0) if math.isfinite(v) else 0.0


_TIMES = {"dawn": 6.2, "sunrise": 6.5, "morning": 9, "noon": 12, "midday": 12, "afternoon": 15, "golden": 17.6,
          "sunset": 17.9, "dusk": 18.3, "evening": 20, "night": 22, "midnight": 0}


_COLOUR_WORDS = re.compile(r"(red|orange|amber|yellow|gold|golden|green|teal|cyan|blue|purple|violet|magenta|"
                           r"pink|white|neon|warm|cool|cold)", re.I)


def _hex_color(value: Any) -> list[int] | None:
    if isinstance(value, str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", value.strip()):
        h = value.strip().lstrip("#")
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 1000 <= value <= 12000:
        return kelvin_to_rgb(value)
    return None


def _scale(color: list, factor: float) -> list[int]:
    return [int(round(min(max(c * factor, 0), 255))) for c in color]


def _mix(a: list, b: list, t: float) -> list[int]:
    return [int(round(x + (y - x) * t)) for x, y in zip(a, b)]


def _tint(tint: list, warmth: float) -> list[int]:
    r, g, b = tint
    if warmth >= 0:
        return [r, int(round(g * (1 - 0.03 * warmth))), int(round(b * (1 - 0.09 * warmth)))]
    return [int(round(r * (1 + 0.09 * warmth))), int(round(g * (1 + 0.02 * warmth))), b]


def apply_plan(plan: dict, brief: str = "") -> dict:
    """Clamp the model's plan and map it onto its preset deterministically. Returns a resolved preset dict
    (feed it to lighting_luau) with "plan" (the normalised plan) and "notes" (what changed and why)."""
    plan = plan if isinstance(plan, dict) else {}
    name = plan.get("preset")
    notes = []
    if name not in PRESETS:
        fallback = choose_preset(brief)
        notes.append(f"preset {name!r} unknown or missing; keyword fallback -> {fallback}")
        name = fallback
    p = resolve(name)
    warmth, contrast, sat, fog = (_knob(plan.get(k)) for k in ("warmth", "contrast", "saturation", "fog"))
    norm = {"preset": name, "warmth": warmth, "contrast": contrast, "saturation": sat, "fog": fog}
    tod = plan.get("time_of_day")
    if isinstance(tod, str):
        tod = _TIMES.get(tod.strip().lower(), tod)
        try:
            tod = float(str(tod).split(":")[0]) + (float(str(tod).split(":")[1]) / 60 if ":" in str(tod) else 0)
        except (ValueError, IndexError):
            tod = None
    if isinstance(tod, (int, float)) and not isinstance(tod, bool) and math.isfinite(tod):
        lo, hi = p["clock_range"]
        t = float(tod) % 24
        if not lo <= t <= hi:  # outside the preset's band: snap to the nearer edge on the 24 h circle

            def dist(a, b):
                d = abs(a - b) % 24
                return min(d, 24 - d)

            t = lo if dist(t, lo) <= dist(t, hi) else hi
        p["lighting"]["ClockTime"] = round(t % 24, 2)
        norm["time_of_day"] = p["lighting"]["ClockTime"]
        notes.append(f"time_of_day {tod} -> ClockTime {norm['time_of_day']} (preset band {lo}-{hi})")
    cc = p["post"].get("ColorCorrection")
    if warmth:
        cc["TintColor"] = _tint(cc["TintColor"], warmth)
        for recipe in p["practicals"].values():
            if recipe.get("enabled", True) and "kelvin" in recipe:
                recipe["kelvin"] = int(min(max(recipe["kelvin"] * (1 - 0.08 * warmth), 1500), 12000))
        if p.get("atmosphere"):
            p["atmosphere"]["Color"] = _tint(p["atmosphere"]["Color"], warmth)
        notes.append(f"warmth {warmth:+.2f}: tint, practical kelvin and fog colour shifted")
    if contrast:
        cc["Contrast"] = round(min(max(cc["Contrast"] + 0.15 * contrast, -0.3), 0.5), 3)
        p["lighting"]["Ambient"] = _scale(p["lighting"]["Ambient"], 1 - 0.35 * contrast)
        p["lighting"]["ShadowSoftness"] = round(min(max(p["lighting"]["ShadowSoftness"] - 0.15 * contrast, 0.05),
                                                    0.8), 3)
        notes.append(f"contrast {contrast:+.2f}: CC contrast, ambient fill and shadow softness")
    if sat:
        cc["Saturation"] = round(min(max(cc["Saturation"] + 0.2 * sat, -0.6), 0.5), 3)
        notes.append(f"saturation {sat:+.2f}: CC saturation")
    if fog and p.get("atmosphere"):
        a = p["atmosphere"]
        a["Density"] = round(min(max(a["Density"] + 0.15 * fog, 0.0), 0.6), 3)
        a["Haze"] = round(min(max(a["Haze"] + 1.2 * fog, 0.0), 6.0), 2)
        notes.append(f"fog {fog:+.2f}: atmosphere density/haze")
    key = _hex_color(plan.get("key_light_color"))
    if key and brief and not _COLOUR_WORDS.search(brief):
        notes.append("key_light_color ignored: the brief names no colour")
        key = None
    if key:
        norm["key_light_color"] = "#%02x%02x%02x" % tuple(key)
        role = p.get("key_role")
        if role and p["practicals"].get(role, {}).get("enabled", True):
            p["practicals"][role]["color"] = key
            notes.append(f"key_light_color -> {role} practicals")
        else:
            p["lighting"]["ColorShift_Top"] = _mix(p["lighting"]["ColorShift_Top"], key, 0.5)
            notes.append("key_light_color -> sun tint (ColorShift_Top)")
    p["plan"], p["notes"] = norm, notes
    return p


# --------------------------------------------------------------------------- render checks (Pillow)
def analyze_render(image: Any) -> dict:
    """Histogram metrics of a render (path or PIL image): mean luma, crushed/clipped %, p5/p95, contrast,
    warmth (mean R-B, -1..1) and saturation (mean HSV S of non-black pixels)."""
    from PIL import Image  # only dependency outside the standard library; imported lazily

    img = image if hasattr(image, "convert") else Image.open(image)
    img = img.convert("RGB")
    if img.width > 320:
        img = img.resize((320, max(1, round(img.height * 320 / img.width))))
    hist, n, sum_l, sum_rb, sat_sum, sat_n = [0] * 256, 0, 0.0, 0.0, 0.0, 0
    raw = img.tobytes()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        hist[min(255, int(luma + 0.5))] += 1
        n += 1
        sum_l += luma
        sum_rb += r - b
        mx = max(r, g, b)
        if mx >= 25:
            sat_sum += (mx - min(r, g, b)) / mx
            sat_n += 1

    def pct(q):
        acc = 0
        for i, c in enumerate(hist):
            acc += c
            if acc >= q * n:
                return i
        return 255

    p5, p95 = pct(0.05), pct(0.95)
    return {"mean_luma": round(sum_l / n, 1), "crushed_pct": round(100 * sum(hist[:11]) / n, 2),
            "clipped_pct": round(100 * sum(hist[250:]) / n, 2), "p5": p5, "p95": p95, "contrast": p95 - p5,
            "warmth": round(sum_rb / n / 255, 3), "saturation": round(sat_sum / sat_n, 3) if sat_n else 0.0}


def average_metrics(metrics: list[dict]) -> dict:
    keys = metrics[0].keys()
    return {k: round(sum(m[k] for m in metrics) / len(metrics), 3) for k in keys}


def check_render(metrics: dict, preset: dict) -> list[dict]:
    """Findings: each metric outside the preset's target band."""
    t, out = preset["targets"], []
    for key, metric in (("mean_luma", "mean_luma"), ("contrast", "contrast"), ("warmth", "warmth"),
                        ("saturation", "saturation")):
        lo, hi = t[key]
        v = metrics[metric]
        if v < lo or v > hi:
            out.append({"metric": metric, "value": v, "target": [lo, hi], "problem": "low" if v < lo else "high"})
    for metric, limit in (("crushed_pct", "crushed_max"), ("clipped_pct", "clipped_max")):
        if metrics[metric] > t[limit]:
            out.append({"metric": metric, "value": metrics[metric], "target": [0, t[limit]], "problem": "high"})
    return out


def suggest_fix(metrics: dict, preset: dict, iteration: int = 0) -> tuple[dict, list[str]]:
    """Deterministic overrides (dotted path -> new absolute value) for lighting_luau, plus reasons.
    Only one fix iteration is allowed: iteration >= 1 returns no fix."""
    if iteration >= 1:
        return {}, ["fix budget used (one iteration max)"]
    over, why = {}, []
    t = preset["targets"]
    findings = {f["metric"]: f for f in check_render(metrics, preset)}
    exp = preset["lighting"]["ExposureCompensation"]
    cc = preset["post"].get("ColorCorrection") or {}
    if "mean_luma" in findings:
        lo, hi = t["mean_luma"]
        goal = lo + 0.4 * (hi - lo)  # aim low in the band: dark moods should stay dark
        stops = math.log2(goal / max(metrics["mean_luma"], 1.0))
        if stops > 0 and "crushed_pct" in findings:
            stops *= 0.6  # the ambient fill below also lifts the frame; together they overshoot otherwise
        stops = math.copysign(min(max(abs(stops), 0.15), 0.8), stops)
        new = round(min(max(exp + stops, -2.0), 2.0) * 20) / 20
        over["lighting.ExposureCompensation"] = new
        why.append(f"mean luma {metrics['mean_luma']} outside {lo}-{hi}: exposure {exp:+.2f} -> {new:+.2f}")
    if "crushed_pct" in findings:  # exposure barely lifts true black; ambient fill is the lever for shadows
        for key in ("Ambient", "OutdoorAmbient"):
            over["lighting." + key] = [max(c, 10) for c in _scale(preset["lighting"][key], 1.5)]
        why.append(f"crushed blacks {metrics['crushed_pct']}% > {t['crushed_max']}%: ambient + outdoor ambient x1.5")
    if "clipped_pct" in findings and preset["post"].get("Bloom"):
        bloom = preset["post"]["Bloom"]
        over["post.Bloom.Intensity"] = round(bloom["Intensity"] * 0.6, 3)
        over["post.Bloom.Threshold"] = round(min(bloom["Threshold"] + 0.2, 4), 3)
        why.append(f"clipped whites {metrics['clipped_pct']}% > {t['clipped_max']}%: bloom down")
    if cc:
        if "contrast" in findings:
            step = 0.1 if findings["contrast"]["problem"] == "low" else -0.1
            over["post.ColorCorrection.Contrast"] = round(min(max(cc["Contrast"] + step, -0.3), 0.5), 3)
            why.append(f"contrast {metrics['contrast']} outside {t['contrast']}: CC contrast {step:+.1f}")
        if "warmth" in findings:
            w = 0.5 if findings["warmth"]["problem"] == "low" else -0.5
            over["post.ColorCorrection.TintColor"] = _tint(cc["TintColor"], w)
            why.append(f"warmth {metrics['warmth']} outside {t['warmth']}: tint {'warmer' if w > 0 else 'cooler'}")
        if "saturation" in findings:
            step = 0.1 if findings["saturation"]["problem"] == "low" else -0.1
            over["post.ColorCorrection.Saturation"] = round(min(max(cc["Saturation"] + step, -0.6), 0.5), 3)
            why.append(f"saturation {metrics['saturation']} outside {t['saturation']}: CC saturation {step:+.1f}")
    return over, why
