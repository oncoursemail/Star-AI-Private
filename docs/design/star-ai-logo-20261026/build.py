"""Builds the three STAR AI logo options: SVG sources, PNG sizes and a multi-size .ico per option.

Everything is drawn here as paths (no fonts). PNGs are rendered by headless Microsoft Edge (real Chromium SVG
renderer) and cropped with Pillow; the .ico is written by Pillow and reopened to list its sizes.

Run:  <python with Pillow> build.py            (writes option-a/, option-b/, option-c/)
      <python with Pillow> build.py --shots    (also screenshots preview.html in dark and light)
"""
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PROFILE = Path(os.environ.get("TEMP", str(OUT))) / "star-logo-edge-profile"
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Palette (from frontend/src/appearance.ts: Obsidian #101113 / accent #E4C48B, Pearl #F7F5F0 / accent #785C2D)
INK, PAPER = "#101113", "#F7F5F0"
TEXT_DARK_BG, TEXT_LIGHT_BG = "#F3F1EC", "#232524"
GOLD = ["#F7DEAA", "#E8BF76", "#C99D58", "#9C7740"]        # light -> deep, for dark backgrounds
GOLD_ON_LIGHT = ["#DDB063", "#C79443", "#9E7333", "#785C2D"]  # deeper set for Pearl / white
ACCENT_DARK_BG, ACCENT_LIGHT_BG = "#E8BF76", "#8A6830"


def f(v):
    s = "%.2f" % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def svg(view_w, view_h, body, w=None, h=None):
    size = f' width="{f(w)}" height="{f(h)}"' if w else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {f(view_w)} {f(view_h)}"{size}>'
            f"{body}</svg>\n")


# ---------------------------------------------------------------- the shared star (Star's hair clip)
def clip_star(cx, cy, r, k=0.28, tip=0.0):
    """Four-point star with concave sides, as on Star's hair clip.

    Returns (outline_d, facets) where facets is a list of (tone_index, d). Each ray is split along its axis into
    two facets; tone 0 is the brightest. Light comes from the upper left, a little more from above.
    """
    dirs = [(0, -1), (1, 0), (0, 1), (-1, 0)]  # up, right, down, left (screen coordinates)
    tips = []
    for dx, dy in dirs:
        px, py = -dy, dx  # perpendicular, clockwise side
        mid = (cx + dx * r, cy + dy * r)
        a = (mid[0] - px * tip / 2, mid[1] - py * tip / 2)
        b = (mid[0] + px * tip / 2, mid[1] + py * tip / 2)
        tips.append((a, b, mid))
    q = r * k
    ctrls = [(cx + q, cy - q), (cx + q, cy + q), (cx - q, cy + q), (cx - q, cy - q)]
    P = lambda p: f"{f(p[0])} {f(p[1])}"
    d = f"M{P(tips[0][0])}"
    for i in range(4):
        a, b, _ = tips[i]
        na = tips[(i + 1) % 4][0]
        if tip:
            d += f"L{P(b)}"
        d += f"Q{P(ctrls[i])} {P(na)}"
    d += "Z"
    light = (-0.45, -0.89)
    facets = []
    for i in range(4):
        a, b, mid = tips[i]
        n = (i + 1) % 4
        na, nb, nmid = tips[n]
        c = ctrls[i]
        c1 = ((b[0] + c[0]) / 2, (b[1] + c[1]) / 2)
        c2 = ((c[0] + na[0]) / 2, (c[1] + na[1]) / 2)
        m = ((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2)
        # clockwise half of ray i: faces the clockwise perpendicular of ray i
        dx, dy = dirs[i]
        cw = (-dy, dx)
        facets.append((cw[0] * light[0] + cw[1] * light[1],
                       f"M{f(cx)} {f(cy)}L{P(mid)}" + (f"L{P(b)}" if tip else "") + f"Q{P(c1)} {P(m)}Z"))
        ndx, ndy = dirs[n]
        ccw = (ndy, -ndx)
        facets.append((ccw[0] * light[0] + ccw[1] * light[1],
                       f"M{f(cx)} {f(cy)}L{P(m)}Q{P(c2)} {P(na)}" + (f"L{P(nmid)}" if tip else "") + "Z"))
    ranks = sorted({round(v, 3) for v, _ in facets}, reverse=True)
    return d, [(ranks.index(round(v, 3)), dd) for v, dd in facets]


def star_two_tone(cx, cy, r, k, tip, light, dark):
    """Star split along the top-right/bottom-left diagonal: upper-left half light, lower-right half dark."""
    d, _ = clip_star(cx, cy, r, k, tip)
    big = r * 2
    clip_id = f"h{abs(hash((cx, cy, r, k, tip, light))) % 99999}"
    return (f'<clipPath id="{clip_id}"><path d="M{f(cx - big)} {f(cy - big)}H{f(cx + big)}L{f(cx - big)} {f(cy + big)}Z"/></clipPath>'
            f'<path fill="{dark}" d="{d}"/><path fill="{light}" clip-path="url(#{clip_id})" d="{d}"/>')


# ---------------------------------------------------------------- option A: Clip
def a_emblem(pal):
    _, facets = clip_star(32, 32, 30.5, k=0.27, tip=1.6)
    return svg(64, 64, "".join(f'<path fill="{pal[t]}" d="{d}"/>' for t, d in facets))


def a_emblem16(pal):
    # 16-px grid: rays 2 px wide at the tips, centred on the pixel grid; two tones only.
    return svg(16, 16, star_two_tone(8, 8, 8, k=0.2, tip=2, light=pal[1], dark=pal[3]))


def a_emblem24(pal):
    return svg(24, 24, star_two_tone(12, 12, 12, k=0.22, tip=2, light=pal[1], dark=pal[3]))


# ---------------------------------------------------------------- option B: Voice
BUBBLE = ("M19 5H45A16 16 0 0 1 61 21V35A16 16 0 0 1 45 51H25.5"
          "L11.2 60.6Q8 62.6 8.6 58.8L9.6 49.4"
          "A16 16 0 0 1 3 35V21A16 16 0 0 1 19 5Z")


def b_emblem(pal):
    star, _ = clip_star(32, 28, 15.5, k=0.27, tip=1.2)
    return svg(64, 64, f'<path fill="{pal[1]}" d="{BUBBLE}"/><path fill="{INK}" d="{star}"/>')


def b_emblem16(pal):
    bubble = ("M4.5 1H11.5A3.5 3.5 0 0 1 15 4.5V9.5A3.5 3.5 0 0 1 11.5 13H7L3.4 15.6Q2.3 16.2 2.4 15L2.6 12.6"
              "A3.5 3.5 0 0 1 1 9.5V4.5A3.5 3.5 0 0 1 4.5 1Z")
    star, _ = clip_star(8, 7, 4.6, k=0.30, tip=2)
    return svg(16, 16, f'<path fill="{pal[1]}" d="{bubble}"/><path fill="{INK}" d="{star}"/>')


def b_emblem24(pal):
    bubble = ("M7 2H17A6 6 0 0 1 23 8V13A6 6 0 0 1 17 19H10L5 22.6Q3.7 23.5 3.9 22L4.2 18.3"
              "A6 6 0 0 1 1 13V8A6 6 0 0 1 7 2Z")
    star, _ = clip_star(12, 10.5, 6.2, k=0.29, tip=1)
    return svg(24, 24, f'<path fill="{pal[1]}" d="{bubble}"/><path fill="{INK}" d="{star}"/>')


# ---------------------------------------------------------------- option C: Tile
def squircle(x, y, w, h, r, k=0.22):
    """Rounded square with continuous (superellipse-like) corners: control points sit k*r from the corner."""
    c = r * k
    return (f"M{f(x + r)} {f(y)}H{f(x + w - r)}C{f(x + w - c)} {f(y)} {f(x + w)} {f(y + c)} {f(x + w)} {f(y + r)}"
            f"V{f(y + h - r)}C{f(x + w)} {f(y + h - c)} {f(x + w - c)} {f(y + h)} {f(x + w - r)} {f(y + h)}"
            f"H{f(x + r)}C{f(x + c)} {f(y + h)} {f(x)} {f(y + h - c)} {f(x)} {f(y + h - r)}"
            f"V{f(y + r)}C{f(x)} {f(y + c)} {f(x + c)} {f(y)} {f(x + r)} {f(y)}Z")


def square_s(left, right, top, bottom, s, rc):
    """Centre line of the rounded-square S; left/right/top/bottom are the outer edges."""
    h = s / 2
    x0, x1, y0, y1 = left + h, right - h, top + h, bottom - h
    ym = (top + bottom) / 2
    return (f"M{f(right)} {f(y0)}H{f(x0 + rc)}A{f(rc)} {f(rc)} 0 0 0 {f(x0)} {f(y0 + rc)}V{f(ym - rc)}"
            f"A{f(rc)} {f(rc)} 0 0 0 {f(x0 + rc)} {f(ym)}H{f(x1 - rc)}A{f(rc)} {f(rc)} 0 0 1 {f(x1)} {f(ym + rc)}"
            f"V{f(y1 - rc)}A{f(rc)} {f(rc)} 0 0 1 {f(x1 - rc)} {f(y1)}H{f(left)}")


def c_tile(size, inset, radius, s_box, s, rc, pal):
    l, r, t, b = s_box
    return svg(size, size, f'<path fill="{pal[1]}" d="{squircle(inset, inset, size - 2 * inset, size - 2 * inset, radius)}"/>'
               + stroke(square_s(l, r, t, b, s, rc), s, color=INK))


def c_emblem(pal):
    return c_tile(64, 2, 19, (18, 46, 12, 52), 8, 7, pal)


def c_emblem16(pal):
    return c_tile(16, 0, 5, (4, 12, 3, 13), 2, 2, pal)


def c_emblem24(pal):
    return c_tile(24, 1, 7, (6, 18, 4, 19), 3, 3, pal)


# ---------------------------------------------------------------- lettering (cap height 100)
def stroke(d, w, cap="butt", join="miter", color="currentColor"):
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{f(w)}" '
            f'stroke-linecap="{cap}" stroke-linejoin="{join}" stroke-miterlimit="4"/>')


def poly(points):
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in points)


def letters_a(color):
    """Chamfered caps, light weight, wide tracking: the facets of the clip carried into type."""
    s, h, c, mc = 13, 6.5, 16, 11
    def S(W):
        x0, x1, y0, y1, ym = h, W - h, h, 100 - h, 49
        # Terminals end on the chamfer, so they are cut at 45 degrees like a facet.
        return stroke(poly([(x1, y0 + c), (x1 - c, y0), (x0 + c, y0), (x0, y0 + c), (x0, ym - mc),
                            (x0 + mc, ym), (x1 - mc, ym), (x1, ym + mc), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1),
                            (x0, y1 - c)]), s, color=color)
    def T(W):
        return stroke(f"M0 {h}H{W}M{W / 2} {h}V100", s, color=color)
    def A(W):
        x0, x1, y0 = h, W - h, h
        return stroke(poly([(x0, 100), (x0, y0 + c), (x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, 100)])
                      + f"M{x0} 60H{x1}", s, color=color)
    def R(W):
        x0, x1, y0, yb = h, W - h, h, 58
        leg_x = x0 + (x1 - x0) * 0.42
        slope = (x1 - leg_x) / (100 - yb)
        return stroke(poly([(x0, 100), (x0, y0), (x1 - c, y0), (x1, y0 + c), (x1, yb - mc), (x1 - mc, yb), (x0, yb)])
                      + poly([(leg_x, yb), (x1 + slope * 12, 112)]), s, color=color)
    def I(W):
        return stroke(f"M{h} 0V100", s, color=color)
    return dict(S=(S, 62), T=(T, 64), A=(A, 66), R=(R, 64), I=(I, s)), 28


def letters_b(color):
    """Round geometric caps, round ends: friendly, the voice of a companion."""
    s = 16
    h = s / 2
    def S(W):
        cx, rx = W / 2, W / 2 - h
        ryt, ryb = 20.2, 21.8
        cyt = h + ryt
        cyb = cyt + ryt + ryb
        pt = lambda cy, ry, deg: (cx + rx * math.cos(math.radians(deg)), cy - ry * math.sin(math.radians(deg)))
        p0, j, p1 = pt(cyt, ryt, 28), (cx, cyt + ryt), pt(cyb, ryb, 208)
        d = (f"M{f(p0[0])} {f(p0[1])}A{f(rx)} {f(ryt)} 0 1 0 {f(j[0])} {f(j[1])}"
             f"A{f(rx)} {f(ryb)} 0 1 1 {f(p1[0])} {f(p1[1])}")
        return stroke(d, s, cap="round", join="round", color=color)
    def T(W):
        return stroke(f"M{h} {h}H{W - h}M{W / 2} {h}V{100 - h}", s, cap="round", join="round", color=color)
    def A(W):
        top, bot = h, 100 - h
        xl = lambda y: W / 2 - (W / 2 - h) * (y - top) / (bot - top)
        yc = 68
        return stroke(f"M{h} {bot}L{W / 2} {top}L{W - h} {bot}M{f(xl(yc))} {yc}H{f(W - xl(yc))}", s,
                      cap="round", join="round", color=color)
    def R(W):
        yb = 56
        rb = (yb - h) / 2
        xb = W - h - rb
        return stroke(f"M{h} {100 - h}V{h}H{f(xb)}A{f(rb)} {f(rb)} 0 0 1 {f(xb)} {yb}H{h}"
                      f"M{f(xb - 6)} {yb}L{W - h} {100 - h}", s, cap="round", join="round", color=color)
    def I(W):
        return stroke(f"M{h} {h}V{100 - h}", s, cap="round", color=color)
    return dict(S=(S, 60), T=(T, 62), A=(A, 74), R=(R, 62), I=(I, s)), 24


def letters_c(color):
    """Heavy rounded-square caps, built like the S in the tile."""
    s, h, rc = 18, 9, 15
    def S(W):
        return stroke(square_s(0, W, 0, 100, s, rc), s, color=color)
    def T(W):
        return stroke(f"M0 {h}H{W}M{W / 2} {h}V100", s, color=color)
    def A(W):
        x0, x1 = h, W - h
        return stroke(f"M{x0} 100V{h + rc}A{rc} {rc} 0 0 1 {x0 + rc} {h}H{x1 - rc}A{rc} {rc} 0 0 1 {x1} {h + rc}V100"
                      f"M{x0} 60H{x1}", s, color=color)
    def R(W):
        x0, x1, yb = h, W - h, 57
        leg_x = x0 + (x1 - x0) * 0.40
        slope = (x1 - leg_x) / (100 - yb)
        return stroke(f"M{x0} 100V{h}H{x1 - rc}A{rc} {rc} 0 0 1 {x1} {h + rc}V{yb - rc}A{rc} {rc} 0 0 1 {x1 - rc} {yb}H{x0}"
                      f"M{f(leg_x)} {yb}L{f(x1 + slope * 12)} 112", s, color=color)
    def I(W):
        return stroke(f"M{h} 0V100", s, color=color)
    return dict(S=(S, 64), T=(T, 66), A=(A, 68), R=(R, 66), I=(I, s)), 20


def wordmark(letters_fn, text_color, accent_color):
    """Returns (svg_body, width) for 'STAR AI' at cap height 100, starting at x=0."""
    parts, x = [], 0.0
    word_gap = None
    for word, color in (("STAR", text_color), ("AI", accent_color)):
        glyphs, track = letters_fn(color)
        word_gap = word_gap or track * 1.9
        for i, ch in enumerate(word):
            draw, w = glyphs[ch]
            parts.append(f'<g transform="translate({f(x)} 0)">{draw(w)}</g>')
            x += w + (track if i < len(word) - 1 else 0)
        x += word_gap
    clip = '<clipPath id="baseline"><rect x="-500" y="-60" width="3000" height="160"/></clipPath>'
    return clip + '<g clip-path="url(#baseline)">' + "".join(parts) + "</g>", x - word_gap


def lockup(emblem_svg_body, emblem_view, letters_fn, text_color, accent_color, emblem_h=150, gap=50, dy=0):
    words, ww = wordmark(letters_fn, text_color, accent_color)
    ev_w, ev_h = emblem_view
    scale = emblem_h / ev_h
    ew = ev_w * scale
    top = (100 - emblem_h) / 2 + dy
    pad = 4
    y0 = min(0, top) - pad
    H = max(100, top + emblem_h) - y0 + pad
    W = ew + gap + ww + pad * 2
    body = (f'<g transform="translate({f(pad)} {f(top)}) scale({f(scale)})">{emblem_svg_body}</g>'
            f'<g transform="translate({f(pad + ew + gap)} 0)">{words}</g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {f(y0)} {f(W)} {f(H)}">{body}</svg>\n'


def inner(svg_text):
    a = svg_text.index(">") + 1
    return svg_text[a:svg_text.rindex("</svg>")]


def view_of(svg_text):
    vb = svg_text.split('viewBox="')[1].split('"')[0].split()
    return float(vb[2]), float(vb[3])


OPTIONS = {
    "a": dict(name="Clip", emblem=a_emblem, e16=a_emblem16, e24=a_emblem24, letters=letters_a,
              raster={16: "emblem-16.svg", 24: "emblem-24.svg"}, emblem_h=136, gap=50, dy=0),
    "b": dict(name="Voice", emblem=b_emblem, e16=b_emblem16, e24=b_emblem24, letters=letters_b,
              raster={16: "emblem-16.svg", 24: "emblem-24.svg"}, emblem_h=150, gap=46, dy=8),
    "c": dict(name="Tile", emblem=c_emblem, e16=c_emblem16, e24=c_emblem24, letters=letters_c,
              raster={16: "emblem-16.svg", 24: "emblem-24.svg"}, emblem_h=140, gap=46, dy=0),
}


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def edge_shot(html_path, png_path, w, h):
    PROFILE.mkdir(parents=True, exist_ok=True)
    png_path = Path(png_path)
    if png_path.exists():
        png_path.unlink()
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={PROFILE}",
                    "--hide-scrollbars", "--force-device-scale-factor=1", "--default-background-color=00000000",
                    f"--window-size={w},{h}", f"--screenshot={png_path}", html_path.as_uri()],
                   check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # The Edge launcher can return before its headless child has written the file.
    last = -1
    for _ in range(300):
        size = png_path.stat().st_size if png_path.exists() else -1
        if size > 0 and size == last:
            return
        last = size
        time.sleep(0.2)
    raise RuntimeError(f"Edge wrote no screenshot: {png_path}")


def build_option(key, o):
    d = OUT / f"option-{key}"
    e = o["emblem"](GOLD)
    write(d / "emblem.svg", e)
    write(d / "emblem-light.svg", o["emblem"](GOLD_ON_LIGHT))
    write(d / "emblem-16.svg", o["e16"](GOLD))
    write(d / "emblem-16-light.svg", o["e16"](GOLD_ON_LIGHT))
    write(d / "emblem-24.svg", o["e24"](GOLD))
    write(d / "emblem-24-light.svg", o["e24"](GOLD_ON_LIGHT))
    for name, pal, tc, ac in (("wordmark.svg", GOLD, TEXT_DARK_BG, ACCENT_DARK_BG),
                              ("wordmark-light.svg", GOLD_ON_LIGHT, TEXT_LIGHT_BG, ACCENT_LIGHT_BG)):
        em = o["emblem"](pal)
        write(d / name, lockup(inner(em), view_of(em), o["letters"], tc, ac, o["emblem_h"], o["gap"], o["dy"]))
    # Rasterize: one page with every size laid out left to right, then crop.
    xs, x = {}, 0
    for s in SIZES:
        xs[s] = x
        x += s + 8
    imgs = "".join(f'<img src="{o["raster"].get(s, "emblem.svg")}" width="{s}" height="{s}" '
                   f'style="position:absolute;left:{xs[s]}px;top:0">' for s in SIZES)
    page = d / "_raster.html"
    write(page, f'<!doctype html><html><body style="margin:0;background:transparent">{imgs}</body></html>')
    sheet = d / "_raster.png"
    edge_shot(page, sheet, x, 512)
    im = Image.open(sheet).convert("RGBA")
    pngs = {}
    for s in SIZES:
        p = d / f"emblem-{s}.png"
        im.crop((xs[s], 0, xs[s] + s, s)).save(p)
        pngs[s] = p
    page.unlink()
    sheet.unlink()
    ico = d / "star-ai.ico"
    biggest = Image.open(pngs[256])
    biggest.save(ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                 append_images=[Image.open(pngs[s]) for s in ICO_SIZES if s != 256])
    check = Image.open(ico)
    got = sorted(check.info.get("sizes", set()))
    print(f"option-{key}: ico sizes {got}")


CONCEPTS = {
    "a": "The four-point star from Star's hair clip, faceted and lit from the upper left; light chamfered caps.",
    "b": "A speech bubble carrying the clip star: the assistant who talks back; round friendly caps.",
    "c": "A gold app tile with a heavy rounded-square S; typographic, the strongest at 16 px and on any taskbar.",
}

PREVIEW_CSS = """
:root{--page:#0B0C0D;--panel:#101113;--side:#151618;--line:#26272B;--text:#F3F1EC;--muted:#B6B3AC;--btn:#E4C48B;--on-btn:#17140E;
 --task:#1C1C1E;--task-line:#2E2E31;--ph:#3A3B40;--title:#202124;--tab:#2B2C30;--tabbar:#1B1C1F;--wall:#1E2836}
:root[data-theme="light"]{--page:#ECE9E2;--panel:#F7F5F0;--side:#EEEBE4;--line:#D6D2C8;--text:#232524;--muted:#535950;--btn:#785C2D;--on-btn:#FFFEFA;
 --task:#EEF0F3;--task-line:#D5D8DD;--ph:#C4C8CF;--title:#F3F3F3;--tab:#FFFFFF;--tabbar:#DEE1E6;--wall:#4E6A86}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text);font:14px/1.45 'Segoe UI Variable Text','Segoe UI',system-ui,sans-serif}
.dk{display:inline-block}.lt{display:none}
:root[data-theme="light"] .dk{display:none}:root[data-theme="light"] .lt{display:inline-block}
header{padding:28px 24px 8px 144px}
h1{font:600 22px/1.2 'Segoe UI Variable Display','Segoe UI',sans-serif;margin:0 0 4px}
header p{margin:0;color:var(--muted)}
.grid{display:grid;grid-template-columns:120px repeat(3,1fr);gap:12px;padding:12px 24px 28px}
.label{color:var(--muted);font-size:12px;padding-top:10px;text-align:right;padding-right:6px}
.col-head h2{margin:0;font:600 16px/1.2 'Segoe UI Variable Display','Segoe UI',sans-serif}
.col-head p{margin:4px 0 0;color:var(--muted);font-size:12.5px;min-height:36px}
.cell{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;min-height:60px}
.hero{display:flex;align-items:center;justify-content:center;gap:28px;height:170px}
.sizes{display:flex;align-items:flex-end;gap:14px;padding:14px 16px;height:112px}
.sizes figure{margin:0;text-align:center;font-size:10.5px;color:var(--muted)}
.sizes img{display:block;margin:0 auto 4px}
/* sidebar */
.side{display:flex;height:150px}
.side nav{width:248px;background:var(--side);border-right:1px solid var(--line);padding:14px 12px}
.brand{display:flex;align-items:center;height:28px;padding:0 6px;margin-bottom:12px}
.row{height:30px;border-radius:8px;padding:5px 8px;color:var(--muted);font-size:13px}
.row.on{background:rgba(127,127,127,.12);color:var(--text)}
/* sign-in */
.signin{height:290px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px}
.btn{background:var(--btn);color:var(--on-btn);border-radius:8px;padding:8px 22px;font-weight:600;font-size:13.5px}
.fine{color:var(--muted);font-size:12px}
/* windows */
.win{padding:0}
.titlebar{height:32px;background:var(--title);display:flex;align-items:center;gap:8px;padding:0 0 0 10px;font-size:12px;border-bottom:1px solid var(--line)}
.titlebar .ctl{margin-left:auto;display:flex}.titlebar .ctl span{width:40px;text-align:center;color:var(--muted)}
.taskbar{height:48px;background:var(--task);border-top:1px solid var(--task-line);display:flex;align-items:center;justify-content:center;gap:6px;position:relative}
.tb{width:40px;height:40px;border-radius:6px;display:flex;align-items:center;justify-content:center;position:relative}
.tb i{width:24px;height:24px;border-radius:6px;background:var(--ph);display:block}
.tb.on{background:rgba(127,127,127,.14)}
.tb.on::after{content:"";position:absolute;bottom:2px;width:16px;height:3px;border-radius:2px;background:#4CC2FF}
.tray{position:absolute;right:10px;display:flex;align-items:center;gap:10px;font-size:11px;color:var(--text)}
.tray i{width:16px;height:16px;border-radius:3px;background:var(--ph);display:block}
.winbody{height:58px;background:var(--panel)}
/* browser tab */
.tabbar{background:var(--tabbar);height:40px;display:flex;align-items:flex-end;padding:0 10px}
.tab{background:var(--tab);height:32px;border-radius:8px 8px 0 0;display:flex;align-items:center;gap:8px;padding:0 12px;width:210px;font-size:12px}
.tab .x{margin-left:auto;color:var(--muted)}
.tab.off{background:transparent;color:var(--muted)}
.urlbar{background:var(--tab);height:34px;display:flex;align-items:center;padding:0 12px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line)}
/* desktop */
.desk{background:var(--wall);height:300px;display:flex;align-items:center;justify-content:space-around;padding:16px}
.shortcut{width:84px;text-align:center;color:#fff;font-size:12px;text-shadow:0 1px 2px rgba(0,0,0,.7)}
.shortcut img{display:block;margin:0 auto 4px}
/* installer */
.setup{background:#F0F0F0;margin:14px;border:1px solid #9a9a9a;color:#1a1a1a;font:12px 'Segoe UI',sans-serif}
.setup .t{height:28px;background:#fff;display:flex;align-items:center;gap:6px;padding:0 8px;border-bottom:1px solid #ddd}
.setup .b{display:flex;height:220px;background:#fff}
.setup .l{width:130px;background:#101113;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px}
.setup .r{padding:16px;flex:1}.setup .r b{font-size:14px;display:block;margin-bottom:8px}
.setup .f{height:40px;border-top:1px solid #ddd;display:flex;justify-content:flex-end;align-items:center;gap:8px;padding:0 10px}
.setup .f span{border:1px solid #aaa;background:#fdfdfd;padding:3px 14px}
"""


def make_preview():
    def col(k, html):
        return f'<div class="cell">{html}</div>'
    rows = []
    rows.append(("", [f'<div class="col-head"><h2>Option {k.upper()}: {OPTIONS[k]["name"]}</h2><p>{CONCEPTS[k]}</p></div>'
                      for k in "abc"], True))
    def wm(k, h, extra=""):
        return (f'<img class="dk" src="option-{k}/wordmark.svg" height="{h}" alt="STAR AI"{extra}>'
                f'<img class="lt" src="option-{k}/wordmark-light.svg" height="{h}" alt="STAR AI"{extra}>')
    def em(k, h, small=""):
        name = f"emblem{small}"
        return (f'<img class="dk" src="option-{k}/{name}.svg" width="{h}" height="{h}" alt="">'
                f'<img class="lt" src="option-{k}/{name}-light.svg" width="{h}" height="{h}" alt="">')
    rows.append(("Mark and lockup", [col(k, f'<div class="hero">{em(k, 112)}{wm(k, 40)}</div>') for k in "abc"], False))
    rows.append(("Icon sizes (PNG in the .ico)", [col(k, '<div class="sizes">' + "".join(
        f'<figure><img src="option-{k}/emblem-{s}.png" width="{s}" height="{s}" alt="">{s}</figure>'
        for s in (16, 24, 32, 48, 64)) + "</div>") for k in "abc"], False))
    rows.append(("App sidebar, 20 px mark", [col(k, f'<div class="side"><nav><div class="brand">{wm(k, 22)}</div>'
                 '<div class="row on">Chat</div><div class="row">Projects</div><div class="row">Settings</div></nav></div>')
                 for k in "abc"], False))
    rows.append(("Sign-in screen", [col(k, f'<div class="signin">{wm(k, 54)}<span class="btn">Sign in</span>'
                 '<span class="fine">Local first. Your files stay yours.</span></div>') for k in "abc"], False))
    rows.append(("Window title bar 16, taskbar 24, tray 16", [col(k,
        f'<div class="win"><div class="titlebar"><img src="option-{k}/emblem-16.png" width="16" height="16" alt="">STAR AI'
        '<span class="ctl"><span>&#8211;</span><span>&#9633;</span><span>&#10005;</span></span></div><div class="winbody"></div>'
        '<div class="taskbar"><span class="tb"><i></i></span><span class="tb"><i></i></span>'
        f'<span class="tb on"><img src="option-{k}/emblem-24.png" width="24" height="24" alt=""></span><span class="tb"><i></i></span>'
        f'<span class="tray"><i></i><img src="option-{k}/emblem-16.png" width="16" height="16" alt=""><i></i>17:58</span></div></div>')
        for k in "abc"], False))
    rows.append(("Favicon in a browser tab", [col(k,
        f'<div class="tabbar"><div class="tab"><img src="option-{k}/emblem-16.png" width="16" height="16" alt="">STAR AI'
        '<span class="x">&#10005;</span></div><div class="tab off">New tab</div></div><div class="urlbar">localhost:8080</div>')
        for k in "abc"], False))
    rows.append(("Desktop shortcut 48 and 256", [col(k,
        f'<div class="desk"><div class="shortcut"><img src="option-{k}/emblem-48.png" width="48" height="48" alt="">STAR AI</div>'
        f'<img src="option-{k}/emblem-256.png" width="256" height="256" alt=""></div>') for k in "abc"], False))
    rows.append(("Installer (Inno Setup)", [col(k,
        f'<div class="setup"><div class="t"><img src="option-{k}/emblem-16.png" width="16" height="16" alt="">Setup - STAR AI</div>'
        f'<div class="b"><div class="l"><img src="option-{k}/emblem.svg" width="56" height="56" alt="">'
        f'<img src="option-{k}/wordmark.svg" height="16" alt=""></div><div class="r"><b>Welcome to the STAR AI Setup Wizard</b>'
        'This will install STAR AI on your computer.<br><br>Click Next to continue, or Cancel to exit Setup.</div></div>'
        '<div class="f"><span>Next &gt;</span><span>Cancel</span></div></div>') for k in "abc"], False))
    body = []
    for label, cells, head in rows:
        body.append(f'<div class="label">{label}</div>' + "".join(cells))
    html = (f'<!doctype html>\n<html lang="en" data-theme="dark"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>STAR AI logo options</title>'
            f'<link rel="icon" href="option-a/emblem-16.png"><style>{PREVIEW_CSS}</style></head><body>'
            '<header><h1>STAR AI logo options</h1><p>Three directions, shown where the logo will live. '
            'Theme: add <code>?light</code> to the address for Pearl.</p></header>'
            f'<div class="grid">{"".join(body)}</div>'
            "<script>if(location.search.indexOf('light')>-1)document.documentElement.dataset.theme='light'</script>"
            "</body></html>\n")
    write(OUT / "preview.html", html)


def shots():
    page = OUT / "preview.html"
    for theme in ("dark", "light"):
        tmp = OUT / f"_preview-{theme}.html"
        tmp.write_text(page.read_text(encoding="utf-8").replace('data-theme="dark"', f'data-theme="{theme}"'),
                       encoding="utf-8")
        edge_shot(tmp, OUT / f"preview-{theme}.png", 1440, 1860)
        tmp.unlink()
        print("wrote", f"preview-{theme}.png")


if __name__ == "__main__":
    for key, o in OPTIONS.items():
        build_option(key, o)
    make_preview()
    if "--shots" in sys.argv:
        shots()
