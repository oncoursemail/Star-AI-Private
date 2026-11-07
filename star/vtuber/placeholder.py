"""A plain generated test character (NOT Star's art): geometric shapes in layers, with every layer type the model
format supports (blink, gaze, brows, blush, five mouth shapes, hair and body follow-through). It exists so tests, the
sample clip and a first run work before the owner approves the real model; replace it with the vtuber_model setting.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

VERSION = 2
S = 3                                   # supersampling for smooth edges


def _canvas(w: int, h: int):
    img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _save(img: Image.Image, path: Path, w: int, h: int) -> None:
    img.resize((w, h), Image.Resampling.LANCZOS).save(path)


def _ellipse(draw, box, fill, outline=None, width=0):
    draw.ellipse([v * S for v in box], fill=fill, outline=outline, width=width * S)


MOUTHS = {  # name: (width, height) of the opening on a 120 x 70 sprite, lips drawn around it
    "closed": (70, 5), "small": (46, 20), "aa": (62, 52), "ih": (74, 20), "ou": (30, 30), "ee": (80, 14), "oh": (44, 42)}


def build_placeholder(folder: str | Path | None = None) -> Path:
    base = Path(folder) if folder else Path(tempfile.gettempdir()) / f"star-vtuber-placeholder-v{VERSION}"
    if (base / "avatar.json").is_file():
        return base
    base.mkdir(parents=True, exist_ok=True)
    skin, ink, hair, cloth = (255, 224, 196, 255), (60, 40, 50, 255), (70, 50, 110, 255), (90, 120, 200, 255)

    img, d = _canvas(520, 420)                       # body
    _ellipse(d, (60, 150, 460, 560), cloth)
    _save(img, base / "body.png", 520, 420)
    img, d = _canvas(440, 460)                       # hair behind the head
    _ellipse(d, (10, 10, 430, 450), hair)
    _save(img, base / "hair_back.png", 440, 460)
    img, d = _canvas(340, 340)                       # face
    _ellipse(d, (6, 6, 334, 334), skin, outline=ink, width=4)
    _save(img, base / "face.png", 340, 340)
    img, d = _canvas(340, 130)                       # open eyes (whites + pupils are separate so the gaze can move)
    for cx in (95, 245):
        _ellipse(d, (cx - 38, 20, cx + 38, 110), (255, 255, 255, 255), outline=ink, width=3)
    _save(img, base / "eyes_open.png", 340, 130)
    img, d = _canvas(340, 130)
    for cx in (95, 245):
        _ellipse(d, (cx - 15, 45, cx + 15, 90), ink)
    _save(img, base / "pupils.png", 340, 130)
    img, d = _canvas(340, 130)                       # closed eyes
    for cx in (95, 245):
        d.arc([(cx - 36) * S, 40 * S, (cx + 36) * S, 100 * S], 20, 160, fill=ink, width=5 * S)
    _save(img, base / "eyes_closed.png", 340, 130)
    img, d = _canvas(340, 40)                        # brows
    for cx in (95, 245):
        d.line([(cx - 36) * S, 24 * S, (cx + 36) * S, 18 * S], fill=ink, width=7 * S)
    _save(img, base / "brows.png", 340, 40)
    img, d = _canvas(340, 60)                        # blush
    for cx in (60, 280):
        _ellipse(d, (cx - 34, 8, cx + 34, 52), (255, 140, 150, 170))
    _save(img, base / "blush.png", 340, 60)
    for name, (ow, oh) in MOUTHS.items():            # five mouth shapes + closed + small
        img, d = _canvas(120, 70)
        box = (60 - ow / 2, 35 - oh / 2, 60 + ow / 2, 35 + oh / 2)
        _ellipse(d, box, (150, 40, 60, 255) if oh > 8 else ink, outline=ink, width=3)
        _save(img, base / f"mouth_{name}.png", 120, 70)

    cx, cy = 640, 330
    spec = {"name": "placeholder (generated test character, not Star's art)", "size": [1280, 720],
            "background": [28, 30, 44], "layers": [
        {"id": "body", "image": "body.png", "pos": [cx, 560], "pivot": [260, 200],
         "bind": {"tx": {"param": "body_lean", "gain": 40}, "sy": {"param": "breath", "gain": 0.012}}},
        {"id": "head", "pos": [cx, cy + 150], "bind": {
            "tx": {"param": "head_x", "gain": 70}, "ty": {"param": "head_y", "gain": 40},
            "rot": {"param": "head_roll", "gain": 8}}},
        {"id": "hair_back", "parent": "head", "image": "hair_back.png", "pos": [cx, cy - 10],
         "bind": {"rot": {"param": "hair_sway", "gain": 4}}},
        {"id": "face", "parent": "head", "image": "face.png", "pos": [cx, cy]},
        {"id": "blush", "parent": "head", "image": "blush.png", "pos": [cx, cy + 40],
         "bind": {"opacity": {"param": "smile", "gain": 1.2}}},
        {"id": "eyes", "parent": "head", "image": "eyes_open.png", "pos": [cx, cy - 25],
         "bind": {"opacity": {"param": "blink", "gain": -1.0, "offset": 1.0}}},
        {"id": "pupils", "parent": "head", "image": "pupils.png", "pos": [cx, cy - 25],
         "bind": {"tx": {"param": "gaze_x", "gain": 14}, "ty": {"param": "gaze_y", "gain": 8},
                  "opacity": {"param": "blink", "gain": -1.0, "offset": 1.0}}},
        {"id": "eyes_closed", "parent": "head", "image": "eyes_closed.png", "pos": [cx, cy - 25],
         "bind": {"opacity": {"param": "blink", "gain": 1.0}}},
        {"id": "brows", "parent": "head", "image": "brows.png", "pos": [cx, cy - 70],
         "bind": {"ty": {"param": "brow_raise", "gain": -14}}},
        {"id": "mouth", "parent": "head", "pos": [cx, cy + 95], "state": "mouth",
         "states": {"default": "mouth_small.png", **{k: f"mouth_{k}.png" for k in MOUTHS}},
         "bind": {"sy": {"param": "smile", "gain": -0.1}, "sx": {"param": "smile", "gain": 0.15}}}]}
    (base / "avatar.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return base
