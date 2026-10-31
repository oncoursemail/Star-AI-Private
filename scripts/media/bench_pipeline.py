"""End-to-end benchmark of STAR's image pipeline on the fixed prompt set (evals/image_quality/prompts.json).

    STAR_EVAL_SERVER=http://<brain>:8080/v1 python scripts/media/bench_pipeline.py --phase 2 --out r2.json --pictures <folder>

Needs ComfyUI on 127.0.0.1 and the brain's key in ~/.star/server_api_key (read, never printed). Every picture goes through
`star.image_quality.generate_best` from the request words, with a cold rewriter cache, so the seconds are the whole thing the
owner waits for. `--phase 1` runs the phase-1 pipeline (`legacy=True`: 8 steps, every draft, no repair), `--phase 2` the
current one. After the runs, every final picture is judged again with the SAME blind judge (768 px, same questions) and its
text is read at 1024 px, so the two phases are compared by one yardstick. Resumable: finished rows are skipped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from star import image_judge, image_prompt, image_quality  # noqa: E402
from star.desktop_core import Settings  # noqa: E402

SUITE = Path(__file__).resolve().parents[2] / 'evals' / 'image_quality' / 'prompts.json'


def settings_for_brain() -> Settings:
    key = (Path.home() / '.star' / 'server_api_key').read_text(encoding='utf-8').strip()
    os.environ['STAR_SERVER_API_KEY'] = key
    server = os.environ.get('STAR_EVAL_SERVER', '').rstrip('/')
    if not server:
        raise SystemExit('Set STAR_EVAL_SERVER to the brain address (http://<host>:8080/v1)')
    return Settings(provider='star_server', server_endpoint=server, model='star-fast', fast_model='star-fast',
                    vision_model='star-fast', project='STAR-eval', allow_cgnat=True)


def final_judge(settings, png_path: Path, plan_checks, expected_text, scratch: Path) -> dict:
    """One yardstick for both phases: the blind judge at 768 px (text: 1024 px), the plan's own yes/no questions."""
    side = 1024 if expected_text else 768
    copy = image_quality.judge_copy(png_path.read_bytes(), scratch, png_path.stem + '-final.jpg', side)
    verdict = image_judge.judge(settings, copy, tuple(plan_checks), expected_text=None)
    row = verdict.as_note()
    row['text_exact'] = image_judge.exact_text(expected_text, verdict.text_read) if expected_text else None
    return row


def summarize(results: dict, phase: str) -> dict:
    rows = [r for r in results['rows'] if r['phase'] == phase and r.get('final')]
    if not rows:
        return {}
    anatomy = [r for r in rows if r['category'] != 'text']
    text = [r for r in rows if r['category'] == 'text']
    seconds = [r['seconds'] for r in rows]
    return {'pictures': len(rows),
            'anatomy_pass': f"{sum(r['final']['anatomy_ok'] for r in anatomy)}/{len(anatomy)}",
            'prompt_match_yes': f"{sum(r['final']['checks_yes'] for r in anatomy)}/{sum(r['final']['checks_total'] for r in anatomy)}",
            'exact_text': f"{sum(bool(r['final']['text_exact']) for r in text)}/{len(text)}",
            'seconds_mean': round(statistics.mean(seconds), 1), 'seconds_median': round(statistics.median(seconds), 1),
            'seconds_max': round(max(seconds), 1),
            'early_stop': sum(bool(r['timing'].get('early_stop')) for r in rows),
            'repairs': sum(sum(d['kind'] == 'repair' for d in r['drafts']) for r in rows),
            'text_fallback': sum(bool(r['timing'].get('text_fallback')) for r in rows),
            'pictures_drawn_mean': round(statistics.mean(r['timing']['pictures_drawn'] for r in rows), 2),
            'rewrite_s_mean': round(statistics.mean(r['timing']['rewrite_s'] for r in rows), 1)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--phase', choices=('1', '2'), required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--pictures', required=True, type=Path)
    parser.add_argument('--seeds', default='', help='comma list; default: the suite seeds')
    parser.add_argument('--only', default='', help='comma list of prompt ids')
    args = parser.parse_args(argv)
    suite = json.loads(SUITE.read_text(encoding='utf-8'))
    seeds = [int(s) for s in args.seeds.split(',')] if args.seeds else suite['seeds']
    only = set(filter(None, args.only.split(',')))
    settings = settings_for_brain()
    args.pictures.mkdir(parents=True, exist_ok=True)
    home = args.pictures / 'home'
    home.mkdir(exist_ok=True)
    results = json.loads(args.out.read_text(encoding='utf-8')) if args.out.is_file() else {'rows': []}
    done = {(r['phase'], r['id'], r['seed']) for r in results['rows']}
    from star.image_quality import generate_best
    for entry in suite['prompts']:
        if only and entry['id'] not in only:
            continue
        for seed in seeds:
            if (args.phase, entry['id'], seed) in done:
                continue
            image_prompt._CACHE.clear()          # every run pays its own rewrite: the seconds are end to end
            started = time.monotonic()
            made = generate_best(settings, entry['request'], home, seed=seed, legacy=args.phase == '1',
                                 on_progress=lambda m: None)
            seconds = round(time.monotonic() - started, 1)
            target = args.pictures / f"p{args.phase}-{entry['id']}-{seed}.png"
            target.write_bytes(Path(made['path']).read_bytes())
            note = made['note']
            row = {'phase': args.phase, 'id': entry['id'], 'category': entry['category'], 'seed': seed, 'seconds': seconds,
                   'file': target.name, 'answer': made['answer'], 'timing': note['timing'], 'drafts': note['drafts'],
                   'chosen': note['chosen'], 'checks': note['plan']['checks'], 'overlays': note['plan']['overlays'],
                   'expected_text': entry.get('text', [])}
            results['rows'].append(row)
            args.out.write_text(json.dumps(results, indent=1), encoding='utf-8')
            print(args.phase, entry['id'], seed, seconds, 's', note['timing'].get('early_stop'), flush=True)
    # one yardstick for every final picture (both phases), judged two at a time
    scratch = args.pictures / 'judge'
    scratch.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {}
        for row in results['rows']:
            if 'final' not in row:
                futures[pool.submit(final_judge, settings, args.pictures / row['file'], row['checks'],
                                    row['expected_text'], scratch)] = row
        for future, row in futures.items():
            try:
                row['final'] = future.result()
            except Exception as exc:
                row['final'] = {'judged': False, 'anatomy_ok': False, 'checks_yes': 0, 'checks_total': 0,
                                'text_exact': None, 'error': type(exc).__name__}
    results['summary'] = {p: summarize(results, p) for p in ('1', '2')}
    args.out.write_text(json.dumps(results, indent=1), encoding='utf-8')
    print(json.dumps(results['summary'], indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
