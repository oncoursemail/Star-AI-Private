"""STAR compute-mesh router: one OpenAI-compatible front (:8100) over the GPU nodes and the brain's llama router.

Contract: docs/agents/WAVE-20261027-MESH-BRIEF.md. Each GPU node publishes `GET :8099/status`
({"state": "idle|busy|away|off", "models": [{"id": "litha-fast", "url": ".../v1", "loaded": true, "tok_s": ..}]}).

Models: `litha` = the best idle node by measured tok/s and queue, else the brain's star-fast; `litha-deep` = star-deep;
every other model id passes through to the brain. A request is never sent to a node whose state is not `idle` or
whose status is stale. The client sees nothing until a backend produced its first token, so any failure before that
moves on to the next backend; with hedging the two best start together and the first token wins (the other is
cancelled). A stream that stops without a finish_reason (connection drop, error event, killed model) is a cut: the
answer goes on on the next backend with the words already sent as an assistant prefix, stitched into the same
stream; only when no backend can continue does the client get an error event. Stdlib only (asyncio), so the
container needs nothing but python3.
"""
from __future__ import annotations

import asyncio
import collections
import hmac
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

from . import instant

VERSION = "3"
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
    "max_continuations": 2,           # a cut stream goes on on another backend at most this many times
    "warm_every_s": 60.0,             # at most one POST /load per node per this many seconds
    "hedge": False,                   # default; a request can ask with header X-Mesh-Hedge: 1 or "mesh_hedge": true
    "max_body_mb": 64,
    "register_ttl_s": 60.0,           # a self-registration lasts this long unless re-sent (nodes re-send every 30 s)
    "max_registered": 16,
    # instant answers (server/mesh/instant.py)
    "affinity_bonus": 2.0,            # score multiplier for the backend that holds the conversation's KV cache
    "affinity_ttl_s": 1800.0,
    "prefetch_debounce_s": 0.4,       # at most one prefetch per conversation per this many seconds (latest text wins)
    "prefetch_max_tokens": 0,         # 0 = prompt only (llama-server fills the KV cache and returns)
    "prefetch_brain": True,           # prefetch on the brain too, only while its model is already loaded and idle
    "verify_url": "http://127.0.0.1:8101",   # the verifier; /mesh/verify on this router is forwarded there
    "cache_db": "",                   # SQLite path of the verified answer cache; "" = cache off
    "cache_threshold": 0.95,          # cosine for a semantic hit (calibrated on star-embed: 0 false hits in 27 near
                                      # misses, 5 of 19 paraphrases; docs/agents/instant-answers-20261028.md)
    "cache_ttl_days": 30.0,
    "cache_reverify_s": 86400.0,      # a hit on an entry verified longer ago than this re-checks it in the background
    "cache_min_score_ratio": 1.0,     # entries need score / max_score >= this (full marks by default)
    "embed_model": "star-embed",
    "embed_prefix": "task: sentence similarity | query: ",
    "embed_timeout_s": 1.0,
}
NODE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


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


LOOPBACK = ("0.0.0.0", "localhost", "127.0.0.1", "::", "::1")


def _same_host(url: str, ref: str) -> str:
    """A loopback host in a node-reported URL means 'me': use the host the router reaches the node on."""
    u, r = urllib.parse.urlsplit(url), urllib.parse.urlsplit(ref)
    if u.hostname in LOOPBACK and r.hostname and r.hostname not in LOOPBACK:
        return u._replace(netloc=f"{r.hostname}:{u.port or 80}").geturl()
    return url


class Node(Backend):
    def __init__(self, name: str, status_url: str | None, static: bool = True):
        super().__init__(name, 0.0)
        self.static_url = status_url if static else None
        self.status, self.state, self.reason = {}, "unknown", "not polled yet"
        self.last_ok, self.last_warm = 0.0, 0.0
        self.reg_status_url, self.reg_model_url, self.reg_until = status_url if not static else None, None, 0.0

    def registered(self, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) < self.reg_until

    @property
    def status_url(self) -> str:
        return self.reg_status_url if self.registered() and self.reg_status_url else (self.static_url or "")

    @property
    def source(self) -> str:
        if self.static_url:
            return "static+registered" if self.registered() else "static"
        return "registered"

    @property
    def measured_any(self) -> bool:
        return self.samples > 0

    def model(self, ids) -> dict | None:
        url = self.reg_model_url if self.registered() else None
        for m in self.status.get("models") or []:
            if m.get("id") in ids and (url or m.get("url")):
                return {**m, "url": url or _same_host(m["url"], self.status_url)}
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
        self.affinity = instant.Affinity(cfg["affinity_ttl_s"])
        self.prefetching: dict[str, dict] = {}
        self.counters = collections.Counter()
        self.cache = instant.AnswerCache(cfg["cache_db"]) if cfg.get("cache_db") else None

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

    def register(self, body: dict, peer: str) -> tuple[int, dict]:
        """Node self-registration (heartbeat). Missing URLs are built from the request's source address."""
        name = str(body.get("node") or "")
        if not NODE_NAME.match(name):
            return 400, err("node must be 1-40 letters, digits, '.', '_' or '-'")
        urls = {"status_url": str(body.get("status_url") or "") or f"http://{peer}:8099/status",
                "model_url": str(body.get("model_url") or "")}
        for key, port in (("status_url", 8099), ("model_url", 8098)):
            if not urls[key]:
                continue                  # no model_url: the URL in the node's own status is used
            u = urllib.parse.urlsplit(urls[key])
            if u.scheme != "http" or not u.hostname:
                return 400, err(f"{key} must be an http:// URL")
            if u.hostname in LOOPBACK and peer:   # the node does not know its LAN address: use the source IP
                urls[key] = u._replace(netloc=f"{peer}:{u.port or port}").geturl()
        node = next((n for n in self.nodes if n.name == name), None)
        if node is None:
            if sum(1 for n in self.nodes if not n.static_url) >= self.cfg["max_registered"]:
                return 429, err("too many registered nodes")
            node = Node(name, urls["status_url"], static=False)
            self.nodes.append(node)
        fresh = not node.registered() or node.reg_status_url != urls["status_url"]
        node.reg_status_url, node.reg_model_url = urls["status_url"], urls["model_url"] or None
        node.reg_until = time.monotonic() + self.cfg["register_ttl_s"]
        if fresh:                                   # poll it now so it can take requests at once
            asyncio.get_running_loop().create_task(self.poll_node(node))
        return 200, {"ok": True, "node": name, "source": node.source, **urls,
                     "expires_in_s": self.cfg["register_ttl_s"]}

    def expire(self):
        """Drop registered-only nodes whose heartbeat stopped; static nodes fall back to their configured URL."""
        now = time.monotonic()
        self.nodes = [n for n in self.nodes if n.static_url or n.registered(now)]

    async def poll_loop(self):
        while True:
            self.expire()
            now = time.monotonic()
            for key in [k for k, v in self.prefetching.items() if now - v["last"] > 60 and v["task"].done()]:
                del self.prefetching[key]
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

    def plan(self, model: str, conv: str | None = None) -> tuple[list[tuple[Backend, str, str]], str]:
        """Ranked [(backend, base_url, backend_model)] for a requested model, plus a reason line. The backend that
        served this conversation last gets `affinity_bonus` on its score (its llama-server still holds the KV)."""
        brain_url = self.cfg["brain_url"].rstrip("/") + "/v1"
        if model == DEEP:
            return [(self.brain, brain_url, self.cfg["brain_deep_model"])], "litha-deep -> brain star-deep"
        if model != FAST:
            return [(self.brain, brain_url, model)], "pass-through to brain"
        now, ranked, skipped = time.monotonic(), [], []
        sticky = self.affinity.get(conv)

        def bonus(b):
            return self.cfg["affinity_bonus"] if b.name == sticky else 1.0
        for node in self.nodes:
            ok, why = self.node_usable(node, now)
            if ok:
                m = node.model(self.cfg["node_fast_models"])
                ranked.append((node.score() * bonus(node), 1, node, m["url"].rstrip("/"), m["id"]))
            else:
                skipped.append(f"{node.name}: {why}")
        ranked.append((self.brain.score() * bonus(self.brain), 0, self.brain, brain_url,
                       self.cfg["brain_fast_model"]))
        ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
        parts = [f"{b.name} {b.tok_s:.1f} tok/s q{b.inflight}" + (" (kv)" if b.name == sticky else "")
                 for _, _, b, _, _ in ranked]
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
                    data = await up.body()
                    try:
                        whole = isinstance(json.loads(data), dict)
                    except ValueError:
                        whole = False
                    if not whole:
                        raise UpstreamError("answer cut (incomplete body)")
                    return up, [], data
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
            peer = (writer.get_extra_info("peername") or ("",))[0]
            url = urllib.parse.urlsplit(target)
            headers[":query"] = url.query
            await self.dispatch(method, url.path, headers, body, writer, peer)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def dispatch(self, method, path, headers, body, writer, peer=""):
        if path == "/health":
            return await send_json(writer, 200, {"status": "ok"})
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if method == "POST" and path == "/mesh/register":
            mesh_token = self.mesh_token.first()
            if not token or not mesh_token or not hmac.compare_digest(token.encode(), mesh_token.encode()):
                return await send_json(writer, 401, err("invalid mesh token", "invalid_request_error"))
            try:
                req = json.loads(body or b"{}")
                assert isinstance(req, dict)
            except (ValueError, AssertionError):
                return await send_json(writer, 400, err("body must be a JSON object"))
            return await send_json(writer, *self.register(req, peer))
        if path == "/mesh/cache" and method != "GET":    # cache changes: mesh token (checked in cache_api)
            return await send_json(writer, *await self.cache_api(method, headers, body))
        if not token or not self.keys.check(token):
            return await send_json(writer, 401, err("invalid api key", "invalid_request_error"))
        if method == "GET" and path == "/v1/models":
            return await send_json(writer, 200, await self.models())
        if method == "GET" and path == "/mesh/status":
            return await send_json(writer, 200, self.status())
        if method == "POST" and path == "/mesh/prefetch":
            return await send_json(writer, *await self.prefetch(body, headers))
        if path == "/mesh/verify":
            return await self.forward(self.cfg["verify_url"], method, path, headers, body, writer)
        if path == "/mesh/cache":
            return await send_json(writer, *await self.cache_api(method, headers, body))
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
            nodes.append({"name": n.name, "source": n.source, "status_url": n.status_url,
                          "registered_expires_in_s": round(n.reg_until - now, 1) if n.registered(now) else None,
                          "state": n.state, "reason": n.reason, "usable": ok, "why_not": why,
                          "status_age_s": round(now - n.last_ok, 1) if n.last_ok else None,
                          "tok_s": round(n.tok_s, 1), "tok_s_measured": n.measured_any, "inflight": n.inflight,
                          "served": n.served, "last_error": n.last_error, "gpu": n.status.get("gpu"),
                          "models": [{k: m.get(k) for k in ("id", "loaded", "tok_s", "ctx")}
                                     for m in n.status.get("models") or []]})
        return {"router": {"version": VERSION, "uptime_s": round(time.time() - self.started),
                           "hedge_default": self.cfg["hedge"], "poll_s": self.cfg["poll_s"]},
                "brain": {"name": self.brain.name, "healthy": self.brain_ok, "tok_s": round(self.brain.tok_s, 1),
                          "inflight": self.brain.inflight, "served": self.brain.served},
                "instant": {"affinity_conversations": len(self.affinity), "counters": dict(self.counters),
                            "cache": self.cache.stats() if self.cache else None,
                            "cache_threshold": self.cfg["cache_threshold"]},
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
        conv = instant.conversation_key(req, headers) if model == FAST else None
        t0 = time.monotonic()
        cache_hdr, question, context = {}, None, ""
        if model == FAST and self.cache is not None:
            cache_hdr, question, context = self.cache_check(req, headers)
            row = self.cache.exact(question, context) if question else None
            if row is not None:
                return await self.serve_cached(row, "exact", 1.0, round((time.monotonic() - t0) * 1000, 1), stream,
                                               writer, t0)
        for k in instant.MESH_FIELDS:
            req.pop(k, None)
        if model == FAST:
            req.setdefault("cache_prompt", True)

        def body_for(mid):
            return json.dumps({**req, "model": mid}).encode()

        plan, reason = self.plan(model, conv)
        log = {"ts": round(time.time(), 3), "model": model, "stream": stream, "hedge": bool(hedge),
               "candidates": [b.name for b, _, _ in plan], "reason": reason, "errors": []}
        if conv:
            log["conv"], log["affinity"] = conv[:12], self.affinity.get(conv)
        self.decisions.append(log)
        # the semantic cache lookup (an embedding round trip) runs while the backend starts: a hit before the first
        # token cancels the backend, otherwise the live answer goes on and the lookup costs nothing
        race = asyncio.ensure_future(self.race(plan, path, body_for, headers.get("authorization", ""), stream,
                                               bool(hedge), log))
        if question:
            lookup = asyncio.ensure_future(self.cache_semantic(question, context))
            await asyncio.wait({race, lookup}, return_when=asyncio.FIRST_COMPLETED)
            if lookup.done() and not race.done():
                row, sim, ms = lookup.result()
                if row is not None:
                    race.cancel()
                    await asyncio.gather(race, return_exceptions=True)
                    log.update(chosen=None, outcome="cancelled: semantic cache hit")
                    return await self.serve_cached(row, "semantic", sim, ms, stream, writer, t0)
                cache_hdr["X-Mesh-Cache-Ms"] = str(ms)
                if sim is not None:
                    cache_hdr["X-Mesh-Cache-Similarity"] = f"{sim:.4f}"
                    log["cache_similarity"] = round(sim, 4)
            else:
                lookup.cancel()
                cache_hdr["X-Mesh-Cache-Ms"] = "late"
            self.counters["cache_miss"] += 1
        if cache_hdr:
            log["cache"] = cache_hdr.get("X-Mesh-Cache")
        try:
            backend, result = await race
        except UpstreamError as e:
            log.update(chosen=None, outcome=f"failed: {e}")
            print("mesh", json.dumps(log), flush=True)
            if e.body:
                return await send_raw(writer, e.status, e.headers.get("content-type", "application/json"), e.body)
            return await send_json(writer, 502, err(f"no backend answered: {e}", "server_error"))
        log["chosen"] = backend.name
        self.affinity.set(conv, backend.name)
        up, pending, rest = result
        log["ttft_ms"] = round((time.monotonic() - t0) * 1000)
        try:
            if not stream:
                await send_raw(writer, 200, up.headers.get("content-type", "application/json"), rest,
                               {"X-Mesh-Backend": backend.name, **cache_hdr})
                try:
                    timings = json.loads(rest).get("timings") or {}
                except (ValueError, AttributeError):
                    timings = {}
                backend.measured(timings.get("predicted_per_second"))
                log["tok_s"], log["outcome"] = timings.get("predicted_per_second"), "ok"
                return
            await self.relay_stream(backend, up, pending, rest, writer, log, cache_hdr,
                                    {"model": model, "req": req, "path": path, "conv": conv,
                                     "auth": headers.get("authorization", "")})
        finally:
            backend.inflight -= 1
            up.close()
            log["total_ms"] = round((time.monotonic() - t0) * 1000)
            print("mesh", json.dumps(log), flush=True)

    async def relay_stream(self, backend, up, pending, events, writer, log, extra=None, ctx=None):
        """Relay a stream to the client. A stream that ends without a finish_reason/[DONE], drops, or sends an error
        event is a cut: it goes on on the next backend (`_continue`), stitched into the same response."""
        more = "".join(f"{k}: {v}\r\n" for k, v in (extra or {}).items()).encode("latin-1")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\n"
                     b"Connection: close\r\nX-Mesh-Backend: " + backend.name.encode() + b"\r\n" + more + b"\r\n")
        sent, used, skip = [], [backend], ""
        seg, own = (backend, up, pending, events), False     # own: a continuation, closed here (not by complete())
        try:
            while True:
                b, u, pend, evs = seg
                first_at, pieces, timings, finished, why = time.monotonic(), 0, None, False, ""
                try:
                    async for ev in _chain(pend, evs):
                        obj = _event_json(ev)
                        if obj == "DONE":
                            finished = True
                            break
                        if isinstance(obj, dict) and "error" in obj:
                            why = f"error event: {str(obj['error'])[:160]}"
                            break
                        if isinstance(obj, dict):
                            changed = False
                            for choice in obj.get("choices") or []:
                                delta = choice.get("delta") or {}
                                text = delta.get("content")
                                if text and skip:           # the continuation repeats the cut word: drop that part
                                    text, skip = _strip_tail(text, skip)
                                    delta["content"], changed = text, True
                                if text:
                                    sent.append(text)
                                    pieces += 1
                                elif delta.get("reasoning_content"):
                                    pieces += 1
                                if choice.get("finish_reason"):
                                    finished = True
                            if isinstance(obj.get("timings"), dict):
                                timings = obj["timings"]
                            if changed:
                                ev = b"data: " + json.dumps(obj).encode()
                        writer.write(ev + b"\n\n")
                        await writer.drain()
                except (UpstreamError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                    why = why or f"connection dropped: {str(e) or type(e).__name__}"
                if finished and not why:
                    tok_s = (timings or {}).get("predicted_per_second")
                    if tok_s is None and pieces > 4:
                        tok_s = pieces / max(1e-3, time.monotonic() - first_at)
                    b.measured(tok_s)
                    log["tok_s"] = round(tok_s, 1) if tok_s else None
                    log["outcome"] = "ok" if b is backend else f"cut, continued on {b.name}: ok"
                    writer.write(b"data: [DONE]\n\n")
                    await writer.drain()
                    return
                why = why or "stream ended without a finish_reason"
                self._failed(b, UpstreamError(why))
                log.setdefault("cuts", []).append({"backend": b.name, "why": why, "sent_chars": sum(map(len, sent))})
                if own:
                    b.inflight -= 1
                    u.close()
                    own = False
                nxt = None
                if ctx and len(log["cuts"]) <= self.cfg["max_continuations"]:
                    nxt, skip = await self._continue(ctx, "".join(sent), len(sent), used, log)
                if nxt is None:
                    log["outcome"] = f"cut: {b.name}: {why}; nobody could continue, error sent"
                    msg = {"error": {"message": f"mesh: {b.name} stopped in the middle of the answer",
                                     "type": "server_error"}}
                    writer.write(b"data: " + json.dumps(msg).encode() + b"\n\ndata: [DONE]\n\n")
                    await writer.drain()
                    return
                seg, own = nxt, True
                used.append(nxt[0])
        except (ConnectionError, OSError) as e:
            log["outcome"] = f"client went away ({type(e).__name__})"
        finally:
            if own:
                seg[0].inflight -= 1
                seg[1].close()

    async def _continue(self, ctx: dict, partial: str, pieces: int, used: list, log: dict):
        """Start the next backend for a cut stream: same request, plus the words already sent as an assistant prefix
        (llama-server continues an assistant message that ends the conversation). The prefix stops before the last
        word, so the model writes that word whole; `tail` (the part already sent) is dropped from its output.
        Returns ((backend, upstream, pending, events), tail), or (None, "") when no backend starts."""
        prefill, tail = _split_prefix(partial)
        req = dict(ctx["req"])
        if prefill:
            if ctx["path"] == "/chat/completions":
                msgs = list(req.get("messages") or [])
                last = msgs[-1] if msgs and isinstance(msgs[-1], dict) else {}
                if last.get("role") == "assistant" and isinstance(last.get("content"), str):
                    msgs[-1] = {**last, "content": last["content"] + prefill}
                else:
                    msgs.append({"role": "assistant", "content": prefill})
                req["messages"] = msgs
            else:
                req["prompt"] = str(req.get("prompt") or "") + prefill
            for k in ("max_tokens", "n_predict", "max_completion_tokens"):
                if isinstance(req.get(k), int) and req[k] > 0:
                    req[k] = max(32, req[k] - pieces)
        plan, _ = self.plan(ctx["model"], ctx["conv"])
        plan = [p for p in plan if p[0] not in used]
        if not plan:
            return None, ""
        sub = {"errors": []}
        try:
            backend, (up, pending, events) = await self.race(
                plan, ctx["path"], lambda mid: json.dumps({**req, "model": mid}).encode(), ctx["auth"], True, False,
                sub)
        except UpstreamError:
            log["errors"] += sub["errors"]
            return None, ""
        log["errors"] += sub["errors"]
        log.setdefault("continued_on", []).append(backend.name)
        self.affinity.set(ctx["conv"], backend.name)
        return (backend, up, pending, events), tail

    # ---- instant answers -----------------------------------------------------------------------------------------
    async def prefetch(self, body: bytes, headers: dict) -> tuple[int, dict]:
        """Warm the KV cache of the backend that will serve this conversation (prompt only, no answer). Debounced:
        at most one upstream prefetch per conversation per `prefetch_debounce_s`; newer text replaces waiting text."""
        try:
            req = json.loads(body or b"{}")
            assert isinstance(req, dict) and isinstance(req.get("messages"), list) and req["messages"]
        except (ValueError, AssertionError):
            return 400, err("body must be {\"messages\": [...], \"conversation_id\"?: ...}")
        if str(req.get("model") or FAST) != FAST:
            return 400, err(f"prefetch is for model {FAST} only")
        conv = instant.conversation_key(req, headers)
        if conv is None:
            return 400, err("need a user message or a conversation_id")
        slot = self.prefetching.setdefault(conv, {"last": 0.0, "task": None, "result": None})
        slot["payload"], slot["auth"] = req, headers.get("authorization", "")
        self.counters["prefetch_requests"] += 1
        if slot["task"] is None or slot["task"].done():
            slot["task"] = asyncio.get_running_loop().create_task(self._prefetch_loop(conv, slot))
            state = "scheduled"
        else:
            state = "debounced"
            self.counters["prefetch_debounced"] += 1
        if req.get("wait"):
            await asyncio.shield(slot["task"])
            return 200, {"ok": True, "conversation": conv[:12], **(slot["result"] or {})}
        return 202, {"ok": True, "conversation": conv[:12], "state": state}

    async def _prefetch_loop(self, conv: str, slot: dict):
        while slot.get("payload") is not None:
            wait = slot["last"] + self.cfg["prefetch_debounce_s"] - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            req = slot.pop("payload", None)
            if req is None:
                break
            slot["last"] = time.monotonic()
            try:
                slot["result"] = await self._prefetch_once(conv, req, slot.get("auth", ""))
            except Exception as e:                       # never let a prefetch break anything
                slot["result"] = {"skipped": f"error: {type(e).__name__}"}

    async def _brain_loaded(self, model: str) -> bool:
        await self.models()
        for m in self.brain_models:
            if model == m.get("id") or model in (m.get("aliases") or []):
                return (m.get("status") or {}).get("value", "loaded") == "loaded"
        return False

    async def _prefetch_once(self, conv: str, req: dict, auth: str) -> dict:
        plan, _ = self.plan(FAST, conv)
        backend, url, mid = plan[0]
        if backend.inflight > 0:
            self.counters["prefetch_skipped"] += 1
            return {"backend": backend.name, "skipped": "backend busy with an answer"}
        if backend is self.brain and not (self.cfg["prefetch_brain"] and await self._brain_loaded(mid)):
            self.counters["prefetch_skipped"] += 1
            return {"backend": backend.name, "skipped": "brain model not loaded (a prefetch never loads one)"}
        body = {k: v for k, v in req.items() if k not in instant.MESH_FIELDS + ("wait", "stream_options")}
        body.update(model=mid, stream=False, max_tokens=self.cfg["prefetch_max_tokens"], cache_prompt=True)
        t0 = time.monotonic()
        try:
            up = await open_upstream(url + "/chat/completions", "POST", json.dumps(body).encode(),
                                     self._headers_for(backend, auth), idle_s=60)
            try:
                raw = await asyncio.wait_for(up.body(), 60)
            finally:
                up.close()
        except (UpstreamError, asyncio.TimeoutError) as e:
            self.counters["prefetch_failed"] += 1
            return {"backend": backend.name, "skipped": f"failed: {str(e)[:80] or type(e).__name__}"}
        if up.status != 200:
            self.counters["prefetch_failed"] += 1
            return {"backend": backend.name, "skipped": f"HTTP {up.status}"}
        self.affinity.set(conv, backend.name)
        self.counters["prefetch_sent"] += 1
        try:
            t = json.loads(raw).get("timings") or {}
        except (ValueError, AttributeError):
            t = {}
        return {"backend": backend.name, "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n"),
                "prompt_ms": t.get("prompt_ms"), "ms": round((time.monotonic() - t0) * 1000)}

    async def forward(self, base: str, method: str, path: str, headers: dict, body: bytes, writer):
        """/mesh/verify -> the verifier (same key; the fix loop can take minutes)."""
        query = headers.get(":query") or ""
        url = base.rstrip("/") + path + (f"?{query}" if query else "")
        try:
            up = await open_upstream(url, method, body, {"Content-Type": "application/json",
                                                         "Authorization": headers.get("authorization", "")},
                                     idle_s=400)
            data = await asyncio.wait_for(up.body(), 400)
            up.close()
        except (UpstreamError, asyncio.TimeoutError) as e:
            return await send_json(writer, 502, err(f"verifier: {e}", "server_error"))
        return await send_raw(writer, up.status, up.headers.get("content-type", "application/json"), data)

    async def embed(self, text: str) -> list[float] | None:
        body = json.dumps({"model": self.cfg["embed_model"], "input": self.cfg["embed_prefix"] + text}).encode()
        try:
            up = await open_upstream(self.cfg["brain_url"].rstrip("/") + "/v1/embeddings", "POST", body,
                                     {"Content-Type": "application/json",
                                      "Authorization": f"Bearer {self.keys.first()}"},
                                     connect_s=self.cfg["embed_timeout_s"], idle_s=self.cfg["embed_timeout_s"])
            try:
                raw = await asyncio.wait_for(up.body(), self.cfg["embed_timeout_s"])
            finally:
                up.close()
            vec = json.loads(raw)["data"][0]["embedding"]
            return [float(x) for x in vec] if up.status == 200 else None
        except (UpstreamError, asyncio.TimeoutError, ValueError, KeyError, IndexError, TypeError):
            self.counters["embed_failed"] += 1
            return None

    async def verify_ok(self, answer: str) -> bool | None:
        """True when the verifier finds no error and no warning, False otherwise, None when it cannot be reached."""
        try:
            up = await open_upstream(self.cfg["verify_url"].rstrip("/") + "/mesh/verify", "POST",
                                     json.dumps({"answer": answer}).encode(),
                                     {"Content-Type": "application/json",
                                      "Authorization": f"Bearer {self.keys.first()}"}, idle_s=30)
            raw = await asyncio.wait_for(up.body(), 30)
            up.close()
            if up.status != 200:
                return None
            report = json.loads(raw)                     # warnings (deprecated API ...) also keep it out
            return bool(report.get("ok")) and not report.get("needs_fix")
        except (UpstreamError, asyncio.TimeoutError, ValueError, AttributeError):
            return None

    async def cache_semantic(self, question: str, context: str) -> tuple[dict | None, float | None, float]:
        """(row or None, best similarity, ms): embed the question through the brain, compare with the entries."""
        t0 = time.monotonic()
        emb = await self.embed(question)
        row, sim = self.cache.nearest(emb, context, question) if emb is not None else (None, None)
        if row is not None and sim < self.cfg["cache_threshold"]:
            row = None
        return row, sim, round((time.monotonic() - t0) * 1000, 1)

    def cache_check(self, req: dict, headers: dict) -> tuple[dict, str | None, str]:
        """X-Mesh-Cache headers for a live answer, plus (question, context) when the cache may answer it."""
        if req.get("mesh_cache") is False or headers.get("x-mesh-cache", "").lower() in ("off", "0", "no"):
            return {"X-Mesh-Cache": "off"}, None, ""
        question, why = instant.cache_question(req)
        if question is None:
            self.counters["cache_skip"] += 1
            return {"X-Mesh-Cache": "skip"}, None, ""
        return {"X-Mesh-Cache": "miss"}, question, instant.clean_context(
            headers.get("x-mesh-context") or req.get("mesh_context"))

    async def serve_cached(self, row: dict, how: str, sim, lookup_ms: float, stream: bool, writer, t0: float):
        self.counters["cache_hit"] += 1
        self.cache.hit(row["id"])
        if time.time() - row["verified_at"] > self.cfg["cache_reverify_s"]:
            asyncio.get_running_loop().create_task(self._reverify(row["id"], row["answer"]))
        hdr = {"X-Mesh-Backend": "cache", "X-Mesh-Cache": "hit", "X-Mesh-Cache-Match": how,
               "X-Mesh-Cache-Id": str(row["id"]), "X-Mesh-Cache-Ms": str(lookup_ms)}
        if stream:
            await send_raw(writer, 200, "text/event-stream", instant.sse_from_text(row["answer"], FAST), hdr)
        else:
            await send_json(writer, 200, instant.completion_from_text(row["answer"], FAST), hdr)
        self.decisions.append({"ts": round(time.time(), 3), "model": FAST, "stream": stream, "cache": how,
                               "similarity": round(sim, 4) if sim is not None else None, "lookup_ms": lookup_ms,
                               "chosen": "cache", "entry": row["id"], "outcome": "ok",
                               "total_ms": round((time.monotonic() - t0) * 1000, 1)})

    async def _reverify(self, rid: int, answer: str):
        ok = await self.verify_ok(answer)
        if ok is True:
            self.cache.reverified(rid)
        elif ok is False:
            self.cache.delete(rid)
            self.counters["cache_dropped_on_reverify"] += 1

    async def cache_api(self, method: str, headers: dict, body: bytes) -> tuple[int, dict]:
        """GET: list (client key). POST add / DELETE ?id=N: mesh token only (the night jobs, never the launcher)."""
        if self.cache is None:
            return 404, err("answer cache is off (cache_db not set)")
        if method == "GET":
            self.cache.purge_expired()
            return 200, {"stats": self.cache.stats(), "entries": self.cache.listing()}
        auth = headers.get("authorization", "")
        token, mesh_token = auth[7:].strip() if auth.lower().startswith("bearer ") else "", self.mesh_token.first()
        if not token or not mesh_token or not hmac.compare_digest(token.encode(), mesh_token.encode()):
            return 401, err("cache changes need the mesh token")
        if method == "DELETE":
            ids = urllib.parse.parse_qs(headers.get(":query") or "").get("id", [""])
            return (200, {"ok": True}) if ids[0].isdigit() and self.cache.delete(int(ids[0])) else (404, err("no such id"))
        if method != "POST":
            return 405, err("GET, POST or DELETE")
        try:
            e = json.loads(body or b"{}")
            question, answer = str(e["question"]), str(e["answer"])
            score, max_score = float(e["score"]), float(e.get("max_score") or 3)
        except (ValueError, KeyError, TypeError):
            return 400, err("need question, answer, score (+ max_score, context, source)")
        if max_score <= 0 or score / max_score < self.cfg["cache_min_score_ratio"]:
            return 422, err("score too low for the cache")
        q, why = instant.cache_question({"messages": [{"role": "user", "content": question}]})
        if q is None:
            return 422, err(f"not cacheable: {why}")
        ok = await self.verify_ok(answer)
        if ok is None:
            return 503, err("verifier unreachable; nothing cached unverified")
        if not ok:
            return 422, err("the verifier found problems in this answer")
        emb = await self.embed(q)
        if emb is None:
            return 503, err("embedding failed")
        rid = self.cache.put(q, answer, instant.clean_context(e.get("context")), str(e.get("source") or "")[:120],
                             score / max_score, emb, self.cfg["cache_ttl_days"] * 86400)
        return 200, {"ok": True, "id": rid}

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


async def _chain(first, rest):
    for ev in first:
        yield ev
    async for ev in rest:
        yield ev


def _split_prefix(partial: str, longest: int = 64) -> tuple[str, str]:
    """(prefix to continue from, tail already sent). The prefix ends before the last whitespace, so the next model
    writes the cut word whole (models continue a half word badly: "Ve" + "inus")."""
    stripped = partial.rstrip()
    if stripped != partial:
        return stripped, partial[len(stripped):]
    i = max(partial.rfind(" "), partial.rfind("\n"), partial.rfind("\t"))
    if i < 0 or len(partial) - i > longest:
        return (partial, "") if len(partial) > longest else ("", partial)
    return partial[:i], partial[i:]


def _strip_tail(text: str, tail: str) -> tuple[str, str]:
    """Drop from `text` what matches the start of `tail` (already sent). Returns (text left, tail left)."""
    n = 0
    while n < len(text) and n < len(tail) and text[n] == tail[n]:
        n += 1
    if n == len(text) and n < len(tail):
        return "", tail[n:]
    return text[n:], ""


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
