"""Exact text on generated pictures. Image models misspell; Pillow does not.

The art is made with the text area left blank, then the real words are drawn here with a bundled free font
(star/data/fonts: Press Start 2P and Anton, both SIL Open Font License 1.1, licence files beside them).
"""
from __future__ import annotations

import io
from pathlib import Path

from .image_prompt import Overlay

FONTS = Path(__file__).resolve().parent / 'data' / 'fonts'
FONT_FILES = {'pixel': 'PressStart2P-Regular.ttf', 'bold': 'Anton-Regular.ttf', 'plain': 'Anton-Regular.ttf'}
MARGIN = 0.04            # share of the picture's shorter side


def _font(style: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(FONTS / FONT_FILES.get(style, FONT_FILES['bold'])), size)
    except OSError:
        return ImageFont.load_default(size)      # Pillow's own bundled font, never a missing-font crash


def _fit(draw, text: str, style: str, max_width: int, max_height: int):
    """The largest font (down to 10 px) in which `text` fits the box."""
    low, high, best = 10, max(10, max_height), None
    while low <= high:
        mid = (low + high) // 2
        font = _font(style, mid)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            best, low = font, mid + 1
        else:
            high = mid - 1
    return best or _font(style, 10)


def anchor(where: str, width: int, height: int, box: tuple[int, int, int, int]) -> tuple[int, int]:
    """Top-left corner for a text box (its bbox) placed at `where`."""
    pad = int(min(width, height) * MARGIN)
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    vertical = 'top' if where.startswith('top') else 'bottom' if where.startswith('bottom') else 'middle'
    horizontal = 'left' if where.endswith('left') else 'right' if where.endswith('right') else 'center'
    x = {'left': pad, 'right': width - pad - text_w, 'center': (width - text_w) // 2}[horizontal]
    y = {'top': pad, 'bottom': height - pad - text_h, 'middle': (height - text_h) // 2}[vertical]
    return x - box[0], y - box[1]


def draw_overlays(picture: bytes, overlays: tuple[Overlay, ...] | list[Overlay]) -> bytes:
    """PNG bytes of `picture` with each overlay's exact text drawn in. No overlays: the picture is returned as is."""
    if not overlays:
        return picture
    from PIL import ImageDraw
    from .pil_safe import Image
    with Image.open(io.BytesIO(picture)) as opened:
        canvas = opened.convert('RGBA')
    width, height = canvas.size
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for item in overlays:
        max_w = int(width * (0.88 if item.where in ('top', 'center', 'bottom') else 0.44))
        max_h = int(height * (0.16 if item.style != 'plain' else 0.10))
        font = _fit(draw, item.text, item.style, max_w, max_h)
        box = draw.textbbox((0, 0), item.text, font=font)
        x, y = anchor(item.where, width, height, box)
        size = getattr(font, 'size', 16)
        stroke = max(2, size // 14)
        light = item.style == 'pixel'
        fill = (255, 255, 255, 255) if not light else (255, 238, 120, 255)
        draw.text((x + stroke, y + stroke), item.text, font=font, fill=(0, 0, 0, 150))
        draw.text((x, y), item.text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    out = io.BytesIO()
    Image.alpha_composite(canvas, layer).convert('RGB').save(out, format='PNG')
    return out.getvalue()
