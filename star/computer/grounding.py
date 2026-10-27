"""Vision grounding: find where to click from a screenshot when the app's accessibility tree is empty or lacks the
control ("the red heart icon", "the play button in the video"). Behind one interface, `Grounder.locate(image, query)`,
so the model is a setting (settings.py `grounder`) and tests use a fake.

`VlmGrounder` talks to any OpenAI-compatible vision endpoint (llama.cpp server with its mmproj file, vLLM, Ollama, LM
Studio, the brain): UI-TARS-1.5-7B / UI-TARS-2B, Qwen3-VL, ShowUI, OS-Atlas and UGround all answer "where is X" with
a point, but they disagree on the coordinate system (original pixels, the model's resized image, 0-1000, 0-1).
`detect_format` settles that by measurement: show the model a synthetic screen with known button positions and keep
the convention with the smallest error, instead of trusting a recollection of each model card.
`MODELS` lists what the installer can fetch (sizes and scores: docs/research/computer-use-20261026.md); nothing is
downloaded by this package.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import json
import math
import re
import time
import urllib.request
from typing import Callable, Protocol

FORMATS = ("pixels", "resized", "unit1000", "unit1")
POINT_PROMPT = ("Output only the coordinate of one point in your response. "
                "What element matches the following task: {query}")


@dataclass(frozen=True)
class GroundingModel:
    name: str
    hf_id: str
    params_b: float
    fmt: str                  # usual coordinate system (confirmed on the PC by detect_format, not assumed)
    gguf_q4_gb: float         # weights file at 4-bit; plus a vision projector file of a few hundred MB
    note: str


MODELS = {m.name: m for m in (
    GroundingModel("ui-tars-1.5-7b", "ByteDance-Seed/UI-TARS-1.5-7B", 7.0, "resized", 4.4,
                   "Apache-2.0; ScreenSpot-Pro 49.6, OSWorld 27.5 (model card); Q4_K_M ~4.4 GB: tight beside a game"),
    GroundingModel("ui-tars-2b", "ByteDance-Seed/UI-TARS-2B-SFT", 2.0, "unit1000", 1.5,
                   "Apache-2.0; ScreenSpot-Pro 27.7, ScreenSpot-v2 84.7 (model card); small enough for game mode"),
    GroundingModel("qwen3-vl-4b", "Qwen/Qwen3-VL-4B-Instruct", 4.0, "unit1000", 2.8,
                   "Apache-2.0; general VLM with GUI grounding; GUI fine-tunes of it report ScreenSpot-Pro 60+"),
    GroundingModel("qwen3-vl-2b", "Qwen/Qwen3-VL-2B-Instruct", 2.0, "unit1000", 1.5,
                   "Apache-2.0; base ScreenSpot-Pro 43.3 as measured by a third party"),
    GroundingModel("showui-2b", "showlab/ShowUI-2B", 2.0, "unit1", 1.5,
                   "ScreenSpot 75.1 (paper); weak on high-resolution screens"),
)}


class Grounder(Protocol):
    def locate(self, image, query: str) -> "Grounded | None": ...


@dataclass(frozen=True)
class Grounded:
    x: int
    y: int                    # screen pixels of the image given to locate()
    raw: str = ""
    seconds: float = 0.0


def smart_resize(height: int, width: int, factor: int = 28, min_pixels: int = 56 * 56,
                 max_pixels: int = 16384 * 28 * 28) -> tuple[int, int]:
    """The image size Qwen2/2.5-VL-family models look at (multiples of 28, pixel budget)."""
    h = max(factor, round(height / factor) * factor)
    w = max(factor, round(width / factor) * factor)
    if h * w > max_pixels:
        beta = math.sqrt(height * width / max_pixels)
        h, w = max(factor, math.floor(height / beta / factor) * factor), max(factor, math.floor(width / beta / factor) * factor)
    elif h * w < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h, w = math.ceil(height * beta / factor) * factor, math.ceil(width * beta / factor) * factor
    return h, w


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_point(text: str) -> tuple[float, float] | None:
    """The first point in a model's answer: `<|box_start|>(x,y)<|box_end|>`, `(x, y)`, `[x, y]`, `<point>x y</point>`,
    `{"coordinate": [x, y]}`, `start_box='(x,y)'`; a box of four numbers gives its centre."""
    text = str(text or "")
    for match in re.finditer(r"\{.*?\}", text, re.S):
        try:
            data = json.loads(match.group(0))
        except ValueError:
            continue
        for key in ("coordinate", "point", "coordinates", "box", "bbox"):
            if isinstance(data.get(key), list):
                numbers = [float(v) for v in data[key] if isinstance(v, (int, float))]
                return _from_numbers(numbers)
        if isinstance(data.get("x"), (int, float)) and isinstance(data.get("y"), (int, float)):
            return float(data["x"]), float(data["y"])
    body = re.sub(r"<\|?[a-z_/]+\|?>", " ", text)                   # drop tags like <|box_start|>, keep the numbers
    return _from_numbers([float(n) for n in _NUM.findall(body)])


def _from_numbers(numbers: list[float]) -> tuple[float, float] | None:
    if len(numbers) >= 4:
        return (numbers[0] + numbers[2]) / 2, (numbers[1] + numbers[3]) / 2
    return (numbers[0], numbers[1]) if len(numbers) >= 2 else None


def to_pixels(point: tuple[float, float], size: tuple[int, int], fmt: str) -> tuple[int, int]:
    """Convert a model's point to pixels of an image of `size` (width, height) under one coordinate convention."""
    w, h = size
    x, y = point
    if fmt == "resized":
        rh, rw = smart_resize(h, w)
        x, y = x * w / rw, y * h / rh
    elif fmt == "unit1000":
        x, y = x * w / 1000, y * h / 1000
    elif fmt == "unit1":
        x, y = x * w, y * h
    elif fmt != "pixels":
        raise ValueError(f"unknown coordinate format {fmt!r}")
    return int(round(min(max(x, 0), w - 1))), int(round(min(max(y, 0), h - 1)))


def detect_format(raw_points: list[tuple[float, float]], truth: list[tuple[int, int]],
                  size: tuple[int, int]) -> tuple[str, dict[str, float]]:
    """The convention under which the model's raw points land closest to the known positions (mean pixel error)."""
    errors = {}
    for fmt in FORMATS:
        pts = [to_pixels(p, size, fmt) for p in raw_points]
        errors[fmt] = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(pts, truth)) / max(1, len(truth))
    return min(errors, key=lambda k: errors[k]), errors


def encode_png(image, max_side: int) -> tuple[str, tuple[int, int]]:
    """Base64 PNG of a PIL image scaled so its longer side is at most `max_side`; also the size actually sent."""
    from PIL import Image
    w, h = image.size
    scale = min(1.0, max_side / max(w, h))
    sent = image if scale >= 1.0 else image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    sent.convert("RGB").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii"), sent.size


class VlmGrounder:
    """locate() through an OpenAI-compatible vision chat endpoint. `fmt` is a coordinate convention or "auto"
    (then call calibrate() once; until then "pixels" is assumed)."""

    def __init__(self, url: str, model: str, *, fmt: str = "pixels", max_side: int = 1280, timeout_s: float = 60.0,
                 api_key: str = "", opener: Callable = urllib.request.urlopen, prompt: str = POINT_PROMPT) -> None:
        self.url = url.rstrip("/")
        self.endpoint = self.url + ("/chat/completions" if self.url.endswith("/v1") else "/v1/chat/completions")
        self.model, self.fmt, self.max_side, self.timeout_s = model, "pixels" if fmt == "auto" else fmt, max_side, timeout_s
        self.api_key, self.opener, self.prompt = api_key, opener, prompt

    def ask(self, image, query: str) -> tuple[str, tuple[int, int], float]:
        b64, sent = encode_png(image, self.max_side)
        payload = {"model": self.model, "temperature": 0, "max_tokens": 96, "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            {"type": "text", "text": self.prompt.format(query=query)}]}]}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                                         headers=headers)
        started = time.perf_counter()
        with self.opener(request, timeout=self.timeout_s) as response:
            reply = json.loads(response.read().decode("utf-8"))
        return str(reply["choices"][0]["message"].get("content") or ""), sent, time.perf_counter() - started

    def locate(self, image, query: str) -> Grounded | None:
        raw, sent, seconds = self.ask(image, query)
        point = parse_point(raw)
        if point is None:
            return None
        x, y = to_pixels(point, sent, self.fmt)
        return Grounded(round(x * image.size[0] / sent[0]), round(y * image.size[1] / sent[1]), raw[:120], seconds)

    def calibrate(self, size: tuple[int, int] = (1280, 720)) -> tuple[str, dict[str, float]]:
        """Pick the coordinate convention by measurement on a synthetic screen with six labelled buttons. Returns the
        convention (also stored in self.fmt) and each convention's mean error in pixels."""
        image, truth = synthetic_screen(size)
        raws = []
        for label, _ in truth:
            raw, _sent, _seconds = self.ask(image, f"the button labelled {label}")
            raws.append(parse_point(raw) or (0.0, 0.0))
        sent_size = encode_png(image, self.max_side)[1]
        scale = sent_size[0] / image.size[0]
        fmt, errors = detect_format(raws, [(round(x * scale), round(y * scale)) for _, (x, y) in truth], sent_size)
        self.fmt = fmt
        return fmt, errors


def synthetic_screen(size: tuple[int, int] = (1280, 720)):
    """A plain screen with six labelled buttons at known places; returns (image, [(label, (x, y))])."""
    from PIL import Image, ImageDraw
    w, h = size
    image = Image.new("RGB", size, (240, 240, 240))
    draw = ImageDraw.Draw(image)
    labels = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
    spots = [(0.2, 0.2), (0.7, 0.15), (0.45, 0.45), (0.15, 0.75), (0.8, 0.6), (0.55, 0.85)]
    truth = []
    for label, (fx, fy) in zip(labels, spots):
        cx, cy = int(w * fx), int(h * fy)
        draw.rectangle((cx - 60, cy - 20, cx + 60, cy + 20), fill=(30, 90, 200), outline=(0, 0, 0))
        draw.text((cx - 22, cy - 6), label, fill=(255, 255, 255))
        truth.append((label, (cx, cy)))
    return image, truth
