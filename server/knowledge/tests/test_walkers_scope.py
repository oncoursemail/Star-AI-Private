"""Knowledge school (2026-10-18): generic walkers (RST, CNXML, fetched JSONL pages) and the search scope that keeps
Roblox questions on the Roblox documentation. No network, no model: the embedding step is never called.

    python -m pytest -q server/knowledge/tests/test_walkers_scope.py
"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starkb import search, store, walkers  # noqa: E402
from starkb.fetch_pages import extract_to_markdown, wikitext_to_markdown  # noqa: E402

RST = """.. _doc_nodes_and_scenes:

Nodes and scenes
================

.. note:: This page assumes :ref:`the previous one <doc_introduction>`.

In Godot, a **scene** is a tree of ``Node`` objects. See :ref:`doc_scene_tree`.

Creating a node
---------------

.. image:: img/nodes.png

.. code-block:: gdscript

    var node = Node.new()
    add_child(node)

.. toctree::
   :maxdepth: 1

   a
   b

A literal follows::

    print("hi")

Done.
"""

CNXML = """<document xmlns="http://cnx.rice.edu/cnxml" xmlns:m="http://www.w3.org/1998/Math/MathML" id="m1">
<title>Newton's Second Law</title>
<content>
<section id="s1"><title>Force and acceleration</title>
<para id="p1">The net force on a body equals its mass times its acceleration: <m:math><m:mi>F</m:mi><m:mo>=</m:mo><m:mi>m</m:mi><m:mi>a</m:mi></m:math>.</para>
<list id="l1"><item>mass in kilograms</item><item>acceleration in metres per second squared</item></list>
<exercise id="e1"><problem id="pr1"><para id="p2">A 2 kg mass accelerates at 3 m/s^2. Find the force.</para></problem>
<solution id="so1"><para id="p3">6 N.</para></solution></exercise>
</section>
</content>
</document>"""


def test_rst_becomes_markdown_with_headings_code_and_notes():
    title, body = walkers.rst_to_markdown(RST)
    assert title == "Nodes and scenes"
    assert "# Nodes and scenes" in body and "## Creating a node" in body
    assert "```gdscript\nvar node = Node.new()\nadd_child(node)\n```" in body
    assert "**Note:**" in body and "the previous one" in body and "doc_introduction" not in body
    assert "`Node`" in body and "img/nodes.png" not in body and "maxdepth" not in body
    assert "```\nprint(\"hi\")\n```" in body and "A literal follows:" in body
    assert "_doc_nodes_and_scenes" not in body


def test_rst_tree_yields_docs_within_the_included_prefixes(tmp_path):
    (tmp_path / "tutorials").mkdir()
    (tmp_path / "classes").mkdir()
    (tmp_path / "tutorials" / "nodes.rst").write_text(RST, encoding="utf-8")
    (tmp_path / "classes" / "class_node.rst").write_text("Node\n====\n\nThe base class.\n" * 10, encoding="utf-8")
    docs = list(walkers.rst_tree(tmp_path, "https://docs.example/en/latest", include=["tutorials/"], url_suffix=".html"))
    assert [d.path for d in docs] == ["tutorials/nodes.rst"]
    assert docs[0].url == "https://docs.example/en/latest/tutorials/nodes.html"
    assert docs[0].title == "Nodes and scenes" and docs[0].chunks
    assert any("add_child(node)" in c.text for c in docs[0].chunks)


def test_cnxml_module_becomes_text_with_math_lists_and_exercises(tmp_path):
    title, body = walkers.cnxml_to_markdown(CNXML)
    assert title == "Newton's Second Law"
    assert "Force and acceleration" in body and "F = m a" in body
    assert "- mass in kilograms" in body and "**Exercise:**" in body and "6 N." in body
    (tmp_path / "modules" / "m1").mkdir(parents=True)
    (tmp_path / "modules" / "m1" / "index.cnxml").write_text(CNXML, encoding="utf-8")
    (tmp_path / "collections").mkdir()
    (tmp_path / "collections" / "book.collection.xml").write_text(
        '<col:collection xmlns:col="http://cnx.rice.edu/collxml" xmlns:md="http://cnx.rice.edu/mdml">'
        '<col:metadata><md:title>University Physics</md:title></col:metadata><col:content>'
        '<col:subcollection><md:title>Dynamics</md:title><col:content><col:module document="m1"/></col:content>'
        '</col:subcollection></col:content></col:collection>', encoding="utf-8")
    docs = list(walkers.cnxml_tree(tmp_path, "https://github.com/x/y/blob/abc"))
    assert docs[0].title == "University Physics > Dynamics > Newton's Second Law"
    assert docs[0].url == "https://github.com/x/y/blob/abc/modules/m1/index.cnxml"


def test_jsonl_pages_leave_out_excluded_titles(tmp_path):
    body = "A passage long enough to be kept as a chunk of the index. " * 3
    rows = [{"id": i, "title": t, "url": "u/" + t, "text": body} for i, t in enumerate(
        ["Potassium", "March 3", "1920s", "List of lakes", "Eagle (disambiguation)", "2006 Winter Olympics", "Game design"])]
    (tmp_path / "simplewiki-001.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    source = {"name": "simplewiki", "walker": "jsonl-pages", "exclude_titles": [
        r"^(January|March)( \d{1,2})?$", r"^\d{1,4}s?$", r"^List of ", r"\(disambiguation\)$", r"^\d{4} .*\bOlympics\b"]}
    titles = [d.title for d in walkers.walker_for(source)(tmp_path, "https://simple.wikipedia.org/wiki")]
    assert titles == ["Potassium", "Game design"]


def test_jsonl_pages_keep_their_own_url_and_skip_short_rows(tmp_path):
    rows = [{"id": 7, "title": "Level design", "url": "https://en.wikipedia.org/wiki/Level_design",
             "text": "# Level design\n\nLevel design is the creation of levels. " * 8},
            {"id": 8, "title": "Stub", "url": "https://en.wikipedia.org/wiki/Stub", "text": "short"}]
    (tmp_path / "game-design.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    docs = list(walkers.jsonl_pages(tmp_path, "https://en.wikipedia.org/wiki"))
    assert len(docs) == 1 and docs[0].url.endswith("/Level_design") and docs[0].path == "game-design.jsonl#7"
    assert docs[0].title == "Level design"


def test_wikipedia_text_conversions_drop_reference_sections():
    text = extract_to_markdown("Intro.\n\n== History ==\nOld.\n\n=== Early ===\nVery old.\n\n== References ==\n1. x\n")
    assert text == "Intro.\n\n## History\nOld.\n\n### Early\nVery old."
    wiki = wikitext_to_markdown("{{Infobox|a=b}}'''Bold''' [[link|shown]] and [[plain]] <ref>r</ref>.\n== See also ==\n* [[x]]\n== Use ==\n* one\n")
    assert wiki == "Bold shown and plain .\n\n## Use\n- one"


def _index(tmp_path: Path) -> Path:
    """A tiny mixed index: a Roblox page and an encyclopaedia page, built through the generic walker path."""
    sources = tmp_path / "sources"
    (sources / "wiki").mkdir(parents=True)
    (sources / "wiki" / "SNAPSHOT.json").write_text('{"commit": "wiki-1", "commit_date": "2026-10-18"}', encoding="utf-8")
    (sources / "wiki" / "p.jsonl").write_text(json.dumps({
        "id": 1, "title": "Tween", "url": "https://en.wikipedia.org/wiki/Inbetweening",
        "text": "Inbetweening or tweening is the process of generating intermediate frames between two keyframes. " * 6}),
        encoding="utf-8")
    manifest = tmp_path / "corpora.json"
    manifest.write_text(json.dumps({"sources": [
        {"name": "creator-docs", "group": "roblox", "repo": "r.git", "branch": "main", "licence": "l", "attribution": "a",
         "content_root": "", "public_base": "https://create.roblox.com/docs"},
        {"name": "wiki", "group": "general", "kind": "files", "walker": "jsonl-pages", "repo": "https://en.wikipedia.org",
         "branch": "", "licence": "CC-BY-SA-4.0", "attribution": "w", "content_root": "", "public_base": "https://en.wikipedia.org/wiki"},
    ]}), encoding="utf-8")

    def roblox_walker(root, base):
        from starkb.chunking import chunk_markdown
        yield chunk_markdown("TweenService:Create makes a Tween that interpolates a property. " * 6,
                             path="reference/TweenService.md", url=base + "/reference/TweenService",
                             fallback_title="TweenService")
    db_path = tmp_path / "kb.sqlite3"
    stats = store.build(db_path, sources, manifest, walkers={"creator-docs": roblox_walker},
                        source_metadata={"creator-docs": {"commit": "c" * 40, "commit_date": "2026-10-18"}})
    assert stats["wiki"]["docs"] == 1 and stats["creator-docs"]["docs"] == 1
    return db_path


def test_roblox_queries_stay_on_the_roblox_group_and_others_see_everything(tmp_path):
    db_path = _index(tmp_path)
    searcher = search.Searcher(db_path, brain=object())
    assert searcher.groups == {"creator-docs": "roblox", "wiki": "general"}
    assert search.auto_scope("How do I use TweenService to tween a part in Roblox?") == "roblox"
    assert search.auto_scope("What is tweening in animation?") == "auto"
    assert search.auto_scope("Godot equivalent of a Roblox RemoteEvent") == "all"
    roblox, _ = searcher.search("tween a part with TweenService in Roblox", mode="bm25", top=5)
    assert {p.source for p in roblox} == {"creator-docs"}
    # "auto", BM25: the encyclopaedia page matches every word and wins clearly, so everything is searched
    general, timing = searcher.search("what is tweening between keyframes", mode="bm25", top=5)
    assert {p.source for p in general} == {"creator-docs", "wiki"} and timing["roblox_first"] == 0
    forced, timing = searcher.search("tweening", mode="bm25", top=5, scope="general")
    assert {p.source for p in forced} == {"wiki"} and timing["scoped_sources"] == 1
    wiki = next(p for p in forced)
    assert wiki.permalink == wiki.url.split("#")[0] and wiki.licence == "CC-BY-SA-4.0"
    assert wiki.commit == "wiki-1"


def test_a_source_needs_a_known_walker():
    with pytest.raises(KeyError):
        walkers.walker_for({"name": "x", "walker": "pdf-tree"})


class QueryBrain:
    """Returns a fixed query vector (the index's vectors are written by the test)."""

    def __init__(self, vector):
        self.vector = vector

    def embed(self, texts):
        return [self.vector for _ in texts], 0


def _vectors(db_path: Path, by_source: dict[str, list[float]]) -> None:
    import sqlite3
    import numpy as np
    from starkb.client import EMBED_MODEL
    db = sqlite3.connect(db_path)
    for sha, source in db.execute("SELECT c.text_sha, d.source FROM chunks c JOIN docs d ON d.id=c.doc_id").fetchall():
        vec = np.asarray(by_source[source], dtype=np.float32)
        db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?)",
                   (sha, EMBED_MODEL, len(vec), (vec / np.linalg.norm(vec)).tobytes(), "t"))
    db.commit()
    db.close()


@pytest.mark.parametrize("roblox_cos, wiki_cos, roblox_only", [
    (0.50, 0.50 + search.ROBLOX_MARGIN - 0.02, True),     # the other corpus is a little better: Roblox stays first
    (0.30, 0.30 + search.ROBLOX_MARGIN + 0.05, False),    # clearly better: the whole index answers
    (0.60, 0.20, True),
])
def test_auto_scope_keeps_roblox_unless_another_corpus_is_clearly_better(tmp_path, roblox_cos, wiki_cos, roblox_only):
    import math
    db_path = _index(tmp_path)
    _vectors(db_path, {"creator-docs": [1, 0, 0], "wiki": [0, 1, 0]})
    query = [roblox_cos, wiki_cos, math.sqrt(max(0.0, 1 - roblox_cos ** 2 - wiki_cos ** 2))]
    searcher = search.Searcher(db_path, brain=QueryBrain(query))
    passages, timing = searcher.search("how does an object move smoothly between two states", mode="vector", top=5)
    assert timing["roblox_first"] == (1.0 if roblox_only else 0.0)
    assert [p.source for p in passages][0] == ("creator-docs" if roblox_only or roblox_cos > wiki_cos else "wiki")
    assert ({p.source for p in passages} == {"creator-docs"}) is roblox_only
    # an explicit scope is never second-guessed
    everything, timing = searcher.search("how does an object move smoothly between two states", mode="vector",
                                         top=5, scope="all")
    assert {p.source for p in everything} == {"creator-docs", "wiki"} and "roblox_first" not in timing


def test_eval_refuses_a_question_whose_verbatim_answer_is_not_in_its_expected_page(tmp_path, monkeypatch):
    from starkb.evaluate import run_eval
    db_path = _index(tmp_path)
    monkeypatch.setattr(search, "Brain", lambda: object())       # BM25 only: no model
    good = {"id": "g1", "question": "what is inbetweening between keyframes", "answer": "intermediate frames between two keyframes",
            "expected": ["p.jsonl#1"]}
    questions = tmp_path / "q.jsonl"
    questions.write_text(json.dumps(good) + "\n", encoding="utf-8")
    assert run_eval(db_path, questions, ["bm25"], details=False)["summary"]["bm25"]["hits@5"] == 1
    questions.write_text(json.dumps({**good, "answer": "a sentence the page does not contain"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="answer not found"):
        run_eval(db_path, questions, ["bm25"], details=False)
