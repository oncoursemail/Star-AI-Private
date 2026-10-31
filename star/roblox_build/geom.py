"""Parts, styles, palettes and materials for STAR's Roblox environment builder.

A part is a plain dict (see `part`); kits return lists of them, the compiler turns them into Luau. Everything is
anchored. Rotations are Roblox CFrame.Angles(rx, ry, rz) in degrees (matrix Rx * Ry * Rz).
"""
from __future__ import annotations

import colorsys
import math
import random

STYLES = ("stud", "lowpoly", "midpoly", "highpoly")
SHAPES = {"B": "Block", "W": "Wedge", "CW": "CornerWedge", "C": "Cylinder", "S": "Ball", "M": "MeshPart"}

# Semantic material -> Enum.Material per style. stud/lowpoly collapse to plastic on purpose (style discipline).
_REAL = {
    "stone": "Slate", "cobble": "Cobblestone", "brick": "Brick", "wood": "Wood", "plank": "WoodPlanks",
    "metal": "Metal", "rust": "CorrodedMetal", "glass": "Glass", "fabric": "Fabric", "plaster": "Plaster",
    "tile": "CeramicTiles", "marble": "Marble", "concrete": "Concrete", "grass": "Grass", "sand": "Sand",
    "water": "Glass", "foliage": "LeafyGrass", "neon": "Neon", "snow": "Snow", "rock": "Rock",
    "leather": "Leather", "paper": "SmoothPlastic", "ceramic": "SmoothPlastic", "carpet": "Carpet",
    "roof": "RoofShingles", "clay": "ClayRoofTiles", "asphalt": "Asphalt", "paint": "SmoothPlastic",
    "plastic": "SmoothPlastic", "ground": "Ground", "pebble": "Pebble", "granite": "Granite",
    "sandstone": "Sandstone", "ice": "Ice", "mud": "Mud", "cardboard": "Cardboard",
}
MATERIALS = tuple(sorted(_REAL))

# Natural colour per semantic material (RGB 0-255), per style family. Kits use these unless a palette role is asked.
_NATURAL = {
    "stone": (128, 126, 120), "cobble": (120, 116, 108), "brick": (150, 82, 64), "wood": (122, 84, 52),
    "plank": (140, 100, 64), "metal": (130, 134, 140), "rust": (120, 78, 52), "glass": (190, 220, 235),
    "fabric": (150, 60, 55), "plaster": (222, 212, 192), "tile": (226, 222, 212), "marble": (232, 230, 224),
    "concrete": (150, 150, 146), "grass": (98, 140, 70), "sand": (214, 196, 150), "water": (70, 130, 160),
    "foliage": (78, 124, 62), "neon": (255, 200, 120), "snow": (240, 244, 248), "rock": (112, 108, 102),
    "leather": (96, 58, 40), "paper": (236, 228, 206), "ceramic": (236, 232, 222), "carpet": (120, 40, 44),
    "roof": (84, 70, 66), "clay": (170, 90, 62), "asphalt": (60, 60, 62), "paint": (200, 200, 200),
    "plastic": (200, 200, 200), "ground": (110, 90, 66), "pebble": (150, 144, 134), "granite": (140, 136, 132),
    "sandstone": (200, 170, 130), "ice": (200, 230, 245), "mud": (90, 70, 50), "cardboard": (176, 140, 96),
}

# Classic Roblox BrickColor palette for the stud style (name, RGB). Stud builds snap every colour to this list.
BRICK = [
    ("White", (242, 243, 243)), ("Light stone grey", (229, 228, 223)), ("Medium stone grey", (163, 162, 165)),
    ("Dark stone grey", (99, 95, 98)), ("Black", (27, 42, 53)), ("Bright red", (196, 40, 28)),
    ("Dusty Rose", (163, 75, 75)), ("Brick yellow", (215, 197, 154)), ("Nougat", (204, 142, 105)),
    ("Reddish brown", (105, 64, 40)), ("Brown", (124, 92, 70)), ("Dark orange", (160, 95, 53)),
    ("Bright orange", (218, 133, 65)), ("Bright yellow", (245, 205, 48)), ("Cool yellow", (253, 234, 141)),
    ("Bright green", (75, 151, 75)), ("Earth green", (39, 70, 45)), ("Sand green", (120, 144, 130)),
    ("Medium green", (161, 196, 140)), ("Bright blue", (13, 105, 172)), ("Medium blue", (110, 153, 202)),
    ("Sand blue", (116, 134, 157)), ("Pastel blue", (128, 187, 220)), ("Bright violet", (107, 50, 124)),
    ("Lavender", (140, 91, 159)), ("Teal", (18, 238, 212)), ("Pine Cone", (108, 88, 75)),
    ("Burnt Sienna", (143, 76, 42)), ("Salmon", (255, 148, 148)), ("Wheat", (241, 231, 199)),
]

LIGHT_KINDS = ("point", "spot", "surface")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def hex_rgb(text: str) -> tuple[int, int, int] | None:
    if not isinstance(text, str):
        return None
    text = text.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def mix(a, b, t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def shade(color, factor: float):
    """factor < 1 darkens, > 1 lightens (towards white)."""
    if factor <= 1:
        return tuple(int(round(c * factor)) for c in color)
    return mix(color, (255, 255, 255), clamp(factor - 1, 0, 1))


def nearest_brick(color) -> tuple[int, int, int]:
    return min(BRICK, key=lambda item: sum((item[1][i] - color[i]) ** 2 for i in range(3)))[1]


def _saturate(color, amount: float):
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in color))
    r, g, b = colorsys.hls_to_rgb(h, l, clamp(s * amount, 0, 1))
    return (int(r * 255), int(g * 255), int(b * 255))


def rot_matrix(rx: float, ry: float, rz: float):
    """Rx * Ry * Rz (Roblox CFrame.Angles order)."""
    x, y, z = math.radians(rx), math.radians(ry), math.radians(rz)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rxm = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    rym = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    rzm = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))

    def mul(a, b):
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return mul(mul(rxm, rym), rzm)


def aabb(p: dict) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """World axis-aligned bounds of a part (exact for boxes, a box bound for the other shapes)."""
    sx, sy, sz = (v / 2 for v in p["z"])
    m = rot_matrix(*p.get("r", (0, 0, 0)))
    ext = [abs(m[i][0]) * sx + abs(m[i][1]) * sy + abs(m[i][2]) * sz for i in range(3)]
    c = p["p"]
    return (tuple(c[i] - ext[i] for i in range(3)), tuple(c[i] + ext[i] for i in range(3)))  # type: ignore[return-value]


def axis_aligned(p: dict) -> bool:
    return all(abs(((a % 90) + 90) % 90) < 1e-6 or abs(((a % 90) + 90) % 90 - 90) < 1e-6 for a in p.get("r", (0, 0, 0)))


class Ctx:
    """Style, palette, mood and a seeded RNG shared by the kits of one build."""

    def __init__(self, style: str, palette: dict | None = None, *, seed: int = 7, state: str = "worn"):
        if style not in STYLES:
            raise ValueError(f"style must be one of {STYLES}")
        self.style, self.state, self.rng = style, state, random.Random(seed)
        pal = palette or {}
        self.palette = {}
        defaults = {"primary": (200, 190, 170), "secondary": (110, 80, 60), "accent": (180, 60, 50), "trim": (70, 60, 55)}
        for role, fallback in defaults.items():
            got = hex_rgb(pal.get(role, "")) if isinstance(pal, dict) else None
            self.palette[role] = self.tone(got or fallback)
        self.parts_made = 0

    # --- colour and material discipline
    def tone(self, color):
        if self.style == "stud":
            return nearest_brick(color)
        if self.style == "lowpoly":
            return _saturate(color, 1.15)
        return tuple(int(c) for c in color)

    def color(self, material: str = "", role: str = "", vary: float = 0.0):
        base = self.palette.get(role) if role else None
        if base is None:
            base = _NATURAL.get(material, (180, 180, 180))
        if self.state == "abandoned" and material not in ("neon", "glass", "water"):
            base = mix(base, (90, 86, 80), 0.25)
        if vary and self.style != "stud":
            f = 1 + self.rng.uniform(-vary, vary)
            base = shade(base, f)
        return self.tone(base)

    def material(self, semantic: str) -> str:
        if semantic == "neon":
            return "Neon"
        if semantic in ("glass", "water", "ice") and self.style in ("stud", "lowpoly"):
            return "Glass" if semantic != "water" else "SmoothPlastic"
        if self.style == "stud":
            return "Plastic"
        if self.style == "lowpoly":
            return "SmoothPlastic"
        real = _REAL.get(semantic, "SmoothPlastic")
        if self.state == "abandoned" and real == "Metal":
            return "CorrodedMetal"
        return real

    def detail(self) -> int:
        """How many segments round things get: the visible difference between the poly styles."""
        return {"stud": 6, "lowpoly": 6, "midpoly": 10, "highpoly": 18}[self.style]

    def snap(self, value: float) -> float:
        return round(value) if self.style == "stud" else value


def part(ctx: Ctx, shape: str, size, pos, *, mat: str = "plastic", role: str = "", color=None, rot=(0, 0, 0),
         t: float = 0.0, collide: bool = True, name: str = "", vary: float = 0.0, light: dict | None = None,
         studs: bool | None = None, cast: bool = True) -> dict:
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape}")
    size = [max(0.05, float(v)) for v in size]
    out = {"s": shape, "z": [round(v, 3) for v in size], "p": [round(float(v), 3) for v in pos],
           "c": list(ctx.tone(color) if color is not None else ctx.color(mat, role, vary)),
           "m": ctx.material(mat), "sem": mat, "cc": bool(collide)}
    if any(rot):
        out["r"] = [round(float(v), 3) for v in rot]
    if mat in ("glass",) and not t:
        t = 0.55
    if mat == "water" and not t:
        t = 0.3
    if t:
        out["t"] = round(clamp(t, 0, 1), 3)
    if name:
        out["n"] = name
    if light:
        out["light"] = light
    if not cast:
        out["cast"] = False
    want_studs = (ctx.style == "stud") if studs is None else studs
    if want_studs and shape in ("B", "W") and out["m"] == "Plastic":
        out["studs"] = True
    ctx.parts_made += 1
    return out


def light(kind: str = "point", color=(255, 200, 140), brightness: float = 1.5, range_: float = 16, angle: float = 70,
          face: str = "Bottom", shadows: bool = True) -> dict:
    if kind not in LIGHT_KINDS:
        raise ValueError("light kind")
    return {"k": kind, "c": list(color), "b": round(brightness, 2), "r": round(clamp(range_, 2, 60), 1),
            "a": round(clamp(angle, 5, 180), 1), "f": face, "sh": bool(shadows)}


def transform(parts: list[dict], at, yaw: float = 0.0) -> list[dict]:
    """Rotate kit-local parts by yaw (degrees, about +Y) and move them to `at` (x, y, z)."""
    if not yaw:
        for p in parts:
            p["p"] = [round(p["p"][0] + at[0], 3), round(p["p"][1] + at[1], 3), round(p["p"][2] + at[2], 3)]
        return parts
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    for p in parts:
        x, y, z = p["p"]
        p["p"] = [round(x * c + z * s + at[0], 3), round(y + at[1], 3), round(-x * s + z * c + at[2], 3)]
        r = p.get("r", [0, 0, 0])
        if not any(r):
            p["r"] = [0, round(yaw, 3), 0]
        elif abs(r[0]) < 1e-9 and abs(r[2]) < 1e-9:
            p["r"] = [0, round(r[1] + yaw, 3), 0]
        else:
            # General case: world = Ry(yaw) * R_local; express back as Angles(rx, ry, rz).
            m = _mul(rot_matrix(0, yaw, 0), rot_matrix(*r))
            p["r"] = list(_angles(m))
    return parts


def _mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _angles(m) -> tuple[float, float, float]:
    """Inverse of rot_matrix (Rx * Ry * Rz)."""
    sy = clamp(m[0][2], -1, 1)
    y = math.asin(sy)
    if abs(sy) < 0.99999:
        x = math.atan2(-m[1][2], m[2][2])
        z = math.atan2(-m[0][1], m[0][0])
    else:
        x = math.atan2(m[2][1], m[1][1])
        z = 0.0
    return (round(math.degrees(x), 3), round(math.degrees(y), 3), round(math.degrees(z), 3))


def lathe(ctx: Ctx, profile, base, *, segments: int = 0, **kw) -> dict:
    """A smooth surface of revolution (EditableMesh -> MeshPart in Studio, no asset upload). profile: [(radius, y), ...]
    from bottom to top in studs, relative to `base` (x, y, z of the bottom centre). Used by the high-poly style."""
    pts = [(max(0.0, float(r)), float(y)) for r, y in profile]
    if len(pts) < 2:
        raise ValueError("lathe needs 2+ profile points")
    rmax = max(r for r, _ in pts) or 0.1
    y0, y1 = min(y for _, y in pts), max(y for _, y in pts)
    seg = segments or max(12, ctx.detail() + 6)
    p = part(ctx, "M", (2 * rmax, max(0.05, y1 - y0), 2 * rmax), (base[0], base[1] + (y0 + y1) / 2, base[2]), **kw)
    p["mesh"] = {"lathe": [[round(r, 3), round(y - (y0 + y1) / 2, 3)] for r, y in pts], "seg": int(seg)}
    return p
