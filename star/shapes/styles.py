"""Style packs for 3D templates: the same template geometry, rendered in a style picked from the brief.

The geometry side of a style lives in the template Kit (detail level, chunkiness, cuts) and the builder side in
star.asset3d.spec.STYLE / build_bpy.STYLE (bevel, segments, subdivision, shading, material recipe). This module only
holds the data that maps a brief to a style and the one-line description shown to a planner.
"""
from __future__ import annotations

import re

STYLE_PACKS = {  # checked in this order: the first style whose keywords appear in the brief wins
    "roblox": {"keywords": ("roblox",),
               "doc": "Roblox-ready: chunky parts, 1024 px texture, mesh under 20k triangles"},
    "lowpoly": {"keywords": ("low-poly", "low poly", "lowpoly", "faceted", "flat-shaded", "flat shaded", "polygonal"),
                "doc": "low poly: few faces, flat shading, flat colours tinted by face direction"},
    "highpoly": {"keywords": ("high-poly", "high poly", "highpoly", "subd", "subdivision", "hero asset", "cinematic",
                              "sculpted", "smooth bevelled", "smooth beveled"),
                 "doc": "high poly: bevelled support loops + subdivision + weighted normals, edge wear"},
    "stylized": {"keywords": ("stylized", "stylised", "cartoon", "hand-painted", "hand painted", "toon", "painterly",
                              "chibi", "cute", "chunky"),
                 "doc": "stylized: chunky shapes, painted gradient, edge highlights, soft AO"},
    "pbr": {"keywords": ("realistic", "pbr", "photoreal", "aaa", "real-world", "game-ready", "game ready"),
            "doc": "realistic PBR: real proportions, metal/roughness maps, fine detail and wear"},
}


def style_from_brief(brief: str, default: str = "pbr") -> str:
    text = brief.lower() if isinstance(brief, str) else ""
    for style, pack in STYLE_PACKS.items():
        if any(re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text) for k in pack["keywords"]):
            return style
    return default
