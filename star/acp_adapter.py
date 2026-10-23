"""Opt-in pilot: hand one STAR chat turn to a local agent over ACP (JSON-RPC over stdio).

ACP = Agent Client Protocol (newline-delimited JSON-RPC 2.0). STAR is the client.
Off by default (``enabled=True`` is required). The adapter advertises NO client
capabilities (no fs, no terminal), so the agent cannot read or write through STAR.
Permission requests from the agent are rejected unless the host passes an
``approve`` callback, and every tool call the agent reports is kept as a receipt
labelled ``agent_reported`` (not host-verified). Nothing is installed or started
by merely importing this module.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import shutil
from typing import Any, Callable, Literal, Sequence

State = Literal["ok", "unavailable", "auth_required", "timeout", "cancelled", "error"]
_MAX_TEXT = 200_000


@dataclass(frozen=True)
class AcpTurn:
    state: State
    text: str = ""
    stop_reason: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()   # agent_reported receipts
    permission_requests: tuple[dict[str, Any], ...] = ()
    error: str = ""
    agent: str = ""


@dataclass
class AcpAdapter:
    command: Sequence[str]
    name: str = "acp-agent"
    enabled: bool = False
    cwd: str | None = None
    timeout: float = 120.0
    approve: Callable[[dict[str, Any]], bool] | None = None
    _cancel: asyncio.Event | None = field(default=None, init=False, repr=False)

    def probe(self) -> dict[str, Any]:
        """Installed check only; never launches the agent, never guesses auth or quota."""
        path = shutil.which(self.command[0]) if self.command else None
        return {"agent": self.name, "installed": bool(path), "enabled": self.enabled,
                "auth": "unknown", "quota": "unknown"}

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    async def run_turn(self, prompt: str) -> AcpTurn:
        if self.enabled is not True:
            raise PermissionError("ACP agent hand-off is off until explicitly enabled")
        if not self.probe()["installed"]:
            return AcpTurn("unavailable", error="agent command not found", agent=self.name)
        self._cancel = asyncio.Event()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command, cwd=self.cwd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError as exc:
            return AcpTurn("unavailable", error=type(exc).__name__, agent=self.name)
        try:
            return await asyncio.wait_for(self._session(proc, prompt), self.timeout)
        except asyncio.TimeoutError:
            return AcpTurn("timeout", error=f"no result in {self.timeout:g}s", agent=self.name)
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    async def _session(self, proc: asyncio.subprocess.Process, prompt: str) -> AcpTurn:
        text: list[str] = []
        calls: dict[str, dict[str, Any]] = {}
        perms: list[dict[str, Any]] = []
        nid = 0
        stdin, stdout = proc.stdin, proc.stdout
        if stdin is None or stdout is None:
            return AcpTurn("error", error="agent pipes unavailable", agent=self.name)

        def send(obj: dict[str, Any]) -> None:
            stdin.write((json.dumps(obj) + "\n").encode())

        async def request(method: str, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal nid
            nid += 1
            mine = nid
            send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params})
            await stdin.drain()
            while True:
                if self._cancel is not None and self._cancel.is_set():
                    send({"jsonrpc": "2.0", "method": "session/cancel",
                          "params": {"sessionId": params.get("sessionId", "")}})
                    await stdin.drain()
                    raise asyncio.CancelledError
                line = await stdout.readline()
                if not line:
                    raise ConnectionError("agent closed stdout")
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("id") == mine and "method" not in msg:
                    return msg
                method_in = msg.get("method")
                if method_in == "session/update":
                    self._update((msg.get("params") or {}).get("update") or {}, text, calls)
                elif method_in == "session/request_permission":
                    self._permission(msg, perms, send)
                    await stdin.drain()
                elif method_in and "id" in msg:  # fs/terminal/etc: not offered
                    send({"jsonrpc": "2.0", "id": msg["id"],
                          "error": {"code": -32601, "message": "not offered by STAR"}})
                    await stdin.drain()

        try:
            init = await request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
            if "error" in init:
                return self._fail(init["error"])
            new = await request("session/new", {"cwd": self.cwd or ".", "mcpServers": []})
            if "error" in new:
                return self._fail(new["error"])
            sid = (new.get("result") or {}).get("sessionId", "")
            done = await request("session/prompt", {
                "sessionId": sid, "prompt": [{"type": "text", "text": prompt}]})
            if "error" in done:
                return self._fail(done["error"], text="".join(text))
            stop = str((done.get("result") or {}).get("stopReason", ""))
            return AcpTurn("cancelled" if stop == "cancelled" else "ok", "".join(text)[:_MAX_TEXT],
                           stop, tuple(calls.values()), tuple(perms), agent=self.name)
        except asyncio.CancelledError:
            if not (self._cancel is not None and self._cancel.is_set()):
                raise  # timeout/outer cancellation, not a user cancel
            return AcpTurn("cancelled", "".join(text)[:_MAX_TEXT], "cancelled",
                           tuple(calls.values()), tuple(perms), agent=self.name)
        except (ConnectionError, BrokenPipeError) as exc:
            return AcpTurn("error", "".join(text)[:_MAX_TEXT], error=str(exc), agent=self.name)

    def _fail(self, err: Any, text: str = "") -> AcpTurn:
        code = err.get("code") if isinstance(err, dict) else None
        msg = str(err.get("message", "")) if isinstance(err, dict) else str(err)
        state: State = "auth_required" if code == -32000 else "error"
        return AcpTurn(state, text[:_MAX_TEXT], error=msg[:300], agent=self.name)

    @staticmethod
    def _update(upd: dict[str, Any], text: list[str], calls: dict[str, dict[str, Any]]) -> None:
        kind = upd.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = upd.get("content") or {}
            if content.get("type") == "text":
                text.append(str(content.get("text", "")))
        elif kind in ("tool_call", "tool_call_update"):
            tid = str(upd.get("toolCallId", ""))
            rec = calls.setdefault(tid, {"id": tid, "source": "agent_reported"})
            for key in ("title", "kind", "status"):
                if key in upd:
                    rec[key] = str(upd[key])

    def _permission(self, msg: dict[str, Any], perms: list[dict[str, Any]], send) -> None:
        params = msg.get("params") or {}
        options = params.get("options") or []
        tool = params.get("toolCall") or {}
        allowed = False
        if self.approve is not None:
            try:
                allowed = self.approve(params) is True
            except Exception:
                allowed = False
        want = ("allow_once",) if allowed else ("reject_once", "reject_always")
        pick = next((o.get("optionId") for o in options if o.get("kind") in want), None)
        perms.append({"tool": str(tool.get("title", tool.get("toolCallId", ""))),
                      "granted": bool(allowed and pick)})
        outcome = ({"outcome": "selected", "optionId": pick} if pick
                   else {"outcome": "cancelled"})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": outcome}})
