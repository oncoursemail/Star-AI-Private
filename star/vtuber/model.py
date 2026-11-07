"""The avatar model: a layered 2D puppet read from a folder (avatar.json + PNG layers). The art is a setting, not code.

Any painted character that is cut into layers can be driven: head, eyes open/closed, five mouth shapes, hair, tail.
Nothing here knows what the character looks like; the manifest says which image to show and how each pose
parameter moves it. Pose parameters are the names in rig.Pose.params(): head_x, head_y, head_roll, body_lean,
breath, blink, talk, smile, brow_raise, gaze_x, hair_sway, ear_left, ear_right, tail_sway, shoulder_lift, v_aa ..
v_oh, and the text values face, viseme, mouth (closed|small|aa|ih|ou|ee|oh).

avatar.json
  {"name": "...", "size": [1280, 720], "background": [18, 18, 24] | "backdrop.png",
   "layers": [                                   # drawn in this order, first = back
     {"id": "head",                              # no image = a group: its movement carries its children
      "pos": [640, 360], "bind": {"tx": {"param": "head_x", "gain": 40}, "rot": {"param": "head_roll", "gain": 6}}},
     {"id": "face", "parent": "head", "pos": [640, 360], "pivot": [256, 256], "scale": 1.0,
      "states": {"default": "face.png", "happy": "face_happy.png"}, "state": "face"},
     {"id": "blink", "parent": "head", "image": "eyes_closed.png", "pos": [640, 360],
      "bind": {"opacity": {"param": "blink", "gain": 1}}, "when": {"face": ["idle", "happy"]}},
     {"id": "mouth", "parent": "head", "pos": [640, 420], "state": "mouth",
      "states": {"closed": "m_closed.png", "aa": "m_aa.png", "default": "m_small.png"}}]}
  pos        where the pivot of the layer sits on the canvas; pivot is in the layer's own pixels (default centre)
  bind       channel -> {"param", "gain", "offset"}: tx, ty (pixels), rot (degrees), sx, sy (scale change, 0.02 = +2 %),
             opacity (0..1, absolute). Several channels per layer.
  states     image per value of the parameter named in "state"; a missing value falls back (aa/ih/ou/ee/oh -> "open"
             -> "small" -> "default").
  when       {"face": [...]} show the layer only for those values (any text parameter)

Drawing is Pillow on the CPU, no GPU, so the card stays free for her game and her voice models. Quality "high" samples
every layer at 2x and averages down (smooth edges); "fast" samples once (jagged, about 3x cheaper); the camera drops to
"fast" by itself when frames take too long. render() returns an RGB uint8 array ready for a virtual camera.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .rig import LiveRig, Pose

MAX_LAYERS = 64
MAX_PIXELS = 64 * 1024 * 1024          # all layer images together, decoded
MAX_SIDE = 4096
CHANNELS = ("tx", "ty", "rot", "sx", "sy", "opacity")
TEXT_PARAMS = ("face", "viseme", "mouth")
FALLBACK = {"aa": ("open", "small"), "ih": ("open", "small"), "ou": ("open", "small"), "ee": ("open", "small"),
            "oh": ("open", "small"), "open": ("small",), "small": (), "closed": ()}


class ModelError(ValueError):
    pass


def numeric_params() -> set[str]:
    """The names a binding may use (checked when the model loads, so a typo is an error, not a motionless avatar)."""
    return {k for k in params_of(LiveRig().neutral(0.0)) if k not in TEXT_PARAMS}


def params_of(pose: Pose) -> dict:
    values = pose.params()
    opening = pose.mouth_open
    values["mouth"] = "closed" if opening < 0.06 else ("small" if opening < 0.3 else pose.viseme)
    return values


def _matrix(tx: float, ty: float, deg: float, sx: float, sy: float, px: float, py: float, ox: float, oy: float):
    """T(o + t) . R(deg) . S(sx, sy) . T(-p) as a 3x3, row-major tuples; (px, py) pivot, (ox, oy) pos."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    a, b, d, e = c * sx, -s * sy, s * sx, c * sy
    return ((a, b, ox + tx - (a * px + b * py)), (d, e, oy + ty - (d * px + e * py)), (0.0, 0.0, 1.0))


def _mul(m, n):
    return tuple(tuple(sum(m[i][k] * n[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _inverse(m):
    (a, b, c), (d, e, f), _ = m
    det = a * e - b * d
    if abs(det) < 1e-9:
        return None
    ia, ib, id_, ie = e / det, -b / det, -d / det, a / det
    return ((ia, ib, -(ia * c + ib * f)), (id_, ie, -(id_ * c + ie * f)), (0.0, 0.0, 1.0))


class Sprite:
    """One layer image: straight-alpha RGBA for the fast path, premultiplied 2x copy for the smooth path (premultiplied
    so averaging never drags the colour of transparent pixels into an edge)."""

    def __init__(self, rgba: Image.Image) -> None:
        self.rgba = rgba
        self.width, self.height = rgba.size
        self.double = rgba.convert("RGBa").resize((self.width * 2, self.height * 2), Image.Resampling.BILINEAR)


@dataclass
class Layer:
    id: str
    parent: str | None
    pos: tuple
    pivot: tuple | None
    scale: float
    images: dict
    state: str | None
    bind: dict
    when: dict
    opacity: float = 1.0
    order: int = 0


@dataclass
class AvatarModel:
    name: str
    size: tuple
    background: Image.Image
    layers: list
    base: Path | None = None
    quality: str = "high"               # "high" | "fast"
    _by_id: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {layer.id: layer for layer in self.layers}

    # -- rendering -------------------------------------------------------------------------------------------
    def _local(self, layer: Layer, values: dict):
        d = {c: 0.0 for c in CHANNELS if c != "opacity"}
        for channel, rule in layer.bind.items():
            if channel == "opacity":
                continue
            d[channel] = rule.get("offset", 0.0) + rule["gain"] * float(values[rule["param"]])
        sx = layer.scale * (1.0 + d["sx"])
        sy = layer.scale * (1.0 + d["sy"])
        if layer.images:
            image = next(iter(layer.images.values()))
            px, py = layer.pivot if layer.pivot is not None else (image.width / 2, image.height / 2)
        else:
            px, py = layer.pos
        return _matrix(d["tx"], d["ty"], d["rot"], sx, sy, px, py, layer.pos[0], layer.pos[1])

    def _total(self, layer: Layer, values: dict, cache: dict):
        if layer.id in cache:
            return cache[layer.id]
        m = self._local(layer, values)
        if layer.parent:
            m = _mul(self._total(self._by_id[layer.parent], values, cache), m)
        cache[layer.id] = m
        return m

    def _pick(self, layer: Layer, values: dict) -> Sprite | None:
        if not layer.images:
            return None
        key = str(values.get(layer.state, "")) if layer.state else "default"
        if key in layer.images:
            return layer.images[key]
        for alt in FALLBACK.get(key, ()):
            if alt in layer.images:
                return layer.images[alt]
        return layer.images.get("default")

    def render(self, pose: Pose) -> np.ndarray:
        values = params_of(pose)
        canvas = self.background.copy()
        cache: dict = {}
        width, height = self.size
        for layer in self.layers:
            if any(str(values.get(p)) not in [str(v) for v in allowed] for p, allowed in layer.when.items()):
                continue
            image = self._pick(layer, values)
            if image is None:
                continue
            opacity = layer.opacity
            rule = layer.bind.get("opacity")
            if rule:
                opacity *= min(1.0, max(0.0, rule.get("offset", 0.0) + rule["gain"] * float(values[rule["param"]])))
            if opacity <= 0.004:
                continue
            m = self._total(layer, values, cache)
            inv = _inverse(m)
            if inv is None:
                continue
            corners = [(0, 0), (image.width, 0), (0, image.height), (image.width, image.height)]
            xs = [m[0][0] * x + m[0][1] * y + m[0][2] for x, y in corners]
            ys = [m[1][0] * x + m[1][1] * y + m[1][2] for x, y in corners]
            x0, y0 = max(0, int(math.floor(min(xs)))), max(0, int(math.floor(min(ys))))
            x1, y1 = min(width, int(math.ceil(max(xs)))), min(height, int(math.ceil(max(ys))))
            if x1 <= x0 or y1 <= y0:
                continue
            a, b, c = inv[0]
            d, e, f = inv[1]
            if self.quality == "fast":
                piece = image.rgba.transform((x1 - x0, y1 - y0), Image.Transform.AFFINE,
                                             (a, b, a * x0 + b * y0 + c, d, e, d * x0 + e * y0 + f),
                                             resample=Image.Resampling.NEAREST)
            else:
                piece = image.double.transform((2 * (x1 - x0), 2 * (y1 - y0)), Image.Transform.AFFINE,
                                               (a, b, 2 * (a * x0 + b * y0 + c), d, e, 2 * (d * x0 + e * y0 + f)),
                                               resample=Image.Resampling.NEAREST).reduce(2).convert("RGBA")
            if opacity < 0.996:
                alpha = piece.getchannel("A").point([int(i * opacity) for i in range(256)])
                piece.putalpha(alpha)
            canvas.alpha_composite(piece, (x0, y0))
        return np.asarray(canvas.convert("RGB"), dtype=np.uint8)


# -- loading --------------------------------------------------------------------------------------------------
def _png(base: Path, name: str, budget: list) -> Image.Image:
    path = (base / name).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise ModelError(f"{name!r} is outside the avatar folder") from exc
    if not path.is_file():
        raise ModelError(f"image not found: {name}")
    with Image.open(path) as opened:
        if max(opened.size) > MAX_SIDE:
            raise ModelError(f"{name} is larger than {MAX_SIDE} px")
        budget[0] += opened.width * opened.height
        if budget[0] > MAX_PIXELS:
            raise ModelError("the layers together are too large")
        return opened.convert("RGBA")


def _pair(value, what: str) -> tuple:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        raise ModelError(f"{what} must be [x, y]")
    return float(value[0]), float(value[1])


def load_manifest(spec: dict, base: Path) -> AvatarModel:
    base = Path(base)
    size = tuple(int(v) for v in _pair(spec.get("size", [1280, 720]), "size"))
    if not (64 <= size[0] <= 3840 and 64 <= size[1] <= 2160):
        raise ModelError("size out of range")
    budget = [0]
    bg = spec.get("background", [20, 20, 28])
    if isinstance(bg, str):
        backdrop = _png(base, bg, budget).resize(size, Image.Resampling.BILINEAR)
    else:
        if not isinstance(bg, list) or len(bg) != 3 or not all(isinstance(v, int) and 0 <= v <= 255 for v in bg):
            raise ModelError("background must be [r, g, b] or an image name")
        backdrop = Image.new("RGBA", size, (*bg, 255))
    valid = numeric_params()
    layers: list[Layer] = []
    raw_layers = spec.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers or len(raw_layers) > MAX_LAYERS:
        raise ModelError(f"layers must be a list of 1 to {MAX_LAYERS}")
    for index, raw in enumerate(raw_layers):
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise ModelError(f"layer {index} needs an id")
        images: dict = {}
        if "image" in raw:
            images["default"] = Sprite(_png(base, str(raw["image"]), budget))
        for key, name in (raw.get("states") or {}).items():
            images[str(key)] = Sprite(_png(base, str(name), budget))
        bind = {}
        for channel, rule in (raw.get("bind") or {}).items():
            if channel not in CHANNELS:
                raise ModelError(f"layer {raw['id']}: unknown channel {channel!r}")
            if not isinstance(rule, dict) or rule.get("param") not in valid:
                raise ModelError(f"layer {raw['id']}: unknown parameter {rule.get('param') if isinstance(rule, dict) else rule!r}")
            gain, offset = rule.get("gain", 1.0), rule.get("offset", 0.0)
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (gain, offset)):
                raise ModelError(f"layer {raw['id']}: gain and offset must be numbers")
            bind[channel] = {"param": rule["param"], "gain": float(gain), "offset": float(offset)}
        state = raw.get("state")
        if state is not None and state not in TEXT_PARAMS:
            raise ModelError(f"layer {raw['id']}: state must be one of {TEXT_PARAMS}")
        when = raw.get("when") or {}
        if not isinstance(when, dict) or any(k not in TEXT_PARAMS or not isinstance(v, list) for k, v in when.items()):
            raise ModelError(f"layer {raw['id']}: bad 'when'")
        pivot = _pair(raw["pivot"], "pivot") if "pivot" in raw else None
        layers.append(Layer(raw["id"], raw.get("parent"), _pair(raw.get("pos", [size[0] / 2, size[1] / 2]), "pos"),
                            pivot, float(raw.get("scale", 1.0)), images, state, bind, when,
                            float(raw.get("opacity", 1.0)), index))
    ids = {layer.id for layer in layers}
    if len(ids) != len(layers):
        raise ModelError("layer ids must be unique")
    order = {layer.id: i for i, layer in enumerate(layers)}
    for layer in layers:
        if layer.parent is not None and (layer.parent not in ids or order[layer.parent] >= order[layer.id]):
            raise ModelError(f"layer {layer.id}: parent must be an earlier layer")
    return AvatarModel(str(spec.get("name", "avatar")), size, backdrop, layers, base)


# -- the StarFace expression set (the approved mascot art, used as it is) --------------------------------------
STARFACE_STATES = {"default": "normal.png", "idle": "normal.png", "listening": "happy.png", "thinking": "thinking.png",
                   "writing": "focused.png", "happy": "happy.png", "oops": "nervous.png", "stopped": "surprised.png",
                   "looking": "puppy-eyes.png"}        # same mapping as frontend/src/StarFace.tsx
STARFACE_BLINKS = ["idle", "listening", "looking"]      # faces whose eyes line up with content.png (see StarFace.tsx)


def find_starface_dir() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [os.environ.get("STAR_FACES_DIR", "")]
    for up in range(2, 6):
        root = here.parents[up] if len(here.parents) > up else None
        if root:
            candidates += [str(root / "frontend" / "public" / "assets" / "mascot" / "faces"),
                           str(root / "assets" / "mascot" / "faces"),
                           str(root / "frontend" / "dist" / "assets" / "mascot" / "faces")]
    return next((Path(c) for c in candidates if c and (Path(c) / "normal.png").is_file()), None)


def starface_spec(size=(1280, 720)) -> tuple[dict, Path]:
    """The mascot's expression images as a model: whole-face swaps for the mood, the closed-eye face as the blink, a
    gentle squash on the voice. The faces have their mouth painted in, so this pack cannot show visemes: it moves
    with her voice instead. A layered model with mouth shapes does real lip-sync."""
    faces = find_starface_dir()
    if faces is None:
        raise ModelError("the StarFace images were not found (set STAR_FACES_DIR to .../mascot/faces)")
    cx, cy = size[0] / 2, size[1] / 2 + 20
    scale = size[1] * 0.92 / 512
    spec = {"name": "StarFace", "size": list(size), "background": [22, 22, 30], "layers": [
        {"id": "head", "pos": [cx, cy + 256 * scale], "bind": {
            "tx": {"param": "head_x", "gain": 60}, "ty": {"param": "breath", "gain": -5}, "rot": {"param": "head_roll", "gain": 5},
            "sx": {"param": "talk", "gain": -0.012}, "sy": {"param": "talk", "gain": 0.035}}},
        {"id": "face", "parent": "head", "pos": [cx, cy], "pivot": [256, 256], "scale": scale,
         "states": dict(STARFACE_STATES), "state": "face"},
        {"id": "blink", "parent": "head", "image": "content.png", "pos": [cx, cy], "pivot": [256, 256], "scale": scale,
         "bind": {"opacity": {"param": "blink", "gain": 1.6}}, "when": {"face": STARFACE_BLINKS}}]}
    return spec, faces


def load_model(source: str | os.PathLike | None, *, size=(1280, 720)) -> AvatarModel:
    """`source` is the vtuber_model setting: a folder with avatar.json, the avatar.json itself, "starface" (the
    mascot's expression set), or "placeholder" (a plain generated test character, see placeholder.py)."""
    text = str(source or "starface")
    if text == "starface":
        spec, base = starface_spec(size)
        return load_manifest(spec, base)
    if text == "placeholder":
        from .placeholder import build_placeholder
        folder = build_placeholder()
        return load_manifest(json.loads((folder / "avatar.json").read_text(encoding="utf-8")), folder)
    path = Path(text)
    manifest = path / "avatar.json" if path.is_dir() else path
    try:
        spec = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelError(f"cannot read {manifest}: {exc}") from exc
    return load_manifest(spec, manifest.parent)
