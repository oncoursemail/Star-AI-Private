"""Offline regressions for one-pass, bounded multi-query workspace navigation."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from star import code_navigation as navigation
from star import code_search_batch as batch
from star.workspace import Workspace


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    monkeypatch.delenv("STAR_CODE_SEARCH_CACHE", raising=False)
    navigation.clear_source_cache()
    yield
    navigation.clear_source_cache()


def write(root, name: str, text: str):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_mixed_batch_matches_untruncated_single_queries(tmp_path):
    write(tmp_path, "src/inventory.py",
          "class InventoryStore:\n"
          "    def load_items(self, player_id: int):\n"
          "        return 'items ready'\n\n"
          "def save_items(items):\n    return items\n")
    write(tmp_path, "src/Hud.tsx", "export function InventoryHUD() { return null; }\n")
    write(tmp_path, "guide.md", "Inventory data and items ready\n")
    queries = [{"query": "items ready"}, {"query": "load inventory", "mode": "symbols"},
               {"query": "InventoryHUD", "mode": "symbols"}, {"query": "absent"}]
    ws = Workspace(tmp_path)
    actual = batch.batch_search_workspace(ws, queries)
    assert len(actual["results"]) == len(queries)
    for query, result in zip(queries, actual["results"]):
        expected = navigation.search_workspace(ws, query["query"], query.get("mode", "text"))
        assert result["matches"] == expected["matches"]
        assert result["query"] == query["query"]
        assert result["mode"] == query.get("mode", "text")
        assert result["omitted_matches"] == 0
        assert not result["incomplete"]
    assert actual["scanned_files"] == 3
    assert not actual["incomplete"]


def test_each_file_read_once_and_python_parses_shared(tmp_path, monkeypatch):
    paths = [write(tmp_path, f"module{n}.py",
                   f"def calculate_value_{n}():\n    return 'shared needle'\n") for n in range(3)]
    reads, walks, symbol_parses, span_parses = [], [], [], []
    original_read, original_files = Path.read_text, navigation._files
    original_symbols, original_spans = navigation._py_symbols, navigation._py_spans

    def read(path, *args, **kwargs):
        reads.append(path)
        return original_read(path, *args, **kwargs)

    def files(*args, **kwargs):
        walks.append(True)
        yield from original_files(*args, **kwargs)

    def symbols(source):
        symbol_parses.append(True)
        return original_symbols(source)

    def spans(source):
        span_parses.append(True)
        return original_spans(source)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(navigation, "_files", files)
    monkeypatch.setattr(navigation, "_py_symbols", symbols)
    monkeypatch.setattr(navigation, "_py_spans", spans)
    result = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "shared"}, {"query": "needle"},
        {"query": "calculate", "mode": "symbols"}, {"query": "value", "mode": "symbols"},
    ])
    assert sorted(reads) == sorted(paths)
    assert len(walks) == 1
    assert len(symbol_parses) == len(span_parses) == 3
    assert all(len(item["matches"]) == 3 for item in result["results"])


@pytest.mark.parametrize("queries", [
    None, {}, (), [], [{"query": "a"}] * 9, ["needle"], [{}],
    [{"query": "needle", "path": "../secret"}], [{"query": ""}], [{"query": "  "}],
    [{"query": 3}], [{"query": "x" * 301}], [{"query": "needle", "mode": "map"}],
    [{"query": "needle", "mode": []}], [{"query": "🌟", "mode": "symbols"}],
    [{"query": "needle"}, {"query": "\ud800"}],
])
def test_invalid_queries_rejected_before_filesystem_io(tmp_path, monkeypatch, queries):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input reached the filesystem")

    monkeypatch.setattr(navigation, "_files", forbidden)
    with pytest.raises(ValueError):
        batch.batch_search_workspace(Workspace(tmp_path), queries)


def test_shared_budget_counts_full_unicode_json_and_preserves_query_fairness(tmp_path):
    queries = [{"query": f"pattern{n}"} for n in range(8)]
    for n in range(8):
        write(tmp_path, f"unicode{n}.txt", (f"pattern{n} " + "🪐" * 90 + "\n") * 12)
    output = batch.batch_search_workspace(Workspace(tmp_path), queries)
    assert len(json.dumps(output, ensure_ascii=False).encode("utf-8")) <= batch.MAX_BATCH_RESULT_BYTES
    assert output["incomplete"]
    counts = [len(result["matches"]) for result in output["results"]]
    assert min(counts) > 0
    assert max(counts) - min(counts) <= 1
    for result in output["results"]:
        assert len(result["matches"]) + result["omitted_matches"] == 12
        assert result["incomplete"]
        assert not result["limit_reached"]


def test_longest_valid_queries_fit_metadata_budget(tmp_path):
    queries = [{"query": "🌟" * 300} for _ in range(8)]
    result = batch.batch_search_workspace(Workspace(tmp_path), queries)
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= batch.MAX_BATCH_RESULT_BYTES
    assert not result["incomplete"]


def test_budget_metadata_rejection_also_precedes_io(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "MAX_BATCH_RESULT_BYTES", 100)

    def forbidden(*args, **kwargs):
        raise AssertionError("Impossible budget reached the filesystem")

    monkeypatch.setattr(navigation, "_files", forbidden)
    with pytest.raises(ValueError, match="metadata"):
        batch.batch_search_workspace(Workspace(tmp_path), [{"query": "needle"}])


def test_each_text_query_caps_independently_without_starving_later_query(tmp_path, monkeypatch):
    monkeypatch.setattr(navigation, "MAX_RESULTS", 3)
    write(tmp_path, "a.txt", "frequent needle\n" * 20)
    write(tmp_path, "z.txt", "rare target\n")
    report = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "needle"}, {"query": "target"}])
    frequent, rare = report["results"]
    assert len(frequent["matches"]) == 3
    assert frequent["limit_reached"] and frequent["incomplete"]
    assert frequent["omitted_matches"] == 0  # Additional unseen hits are not fabricated counts.
    assert [row["file"] for row in rare["matches"]] == ["z.txt"]
    assert not rare["incomplete"]
    assert report["scanned_files"] == 2


def test_scan_stops_once_all_text_queries_hit_their_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(navigation, "MAX_RESULTS", 2)
    write(tmp_path, "a.txt", "first second\n" * 3)
    write(tmp_path, "z.txt", "unnecessary read\n")
    report = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "first"}, {"query": "second"}])
    assert report["scanned_files"] == 1
    assert all(item["limit_reached"] for item in report["results"])


def test_symbol_rank_considers_late_better_match_after_many_early_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(navigation, "MAX_RESULTS", 3)
    for n in range(16):
        write(tmp_path, f"a{n:02}.py", f"def prefix_target_{n}():\n    pass\n")
    write(tmp_path, "z.py", "def target():\n    pass\n")
    ws = Workspace(tmp_path)
    report = batch.batch_search_workspace(ws, [{"query": "target", "mode": "symbols"}])
    assert report["results"][0]["matches"] == navigation.search_workspace(ws, "target", "symbols")["matches"]
    assert report["results"][0]["matches"][0]["name"] == "target"
    assert report["results"][0]["limit_reached"]
    assert report["scanned_files"] == 17


def test_secret_generated_binary_and_symlink_content_excluded(tmp_path):
    write(tmp_path, "approved.py", "def visible_symbol():\n    return 'approved needle'\n")
    for name in (".env", ".env.local", ".git/config", ".ssh/id_rsa", "secret.key",
                 "secrets.json", "node_modules/vendor.py", "build/generated.py"):
        write(tmp_path, name, "def leaked_symbol():\n    return 'private needle'\n")
    (tmp_path / "binary.txt").write_bytes(b"private needle\x00binary")
    (tmp_path / "invalid.txt").write_bytes(b"private needle\xff")
    outside = tmp_path.parent / "outside-batch-source.py"
    outside.write_text("def leaked_symbol():\n    return 'private needle'\n", encoding="utf-8")
    try:
        (tmp_path / "external.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    report = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "needle"}, {"query": "symbol", "mode": "symbols"}])
    assert all(row["file"] == "approved.py" for result in report["results"] for row in result["matches"])
    serialized = json.dumps(report)
    assert "private needle" not in serialized
    assert "leaked_symbol" not in serialized
    assert report["scan_limited"]  # Invalid UTF-8 was unreadable, not a complete negative search.


def test_credential_literals_redacted_in_text_and_signatures(tmp_path):
    token = "sk-" + "A" * 32
    write(tmp_path, "source.py", f"def connect(api_key='{token}'):\n    return api_key\n")
    result = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "connect"}, {"query": "connect", "mode": "symbols"}, {"query": "return"}])
    assert token not in json.dumps(result)
    assert "[REDACTED]" in json.dumps(result)


def test_non_source_text_does_not_become_symbol_input_in_mixed_batch(tmp_path):
    write(tmp_path, "guide.md", "def fake_symbol():\n    pass\n")
    report = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "fake_symbol"}, {"query": "fake_symbol", "mode": "symbols"}])
    assert report["results"][0]["matches"]
    assert report["results"][1]["matches"] == []


def test_total_source_byte_budget_marks_results_incomplete(tmp_path, monkeypatch):
    first = write(tmp_path, "a.txt", "first needle\n")
    write(tmp_path, "z.txt", "second needle\n")
    monkeypatch.setattr(batch, "MAX_BATCH_SOURCE_BYTES", first.stat().st_size)
    report = batch.batch_search_workspace(Workspace(tmp_path), [{"query": "needle"}])
    assert report["scanned_files"] == 1
    assert report["source_bytes"] == first.stat().st_size
    assert report["scan_limited"] and report["incomplete"]
    assert report["results"][0]["incomplete"]


def test_existing_file_scan_limit_remains_authoritative(tmp_path, monkeypatch):
    monkeypatch.setattr(navigation, "MAX_FILES", 1)
    write(tmp_path, "a.py", "def first_symbol():\n    pass\n")
    write(tmp_path, "z.py", "def last_symbol():\n    pass\n")
    report = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "symbol", "mode": "symbols"}])
    assert report["scanned_files"] == 1
    assert report["scan_limited"] and report["incomplete"]


def test_cache_is_optional_fresh_after_edit_and_absent_after_delete(tmp_path, monkeypatch):
    path = write(tmp_path, "module.py", "def old_symbol():\n    return 1\n")
    ws = Workspace(tmp_path)
    queries = [{"query": "symbol", "mode": "symbols"}, {"query": "return"}]
    uncached = batch.batch_search_workspace(ws, queries)
    assert navigation.source_cache_stats()["entries"] == 0
    monkeypatch.setenv("STAR_CODE_SEARCH_CACHE", "on")
    assert batch.batch_search_workspace(ws, queries) == uncached
    assert batch.batch_search_workspace(ws, queries) == uncached
    assert navigation.source_cache_stats()["entries"] == 1
    path.write_text("def new_symbol():\n    return 2\n", encoding="utf-8")
    # Coarse Windows timestamps can collide for same-sized immediate writes;
    # exercise the documented metadata invalidation rather than a clock race.
    stamp = path.stat()
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 50_000_000))
    edited = batch.batch_search_workspace(ws, queries)
    assert edited["results"][0]["matches"][0]["name"] == "new_symbol"
    assert "old_symbol" not in json.dumps(edited)
    path.unlink()
    deleted = batch.batch_search_workspace(ws, queries)
    assert all(not row["matches"] for row in deleted["results"])
    assert deleted["scanned_files"] == 0


def test_warm_cache_avoids_source_reads_and_is_scoped_to_workspace(tmp_path, monkeypatch):
    first, second = tmp_path / "one", tmp_path / "two"
    write(first, "module.py", "def first_symbol():\n    pass\n")
    write(second, "module.py", "def second_symbol():\n    pass\n")
    monkeypatch.setenv("STAR_CODE_SEARCH_CACHE", "on")
    queries = [{"query": "symbol", "mode": "symbols"}]
    one = Workspace(first)
    batch.batch_search_workspace(one, queries)
    original = Path.read_text
    reads = []

    def record(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", record)
    warm = batch.batch_search_workspace(one, queries)
    assert not reads
    other = batch.batch_search_workspace(Workspace(second), queries)
    assert reads == [second / "module.py"]
    assert warm["results"][0]["matches"][0]["name"] == "first_symbol"
    assert other["results"][0]["matches"][0]["name"] == "second_symbol"


def test_source_is_never_executed_and_query_input_is_not_mutated(tmp_path):
    write(tmp_path, "source.py", "raise RuntimeError('must not execute')\ndef target():\n    pass\n")
    queries = [{"query": "target", "mode": "symbols"}]
    before = json.dumps(queries)
    report = batch.batch_search_workspace(Workspace(tmp_path), queries)
    assert report["results"][0]["matches"][0]["name"] == "target"
    assert json.dumps(queries) == before


def test_empty_workspace_reports_complete_empty_results(tmp_path):
    result = batch.batch_search_workspace(Workspace(tmp_path), [
        {"query": "needle"}, {"query": "symbol", "mode": "symbols"}])
    assert result["scanned_files"] == result["source_bytes"] == 0
    assert not result["incomplete"]
    assert all(not row["matches"] for row in result["results"])
