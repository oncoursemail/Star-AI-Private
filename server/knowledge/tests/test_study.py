"""The study job (doc2query), the lock helper and the safe rebuild, with a fake model and a tiny index.

Run on the PC:  python -m pytest -q server/knowledge/tests
"""
from pathlib import Path
import os
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starkb import quiet, search, store, study  # noqa: E402
from starkb.evaluate import parse_mode  # noqa: E402

TEXTS = {
    "sha-tween": ("TweenService", "TweenService > Create", "TweenService:Create(instance, tweenInfo, goals): Tween"),
    "sha-remote": ("Remote events", "Remote events", "A RemoteEvent sends one-way messages across the client-server boundary."),
    "sha-store": ("Data stores", "Data stores > Save", "SetAsync writes a value to a GlobalDataStore."),
}


def build_index(path: Path) -> None:
    db = store.connect(path)
    db.execute(store.FTS)
    db.execute("INSERT INTO sources VALUES('creator-docs','https://example.invalid/docs.git','main','c0ffee',"
               "'2026-01-01T00:00:00+00:00','CC-BY-4.0','Example','2026-01-01T00:00:00+00:00')")
    for n, (sha, (title, heading, text)) in enumerate(TEXTS.items()):
        doc = db.execute("INSERT INTO docs(source,path,kind,title,url) VALUES('creator-docs',?,?,?,?)",
                         (f"content/en-us/{sha}.md", "guide", title, "https://example.invalid/" + sha)).lastrowid
        rowid = db.execute("INSERT INTO chunks(doc_id,ord,kind,heading,anchor,text,idents,text_sha) VALUES(?,?,?,?,?,?,?,?)",
                           (doc, 0, "api-member" if n == 0 else "guide", heading, "", text, "", sha)).lastrowid
        db.execute("INSERT INTO chunks_fts(rowid,title,heading,idents,text,questions) VALUES(?,?,?,?,?,?)",
                   (rowid, title, heading, "", text, ""))
        vector = [0.0] * 4
        vector[n] = 1.0
        db.execute("INSERT INTO embeddings VALUES(?,?,?,?,?)", (sha, search.EMBED_MODEL, 4, store_vector(vector), "t"))
    db.execute("INSERT OR REPLACE INTO meta VALUES('built_at','2026-01-01T00:00:00+00:00')")
    db.commit()
    db.close()


def store_vector(values):
    from array import array
    return array("f", values).tobytes()


class FakeBrain:
    """Answers the chat request with canned lines and embeds every text as the same unit vector."""

    def __init__(self, replies, fail_first=0):
        self.replies = replies
        self.fail = fail_first
        self.chats = 0
        self.passages = []

    def _post(self, path, payload, retries=None):
        assert path == "/v1/chat/completions" and payload["model"] == study.GEN_MODEL
        if self.fail:
            self.fail -= 1
            raise RuntimeError("HTTP 503")
        self.chats += 1
        passage = payload["messages"][1]["content"]
        self.passages.append(passage)
        key = next(k for k in self.replies if k in passage)
        return {"choices": [{"message": {"content": self.replies[key]}}], "timings": {"predicted_n": 20}}

    def embed(self, texts):
        return [[0.0, 0.0, 0.0, 1.0] for _ in texts], 5 * len(texts)

    def embed_query(self, query):
        return [0.0, 0.0, 0.0, 1.0]


def test_model_output_is_reduced_to_plain_short_questions():
    raw = ("Here are 3 questions:\n1. What does TweenService:Create return?\n- \"How can I animate a part smoothly\"\n"
           "How do I tween a door?\nHow do I tween a door?\nsee https://evil.example/x?\n<b>What is this?</b>\ntask.wait()\n"
           "What else?\n")
    assert study.clean_questions(raw) == ["What does TweenService:Create return?", "How can I animate a part smoothly?",
                                          "How do I tween a door?"]
    assert study.clean_questions("") == [] and study.clean_questions("no question here\nok") == []


def test_study_stores_questions_makes_them_searchable_and_resumes(tmp_path):
    index = tmp_path / "kb.sqlite3"
    build_index(index)
    replies = {"TweenService": "What does TweenService:Create return?\nHow can I animate a door opening smoothly?",
               "Remote events": "nothing useful",
               "Data stores": "How do I save coins when a player leaves?"}
    brain = FakeBrain(replies)
    logs = []
    first = study.run(index, limit=2, log=logs.append, stop=lambda: False, brain=brain)
    assert first["status"] == "finished" and first["studied_now"] == 2 and brain.chats == 2
    # API reference is studied before guides; a chunk with no usable question is logged, not retried
    assert "TweenService" in brain.passages[0]
    again = study.run(index, log=logs.append, stop=lambda: False, brain=brain)
    assert again["studied_now"] == 1 and brain.chats == 3
    assert again["index"] == {**again["index"], "studied": 3, "remaining": 0, "questions": 3, "empty": 1,
                              "questions_without_vector": 0}
    assert study.run(index, log=logs.append, stop=lambda: False, brain=brain)["studied_now"] == 0

    searcher = search.Searcher(index, brain=brain)
    # the word "door" exists only in a generated question
    assert searcher.bm25("door", questions=False) == []
    hit = searcher.bm25("door", questions=True)
    assert len(hit) == 1
    heading = searcher._rows([hit[0][0]])[hit[0][0]]["heading"]
    assert heading == "TweenService > Create"
    # embedding search: the query vector matches only question vectors
    with_q = searcher.vector("x", k=3, questions=True)
    without = searcher.vector("x", k=3, questions=False)
    assert max(score for _, score in without) == 0.0
    best = {cid: score for cid, score in with_q}
    assert sorted(best.values(), reverse=True)[:2] == [pytest.approx(searcher.question_scale)] * 2
    searcher.close()


def test_study_stops_cleanly_and_gives_up_after_repeated_failures(tmp_path, monkeypatch):
    index = tmp_path / "kb.sqlite3"
    build_index(index)
    monkeypatch.setattr(study.time, "sleep", lambda _s: None)
    stopped = study.run(index, log=lambda _m: None, stop=lambda: True, brain=FakeBrain({}))
    assert stopped["status"] == "stopped" and stopped["studied_now"] == 0
    failed = study.run(index, log=lambda _m: None, stop=lambda: False, brain=FakeBrain({}, fail_first=99), max_failures=3)
    assert failed["status"] == "failed" and failed["studied_now"] == 0
    recovered = study.run(index, limit=1, log=lambda _m: None, stop=lambda: False,
                          brain=FakeBrain({"TweenService": "What does Create return?"}, fail_first=2), max_failures=3)
    assert recovered["status"] == "finished" and recovered["studied_now"] == 1


def test_jobs_wait_while_the_lock_exists_and_ignore_a_stale_one(tmp_path):
    lock = tmp_path / "lock"
    assert quiet.lock_held(lock) is False
    lock.mkdir()
    (lock / "owner").write_text("someone 00:00")
    assert quiet.lock_held(lock) is True
    five_seconds_ago = time.time() - 5      # a file stamp can be a few ms ahead of time.time() on Windows: age it for real
    os.utime(lock / "owner", (five_seconds_ago, five_seconds_ago))
    os.utime(lock, (five_seconds_ago, five_seconds_ago))
    assert quiet.lock_held(lock) is True
    assert quiet.lock_held(lock, stale_seconds=0) is False          # older than the limit: left behind
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            (lock / "owner").unlink()
            lock.rmdir()

    waited = quiet.wait_while_locked(log=lambda _m: None, lock_dir=lock, sleep=sleep, poll=5.0)
    assert waited == 15.0 and len(slept) == 3
    assert quiet.wait_while_locked(log=lambda _m: None, lock_dir=lock, sleep=sleep) == 0.0


def test_a_rebuild_that_fails_or_shrinks_keeps_the_working_index(tmp_path, monkeypatch):
    index = tmp_path / "kb.sqlite3"
    build_index(index)
    manifest = tmp_path / "corpora.json"
    manifest.write_text('{"sources": [{"name": "creator-docs", "repo": "r", "branch": "main", "licence": "l", '
                        '"attribution": "a", "content_root": "content/en-us", "public_base": "https://example.invalid"}]}')
    monkeypatch.setattr(store, "_git", lambda repo, *args: "c0ffee")

    def one_doc(root, base):
        from starkb.chunking import Chunk, Doc
        doc = Doc(path="only.md", kind="guide", title="Only", url=base + "/only")
        doc.chunks.append(Chunk(kind="guide", heading="Only", anchor="", text="one small page", idents=""))
        yield doc

    def broken(root, base):
        yield from one_doc(root, base)
        raise OSError("checkout is damaged")

    def state():
        db = store.connect(index)
        try:
            return (db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'tween'").fetchone()[0],
                    db.execute("SELECT value FROM meta WHERE name='built_at'").fetchone()[0])
        finally:
            db.close()

    before = state()
    assert before[:2] == (3, 1)
    monkeypatch.setitem(store.WALKERS, "creator-docs", one_doc)          # 1 chunk where there were 3
    with pytest.raises(store.RebuildRefused):
        store.build(index, tmp_path, manifest)
    assert state() == before
    monkeypatch.setitem(store.WALKERS, "creator-docs", broken)
    with pytest.raises(OSError):
        store.build(index, tmp_path, manifest, force=True)
    assert state() == before
    monkeypatch.setitem(store.WALKERS, "creator-docs", one_doc)
    stats = store.build(index, tmp_path, manifest, force=True)          # the owner insists
    assert stats["_all"]["chunks"] == 1 and stats["_all"]["texts_removed"] == 3 and state()[0] == 1


def test_mode_names():
    assert parse_mode("vector") == ("vector", {"fallback": False, "questions": False, "facets": False})
    assert parse_mode("vector+q+fallback") == ("vector", {"fallback": True, "questions": True, "facets": False})
    assert parse_mode("hybrid+rerank") == ("hybrid+rerank", {"fallback": False, "questions": False, "facets": False})
    assert parse_mode("vector+f")[1]["facets"] is True and parse_mode("bm25+frrf")[1]["facet_merge"] == "rrf"
    assert parse_mode("hybrid+lw0.3+rr")[1] == {"fallback": False, "questions": False, "facets": False,
                                                "remote_rerank_n": 10, "lexical_weight": 0.3}
    with pytest.raises(ValueError):
        parse_mode("bm25+magic")
    with pytest.raises(ValueError):
        parse_mode("hybrid+lwx")


def test_weighted_rrf_lets_the_vector_list_win_ties():
    lexical, dense = [(1, 9.0), (2, 8.0)], [(2, 0.9), (1, 0.8)]
    assert search.Searcher.rrf(lexical, dense)[0][1] == search.Searcher.rrf(dense, lexical)[0][1]   # plain RRF: a tie
    assert [cid for cid, _ in search.Searcher.rrf(lexical, dense, weights=(0.1, 1.0))] == [2, 1]
    assert [cid for cid, _ in search.Searcher.rrf(lexical, dense, weights=(1.0, 0.1))] == [1, 2]


def test_long_prompts_are_also_searched_sentence_by_sentence(tmp_path):
    short = "How do I tween a part?"
    long = ("Write a server script that saves coins with a data store when the player leaves. "
            "Also tween the door open over two seconds; and fire a remote event to every client afterwards.")
    assert search.split_facets(short) == []
    assert search.split_facets("x" * 400) == []                      # one sentence: nothing to split
    parts = search.split_facets(long)
    assert len(parts) == 3 and parts[1].startswith("Also tween the door")
    assert search.merge_facets([(1, 0.5), (2, 0.4)], [[(3, 0.9), (1, 0.2)]], "max") == [(3, 0.9), (1, 0.5), (2, 0.4)]
    fused = search.merge_facets([(1, 9.0), (2, 8.0)], [[(2, 1.0)], [(3, 1.0)]], "rrf")
    assert [cid for cid, _ in fused] == [2, 1, 3]                    # 2 is in two lists; the whole prompt counts twice

    index = tmp_path / "kb.sqlite3"
    build_index(index)

    class Brain:
        requests = []

        def embed(self, texts):
            self.requests.append(list(texts))
            # the whole prompt points at nothing indexed; the "tween" sentence points at chunk 1
            return [[1.0, 0.0, 0.0, 0.0] if "tween the door" in t and not t.endswith("afterwards.") else [0.0, 0.0, 0.0, 1.0]
                    for t in texts], 0

    brain = Brain()
    searcher = search.Searcher(index, brain=brain)
    plain, _ = searcher.search(long, mode="vector", top=1, facets=False)
    faceted, timing = searcher.search(long, mode="vector", top=1, facets=True)
    assert plain[0].score == 0.0
    assert faceted[0].heading == "TweenService > Create" and faceted[0].score == 1.0 and timing["facets"] == 3.0
    assert len(brain.requests[-1]) == 4 and all(t.startswith(search.QUERY_PREFIX) for t in brain.requests[-1])   # one request
    lexical, _ = searcher.search(long, mode="bm25", top=3, facets=True)
    assert lexical and searcher.search(short, mode="bm25", top=1, facets=True)[1].get("facets") is None
    searcher.close()
