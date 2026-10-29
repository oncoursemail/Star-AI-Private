"""Compile a normalized spec into Blockbench, Java and Bedrock files plus one pixel-art texture atlas.

Outputs (all in memory; `write_outputs` saves them):
  .bbmodel (Blockbench 5 project, texture embedded), Java block/item model JSON (block/item/furniture),
  Bedrock geometry + animation JSON (mob/entity/armor), the atlas PNG.
Conventions verified against Blockbench 5.2.2's own compile (see docs/agents/blockbench-20261029.md).
"""
from __future__ import annotations

import base64
import io
import json
import uuid
from pathlib import Path

from PIL import Image

from .paint import paint_face, seed_of
from .spec import FACES, model_format

NS = uuid.UUID("6c0b6a52-4a43-4c39-9d0e-8a8bbf2b7c11")


def _uuid(*parts) -> str:
    return str(uuid.uuid5(NS, "|".join(str(p) for p in parts)))


def face_dims(size, face):
    sx, sy, sz = size
    return {"north": (sx, sy), "south": (sx, sy), "east": (sz, sy), "west": (sz, sy),
            "up": (sx, sz), "down": (sx, sz)}[face]


def _role(face):
    return "top" if face == "up" else ("bottom" if face == "down" else "side")


def _pack(rects):
    """Shelf-pack (key, w, h) into the smallest power-of-two square. Returns (size, {key: (x, y)})."""
    area = sum(w * h for _, w, h in rects)
    widest = max([w for _, w, _ in rects] + [h for _, _, h in rects] + [16])
    size = 16
    while size * size < area or size < widest:
        size *= 2
    order = sorted(rects, key=lambda r: (-r[2], -r[1], str(r[0])))
    while size <= 4096:
        pos, x, y, shelf = {}, 0, 0, 0
        ok = True
        for key, w, h in order:
            if x + w > size:
                x, y, shelf = 0, y + shelf, 0
            if y + h > size:
                ok = False
                break
            pos[key] = (x, y)
            x += w
            shelf = max(shelf, h)
        if ok:
            return size, pos
        size *= 2
    raise ValueError("texture atlas would exceed 4096 px; use fewer or smaller parts")


def build(spec: dict) -> dict:
    """spec must come from spec.normalize. Returns a dict of output documents."""
    fmt = model_format(spec["category"])
    d = spec["density"]
    mats = spec["materials"]
    by_name = {p["name"]: p for p in spec["parts"]}
    rects, pixels = [], {}
    for p in spec["parts"]:
        size = [p["to"][j] - p["from"][j] for j in range(3)]
        src = by_name.get(p.get("mirror_of"), p)
        for face in FACES:
            fw, fh = face_dims(size, face)
            if fw <= 0 or fh <= 0:
                continue
            tw, th = max(1, round(fw * d)), max(1, round(fh * d))
            decals = [x for x in p.get("decals", []) if x["face"] == face]
            pixels[(p["name"], face)] = paint_face(
                mats[p["material"]], _role(face), tw, th, density=d,
                seed=seed_of(spec["name"], src["name"], face), decals=decals)
            rects.append(((p["name"], face), tw, th))
    size, pos = _pack(rects)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for key, (x, y) in pos.items():
        grid = pixels[key]
        for yy, row in enumerate(grid):
            for xx, c in enumerate(row):
                img.putpixel((x + xx, y + yy), tuple(c))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png = buf.getvalue()
    uv = {}
    for (name, face), (x, y) in pos.items():
        g = pixels[(name, face)]
        uv[(name, face)] = [x, y, x + len(g[0]), y + len(g)]

    off = 8 if fmt == "java_block" else 0
    def shift(v):
        return [v[0] + off, v[1], v[2] + off]

    tex_uuid = _uuid(spec["name"], "texture")
    elements, groups = [], []
    for p in spec["parts"]:
        faces = {}
        for face in FACES:
            if (p["name"], face) in uv:
                faces[face] = {"uv": uv[(p["name"], face)], "texture": 0}
            else:
                faces[face] = {"uv": [0, 0, 0, 0], "texture": None}
        el = {"name": p["name"], "box_uv": False, "render_order": "default", "locked": False,
              "export": True, "scope": 0, "allow_mirror_modeling": True,
              "from": shift(p["from"]), "to": shift(p["to"]), "autouv": 0, "color": len(elements) % 8,
              "origin": shift(p["pivot"]), "faces": faces, "type": "cube",
              "uuid": _uuid(spec["name"], "cube", p["name"])}
        if p.get("inflate"):
            el["inflate"] = p["inflate"]
        if fmt == "java_block" and any(p["rotation"]):
            el["rotation"] = p["rotation"]
        elements.append(el)
    outliner = []
    if fmt == "bedrock":
        gid = {p["name"]: _uuid(spec["name"], "group", p["name"]) for p in spec["parts"]}
        for p in spec["parts"]:
            groups.append({"name": p["name"], "uuid": gid[p["name"]], "export": True, "locked": False,
                           "scope": 0, "selected": False, "visibility": True, "origin": p["pivot"],
                           "rotation": p["rotation"], "bedrock_binding": "", "color": 0, "children": [],
                           "reset": False, "shade": True, "mirror_uv": False, "autouv": 0, "isOpen": False})
        nodes = {p["name"]: {"uuid": gid[p["name"]], "isOpen": False,
                             "children": [_uuid(spec["name"], "cube", p["name"])]} for p in spec["parts"]}
        for p in spec["parts"]:
            if p.get("parent"):
                nodes[p["parent"]]["children"].append(nodes[p["name"]])
            else:
                outliner.append(nodes[p["name"]])
    else:
        outliner = [e["uuid"] for e in elements]

    data_uri = "data:image/png;base64," + base64.b64encode(png).decode()
    folder = "entity" if fmt == "bedrock" else ("item" if spec["category"] == "item" else "block")
    bb = {"meta": {"format_version": "5.0", "model_format": fmt, "box_uv": False},
          "name": spec["name"], "model_identifier": spec["name"] if fmt == "bedrock" else "",
          "visible_box": [1, 1, 0], "variable_placeholders": "", "variable_placeholder_buttons": [],
          "timeline_setups": [], "unhandled_root_fields": {},
          "resolution": {"width": size, "height": size},
          "elements": elements, "outliner": outliner,
          "textures": [{"path": "", "name": f"{spec['name']}.png", "folder": folder, "namespace": "",
                        "id": "0", "group": "", "width": size, "height": size, "uv_width": size,
                        "uv_height": size, "particle": False, "use_as_default": False,
                        "layers_enabled": False, "sync_to_project": "", "render_mode": "default",
                        "render_sides": "auto", "frame_time": 1, "frame_order_type": "loop",
                        "frame_order": "", "frame_interpolate": False, "visible": True,
                        "internal": True, "saved": True, "uuid": tex_uuid, "source": data_uri}]}
    if fmt == "bedrock":
        bb["groups"] = groups
        bb["bedrock_animation_mode"] = "entity"
        bb["animations"] = _bb_animations(spec, gid)
    out = {"format": fmt, "texture_png": png, "texture_size": size, "bbmodel": bb, "uv": uv}
    if fmt == "java_block":
        out["java_model"] = _java_model(spec, uv, size)
    else:
        out["bedrock_geometry"] = _bedrock_geo(spec, uv, size)
        if spec["animations"]:
            out["bedrock_animation"] = _bedrock_anim(spec)
    return out


def _bb_animations(spec, gid):
    anims = []
    for a in spec["animations"]:
        animators = {}
        for bone, chans in a["bones"].items():
            kfs = []
            for ch, keys in chans.items():
                for t, v in keys.items():
                    kfs.append({"channel": ch, "data_points": [{"x": str(v[0]), "y": str(v[1]), "z": str(v[2])}],
                                "uuid": _uuid(spec["name"], a["name"], bone, ch, t), "time": t, "color": -1,
                                "interpolation": "linear"})
            animators[gid[bone]] = {"name": bone, "type": "bone", "rotation_global": False,
                                    "quaternion_interpolation": False, "keyframes": kfs}
        anims.append({"uuid": _uuid(spec["name"], "anim", a["name"]),
                      "name": f"animation.{spec['name']}.{a['name']}", "loop": "loop" if a["loop"] else "once",
                      "override": False, "length": a["length"], "snapping": 24, "selected": False,
                      "saved": True, "path": "", "scope": 0, "anim_time_update": "", "blend_weight": "",
                      "start_delay": "", "loop_delay": "", "animators": animators})
    return anims


def _num(x):
    x = round(float(x), 4)
    return int(x) if x.is_integer() else x


def _java_model(spec, uv, size):
    s = 16.0 / size
    els = []
    for p in spec["parts"]:
        el = {"name": p["name"], "from": [_num(p["from"][0] + 8), _num(p["from"][1]), _num(p["from"][2] + 8)],
              "to": [_num(p["to"][0] + 8), _num(p["to"][1]), _num(p["to"][2] + 8)]}
        r = p["rotation"]
        if any(r):
            axis = max(range(3), key=lambda j: abs(r[j]))
            el["rotation"] = {"angle": _num(r[axis]), "axis": "xyz"[axis],
                              "origin": [_num(p["pivot"][0] + 8), _num(p["pivot"][1]), _num(p["pivot"][2] + 8)]}
        faces = {}
        for face in FACES:
            if (p["name"], face) in uv:
                u = uv[(p["name"], face)]
                faces[face] = {"uv": [_num(c * s) for c in u], "texture": "#0"}
        el["faces"] = faces
        els.append(el)
    span = max(max(abs(p["from"][0]), abs(p["to"][0]), abs(p["from"][2]), abs(p["to"][2])) for p in spec["parts"]) * 2
    fit = min(1.0, 16.0 / max(16.0, span, max(p["to"][1] for p in spec["parts"])))
    folder = "item" if spec["category"] == "item" else "block"
    ref = f"star:{folder}/{spec['name']}"
    display = {
        "gui": {"rotation": [30, 225, 0], "scale": [_num(0.625 * fit)] * 3},
        "ground": {"translation": [0, 3, 0], "scale": [_num(0.25 * fit)] * 3},
        "fixed": {"scale": [_num(0.5 * fit)] * 3},
        "thirdperson_righthand": {"rotation": [75, 45, 0], "translation": [0, 2.5, 0], "scale": [_num(0.375 * fit)] * 3},
        "firstperson_righthand": {"rotation": [0, 45, 0], "scale": [_num(0.4 * fit)] * 3},
        "firstperson_lefthand": {"rotation": [0, 225, 0], "scale": [_num(0.4 * fit)] * 3},
    }
    return {"credit": "Made with STAR", "texture_size": [size, size],
            "textures": {"0": ref, "particle": ref}, "elements": els, "display": display}


def _bedrock_geo(spec, uv, size):
    bones = []
    lo = [min(p["from"][j] for p in spec["parts"]) for j in range(3)]
    hi = [max(p["to"][j] for p in spec["parts"]) for j in range(3)]
    for p in spec["parts"]:
        # Bedrock files mirror X relative to Blockbench's editor space (checked against Blockbench 5.2.2)
        cube = {"origin": [_num(-p["to"][0]), _num(p["from"][1]), _num(p["from"][2])],
                "size": [_num(p["to"][j] - p["from"][j]) for j in range(3)], "uv": {}}
        if p.get("inflate"):
            cube["inflate"] = _num(p["inflate"])
        for face in FACES:
            if (p["name"], face) not in uv:
                continue
            u1, v1, u2, v2 = uv[(p["name"], face)]
            if face in ("up", "down"):
                cube["uv"][face] = {"uv": [u2, v2], "uv_size": [u1 - u2, v1 - v2]}
            else:
                cube["uv"][face] = {"uv": [u1, v1], "uv_size": [u2 - u1, v2 - v1]}
        bone = {"name": p["name"]}
        if p.get("parent"):
            bone["parent"] = p["parent"]
        bone["pivot"] = [_num(-p["pivot"][0]), _num(p["pivot"][1]), _num(p["pivot"][2])]
        r = p["rotation"]
        if any(r):
            bone["rotation"] = [_num(-r[0]), _num(-r[1]), _num(r[2])]
        bone["cubes"] = [cube]
        bones.append(bone)
    width = max(hi[0] - lo[0], hi[2] - lo[2]) / 16.0
    height = (hi[1] - lo[1]) / 16.0
    return {"format_version": "1.12.0", "minecraft:geometry": [{
        "description": {"identifier": f"geometry.{spec['name']}", "texture_width": size, "texture_height": size,
                        "visible_bounds_width": _num(max(1, round(width + 1))),
                        "visible_bounds_height": _num(max(1, round(height + 1.5, 1))),
                        "visible_bounds_offset": [0, _num(round(height / 2 + 0.25, 2)), 0]},
        "bones": bones}]}


def _bedrock_anim(spec):
    out = {}
    for a in spec["animations"]:
        bones = {}
        for bone, chans in a["bones"].items():
            b = {}
            for ch, keys in chans.items():
                conv = {}
                for t, v in keys.items():
                    if ch == "rotation":
                        vv = [-v[0], -v[1], v[2]]
                    elif ch == "position":
                        vv = [-v[0], v[1], v[2]]
                    else:
                        vv = list(v)
                    conv[f"{float(t):.4g}" if float(t) % 1 else f"{float(t):.1f}"] = [_num(x) for x in vv]
                b[ch] = conv
            bones[bone] = b
        entry = {"loop": True} if a["loop"] else {}
        entry["animation_length"] = _num(a["length"])
        entry["bones"] = bones
        out[f"animation.{spec['name']}.{a['name']}"] = entry
    return {"format_version": "1.8.0", "animations": out}


def write_outputs(spec: dict, built: dict, out_dir, *, pack_version: str | None = "26.3") -> dict:
    """Write every output file under out_dir (created). Returns {kind: path}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = spec["name"]
    paths = {}
    def put(rel, data):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (dict, list)):
            p.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        else:
            p.write_bytes(data)
        return str(p)
    paths["spec"] = put(f"{name}.spec.json", spec)
    paths["bbmodel"] = put(f"{name}.bbmodel", built["bbmodel"])
    paths["texture"] = put(f"{name}.png", built["texture_png"])
    if built["format"] == "java_block":
        paths["java_model"] = put(f"{name}.java.json", built["java_model"])
        if pack_version:
            from ..minecraft_assets import RESOURCE_FORMATS
            fmt = RESOURCE_FORMATS[pack_version]
            folder = "item" if spec["category"] == "item" else "block"
            pack = {"pack": {"description": f"STAR model: {name}"}}
            if fmt[0] >= 65:
                pack["pack"]["min_format"] = list(fmt)
                pack["pack"]["max_format"] = list(fmt)
            else:
                pack["pack"]["pack_format"] = fmt[0]
            put("resourcepack/pack.mcmeta", pack)
            put(f"resourcepack/assets/star/models/{folder}/{name}.json", built["java_model"])
            put(f"resourcepack/assets/star/textures/{folder}/{name}.png", built["texture_png"])
            put(f"resourcepack/assets/star/items/{name}.json",
                {"model": {"type": "minecraft:model", "model": f"star:{folder}/{name}"}})
            paths["resourcepack"] = str(out / "resourcepack")
    else:
        paths["bedrock_geometry"] = put(f"{name}.geo.json", built["bedrock_geometry"])
        if "bedrock_animation" in built:
            paths["bedrock_animation"] = put(f"{name}.animation.json", built["bedrock_animation"])
    return paths
