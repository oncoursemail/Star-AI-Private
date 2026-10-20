import hashlib
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starkb import store
from starkb.corpus_cli import preview
from starkb.corpus_manifest import CorpusError
from starkb.corpus_plan import build_candidate, plan, readonly_index
from corpus_fixture import git, save, snapshot, tree_bytes


def test_built_candidate_retrieves_exact_source_and_provenance(tmp_path, monkeypatch):
    repo, manifest, source = snapshot(tmp_path)
    monkeypatch.setattr("starkb.client.Brain.embed", lambda *a, **k: pytest.fail("no model calls"))
    output = tmp_path / "first.candidate.sqlite3"
    result = build_candidate(manifest, repo.parent, output, selected=[source["name"]])
    assert result["activated"] is False and result["embedded_now"] == 0
    answer = preview(output, "cancel previous animation", sources=["luau-site"])
    passage = answer["passages"][0]
    raw = (repo / source["paths"][0]).read_bytes().decode()
    spans = passage["provenance"]
    assert passage["text"] == "".join(raw.splitlines(keepends=True)[spans["line_start"] - 1:spans["line_end"]])
    assert passage["commit"] == source["revision"]
    assert passage["attribution"] == source["attribution"]
    assert passage["permalink"].endswith(source["revision"] + "/" + source["paths"][0])
    assert answer["untrusted_reference"] and not answer["activated"]
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0


def test_existing_baseline_source_and_embedding_are_preserved(tmp_path):
    repo, manifest, source = snapshot(tmp_path)
    base = tmp_path / "baseline.sqlite3"
    db = store.connect(base)
    db.execute(store.FTS)
    db.execute("INSERT INTO sources VALUES('creator-docs','https://github.com/Roblox/creator-docs.git','main',?,'date','CC-BY-4.0','baseline attribution','date')", ("a" * 40,))
    doc = db.execute("INSERT INTO docs(source,path,kind,title,url) VALUES('creator-docs','content/en-us/a.md','guide','Baseline','https://example.invalid/a')").lastrowid
    row = db.execute("INSERT INTO chunks(doc_id,ord,kind,heading,anchor,text,idents,text_sha) VALUES(?,0,'guide','Baseline','','baseline Roblox tween evidence','','baseline-sha')", (doc,)).lastrowid
    db.execute("INSERT INTO chunk_questions(text_sha,ord,question,q_sha,model,created_at) VALUES('baseline-sha',0,'persistent question evidence','question-sha','authored-fake','date')")
    db.execute("INSERT INTO chunks_fts(rowid,title,heading,idents,text,questions) VALUES(?,'Baseline','Baseline','','baseline Roblox tween evidence','persistent question evidence')", (row,))
    db.execute("INSERT INTO embeddings VALUES('baseline-sha','authored-fake',1,?, 'date')", (b"1234",))
    db.commit()
    original_source = tuple(db.execute("SELECT * FROM sources WHERE name='creator-docs'").fetchone())
    original_doc = tuple(db.execute("SELECT * FROM docs WHERE id=?", (doc,)).fetchone())
    original_chunk = tuple(db.execute("SELECT * FROM chunks WHERE id=?", (row,)).fetchone())
    original_embedding = tuple(db.execute("SELECT * FROM embeddings WHERE text_sha='baseline-sha'").fetchone())
    db.close()
    before = base.read_bytes()
    before_sha = hashlib.sha256(before).hexdigest()
    output = tmp_path / "mixed.candidate.sqlite3"
    build_candidate(manifest, repo.parent, output, selected=["luau-site"], previous=base)
    assert base.read_bytes() == before
    assert hashlib.sha256(base.read_bytes()).hexdigest() == before_sha
    assert preview(output, "baseline tween", sources=["creator-docs"])["passages"][0]["text"] == "baseline Roblox tween evidence"
    assert not preview(output, "baseline Roblox", sources=["luau-site"])["passages"]
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT * FROM sources WHERE name='creator-docs'").fetchone() == original_source
        assert db.execute("SELECT * FROM docs WHERE id=?", (doc,)).fetchone() == original_doc
        assert db.execute("SELECT * FROM chunks WHERE id=?", (row,)).fetchone() == original_chunk
        assert db.execute("SELECT * FROM embeddings WHERE text_sha='baseline-sha'").fetchone() == original_embedding
        assert db.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'persistent question'").fetchall() == [(row,)]
        assert db.execute("SELECT value FROM meta WHERE name='candidate_only'").fetchone()[0] == "true"
    live = (Path(__file__).resolve().parents[1] / "corpora.json").read_text()
    # knowledge school (2026-10-18): the live catalogue lists further open-licensed sources, each with its licence
    import json as _json
    assert all(src.get("licence") and src.get("attribution") for src in _json.loads(live)["sources"])


def test_incremental_changes_deletions_and_unchanged_hashes(tmp_path):
    files = {f"src/content/docs/{i}.md": f"# Fixture {i}\nEvidence unchanged {i}.\n" for i in range(5)}
    repo, manifest, source = snapshot(tmp_path, files=files)
    first = tmp_path / "first.sqlite3"
    build_candidate(manifest, repo.parent, first, selected=["luau-site"])
    # Seed an authored fake vector for one unchanged text; no embedding server is used.
    db = store.connect(first)
    sha = db.execute("SELECT c.text_sha FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE d.path=?", (source["paths"][0],)).fetchone()[0]
    db.execute("INSERT INTO embeddings VALUES(?,'authored-fake',1,?,'date')", (sha, b"1234"))
    db.commit()
    db.close()
    before = first.read_bytes()
    removed = source["paths"].pop()
    (repo / removed).unlink()
    changed = source["paths"][1]
    (repo / changed).write_text("# Changed fixture\nCorrected final evidence.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "authored changed/deleted snapshot")
    source["revision"] = git(repo, "rev-parse", "HEAD")
    save(manifest, [source])
    planned = plan(manifest, repo.parent, previous=first)["sources"][0]
    assert planned["removed"] == [removed] and planned["changed"] == [changed]
    assert source["paths"][0] in planned["unchanged"]
    second = tmp_path / "second.sqlite3"
    result = build_candidate(manifest, repo.parent, second, selected=["luau-site"], previous=first)
    assert first.read_bytes() == before
    assert result["index"]["_all"]["texts_added"] == 1
    assert result["index"]["_all"]["texts_removed"] == 2
    with sqlite3.connect(second) as db:
        assert db.execute("SELECT vec FROM embeddings WHERE text_sha=?", (sha,)).fetchone()[0] == b"1234"
        assert not db.execute("SELECT 1 FROM docs WHERE path=?", (removed,)).fetchone()


def test_build_never_overwrites_existing_or_supplied_database(tmp_path):
    repo, manifest, _ = snapshot(tmp_path)
    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"precious existing content")
    before = tree_bytes(tmp_path)
    with pytest.raises(CorpusError, match="new file"):
        build_candidate(manifest, repo.parent, target, selected=["luau-site"])
    assert tree_bytes(tmp_path) == before


def test_invalid_input_and_mid_build_failure_publish_nothing(tmp_path, monkeypatch):
    repo, manifest, source = snapshot(tmp_path)
    previous = tmp_path / "previous.sqlite3"
    build_candidate(manifest, repo.parent, previous, selected=["luau-site"])
    previous_sha = hashlib.sha256(previous.read_bytes()).hexdigest()
    output = tmp_path / "discarded.sqlite3"
    monkeypatch.setattr(store, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated rebuild failure")))
    before = tree_bytes(tmp_path)
    with pytest.raises(RuntimeError, match="simulated"):
        build_candidate(manifest, repo.parent, output, selected=["luau-site"], previous=previous)
    assert tree_bytes(tmp_path) == before and not output.exists()
    assert hashlib.sha256(previous.read_bytes()).hexdigest() == previous_sha
    source["revision"] = None
    save(manifest, [source])
    with pytest.raises(CorpusError, match="unresolved"):
        build_candidate(manifest, repo.parent, output, selected=["luau-site"], previous=previous)
    assert not output.exists()
    assert hashlib.sha256(previous.read_bytes()).hexdigest() == previous_sha


def test_reduced_selection_cannot_wipe_baseline_source(tmp_path):
    files = {f"src/content/docs/{i}.md": f"# {i}\nFixture evidence.\n" for i in range(5)}
    repo, manifest, source = snapshot(tmp_path, files=files)
    first = tmp_path / "first.sqlite3"
    build_candidate(manifest, repo.parent, first, selected=["luau-site"])
    source["paths"] = source["paths"][:1]
    save(manifest, [source])
    output = tmp_path / "smaller.sqlite3"
    before = first.read_bytes()
    with pytest.raises(CorpusError, match="20%"):
        build_candidate(manifest, repo.parent, output, selected=["luau-site"], previous=first)
    assert first.read_bytes() == before and not output.exists()


def test_preview_is_scoped_and_rejects_live_or_unregistered_indexes(tmp_path):
    repo, manifest, _ = snapshot(tmp_path)
    output = tmp_path / "candidate.sqlite3"
    build_candidate(manifest, repo.parent, output, selected=["luau-site"])
    with pytest.raises(CorpusError, match="unknown"):
        preview(output, "fixture", sources=["invented"])
    db = sqlite3.connect(output)
    db.execute("DELETE FROM meta WHERE name='candidate_only'")
    db.commit()
    db.close()
    with pytest.raises(CorpusError, match="candidate indexes"):
        preview(output, "fixture", sources=["luau-site"])


def test_publication_race_cannot_replace_file_created_after_planning(tmp_path, monkeypatch):
    repo, manifest, _ = snapshot(tmp_path)
    output = tmp_path / "race.sqlite3"
    import starkb.corpus_plan as module
    actual = module.os.link

    def raced_link(source, target):
        Path(target).write_bytes(b"created by another writer")
        return actual(source, target)

    monkeypatch.setattr(module.os, "link", raced_link)
    with pytest.raises(FileExistsError):
        build_candidate(manifest, repo.parent, output, selected=["luau-site"])
    assert output.read_bytes() == b"created by another writer"
    assert not list(tmp_path.glob(".corpus-candidate-*"))


def test_cancellation_discards_candidate_without_changing_previous(tmp_path, monkeypatch):
    repo, manifest, _ = snapshot(tmp_path)
    first = tmp_path / "first.sqlite3"
    build_candidate(manifest, repo.parent, first, selected=["luau-site"])
    before = first.read_bytes()
    output = tmp_path / "cancelled.sqlite3"
    monkeypatch.setattr(store, "build", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        build_candidate(manifest, repo.parent, output, selected=["luau-site"], previous=first)
    assert first.read_bytes() == before and not output.exists()
    assert not list(tmp_path.glob(".corpus-candidate-*"))


def test_live_wal_is_rejected_without_creating_or_mutating_files(tmp_path):
    path = tmp_path / "live.sqlite3"
    db = store.connect(path)
    before = tree_bytes(tmp_path)
    try:
        with pytest.raises(CorpusError, match="checkpointed"):
            readonly_index(path)
        assert tree_bytes(tmp_path) == before
    finally:
        db.close()
