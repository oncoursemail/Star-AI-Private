"""The in-memory term cache of worked-example retrieval changes speed only, never the result."""
from star import worked_examples as examples
from tests.test_worked_examples import TOPICS, export_file, row


def test_cached_terms_give_exactly_the_uncached_ranking(tmp_path):
    home = tmp_path / "home"
    examples.import_file(export_file(tmp_path, [row(i + 1, t) for i, t in enumerate(TOPICS)]), home=home, project="STAR")
    queries = ["Could you implement " + topic + "?" for topic in TOPICS] + ["tween the shop menu", "hello there"]
    examples._DOCUMENTS.clear()
    examples._compile_corpus.cache_clear()
    cold = [examples.select(home, "STAR", q) for q in queries]
    assert len(examples._DOCUMENTS) == len(TOPICS)          # every example tokenized once, kept in memory
    warm = [examples.select(home, "STAR", q) for q in queries]
    assert warm == cold
    assert sum(bool(found) for _, found in warm) >= 20


def test_term_cache_is_capped(monkeypatch):
    monkeypatch.setattr(examples, "_DOCUMENT_CACHE", 3)
    examples._DOCUMENTS.clear()
    for i in range(7):
        examples._document(examples.Example(f"night-school-c{i}", f"c{i}", "", f"Implement thing {i}", "return 1"))
        assert len(examples._DOCUMENTS) <= 3
