"""Prompts for the builder stages. Written for STAR's own models (litha); they return JSON only."""
from __future__ import annotations

import json

from . import kits
from .geom import MATERIALS
from .scene import MOODS, ROOFS, WINDOWS

STYLE_GUIDE = {
    "stud": "STUD (classic Roblox): chunky blocks on a whole-stud grid, studded tops, a LIMITED palette of 4-6 classic "
            "BrickColors, bold readable silhouettes, terraced/stacked masses (staggered blocks, two-tone layers, moss "
            "drips), toy-like scale exaggeration is fine. No realistic materials.",
    "lowpoly": "LOW-POLY: faceted shapes from wedges and rotated blocks, flat smooth colours, soft saturated palette "
               "with clear value contrast, simple bold forms, fewer but larger props, gradients through colour steps.",
    "midpoly": "MID-POLY: believable proportions, real materials (wood, brick, plaster, metal, fabric), round shapes, "
               "trims and frames, moderate prop density, coherent warm/cool lighting.",
    "highpoly": "HIGH-POLY: dense detail - trims, bevels, fluting, many small props with intent, layered lighting "
                "(practical lamps + fill), atmosphere and post effects, realistic materials, cinematic composition.",
}

RULES = """Roblox scale: a character is 5 studs tall and 2 wide. Doors >= 5 wide x 8 high. Corridors >= 6 wide.
Ceilings 12-16 for homes/shops, 24-40 for halls/cathedrals. Seats 2 high, tables 3 high, counters 3.9 high.
Coordinates: the map is centred on (0,0); x across, z deep; size [W, D]. Sides: N = -z edge, S = +z edge,
W = -x edge, E = +x edge. Kits face -z (front) unless rotated by "rot" (degrees about up).
Composition: one clear focal point the eye lands on; a path / row of repeated props leading to it (leading lines);
frame it (columns, trees, arches); layered depth (foreground, middle, background); leave breathing room (negative
space) around the focal point; asymmetry with balance; a clear walkable route from spawn to every focal point.
Storytelling: 2-4 small story moments placed with intent (e.g. an overturned chair by a door, papers trailing to a
desk, rubble under a hole in the roof); clutter goes in corners, along walls and near story moments - never as
uniform noise spread everywhere.
Lighting: light pools at the focal point and along the route; warm vs cool contrast; practical lamps placed where
they would really be (pendants over tables/counters, sconces on walls, lamp posts along paths).
Colour/material discipline: a palette of primary/secondary/accent/trim (hex) that fits the mood; few materials;
one accent colour used sparingly on things that matter.
Automatic helpers: wall kits (shelf, picture, sconce, vines, cabinet, fireplace, cobweb, bookcase_tall, aquarium_tank,
vending_machine, paper_screen, info_plaque, planks, trash) snap to the nearest wall of their room if placed within 8
studs of it; chandelier/pendant_lamp inside a room attach to its ceiling; invisible fill light is added to rooms."""

SCHEMA = {
    "name": "short name", "style": "stud|lowpoly|midpoly|highpoly", "state": "new|worn|abandoned",
    "mood": "|".join(MOODS), "palette": {"primary": "#hex", "secondary": "#hex", "accent": "#hex", "trim": "#hex"},
    "size": [100, 80], "ground": "one of the materials", "sign_text": "text for sign kits (optional)",
    "zones": [{"id": "hall", "rect": [-30, -30, 30, 20], "floor": "material or empty for outdoor ground",
               "purpose": "what happens here"}],
    "rooms": [{"zone": "hall", "h": 16, "wall": "material", "roof": "|".join(ROOFS), "windows": "|".join(WINDOWS),
               "openings": [{"side": "S", "at": 0.5, "w": 6, "h": 9, "kind": "door|window|arch|open"}]}],
    "spawn": [0, 35], "focal": [{"id": "altar", "at": [0, -25], "why": "..."}],
    "paths": [{"from": [0, 40], "to": [0, 20], "w": 6, "mat": "cobble"}],
    "props": [{"kit": "pew", "at": [-6, -10], "rot": 0, "params": {"len": 10}, "repeat": {"n": 6, "step": [0, 5]},
               "why": "rows lead to the altar"}, {"kit": "candles", "at": [3, -24], "y": 1.5, "params": {"n": 6}}],
}


def _base(style: str) -> str:
    return (f"STYLE: {STYLE_GUIDE[style]}\n\nRULES:\n{RULES}\n\nMaterials: {', '.join(MATERIALS)}\n"
            f"Moods: {', '.join(MOODS)}")


def plan_messages(brief: str, style: str) -> list[dict]:
    schema = {k: SCHEMA[k] for k in ("name", "style", "state", "mood", "palette", "size", "ground", "sign_text", "zones",
                                      "rooms", "spawn", "focal", "paths")}
    return [{"role": "system", "content": "You are STAR, a senior Roblox environment artist. You plan levels like a "
             "professional: layout first, then detail. Answer with one JSON object only."},
            {"role": "user", "content": f"{_base(style)}\n\nBRIEF: {brief}\nART STYLE: {style}\n\nStep 1 - LAYOUT PLAN. "
             "Decide the footprint, zones (rectangles that do not overlap), rooms (walls/roof per indoor zone, with doors "
             "facing the route), spawn, 1-3 focal points, paths, palette and mood. Also add \"story\": a list of 2-4 "
             "story moments {\"at\": [x, z], \"what\": \"...\"} and \"sightline\": one sentence on what the player sees "
             "first from the spawn. JSON shape:\n" + json.dumps(schema)}]


def detail_messages(brief: str, style: str, plan: dict) -> list[dict]:
    return [{"role": "system", "content": "You are STAR, a senior Roblox environment artist. Answer with one JSON object only."},
            {"role": "user", "content": f"{_base(style)}\n\nKIT CATALOG (kit(params): what it is):\n{kits.catalog()}\n\n"
             f"BRIEF: {brief}\nART STYLE: {style}\nLAYOUT PLAN (fixed):\n{json.dumps(plan)}\n\nStep 2 - DETAIL PASS. Dress "
             "the plan with props from the catalog: structure first (columns, stairs, platforms), then hero props at "
             "the focal points, then furniture/sets per zone, then lights, then story props at the story moments, then "
             "nature/dressing. Use \"repeat\" for rows. Keep the route from spawn to each focal point clear (6 studs). "
             "Aim for 35-80 prop entries; every zone gets props that match its purpose. Answer {\"props\": [...]} "
             "with entries shaped like " + json.dumps(SCHEMA["props"])}]


def baseline_messages(brief: str, style: str) -> list[dict]:
    return [{"role": "system", "content": "You are STAR, a senior Roblox environment artist. Answer with one JSON object only."},
            {"role": "user", "content": f"{_base(style)}\n\nKIT CATALOG (kit(params): what it is):\n{kits.catalog()}\n\n"
             f"BRIEF: {brief}\nART STYLE: {style}\n\nWrite the complete build spec in one go (zones, rooms, spawn, focal, "
             "paths and 35-80 prop entries). JSON shape:\n" + json.dumps(SCHEMA)}]


CRITIC_RUBRIC = """Score this Roblox environment (4 camera shots: eye-level hero view from the spawn, wide view, detail
view, overview) like a strict senior environment-art lead. Scores 1-10 (10 = portfolio quality):
composition (clear focal point, leading lines, framing, depth, negative space), scale (believable vs a 5-stud
character), lighting (mood, light pools, contrast; not flat, not murky), detail (density right for the style; not empty,
not noisy), story (intentional details that tell what happened here), style (one consistent art style), color (palette
and material discipline), cleanliness (no floating/clipping/overlapping parts, no z-fighting, no 'AI slop': random
clutter, uniform noise, mismatched pieces)."""


def critic_messages(brief: str, style: str, sheet_part: dict, props_text: str, metrics: dict) -> list[dict]:
    return [{"role": "user", "content": [
        {"type": "text", "text": f"{CRITIC_RUBRIC}\n\nBRIEF: {brief}\nTARGET STYLE: {style}\nMEASURED: {json.dumps(metrics)}\n"
         f"PROPS (index: kit at [x,z]):\n{props_text}\n\nReturn JSON: {{\"scores\": {{\"composition\": n, \"scale\": n, "
         "\"lighting\": n, \"detail\": n, \"story\": n, \"style\": n, \"color\": n, \"cleanliness\": n}}, \"overall\": n, "
         "\"problems\": [\"...\"], \"fixes\": [\"concrete change, naming props by index or position, e.g. 'add 3 "
         "pendant_lamp over the counter at x=-6..6, z=-10' or 'remove prop 14' or 'mood warm_evening'\"]}. At most 6 fixes, "
         "most impactful first."},
        sheet_part]}]


OPS_HELP = """Edit operations (JSON list "ops"):
{"op":"add","prop":{"kit":...,"at":[x,z],"rot":0,"params":{...},"repeat":{...},"y":optional}}
{"op":"move","index":i,"at":[x,z]}            {"op":"rotate","index":i,"rot":deg}
{"op":"remove","index":i}                      {"op":"params","index":i,"params":{...}}
{"op":"set","field":"mood|state|ground|palette","value":...}
{"op":"room","zone":"id","field":"h|roof|windows|wall","value":...}
{"op":"opening","zone":"id","opening":{"side":"S","at":0.5,"w":6,"h":9,"kind":"door"}}"""


def revise_messages(brief: str, style: str, spec: dict, defects: list[str], critique: dict | None) -> list[dict]:
    props = [{"i": i, "kit": p["kit"], "at": p["at"], "rot": p["rot"], "params": p["params"],
              **({"repeat": p["repeat"]} if p.get("repeat") else {})} for i, p in enumerate(spec["props"])]
    head = {k: spec[k] for k in ("style", "state", "mood", "palette", "size", "ground", "zones", "rooms", "spawn", "focal")}
    crit = json.dumps({k: critique.get(k) for k in ("scores", "problems", "fixes")}) if critique else "none"
    return [{"role": "system", "content": "You are STAR, a senior Roblox environment artist fixing your own build. "
             "Answer with one JSON object only."},
            {"role": "user", "content": f"{_base(style)}\n\nKIT CATALOG:\n{kits.catalog()}\n\nBRIEF: {brief}\n"
             f"CURRENT SPEC (head): {json.dumps(head)}\nPROPS: {json.dumps(props)}\n\nMEASURED DEFECTS:\n"
             + ("\n".join(f"- {d}" for d in defects) or "- none") + f"\n\nART-LEAD CRITIQUE OF THE RENDER: {crit}\n\n"
             f"{OPS_HELP}\n\nFix the defects and apply the critique's fixes (only the ones that make the build better "
             "for the brief). Prefer few strong changes over many small ones. Answer {\"ops\": [...]}."}]


def metric_critic_messages(brief: str, style: str, spec: dict, props_text: str, metrics: dict, facts: dict) -> list[dict]:
    head = {k: spec[k] for k in ("style", "state", "mood", "palette", "size", "zones", "rooms", "spawn", "focal", "paths")}
    text = (f"{CRITIC_RUBRIC}\n\nYou cannot see the images; you get measured facts of the 4 rendered shots (hero, wide, "
            "detail, overview) and the full build spec. Judge the layout, composition, lighting choices, density and "
            f"storytelling from them.\n\nRULES:\n{RULES}\n\nBRIEF: {brief}\nTARGET STYLE: {style}\nSPEC: {json.dumps(head)}\n"
            f"PROPS (index: kit at [x,z]):\n{props_text}\nSCENE METRICS: {json.dumps(metrics)}\nSHOT FACTS: {json.dumps(facts)}\n\n"
            'Return JSON: {"scores": {"composition": n, "scale": n, "lighting": n, "detail": n, "story": n, "style": n, '
            '"color": n, "cleanliness": n}, "overall": n, "problems": ["..."], "fixes": ["concrete change naming props by '
            'index or position"]}. At most 6 fixes, most impactful first: missing brief elements, empty zones, weak focal '
            "point, lights.")
    return [{"role": "system", "content": "You are STAR's strict senior environment-art lead. Answer with one JSON object only."},
            {"role": "user", "content": text}]
