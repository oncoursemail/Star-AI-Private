"""The quality pipeline for text-to-image in the chat: rewrite, draw N drafts, judge blind, pick, draw exact text.

    request -> rewriter (star/image_prompt.py) -> N drafts on ComfyUI (Klein or Z-Image Turbo)
            -> blind vision judge per draft (star/image_judge.py, overlaps with the next draft)
            -> best draft; if every draft fails, ONE repair round with new seeds and the judge's complaints
            -> exact text drawn with Pillow (star/image_post.py)

Settings (all optional, defaults on): `image_quality` (bool), `image_drafts` (1-5, default 3),
`image_engine` ('auto' | 'klein' | 'zimage'). With `image_quality` off, or for edits and inpaints, STAR keeps the
single-shot path in `star.image_gen`. A judge that cannot be reached never blocks a picture: the first draft is used.
"""
from __future__ import annotations

import concurrent.futures
import io
import secrets
import tempfile
import time
from pathlib import Path

from . import image_judge, image_post, image_prompt, media_places, references
from .chat_images import PREFIX, preview_image
from .comfy import ENGINES, ComfyClient, klein_text_to_image, zimage_text_to_image
from .image_gen import DEFAULT_SIZE, SIZES, _png, _save
from .pil_safe import Image

DEFAULT_ENGINE = 'klein'           # the benchmark winner (docs/agents/image-quality-20261023.md)
JUDGE_SIDE = 768                   # pictures are judged at this size (the vision server reads ~30 s per megapixel)
MAX_DRAFTS = 5


def settings_for(settings) -> tuple[bool, int, str]:
    on = getattr(settings, 'image_quality', True) is not False
    drafts = getattr(settings, 'image_drafts', 3)
    drafts = drafts if type(drafts) is int and 1 <= drafts <= MAX_DRAFTS else 3
    engine = getattr(settings, 'image_engine', 'auto')
    return on, drafts, engine if engine in ('auto', *ENGINES) else 'auto'


def enabled(settings) -> bool:
    return settings_for(settings)[0]


def choose_engine(setting: str, available: dict[str, bool], has_references: bool) -> str:
    """References only work with Klein; otherwise the owner's choice, else the default if its files are installed."""
    if has_references:
        return 'klein'
    if setting in ENGINES:
        return setting
    return DEFAULT_ENGINE if available.get(DEFAULT_ENGINE, True) else 'klein'


def judge_copy(png: bytes, folder: Path, name: str) -> Path:
    with Image.open(io.BytesIO(png)) as picture:
        small = picture.convert('RGB')
        small.thumbnail((JUDGE_SIDE, JUDGE_SIDE), Image.Resampling.LANCZOS)
    path = folder / name
    small.save(path, format='JPEG', quality=90)
    return path


def run_rounds(plan, *, drafts: int, seed: int, render, judge_one, cancel=lambda: False):
    """Draw and judge. `render(prompt, seed) -> png bytes`; `judge_one(png, plan) -> Verdict`.

    Returns (items, best index, rounds) where items are dicts {png, seed, verdict}. At most two rounds: the second
    only when no draft of the first passed, with new seeds and the judge's complaints in the prompt.
    """
    items: list[dict] = []
    judge_dead = False
    current = plan
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        for round_no in (0, 1):
            pending = []
            for index in range(drafts):
                if cancel():
                    raise RuntimeError('STAR image generation cancelled by user')
                draft_seed = (seed + round_no * 7919 + index) % 2 ** 48
                png = render(current.prompt, draft_seed)
                item = {'png': png, 'seed': draft_seed, 'round': round_no, 'prompt': current.prompt, 'verdict': None}
                items.append(item)
                if not judge_dead:
                    pending.append((item, pool.submit(judge_one, png, current)))
            for item, future in pending:
                verdict = future.result()
                item['verdict'] = verdict
                judge_dead = judge_dead or not verdict.judged
            if judge_dead or any(i['verdict'] is not None and i['verdict'].passed for i in items):
                break
            issues = [x for i in items if i['verdict'] for x in i['verdict'].issues]
            current = image_prompt.repaired(plan, issues)
    for item in items:
        if item['verdict'] is None:
            item['verdict'] = image_judge.Verdict(judged=False)
    best = image_judge.pick([i['verdict'] for i in items]) if not judge_dead else 0
    return items, best, (max(i['round'] for i in items) + 1)


def summary(items: list[dict], best: int, plan, engine_name: str, seconds: float, width: int, height: int) -> str:
    chosen = items[best]
    verdict = chosen['verdict']
    judged = [i for i in items if i['verdict'].judged]
    drafts = len(items)
    line = f'Image generated on this PC in {seconds} s · {engine_name}, {width} x {height}, seed {chosen["seed"]}'
    if plan.rewritten:
        line += ' · prompt expanded by STAR'
    if judged:
        position = items.index(chosen) + 1
        line += (f' · {drafts} draft{"s" if drafts != 1 else ""} judged blind, #{position} picked ({verdict.brief()}'
                 + (', all drafts failed the judge, best one kept' if not verdict.passed else '') + ')')
        if any(i['round'] for i in items):
            line += ' · one repair round'
    elif drafts > 1 or plan.rewritten:
        line += ' · the judge was not reachable, first draft kept'
    if plan.overlays:
        line += ' · text drawn by STAR: ' + ', '.join(f'"{o.text}"' for o in plan.overlays) + ' (exact letters)'
    return line + ' · original saved in STAR/generated-images'


def generate_best(settings, request: str, home: Path, *, size: str = DEFAULT_SIZE, seed: int | None = None,
                  cancel_event=None, on_progress=None, client: ComfyClient | None = None,
                  ask_brain=image_prompt.brain_text, ask_vision=None) -> dict:
    """Make one picture the careful way. Returns the same dict shape as `star.image_gen.generate`."""
    request = (request or '').strip()
    if not 1 <= len(request) <= 1500:
        raise ValueError('Image prompt must be 1–1500 characters')
    if size not in SIZES:
        raise ValueError('Choose one of the image sizes: ' + ', '.join(SIZES))
    media_places.require(settings, 'images', home)
    say = on_progress or (lambda message: None)
    _, drafts, engine_setting = settings_for(settings)
    seed = secrets.randbelow(2 ** 48) if seed is None else int(seed) % 2 ** 48
    started = time.monotonic()
    say({'text': 'Planning the picture…', 'mode': 'text'})
    plan = image_prompt.rewrite(settings, request, ask=ask_brain)
    if size == DEFAULT_SIZE and plan.aspect in ('wide', 'tall'):
        size = plan.aspect
    width, height = SIZES[size]
    own = client is None
    comfy = client or ComfyClient(port=settings.comfy_port)
    try:
        comfy.status()
        pinned = (references.paths(home, settings.project, references.TURN_LIMIT)
                  if getattr(settings, 'media_use_references', True) else [])
        available = {name: not comfy.missing_models(name) for name in ENGINES}
        engine = choose_engine(engine_setting, available, bool(pinned))
        if not available.get(engine, False):
            engine = 'klein'
        uploaded = []
        for index, (_, path) in enumerate(pinned):
            with Image.open(path) as picture:
                small = picture.convert('RGB')
                small.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            uploaded.append(comfy.upload(_png(small), f'star_ref{index}.png'))
        engine_name = ENGINES[engine][0]
        first = [True]

        def render(prompt: str, draft_seed: int) -> bytes:
            flow = (zimage_text_to_image(prompt, width, height, draft_seed) if engine == 'zimage'
                    else klein_text_to_image(prompt, width, height, draft_seed, tuple(uploaded)))
            wait = 900 if first[0] else 300         # the first picture after a start reads the model from disk
            first[0] = False
            say({'text': f'Drawing the pictures on this PC ({engine_name})…', 'mode': 'text'})
            return comfy.run(flow, timeout_seconds=wait, cancel_event=cancel_event)[0]

        expected_text = []          # the art is drawn without text; STAR draws it afterwards
        with tempfile.TemporaryDirectory(prefix='star-judge-') as scratch:
            counter = [0]
            dead = [False]

            def judge_one(png: bytes, current) -> image_judge.Verdict:
                if dead[0]:
                    return image_judge.Verdict(judged=False)
                counter[0] += 1
                try:
                    path = judge_copy(png, Path(scratch), f'draft{counter[0]}.jpg')
                    kwargs = {'ask': ask_vision} if ask_vision else {}
                    return image_judge.judge(settings, path, current.checks, expected_text=expected_text, **kwargs)
                except Exception:        # vision model unreachable or answering nonsense: never block the picture
                    dead[0] = True
                    return image_judge.Verdict(judged=False)

            items, best, rounds = run_rounds(
                plan, drafts=drafts, seed=seed, render=render, judge_one=judge_one,
                cancel=lambda: bool(cancel_event is not None and cancel_event.is_set()))
    finally:
        if own:
            comfy.close()
    picture = items[best]['png']
    if plan.overlays:
        picture = image_post.draw_overlays(picture, plan.overlays)
    seconds = round(time.monotonic() - started, 1)
    answer = summary(items, best, plan, engine_name, seconds, width, height)
    chosen = items[best]
    note = {'answer': answer, 'mode': 'text', 'prompt': request, 'rewritten_prompt': chosen['prompt'],
            'plan': plan.as_note(), 'seed': chosen['seed'], 'width': width, 'height': height,
            'model': engine_name, 'engine': engine, 'seconds': seconds, 'place': 'pc', 'rounds': rounds,
            'drafts': [{'seed': i['seed'], 'round': i['round'], 'judge': i['verdict'].as_note()} for i in items],
            'chosen': best, 'references': [row['label'] for row, _ in pinned], 'source': '',
            'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    path = _save(home, picture, note)
    return {'answer': answer, 'image': preview_image(path), 'message': PREFIX + path.name, 'path': path, 'note': note}
