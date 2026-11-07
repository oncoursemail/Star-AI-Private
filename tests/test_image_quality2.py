"""Image quality phase 2: early stop, the repair loop (decisions, geometry, pixels), in-scene text with read-back and
fallback, the Z-Image inpaint workflow, Discord /draw on the same pipeline. No GPU, no network."""
import io
import json
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from star import image_judge, image_prompt, image_quality, image_repair
from star.comfy import ZIMAGE_STEPS, ZIMAGE_STEPS_FAST, zimage_inpaint, zimage_text_to_image
from star.desktop_core import Settings

PLAN = json.dumps({
    'prompt': 'Full-body side view of a Holstein cow standing on green grass, four legs visible, one head, two ears, '
              'one tail, soft morning light, 85mm photo.',
    'aspect': 'square', 'overlays': [], 'checks': ['Is there a cow?', 'Is it on grass?']})
SIGN_PLAN = json.dumps({
    'prompt': 'A brick wall at night with a blank glowing neon tube sign in the middle, moody street light.',
    'aspect': 'square', 'checks': ['Is there a brick wall?', 'Is there a sign?'],
    'overlays': [{'text': 'PIZZA', 'where': 'center', 'style': 'bold', 'scene': True},
                 {'text': 'SCORE 0420', 'where': 'top-left', 'style': 'pixel', 'scene': False}]})


def plan_of(text=PLAN):
    return image_prompt.parse_plan('x', text)


def noisy_png(size=(256, 256), color=(10, 20, 30)) -> bytes:
    image = Image.new('RGB', size, color)
    for x in range(0, size[0], 3):
        for y in range(0, size[1], 3):
            image.putpixel((x, y), (x * 255 // size[0], y * 255 // size[1], 90))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def clear_verdict(**kw):
    return image_judge.Verdict(checks_yes=2, checks_total=2, score=0.9, **kw)


def failing(issue='cow: exactly 4 legs each, not 6'):
    return image_judge.Verdict(anatomy_ok=False, issues=[issue], score=0.05)


# ---- early stop ------------------------------------------------------------------------------------------------

def test_clear_means_a_pass_with_nothing_left_to_doubt():
    assert clear_verdict().clear
    assert image_judge.Verdict(checks_yes=2, checks_total=3, score=0.7).clear       # one "no" of three is allowed (taste)
    assert not image_judge.Verdict(checks_yes=1, checks_total=2).clear
    assert not image_judge.Verdict(checks_yes=1, checks_total=3).clear              # does not even pass
    assert not image_judge.Verdict(checks_yes=2, checks_total=2, soft=['legs: 2-4, saw 1']).clear
    assert not image_judge.Verdict(checks_yes=2, checks_total=2, text_ok=False).clear
    assert not image_judge.Verdict(judged=False).clear


def test_early_stop_takes_a_clear_first_draft_and_cancels_the_draft_in_flight():
    stop = threading.Event()
    seeds = []

    def render(prompt, seed):
        seeds.append(seed)
        if len(seeds) == 1:
            return b'one'
        for _ in range(500):                           # the 2nd draft is being drawn when the judge answers
            if stop.is_set():
                raise RuntimeError('STAR image generation cancelled by user')
            time.sleep(0.01)
        return b'two'

    def slow_judge(png_, plan):
        time.sleep(0.15)                               # the judge is the slow part: draft 2 is already being drawn
        return clear_verdict()

    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=3, seed=10, render=render, judge_one=slow_judge, stop=stop)
    assert seeds == [10, 11] and len(items) == 1 and best == 0 and rounds == 1


def test_a_judge_job_that_starts_after_the_stop_is_skipped_not_run():
    judged = []
    gate = threading.Event()

    def judge_one(png_, plan):
        judged.append(png_)
        if png_ == b'x10':
            gate.wait(2)                                # draft 2 is drawn and queued while draft 1 is being judged
        return clear_verdict()

    def render(prompt, seed):
        if seed == 11:
            gate.set()
        return b'x%d' % seed

    items, best, rounds = image_quality.run_rounds(plan_of(), drafts=3, seed=10, render=render, judge_one=judge_one)
    assert judged == [b'x10'] and len(items) == 1


def test_no_early_stop_when_a_doubt_remains_or_when_switched_off():
    drawn = []
    items, best, _ = image_quality.run_rounds(
        plan_of(), drafts=3, seed=1, render=lambda p, s: (drawn.append(s) or b'x'),
        judge_one=lambda png_, plan: image_judge.Verdict(checks_yes=3, checks_total=3, soft=['legs: 2-4, saw 1'], score=0.7))
    assert len(drawn) == 3 and len(items) == 3
    drawn.clear()
    image_quality.run_rounds(plan_of(), drafts=3, seed=1, render=lambda p, s: (drawn.append(s) or b'x'),
                             judge_one=lambda png_, plan: clear_verdict(), early_stop=False)
    assert len(drawn) == 3


def test_the_judge_is_never_more_than_one_draft_behind_the_painter():
    ahead = []
    open_jobs = [0]
    lock = threading.Lock()

    def judge_one(png_, plan):
        time.sleep(0.05)
        with lock:
            open_jobs[0] -= 1
        return image_judge.Verdict(checks_yes=1, checks_total=2, score=0.4, anatomy_ok=False, issues=['x'])

    def render(prompt, seed):
        with lock:
            ahead.append(open_jobs[0])
            open_jobs[0] += 1
        return b'x'

    image_quality.run_rounds(plan_of(), drafts=4, seed=1, render=render, judge_one=judge_one)
    assert max(ahead[:4]) <= image_quality.LOOKAHEAD - 1


# ---- repair decisions -------------------------------------------------------------------------------------------

def test_decide_table():
    ok, bad = clear_verdict(), failing()
    assert image_repair.decide(ok, repairs_done=0) == 'accept'
    assert image_repair.decide(bad, repairs_done=0) == 'locate'
    assert image_repair.decide(bad, repairs_done=0, flaws_found=True) == 'repair'
    assert image_repair.decide(bad, repairs_done=0, flaws_found=False) == 'reroll'
    assert image_repair.decide(bad, repairs_done=image_repair.MAX_REPAIRS) == 'keep'
    assert image_repair.decide(image_judge.Verdict(judged=False), repairs_done=0) == 'accept'    # nobody can judge: take it
    assert image_repair.decide(image_judge.Verdict(blank=True), repairs_done=0) == 'reroll'      # a flat picture has no region
    assert image_repair.decide(image_judge.Verdict(checks_yes=0, checks_total=3), repairs_done=0) == 'locate'


def test_a_repaired_picture_is_kept_only_when_it_is_better():
    before = failing()
    assert image_repair.better(clear_verdict(), before)
    assert image_repair.better(image_judge.Verdict(anatomy_ok=False, issues=['x'], score=0.1), before) is True
    assert not image_repair.better(image_judge.Verdict(anatomy_ok=False, issues=['x'] * 3, score=0.0), before)
    assert not image_repair.better(image_judge.Verdict(judged=False), before)
    assert not image_repair.better(failing(), clear_verdict())


def test_parse_flaws_drops_boxes_that_cannot_be_a_local_repair():
    reply = json.dumps({'regions': [
        {'box': [100, 500, 300, 900], 'fix': 'a normal front leg of a cow'},
        {'box': [0, 0, 1000, 1000], 'fix': 'everything'},            # the whole picture is a new draft, not a repair
        {'box': [500, 500, 500, 900], 'fix': 'zero width'},
        {'box': [900, 900, 905, 903], 'fix': 'a speck'},             # too small
        {'box': [-50, 100, 200, 1200], 'fix': 'clamped into the picture'},
        {'box': ['a', 1, 2, 3]}, {'box': [1, 2, 3]}, 'junk']})
    flaws = image_repair.parse_flaws('Sure: ' + reply)
    assert [f.fix for f in flaws] == ['a normal front leg of a cow', 'clamped into the picture']
    assert flaws[0].box == pytest.approx((0.1, 0.5, 0.3, 0.9))
    assert flaws[1].box[0] == 0.0 and flaws[1].box[3] == 1.0
    assert image_repair.parse_flaws('no json') == [] and image_repair.parse_flaws('{"regions": 5}') == []


def test_locate_never_raises():
    def boom(*a, **k):
        raise ConnectionError('down')

    assert image_repair.locate(None, 'x.png', ['six legs'], ask=boom) == []
    seen = {}

    def ask(settings, question, images, max_tokens=0):
        seen['q'] = question
        return SimpleNamespace(text='{"regions":[{"box":[100,100,400,500],"fix":"two normal legs"}]}')

    flaws = image_repair.locate(None, 'x.png', ['cow: exactly 4 legs each, not 6'], ask=ask)
    assert flaws[0].fix == 'two normal legs' and 'exactly 4 legs' in seen['q']


# ---- repair geometry and pixels --------------------------------------------------------------------------------

@pytest.mark.parametrize('box', [(0.1, 0.5, 0.3, 0.9), (0.0, 0.0, 0.2, 0.2), (0.8, 0.8, 1.0, 1.0), (0.45, 0.4, 0.55, 0.6)])
def test_crop_contains_the_flaw_stays_inside_and_is_a_multiple_of_16(box):
    flaw = image_repair.Flaw(box)
    for width, height in ((1024, 1024), (1280, 720), (720, 1280)):
        left, top, right, bottom = image_repair.crop_box(flaw, width, height)
        assert 0 <= left < right <= width and 0 <= top < bottom <= height
        assert left <= box[0] * width and right >= box[2] * width and top <= box[1] * height and bottom >= box[3] * height
        assert (right - left) % 16 == 0 and (bottom - top) % 16 == 0
        assert right - left >= min(image_repair.MIN_CROP, width) - 16


def test_work_size_keeps_the_shape_in_multiples_of_16():
    for crop in ((384, 384), (400, 640), (1024, 352)):
        w, h = image_repair.work_size(*crop)
        assert w % 16 == 0 and h % 16 == 0 and max(w, h) <= image_repair.REPAIR_SIDE + 16
        assert abs(w / h - crop[0] / crop[1]) < 0.12


def test_paste_back_changes_only_the_flawed_box():
    original = noisy_png((512, 512), (10, 20, 30))
    flaw = image_repair.Flaw((0.4, 0.4, 0.6, 0.6))
    crop = image_repair.crop_box(flaw, 512, 512)
    patch = io.BytesIO()
    Image.new('RGB', (crop[2] - crop[0], crop[3] - crop[1]), (255, 0, 0)).save(patch, format='PNG')
    fixed = Image.open(io.BytesIO(image_repair.paste_back(original, patch.getvalue(), flaw, crop))).convert('RGB')
    before = Image.open(io.BytesIO(original)).convert('RGB')
    assert fixed.getpixel((256, 256)) == (255, 0, 0)                                  # inside the box: repainted
    for point in ((5, 5), (500, 20), (20, 500), (500, 500), (256, 20), (60, 256)):    # far outside: untouched
        assert fixed.getpixel(point) == before.getpixel(point)
    assert fixed.size == before.size


def test_inpaint_inputs_mask_is_white_over_the_flaw_and_black_elsewhere():
    original = noisy_png((512, 512))
    flaw = image_repair.Flaw((0.4, 0.4, 0.6, 0.6))
    crop = image_repair.crop_box(flaw, 512, 512)
    work = image_repair.work_size(crop[2] - crop[0], crop[3] - crop[1])
    piece, mask = image_repair.inpaint_inputs(original, flaw, crop, work)
    mask_image = Image.open(io.BytesIO(mask)).convert('L')
    piece_image = Image.open(io.BytesIO(piece))
    assert mask_image.size == work and piece_image.size == work
    centre = (work[0] // 2, work[1] // 2)
    assert mask_image.getpixel(centre) == 255 and mask_image.getpixel((2, 2)) == 0
    share = sum(v > 127 for v in mask_image.tobytes()) / (work[0] * work[1])
    assert 0.02 < share < 0.6                                                           # a region, never the whole crop


def test_local_prompt_uses_the_fix_and_only_the_style_tail_of_the_scene():
    flaw = image_repair.Flaw((0.1, 0.1, 0.3, 0.3), 'a normal cow leg')
    text = image_repair.local_prompt(flaw, 'A Holstein cow in a field. Soft morning light, 85mm photo.')
    assert text.startswith('a normal cow leg.') and 'Soft morning light, 85mm photo' in text and 'Holstein' not in text
    # an instruction is not a description of what to paint: the generic continuation is used instead
    instruction = image_repair.Flaw((0, 0, 0.1, 0.1), 'Remove the extra leg')
    assert image_repair.local_prompt(instruction, 'A cow, soft light.').startswith(image_repair.GENERIC_FIX)
    assert image_repair.local_prompt(image_repair.Flaw((0, 0, 0.1, 0.1)), '').startswith(image_repair.GENERIC_FIX)


# ---- repair inside the rounds ----------------------------------------------------------------------------------

def test_a_failing_draft_is_repaired_instead_of_redrawn_and_the_repair_wins():
    calls = []

    def judge_one(png_, plan):
        return clear_verdict() if png_ == b'fixed' else failing()

    def repair_one(item, plan, attempt):
        calls.append((item['seed'], attempt))
        return {'png': b'fixed', 'seed': 99, 'round': 0, 'prompt': 'fix', 'verdict': None, 'kind': 'repair'}

    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=2, seed=10, render=lambda p, s: b'bad', judge_one=judge_one, repair_one=repair_one)
    assert calls == [(10, 0)] and rounds == 1 and len(items) == 3        # 2 drafts + 1 repair, no reroll round
    assert items[best]['kind'] == 'repair' and items[best]['verdict'].passed


def test_repair_stops_after_the_budget_and_then_rerolls_once():
    attempts = []

    def repair_one(item, plan, attempt):
        attempts.append(attempt)
        return {'png': b'still bad', 'seed': 50 + attempt, 'round': 0, 'prompt': 'fix', 'verdict': None, 'kind': 'repair'}

    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=2, seed=10, render=lambda p, s: b'bad', judge_one=lambda png_, plan: failing(),
        repair_one=repair_one)
    assert attempts == list(range(image_repair.MAX_REPAIRS))
    assert rounds == 2 and sum(i['kind'] == 'draft' for i in items) == 3      # 2 drafts + a reroll of 1
    assert not items[best]['verdict'].passed


def test_nothing_to_box_goes_straight_to_the_reroll():
    attempts = []
    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=2, seed=10, render=lambda p, s: b'bad', judge_one=lambda png_, plan: failing(),
        repair_one=lambda item, plan, attempt: attempts.append(attempt))
    assert attempts == [0] and rounds == 2 and not any(i['kind'] == 'repair' for i in items)


def test_a_passing_draft_is_never_repaired():
    called = []
    image_quality.run_rounds(
        plan_of(), drafts=1, seed=10, render=lambda p, s: b'ok',
        judge_one=lambda png_, plan: image_judge.Verdict(checks_yes=2, checks_total=3, soft=['x'], score=0.7),
        repair_one=lambda *a: called.append(a))
    assert not called


# ---- text inside the scene -------------------------------------------------------------------------------------

def test_exact_text_needs_every_word_as_a_whole():
    assert image_judge.exact_text(['PIZZA'], ['pizza'])
    assert not image_judge.exact_text(['PIZZA'], ['PIZZAS'])
    assert not image_judge.exact_text(['OPEN 24 HOURS'], ['OPEN 24 HOUR'])
    assert image_judge.exact_text(['SCORE 0420', 'LIVES 3'], ['SCORE: 0420 LIVES 3'])
    assert not image_judge.exact_text(['SCORE 0420', 'LIVES 3'], ['SCORE 0420'])
    assert image_judge.exact_text([], [])


def test_the_judge_fails_a_picture_whose_words_do_not_read_back(tmp_path):
    path = tmp_path / 'a.png'
    path.write_bytes(noisy_png())
    calls = []

    def ask(settings, question, images, max_tokens=0):
        calls.append(question)
        return SimpleNamespace(text='{"subjects":[],"text":["PIZA"]}')

    verdict = image_judge.judge(None, path, ('Is there a sign?',), expected_text=['PIZZA'], ask=ask)
    assert verdict.text_ok is False and not verdict.passed and not verdict.clear and len(calls) == 1
    assert 'PIZZA' in verdict.issues[0] and 'NOT read back' in verdict.brief()
    good = image_judge.judge(None, path, (), expected_text=['PIZZA'], ask=lambda *a, **k: SimpleNamespace(
        text='{"subjects":[],"text":["PIZZA"]}'))
    assert good.text_ok is True and good.passed


def test_parallel_judge_asks_both_questions_at_once_and_ignores_the_checks_of_a_failed_look(tmp_path):
    path = tmp_path / 'a.png'
    path.write_bytes(noisy_png())
    asked = []

    def ask(settings, question, images, max_tokens=0):
        asked.append('blind' if 'List every animal' in question else 'checks')
        time.sleep(0.02)
        return SimpleNamespace(text=GOOD if 'List every animal' in question else '{"answers":["yes","yes"]}')

    GOOD = '{"subjects":[{"kind":"cow","visible_legs":4,"heads":1}],"text":[]}'
    verdict = image_judge.judge(None, path, ('a?', 'b?'), expected_text=[], ask=ask, parallel=True)
    assert verdict.clear and sorted(asked) == ['blind', 'checks']
    asked.clear()
    bad = '{"subjects":[{"kind":"cow","visible_legs":6,"heads":1}],"text":[]}'
    verdict = image_judge.judge(None, path, ('a?',), ask=lambda s, q, i, max_tokens=0: SimpleNamespace(
        text=bad if 'List every animal' in q else '{"answers":["yes"]}'), parallel=True)
    assert not verdict.passed and verdict.checks_total == 0


def test_parse_plan_scene_flag_only_for_short_words_on_an_object():
    plan = plan_of(SIGN_PLAN)
    assert [o.scene for o in plan.overlays] == [True, False]
    long = json.loads(SIGN_PLAN)
    long['overlays'] = [{'text': 'THE QUICK BROWN FOX JUMPS', 'scene': True}, {'text': 'OPEN', 'scene': 'yes'}]
    plan = image_prompt.parse_plan('x', json.dumps(long))
    assert [o.scene for o in plan.overlays] == [False, False]
    assert image_prompt.scene_prompt(plan_of(SIGN_PLAN)).endswith('reads exactly "PIZZA", in clear, large, correctly spelled letters.')
    assert image_prompt.scene_prompt(plan_of()) == plan_of().prompt


def test_zimage_workflows():
    flow = zimage_text_to_image('a cow', 512, 512, 7, 5)
    assert flow['sample']['inputs']['steps'] == 5
    assert zimage_text_to_image('a cow', 512, 512, 7)['sample']['inputs']['steps'] == ZIMAGE_STEPS == 8
    assert ZIMAGE_STEPS_FAST < ZIMAGE_STEPS
    fix = zimage_inpaint('a leg', 'star/src.png', 'star/mask.png', 768, 640, 3, 0.7, 6)
    assert 'latent' not in fix and fix['masked']['class_type'] == 'SetLatentNoiseMask'
    assert fix['sample']['inputs']['latent_image'] == ['masked', 0] and fix['sample']['inputs']['denoise'] == 0.7
    assert fix['sample']['inputs']['steps'] == 6 and fix['encode']['inputs']['pixels'] == ['source', 0]
    assert fix['source']['inputs']['image'] == 'star/src.png' and fix['mask_image']['inputs']['image'] == 'star/mask.png'
    for node in fix.values():                                   # core ComfyUI nodes only
        assert node['class_type'] in {'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode', 'ConditioningZeroOut',
                                      'ModelSamplingAuraFlow', 'KSampler', 'VAEDecode', 'PreviewImage', 'LoadImage',
                                      'VAEEncode', 'ImageToMask', 'SetLatentNoiseMask'}


# ---- generate_best with a fake ComfyUI that has Z-Image --------------------------------------------------------

class FakeZ:
    """ComfyUI with Z-Image. Paints noise at the workflow's size; repairs return a flat red patch."""

    def __init__(self, hold=False):
        self.flows = []
        self.uploads = []
        self.sizes = {}
        self.hold = hold

    def status(self):
        return {'running': True}

    def missing_models(self, engine='klein'):
        return []

    def upload(self, content, name):
        self.uploads.append(name)
        self.sizes[name] = Image.open(io.BytesIO(content)).size
        return 'star/' + name

    def run(self, flow, **kwargs):
        self.flows.append(flow)
        cancel = kwargs.get('cancel_event')
        if self.hold and len([f for f in self.flows if 'masked' not in f]) > 2 and cancel is not None:
            for _ in range(300):
                if cancel.is_set():
                    raise RuntimeError('STAR image generation cancelled by user')
                time.sleep(0.01)
        if 'masked' in flow:                       # a repair: a flat red patch the size of the uploaded crop
            return [_flat(self.sizes['star_fix_src.png'], (255, 0, 0))]
        node = flow['latent']
        return [noisy_png((node['inputs']['width'], node['inputs']['height']))]

    def close(self):
        pass


def _flat(size, color):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format='PNG')
    return out.getvalue()


def vision_script(blind_replies, checks='{"answers":["yes","yes"]}', locate_reply=None):
    """blind_replies: one reply per blind look, in order (the looks are made one at a time)."""
    queue = list(blind_replies)
    lock = threading.Lock()
    questions = []

    def ask(settings, question, images, max_tokens=0):
        with lock:
            questions.append(question)
            if 'List every animal' in question:
                return SimpleNamespace(text=queue.pop(0) if len(queue) > 1 else queue[0])
        if 'smallest region' in question:
            return SimpleNamespace(text=locate_reply or '{"regions":[]}')
        return SimpleNamespace(text=checks)
    ask.questions = questions
    return ask


@pytest.fixture
def quiet(monkeypatch):
    image_prompt._CACHE.clear()
    monkeypatch.setattr(image_quality.media_places, 'require', lambda *a, **k: 'pc')
    monkeypatch.setattr(image_quality.references, 'paths', lambda *a, **k: [])
    monkeypatch.setattr(image_quality, 'warm_up', lambda *a, **k: None)


def test_a_bad_cow_is_repaired_in_its_region_and_judged_again(tmp_path, quiet):
    bad = '{"subjects":[{"kind":"cow","visible_legs":6,"heads":1}],"text":[]}'
    good = '{"subjects":[{"kind":"cow","visible_legs":4,"heads":1}],"text":[]}'
    locate = '{"regions":[{"box":[400,400,600,700],"fix":"one normal cow leg"}]}'
    comfy = FakeZ()
    result = image_quality.generate_best(
        Settings(image_drafts=2), 'a real cow', tmp_path, client=comfy, ask_brain=lambda s, system, user: PLAN, seed=4,
        ask_vision=vision_script([bad, bad, good], locate_reply=locate))
    note = result['note']
    kinds = [d['kind'] for d in note['drafts']]
    assert kinds[:2] == ['draft', 'draft'] and kinds[-1] == 'repair'
    assert note['drafts'][note['chosen']]['kind'] == 'repair' and note['drafts'][note['chosen']]['judge']['passed']
    assert 'repainted and judged again' in result['answer'] and note['rounds'] == 1
    repaint = [f for f in comfy.flows if 'masked' in f]
    assert len(repaint) == 1 and repaint[0]['sample']['inputs']['denoise'] == image_repair.DENOISE
    assert 'one normal cow leg' in repaint[0]['text']['inputs']['text']
    assert 'star_fix_src.png' in comfy.uploads and 'star_fix_mask.png' in comfy.uploads
    picture = Image.open(result['path']).convert('RGB')
    assert picture.size == (1024, 1024)
    assert picture.getpixel((512, 550)) == (255, 0, 0)                                          # the repaired region is pasted in
    assert picture.getpixel((30, 30)) == Image.open(io.BytesIO(noisy_png((1024, 1024)))).convert('RGB').getpixel((30, 30))


def test_in_scene_words_read_back_exactly_are_kept_and_only_the_other_text_is_drawn_by_star(tmp_path, quiet):
    blind = '{"subjects":[],"text":["PIZZA"]}'
    comfy = FakeZ()
    result = image_quality.generate_best(
        Settings(), 'a neon sign that says PIZZA', tmp_path, client=comfy, ask_brain=lambda s, system, user: SIGN_PLAN,
        seed=4, ask_vision=vision_script([blind]))
    note = result['note']
    assert note['timing']['text_in_scene'] and not note['timing']['text_fallback']
    assert note['steps'] == ZIMAGE_STEPS                                          # words get the full 8 steps
    first = [f for f in comfy.flows if 'latent' in f][0]
    assert 'reads exactly "PIZZA"' in first['text']['inputs']['text']
    assert 'text drawn by the model and read back exactly: "PIZZA"' in result['answer']
    assert 'text drawn by STAR: "SCORE 0420"' in result['answer'] and '"PIZZA"' not in result['answer'].split('text drawn by STAR')[1]


def test_in_scene_words_that_do_not_read_back_fall_back_to_a_blank_scene_and_the_pillow_text(tmp_path, quiet):
    blind = '{"subjects":[],"text":["PIZA"]}'
    comfy = FakeZ()
    result = image_quality.generate_best(
        Settings(), 'a neon sign that says PIZZA', tmp_path, client=comfy, ask_brain=lambda s, system, user: SIGN_PLAN,
        seed=4, ask_vision=vision_script([blind]))
    note = result['note']
    assert note['timing']['text_fallback']
    last = [f for f in comfy.flows if 'latent' in f][-1]
    assert 'reads exactly' not in last['text']['inputs']['text']                    # the blank-area prompt
    assert 'text drawn by STAR: "PIZZA", "SCORE 0420"' in result['answer']
    assert note['drafts'][note['chosen']]['kind'] == 'blank'


def test_with_a_dead_judge_the_in_scene_words_cannot_be_trusted_so_star_draws_them(tmp_path, quiet):
    def boom(*a, **k):
        raise ConnectionError('down')

    result = image_quality.generate_best(
        Settings(), 'a neon sign that says PIZZA', tmp_path, client=FakeZ(), ask_brain=lambda s, system, user: SIGN_PLAN,
        seed=4, ask_vision=boom)
    assert result['note']['timing']['text_fallback'] and '"PIZZA"' in result['answer']


def test_klein_never_draws_words_itself(tmp_path, quiet):
    comfy = FakeZ()
    comfy.missing_models = lambda engine='klein': ['models/x'] if engine == 'zimage' else []
    result = image_quality.generate_best(
        Settings(), 'a neon sign that says PIZZA', tmp_path, client=SimpleNamespace(
            status=comfy.status, missing_models=comfy.missing_models, upload=comfy.upload, close=comfy.close,
            run=lambda flow, **kw: [noisy_png((flow['latent']['inputs']['width'], flow['latent']['inputs']['height']))]),
        ask_brain=lambda s, system, user: SIGN_PLAN, seed=4,
        ask_vision=vision_script(['{"subjects":[],"text":[]}']))
    assert not result['note']['timing']['text_in_scene'] and 'text drawn by STAR: "PIZZA", "SCORE 0420"' in result['answer']


def test_legacy_pipeline_is_the_phase_one_behaviour(tmp_path, quiet):
    comfy = FakeZ()
    result = image_quality.generate_best(
        Settings(image_drafts=2), 'a real cow', tmp_path, client=comfy, ask_brain=lambda s, system, user: PLAN, seed=4,
        legacy=True, ask_vision=vision_script(['{"subjects":[{"kind":"cow","visible_legs":4,"heads":1}],"text":[]}']))
    note = result['note']
    assert note['timing']['pipeline'] == 'phase1' and note['steps'] == ZIMAGE_STEPS and not note['timing']['early_stop']
    assert len(note['drafts']) == 2 and all(f['sample']['inputs']['steps'] == ZIMAGE_STEPS for f in comfy.flows)


def test_phase_two_drafts_use_the_fast_step_count(tmp_path, quiet):
    comfy = FakeZ()
    result = image_quality.generate_best(
        Settings(), 'a real cow', tmp_path, client=comfy, ask_brain=lambda s, system, user: PLAN, seed=4,
        ask_vision=vision_script(['{"subjects":[{"kind":"cow","visible_legs":4,"heads":1}],"text":[]}']))
    assert result['note']['steps'] == ZIMAGE_STEPS_FAST and result['note']['timing']['pipeline'] == 'phase2'
    assert all(f['sample']['inputs']['steps'] == ZIMAGE_STEPS_FAST for f in comfy.flows)


def test_warm_up_draws_a_tiny_picture_for_zimage_only():
    ran = []
    comfy = SimpleNamespace(run=lambda flow, **kw: ran.append((flow['latent']['inputs']['width'], flow['sample']['inputs']['steps'])))
    thread = image_quality.warm_up(comfy, 'zimage', None)
    thread.join(2)
    assert ran == [(512, 4)] and image_quality.warm_up(comfy, 'klein', None) is None

    def broken(flow, **kw):
        raise RuntimeError('out of memory')
    image_quality.warm_up(SimpleNamespace(run=broken), 'zimage', None).join(2)         # never raises


def test_the_user_can_cancel_while_the_pipeline_waits_for_the_judge(tmp_path, quiet):
    cancel = threading.Event()
    gate = threading.Event()

    def slow_vision(settings, question, images, max_tokens=0):
        gate.set()
        cancel.set()
        time.sleep(0.2)
        return SimpleNamespace(text='{"subjects":[],"text":[]}')

    with pytest.raises(RuntimeError, match='cancelled'):
        image_quality.generate_best(Settings(image_drafts=4), 'a real cow', tmp_path, client=FakeZ(), cancel_event=cancel,
                                    ask_brain=lambda s, system, user: PLAN, seed=1, ask_vision=slow_vision)


# ---- Discord /draw uses the same pipeline ----------------------------------------------------------------------

def test_discord_draw_uses_the_careful_pipeline_when_it_is_on_and_the_single_shot_when_not(tmp_path, monkeypatch):
    from star import image_gen
    from star.discord_bot import draw
    seen = []
    monkeypatch.setattr(image_quality, 'generate_best', lambda settings, prompt, home, **kw: seen.append(('best', kw)) or {})
    monkeypatch.setattr(image_gen, 'generate', lambda settings, prompt, home, **kw: seen.append(('single', kw)) or {})
    draw.make_picture(Settings(), 'a dragon', tmp_path, size='square', use_references=False)
    draw.make_picture(Settings(image_quality=False), 'a dragon', tmp_path)
    draw.make_picture(Settings(comfy_workflow='my.json'), 'a dragon', tmp_path)
    assert [kind for kind, _ in seen] == ['best', 'single', 'single']
    assert seen[0][1]['use_references'] is False and seen[0][1]['size'] == 'square'


def test_discord_drawer_defaults_to_the_pipeline_and_a_timeout_that_fits_it():
    from star.discord_bot import draw
    assert draw.DrawSettings().timeout_seconds == draw.DEFAULT_TIMEOUT >= 360
    drawer = draw.Drawer(draw.DrawSettings())
    generate, _, _ = drawer._parts()
    assert generate is draw.make_picture
