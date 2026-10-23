"""Real Settings and run_task paths, with model and HTTP boundaries replaced by fakes."""
import asyncio
from contextlib import asynccontextmanager
import json
import secrets
from types import SimpleNamespace

import httpx
import pytest

from star import desktop_core, doc_grounding, doc_knowledge
from star.desktop_core import Settings, run_task
from star.luau_run_repair import MARKER

CODE = "return 6 * 7\n"
ANSWER = "Example:\n```luau\n" + CODE + "```\n"


def response(ok=True):
    return {"executed": True, "ok": ok, "status": "pass" if ok else "fail",
            "exit_code": 0 if ok else 1, "timed_out": False, "output_limited": False,
            "error": "" if ok else "runtime_error", "errors": [], "output": "42",
            "usage": {"wall_seconds": 0.01, "cpu_seconds": 0.001,
                      "max_rss_bytes": 4096, "output_bytes": 2}}


def test_real_settings_default_old_file_and_saved_opt_in(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings().luau_run_before_answer is False
    assert Settings.load(path).luau_run_before_answer is False
    path.write_text(json.dumps({"model": "m", "studio_target": "local_pc"}), encoding="utf-8")
    old = Settings.load(path)
    assert old.luau_run_before_answer is False
    old.luau_run_before_answer = True
    old.save(path)
    assert json.loads(path.read_text())["luau_run_before_answer"] is True
    restored = Settings.load(path)
    assert restored.luau_run_before_answer is True
    assert restored.studio_edit is False and restored.studio_luau is False
    restored.luau_run_before_answer = False
    restored.save(path)
    assert Settings.load(path).luau_run_before_answer is False


def test_the_settings_switch_is_saved_through_the_desktop_bridge(tmp_path):
    """The React Settings checkbox reaches Settings only through the shell allowlist."""
    from star.react_shell import apply_setting_changes
    path = tmp_path / "settings.json"
    settings = apply_setting_changes(Settings(), {"luau_run_before_answer": True})
    settings.save(path)
    assert Settings.load(path).luau_run_before_answer is True
    settings = apply_setting_changes(Settings.load(path), {"luau_run_before_answer": False})
    settings.save(path)
    assert Settings.load(path).luau_run_before_answer is False


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_settings_reject_non_boolean_grants(value, tmp_path):
    with pytest.raises(ValueError, match="true or false"):
        Settings(luau_run_before_answer=value).save(tmp_path / "settings.json")
    assert not (tmp_path / "settings.json").exists()


class Model:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        assert not kwargs.get("stream"), "opt-in code must not be shown before review"
        system = str((kwargs.get("messages") or [{}])[0].get("content") or "")
        if "Write independent executable assertions" in system:
            text = "```luau\nassert(result == 42)\nassert(result ~= 0)\n```"
        elif "Repair one pure Luau module" in system:
            text = "```luau\n" + CODE + "```"
        else:
            text = ANSWER
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))])


@pytest.mark.parametrize("status, ok", [(200, True), (200, False), (503, False), (429, False)])
def test_run_task_real_model_path_and_client_http_contract(monkeypatch, tmp_path, status, ok):
    model = Model()
    calls, events = [], []
    key = secrets.token_hex(24)
    def server(request):
        calls.append(request)
        assert request.method == "POST" and request.url.path == "/luau/run"
        assert request.headers["Authorization"] == "Bearer " + key
        assert json.loads(request.content) == {
            "code": CODE, "tests": "assert(result == 42)\nassert(result ~= 0)\n",
            "time_limit_s": 3.0, "memory_limit_mb": 256}
        return httpx.Response(status, json=response(ok) if status == 200 else {"executed": False})
    knowledge = doc_knowledge.KnowledgeClient("https://knowledge.invalid", key, httpx.MockTransport(server))
    @asynccontextmanager
    async def model_client(settings, **kwargs):
        yield model
    monkeypatch.setattr(desktop_core, "app_data", lambda: tmp_path)
    monkeypatch.setattr(desktop_core, "open_client", model_client)
    monkeypatch.setattr(doc_knowledge, "client_for", lambda settings: knowledge)
    # This question has no documentation route: the opt-in must not depend on a search hit.
    answer = run_task(Settings(model="m", luau_run_before_answer=True, verify_ladder="off"),
                      "Give a tiny arithmetic example.", mode="fast", stream_tokens=True,
                      on_event=events.append)
    assert len(calls) == 1
    assert len(model.calls) == (3 if status == 200 and not ok else 2)
    assert CODE in answer and MARKER in answer
    assert ("generated assertions passed" in answer) is (status == 200 and ok)
    assert ("not verified" in answer) is (status != 200)
    transcript = json.loads(next((tmp_path / "runs").glob("*/transcript.json")).read_text())
    assert transcript["messages"][-1]["content"] == answer
    records = [a["star_luau_run"]["blocks"] for a in transcript["archive"] if "star_luau_run" in a]
    assert len(records) == 1 and records[0][0]["ran"] is (status == 200)
    assert key not in json.dumps(transcript) and "https://knowledge.invalid" not in json.dumps(transcript)
    assert next((tmp_path / "runs").glob("*/answer.md")).read_text() == answer
    names = [event.get("event") for event in events]
    assert names.index("luau_run_finished") < names.index("saved")
    assert "assistant_delta" not in names


@pytest.mark.parametrize("enabled", [False, True])
def test_run_task_streaming_gate_and_default_no_client_access(monkeypatch, tmp_path, enabled):
    captured = []
    @asynccontextmanager
    async def model_client(settings, **kwargs):
        yield Model()
    async def execute(**kwargs):
        captured.append(kwargs["stream_tokens"])
        return ANSWER, [{"role": "assistant", "content": ANSWER}], []
    def no_client(settings):
        assert enabled, "default-off must not resolve a sandbox client"
        return None
    monkeypatch.setattr(desktop_core, "app_data", lambda: tmp_path)
    monkeypatch.setattr(desktop_core, "open_client", model_client)
    monkeypatch.setattr(desktop_core, "execute", execute)
    monkeypatch.setattr(doc_knowledge, "client_for", no_client)
    answer = run_task(Settings(model="m", luau_run_before_answer=enabled, verify_ladder="off"),
                      "Give a tiny arithmetic example.", mode="fast", stream_tokens=True)
    assert captured == [not enabled]
    assert (MARKER in answer) is enabled
    if not enabled:
        assert answer == ANSWER


def test_runtime_uses_the_repaired_displayed_code_and_preserves_transcript(monkeypatch):
    original = '```luau\nlocal x: string = 1\nreturn x\n```'
    fixed = 'local x: string = "1"\nreturn x\n'
    checked, executed = [], []
    class Knowledge:
        def luau_check(self, code):
            checked.append(code)
            return {"ran": True, "ok": len(checked) > 1, "error_count": 1 if len(checked) == 1 else 0,
                    "errors": [{"line": 1, "column": 1, "kind": "TypeError", "message": "Use a string"}]
                              if len(checked) == 1 else []}
        def luau_run(self, code, **kwargs):
            executed.append(code)
            return {"ran": True, **response()}
    class Repair:
        def __init__(self):
            self.calls = 0
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        async def create(self, **kwargs):
            self.calls += 1
            text = ('```luau\n' + fixed + '```' if self.calls == 1
                    else '```luau\nassert(result == "1")\nassert(result ~= "2")\n```')
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    knowledge = Knowledge()
    monkeypatch.setattr(doc_knowledge, "client_for", lambda settings: knowledge)
    found = doc_grounding.Grounding(client=knowledge,
        plan=SimpleNamespace(check_luau=True, retrieve="none", reasons=()))
    route = SimpleNamespace(task_timeout=600, quick=False, model="m", response_tokens=1600)
    from time import monotonic
    result = asyncio.run(doc_grounding.finalize(found, route,
        (original, [{"role": "assistant", "content": original}], []), model_client=Repair(),
        settings=Settings(luau_run_before_answer=True, verify_ladder="off"), started=monotonic()))
    assert len(checked) == 2 and executed == [fixed]
    assert fixed in result[0] and "not run by this static check" in result[0]
    assert "generated assertions passed" in result[0] and result[1][-1]["content"] == result[0]
    assert any("star_luau_run" in item for item in result[2])


def test_knowledge_off_is_not_overridden_by_execution_opt_in(monkeypatch):
    def no_vault(*args, **kwargs):
        pytest.fail("knowledge=off must not access a key or transport")
    monkeypatch.setattr(doc_knowledge, "get_api_key", no_vault)
    assert doc_knowledge.client_for(Settings(luau_run_before_answer=True, knowledge_endpoint="off")) is None
