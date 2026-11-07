"""Bounded, untrusted VLM candidate observations from one authorized game frame.

A vision model may *suggest* that a UI element or scene changed. Its confidence
is not calibrated proof, game-state verification, or permission to take action.
Only a trusted capture host supplies the pixel dimensions and timestamp.
Free-form captions, URLs and instructions are deliberately never transported.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

VISUAL_KINDS = frozenset({
    "hud_change", "scene_change", "player_motion", "object_appeared",
    "menu_change", "hazard_indicator", "unknown",
})
VISUAL_REGIONS = frozenset({"world", "hud", "focus_0", "focus_1", "focus_2", "focus_3"})
MAX_FINDINGS = 4
MAX_PIXELS = 3840 * 2160


def _finite_number(value: object, *, low: float, high: float) -> float:
    if type(value) not in (int, float):
        raise ValueError("numeric visual evidence field required")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError("visual evidence numeric range exceeded")
    return result


@dataclass(frozen=True)
class VisualFinding:
    """A model-suggested categorical cue, never an independently verified fact."""

    kind: str
    region: str
    confidence: float
    # Normalized (left, top, right, bottom) in 0..1000 coordinates.
    box: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in VISUAL_KINDS:
            raise ValueError("unrecognized visual cue")
        if type(self.region) is not str or self.region not in VISUAL_REGIONS:
            raise ValueError("unrecognized host-defined region")
        _finite_number(self.confidence, low=0, high=1)
        if self.box is not None:
            if (type(self.box) is not tuple or len(self.box) != 4
                    or any(type(value) is not int or not 0 <= value <= 1000
                           for value in self.box)
                    or self.box[0] >= self.box[2] or self.box[1] >= self.box[3]):
                raise ValueError("invalid normalized visual box")


@dataclass(frozen=True)
class VisualPacket:
    """Only bounded categorical evidence can leave the model worker.

    The capture host must compare these fields with the exact frame it passed
    to the worker. Merely constructing this object does not establish that
    any game state changed, an action succeeded, or a person was seen.
    """

    captured_ms: float
    width: int
    height: int
    findings: tuple[VisualFinding, ...]

    def __post_init__(self) -> None:
        _finite_number(self.captured_ms, low=0, high=1e13)
        if (type(self.width) is not int or type(self.height) is not int
                or not 9 <= self.width <= 8192 or not 8 <= self.height <= 8192
                or self.width * self.height > MAX_PIXELS):
            raise ValueError("invalid authorized frame dimensions")
        if (type(self.findings) is not tuple
                or not 1 <= len(self.findings) <= MAX_FINDINGS
                or any(type(x) is not VisualFinding for x in self.findings)):
            raise ValueError("expected 1..4 categorical findings")
        keys = [(x.kind, x.region) for x in self.findings]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate visual findings")


def parse_visual_packet(
    payload: object, *, captured_ms: float, width: int, height: int,
) -> VisualPacket:
    """Validate a tiny VLM JSON-style result; discard arbitrary model text.

    Invoke only inside the trusted synchronous worker after parsing JSON.
    Timestamp and image geometry MUST come from CapturedVisionFrame, never
    from user/viewer/model output. This is a schema/parser, NOT model inference.
    """
    if type(payload) is not dict or set(payload) != {"findings"}:
        raise ValueError("only findings schema is accepted")
    raw = payload["findings"]
    if type(raw) is not list or not 1 <= len(raw) <= MAX_FINDINGS:
        raise ValueError("expected 1..4 findings")
    parsed: list[VisualFinding] = []
    for item in raw:
        if type(item) is not dict or set(item) not in (
            {"kind", "region", "confidence"},
            {"kind", "region", "confidence", "box"},
        ):
            raise ValueError("unrecognized VLM finding fields")
        bounds = item.get("box")
        if bounds is not None:
            if type(bounds) is not list or len(bounds) != 4:
                raise ValueError("visual box must be four integers")
            bounds = tuple(bounds)
        parsed.append(VisualFinding(
            kind=item["kind"], region=item["region"],
            confidence=item["confidence"], box=bounds,
        ))
    return VisualPacket(
        captured_ms=captured_ms, width=width, height=height,
        findings=tuple(parsed),
    )


__all__ = [
    "VISUAL_KINDS", "VISUAL_REGIONS", "VisualFinding", "VisualPacket",
    "parse_visual_packet",
]
