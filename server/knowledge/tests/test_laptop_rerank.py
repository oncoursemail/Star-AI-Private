"""Remote (laptop) reranker: fallback to the brain's reranker and the 60 s skip after a failure, plus the worker's
HTTP contract with a stub model. Real local HTTP servers on 127.0.0.1; no GPU, no torch, no `requests` package.

    python -m pytest -q server/knowledge/tests/test_laptop_rerank.py
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "laptop"))

from starkb import client  # noqa: E402
import rerank_worker  # noqa: E402


class FakeWorker(BaseHTTPRequestHandler):
    """mode: ok (reverse order), slow (sleeps past the client timeout), error (HTTP 500), garbage (bad index)."""
    mode = "ok"
    calls = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        type(self).calls += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.mode == "slow":
            time.sleep(1.0)
        if self.mode == "error":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        n = len(body["documents"])
        results = [{"index": 99 if self.mode == "garbage" else i, "relevance_score": float(i)} for i in reversed(range(n))]
        data = json.dumps({"results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def worker():
    FakeWorker.mode, FakeWorker.calls = "ok", 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWorker)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def brain_with(remote):
    """A Brain whose own /v1/rerank is a recorder (no `requests`, no network to a brain)."""
    brain = object.__new__(client.Brain)
    brain.remote_rerank, brain.last_rerank_source = remote, ""
    brain.local_calls = []

    def post(path, payload, retries=None):
        brain.local_calls.append(payload)
        return {"results": [{"index": i, "relevance_score": 1.0 - i / 10} for i in range(len(payload["documents"]))]}

    brain._post = post
    return brain


def remote_for(server, clock, timeout=0.3):
    return client.RemoteReranker(f"http://127.0.0.1:{server.server_address[1]}", "no-such-key-file",
                                 timeout=timeout, clock=clock)


def test_remote_answer_is_used(worker):
    brain = brain_with(remote_for(worker, Clock()))
    assert brain.rerank("q", ["a", "b", "c"]) == [(2, 2.0), (1, 1.0), (0, 0.0)]
    assert brain.last_rerank_source == "remote" and brain.local_calls == []


@pytest.mark.parametrize("mode", ["slow", "error", "garbage"])
def test_bad_remote_falls_back_then_is_skipped_for_60s(worker, mode):
    FakeWorker.mode = mode
    clock = Clock()
    brain = brain_with(remote_for(worker, clock))
    started = time.perf_counter()
    assert brain.rerank("q", ["a", "b"]) == [(0, 1.0), (1, 0.9)]          # the brain's own order
    assert time.perf_counter() - started < 0.9                           # the timeout (0.3 s) cut the slow call
    assert brain.last_rerank_source == "brain" and FakeWorker.calls == 1
    FakeWorker.mode = "ok"
    clock.now += 59
    brain.rerank("q", ["a", "b"])
    assert FakeWorker.calls == 1 and len(brain.local_calls) == 2         # still cooling down: no remote call
    clock.now += 2
    assert brain.rerank("q", ["a", "b"]) == [(1, 1.0), (0, 0.0)]
    assert brain.last_rerank_source == "remote" and FakeWorker.calls == 2


def test_worker_down_falls_back():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWorker)
    port = server.server_address[1]
    server.server_close()                                                # nothing listens there now
    brain = brain_with(client.RemoteReranker(f"http://127.0.0.1:{port}", "none", timeout=0.3, clock=Clock()))
    assert brain.rerank("q", ["a"]) == [(0, 1.0)]
    assert brain.last_rerank_source == "brain"
    assert brain.remote_rerank.down_until > 1000.0


def test_off_unless_url_is_set(monkeypatch):
    monkeypatch.delenv("STAR_KB_RERANK_URL", raising=False)
    assert client.RemoteReranker.from_env() is None
    monkeypatch.setenv("STAR_KB_RERANK_URL", "http://192.0.2.9:8092/")
    monkeypatch.setenv("STAR_KB_RERANK_TIMEOUT", "2")
    remote = client.RemoteReranker.from_env()
    assert remote.url == "http://192.0.2.9:8092" and remote.timeout == 2.0


# --- the worker (server/knowledge/laptop/rerank_worker.py) with a stub model ---

class StubModel:
    name, model, device, on_gpu = "stub", None, "cpu", False

    def score(self, query, documents):
        return [float(len(d)) for d in documents]


@pytest.fixture
def real_worker():
    server = ThreadingHTTPServer(("127.0.0.1", 0), rerank_worker.make_handler(StubModel(), "k3y"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def call(url, body, key="k3y"):
    request = urllib.request.Request(url + "/v1/rerank", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_worker_contract(real_worker):
    with urllib.request.urlopen(real_worker + "/health", timeout=5) as response:
        assert json.loads(response.read())["ok"] is True
    reply = call(real_worker, {"query": "q", "documents": ["aa", "a", "aaa"], "top_n": 2})
    assert reply["results"] == [{"index": 2, "relevance_score": 3.0}, {"index": 0, "relevance_score": 2.0}]
    # the client reads the worker's reply unchanged
    remote = client.RemoteReranker(real_worker, "none", clock=Clock())
    remote.key = "k3y"
    assert remote.rerank("q", ["aa", "a"], 2) == [(0, 2.0), (1, 1.0)]


@pytest.mark.parametrize("body,key,status", [
    ({"query": "q", "documents": ["a"]}, "wrong", 401),
    ({"query": "q", "documents": []}, "k3y", 400),
    ({"query": "q", "documents": [1]}, "k3y", 400),
    ({"documents": ["a"]}, "k3y", 400),
])
def test_worker_refuses(real_worker, body, key, status):
    with pytest.raises(urllib.error.HTTPError) as err:
        call(real_worker, body, key)
    assert err.value.code == status


def test_lan_only():
    assert rerank_worker.is_lan("fd12::1") and rerank_worker.is_lan("127.0.0.1")
    assert not rerank_worker.is_lan("8.8.8.8") and not rerank_worker.is_lan("not-an-ip")


# --- the live search path: `vector` + remote rerank, and plain `vector` when the remote fails ---

def test_vector_search_reranks_remotely_and_keeps_vector_order_when_remote_fails(tmp_path):
    pytest.importorskip("numpy")
    from starkb import search
    from test_walkers_scope import QueryBrain, _index, _vectors

    class RerankBrain(QueryBrain):
        remote_rerank = object()        # "a remote is configured"

        def __init__(self, vector, fail):
            super().__init__(vector)
            self.fail, self.calls = fail, []

        def rerank(self, query, documents, top_n=None, local_fallback=True):
            self.calls.append((len(documents), local_fallback))
            if self.fail:
                raise client.RerankUnavailable("down")
            return [(i, float(i)) for i in range(len(documents))]

    db_path = _index(tmp_path)
    _vectors(db_path, {"creator-docs": [1, 0, 0], "wiki": [0, 1, 0]})
    for fail in (False, True):
        brain = RerankBrain([0.3, 0.9, 0.3], fail)
        searcher = search.Searcher(db_path, brain=brain)
        plain, timing = searcher.search("tweening", mode="vector", top=5, scope="all")
        assert brain.calls == [] and "rerank_ms" not in timing          # remote_rerank_n=0: unchanged behaviour
        passages, timing = searcher.search("tweening", mode="vector", top=5, scope="all", remote_rerank_n=10)
        assert brain.calls == [(2, False)]                              # never the brain's slow reranker
        assert timing.get("rerank_remote" if not fail else "rerank_skipped") == 1.0
        assert [p.chunk_id for p in passages] == [p.chunk_id for p in plain]   # 2 items: RRF keeps the tie order
        assert [p.score for p in passages] == [p.score for p in plain]        # scores stay cosines
