"""Offline paired measurements of deterministic context discovery, with exact parity.

Run: python -m benchmarks.freebuff_context --files 300 --repeats 9
Creates synthetic files in a temporary directory; never runs workspace code or
models. Timings include the real Workspace.call schema validation/dispatch path.
No claim about inference speed, answer quality, Windows, or GPU performance.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
from contextlib import contextmanager
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from star import code_navigation
from star.workspace import Workspace


@contextmanager
def flags(**values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def summary(samples):
    ordered = sorted(samples)
    return {'median_ms': round(median(samples), 4),
            'p95_ms': round(ordered[math.ceil(len(ordered) * .95) - 1], 4),
            'samples_ms': [round(value, 4) for value in samples]}


def run(files=300, repeats=9):
    if type(files) is not int or not 40 <= files <= 1200:
        raise ValueError('files must be 40..1200')
    if type(repeats) is not int or not 5 <= repeats <= 30:
        raise ValueError('repeats must be 5..30')
    samples = {name: [] for name in ('single_uncached', 'batch_uncached', 'single_warm',
                                     'batch_warm', 'map_uncached', 'map_warm')}
    with TemporaryDirectory(prefix='litha-context-bench-') as folder:
        root = Path(folder)
        for index in range(files):
            content = (f'class Inventory{index:04d}:\n'
                       + ''.join(f'    def action_{index:04d}_{method:02d}(self, player_id):\n'
                                 f'        return player_id + {method}\n' for method in range(14))
                       + f'\ndef load_inventory_{index:04d}():\n'
                       + f'    return Inventory{index:04d}()\n'
                       + f'# event_route_{index:04d}\n')
            (root / f'component_{index:04d}.py').write_text(content, encoding='utf-8')
        workspace = Workspace(root)
        positions = [index * (files - 1) // 7 for index in range(8)]
        queries = [{'query': (f'load_inventory_{position:04d}' if index % 2 == 0
                              else f'event_route_{position:04d}'),
                    'mode': 'symbols' if index % 2 == 0 else 'text'}
                   for index, position in enumerate(positions)]

        def single():
            return [workspace.call('workspace_search', query) for query in queries]

        def batch():
            return workspace.call('workspace_search_batch', {'queries': queries})

        def mapped():
            return workspace.call('workspace_search', {'query': 'Inventory', 'mode': 'map'})

        with flags(STAR_CODE_SEARCH_BATCH='on', STAR_CODE_SEARCH_CACHE='off', STAR_CODE_MAP_CACHE='off'):
            expected = single()
            expected_map = mapped()
            assert all(not result['incomplete'] for result in expected)
            expected_matches = [result['matches'] for result in expected]

            def check_batch(result):
                assert [item['matches'] for item in result['results']] == expected_matches
                assert not result['incomplete']

            check_batch(batch())
            # Count real source reads independently of timings. The synthetic
            # files are the only inputs; schema/library file reads are excluded.
            original_read = Path.read_text
            read_counts = {}
            try:
                for label, operation in (('single_uncached', single), ('batch_uncached', batch)):
                    counter = [0]

                    def counted(path, *args, **kwargs):
                        if path.parent == root:
                            counter[0] += 1
                        return original_read(path, *args, **kwargs)

                    Path.read_text = counted
                    operation()
                    read_counts[label] = counter[0]
            finally:
                Path.read_text = original_read

            # Alternate measured order to reduce persistent warm-page/order bias.
            for repeat in range(repeats):
                for warmed in (False, True):
                    cache = 'on' if warmed else 'off'
                    with flags(STAR_CODE_SEARCH_CACHE=cache, STAR_CODE_MAP_CACHE=cache):
                        code_navigation.clear_source_cache()
                        if warmed:
                            batch()
                            mapped()
                        operations = [('single', single), ('batch', batch), ('map', mapped)]
                        if repeat % 2:
                            operations.reverse()
                        for label, operation in operations:
                            start = perf_counter()
                            result = operation()
                            elapsed = (perf_counter() - start) * 1000
                            samples[f'{label}_{"warm" if warmed else "uncached"}'].append(elapsed)
                            if label == 'single':
                                assert result == expected
                            elif label == 'batch':
                                check_batch(result)
                            else:
                                assert result == expected_map
            cache_stats = code_navigation.source_cache_stats()
            output = batch()
            source_bytes = sum(path.stat().st_size for path in root.iterdir())
        code_navigation.clear_source_cache()

    timings = {key: summary(value) for key, value in samples.items()}
    return {
        'schema_version': 1,
        'workload': {'files': files, 'source_bytes': source_bytes, 'queries_per_batch': len(queries),
                     'repeats': repeats, 'query_modes': [query['mode'] for query in queries]},
        'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                        'machine': platform.machine()},
        'exact_result_parity': True, 'source_reads': read_counts,
        'batch_result_bytes': len(json.dumps(output, ensure_ascii=False).encode('utf-8')),
        'timings': timings,
        'ratios': {
            'uncached_batch_speedup': round(median(samples['single_uncached']) / median(samples['batch_uncached']), 4),
            'warm_batch_speedup': round(median(samples['single_warm']) / median(samples['batch_warm']), 4),
            'map_cache_speedup': round(median(samples['map_uncached']) / median(samples['map_warm']), 4),
        },
        'shared_cache': cache_stats,
        'limitations': [
            'Synthetic sparse eight-query discovery workload; not arbitrary query distributions.',
            'Uncached means the application source cache is disabled, not cold filesystem pages.',
            'Map scan uses its existing 320-file cap when the generated project exceeds it.',
            'Warm-cache results assume unchanged files already resident in the bounded cache.',
            'No inference, live task-success, Windows package, GPU, RSS or production measurement.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files', type=int, default=300)
    parser.add_argument('--repeats', type=int, default=9)
    args = parser.parse_args()
    print(json.dumps(run(args.files, args.repeats), indent=2))


if __name__ == '__main__':
    main()
