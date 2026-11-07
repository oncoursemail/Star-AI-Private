"""Prompts for the builder stages, sized for STAR's GPU nodes (litha: 4096 tokens of context for prompt + answer).

Props use a compact array form: [kit, x, z, rot, {params}, n, dx, dz] (n/dx/dz = repeat count and step, optional).
"""
from __future__ import annotations

import json

from . import kits
from .scene import MOODS

STYLE_GUIDE = {
    "stud": "STUD: chunky whole-stud blocks, studded tops, 4-6 classic BrickColors, bold silhouettes, terraced stacked masses.",
    "lowpoly": "LOW-POLY: faceted wedges, flat colours, soft saturated palette with value contrast, fewer bigger props.",
    "midpoly": "MID-POLY: believable proportions, real materials (wood, brick, plaster, metal, fabric), trims, moderate detail.",
    "highpoly": "HIGH-POLY: dense purposeful detail, trims, smooth round props, layered practical lighting, cinematic.",
}

RULES = """Scale: character 5 tall. Doors >=5x8. Paths >=6 wide. Ceilings 12-16 (homes/shops), 24-40 (halls).
Sizes: a small room/shop/cafe is 24-40 wide, a hall 40-80; outdoor maps 80-200. Keep spaces tight enough to fill.
Map centred on (0,0): x across, z deep. Sides: N=-z, S=+z, W=-x, E=+x. Kits face -z unless rot (deg).
Composition: one clear focal point; leading lines (paths, rows) toward it; framing; foreground/middle/background;
space around the focal point; clear walkable route spawn->focal. Story: 2-4 small story moments with clutter
clustered at walls/corners/story spots, never spread evenly. Lights: pools at focal point and along the route,
lamps where they really hang. Palette: primary/secondary/accent/trim hex; accent used sparingly.
Wall kits snap to the nearest wall within 8 studs; ceiling lamps attach to the ceiling."""

MATS = ("stone cobble brick wood plank metal rust glass fabric plaster tile marble concrete grass sand water foliage "
        "snow rock carpet roof clay asphalt ground pebble granite sandstone ice mud")

CORE = ("column", "platform", "stairs", "railing", "fence", "table", "chair", "bench", "shelf", "rug", "cabinet",
        "potted_plant", "pendant_lamp", "chandelier", "sconce", "floor_lamp", "lamp_post", "candles", "lantern",
        "string_lights", "tree", "bush", "rocks", "grass_tufts", "crate", "barrel", "rubble", "papers", "sign",
        "picture", "counter", "water", "cliff", "puddle", "cobweb", "vines", "planks", "trash")


def kit_menu(brief: str, limit: int = 46) -> str:
    """The kits worth showing for this brief: whole-word brief matches first, then the core set; off-theme kits and
    landmarks the brief does not name are never offered (substring matching put a lighthouse in every scene)."""
    from . import art
    on = art.themes_on(brief)
    scored = []
    for name in kits.KITS:
        if not art.kit_allowed(name, brief, on):
            continue
        scored.append((-art.kit_score(name, brief) - (3 if name in CORE else 0), name))
    chosen = [n for _, n in sorted(scored)][:limit]
    lines = []
    for name in sorted(chosen):
        info = kits.KITS[name]
        ps = []
        for key, rule in info["params"].items():
            ps.append(f"{key}:{'|'.join(rule[1])}" if isinstance(rule[1], list) else f"{key}:{rule[0]:g}")
        summary = info["summary"].split("(")[0].split(",")[0][:38]
        lines.append(f"{name}({' '.join(ps)}) {summary}")
    return "\n".join(lines)


PROP_FORMAT = ('props: [[kit, x, z, rot, {params}, n, dx, dz], ...]  (n,dx,dz optional: n copies stepping dx,dz; '
               'optional "y" in params = base height, e.g. on a table)')

PLAN_SHAPE = ('{"name":"..","state":"new|worn|abandoned","mood":"' + "|".join(MOODS) + '",'
              '"palette":{"primary":"#hex","secondary":"#hex","accent":"#hex","trim":"#hex"},"size":[W,D],"ground":"mat",'
              '"sign_text":"..","zones":[{"id":"hall","rect":[x0,z0,x1,z1],"floor":"mat or empty","purpose":".."}],'
              '"rooms":[{"zone":"hall","h":16,"wall":"mat","roof":"flat|gable|vault|broken|none","windows":"plain|stained|none",'
              '"openings":[{"side":"S","at":0.5,"w":6,"h":9,"kind":"door|window|arch|open"}]}],'
              '"spawn":[x,z],"focal":[{"id":"..","at":[x,z]}],"paths":[{"from":[x,z],"to":[x,z],"w":6,"mat":"cobble"}],'
              '"story":[{"at":[x,z],"what":".."}]}')


def _sys() -> dict:
    return {"role": "system", "content": "You are STAR, a senior Roblox environment artist. Reply with one compact JSON object only."}


def plan_messages(brief: str, style: str) -> list[dict]:
    return [_sys(), {"role": "user", "content":
            f"{STYLE_GUIDE[style]}\n{RULES}\nMaterials: {MATS}\n\nBRIEF: {brief}\n\nSTEP 1 LAYOUT PLAN only (no props yet): "
            "footprint, non-overlapping zones, rooms for indoor zones (doors facing the route), spawn, 1-3 focal points, "
            f"paths, palette, mood, 2-4 story moments. JSON:\n{PLAN_SHAPE}"}]


def _plan_text(plan: dict) -> str:
    keep = {k: plan.get(k) for k in ("size", "mood", "state", "zones", "rooms", "spawn", "focal", "paths", "story") if plan.get(k)}
    return json.dumps(keep, separators=(",", ":"))


def detail_messages(brief: str, style: str, plan: dict, zone: dict | None = None, notes: str = "") -> list[dict]:
    if zone:
        x0, z0, x1, z1 = zone["rect"]
        n = int(max(8, min(30, (x1 - x0) * (z1 - z0) / 45)))
        focus = (f"Dress ONLY zone '{zone['id']}' x {x0:g}..{x1:g}, z {z0:g}..{z1:g} ({zone.get('purpose', '')}): about {n} "
                 "entries, all inside it, spread over its whole area (sets of furniture, not one pile). ")
    else:
        focus = "Dress all zones: 25-60 entries. "
    return [_sys(), {"role": "user", "content":
            f"{STYLE_GUIDE[style]}\n{RULES}\n\nKITS:\n{kit_menu(brief)}\n\nBRIEF: {brief}\nPLAN: {_plan_text(plan)}\n\n"
            + ("ART-LEAD NOTES ON THE LAST RENDER (fix these): " + notes + "\n" if notes else "") +
            f"STEP 2 DETAIL PASS. {focus}Order: structure, hero props at focal points, furniture/sets, lights, story "
            "props at the story moments, dressing. Use repeats for rows. Keep 6 studs clear on the route. JSON: "
            f'{{"props": [...]}} with {PROP_FORMAT}'}]


def baseline_messages(brief: str, style: str) -> list[dict]:
    shape = PLAN_SHAPE[:-1] + ',"props":[[kit,x,z,rot,{params},n,dx,dz]]}'
    return [_sys(), {"role": "user", "content":
            f"{STYLE_GUIDE[style]}\n{RULES}\nMaterials: {MATS}\n\nKITS:\n{kit_menu(brief)}\n\nBRIEF: {brief}\n\n"
            f"Write the complete build in one JSON (zones, rooms, spawn, focal, paths and 25-60 props). {PROP_FORMAT}\n{shape}"}]


CRITIC_RUBRIC = ("Score this Roblox environment like a strict senior environment-art lead, 1-10 each (10 = portfolio): "
                 "composition (focal point, leading lines, framing, depth), scale (vs 5-stud character), lighting (mood, light "
                 "pools, contrast; not flat or murky), detail (density right; not empty, not noisy), story (intentional "
                 "details), style (consistent), color (palette/material discipline), cleanliness (no floating/clipping, no "
                 "random clutter or mismatched pieces).")

CRITIC_SHAPE = ('{"scores":{"composition":n,"scale":n,"lighting":n,"detail":n,"story":n,"style":n,"color":n,'
                '"cleanliness":n},"overall":n,"problems":[".."],"fixes":["concrete change naming prop index or position"]}')


def critic_messages(brief: str, style: str, sheet_part: dict, props_text: str, metrics: dict) -> list[dict]:
    return [{"role": "user", "content": [
        {"type": "text", "text": f"{CRITIC_RUBRIC}\n4 shots: hero (eye level from spawn), wide, detail, overview.\nBRIEF: {brief}\n"
         f"STYLE: {style}\nMEASURED: {json.dumps(metrics)}\nPROPS:\n{props_text}\nReturn JSON {CRITIC_SHAPE}, at most 6 fixes."},
        sheet_part]}]


def metric_critic_messages(brief: str, style: str, spec: dict, props_text: str, metrics: dict, facts: dict) -> list[dict]:
    head = {k: spec[k] for k in ("mood", "state", "size", "spawn", "focal")}
    head["zones"] = [[z["id"], z["rect"]] for z in spec["zones"]]
    head["rooms"] = [[r["zone"], r["h"], r["roof"], [o["side"] + ":" + o["kind"] for o in r["openings"]]] for r in spec["rooms"]]
    shots = {k: v["notes"] or ["ok exposure/contrast"] for k, v in facts.items()}
    return [_sys(), {"role": "user", "content":
            f"{CRITIC_RUBRIC}\nYou cannot see the renders; judge from the spec, the props and measured shot facts.\n"
            f"BRIEF: {brief}\nSTYLE: {style}\nSPEC: {json.dumps(head, separators=(',', ':'))}\nPROPS:\n{props_text}\n"
            f"METRICS: {json.dumps(metrics, separators=(',', ':'))}\nSHOTS: {json.dumps(shots)}\n"
            f"Return JSON {CRITIC_SHAPE}. At most 6 fixes, most impactful first: missing brief elements, empty zones, "
            "weak focal point, missing lights, clutter without intent."}]


OPS_HELP = ('ops: ["add",kit,x,z,rot,{params}] ["move",i,x,z] ["remove",i] ["params",i,{..}] ["rotate",i,deg] '
            '["mood",name] ["room",zone,"h|roof|windows|wall",value] ["door",zone,side]')


def revise_messages(brief: str, style: str, spec: dict, defects: list[str], critique: dict | None) -> list[dict]:
    head = {k: spec[k] for k in ("mood", "state", "size", "spawn", "focal")}
    head["zones"] = [[z["id"], z["rect"]] for z in spec["zones"]]
    crit = {k: critique.get(k) for k in ("problems", "fixes")} if critique else {}
    return [_sys(), {"role": "user", "content":
            f"{STYLE_GUIDE[style]}\n\nKITS:\n{kit_menu(brief, 34)}\n\nBRIEF: {brief}\nSPEC: {json.dumps(head, separators=(',', ':'))}\n"
            f"PROPS:\n{props_line(spec)}\nDEFECTS: {json.dumps(defects[:10])}\nCRITIQUE: {json.dumps(crit)}\n\n"
            f"Fix the defects and apply the useful critique fixes with few strong edits. {OPS_HELP}\nJSON: {{\"ops\": [...]}}"}]


def props_line(spec: dict, limit: int = 70) -> str:
    return " ".join(f"{i}:{p['kit']}@{p['at'][0]:g},{p['at'][1]:g}" + (f"x{p['repeat']['n']}" if p.get("repeat") else "")
                    for i, p in enumerate(spec["props"][:limit]))
