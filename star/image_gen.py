"""Image generation, editing and inpainting for the chat, on the place chosen in Settings.

Today one place exists: ComfyUI on this PC with FLUX.2 klein 4B (`star.comfy`). One model does
all three jobs:
  - text to image;
  - edit: an attached image plus an instruction (the image is given to the model as a reference);
  - inpaint: the same with a mask (white = the area to change). Sampling starts from the image,
    only the masked area is regenerated, and STAR then pastes the result back through the mask so
    every pixel outside it is the original.
A project's pinned references (`star.references`) are given to the model as extra reference images.

The original is saved under `<STAR data>/generated-images` with a small JSON note beside it
(prompt, seed, size, model, seconds, references), so a result can be reproduced.
"""
from __future__ import annotations

import io
import json
import os
import secrets
import time
from pathlib import Path

from ._lazy import lazy_attr, lazy_module
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # type checkers see the real module; at run time Pillow loads on first use
    from PIL import Image
else:
    Image = lazy_attr("star.pil_safe", "Image")   # Pillow loads on first use, with the pixel limit set
ImageFilter = lazy_module("PIL.ImageFilter")

from . import media_places, references
from .chat_images import NAME, PREFIX, preview_image
from .comfy import KLEIN_NAME, ComfyClient, ComfyError, klein_edit, klein_text_to_image

SIZES = {'square': (1024, 1024), 'wide': (1280, 720), 'tall': (720, 1280), 'draft': (512, 512)}
SIZE_LABELS = {'square': 'Square 1024 x 1024', 'wide': 'Wide 1280 x 720', 'tall': 'Tall 720 x 1280',
               'draft': 'Draft 512 x 512 (fastest)'}
DEFAULT_SIZE = 'square'
EDIT_PIXELS = {'draft': 512 * 512}          # an edit keeps the picture's shape at about this many pixels
EDIT_PIXELS_DEFAULT = 1024 * 1024


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def working_size(width: int, height: int, pixels: int) -> tuple[int, int]:
    """The picture's own shape at about `pixels`, each side a multiple of 16 (what the model needs)."""
    scale = (pixels / (width * height)) ** 0.5
    return (max(256, min(2048, round(width * scale / 16) * 16)),
            max(256, min(2048, round(height * scale / 16) * 16)))


def read_mask(path: Path, size: tuple[int, int]) -> Image.Image:
    """An 8-bit mask at `size`: white where the picture may change.

    A mask with real transparency means "the erased part changes"; otherwise bright pixels do.
    """
    try:
        opened = Image.open(path)
    except (OSError, ValueError) as exc:
        raise ValueError('The mask must be a PNG, JPEG or WebP picture') from exc
    with opened:
        if opened.width * opened.height > 40_000_000:
            raise ValueError('The mask is too large')
        if opened.mode in ('RGBA', 'LA') and opened.getchannel('A').getextrema()[0] < 250:
            mask = opened.getchannel('A').point(lambda value: 255 if value < 128 else 0)
        else:
            mask = opened.convert('L').point(lambda value: 255 if value > 127 else 0)
    mask = mask.resize(size, Image.Resampling.NEAREST)
    low, high = mask.getextrema()
    if high == 0:
        raise ValueError('The mask has no white area. Paint the part you want changed white '
                         '(or erase it to transparent) and attach the mask as the second image.')
    if low == 255:
        raise ValueError('The mask is completely white. Leave the mask out to edit the whole picture.')
    return mask


def _save(home: Path, picture: bytes, note: dict) -> Path:
    folder = home / 'generated-images'
    folder.mkdir(parents=True, exist_ok=True)
    name = f"star-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{note['seed'] % 100000:05d}.png"
    if not NAME.fullmatch(name):
        raise RuntimeError('Unexpected generated image filename')
    path = folder / name
    # The note first, the picture last and under a temporary name: a picture that exists is complete and has its note,
    # and the chat only ever names a file that is on disk (a reference must never run ahead of the file).
    path.with_suffix('.json').write_text(json.dumps(note, ensure_ascii=False, indent=1), encoding='utf-8')
    partial = path.with_name(path.name + '.part')
    with open(partial, 'wb') as out:
        out.write(picture)
        out.flush()
        os.fsync(out.fileno())
    os.replace(partial, path)
    if not path.is_file() or path.stat().st_size != len(picture):
        raise RuntimeError('The picture was made but could not be saved in the STAR data folder')
    return path


def generate(settings, prompt: str, home: Path, *, size: str = DEFAULT_SIZE, seed: int | None = None,
             source: Path | None = None, mask: Path | None = None, use_references: bool = True,
             cancel_event=None, on_progress=None, client: ComfyClient | None = None) -> dict:
    """Make or change one picture. Returns the chat result (answer, preview, stored message, note)."""
    prompt = (prompt or '').strip()
    if not 1 <= len(prompt) <= 1500:
        raise ValueError('Image prompt must be 1–1500 characters')
    if size not in SIZES:
        raise ValueError('Choose one of the image sizes: ' + ', '.join(SIZES))
    if mask is not None and source is None:
        raise ValueError('A mask needs the picture it belongs to. Attach the picture first, then the mask.')
    media_places.require(settings, 'images', home)       # the only place today is this PC
    say = on_progress or (lambda message: None)
    seed = secrets.randbelow(2 ** 48) if seed is None else int(seed) % 2 ** 48
    mode = 'inpaint' if mask is not None else 'edit' if source is not None else 'text'
    own = client is None
    comfy = client or ComfyClient(port=settings.comfy_port)
    started = time.monotonic()
    try:
        comfy.status()                                   # fails here, clearly, when ComfyUI is not running
        pinned = (references.paths(home, settings.project, references.TURN_LIMIT)
                  if use_references and getattr(settings, 'media_use_references', True) else [])
        uploaded = []
        for index, (_, path) in enumerate(pinned):
            with Image.open(path) as picture:
                small = picture.convert('RGB')
                small.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            uploaded.append(comfy.upload(_png(small), f'star_ref{index}.png'))
        original = keep = None
        if mode == 'text':
            width, height = SIZES[size]
            flow = klein_text_to_image(prompt, width, height, seed, tuple(uploaded))
        else:
            original = references._open(Path(source))
            width, height = working_size(original.width, original.height,
                                         EDIT_PIXELS.get(size, EDIT_PIXELS_DEFAULT))
            original = original.resize((width, height), Image.Resampling.LANCZOS)
            source_name = comfy.upload(_png(original), 'star_src.png')
            mask_name = None
            if mode == 'inpaint':
                keep = read_mask(Path(mask), (width, height))
                # The model may repaint a little beyond the painted area so the join has room to blend.
                grown = keep.filter(ImageFilter.MaxFilter(9))
                mask_name = comfy.upload(_png(Image.merge('RGB', (grown, grown, grown))), 'star_mask.png')
            flow = klein_edit(prompt, source_name, width, height, seed, mask_name, tuple(uploaded))
        say({'text': 'Creating the image on this PC…', 'mode': mode})
        pictures = comfy.run(flow, timeout_seconds=300, cancel_event=cancel_event)
    finally:
        if own:
            comfy.close()
    picture = pictures[0]
    if mode == 'inpaint':
        with Image.open(io.BytesIO(picture)) as made:
            made = made.convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
        soft = keep.filter(ImageFilter.GaussianBlur(max(3, min(width, height) // 160)))
        picture = _png(Image.composite(made, original, soft))
    seconds = round(time.monotonic() - started, 1)
    labels = [row['label'] for row, _ in pinned]
    did = {'text': 'Image generated', 'edit': 'Image edited', 'inpaint': 'Masked area changed'}[mode]
    answer = (f'{did} on this PC in {seconds} s · {KLEIN_NAME}, {width} x {height}, seed {seed}'
              + (f" · followed {len(labels)} project reference{'s' if len(labels) != 1 else ''}: {', '.join(labels)}"
                 if labels else '')
              + (' · everything outside the mask is the original picture' if mode == 'inpaint' else '')
              + ' · original saved in STAR/generated-images')
    note = {'answer': answer, 'mode': mode, 'prompt': prompt, 'seed': seed, 'width': width, 'height': height,
            'model': KLEIN_NAME, 'steps': 4, 'seconds': seconds, 'place': 'pc', 'references': labels,
            'source': Path(source).name if source else '', 'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    path = _save(home, picture, note)
    return {'answer': answer, 'image': preview_image(path), 'message': PREFIX + path.name,
            'path': path, 'note': note}


def latest(home: Path) -> Path | None:
    """The newest picture STAR made (for "compare with reference")."""
    folder = home / 'generated-images'
    if not folder.is_dir():
        return None
    found = sorted((p for p in folder.glob('*.png') if NAME.fullmatch(p.name)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def status(settings) -> dict:
    """What the Settings page shows about the image engine on this PC. Never raises."""
    try:
        with ComfyClient(port=settings.comfy_port, timeout=5.0) as comfy:
            info = comfy.status()
            missing = comfy.missing_models()
        return {**info, 'model': KLEIN_NAME, 'missing': missing, 'ready': not missing,
                'message': ('Ready.' if not missing else
                            'ComfyUI is running but model files are missing: ' + ', '.join(missing))}
    except ComfyError as exc:
        return {'running': False, 'ready': False, 'missing': [], 'model': KLEIN_NAME, 'message': str(exc)}
    except Exception as exc:
        return {'running': False, 'ready': False, 'missing': [], 'model': KLEIN_NAME,
                'message': f'ComfyUI on this PC answered unexpectedly ({type(exc).__name__}).'}
