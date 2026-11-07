"""Protocol bounds and opt-in debugger lifecycle tests on synthetic local programs."""
from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

import pytest

from star import debug_dap as dap


def _wire(message: dict) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


class Writer:
    def __init__(self, reader=None, handler=None):
        self.reader, self.handler = reader, handler
        self.messages = []

    def write(self, data):
        message = json.loads(data.split(b"\r\n\r\n", 1)[1])
        self.messages.append(message)
        if self.handler:
            for reply in self.handler(message):
                self.reader.feed_data(_wire(reply))

    async def drain(self):
        pass


def _reply(request, body=None):
    return {"seq": 1, "type": "response", "command": request["command"],
            "request_seq": request["seq"], "success": True, "body": body or {}}


def _event(name, body=None):
    return {"seq": 1, "type": "event", "event": name, "body": body or {}}


@pytest.mark.parametrize("raw, expected", [
    (b"Content-Length: 999999999\r\n\r\n", dap.CaptureLimit),
    (b"Content-Length: -1\r\n\r\n", dap.ProtocolError),
    (b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}", dap.ProtocolError),
    (b"Content-Length: 3\r\n\r\n{xx", dap.ProtocolError),
    (b"Content-Length: 5\r\n\r\n{}", dap.ProtocolError),
    (b"x" * (dap.MAX_HEADER_BYTES + 1) + b"\n", dap.CaptureLimit),
    (_wire({"type": []}), dap.ProtocolError),
])
def test_rejects_invalid_or_oversized_frames(raw, expected):
    async def run():
        reader = asyncio.StreamReader(limit=dap.MAX_HEADER_BYTES)
        reader.feed_data(raw)
        reader.feed_eof()
        with pytest.raises(expected):
            await dap._Client(reader, Writer())._read()
    asyncio.run(run())


def test_framing_counts_utf8_bytes_and_session_limits(monkeypatch):
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(_wire(_event("stopped", {"description": "réel"})))
        client = dap._Client(reader, Writer())
        assert (await client._read())["body"]["description"] == "réel"
        monkeypatch.setattr(dap, "MAX_MESSAGES", 1)
        reader.feed_data(_wire(_event("initialized")))
        with pytest.raises(dap.CaptureLimit, match="session"):
            await client._read()
    asyncio.run(run())


def test_full_fake_handshake_preserves_early_stop_and_only_reads_bounded_locals(tmp_path):
    async def run():
        launch = None

        def handle(request):
            nonlocal launch
            command = request["command"]
            if command == "initialize":
                return [_event("output", {"category": "telemetry", "output": "do-not-persist"}),
                        _reply(request, {"supportsExceptionInfoRequest": True})]
            if command == "launch":
                launch = request
                return [_event("initialized")]
            if command == "configurationDone":
                return [_event("stopped", {"reason": "exception", "threadId": 7, "description": "division by zero"}),
                        _reply(launch), _reply(request)]
            if command == "exceptionInfo":
                return [_reply(request, {"exceptionId": "ZeroDivisionError", "description": "division by zero"})]
            if command == "stackTrace":
                return [_reply(request, {"stackFrames": [
                    {"id": index, "name": "fail", "source": {"path": str(tmp_path / "fail.py")}, "line": 4}
                    for index in range(1, 6)]})]
            if command == "scopes":
                return [_reply(request, {"scopes": [
                    {"name": "Globals", "variablesReference": 999},
                    {"name": "Locals", "presentationHint": "locals", "variablesReference": 123}]})]
            if command == "variables":
                assert request["arguments"]["variablesReference"] == 123
                return [_reply(request, {"variables": [
                    {"name": "count", "value": "7", "type": "int"},
                    {"name": "api_key", "value": "short-secret", "type": "str"},
                    {"name": "not_requested", "value": "ignore"}]})]
            return [_reply(request)]

        reader = asyncio.StreamReader()
        writer = Writer(reader, handle)
        client = dap._Client(reader, writer)
        report = {"frames": [], "variables": [], "diagnostics": [], "breakpoints": []}
        await asyncio.wait_for(dap._drive(client, tmp_path / "fail.py", tmp_path, [4], report, 2, 2), 1)
        assert report["status"] == "captured"
        assert len(report["frames"]) == 2
        assert len(report["variables"]) == 2
        assert report["variables"][1]["value"] == "[REDACTED]"
        assert "short-secret" not in json.dumps(report)
        assert not client.output
        commands = [message["command"] for message in writer.messages]
        assert commands == ["initialize", "launch", "setBreakpoints", "setExceptionBreakpoints", "configurationDone",
                            "exceptionInfo", "stackTrace", "scopes", "variables"]
        assert launch["arguments"]["subProcess"] is False
        assert launch["arguments"]["console"] == "internalConsole"
        assert launch["arguments"]["stopOnEntry"] is False
    asyncio.run(run())


def test_reverse_requests_are_rejected_and_no_expression_execution_is_available():
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(_wire({"seq": 9, "type": "request", "command": "runInTerminal", "arguments": {"args": ["unexpected"]}}))
        writer = Writer()
        client = dap._Client(reader, writer)
        with pytest.raises(dap.ProtocolError, match="reverse"):
            await client._pump()
        assert writer.messages[0]["success"] is False
        for command in ("attach", "evaluate", "setVariable", "continue", "runInTerminal"):
            with pytest.raises(dap.ProtocolError, match="does not permit"):
                await client.send_request(command)
    asyncio.run(run())


def test_unknown_response_cannot_supply_results():
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(_wire({"type": "response", "request_seq": 100, "command": "initialize", "success": True}))
        with pytest.raises(dap.ProtocolError, match="sequence"):
            await dap._Client(reader, Writer())._pump()
    asyncio.run(run())


def test_failed_deferred_launch_reports_immediately_and_redacts_error(tmp_path):
    async def run():
        def handle(request):
            reply = _reply(request)
            if request["command"] == "launch":
                reply.update(success=False, message="Cannot launch; password=synthetic-short-secret")
            return [reply]

        reader = asyncio.StreamReader()
        client = dap._Client(reader, Writer(reader, handle))
        report = {"frames": [], "variables": [], "diagnostics": [], "breakpoints": []}
        with pytest.raises(dap.ProtocolError, match="Cannot launch") as caught:
            await asyncio.wait_for(dap._drive(client, tmp_path / "fail.py", tmp_path, [], report, 2, 2), 0.2)
        assert "synthetic-short-secret" not in str(caught.value)
    asyncio.run(run())


def test_output_burst_is_bounded_and_stderr_has_independent_limit():
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(_wire(_event("output", {"category": "stdout", "output": "x" * (dap.MAX_OUTPUT_BYTES + 1)})))
        client = dap._Client(reader, Writer())
        with pytest.raises(dap.CaptureLimit, match="output limit"):
            await client._pump()
        assert len(client.output) == dap.MAX_OUTPUT_BYTES
        stderr = asyncio.StreamReader()
        stderr.feed_data(b"x" * (dap.MAX_OUTPUT_BYTES + 1))
        with pytest.raises(dap.CaptureLimit, match="diagnostic output"):
            await client.drain_stderr(stderr)
        assert len(client.stderr) == dap.MAX_OUTPUT_BYTES
    asyncio.run(run())


@pytest.mark.parametrize("options", [
    {"timeout_seconds": float("nan")}, {"timeout_seconds": 0}, {"timeout_seconds": 61},
    {"max_frames": True}, {"max_frames": 33}, {"max_variables": 101},
    {"breakpoints": [False]}, {"breakpoints": [0]}, {"breakpoints": list(range(1, 34))},
])
def test_input_bounds_prevent_launch(tmp_path, monkeypatch, options):
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "safe.py"
    program.write_text("pass\n")
    with pytest.raises(ValueError):
        dap.capture_python(program, **options)


def test_program_must_be_regular_python_inside_current_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n")
    with pytest.raises(ValueError, match="inside"):
        dap.capture_python(outside)
    wrong = workspace / "wrong.txt"
    wrong.write_text("pass\n")
    with pytest.raises(ValueError, match="regular .py"):
        dap.capture_python(wrong)
    link = workspace / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        return  # Windows accounts without symlink privilege still test the path checks above.
    with pytest.raises(ValueError):
        dap.capture_python(link)


def test_missing_debugpy_is_honest_and_does_not_launch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "safe.py"
    program.write_text("raise RuntimeError('must not run')\n")

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(dap.importlib.metadata, "version", missing)
    report = dap.capture_python(program)
    assert report["status"] == "unavailable"
    assert report["exit_code"] is None
    assert report["frames"] == []


def _has_debugpy():
    try:
        importlib.metadata.version("debugpy")
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


REAL_DEBUGPY = pytest.mark.skipif(not _has_debugpy(), reason="Optional debugpy package is not installed")


@REAL_DEBUGPY
def test_real_debugpy_captures_exception_and_redacts_locals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "failure.py"
    program.write_text("def fail():\n    count = 7\n    api_key = 'synthetic-short-secret'\n    denominator = 0\n    return count / denominator\nfail()\n")
    report = dap.capture_python(program, timeout_seconds=15, max_frames=3, max_variables=20)
    assert report["status"] == "captured", report
    assert report["stop_reason"] == "exception"
    assert report["cleanup"] == "confirmed"
    assert any(frame["file"].endswith("failure.py") and frame["line"] == 5 for frame in report["frames"])
    values = {value["name"]: value["value"] for value in report["variables"]}
    assert values["count"] == "7"
    assert values["api_key"] == "[REDACTED]"
    assert "synthetic-short-secret" not in json.dumps(report)
    assert report["exit_code"] is None  # No natural program exit was observed before terminating the capture.


@REAL_DEBUGPY
def test_real_breakpoint_stops_before_later_code_and_normal_run_is_not_a_correctness_claim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "breakpoint.py"
    program.write_text("from pathlib import Path\nstage = 'before'\nstage = 'after'\nPath('must-not-exist').write_text('bad')\n")
    report = dap.capture_python(program, breakpoints=[3], timeout_seconds=15)
    assert report["status"] == "captured", report
    assert report["stop_reason"] == "breakpoint"
    assert any(value["name"] == "stage" and "before" in value["value"] for value in report["variables"])
    assert not (tmp_path / "must-not-exist").exists()
    normal = tmp_path / "normal.py"
    normal.write_text("print('synthetic normal completion')\n")
    report = dap.capture_python(normal, timeout_seconds=15)
    assert report["status"] == "completed", report
    assert report["exit_code"] == 0
    assert any(item["category"] == "no_stop" for item in report["diagnostics"])
    assert "synthetic normal completion" in report["output"]


def _windows_alive(pid: int) -> bool:
    # Windows os.kill(pid, 0) terminates the target instead of probing it.
    # SYNCHRONIZE grants only the read-only wait needed to inspect process exit.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE; no terminate rights.
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: this process no longer exists.
            return False
        raise ctypes.WinError(error)  # Inability to observe is never proof of cleanup.
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 258:  # WAIT_TIMEOUT: the process handle is not signaled.
            return True
        if status == 0:  # WAIT_OBJECT_0: the process exited.
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.parametrize("handle,wait_status,error,expected", [
    (9, 258, 0, True), (9, 0, 0, False), (None, None, 87, False), (None, None, 5, "error"),
])
def test_windows_liveness_probe_is_read_only_and_observation_errors_do_not_pass(
        monkeypatch, handle, wait_status, error, expected):
    import ctypes
    from types import SimpleNamespace

    calls = []

    def open_process(*args):
        calls.append(("open", *args))
        return handle

    def wait(*args):
        calls.append(("wait", *args))
        return wait_status

    def close(*args):
        calls.append(("close", *args))
        return True

    kernel = SimpleNamespace(OpenProcess=open_process, WaitForSingleObject=wait, CloseHandle=close)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda value: OSError(value, "synthetic query error"), raising=False)
    if expected == "error":
        with pytest.raises(OSError):
            _windows_alive(1234)
    else:
        assert _windows_alive(1234) is expected
    assert calls == ([("open", 0x00100000, False, 1234), ("wait", 9, 0), ("close", 9)]
                     if handle else [("open", 0x00100000, False, 1234)])


def _alive(pid: int) -> bool:
    if os.name == "nt":
        return _windows_alive(pid)
    if sys.platform.startswith("linux"):
        try:
            return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0] != "Z"
        except FileNotFoundError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _assert_dead(pid: int):
    deadline = time.monotonic() + 2
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _alive(pid), f"Synthetic debuggee process {pid} is still alive"


@REAL_DEBUGPY
def test_real_timeout_terminates_debuggee_and_undebugged_child(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "wait.py"
    program.write_text("import os, pathlib, subprocess, sys, time\n"
        "pathlib.Path('debuggee.pid').write_text(str(os.getpid()))\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "time.sleep(60)\n")
    started = time.monotonic()
    report = dap.capture_python(program, timeout_seconds=5)
    assert report["status"] == "timeout", report
    assert report["cleanup"] == "confirmed", report
    assert time.monotonic() - started < 9
    for filename in ("debuggee.pid", "child.pid"):
        path = tmp_path / filename
        assert path.exists(), "Synthetic program did not start before timeout"
        _assert_dead(int(path.read_text()))


@REAL_DEBUGPY
def test_real_cancel_terminates_debuggee(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "cancel.py"
    program.write_text("import os, pathlib, time\npathlib.Path('cancel.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n")

    async def run():
        task = asyncio.create_task(dap._capture(program, tmp_path, [], 15, 8, 20))
        deadline = asyncio.get_running_loop().time() + 8
        while not (tmp_path / "cancel.pid").exists():
            if task.done() or asyncio.get_running_loop().time() > deadline:
                if not task.done():
                    task.cancel()
                pytest.fail("Synthetic debuggee did not start: " + str(await task))
            await asyncio.sleep(0.025)
        task.cancel()
        return await task

    report = asyncio.run(run())
    assert report["status"] == "cancelled", report
    assert report["cleanup"] == "confirmed", report
    _assert_dead(int((tmp_path / "cancel.pid").read_text()))


def test_cli_requires_explicit_program_and_explains_trust_boundary(capsys):
    with pytest.raises(SystemExit) as caught:
        dap.main(["--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "NOT a security sandbox" in text
    assert "--program" in text
    assert "--output" in text
