"""STAR compute-mesh router: one OpenAI-compatible front (:8100) over the GPU nodes and the brain's llama router.

Contract: docs/agents/WAVE-20261027-MESH-BRIEF.md. Each GPU node publishes `GET :8099/status`
({"state": "idle|busy|away|off", "models": [{"id": "litha-fast", "url": ".../v1", "loaded": true, "tok_s": ..}]}).

Models: `litha` = the best idle node by measured tok/s and queue, else the brain's star-fast; `litha-deep` = star-deep;
every other model id passes through to the brain. A request is never sent to a node whose state is not `idle` or
whose status is stale. The client sees nothing until a backend produced its first token, so any failure before that
moves on to the next backend; with hedging the two best start together and the first token wins (the other is
cancelled). Stdlib only (asyncio), so the container needs nothing but python3.
"""
from __future__ import annotations

import asyncio
import collections
import hmac
import json
import os
import time
import urllib.parse
from pathlib import Path

VERSION = "1"
FAST, DEEP = "litha", "litha-deep"

DEFAULTS = {
    "listen": "0.0.0.0",
    "port": 8100,
    "brain_url": "http://127.0.0.1:8080",
    "brain_fast_model": "star-fast",
    "brain_deep_model": "star-deep",
    "brain_tok_s": 10.0,              # starting guess until a brain answer has been measured
    "client_keys_file": "/etc/star-mesh/api_keys",   # same file the brain uses: one key per line
    "mesh_token_file": "/etc/star-mesh/mesh_token",
    "nodes": [],                      # [{"name": "owner-pc", "status_url": "http://<node>:8099/status"}]
    "node_fast_models": ["litha-fast"],
    "poll_s": 3.0,
    "status_timeout_s": 1.5,
    "stale_s": 10.0,                  # a node status older than this is not used
    "node_first_token_s": 45.0,       # no first token from a node within this -> next backend
    "brain_first_token_s": 900.0,
    "read_idle_s": 120.0,             # silence in the middle of a stream -> the backend failed
    "fail_cooldown_s": 30.0,
    "warm_every_s": 60.0,             # at most one POST /load per node per this many seconds
    "hedge": False,                   # default; a request can ask with header X-Mesh-Hedge: 1 or "mesh_hedge": true
    "max_body_mb": 64,
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    path = path or os.environ.get("STAR_MESH_CONFIG", "")
    if path and Path(path).is_file():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    for key in ("brain_url", "client_keys_file", "mesh_token_file"):
        env = os.environ.get("STAR_MESH_" + key.upper())
        if env:
            cfg[key] = env
    return cfg


class KeyFile:
    """Keys from a file (one per line, '#' comments), re-read when the file changes. Values are never logged."""

    def __init__(self, path: str):
        self.path, self.mtime, self.keys = Path(path), None, []

    def _load(self) -> list[str]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self.keys = []
            return self.keys
        if mtime != self.mtime:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            self.keys = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
            self.mtime = mtime
        return self.keys

    def first(self) -> str:
        keys = self._load()
        return keys[0] if keys else ""

    def check(self, token: str) -> bool:
        ok = False
        for key in self._load():
            ok |= hmac.compare_digest(token.encode(), key.encode())
        return ok


class UpstreamError(Exception):
    def __init__(self, msg: str, status: int = 502, body: bytes = b"", headers: dict | None = None):
        super().__init__(msg)
        self.status, self.body, self.headers = status, body, headers or {}


class Upstream:
    """One HTTP/1.1 response from a backend; `close()` aborts it (llama-server then stops generating)."""

    def __init__(self, reader, writer, status: int, headers: dict, idle_s: float):
        self.reader, self.writer, self.status, self.headers, self.idle_s = reader, writer, status, headers, idle_s

    async def _read(self, coro):
        return await asyncio.wait_for(coro, self.idle_s)

    async def chunks(self):
        if "chunked" in self.headers.get("transfer-encoding", "").lower():
            while True:
                line = await self._read(self.reader.readline())
                if not line:
                    raise UpstreamError("connection closed inside a chunked body")
                size = int(line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while (await self._read(self.reader.readline())) not in (b"\r\n", b"\n", b""):
                        pass
                    return
                data = await self._read(self.reader.readexactly(size))
                await self._read(self.reader.readexactly(2))
                yield data
        elif "content-length" in self.headers:
            left = int(self.headers["content-length"])
            while left > 0:
                data = await self._read(self.reader.read(min(65536, left)))
                if not data:
                    raise UpstreamError("connection closed before the end of the body")
                left -= len(data)
                yield data
        else:
            while data := await self._read(self.reader.read(65536)):
                yield data

    async def body(self) -> bytes:
        return b"".join([c async for c in self.chunks()])

    async def events(self):
        """Server-sent events, each as raw bytes without the blank line that ends it."""
        buf = b""
        async for chunk in self.chunks():
            buf += chunk
            if b"\r" in buf:
                buf = buf.replace(b"\r\n", b"\n")
            while (i := buf.find(b"\n\n")) >= 0:
                event, buf = buf[:i], buf[i + 2:]
                if event.strip():
                    yield event
        if buf.strip():
            yield buf

    def close(self):
        try:
            self.writer.transport.abort()
        except Exception:
            pass


async def open_upstream(url: str, method: str = "GET", body: bytes = b"", headers: dict | None = None,
                        connect_s: float = 3.0, idle_s: float = 120.0) -> Upstream:
    """Send one request and read the status line + headers (bounded by idle_s)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "http":
        raise UpstreamError(f"only http:// backends are supported ({u.scheme})")
    host, port = u.hostname or "127.0.0.1", u.port or 80
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, limit=1 << 20), connect_s)
    except (OSError, asyncio.TimeoutError) as e:
        raise UpstreamError(f"connect failed: {type(e).__name__}") from None
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    head = [f"{method} {path} HTTP/1.1", f"Host: {host}:{port}", "Connection: close", "Accept-Encoding: identity",
            f"Content-Length: {len(body)}"]
    head += [f"{k}: {v}" for k, v in (headers or {}).items()]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body)
    up = Upstream(reader, writer, 0, {}, idle_s)
    try:
        await writer.drain()
        line = await up._read(reader.readline())
        parts = line.decode("latin-1").split(" ", 2)
        if len(parts) < 2 or not parts[1].isdigit():
            raise UpstreamError("bad status line")
        up.status = int(parts[1])
        while (h := await up._read(reader.readline())) not in (b"\r\n", b"\n", b""):
            k, _, v = h.decode("latin-1").partition(":")
            up.headers[k.strip().lower()] = v.strip()
    except UpstreamError:
        up.close()
        raise
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
        up.close()
        raise UpstreamError(f"no response: {type(e).__name__}") from None
    return up


def _event_json(event: bytes):
    for line in event.split(b"\n"):
        if line.startswith(b"data:"):
            data = line[5:].strip()
            if data == b"[DONE]":
                return "DONE"
            try:
                return json.loads(data)
            except ValueError:
                return None
    return None


def first_token(event: bytes) -> bool:
    """True when this SSE event carries generated output (or ends the stream); raises on an error event."""
    obj = _event_json(event)
    if obj == "DONE":
        return True
    if not isinstance(obj, dict):
        return False
    if "error" in obj:
        raise UpstreamError(f"backend error event: {str(obj['error'])[:200]}")
    for choice in obj.get("choices") or []:
        delta = choice.get("delta") or {}
        if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls") or choice.get("text"):
            return True
        if choice.get("finish_reason"):
            return True
    return False


class Backend:
    def __init__(self, name: str, tok_s: float):
        self.name, self.tok_s, self.inflight, self.fail_until = name, tok_s, 0, 0.0
        self.served, self.samples, self.last_error = 0, 0, ""

    def score(self) -> float:
        return self.tok_s / (1 + self.inflight)

    def measured(self, tok_s: float | None):
        self.served += 1
        if tok_s and tok_s > 0:
            self.samples += 1
            self.tok_s = tok_s if self.samples == 1 else 0.7 * self.tok_s + 0.3 * tok_s


class Node(Backend):
    def __init__(self, name: str, status_url: str):
        super().__init__(name, 0.0)
        self.status_url, self.status, self.state, self.reason = status_url, {}, "unknown", "not polled yet"
        self.last_ok, self.last_warm = 0.0, 0.0

    @property
    def measured_any(self) -> bool:
        return self.samples > 0

    def model(self, ids) -> dict | None:
        for m in self.status.get("models") or []:
            if m.get("id") in ids and m.get("url"):
                return m
        return None


class Router:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.keys = KeyFile(cfg["client_keys_file"])
        self.mesh_token = KeyFile(cfg["mesh_token_file"])
        self.brain = Backend("brain1", float(cfg["brain_tok_s"]))
        self.brain_ok, self.brain_models, self.brain_models_at = None, [], 0.0
        self.nodes = [Node(n["name"], n["status_url"]) for n in cfg["nodes"]]
        self.decisions = collections.deque(maxlen=50)
        self.started = time.time()
        self.server = None

    # ---- node status ---------------------------------------------------------------------------------------------
    def _node_headers(self) -> dict:
        token = self.mesh_token.first()
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def poll_node(self, node: Node):
        try:
            up = await open_upstream(node.status_url, headers=self._node_headers(),
                                     connect_s=self.cfg["status_timeout_s"], idle_s=self.cfg["status_timeout_s"])
            try:
                raw = await asyncio.wait_for(up.body(), self.cfg["status_timeout_s"])
            finally:
                up.close()
            if up.status != 200:
                raise UpstreamError(f"status HTTP {up.status}")
            st = json.loads(raw)
            node.status, node.state = st, str(st.get("state", "unknown"))
            node.reason, node.last_ok = str(st.get("reason", "")), time.monotonic()
            m = node.model(self.cfg["node_fast_models"])
            if m and m.get("tok_s") and not node.measured_any:
                node.tok_s = float(m["tok_s"])
            if node.state == "idle" and m is not None and not m.get("loaded"):
                self._warm(node, m)
        except (UpstreamError, ValueError, asyncio.TimeoutError, OSError) as e:
            node.state, node.reason = "off", f"unreachable ({str(e)[:80]})"

    def _warm(self, node: Node, model: dict):
        now = time.monotonic()
        if now - node.last_warm < self.cfg["warm_every_s"]:
            return
        node.last_warm = now
        url = node.status_url.rsplit("/status", 1)[0] + "/load"
        body = json.dumps({"model": model["id"]}).encode()

        async def go():
            try:
                up = await open_upstream(url, "POST", body, {**self._node_headers(), "Content-Type": "application/json"},
                                         idle_s=10)
                up.close()
            except UpstreamError:
                pass
        asyncio.get_running_loop().create_task(go())

    async def poll_brain(self):
        try:
            up = await open_upstream(self.cfg["brain_url"].rstrip("/") + "/health", idle_s=3)
            await asyncio.wait_for(up.body(), 3)
            up.close()
            self.brain_ok = up.status == 200
        except (UpstreamError, asyncio.TimeoutError):
            self.brain_ok = False

    async def poll_loop(self):
        while True:
            await asyncio.gather(self.poll_brain(), *(self.poll_node(n) for n in self.nodes))
            await asyncio.sleep(self.cfg["poll_s"])

    # ---- routing -------------------------------------------------------------------------------------------------
    def node_usable(self, node: Node, now: float) -> tuple[bool, str]:
        if node.state != "idle":
            return False, f"{node.state}" + (f" ({node.reason})" if node.reason else "")
        if now - node.last_ok > self.cfg["stale_s"]:
            return False, "status stale"
        if now < node.fail_until:
            return False, f"cooling down after a failure ({node.last_error})"
        m = node.model(self.cfg["node_fast_models"])
        if m is None:
            return False, "no fast model offered"
        if not m.get("loaded"):
            return False, "model not loaded (warming)"
        return True, ""

    def plan(self, model: str) -> tuple[list[tuple[Backend, str, str]], str]:
        """Ranked [(backend, base_url, backend_model)] for a requested model, plus a reason line."""
        brain_url = self.cfg["brain_url"].rstrip("/") + "/v1"
        if model == DEEP:
            return [(self.brain, brain_url, self.cfg["brain_deep_model"])], "litha-deep -> brain star-deep"
        if model != FAST:
            return [(self.brain, brain_url, model)], "pass-through to brain"
        now, ranked, skipped = time.monotonic(), [], []
        for node in self.nodes:
            ok, why = self.node_usable(node, now)
            if ok:
                m = node.model(self.cfg["node_fast_models"])
                ranked.append((node.score(), 1, node, m["url"].rstrip("/"), m["id"]))
            else:
                skipped.append(f"{node.name}: {why}")
        ranked.append((self.brain.score(), 0, self.brain, brain_url, self.cfg["brain_fast_model"]))
        ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
        parts = [f"{b.name} {b.tok_s:.1f} tok/s q{b.inflight}" for _, _, b, _, _ in ranked]
        reason = "ranked: " + " > ".join(parts) + ("; skipped " + "; ".join(skipped) if skipped else "")
        return [(b, url, mid) for _, _, b, url, mid in ranked], reason

    def _headers_for(self, backend: Backend, client_auth: str) -> dict:
        h = {"Content-Type": "application/json"}
        if backend is self.brain:
            if client_auth:
                h["Authorization"] = client_auth     # the brain checks the same key file
        else:
            h.update(self._node_headers())
        return h

    async def _attempt(self, backend, url, path, body, client_auth, stream):
        """Start one backend; return once it produced its first token (stream) or its whole answer."""
        is_node = backend is not self.brain
        limit = self.cfg["node_first_token_s" if is_node else "brain_first_token_s"]
        backend.inflight += 1
        up = None
        try:
            async def start():
                nonlocal up
                up = await open_upstream(url + path, "POST", body, self._headers_for(backend, client_auth),
                                         idle_s=limit)
                if up.status != 200:
                    raise UpstreamError(f"HTTP {up.status}", up.status, await up.body(), up.headers)
                if not stream:
                    return up, [], await up.body()
                events, pending = up.events(), []
                async for ev in events:
                    pending.append(ev)
                    if first_token(ev):
                        return up, pending, events
                raise UpstreamError("stream ended before any token")
            result = await asyncio.wait_for(start(), limit)
            up.idle_s = self.cfg["read_idle_s"]
            return result
        except BaseException as e:
            backend.inflight -= 1
            if up is not None:
                up.close()
            if isinstance(e, asyncio.TimeoutError):
                raise UpstreamError(f"no first token within {limit:.0f} s") from None
            if isinstance(e, (OSError, asyncio.IncompleteReadError)):
                raise UpstreamError(f"{type(e).__name__}") from None
            raise

    def _failed(self, backend: Backend, err: Exception):
        backend.last_error = str(err)[:120]
        if backend is not self.brain:
            backend.fail_until = time.monotonic() + self.cfg["fail_cooldown_s"]

    async def race(self, plan, path, body_for, client_auth, stream, hedge, log):
        """Try backends best first (two at a time when hedging); the first one to produce a token wins."""
        remaining = list(plan)
        last_err: UpstreamError | None = None
        while remaining:
            n = 2 if hedge and len(remaining) >= 2 else 1
            batch, remaining = remaining[:n], remaining[n:]
            tasks = {asyncio.ensure_future(self._attempt(b, url, path, body_for(mid), client_auth, stream)): b
                     for b, url, mid in batch}
            winner = None
            try:
                while tasks and winner is None:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        b = tasks.pop(t)
                        err = t.exception()
                        if err is not None:
                            self._failed(b, err)
                            log["errors"].append(f"{b.name}: {err}")
                            last_err = err if isinstance(err, UpstreamError) else UpstreamError(str(err))
                        elif winner is None:
                            winner = (b, t.result())
                        else:                          # finished together with the winner: drop it
                            t.result()[0].close()
                            b.inflight -= 1
            finally:
                for t, b in tasks.items():             # the hedging loser (or everything on client cancel)
                    if t.done() and not t.cancelled() and t.exception() is None:
                        t.result()[0].close()
                        b.inflight -= 1
                    else:
                        t.cancel()
                    log.setdefault("cancelled", []).append(b.name)
            if winner:
                return winner
        raise last_err or UpstreamError("no backend")

    # ---- HTTP front ----------------------------------------------------------------------------------------------
    async def handle(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), 30)
            parts = line.decode("latin-1").split(" ")
            if len(parts) < 3:
                return
            method, target = parts[0], parts[1]
            headers = {}
            while (h := await asyncio.wait_for(reader.readline(), 30)) not in (b"\r\n", b"\n", b""):
                k, _, v = h.decode("latin-1").partition(":")
                headers[k.strip().lower()] = v.strip()
            n = int(headers.get("content-length") or 0)
            if n > self.cfg["max_body_mb"] << 20:
                return await send_json(writer, 413, err("request too large"))
            body = await asyncio.wait_for(reader.readexactly(n), 120) if n else b""
            await self.dispatch(method, urllib.parse.urlsplit(target).path, headers, body, writer)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def dispatch(self, method, path, headers, body, writer):
        if path == "/health":
            return await send_json(writer, 200, {"status": "ok"})
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token or not self.keys.check(token):
            return await send_json(writer, 401, err("invalid api key", "invalid_request_error"))
        if method == "GET" and path == "/v1/models":
            return await send_json(writer, 200, await self.models())
        if method == "GET" and path == "/mesh/status":
            return await send_json(writer, 200, self.status())
        if method == "POST" and path in ("/v1/chat/completions", "/v1/completions"):
            return await self.complete(path[3:], headers, body, writer)
        return await self.passthrough(method, path, auth, body, writer)

    async def models(self) -> dict:
        if time.monotonic() - self.brain_models_at > 30:
            try:
                up = await open_upstream(self.cfg["brain_url"].rstrip("/") + "/v1/models",
                                         headers={"Authorization": f"Bearer {self.keys.first()}"}, idle_s=5)
                data = json.loads(await up.body())
                up.close()
                self.brain_models = [m for m in data.get("data", []) if m.get("id") not in (FAST, DEEP)]
                self.brain_models_at = time.monotonic()
            except (UpstreamError, ValueError, asyncio.TimeoutError):
                pass
        own = [{"id": FAST, "object": "model", "owned_by": "star-mesh"},
               {"id": DEEP, "object": "model", "owned_by": "star-mesh"}]
        return {"object": "list", "data": own + self.brain_models}

    def status(self) -> dict:
        now = time.monotonic()
        nodes = []
        for n in self.nodes:
            ok, why = self.node_usable(n, now)
            nodes.append({"name": n.name, "state": n.state, "reason": n.reason, "usable": ok, "why_not": why,
                          "status_age_s": round(now - n.last_ok, 1) if n.last_ok else None,
                          "tok_s": round(n.tok_s, 1), "tok_s_measured": n.measured_any, "inflight": n.inflight,
                          "served": n.served, "last_error": n.last_error, "gpu": n.status.get("gpu"),
                          "models": [{k: m.get(k) for k in ("id", "loaded", "tok_s", "ctx")}
                                     for m in n.status.get("models") or []]})
        return {"router": {"version": VERSION, "uptime_s": round(time.time() - self.started),
                           "hedge_default": self.cfg["hedge"], "poll_s": self.cfg["poll_s"]},
                "brain": {"name": self.brain.name, "healthy": self.brain_ok, "tok_s": round(self.brain.tok_s, 1),
                          "inflight": self.brain.inflight, "served": self.brain.served},
                "nodes": nodes, "decisions": list(self.decisions)[::-1]}

    async def complete(self, path, headers, body, writer):
        try:
            req = json.loads(body or b"{}")
            assert isinstance(req, dict)
        except (ValueError, AssertionError):
            return await send_json(writer, 400, err("body must be a JSON object"))
        model, stream = str(req.get("model") or FAST), bool(req.get("stream"))
        hedge = req.pop("mesh_hedge", None)
        if hedge is None:
            hedge = headers.get("x-mesh-hedge", "").strip().lower() in ("1", "true", "yes") or self.cfg["hedge"]
        def body_for(mid):
            return json.dumps({**req, "model": mid}).encode()

        plan, reason = self.plan(model)
        t0 = time.monotonic()
        log = {"ts": round(time.time(), 3), "model": model, "stream": stream, "hedge": bool(hedge),
               "candidates": [b.name for b, _, _ in plan], "reason": reason, "errors": []}
        self.decisions.append(log)
        try:
            backend, result = await self.race(plan, path, body_for, headers.get("authorization", ""), stream,
                                              bool(hedge), log)
        except UpstreamError as e:
            log.update(chosen=None, outcome=f"failed: {e}")
            print("mesh", json.dumps(log), flush=True)
            if e.body:
                return await send_raw(writer, e.status, e.headers.get("content-type", "application/json"), e.body)
            return await send_json(writer, 502, err(f"no backend answered: {e}", "server_error"))
        log["chosen"] = backend.name
        up, pending, rest = result
        log["ttft_ms"] = round((time.monotonic() - t0) * 1000)
        try:
            if not stream:
                await send_raw(writer, 200, up.headers.get("content-type", "application/json"), rest,
                               {"X-Mesh-Backend": backend.name})
                try:
                    timings = json.loads(rest).get("timings") or {}
                except (ValueError, AttributeError):
                    timings = {}
                backend.measured(timings.get("predicted_per_second"))
                log["tok_s"], log["outcome"] = timings.get("predicted_per_second"), "ok"
                return
            await self.relay_stream(backend, up, pending, rest, writer, log)
        finally:
            backend.inflight -= 1
            up.close()
            log["total_ms"] = round((time.monotonic() - t0) * 1000)
            print("mesh", json.dumps(log), flush=True)

    async def relay_stream(self, backend, up, pending, events, writer, log):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\n"
                     b"Connection: close\r\nX-Mesh-Backend: " + backend.name.encode() + b"\r\n\r\n")
        first_at, pieces, timings = time.monotonic(), 0, None
        try:
            for ev in pending:
                writer.write(ev + b"\n\n")
            await writer.drain()
            async for ev in events:
                writer.write(ev + b"\n\n")
                await writer.drain()
                if b'"timings"' in ev:
                    obj = _event_json(ev)
                    if isinstance(obj, dict) and isinstance(obj.get("timings"), dict):
                        timings = obj["timings"]
                elif b'"content"' in ev or b'"reasoning_content"' in ev:
                    pieces += 1
            tok_s = (timings or {}).get("predicted_per_second")
            if tok_s is None and pieces > 4:
                tok_s = pieces / max(1e-3, time.monotonic() - first_at)
            backend.measured(tok_s)
            log["tok_s"], log["outcome"] = round(tok_s, 1) if tok_s else None, "ok"
        except (ConnectionError, OSError) as e:
            log["outcome"] = f"client went away ({type(e).__name__})"
        except (UpstreamError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
            self._failed(backend, e)
            log["outcome"] = f"backend failed mid-stream: {str(e) or type(e).__name__}"
            try:
                msg = {"error": {"message": f"mesh: {backend.name} stopped in the middle of the answer",
                                 "type": "server_error"}}
                writer.write(b"data: " + json.dumps(msg).encode() + b"\n\ndata: [DONE]\n\n")
                await writer.drain()
            except (ConnectionError, OSError):
                pass

    async def passthrough(self, method, path, auth, body, writer):
        try:
            up = await open_upstream(self.cfg["brain_url"].rstrip("/") + path, method, body,
                                     {"Content-Type": "application/json", **({"Authorization": auth} if auth else {})},
                                     idle_s=self.cfg["brain_first_token_s"])
        except UpstreamError as e:
            return await send_json(writer, 502, err(f"brain: {e}", "server_error"))
        try:
            writer.write(f"HTTP/1.1 {up.status} X\r\nContent-Type: "
                         f"{up.headers.get('content-type', 'application/json')}\r\nConnection: close\r\n\r\n".encode())
            async for chunk in up.chunks():
                writer.write(chunk)
                await writer.drain()
        except (UpstreamError, asyncio.TimeoutError, ConnectionError, OSError):
            pass
        finally:
            up.close()

    async def serve(self):
        self.server = await asyncio.start_server(self.handle, self.cfg["listen"], self.cfg["port"], limit=1 << 20)
        return self.server


def err(message: str, kind: str = "invalid_request_error") -> dict:
    return {"error": {"message": message, "type": kind}}


async def send_raw(writer, status: int, ctype: str, body: bytes, extra: dict | None = None):
    head = f"HTTP/1.1 {status} X\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in (extra or {}).items())
    writer.write(head.encode("latin-1") + b"\r\n" + body)
    await writer.drain()


async def send_json(writer, status: int, obj, extra: dict | None = None):
    await send_raw(writer, status, "application/json", json.dumps(obj).encode(), extra)


async def main(config_path: str | None = None):
    router = Router(load_config(config_path))
    await router.serve()
    print(f"star-mesh {VERSION} on {router.cfg['listen']}:{router.cfg['port']}, nodes: "
          f"{', '.join(n.name for n in router.nodes) or 'none'}", flush=True)
    await router.poll_loop()
