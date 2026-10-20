"""star.priority_proxy: scheduler rules, continuation requests, and the proxy end to end against a fake llama.cpp
server that streams numbered words, honours continue_final_message and frees a slot when its client disconnects."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import threading
import time

import pytest

from star import priority_proxy as pp


# --- scheduler ------------------------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_sched(slots=2, bg_cap=0, solo=False, grace=2.0):
    cfg = pp.Config(solo_p0=solo, grace_s=grace, models={"m": pp.ModelPolicy("m", slots, bg_cap, ("alias",))})
    clock = Clock()
    return pp.Scheduler(cfg, clock=clock), clock


def start(sched, cls, cancelled=None):
    """Queue a job without blocking; returns it (running or queued)."""
    job = sched.new_job(cls, "m")
    with sched._cv:
        job.state, job.queued_at = "queued", sched._clock()
        sched._queued.append(job)
        sched._schedule()
    if cancelled is not None:
        sched.attach(job, lambda: cancelled.append(job))
    return job


def test_background_fills_every_slot_and_p0_pauses_the_newest_lowest():
    sched, _ = make_sched(slots=2)
    cancelled: list = []
    p2 = start(sched, 2, cancelled)
    p3 = start(sched, 3, cancelled)
    assert p2.state == p3.state == "running"
    p0 = start(sched, 0)
    assert p0.state == "queued"
    assert p3.state == "pausing" and p2.state == "running"      # P3 goes before P2
    assert cancelled == [p3]
    sched.paused(p3)
    assert p0.state == "running"
    assert sched.stats[3].preemptions == 1


def test_one_pause_per_waiting_urgent_request():
    sched, _ = make_sched(slots=2)
    a, b = start(sched, 3), start(sched, 3)
    start(sched, 0)
    assert sorted([a.state, b.state]) == ["pausing", "running"]
    assert b.state == "pausing"                                  # the newest of the same class
    start(sched, 1)
    assert a.state == "pausing"


def test_equal_or_higher_priority_is_never_paused():
    sched, _ = make_sched(slots=1)
    first = start(sched, 1)
    second = start(sched, 1)
    assert first.state == "running" and second.state == "queued"
    urgent = start(sched, 0)
    assert first.state == "pausing" and urgent.state == "queued"   # P0 pauses P1, a P1 never pauses a P1


def test_not_preemptible_job_is_left_alone():
    sched, _ = make_sched(slots=1)
    job = start(sched, 3)
    assert sched.set_preemptible(job, False)
    start(sched, 0)
    assert job.state == "running"


def test_background_cap():
    sched, _ = make_sched(slots=3, bg_cap=2)
    jobs = [start(sched, 3) for _ in range(3)]
    assert [j.state for j in jobs] == ["running", "running", "queued"]
    chat = start(sched, 0)
    assert chat.state == "running"                               # the third slot stays free for P0/P1


def test_solo_p0_pauses_all_background_and_holds_it_for_the_grace_period():
    sched, clock = make_sched(slots=3, solo=True, grace=2.0)
    bg = [start(sched, 3), start(sched, 2)]
    p1 = start(sched, 1)
    p0 = start(sched, 0)
    assert p0.state == "queued" and p1.state == "running"        # all three slots taken until a pause lands
    assert [j.state for j in bg] == ["pausing", "pausing"]
    sched.paused(bg[0])
    assert p0.state == "running"
    for job in bg:
        if job.state == "pausing":
            sched.paused(job)
    for job in bg:
        sched.paused(job)
        with sched._cv:
            job.state = "queued"
            sched._queued.append(job)
            sched._schedule()
    assert sched.p0_active()
    sched.release(p0)
    assert [j.state for j in bg] == ["queued", "queued"]          # grace: a quick follow-up keeps the CPU
    clock.now += 2.5
    with sched._cv:
        sched._schedule()
    assert [j.state for j in bg] == ["running", "running"]
    assert not sched.p0_active()


def test_slot_affinity_keeps_a_paused_answer_its_slot():
    sched, _ = make_sched(slots=3)
    bg = start(sched, 3)
    assert sched.take_slot(bg, set()) == 0                      # background takes the lowest free slot
    other = start(sched, 3)
    assert sched.take_slot(other, {0}) == 1
    sched._pause(bg)
    sched.paused(bg)
    chat = start(sched, 0)
    assert sched.take_slot(chat, set(), wanted=0) == 2           # not the slot a paused answer waits for
    sched.release(chat)
    with sched._cv:
        bg.state = "queued"
        sched._queued.append(bg)
        sched._schedule()
    assert bg.state == "running" and sched.take_slot(bg, set()) == 0     # its own slot again: its cache is there
    late = start(sched, 1)
    assert sched.take_slot(late, {2}) is None                    # 0 and 1 ours, 2 used by another client


def test_slot_affinity_skips_slots_another_client_uses():
    sched, _ = make_sched(slots=2)
    job = start(sched, 0)
    assert sched.take_slot(job, {1}, wanted=1) == 0
    assert sched.take_slot(job, {0, 1}) is None and job.slot is None


def test_acquire_raises_gone_when_the_client_leaves():
    sched, _ = make_sched(slots=1)
    start(sched, 2)
    job = sched.new_job(3, "m")
    with pytest.raises(pp.Gone):
        sched.acquire(job, gone=lambda: True, poll_s=0.01)
    assert job.state == "done" and not sched._queued


# --- continuation ---------------------------------------------------------------------------------------------------

def test_chat_continuation_appends_the_text_so_far_and_cuts_the_budget():
    req = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}
    ans = pp.Answer("chat", content="Hello wor", completion_tokens=3)
    out = pp.continuation("chat", req, ans)
    assert out is not None
    assert out["messages"][-1] == {"role": "assistant", "content": "Hello wor"}
    assert out["continue_final_message"] is True and out["add_generation_prompt"] is False
    assert out["max_tokens"] == 47
    assert req["messages"] == [{"role": "user", "content": "hi"}]          # the original is untouched


def test_continuation_merges_a_client_prefill_and_keeps_reasoning():
    req = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "```lua\n"}]}
    out = pp.continuation("chat", req, pp.Answer("chat", content="local x", reasoning="think"))
    assert out is not None
    assert out["messages"][-1] == {"role": "assistant", "content": "```lua\nlocal x", "reasoning_content": "think"}
    assert len(out["messages"]) == 2
    only_reasoning = pp.continuation("chat", {"messages": [{"role": "user", "content": "q"}]},
                                     pp.Answer("chat", reasoning="hmm"))
    assert only_reasoning is not None and only_reasoning["continue_final_message"] == "reasoning_content"


def test_continuation_text_completion_and_budget_used_up():
    assert pp.continuation("text", {"prompt": "a", "n_predict": 4}, pp.Answer("text", content="bc",
                                                                              completion_tokens=2)) == \
        {"prompt": "abc", "n_predict": 2}
    assert pp.continuation("text", {"prompt": "a", "max_tokens": 2}, pp.Answer("text", content="bc",
                                                                               completion_tokens=2)) is None
    assert pp.continuation("chat", {"messages": [{"role": "user", "content": "q"}]}, pp.Answer("chat")) == \
        {"messages": [{"role": "user", "content": "q"}]}                  # nothing generated: same request


def test_continuable():
    msgs = [{"role": "user", "content": "q"}]
    assert pp.continuable("chat", {"messages": msgs, "tools": [{"type": "function"}]})
    assert not pp.continuable("chat", {"messages": msgs, "grammar": "root ::= x"})
    assert not pp.continuable("chat", {"messages": msgs, "response_format": {"type": "json_object"}})
    assert not pp.continuable("chat", {"messages": msgs, "n": 2})
    assert not pp.continuable("text", {"prompt": [1, 2, 3]})
    assert pp.continuable("text", {"prompt": "x"})


def test_answer_absorbs_stream_chunks():
    ans = pp.Answer("chat")
    ans.absorb({"id": "c1", "created": 5, "model": "m", "choices": [{"delta": {"role": "assistant", "content": None}}]})
    assert ans.absorb({"choices": [{"delta": {"content": "Hi"}}], "timings": {"predicted_n": 1}})
    ans.absorb({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "t", "function": {"name": "f",
                                                                                          "arguments": "{"}}]}}]})
    ans.absorb({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}}]})
    ans.absorb({"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "timings": {"predicted_n": 7}})
    ans.absorb({"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 7}})
    ans.end_segment()
    out = ans.response()
    assert out["id"] == "c1" and out["choices"][0]["finish_reason"] == "tool_calls"
    assert out["choices"][0]["message"]["tool_calls"] == [{"id": "t", "type": "function",
                                                           "function": {"name": "f", "arguments": "{}"}}]
    assert out["usage"] == {"prompt_tokens": 9, "completion_tokens": 7, "total_tokens": 16}
    assert not ans.exact


# --- end to end against a fake llama.cpp ----------------------------------------------------------------------------

NATURAL_END = 40


def words(start: int, stop: int) -> str:
    return "".join(f"w{i} " for i in range(start, stop))


class FakeLlama:
    """Answers are 'w0 w1 ... ' (NATURAL_END words, or max_tokens). A continuation starts after the words already in
    the assistant prefix. `slots` requests generate at once; a disconnected client frees its slot."""

    def __init__(self, slots: int, delay: float = 0.02):
        self.slots, self.delay = slots, delay
        self.free = threading.Semaphore(slots)
        self.lock = threading.Lock()
        self.busy = self.max_busy = 0
        self.requests: list[dict] = []
        self.cancelled = 0
        self.slot_busy: dict[int, bool] = {}
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return

            def _json(self, data):
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path.startswith("/props"):
                    self._json({"total_slots": fake.slots})
                elif self.path.startswith("/slots"):
                    with fake.lock:
                        self._json([{"id": i, "is_processing": fake.slot_busy.get(i, False)} for i in range(fake.slots)])
                else:
                    self._json({"data": [{"id": "m"}], "path": self.path})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fake.lock:
                    fake.requests.append(body)
                fake.free.acquire()
                with fake.lock:
                    fake.busy += 1
                    fake.max_busy = max(fake.max_busy, fake.busy)
                    if isinstance(body.get("id_slot"), int):
                        fake.slot_busy[body["id_slot"]] = True
                try:
                    self._stream(body)
                finally:
                    with fake.lock:
                        fake.busy -= 1
                        if isinstance(body.get("id_slot"), int):
                            fake.slot_busy[body["id_slot"]] = False
                    fake.free.release()

            def _send(self, data):
                raw = b"data: " + json.dumps(data).encode() + b"\n\n"
                self.wfile.write(b"%x\r\n%s\r\n" % (len(raw), raw))
                self.wfile.flush()

            def _stream(self, body):
                chat = "messages" in body
                if chat:
                    last = body["messages"][-1]
                    prefix = last["content"] if body.get("continue_final_message") else ""
                else:
                    prefix = body["prompt"].split("|", 1)[1] if "|" in body["prompt"] else ""
                first = len(prefix.split())
                limit = body.get("max_tokens") or body.get("n_predict") or 10_000
                stop = min(NATURAL_END, first + limit)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                timing = {"prompt_n": 1 if first else 12, "cache_n": first}
                try:
                    self._send({"id": "up", "created": 1, "model": "m", "choices": [
                        {"index": 0, "delta": {"role": "assistant", "content": None}}]} if chat else
                        {"id": "up", "created": 1, "model": "m", "choices": []})
                    for n, i in enumerate(range(first, stop), 1):
                        time.sleep(fake.delay)
                        piece = f"w{i} "
                        choice = {"index": 0, "delta": {"content": piece}} if chat else {"index": 0, "text": piece}
                        self._send({"id": "up", "created": 1, "model": "m", "choices": [choice],
                                    "timings": {**timing, "predicted_n": n}})
                    reason = "stop" if stop == NATURAL_END else "length"
                    end = {"index": 0, "delta": {}, "finish_reason": reason} if chat else \
                        {"index": 0, "text": "", "finish_reason": reason}
                    self._send({"id": "up", "created": 1, "model": "m", "choices": [end],
                                "timings": {**timing, "predicted_n": stop - first}})
                    self._send({"id": "up", "created": 1, "model": "m", "choices": [],
                                "usage": {"prompt_tokens": 12, "completion_tokens": stop - first}})
                    raw = b"data: [DONE]\n\n"
                    self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(raw), raw))
                    self.wfile.flush()
                except OSError:
                    with fake.lock:
                        fake.cancelled += 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def continuations(self) -> list[dict]:
        with self.lock:
            return [r for r in self.requests if r.get("continue_final_message") or "|w" in str(r.get("prompt"))]


@pytest.fixture
def stack(tmp_path):
    made = []

    def build(slots=2, solo=False, bg_cap=0, keys=None, grace=0.2):
        fake = FakeLlama(slots)
        cfg = pp.Config(upstream=fake.url, host="127.0.0.1", port=0, solo_p0=solo, grace_s=grace,
                        log=str(tmp_path / "proxy.jsonl"),
                        models={"m": pp.ModelPolicy("m", slots, bg_cap, ("alias",))})
        if keys:
            (tmp_path / "keys").write_text("\n".join(keys) + "\n")
            cfg.key_file = str(tmp_path / "keys")
        server = pp.make_server(cfg)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        made.append((fake, server))
        return fake, server, server.server_address[1]

    yield build
    for fake, server in made:
        server.shutdown()
        fake.server.shutdown()


def call(port, path, body, key="k", timeout=30):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    conn.request("POST", path, body=json.dumps(body), headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    if body.get("stream") and resp.status == 200:
        chunks = [json.loads(line[5:]) for line in raw.decode().splitlines()
                  if line.startswith("data:") and line[5:].strip() != "[DONE]"]
        return resp.status, chunks, raw
    return resp.status, json.loads(raw), raw


def chat(n=None, stream=False, **extra):
    body = {"model": "m", "messages": [{"role": "user", "content": "go"}], "stream": stream, **extra}
    if n:
        body["max_tokens"] = n
    return body


def wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


def run_bg(port, path, body, out, key):
    out[key] = call(port, path, body)


def test_p0_pauses_background_and_both_background_answers_come_back_whole(stack):
    fake, server, port = stack(slots=2)
    results: dict = {}
    bg = [threading.Thread(target=run_bg, args=(port, "/p3/v1/chat/completions", chat(30), results, f"bg{i}"))
          for i in range(2)]
    for t in bg:
        t.start()
    assert wait_for(lambda: fake.busy == 2)
    time.sleep(0.1)
    t0 = time.monotonic()
    status, chunks, _ = call(port, "/p0/v1/chat/completions", chat(5, stream=True))
    p0_time = time.monotonic() - t0
    assert status == 200
    assert "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks if c.get("choices")) == words(0, 5)
    assert any(t.is_alive() for t in bg), "P0 had to wait for a background answer to finish"
    for t in bg:
        t.join(30)
    for key in ("bg0", "bg1"):
        status, data, _ = results[key]
        assert status == 200
        assert data["choices"][0]["message"]["content"] == words(0, 30)        # nothing lost, nothing twice
        assert data["choices"][0]["finish_reason"] == "length"
        assert data["usage"]["completion_tokens"] == 30
        assert data["object"] == "chat.completion"
    cont = fake.continuations()
    assert len(cont) == 1                                       # exactly one background request was paused
    assert cont[0]["add_generation_prompt"] is False
    assert cont[0]["max_tokens"] == 30 - len(cont[0]["messages"][-1]["content"].split())
    assert fake.max_busy == 2 and p0_time < 2.0
    view = server.RequestHandlerClass.proxy.sched.view()
    assert view["classes"]["P3"]["preemptions"] == 1 and view["classes"]["P3"]["resumes"] == 1
    assert view["classes"]["P3"]["resume_cached_tokens"] > 0


def test_solo_p0_pauses_every_background_stream(stack):
    fake, server, port = stack(slots=3, solo=True)
    results: dict = {}
    bg = [threading.Thread(target=run_bg, args=(port, "/p3/v1/chat/completions", chat(), results, f"bg{i}"))
          for i in range(2)]
    for t in bg:
        t.start()
    assert wait_for(lambda: fake.busy == 2)
    time.sleep(0.1)
    status, data, _ = call(port, "/p0/v1/chat/completions", chat(8))
    assert status == 200 and data["choices"][0]["message"]["content"] == words(0, 8)
    for t in bg:
        t.join(30)
    for key in ("bg0", "bg1"):
        assert results[key][1]["choices"][0]["message"]["content"] == words(0, NATURAL_END)
        assert results[key][1]["choices"][0]["finish_reason"] == "stop"
    cont = fake.continuations()
    assert len(cont) == 2
    first_slots = {r["id_slot"] for r in fake.requests[:2]}
    assert {r["id_slot"] for r in cont} == first_slots == {0, 1}    # each answer resumed on its own slot
    assert [r["id_slot"] for r in fake.requests if r.get("max_tokens") == 8] == [2]   # the chat took the spare one
    rows = [json.loads(line) for line in open(server.RequestHandlerClass.proxy.cfg.log)]
    assert {r["class"] for r in rows} == {"P0", "P3"} and all(r["status"] == "ok" for r in rows)
    assert sum(r["pauses"] for r in rows if r["class"] == "P3") == 2


def test_streaming_background_client_sees_one_seamless_answer(stack):
    fake, _, port = stack(slots=1)
    results: dict = {}
    t = threading.Thread(target=run_bg, args=(port, "/p2/v1/chat/completions", chat(25, stream=True), results, "bg"))
    t.start()
    assert wait_for(lambda: fake.busy == 1)
    time.sleep(0.15)
    assert call(port, "/p0/v1/chat/completions", chat(3))[0] == 200
    t.join(30)
    status, chunks, raw = results["bg"]
    assert status == 200 and raw.rstrip().endswith(b"data: [DONE]")
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks if c.get("choices"))
    assert text == words(0, 25)
    assert {c["id"] for c in chunks} == {"up"}
    assert sum(1 for c in chunks for ch in c.get("choices", []) if "role" in ch.get("delta", {})) == 1
    assert sum(1 for c in chunks for ch in c.get("choices", []) if ch.get("finish_reason")) == 1
    assert not any("usage" in c for c in chunks)                 # the client did not ask for usage
    assert len(fake.continuations()) == 1


def test_text_completion_resumes_from_prompt_plus_text(stack):
    fake, _, port = stack(slots=1)
    results: dict = {}
    body = {"model": "alias", "prompt": "story|", "max_tokens": 20}
    t = threading.Thread(target=run_bg, args=(port, "/p3/v1/completions", body, results, "bg"))
    t.start()
    assert wait_for(lambda: fake.busy == 1)
    time.sleep(0.1)
    assert call(port, "/p1/v1/completions", {"model": "m", "prompt": "x", "max_tokens": 2})[0] == 200
    t.join(30)
    data = results["bg"][1]
    assert data["choices"][0]["text"] == words(0, 20) and data["object"] == "text_completion"
    cont = fake.continuations()
    assert len(cont) == 1 and cont[0]["prompt"].startswith("story|w0 ")


def test_constrained_non_streaming_request_starts_over_without_duplicates(stack):
    fake, server, port = stack(slots=1)
    results: dict = {}
    body = chat(15, grammar="root ::= x")
    t = threading.Thread(target=run_bg, args=(port, "/p3/v1/chat/completions", body, results, "bg"))
    t.start()
    assert wait_for(lambda: fake.busy == 1)
    time.sleep(0.1)
    assert call(port, "/p0/v1/chat/completions", chat(2))[0] == 200
    t.join(30)
    assert results["bg"][1]["choices"][0]["message"]["content"] == words(0, 15)
    assert fake.continuations() == []
    assert server.RequestHandlerClass.proxy.sched.view()["classes"]["P3"]["restarts"] == 1


def test_passthrough_and_unscheduled_models(stack):
    fake, _, port = stack()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/p3/v1/models")
    resp = conn.getresponse()
    assert resp.status == 200 and json.loads(resp.read())["path"] == "/v1/models"
    conn.close()
    status, chunks, _ = call(port, "/v1/chat/completions", {"model": "other", "stream": True,
                                                            "messages": [{"role": "user", "content": "q"}]})
    assert status == 200 and fake.requests[-1]["model"] == "other" and chunks[-1]["usage"]
    assert "timings_per_token" not in fake.requests[-1]          # not touched: passed through as sent


def test_key_checked_before_scheduling(stack):
    fake, _, port = stack(keys=["right"])
    status, data, _ = call(port, "/p0/v1/chat/completions", chat(3), key="wrong")
    assert status == 401 and fake.requests == []
    assert call(port, "/p0/v1/chat/completions", chat(3), key="right")[0] == 200


def test_status_endpoint(stack):
    _, _, port = stack()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/priority/v1/status")
    data = json.loads(conn.getresponse().read())
    assert set(data["classes"]) == {"P0", "P1", "P2", "P3"} and data["models"]["m"]["slots"] == 2
    assert data["p0_active"] is False


def test_class_port_labels_clients_without_a_path(tmp_path):
    fake = FakeLlama(1)
    cfg = pp.Config(upstream=fake.url, host="127.0.0.1", port=0, default_class=0, solo_p0=False,
                    class_ports={0: 3}, models={"m": pp.ModelPolicy("m", 1, 0, ())})
    servers = pp.make_servers(cfg)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    main_port, p3_port = (s.server_address[1] for s in servers)
    try:
        results: dict = {}
        t = threading.Thread(target=run_bg, args=(p3_port, "/v1/chat/completions", chat(20), results, "bg"))
        t.start()
        assert wait_for(lambda: fake.busy == 1)
        time.sleep(0.1)
        assert call(main_port, "/v1/chat/completions", chat(2))[0] == 200          # unlabelled = owner (P0)
        t.join(30)
        assert results["bg"][1]["choices"][0]["message"]["content"] == words(0, 20)
        view = servers[0].RequestHandlerClass.proxy.sched.view()
        assert view["classes"]["P3"]["preemptions"] == 1 and view["classes"]["P0"]["requests"] == 1
        conn = http.client.HTTPConnection("127.0.0.1", main_port, timeout=10)
        conn.request("HEAD", "/v1/models")
        assert conn.getresponse().status in (200, 501)                              # passed through, not refused here
    finally:
        for server in servers:
            server.shutdown()
        fake.server.shutdown()


def test_logprobs_requests_are_passed_through_unscheduled(stack):
    fake, server, port = stack()
    status, chunks, _ = call(port, "/p0/v1/chat/completions", chat(3, stream=True, logprobs=True))
    assert status == 200 and "timings_per_token" not in fake.requests[-1]
    assert server.RequestHandlerClass.proxy.sched.view()["classes"]["P0"]["requests"] == 0


def test_header_overrides_class_and_config_file(tmp_path):
    cfg_file = tmp_path / "priority.json"
    cfg_file.write_text(json.dumps({"port": 9, "default_class": "P3", "solo_p0": False, "class_ports": {"8083": "P3"},
                                    "models": {"star-fast": {"slots": 3, "bg_cap": 2, "aliases": ["star-code"]}}}))
    cfg = pp.Config.load(str(cfg_file))
    assert cfg.port == 9 and cfg.default_class == 3 and not cfg.solo_p0 and cfg.class_ports == {8083: 3}
    assert cfg.canonical("star-code") == "star-fast" and cfg.canonical("star-voice") == ""
    assert cfg.models["star-fast"].cap() == 2
    assert pp.parse_class("p1", 2) == 1 and pp.parse_class("urgent", 2) == 2


def test_abort_from_another_thread_ends_the_read_cleanly():
    """The scheduler stops a generation from its own thread while the request thread reads (seen live: closing the
    http.client connection from another thread raised AttributeError inside http.client)."""
    fake = FakeLlama(1, delay=0.05)
    try:
        for _ in range(10):
            up = pp.Upstream(fake.url, "POST", "/v1/chat/completions", json.dumps(chat(40)).encode(),
                             {"Content-Type": "application/json"})
            resp = up.response()
            errors: list = []

            def read():
                try:
                    while resp.readline():
                        pass
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                except Exception as exc:                 # anything else is the bug
                    errors.append(exc)
            reader = threading.Thread(target=read)
            reader.start()
            time.sleep(0.12)
            up.abort()
            reader.join(5)
            up.close()
            assert not reader.is_alive() and errors == []
        assert wait_for(lambda: fake.cancelled == 10)          # every aborted generation was stopped upstream
    finally:
        fake.server.shutdown()
