"""A/B benchmark of STAR's image engines on a fixed prompt set, judged by STAR's own blind vision judge.

    STAR_EVAL_SERVER=http://<brain>:8080/v1 python scripts/media/bench_images.py --out results.json --pictures <folder>

Needs ComfyUI on 127.0.0.1 and the brain's key in ~/.star/server_api_key (read, never printed). For each engine it
draws every prompt with every seed (the first picture is a warm-up, timed separately), judges blind
(star/image_judge.py) and prints anatomy pass rate, exact-text rate and seconds per image. Resumable: finished
rows are skipped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from star import image_judge, image_prompt, image_quality  # noqa: E402
from star.comfy import ENGINES, ComfyClient, klein_text_to_image, zimage_text_to_image  # noqa: E402
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


def summarize(results: dict) -> None:
    for engine in ENGINES:
        rows = [r for r in results['rows'] if r['engine'] == engine]
        judged = [r for r in rows if r.get('judge', {}).get('judged')]
        if not rows:
            continue
        anatomy = [r for r in judged if r['category'] != 'text']
        text = [r for r in judged if r['category'] == 'text']
        print(engine, 'anatomy pass', sum(r['judge']['anatomy_ok'] for r in anatomy), '/', len(anatomy),
              '| text exact', round(sum((r['text_exact'] or 0) for r in text) / max(1, len(text)), 2),
              '| s/image', round(sum(r['seconds'] for r in rows) / len(rows), 1), flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--pictures', required=True, type=Path)
    parser.add_argument('--engines', default='klein,zimage')
    parser.add_argument('--size', type=int, default=1024)
    parser.add_argument('--rejudge', action='store_true', help='judge the saved pictures again (judge rules changed); no drawing')
    args = parser.parse_args(argv)
    suite = json.loads(SUITE.read_text(encoding='utf-8'))
    settings = settings_for_brain()
    args.pictures.mkdir(parents=True, exist_ok=True)
    results = (json.loads(args.out.read_text(encoding='utf-8')) if args.out.is_file()
               else {'rows': [], 'warmup': {}, 'prompts': {}})
    done = {(r['engine'], r['id'], r['seed']) for r in results['rows']}
    old = {(r['engine'], r['id'], r['seed']): r for r in results['rows']}
    if args.rejudge:
        again = set(args.engines.split(','))
        results['rows'] = [r for r in results['rows'] if r['engine'] not in again]
        done = {k for k in done if k[0] not in again}
    for entry in suite['prompts']:      # the rewriter runs once per request, so both engines get identical words
        if entry['id'] in results['prompts']:
            continue
        if 'inline' in entry:
            results['prompts'][entry['id']] = {'prompt': entry['inline'], 'checks': []}
        else:
            plan = image_prompt.rewrite(settings, entry['request'])
            if not plan.rewritten:       # a benchmark of raw prompts would be a different benchmark: ask again, then stop
                plan = image_prompt.rewrite(settings, entry['request'])
            if not plan.rewritten:
                raise SystemExit(f"the rewriter failed for {entry['id']}: {plan.notes}")
            results['prompts'][entry['id']] = {'prompt': plan.prompt, 'checks': list(plan.checks),
                                               'rewritten': plan.rewritten}
    args.out.write_text(json.dumps(results, indent=1), encoding='utf-8')
    side = args.size
    with ComfyClient(port=8188, timeout=60.0) as comfy, concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        for engine in args.engines.split(','):
            if not args.rejudge and comfy.missing_models(engine):
                print('engine not installed:', engine, flush=True)
                continue
            build = zimage_text_to_image if engine == 'zimage' else klein_text_to_image
            if engine not in results['warmup'] and not args.rejudge:
                started = time.monotonic()
                comfy.run(build('a red apple on a table', side, side, 1), timeout_seconds=1200)
                results['warmup'][engine] = round(time.monotonic() - started, 1)
                print(engine, 'warm-up', results['warmup'][engine], flush=True)
            pending = []
            for entry in suite['prompts']:
                for seed in suite['seeds']:
                    if (engine, entry['id'], seed) in done:
                        continue
                    info = results['prompts'][entry['id']]
                    path = args.pictures / f"{engine}-{entry['id']}-{seed}.png"
                    if args.rejudge:
                        if (engine, entry['id'], seed) not in old:
                            continue
                        png, seconds = path.read_bytes(), old[(engine, entry['id'], seed)]['seconds']
                    else:
                        started = time.monotonic()
                        png = comfy.run(build(info['prompt'], side, side, seed), timeout_seconds=900)[0]
                        seconds = round(time.monotonic() - started, 1)
                        path.write_bytes(png)
                    # text is read at 1024 px; anatomy at the pipeline's 768
                    image_quality.JUDGE_SIDE = 1024 if entry['category'] == 'text' else 768
                    judged = image_quality.judge_copy(png, args.pictures, f"{engine}-{entry['id']}-{seed}-judge.jpg")
                    row = {'engine': engine, 'id': entry['id'], 'category': entry['category'], 'seed': seed,
                           'seconds': seconds, 'file': path.name, 'expected_text': entry.get('text', [])}

                    def work(row=row, judged=judged, info=info):
                        try:
                            verdict = image_judge.judge(settings, judged, tuple(info['checks']), expected_text=None)
                            row['judge'] = verdict.as_note()
                            row['text_exact'] = (image_judge.text_matches(row['expected_text'], verdict.text_read)
                                                 if row['expected_text'] else None)
                        except Exception as exc:
                            row['judge'] = {'judged': False, 'error': type(exc).__name__}
                        return row
                    pending.append(pool.submit(work))
                    print(engine, entry['id'], seed, seconds, 's', flush=True)
            for future in pending:
                results['rows'].append(future.result())
            args.out.write_text(json.dumps(results, indent=1), encoding='utf-8')
    summarize(results)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
