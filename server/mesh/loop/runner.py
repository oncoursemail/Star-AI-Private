"""Router side of the loop: a second candidate on the node's second slot while the first one streams, a verified pick
when the first one ends (verifier + regex checks, then a one-token judge per answer), and the hidden Roblox tool
loop, all before the stream's [DONE]. Measured in docs/agents/litha-loop-20261028.md.

Opt-in per request (`"mesh_loop": true` or header `X-Mesh-Loop: 1`), model `litha`, streaming only. The client sees
candidate A stream as usual. When A finishes, the router verifies it; if A has a problem and B (same question, a
"careful" framing, started at the same moment on the node's second slot) is better on the cheap signals, or the tool
loop repaired A's code, ONE extra SSE event goes out before [DONE]:

    data: {"object": "mesh.replace", "mesh_replace": {"content": "<whole final answer>", "source": "B|patch|B+patch",
           "why": "...", "verify": {"errors": n, "warnings": n}}}

It has no "choices", so clients that do not know it keep A unchanged. B is never started when the node has only one
slot (config `loop_best_of_nodes` lists the nodes that run 2 parallel streams).
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from . import checks, judge, patch

LOOP_DEFAULTS = {
    "loop_best_of_nodes": [],        # node names with 2 llama-server slots (-np 2); empty = no second candidate
    "loop_wait_b_s": 4.0,            # after A ends with a problem, wait at most this long for B to finish
    "loop_tool_budget_s": 1.5,       # hidden Roblox tool loop budget (model part) after A ends
    "loop_judge_margin": 0.5,        # on a cheap-signal tie B replaces A only when P(bad A) - P(bad B) > this
    "loop_b_temperature": 0.6,
    "loop_b_max_tokens": 600,
}
CAREFUL = ("\n\nBefore you answer, check silently (do not list these checks):\n"
           "- Say which script type (Script, LocalScript, ModuleScript) and exactly where it goes; LocalScripts do "
           "not run in Workspace or ServerScriptService.\n"
           "- The server checks everything a client sends (never trust an amount, price or target from the client).\n"
           "- Touched fires many times: add a per-player debounce when it should act once.\n"
           "- Every API name is real and current; every prose claim about Studio settings or defaults is true, "
           "otherwise leave it out.\n"
           "- Unity: say if code uses the old Input Manager (Unity 6 defaults to the Input System). Minecraft: Java "
           "1.21 syntax.")
ROBLOX = re.compile(r"\broblox\b|\bluau?\b|\bstudio\b|\bscript\b|\bpart\b|\bplayer\b|leaderstats|remote", re.I)


def wanted(req: dict, headers: dict) -> bool:
    flag = req.pop("mesh_loop", None)
    if flag is None:
        flag = headers.get("x-mesh-loop", "").strip().lower() in ("1", "true", "yes")
    return bool(flag) and bool(req.get("stream"))


def careful_messages(messages: list) -> list:
    msgs = [dict(m) if isinstance(m, dict) else m for m in messages]
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "system" and isinstance(m.get("content"), str):
            m["content"] = m["content"] + CAREFUL
            return msgs
    return [{"role": "system", "content": CAREFUL.strip()}] + msgs


def last_user(req: dict) -> str:
    for m in reversed(req.get("messages") or []):
        if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


class Run:
    """One opted-in request. `start()` before the race, `before_done(text)` from relay_stream, `close()` always."""

    def __init__(self, router, req: dict, path: str, plan: list, auth: str, log: dict):
        self.router, self.cfg, self.req, self.path, self.auth = router, router.cfg, req, path, auth
        self.log = log.setdefault("loop", {})
        self.b_task: asyncio.Task | None = None
        self.b_backend = None
        self.t0 = time.monotonic()
        if path == "/chat/completions":
            for backend, url, mid in plan:
                if getattr(backend, "name", None) in self.cfg["loop_best_of_nodes"]:
                    self.b_backend, self.b_url, self.b_model = backend, url, mid
                    break

    # ---- candidate B ---------------------------------------------------------------------------------------------
    def start(self):
        if self.b_backend is None:
            self.log["b"] = "off (no 2-slot node usable)"
            return
        body = {k: v for k, v in self.req.items() if k not in ("stream", "stream_options")}
        body.update(model=self.b_model, stream=False, messages=careful_messages(self.req.get("messages") or []),
                    temperature=self.cfg["loop_b_temperature"],
                    max_tokens=min(int(body.get("max_tokens") or 600), self.cfg["loop_b_max_tokens"]))
        self.b_task = asyncio.ensure_future(self._b(body))
        self.log["b"] = f"started on {self.b_backend.name}"

    async def _b(self, body: dict) -> dict:
        """Candidate B, then its judge score at once (B's slot is free by then)."""
        out = await self._call(self.b_backend, self.b_url, body, 300)
        out["p_bad"] = await self._p_bad(out["text"]) if out["text"].strip() else None
        return out

    async def _p_bad(self, text: str) -> float | None:
        backend, url, mid = self._fast_backend()
        try:
            out = await self._call(backend, url, {**judge.request(last_user(self.req), text), "model": mid}, 20)
        except Exception:
            return None
        return judge.p_bad(out["raw"])

    async def _call(self, backend, url, body: dict, timeout: float) -> dict:
        from ..router import open_upstream, UpstreamError
        backend.inflight += 1
        up = None
        try:
            up = await open_upstream(url + "/chat/completions", "POST", json.dumps(body).encode(),
                                     self.router._headers_for(backend, self.auth), idle_s=timeout)
            raw = await asyncio.wait_for(up.body(), timeout)
            if up.status != 200:
                raise UpstreamError(f"HTTP {up.status}")
            data = json.loads(raw)
            ch = (data.get("choices") or [{}])[0]
            return {"text": (ch.get("message") or {}).get("content") or "", "finish": ch.get("finish_reason"),
                    "ms": round((time.monotonic() - self.t0) * 1000), "raw": data}
        finally:
            backend.inflight -= 1
            if up is not None:
                up.close()

    async def _model(self, body: dict) -> str:
        backend, url, mid = self._fast_backend()
        out = await self._call(backend, url, {**body, "model": mid}, 30)
        return out["text"]

    def _fast_backend(self):
        if self.b_backend is not None:
            return self.b_backend, self.b_url, self.b_model
        plan, _ = self.router.plan("litha")
        return plan[0]

    async def _verify(self, text: str) -> dict | None:
        from ..router import open_upstream, UpstreamError
        try:
            up = await open_upstream(self.cfg["verify_url"].rstrip("/") + "/mesh/verify", "POST",
                                     json.dumps({"answer": text}).encode(),
                                     {"Content-Type": "application/json",
                                      "Authorization": f"Bearer {self.router.keys.first()}"}, idle_s=5)
            raw = await asyncio.wait_for(up.body(), 5)
            up.close()
            return json.loads(raw) if up.status == 200 else None
        except (UpstreamError, asyncio.TimeoutError, ValueError):
            return None

    # ---- the end of A --------------------------------------------------------------------------------------------
    async def before_done(self, text_a: str) -> bytes:
        try:
            return await self._decide(text_a)
        except Exception as e:                         # never break the answer that already streamed
            self.log["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            return b""
        finally:
            self.close()

    async def _decide(self, text_a: str) -> bytes:
        t_end = time.monotonic()
        if "```" not in text_a:
            self.log["result"] = "no code: A kept"
            return b""
        if self.b_task is None:
            rep_a, pa = await self._verify(text_a), None
        else:
            rep_a, pa = await asyncio.gather(self._verify(text_a), self._p_bad(text_a))
        sa = checks.signals(text_a, rep_a)
        margin = self.cfg["loop_judge_margin"]
        self.log["a"], self.log["a_p_bad"] = checks.badness(sa), pa
        final, rep, source, why = text_a, rep_a, "", ""
        if self.b_task is not None and checks.clean(sa) and pa is not None and pa <= margin:
            why = "A clean and judged ok"
        elif self.b_task is not None:
            try:
                b = await asyncio.wait_for(asyncio.shield(self.b_task), self.cfg["loop_wait_b_s"])
            except (asyncio.TimeoutError, Exception) as e:
                b = None
                self.log["b_result"] = f"not used ({type(e).__name__})"
            if b is not None and b["text"].strip():
                rep_b = await self._verify(b["text"])
                sb = checks.signals(b["text"], rep_b, b["finish"])
                self.log["b_badness"], self.log["b_p_bad"] = checks.badness(sb), b.get("p_bad")
                choice, why = checks.pick(sa, sb)
                if choice is None and pa is not None and b.get("p_bad") is not None:
                    choice = "B" if pa - b["p_bad"] > margin else "A"
                    why = f"judge P(bad) A {pa:.2f} vs B {b['p_bad']:.2f}"
                if choice == "B":
                    final, rep, source = b["text"], rep_b, "B"
        if rep is not None and ROBLOX.search(last_user(self.req) + final):
            fixed, info = await patch.run(final, rep, self._verify, self._model, self.cfg["loop_tool_budget_s"])
            self.log["tool"] = info
            if fixed != final:
                final, source = fixed, (source + "+patch" if source else "patch")
                rep = await self._verify(final)
        self.log["extra_ms"] = round((time.monotonic() - t_end) * 1000)
        if final == text_a:
            self.log["result"] = "A kept" + (f" ({why})" if why else "")
            return b""
        summ = checks.signals(final, rep)
        self.log["result"] = f"replaced: {source}" + (f" ({why})" if why else "")
        event = {"object": "mesh.replace", "mesh_replace": {
            "content": final, "source": source, "why": why,
            "verify": {"errors": summ["errors"], "warnings": summ["warnings"]}}}
        return b"data: " + json.dumps(event).encode() + b"\n\n"

    def close(self):
        if self.b_task is not None and not self.b_task.done():
            self.b_task.cancel()
