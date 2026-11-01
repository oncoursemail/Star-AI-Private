"""Corpus indexing preserves retrieval behavior, freshness and bounded memory."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import random
import sqlite3
from types import SimpleNamespace

import pytest

from benchmarks.worked_example_retrieval import legacy_rank
from star import worked_examples as examples
from tests.test_worked_examples import TOPICS, export_file, row


@pytest.fixture(autouse=True)
def clean_caches():
    examples._DOCUMENTS.clear()
    examples._compile_corpus.cache_clear()
    yield
    examples._DOCUMENTS.clear()
    examples._compile_corpus.cache_clear()


def test_exact_ranking_parity_on_varied_corpora_and_query_coverage():
    rng = random.Random(20261031)
    vocabulary = [word for topic in TOPICS for word in topic.split()]
    corpus = [examples.Example(
        f"id-{i:04d}", str(i), "practice", " ".join(rng.choices(vocabulary, k=8)),
        "return " + " ".join(rng.choices(("Vector3.new", "CFrame.lookAt", "TweenService:Create", "RunService.Heartbeat"), k=3)),
    ) for i in range(500)]
    queries = [" ".join(rng.choices(vocabulary, k=rng.randint(2, 12))) for _ in range(50)]
    queries += TOPICS + ["", "hello", "unknown only", "script code", "TweenService", "Vector3 new projectile"]
    for count in (1, 20, 500):
        rows = corpus[:count]
        for query in queries:
            for limit in (1, 2):
                assert examples.rank(query, rows, limit=limit) == legacy_rank(query, rows, limit=limit)


def test_reordered_edited_added_and_removed_rows_recompute_exact_scores():
    corpus = [examples.Example("b", "group-b", "", "inventory autosave retries", "return 1"),
              examples.Example("a", "group-a", "", "inventory autosave retries", "return 2"),
              examples.Example("c", "group-c", "", "enemy patrol navigation", "return 3")]
    original = examples.rank("inventory autosave retries", corpus)
    assert [row.id for row, _ in original] == ["a", "b"]
    variants = [list(reversed(corpus)), corpus[:1], corpus[1:],
                corpus + [replace(corpus[0], id="d", response="return 4")],
                [replace(corpus[0], instruction="sprint stamina keyboard"), *corpus[1:]],
                [replace(corpus[0], response="return RunService.Heartbeat"), *corpus[1:]]]
    for rows in variants:
        for query in ("inventory autosave retries", "sprint stamina keyboard", "RunService Heartbeat"):
            assert examples.rank(query, rows) == legacy_rank(query, rows)


def test_identical_text_across_projects_returns_only_current_objects_and_metadata():
    first = examples.Example("first", "first-group", "first-category", "inventory autosave retries", "return 1",
                             ("first provenance",))
    second = replace(first, id="second", group_id="second-group", category="second-category",
                     evidence=("second provenance",))
    examples.rank(first.instruction, [first])
    found = examples.rank(second.instruction, [second])
    assert found and found[0][0] is second
    assert examples._compile_corpus.cache_info().hits == 1
    assert "first" not in repr(found)


def test_select_rechecks_database_edits_deletes_and_project_on_cache_hit(tmp_path):
    home = tmp_path / "home"
    exported = row(1, TOPICS[0])
    examples.import_file(export_file(tmp_path, [exported]), home=home, project="FIRST")
    examples.import_file(export_file(tmp_path, [exported]), home=home, project="SECOND")
    assert examples.select(home, "FIRST", TOPICS[0])[1]
    with sqlite3.connect(home / "worked_examples.sqlite3") as db:
        db.execute("UPDATE worked_examples SET response=? WHERE project=?", ("return 'changed'", "SECOND"))
    text, found = examples.select(home, "SECOND", TOPICS[0])
    assert found and "return 'changed'" in text and found[0].response == "return 'changed'"
    assert "return 'changed'" not in examples.select(home, "FIRST", TOPICS[0])[0]
    with sqlite3.connect(home / "worked_examples.sqlite3") as db:
        db.execute("DELETE FROM worked_examples WHERE project='SECOND'")
    assert examples.select(home, "SECOND", TOPICS[0]) == ("", [])
    assert examples.select(home, "FIRST", TOPICS[0])[1]


def test_select_does_not_reuse_expired_rows_after_warm_cache(tmp_path, monkeypatch):
    home = tmp_path / "home"
    first, second = row(1, TOPICS[0]), row(2, TOPICS[1])
    examples.import_file(export_file(tmp_path, [first, second]), home=home, project="STAR")
    with sqlite3.connect(home / "worked_examples.sqlite3") as db:
        db.execute("CREATE TABLE example_expiry (project TEXT, id TEXT, expires_at TEXT)")
        db.execute("INSERT INTO example_expiry VALUES (?,?,?)", ("STAR", first["id"], "2030-01-02T00:00:00"))
    monkeypatch.setattr(examples, "now", lambda: "2030-01-01T00:00:00")
    assert examples.select(home, "STAR", TOPICS[0])[1]
    monkeypatch.setattr(examples, "now", lambda: "2030-01-03T00:00:00")
    assert examples.select(home, "STAR", TOPICS[0]) == ("", [])
    assert examples.select(home, "STAR", TOPICS[1])[1]


def test_corpus_cache_is_bounded_and_oversized_text_is_not_retained(monkeypatch):
    for i in range(8):
        sample = examples.Example(str(i), str(i), "", "inventory autosave retries", f"return {i}")
        assert examples.rank(sample.instruction, [sample]) == legacy_rank(sample.instruction, [sample])
        assert examples._compile_corpus.cache_info().currsize <= 2
    examples._compile_corpus.cache_clear()
    monkeypatch.setattr(examples, "_CORPUS_CACHE_MAX_CHARS", 30)
    large = examples.Example("large", "large", "", "inventory autosave retries", "-- " + "x" * 1000)
    assert examples.rank(large.instruction, [large]) == legacy_rank(large.instruction, [large])
    assert examples._compile_corpus.cache_info().currsize == 0


def test_threaded_queries_do_not_mix_corpora_or_current_row_identity():
    corpora = [[examples.Example(f"id-{project}-{i}", str(i), str(project),
                                TOPICS[(i + project) % len(TOPICS)], f"return {i + project}")
                for i in range(40)] for project in range(4)]
    jobs = [(corpora[i % len(corpora)], TOPICS[i % len(TOPICS)]) for i in range(120)]
    expected = [legacy_rank(query, rows) for rows, query in jobs]
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(lambda job: examples.rank(job[1], job[0]), jobs))
    assert actual == expected
    for (rows, _query), results in zip(jobs, actual):
        assert all(any(result is row for row in rows) for result, _score in results)


def test_api_extraction_stops_after_fifty_matches(monkeypatch):
    consumed = []

    def finditer(_text):
        for i in range(100_000):
            consumed.append(i)
            yield SimpleNamespace(group=lambda: "Vector3")

    monkeypatch.setattr(examples, "_API", SimpleNamespace(finditer=finditer))
    sample = examples.Example("one", "one", "", "projectile trajectory", "synthetic long response")
    assert examples._document(sample) == Counter(examples.terms(sample.instruction) * 3 + examples.terms("Vector3") * 50)
    assert len(consumed) == 50
