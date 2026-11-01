"""The map may reuse parsing work, but must still inspect the current workspace."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from star import code_navigation
from star.workspace import Workspace


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    code_navigation.clear_source_cache()
    monkeypatch.delenv('STAR_CODE_SEARCH_CACHE', raising=False)
    monkeypatch.delenv('STAR_CODE_MAP_CACHE', raising=False)
    yield
    code_navigation.clear_source_cache()


def mapped(workspace, query='inventory'):
    return workspace.call('workspace_search', {'query': query, 'mode': 'map'})


@pytest.mark.parametrize('search_flag,map_flag', [(False, False), (True, False), (False, True)])
def test_map_cache_requires_both_explicit_switches(tmp_path, monkeypatch, search_flag, map_flag):
    source = tmp_path / 'inventory.py'
    source.write_text('def inventory():\n    return 1\n', encoding='utf-8')
    reads = []
    original = Path.read_text

    def counted(path, *args, **kwargs):
        if path == source:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', counted)
    if search_flag:
        monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    if map_flag:
        monkeypatch.setenv('STAR_CODE_MAP_CACHE', 'on')
    workspace = Workspace(tmp_path)
    assert mapped(workspace) == mapped(workspace)
    assert len(reads) == 2
    assert code_navigation.source_cache_stats()['entries'] == 0


def test_warm_map_reuses_search_parse_and_preserves_exact_result(tmp_path, monkeypatch):
    source = tmp_path / 'inventory.py'
    source.write_text('class Inventory:\n    def inventory(self):\n        return 1\n', encoding='utf-8')
    workspace = Workspace(tmp_path)
    expected = mapped(workspace)
    reads, parses = [], []
    original_read, original_parse = Path.read_text, code_navigation._py_symbols

    def counted_read(path, *args, **kwargs):
        if path == source:
            reads.append(path)
        return original_read(path, *args, **kwargs)

    def counted_parse(text):
        parses.append(True)
        return original_parse(text)

    monkeypatch.setattr(Path, 'read_text', counted_read)
    monkeypatch.setattr(code_navigation, '_py_symbols', counted_parse)
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setenv('STAR_CODE_MAP_CACHE', 'on')
    workspace.call('workspace_search', {'query': 'inventory', 'mode': 'symbols'})
    for _ in range(3):
        assert mapped(workspace) == expected
    assert len(reads) == len(parses) == 1
    assert code_navigation.source_cache_stats()['entries'] == 1


def test_map_sees_edits_deletions_and_new_files(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setenv('STAR_CODE_MAP_CACHE', 'on')
    source = tmp_path / 'inventory.py'
    source.write_text('def old_name():\n    return 1\n', encoding='utf-8')
    workspace = Workspace(tmp_path)
    assert mapped(workspace, 'old_name')['files'][0]['symbols'][0]['name'] == 'old_name'
    source.write_text('def new_name():\n    return 2\n', encoding='utf-8')
    stamp = source.stat()
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 50_000_000))
    updated = mapped(workspace, 'new_name')
    assert updated['files'][0]['symbols'][0]['name'] == 'new_name'
    source.unlink()
    assert mapped(workspace)['files'] == []
    (tmp_path / 'new_module.py').write_text('def inventory():\n    return 3\n', encoding='utf-8')
    assert mapped(workspace)['files'][0]['file'] == 'new_module.py'


def test_cached_file_replaced_by_external_link_is_not_returned(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setenv('STAR_CODE_MAP_CACHE', 'on')
    root = tmp_path / 'workspace'
    root.mkdir()
    source = root / 'source.py'
    source.write_text('def inventory():\n    return 1\n', encoding='utf-8')
    workspace = Workspace(root)
    assert mapped(workspace)['files']
    source.unlink()
    outside = tmp_path / 'outside.py'
    outside.write_text('def private_inventory():\n    return 2\n', encoding='utf-8')
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip('Symlinks unavailable on this platform')
    assert mapped(workspace)['files'] == []


def test_map_cache_shares_entry_and_byte_limits(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setenv('STAR_CODE_MAP_CACHE', 'on')
    monkeypatch.setattr(code_navigation, '_CACHE_ENTRIES_LIMIT', 2)
    for index in range(8):
        (tmp_path / f'item{index}.py').write_text(f'def inventory_{index}():\n    return {index}\n', encoding='utf-8')
    workspace = Workspace(tmp_path)
    assert len(mapped(workspace)['files']) == 8
    stats = code_navigation.source_cache_stats()
    assert stats['entries'] == 2
    assert 0 < stats['bytes'] <= stats['max_bytes']


def test_map_toggle_revocation_stops_reusing_cached_text(tmp_path, monkeypatch):
    monkeypatch.setenv('STAR_CODE_SEARCH_CACHE', 'on')
    monkeypatch.setenv('STAR_CODE_MAP_CACHE', 'on')
    source = tmp_path / 'inventory.py'
    source.write_text('def inventory():\n    return 1\n', encoding='utf-8')
    workspace = Workspace(tmp_path)
    expected = mapped(workspace)
    monkeypatch.delenv('STAR_CODE_MAP_CACHE')
    original = Path.read_text
    reads = []

    def counted(path, *args, **kwargs):
        if path == source:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', counted)
    assert mapped(workspace) == expected
    assert reads == [source]
