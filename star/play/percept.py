"""What the fast layer sees in one frame: detections and new chat lines (no numpy needed to read them)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Detection:
    label: str
    x: float                           # left, frame pixels
    y: float                           # top
    w: float
    h: float
    score: float = 1.0
    area_frac: float = 0.0             # share of the frame the object covers

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class ChatLine:
    author: str
    text: str


@dataclass
class Percept:
    frame_index: int
    t_capture: float
    width: int
    height: int
    detections: list[Detection] = field(default_factory=list)
    chat: list[ChatLine] = field(default_factory=list)
    stage_ms: dict = field(default_factory=dict)

    def of(self, label: str) -> list[Detection]:
        return [d for d in self.detections if d.label == label]
