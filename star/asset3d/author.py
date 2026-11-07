"""Prompts that turn a brief into an asset spec (pipeline), a revised spec (critique loop) or a baseline spec."""
from __future__ import annotations

import json

from . import llm
from .spec import MATERIALS, SpecError, budget, ground, prepare, validate_baseline

GRAMMAR = f"""You design game-ready 3D props as JSON for a trusted Blender builder. Units are METRES.
Axes: +X = front (muzzle, nose, blade tip, the side a user faces), Y = width (+Y = left), +Z = up.

JSON shape:
{{"name": str, "category": "weapon|vehicle|furniture|prop|accessory", "style": "pbr|stylized|lowpoly|roblox",
 "dims": [length_x, width_y, height_z], "parts": [part, ...]}}

LAYOUT: do not compute coordinates. The FIRST part is the main body (no attach). Every other part says where it sits
on a part listed BEFORE it:
 "attach": {{"to": "<parent id>", "side": "front|back|top|bottom|left|right|center", "u": -1..1, "v": -1..1}}
 side = which face of the parent it sits on (center = inside the parent, centred).
 u, v = position across that face: for top/bottom/left/right u runs back(-1) -> front(+1); for front/back u runs
 right(-1) -> left(+1). v: for front/back/left/right v runs bottom(-1) -> top(+1); for top/bottom v runs right(-1) ->
 left(+1). 0 = centred. Parts overlap their parent slightly by themselves. Optional "offset": [dx,dy,dz] metres.

Every part: "id" (short unique), "type", "attach" (except the first), optional "rot": [deg_x, deg_y, deg_z],
"mat" (one of: {", ".join(MATERIALS)}), optional "color": "#rrggbb", optional "mirror_y": true (adds a copy on the
other side: attach the original on the left side), optional "bevel" (metres; omit for the style default), optional
"count": n + "step": [dx,dy,dz] (repeats the part: bolts, rail slots, slats).
Types and their size fields:
- box: "size": [x,y,z]; optional "taper": [sx, sy] scales the top face (wedges, sloped hoods, trapezoids).
- cylinder: "radius", "depth" = length along "axis": "x"|"y"|"z".
- cone: like cylinder plus "radius2" (radius at the +axis end; 0 = point).
- sphere: "radius", optional "scale": [sx,sy,sz] (ellipsoids, domes).
- torus: "radius" (ring), "tube" (thickness radius), "axis" = the axle (tires on a car: axis "y").
- profile: "points": [[x,z], ...] side-view outline (X-Z plane), 6-30 points, must not cross itself, "thickness"
  along Y. Best for silhouettes: stocks, grips, blades, frames, fenders, chair backs, handles.
- lathe: "points": [[position_along_axis, radius], ...] revolved around "axis" (radius = distance from the axis,
  usually small): barrels, bottles, knobs, scopes, cans, hubs.
- tube: "points": [[x,y,z], ...] path with "radius": pipes, bent handles, roll bars, frames, straps.
Details:
- "cuts": [{{"shape": "box"|"cylinder", "size": [x,y,z] | "radius"+"depth"+"axis", "side": face of THIS part,
  "u", "v", "count": n, "step": [dx,dy,dz]}}]: holes, slots, vents, grooves, serrations (the cut goes half its
  size deep; count + step repeats it).
- "seams": [{{"axis": "x"|"y"|"z", "at": [-1..1 positions along the part]}}]: thin panel lines around the part.

Quality rules (portfolio-level):
1. Real-world sizes for every part. Big masses first, then secondary parts, then small details. 15-40 parts.
2. Readable silhouette from the side and 3/4 views; vary part sizes; avoid a row of equal blocks.
3. Use profile/lathe/tube for anything that is not a plain block; cuts and seams for panel lines, vents, grips.
4. Accent colours on a few small parts only. Realistic materials (metal, rubber tires, wood only for wood).
5. Orientation: the axis of a round part is its long direction: an upright barrel/can/bottle/lamp post = axis "z";
   a gun barrel/scope/flashlight = axis "x"; wheels and tires = axis "y". Rings or bands around a round body = torus
   with the SAME axis, attach side "center" + "offset" along that axis. Legs under a top: side "bottom" with u/v near
   +-0.9 (corners). Things standing on the ground have nothing below the main body except legs/wheels.
"""

STYLE_NOTES = {
    "pbr": "Style pbr: realistic PBR, subtle wear; realistic colours; fine details (screws, seams, vents) matter.",
    "stylized": "Style stylized: chunky exaggerated shapes, thicker parts, bigger bevels, saturated readable colours, "
                "fewer but bolder details, coloured accent trims.",
    "lowpoly": "Style lowpoly: few simple facets, clean flat colours, 8-20 parts, no tiny details, no cuts or seams.",
    "roblox": "Style roblox: clean stylized look that reads well at game distance, chunky shapes, Roblox limits "
              "(one mesh <= 20k triangles, 1024 px textures): 12-30 parts, avoid tiny details.",
}

EXAMPLE = {"name": "Tactical flashlight", "category": "prop", "style": "pbr", "dims": [0.16, 0.04, 0.04],
           "parts": [
               {"id": "body", "type": "lathe", "axis": "x", "mat": "anodized", "color": "#2a2c30",
                "points": [[-0.08, 0.0], [-0.08, 0.013], [-0.075, 0.0135], [0.02, 0.0135], [0.045, 0.019],
                           [0.075, 0.019], [0.075, 0.0]],
                "cuts": [{"shape": "box", "size": [0.004, 0.04, 0.003], "side": "top", "u": -0.4, "count": 8,
                          "step": [0.007, 0, 0]}],
                "seams": [{"axis": "x", "at": [-0.8, 0.3]}]},
               {"id": "lens", "type": "cylinder", "axis": "x", "radius": 0.016, "depth": 0.004,
                "attach": {"to": "body", "side": "front"}, "mat": "emissive", "color": "#fff3d0"},
               {"id": "bezel", "type": "torus", "axis": "x", "radius": 0.0175, "tube": 0.002,
                "attach": {"to": "body", "side": "front"}, "mat": "bare_metal"},
               {"id": "switch", "type": "cylinder", "axis": "x", "radius": 0.009, "depth": 0.006,
                "attach": {"to": "body", "side": "back"}, "mat": "rubber"},
               {"id": "clip", "type": "box", "size": [0.05, 0.003, 0.006], "taper": [0.8, 1.0],
                "attach": {"to": "body", "side": "left", "u": -0.5, "v": 0.3}, "mat": "bare_metal"}]}


def _brief_msg(brief: dict) -> str:
    b = budget({"style": brief["style"], "category": brief["category"]})
    return (f"Brief: {brief['brief']}\nCategory: {brief['category']}. Style: {brief['style']}. "
            f"{STYLE_NOTES[brief['style']]}\nTriangle budget for the whole asset: about {b['tris']}.\n"
            "Think about the real object's parts and sizes first (silently), then answer with the JSON only.")


def _system() -> str:
    return GRAMMAR + "\nExample of the format (a different object):\n" + json.dumps(EXAMPLE)


def write_spec(brief: dict, model: str = "litha", tries: int = 3) -> tuple[dict, dict]:
    msgs = [{"role": "system", "content": _system()}, {"role": "user", "content": _brief_msg(brief)}]
    return _ask_spec(msgs, brief, model, tries)


def _ask_spec(msgs, brief, model, tries, max_tokens=2300, patch_base=None):
    info = {"calls": []}
    last = ""
    for _ in range(tries):
        # the GPU nodes have a 4096-token context: prompt + answer must fit or the router falls back to the brain
        est = sum(llm.estimate_tokens(m["content"]) for m in msgs if isinstance(m["content"], str)) + 40
        if est > 3500:  # keep only the first and the last exchange
            msgs = msgs[:2] + msgs[-2:] if len(msgs) > 4 else msgs[:2]
            est = sum(llm.estimate_tokens(m["content"]) for m in msgs if isinstance(m["content"], str)) + 40
        try:
            text, meta = llm.chat(model, msgs, max_tokens=max(400, min(max_tokens, 4000 - est)), temperature=0.4,
                                  json_mode=True)
        except ValueError as e:  # HTTP 400 from the node: too long
            info["calls"].append({"error": str(e)[:200]})
            last = str(e)
            msgs = msgs[:2]
            continue
        info["calls"].append(meta)
        try:
            raw = llm.extract_json(text)
            if patch_base is not None:
                raw = apply_patch(patch_base, raw)
            raw["category"], raw["style"] = brief["category"], brief["style"]
            return ground(prepare(raw)), {**info, "raw": raw}
        except (ValueError, SpecError) as e:
            last = str(e)
            if meta.get("finish") == "length":  # cut off: a shorter design fits the 4096-token context
                last = "the answer was cut off (too long)"
                msgs = msgs[:2] + [{"role": "user", "content": "Your last answer was too long and got cut off. Send a "
                                    "shorter design: at most 22 parts, numbers with at most 3 decimals."}]
                continue
            msgs = msgs + [{"role": "assistant", "content": text[:6000]},
                           {"role": "user", "content": f"That JSON was rejected: {last}. Send the corrected full JSON."}]
    raise SpecError(f"model could not write a valid spec: {last}")


def compact(raw: dict) -> str:
    def r(v):
        if isinstance(v, float):
            return round(v, 3)
        if isinstance(v, list):
            return [r(x) for x in v]
        if isinstance(v, dict):
            return {k: r(x) for k, x in v.items()}
        return v
    return json.dumps(r(raw), separators=(",", ":"))


def apply_patch(raw: dict, patch: dict) -> dict:
    """{"edit": [{"id", "set": {...}}], "add": [part], "remove": [id], "dims": [...]} applied to a copy of raw.
    A reply that is a full spec (has "parts") replaces it instead."""
    if isinstance(patch.get("parts"), list) and not any(k in patch for k in ("edit", "add", "remove")):
        return patch
    out = json.loads(json.dumps(raw))
    parts = out.get("parts", [])
    rm = {str(x) for x in patch.get("remove", []) if isinstance(x, (str, int))}
    parts = [p for p in parts if str(p.get("id")) not in rm]
    by_id = {str(p.get("id")): p for p in parts}
    for e in patch.get("edit", []) or []:
        if isinstance(e, dict) and str(e.get("id")) in by_id and isinstance(e.get("set"), dict):
            for k, v in e["set"].items():
                if k != "id":
                    by_id[str(e["id"])][k] = v
    for a in patch.get("add", []) or []:
        if isinstance(a, dict) and a.get("type"):
            if str(a.get("id")) in by_id:
                a = dict(a, id=f"{a.get('id')}_{len(parts)}")
            parts.append(a)
    out["parts"] = parts
    if isinstance(patch.get("dims"), list):
        out["dims"] = patch["dims"]
    return out


PATCH_FORMAT = """Answer with a JSON patch only (not the whole design):
{"edit": [{"id": "<part id>", "set": {<fields to change, e.g. "pos": [..], "size": [..], "points": [..]>}}],
 "add": [<new full parts>], "remove": ["<part id>"], "dims": [<new overall dims, optional>]}"""


def revise_spec(brief: dict, raw: dict, qa_notes: list[str], critique: dict, model: str = "litha",
                tries: int = 3) -> tuple[dict, dict]:
    issues = critique.get("issues", [])[:6] if isinstance(critique, dict) else []
    lines = [f"- {i.get('part', '?')}: {i.get('problem', '')} -> {i.get('fix', '')}"[:300] for i in issues
             if isinstance(i, dict)]
    msg = (_brief_msg(brief).split("Think about")[0] +
           "\nYour current design:\n" + compact(raw) +
           f"\n\nAn art director reviewed studio renders of it (score {critique.get('overall', '?')}/10). Notes:\n" +
           ("\n".join(lines) or "- none") + "\n\nAutomatic checks:\n" +
           ("\n".join(f"- {n}" for n in qa_notes) or "- all passed") +
           "\n\nFix every note (move/resize/add/remove parts), keep what already works.\n" + PATCH_FORMAT)
    msgs = [{"role": "system", "content": GRAMMAR}, {"role": "user", "content": msg}]
    return _ask_spec(msgs, brief, model, tries, max_tokens=1100, patch_base=raw)


BASELINE_SYSTEM = """You build simple 3D models for Blender from primitives. Units are metres; +X front, +Z up.
Answer with JSON only: {"name": str, "parts": [{"type": "cube"|"cylinder"|"sphere"|"cone", "size": [x,y,z],
"pos": [x,y,z], "rot": [deg_x,deg_y,deg_z], "color": "#rrggbb", "metallic": 0-1, "roughness": 0-1}, ...]}
(cylinder/cone size: [diameter_x, diameter_y, height_z] along Z before rotation)."""


def write_baseline(brief: dict, model: str = "litha", tries: int = 3) -> tuple[dict, dict]:
    msgs = [{"role": "system", "content": BASELINE_SYSTEM},
            {"role": "user", "content": f"Make this game asset: {brief['brief']} (style: {brief['style']})."}]
    info = {"calls": []}
    last = ""
    for _ in range(tries):
        text, meta = llm.chat(model, msgs, max_tokens=4000, temperature=0.4, json_mode=True)
        info["calls"].append(meta)
        try:
            return validate_baseline(llm.extract_json(text)), info
        except (ValueError, SpecError) as e:
            last = str(e)
            msgs = msgs + [{"role": "assistant", "content": text[:4000]},
                           {"role": "user", "content": f"Rejected: {last}. Send the corrected full JSON."}]
    raise SpecError(f"baseline spec failed: {last}")
