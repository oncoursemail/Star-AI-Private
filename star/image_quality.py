"""The quality pipeline for text-to-image in the chat: rewrite, draw N drafts, judge blind, pick, draw exact text.

    request -> rewriter (star/image_prompt.py) -> N drafts on ComfyUI (Klein or Z-Image Turbo)
            -> blind vision judge per draft (star/image_judge.py, overlaps with the next draft)
            -> EARLY STOP: the first draft the judge passes without any doubt is taken, the rest are not drawn
            -> best draft; a flawed region is repainted alone (star/image_repair.py) and judged again (max 2 repairs)
            -> still failing and nothing to box: ONE reroll round with new seeds and the judge's complaints
            -> text: words that belong on an object are drawn by the model and read back (exact match, else STAR draws
               them); all other text is drawn with Pillow (star/image_post.py)

The models stay resident on the card (one engine for drafts and repairs), and a tiny picture is drawn while the
rewriter is still thinking, so the first real draft finds the model already loaded.

Settings (all optional, defaults on): `image_quality` (bool), `image_drafts` (1-5, default 3),
`image_engine` ('auto' | 'klein' | 'zimage'). With `image_quality` off, or for edits and inpaints, STAR keeps the
single-shot path in `star.image_gen`. A judge that cannot be reached never blocks a picture: the first draft is used.
"""
from __future__ import annotations

import concurrent.futures
import io
import secrets
import tempfile
import threading
import time
from pathlib import Path

from . import image_judge, image_post, image_prompt, image_repair, media_places, references
from .chat_images import PREFIX, preview_image
from .comfy import (ENGINES, ZIMAGE_STEPS, ZIMAGE_STEPS_FAST, ComfyClient, klein_edit, klein_text_to_image,
                    zimage_inpaint, zimage_text_to_image)
from .image_gen import DEFAULT_SIZE, SIZES, _png, _save
from .pil_safe import Image

DEFAULT_ENGINE = 'zimage'          # A/B winner on exact text and the pictures themselves, 5-6x slower (docs/agents/image-quality-20261023.md)
JUDGE_SIDE = 640                   # pictures are judged at this size (the vision server reads ~25 tokens a second: 768 px 65 s, 640 px 40 s, 512 px 28 s per picture)
CHECK_SIDE = 448                   # the yes/no look at the subject and setting needs less
LEGACY_JUDGE_SIDE = 768            # phase 1
TEXT_JUDGE_SIDE = 1024             # a picture whose words must be read back is judged larger
MAX_DRAFTS = 5
LOOKAHEAD = 2                      # pictures drawn but not yet judged: while the judge reads one, one more is drawn, no further
WARMUP_PROMPT = 'a red apple on a wooden table'


class AnyEvent:
    """`is_set()` is true when any of the events is (the owner's cancel, or "an earlier draft is clearly good")."""

    def __init__(self, *events):
        self.events = [e for e in events if e is not None]

    def is_set(self) -> bool:
        return any(e.is_set() for e in self.events)


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


def judge_copy(png: bytes, folder: Path, name: str, side: int | None = None) -> Path:
    side = side or JUDGE_SIDE
    with Image.open(io.BytesIO(png)) as picture:
        small = picture.convert('RGB')
        small.thumbnail((side, side), Image.Resampling.LANCZOS)
    path = folder / name
    small.save(path, format='JPEG', quality=90)
    return path


def run_rounds(plan, *, drafts: int, seed: int, render, judge_one, cancel=lambda: False, stop=None,
               early_stop: bool = True, repair_one=None, draw_prompt=lambda current: current.prompt):
    """Draw, judge, repair. `render(prompt, seed) -> png bytes`; `judge_one(png, plan) -> Verdict`.

    Returns (items, best index, rounds) where items are dicts {png, seed, verdict, round, kind, prompt}.
    - Early stop: when a verdict is `clear` (a pass with nothing left to doubt) `stop` is set, the draft that is being
      drawn is cancelled by `render` (it watches the same event) and nothing more is drawn.
    - Repair: when round 0 produced no pass, `repair_one(item, plan, attempt)` repaints the best draft's flawed region
      (max `image_repair.MAX_REPAIRS`, each judged again). It returns None when no region can be boxed.
    - Reroll: still no pass (and not an early stop): ONE more round, half as many drafts, new seeds, the judge's
      complaints in the prompt (the time is the cost).
    """
    items: list[dict] = []
    judge_dead = False
    current = plan
    stop = stop if stop is not None else threading.Event()

    def guarded(png, current):
        """A judge job that starts after an earlier draft was clearly good is skipped (None), not run."""
        if early_stop and stop.is_set():
            return None
        return judge_one(png, current)

    def on_judged(future):
        try:
            verdict = future.result()
        except Exception:
            return
        if early_stop and verdict is not None and verdict.clear:
            stop.set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        for round_no in (0, 1):
            pending = []
            for index in range(drafts if round_no == 0 else max(1, -(-drafts // 2))):   # the reroll is half as big
                if cancel():
                    raise RuntimeError('STAR image generation cancelled by user')
                while sum(not f.done() for _, f in pending) >= LOOKAHEAD and not stop.is_set():
                    # the judge is the slow part: never draw more than LOOKAHEAD pictures ahead of it
                    concurrent.futures.wait([f for _, f in pending], timeout=0.3,
                                            return_when=concurrent.futures.FIRST_COMPLETED)
                    if cancel():
                        raise RuntimeError('STAR image generation cancelled by user')
                if stop.is_set():
                    break
                draft_seed = (seed + round_no * 7919 + index) % 2 ** 48
                prompt = draw_prompt(current)
                try:
                    png = render(prompt, draft_seed)
                except RuntimeError:
                    if stop.is_set() and not cancel():      # an earlier draft is clearly good: this one was cancelled
                        break
                    raise
                item = {'png': png, 'seed': draft_seed, 'round': round_no, 'prompt': prompt, 'verdict': None,
                        'kind': 'draft'}
                items.append(item)
                if not judge_dead:
                    future = pool.submit(guarded, png, current)
                    future.add_done_callback(on_judged)
                    pending.append((item, future))
            for item, future in pending:
                verdict = future.result()
                if verdict is None:                         # skipped: an earlier draft was clearly good
                    items[:] = [i for i in items if i is not item]
                    continue
                item['verdict'] = verdict
                judge_dead = judge_dead or not verdict.judged
            judged = [i['verdict'] for i in items if i['verdict'] is not None]
            if judge_dead or stop.is_set() or any(v.passed for v in judged):
                break
            if round_no == 0 and repair_one is not None:
                for attempt in range(image_repair.MAX_REPAIRS):
                    if cancel():
                        raise RuntimeError('STAR image generation cancelled by user')
                    scored = [i for i in items if i['verdict'] is not None]
                    target = scored[image_judge.pick([i['verdict'] for i in scored])]
                    if image_repair.decide(target['verdict'], repairs_done=attempt) != 'locate':
                        break
                    fixed = repair_one(target, current, attempt)
                    if fixed is None:                       # nothing that can be boxed: a new draft is the only fix
                        break
                    fixed['verdict'] = judge_one(fixed['png'], current)
                    items.append(fixed)
                    if not fixed['verdict'].judged:
                        judge_dead = True
                        break
                    if fixed['verdict'].passed:
                        break
                if judge_dead or any(i['verdict'] is not None and i['verdict'].passed for i in items):
                    break
            issues = [x for i in items if i['verdict'] for x in i['verdict'].issues]
            current = image_prompt.repaired(plan, issues)
    for item in items:
        if item['verdict'] is None:
            item['verdict'] = image_judge.Verdict(judged=False)
    best = image_judge.pick([i['verdict'] for i in items]) if not judge_dead else 0
    return items, best, (max(i['round'] for i in items) + 1)


def summary(items: list[dict], best: int, plan, engine_name: str, seconds: float, width: int, height: int,
            extra: dict | None = None) -> str:
    extra = extra or {}
    chosen = items[best]
    verdict = chosen['verdict']
    judged = [i for i in items if i['verdict'].judged]
    drafts = sum(i.get('kind', 'draft') == 'draft' for i in items)
    repairs = sum(i.get('kind') == 'repair' for i in items)
    line = f'Image generated on this PC in {seconds} s · {engine_name}, {width} x {height}, seed {chosen["seed"]}'
    if plan.rewritten:
        line += ' · prompt expanded by STAR'
    if judged:
        position = items.index(chosen) + 1
        line += (f' · {drafts} draft{"s" if drafts != 1 else ""} judged blind, #{position} picked ({verdict.brief()}'
                 + (', all drafts failed the judge, best one kept' if not verdict.passed else '') + ')')
        if extra.get('early_stop'):
            line += ' · a draft was clearly good, the rest were skipped'
        if repairs:
            line += f' · {repairs} flawed region{"s" if repairs != 1 else ""} repainted and judged again'
        if any(i['round'] for i in items):
            line += ' · one reroll round'
    elif drafts > 1 or plan.rewritten:
        line += ' · the judge was not reachable, first draft kept'
    by_model = extra.get('model_text') or []
    if by_model:
        line += ' · text drawn by the model and read back exactly: ' + ', '.join(f'"{t}"' for t in by_model)
    by_star = extra.get('star_text')
    if by_star is None:
        by_star = list(plan.overlays)
    if by_star:
        line += ' · text drawn by STAR: ' + ', '.join(f'"{o.text}"' for o in by_star) + ' (exact letters)'
    return line + ' · original saved in STAR/generated-images'


def warm_up(comfy, engine: str, cancel_event) -> threading.Thread | None:
    """Draw a tiny picture while the rewriter thinks, so the model is on the card when the first draft arrives."""
    if engine != 'zimage':
        return None

    def work():
        try:
            comfy.run(zimage_text_to_image(WARMUP_PROMPT, 512, 512, 1, 4), timeout_seconds=900, cancel_event=cancel_event)
        except Exception:        # a failed warm-up is only a lost head start
            pass
    thread = threading.Thread(target=work, name='star-image-warmup', daemon=True)
    thread.start()
    return thread


def repaint_region(png: bytes, flaw: image_repair.Flaw, scene_prompt: str, *, comfy, engine: str, seed: int, steps: int,
                   paint=None) -> tuple[bytes, str]:
    """Repaint ONE region of a picture and paste it back. Returns (picture, the prompt used).

    Crop around the flaw, repaint the crop with the engine that drew the picture (masked: only the flaw's box may change),
    blend the result back through a feathered mask. `paint(flow) -> png bytes` runs a workflow (default: ComfyUI directly).
    """
    with Image.open(io.BytesIO(png)) as opened:
        full_w, full_h = opened.size
    crop = image_repair.crop_box(flaw, full_w, full_h)
    work = image_repair.work_size(crop[2] - crop[0], crop[3] - crop[1])
    piece, mask = image_repair.inpaint_inputs(png, flaw, crop, work)
    source_name = comfy.upload(piece, 'star_fix_src.png')
    mask_name = comfy.upload(mask, 'star_fix_mask.png')
    prompt = image_repair.local_prompt(flaw, scene_prompt)
    flow = (zimage_inpaint(prompt, source_name, mask_name, work[0], work[1], seed, image_repair.DENOISE, steps)
            if engine == 'zimage' else klein_edit(prompt, source_name, work[0], work[1], seed, mask_name))
    patch = paint(flow) if paint is not None else comfy.run(flow, timeout_seconds=300)[0]
    return image_repair.paste_back(png, patch, flaw, crop), prompt


def generate_best(settings, request: str, home: Path, *, size: str = DEFAULT_SIZE, seed: int | None = None,
                  cancel_event=None, on_progress=None, client: ComfyClient | None = None,
                  ask_brain=image_prompt.brain_text, ask_vision=None, use_references: bool = True,
                  legacy: bool = False) -> dict:
    """Make one picture the careful way. Returns the same dict shape as `star.image_gen.generate`.

    `legacy=True` is the phase-1 pipeline (8 steps, every draft drawn, one reroll, Pillow for all text, no warm-up, 768 px
    judge): the "old" side of the owner's blind A/B and the baseline of the benchmark.
    """
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
    timing = {'rewrite': 0.0, 'draw': 0.0, 'drawn': 0, 'repair_draw': 0.0}
    own = client is None
    comfy = client or ComfyClient(port=settings.comfy_port)
    warm_stop = threading.Event()
    warm = None
    try:
        comfy.status()                      # fails here, clearly and at once, when ComfyUI is not running
        pinned = (references.paths(home, settings.project, references.TURN_LIMIT)
                  if use_references and getattr(settings, 'media_use_references', True) else [])
        available = {name: not comfy.missing_models(name) for name in ENGINES}
        engine = choose_engine(engine_setting, available, bool(pinned))
        if not available.get(engine, False):
            engine = 'klein'
        warm = None if legacy else warm_up(comfy, engine, AnyEvent(cancel_event, warm_stop))
        say({'text': 'Planning the picture…', 'mode': 'text'})
        mark = time.monotonic()
        plan = image_prompt.rewrite(settings, request, ask=ask_brain)
        timing['rewrite'] = round(time.monotonic() - mark, 1)
        if size == DEFAULT_SIZE and plan.aspect in ('wide', 'tall'):
            size = plan.aspect
        width, height = SIZES[size]
        uploaded = []
        for index, (_, path) in enumerate(pinned):
            with Image.open(path) as picture:
                small = picture.convert('RGB')
                small.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            uploaded.append(comfy.upload(_png(small), f'star_ref{index}.png'))
        engine_name = ENGINES[engine][0]
        first = [True]
        stop = threading.Event()            # set when a draft is clearly good: the draft in flight is cancelled
        scene_words = [o.text for o in plan.overlays if o.scene] if (engine == 'zimage' and not legacy) else []
        text_mode = bool(scene_words)
        steps = ZIMAGE_STEPS if (text_mode or legacy) else ZIMAGE_STEPS_FAST

        def paint(flow, wait_for: float = 300) -> bytes:
            wait = 900 if first[0] else wait_for         # the first picture after a start reads the model from disk
            first[0] = False
            mark = time.monotonic()
            try:
                return comfy.run(flow, timeout_seconds=wait, cancel_event=AnyEvent(cancel_event, stop))[0]
            finally:
                timing['draw'] += time.monotonic() - mark

        def render(prompt: str, draft_seed: int) -> bytes:
            flow = (zimage_text_to_image(prompt, width, height, draft_seed, steps) if engine == 'zimage'
                    else klein_text_to_image(prompt, width, height, draft_seed, tuple(uploaded)))
            say({'text': f'Drawing the pictures on this PC ({engine_name})…', 'mode': 'text'})
            png = paint(flow)
            timing['drawn'] += 1
            return png

        with tempfile.TemporaryDirectory(prefix='star-judge-') as scratch:
            counter = [0]
            dead = [False]

            def judge_one(png: bytes, current) -> image_judge.Verdict:
                if dead[0]:
                    return image_judge.Verdict(judged=False)
                counter[0] += 1
                try:
                    path = judge_copy(png, Path(scratch), f'draft{counter[0]}.jpg',
                                      TEXT_JUDGE_SIDE if text_mode else LEGACY_JUDGE_SIDE if legacy else None)
                    small = (judge_copy(png, Path(scratch), f'check{counter[0]}.jpg', CHECK_SIDE)
                             if (current.checks and not legacy) else None)
                    kwargs = {'ask': ask_vision} if ask_vision else {}
                    return image_judge.judge(settings, path, current.checks, expected_text=scene_words if text_mode else [],
                                             checks_image=small, parallel=not legacy, **kwargs)
                except Exception:        # vision model unreachable or answering nonsense: never block the picture
                    dead[0] = True
                    return image_judge.Verdict(judged=False)

            def repair_one(item, current, attempt):
                """Repaint the flawed region of `item` alone. None when the judge cannot box the flaw."""
                counter[0] += 1
                path = judge_copy(item['png'], Path(scratch), f'locate{counter[0]}.jpg')
                flaws = image_repair.locate(settings, path, list(item['verdict'].issues),
                                            **({'ask': ask_vision} if ask_vision else {}))
                if not flaws:
                    return None
                flaw = flaws[0]
                if text_mode and item['verdict'].text_ok is False:
                    flaw = image_repair.Flaw(flaw.box, 'the lettering reads exactly '
                                             + ' and '.join(f'"{w}"' for w in scene_words)
                                             + ', in clear, large, correctly spelled letters')
                say({'text': 'Repainting one flawed region…', 'mode': 'text'})
                mark = time.monotonic()
                fix_seed = (item['seed'] + 104729 * (attempt + 1)) % 2 ** 48
                fixed, prompt = repaint_region(
                    item['png'], flaw, current.prompt, comfy=comfy, engine=engine, seed=fix_seed,
                    steps=ZIMAGE_STEPS if text_mode else ZIMAGE_STEPS_FAST, paint=paint)
                timing['repair_draw'] += time.monotonic() - mark
                return {'png': fixed, 'seed': fix_seed, 'round': item['round'], 'prompt': prompt, 'verdict': None,
                        'kind': 'repair', 'flaw': {'box': [round(v, 3) for v in flaw.box], 'fix': flaw.fix}}

            items, best, rounds = run_rounds(
                plan, drafts=drafts, seed=seed, render=render, judge_one=judge_one,
                cancel=lambda: bool(cancel_event is not None and cancel_event.is_set()), stop=stop,
                early_stop=not legacy, repair_one=None if legacy else repair_one,
                draw_prompt=image_prompt.scene_prompt if text_mode else (lambda current: current.prompt))
            chosen = items[best]
            text_fallback = False
            if text_mode and chosen['verdict'].text_ok is not True:
                # the model did not write the words exactly (or nobody could check): draw the scene with a blank area
                # and let STAR draw every word
                stop.clear()
                say({'text': 'Drawing the scene again with an empty area for the text…', 'mode': 'text'})
                blank_seed = (seed + 31337) % 2 ** 48
                blank_png = paint(zimage_text_to_image(plan.prompt, width, height, blank_seed, ZIMAGE_STEPS_FAST))
                timing['drawn'] += 1
                items.append({'png': blank_png, 'seed': blank_seed, 'round': rounds, 'prompt': plan.prompt,
                              'verdict': image_judge.Verdict(judged=False), 'kind': 'blank'})
                best = len(items) - 1
                chosen = items[best]
                text_fallback = True
    finally:
        warm_stop.set()
        if warm is not None:
            warm.join(timeout=3)
        if own:
            comfy.close()
    picture = chosen['png']
    star_text = [o for o in plan.overlays if not o.scene] if (text_mode and not text_fallback) else list(plan.overlays)
    if star_text:
        picture = image_post.draw_overlays(picture, star_text)
    seconds = round(time.monotonic() - started, 1)
    drafts_total = sum(i['kind'] == 'draft' for i in items)
    early = bool(not text_fallback and chosen['kind'] == 'draft' and chosen['verdict'].clear and drafts_total < drafts)
    extra = {'early_stop': early, 'star_text': star_text,
             'model_text': scene_words if (text_mode and not text_fallback) else []}
    answer = summary(items, best, plan, engine_name, seconds, width, height, extra)
    note = {'answer': answer, 'mode': 'text', 'prompt': request, 'rewritten_prompt': chosen['prompt'],
            'plan': plan.as_note(), 'seed': chosen['seed'], 'width': width, 'height': height,
            'model': engine_name, 'engine': engine, 'steps': steps if engine == 'zimage' else None,
            'seconds': seconds, 'place': 'pc', 'rounds': rounds,
            'timing': {'rewrite_s': timing['rewrite'], 'draw_s': round(timing['draw'], 1),
                       'pictures_drawn': timing['drawn'], 'repair_draw_s': round(timing['repair_draw'], 1),
                       'early_stop': early, 'text_in_scene': text_mode, 'text_fallback': text_fallback,
                       'pipeline': 'phase1' if legacy else 'phase2'},
            'drafts': [{'seed': i['seed'], 'round': i['round'], 'kind': i['kind'], 'judge': i['verdict'].as_note(),
                        **({'flaw': i['flaw']} if 'flaw' in i else {})} for i in items],
            'chosen': best, 'references': [row['label'] for row, _ in pinned], 'source': '',
            'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    path = _save(home, picture, note)
    return {'answer': answer, 'image': preview_image(path), 'message': PREFIX + path.name, 'path': path, 'note': note}
