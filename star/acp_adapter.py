"""Opt-in pilot: hand STAR chat turns to a local agent over ACP (JSON-RPC over stdio).

ACP = Agent Client Protocol (newline-delimited JSON-RPC 2.0). STAR is the client.
``AcpAdapter`` implements the typed ``AgentSessionAdapter`` contract (star/agent_session.py):
``probe`` / ``start`` / ``stream`` / ``request_tool_approval`` / ``cancel`` / ``stop``;
``run_turn`` is start + stream + stop in one bounded call.
Off by default (``enabled=True`` is required). The adapter advertises NO client
capabilities (no fs, no terminal), so the agent cannot read or write through STAR.
Permission requests from the agent are rejected unless the host passes an
``approve`` callback, and every tool call the agent reports is kept as a receipt
labelled ``agent_reported`` (not host-verified). Model list, tier and billing come
only from an owner-authorized ``usage_probe`` (a provider API call), never from names.
Nothing is installed or started by merely importing this module.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import shutil
from typing import Any, AsyncIterator, Callable, Mapping, Sequence

from star.agent_session import (UNMEASURED, AuthState, SessionEvent, SessionProbe, SessionState,
                                TurnState, UsageReport)
from star.process_shutdown import terminate_managed_async
from star.process_supervisor import ProcessTreeSupervisor, start_managed_async_process

State = TurnState
_MAX_TEXT = 200_000
_POLL = 0.1   # seconds between cancel checks while the agent is silent


class _UserCancel(Exception):
    pass


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
    usage_probe: Callable[[], UsageReport] | None = None   # owner-authorized provider API call
    state: SessionState = field(default="idle", init=False)
    auth: AuthState = field(default="unknown", init=False)   # "ok" = the agent opened a session without login
    error: str = field(default="", init=False)
    last_turn: AcpTurn | None = field(default=None, init=False)
    _cancel: asyncio.Event | None = field(default=None, init=False, repr=False)
    _proc: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)
    _tree: ProcessTreeSupervisor | None = field(default=None, init=False, repr=False)
    process_tree_mode: str = field(default="", init=False)
    _sid: str = field(default="", init=False, repr=False)
    _nid: int = field(default=0, init=False, repr=False)
    _text: list[str] = field(default_factory=list, init=False, repr=False)
    _calls: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _perms: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def probe(self) -> SessionProbe:
        """Installed check plus the host's usage measurement; never launches the agent, never guesses."""
        usage, err = UNMEASURED, ""
        if self.usage_probe is not None:
            try:
                got = self.usage_probe()
            except Exception as exc:
                got, err = None, f"usage probe failed: {type(exc).__name__}"
            if isinstance(got, UsageReport):
                usage = got
            elif not err:
                err = "usage probe returned no UsageReport"
        return SessionProbe(self.name, self._installed(), self.enabled, self.state, self.auth, usage,
                            err or self.error)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    async def request_tool_approval(self, request: Mapping[str, Any]) -> bool:
        """The host's ``approve`` decides; no callback, an error or anything but True is a no."""
        if self.approve is None:
            return False
        try:
            return self.approve(request) is True  # type: ignore[arg-type]
        except Exception:
            return False

    async def start(self) -> SessionState:
        """Launch the agent and open one session (initialize + session/new)."""
        if self.enabled is not True:
            raise PermissionError("ACP agent hand-off is off until explicitly enabled")
        if self._proc is not None:
            raise RuntimeError("ACP session already started")
        self._cancel, self._text, self._calls, self._perms = asyncio.Event(), [], {}, []
        self.error, self.last_turn = "", None
        if not self._installed():
            return await self._down("unavailable", "agent command not found")
        try:
            self._tree = await start_managed_async_process(
                *self.command, cwd=self.cwd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            self._proc = self._tree.process
            self.process_tree_mode = self._tree.mode
        except OSError as exc:
            return await self._down("unavailable", type(exc).__name__)
        deadline = asyncio.get_running_loop().time() + self.timeout
        try:
            reply = await self._call("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, deadline)
            if "error" not in reply:
                reply = await self._call("session/new", {"cwd": self.cwd or ".", "mcpServers": []}, deadline)
        except _UserCancel:
            return await self._down("cancelled", "cancelled before the session opened")
        except TimeoutError:
            return await self._down("timeout", f"no session in {self.timeout:g}s")
        except (ConnectionError, BrokenPipeError) as exc:
            return await self._down("error", str(exc))
        if "error" in reply:
            failed = self._fail(reply["error"])
            from typing import cast

            return await self._down(cast("SessionState", failed.state), failed.error)
        self._sid = str((reply.get("result") or {}).get("sessionId", ""))
        self.auth, self.state = "ok", "ready"
        return "ready"

    async def stream(self, prompt: str) -> AsyncIterator[SessionEvent]:
        """One prompt on the open session; events as they arrive, then one ``end`` event."""
        if self.state != "ready" or self._proc is None:
            raise RuntimeError("start() must return 'ready' before stream()")
        self.state, self._text, self._calls, self._perms = "running", [], {}, []
        deadline = asyncio.get_running_loop().time() + self.timeout
        done: dict[str, Any] = {}
        try:
            async for item in self._exchange("session/prompt", {
                    "sessionId": self._sid, "prompt": [{"type": "text", "text": prompt}]}, deadline):
                if isinstance(item, SessionEvent):
                    yield item
                else:
                    done = item
            if "error" in done:
                turn = self._fail(done["error"])
            else:
                stop = str((done.get("result") or {}).get("stopReason", ""))
                turn = self._turn("cancelled" if stop == "cancelled" else "ok", stop)
        except _UserCancel:
            turn = self._turn("cancelled", "cancelled")
        except TimeoutError:
            turn = self._turn("timeout", error=f"no result in {self.timeout:g}s")
        except (ConnectionError, BrokenPipeError) as exc:
            turn = self._turn("error", error=str(exc))
        self.last_turn = turn
        if turn.state in ("ok", "cancelled"):
            self.state = "ready"   # the session takes another prompt
            if self._cancel is not None:
                self._cancel.clear()
        else:
            await self._down(turn.state, turn.error)
        yield SessionEvent("end", {"state": turn.state, "stop_reason": turn.stop_reason, "error": turn.error})

    async def stop(self) -> None:
        await self._close()
        if self.state in ("ready", "running"):
            self.state = "stopped"

    async def run_turn(self, prompt: str) -> AcpTurn:
        """One prompt: start, stream to the end, stop. The whole call is bounded by ``timeout``."""
        if self.enabled is not True:
            raise PermissionError("ACP agent hand-off is off until explicitly enabled")
        try:
            return await asyncio.wait_for(self._one_turn(prompt), self.timeout)
        except TimeoutError:
            self.state, self.error = "timeout", f"no result in {self.timeout:g}s"
            return self._turn("timeout", error=self.error)
        finally:
            await self.stop()

    async def _one_turn(self, prompt: str) -> AcpTurn:
        state = await self.start()
        if state != "ready":
            return AcpTurn(state, error=self.error, agent=self.name)  # type: ignore[arg-type]
        async for _ in self.stream(prompt):
            pass
        return self.last_turn or AcpTurn("error", error="no turn result", agent=self.name)

    def _installed(self) -> bool:
        return bool(self.command) and shutil.which(self.command[0]) is not None

    async def _down(self, state: SessionState, error: str) -> SessionState:
        self.state, self.error = state, error
        if state == "auth_required":
            self.auth = "auth_required"
        await self._close()
        return state

    async def _close(self) -> None:
        proc, self._proc = self._proc, None
        tree, self._tree = self._tree, None
        if proc is None:
            return
        if tree is not None:
            empty = await terminate_managed_async(tree, grace_period_s=0.35)
            tree.close()
            if not empty:
                self.error = (self.error + "; process-tree cleanup not confirmed after hard-stop")[-300:]
        elif proc.returncode is None:
            proc.kill()
        if proc.returncode is None:
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=2.0)
            except TimeoutError:
                self.error = (self.error + "; worker exit not confirmed")[-300:]

    def _send(self, obj: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise ConnectionError("agent pipes unavailable")
        self._proc.stdin.write((json.dumps(obj) + "\n").encode())

    async def _call(self, method: str, params: dict[str, Any], deadline: float) -> dict[str, Any]:
        reply: dict[str, Any] = {}
        async for item in self._exchange(method, params, deadline):
            if isinstance(item, dict):
                reply = item
        return reply

    async def _exchange(self, method: str, params: dict[str, Any],
                        deadline: float) -> AsyncIterator[SessionEvent | dict[str, Any]]:
        """Send one request; yield events until its response, which is yielded last."""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise ConnectionError("agent pipes unavailable")
        stdin, stdout = proc.stdin, proc.stdout
        loop = asyncio.get_running_loop()
        self._nid += 1
        mine = self._nid
        self._send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params})
        await stdin.drain()
        while True:
            if self._cancel is not None and self._cancel.is_set():
                self._send({"jsonrpc": "2.0", "method": "session/cancel",
                            "params": {"sessionId": params.get("sessionId", "")}})
                await stdin.drain()
                raise _UserCancel
            left = deadline - loop.time()
            if left <= 0:
                raise TimeoutError
            try:   # a partly read line stays buffered, so polling for a cancel is safe
                line = await asyncio.wait_for(stdout.readline(), min(left, _POLL))
            except TimeoutError:
                continue
            if not line:
                raise ConnectionError("agent closed stdout")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == mine and "method" not in msg:
                yield msg
                return
            method_in = msg.get("method")
            raw_params = msg.get("params")
            params_in = raw_params if isinstance(raw_params, dict) else {}
            if method_in == "session/update":
                event = self._update(params_in.get("update"))
                if event is not None:
                    yield event
            elif method_in == "session/request_permission" and "id" in msg:
                event = await self._permission(msg["id"], params_in)
                await stdin.drain()
                yield event
            elif method_in and "id" in msg:  # fs/terminal/etc: not offered
                self._send({"jsonrpc": "2.0", "id": msg["id"],
                            "error": {"code": -32601, "message": "not offered by STAR"}})
                await stdin.drain()

    def _turn(self, state: State, stop: str = "", error: str = "") -> AcpTurn:
        return AcpTurn(state, "".join(self._text)[:_MAX_TEXT], stop, tuple(self._calls.values()),
                       tuple(self._perms), error, self.name)

    def _fail(self, err: Any) -> AcpTurn:
        code = err.get("code") if isinstance(err, dict) else None
        msg = str(err.get("message", "")) if isinstance(err, dict) else str(err)
        state: State = "auth_required" if code == -32000 else "error"
        return self._turn(state, error=msg[:300])

    def _update(self, upd: Any) -> SessionEvent | None:
        if not isinstance(upd, dict):
            return None
        kind = upd.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = upd.get("content") or {}
            if isinstance(content, dict) and content.get("type") == "text":
                chunk = str(content.get("text", ""))
                self._text.append(chunk)
                return SessionEvent("text", {"text": chunk})
        elif kind in ("tool_call", "tool_call_update"):
            tid = str(upd.get("toolCallId", ""))
            rec = self._calls.setdefault(tid, {"id": tid, "source": "agent_reported"})
            for key in ("title", "kind", "status"):
                if key in upd:
                    rec[key] = str(upd[key])
            return SessionEvent("tool_call", dict(rec))
        return None

    async def _permission(self, req_id: Any, params: dict[str, Any]) -> SessionEvent:
        options = params.get("options") or []
        tool = params.get("toolCall") or {}
        allowed = await self.request_tool_approval(params)
        want = ("allow_once",) if allowed else ("reject_once", "reject_always")
        pick = next((o.get("optionId") for o in options if isinstance(o, dict) and o.get("kind") in want), None)
        title = str(tool.get("title", tool.get("toolCallId", ""))) if isinstance(tool, dict) else ""
        rec = {"tool": title, "granted": bool(allowed and pick)}
        self._perms.append(rec)
        outcome = ({"outcome": "selected", "optionId": pick} if pick
                   else {"outcome": "cancelled"})
        self._send({"jsonrpc": "2.0", "id": req_id, "result": {"outcome": outcome}})
        return SessionEvent("permission", dict(rec))
