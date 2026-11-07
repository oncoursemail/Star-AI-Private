"""Watchdog (starkb/watchdog.py) and the luau-check spawn that no longer uses preexec_fn. Runs on the PC."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starkb import luaucheck, watchdog  # noqa: E402

NOW = datetime(2026, 10, 20, 7, 8, tzinfo=timezone.utc)


@pytest.fixture
def server():
    """A local HTTP server whose reply the test chooses: (status, body) or "hang"."""
    behaviour = {"reply": (200, {"passages": [{"text": "x"}]})}
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append((self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            if behaviour["reply"] == "hang":
                time.sleep(2)
                return
            status, body = behaviour["reply"]
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/search", behaviour, seen
    httpd.shutdown()
    httpd.server_close()


def test_check_passes_on_a_real_reply_and_sends_the_key_and_a_per_minute_query(server):
    url, _, seen = server
    assert watchdog.check(url, "k1", timeout=5, now=NOW) == ""
    assert watchdog.check(url, "k1", timeout=5, now=NOW + timedelta(minutes=1)) == ""
    assert seen[0][0] == "Bearer k1"
    assert seen[0][1]["query"] != seen[1][1]["query"]      # the reply cache cannot answer the next check


def test_check_fails_on_no_passages_http_error_hang_and_refused(server):
    url, behaviour, _ = server
    behaviour["reply"] = (200, {"passages": []})
    assert watchdog.check(url, timeout=5, now=NOW) == "no passages"
    behaviour["reply"] = (503, {"error": "busy"})
    assert watchdog.check(url, timeout=5, now=NOW) == "HTTP 503"
    behaviour["reply"] = "hang"
    assert "timed out" in watchdog.check(url, timeout=0.5, now=NOW)
    assert watchdog.check("http://127.0.0.1:9/search", timeout=2, now=NOW) != ""


def test_restart_only_after_two_failures_in_a_row_and_a_success_resets():
    calls = []
    state = watchdog.tick({"failures": 0, "restarts": []}, "HTTP 503", NOW, lambda: calls.append(1) or True, log=lambda m: None)
    assert state["failures"] == 1 and not calls
    state = watchdog.tick(state, "", NOW, lambda: calls.append(1) or True, log=lambda m: None)
    assert state["failures"] == 0 and state["ok"] is True
    state = watchdog.tick(state, "TimeoutError: timed out", NOW, lambda: calls.append(1) or True, log=lambda m: None)
    state = watchdog.tick(state, "TimeoutError: timed out", NOW + timedelta(minutes=1),
                          lambda: calls.append(1) or True, log=lambda m: None)
    assert calls == [1]
    assert state["failures"] == 0
    assert state["restarts"] == [{"at": "2026-10-20T07:09:00Z", "reason": "TimeoutError: timed out",
                                  "failures": 2, "done": True}]


def test_no_more_than_three_restarts_an_hour():
    calls = []
    old = [{"at": watchdog._stamp(NOW - timedelta(minutes=m)), "reason": "x", "failures": 2, "done": True}
           for m in (50, 30, 10)]
    state = watchdog.tick({"failures": 1, "restarts": old}, "HTTP 500", NOW, lambda: calls.append(1) or True,
                          log=lambda m: None)
    assert not calls and len(state["restarts"]) == 3 and state["failures"] == 2
    old[0]["at"] = watchdog._stamp(NOW - timedelta(minutes=70))     # one of them is now older than an hour
    state = watchdog.tick({"failures": 1, "restarts": old}, "HTTP 500", NOW, lambda: calls.append(1) or True,
                          log=lambda m: None)
    assert calls == [1] and len(state["restarts"]) == 4


def test_restart_dumps_the_stacks_before_restarting():
    argv = []

    class Done:
        returncode = 0

    assert watchdog.restart("star-knowledge", run=lambda a, **k: argv.append(a) or Done(), sleep=lambda s: None)
    assert argv == [["systemctl", "kill", "--signal=SIGUSR1", "star-knowledge"],
                    ["systemctl", "restart", "star-knowledge"]]


def test_state_file_round_trip_and_a_broken_file_starts_fresh(tmp_path):
    path = tmp_path / "watchdog.json"
    assert watchdog.load_state(path) == {"failures": 0, "restarts": []}
    watchdog.save_state(path, {"failures": 1, "restarts": [], "ok": False})
    assert watchdog.load_state(path)["failures"] == 1
    path.write_text("{not json", encoding="utf-8")
    assert watchdog.load_state(path) == {"failures": 0, "restarts": []}


def test_luau_tools_run_under_prlimit_without_preexec_fn(tmp_path, monkeypatch):
    seen = {}

    class Proc:
        pid = 1

        def wait(self, timeout=None):
            return 0

    def popen(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return Proc()

    monkeypatch.setattr(luaucheck.subprocess, "Popen", popen)
    code, _, timed_out = luaucheck._run(["luau-analyze", "x.luau"], tmp_path, timeout=5, memory_bytes=1 << 28)
    assert (code, timed_out) == (0, False)
    assert "preexec_fn" not in seen["kwargs"]
    assert Path(seen["argv"][0]).stem == "prlimit"
    assert seen["argv"][-3:] == ["--", "luau-analyze", "x.luau"]
    assert "--cpu=6" in seen["argv"] and f"--as={1 << 28}" in seen["argv"]
