"""The private corpus (the team's brain vault) is its own index and only `corpus: "private"` reaches it.

    python -m pytest -q server/knowledge/tests/test_private_corpus.py
No network and no model: BM25 only.
"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starkb import private_corpus, serve, store  # noqa: E402
from starkb.evaluate import run_eval  # noqa: E402

KEY = b"test-key-not-a-real-one"

NOTES = {
    "notes/agents/night-conductor.md": "---\ntitle: \"Night conductor\"\n---\n# Night conductor\n\nNight school writes its own "
                                       "practice tasks from yesterday's failures and checks each one before it is used.\n",
    "notes/agents/forge.md": "# Forge\n\nThe forge listens for git over ssh on port 2222 and serves its web page on 3000.\n",
    "code/star/slop_py.md": "# star/slop.py\n\nAnti-slop checker.\n\n## Defines (2)\n\n- `check_prose()` (line 185)\n",
    ".obsidian/workspace.md": "# hidden\n\nsecret layout that is never indexed\n",
}


@pytest.fixture()
def vault(tmp_path):
    root = tmp_path / "brain"
    for rel, text in NOTES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def public_index(path: Path) -> None:
    db = store.connect(path)
    db.execute(store.FTS)
    db.execute("INSERT INTO sources VALUES('creator-docs','https://example.invalid/docs.git','main','c0ffee',"
               "'2026-01-01T00:00:00+00:00','CC-BY-4.0','Example','2026-01-01T00:00:00+00:00')")
    doc = db.execute("INSERT INTO docs(source,path,kind,title,url) VALUES('creator-docs','content/en-us/a.md','guide',"
                     "'Tweens','https://example.invalid/a')").lastrowid
    text = "TweenService creates tweens for parts. Night school is not mentioned here."
    rowid = db.execute("INSERT INTO chunks(doc_id,ord,kind,heading,anchor,text,idents,text_sha) VALUES(?,?,?,?,?,?,?,?)",
                       (doc, 0, "guide", "Tweens", "", text, "", "sha0")).lastrowid
    db.execute("INSERT INTO chunks_fts(rowid,title,heading,idents,text,questions) VALUES(?,?,?,?,?,?)",
               (rowid, "Tweens", "Tweens", "", text, ""))
    db.execute("INSERT OR REPLACE INTO meta VALUES('built_at','2026-01-01T00:00:00+00:00')")
    db.commit()
    db.close()


def test_build_indexes_notes_not_hidden_folders_and_marks_the_source_private(vault, tmp_path):
    db_path = tmp_path / "private.sqlite3"
    stats = private_corpus.build_private(vault, db_path, log=lambda m: None)
    assert stats[private_corpus.SOURCE]["docs"] == 3
    db = store.connect_readonly(db_path)
    paths = {r[0]: r[1] for r in db.execute("SELECT path, kind FROM docs")}
    assert set(paths) == {"notes/agents/night-conductor.md", "notes/agents/forge.md", "code/star/slop_py.md"}
    assert paths["code/star/slop_py.md"] == "code-note" and paths["notes/agents/forge.md"] == "note"
    assert json.loads(db.execute("SELECT value FROM meta WHERE name='source_groups'").fetchone()[0]) == \
        {private_corpus.SOURCE: private_corpus.GROUP}
    assert db.execute("SELECT licence FROM sources").fetchone()[0].startswith("PRIVATE")


def test_rebuild_follows_the_notes_and_keeps_the_fingerprint_honest(vault, tmp_path):
    db_path = tmp_path / "private.sqlite3"
    private_corpus.build_private(vault, db_path, log=lambda m: None)
    first = private_corpus.fingerprint(vault)
    (vault / "notes/agents/forge.md").write_text("# Forge\n\nNow it listens on port 2223.\n", encoding="utf-8")
    assert private_corpus.fingerprint(vault) != first
    private_corpus.build_private(vault, db_path, log=lambda m: None)
    db = store.connect_readonly(db_path)
    text = " ".join(r[0] for r in db.execute("SELECT text FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE d.path=?",
                                              ("notes/agents/forge.md",)))
    assert "2223" in text and "2222" not in text
    assert db.execute("SELECT commit_sha FROM sources").fetchone()[0] == private_corpus.fingerprint(vault)


def test_missing_vault_is_an_error_not_an_empty_index(tmp_path):
    with pytest.raises(FileNotFoundError):
        private_corpus.build_private(tmp_path / "nope", tmp_path / "p.sqlite3", log=lambda m: None)


def test_service_keeps_the_private_corpus_out_of_default_searches(vault, tmp_path):
    public, private = tmp_path / "kb.sqlite3", tmp_path / "private.sqlite3"
    public_index(public)
    private_corpus.build_private(vault, private, log=lambda m: None)
    service = serve.Service(public, [KEY], brain=object(), private_db_path=private)

    status, reply = service.search({"query": "night school practice tasks", "mode": "bm25"})
    assert status == 200 and reply["corpus"] == "public"
    assert all(p["source"] == "creator-docs" for p in reply["passages"])

    status, reply = service.search({"query": "night school practice tasks", "mode": "bm25", "corpus": "private"})
    assert status == 200 and reply["corpus"] == "private"
    assert reply["passages"][0]["path"] == "notes/agents/night-conductor.md"
    assert reply["passages"][0]["source"] == private_corpus.SOURCE
    assert reply["passages"][0]["url"].startswith("vault://")

    status, reply = service.search({"query": "git ssh port", "mode": "bm25", "corpus": "private"})
    assert reply["passages"][0]["path"] == "notes/agents/forge.md"


def test_private_requests_are_refused_without_a_private_index_or_with_a_bad_corpus(tmp_path):
    public = tmp_path / "kb.sqlite3"
    public_index(public)
    service = serve.Service(public, [KEY], brain=object())
    assert service.search({"query": "night school", "mode": "bm25", "corpus": "private"})[0] == 404
    assert service.search({"query": "night school", "mode": "bm25", "corpus": "../etc"})[0] == 400
    gone = serve.Service(public, [KEY], brain=object(), private_db_path=tmp_path / "missing.sqlite3")
    assert gone.search({"query": "night school", "mode": "bm25", "corpus": "private"})[0] == 404


def test_the_shipped_question_file_matches_the_evaluator_format():
    questions = Path(__file__).resolve().parents[1] / "eval" / "vault-questions.jsonl"
    rows = [json.loads(line) for line in questions.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("//")]
    assert len(rows) == 30 and len({r["id"] for r in rows}) == 30
    assert all(r["question"] and r["expected"] and r["fact"] for r in rows)
    assert callable(run_eval)
