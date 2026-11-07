"""Deterministic art-direction rules measured against the 10-29 blind eval defects.

- kit relevance: whole-word brief matching with stopwords, theme gating and landmark caps (a lighthouse or a subway
  car only appears when the brief asks for it; the old substring match put them in almost every scene);
- room fitting: rooms shrink towards their furniture when the floor is mostly empty (big sparse rooms);
- framing scatter: outdoor maps get vegetation/rock clusters in an edge band, denser at the edge (density gradient);
- night dressing: lamp posts / lanterns along paths, warm windows; mood -> one of the measured lighting presets.
"""
from __future__ import annotations

import copy
import math
import random
import re

from . import kits, scene

STOP = frozenset("""a an and the of in on at to for with by from into onto over under near behind around between
some few small big large tiny huge little long tall short wide one two three four five six seven eight nine ten
is are be it its this that there their his her our your as or but not no all each every very more most less up
down out off back front side end middle centre center top bottom left right new old style map scene game area
room hall place build level full rows row set sets lots lot""".split())

# theme -> words in a brief that switch it on. Kits tagged with a theme are only offered when the theme is on
# (or the kit's own name is in the brief).
THEMES = {
    "coast": {"fish", "fishing", "lake", "dock", "pier", "harbor", "harbour", "sea", "boat", "rowboat", "lighthouse",
              "bait", "shore", "coast", "port", "marina", "ocean", "buoy"},
    "beach": {"beach", "tropical", "palm", "umbrella", "towel", "lifeguard", "sandcastle", "surf", "seaside"},
    "museum": {"museum", "exhibit", "fossil", "dinosaur", "dino", "skeleton", "gallery", "plaque"},
    "urban": {"subway", "metro", "train", "underground", "turnstile", "turnstiles", "vending", "city", "street"},
    "obby": {"obby", "parkour", "checkpoint", "arena", "course", "spawn", "finish", "kill", "spinner"},
    "camp": {"camp", "camping", "tent", "campfire", "cabin", "woods", "log", "logs", "porch", "forest"},
    "winter": {"snow", "snowy", "winter", "frozen", "ice", "christmas", "snowman"},
    "japanese": {"japanese", "japan", "tea", "teahouse", "koi", "torii", "bamboo", "shoji", "zen", "cherry",
                 "sakura", "screens"},
    "hospital": {"hospital", "ward", "clinic", "nurse", "medical", "doctor", "iv", "infirmary"},
    "library": {"library", "book", "books", "bookshop", "bookstore", "bookcase", "bookcases", "reading", "globe",
                "lectern", "study"},
    "themepark": {"theme", "carnival", "fair", "funfair", "circus", "carousel", "amusement", "ride", "ticket",
                  "ferris"},
    "aquarium": {"aquarium", "tank", "tanks", "underwater", "coral", "reef", "algae", "tunnel"},
}

# big single-purpose set pieces: never more than LANDMARK_CAP copies, and only when the brief names them
LANDMARKS = {
    "lighthouse": {"lighthouse"}, "subway_car": {"subway", "train", "metro", "carriage"},
    "ferris_wheel": {"ferris"}, "carousel": {"carousel", "merry"}, "park_arch_gate": {"gate", "entrance", "arch"},
    "torii_gate": {"torii"}, "dino_skeleton": {"dinosaur", "dino", "skeleton", "fossil"},
    "tunnel_tank": {"tunnel"}, "lifeguard_tower": {"lifeguard"}, "finish_pad": {"finish"},
    "bait_shop_stall": {"bait", "tackle"}, "ticket_booth": {"ticket", "booth"}, "arched_bridge": {"bridge"},
    "koi_pond_edge": {"koi"}, "cabin_porch": {"cabin", "porch"}, "striped_tent": {"circus", "fair", "carnival", "striped"},
}
LANDMARK_CAP = {"cabin_porch": 4, "striped_tent": 3, "ticket_booth": 2}
BIG_KIT_AREA = 120   # footprint area (studs^2) above which a kit is a set piece: at most BIG_KIT_CAP copies
BIG_KIT_CAP = 3


def terms(brief: str) -> set[str]:
    """Content words of a brief plus a naive singular form."""
    words = {w for w in re.findall(r"[a-z]+", (brief or "").lower()) if len(w) >= 2 and w not in STOP}
    out = set(words)
    for w in words:
        if w.endswith("ies") and len(w) > 4:
            out.add(w[:-3] + "y")
        elif w.endswith("es") and len(w) > 4 and w[-3] in "sxzh":
            out.add(w[:-2])
        elif w.endswith("s") and len(w) > 3:
            out.add(w[:-1])
    return out


def themes_on(brief: str) -> set[str]:
    t = terms(brief)
    return {name for name, words in THEMES.items() if t & words}


def kit_words(name: str) -> set[str]:
    info = kits.KITS[name]
    return terms(name.replace("_", " ") + " " + info["summary"].split("(")[0])


def kit_allowed(name: str, brief: str, on: set[str] | None = None) -> bool:
    """Theme gate + landmark gate. Untagged / generic kits are always allowed."""
    t = terms(brief)
    on = themes_on(brief) if on is None else on
    if name in LANDMARKS and not (t & LANDMARKS[name]):
        return False
    themed = [tag for tag in kits.KITS[name].get("tags", ()) if tag in THEMES]
    if themed and not (set(themed) & on) and not terms(name.replace("_", " ")) <= t:   # all name words named
        return False
    return True


def kit_score(name: str, brief: str) -> int:
    t = terms(brief)
    name_hits = len(t & terms(name.replace("_", " ")))
    summary_hits = len(t & kit_words(name))
    return name_hits * 10 + summary_hits * 3


def cohere(spec: dict, brief: str) -> tuple[dict, list[str]]:
    """Drop off-theme kits and cap landmark copies (keeps the first ones the model placed)."""
    spec = copy.deepcopy(spec)
    on = themes_on(brief)
    log: list[str] = []
    counts: dict[str, int] = {}
    keep = []
    for p in spec["props"]:
        name = p["kit"]
        if not kit_allowed(name, brief, on):
            log.append(f"dropped off-brief {name}")
            continue
        fw, fd = kits.KITS[name]["footprint"]
        big = fw * fd >= BIG_KIT_AREA and name not in ("water", "cliff", "platform", "rug")
        if name in LANDMARKS or big:
            cap = LANDMARK_CAP.get(name, 1 if name in LANDMARKS else BIG_KIT_CAP)
            n = (p.get("repeat") or {}).get("n", 1)
            if counts.get(name, 0) >= cap:
                log.append(f"dropped extra {name}")
                continue
            if counts.get(name, 0) + n > cap:
                p = dict(p, repeat={"n": cap - counts.get(name, 0), "step": p["repeat"]["step"]})
                if p["repeat"]["n"] <= 1:
                    p.pop("repeat")
            counts[name] = counts.get(name, 0) + (p.get("repeat") or {}).get("n", 1)
        keep.append(p)
    spec["props"] = keep
    return spec, log


# --------------------------------------------------------------------------- rooms sized by their furniture

def _foot(p: dict) -> float:
    fw, fd = kits.KITS[p["kit"]]["footprint"]
    return fw * fd * (p.get("repeat") or {}).get("n", 1)


def fit_rooms(spec: dict, min_cover: float = 0.16, min_side: float = 22.0, max_cut: float = 0.35) -> tuple[dict, list[str]]:
    """A room whose furniture covers < min_cover of its floor shrinks towards the furniture (+5 studs), at most
    max_cut of each side length, never below min_side; spawn/focal points inside are kept inside."""
    spec = copy.deepcopy(spec)
    log = []
    for room in spec["rooms"]:
        zone = next(z for z in spec["zones"] if z["id"] == room["zone"])
        x0, z0, x1, z1 = zone["rect"]
        area = (x1 - x0) * (z1 - z0)
        inside = [p for p in spec["props"] if x0 <= p["at"][0] <= x1 and z0 <= p["at"][1] <= z1]
        cover = sum(_foot(p) for p in inside) / max(1.0, area)
        if cover >= min_cover or area < min_side * min_side * 1.5 or not inside:
            continue
        pts = [p["at"] for p in inside] + [f["at"] for f in spec["focal"] if x0 <= f["at"][0] <= x1 and z0 <= f["at"][1] <= z1]
        sx, sz = spec["spawn"]
        if x0 <= sx <= x1 and z0 <= sz <= z1:
            pts.append([sx, sz])
        bx0, bx1 = min(q[0] for q in pts) - 5, max(q[0] for q in pts) + 5
        bz0, bz1 = min(q[1] for q in pts) - 5, max(q[1] for q in pts) + 5

        def cut(lo, hi, blo, bhi):
            length = hi - lo
            room_for = max(0.0, length - max(min_side, bhi - blo))
            limit = min(room_for, length * max_cut)
            take_lo = min(max(0.0, blo - lo), limit)
            take_hi = min(max(0.0, hi - bhi), limit - take_lo)
            return lo + take_lo, hi - take_hi
        nx0, nx1 = cut(x0, x1, bx0, bx1)
        nz0, nz1 = cut(z0, z1, bz0, bz1)
        if (nx1 - nx0) * (nz1 - nz0) < area * 0.97:
            zone["rect"] = [round(nx0, 1), round(nz0, 1), round(nx1, 1), round(nz1, 1)]
            log.append(f"room {zone['id']} {x1 - x0:g}x{z1 - z0:g} -> {nx1 - nx0:g}x{nz1 - nz0:g} (cover {cover:.2f})")
    return spec, log


# --------------------------------------------------------------------------- outdoor framing scatter

def outdoor_share(spec: dict) -> float:
    w, d = spec["size"]
    roofed = sum((z["rect"][2] - z["rect"][0]) * (z["rect"][3] - z["rect"][1])
                 for z in spec["zones"] for r in spec["rooms"] if r["zone"] == z["id"] and r["roof"] != "none")
    return max(0.0, 1 - roofed / max(1.0, w * d))


def _nature_set(spec: dict, brief: str) -> list[tuple[str, dict]]:
    on = themes_on(brief)
    if "winter" in on:
        return [("snow_pine", {}), ("snow_pine", {}), ("rocks", {}), ("bush", {})]
    if "beach" in on:
        return [("tree", {"kind": "palm"}), ("tree", {"kind": "palm"}), ("rocks", {}), ("bush", {})]
    if "japanese" in on:
        return [("tree", {"kind": "cherry"}), ("bamboo_cluster", {}), ("rocks", {}), ("bush", {})]
    if spec["state"] == "abandoned" or spec["mood"] in ("foggy_horror",):
        return [("tree", {"kind": "dead"}), ("tree", {"kind": "pine"}), ("rocks", {}), ("bush", {})]
    if "camp" in on:
        return [("tree", {"kind": "pine"}), ("tree", {"kind": "pine"}), ("tree", {"kind": "birch"}), ("rocks", {}), ("bush", {})]
    return [("tree", {"kind": "oak"}), ("tree", {"kind": "pine"}), ("bush", {}), ("rocks", {})]


def _blocked(spec: dict, x: float, z: float, r: float) -> bool:
    for zone in spec["zones"]:
        x0, z0, x1, z1 = zone["rect"]
        room = any(rm["zone"] == zone["id"] for rm in spec["rooms"])
        hard = room or zone.get("floor") == "water"
        if hard and x0 - r <= x <= x1 + r and z0 - r <= z <= z1 + r:
            return True
    for pth in spec["paths"]:
        (ax, az), (bx, bz) = pth["from"], pth["to"]
        vx, vz = bx - ax, bz - az
        L2 = vx * vx + vz * vz or 1.0
        t = max(0.0, min(1.0, ((x - ax) * vx + (z - az) * vz) / L2))
        if math.hypot(x - (ax + t * vx), z - (az + t * vz)) < pth["w"] / 2 + r + 1:
            return True
    for p in spec["props"]:
        fw, fd = kits.KITS[p["kit"]]["footprint"]
        if math.hypot(x - p["at"][0], z - p["at"][1]) < max(fw, fd) / 2 + r:
            return True
        if p["kit"] == "water":
            ww, dd = p["params"].get("w", 20), p["params"].get("d", 20)
            if abs(x - p["at"][0]) < ww / 2 + r and abs(z - p["at"][1]) < dd / 2 + r:
                return True
    sx, sz = spec["spawn"]
    if math.hypot(x - sx, z - sz) < 10:
        return True
    for f in spec["focal"]:
        if math.hypot(x - f["at"][0], z - f["at"][1]) < 12:
            return True
    return False


def scatter(spec: dict, brief: str, max_add: int = 40) -> tuple[dict, list[str]]:
    """Clustered framing vegetation in the outer band of outdoor maps (denser at the edge, sparse inside)."""
    if outdoor_share(spec) < 0.45:
        return spec, []
    spec = copy.deepcopy(spec)
    rng = random.Random(spec.get("seed", 7) * 31 + 5)
    w, d = spec["size"]
    band = max(8.0, min(w, d) * 0.16)
    kinds = _nature_set(spec, brief)
    added = 0
    centres = []
    perimeter = 2 * (w + d)
    n_clusters = int(max(6, min(16, perimeter / 30)))
    for i in range(n_clusters):
        u = (i + rng.uniform(0.2, 0.8)) / n_clusters * perimeter
        inset = band * rng.uniform(0.15, 0.6)
        if u < w:
            x, z = -w / 2 + u, -d / 2 + inset
        elif u < w + d:
            x, z = w / 2 - inset, -d / 2 + (u - w)
        elif u < 2 * w + d:
            x, z = w / 2 - (u - w - d), d / 2 - inset
        else:
            x, z = -w / 2 + inset, d / 2 - (u - 2 * w - d)
        centres.append((x, z))
    for cx, cz in centres:
        for k in range(rng.randint(2, 4)):
            if added >= max_add:
                break
            kit, params = kinds[0] if k == 0 else rng.choice(kinds)
            x = max(-w / 2 + 2, min(w / 2 - 2, cx + rng.uniform(-6, 6)))
            z = max(-d / 2 + 2, min(d / 2 - 2, cz + rng.uniform(-6, 6)))
            r = 3.5 if kit in ("tree", "snow_pine", "bamboo_cluster") else 1.5
            if _blocked(spec, x, z, r):
                continue
            spec["props"].append({"kit": kit, "at": [round(x, 1), round(z, 1)], "rot": round(rng.uniform(0, 360)),
                                  "params": kits.clean_params(kit, params), "why": "edge framing"})
            added += 1
    # stud / low-poly: terraced cliffs along the back edge (far side from the spawn) close the horizon
    if spec["style"] in ("stud", "lowpoly") and "beach" not in themes_on(brief):
        sx, sz = spec["spawn"]
        back_z = -d / 2 + 6 if sz > 0 else d / 2 - 6
        n = int(max(2, min(6, w // 40)))
        mat = "snow" if "winter" in themes_on(brief) else "rock"
        for k in range(n):
            x = -w / 2 + (k + 0.5) * w / n
            if not _blocked(spec, x, back_z, 7):
                params = {"h": rng.choice((10, 14, 18)), "w": min(80, w / n + 2), "mat": mat}
                spec["props"].append({"kit": "cliff", "at": [round(x, 1), round(back_z, 1)],
                                      "rot": 0 if sz > 0 else 180, "params": kits.clean_params("cliff", params),
                                      "why": "backdrop terraces"})
                added += 1
    # sparse ground dressing towards the middle (gradient: edge clusters dense, inner tufts sparse)
    for _ in range(int(min(14, w * d / 900))):
        x, z = rng.uniform(-w / 2 + band, w / 2 - band), rng.uniform(-d / 2 + band, d / 2 - band)
        kit = "grass_tufts" if spec["ground"] in ("grass", "ground", "mud") else "rocks"
        if spec["ground"] in ("snow", "ice"):
            kit = "rocks"
        if not _blocked(spec, x, z, 2):
            spec["props"].append({"kit": kit, "at": [round(x, 1), round(z, 1)], "rot": 0, "params": {}, "why": "ground dressing"})
            added += 1
    return spec, [f"scatter: {added} framing/dressing props"]


# --------------------------------------------------------------------------- night: practicals + preset

NIGHT_MOODS = {"cold_night", "neon_night", "foggy_horror"}
PRESET_FOR_MOOD = {"cold_night": "moonlit_night_exterior", "neon_night": "neon_cyber_night",
                   "foggy_horror": "overcast_horror", "golden_hour": "golden_hour_exterior"}
INTERIOR_NIGHT = {"cold_night": "warm_luxury_interior", "neon_night": "neon_cyber_night",
                  "foggy_horror": "overcast_horror"}


def preset_for(spec: dict) -> str | None:
    """One of the measured presets in star.roblox_lighting_presets for night/horror/golden moods, else None (the
    builder's own day/interior moods stay; they scored best in the 10-29 eval)."""
    mood = spec["mood"]
    if outdoor_share(spec) < 0.4:
        if spec["state"] == "abandoned" and mood in NIGHT_MOODS:
            return "overcast_horror"
        return INTERIOR_NIGHT.get(mood)
    return PRESET_FOR_MOOD.get(mood)


def night_dress(spec: dict, brief: str = "", max_add: int = 10) -> tuple[dict, list[str]]:
    """Night/dusk outdoor scenes: practical lights along every path (alternating sides, ~22 studs apart)."""
    if spec["mood"] not in NIGHT_MOODS | {"warm_evening"} or outdoor_share(spec) < 0.4:
        return spec, []
    spec = copy.deepcopy(spec)
    lights = [p for p in spec["props"] if "light" in kits.KITS[p["kit"]].get("tags", ())]
    kit = "lantern" if spec["style"] in ("lowpoly",) or spec["state"] == "abandoned" and spec["mood"] == "foggy_horror" else "lamp_post"
    added = 0
    for pth in spec["paths"]:
        (ax, az), (bx, bz) = pth["from"], pth["to"]
        length = math.hypot(bx - ax, bz - az)
        if length < 10:
            continue
        ux, uz = (bx - ax) / length, (bz - az) / length
        steps = max(1, int(length // 22))
        for i in range(steps):
            if added >= max_add:
                break
            t = (i + 0.5) / steps * length
            side = 1 if i % 2 == 0 else -1
            off = pth["w"] / 2 + 1.5
            x, z = ax + ux * t - uz * off * side, az + uz * t + ux * off * side
            if any(math.hypot(p["at"][0] - x, p["at"][1] - z) < 10 for p in lights):
                continue
            prop = {"kit": kit, "at": [round(x, 1), round(z, 1)], "rot": 0,
                    "params": kits.clean_params(kit, {"color": "warm"} if kit == "lamp_post" else {}), "why": "path light at night"}
            if spec["state"] == "abandoned" and kit == "lamp_post" and i % 3 == 2:
                prop["params"] = kits.clean_params(kit, {"broken": 1})
            spec["props"].append(prop)
            lights.append(prop)
            added += 1
    return spec, [f"night: {added} path lights"] if added else []


def apply_all(spec: dict, brief: str) -> tuple[dict, list[str]]:
    """The deterministic art pass the new pipeline runs after generation (before autofix)."""
    log: list[str] = []
    for step in (cohere, None, scatter, night_dress):
        if step is None:
            spec, got = fit_rooms(spec)
        else:
            spec, got = step(spec, brief)
        log += got
    norm, _notes = scene.normalize(spec)
    norm["preset"] = preset_for(norm)
    return norm, log
