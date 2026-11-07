"""Draw: she picks a subject, the model plans a simple vector sketch (strokes on a 100x100 board), and she paints it
with her mouse in MS Paint, saves it to her gallery folder and checks the saved picture against the plan.

Plan   {"title": str, "strokes": [{"color": "Red", "points": [[x, y], ...]}]}   x right, y down, 0-100. At most 40
       strokes of 2-80 points. Colours are Paint's own swatch names (hex colours are mapped to the nearest swatch).
Paint  each stroke is one smooth mouse drag at human speed (hands.drag): press, follow a spline through the points
       with one minimum-jerk speed profile, release. Strokes are mapped into a square in the middle of the canvas
       and clamped inside it, so no stroke can reach the toolbar. A colour is chosen by clicking its swatch (found
       by name in the UI Automation tree) and checked on the "Color 1:" control afterwards.
Check  the saved file exists and is a picture, and its ink matches the plan: precision (ink that lies on planned
       strokes) and recall (planned strokes that have ink), both measured on a 100x100 grid after a one-cell
       dilation. `verified` needs both at least 0.5. A blank or wildly different picture is reported as not verified.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import time

from .agent import Computer, json_objects
from .hands import Stopped
from .screen import Rect, Screen

MAX_STROKES, MAX_POINTS = 40, 80
PALETTE = {"Black": (0, 0, 0), "Gray": (127, 127, 127), "Dark red": (136, 0, 21), "Red": (237, 28, 36),
           "Orange": (255, 127, 39), "Yellow": (255, 242, 0), "Green": (34, 177, 76), "Turquoise": (0, 162, 232),
           "Indigo": (63, 72, 204), "Purple": (163, 73, 164), "Light gray": (195, 195, 195), "Brown": (185, 122, 87),
           "Rose": (255, 174, 201), "Gold": (255, 201, 14), "Light yellow": (239, 228, 176), "Lime": (181, 230, 29),
           "Light turquoise": (153, 217, 234), "Blue-gray": (112, 146, 190), "Lavender": (200, 191, 231)}
PLAN_SYSTEM = """You plan simple line drawings that a person could paint with a mouse. Reply with ONE JSON object:
{"title": "short title", "strokes": [{"color": "Red", "points": [[x, y], [x, y], ...]}]}
The board is 100 x 100, x to the right, y down. Use at most 25 strokes of 2 to 40 points; a closed shape repeats its
first point at the end; keep everything inside 5..95. Colours must come from: """ + ", ".join(PALETTE) + """.
Draw the outline first, then details. Simple and recognisable beats detailed."""


@dataclass(frozen=True)
class Stroke:
    color: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Plan:
    title: str
    strokes: tuple[Stroke, ...]

    def as_json(self) -> dict:
        return {"title": self.title, "strokes": [{"color": s.color, "points": [list(p) for p in s.points]}
                                                 for s in self.strokes]}


def nearest_color(value) -> str:
    """A Paint swatch name for a colour given as a name or #rrggbb."""
    text = str(value or "").strip()
    for name in PALETTE:
        if name.lower() == text.lower():
            return name
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", text)
    if match:
        rgb = tuple(int(match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
        return min(PALETTE, key=lambda n: sum((a - b) ** 2 for a, b in zip(PALETTE[n], rgb)))
    return "Black"


def validate_plan(data) -> Plan | str:
    """A Plan from a model's JSON, or a message saying what to fix."""
    if not isinstance(data, dict) or not isinstance(data.get("strokes"), list) or not data["strokes"]:
        return "need an object with a non-empty \"strokes\" list"
    strokes = []
    for i, raw in enumerate(data["strokes"][:MAX_STROKES]):
        pts = raw.get("points") if isinstance(raw, dict) else None
        if not isinstance(pts, list) or len(pts) < 2:
            return f"stroke {i + 1} needs a \"points\" list of at least two [x, y] pairs"
        clean = []
        for p in pts[:MAX_POINTS]:
            if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)):
                return f"stroke {i + 1} has a point that is not [x, y] numbers"
            clean.append((min(100.0, max(0.0, float(p[0]))), min(100.0, max(0.0, float(p[1])))))
        strokes.append(Stroke(nearest_color(raw.get("color")), tuple(clean)))
    return Plan(str(data.get("title") or "untitled")[:60], tuple(strokes))


def plan_drawing(chat, subject: str, attempts: int = 2) -> tuple[Plan | None, str]:
    """Ask the model for a stroke plan; one retry with the validation message. Returns (plan, error)."""
    error = ""
    for _ in range(attempts):
        ask = f"Subject: {subject}" + (f"\nYour last reply was rejected: {error}" if error else "")
        reply = chat([{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": ask}], [])
        error = "no JSON object in the reply"
        for data in json_objects(reply.get("content") or ""):
            checked = validate_plan(data)
            if isinstance(checked, Plan):
                return checked, ""
            error = checked
    return None, error


def render_plan(plan: Plan, size: int = 400):
    """The plan as a picture (white board, coloured strokes): the reference the saved painting is compared with."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    width = max(2, size // 60)
    for stroke in plan.strokes:
        pts = [(x * size / 100, y * size / 100) for x, y in stroke.points]
        draw.line(pts, fill=PALETTE[stroke.color], width=width, joint="curve")
    return image


# ---- finding the canvas ---------------------------------------------------------------------------------------
def largest_light_rect(image, threshold: int = 235, cell: int = 8) -> Rect | None:
    """The biggest rectangle of near-white pixels in a PIL image (left, top, right, bottom), found on a grid of
    `cell`-pixel cells with the classic largest-rectangle-in-a-histogram scan."""
    small = image.convert("RGB").resize((max(1, image.width // cell), max(1, image.height // cell)))
    w, h = small.size
    px = small.load()
    heights = [0] * w
    best = (0, 0, 0, 0, 0)                                   # area, left, top, right, bottom (cells)
    for y in range(h):
        for x in range(w):
            heights[x] = heights[x] + 1 if min(px[x, y]) >= threshold else 0
        stack: list[int] = []
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            while stack and heights[stack[-1]] >= cur:
                top = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                area = top * (x - left)
                if area > best[0]:
                    best = (area, left, y - top + 1, x, y + 1)
            stack.append(x)
    if best[0] == 0:
        return None
    return _refine(image, (best[1] * cell, best[2] * cell, best[3] * cell, best[4] * cell), threshold, cell)


def _refine(image, rect: Rect, threshold: int, reach: int) -> Rect:
    """Move each edge of a grid-aligned rectangle to the exact pixel where the white page ends (a 8-pixel error would
    shift thin strokes by two cells of the 100x100 check)."""
    from PIL import ImageStat
    gray = image.convert("L").point(lambda v: 255 if v >= threshold else 0)
    l, t, r, b = rect

    def white(box) -> bool:
        if box[2] <= box[0] or box[3] <= box[1] or box[0] < 0 or box[1] < 0 or box[2] > gray.width or box[3] > gray.height:
            return False
        return ImageStat.Stat(gray.crop(box)).mean[0] / 255 >= 0.97

    for _ in range(reach):                                    # grow while the next line is still white
        if white((l - 1, t, l, b)):
            l -= 1
        if white((r, t, r + 1, b)):
            r += 1
        if white((l, t - 1, r, t)):
            t -= 1
        if white((l, b, r, b + 1)):
            b += 1
    for _ in range(reach):                                    # shrink while the edge line is not white
        if r - l > 2 and not white((l, t, l + 1, b)):
            l += 1
        if r - l > 2 and not white((r - 1, t, r, b)):
            r -= 1
        if b - t > 2 and not white((l, t, r, t + 1)):
            t += 1
        if b - t > 2 and not white((l, b - 1, r, b)):
            b -= 1
    return l, t, r, b


def find_canvas(screen: Screen, image=None) -> Rect | None:
    """Where the drawing surface is on screen. The UI Automation element for the canvas first (Win11 Paint names it
    "... on Canvas", automation id "image"), then tightened to the white page inside it when a screenshot is given;
    with no such element, the largest white rectangle in the window."""
    cands = [e for e in screen.elements if e.width > 150 and e.height > 150 and
             (e.auto_id.lower() in ("image", "canvas", "drawingcanvas") or re.search(r"\bcanvas\b", e.name, re.I))]
    cands.sort(key=lambda e: -e.width * e.height)
    window = next((e for e in screen.elements if e.role == "window"), None)
    area = cands[0].rect if cands else (window.rect if window else None)
    if area is None or image is None:
        return area
    l, t, r, b = (max(0, area[0]), max(0, area[1]), min(image.width, area[2]), min(image.height, area[3]))
    if r - l < 50 or b - t < 50:
        return area
    white = largest_light_rect(image.crop((l, t, r, b)))
    if white is None or (white[2] - white[0]) * (white[3] - white[1]) < 0.2 * (r - l) * (b - t):
        return area if cands else None
    return l + white[0], t + white[1], l + white[2], t + white[3]


def square_in(rect: Rect, margin: float = 0.04) -> Rect:
    """The centred square of a rectangle, pulled in by `margin` of its side: where the 100x100 board is painted."""
    l, t, r, b = rect
    side = min(r - l, b - t) * (1 - 2 * margin)
    cx, cy = (l + r) / 2, (t + b) / 2
    return int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2)


def to_screen(plan: Plan, square: Rect) -> list[tuple[str, list[tuple[float, float]]]]:
    l, t, r, b = square
    return [(s.color, [(l + x / 100 * (r - l), t + y / 100 * (b - t)) for x, y in s.points]) for s in plan.strokes]


# ---- checking the result --------------------------------------------------------------------------------------
def ink_mask(image, box: tuple[float, float, float, float] | None = None, grid: int = 100):
    """A grid x grid grid of 0/1: where the picture is not white. `box` is a region as fractions (l, t, r, b)."""
    from PIL import Image
    w, h = image.size
    if box:
        image = image.crop((int(box[0] * w), int(box[1] * h), max(int(box[2] * w), int(box[0] * w) + 1),
                            max(int(box[3] * h), int(box[1] * h) + 1)))
    small = image.convert("RGB").resize((grid, grid), Image.BOX)
    px = small.load()
    return [[1 if min(px[x, y]) < 200 else 0 for x in range(grid)] for y in range(grid)]


def _dilate(mask: list[list[int]], n: int = 1) -> list[list[int]]:
    h, w = len(mask), len(mask[0])
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                for yy in range(max(0, y - n), min(h, y + n + 1)):
                    for xx in range(max(0, x - n), min(w, x + n + 1)):
                        out[yy][xx] = 1
    return out


def compare_to_plan(saved, plan: Plan, box: tuple[float, float, float, float]) -> dict:
    """precision / recall / ink share of the saved picture's square region against the plan, on a 100x100 grid."""
    ink = ink_mask(saved, box)
    ref = ink_mask(render_plan(plan, 400))
    ink_n, ref_n = sum(map(sum, ink)), sum(map(sum, ref))
    near_ref, near_ink = _dilate(ref), _dilate(ink)
    hit_ink = sum(1 for y in range(100) for x in range(100) if ink[y][x] and near_ref[y][x])
    hit_ref = sum(1 for y in range(100) for x in range(100) if ref[y][x] and near_ink[y][x])
    precision = hit_ink / ink_n if ink_n else 0.0
    recall = hit_ref / ref_n if ref_n else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "ink_cells": ink_n, "plan_cells": ref_n,
            "match": bool(ink_n and precision >= 0.5 and recall >= 0.5)}


# ---- painting -------------------------------------------------------------------------------------------------
def select_color(computer: Computer, name: str) -> tuple[bool, str]:
    """Click the swatch called `name` and confirm the "Color 1:" control now names it."""
    screen = computer.see()
    swatch = next((e for _, e in screen.find(name, limit=8) if e.name.lower() == name.lower() and
                   e.role in ("listitem", "button", "radio")), None)
    if swatch is None:
        return False, f"no swatch called {name!r} on screen"
    x, y = computer.aim_point(swatch)
    computer.hands.click(x, y, width=min(swatch.width, swatch.height))
    computer.sleep(0.3)
    after = computer.see()
    chosen = next((e.name for e in after.elements if e.name.lower().startswith("color 1")), "")
    return (name.lower() in chosen.lower() if chosen else True), chosen or "colour control not found"


def paint_plan(computer: Computer, plan: Plan, square: Rect, speed_px_s: float = 380.0) -> list[str]:
    """Paint every stroke; returns problems (empty = every stroke was drawn and every colour was set)."""
    problems: list[str] = []
    current = "Black"
    for color, points in to_screen(plan, square):
        if color != current:
            ok, seen = select_color(computer, color)
            if ok:
                current = color
            else:
                problems.append(f"could not set colour {color}: {seen}")
        computer.hands.drag(points, speed_px_s=speed_px_s)
        computer.sleep(0.12)
    return problems


def save_as(computer: Computer, path: Path) -> tuple[bool, str]:
    """Ctrl+S in Paint, type the full path in the file-name box, Enter. True when the file appears."""
    computer.hands.key("ctrl+s")
    deadline = computer.clock() + 10
    name_box = None
    while computer.clock() < deadline and name_box is None:
        computer.sleep(0.4)
        screen = computer.see()
        name_box = next((e for e in screen.elements if e.role == "edit" and
                         re.search(r"file name", e.name, re.I)), None)
    if name_box is None:
        return False, "the Save As box did not appear"
    x, y = computer.aim_point(name_box)
    computer.hands.click(x, y, width=name_box.height)
    computer.hands.key("ctrl+a")
    computer.hands.type_text(str(path), speed=4.0)
    computer.hands.key("enter")
    deadline = computer.clock() + 12
    while computer.clock() < deadline:
        computer.sleep(0.5)
        if path.is_file() and path.stat().st_size > 0:
            return True, f"saved {path}"
    return False, "the file did not appear after Enter"


def draw_session(computer: Computer, plan: Plan, subject: str, gallery: Path, *, app: str = "mspaint.exe",
                 settings: dict | None = None, close_after: bool = True) -> dict:
    """Open Paint, paint the plan, save to the gallery, check the file. Returns the home-loop outcome dict."""
    cfg = settings or computer.cfg
    failures: list[str] = []
    gallery.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:40] or "drawing"
    path = gallery / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.png"
    try:
        info, message = computer.open_app(app, match="paint")
        if info is None:
            return _out(False, False, f"could not open Paint: {message}", [], failures + [f"draw: {message}"])
        if computer.guard is not None:
            computer.guard.exes = {info.exe}
        screen = computer.see()
        image = computer.eye.grab() if computer.eye is not None else None
        canvas = find_canvas(screen, image)
        if canvas is None:
            return _out(False, False, "could not find the canvas", [], failures + ["draw: no canvas found"])
        square = square_in(canvas)
        problems = paint_plan(computer, plan, square, float(cfg.get("speed_px_s", 380)))
        failures += [f"draw: {p}" for p in problems]
        saved_ok, saved = save_as(computer, path)
        if not saved_ok:
            return _out(False, False, f"painted but not saved: {saved}", [], failures + [f"draw: {saved}"])
        from PIL import Image
        with Image.open(path) as picture:
            picture.load()
            cw, ch = canvas[2] - canvas[0], canvas[3] - canvas[1]
            box = ((square[0] - canvas[0]) / cw, (square[1] - canvas[1]) / ch,
                   (square[2] - canvas[0]) / cw, (square[3] - canvas[1]) / ch)
            metrics = compare_to_plan(picture, plan, box)
            metrics["file_size"] = [picture.width, picture.height]
        sidecar = path.with_suffix(".json")
        sidecar.write_text(json.dumps({"subject": subject, "app": app, "plan": plan.as_json(), "check": metrics,
                                       "problems": problems}, indent=1), encoding="utf-8")
        verified = metrics["match"] and not problems
        summary = (f"drew {plan.title!r} ({len(plan.strokes)} strokes) in Paint, saved {path.name}; "
                   f"precision {metrics['precision']}, recall {metrics['recall']}")
        if close_after:
            computer.hands.key("alt+f4")
        return _out(True, verified, summary, [str(path), str(sidecar)], failures if not verified else failures)
    except Stopped:
        return _out(False, False, "stopped by the owner", [], failures)


def _out(ok: bool, verified: bool, summary: str, evidence: list, failures: list) -> dict:
    return {"ok": ok, "verified": verified, "summary": summary, "evidence": evidence, "failures": failures[:8],
            "steps": 0, "goal_done": verified}
