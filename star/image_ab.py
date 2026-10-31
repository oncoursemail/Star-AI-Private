"""The owner's blind A/B test of two image pipelines.

Each pair is two pictures of the SAME prompt: one from the old pipeline, one from the new. The page shows them as "left"
and "right" in an order drawn at random when the pair is stored (so it never changes on reload and never leaks which is
which). The owner picks the better one or says "same". Picks are appended to a file and summarised with a sign test, so
"the new pipeline is better" has to be earned by the owner's own eyes, not by STAR's judge.

Files under `<STAR data>/image-ab/`: `pairs.json` (pairs, with which pipeline is on which side), `picks.jsonl` (one pick per
line, append-only), `<pair id>-left.png` / `-right.png`.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from pathlib import Path

PIPELINES = ('old', 'new')
SIDES = ('left', 'right', 'tie')
ID = re.compile(r'^[a-z0-9]{8,32}$')
MAX_PROMPT = 400
MAX_PAIRS = 400


def folder(home: Path) -> Path:
    return Path(home) / 'image-ab'


def _read_pairs(home: Path) -> list[dict]:
    try:
        data = json.loads((folder(home) / 'pairs.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, dict) and ID.fullmatch(str(p.get('id', '')))] if isinstance(data, list) else []


def _write_atomic(path: Path, text: str) -> None:
    partial = path.with_name(path.name + '.part')
    with open(partial, 'w', encoding='utf-8') as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    os.replace(partial, path)


def read_picks(home: Path) -> list[dict]:
    """Every stored pick. A damaged line is skipped, never fatal."""
    picks = []
    try:
        lines = (folder(home) / 'picks.jsonl').read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('chose') in PIPELINES + ('tie',) and ID.fullmatch(str(row.get('pair', ''))):
            picks.append(row)
    return picks


def add_pair(home: Path, prompt: str, old_png: bytes, new_png: bytes, *, rng=None, meta: dict | None = None) -> dict:
    """Store one pair. Which pipeline is on the left is decided here, at random, and kept."""
    prompt = re.sub(r'\s+', ' ', str(prompt or '')).strip()[:MAX_PROMPT]
    if not prompt:
        raise ValueError('A pair needs the prompt both pictures were made from')
    if not old_png or not new_png:
        raise ValueError('A pair needs two pictures')
    pairs = _read_pairs(home)
    if len(pairs) >= MAX_PAIRS:
        raise ValueError(f'The A/B test already holds {MAX_PAIRS} pairs')
    choose = rng.random if rng is not None else secrets.SystemRandom().random
    left, right = ('old', 'new') if choose() < 0.5 else ('new', 'old')
    pair_id = secrets.token_hex(6)
    base = folder(home)
    base.mkdir(parents=True, exist_ok=True)
    pictures = {'old': old_png, 'new': new_png}
    (base / f'{pair_id}-left.png').write_bytes(pictures[left])
    (base / f'{pair_id}-right.png').write_bytes(pictures[right])
    pair = {'id': pair_id, 'prompt': prompt, 'left': left, 'right': right,
            'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'meta': meta or {}}
    pairs.append(pair)
    _write_atomic(base / 'pairs.json', json.dumps(pairs, ensure_ascii=False, indent=1))
    return pair


def _preview(path: Path) -> str:
    from .chat_images import preview_image
    return preview_image(path)


def next_pair(home: Path) -> dict | None:
    """The oldest pair the owner has not picked yet, for the page. It does not say which side is which pipeline."""
    done = {row['pair'] for row in read_picks(home)}
    for pair in _read_pairs(home):
        if pair['id'] in done:
            continue
        base = folder(home)
        left, right = base / f"{pair['id']}-left.png", base / f"{pair['id']}-right.png"
        if not (left.is_file() and right.is_file()):
            continue
        return {'id': pair['id'], 'prompt': pair['prompt'], 'left': _preview(left), 'right': _preview(right),
                'waiting': sum(p['id'] not in done for p in _read_pairs(home))}
    return None


def pick(home: Path, pair_id: str, side: str) -> dict:
    """Store the owner's choice: 'left', 'right' or 'tie'. One pick per pair; returns the summary."""
    if side not in SIDES:
        raise ValueError('Choose left, right or same')
    if not ID.fullmatch(str(pair_id)):
        raise ValueError('Unknown pair')
    pair = next((p for p in _read_pairs(home) if p['id'] == pair_id), None)
    if pair is None:
        raise ValueError('Unknown pair')
    if any(row['pair'] == pair_id for row in read_picks(home)):
        raise ValueError('That pair already has your pick')
    chose = 'tie' if side == 'tie' else pair[side]
    row = {'pair': pair_id, 'chose': chose, 'side': side, 'prompt': pair['prompt'],
           'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    base = folder(home)
    base.mkdir(parents=True, exist_ok=True)
    with open(base / 'picks.jsonl', 'a', encoding='utf-8') as out:
        out.write(json.dumps(row, ensure_ascii=False) + '\n')
        out.flush()
        os.fsync(out.fileno())
    return summarize(home)


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact binomial p-value for `wins` of `wins + losses` decided pairs under a fair coin."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def summarize(home: Path) -> dict:
    """Counts, the new pipeline's win rate among decided pairs, the sign-test p-value and a plain verdict."""
    picks = read_picks(home)
    new = sum(p['chose'] == 'new' for p in picks)
    old = sum(p['chose'] == 'old' for p in picks)
    tie = sum(p['chose'] == 'tie' for p in picks)
    decided = new + old
    p_value = sign_test_p(new, old)
    if decided < 6:
        verdict = f'Too few decided pairs to say anything yet ({decided}; at least 6 are needed).'
    elif p_value < 0.05:
        verdict = ('The new pipeline is better: ' if new > old else 'The OLD pipeline is better: ') + f'{max(new, old)} of {decided} decided pairs (p = {p_value:.3f}).'
    else:
        verdict = f'No clear difference yet: new {new}, old {old} (p = {p_value:.2f}).'
    pairs = _read_pairs(home)
    done = {p['pair'] for p in picks}
    return {'picked': len(picks), 'new': new, 'old': old, 'tie': tie, 'decided': decided,
            'new_rate': round(new / decided, 3) if decided else None, 'p': round(p_value, 4), 'verdict': verdict,
            'waiting': sum(p['id'] not in done for p in pairs), 'pairs': len(pairs)}


def make_pair(settings, home: Path, prompt: str, *, cancel_event=None, generate=None, rng=None) -> dict:
    """Draw one pair with the real pipelines (minutes on the GPU): the OLD (phase 1) and the NEW (phase 2), then store it.

    `generate(settings, prompt, home, legacy=..., cancel_event=...)` is `image_quality.generate_best` (a fake in tests).
    """
    prompt = re.sub(r'\s+', ' ', str(prompt or '')).strip()
    if not 1 <= len(prompt) <= MAX_PROMPT:
        raise ValueError(f'Give a prompt of 1 to {MAX_PROMPT} characters')
    if generate is None:
        from .image_quality import generate_best as generate
    seconds = {}
    pictures = {}
    for name, legacy in (('old', True), ('new', False)):
        made = generate(settings, prompt, home, legacy=legacy, cancel_event=cancel_event)
        pictures[name] = Path(made['path']).read_bytes()
        seconds[name] = made['note'].get('seconds')
    return add_pair(home, prompt, pictures['old'], pictures['new'], rng=rng, meta={'seconds': seconds})


def import_benchmark(home: Path, results_path: Path, pictures: Path, suite_path: Path, *, rng=None) -> int:
    """Store one pair per prompt that the benchmark drew with both pipelines (same prompt id and seed).

    `results_path` is the JSON of scripts/media/bench_pipeline.py, `pictures` its picture folder, `suite_path` the prompt
    set (rows carry the prompt id, the owner-facing words are the suite's `request`). Returns the number of pairs added.
    """
    rows = json.loads(Path(results_path).read_text(encoding='utf-8')).get('rows', [])
    requests = {p['id']: p['request'] for p in json.loads(Path(suite_path).read_text(encoding='utf-8'))['prompts']}
    old = {(r['id'], r['seed']): r for r in rows if r.get('phase') == '1'}
    new = {(r['id'], r['seed']): r for r in rows if r.get('phase') == '2'}
    added = 0
    for key in sorted(set(old) & set(new)):
        if key[0] not in requests:
            continue
        old_file, new_file = Path(pictures) / old[key]['file'], Path(pictures) / new[key]['file']
        if not (old_file.is_file() and new_file.is_file()):
            continue
        add_pair(home, requests[key[0]], old_file.read_bytes(), new_file.read_bytes(), rng=rng,
                 meta={'source': 'benchmark', 'id': key[0], 'seed': key[1],
                       'seconds': {'old': old[key]['seconds'], 'new': new[key]['seconds']}})
        added += 1
    return added


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Fill the blind A/B test from a benchmark run (bench_pipeline.py).')
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--pictures', required=True, type=Path)
    parser.add_argument('--home', required=True, type=Path, help='the STAR data folder (the one that holds generated-images)')
    parser.add_argument('--suite', type=Path, default=Path('evals/image_quality/prompts.json'), help='default: run from the repository root')
    args = parser.parse_args(argv)
    print(f'{import_benchmark(args.home, args.results, args.pictures, args.suite)} pairs added to {folder(args.home)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
