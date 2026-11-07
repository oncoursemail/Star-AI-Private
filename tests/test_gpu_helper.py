"""Settings > Use my GPU (star/gpu_helper.py): life of the PC model server, busy detection, routing and fallback.

Everything here runs with fakes: no process, no nvidia-smi, no network.
"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import gpu_helper, providers, server_roles, turn_memory
from star.desktop_core import Settings
from star.gpu_helper import GpuHelper, GpuReading, GpuRoutingClient

LAN = "http://192.168." + "1.20:8080/v1"   # an example private address
KEY = "test-server-key-0123456789"
FREE = GpuReading(utilization=5, used_mib=900, total_mib=8192)


@pytest.fixture(autouse=True)
def clean_process_memory():
    def clear():
        server_roles.forget()
        turn_memory.forget()
        providers._SERVER_LIMITS.clear()
        providers._MODEL_NAMES.clear()
        providers._SLOT_TABLE.clear()
    clear()
    yield
    clear()


class Process:
    def __init__(self):
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = 1

    def kill(self):
        self.code = -9

    def wait(self, timeout=None):
        return self.code


class Rig:
    """A GpuHelper whose card, clock, health check and process are all set by the test."""

    def __init__(self, tmp_path: Path):
        self.now = 1000.0
        self.reading = FREE
        self.ram = 20_000
        self.comfy = False
        self.up = False
        self.started: list[list[str]] = []
        self.processes: list[Process] = []

        def popen(argv, **_):
            self.started.append(argv)
            self.processes.append(Process())
            return self.processes[-1]
        self.helper = GpuHelper(popen=popen, gpu=lambda: self.reading, ram=lambda: self.ram,
                                image_engine=lambda port: self.comfy, health=lambda base: self.up,
                                clock=lambda: self.now, pick_port=lambda: 18555, watchdog=False, warm=None)
        exe, model = tmp_path / "llama-server.exe", tmp_path / "star-fast.gguf"
        exe.write_bytes(b"MZ")
        model.write_bytes(b"GGUF")
        self.home = tmp_path / "home"
        self.settings = Settings(provider="star_server", server_endpoint=LAN, model="star-fast", use_my_gpu=True,
                                 gpu_helper_server=str(exe), gpu_helper_model=str(model), gpu_idle_minutes=10)

    def ready(self):
        self.helper.configure(self.settings, self.home, start=True)
        self.helper.tick()               # starts the process
        self.up = True
        self.helper.tick()               # health answers: ready
        assert self.helper.state == "ready", self.helper.status()
        return self.helper


def test_switch_on_loads_with_the_measured_settings_and_off_stops_it(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.helper
    assert helper.status()["state"] == "off" and helper.lease() is None
    helper.configure(rig.settings, rig.home, start=True)
    helper.tick()
    assert helper.state == "starting"
    argv = rig.started[0]
    joined = " ".join(argv)
    for flag in ("--n-cpu-moe 34", "-b 2048", "-ub 2048", "-fa on", "-c 32768", "-np 1", "--host 127.0.0.1",
                 "--alias star-fast", "--reasoning off", "-ngl 99"):
        assert flag in joined
    assert argv[argv.index("-t") + 1] in {str(n) for n in range(1, 7)}
    assert helper.lease() is None                # still loading: this request uses the server
    rig.up = True
    helper.tick()
    assert helper.status()["state"] == "ready"
    assert helper.lease() == "http://127.0.0.1:18555/v1"
    assert helper.lease() is None                # one request at a time (-np 1)
    helper.finish(ok=True, tokens_per_second=31.24)
    assert "31.2 tokens per second" in helper.status()["text"]
    off = Settings(**{**rig.settings.__dict__, "use_my_gpu": False})
    helper.configure(off, rig.home)
    assert rig.processes[0].terminated and helper.state == "off" and helper.lease() is None


def test_ready_only_after_the_warm_up_read_a_prompt(tmp_path):
    import threading
    rig = Rig(tmp_path)
    release, warmed = threading.Event(), []

    def warm(base):
        warmed.append(base)
        release.wait(5)
    rig.helper._warm = warm
    rig.helper.configure(rig.settings, rig.home, start=True)
    rig.helper.tick()
    rig.up = True
    rig.helper.tick()
    rig.helper.tick()
    assert rig.helper.state == "starting" and rig.helper.lease() is None
    release.set()
    for _ in range(100):
        if rig.helper.state == "ready":
            break
        threading.Event().wait(0.02)
    assert rig.helper.state == "ready" and warmed == ["http://127.0.0.1:18555/v1"]


def test_app_start_arms_without_loading_and_the_first_request_starts_it(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.helper
    helper.configure(rig.settings, rig.home)     # app start: switch saved on
    helper.tick()
    assert helper.state == "idle" and not rig.started
    assert helper.lease() is None                # this request goes to the server ...
    helper.tick()
    assert helper.state == "starting" and rig.started   # ... and the model loads for the next one


def test_idle_minutes_unload_it_and_the_next_request_loads_it_again(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    rig.now += 9 * 60
    helper.tick()
    assert helper.state == "ready"
    rig.now += 2 * 60
    helper.tick()
    assert helper.state == "idle" and rig.processes[0].terminated
    assert "idle minutes" in helper.status()["text"]
    assert helper.lease() is None
    helper.tick()
    assert helper.state == "starting" and len(rig.started) == 2


@pytest.mark.parametrize("reading, ram, comfy, words", [
    (GpuReading(80, 2000, 8192), 20_000, False, "another program is using"),
    (GpuReading(5, 4000, 8192), 20_000, False, "graphics memory is free"),
    (FREE, 4000, False, "of memory is free"),
    (FREE, 20_000, True, "image engine"),
    (None, 20_000, False, "no NVIDIA"),
])
def test_it_does_not_start_while_the_card_is_not_free(tmp_path, reading, ram, comfy, words):
    rig = Rig(tmp_path)
    rig.reading, rig.ram, rig.comfy = reading, ram, comfy
    rig.helper.configure(rig.settings, rig.home, start=True)
    rig.helper.tick()
    assert rig.helper.state == "busy" and not rig.started
    assert words in rig.helper.status()["text"]


def test_a_game_pauses_an_idle_model_and_it_resumes_after_two_free_minutes(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    rig.reading = GpuReading(97, 7600, 8192)     # the owner starts a game
    helper.tick()
    assert helper.state == "ready"               # one hot sample is not enough
    helper.tick()
    assert helper.state == "busy" and rig.processes[0].terminated
    assert helper.lease() is None
    rig.now += 60
    helper.tick()
    rig.reading = FREE                           # the game is closed
    rig.now += 60
    helper.tick()
    assert helper.state == "busy"
    rig.now += gpu_helper.RESUME_SECONDS
    helper.tick()
    assert helper.state == "idle"                # loads again with the next question
    helper.lease()
    helper.tick()
    assert helper.state == "starting"


def test_its_own_answer_is_not_mistaken_for_a_game(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    assert helper.lease()
    rig.reading = GpuReading(99, 7600, 8192)
    for _ in range(5):
        helper.tick()
    assert helper.state == "ready" and not rig.processes[0].terminated


def test_low_video_memory_or_the_image_engine_stops_it(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    rig.reading = GpuReading(10, 8000, 8192)
    helper.tick()
    assert helper.state == "busy" and "memory" in helper.status()["text"]
    rig = Rig(tmp_path)
    helper = rig.ready()
    helper.yield_to("the image engine is making a picture")
    assert helper.state == "busy" and rig.processes[0].terminated and helper.lease() is None


def test_a_crash_is_reported_and_retried_after_a_minute(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    rig.processes[0].code = 3
    helper.tick()
    assert helper.state == "failed" and "exit code 3" in helper.status()["text"]
    assert helper.lease() is None
    helper.tick()
    assert len(rig.started) == 1                 # not straight away
    rig.now += gpu_helper.RETRY_SECONDS
    helper.tick()
    assert len(rig.started) == 2 and helper.state == "starting"


def test_missing_files_and_a_slow_load_fail_with_a_reason(tmp_path):
    rig = Rig(tmp_path)
    rig.settings.gpu_helper_model = str(tmp_path / "nothing.gguf")
    rig.helper.configure(rig.settings, rig.home, start=True)
    rig.helper.tick()
    assert rig.helper.state == "failed" and "model file was not found" in rig.helper.status()["text"]
    rig = Rig(tmp_path)
    rig.helper.configure(rig.settings, rig.home, start=True)
    rig.helper.tick()
    rig.now += gpu_helper.LOAD_SECONDS + 1
    rig.helper.tick()
    assert rig.helper.state == "failed" and "did not load" in rig.helper.status()["text"]


def test_the_setting_is_off_by_default_and_validated():
    assert Settings().use_my_gpu is False
    Settings(use_my_gpu=True, gpu_idle_minutes=30).validate()
    for bad in ({"use_my_gpu": "yes"}, {"gpu_idle_minutes": 0}, {"gpu_idle_minutes": 241},
                {"gpu_helper_server": "https://example.com/llama-server.exe"},
                {"gpu_helper_model": "\\\\share\\star-fast.gguf"}):
        with pytest.raises(ValueError):
            Settings(**bad).validate()
    from star.react_shell import ALLOWED_ACTIONS, PERMITTED_SETTINGS
    assert {"gpuHelperStatus", "gpuHelperSet"} <= ALLOWED_ACTIONS
    # The switch is saved only by gpuHelperSet, so a Save of an older form cannot turn it back.
    assert "use_my_gpu" not in PERMITTED_SETTINGS
    assert {"gpu_helper_server", "gpu_helper_model", "gpu_idle_minutes"} <= PERMITTED_SETTINGS


# ---- routing ------------------------------------------------------------------------------------------------------
def chunk(text=None, tool=None, finish=None, timings=None):
    delta = SimpleNamespace(content=text, tool_calls=[tool] if tool else None)
    item = SimpleNamespace(model="star-fast", usage=None,
                           choices=[SimpleNamespace(delta=delta, finish_reason=finish)])
    if timings:
        item.timings = timings
    return item


class Stream:
    def __init__(self, items, fail_after=None, error=None):
        self.items, self.fail_after, self.error = items, fail_after, error

    def __aiter__(self):
        return self._go()

    async def _go(self):
        for number, item in enumerate(self.items):
            if self.fail_after is not None and number == self.fail_after:
                raise self.error
            yield item
        if self.fail_after is not None and self.fail_after >= len(self.items):
            raise self.error


class Fake:
    """A client whose create() answers from a list (an exception in the list is raised)."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []
        self.chat = SimpleNamespace(completions=self)
        self.closed = 0

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def close(self):
        self.closed += 1


class StatusError(Exception):
    status_code = 400


def reply(text):
    return SimpleNamespace(model="star-fast", timings={"predicted_per_second": 33.2},
                           choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))])


def routed(tmp_path, server, local):
    rig = Rig(tmp_path)
    rig.ready()
    return rig, GpuRoutingClient(server, rig.settings, helper=rig.helper, open_local=lambda base: local)


REQUEST = {"model": "star-fast", "messages": [{"role": "user", "content": "Write a Luau function."}],
           "extra_body": {"cache_prompt": True, "id_slot": 1}}


async def collect(stream):
    return [item async for item in stream]


def text_of(items):
    return "".join(i.choices[0].delta.content or "" for i in items if i.choices[0].delta.content)


def test_the_code_model_goes_to_the_pc_without_a_server_slot(tmp_path):
    server, local = Fake(), Fake(reply("from the PC"))
    rig, client = routed(tmp_path, server, local)
    answer = asyncio.run(client.chat.completions.create(**REQUEST))
    assert answer.choices[0].message.content == "from the PC" and not server.requests
    assert local.requests[0]["model"] == "star-fast"
    assert local.requests[0]["extra_body"] == {"cache_prompt": True}
    assert rig.helper.tokens_per_second == 33.2 and rig.helper.in_flight == 0


@pytest.mark.parametrize("request_", [
    {**REQUEST, "model": "star-voice"},
    {**REQUEST, "messages": [{"role": "user", "content": [{"type": "text", "text": "what is this"},
                                                          {"type": "image_url", "image_url": {"url": "data:"}}]}]},
])
def test_other_models_and_pictures_stay_on_the_server(tmp_path, request_):
    server, local = Fake(reply("server")), Fake()
    _, client = routed(tmp_path, server, local)
    assert asyncio.run(client.chat.completions.create(**request_)).choices[0].message.content == "server"
    assert not local.requests


def test_an_alias_the_server_reported_counts_as_the_code_model(tmp_path):
    providers.remember_model_names(LAN, "star-fast", ["star-code", "star-vision"])
    server, local = Fake(), Fake(reply("pc"))
    _, client = routed(tmp_path, server, local)
    asyncio.run(client.chat.completions.create(**{**REQUEST, "model": "star-vision"}))
    assert local.requests and not server.requests


def test_not_ready_means_the_server_answers_and_other_attributes_are_the_servers(tmp_path):
    rig = Rig(tmp_path)
    server = Fake(reply("server"))
    server.embeddings = "server embeddings"
    client = GpuRoutingClient(server, rig.settings, helper=rig.helper, open_local=lambda base: pytest.fail("PC"))
    assert asyncio.run(client.chat.completions.create(**REQUEST)).choices[0].message.content == "server"
    assert server.requests[0]["extra_body"] == {"cache_prompt": True, "id_slot": 1}   # untouched
    assert client.embeddings == "server embeddings"


def test_a_dead_pc_server_falls_back_and_is_marked_failed(tmp_path):
    server, local = Fake(reply("server")), Fake(ConnectionError("refused"))
    rig, client = routed(tmp_path, server, local)
    assert asyncio.run(client.chat.completions.create(**REQUEST)).choices[0].message.content == "server"
    assert server.requests[0] == json.loads(json.dumps(REQUEST))
    assert rig.helper.state == "failed" and rig.processes[0].terminated and local.closed


def test_an_error_answer_falls_back_but_keeps_the_pc_ready(tmp_path):
    server, local = Fake(reply("server")), Fake(StatusError("too long"))
    rig, client = routed(tmp_path, server, local)
    assert asyncio.run(client.chat.completions.create(**REQUEST)).choices[0].message.content == "server"
    assert rig.helper.state == "ready" and "HTTP 400" in rig.helper.status()["text"]


def test_a_stream_is_passed_through_and_its_speed_recorded(tmp_path):
    items = [chunk("local "), chunk("lua"), chunk(finish="stop", timings={"predicted_per_second": 31.9})]
    server, local = Fake(), Fake(Stream(items))
    rig, client = routed(tmp_path, server, local)
    stream = asyncio.run(client.chat.completions.create(**REQUEST, stream=True))
    got = asyncio.run(collect(stream))
    assert text_of(got) == "local lua" and not server.requests
    assert rig.helper.tokens_per_second == 31.9 and rig.helper.in_flight == 0 and rig.helper.state == "ready"


def test_a_stream_that_breaks_continues_on_the_server_from_the_text_shown(tmp_path):
    items = [chunk("local "), chunk("Luau "), chunk("never")]
    server = Fake(Stream([chunk("then the server.")]))
    local = Fake(Stream(items, fail_after=2, error=ConnectionResetError("PC gone")))
    rig, client = routed(tmp_path, server, local)
    stream = asyncio.run(client.chat.completions.create(**REQUEST, stream=True))
    got = asyncio.run(collect(stream))
    assert text_of(got) == "local Luau then the server."
    continued = server.requests[0]
    assert continued["messages"][-1] == {"role": "assistant", "content": "local Luau "}
    assert continued["messages"][:-1] == REQUEST["messages"] and continued["stream"] is True
    assert continued["extra_body"] == REQUEST["extra_body"]
    assert rig.helper.state == "failed"


def test_a_break_before_any_text_asks_the_server_the_original_request(tmp_path):
    server = Fake(Stream([chunk("server only")]))
    local = Fake(Stream([chunk("x")], fail_after=0, error=TimeoutError()))
    _, client = routed(tmp_path, server, local)
    got = asyncio.run(collect(asyncio.run(client.chat.completions.create(**REQUEST, stream=True))))
    assert text_of(got) == "server only"
    assert server.requests[0]["messages"] == REQUEST["messages"]


def test_tool_calls_are_held_until_the_pc_finished_and_dropped_if_it_breaks(tmp_path):
    tool = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="read_file", arguments='{"pa'))
    whole = [chunk("Let me look. "), chunk(tool=tool), chunk(finish="tool_calls")]
    server, local = Fake(), Fake(Stream(whole))
    _, client = routed(tmp_path, server, local)

    async def order():
        seen = []
        async for item in await client.chat.completions.create(**REQUEST, stream=True):
            seen.append("tool" if item.choices[0].delta.tool_calls else "text" if item.choices[0].delta.content
                        else "end")
        return seen
    assert asyncio.run(order()) == ["text", "tool", "end"]

    server = Fake(Stream([chunk(tool=tool), chunk(finish="tool_calls")]))
    local = Fake(Stream(whole, fail_after=2, error=ConnectionResetError()))
    _, client = routed(tmp_path, server, local)
    got = asyncio.run(collect(asyncio.run(client.chat.completions.create(**REQUEST, stream=True))))
    assert [bool(i.choices[0].delta.tool_calls) for i in got] == [False, True, False]   # the server's call only
    assert server.requests[0]["messages"][-1] == {"role": "assistant", "content": "Let me look. "}


def test_switching_off_mid_answer_lets_the_answer_finish_on_the_pc_then_stops_it(tmp_path):
    tool = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="read_file", arguments='{"path": "a"}'))
    server = Fake(Stream([chunk("server for the next request")]))
    local = Fake(Stream([chunk("Let me look. "), chunk("Reading. "), chunk(tool=tool), chunk(finish="tool_calls")]))
    rig, client = routed(tmp_path, server, local)
    process = rig.processes[0]
    off = replace(rig.settings, use_my_gpu=False)
    seen = []

    async def answer():
        stream = await client.chat.completions.create(**REQUEST, stream=True)
        async for item in stream:
            seen.append("tool" if item.choices[0].delta.tool_calls else "text" if item.choices[0].delta.content else "end")
            if len(seen) == 1:                       # the owner flips the switch while the PC is answering
                rig.helper.configure(off, rig.home)
                assert rig.helper.status()["state"] == "off" and rig.helper.status()["enabled"] is False
                assert process.terminated is False   # the running answer is not cut
    asyncio.run(answer())
    assert seen == ["text", "text", "tool", "end"]   # complete: text, then the whole tool call, no error
    assert not server.requests and process.terminated and rig.helper.in_flight == 0
    assert rig.helper.status()["state"] == "off" and rig.helper.last_fallback == ""
    assert rig.helper.lease() is None                # the next request goes to the server
    got = asyncio.run(collect(asyncio.run(client.chat.completions.create(**REQUEST, stream=True))))
    assert text_of(got) == "server for the next request" and len(rig.started) == 1


def test_switching_off_when_nothing_runs_stops_at_once_and_a_late_failure_does_not_show_failed(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    off = replace(rig.settings, use_my_gpu=False)
    helper.configure(off, rig.home)
    assert rig.processes[0].terminated and helper.state == "off"
    rig = Rig(tmp_path)
    helper = rig.ready()
    assert helper.lease()
    helper.configure(off, rig.home)
    helper.finish(ok=False, reason="the graphics card server stopped answering", hard=True)
    assert rig.processes[0].terminated and helper.state == "off" and helper.status()["label"] == "Off"


def test_switching_on_again_mid_answer_keeps_the_loaded_model_for_the_next_request(tmp_path):
    rig = Rig(tmp_path)
    helper = rig.ready()
    assert helper.lease()
    off = replace(rig.settings, use_my_gpu=False)
    helper.configure(off, rig.home)
    helper.configure(rig.settings, rig.home)         # back on before the answer ended
    assert helper.state == "ready" and not rig.processes[0].terminated
    helper.finish(ok=True)
    assert not rig.processes[0].terminated and helper.lease() == helper.base
    assert len(rig.started) == 1


def test_automatic_night_use_runs_with_the_switch_off_and_follows_the_switch_by_day(tmp_path):
    hour = {"now": 3}
    for auto, now, runs in ((True, 3, True), (False, 3, False), (True, 14, False), (True, 8, False), (True, 1, True)):
        rig = Rig(tmp_path)
        rig.helper._hour = lambda: hour["now"]
        hour["now"] = now
        settings = replace(rig.settings, use_my_gpu=False, use_my_pc_auto_night=auto)
        rig.helper.configure(settings, rig.home, start=True)
        assert rig.helper.enabled is runs, (auto, now)
        assert rig.helper.status()["switch"] is False and rig.helper.status()["night"] is runs
    day = Rig(tmp_path)
    day.helper._hour = lambda: 14
    day.helper.configure(replace(day.settings, use_my_gpu=True, use_my_pc_auto_night=False), day.home, start=True)
    assert day.helper.enabled and day.helper.status()["switch"] is True and day.helper.status()["night"] is False
    assert gpu_helper.pc_allowed(SimpleNamespace(use_my_gpu=False)) is False      # no setting at all: fails closed


def test_the_night_ending_returns_to_the_switch_after_the_running_answer(tmp_path):
    hour = {"now": 3}
    rig = Rig(tmp_path)
    rig.helper._hour = lambda: hour["now"]
    rig.settings = replace(rig.settings, use_my_gpu=False, use_my_pc_auto_night=True)
    helper = rig.ready()
    assert helper.status()["night"] is True and "at night" in helper.status()["text"]
    assert helper.lease() == helper.base
    hour["now"] = 8                                   # 08:00: the night is over while an answer runs
    assert helper.lease() is None                     # a new request already goes to the server
    helper.tick()
    assert helper.status()["state"] == "off" and not rig.processes[0].terminated
    helper.finish(ok=True)
    assert rig.processes[0].terminated and helper.status()["enabled"] is False


def test_a_reader_that_stops_early_frees_the_pc(tmp_path):
    server, local = Fake(), Fake(Stream([chunk("a"), chunk("b"), chunk("c")]))
    rig, client = routed(tmp_path, server, local)

    async def first():
        stream = await client.chat.completions.create(**REQUEST, stream=True)
        iterator = stream.__aiter__()
        await iterator.__anext__()
        await iterator.aclose()
    asyncio.run(first())
    assert rig.helper.in_flight == 0 and rig.helper.state == "ready" and local.closed


def test_run_task_sends_the_turn_through_the_pc_only_when_switched_on(tmp_path, monkeypatch):
    import star.desktop_core as core
    import star.doc_grounding as doc_grounding
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    monkeypatch.setattr(doc_grounding, "client_for", lambda settings: None)
    rig = Rig(tmp_path)
    rig.ready()
    monkeypatch.setattr(gpu_helper, "HELPER", rig.helper)
    for on, where in ((True, "pc"), (False, "server")):
        server, local = Fake(reply("from the server")), Fake(reply("from the PC"))

        class Client:
            def __init__(self):
                self.chat = SimpleNamespace(completions=server)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False
        monkeypatch.setattr(core, "open_client", lambda settings, **_: Client())
        monkeypatch.setattr(gpu_helper, "local_client", lambda base: local)
        settings = Settings(**{**rig.settings.__dict__, "use_my_gpu": on})
        answer = core.run_task(settings, "Write a Luau function that adds two numbers.", mode="fast")
        assert answer == ("from the PC" if where == "pc" else "from the server")
        assert bool(local.requests) is (where == "pc") and bool(server.requests) is (where == "server")
