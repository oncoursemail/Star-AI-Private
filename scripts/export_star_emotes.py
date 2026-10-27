"""Export generated square emote masters to Twitch's manual PNG sizes.

This performs size/format conversion only. It does not draw, retouch or replace
the generated character artwork. Usage: python scripts/export_star_emotes.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def export(source: Path, destination: Path) -> list[dict]:
    outputs = []
    for name in ("laugh", "love", "hype", "think"):
        with Image.open(source / f"star-{name}-master.png") as original:
            if original.width != original.height or original.width < 112:
                raise ValueError(f"{name}: expected a square master at least 112 pixels wide")
            rgba = original.convert("RGBA")
            if rgba.getchannel("A").getextrema()[0] == 255:
                raise ValueError(f"{name}: master has no transparent pixels")
            for size in (28, 56, 112):
                folder = destination / str(size)
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"star-{name}.png"
                rgba.convert("RGBa").resize((size, size), Image.Resampling.LANCZOS).convert("RGBA").save(path, optimize=True)
                with Image.open(path) as check:
                    if check.size != (size, size) or check.mode != "RGBA" or path.stat().st_size >= 1_000_000:
                        raise ValueError(f"{name}: export failed Twitch's format limits")
                outputs.append({"path": str(path), "size": size, "bytes": path.stat().st_size})
    return outputs


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "assets" / "vtuber" / "emotes" / "masters")
    parser.add_argument("--out", type=Path, default=root / "assets" / "vtuber" / "emotes" / "upload")
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.out), indent=2))


if __name__ == "__main__":
    main()
