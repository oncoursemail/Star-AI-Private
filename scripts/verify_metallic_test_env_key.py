"""Retained regression probe for configured environment values in test-cache keys."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'metallic'))

from metallic.cache import Cache  # noqa: E402
from metallic.config import Config  # noqa: E402
from metallic.impact import Graph, test_key  # noqa: E402


def run() -> None:
    from tempfile import TemporaryDirectory

    graph = Graph(files={'tests/example.py': 'test-blob', 'src.py': 'source-blob'},
                  deps={'tests/example.py': {'src.py'}}, rdeps={}, tests=['tests/example.py'])

    def key(env):
        return test_key(graph, 'tests/example.py', Config(test_cmd=['python', '-m', 'pytest'], test_env=env), 'toolchain')

    off, on = key({'FEATURE': '0'}), key({'FEATURE': '1'})
    assert off != on, 'changed environment values must invalidate cached test results'
    assert key({'A': '1', 'B': '2'}) == key({'B': '2', 'A': '1'}), 'mapping order is immaterial'
    assert key({}) != key({'FEATURE': ''}), 'an explicit empty variable differs from no configured variable'
    assert key({'FEATURE': '1'}) == on, 'identical explicit settings retain cache reuse'
    assert key({'FEATURE': '1', 'OTHER': 'x'}) != on, 'additional variables invalidate the key'
    assert key({'FEATURE': '1\n2'}) != key({'FEATURE': '12'}), 'value boundaries remain significant'
    with TemporaryDirectory() as folder:
        cache = Cache(Path(folder))
        cache.put(off, {'status': 'pass'})
        assert cache.get(on) is None, 'a pass under FEATURE=0 must not be reused under FEATURE=1'
        restored = Cache(Path(folder)).get(off)
        assert restored is not None and restored['status'] == 'pass', 'same-environment reuse survives restart'
    print('8 test-environment cache-key checks passed; no commands or test fixtures executed')


if __name__ == '__main__':
    run()
