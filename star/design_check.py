"""Design checker: measurable rules against the "AI look" for HTML/CSS pages, Roblox UI trees (Luau or JSON),
CSS/Tween motion and Roblox VFX. Pure Python, no browser: everything here is read from the code the model wrote.
The rules and their sources are in docs/design/anti-ai-look-rubric.md (rule ids match the finding ids below).
`star.design_render` adds what only a browser can measure (overflow, computed contrast) and a vision judge.

Night school / evals hook: a task's `auto.design` block ({"kind": "html"|"roblox-ui"|"roblox-vfx"|"auto",
"min_score": 70, "max_fails": 0}) turns one answer into one `design:score` check (see `auto_checks`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re

PASS_SCORE = 70          # default threshold; a task may ask for more
FAIL_COST, WARN_COST = 15, 5

# --- findings ------------------------------------------------------------------------------------------------


@dataclass
class Finding:
    id: str
    level: str            # "fail" | "warn" | "info"
    detail: str = ""

    def record(self) -> dict:
        return {"id": self.id, "level": self.level, **({"detail": self.detail} if self.detail else {})}


@dataclass
class Report:
    kind: str
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def add(self, id: str, level: str, detail: str = "") -> None:
        self.findings.append(Finding(id, level, detail))

    @property
    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "fail"]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warn"]

    @property
    def score(self) -> int:
        return max(0, 100 - FAIL_COST * len(self.fails) - WARN_COST * len(self.warns))

    def passed(self, min_score: int = PASS_SCORE, max_fails: int = 0) -> bool:
        return self.score >= min_score and len(self.fails) <= max_fails

    def summary(self) -> str:
        bad = [f"{f.id}({f.level[0]})" for f in self.findings if f.level != "info"]
        return f"{self.kind} score {self.score}: " + (", ".join(bad) if bad else "no tells")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "score": self.score, "findings": [f.record() for f in self.findings],
                "metrics": self.metrics}


# --- colour maths --------------------------------------------------------------------------------------------

_NAMED = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0),
          "gray": (128, 128, 128), "grey": (128, 128, 128), "yellow": (255, 255, 0), "orange": (255, 165, 0),
          "purple": (128, 0, 128), "pink": (255, 192, 203), "navy": (0, 0, 128), "teal": (0, 128, 128),
          "silver": (192, 192, 192), "transparent": None, "inherit": None, "currentcolor": None}
_HEX = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_RGB = re.compile(r"rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)")
_HSL = re.compile(r"hsla?\(\s*([\d.]+)(?:deg)?\s*[, ]\s*([\d.]+)%\s*[, ]\s*([\d.]+)%")
_RGB_LUAU = re.compile(r"Color3\.fromRGB\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_HEX_LUAU = re.compile(r"Color3\.fromHex\(\s*[\"']#?([0-9a-fA-F]{6})[\"']\s*\)")


def parse_color(text: str):
    """One CSS colour -> (r, g, b) or None."""
    text = text.strip().lower()
    if text in _NAMED:
        return _NAMED[text]
    m = _HEX.match(text)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        if len(h) >= 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = _RGB.match(text)
    if m:
        return tuple(min(255, int(float(v))) for v in m.groups())
    m = _HSL.match(text)
    if m:
        return hsl_to_rgb(float(m.group(1)), float(m.group(2)) / 100, float(m.group(3)) / 100)
    return None


def hsl_to_rgb(h: float, s: float, l: float):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(int(round((v + m) * 255)) for v in (r, g, b))


def rgb_to_hsl(rgb):
    r, g, b = [v / 255 for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (1 - abs(2 * l - 1))
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60, s, l


def luminance(rgb) -> float:
    def chan(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hue_buckets(colors) -> set[int]:
    """Chromatic hues used, in 30-degree buckets (neutral colours do not count)."""
    out = set()
    for c in colors:
        h, s, l = rgb_to_hsl(c)
        if s > 0.18 and 0.08 < l < 0.95:
            out.add(int(h // 30) % 12)
    return out


def _is_violet(rgb) -> bool:
    h, s, l = rgb_to_hsl(rgb)
    return 235 <= h <= 290 and s > 0.35 and 0.3 < l < 0.8


def _is_terracotta(rgb) -> bool:
    h, s, l = rgb_to_hsl(rgb)
    return 8 <= h <= 28 and 0.45 < s < 0.9 and 0.45 < l < 0.7


def _is_cream(rgb) -> bool:
    h, s, l = rgb_to_hsl(rgb)
    return 30 <= h <= 60 and 0.1 < s < 0.6 and l > 0.88


def _is_neutral(rgb) -> bool:
    return rgb_to_hsl(rgb)[1] < 0.12


# --- shared text rules ----------------------------------------------------------------------------------------

EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF⭐✅❌✨]")
PLACEHOLDER = re.compile(r"\b(?:lorem ipsum|lorem|dolor sit|your (?:company|brand|product|text|title) here|title here|"
                         r"description (?:goes )?here|insert \w+ here|placeholder|feature (?:one|two|three|[123])\b|"
                         r"card (?:title|[123])\b|item [123]\b|button text|some text|click here|lorem)\b", re.I)
INDEX_NUMBER = re.compile(r"(?<![\d.$€£#])\b0[1-9]\b(?![\d:%.])")
MIDDLE_DOT_META = re.compile(r"\S\s[·•]\s\S")
ARROW_LABEL = re.compile(r"(?:→|&rarr;|&#8594;|-->)\s*<|>\s*(?:→|&rarr;)|\s→\s*$", re.M)


def _grid_misses(values: list[int], step: int = 4) -> tuple[int, int]:
    """(off-grid count, total) for spacing values; 0, 1 and 2 px are hairline/optical adjustments and do not count."""
    sized = [v for v in values if v > 2]
    return sum(1 for v in sized if v % step), len(sized)


# --- HTML / CSS --------------------------------------------------------------------------------------------------

_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_STYLE_ATTR = re.compile(r"style\s*=\s*\"([^\"]*)\"", re.I)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_DECL = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<script[^>]*>.*?</script>", re.S | re.I)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_HEADING_ACCENT = re.compile(r"<h[12][^>]*>[^<]*<(?:span|em|i|strong|b)\b[^>]*(?:class|style)=", re.S | re.I)
_BUTTONISH = re.compile(r"<(?:a|button)\b[^>]*>(.*?)</(?:a|button)>", re.S | re.I)
_FONT_FACE = re.compile(r"@font-face", re.I)
_GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
                  "-apple-system", "blinkmacsystemfont", "segoe ui", "cursive", "fantasy", "inherit", "initial"}
_DEFAULT_FONTS = {"inter", "roboto", "arial", "helvetica", "helvetica neue", "open sans", "poppins", "montserrat"}
_LAYOUT_PROPS = {"width", "height", "top", "left", "right", "bottom", "margin", "padding", "all", "max-height",
                 "margin-top", "margin-left", "padding-top", "font-size"}
_BOUNCY = re.compile(r"cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)")
_TIME = re.compile(r"(\d*\.?\d+)\s*(ms|s)\b")


def _ms(text: str) -> list[float]:
    return [float(v) * (1000 if u == "s" else 1) for v, u in _TIME.findall(text)]


def _css_rules(html: str) -> list[tuple[str, dict]]:
    """(selector, {prop: value}) for every rule in <style> blocks and every style attribute (selector 'inline')."""
    rules = []
    for block in _STYLE_BLOCK.findall(html):
        block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        # Flatten @media / @keyframes one level so the inner rules are still read.
        flat = re.sub(r"@(?:media|supports|layer)[^{]*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", r"\1", block)
        for selector, body in _RULE.findall(flat):
            decls = {k.strip().lower(): v.strip() for k, v in _DECL.findall(body)}
            rules.append((" ".join(selector.split()), decls))
    for body in _STYLE_ATTR.findall(html):
        rules.append(("inline", {k.strip().lower(): v.strip() for k, v in _DECL.findall(body)}))
    return rules


def _text_of(html: str) -> str:
    body = _SCRIPT.sub("", html)
    body = _STYLE_BLOCK.sub("", body)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)      # comments are not copy the reader sees
    return re.sub(r"\s+", " ", _TAG.sub(" ", body))


def _colors_in(value: str) -> list:
    found = []
    for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)|\b(?:white|black|red|blue|green|gr[ae]y|"
                         r"yellow|orange|purple|pink|navy|teal|silver)\b", value, re.I):
        c = parse_color(m.group(0))
        if c is not None:
            found.append(c)
    return found


def _px(value: str) -> list[int]:
    return [int(round(float(v))) for v in re.findall(r"(-?\d*\.?\d+)px", value)]


def check_html(html: str) -> Report:
    """Static reading of one HTML document (inline CSS). Finding ids match the rubric."""
    rep = Report("html")
    rules = _css_rules(html)
    text = _text_of(html)
    css_all = "\n".join(f"{sel}{{{';'.join(f'{k}:{v}' for k, v in d.items())}}}" for sel, d in rules)
    m = rep.metrics

    # Colour, gradients, glass, shadows.
    colors, families, weights, sizes, spacing, radii = [], set(), set(), set(), [], set()
    gradients = len(re.findall(r"(?:linear|radial|conic)-gradient\(", css_all))
    gradient_text = bool(re.search(r"background-clip\s*:\s*text|-webkit-background-clip\s*:\s*text", css_all))
    blur_panels = len(re.findall(r"backdrop-filter\s*:\s*[^;]*blur", css_all))
    shadows_rest = glows = hairlines = caps_labels = centered = 0
    transition_all = ease_in = long_ui = very_long = bouncy = infinite = layout_anim = scale0 = 0
    uses_motion = False
    for sel, d in rules:
        hover = ":hover" in sel or ":focus" in sel or ":active" in sel
        for prop, value in d.items():
            colors.extend(_colors_in(value))
            if prop == "font-family":
                for fam in value.split(","):
                    fam = fam.strip().strip("'\"").lower()
                    if fam and fam not in _GENERIC_FONTS and not fam.startswith("var("):
                        families.add(fam)
            elif prop == "font-weight":
                w = value.strip().lower()
                weights.add({"bold": "700", "normal": "400"}.get(w, w))
            elif prop == "font-size":
                for px in _px(value):
                    sizes.add(px)
                if "rem" in value or "em" in value:
                    try:
                        sizes.add(int(round(float(re.findall(r"[\d.]+", value)[0]) * 16)))
                    except (IndexError, ValueError):
                        pass
            elif prop in ("padding", "margin", "gap", "row-gap", "column-gap") or prop.startswith(("padding-", "margin-")):
                spacing.extend(abs(v) for v in _px(value))
            elif prop == "border-radius":
                radii.update(_px(value))
            elif prop == "box-shadow" and value != "none":
                if not hover:
                    shadows_rest += 1
                if re.search(r"\b(?:[2-9]\d|\d{3})px", value) and any(not _is_neutral(c) for c in _colors_in(value)):
                    glows += 1
            elif prop in ("border", "border-top", "border-bottom", "border-left", "border-right", "outline"):
                if re.match(r"1px\s+solid", value) and not re.search(r"\b(?:table|td|th|input|textarea|select|kbd|pre)\b", sel):
                    hairlines += 1
            elif prop == "text-align" and value == "center":
                centered += 1
            elif prop in ("transition", "animation", "transition-duration", "animation-duration",
                          "transition-timing-function", "animation-timing-function", "transition-property"):
                uses_motion = True
                if prop in ("transition", "transition-property") and re.search(r"(?:^|\s|,)all(?:\s|,|$)", value):
                    transition_all += 1
                if re.search(r"(?<![-\w])ease-in(?!-out)", value):
                    ease_in += 1
                if prop.startswith("transition") or prop.startswith("animation"):
                    for ms in _ms(value):
                        if prop.startswith("transition") and ms > 500:
                            long_ui += 1
                        if ms > 1200:
                            very_long += 1
                for bz in _BOUNCY.findall(value):
                    if float(bz[1]) > 1.0 or float(bz[3]) > 1.05 or float(bz[1]) < -0.05:
                        bouncy += 1
                if "infinite" in value:
                    infinite += 1
                if prop in ("transition", "transition-property"):
                    props = {p.strip().split(" ")[0] for p in value.split(",")}
                    if props & _LAYOUT_PROPS - {"all"}:
                        layout_anim += 1
        if ("text-transform" in d and "uppercase" in d["text-transform"] and "letter-spacing" in d
                and any(s <= 13 for s in _px(d.get("font-size", "")) or [12])):
            caps_labels += 1
    if re.search(r"scale\(\s*0\s*\)", css_all):
        scale0 = 1
    if re.search(r"@keyframes[^{]*\{[^}]*(?:width|height|top|left|margin)\s*:", css_all):
        layout_anim += 1
    m.update(colors=len(set(colors)), hues=len(hue_buckets(set(colors))), font_families=sorted(families),
             font_weights=sorted(weights), font_sizes=sorted(sizes), gradients=gradients, blur_panels=blur_panels,
             shadows_at_rest=shadows_rest, glows=glows, hairlines=hairlines, caps_labels=caps_labels,
             text_align_center=centered, radii=sorted(radii))

    # A1 palette tells.
    if any(_is_violet(c) for c in colors) and gradients:
        rep.add("A1.violet_gradient", "fail", "violet/indigo accent combined with a gradient")
    elif any(_is_violet(c) for c in colors):
        rep.add("A1.violet_accent", "warn", "violet/indigo accent (the commonest generated accent)")
    if any(_is_terracotta(c) for c in colors) and any(_is_cream(c) for c in colors):
        rep.add("A1.cream_terracotta", "fail", "yellow-cream ground with a terracotta accent (the 2025-26 'editorial' tell)")
    # A2 gradients.
    if gradient_text:
        rep.add("A2.gradient_text", "fail", "gradient-filled text")
    if gradients >= 3:
        rep.add("A2.gradients", "fail", f"{gradients} gradients")
    elif gradients >= 1:
        rep.add("A2.gradients", "warn", f"{gradients} gradient(s)")
    # A3 glass.
    if blur_panels >= 2:
        rep.add("A3.glass", "fail", f"{blur_panels} backdrop-blur panels")
    elif blur_panels == 1:
        rep.add("A3.glass", "warn", "one backdrop-blur panel")
    # A4 shadows and glows.
    if shadows_rest >= 4:
        rep.add("A4.shadows", "fail", f"{shadows_rest} box-shadows on things at rest")
    elif shadows_rest >= 2:
        rep.add("A4.shadows", "warn", f"{shadows_rest} box-shadows on things at rest")
    if glows:
        rep.add("A4.glow", "warn", f"{glows} coloured glow shadow(s)")
    # A5 emoji.
    emo = len(EMOJI.findall(text))
    if emo:
        rep.add("A5.emoji", "fail", f"{emo} emoji in the page text")
    # A6 type: families, weights, scale.
    if len(families) > 2:
        rep.add("A6.font_families", "fail", f"{len(families)} typefaces: {', '.join(sorted(families))}")
    if families and families <= _DEFAULT_FONTS and len(weights) <= 1 and not _FONT_FACE.search(html):
        rep.add("A6.default_font", "warn", f"default typeface at one weight ({', '.join(sorted(families))})")
    if len(sizes) > 8:
        rep.add("A6.type_scale", "fail", f"{len(sizes)} distinct font sizes (no scale)")
    elif len(sizes) >= 2 and max(sizes) / max(1, min(s for s in sizes if s >= 10)) < 1.8:
        rep.add("A6.flat_hierarchy", "warn", f"largest text only {max(sizes)}px against {min(sizes)}px body")
    if len(sizes) >= 3 and len(weights) <= 1 and "font-weight" not in css_all:
        rep.add("A6.one_weight", "warn", "several sizes but one weight: hierarchy carried by size alone")
    if caps_labels >= 3:
        rep.add("A6.tracked_caps", "fail", f"{caps_labels} tiny tracked-uppercase labels")
    elif caps_labels:
        rep.add("A6.tracked_caps", "warn", f"{caps_labels} tiny tracked-uppercase label(s)")
    # A7 spacing grid.
    off, total = _grid_misses(spacing)
    m["spacing_values"], m["spacing_off_grid"] = total, off
    if total >= 4 and off / total > 0.25:
        rep.add("A7.spacing_grid", "fail", f"{off} of {total} spacing values off the 4px grid")
    elif off:
        rep.add("A7.spacing_grid", "warn", f"{off} of {total} spacing values off the 4px grid")
    if len(radii) > 3:
        rep.add("A7.radii", "warn", f"{len(radii)} different corner radii")
    # A8 contrast (same-rule pairs; the renderer measures the real pairs).
    low = []
    body_bg = None
    for sel, d in rules:
        if sel.strip() in ("body", "html", "html, body", "body, html", ":root") and "background" in " ".join(d):
            for k in ("background-color", "background"):
                if k in d and _colors_in(d[k]) and "gradient" not in d[k]:
                    body_bg = _colors_in(d[k])[0]
    for sel, d in rules:
        fg = _colors_in(d.get("color", ""))
        bg = _colors_in(d.get("background-color", d.get("background", "")))
        if fg and (bg or body_bg is not None) and "gradient" not in d.get("background", ""):
            ratio = contrast(fg[0], (bg or [body_bg])[0])
            big = any(s >= 24 for s in _px(d.get("font-size", "")))
            if ratio < (3.0 if big else 4.5):
                low.append(f"{sel[:30]} {ratio:.1f}:1")
    m["low_contrast_pairs"] = low
    if low:
        rep.add("A8.contrast", "fail" if len(low) > 1 else "warn", "; ".join(low[:3]))
    # A9 palette size.
    hues = m["hues"]
    if hues > 4:
        rep.add("A9.palette", "fail", f"{hues} chromatic hue families")
    elif hues == 4:
        rep.add("A9.palette", "warn", "4 chromatic hue families")
    # A10 layout tells.
    if centered >= 4:
        rep.add("A10.centered", "warn", f"text-align:center in {centered} rules")
    cards = re.findall(r"class=\"[^\"]*\b(?:card|feature|tile)\b[^\"]*\"", html, re.I)
    icon_cards = len(re.findall(r"class=\"[^\"]*\b(?:card|feature)\b[^\"]*\"[^>]*>\s*(?:<div[^>]*icon|<svg|<span[^>]*icon|<i\b)",
                                html, re.I | re.S))
    if len(cards) >= 3 and icon_cards >= 3:
        rep.add("A10.icon_cards", "fail", f"{icon_cards} icon-topped feature cards in a row")
    elif len(cards) >= 6:
        rep.add("A10.card_rows", "warn", f"{len(cards)} identical cards")
    if hairlines >= 6:
        rep.add("A10.hairlines", "fail", f"{hairlines} 1px hairline borders")
    elif hairlines >= 3:
        rep.add("A10.hairlines", "warn", f"{hairlines} 1px hairline borders")
    # A11 copy tells.
    ph = PLACEHOLDER.findall(text)
    if ph:
        rep.add("A11.placeholder_copy", "fail", "placeholder copy: " + ", ".join(sorted({p.lower() for p in ph})[:4]))
    h1s = [re.sub(r"\s+", " ", _TAG.sub(" ", h)).strip() for h in _H1.findall(html)]
    if any(len(h.split()) > 12 for h in h1s):
        rep.add("A11.long_headline", "warn", "h1 longer than 12 words (reads as three or four lines)")
    if len(INDEX_NUMBER.findall(text)) >= 3:
        rep.add("A11.index_numbering", "warn", "01 / 02 / 03 index markers")
    if len(MIDDLE_DOT_META.findall(text)) >= 2:
        rep.add("A11.middle_dots", "warn", "meta strings joined with middle dots")
    labels = [re.sub(r"\s+", " ", _TAG.sub("", b)).strip() for b in _BUTTONISH.findall(html)]
    if any("→" in l or "&rarr;" in l for l in labels):
        rep.add("A11.arrow_labels", "warn", "an arrow appended to button or link text")
    if _HEADING_ACCENT.search(html):
        rep.add("A11.accent_word", "warn", "one styled accent word inside the headline")
    eyebrow = re.findall(r"<(?:p|span|div)[^>]*class=\"[^\"]*\b(?:eyebrow|kicker|overline|label|badge|pill|tag)\b[^\"]*\"[^>]*>", html, re.I)
    if eyebrow:
        rep.add("A11.eyebrow", "warn", f"{len(eyebrow)} eyebrow/kicker/badge element(s) above headings")
    # A12 responsiveness (static part).
    if "@media" not in css_all and "clamp(" not in css_all and not re.search(r"\d+(?:vw|%|fr|ch)\b", css_all):
        rep.add("A12.no_responsive_rules", "warn", "no @media, clamp() or fluid units")
    if re.search(r"(?<!max-)width\s*:\s*(?:[4-9]\d\d|\d{4,})px", css_all) and "max-width" not in css_all:
        rep.add("A12.fixed_width", "warn", "a fixed width over 390px with no max-width")
    if "viewport" not in html.lower() and "<html" in html.lower():
        rep.add("A12.no_viewport_meta", "warn", "no viewport meta tag")
    # M: motion (CSS).
    m.update(transition_all=transition_all, ease_in=ease_in, long_ui_transitions=long_ui, bouncy_easing=bouncy,
             infinite_animations=infinite, layout_animations=layout_anim)
    if transition_all:
        rep.add("M1.transition_all", "warn", f"transition: all in {transition_all} rule(s)")
    if ease_in:
        rep.add("M2.ease_in", "fail", f"ease-in on UI motion in {ease_in} rule(s)")
    if very_long:
        rep.add("M3.duration", "fail", f"{very_long} motion duration(s) over 1200ms")
    elif long_ui:
        rep.add("M3.duration", "warn", f"{long_ui} UI transition(s) over 500ms")
    if bouncy:
        rep.add("M4.bounce", "warn", f"{bouncy} overshooting (bounce/elastic) curve(s)")
    if infinite and not re.search(r"marquee|progress|spinner|loading|pulse-?dot", css_all, re.I):
        rep.add("M5.infinite", "warn", f"{infinite} infinite animation(s) without a loading/marquee purpose")
    if layout_anim:
        rep.add("M6.layout_props", "warn", "animating layout properties (width/height/top/left/margin)")
    if scale0:
        rep.add("M7.scale_zero", "warn", "an element enters from scale(0)")
    reveals = len(re.findall(r"animation\s*:\s*[\w-]*(?:fade|rise|slide|reveal)", css_all, re.I))
    if reveals >= 4:
        rep.add("M8.fade_up_everywhere", "warn", f"{reveals} fade/rise entrance animations")
    if uses_motion and "prefers-reduced-motion" not in html:
        rep.add("M9.reduced_motion", "warn", "motion without a prefers-reduced-motion rule")
    if ":focus-visible" in css_all or ":focus" in css_all:
        rep.add("P1.focus_visible", "info", "focus style present")
    return rep


# --- Roblox UI (Luau Instance tree or JSON tree) -----------------------------------------------------------------

_INST = re.compile(r"(?:local\s+)?([\w.]+)\s*=\s*Instance\.new\(\s*[\"'](\w+)[\"']")
_PROP = re.compile(r"^\s*([\w.]+)\.(\w+)\s*=\s*(.+?)\s*$", re.M)
_UDIM2 = re.compile(r"UDim2\.(?:new|fromOffset|fromScale)\(\s*([^)]*)\)")
_UDIM = re.compile(r"UDim\.new\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)")
_FONT_ENUM = re.compile(r"Enum\.Font\.(\w+)")
_FONT_NEW = re.compile(r"Font\.new\(\s*[\"']([^\"']+)[\"'](?:\s*,\s*Enum\.FontWeight\.(\w+))?")
_TWEENINFO = re.compile(r"TweenInfo\.new\(\s*([^)]*)\)")
_UI_CLASSES = {"Frame", "TextLabel", "TextButton", "TextBox", "ImageLabel", "ImageButton", "ScrollingFrame",
               "ScreenGui", "UIGradient", "UIStroke", "UICorner", "UIPadding", "UIListLayout", "UIGridLayout",
               "UIScale", "UIAspectRatioConstraint", "UISizeConstraint", "UITextSizeConstraint", "CanvasGroup",
               "ViewportFrame", "BillboardGui", "SurfaceGui"}


def _json_tree(text: str) -> list[dict] | None:
    """A JSON layout tree -> flat list of {"class":..., "props":{...}} nodes, or None if `text` is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    nodes: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            cls = node.get("class") or node.get("Class") or node.get("ClassName") or node.get("type")
            if cls:
                props = {k: v for k, v in node.items() if k not in ("children", "Children", "class", "Class", "ClassName", "type")}
                props.update(node.get("props") or node.get("properties") or {})
                nodes.append({"class": str(cls), "props": props, "name": str(node.get("Name") or node.get("name") or "")})
            for key in ("children", "Children"):
                if key in node:
                    walk(node[key])
    walk(data)
    return nodes if nodes else None


def _luau_tree(code: str) -> list[dict]:
    objects: dict[str, dict] = {}
    for var, cls in _INST.findall(code):
        objects[var] = {"class": cls, "props": {}, "name": var}
    for var, prop, value in _PROP.findall(code):
        if var in objects:
            objects[var]["props"][prop] = value.rstrip(";")
    return list(objects.values())


def _value_colors(value) -> list:
    if isinstance(value, str):
        out = [tuple(int(v) for v in m) for m in _RGB_LUAU.findall(value)]
        out += [parse_color("#" + h) for h in _HEX_LUAU.findall(value)]
        if value.startswith("#") and parse_color(value):
            out.append(parse_color(value))
        return [c for c in out if c]
    if isinstance(value, (list, tuple)) and len(value) == 3 and all(isinstance(v, (int, float)) for v in value):
        return [tuple(int(v) for v in value)]
    if isinstance(value, dict) and {"r", "g", "b"} <= set(k.lower() for k in value):
        return [tuple(int(value[k]) for k in sorted(value, key=str.lower))]
    return []


def _numbers(value) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        return [float(v) for v in re.findall(r"-?\d*\.?\d+", value)]
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value if isinstance(v, (int, float))]
    return []


def check_roblox_ui(code: str) -> Report:
    """Static reading of a Roblox UI tree written as Luau (Instance.new + property lines) or as a JSON tree."""
    rep = Report("roblox-ui")
    nodes = _json_tree(code.strip()) or _luau_tree(code)
    m = rep.metrics
    classes = [n["class"] for n in nodes]
    m["instances"] = len(nodes)
    if not nodes:
        rep.add("R0.no_tree", "fail", "no UI instances found (Instance.new or a JSON layout tree)")
        return rep
    colors, text_sizes, fonts, weights, offsets, scales, radii = [], set(), set(), set(), [], 0, set()
    emoji = placeholder = small_buttons = scaled_without_constraint = strokes_glow = shadows = 0
    low = []
    for n in nodes:
        p = n["props"]
        for key, value in p.items():
            colors.extend(_value_colors(value))
            if key in ("TextSize",):
                text_sizes.update(int(v) for v in _numbers(value))
            elif key in ("Font", "FontFace"):
                if isinstance(value, str):
                    fonts.update(_FONT_ENUM.findall(value))
                    for fam, weight in _FONT_NEW.findall(value):
                        fonts.add(fam.rsplit("/", 1)[-1].replace(".json", ""))
                        if weight:
                            weights.add(weight)
                    if re.search(r"Enum\.Font\.\w*(?:Bold|Black|Semibold|Medium|Light)", value):
                        weights.add("enum-weight")
            elif key in ("Size", "Position"):
                if isinstance(value, str):
                    for args in _UDIM2.findall(value):
                        nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", args)]
                        if "fromOffset" in value:
                            offsets.extend(int(v) for v in nums)
                        elif len(nums) == 4:
                            offsets.extend(int(v) for v in (nums[1], nums[3]))
                            scales += int(nums[0] != 0 or nums[2] != 0)
                        elif "fromScale" in value:
                            scales += 1
                elif isinstance(value, (list, dict)):
                    scales += 1
            elif key in ("PaddingLeft", "PaddingRight", "PaddingTop", "PaddingBottom", "Padding", "CellPadding"):
                for s, o in _UDIM.findall(str(value)):
                    offsets.append(int(float(o)))
                if isinstance(value, (int, float)):
                    offsets.append(int(value))
            elif key == "CornerRadius":
                for s, o in _UDIM.findall(str(value)):
                    radii.add(int(float(o)))
            elif key == "Text" and isinstance(value, str):
                emoji += len(EMOJI.findall(value))
                placeholder += bool(PLACEHOLDER.search(value)) or value.strip("\"' ") in {"Button", "Label", "Title", "Text", "TextLabel"}
        if n["class"] == "UIStroke":
            th = _numbers(p.get("Thickness", 1))
            if th and th[0] >= 4 and _numbers(p.get("Transparency", 0)) and _numbers(p.get("Transparency", 0))[0] > 0.2:
                strokes_glow += 1
        if n["class"] in ("ImageLabel", "ImageButton") and re.search(r"shadow|glow", n["name"] + str(p.get("Name", "")) + str(p.get("Image", "")), re.I):
            shadows += 1
        if n["class"] in ("TextButton", "ImageButton", "TextBox"):
            for args in _UDIM2.findall(str(p.get("Size", ""))):
                nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", args)]
                if len(nums) == 4 and nums[2] == 0 and 0 < nums[3] < 44:
                    small_buttons += 1
        if str(p.get("TextScaled", "")).lower() in ("true",) or p.get("TextScaled") is True:
            if "UITextSizeConstraint" not in classes:
                scaled_without_constraint += 1
        fg, bg = _value_colors(p.get("TextColor3", "")), _value_colors(p.get("BackgroundColor3", ""))
        transparent = _numbers(p.get("BackgroundTransparency", 0))
        if fg and bg and (not transparent or transparent[0] < 0.5):
            ratio = contrast(fg[0], bg[0])
            big = any(s >= 24 for s in (int(v) for v in _numbers(p.get("TextSize", 14))))
            if ratio < (3.0 if big else 4.5):
                low.append(f"{n['name'] or n['class']} {ratio:.1f}:1")
    gradients = classes.count("UIGradient")
    m.update(colors=len(set(colors)), hues=len(hue_buckets(set(colors))), fonts=sorted(fonts), weights=sorted(weights),
             text_sizes=sorted(text_sizes), gradients=gradients, scale_sizes=scales, offsets=len(offsets),
             radii=sorted(radii), low_contrast_pairs=low, buttons_under_44px=small_buttons)
    if any(_is_violet(c) for c in colors) and gradients:
        rep.add("A1.violet_gradient", "fail", "violet/indigo fill with a UIGradient")
    elif any(_is_violet(c) for c in colors):
        rep.add("A1.violet_accent", "warn", "violet/indigo accent")
    if gradients >= 2:
        rep.add("A2.gradients", "fail", f"{gradients} UIGradients")
    elif gradients == 1:
        rep.add("A2.gradients", "warn", "one UIGradient")
    if strokes_glow:
        rep.add("A4.glow", "warn", f"{strokes_glow} thick translucent UIStroke glow(s)")
    if shadows >= 3:
        rep.add("A4.shadows", "warn", f"{shadows} shadow/glow images")
    if emoji:
        rep.add("A5.emoji", "fail", f"{emoji} emoji in Text")
    if len(fonts) > 2:
        rep.add("A6.font_families", "fail", f"{len(fonts)} fonts: {', '.join(sorted(fonts))}")
    if len(text_sizes) > 6:
        rep.add("A6.type_scale", "fail", f"{len(text_sizes)} distinct TextSizes (no scale)")
    elif len(text_sizes) >= 2 and max(text_sizes) / min(text_sizes) < 1.6:
        rep.add("A6.flat_hierarchy", "warn", f"TextSizes {min(text_sizes)}-{max(text_sizes)}: no size contrast")
    if text_sizes and min(text_sizes) < 12:
        rep.add("A6.tiny_text", "fail", f"TextSize {min(text_sizes)} is unreadable on a phone")
    if len(text_sizes) >= 3 and not weights:
        rep.add("A6.one_weight", "warn", "several sizes but one font weight")
    if scaled_without_constraint:
        rep.add("A6.textscaled_unbounded", "warn", f"{scaled_without_constraint} TextScaled label(s) without UITextSizeConstraint")
    off, total = _grid_misses([abs(o) for o in offsets])
    m["spacing_off_grid"], m["spacing_values"] = off, total
    if total >= 4 and off / total > 0.25:
        rep.add("A7.spacing_grid", "fail", f"{off} of {total} offsets off the 4px grid")
    elif off:
        rep.add("A7.spacing_grid", "warn", f"{off} of {total} offsets off the 4px grid")
    if len(radii) > 3:
        rep.add("A7.radii", "warn", f"{len(radii)} corner radii")
    if low:
        rep.add("A8.contrast", "fail" if len(low) > 1 else "warn", "; ".join(low[:3]))
    hues = m["hues"]
    if hues > 4:
        rep.add("A9.palette", "fail", f"{hues} chromatic hue families")
    elif hues == 4:
        rep.add("A9.palette", "warn", "4 chromatic hue families")
    if placeholder:
        rep.add("A11.placeholder_copy", "fail", f"{placeholder} placeholder label(s)")
    if len(nodes) >= 4 and scales == 0:
        rep.add("A12.offset_only", "warn", "every Size/Position is Offset-only: the layout does not scale to phones")
    if small_buttons:
        rep.add("A12.touch_target", "warn", f"{small_buttons} button(s) under 44px tall")
    if any(c in classes for c in ("TextButton", "ImageButton")) and len(nodes) >= 4:
        if not any(c in classes for c in ("UIListLayout", "UIGridLayout", "UIPageLayout", "UITableLayout")):
            rep.add("A10.hand_positioned", "warn", "repeated elements without a UIListLayout/UIGridLayout")
        if not any(c in classes for c in ("UIAspectRatioConstraint", "UISizeConstraint", "UIScale")):
            rep.add("A12.no_constraints", "info", "no UIAspectRatioConstraint/UISizeConstraint/UIScale")
    rep.findings.extend(check_tweens(code).findings)
    if any(c in classes for c in ("TextButton", "ImageButton")) and "TweenInfo" not in code and "MouseEnter" not in code:
        rep.add("M10.no_feedback", "warn", "buttons without hover/press feedback")
    return rep


def check_tweens(code: str) -> Report:
    """TweenService motion rules (also used inside check_roblox_ui)."""
    rep = Report("roblox-motion")
    long_ui = very_long = ease_in = bouncy = infinite = 0
    for args in _TWEENINFO.findall(code):
        parts = [a.strip() for a in args.split(",")]
        try:
            dur = float(parts[0])
        except (ValueError, IndexError):
            continue
        if dur > 1.0:
            very_long += 1
        elif dur > 0.5:
            long_ui += 1
        if re.search(r"EasingStyle\.(?:Bounce|Elastic|Back)", args):
            bouncy += 1
        if re.search(r"EasingDirection\.In\b", args):
            ease_in += 1
        if len(parts) >= 4 and parts[3].strip() in ("-1",):
            infinite += 1
    rep.metrics.update(tweens=len(_TWEENINFO.findall(code)), long_tweens=long_ui, very_long_tweens=very_long)
    if ease_in:
        rep.add("M2.ease_in", "fail", f"{ease_in} tween(s) with EasingDirection.In")
    if very_long:
        rep.add("M3.duration", "fail", f"{very_long} UI tween(s) longer than 1 s")
    elif long_ui:
        rep.add("M3.duration", "warn", f"{long_ui} UI tween(s) longer than 0.5 s")
    if bouncy:
        rep.add("M4.bounce", "warn", f"{bouncy} Bounce/Elastic/Back tween(s)")
    if infinite:
        rep.add("M5.infinite", "warn", f"{infinite} tween(s) repeating forever")
    if re.search(r":Tween(?:Position|Size|SizeAndPosition)\(", code):
        rep.add("M11.deprecated_tween", "warn", "GuiObject:TweenPosition/TweenSize (deprecated; use TweenService)")
    return rep


# --- Roblox VFX ----------------------------------------------------------------------------------------------------

_NUMSEQ_KEYPOINT = re.compile(r"NumberSequenceKeypoint\.new\(\s*([-\d.]+)\s*,\s*([-\d.]+)")
_NUMSEQ = re.compile(r"NumberSequence\.new\(\s*([-\d.]+)(?:\s*,\s*([-\d.]+))?\s*\)")


def check_vfx(code: str) -> Report:
    """ParticleEmitter / Beam / Trail / post-processing budget and taste rules."""
    rep = Report("roblox-vfx")
    nodes = _json_tree(code.strip()) or _luau_tree(code)
    emitters = [n for n in nodes if n["class"] == "ParticleEmitter"]
    m = rep.metrics
    m["emitters"] = len(emitters)
    if not emitters and "ParticleEmitter" not in code and "Beam" not in code and "Trail" not in code:
        rep.add("V0.no_effect", "fail", "no ParticleEmitter, Beam or Trail")
        return rep
    rates, lifetimes, colors, big_opaque, light_all = [], [], [], 0, 0
    for n in emitters:
        p = n["props"]
        rates.extend(_numbers(p.get("Rate", "")))
        for s in (p.get("Lifetime", ""),):
            lifetimes.extend(_numbers(s)[:2])
        colors.extend(_value_colors(str(p.get("Color", ""))))
        size_max = max(_numbers(str(p.get("Size", "0"))) or [0])
        tr = _numbers(str(p.get("Transparency", "0")))
        if size_max > 15 and (not tr or min(tr) < 0.5):
            big_opaque += 1
        if _numbers(p.get("LightEmission", 0)) and _numbers(p.get("LightEmission", 0))[0] >= 0.9:
            light_all += 1
    colors += [tuple(int(v) for v in c) for c in _RGB_LUAU.findall(code)] if not colors else []
    emits = [int(float(v)) for v in re.findall(r":Emit\(\s*(\d+)", code)]
    m.update(max_rate=max(rates) if rates else 0, max_lifetime=max(lifetimes) if lifetimes else 0,
             hues=len(hue_buckets(set(colors))), emit_counts=emits)
    if len(emitters) > 12:
        rep.add("V1.emitter_count", "fail", f"{len(emitters)} emitters in one effect")
    elif len(emitters) > 6:
        rep.add("V1.emitter_count", "warn", f"{len(emitters)} emitters in one effect")
    if rates and max(rates) > 400:
        rep.add("V2.rate", "fail", f"Rate {max(rates):g} > 400/s (engine limit)")
    elif rates and max(rates) > 100:
        rep.add("V2.rate", "warn", f"Rate {max(rates):g} > 100/s (mobile cap)")
    if emits and max(emits) > 200:
        rep.add("V2.burst", "warn", f"Emit({max(emits)}) in one burst")
    if lifetimes and max(lifetimes) > 20:
        rep.add("V3.lifetime", "fail", f"Lifetime {max(lifetimes):g}s > 20s cap")
    elif lifetimes and max(lifetimes) > 6:
        rep.add("V3.lifetime", "warn", f"Lifetime {max(lifetimes):g}s lingers")
    if big_opaque:
        rep.add("V4.overdraw", "warn", f"{big_opaque} large (>15 studs) mostly opaque particle(s): overdraw")
    if m["hues"] > 3:
        rep.add("V5.colour_restraint", "warn", f"{m['hues']} hue families in one effect (noisy silhouette)")
    bloom = re.search(r"Intensity\s*=\s*([\d.]+)", code) if "BloomEffect" in code else None
    if bloom and float(bloom.group(1)) > 2:
        rep.add("V6.bloom", "fail", f"Bloom Intensity {bloom.group(1)}")
    elif bloom and float(bloom.group(1)) > 1:
        rep.add("V6.bloom", "warn", f"Bloom Intensity {bloom.group(1)}")
    thr = re.search(r"Threshold\s*=\s*([\d.]+)", code) if "BloomEffect" in code else None
    if thr and float(thr.group(1)) < 0.8:
        rep.add("V6.bloom_threshold", "warn", f"Bloom Threshold {thr.group(1)} blooms mid-tones")
    if emitters and light_all == len(emitters) and len(emitters) >= 3:
        rep.add("V6.all_additive", "warn", "every emitter at LightEmission 1: nothing reads as solid")
    phases = len(re.findall(r"task\.(?:wait|delay)\(", code)) + len(emits)
    if emitters and phases < 2 and len(emits) <= 1:
        rep.add("V7.no_layering", "warn", "one burst, no anticipation/impact/aftermath phases")
    continuous = [n for n in emitters if str(n["props"].get("Enabled", "")).lower() == "true" and
                  (_numbers(n["props"].get("Rate", 0)) or [0])[0] > 0]
    if continuous and not re.search(r"Debris|:Destroy\(\)|Enabled\s*=\s*false", code):
        rep.add("V8.no_cleanup", "warn", "continuous emitters never disabled or destroyed")
    if re.search(r"Size\s*=\s*NumberSequence\.new\(\s*[\d.]+\s*\)", code) and emitters:
        rep.add("V9.flat_size", "info", "constant particle size: no growth/shrink over life")
    return rep


# --- answer -> report ------------------------------------------------------------------------------------------------

_FENCE = re.compile(r"```[ \t]*([\w+-]*)[^\n]*\n(.*?)```", re.S)


def extract(answer: str) -> dict[str, list[str]]:
    """Fenced blocks by language family: html (html+css+svg), lua, json, other."""
    out: dict[str, list[str]] = {"html": [], "css": [], "lua": [], "json": [], "other": []}
    for lang, body in _FENCE.findall(answer or ""):
        lang = lang.lower()
        key = ("html" if lang in ("html", "htm", "svg", "xml", "vue", "jsx", "tsx") else "css" if lang in ("css", "scss")
               else "lua" if lang in ("lua", "luau") else "json" if lang in ("json", "json5") else "other")
        if key == "other" and ("<html" in body or "<!doctype" in body.lower() or "<div" in body):
            key = "html"
        elif key == "other" and "Instance.new" in body:
            key = "lua"
        out[key].append(body)
    if not any(out.values()) and answer:
        if "<html" in answer.lower() or "<!doctype" in answer.lower():
            out["html"].append(answer)
        elif "Instance.new" in answer:
            out["lua"].append(answer)
    return out


def html_document(parts: dict[str, list[str]]) -> str:
    html = "\n".join(parts["html"])
    if parts["css"]:
        html += "\n<style>\n" + "\n".join(parts["css"]) + "\n</style>"
    return html


def check_answer(answer: str, kind: str = "auto") -> Report:
    """Score a model answer. kind: html | roblox-ui | roblox-vfx | auto (chosen from the fenced blocks)."""
    parts = extract(answer)
    code = "\n".join(parts["lua"] + parts["json"])
    if kind == "auto":
        if parts["html"] or parts["css"]:
            kind = "html"
        elif "ParticleEmitter" in code or "Beam" in code and "Attachment" in code:
            kind = "roblox-vfx"
        else:
            kind = "roblox-ui"
    if kind == "html":
        doc = html_document(parts)
        if not doc.strip():
            rep = Report("html")
            rep.add("A0.no_markup", "fail", "no fenced html/css block in the answer")
            return rep
        return check_html(doc)
    if kind == "roblox-vfx":
        if not code.strip():
            rep = Report("roblox-vfx")
            rep.add("V0.no_effect", "fail", "no fenced Luau/JSON block in the answer")
            return rep
        return check_vfx(code)
    if not code.strip():
        rep = Report("roblox-ui")
        rep.add("R0.no_tree", "fail", "no fenced Luau/JSON block in the answer")
        return rep
    return check_roblox_ui(code)


def auto_checks(spec: dict, body: str):
    """The evals/night-school hook: one `design:score` check from a task's `auto.design` block."""
    from .eval_checks import Check
    spec = spec or {}
    rep = check_answer(body, spec.get("kind", "auto"))
    ok = rep.passed(int(spec.get("min_score", PASS_SCORE)), int(spec.get("max_fails", 0)))
    detail = "" if ok else rep.summary()[:200]
    checks = [Check("design:score", ok, detail)]
    # Words the answer must contain anywhere (the brief's subject, a required element), case-insensitive. HTML answers
    # have no Luau block, so the generic `require` patterns (which read Luau blocks) cannot see them.
    for needle in spec.get("require_text", []) or []:
        found = bool(re.search(re.escape(str(needle)), body or "", re.I))
        checks.append(Check("design:text:" + re.sub(r"\W+", "_", str(needle))[:24], found,
                            "" if found else f"the answer does not mention {needle!r}"))
    return checks


def main(argv=None) -> int:
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Score an HTML page, Roblox UI tree or VFX script for AI-look tells.")
    ap.add_argument("file", nargs="?", help="file to score (default: stdin); .md answers are read for fenced blocks")
    ap.add_argument("--kind", default="auto", choices=["auto", "html", "roblox-ui", "roblox-vfx"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    if args.file and not args.file.endswith(".md"):
        suffix = args.file.rsplit(".", 1)[-1].lower()
        text = f"```{suffix}\n{text}\n```"
    rep = check_answer(text, args.kind)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=1))
    else:
        print(rep.summary())
        for f in rep.findings:
            print(f"  {f.level:4} {f.id}: {f.detail}")
    return 0 if rep.passed() else 1


if __name__ == "__main__":
    raise SystemExit(main())
