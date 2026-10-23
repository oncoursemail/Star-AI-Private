"""Image quality pipeline: rewriter, blind-judge parsing and counting, exact text overlay, draft selection. No GPU."""
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from star import image_judge, image_post, image_prompt, image_quality
from star.comfy import ENGINES, zimage_text_to_image
from star.desktop_core import Settings

GOOD_PLAN = json.dumps({
    'prompt': 'Full-body side view of a Holstein cow standing on green grass, four legs visible, one head, two ears, '
              'one tail, soft morning light, 85mm photo.',
    'aspect': 'wide', 'overlays': [{'text': 'SCORE 0420', 'where': 'top-left', 'style': 'pixel'},
                                   {'text': 'x', 'where': 'nowhere', 'style': 'fancy'}],
    'checks': ['Is there a cow?', 'Is it standing on grass?']})


def png(color=(200, 120, 40), size=(320, 200), noisy=True) -> bytes:
    image = Image.new('RGB', size, color)
    if noisy:
        for x in range(size[0]):
            for y in range(size[1]):
                image.putpixel((x, y), (min(255, x * 255 // size[0]), min(255, y * 255 // size[1]), 90))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


# ---- rewriter --------------------------------------------------------------------------------------------------

def test_parse_json_tolerates_fences_and_chatter():
    assert image_prompt.parse_json('Sure!\n```json\n{"a": {"b": "}"}, "c": 1}\n```\nbye') == {'a': {'b': '}'}, 'c': 1}
    assert image_prompt.parse_json('no json here') is None
    assert image_prompt.parse_json('[1,2]') is None


def test_parse_plan_validates_fields():
    plan = image_prompt.parse_plan('a real cow', GOOD_PLAN)
    assert plan.rewritten and plan.aspect == 'wide' and len(plan.checks) == 2
    assert plan.overlays[0] == image_prompt.Overlay('SCORE 0420', 'top-left', 'pixel')
    assert plan.overlays[1] == image_prompt.Overlay('x', 'bottom', 'bold')      # bad where/style fall back
    assert image_prompt.parse_plan('x', '{"prompt": "short"}') is None


def test_rewrite_falls_back_to_the_owners_words_and_does_not_cache_the_fallback():
    calls = []

    def broken(settings, system, user):
        calls.append(user)
        raise TimeoutError('brain down')

    image_prompt._CACHE.clear()
    plan = image_prompt.rewrite(None, 'a sign that says "OPEN 24 HOURS" on a shop', ask=broken)
    assert not plan.rewritten and plan.overlays == (image_prompt.Overlay('OPEN 24 HOURS', 'bottom', 'bold'),)
    assert '"' not in plan.prompt
    image_prompt.rewrite(None, 'a sign that says "OPEN 24 HOURS" on a shop', ask=broken)
    assert len(calls) == 2


def test_rewrite_caches_per_request():
    calls = []

    def brain(settings, system, user):
        calls.append(user)
        return GOOD_PLAN

    image_prompt._CACHE.clear()
    first = image_prompt.rewrite(None, 'A real cow', ask=brain)
    assert image_prompt.rewrite(None, 'a real cow', ask=brain) is first and len(calls) == 1


def test_repaired_prompt_adds_the_judges_complaints():
    plan = image_prompt.parse_plan('cow', GOOD_PLAN)
    fixed = image_prompt.repaired(plan, ['cow: exactly 4 legs each, not 5', 'cow: exactly 4 legs each, not 5'])
    assert fixed.prompt.count('exactly 4 legs') == 1 and fixed.prompt.startswith(plan.prompt)


# ---- judge counting --------------------------------------------------------------------------------------------

def test_five_legged_cow_fails_and_hidden_legs_do_not():
    hard, soft = image_judge.check_anatomy([{'kind': 'cow', 'visible_legs': 5, 'heads': 1, 'tails': 1}])
    assert hard == ['cow: exactly 4 legs each, not 5']
    assert image_judge.check_anatomy([{'kind': 'Holstein cows', 'visible_legs': 3, 'heads': 1}]) == ([], [])
    hard, soft = image_judge.check_anatomy([{'kind': 'cow', 'visible_legs': 1, 'heads': 1}])
    assert hard == [] or 'legs' in hard[0]
    assert image_judge.check_anatomy([{'kind': 'cow', 'visible_legs': 4, 'heads': 2}])[0] == ['cow: exactly 1 heads each, not 2']


def test_people_fingers_arms_and_limb_attachment():
    hard, _ = image_judge.check_anatomy([{'kind': 'woman', 'visible_arms': 3, 'visible_legs': 2, 'heads': 1,
                                          'fingers_per_hand': [5, 6]}])
    assert 'woman: exactly 2 arms each, not 3' in hard and 'woman: five fingers on each hand, not 6' in hard
    hard, _ = image_judge.check_anatomy([{'kind': 'horse', 'heads': 1, 'limbs_attach_naturally': False}])
    assert hard == ['each horse needs limbs that attach naturally to the body']
    # made-up creatures and sprites are never a hard failure; a cropped close-up has no head; two people have two heads
    assert image_judge.check_anatomy([{'kind': 'green alien', 'heads': 3, 'limbs_attach_naturally': False}])[0] == []
    assert image_judge.check_anatomy([{'kind': 'hands', 'heads': 0}]) == ([], [])
    assert image_judge.check_anatomy([{'kind': 'woman', 'heads': 0, 'visible_arms': 2}]) == ([], [])
    assert image_judge.check_anatomy([{'kind': 'people', 'count': 2, 'heads': 2, 'visible_arms': 4, 'visible_legs': 4}]) == ([], [])
    assert image_judge.check_anatomy([{'kind': 'people', 'count': 2, 'heads': 3}])[0]
    assert image_judge.check_anatomy([{'kind': 'spider', 'visible_legs': 8, 'heads': 1}]) == ([], [])
    assert image_judge.check_anatomy([{'kind': 'spider', 'visible_legs': 10}])[0]
    assert image_judge.check_anatomy('garbage') == ([], [])


def test_numbers_can_be_strings_or_null_and_unknown_kinds_are_not_guessed():
    assert image_judge.check_anatomy([{'kind': 'cow', 'visible_legs': '4', 'heads': None}]) == ([], [])
    assert image_judge.check_anatomy([{'kind': 'blob', 'visible_legs': 12}]) == ([], [])
    assert image_judge.kind_of('player ship') == '' and image_judge.kind_of('Holstein cows') == 'quadruped'
    assert image_judge.check_anatomy([{'kind': 'player_ship', 'limbs_attach_naturally': False}])[0] == []


def test_parse_blind_and_answers():
    reply = '```json\n{"subjects":[{"kind":"cow","visible_legs":5,"heads":1}],"text":["EXIT"],"problems":"an extra leg"}\n```'
    hard, soft, text = image_judge.parse_blind(reply)
    assert hard and text == ['EXIT'] and soft == ['judge noted: an extra leg']
    assert image_judge.parse_blind('I see a cow.') is None
    assert image_judge.parse_answers('{"answers":["yes","No","yes"]}', 3) == 2
    assert image_judge.parse_answers('1. yes\n2. no\n3. no', 3) == 1
    assert image_judge.parse_answers('{"answers":["yes"]}', 3) is None


def test_text_matches_is_exact_apart_from_case_and_punctuation():
    assert image_judge.text_matches(['SCORE 0420'], ['score: 0420', 'LIVES 3']) == 1.0
    assert image_judge.text_matches(['SCORE 0420', 'LIVES 3'], ['SCORE 0402']) == 0.0
    assert image_judge.text_matches([], ['anything']) == 1.0


def ask_with(*replies):
    queue = list(replies)
    seen = []

    def ask(settings, question, images, max_tokens=0):
        seen.append(question)
        return SimpleNamespace(text=queue.pop(0))
    ask.seen = seen
    return ask


def test_judge_is_blind_and_checks_only_clean_pictures(tmp_path):
    path = tmp_path / 'a.png'
    path.write_bytes(png())
    good = '{"subjects":[{"kind":"cow","visible_legs":4,"heads":1}],"text":[]}'
    ask = ask_with(good, '{"answers":["yes","yes"]}')
    verdict = image_judge.judge(None, path, ('Is there a cow?', 'On grass?'), expected_text=[], ask=ask)
    assert verdict.passed and verdict.checks_yes == 2 and 'cow' not in ask.seen[0].lower()
    assert 'Is there a cow' not in ask.seen[0] and 'Is there a cow' in ask.seen[1]
    bad = '{"subjects":[{"kind":"cow","visible_legs":6,"heads":1}],"text":[]}'
    ask = ask_with(bad)
    verdict = image_judge.judge(None, path, ('Is there a cow?',), ask=ask)
    assert not verdict.passed and len(ask.seen) == 1 and 'FAIL' in verdict.brief()


def test_judge_retries_unusable_json_once_then_gives_up(tmp_path):
    path = tmp_path / 'a.png'
    path.write_bytes(png())
    verdict = image_judge.judge(None, path, (), ask=ask_with('nope', 'still nope'))
    assert not verdict.judged and not verdict.passed


def test_blank_picture_fails_without_a_vision_call(tmp_path):
    path = tmp_path / 'blank.png'
    path.write_bytes(png(noisy=False))
    ask = ask_with()
    verdict = image_judge.judge(None, path, ('x?',), ask=ask)
    assert verdict.blank and not verdict.passed and not ask.seen


def test_two_of_three_checks_passes():
    assert image_judge.Verdict(checks_yes=2, checks_total=3).passed
    assert not image_judge.Verdict(checks_yes=1, checks_total=3).passed


def test_pick_prefers_passing_then_score():
    low = image_judge.Verdict(score=0.2)
    fail = image_judge.Verdict(anatomy_ok=False, issues=['x'], score=0.9)
    high = image_judge.Verdict(score=0.8, checks_yes=2, checks_total=2)
    assert image_judge.pick([fail, low, high]) == 2
    assert image_judge.pick([fail, image_judge.Verdict(anatomy_ok=False, issues=['y'], score=0.3)]) == 0


# ---- text overlay ----------------------------------------------------------------------------------------------

def test_bundled_fonts_and_licences_exist():
    for name in ('PressStart2P-Regular.ttf', 'Anton-Regular.ttf', 'OFL-PressStart2P.txt', 'OFL-Anton.txt'):
        assert (image_post.FONTS / name).is_file()
    assert 'SIL Open Font License' in (image_post.FONTS / 'OFL-Anton.txt').read_text(encoding='utf-8')


def test_overlay_draws_text_where_asked_and_nowhere_else():
    base = png(color=(10, 10, 40), size=(640, 360), noisy=False)
    out = image_post.draw_overlays(base, [image_prompt.Overlay('SCORE 0420', 'top-left', 'pixel')])
    before, after = Image.open(io.BytesIO(base)).convert('RGB'), Image.open(io.BytesIO(out)).convert('RGB')
    assert after.size == before.size
    changed = [(x, y) for x in range(0, 640, 2) for y in range(0, 360, 2) if before.getpixel((x, y)) != after.getpixel((x, y))]
    assert changed
    assert max(x for x, _ in changed) < 640 * 0.5 and max(y for _, y in changed) < 360 * 0.25      # top-left only
    assert image_post.draw_overlays(base, []) is base


def test_two_overlays_of_one_style_share_one_size():
    base = png(color=(10, 10, 40), size=(800, 450), noisy=False)
    out = image_post.draw_overlays(base, [image_prompt.Overlay('SCORE 0420 PLUS', 'top-left', 'pixel'),
                                          image_prompt.Overlay('3', 'top-right', 'pixel')])
    after = Image.open(io.BytesIO(out)).convert('RGB')
    right = [(x, y) for x in range(400, 800) for y in range(0, 225) if after.getpixel((x, y)) != (10, 10, 40)]
    assert right and (max(y for _, y in right) - min(y for _, y in right)) < 450 * 0.16     # a lone "3" is not blown up


def test_overlay_text_fits_the_picture_even_when_long():
    base = png(size=(400, 400), noisy=False)
    out = image_post.draw_overlays(base, [image_prompt.Overlay('A VERY LONG TITLE FOR THIS POSTER', 'bottom', 'bold')])
    after = Image.open(io.BytesIO(out)).convert('RGB')
    cols = [x for x in range(400) if any(after.getpixel((x, y)) != (200, 120, 40) for y in range(0, 400, 3))]
    assert cols and min(cols) >= 4 and max(cols) <= 395


# ---- rounds, engine choice, settings ---------------------------------------------------------------------------

def plan_of(**kw):
    return image_prompt.parse_plan('cow', GOOD_PLAN)


def test_run_rounds_picks_the_best_draft_without_a_repair_round():
    verdicts = iter([image_judge.Verdict(anatomy_ok=False, issues=['a'], score=0.1),
                     image_judge.Verdict(score=0.95, checks_yes=2, checks_total=2),
                     image_judge.Verdict(score=0.6, checks_yes=1, checks_total=2)])
    drawn = []
    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=3, seed=10, render=lambda prompt, seed: (drawn.append(seed) or b'png%d' % seed),
        judge_one=lambda png_, plan: next(verdicts))
    assert drawn == [10, 11, 12] and best == 1 and rounds == 1 and items[best]['seed'] == 11


def test_run_rounds_does_one_repair_round_with_new_seeds_and_the_complaints():
    prompts = []

    def judge_one(png_, plan):
        prompts.append(plan.prompt)
        ok = len(prompts) > 3 and png_.endswith(b'7930')
        return image_judge.Verdict() if ok else image_judge.Verdict(anatomy_ok=False, issues=['cow: exactly 4 legs each, not 5'])

    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=3, seed=10, render=lambda prompt, seed: b'png%d' % seed, judge_one=judge_one)
    assert rounds == 2 and len(items) == 5          # 3 drafts, then a repair round of half the size (2)
    assert all('exactly 4 legs' not in p for p in prompts[:3]) and all('exactly 4 legs' in p for p in prompts[3:])
    assert items[best]['round'] == 1 and items[best]['seed'] == 10 + 7919 + 1


def test_run_rounds_never_does_a_third_round_and_keeps_the_best_of_a_bad_lot():
    items, best, rounds = image_quality.run_rounds(
        plan_of(), drafts=2, seed=1, render=lambda prompt, seed: b'x',
        judge_one=lambda png_, plan: image_judge.Verdict(anatomy_ok=False, issues=['i'], score=0.05))
    assert rounds == 2 and len(items) == 3 and not items[best]['verdict'].passed


def test_dead_judge_stops_judging_and_keeps_the_first_draft():
    judged = []

    def dead(png_, plan):
        judged.append(1)
        return image_judge.Verdict(judged=False)

    items, best, rounds = image_quality.run_rounds(plan_of(), drafts=3, seed=5, render=lambda p, s: b'x', judge_one=dead)
    assert best == 0 and rounds == 1 and len(items) == 3 and len(judged) <= 3


def test_run_rounds_cancel():
    with pytest.raises(RuntimeError, match='cancelled'):
        image_quality.run_rounds(plan_of(), drafts=2, seed=1, render=lambda p, s: b'x',
                                 judge_one=lambda *a: image_judge.Verdict(), cancel=lambda: True)


def test_engine_choice_and_settings_defaults():
    assert image_quality.choose_engine('auto', {'klein': True, 'zimage': True}, False) == image_quality.DEFAULT_ENGINE
    assert image_quality.choose_engine('zimage', {'zimage': False}, False) == 'zimage'
    assert image_quality.choose_engine('zimage', {}, True) == 'klein'            # references need Klein
    settings = Settings()
    assert image_quality.settings_for(settings) == (True, 3, 'auto')
    assert image_quality.settings_for(SimpleNamespace(image_quality=False, image_drafts=9, image_engine='x')) == (False, 3, 'auto')
    for bad in ({'image_drafts': 0}, {'image_engine': 'sdxl'}, {'image_quality': 'yes'}):
        with pytest.raises(ValueError):
            Settings(**bad).validate()


def test_zimage_workflow_uses_core_nodes_and_the_installed_files():
    flow = zimage_text_to_image('a cow', 1024, 1024, 7)
    assert flow['sample']['inputs']['seed'] == 7 and flow['sample']['inputs']['steps'] == 8
    assert flow['clip']['inputs']['type'] == 'lumina2' and flow['text']['inputs']['text'] == 'a cow'
    assert set(ENGINES) == {'klein', 'zimage'}


class FakeComfy:
    def __init__(self):
        self.runs = 0

    def status(self):
        return {'running': True}

    def missing_models(self, engine='klein'):
        return [] if engine == 'klein' else ['models/x']

    def upload(self, content, name):
        return name

    def run(self, flow, **kwargs):
        self.runs += 1
        size = (flow['latent']['inputs']['width'], flow['latent']['inputs']['height'])
        return [png(color=(self.runs * 20, 90, 120), size=size)]

    def close(self):
        pass


def test_generate_best_end_to_end_with_fakes(tmp_path, monkeypatch):
    image_prompt._CACHE.clear()
    monkeypatch.setattr(image_quality.media_places, 'require', lambda *a, **k: 'pc')
    monkeypatch.setattr(image_quality.references, 'paths', lambda *a, **k: [])
    answers = iter(['{"subjects":[{"kind":"cow","visible_legs":4,"heads":1}],"text":[]}', '{"answers":["yes","yes"]}'] * 3)
    comfy = FakeComfy()
    result = image_quality.generate_best(
        Settings(), 'a real cow', tmp_path, client=comfy, ask_brain=lambda s, system, user: GOOD_PLAN,
        ask_vision=lambda s, q, images, max_tokens=0: SimpleNamespace(text=next(answers)), seed=3)
    assert comfy.runs == 3
    assert result['path'].is_file() and result['message'].endswith(result['path'].name)
    note = json.loads(result['path'].with_suffix('.json').read_text(encoding='utf-8'))
    assert note['prompt'] == 'a real cow' and note['plan']['rewritten'] and len(note['drafts']) == 3
    assert '3 drafts judged blind' in result['answer'] and 'SCORE 0420' in result['answer']
    assert (note['width'], note['height']) == (1280, 720)                       # the rewriter said "wide"
    drawn = Image.open(result['path']).convert('RGB')
    assert drawn.size == (1280, 720)


def test_generate_best_survives_a_dead_brain_and_a_dead_vision_model(tmp_path, monkeypatch):
    image_prompt._CACHE.clear()
    monkeypatch.setattr(image_quality.media_places, 'require', lambda *a, **k: 'pc')
    monkeypatch.setattr(image_quality.references, 'paths', lambda *a, **k: [])

    def boom(*args, **kwargs):
        raise ConnectionError('down')

    comfy = FakeComfy()
    result = image_quality.generate_best(Settings(), 'a real cow', tmp_path, client=comfy, ask_brain=boom,
                                         ask_vision=boom, seed=1)
    assert result['path'].is_file() and 'judge was not reachable' in result['answer']


def test_chat_entry_uses_the_careful_pipeline_by_default_and_not_for_edits(tmp_path, monkeypatch):
    from star import chat_images, image_gen
    (tmp_path / 'generated-images').mkdir()
    (tmp_path / 'generated-images' / 'x.png').write_bytes(b'x')
    seen = []
    monkeypatch.setattr(image_quality, 'generate_best',
                        lambda settings, prompt, home, **kw: seen.append(('best', kw['size'])) or
                        {'answer': 'a', 'image': 'i', 'message': chat_images.PREFIX + 'x.png'})
    monkeypatch.setattr(image_gen, 'generate',
                        lambda settings, prompt, home, **kw: seen.append(('single', kw['size'])) or
                        {'answer': 'a', 'image': 'i', 'message': chat_images.PREFIX + 'x.png'})
    chat_images.generate_chat_image(Settings(project='T'), 'a cat', tmp_path, size='wide')
    chat_images.generate_chat_image(Settings(project='T', image_quality=False), 'a cat', tmp_path)
    chat_images.generate_chat_image(Settings(project='T'), 'make it blue', tmp_path, source=tmp_path / 'x.png')
    assert seen == [('best', 'wide'), ('single', 'square'), ('single', 'square')]


def test_careful_pipeline_result_must_be_on_disk_too(tmp_path, monkeypatch):
    from star import chat_images
    monkeypatch.setattr(image_quality, 'generate_best', lambda *a, **k: {
        'answer': 'x', 'image': 'data:', 'message': chat_images.PREFIX + 'star-20260101-000000-00001.png'})
    with pytest.raises(RuntimeError, match='not in the STAR data folder'):
        chat_images.generate_chat_image(Settings(project='T'), 'a cow', tmp_path)
