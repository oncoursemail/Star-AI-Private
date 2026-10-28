"""Litha mesh node (server/mesh/node/node_agent.py): busy rules, status shape, load/unload auth, the proxy.
Everything is a fake: no GPU, no llama-server, no scheduled task, no real game."""
import http.client
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "mesh" / "node"))

import node_agent as na  # noqa: E402

TOKEN = "ab" * 32


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Proc:
    def __init__(self, pid=4242):
        self.pid, self.returncode, self.killed = pid, None, False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed, self.returncode = True, -9

    def wait(self, timeout=None):
        return self.returncode


class Probe:
    def __init__(self):
        self.procs = {4: "System", 100: "explorer.exe", 200: "brave.exe"}
        self.paths = {}
        self.titles = {}
        self.full = False

    def processes(self):
        return dict(self.procs)

    def exe_path(self, pid, name):
        return self.paths.get(pid, "C:\\Windows\\" + name)

    def window_titles(self, pids):
        return [t for p, t in self.titles.items() if p in pids]

    def fullscreen(self):
        return self.full


def make(tmp_path, **over):
    config = dict(na.DEFAULTS, node="test-pc", advertise_host="node.test", resume_seconds=60, retry_seconds=30,
                  need_free_vram_mb=0)
    config.update(over)
    engine = tmp_path / "engine"
    engine.mkdir(exist_ok=True)
    (engine / "llama-server.exe").write_bytes(b"")
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models" / "litha-fast.gguf").write_bytes(b"")
    gpu = {"name": "Fake 8G", "total": 8192, "used": 1600, "util": 3}
    clock = Clock()
    procs = []

    def popen(argv, **kw):
        procs.append((argv, kw))
        return Proc()

    def fake_gpu():
        return dict(gpu)

    node = na.Node(config, tmp_path, probe=Probe(), gpu=fake_gpu, ram=lambda: 20000, popen=popen,
                   healthy=lambda port: True, measure=lambda port, cfg: (41.5, 900.0), clock=clock,
                   log=lambda text: None, background=False)
    return node, gpu, clock, procs


def loaded(tmp_path, **over):
    node, gpu, clock, procs = make(tmp_path, **over)

    def popen(argv, **kw):
        procs.append((argv, kw))
        gpu["used"] = 7300                     # the model takes its memory while it loads
        return Proc()
    node._popen = popen
    node.tick()
    assert node.state == "idle" and node.ready
    return node, gpu, clock, procs


# ---- program rules -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["RobloxPlayerBeta.exe", "robloxstudiobeta.exe", "obs64.exe", "recroom_release.exe",
                                  "vrserver.exe", "Minecraft.Windows.exe"])
def test_known_programs_are_busy(name):
    reason = na.program_reason(na.DEFAULTS, {10: name}, set(), lambda p, n: "", lambda pids: [], False)
    assert name in reason


def test_steam_game_by_path_and_ignored_helpers():
    procs = {10: "game.exe", 11: "wallpaper32.exe"}
    paths = {10: "D:\\SteamLibrary\\steamapps\\common\\Some Game\\game.exe",
             11: "C:\\Steam\\steamapps\\common\\wallpaper_engine\\wallpaper32.exe"}
    path = lambda pid, name: paths[pid]  # noqa: E731
    assert "Steam game" in na.program_reason(na.DEFAULTS, procs, set(), path, lambda p: [], False)
    assert na.program_reason(na.DEFAULTS, {11: "wallpaper32.exe"}, set(), path, lambda p: [], False) == ""


def test_minecraft_java_by_path_or_window_title():
    path = lambda pid, name: {1: "C:\\x\\.minecraft\\runtime\\bin\\javaw.exe"}.get(pid, "C:\\jdk\\bin\\javaw.exe")  # noqa: E731
    assert "Minecraft" in na.program_reason(na.DEFAULTS, {1: "javaw.exe"}, set(), path, lambda p: [], False)
    assert na.program_reason(na.DEFAULTS, {2: "javaw.exe"}, set(), path, lambda p: ["IntelliJ"], False) == ""
    assert "Minecraft" in na.program_reason(na.DEFAULTS, {2: "javaw.exe"}, set(), path,
                                            lambda p: ["Minecraft 1.21.4"], False)


def test_fullscreen_and_own_process_and_quiet_desktop():
    assert "full-screen" in na.program_reason(na.DEFAULTS, {}, set(), lambda p, n: "", lambda p: [], True)
    assert na.program_reason(dict(na.DEFAULTS, fullscreen=False), {}, set(), lambda p, n: "", lambda p: [], True) == ""
    cfg = dict(na.DEFAULTS, block_processes=["llama-server.exe"])
    assert na.program_reason(cfg, {7: "llama-server.exe"}, {7}, lambda p, n: "", lambda p: [], False) == ""
    desktop = {4: "System", 100: "explorer.exe", 200: "brave.exe", 300: "Discord.exe"}
    assert na.program_reason(na.DEFAULTS, desktop, set(), lambda p, n: "C:\\x\\" + n, lambda p: [], False) == ""


# ---- the guard state machine ---------------------------------------------------------------------------------------
def test_autoload_measures_speed_and_reports_idle(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    argv, kw = procs[0]
    assert "--host" in argv and argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--alias") + 1] == "litha-fast"
    assert kw["creationflags"] & na.NO_WINDOW == na.NO_WINDOW
    assert node.tok_s == 41.5 and node.own_mb == 7300 - 1600


def test_game_unloads_at_once_and_reloads_after_free_time(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    process = node.process
    node.probe.procs[999] = "RobloxPlayerBeta.exe"
    node.tick()
    assert node.state == "busy" and "RobloxPlayerBeta.exe" in node.reason
    assert process.killed and node.process is None and not node.ready
    gpu["used"] = 1600
    del node.probe.procs[999]
    clock.t += 1
    node.tick()
    assert node.state == "busy" and "free for 0 of 60 s" in node.reason and node.process is None
    clock.t += 30
    node.tick()
    assert node.state == "busy" and "free for 30 of 60 s" in node.reason
    node.probe.procs[998] = "obs64.exe"                     # busy again: the free time starts over
    node.tick()
    del node.probe.procs[998]
    clock.t += 59
    node.tick()
    clock.t += 59
    node.tick()
    assert node.state == "busy"
    clock.t += 2
    node.tick()
    assert node.state == "idle" and node.ready and len(procs) == 2


def test_fake_busy_file_is_the_test_hook(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    (tmp_path / "FAKE_BUSY").write_text("x")
    node.tick()
    assert node.state == "busy" and "FAKE_BUSY" in node.reason and not node.ready


def test_other_gpu_load_needs_two_looks_and_ignores_own_requests(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    clock.t += 10
    gpu["util"] = 95
    assert node.begin_request()                             # our own answer is running: the load is ours
    node.tick()
    node.tick()
    assert node.state == "idle"
    node.end_request()
    node.tick()                                             # within 3 s after the answer: still ours
    assert node.state == "idle"
    clock.t += 5
    node.tick()
    assert node.state == "idle"                             # first look
    node.tick()
    assert node.state == "busy" and "95%" in node.reason


def test_other_programs_growing_video_memory(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path, other_vram_grow_mb=1000)
    gpu["used"] = 7300 + 900
    node.tick()
    assert node.state == "idle"
    gpu["used"] = 7300 + 1100
    node.tick()
    assert node.state == "busy" and "1100 MB" in node.reason


def test_not_enough_free_memory_blocks_the_load(tmp_path):
    node, gpu, clock, procs = make(tmp_path, need_free_vram_mb=5800)
    gpu["used"] = 3000
    node.tick()
    assert node.state == "busy" and "5800 MB needed" in node.reason and not procs


def test_off_file_and_unload_hold(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    node.unload("unloaded on request", hold=True)
    clock.t += 100
    node.tick()
    assert node.state == "away" and "POST /load" in node.reason and len(procs) == 1
    node.hold = False
    (tmp_path / "OFF").write_text("off")
    node.tick()
    assert node.state == "off" and len(procs) == 1


def test_crashed_server_waits_before_retrying(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    node.process.returncode = 3
    node.tick()
    assert node.state == "away" and "code 3" in node.reason
    clock.t += 10
    node.tick()
    assert len(procs) == 1
    clock.t += 30
    node.tick()
    assert len(procs) == 2 and node.ready


def test_missing_files_fail_cleanly(tmp_path):
    node, gpu, clock, procs = make(tmp_path, model_path="models/none.gguf")
    node.tick()
    assert node.state == "away" and node.reason.startswith("failed: the model file was not found")


# ---- status shape --------------------------------------------------------------------------------------------------
def test_status_json_shape(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    status = json.loads(json.dumps(node.status()))
    assert set(status) >= {"node", "state", "reason", "gpu", "ram_free_mb", "models", "ts"}
    assert status["state"] in ("idle", "busy", "away", "off") and status["node"] == "test-pc"
    assert status["gpu"] == {"name": "Fake 8G", "vram_total_mb": 8192, "vram_free_mb": 8192 - 7300, "util": 3}
    model = status["models"][0]
    assert model["id"] == "litha-fast" and model["url"] == "http://node.test:8098/v1"
    assert model["loaded"] is True and model["tok_s"] == 41.5 and model["ctx"] == 8192
    assert TOKEN not in json.dumps(status)


# ---- token and HTTP auth -------------------------------------------------------------------------------------------
def test_token_created_once_and_compared_safely(tmp_path):
    path = tmp_path / "star" / "mesh_token"
    token = na.read_or_create_token(path)
    assert len(token) == 64 and int(token, 16) >= 0
    assert na.read_or_create_token(path) == token
    assert na.authorized("Bearer " + token, token)
    assert not na.authorized("Bearer " + token[:-1] + "0", token) or token.endswith("0")
    assert not na.authorized(None, token) and not na.authorized(token, token) and not na.authorized("Bearer x", "")


def serve_control(node):
    server = na.Server(("127.0.0.1", 0), na.make_control_handler(node, TOKEN))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def call(server, method, path, token=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    conn.request(method, path, body=json.dumps(body or {}) if method == "POST" else None, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


def test_load_unload_need_the_token(tmp_path):
    node, gpu, clock, procs = loaded(tmp_path)
    server = serve_control(node)
    try:
        assert call(server, "GET", "/status")[0] == 200
        assert call(server, "POST", "/unload")[0] == 401
        assert call(server, "POST", "/unload", token="cd" * 32)[0] == 401
        assert node.ready
        code, data = call(server, "POST", "/unload", token=TOKEN)
        assert code == 200 and not node.ready and data["state"] == "away"
        assert call(server, "POST", "/load", token="nope")[0] == 401 and not node.ready
        code, data = call(server, "POST", "/load", token=TOKEN)
        assert code == 202 and node.ready and data["models"][0]["loaded"] is True
        node.probe.procs[5] = "obs64.exe"
        node.tick()
        code, data = call(server, "POST", "/load", token=TOKEN)
        assert code == 409 and data["state"] == "busy" and not node.ready
    finally:
        server.shutdown()


def test_model_proxy_needs_token_and_a_loaded_model(tmp_path):
    node, gpu, clock, procs = make(tmp_path)
    upstream = na.Server(("127.0.0.1", 0), _FakeLlama)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    node.config["internal_port"] = upstream.server_address[1]
    proxy = na.Server(("127.0.0.1", 0), na.make_model_handler(node, TOKEN))
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        assert call(proxy, "POST", "/v1/chat/completions", token=TOKEN)[0] == 503    # not loaded yet
        node.ready = True
        assert call(proxy, "POST", "/v1/chat/completions")[0] == 401
        code, data = call(proxy, "POST", "/v1/chat/completions", token=TOKEN, body={"messages": []})
        assert code == 200 and data["seen_auth"] is None and data["path"] == "/v1/chat/completions"
        assert node.in_flight == 0
    finally:
        proxy.shutdown()
        upstream.shutdown()


class _FakeLlama(na.http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"path": self.path, "seen_auth": self.headers.get("Authorization")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_firewall_rule_is_lan_only_and_names_the_program():
    rule = na.firewall_command(Path("C:/py/python.exe"), na.DEFAULTS)
    assert "remoteip=LocalSubnet" in rule and "localport=8098,8099" in rule and "dir=in" in rule
    assert any(part.startswith("program=") and part.endswith("python.exe") for part in rule)


def test_load_for_another_model_is_refused(tmp_path):
    node, gpu, clock, procs = make(tmp_path, autoload=False)
    node.tick()
    server = serve_control(node)
    try:
        assert call(server, "POST", "/load", token=TOKEN, body={"model": "other"})[0] == 404 and not procs
        assert call(server, "POST", "/load", token=TOKEN, body={"model": "litha-fast"})[0] == 202 and node.ready
    finally:
        server.shutdown()


def test_self_registration_sends_token_and_urls(tmp_path):
    node, gpu, clock, procs = make(tmp_path, router_url="http://router.test:8100/", register_seconds=0.01)
    stop = threading.Event()
    sent = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def post(req, timeout):
        sent.append(req)
        stop.set()
        return Resp()
    na.register_loop(node, TOKEN, stop, post=post)
    req = sent[0]
    assert req.full_url == "http://router.test:8100/mesh/register" and req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer " + TOKEN
    assert json.loads(req.data) == {"node": "test-pc", "status_url": "http://node.test:8099/status",
                                    "model_url": "http://node.test:8098/v1"}
    na.register_loop(make(tmp_path)[0], TOKEN, threading.Event())       # no router_url: returns at once
