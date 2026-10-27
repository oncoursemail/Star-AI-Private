"""The owner's blind A/B test: random sides that never leak, one stored pick per pair, an honest summary, the host actions."""
import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image

from star import image_ab, media_actions
from star.desktop_core import Settings


def picture(color) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', (64, 48), color).save(out, format='PNG')
    return out.getvalue()


OLD, NEW = picture((200, 30, 30)), picture((30, 30, 200))


def red(png: bytes) -> bool:
    return Image.open(io.BytesIO(png)).convert('RGB').getpixel((1, 1))[0] > 100


def stored(home: Path, pair: dict, side: str) -> bytes:
    return (image_ab.folder(home) / f"{pair['id']}-{side}.png").read_bytes()


def test_the_sides_are_random_and_stored_so_each_side_holds_what_the_pair_says(tmp_path):
    rng = random.Random(7)
    lefts = []
    for index in range(40):
        pair = image_ab.add_pair(tmp_path, f'prompt {index}', OLD, NEW, rng=rng)
        lefts.append(pair['left'])
        assert {pair['left'], pair['right']} == {'old', 'new'}
        assert red(stored(tmp_path, pair, 'left')) == (pair['left'] == 'old')
        assert red(stored(tmp_path, pair, 'right')) == (pair['right'] == 'old')
    assert 10 <= lefts.count('old') <= 30                      # a coin, not a pattern


def test_the_page_never_learns_which_side_is_which_pipeline(tmp_path):
    pair = image_ab.add_pair(tmp_path, 'a real cow', OLD, NEW, rng=random.Random(1))
    shown = image_ab.next_pair(tmp_path)
    assert shown['id'] == pair['id'] and shown['prompt'] == 'a real cow' and shown['waiting'] == 1
    assert shown['left'].startswith('data:image/webp;base64,') and shown['right'].startswith('data:image/webp;base64,')
    text = json.dumps(shown).lower()
    assert 'old' not in text.replace('hold', '') and '"new"' not in text and 'pipeline' not in text


def test_a_pick_maps_the_side_to_the_pipeline_and_is_stored_once(tmp_path):
    pair = image_ab.add_pair(tmp_path, 'a real cow', OLD, NEW, rng=random.Random(1))
    summary = image_ab.pick(tmp_path, pair['id'], 'left')
    chose = pair['left']
    assert summary[chose] == 1 and summary['picked'] == 1 and summary['waiting'] == 0
    rows = image_ab.read_picks(tmp_path)
    assert rows[0]['chose'] == chose and rows[0]['side'] == 'left' and rows[0]['prompt'] == 'a real cow'
    with pytest.raises(ValueError, match='already has your pick'):
        image_ab.pick(tmp_path, pair['id'], 'right')
    assert image_ab.next_pair(tmp_path) is None                # nothing left to show


def test_same_is_stored_as_a_tie_and_does_not_count_for_either(tmp_path):
    pair = image_ab.add_pair(tmp_path, 'x', OLD, NEW)
    summary = image_ab.pick(tmp_path, pair['id'], 'tie')
    assert summary['tie'] == 1 and summary['new'] == summary['old'] == summary['decided'] == 0
    assert summary['new_rate'] is None


@pytest.mark.parametrize('bad', ['', 'middle', 'LEFT', 'old', None])
def test_a_bad_side_or_pair_is_refused(tmp_path, bad):
    pair = image_ab.add_pair(tmp_path, 'x', OLD, NEW)
    with pytest.raises(ValueError):
        image_ab.pick(tmp_path, pair['id'], bad)
    with pytest.raises(ValueError, match='Unknown pair'):
        image_ab.pick(tmp_path, 'nope', 'left')
    with pytest.raises(ValueError, match='Unknown pair'):
        image_ab.pick(tmp_path, '../../etc/passwd', 'left')
    assert image_ab.read_picks(tmp_path) == []


def test_pairs_are_shown_oldest_first_and_only_until_picked(tmp_path):
    first = image_ab.add_pair(tmp_path, 'first', OLD, NEW)
    image_ab.add_pair(tmp_path, 'second', OLD, NEW)
    assert image_ab.next_pair(tmp_path)['prompt'] == 'first' and image_ab.next_pair(tmp_path)['waiting'] == 2
    image_ab.pick(tmp_path, first['id'], 'right')
    assert image_ab.next_pair(tmp_path)['prompt'] == 'second' and image_ab.next_pair(tmp_path)['waiting'] == 1


def test_add_pair_validation(tmp_path):
    with pytest.raises(ValueError, match='prompt'):
        image_ab.add_pair(tmp_path, '  ', OLD, NEW)
    with pytest.raises(ValueError, match='two pictures'):
        image_ab.add_pair(tmp_path, 'x', b'', NEW)
    long = image_ab.add_pair(tmp_path, 'word ' * 200, OLD, NEW)
    assert len(long['prompt']) <= image_ab.MAX_PROMPT


def test_sign_test_p_values():
    assert image_ab.sign_test_p(0, 0) == 1.0
    assert image_ab.sign_test_p(5, 5) == 1.0
    assert image_ab.sign_test_p(8, 0) == pytest.approx(2 / 256)
    assert image_ab.sign_test_p(0, 8) == image_ab.sign_test_p(8, 0)
    assert image_ab.sign_test_p(9, 3) == pytest.approx(0.146, abs=0.001)


def pick_all(home, new_wins, old_wins, ties=0):
    """Store that many picks of each kind, whatever side each pair put them on."""
    for chose in ['new'] * new_wins + ['old'] * old_wins + ['tie'] * ties:
        pair = image_ab.add_pair(home, f'p{chose}', OLD, NEW)
        side = 'tie' if chose == 'tie' else pair['left'] == chose and 'left' or 'right'
        image_ab.pick(home, pair['id'], side)
    return image_ab.summarize(home)


def test_the_verdict_says_nothing_until_enough_pairs_are_decided(tmp_path):
    summary = pick_all(tmp_path, 4, 1, ties=3)
    assert summary['decided'] == 5 and 'Too few' in summary['verdict'] and summary['new_rate'] == 0.8


def test_the_verdict_names_the_winner_only_when_the_sign_test_says_so(tmp_path):
    summary = pick_all(tmp_path, 9, 1)
    assert summary['verdict'].startswith('The new pipeline is better: 9 of 10') and summary['p'] < 0.05
    other = tmp_path / 'b'
    assert pick_all(other, 1, 9)['verdict'].startswith('The OLD pipeline is better')
    close = tmp_path / 'c'
    assert pick_all(close, 6, 4)['verdict'].startswith('No clear difference yet')


def test_a_damaged_picks_file_is_survived(tmp_path):
    pair = image_ab.add_pair(tmp_path, 'x', OLD, NEW)
    image_ab.pick(tmp_path, pair['id'], 'left')
    with open(image_ab.folder(tmp_path) / 'picks.jsonl', 'a', encoding='utf-8') as out:
        out.write('{not json\n[1,2]\n{"pair": "zz", "chose": "new"}\n{"pair": "' + pair['id'] + 'x", "chose": "sideways"}\n')
    assert len(image_ab.read_picks(tmp_path)) == 1 and image_ab.summarize(tmp_path)['picked'] == 1
    (image_ab.folder(tmp_path) / 'pairs.json').write_text('garbage', encoding='utf-8')
    assert image_ab.next_pair(tmp_path) is None


def test_a_pair_with_a_missing_picture_is_skipped_not_fatal(tmp_path):
    broken = image_ab.add_pair(tmp_path, 'broken', OLD, NEW)
    image_ab.add_pair(tmp_path, 'fine', OLD, NEW)
    (image_ab.folder(tmp_path) / f"{broken['id']}-left.png").unlink()
    assert image_ab.next_pair(tmp_path)['prompt'] == 'fine'


def test_make_pair_draws_the_old_and_the_new_pipeline_from_one_prompt(tmp_path):
    calls = []

    def generate(settings, prompt, home, *, legacy, cancel_event=None):
        calls.append((prompt, legacy))
        path = tmp_path / f"{'old' if legacy else 'new'}.png"
        path.write_bytes(OLD if legacy else NEW)
        return {'path': path, 'note': {'seconds': 180.0 if legacy else 70.0}}

    pair = image_ab.make_pair(None, tmp_path, ' a   real cow ', generate=generate, rng=random.Random(3))
    assert calls == [('a real cow', True), ('a real cow', False)]
    assert red(stored(tmp_path, pair, pair['left'] and 'left')) == (pair['left'] == 'old')
    assert pair['meta']['seconds'] == {'old': 180.0, 'new': 70.0}
    with pytest.raises(ValueError):
        image_ab.make_pair(None, tmp_path, '', generate=generate)


def test_host_actions(tmp_path):
    def run(action, **body):
        return media_actions.handle(action, body, settings=Settings(project='T'), home=tmp_path, allowed_file=lambda p: p)

    assert {'imageAbNext', 'imageAbPick', 'imageAbSummary', 'imageAbMake'} <= media_actions.MEDIA_ACTIONS
    assert 'imageAbMake' in media_actions.SLOW_MEDIA_ACTIONS and 'imageAbPick' not in media_actions.SLOW_MEDIA_ACTIONS
    assert run('imageAbNext')['pair'] is None
    pair = image_ab.add_pair(tmp_path, 'a cat', OLD, NEW, rng=random.Random(2))
    shown = run('imageAbNext')
    assert shown['pair']['id'] == pair['id'] and shown['summary']['waiting'] == 1
    done = run('imageAbPick', id=pair['id'], side='right')
    assert done['summary'][pair['right']] == 1
    assert run('imageAbSummary')['picked'] == 1
    with pytest.raises(ValueError):
        run('imageAbPick', id=pair['id'], side='right')


def test_a_benchmark_run_becomes_pairs_of_the_same_prompt_and_seed(tmp_path):
    pics = tmp_path / 'pics'
    pics.mkdir()
    suite = tmp_path / 'suite.json'
    suite.write_text(json.dumps({'prompts': [{'id': 'cow', 'request': 'a real cow'}, {'id': 'horse', 'request': 'a horse'}]}),
                     encoding='utf-8')
    rows = []
    for phase, png_ in (('1', OLD), ('2', NEW)):
        for pid, seed in (('cow', 1111), ('cow', 2222), ('horse', 1111)):
            if phase == '1' and seed == 2222:
                continue                                         # no phase-1 picture for this one: no pair
            name = f'p{phase}-{pid}-{seed}.png'
            (pics / name).write_bytes(png_)
            rows.append({'phase': phase, 'id': pid, 'seed': seed, 'file': name, 'seconds': 100.0 if phase == '1' else 40.0})
    results = tmp_path / 'r.json'
    results.write_text(json.dumps({'rows': rows}), encoding='utf-8')
    home = tmp_path / 'home'
    assert image_ab.import_benchmark(home, results, pics, suite, rng=random.Random(5)) == 2
    assert image_ab.import_benchmark(tmp_path / 'other', results, pics, suite) == 2
    shown = image_ab.next_pair(home)
    assert shown['prompt'] == 'a real cow' and shown['waiting'] == 2
    assert image_ab._read_pairs(home)[0]['meta']['seconds'] == {'old': 100.0, 'new': 40.0}
