"""STAR's system self-model (server/mesh/selfmodel): collector on fake sources, brief text, self-question detection,
reports store, the HTTP service with auth, and code.py's pure parts."""
from __future__ import annotations

import http.client
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.selfmodel import brief, code, collect, reports, service  # noqa: E402
sys.path.remove(str(ROOT / "server"))

KEY = "client-key-for-tests"
TOKEN = "mesh-token-for-tests"

STATUS = {
    "router": {"version": "3", "uptime_s": 100},
    "brain": {"name": "brain1", "healthy": True, "tok_s": 10.7, "inflight": 0},
    "instant": {"cache": {"entries": 10, "hits": 2}},
    "nodes": [
        {"name": "owner-pc", "state": "busy", "reason": "only 1415 MB of graphics memory is free (6175 MB needed)",
         "usable": False, "tok_s": 20.6, "inflight": 0, "served": 6, "last_error": "no first token within 45 s",
         "gpu": {"name": "NVIDIA GeForce RTX 3060 Ti", "vram_total_mb": 8192, "vram_free_mb": 1415, "util": 0},
         "models": [{"id": "litha-fast", "loaded": False}]},
        {"name": "star-pc", "state": "idle", "reason": "", "usable": True, "tok_s": 42.5, "inflight": 0, "served": 28,
         "last_error": "", "gpu": {"name": "NVIDIA GeForce RTX 4060", "vram_total_mb": 8188, "vram_free_mb": 680, "util": 3},
         "models": [{"id": "litha-fast", "loaded": True}]},
        {"name": "laptop", "state": "off", "reason": "unreachable (connect failed: TimeoutError)", "usable": False,
         "tok_s": 0.0, "inflight": 0, "served": 0, "last_error": "", "gpu": None, "models": []},
    ],
    "decisions": [
        {"model": "litha", "chosen": "star-pc", "ttft_ms": 900, "tok_s": 41.0, "errors": [], "outcome": "ok", "reason": "ranked"},
        {"model": "litha", "chosen": "star-pc", "ttft_ms": 1100, "tok_s": 39.0, "errors": [], "outcome": "ok"},
        {"model": "litha", "chosen": "brain1", "ttft_ms": 7600, "tok_s": 7.0, "errors": ["owner-pc: no first token"], "outcome": "ok"},
    ],
}
MODELS = {"data": [
    {"id": "litha-26b", "status": {"value": "loaded", "args": ["llama-server", "--ctx-size", "16384", "--threads", "24",
                                                               "--parallel", "1", "--model", "/m/gemma-4-26B_q4_0-it.gguf"]},
     "meta": {"size": 14423538808}},
    {"id": "star-deep", "status": {"value": "unloaded", "args": ["llama-server", "--model-draft", "/m/mtp.gguf",
                                                                 "--model", "/m/Qwen3.8-27B.gguf"]}},
]}
METRICS = "llamacpp:requests_processing 1\nllamacpp:requests_deferred 0\nllamacpp:predicted_tokens_seconds 12.25\n"

CFG = {
    "router_url": "http://router", "brain_url": "http://brain",
    "services": [{"name": "knowledge", "host": "brain1", "url": "http://k/health"},
                 {"name": "forgejo", "host": "brain1", "url": "http://forge/",
                  "version_regex": "VersionEncoded: encodeURIComponent\\('([^'~]+)"},
                 {"name": "images", "host": "brain1", "url": "http://img/health"}],
    "deployed_files": {"router": "/opt/star-mesh/app/mesh/router.py"},
    "machines": {"brain1": {"cpu": "EPYC 7451 24 cores", "role": "brain"}, "star-pc": {"cpu": "i7-9700", "gpu": "RTX 4060"}},
    "load_file": "/proc/loadavg",
}


def fake_fetch(seen):
    def fetch(url, headers, timeout):
        seen.append((url, "Authorization" in headers))
        if url == "http://router/mesh/status":
            return 200, json.dumps(STATUS).encode()
        if url == "http://brain/models":
            return 200, json.dumps(MODELS).encode()
        if url.startswith("http://brain/metrics?model=litha-26b"):
            return 200, METRICS.encode()
        if url == "http://k/health":
            return 200, b'{"ok": true, "service": "star-knowledge", "sources": [1, 2]}'
        if url == "http://forge/":
            return 200, b"<script>VersionEncoded: encodeURIComponent('17.0.1~gitea-1.22')</script>"
        raise ConnectionRefusedError("refused")
    return fetch


FILES = {"/opt/star-mesh/app/mesh/router.py": b"print('hi')\n", "/proc/loadavg": b"15.2 18.3 18.8 1/2 3\n"}


def read_file(p):
    if p in FILES:
        return FILES[p]
    raise OSError(p)


def snap():
    seen = []
    return collect.collect(CFG, KEY, fake_fetch(seen), read_file), seen


def test_collect_builds_one_view_from_existing_endpoints():
    s, seen = snap()
    nodes = {n["name"]: n for n in s["nodes"]}
    assert nodes["star-pc"]["state"] == "idle" and nodes["star-pc"]["model_loaded"] and nodes["star-pc"]["gpu"] == "NVIDIA GeForce RTX 4060"
    assert nodes["owner-pc"]["vram_free_mb"] == 1415
    m = {x["id"]: x for x in s["brain"]["models"]}
    assert m["litha-26b"]["loaded"] and m["litha-26b"]["ctx"] == 16384 and m["litha-26b"]["processing"] == 1
    assert m["litha-26b"]["tok_s_avg"] == 12.2 or m["litha-26b"]["tok_s_avg"] == 12.3
    assert m["star-deep"]["drafter"] and not m["star-deep"]["loaded"]
    assert s["brain"]["host_load"] == [15.2, 18.3, 18.8]
    svc = {x["name"]: x for x in s["services"]}
    assert svc["knowledge"]["ok"] and svc["forgejo"]["detail"] == "version=17.0.1" and not svc["images"]["ok"]
    assert s["router"]["recent"]["by_backend"] == {"star-pc": 2, "brain1": 1}
    assert s["router"]["recent"]["median_first_word_ms"] == 1100
    assert s["code"]["deployed"]["router"]["blob"] == collect.blob_id(b"print('hi')\n")
    wheres = [e["where"] for e in s["errors"]]
    assert "node owner-pc" in wheres and "service images" in wheres
    # the brain key goes only to the router and the brain, never to Forgejo/knowledge/images
    for url, authed in seen:
        assert authed == (url.startswith("http://router") or url.startswith("http://brain")), url


def test_blob_id_matches_git():
    assert collect.blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert collect.blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_collect_survives_every_source_down():
    def down(url, headers, timeout):
        raise TimeoutError("timed out")
    s = collect.collect(CFG, KEY, down, lambda p: (_ for _ in ()).throw(OSError(p)))
    assert s["nodes"] == [] and s["router"]["ok"] is False and s["brain"]["ok"] is False
    assert s["code"]["deployed"]["router"]["blob"] is None
    assert s["scheduling"]["free_gpus"] == []


def test_scheduling_uses_real_states():
    s, _ = snap()
    sch = s["scheduling"]
    assert [f["name"] for f in sch["free_gpus"]] == ["star-pc"] and sch["best_gpu"] == "star-pc"
    assert sch["brain_idle"] is False   # litha-26b is processing one request
    nodes = [{"name": "a", "state": "off", "reason": "the OFF file exists", "vram_free_mb": 7600, "inflight": 0, "gpu": "x"},
             {"name": "b", "state": "off", "reason": "the OFF file exists", "vram_free_mb": 400, "inflight": 0, "gpu": "y"}]
    sch = collect.scheduling(nodes, {"healthy": True, "models": [], "inflight": 0})
    assert [f["name"] for f in sch["free_gpus"]] == ["a"] and sch["brain_idle"] is True


SELF_QS = [
    "how are you running right now?", "what GPU are you on?", "why are you so slow today", "which server are you running on",
    "what's your gpu", "what version are you running", "are you learning anything at night?", "how fast are you",
    "Litha, why is your answer so slow", "how many GPUs do you have", "what model are you", "you seem slow",
]
NOT_SELF = [
    "how do I use the GPU for particles in Roblox?", "why is my game so slow on mobile", "write a server script for a shop",
    "what is a graphics card", "make the NPC run faster", "which model should I use for a car in Blender",
    "how do I train a neural network in python", "explain CPU cores to a kid",
]


def test_self_question_detection_is_narrow():
    for q in SELF_QS:
        assert brief.wants_self(q), q
    for q in NOT_SELF:
        assert not brief.wants_self(q), q


def test_brief_answers_from_measured_values():
    s, _ = snap()
    s["reports"] = {"training": {"state": "trained, held-out +2.1, safety same, promoted", "ts": time.time() - 3600},
                    "autotune": [{"node": "star-pc", "decision": "keep", "candidate": "ub 256", "tok_s": 45.0,
                                  "baseline_tok_s": 42.0, "quality": 10, "baseline_quality": 10, "ts": time.time()}],
                    "upgrade": [{"component": "llama.cpp", "current": "b11936", "latest": "b12001", "decision": "trial",
                                 "why": "newer release", "ts": time.time()}],
                    "evals": {"luau": [{"score": 71}, {"score": 74}]},
                    "code": {"branch": "star/next", "head": "29ce1dcfabc", "ci": {"state": "passing"}, "ts": time.time(),
                             "prs": [{"number": 770, "title": "litha smart", "services": ["router"]}],
                             "deployed": {"router": {"commit": "daef03c0123"}}}}
    gpu = brief.render(s, "gpu", backend="star-pc")
    assert "This reply is generated on star-pc (NVIDIA GeForce RTX 4060), ~42.5 tok/s" in gpu
    assert "owner-pc (NVIDIA GeForce RTX 3060 Ti): busy: only 1415 MB" in gpu
    assert "laptop (GPU ?): off: unreachable" in gpu
    assert "brain1 (EPYC 7451 24 cores, no GPU): healthy; loaded: litha-26b (12.2 tok/s avg)" in gpu.replace("12.3", "12.2")
    speed = brief.render(s, "speed")
    assert "median first word 1100 ms" in speed and "star-pc 2, brain1 1" in speed
    assert "Recent problem: node owner-pc: no first token within 45 s" in speed
    codetxt = brief.render(s, "code")
    assert "router daef03c0" in codetxt and "CI: passing" in codetxt and "PR #770" in codetxt
    learn = brief.render(s, "learning")
    assert "Autotuner" in learn and "keep ub 256 (45.0 vs 42.0 tok/s" in learn and "llama.cpp running b11936, latest b12001: trial" in learn
    assert "Eval luau: 71 -> 74" in learn
    assert len(brief.render(s, "all", max_chars=300)) <= 300
    assert brief.render({}) .startswith("System facts: the self-model has no data yet")


def test_topics():
    assert brief.topic_of("what GPU are you on") == "gpu"
    assert brief.topic_of("why are you so slow") == "speed"
    assert brief.topic_of("what version of your code is deployed") == "code"
    assert brief.topic_of("are you learning") == "learning"
    assert brief.topic_of("hello") == "all"


def test_reports_store_bounds_and_refuses_secrets(tmp_path):
    r = reports.Reports(tmp_path)
    assert r.add({"kind": "nope"})[0] is False
    assert r.add({"kind": "eval", "suite": "luau", "score": 70})[0]
    assert r.add({"kind": "error", "where": "x", "error": "Bearer abcdefghijklmnopqrstuvwxyz"})[0] is False
    for i in range(reports.KEEP + 5):
        r.add({"kind": "autotune", "node": "n", "decision": "reject", "i": i})
    assert len((tmp_path / "report-autotune.jsonl").read_text().splitlines()) == reports.KEEP
    summ = r.summary()
    assert summ["evals"]["luau"][0]["score"] == 70 and len(summ["autotune"]) == 12 and summ["autotune"][-1]["i"] == reports.KEEP + 4


def test_history_points(tmp_path):
    h = reports.History(tmp_path, every_s=300)
    s, _ = snap()
    assert h.maybe_add(s) and not h.maybe_add({**s, "ts": s["ts"] + 10}) and h.maybe_add({**s, "ts": s["ts"] + 301})
    pts = h.points()
    assert len(pts) == 2 and pts[0]["nodes"]["star-pc"] == ["idle", 42.5, 680] and pts[0]["busy"] == 1


def _serve(tmp_path):
    (tmp_path / "keys").write_text(f"# brain keys\n{KEY}\n")
    (tmp_path / "token").write_text(TOKEN + "\n")
    cfg = {**service.DEFAULTS, **CFG, "port": 0, "client_keys_file": str(tmp_path / "keys"),
           "mesh_token_file": str(tmp_path / "token"), "state_dir": str(tmp_path / "state")}
    srv = service.serve(cfg, fetch=fake_fetch([]), read_file=read_file, start_collector=False)
    srv.self_model.refresh()
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _req(srv, method, path, body=None, key=KEY):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request(method, path, body=json.dumps(body) if body is not None else None,
              headers={"Authorization": f"Bearer {key}"} if key else {})
    r = c.getresponse()
    return r.status, json.loads(r.read())


def test_service_auth_endpoints_and_reports(tmp_path):
    srv = _serve(tmp_path)
    try:
        assert _req(srv, "GET", "/health", key=None)[0] == 200
        assert _req(srv, "GET", "/mesh/self", key=None)[0] == 401
        assert _req(srv, "GET", "/mesh/self", key="wrong")[0] == 401
        st, view = _req(srv, "GET", "/mesh/self")
        assert st == 200 and {n["name"] for n in view["nodes"]} == {"owner-pc", "star-pc", "laptop"} and "reports" in view
        st, b = _req(srv, "GET", "/mesh/self/brief?q=what%20gpu%20are%20you%20on&backend=star-pc")
        assert st == 200 and b["self"] is True and b["topic"] == "gpu" and "star-pc" in b["text"]
        assert _req(srv, "GET", "/mesh/self/schedule")[1]["best_gpu"] == "star-pc"
        # a job reports with the mesh token; a client key works too; nothing else does
        assert _req(srv, "POST", "/mesh/self/report", {"kind": "eval", "suite": "luau", "score": 74}, key=TOKEN)[0] == 200
        assert _req(srv, "POST", "/mesh/self/report", {"kind": "training", "state": "idle"})[0] == 200
        assert _req(srv, "POST", "/mesh/self/report", {"kind": "eval"}, key="nope")[0] == 401
        assert _req(srv, "POST", "/mesh/self/report", {"kind": "bogus"})[0] == 400
        view = _req(srv, "GET", "/mesh/self")[1]
        assert view["reports"]["evals"]["luau"][-1]["score"] == 74 and view["reports"]["training"]["state"] == "idle"
        # the token is accepted only for reports, not for reading
        assert _req(srv, "GET", "/mesh/self", key=TOKEN)[0] == 401
    finally:
        srv.shutdown()
        srv.stop_collector.set()


def test_code_services_and_ci():
    assert code.services_of(["server/mesh/router.py", "server/mesh/node/node_agent.py", "star/agent.py", "x.txt"]) == \
        ["router", "gpu-node", "star-app", "other"]
    assert code.ci_state([])["state"] == "none"
    assert code.ci_state([{"name": "py", "status": "completed", "conclusion": "success"}])["state"] == "passing"
    assert code.ci_state([{"name": "py", "status": "completed", "conclusion": "failure"},
                          {"name": "ts", "status": "in_progress"}]) == {"state": "failing", "failing": ["py"], "checks": 2}


def test_code_commit_of_blob_on_a_real_repo(tmp_path):
    import subprocess
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(tmp_path)]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "server" / "mesh").mkdir(parents=True)
    f = tmp_path / "server" / "mesh" / "router.py"
    f.write_bytes(b"v1\n")
    subprocess.run(g + ["add", "."], check=True)
    subprocess.run(g + ["commit", "-qm", "one"], check=True)
    c1 = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    f.write_bytes(b"v2\n")
    subprocess.run(g + ["commit", "-qam", "two"], check=True)
    # pretend origin/star/next is this branch
    subprocess.run(g + ["update-ref", "refs/remotes/origin/star/next", "HEAD"], check=True)
    got = code.commit_of_blob(str(tmp_path), collect.blob_id(b"v1\n"), "server/mesh/router.py", "star/next")
    assert got == {"commit": c1, "newer_commits_on_branch": 1}
    assert code.commit_of_blob(str(tmp_path), collect.blob_id(b"local edit\n"), "server/mesh/router.py", "star/next")["commit"] is None


def test_router_forwards_and_puts_live_facts_in_front_of_a_self_question(tmp_path):
    import asyncio
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        from test_mesh_router import KEY as RKEY, Fake, call, setup   # the router's fakes
    finally:
        sys.path.remove(str(ROOT / "tests"))
    (tmp_path / "keys").write_text(RKEY + "\n")
    (tmp_path / "token").write_text(TOKEN + "\n")
    cfg = {**service.DEFAULTS, **CFG, "port": 0, "client_keys_file": str(tmp_path / "keys"),
           "mesh_token_file": str(tmp_path / "token"), "state_dir": str(tmp_path / "state")}
    srv = service.serve(cfg, fetch=fake_fetch([]), read_file=read_file, start_collector=False)
    srv.self_model.refresh()
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    async def go():
        node = Fake("star-pc", tok_s=40.0, words=("ok",))
        (tmp_path / "r").mkdir()
        r, port, brain = await setup(tmp_path / "r", [node], self_url=f"http://127.0.0.1:{srv.server_address[1]}",
                                     docs_url="http://127.0.0.1:9")
        chat = {"model": "litha", "stream": True, "messages": [
            {"role": "system", "content": "You are Litha."}, {"role": "user", "content": "what GPU are you on right now?"}]}
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        sent = node.requests[-1]["messages"]
        assert st == 200 and headers.get("X-Mesh-Self") == "gpu" and "X-Mesh-Docs" not in headers
        assert sent[0] == chat["messages"][0]                                   # cached prefix unchanged
        assert sent[-1]["content"].startswith("Live system facts about you")
        assert "This reply is generated on star-pc (NVIDIA GeForce RTX 4060)" in sent[-1]["content"]
        assert sent[-1]["content"].endswith("---\nwhat GPU are you on right now?")
        # not about herself: untouched (and docs were tried as before -> "late" since the docs URL is dead)
        chat["messages"][-1]["content"] = "how do I use the GPU for particles in Roblox?"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        assert "X-Mesh-Self" not in headers and node.requests[-1]["messages"][-1]["content"] == chat["messages"][-1]["content"]
        # opt-out header
        chat["messages"][-1]["content"] = "why are you so slow"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat,
                                                 headers={"X-Mesh-Self": "off"})
        assert "X-Mesh-Self" not in headers
        # forwarded reads through the router's address and key
        st, _, data = await asyncio.to_thread(call, port, "GET", "/mesh/self/schedule")
        assert st == 200 and json.loads(data)["best_gpu"] == "star-pc"
        st, _, data = await asyncio.to_thread(call, port, "GET", "/mesh/self/history?n=5")
        assert st == 200 and "points" in json.loads(data)
        # a node job reports through the router with the mesh token; a wrong token is refused by the self-model
        st, _, _ = await asyncio.to_thread(call, port, "POST", "/mesh/self/report",
                                           {"kind": "autotune", "node": "star-pc", "decision": "reject"}, TOKEN)
        assert st == 200 and srv.self_model.reports.last("autotune")[-1]["node"] == "star-pc"
        st, _, _ = await asyncio.to_thread(call, port, "POST", "/mesh/self/report", {"kind": "eval"}, "nope")
        assert st == 401
        st, _, _ = await asyncio.to_thread(call, port, "GET", "/mesh/self", None, TOKEN)
        assert st == 401                                                       # the token cannot read
        # self-model down: the answer goes on without facts
        r.cfg["self_url"] = "http://127.0.0.1:9"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        assert st == 200 and headers.get("X-Mesh-Self") == "late"
        assert not node.requests[-1]["messages"][-1]["content"].startswith("Live system facts")
    try:
        asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        srv.shutdown()
        srv.stop_collector.set()


def test_night_window_is_chicago_time():
    import datetime
    import pytest
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/Chicago")
    except Exception:
        pytest.skip("no tz database here (the container has one)")
    t = datetime.datetime(2026, 10, 29, 3, 30, tzinfo=datetime.timezone.utc).timestamp()
    assert collect.local_hour("America/Chicago", t) == 22     # 22:30 CDT: not night, although the UTC hour is 3
    assert collect.local_hour("UTC", t) == 3


def test_brief_shows_why_for_skipped_runs():
    s, _ = snap()
    s["reports"] = {"autotune": [{"node": "star-pc", "decision": "skip", "why": "outside the night window 01-06h",
                                  "ts": time.time()}]}
    assert "star-pc skip: outside the night window 01-06h" in brief.render(s, "learning")
