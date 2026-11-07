"""Unit tests for the GPU training pilot scripts (server/training/gpu): data building and the paired comparison.
No model, no GPU: only the parts that decide WHAT is trained on and HOW a result is judged."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import pytest

GPU = Path(__file__).resolve().parents[1] / "server" / "training" / "gpu"
sys.path.insert(0, str(GPU))

import build_pairs  # noqa: E402
import eval_retrieval  # noqa: E402
import gen_queries  # noqa: E402


def first_heldout() -> dict:
    for line in (build_pairs.KNOWLEDGE / "eval" / "heldout.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("//"):
            return json.loads(line)
    raise AssertionError("no held-out question")


def make_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE sources(name TEXT PRIMARY KEY, repo TEXT, branch TEXT, commit_sha TEXT, commit_date TEXT,
                             licence TEXT, attribution TEXT, indexed_at TEXT);
        CREATE TABLE docs(id INTEGER PRIMARY KEY, source TEXT, path TEXT, kind TEXT, title TEXT, url TEXT);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc_id INTEGER, ord INTEGER, kind TEXT, heading TEXT, anchor TEXT,
                            text TEXT, idents TEXT, text_sha TEXT);
        CREATE TABLE chunk_questions(id INTEGER PRIMARY KEY, text_sha TEXT, ord INTEGER, question TEXT, q_sha TEXT,
                                     model TEXT, created_at TEXT);
    """)
    db.execute("INSERT INTO sources VALUES('creator-docs','https://example.invalid/docs.git','main','abc','d',"
               "'CC-BY-4.0','attr','t')")
    # an evaluation answer page (the first held-out question's expected page) and an ordinary page
    db.execute("INSERT INTO docs VALUES(1,'creator-docs',?,'guide','Versioning','u')", (first_heldout()["expected"][0],))
    db.execute("INSERT INTO docs VALUES(2,'creator-docs','content/en-us/other/page.md','guide','Other','u')")
    db.execute("INSERT INTO docs VALUES(3,'creator-docs','content/en-us/news/n.md','news','News','u')")
    long = "x " * 150
    db.execute("INSERT INTO chunks VALUES(1,1,0,'guide','Versions','a','Data store versions ' || ?,'', 'sha-eval')", (long,))
    db.execute("INSERT INTO chunks VALUES(2,2,0,'guide','Part','a','Some other page ' || ?,'', 'sha-other')", (long,))
    db.execute("INSERT INTO chunks VALUES(3,3,0,'news','N','a','Release notes ' || ?,'', 'sha-news')", (long,))
    db.execute("INSERT INTO chunk_questions VALUES(1,'sha-other',0,'How do I move a part smoothly?','q','star-quick/q1','t')")
    db.commit()
    db.close()


def eval_question() -> str:
    return first_heldout()["question"]


def run_build(tmp_path: Path, monkeypatch, *extra: str) -> tuple[list[dict], dict]:
    db = tmp_path / "kb.sqlite3"
    make_db(db)
    queries = tmp_path / "q.jsonl"
    prov = {"generator": "local-open-model", "claude_or_chatgpt_involved": False}
    rows = [
        {"text_sha": "sha-other", "ok": True, "question": "How can I make a brick glide across the map nicely?",
         "task": "Write a script that slides a block from A to B over two seconds and then stops at B.", "provenance": prov},
        {"text_sha": "sha-other", "ok": True, "question": eval_question(), "task": "unrelated words here for the task "
         "field so that it passes length checks easily and fully", "provenance": prov},
        {"text_sha": "sha-eval", "ok": True, "question": "Where do I find old saved copies of my stored values?",
         "task": "Build an admin command that lists previous saved versions of a player's stored record.", "provenance": prov},
        {"text_sha": "sha-other", "ok": False, "question": "bad", "task": "bad", "provenance": prov},
    ]
    queries.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "pairs.jsonl"
    monkeypatch.setattr(sys, "argv", ["build_pairs", "--db", str(db), "--queries", str(queries), "--out", str(out), *extra])
    build_pairs.main()
    pairs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    manifest = json.loads(out.with_suffix(".manifest.json").read_text())
    return pairs, manifest


def test_pairs_drop_eval_lookalikes_and_bad_rows(tmp_path, monkeypatch):
    pairs, manifest = run_build(tmp_path, monkeypatch)
    anchors = [p["anchor"] for p in pairs]
    assert not any(eval_question() in a for a in anchors), "an evaluation question must never become training data"
    assert manifest["dropped"]["too similar to an evaluation question"] >= 1
    assert all(a.startswith("task: search result | query: ") for a in anchors)
    assert all(p["positive"].startswith("title: ") for p in pairs)
    assert manifest["claude_or_chatgpt_outputs_used"] is False
    assert {p["origin"] for p in pairs} == {"synthetic-question", "synthetic-task", "doc2query-index"}
    assert all(p["provenance"]["doc_source"]["licence"] == "CC-BY-4.0" for p in pairs)
    assert manifest["eval_pages_in_training"] == 1


def test_strict_variant_leaves_out_evaluation_pages(tmp_path, monkeypatch):
    pairs, manifest = run_build(tmp_path, monkeypatch, "--exclude-eval-pages")
    assert all(p["text_sha"] != "sha-eval" for p in pairs)
    assert manifest["eval_pages_in_training"] == 0
    assert manifest["dropped"]["page is an evaluation answer (strict variant)"] == 2


def test_sampler_skips_news_and_excluded_pages(tmp_path):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    db = sqlite3.connect(db_path)
    picked = gen_queries.sample_chunks(db, 100, 1, set())
    assert {c["text_sha"] for c in picked} == {"sha-eval", "sha-other"}
    picked = gen_queries.sample_chunks(db, 100, 1, {"content/en-us/other/page.md"})
    assert {c["text_sha"] for c in picked} == {"sha-eval"}
    db.close()


def test_sign_test_and_compare(tmp_path):
    assert eval_retrieval.sign_test(0, 0) == 1.0
    assert eval_retrieval.sign_test(5, 0) == pytest.approx(1 / 32)
    assert eval_retrieval.sign_test(3, 1) == pytest.approx(5 / 16)
    a = {"sets": {"golden": {"ranks": {"vector": {"q1": 1, "q2": None, "q3": 7, "q4": 2}}}}}
    b = {"sets": {"golden": {"ranks": {"vector": {"q1": 1, "q2": 3, "q3": 4, "q4": 9}}}}}
    (tmp_path / "a.json").write_text(json.dumps(a))
    (tmp_path / "b.json").write_text(json.dumps(b))
    rep = eval_retrieval.compare(tmp_path / "a.json", tmp_path / "b.json")["golden/vector"]
    assert (rep["a"], rep["b"], rep["wins"], rep["losses"]) == (2, 3, ["q2", "q3"], ["q4"])


# Adversarial fixtures intentionally exercise the public pair-building entrypoint;
# no GPU, model downloads or recorded evaluation results are involved.
def _adversarial_pairs(tmp_path, monkeypatch, *, query_rows=(), strict=False):
    db_path = tmp_path / "kb.sqlite3"
    if not db_path.exists():
        make_db(db_path)
    queries = tmp_path / "adversarial.jsonl"
    queries.write_text("".join(json.dumps(row) + "\n" for row in query_rows), encoding="utf-8")
    output = tmp_path / "adversarial-pairs.jsonl"
    argv = ["build_pairs", "--db", str(db_path), "--queries", str(queries), "--out", str(output)]
    if strict:
        argv.append("--exclude-eval-pages")
    monkeypatch.setattr(sys, "argv", argv)
    build_pairs.main()
    return ([json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()],
            json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8")))


def _synthetic_row(provenance):
    return {
        "text_sha": "sha-other", "ok": True,
        "question": "How can I make a brick glide across the map nicely?",
        "task": "Write a script that slides a block from A to B over two seconds and then stops at B.",
        "provenance": provenance,
    }


def _known_provenance():
    return {"generator": "local-open-model", "claude_or_chatgpt_involved": False}


def test_strict_eval_exclusion_covers_shared_hash_even_when_allowed_page_wins_grouping(tmp_path, monkeypatch):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    db = sqlite3.connect(db_path)
    # Deliberately make the ordinary page the canonical chunk for GROUP BY;
    # the same bytes also exist on a protected expected-answer page.
    db.execute("INSERT INTO chunks VALUES(4,1,1,'guide','Versions','a','duplicate text','', 'sha-other')")
    db.commit()
    db.close()
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch,
                                         query_rows=[_synthetic_row(_known_provenance())], strict=True)
    assert not any(pair["text_sha"] == "sha-other" for pair in pairs)
    assert manifest["eval_pages_in_training"] == 0
    assert manifest["dropped"]["page is an evaluation answer (strict variant)"] >= 3


def test_sampler_excludes_all_pages_with_a_shared_disallowed_hash(tmp_path):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO chunks VALUES(4,1,1,'guide','Versions','a','duplicate text','', 'sha-other')")
    db.commit()
    forbidden = {first_heldout()["expected"][0]}
    assert "sha-other" not in {c["text_sha"] for c in gen_queries.sample_chunks(db, 100, 1, forbidden)}
    db.close()


@pytest.mark.parametrize("generator", [
    "ChatGPT", "Claude-3.5", "OpenAI/GPT-4", "Anthropic/Claude", "Codex", "unknown-private-model",
])
def test_prohibited_or_unidentified_synthetic_generators_are_rejected(tmp_path, monkeypatch, generator):
    prov = {**_known_provenance(), "generator": generator}
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch,
                                         query_rows=[_synthetic_row(prov)])
    assert not any(pair["origin"].startswith("synthetic-") for pair in pairs)
    assert manifest["dropped"]["untrusted query provenance"] >= 2
    assert manifest["claude_or_chatgpt_outputs_used"] is False


@pytest.mark.parametrize("provenance", [
    {},
    {"generator": "local-open-model"},
    {"generator": "local-open-model", "claude_or_chatgpt_involved": None},
    {"generator": "local-open-model", "claude_or_chatgpt_involved": "false"},
    {"generator": "local-open-model", "claude_or_chatgpt_involved": True},
    {"generator": "", "claude_or_chatgpt_involved": False},
])
def test_missing_or_contradictory_generation_claims_are_untrusted(tmp_path, monkeypatch, provenance):
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch,
                                         query_rows=[_synthetic_row(provenance)])
    assert not any(pair["origin"].startswith("synthetic-") for pair in pairs)
    assert manifest["dropped"]["untrusted query provenance"] >= 2


@pytest.mark.parametrize("licence", ["Proprietary", "unknown", "", "GPL-3.0"])
def test_unknown_document_licence_never_gets_rights_clean_pair(tmp_path, monkeypatch, licence):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE sources SET licence = ?", (licence,))
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch,
                                         query_rows=[_synthetic_row(_known_provenance())])
    assert pairs == []
    assert manifest["pairs"] == 0
    assert manifest["dropped"]["untrusted document source"] >= 3


def test_missing_source_record_is_not_silently_certified(tmp_path, monkeypatch):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM sources")
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch,
                                         query_rows=[_synthetic_row(_known_provenance())])
    assert pairs == []
    assert manifest["dropped"]["untrusted document source"] >= 3


def test_conflicting_declared_and_indexed_document_provenance_is_rejected(tmp_path, monkeypatch):
    provenance = {**_known_provenance(),
                  "doc_source": {"repo": "different-repository", "commit": "wrong", "licence": "MIT"}}
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch, query_rows=[_synthetic_row(provenance)])
    assert not any(pair["origin"].startswith("synthetic-") for pair in pairs)
    assert manifest["dropped"]["untrusted query provenance"] >= 2


def test_shared_hash_with_unlicensed_alias_is_not_rights_clean(tmp_path, monkeypatch):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO sources VALUES('unknown-docs','source','main','123','d','unknown','a','t')")
        db.execute("INSERT INTO docs VALUES(4,'unknown-docs','unlicensed/page.md','guide','Alias','u')")
        db.execute("INSERT INTO chunks VALUES(4,4,0,'guide','Alias','a','duplicate text','', 'sha-other')")
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch,
                                         query_rows=[_synthetic_row(_known_provenance())])
    assert not any(pair["text_sha"] == "sha-other" for pair in pairs)
    assert manifest["dropped"]["untrusted document source"] >= 3


@pytest.mark.parametrize("model", ["Claude", "ChatGPT", "", "unverified-provider"])
def test_doc2query_generator_must_be_recognized(tmp_path, monkeypatch, model):
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE chunk_questions SET model=?", (model,))
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch)
    assert pairs == []
    assert manifest["dropped"]["untrusted query provenance"] == 1


def test_casefolded_duplicate_queries_and_manifest_counts(tmp_path, monkeypatch):
    same = _synthetic_row(_known_provenance())
    upper = dict(same, question=same["question"].upper(), task=same["task"].upper())
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch, query_rows=[same, upper])
    assert manifest["dropped"]["duplicate"] == 2
    assert manifest["pairs"] == len(pairs) == 3  # one question, one task, one indexed query
    assert manifest["chunks"] == 1
    assert manifest["pages"] == 1
    assert sum(manifest["by_origin"].values()) == manifest["pairs"]
    assert len({(p["anchor"].casefold(), p["text_sha"]) for p in pairs}) == len(pairs)


def test_every_indexed_corpus_licence_is_accepted(tmp_path, monkeypatch):
    """Review fix: the real index stores creator-docs as 'CC-BY-4.0 (prose), MIT (code samples)' (corpora.json);
    an exact-match allowlist without it dropped every pair of the main corpus."""
    corpora = json.loads((Path(__file__).resolve().parents[1] / "server" / "knowledge" / "corpora.json")
                         .read_text(encoding="utf-8"))
    licences = {source["licence"] for source in corpora["sources"] if source.get("group", "roblox") == "roblox"}
    assert licences and licences <= build_pairs._ALLOWED_LICENCES
    # the other corpora (knowledge school) include non-commercial books: never training pairs
    others = {source["licence"] for source in corpora["sources"]} - licences
    assert "CC-BY-NC-SA-4.0" in others and "CC-BY-NC-SA-4.0" not in build_pairs._ALLOWED_LICENCES
    db_path = tmp_path / "kb.sqlite3"
    make_db(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE sources SET licence = ?", ("CC-BY-4.0 (prose), MIT (code samples)",))
    pairs, manifest = _adversarial_pairs(tmp_path, monkeypatch, query_rows=[_synthetic_row(_known_provenance())])
    assert pairs and manifest["pairs"] == len(pairs)
    assert "untrusted document source" not in manifest["dropped"]
