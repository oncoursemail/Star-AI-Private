"""Offline retrieval correctness, resource limits, fallback and service integration."""
from __future__ import annotations

import array
import concurrent.futures
import http.client
import json
import math
import random
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.docs import build, index, service  # noqa: E402
sys.path.remove(str(ROOT / "server"))


def blob(values):
    return array.array("f", values).tobytes()


def database(tmp_path, rows):
    path = tmp_path / "docs.db"
    with sqlite3.connect(path) as db:
        db.executescript(build.SCHEMA)
        db.execute("INSERT INTO meta VALUES ('meta', '{}')")
        for pid, vector in rows:
            db.execute("INSERT INTO passages VALUES (?, 'test', 'Tween', 'Move', ?, 'tween part position', ?)",
                       (pid, f"https://example.invalid/{pid}", vector))
            db.execute("INSERT INTO passages_fts(rowid,title,heading,body) VALUES (?, 'Tween', 'Move', 'tween part')",
                       (pid,))
    return path


def native():
    return pytest.importorskip("litha_search", reason="optional release-built Rust extension is not installed")


def open_index(path, backend):
    if backend == "rust":
        native()
    return index.DocsIndex(str(path), dense_backend=backend)


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_exact_top_k_matches_previous_method(tmp_path, backend):
    rng = random.Random(419)
    vectors = [(pid, array.array("f", (rng.uniform(-1, 1) for _ in range(96)))) for pid in range(1, 121)]
    path = database(tmp_path, [(pid, v.tobytes()) for pid, v in vectors])
    idx = open_index(path, backend)
    try:
        for _ in range(12):
            query = [rng.uniform(-1, 1) for _ in range(96)]
            norm = math.sqrt(math.fsum(x * x for x in query)) or 1.0
            q = array.array("f", (x / norm for x in query))
            old = sorted(((pid, index._dot(q, v)) for pid, v in vectors), key=lambda hit: -hit[1])[:8]
            actual = idx.dense(query)
            assert [pid for pid, _ in actual] == [pid for pid, _ in old]
            assert [s for _, s in actual] == pytest.approx([s for _, s in old], rel=1e-12, abs=1e-12)
        assert idx.vector_count == 120
        assert idx.vector_bytes == 120 * (96 * 4 + 8)
        if backend == "rust":
            assert idx.vectors == []  # no second persistent Python copy of the corpus
            assert idx.dense_backend == "rust"
    finally:
        idx.db.close()


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_ties_invalid_queries_and_k_boundaries(tmp_path, backend):
    path = database(tmp_path, [(99, blob([1, 0])), (7, blob([1, 0])), (8, blob([-1, 0]))])
    idx = open_index(path, backend)
    try:
        assert idx.dense([1, 0], 100) == [(7, 1.0), (99, 1.0), (8, -1.0)]
        assert idx.dense([0, 0], 2) == [(7, 0.0), (8, 0.0)]
        assert idx.dense([1e308, 0], 1) == [(7, 1.0)]
        for query in (None, [], [1], [1, 0, 0], [math.nan, 0], [math.inf, 1], ["bad", 0], 42):
            assert idx.dense(query) == []
        for k in (-4, 0, 1.5, True):
            assert idx.dense([1, 0], k) == []
        assert idx.dense([1, 0], 1) == [(7, 1.0)]
    finally:
        idx.db.close()


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_invalid_corpus_rows_are_skipped(tmp_path, backend):
    rows = [(1, b"x"), (2, b""), (3, blob([1, 0])), (4, blob([1, 2, 3])),
            (5, blob([math.nan, 0])), (6, blob([math.inf, 0])), (7, "not bytes"), (8, blob([0, 1]))]
    idx = open_index(database(tmp_path, rows), backend)
    try:
        assert idx.invalid_vectors == 6
        assert idx.vector_count == 2
        assert idx.vector_dimension == 2
        assert idx.dense([1, 0]) == [(3, 1.0), (8, 0.0)]
    finally:
        idx.db.close()


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_payload_limit_disables_whole_dense_index_but_preserves_bm25(tmp_path, backend):
    if backend == "rust":
        native()
    path = database(tmp_path, [(1, blob([1, 0])), (2, blob([0, 1]))])
    idx = index.DocsIndex(str(path), dense_backend=backend, dense_max_vector_bytes=16)
    try:
        assert idx.vector_count == 0
        assert idx.dense_backend == "disabled"
        assert idx.dense_backend_reason == "vector_resource_limit"
        assert idx.dense([1, 0]) == []
        assert idx.bm25("tween")
    finally:
        idx.db.close()


def test_missing_native_extension_falls_back_without_changing_results(tmp_path, monkeypatch):
    path = database(tmp_path, [(1, blob([1, 0]))])
    real_import = index.importlib.import_module

    def missing(name):
        if name == "litha_search":
            raise ImportError("not installed")
        return real_import(name)

    monkeypatch.setattr(index.importlib, "import_module", missing)
    idx = index.DocsIndex(str(path), dense_backend="rust")
    try:
        assert idx.dense_backend == "python"
        assert idx.dense_backend_reason == "native_unavailable"
        assert idx.dense([1, 0]) == [(1, 1.0)]
    finally:
        idx.db.close()


def test_default_does_not_import_native_and_load_vectors_false(tmp_path, monkeypatch):
    path = database(tmp_path, [(1, blob([1, 0]))])

    def forbidden(_name):
        raise AssertionError("default backend must not import the Rust extension")

    monkeypatch.setattr(index.importlib, "import_module", forbidden)
    idx = index.DocsIndex(str(path))
    unloaded = index.DocsIndex(str(path), load_vectors=False, dense_backend="rust")
    try:
        assert idx.dense([1, 0]) == [(1, 1.0)]
        assert unloaded.vector_count == 0
        assert unloaded.dense([1, 0]) == []
    finally:
        idx.db.close()
        unloaded.db.close()


def test_native_raw_api_bounds_compensation_and_concurrent_queries():
    module = native()
    rows = [(42, blob([1e20, 1, -1e20])), (3, blob([0, 1, 0])), (9, blob([0, -1, 0]))]
    idx = module.DenseIndex(iter(rows))
    query = blob([1, 1, 1])
    assert idx.search(query, 2) == [(42, 1.0), (3, 1.0)]
    with pytest.raises(ValueError, match="dimension"):
        idx.search(blob([1]), 2)
    with pytest.raises(ValueError, match="finite"):
        idx.search(blob([math.nan, 0, 0]), 2)
    with pytest.raises(ValueError, match="budget"):
        module.DenseIndex(iter(rows), 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        assert all(result == [(42, 1.0), (3, 1.0)]
                   for result in pool.map(lambda _: idx.search(query, 2), range(32)))


@pytest.mark.parametrize("budget", [16, 8])
def test_service_health_and_dense_block_use_native_count(tmp_path, monkeypatch, budget):
    native()
    path = database(tmp_path, [(1, blob([1, 0]))])
    key_file = tmp_path / "keys"
    key_file.write_text("local-test-key\n", encoding="utf-8")
    calls = []

    def embed(_cfg, _keys):
        def run(question):
            calls.append(question)
            return [1, 0]
        return run

    monkeypatch.setattr(service, "embedder", embed)
    cfg = {**service.DEFAULTS, "index": str(path), "port": 0, "client_keys_file": str(key_file),
           "dense_backend": "rust", "dense_in_block": True, "dense_max_vector_bytes": budget}
    srv = service.serve(cfg)
    worker = threading.Thread(target=srv.serve_forever, daemon=True)
    worker.start()

    def request(method, route, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
        conn.request(method, route, body=json.dumps(body) if body else None,
                     headers={"Authorization": "Bearer local-test-key", "Content-Type": "application/json"})
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        assert response.status == 200
        return payload

    try:
        health = request("GET", "/health")
        active = budget == 16
        assert health["dense_backend"] == ("rust" if active else "disabled")
        assert health["vectors"] == int(active)
        assert health["vector_payload_bytes"] == (16 if active else 0)
        assert request("POST", "/mesh/docs/block", {"question": "tween a part in roblox"})["dense"] is active
        assert request("GET", "/mesh/docs?q=tween")["dense"] is active
        assert calls == (["tween a part in roblox", "tween"] if active else [])
    finally:
        srv.shutdown()
        srv.server_close()
        worker.join(timeout=3)
