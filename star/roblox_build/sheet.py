"""Contact sheets (2x2 shot grids, labelled rows) with Pillow. Used for the vision critic and for reports."""
from __future__ import annotations

from pathlib import Path


def grid(files: list[str], out: Path, *, cell=(640, 350), cols: int = 2, label: str = "", quality: int = 85) -> Path:
    from PIL import Image, ImageDraw
    images = [Image.open(f).convert("RGB") for f in files if f and Path(f).is_file()]
    rows = max(1, (len(images) + cols - 1) // cols)
    top = 26 if label else 0
    sheet = Image.new("RGB", (cell[0] * cols, cell[1] * rows + top), (18, 18, 20))
    for i, im in enumerate(images):
        im = im.copy()
        im.thumbnail(cell)
        sheet.paste(im, ((i % cols) * cell[0], top + (i // cols) * cell[1]))
    if label:
        ImageDraw.Draw(sheet).text((8, 6), label, fill=(235, 235, 235))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=quality)
    return out


def rows(entries: list[tuple[str, list[str]]], out: Path, *, cell=(400, 220)) -> Path:
    """One labelled row per entry: (label, [shot files...])."""
    from PIL import Image, ImageDraw
    cols = max((len(files) for _, files in entries), default=1)
    head = 22
    sheet = Image.new("RGB", (cell[0] * cols, (cell[1] + head) * len(entries)), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    for r, (label, files) in enumerate(entries):
        y = r * (cell[1] + head)
        draw.text((8, y + 4), label, fill=(235, 235, 235))
        for c, f in enumerate(files):
            if not f or not Path(f).is_file():
                continue
            im = Image.open(f).convert("RGB")
            im.thumbnail(cell)
            sheet.paste(im, (c * cell[0], y + head))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    return out


def shot_metrics(path: str) -> dict:
    """Cheap image facts a critic can use without vision: exposure, contrast, colour, detail, empty areas."""
    from PIL import Image, ImageFilter, ImageStat
    im = Image.open(path).convert("RGB")
    im.thumbnail((480, 270))
    gray = im.convert("L")
    hist = gray.histogram()
    n = sum(hist) or 1
    edges = gray.filter(ImageFilter.FIND_EDGES)
    tw, th = im.width // 8, im.height // 5
    empty = 0
    for i in range(8):
        for k in range(5):
            tile = edges.crop((i * tw, k * th, (i + 1) * tw, (k + 1) * th))
            if ImageStat.Stat(tile).mean[0] < 6:
                empty += 1
    hsv = im.convert("HSV")
    return {"mean_luma": round(ImageStat.Stat(gray).mean[0], 1), "contrast": round(ImageStat.Stat(gray).stddev[0], 1),
            "near_black": round(sum(hist[:25]) / n, 3), "near_white": round(sum(hist[241:]) / n, 3),
            "saturation": round(ImageStat.Stat(hsv).mean[1], 1), "edge_density": round(ImageStat.Stat(edges).mean[0], 1),
            "empty_tiles": round(empty / 40, 3),
            "colours": len(set(im.quantize(colors=64).getdata()))}


def describe(metrics: dict) -> list[str]:
    out = []
    if metrics["mean_luma"] < 45 or metrics["near_black"] > 0.45:
        out.append(f"too dark (mean brightness {metrics['mean_luma']}/255, {int(metrics['near_black'] * 100)}% near black)")
    if metrics["near_white"] > 0.25 or metrics["mean_luma"] > 200:
        out.append(f"washed out ({int(metrics['near_white'] * 100)}% near white)")
    if metrics["contrast"] < 25:
        out.append(f"flat, low contrast ({metrics['contrast']})")
    if metrics["empty_tiles"] > 0.5:
        out.append(f"{int(metrics['empty_tiles'] * 100)}% of the frame is empty/featureless")
    if metrics["edge_density"] > 40:
        out.append("very busy/noisy frame")
    return out
