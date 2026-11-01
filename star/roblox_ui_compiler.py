"""Deterministic, offline compiler for a small declarative Roblox UI format.

Input is JSON text (or a parsed mapping); no executable Luau is accepted as input.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

KINDS = {
    "screen": "ScreenGui", "frame": "Frame", "scroll": "ScrollingFrame",
    "grid": "Frame", "text": "TextLabel", "button": "TextButton",
    "image": "ImageLabel", "input": "TextBox", "toggle": "TextButton",
    "progress": "Frame",
}
TEXT_KINDS = {"text", "button", "input", "toggle"}
CONTAINERS = {"screen", "frame", "scroll", "grid"}
EASING = {"Linear", "Sine", "Quad", "Cubic", "Quart", "Quint", "Exponential", "Circular", "Back", "Bounce", "Elastic"}
DIRECTIONS = {"In", "Out", "InOut"}
STATE_NAMES = {"hover", "pressed", "disabled", "selected"}
NODE_KEYS = {"type", "id", "name", "size", "position", "anchor", "background", "transparency",
             "visible", "padding", "corner", "stroke", "text", "font", "textSize",
             "textColor", "textWrapped", "image", "layout", "states", "children",
             "minSize", "maxSize", "aspectRatio", "value", "placeholder", "enabled"}
ROOT_KEYS = {"palette", "mobile", "root"}
MOBILE_KEYS = {"safeArea", "minTouchSize", "referenceWidth", "scaleByViewport"}
LAYOUT_KEYS = {"kind", "direction", "spacing", "columns", "cellSize", "cellPadding",
               "horizontalAlignment", "verticalAlignment", "sortOrder"}
STYLE_KEYS = {"background", "textColor", "transparency", "duration", "easing", "direction"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
FONTS = {"Gotham", "GothamBold", "GothamMedium", "SourceSans", "Arial", "Code",
         "Roboto", "Ubuntu", "Cartoon", "FredokaOne"}
HALIGN = {"Left", "Center", "Right"}
VALIGN = {"Top", "Center", "Bottom"}
MAX_NODES = 150
SORT_ORDERS = {"LayoutOrder", "Name"}

@dataclass(frozen=True)
class Diagnostic:
    severity: str
    path: str
    message: str
    line: int = 1
    column: int = 1

    def __str__(self) -> str:
        return f"{self.line}:{self.column}: {self.severity}: {self.path}: {self.message}"


class SpecError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("\n".join(map(str, diagnostics)))


@dataclass(frozen=True)
class Compilation:
    source: str
    warnings: tuple[Diagnostic, ...]


def _location(raw: str, path: str) -> tuple[int, int]:
    # Search for the last property token, retaining useful source locations
    # even for nested fields and arrays without requiring a JSON dependency.
    segments = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", path)
    token = json.dumps(segments[-1]) if segments else '"root"'
    at = raw.find(token)
    if at < 0:
        at = 0
    return raw.count("\n", 0, at) + 1, at - raw.rfind("\n", 0, at)


def _color(rgb: str) -> tuple[int, int, int]:
    return int(rgb[1:3], 16), int(rgb[3:5], 16), int(rgb[5:7], 16)


def _luminance(rgb: str) -> float:
    def channel(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4
    return sum(w * channel(v) for w, v in zip((.2126, .7152, .0722), _color(rgb)))


def _contrast(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + .05) / (y + .05)


def _declared_backdrop(color: str | None, transparency: Any,
                       inherited: str | None) -> str | None:
    """Resolve only an opaque declared colour, without guessing alpha composition."""
    if (type(transparency) not in (int, float) or not 0 <= transparency <= 1
            or not math.isfinite(transparency)):
        return None  # Validation reports the malformed property separately.
    if transparency == 1:
        return inherited
    if transparency == 0:
        return color
    return None


def validate(spec: str | dict[str, Any]) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    """Validate a spec and report declared contrast; rendered UI remains unverified."""
    try:
        raw = spec if isinstance(spec, str) else json.dumps(spec)
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            raise SpecError([Diagnostic("error", "$", exc.msg, exc.lineno, exc.colno)]) from exc
        raise SpecError([Diagnostic("error", "$", str(exc))]) from exc
    issues: list[Diagnostic] = []

    def issue(severity: str, path: str, message: str) -> None:
        line, col = _location(raw, path)
        issues.append(Diagnostic(severity, path, message, line, col))

    def keys(obj: Any, allowed: set[str], path: str) -> bool:
        if not isinstance(obj, dict):
            issue("error", path, "expected object")
            return False
        for k in obj:
            if k not in allowed:
                issue("error", path + "." + str(k), "unknown key")
        return True

    def number(value: Any, path: str, lo: float, hi: float) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi or not math.isfinite(value):
            issue("error", path, f"expected finite number from {lo:g} to {hi:g}")
            return False
        return True

    def dimension(value: Any, path: str) -> None:
        if not keys(value, {"scale", "offset"}, path):
            return
        if not value or any(not number(v, path + "." + k, -100000 if k == "offset" else -10,
                                   100000 if k == "offset" else 10) for k, v in value.items()):
            if not value:
                issue("error", path, "dimension cannot be empty")

    def vector(value: Any, path: str) -> None:
        if not keys(value, {"x", "y"}, path):
            return
        for axis in ("x", "y"):
            if axis not in value:
                issue("error", path + "." + axis, "required")
            else:
                dimension(value[axis], path + "." + axis)

    if not keys(data, ROOT_KEYS, "$"):
        raise SpecError(issues)
    palette = data.get("palette", {})
    if isinstance(palette, dict):
        for name, color in palette.items():
            if not isinstance(name, str) or not ID_RE.fullmatch(name) or not isinstance(color, str) or not COLOR_RE.fullmatch(color):
                issue("error", "$.palette." + str(name), "expected named #RRGGBB colour")
    else:
        issue("error", "$.palette", "expected object")
        palette = {}
    mobile = data.get("mobile", {})
    if keys(mobile, MOBILE_KEYS, "$.mobile"):
        for name in ("safeArea", "scaleByViewport"):
            if name in mobile and not isinstance(mobile[name], bool):
                issue("error", "$.mobile." + name, "expected boolean")
        if "minTouchSize" in mobile:
            number(mobile["minTouchSize"], "$.mobile.minTouchSize", 44, 200)
        if "referenceWidth" in mobile:
            number(mobile["referenceWidth"], "$.mobile.referenceWidth", 320, 3840)

    def palette_color(value: Any, path: str) -> str | None:
        if (not isinstance(value, str) or value not in palette
                or not isinstance(palette[value], str) or not COLOR_RE.fullmatch(palette[value])):
            issue("error", path, "expected a defined, valid palette colour name")
            return None
        return palette[value]

    def contrast_warning(foreground: str | None, background: str | None,
                         path: str, state: str, *, inactive: bool = False) -> None:
        # 4.5:1 is a conservative authoring target for every declared text state.
        # It is not a WCAG conformance verdict: inactive controls are exempt,
        # and the format does not establish rendered font weight/large-text size.
        qualifier = "; inactive controls are exempt from WCAG text contrast" if inactive else ""
        if foreground is None or background is None:
            issue("warning", path + ".textColor",
                  f"{state} text contrast is indeterminate: foreground or opaque backdrop "
                  f"is not fully specified; inspect the rendered UI{qualifier}")
        elif _contrast(foreground, background) < 4.5:
            issue("warning", path + ".textColor",
                  f"declared {state} text contrast is below the 4.5:1 authoring target{qualifier}")

    seen: set[str] = set()
    node_count = 0

    def node(obj: Any, path: str, depth: int, inherited_bg: str | None) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_NODES:
            if node_count == MAX_NODES + 1:
                issue("error", path, f"node limit ({MAX_NODES}) exceeded")
            return
        if depth > 32:
            issue("error", path, "tree depth limit (32) exceeded")
            return
        if not keys(obj, NODE_KEYS, path):
            return
        kind = obj.get("type")
        if not isinstance(kind, str) or kind not in KINDS:
            issue("error", path + ".type", "unknown or missing element type")
            return
        screen_keys = {"type", "id", "name", "children", "enabled"}
        gui_keys = {"type", "id", "name", "size", "position", "anchor",
                    "background", "transparency", "visible", "padding", "corner",
                    "stroke", "minSize", "maxSize", "aspectRatio"}
        supported = (screen_keys if kind == "screen" else
                     gui_keys
                     | ({"children", "layout"} if kind in CONTAINERS else set())
                     | ({"text", "font", "textSize", "textColor", "textWrapped"}
                        if kind in TEXT_KINDS else set())
                     | ({"image"} if kind == "image" else set())
                     | ({"placeholder"} if kind == "input" else set())
                     | ({"states", "enabled"} if kind in {"button", "toggle", "input"} else set())
                     | ({"value"} if kind == "progress" else set()))
        for key in obj:
            if key in NODE_KEYS and key not in supported:  # unknown keys are reported once above
                issue("error", path + "." + key, f"property not supported on {kind}")
        ident = obj.get("id")
        if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
            issue("error", path + ".id", "id must match [A-Za-z][A-Za-z0-9_]*")
        elif ident in seen:
            issue("error", path + ".id", "duplicate id")
        else:
            seen.add(ident)
        if kind == "screen" and depth != 0:
            issue("error", path + ".type", "screen must be root")
        if depth == 0 and kind != "screen":
            issue("error", path + ".type", "root must be screen")
        for k in ("name", "text", "placeholder", "image"):
            if k in obj and (not isinstance(obj[k], str) or len(obj[k]) > 4096):
                issue("error", path + "." + k, "expected string up to 4096 characters")
        if "image" in obj and not re.fullmatch(r"rbxassetid://[0-9]+", str(obj["image"])):
            issue("error", path + ".image", "image must be rbxassetid://<digits>")
        for k in ("size", "position", "anchor", "minSize", "maxSize"):
            if k in obj:
                vector(obj[k], path + "." + k)
        for key in ("minSize", "maxSize"):
            dims = obj.get(key)
            if isinstance(dims, dict):
                for axis in ("x", "y"):
                    dim = dims.get(axis)
                    if isinstance(dim, dict) and "scale" in dim:
                        issue("error", path + "." + key + "." + axis + ".scale",
                              "size constraints require pixel offsets")
        for k in ("padding", "corner", "textSize", "aspectRatio", "value", "transparency"):
            if k in obj:
                bounds = {"padding": (0, 1000), "corner": (0, 1000), "textSize": (1, 200),
                          "aspectRatio": (.01, 100), "value": (0, 1), "transparency": (0, 1)}
                number(obj[k], path + "." + k, *bounds[k])
        if isinstance(obj.get("maxSize"), dict):
            touch = mobile.get("minTouchSize", 44) if kind in {"button", "toggle", "input"} else 0
            if not isinstance(touch, (int, float)):
                touch = 44
            for axis in ("x", "y"):
                max_dim = obj["maxSize"].get(axis)
                min_size = obj.get("minSize")
                min_dim = min_size.get(axis) if isinstance(min_size, dict) else None
                max_px = max_dim.get("offset") if isinstance(max_dim, dict) else None
                min_px = min_dim.get("offset", 0) if isinstance(min_dim, dict) else 0
                if (isinstance(max_px, (int, float)) and not isinstance(max_px, bool)
                        and isinstance(min_px, (int, float)) and not isinstance(min_px, bool)
                        and max_px < max(touch, min_px)):
                    issue("error", path + ".maxSize." + axis + ".offset",
                          "maximum size is smaller than minimum touch/element size")
        for k in ("visible", "textWrapped", "enabled"):
            if k in obj and not isinstance(obj[k], bool):
                issue("error", path + "." + k, "expected boolean")
        if "font" in obj and (not isinstance(obj["font"], str) or obj["font"] not in FONTS):
            issue("error", path + ".font", "unsupported font enum")
        background_color = palette_color(obj["background"], path + ".background") if "background" in obj else None
        foreground = palette_color(obj["textColor"], path + ".textColor") if "textColor" in obj else None
        # Match emission: only these container-like kinds force transparency to
        # one when no background is authored, even if transparency was supplied.
        # Text/image/control defaults do not inherit the parent's colour.
        transparency = obj.get("transparency", 0)
        if kind in {"screen", "frame", "scroll", "grid", "progress"} and "background" not in obj:
            transparency = 1
        background = _declared_backdrop(background_color, transparency, inherited_bg)
        if kind in TEXT_KINDS:
            contrast_warning(foreground, background, path, "base", inactive=obj.get("enabled") is False)
        stroke = obj.get("stroke")
        if stroke is not None and keys(stroke, {"color", "thickness", "transparency"}, path + ".stroke"):
            if "color" in stroke:
                palette_color(stroke["color"], path + ".stroke.color")
            for k, lo, hi in (("thickness", 0, 20), ("transparency", 0, 1)):
                if k in stroke:
                    number(stroke[k], path + ".stroke." + k, lo, hi)
        layout = obj.get("layout")
        if layout is not None and keys(layout, LAYOUT_KEYS, path + ".layout"):
            if kind not in CONTAINERS:
                issue("error", path + ".layout", "layout requires a container")
            layout_kind = layout.get("kind")
            if not isinstance(layout_kind, str) or layout_kind not in {"list", "grid"}:
                issue("error", path + ".layout.kind", "expected list or grid")
            if "direction" in layout and (not isinstance(layout["direction"], str)
                                          or layout["direction"] not in {"Horizontal", "Vertical"}):
                issue("error", path + ".layout.direction", "expected Horizontal or Vertical")
            for k in ("spacing", "cellPadding"):
                if k in layout:
                    number(layout[k], path + ".layout." + k, 0, 1000)
            if "columns" in layout and (type(layout["columns"]) is not int or not 1 <= layout["columns"] <= 50):
                issue("error", path + ".layout.columns", "expected integer 1..50")
            if "cellSize" in layout:
                vector(layout["cellSize"], path + ".layout.cellSize")
            for k, values in (("horizontalAlignment", HALIGN), ("verticalAlignment", VALIGN)):
                if k in layout and (not isinstance(layout[k], str) or layout[k] not in values):
                    issue("error", path + ".layout." + k, "invalid alignment")
            if "sortOrder" in layout and (not isinstance(layout["sortOrder"], str)
                                          or layout["sortOrder"] not in SORT_ORDERS):
                issue("error", path + ".layout.sortOrder", "invalid sort order")
        states = obj.get("states", {})
        if keys(states, STATE_NAMES, path + ".states"):
            for state, settings in states.items():
                sp = path + ".states." + state
                if keys(settings, STYLE_KEYS, sp):
                    # The emitted refresh() resets every goal from the base
                    # style. A pressed state never inherits hover overrides.
                    state_background = (palette_color(settings["background"], sp + ".background")
                                        if "background" in settings else background_color)
                    state_foreground = (palette_color(settings["textColor"], sp + ".textColor")
                                        if "textColor" in settings else foreground)
                    for k, lo, hi in (("transparency", 0, 1), ("duration", 0, 5)):
                        if k in settings:
                            number(settings[k], sp + "." + k, lo, hi)
                    if kind in TEXT_KINDS:
                        state_backdrop = _declared_backdrop(
                            state_background, settings.get("transparency", transparency), inherited_bg)
                        contrast_warning(state_foreground, state_backdrop, sp, state, inactive=state == "disabled")
                    easing = settings.get("easing", "Quad")
                    if not isinstance(easing, str) or easing not in EASING:
                        issue("error", sp + ".easing", "unsupported TweenService easing")
                    direction = settings.get("direction", "Out")
                    if not isinstance(direction, str) or direction not in DIRECTIONS:
                        issue("error", sp + ".direction", "unsupported easing direction")
            if states and kind not in {"button", "toggle", "input"}:
                issue("error", path + ".states", "states require an interactive element")
        children = obj.get("children", [])
        if not isinstance(children, list):
            issue("error", path + ".children", "expected array")
        elif children and kind not in CONTAINERS:
            issue("error", path + ".children", "children require a container")
        else:
            for i, child in enumerate(children):
                node(child, path + f".children[{i}]", depth + 1, background)
    if "root" not in data:
        issue("error", "$.root", "required")
    else:
        node(data["root"], "$.root", 0, None)
    errors = [d for d in issues if d.severity == "error"]
    if errors:
        raise SpecError(errors + [d for d in issues if d.severity == "warning"])
    return data, tuple(d for d in issues if d.severity == "warning")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _lua_string(value: str) -> str:
    # Fixed-width decimal UTF-8 byte escapes, not unsupported JSON \\uXXXX.
    return '"' + "".join(
        chr(byte) if 32 <= byte < 127 and byte not in (34, 92)
        else '\\' + chr(byte) if byte in (34, 92)
        else f"\\{byte:03d}"
        for byte in value.encode("utf-8")
    ) + '"'


def _udim(vec: dict[str, Any]) -> str:
    def part(axis: str) -> str:
        dim = vec[axis]
        return f"{dim.get('scale', 0):g}, {dim.get('offset', 0):g}"
    return f"UDim2.new({part('x')}, {part('y')})"


def _emit(spec: dict[str, Any]) -> str:
    palette = spec.get("palette", {})
    mobile = spec.get("mobile", {})
    lines = [
        "-- Generated by STAR Roblox UI compiler. Client-side presentation only.",
        "-- Never use LocalPlayer UI data as authority for purchases or gameplay.",
        'local TweenService = game:GetService("TweenService")',
        'local GuiService = game:GetService("GuiService")',
        'local Players = game:GetService("Players")',
        'local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")',
        "local handles, connections, tweens = {}, {}, {}",
        "local destroyed = false",
        "local function track(connection)",
        "    table.insert(connections, connection)",
        "end",
        "local function animate(target, goals, duration, easing, direction)",
        "    if destroyed then return end",
        "    if tweens[target] then tweens[target]:Cancel() end",
        "    local tween = TweenService:Create(target, TweenInfo.new(duration, easing, direction), goals)",
        "    tweens[target] = tween",
        "    tween:Play()",
        "end",
    ]
    if mobile.get("safeArea", True):
        lines.extend([
            "-- ScreenGui.ScreenInsets uses the engine's GuiService safe-area information.",
            "local safeTopLeft, safeBottomRight = GuiService:GetGuiInset()",
            "-- Retained for custom inset-aware positioning by consumers.",
            "local guiInsets = {safeTopLeft, safeBottomRight}",
        ])
    root = spec["root"]
    count = 0

    def put(s: str) -> None:
        lines.append(s)

    def color(name: str) -> str:
        rgb = _color(palette[name])
        return f"Color3.fromRGB({rgb[0]}, {rgb[1]}, {rgb[2]})"

    def walk(node: dict[str, Any], parent: str | None) -> None:
        nonlocal count
        count += 1
        var = f"n{count}"
        kind = node["type"]
        put(f'local {var} = Instance.new("{KINDS[kind]}")')
        put(f'{var}.Name = {_lua_string(node.get("name", node["id"]))}')
        if kind == "screen":
            put(f"{var}.ResetOnSpawn = false")
            put(f"{var}.ScreenInsets = Enum.ScreenInsets.{('CoreUISafeInsets' if mobile.get('safeArea', True) else 'None')}")
            if "enabled" in node:
                put(f"{var}.Enabled = {str(node['enabled']).lower()}")
        else:
            put(f"{var}.BorderSizePixel = 0")
            if "size" in node:
                put(f"{var}.Size = {_udim(node['size'])}")
            if "position" in node:
                put(f"{var}.Position = {_udim(node['position'])}")
            if "anchor" in node:
                a = node["anchor"]
                put(f"{var}.AnchorPoint = Vector2.new({a['x'].get('scale', 0):g}, {a['y'].get('scale', 0):g})")
        props = (("background", "BackgroundColor3", color),
                 ("textColor", "TextColor3", color),
                 ("transparency", "BackgroundTransparency", str),
                 ("visible", "Visible", lambda v: str(v).lower()),
                 ("textWrapped", "TextWrapped", lambda v: str(v).lower()),
                 ("textSize", "TextSize", str),
                 ("text", "Text", _lua_string),
                 ("placeholder", "PlaceholderText", _lua_string),
                 ("image", "Image", _lua_string),
                 ("font", "Font", lambda v: f"Enum.Font.{v}"))
        for key, prop, render in props:
            if key in node and (key not in {"textColor", "text", "textWrapped", "textSize", "font"} or kind in TEXT_KINDS):
                put(f"{var}.{prop} = {render(node[key])}")
        if kind in {"frame", "scroll", "grid", "progress"} and "background" not in node:
            put(f"{var}.BackgroundTransparency = 1")
        if kind == "scroll":
            put(f"{var}.AutomaticCanvasSize = Enum.AutomaticSize.Y")
            put(f"{var}.CanvasSize = UDim2.fromOffset(0, 0)")
        if kind == "input":
            put(f"{var}.ClearTextOnFocus = false")
        if "enabled" in node and kind in {"button", "toggle", "input"}:
            put(f"{var}.Interactable = {str(node['enabled']).lower()}")
        if "corner" in node:
            put('do')
            put('    local corner = Instance.new("UICorner")')
            put(f"    corner.CornerRadius = UDim.new(0, {node['corner']:g})")
            put(f"    corner.Parent = {var}")
            put('end')
        if "stroke" in node:
            stroke = node["stroke"]
            put('do')
            put('    local stroke = Instance.new("UIStroke")')
            if "color" in stroke:
                put(f"    stroke.Color = {color(stroke['color'])}")
            if "thickness" in stroke:
                put(f"    stroke.Thickness = {stroke['thickness']:g}")
            if "transparency" in stroke:
                put(f"    stroke.Transparency = {stroke['transparency']:g}")
            put(f"    stroke.Parent = {var}")
            put("end")
        if "padding" in node:
            put('do')
            put('    local padding = Instance.new("UIPadding")')
            for edge in ("Top", "Bottom", "Left", "Right"):
                put(f"    padding.Padding{edge} = UDim.new(0, {node['padding']:g})")
            put(f"    padding.Parent = {var}")
            put("end")
        if "aspectRatio" in node:
            put('do')
            put('    local aspect = Instance.new("UIAspectRatioConstraint")')
            put(f"    aspect.AspectRatio = {node['aspectRatio']:g}")
            put(f"    aspect.Parent = {var}")
            put("end")
        # One constraint per node; merge minimum tap area and authored minimum.
        if kind in {"button", "toggle", "input"} or "minSize" in node or "maxSize" in node:
            put('do')
            put('    local constraint = Instance.new("UISizeConstraint")')
            if kind in {"button", "toggle", "input"} or "minSize" in node:
                touch = mobile.get("minTouchSize", 44) if kind in {"button", "toggle", "input"} else 0
                minimum = node.get("minSize", {})
                x = max(touch, minimum.get("x", {}).get("offset", 0))
                y = max(touch, minimum.get("y", {}).get("offset", 0))
                put(f"    constraint.MinSize = Vector2.new({x:g}, {y:g})")
            if "maxSize" in node:
                maximum = node["maxSize"]
                x = maximum["x"].get("offset", 0)
                y = maximum["y"].get("offset", 0)
                put(f"    constraint.MaxSize = Vector2.new({x:g}, {y:g})")
            put(f"    constraint.Parent = {var}")
            put("end")
        layout = node.get("layout")
        if layout:
            grid = layout["kind"] == "grid"
            put('do')
            put(f'    local layout = Instance.new("{"UIGridLayout" if grid else "UIListLayout"}")')
            if grid:
                if "cellSize" in layout:
                    put(f"    layout.CellSize = {_udim(layout['cellSize'])}")
                put(f"    layout.CellPadding = UDim2.fromOffset({layout.get('cellPadding', 0):g}, {layout.get('cellPadding', 0):g})")
                if "columns" in layout:
                    put(f"    layout.FillDirectionMaxCells = {layout['columns']}")
            else:
                put(f"    layout.FillDirection = Enum.FillDirection.{layout.get('direction', 'Vertical')}")
                put(f"    layout.Padding = UDim.new(0, {layout.get('spacing', 0):g})")
            for key, prop in (("horizontalAlignment", "HorizontalAlignment"),
                              ("verticalAlignment", "VerticalAlignment"),
                              ("sortOrder", "SortOrder")):
                if key in layout:
                    put(f"    layout.{prop} = Enum.{prop}.{layout[key]}")
            put(f"    layout.Parent = {var}")
            put("end")
        if kind in {"button", "toggle", "input"}:
            states = node.get("states", {})
            if states:
                put("do")
                put("    local hovering, pressing, selected = false, false, false")
                put(f"    local baseBackground = {var}.BackgroundColor3")
                put(f"    local baseText = {var}.TextColor3")
                put(f"    local baseTransparency = {var}.BackgroundTransparency")
                put("    local function refresh()")
                put(f"        local state = not {var}.Interactable and 'disabled' or pressing and 'pressed' or selected and 'selected' or hovering and 'hover' or ''")
                put("        local goals = {BackgroundColor3 = baseBackground, TextColor3 = baseText, BackgroundTransparency = baseTransparency}")
                put("        local duration = 0.15")
                put("        local easing = Enum.EasingStyle.Quad")
                put("        local direction = Enum.EasingDirection.Out")
                for state, style in states.items():
                    put(f"        if state == {_lua_string(state)} then")
                    for field, prop in (("background", "BackgroundColor3"), ("textColor", "TextColor3"), ("transparency", "BackgroundTransparency")):
                        if field in style:
                            val = color(style[field]) if field in {"background", "textColor"} else str(style[field])
                            put(f"            goals.{prop} = {val}")
                    put(f"            duration = {style.get('duration', .15):g}")
                    put(f"            easing = Enum.EasingStyle.{style.get('easing', 'Quad')}")
                    put(f"            direction = Enum.EasingDirection.{style.get('direction', 'Out')}")
                    put("        end")
                put(f"        animate({var}, goals, duration, easing, direction)")
                put("    end")
                put(f"    track({var}.MouseEnter:Connect(function() hovering = true; refresh() end))")
                put(f"    track({var}.MouseLeave:Connect(function() hovering = false; pressing = false; refresh() end))")
                put(f"    track({var}.MouseButton1Down:Connect(function() pressing = true; refresh() end))" if kind != "input" else f"    track({var}.Focused:Connect(function() pressing = true; refresh() end))")
                put(f"    track({var}.MouseButton1Up:Connect(function() pressing = false; refresh() end))" if kind != "input" else f"    track({var}.FocusLost:Connect(function() pressing = false; refresh() end))")
                if kind == "toggle":
                    put(f"    track({var}.Activated:Connect(function() selected = not selected; refresh() end))")
                put(f"    track({var}:GetPropertyChangedSignal('Interactable'):Connect(refresh))")
                put("    refresh()")
                put("end")
        if kind == "progress":
            value = node.get("value", 0)
            put('do')
            put('    local fill = Instance.new("Frame")')
            put('    fill.Name = "Fill"')
            put(f"    fill.Size = UDim2.fromScale({value:g}, 1)")
            put("    fill.BorderSizePixel = 0")
            put("    fill.Parent = " + var)
            put("end")
        put(f'handles[{_lua_string(node["id"])}] = {var}')
        # Set Parent after all local properties and decorations.
        put(f"{var}.Parent = {parent or 'playerGui'}")
        child_parent = var
        if kind == "screen":
            put('local host = Instance.new("Frame")')
            put('host.Name = "ResponsiveRoot"')
            put('host.Size = UDim2.fromScale(1, 1)')
            put('host.BackgroundTransparency = 1')
            put(f'host.Parent = {var}')
            child_parent = "host"
        for child in node.get("children", []):
            walk(child, child_parent)

    walk(root, None)
    ref_width = mobile.get("referenceWidth", 1280)
    if mobile.get("scaleByViewport", True):
        lines.extend([
            'local screenScale = Instance.new("UIScale")',
            "screenScale.Name = 'ViewportScale'",
            "local function rescale()",
            "    local camera = workspace.CurrentCamera",
            "    if not camera then return end",
            f"    local scale = math.clamp(camera.ViewportSize.X / {ref_width:g}, 0.5, 2)",
            "    screenScale.Scale = scale",
            "    host.Size = UDim2.fromScale(1 / scale, 1 / scale)",
            "end",
            "screenScale.Parent = host",
            "rescale()",
            "local camera = workspace.CurrentCamera",
            "if camera then track(camera:GetPropertyChangedSignal('ViewportSize'):Connect(rescale)) end",
        ])
    lines.extend([
        "local function destroy()",
        "    if destroyed then return end",
        "    destroyed = true",
        "    for _, connection in ipairs(connections) do connection:Disconnect() end",
        "    for _, tween in pairs(tweens) do tween:Cancel() end",
        "    n1:Destroy()",
        "    table.clear(connections)",
        "    table.clear(tweens)",
        "    table.clear(handles)",
        "end",
        "return {handles = handles, destroy = destroy}",
    ])
    return "\n".join(lines) + "\n"


def compile_ui(spec: str | dict[str, Any]) -> Compilation:
    """Compile validated JSON into a deterministic LocalScript-ready Luau module."""
    data, warnings = validate(spec)
    return Compilation(_emit(data), warnings)
