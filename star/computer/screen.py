"""What STAR sees on her screen: elements (from Windows UI Automation or a vision model) and snapshots of them.

An `Element` is one thing she can point at: a name, a role, a rectangle in screen pixels and where it came from
("uia" = exact, read from the app's accessibility tree; "vision" = a grounding model's guess). A `Screen` is the
elements of the window she is working in plus enough to tell whether the next snapshot is different.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re

INTERACTIVE = frozenset({"button", "edit", "checkbox", "radio", "combobox", "listitem", "menuitem", "tabitem",
                         "hyperlink", "slider", "splitbutton", "treeitem", "dataitem", "spinner", "scrollbar"})
Rect = tuple[int, int, int, int]  # left, top, right, bottom


@dataclass(frozen=True)
class Element:
    id: int
    name: str
    role: str
    rect: Rect
    source: str = "uia"
    enabled: bool = True
    focused: bool = False
    value: str = ""
    password: bool = False
    auto_id: str = ""
    class_name: str = ""
    toggle: int = -1                 # UIA TogglePattern: 0 off, 1 on, 2 mixed, -1 not a switch

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def interactive(self) -> bool:
        return self.role in INTERACTIVE


@dataclass
class Screen:
    elements: list[Element]
    window: str = ""                 # title of the window these elements belong to
    process: str = ""                # its program, e.g. mspaint.exe
    hwnd: int = 0
    size: tuple[int, int] = (0, 0)   # screen size in pixels
    source: str = "uia"
    taken: float = 0.0
    note: str = ""                   # e.g. "UI Automation shows only 2 controls: use target descriptions"
    _sig: frozenset = field(default=frozenset(), repr=False)

    def __post_init__(self) -> None:
        self._sig = frozenset((e.role, e.name, tuple(v // 8 for v in e.rect), e.toggle) for e in self.elements)

    @property
    def thin(self) -> bool:
        """Too few real controls to work from the tree alone (games, canvases, some Electron apps)."""
        return sum(1 for e in self.elements if e.interactive) < 4

    def by_id(self, element_id: int) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)

    def difference(self, other: "Screen") -> float:
        """0.0 = the same controls in the same places, 1.0 = nothing in common (window title counts too)."""
        if self.window != other.window or self.hwnd != other.hwnd:
            return 1.0
        union = self._sig | other._sig
        return 0.0 if not union else 1.0 - len(self._sig & other._sig) / len(union)

    def texts(self) -> list[str]:
        return [self.window] + [t for e in self.elements for t in (e.name, e.value) if t]

    def has_text(self, needle: str) -> bool:
        needle = _norm(needle)
        return bool(needle) and any(needle in _norm(t) for t in self.texts())

    def find(self, query: str, role: str = "", limit: int = 5) -> list[tuple[float, Element]]:
        """Best matches for a name, best first. 1.0 = same name; substring and fuzzy matches score lower."""
        q = _norm(query)
        if not q:
            return []
        scored = []
        for e in self.elements:
            if role and e.role != role:
                continue
            for text in (e.name, e.value):
                t = _norm(text)
                if not t:
                    continue
                if t == q:
                    score = 1.0
                elif q in t or t in q:
                    score = 0.6 + 0.3 * min(len(q), len(t)) / max(len(q), len(t))
                else:
                    score = 0.8 * SequenceMatcher(None, q, t).ratio()
                scored.append((score + (0.02 if e.interactive else 0) + (0.01 if e.enabled else 0), e))
        scored.sort(key=lambda s: -s[0])
        seen, out = set(), []
        for score, e in scored:
            if e.id not in seen:
                seen.add(e.id)
                out.append((min(score, 1.0), e))
        return out[:limit]

    def prompt(self, limit: int = 60) -> str:
        """Compact listing for the model: interactive controls first, in reading order. Names are untrusted text."""
        ranked = sorted(self.elements, key=lambda e: (0 if e.interactive else 1, e.rect[1] // 24, e.rect[0]))
        lines = []
        for e in sorted(ranked[:limit], key=lambda e: e.id):
            flags = ("" if e.enabled else " disabled") + (" focused" if e.focused else "") + (
                " password" if e.password else "") + {0: " off", 1: " on"}.get(e.toggle, "")
            value = f" = {e.value[:40]!r}" if e.value and e.role in ("edit", "combobox") and not e.password else ""
            lines.append(f"[{e.id}] {e.role} {e.name[:60]!r}{value}{flags} @{e.center[0]},{e.center[1]}")
        head = f"window {self.window[:80]!r} ({self.process}), screen {self.size[0]}x{self.size[1]}"
        more = f"\n(+{len(self.elements) - len(lines)} more elements not listed)" if len(self.elements) > len(lines) else ""
        return head + ("\n" + self.note if self.note else "") + "\n" + "\n".join(lines) + more


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text or "").lower())).strip()
