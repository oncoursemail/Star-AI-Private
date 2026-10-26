"""Developer-invoked, bounded debugpy evidence capture; dormant until called.

This runs a trusted local Python program with the developer's normal permissions.
It is NOT a security sandbox and must not be registered as a model execution tool.
The DAP client uses stdio, never attaches to a supplied PID, evaluates expressions,
changes variables, starts a terminal, or enables debugging of subprocesses.
debugpy itself uses internal loopback connections between its helper processes.
Rendering a variable may run the target's __repr__; only trusted programs belong here.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time
from typing import Any
import uuid

from .debug_common import SCHEMA, redact_debug, sha256_file, write_report

MAX_HEADER_BYTES = 4096
MAX_MESSAGE_BYTES = 262_144
MAX_SESSION_BYTES = 2_000_000
MAX_MESSAGES = 512
MAX_OUTPUT_BYTES = 16_384
MAX_FRAMES = 32
MAX_VARIABLES = 100
MAX_BREAKPOINTS = 32
MAX_TIMEOUT_SECONDS = 60
CLEANUP_SECONDS = 2.0
_SECRET_NAME = re.compile(r"(?i)(password|passwd|passphrase|secret|token|api.?key|authorization|cookie|credential|private.?key)")
_REQUESTS = frozenset({
    "initialize", "launch", "setBreakpoints", "setExceptionBreakpoints", "configurationDone",
    "stackTrace", "scopes", "variables", "exceptionInfo", "disconnect",
})


class ProtocolError(RuntimeError):
    """Invalid or unsuccessful adapter communication, never raw protocol contents."""


class CaptureLimit(ProtocolError):
    """A fixed protocol, output, or record limit was reached."""


def _integer(value: Any, *, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError("Adapter returned an invalid object")
    return value


def _records(value: Any) -> list:
    if not isinstance(value, list):
        raise ProtocolError("Adapter returned an invalid record list")
    return value


def _validate(program: Path, breakpoints, timeout_seconds, max_frames, max_variables):
    root = Path.cwd().resolve(strict=True)
    original = Path(program).expanduser()
    path = original.resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Program must be inside the current workspace; run the CLI from that workspace")
    if original.is_symlink() or path.suffix.lower() != ".py" or not path.is_file():
        raise ValueError("Program must be a regular .py file, not a symbolic link")
    if path.stat().st_size > MAX_SESSION_BYTES:
        raise ValueError("Program exceeds the 2 MB source limit")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0.2 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError("Timeout must be finite and between 0.2 and 60 seconds")
    if type(max_frames) is not int or not 1 <= max_frames <= MAX_FRAMES:
        raise ValueError("Frame limit must be between 1 and 32")
    if type(max_variables) is not int or not 1 <= max_variables <= MAX_VARIABLES:
        raise ValueError("Variable limit must be between 1 and 100")
    if breakpoints is None:
        breakpoints = []
    if not isinstance(breakpoints, list) or len(breakpoints) > MAX_BREAKPOINTS:
        raise ValueError("At most 32 breakpoint lines are allowed")
    if any(not _integer(line, minimum=1) or line > 1_000_000 for line in breakpoints):
        raise ValueError("Breakpoint lines must be positive integers at most 1000000")
    return root, path, sorted(set(breakpoints))


class _Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.sequence = 0
        self.bytes_read = 0
        self.messages_read = 0
        self.responses: dict[int, dict] = {}
        self.pending: dict[int, str] = {}
        self.events: list[dict] = []
        self.output = bytearray()
        self.output_bytes = 0
        self.stderr = bytearray()
        self.exit_code: int | None = None
        self.capabilities: dict = {}

    async def _read(self) -> dict:
        header_bytes = 0
        length = None
        while True:
            try:
                line = await self.reader.readline()
            except (ValueError, asyncio.LimitOverrunError) as exc:
                raise CaptureLimit("DAP header limit exceeded") from exc
            if not line:
                raise ProtocolError("Adapter closed its protocol stream")
            header_bytes += len(line)
            if header_bytes > MAX_HEADER_BYTES:
                raise CaptureLimit("DAP header limit exceeded")
            if line in (b"\r\n", b"\n"):
                break
            name, separator, value = line.partition(b":")
            if not separator:
                raise ProtocolError("Malformed DAP header")
            if name.strip().lower() == b"content-length":
                if length is not None or not value.strip().isdigit():
                    raise ProtocolError("Invalid DAP content length")
                length = int(value.strip())
        if length is None or not 0 < length <= MAX_MESSAGE_BYTES:
            raise CaptureLimit("DAP message size is missing or exceeds its limit")
        self.bytes_read += header_bytes + length
        self.messages_read += 1
        if self.bytes_read > MAX_SESSION_BYTES or self.messages_read > MAX_MESSAGES:
            raise CaptureLimit("DAP session byte or message limit exceeded")
        try:
            payload = await self.reader.readexactly(length)
            message = json.loads(payload)
        except (asyncio.IncompleteReadError, UnicodeError, ValueError, RecursionError) as exc:
            raise ProtocolError("Invalid or incomplete DAP JSON message") from exc
        message = _object(message)
        if not isinstance(message.get("type"), str) or message["type"] not in {"event", "response", "request"}:
            raise ProtocolError("Unknown DAP message type")
        if message["type"] == "event" and not isinstance(message.get("event"), str):
            raise ProtocolError("Invalid DAP event name")
        return message

    async def _send(self, message: dict):
        payload = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_HEADER_BYTES * 4:
            raise CaptureLimit("DAP request size exceeded")
        self.writer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload)
        await self.writer.drain()

    async def send_request(self, command: str, arguments: dict | None = None) -> int:
        if command not in _REQUESTS:
            raise ProtocolError("This capture client does not permit that DAP request")
        self.sequence += 1
        if self.sequence > MAX_MESSAGES:
            raise CaptureLimit("DAP request count exceeded")
        self.pending[self.sequence] = command
        await self._send({"seq": self.sequence, "type": "request", "command": command, "arguments": arguments or {}})
        return self.sequence

    async def _pump(self):
        message = await self._read()
        if message["type"] == "request":
            # Never honor reverse requests such as runInTerminal or startDebugging.
            await self._send({"seq": self.sequence + 1, "type": "response", "request_seq": message.get("seq"),
                              "command": message.get("command"), "success": False,
                              "message": "Only a single internal-console launch is supported"})
            self.sequence += 1
            raise ProtocolError("Adapter requested an unsupported reverse operation")
        if message["type"] == "response":
            seq = message.get("request_seq")
            if (not _integer(seq, minimum=1) or seq not in self.pending or seq in self.responses
                    or message.get("command") != self.pending[seq]):
                raise ProtocolError("Invalid DAP response sequence")
            if message.get("success") is not True:
                # In particular, a failed deferred launch must not wait for an
                # initialized event that the adapter will never send.
                raise ProtocolError("DAP request failed: " + redact_debug(message.get("message", "unspecified error"), limit=300))
            self.responses[seq] = message
            return
        body = _object(message.get("body", {}))
        if message.get("event") == "output":
            # debugpy's local DAP telemetry events are neither persisted nor transmitted.
            if body.get("category") not in {"stdout", "stderr"}:
                return
            if not isinstance(body.get("output"), str):
                raise ProtocolError("Invalid debuggee output")
            raw = body["output"].encode("utf-8")
            self.output_bytes += len(raw)
            self.output.extend(raw[:max(0, MAX_OUTPUT_BYTES - len(self.output))])
            if self.output_bytes > MAX_OUTPUT_BYTES:
                raise CaptureLimit("Debuggee output limit exceeded")
            return
        if message.get("event") == "exited":
            if type(body.get("exitCode")) is not int:
                raise ProtocolError("Invalid debuggee exit code")
            self.exit_code = body["exitCode"]
        # Store only events needed for the bounded launch/capture state machine.
        if message.get("event") in {"initialized", "stopped", "terminated", "exited"}:
            self.events.append(message)

    async def response(self, sequence: int) -> dict:
        while sequence not in self.responses:
            await self._pump()
        message = self.responses.pop(sequence)
        self.pending.pop(sequence)
        if message.get("success") is not True:
            raise ProtocolError("DAP request failed: " + redact_debug(message.get("message", "unspecified error"), limit=300))
        return _object(message.get("body", {}))

    async def request(self, command: str, arguments: dict | None = None) -> dict:
        return await self.response(await self.send_request(command, arguments))

    async def event(self, names: set[str]) -> dict:
        while True:
            for index, event in enumerate(self.events):
                if event.get("event") in names:
                    return self.events.pop(index)
            await self._pump()

    async def drain_stderr(self, reader: asyncio.StreamReader):
        total = 0
        while chunk := await reader.read(4096):
            total += len(chunk)
            self.stderr.extend(chunk[:max(0, MAX_OUTPUT_BYTES - len(self.stderr))])
            if total > MAX_OUTPUT_BYTES:
                raise CaptureLimit("Adapter diagnostic output limit exceeded")


async def _inspect_stop(client: _Client, stopped: dict, report: dict, max_frames: int, max_variables: int):
    body = _object(stopped.get("body", {}))
    report["stop_reason"] = redact_debug(body.get("reason", "unknown"), limit=100)
    report["status"] = "captured"
    report["diagnostics"].append({"category": report["stop_reason"], "message": redact_debug(body.get("description") or body.get("text") or body.get("reason"), limit=1200)})
    thread_id = body.get("threadId")
    if not _integer(thread_id, minimum=1):
        raise ProtocolError("Stopped event did not identify a valid thread")
    if body.get("reason") == "exception" and client.capabilities.get("supportsExceptionInfoRequest"):
        info = await client.request("exceptionInfo", {"threadId": thread_id})
        report["diagnostics"].append({"category": "exception", "type": redact_debug(info.get("exceptionId"), limit=200),
                                      "message": redact_debug(info.get("description"), limit=2000)})
    trace = await client.request("stackTrace", {"threadId": thread_id, "startFrame": 0, "levels": max_frames})
    for raw_frame in _records(trace.get("stackFrames", []))[:max_frames]:
        frame = _object(raw_frame)
        if not _integer(frame.get("id")):
            raise ProtocolError("Invalid stack frame identifier")
        source = _object(frame.get("source", {}))
        entry = {"frame_id": frame["id"], "name": redact_debug(frame.get("name"), limit=200),
                 "file": redact_debug(source.get("path") or source.get("name"), limit=600),
                 "line": frame.get("line") if _integer(frame.get("line")) else None}
        report["frames"].append(entry)
        if len(report["variables"]) >= max_variables:
            continue
        scopes = await client.request("scopes", {"frameId": frame["id"]})
        for raw_scope in _records(scopes.get("scopes", []))[:8]:
            scope = _object(raw_scope)
            if scope.get("presentationHint") != "locals" and str(scope.get("name", "")).lower() not in {"local", "locals"}:
                continue
            reference = scope.get("variablesReference")
            if not _integer(reference, minimum=1) or scope.get("expensive") is True:
                continue
            remaining = max_variables - len(report["variables"])
            values = await client.request("variables", {"variablesReference": reference, "filter": "named", "start": 0, "count": remaining})
            for raw_variable in _records(values.get("variables", []))[:remaining]:
                variable = _object(raw_variable)
                name = redact_debug(variable.get("name"), limit=200)
                report["variables"].append({"frame_id": frame["id"], "scope": "locals", "name": name,
                    "type": redact_debug(variable.get("type"), limit=100),
                    "value": "[REDACTED]" if _SECRET_NAME.search(str(variable.get("name", ""))) else redact_debug(variable.get("value"), limit=1000)})
            if len(report["variables"]) >= max_variables:
                break


async def _drive(client: _Client, program: Path, root: Path, breakpoints: list[int], report: dict, max_frames: int, max_variables: int):
    client.capabilities = await client.request("initialize", {
        "clientID": "star-developer-evidence", "adapterID": "python", "pathFormat": "path",
        "linesStartAt1": True, "columnsStartAt1": True, "supportsVariablePaging": True,
        "supportsRunInTerminalRequest": False, "supportsStartDebuggingRequest": False,
    })
    # The launch response is deferred until configurationDone; do not deadlock waiting for it here.
    launch_sequence = await client.send_request("launch", {
        "name": "STAR developer evidence", "type": "python", "request": "launch",
        "program": str(program), "cwd": str(root), "python": [sys.executable], "args": [],
        "console": "internalConsole", "justMyCode": True, "stopOnEntry": False,
        "subProcess": False, "redirectOutput": True, "showReturnValue": False, "logToFile": False,
    })
    await client.event({"initialized"})
    result = await client.request("setBreakpoints", {"source": {"path": str(program)},
        "breakpoints": [{"line": line} for line in breakpoints], "sourceModified": False})
    for breakpoint_record in _records(result.get("breakpoints", []))[:MAX_BREAKPOINTS]:
        item = _object(breakpoint_record)
        report["breakpoints"].append({"verified": item.get("verified") is True,
            "line": item.get("line") if _integer(item.get("line"), minimum=1) else None,
            "message": redact_debug(item.get("message"), limit=200)})
    await client.request("setExceptionBreakpoints", {"filters": ["uncaught"]})
    await client.request("configurationDone")
    await client.response(launch_sequence)
    event = await client.event({"stopped", "terminated", "exited"})
    if event["event"] == "stopped":
        await _inspect_stop(client, event, report, max_frames, max_variables)
    else:
        report["status"] = "completed" if client.exit_code == 0 else "no_stop"
        report["diagnostics"].append({"category": "no_stop", "message": "Program ended without a captured breakpoint or uncaught exception; this does not verify correctness."})


class _WindowsJob:
    """An OS kill-on-close job, assigned before sending any launch request."""
    def __init__(self, pid: int):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("minimum_ws", ctypes.c_size_t), ("maximum_ws", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                ("priority_class", wintypes.DWORD), ("scheduling_class", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel, self.handle = kernel, kernel.CreateJobObjectW(None, None)
        process_handle = None
        try:
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process_handle = kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
            if not process_handle or not kernel.AssignProcessToJobObject(self.handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if self.handle:
                kernel.CloseHandle(self.handle)
                self.handle = None
            raise
        finally:
            if process_handle:
                kernel.CloseHandle(process_handle)

    def close(self):
        if self.handle:
            try:
                self.kernel.TerminateJobObject(self.handle, 1)
            finally:
                self.kernel.CloseHandle(self.handle)
                self.handle = None


def _session_groups(session_id: int) -> set[int]:
    """Find only groups in the session we created, including debugpy's new group.

    This is lifecycle cleanup for trusted programs, not containment against a
    program deliberately daemonizing into another session.
    """
    if Path("/proc").is_dir():
        with os.scandir("/proc") as entries:
            pids = [int(entry.name) for entry in entries if entry.name.isdigit()]
    else:
        result = subprocess.run(["/bin/ps", "-axo", "pid="], capture_output=True, timeout=0.5, check=True)
        if len(result.stdout) > 1_000_000:
            raise CaptureLimit("Process inventory exceeded the cleanup bound")
        pids = [int(value) for value in result.stdout.split() if value.isdigit()]
    if len(pids) > 100_000:
        raise CaptureLimit("Process inventory exceeded the cleanup bound")
    groups = {session_id}
    for pid in pids:
        try:
            if os.getsid(pid) == session_id:
                groups.add(os.getpgid(pid))
        except (ProcessLookupError, PermissionError):
            continue
    return groups


async def _cleanup(process: asyncio.subprocess.Process, client: _Client | None, job: _WindowsJob | None) -> list[str]:
    problems = []
    if client is not None and process.returncode is None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(client.request("disconnect", {"terminateDebuggee": True, "restart": False}), 0.7)
    # Even after a normal exit, remove any descendants left in our OS session/job.
    if job is not None:
        job.close()
    elif os.name == "posix":
        try:
            groups = _session_groups(process.pid)
            for group in sorted(groups, key=lambda value: value == process.pid):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError, CaptureLimit) as exc:
            problems.append("Process-group cleanup: " + redact_debug(exc, limit=200))
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.wait(), 0.7)
    if process.returncode is None:
        problems.append("Adapter did not confirm exit within the cleanup deadline")
    if process.stdin:
        process.stdin.close()
    return problems


async def _capture(program: Path, root: Path, breakpoints: list[int], timeout_seconds: float, max_frames: int, max_variables: int) -> dict:
    started = time.monotonic()
    report = {"schema": SCHEMA, "producer": "debugpy", "run_id": uuid.uuid4().hex,
        "status": "starting", "exit_code": None, "duration_ms": 0,
        "environment": {"os": platform.system(), "python": platform.python_version(), "transport": "stdio",
                        "trusted_developer_program": True, "security_sandbox": False},
        "program": {"path": str(program.relative_to(root)), "sha256": sha256_file(program)},
        "diagnostics": [], "frames": [], "variables": [], "breakpoints": [],
        "limits": {"timeout_seconds": timeout_seconds, "max_frames": max_frames, "max_variables": max_variables,
                   "max_output_bytes": MAX_OUTPUT_BYTES, "max_message_bytes": MAX_MESSAGE_BYTES,
                   "max_session_bytes": MAX_SESSION_BYTES, "max_messages": MAX_MESSAGES},
    }
    try:
        report["environment"]["debugpy"] = importlib.metadata.version("debugpy")
    except importlib.metadata.PackageNotFoundError:
        report["status"] = "unavailable"
        report["diagnostics"].append({"category": "unavailable", "message": "debugpy is not installed in the selected Python environment; nothing was launched."})
        report["duration_ms"] = round((time.monotonic() - started) * 1000)
        return report
    process = None
    client = None
    job = None
    tasks = []
    try:
        async with asyncio.timeout(timeout_seconds):
            env = os.environ.copy()
            for name in ("DEBUGPY_LOG_DIR", "DEBUGPY_LOG_STDERR", "PYDEVD_DEBUG", "PYDEVD_DEBUG_FILE"):
                env.pop(name, None)
            kwargs: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {
                "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
            process = await asyncio.create_subprocess_exec(sys.executable, "-I", "-u", "-m", "debugpy.adapter",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=root, env=env, limit=MAX_HEADER_BYTES, **kwargs)
            if os.name == "nt":
                job = _WindowsJob(process.pid)  # Fail closed before a launch if job assignment fails.
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            client = _Client(process.stdout, process.stdin)
            drive = asyncio.create_task(_drive(client, program, root, breakpoints, report, max_frames, max_variables))
            stderr = asyncio.create_task(client.drain_stderr(process.stderr))
            tasks = [drive, stderr]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if stderr in done:
                await stderr
            await drive
    except TimeoutError:
        report["status"] = "timeout"
        report["diagnostics"].append({"category": "timeout", "message": "Capture reached its time limit; no claim of a passing run is made."})
    except asyncio.CancelledError:
        report["status"] = "cancelled"
        report["diagnostics"].append({"category": "cancelled", "message": "Capture was cancelled; the launched process tree is being terminated."})
    except CaptureLimit as exc:
        report["status"] = "limit_reached"
        report["diagnostics"].append({"category": "limit", "message": redact_debug(exc, limit=400)})
    except (ProtocolError, OSError, RuntimeError) as exc:
        report["status"] = "adapter_error"
        report["diagnostics"].append({"category": "adapter_error", "message": redact_debug(exc, limit=600)})
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if client is not None:
            # A forced termination during cleanup is not the program's natural result.
            report["exit_code"] = client.exit_code
        if process is not None:
            try:
                problems = await asyncio.wait_for(asyncio.shield(_cleanup(process, client, job)), CLEANUP_SECONDS)
            except (TimeoutError, OSError) as exc:
                problems = ["Cleanup deadline or OS operation failed: " + redact_debug(exc, limit=200)]
            for problem in problems:
                report["diagnostics"].append({"category": "cleanup_error", "message": problem})
            report["cleanup"] = "confirmed" if not problems else "incomplete"
        if client is not None:
            report["output"] = redact_debug(client.output.decode("utf-8", errors="replace"), limit=MAX_OUTPUT_BYTES)
            report["adapter_output"] = redact_debug(client.stderr.decode("utf-8", errors="replace"), limit=MAX_OUTPUT_BYTES)
            report["protocol_bytes"] = client.bytes_read
            report["protocol_messages"] = client.messages_read
        report["duration_ms"] = round((time.monotonic() - started) * 1000)
    return report


def capture_python(program: Path, *, breakpoints: list[int] | None = None, timeout_seconds: float = 15,
                   max_frames: int = 8, max_variables: int = 20) -> dict:
    """Capture the first stop of one trusted .py file in the current workspace.

    No execution happens on import. The program runs only in a separate debuggee
    process, with ordinary developer permissions. This synchronous developer API
    should be called outside a running asyncio loop (or from a worker thread).
    """
    root, program, breakpoints = _validate(program, breakpoints, timeout_seconds, max_frames, max_variables)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_capture(program, root, breakpoints, timeout_seconds, max_frames, max_variables))
    raise RuntimeError("Call capture_python from a synchronous developer command or worker thread")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ONE trusted local Python script under debugpy and save bounded evidence. "
        "Dormant until invoked. This executes code with your normal permissions; it is NOT a security sandbox or a model tool.")
    parser.add_argument("--program", type=Path, required=True, help="Trusted .py file inside the current workspace")
    parser.add_argument("--breakpoint", type=int, action="append", default=[], help="1-based breakpoint line (repeatable, maximum 32)")
    parser.add_argument("--timeout", type=float, default=15, help="Session seconds, 0.2–60; cleanup may add up to 2 seconds")
    parser.add_argument("--output", type=Path, required=True, help="Local .json evidence path")
    args = parser.parse_args(argv)
    try:
        report = capture_python(args.program, breakpoints=args.breakpoint, timeout_seconds=args.timeout)
        path = write_report(args.output, report)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, "Capture error: " + redact_debug(exc, limit=400) + "\n")
    print(f"{report['status']}: {path}")
    return 0 if report["status"] in {"captured", "completed"} and report.get("cleanup") != "incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
