"""Embedding on another machine (offload.py) and the refresh's embedding limit. No network, no model, no GPU.

    python -m pytest -q server/knowledge/tests/test_offload.py
"""
from array import array
import io
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starkb import embed, offload, refresh, store  # noqa: E402

MODEL = "star-embed-ft1"
DIM = 4


def unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


class FakeServer:
    """Brain.embed contract; inputs over `max_chars` are refused like an over-long input on llama-server."""

    def __init__(self, max_chars: int = 10_000):
        self.max_chars, self.calls = max_chars, []

    def embed(self, texts):
        self.calls.append(list(texts))
        if any(len(t) > self.max_chars for t in texts):
            raise RuntimeError("/v1/embeddings returned HTTP 500: input is too large to process")
        return [unit(len(t), 1.0, 2.0, 3.0) for t in texts], 0


def make_index(tmp_path: Path, texts: dict[str, str], embedded: dict[str, list[float]]) -> Path:
    index = tmp_path / "kb.sqlite3"
    db = store.connect(index)
    doc = db.execute("INSERT INTO docs(source,path,kind,title,url) VALUES('s','p','guide','T','u')").lastrowid
    for order, (sha, text) in enumerate(texts.items()):
        db.execute("INSERT INTO chunks(doc_id,ord,kind,heading,anchor,text,idents,text_sha) VALUES(?,?,'guide','T','',?,'',?)",
                   (doc, order, text, sha))
    for sha, vec in embedded.items():
        db.execute("INSERT INTO embeddings VALUES(?,?,?,?,'t')", (sha, MODEL, len(vec), array("f", vec).tobytes()))
    db.commit()
    db.close()
    return index


def stored(index: Path) -> dict[str, list[float]]:
    db = store.connect(index)
    try:
        return {r[0]: list(array("f", r[1])) for r in db.execute("SELECT text_sha, vec FROM embeddings WHERE model=?", (MODEL,))}
    finally:
        db.close()


SHA = {name: (name * 64)[:64] for name in "abcd"}       # hex text hashes, as the index stores them


def test_export_lists_only_texts_without_a_vector_with_the_exact_embedding_input(tmp_path):
    index = make_index(tmp_path, {SHA["a"]: "first", SHA["b"]: "second"}, {SHA["a"]: unit(1, 0, 0, 0)})
    out = io.StringIO()
    assert offload.export_pending(index, out, MODEL) == 1
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    assert rows == [{"sha": SHA["b"], "input": store.embed_input("T", "T", "second")}]


def test_embed_file_resumes_after_a_kill_mid_record_and_shortens_like_the_brain(tmp_path):
    pending = tmp_path / "pending.jsonl"
    pending.write_text("".join(json.dumps({"sha": SHA[n], "input": n * size}) + "\n"
                               for n, size in (("a", 3), ("b", 50), ("c", 5))), encoding="utf-8")
    out = tmp_path / "vectors.bin"
    out.write_bytes(bytes.fromhex(SHA["a"]) + array("f", unit(3, 1, 2, 3)).tobytes() + b"\x01\x02")   # a cut record
    server = FakeServer(max_chars=20)
    result = offload.embed_file(server, pending, out, batch=8, dim=DIM, log=lambda _m: None)
    assert result == {"embedded_now": 2, "left": 0, "shortening_retries": 5}
    assert out.stat().st_size == 3 * offload.record_size(DIM)
    with out.open("rb") as handle:
        records = dict(offload.read_records(handle, DIM))
    assert set(records) == {SHA["a"], SHA["b"], SHA["c"]}
    assert all(len(t) <= 20 for t in server.calls[-2])            # "b" was cut 50 -> 42 -> 35 -> 29 -> ... -> fits
    assert offload.embed_file(server, pending, out, batch=8, dim=DIM, log=lambda _m: None)["embedded_now"] == 0


def test_embed_file_stops_when_the_gate_says_so(tmp_path):
    pending = tmp_path / "pending.jsonl"
    pending.write_text("".join(json.dumps({"sha": SHA[n], "input": n}) + "\n" for n in "abc"), encoding="utf-8")
    answers = iter([True, False])
    result = offload.embed_file(FakeServer(), pending, tmp_path / "v.bin", batch=2, dim=DIM,
                                gate=lambda: next(answers), log=lambda _m: None)
    assert result["embedded_now"] == 2 and result["left"] == 1


def test_import_adds_new_vectors_only_and_never_replaces_or_trusts_bad_ones(tmp_path):
    brain_vec = unit(1, 0, 0, 0)
    index = make_index(tmp_path, {SHA["a"]: "x", SHA["b"]: "y", SHA["c"]: "z"}, {SHA["a"]: brain_vec})
    records = b"".join(bytes.fromhex(SHA[n]) + array("f", vec).tobytes() for n, vec in (
        ("a", unit(0, 1, 0, 0)),        # the brain already has one: kept as it is
        ("b", unit(1, 2, 3, 4)),        # new
        ("c", [2.0, 0.0, 0.0, 0.0]),    # not unit length: refused
        ("d", unit(4, 3, 2, 1))))       # no longer in the index
    waits = []
    counts = offload.import_vectors(index, io.BytesIO(records), MODEL, dim=DIM, batch=2, log=lambda _m: None,
                                    wait=lambda log, stop: waits.append(1))
    assert counts == {"read": 4, "inserted": 1, "already": 1, "unknown": 1, "bad": 1, "embeddings_total": 2}
    vectors = stored(index)
    assert vectors[SHA["a"]] == brain_vec and set(vectors) == {SHA["a"], SHA["b"]}
    assert len(waits) == 1                   # one batch of two valid rows, one quiet-lock check before it
    db = store.connect(index)
    assert embed.pending(db, MODEL) == [(SHA["c"], store.embed_input("T", "T", "z"))]
    db.close()


def test_sample_and_compare_report_cosine_to_the_stored_vectors(tmp_path):
    text = "abc"
    vec = FakeServer().embed([store.embed_input("T", "T", text)])[0][0]
    index = make_index(tmp_path, {SHA["a"]: text, SHA["b"]: "other"}, {SHA["a"]: vec, SHA["b"]: unit(0, 0, 0, 1)})
    sample = tmp_path / "sample.jsonl"
    with sample.open("w", encoding="utf-8") as out:
        assert offload.sample_existing(index, out, MODEL, n=10) == 2
    result = offload.compare_sample(FakeServer(), sample)
    assert result["n"] == 2 and result["below_0.999"] == 1 and result["median"] > 0.999


def test_refresh_embeds_at_most_the_limit_and_leaves_the_rest_for_the_offload(tmp_path, monkeypatch):
    home, app = tmp_path / "home", tmp_path / "app"
    (home / "data").mkdir(parents=True)
    app.mkdir()
    (app / "corpora.json").write_text('{"sources": []}')
    index = make_index(home / "data", {SHA["a"]: "x"}, {})
    monkeypatch.setattr(refresh, "lock_held", lambda: False)
    monkeypatch.setattr(refresh, "_git", lambda *a, **k: "")
    monkeypatch.setattr(refresh, "build", lambda *a, **k: {"_all": {"texts_added": 5000, "texts_removed": 0}})
    seen = {}

    def fake_embed(db_path, **kw):
        seen.update(kw)
        return {"embedded_now": 3000, "pending_before": 3000}
    monkeypatch.setattr(embed, "run", fake_embed)
    fetch = lambda sources_dir, config: [{"name": "s", "repo": sources_dir / "s", "old": "a" * 40, "new": "b" * 40}]
    result = refresh.run(index, home, app, log=lambda _m: None, stop=lambda: False, fetch=fetch, check=False,
                         embed_limit=3000)
    assert seen["limit"] == 3000 and result["embed_left"] == "offload"
    assert "embedded_now=3000 embed_left=offload" in (home / "data" / refresh.REPORT_NAME).read_text()
    seen.clear()
    result = refresh.run(index, home, app, log=lambda _m: None, stop=lambda: False, fetch=fetch, check=False,
                         embed_limit=0)
    assert seen["limit"] is None and "embed_left" not in result


class FakeProbe:
    def __init__(self, idle=3600.0, processes=None, gpu=None):
        self.idle, self.names, self.gpu = idle, processes or {1: "explorer.exe"}, gpu or {}

    def idle_seconds(self):
        return self.idle

    def fullscreen(self):
        return False

    def processes(self):
        return self.names

    def gpu_users(self):
        return self.gpu


def gate(tmp_path, probe, clock=lambda: 0.0):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
    import gpu_embed
    config = {**gpu_embed.turbo.DEFAULTS}
    return gpu_embed.Gate(tmp_path, config, probe=probe, clock=clock, hour=lambda: 12)


def test_gpu_job_starts_only_when_the_owner_is_away_and_nothing_else_uses_the_card(tmp_path):
    assert gate(tmp_path, FakeProbe()).start_blocker() == ""
    assert gate(tmp_path, FakeProbe(idle=600)).start_blocker() == "the owner is active"      # 10 of 20 min by day
    assert "RobloxStudioBeta.exe" in gate(tmp_path, FakeProbe(processes={7: "RobloxStudioBeta.exe"})).start_blocker()
    assert "llama-server" in gate(tmp_path, FakeProbe(processes={8: "llama-server.exe"})).start_blocker()
    assert "graphics card" in gate(tmp_path, FakeProbe(processes={9: "game.exe"}, gpu={9: 60.0})).start_blocker()
    (tmp_path / "OFF").write_text("")
    assert gate(tmp_path, FakeProbe()).start_blocker().startswith("off")


def test_gpu_job_stops_on_input_and_ignores_its_own_server(tmp_path):
    now = [0.0]
    probe = FakeProbe(processes={5: "llama-server.exe"}, gpu={5: 95.0})
    g = gate(tmp_path, probe, clock=lambda: now[0])
    g.own = {5}
    assert g.start_blocker() == ""
    now[0] = 20.0
    assert g.stop_reason() == ""
    probe.idle = 2.0
    assert g.stop_reason() == "the owner is back"
