"""Windows UI Automation: the exact, fast way to see an app's controls (names, roles, rectangles).

`ComtypesUia.snapshot(hwnd)` asks Windows once for every control of a window with the properties prefetched
(IUIAutomationElement::FindAllBuildCache), so the cost is one cross-process round trip, not one per property.
`elements_from(nodes, ...)` is pure: it drops what she cannot use (off screen, empty, duplicates) and numbers the rest,
and is what the tests exercise with fake trees. Apps that expose nothing (games, custom-drawn canvases, some Electron
windows) give a thin tree; `Screen.thin` says so and the vision grounder takes over (see grounding.py).
Needs the `comtypes` package (small, pure Python); without it `UiaUnavailable` is raised and `see()` reports a thin
screen instead of crashing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .screen import INTERACTIVE, Element, Rect

ROLES = {50000: "button", 50002: "checkbox", 50003: "combobox", 50004: "edit", 50005: "hyperlink", 50006: "image",
         50007: "listitem", 50008: "list", 50009: "menu", 50010: "menubar", 50011: "menuitem", 50012: "progressbar",
         50013: "radio", 50014: "scrollbar", 50015: "slider", 50016: "spinner", 50017: "statusbar", 50018: "tab",
         50019: "tabitem", 50020: "text", 50021: "toolbar", 50023: "tree", 50024: "treeitem", 50025: "custom",
         50026: "group", 50028: "datagrid", 50029: "dataitem", 50030: "document", 50031: "splitbutton",
         50032: "window", 50033: "pane", 50036: "table", 50037: "titlebar"}
_KEEP_UNNAMED = {"edit", "combobox", "slider", "document"}
_PROPS = {"name": 30005, "type": 30003, "rect": 30001, "enabled": 30010, "offscreen": 30022, "focus": 30008,
          "password": 30019, "auto_id": 30011, "class": 30012, "value": 30045,
          "toggle": 30086}


class UiaUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RawNode:
    name: str
    control_type: int
    rect: Rect
    enabled: bool = True
    offscreen: bool = False
    focused: bool = False
    password: bool = False
    value: str = ""
    auto_id: str = ""
    class_name: str = ""
    toggle: int = -1


class UiaSource(Protocol):
    def snapshot(self, hwnd: int | None) -> list[RawNode]: ...


def elements_from(nodes: list[RawNode], screen: tuple[int, int], max_elements: int = 400,
                  window: Rect | None = None) -> list[Element]:
    """Usable, numbered elements from raw nodes. Interactive controls survive the cap before plain text does."""
    width, height = screen
    seen: set = set()
    keep: list[tuple[RawNode, str]] = []
    for node in nodes:
        left, top, right, bottom = node.rect
        if node.offscreen or right - left < 2 or bottom - top < 2:
            continue
        if right <= 0 or bottom <= 0 or (width and left >= width) or (height and top >= height):
            continue
        role = ROLES.get(node.control_type, "custom")
        name = " ".join(node.name.split())
        if not name and not node.value and role not in _KEEP_UNNAMED:
            continue
        key = (role, name, node.rect)
        if key in seen:
            continue
        seen.add(key)
        keep.append((node, role))
    interactive = [k for k in keep if k[1] in INTERACTIVE]
    rest = [k for k in keep if k[1] not in INTERACTIVE]
    chosen = (interactive + rest)[:max_elements]
    order = {id(k[0]): i for i, k in enumerate(keep)}
    chosen.sort(key=lambda k: order[id(k[0])])                      # back to the app's own (reading) order
    return [Element(i, " ".join(n.name.split()) or n.auto_id or n.class_name, role, n.rect, "uia", n.enabled,
                    n.focused, n.value, n.password, n.auto_id, n.class_name, n.toggle)
            for i, (n, role) in enumerate(chosen, start=1)]



class ComtypesUia:  # pragma: no cover - needs a Windows desktop and the comtypes package
    def __init__(self, timeout_ms: int = 4000) -> None:
        try:
            import comtypes
            import comtypes.client
        except ImportError as why:
            raise UiaUnavailable("the comtypes package is not installed (pip install comtypes)") from why
        self._mod = comtypes.client.GetModule("UIAutomationCore.dll")
        self._uia = comtypes.CoCreateInstance(self._mod.CUIAutomation._reg_clsid_, interface=self._mod.IUIAutomation,
                                              clsctx=comtypes.CLSCTX_INPROC_SERVER)
        try:                                                        # do not hang on an app that does not answer
            uia2 = self._uia.QueryInterface(self._mod.IUIAutomation2)
            uia2.ConnectionTimeout = timeout_ms
            uia2.TransactionTimeout = timeout_ms
        except Exception:
            pass
        self._request = self._uia.CreateCacheRequest()
        for prop in _PROPS.values():
            self._request.AddProperty(prop)
        self._request.AutomationElementMode = self._mod.AutomationElementMode_None
        self._cond = self._uia.ControlViewCondition

    def snapshot(self, hwnd: int | None) -> list[RawNode]:
        root = self._uia.ElementFromHandle(hwnd) if hwnd else self._uia.GetRootElement()
        found = root.FindAllBuildCache(self._mod.TreeScope_Descendants, self._cond, self._request)
        out = [self._node(root.BuildUpdatedCache(self._request))] if hwnd else []
        for i in range(found.Length):
            out.append(self._node(found.GetElement(i)))
        return out

    def _node(self, el) -> RawNode:
        def prop(name):
            try:
                return el.GetCachedPropertyValue(_PROPS[name])
            except Exception:
                return None
        rect = prop("rect")
        if isinstance(rect, (tuple, list)) and len(rect) == 4:      # UIA returns (left, top, width, height) as doubles
            box = (int(rect[0]), int(rect[1]), int(rect[0] + rect[2]), int(rect[1] + rect[3]))
        else:
            box = (0, 0, 0, 0)
        value = prop("value")
        toggle = prop("toggle")
        return RawNode(str(prop("name") or ""), int(prop("type") or 0), box, bool(prop("enabled")),
                       bool(prop("offscreen")), bool(prop("focus")), bool(prop("password")),
                       str(value) if isinstance(value, str) else "", str(prop("auto_id") or ""),
                       str(prop("class") or ""), toggle if isinstance(toggle, int) and 0 <= toggle <= 2 else -1)
