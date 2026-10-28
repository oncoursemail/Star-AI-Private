"""Router hook for parallel sections (server/mesh/speed/sections.py).

`try_sections(router, ...)` is called by Router.complete() for a streamed `litha` request after the exact cache
check. It answers only when sections are switched on (`"sections": true`), the question qualifies
(sections.eligible) and the best backend is a node listed in `sections_nodes` (one that runs `-np 2`). Anything that
fails before the first word returns False and the normal single-stream path answers instead.
"""
from __future__ import annotations

import asyncio
import json
import time

from . import sections

DEFAULTS = {
    "sections": False,            # switch: answer multi-part questions as plan + parallel parts
    "sections_nodes": [],         # node names whose llama-server has 2+ slots (-np 2)
    "sections_max_parts": 2,      # = slots on the node; a 3rd part would wait for a free slot
}


def _chunk(rid: str, model: str, delta: dict, finish=None) -> bytes:
    obj = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


async def try_sections(router, path, headers, req, conv, writer, t0, question, context, cache_hdr) -> bool:
    from ..router import FAST, UpstreamError, open_upstream, _event_json   # noqa: PLC0415 (import cycle)
    from .. import instant                                                         # noqa: PLC0415
    cfg = router.cfg
    if not cfg.get("sections") or path != "/chat/completions" or not sections.eligible(req):
        return False
    plan, reason = router.plan(FAST, conv)
    node, url, mid = plan[0]
    if node is router.brain or node.name not in cfg.get("sections_nodes", []):
        return False
    if question and router.cache is not None:            # the semantic cache still wins (one embed, ~50 ms)
        row, sim, ms = await router.cache_semantic(question, context)
        if row is not None:
            await router.serve_cached(row, "semantic", sim, ms, True, writer, t0)
            return True
    hdr = router._headers_for(node, headers.get("authorization", ""))
    target = url + path

    async def complete(body):
        up = await open_upstream(target, "POST", json.dumps({**body, "model": mid}).encode(), hdr,
                                 idle_s=cfg["node_first_token_s"])
        try:
            if up.status != 200:
                raise UpstreamError(f"HTTP {up.status}")
            return json.loads(await up.body())["choices"][0]["message"]["content"] or ""
        finally:
            up.close()

    async def stream(body):
        up = await open_upstream(target, "POST", json.dumps({**body, "model": mid}).encode(), hdr,
                                 idle_s=cfg["read_idle_s"])
        node.inflight += 1
        try:
            if up.status != 200:
                raise UpstreamError(f"HTTP {up.status}")
            finished = False
            async for ev in up.events():
                obj = _event_json(ev)
                if obj == "DONE":
                    finished = True
                    break
                if isinstance(obj, dict):
                    if "error" in obj:
                        raise UpstreamError(f"error event: {str(obj['error'])[:160]}")
                    for c in obj.get("choices") or []:
                        text = (c.get("delta") or {}).get("content")
                        if text:
                            yield text
                        if c.get("finish_reason"):
                            finished = True
            if not finished:
                raise UpstreamError("part stream ended without a finish_reason")
        finally:
            node.inflight -= 1
            up.close()

    log = {"ts": round(time.time(), 3), "model": FAST, "stream": True, "sections": True, "reason": reason,
           "chosen": node.name, "errors": []}
    if conv:
        log["conv"] = conv[:12]
    router.decisions.append(log)
    stats: dict = {}
    agen = sections.answer({k: v for k, v in req.items() if k not in instant.MESH_FIELDS}, complete, stream,
                           cfg.get("sections_max_parts", 2), stats)
    rid = f"chatcmpl-sec-{int(t0 * 1000) % 10**9}"
    sent = 0
    try:
        try:
            first = await agen.__anext__()
        except (UpstreamError, OSError, asyncio.TimeoutError, StopAsyncIteration, ValueError, KeyError) as e:
            log.update(outcome=f"sections not started ({type(e).__name__}: {str(e)[:80]}); single stream")
            return False
        more = {"X-Mesh-Backend": node.name, "X-Mesh-Sections": str(len(stats.get("parts") or []) or 1), **cache_hdr}
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\n"
                     b"Connection: close\r\n" + "".join(f"{k}: {v}\r\n" for k, v in more.items()).encode("latin-1")
                     + b"\r\n")
        writer.write(_chunk(rid, FAST, {"role": "assistant", "content": ""}))
        log["ttft_ms"] = round((time.monotonic() - t0) * 1000)
        piece = first
        while True:
            writer.write(_chunk(rid, FAST, {"content": piece}))
            sent += len(piece)
            await writer.drain()
            try:
                piece = await agen.__anext__()
            except StopAsyncIteration:
                break
        writer.write(_chunk(rid, FAST, {}, "stop") + b"data: [DONE]\n\n")
        await writer.drain()
        router.affinity.set(conv, node.name)
        log["outcome"] = "ok"
    except (UpstreamError, OSError, asyncio.TimeoutError, ValueError, KeyError) as e:
        log["outcome"] = f"sections cut after {sent} chars: {str(e)[:120]}; error sent"
        msg = {"error": {"message": f"mesh: {node.name} stopped in the middle of the answer", "type": "server_error"}}
        try:
            writer.write(b"data: " + json.dumps(msg).encode() + b"\n\ndata: [DONE]\n\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass
    finally:
        await agen.aclose()
        log.update(parts=len(stats.get("parts") or []), plan_ms=round((stats.get("plan_s") or 0) * 1000),
                   total_ms=round((time.monotonic() - t0) * 1000))
        print("mesh", json.dumps(log), flush=True)
    return True
