"""Fast perception: frame -> detections (+ new chat lines) in a few milliseconds, so reflexes can run at 10-30 Hz.

ColorDetector   numpy only, no model: finds blobs of configured colours on a coarse grid (obby platforms, neon
                checkpoints, lava/kill bricks, health bars). ~5-8 ms at 720p-1080p on one CPU core (measured with bench.py).
YoloDetector    a YOLO-class ONNX detector (YOLOv8/11 output layout) through onnxruntime on the GPU (CUDA or
                DirectML provider) for games where colour is not enough; needs a model trained or fine-tuned for
                that game. Decoding + NMS here, tested with a fake session.
ChatOCR         reads the game's chat box with an OCR engine (RapidOCR/PaddleOCR-compatible callable), splits
                "name: text" lines and returns only lines not seen before. Chat text is untrusted data.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Callable

import numpy as np

from .percept import ChatLine, Detection, Percept

__all__ = ["ChatLine", "ChatOCR", "ColorDetector", "Detection", "Percept", "YoloDetector"]


class ColorDetector:
    """classes: {label: ((r_lo, g_lo, b_lo), (r_hi, g_hi, b_hi))}. The frame is sampled every `stride` pixels
    (0 = about 320 samples across, whatever the resolution); a grid cell counts when at least `min_cell_frac` of its samples match; touching cells form one detection."""

    def __init__(self, classes: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]], *, stride: int = 0,
                 grid: tuple[int, int] = (32, 18), min_cell_frac: float = 0.25, min_cells: int = 1) -> None:
        self.classes = {k: (np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8)) for k, (lo, hi) in classes.items()}
        self.stride, self.grid, self.min_cell_frac, self.min_cells = stride, grid, min_cell_frac, min_cells

    def detect(self, image: np.ndarray) -> list[Detection]:
        height, width = image.shape[:2]
        stride = self.stride or max(1, round(width / 320))
        small = image[::stride, ::stride, :3]
        gx, gy = self.grid
        sh, sw = (small.shape[0] // gy) * gy, (small.shape[1] // gx) * gx
        small = small[:sh, :sw]
        cell_h, cell_w = sh // gy, sw // gx
        if not cell_h or not cell_w:
            return []                                      # frame smaller than the grid
        out: list[Detection] = []
        for label, (lo, hi) in self.classes.items():
            mask = np.all((small >= lo) & (small <= hi), axis=2)
            frac = mask.reshape(gy, cell_h, gx, cell_w).mean(axis=(1, 3))
            cells = frac >= self.min_cell_frac
            for comp in _components(cells):
                if len(comp) < self.min_cells:
                    continue
                rows = [r for r, _ in comp]
                cols = [c for _, c in comp]
                sx, sy = width / gx, height / gy
                coverage = float(sum(frac[r, c] for r, c in comp)) / (gx * gy)
                out.append(Detection(label, min(cols) * sx, min(rows) * sy, (max(cols) - min(cols) + 1) * sx,
                                     (max(rows) - min(rows) + 1) * sy, 1.0, coverage))
        return out


def _components(cells: np.ndarray) -> list[list[tuple[int, int]]]:
    """4-connected components of a small boolean grid (32 x 18 = 576 cells: a plain BFS is microseconds)."""
    seen = np.zeros_like(cells, dtype=bool)
    rows, cols = cells.shape
    comps = []
    for r0, c0 in zip(*np.nonzero(cells)):
        if seen[r0, c0]:
            continue
        stack, comp = [(int(r0), int(c0))], []
        seen[r0, c0] = True
        while stack:
            r, c = stack.pop()
            comp.append((r, c))
            for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= nr < rows and 0 <= nc < cols and cells[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    stack.append((nr, nc))
        comps.append(comp)
    return comps


class YoloDetector:
    """A YOLOv8/YOLO11 ONNX model: input 1x3xSxS float RGB 0..1 (letterboxed), output 1 x (4 + classes) x N."""

    def __init__(self, session, names: list[str], *, size: int = 640, conf: float = 0.35, iou: float = 0.5) -> None:
        self.session, self.names, self.size, self.conf, self.iou = session, names, size, conf, iou
        self._input = session.get_inputs()[0].name

    @classmethod
    def load(cls, model_path: str, names: list[str], **kwargs) -> "YoloDetector":  # pragma: no cover - needs a model
        import onnxruntime as ort
        wanted = ("TensorrtExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
        providers = [p for p in wanted if p in ort.get_available_providers()]
        return cls(ort.InferenceSession(model_path, providers=providers), names, **kwargs)

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float, int, int]:
        from PIL import Image
        height, width = image.shape[:2]
        scale = self.size / max(height, width)
        new_w, new_h = round(width * scale), round(height * scale)
        resized = np.asarray(Image.fromarray(image[:, :, :3]).resize((new_w, new_h), Image.BILINEAR))
        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        pad_x, pad_y = (self.size - new_w) // 2, (self.size - new_h) // 2
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
        return canvas, scale, pad_x, pad_y

    def detect(self, image: np.ndarray) -> list[Detection]:
        canvas, scale, pad_x, pad_y = self._letterbox(image)
        blob = (canvas.transpose(2, 0, 1)[None].astype(np.float32)) / 255.0
        raw = np.asarray(self.session.run(None, {self._input: blob})[0])[0]     # (4 + C, N)
        return self.decode(raw, scale, pad_x, pad_y, image.shape[1], image.shape[0])

    def decode(self, raw: np.ndarray, scale: float, pad_x: int, pad_y: int, width: int, height: int) -> list[Detection]:
        boxes, scores = raw[:4].T, raw[4:].T
        cls = scores.argmax(axis=1)
        best = scores[np.arange(len(cls)), cls]
        keep = best >= self.conf
        boxes, cls, best = boxes[keep], cls[keep], best[keep]
        x1 = (boxes[:, 0] - boxes[:, 2] / 2 - pad_x) / scale
        y1 = (boxes[:, 1] - boxes[:, 3] / 2 - pad_y) / scale
        w, h = boxes[:, 2] / scale, boxes[:, 3] / scale
        out = []
        for i in _nms(x1, y1, w, h, best, cls, self.iou):
            label = self.names[cls[i]] if cls[i] < len(self.names) else str(int(cls[i]))
            out.append(Detection(label, float(x1[i]), float(y1[i]), float(w[i]), float(h[i]), float(best[i]),
                                 float(w[i] * h[i] / (width * height))))
        return out


def _nms(x, y, w, h, score, cls, iou_limit: float) -> list[int]:
    order = list(np.argsort(-score))
    kept: list[int] = []
    while order:
        i = order.pop(0)
        kept.append(int(i))
        rest = []
        for j in order:
            if cls[j] != cls[i]:
                rest.append(j)
                continue
            ix = max(0.0, min(x[i] + w[i], x[j] + w[j]) - max(x[i], x[j]))
            iy = max(0.0, min(y[i] + h[i], y[j] + h[j]) - max(y[i], y[j]))
            inter = ix * iy
            union = w[i] * h[i] + w[j] * h[j] - inter
            if union <= 0 or inter / union <= iou_limit:
                rest.append(j)
        order = rest
    return kept


_LINE = re.compile(r"^\s*[\[(]?([A-Za-z0-9_ .\-]{2,24}?)[\])]?\s*:\s*(.+)$")


class ChatOCR:
    """`engine(image) -> [(box, text, score), ...]` (RapidOCR's result rows). `region` is (x0, y0, x1, y1) as
    fractions of the frame (Roblox's chat box is top-left). Returns only new lines, oldest first."""

    def __init__(self, engine: Callable, region: tuple[float, float, float, float] = (0.0, 0.0, 0.4, 0.35), *,
                 min_score: float = 0.6, memory: int = 200) -> None:
        self.engine, self.region, self.min_score = engine, region, min_score
        self._seen: deque[tuple[str, str]] = deque(maxlen=memory)

    def read(self, image: np.ndarray) -> list[ChatLine]:
        height, width = image.shape[:2]
        x0, y0, x1, y1 = self.region
        crop = image[int(y0 * height):int(y1 * height), int(x0 * width):int(x1 * width)]
        rows = self.engine(crop) or []
        rows = sorted((r for r in rows if len(r) >= 3 and float(r[2]) >= self.min_score), key=lambda r: _top(r[0]))
        fresh = []
        for _, text, _score in rows:
            match = _LINE.match(str(text))
            if not match:
                continue
            line = (match.group(1).strip(), match.group(2).strip())
            if line in self._seen:
                continue
            self._seen.append(line)
            fresh.append(ChatLine(*line))
        return fresh


def _top(box) -> float:
    try:
        return float(min(point[1] for point in box))
    except (TypeError, ValueError, IndexError):
        return 0.0
