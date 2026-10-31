"""Opt-in workspace source-cache security, freshness and equivalence tests."""
from __future__ import annotations

import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from star import code_navigation
from star.workspace import Workspace


@pytest.fixture(autouse=True)
def isolate_cache(monkeypatch):
    code_navigation.clear_source_cache()
    monkeypatch.delenv('STAR_CODE_SEARCH_CACHE', raising=False)
    yield
    code_navigation.clear_source_cache()


def test_cache_default_off_and_explicit_opt_in(tmp_path, monkeypatch):
    file = tmp_path / 'round.py'
    file.write_text('def run_round():\n    pass\n', encoding='utf-8')
    original = Path.read_text
    reads = []

    def counted(self, *a, **kw):
        if self == file:
            reads.append(True)
        return original(self, *a, **kw)

    monkeypatch.setattr(Path, 'read_text', counted)
    workspace = Workspace(tmp_path)
    for _ in range(2):
        assert workspace.call('workspace_search', {'query': 'run_round', 'mode': 'symbols'})['matches']
    assert len(reads) == 2
    assert code_navigation.source_cache_stats()['entries'] == 0

    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    for _ in range(3):
        assert workspace.call('workspace_search', {'query': 'run_round', 'mode': 'symbols'})['matches']
    assert len(reads) == 3
    assert code_navigation.source_cache_stats()['entries'] == 1


def test_same_size_edit_invalidates_cache_and_old_search_disappears(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    file = tmp_path / 'logic.py'
    file.write_text('def start_wave():\n    pass\n')
    workspace = Workspace(tmp_path)
    before = workspace.call('workspace_search', {'query': 'start_wave', 'mode': 'symbols'})
    assert before['matches'][0]['name'] == 'start_wave'
    file.write_text('def clear_wave():\n    pass\n')  # same byte size
    # A real edit lands at a later time; two writes inside one filesystem clock tick (Windows: ~16 ms) share an
    # mtime and a size, which the cache cannot tell apart. Make the later time explicit so the test is not a race.
    stamp = file.stat()
    os.utime(file, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 50_000_000))
    assert workspace.call('workspace_search', {'query': 'start_wave', 'mode': 'symbols'})['matches'] == []
    updated = workspace.call('workspace_search', {'query': 'clear_wave', 'mode': 'symbols'})
    assert updated['matches'][0]['name'] == 'clear_wave'
    assert code_navigation.source_cache_stats()['entries'] == 1


def test_text_search_equivalence_when_cached(tmp_path, monkeypatch):
    (tmp_path / 'design.md').write_text('UNIQUE_UI_HUD\nsecond unique_ui_hud\n')
    (tmp_path / 'game.luau').write_text('local function unique_ui_hud()\nend\n')
    workspace = Workspace(tmp_path)
    original = workspace.call('workspace_search', {'query': 'unique_ui_hud'})
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    cached = workspace.call('workspace_search', {'query': 'unique_ui_hud'})
    warm = workspace.call('workspace_search', {'query': 'unique_ui_hud'})
    assert original == cached == warm


def test_cache_entry_and_byte_bounds(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setattr(code_navigation, '_CACHE_ENTRIES_LIMIT', 2)
    for i in range(5):
        (tmp_path / f'file{i}.py').write_text(f'def code_{i}(): pass\n')
    workspace = Workspace(tmp_path)
    workspace.call('workspace_search', {'query': 'code_', 'mode': 'symbols'})
    stats = code_navigation.source_cache_stats()
    assert stats['entries'] == 2
    assert 0 < stats['bytes'] < stats['max_bytes']


def test_oversized_file_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setattr(code_navigation, '_CACHE_FILE_LIMIT', 12)
    (tmp_path / 'large.py').write_text('def hello_long_file():\n    return 1\n')
    assert Workspace(tmp_path).call('workspace_search', {'query': 'hello_long_file'})['matches']
    assert code_navigation.source_cache_stats()['entries'] == 0


def test_changed_target_symlink_does_not_return_cached_content(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    work = tmp_path / 'work'
    work.mkdir()
    source = work / 'file.py'
    source.write_text('def safe_name(): pass\n')
    workspace = Workspace(work)
    assert workspace.call('workspace_search', {'query': 'safe_name'})['matches']
    outside = tmp_path / 'outside.py'
    outside.write_text('def very_secret(): pass\n')
    source.unlink()
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip('Filesystem does not permit symlinks')
    assert workspace.call('workspace_search', {'query': 'safe_name'})['matches'] == []
    assert workspace.call('workspace_search', {'query': 'very_secret'})['matches'] == []


def test_different_workspace_does_not_receive_cached_source(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    first = tmp_path / 'one'
    second = tmp_path / 'two'
    first.mkdir()
    second.mkdir()
    (first / 'main.py').write_text('def private_symbol(): pass\n')
    (second / 'main.py').write_text('def public_symbol(): pass\n')
    assert Workspace(first).call('workspace_search', {'query': 'private_symbol'})['matches']
    assert not Workspace(second).call('workspace_search', {'query': 'private_symbol'})['matches']


def test_threads_agree_without_crossing_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    for i in range(20):
        (tmp_path / f'mod{i}.py').write_text(f'def worker_{i}(): return {i}\n')
    workspace = Workspace(tmp_path)

    def search(_):
        return workspace.call('workspace_search', {'query': 'worker', 'mode': 'symbols'})

    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(search, range(8)))
    assert outputs and all(row == outputs[0] for row in outputs)
    stats = code_navigation.source_cache_stats()
    assert 0 < stats['entries'] <= stats['max_entries']


def test_python_symbols_parsed_only_once_until_source_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    source = tmp_path / 'fast.py'
    source.write_text('def old_state():\n    return 1\n', encoding='utf-8')
    original = code_navigation._py_symbols
    calls = []

    def checked(text):
        calls.append(True)
        return original(text)

    monkeypatch.setattr(code_navigation, '_py_symbols', checked)
    workspace = Workspace(tmp_path)
    for _ in range(3):
        assert workspace.call('workspace_search', {'query': 'old_state', 'mode': 'symbols'})['matches']
    assert len(calls) == 1

    source.write_text('def new_state():\n    return 2\n', encoding='utf-8')
    assert workspace.call('workspace_search', {'query': 'new_state', 'mode': 'symbols'})['matches']
    assert len(calls) == 2
    assert workspace.call('workspace_search', {'query': 'old_state', 'mode': 'symbols'})['matches'] == []
