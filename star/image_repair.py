"""The repair loop: when the blind judge finds a flawed region, repaint only that region, then judge again.

    flawed draft -> vision model gives a box + what should be there -> crop around the box (with context)
                 -> masked repaint of the crop with the SAME model that drew the picture (no model swap on an 8 GB card)
                 -> paste back through a feathered mask (every pixel outside the box stays the original) -> re-judge

Everything that decides something is plain code here and tested without a GPU: which flaws are repairable, the crop
geometry, whether to repair again, and whether the repaired picture is better than the original.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import cast

from .image_prompt import parse_json

MAX_REPAIRS = 2                  # repairs of one picture (each costs one locate call, one repaint, one judge)
MIN_AREA, MAX_AREA = 0.002, 0.55  # a box smaller than 0.2 % or larger than 55 % of the picture is not a local flaw
PAD = 0.12                       # the repainted area is the box grown by this share on each side
GROW = 0.45                      # context around the box, as a share of its size on each side
MIN_CROP = 384                   # crop sides are at least this many pixels (the model needs room to draw)
CROP_MULTIPLE = 16
REPAIR_SIDE = 768                # the crop is repainted at about this long side (upscaled when smaller)
DENOISE = 0.78                   # how much of the crop the model may redraw (1.0 = everything)

LOCATE_QUESTION = (
    'This picture has a problem: {issues}. Find the smallest region of the picture that has to be repainted to fix it '
    '(for a leg or arm: the limb and the body next to it; for a hand: the hand; for a sign or label: the text area). '
    'Reply with ONE JSON object and nothing else: {{"regions":[{{"box":[x0,y0,x1,y1],"fix":"what the repainted region '
    'shows, as a plain description of its visible content in 8 to 16 words (for example: grass and the belly of the cow, '
    'or: a hand with five fingers holding a mug), never an instruction like remove or fix"}}]}}. Box coordinates are '
    'integers from 0 to 1000 measured from the top-left corner of the picture (x to the right, y downward), x0<x1, '
    'y0<y1. At most 2 regions.')


@dataclass(frozen=True)
class Flaw:
    box: tuple[float, float, float, float]       # x0, y0, x1, y1 as fractions of the picture (0..1)
    fix: str = ''

    @property
    def area(self) -> float:
        return max(0.0, self.box[2] - self.box[0]) * max(0.0, self.box[3] - self.box[1])


def _fraction(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) / 1000.0


def parse_flaws(reply: str) -> list[Flaw]:
    """Repairable regions from the locate reply. Boxes that are inverted, outside the picture, too small or so large
    that they are the whole picture are dropped (a repaint of everything is a new draft, not a repair)."""
    data = parse_json(reply)
    flaws: list[Flaw] = []
    regions = (data or {}).get('regions')
    for item in regions if isinstance(regions, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('box'), list) or len(item['box']) != 4:
            continue
        edges = [_fraction(v) for v in item['box']]
        if any(edge is None for edge in edges):
            continue
        x0, y0, x1, y1 = (cast(float, edge) for edge in edges)
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        fix = re.sub(r'\s+', ' ', str(item.get('fix') or '')).strip()[:160]
        flaw = Flaw((x0, y0, x1, y1), fix)
        if MIN_AREA <= flaw.area <= MAX_AREA:
            flaws.append(flaw)
    return flaws[:2]


def locate(settings, image_path, issues: list[str], *, ask=None) -> list[Flaw]:
    """Ask the vision model where the problem is. Never raises: no answer means no repair (a new draft instead)."""
    if ask is None:
        from .vision import ask as vision_ask
        ask = vision_ask
    try:
        reply = ask(settings, LOCATE_QUESTION.format(issues='; '.join(dict.fromkeys(issues))[:300]),
                    [image_path], max_tokens=220).text
    except Exception:
        return []
    return parse_flaws(reply)


def crop_box(flaw: Flaw, width: int, height: int) -> tuple[int, int, int, int]:
    """Pixel crop (left, top, right, bottom) around the flaw: grown for context, at least MIN_CROP, sides a multiple
    of 16, kept inside the picture. The crop always contains the flaw's own box."""
    x0, y0, x1, y1 = flaw.box
    bw, bh = (x1 - x0) * width, (y1 - y0) * height
    cx, cy = (x0 + x1) / 2 * width, (y0 + y1) / 2 * height
    side_w = max(MIN_CROP, bw * (1 + 2 * GROW))
    side_h = max(MIN_CROP, bh * (1 + 2 * GROW))
    side_w, side_h = min(side_w, width), min(side_h, height)

    def fit(center: float, side: float, limit: int) -> tuple[int, int]:
        side = int(side) // CROP_MULTIPLE * CROP_MULTIPLE
        side = max(CROP_MULTIPLE, min(side, limit // CROP_MULTIPLE * CROP_MULTIPLE or limit))
        start = int(round(center - side / 2))
        start = max(0, min(start, limit - side))
        return start, start + side

    left, right = fit(cx, side_w, width)
    top, bottom = fit(cy, side_h, height)
    # rounding down must never cut the flaw itself: widen by a block where needed
    if left > int(x0 * width):
        left = max(0, int(x0 * width) // CROP_MULTIPLE * CROP_MULTIPLE)
    if right < int(x1 * width):
        right = min(width, -(-int(x1 * width) // CROP_MULTIPLE) * CROP_MULTIPLE)
    if top > int(y0 * height):
        top = max(0, int(y0 * height) // CROP_MULTIPLE * CROP_MULTIPLE)
    if bottom < int(y1 * height):
        bottom = min(height, -(-int(y1 * height) // CROP_MULTIPLE) * CROP_MULTIPLE)
    return left, top, right, bottom


def work_size(crop_w: int, crop_h: int) -> tuple[int, int]:
    """The size the crop is repainted at: long side about REPAIR_SIDE, both sides a multiple of 16."""
    scale = REPAIR_SIDE / max(crop_w, crop_h)
    return (max(256, round(crop_w * scale / CROP_MULTIPLE) * CROP_MULTIPLE),
            max(256, round(crop_h * scale / CROP_MULTIPLE) * CROP_MULTIPLE))


_INSTRUCTION = re.compile(r'^\s*(?:please\s+)?(?:remove|delete|fix|erase|replace|repair|correct|redraw|repaint|make|change)\b', re.I)
GENERIC_FIX = 'a natural, sharp, detailed continuation of the surrounding scene with correct anatomy'


def local_prompt(flaw: Flaw, scene_prompt: str) -> str:
    """The repaint prompt: what the region shows, plus the last phrases of the scene prompt (light, lens, style) so the join
    matches. The scene's subject is NOT repeated (the crop would grow a second one), and an instruction ("remove the leg")
    is not a description, so it is replaced by the generic one."""
    last = re.split(r'(?<=[.!?])\s+', scene_prompt.strip())[-1]
    style = ', '.join(p.strip(' .') for p in re.split(r',\s*', last.rstrip('.'))[-2:])[:90]
    fix = '' if _INSTRUCTION.match(flaw.fix) else flaw.fix.strip(' .')
    return f'{fix or GENERIC_FIX}. {style}'.strip(' .')[:600]


# ---- decisions --------------------------------------------------------------------------------------------------

def decide(verdict, *, repairs_done: int, flaws_found: bool | None = None, max_repairs: int = MAX_REPAIRS) -> str:
    """What to do with the best picture so far.

    'accept'  - it passes (or nothing can be judged): take it
    'locate'  - it fails with a hard problem and repair budget is left: ask where the flaw is
    'repair'  - flaws were located (flaws_found=True): repaint them
    'reroll'  - it fails but the flaw cannot be boxed (a whole-picture problem): a new draft is the only fix
    'keep'    - repair budget is used up: keep the best picture and say so
    """
    if not verdict.judged or verdict.blank:
        return 'accept' if verdict.judged is False else 'reroll'
    if verdict.passed:
        return 'accept'
    if repairs_done >= max_repairs:
        return 'keep'
    if flaws_found is None:
        return 'locate'
    return 'repair' if flaws_found else 'reroll'


def better(after, before) -> bool:
    """Is the repaired picture's verdict better than the original's? Passing beats failing, then the score."""
    if not after.judged:
        return False
    return (after.passed, after.score) > (before.passed, before.score)


# ---- pixels -----------------------------------------------------------------------------------------------------

def feather_mask(size: tuple[int, int], inner: tuple[int, int, int, int], blur: int):
    """An 'L' mask: white inside the flaw's box (grown a little), soft edge. Everything black stays original."""
    from PIL import ImageDraw, ImageFilter
    from .pil_safe import Image
    mask = Image.new('L', size, 0)
    ImageDraw.Draw(mask).rectangle(inner, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def paste_back(original_png: bytes, repaired_png: bytes, flaw: Flaw, crop: tuple[int, int, int, int]) -> bytes:
    """The original picture with the repainted crop blended in through a feathered mask over the flaw's box."""
    from .pil_safe import Image
    with Image.open(io.BytesIO(original_png)) as opened:
        original = opened.convert('RGB')
    width, height = original.size
    left, top, right, bottom = crop
    with Image.open(io.BytesIO(repaired_png)) as opened:
        patch = opened.convert('RGB').resize((right - left, bottom - top), Image.Resampling.LANCZOS)
    x0, y0, x1, y1 = flaw.box
    pad_x, pad_y = int((x1 - x0) * width * PAD), int((y1 - y0) * height * PAD)
    inner = (max(0, int(x0 * width) - pad_x - left), max(0, int(y0 * height) - pad_y - top),
             min(right, int(x1 * width) + pad_x) - left, min(bottom, int(y1 * height) + pad_y) - top)
    blur = max(3, min(right - left, bottom - top) // 40)
    mask = feather_mask((right - left, bottom - top), inner, blur)
    region = Image.composite(patch, original.crop(crop), mask)
    original.paste(region, (left, top))
    out = io.BytesIO()
    original.save(out, format='PNG')
    return out.getvalue()


def inpaint_inputs(png: bytes, flaw: Flaw, crop: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[bytes, bytes]:
    """(the crop resized to `size` as PNG, a mask PNG of the same size). The mask is white over the flaw's box (grown a
    little): the model repaints that and keeps the rest of the crop as context."""
    from PIL import ImageDraw
    from .pil_safe import Image
    with Image.open(io.BytesIO(png)) as opened:
        full = opened.convert('RGB')
        piece = full.crop(crop).resize(size, Image.Resampling.LANCZOS)
        width, height = full.size
    left, top, right, bottom = crop
    scale_x, scale_y = size[0] / (right - left), size[1] / (bottom - top)
    x0, y0, x1, y1 = flaw.box
    pad_x, pad_y = (x1 - x0) * width * PAD, (y1 - y0) * height * PAD
    box = ((x0 * width - pad_x - left) * scale_x, (y0 * height - pad_y - top) * scale_y,
           (x1 * width + pad_x - left) * scale_x, (y1 * height + pad_y - top) * scale_y)
    mask = Image.new('RGB', size, (0, 0, 0))
    ImageDraw.Draw(mask).rectangle([max(0, box[0]), max(0, box[1]), min(size[0], box[2]), min(size[1], box[3])],
                                   fill=(255, 255, 255))
    out_a, out_b = io.BytesIO(), io.BytesIO()
    piece.save(out_a, format='PNG')
    mask.save(out_b, format='PNG')
    return out_a.getvalue(), out_b.getvalue()
