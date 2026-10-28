"""Parallel sections ("skeleton, then expand") for multi-part Litha answers.

A question that asks for several pieces (for example a server Script and a LocalScript) is answered in two steps:
1. a short plan: the model lists 2-3 part titles (~1 s, temperature 0, nothing streamed);
2. every part is written at the same time on its own llama-server slot (`-np 2` on the node), and the parts are
   streamed to the client in order: part 1 live, later parts from their buffers as soon as part 1 ends.
Wall-clock for a 2-part answer is about plan + the longest part instead of the sum of the parts. The plan step adds
~1 s before the first word, so it only pays off for long answers; a plan of ONE (or anything unusable) falls back to
the normal single stream.

Transport-agnostic: the caller passes `complete(body) -> str` (one non-streamed answer) and
`stream(body) -> async iterator of text pieces`. Stdlib only.
"""
from __future__ import annotations

import asyncio
import re

# questions that ask for more than one piece of work
_MULTI = re.compile(
    r"(local ?script.*\b(server )?script\b|\bserver\b.*\bclient\b|\bclient\b.*\bserver\b|\bscript\b.*\bgui\b|"
    r"\bgui\b.*\bscript\b|\band (then |also )?(make|add|show|save|explain|give|let|have)\b|\bboth\b|\bsteps?\b|"
    r"\bshop\b|\bsystem\b|\bleaderboard\b|\bdata ?store\b.*\b(save|load)\b|\bsave\b.*\bload\b)", re.I | re.S)
_CODE = re.compile(r"```|^\s*(local|function|end|public|void|class)\b", re.M)
_ONE = re.compile(r"^\W*one\W*$", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|part \d+:?)\s*", re.I)

PLAN_NOTE = ("\n\n[Planning step, not shown to the user] Plan your reply as 2 or 3 parts that separate writers can "
             "write at the same time (for example: the short answer with the server Script, the LocalScript, the "
             "next step). Reply with only the part titles, one per line, at most 8 words each, no numbers. If the "
             "reply needs only one short piece, reply with the single word ONE.")


def question(req: dict) -> str | None:
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict):
        return None
    last = msgs[-1]
    if last.get("role") != "user" or not isinstance(last.get("content"), str):
        return None
    return last["content"]


def eligible(req: dict, min_chars: int = 30, max_chars: int = 600) -> bool:
    """A streamed chat request whose last user turn asks for several pieces and contains no code of its own."""
    q = question(req)
    if q is None or not req.get("stream") or req.get("tools") or req.get("n", 1) != 1:
        return False
    if not (min_chars <= len(q) <= max_chars) or _CODE.search(q):
        return False
    return bool(_MULTI.search(q))


def _with_user(req: dict, text: str, **over) -> dict:
    msgs = list(req["messages"])
    msgs[-1] = {**msgs[-1], "content": text}
    body = {k: v for k, v in req.items() if k not in ("stream_options",)}
    body.update(messages=msgs, **over)
    return body


def plan_body(req: dict) -> dict:
    return _with_user(req, question(req) + PLAN_NOTE, stream=False, max_tokens=60, temperature=0.0)


def parse_plan(text: str, max_parts: int = 3) -> list[str]:
    """Part titles, or [] when the model said ONE or the plan is unusable (then answer as one stream)."""
    lines = [_BULLET.sub("", ln).strip().strip("*#").strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln and len(ln) <= 80]
    if not lines or any(_ONE.match(ln) for ln in lines[:1]) or len(lines) < 2:
        return []
    return lines[:max_parts]


def part_body(req: dict, parts: list[str], i: int, max_tokens: int | None = None) -> dict:
    n = len(parts)
    plan = " ".join(f"{k + 1}. {p}" for k, p in enumerate(parts))
    note = (f"\n\n[Your reply is written in {n} parts by separate writers and joined in order. Plan: {plan}. "
            f"Write ONLY part {i + 1} ({parts[i]}). Do not write its title as a heading. ")
    if i == 0:
        note += "Start with the one or two sentence answer. "
    else:
        note += ("Do not greet, do not restate the answer and do not repeat earlier parts; start directly with this "
                 "part (one short lead-in sentence at most). ")
    note += "End with one next step or one common mistake to avoid.]" if i == n - 1 else \
        "Do not add a closing, a next step or \"Want the full version?\".]"
    over = {"stream": True}
    if max_tokens:
        over["max_tokens"] = max_tokens
    return _with_user(req, question(req) + note, **over)


async def ordered(streams, sep: str = "\n\n"):
    """Run every async iterator at once; yield their pieces in order (later ones buffered until earlier ones end)."""
    queues = [asyncio.Queue() for _ in streams]
    END = object()

    async def pump(it, q):
        try:
            async for piece in it:
                await q.put(piece)
            await q.put(END)
        except BaseException as e:            # noqa: BLE001 - handed to the consumer
            await q.put(e)

    tasks = [asyncio.ensure_future(pump(it, q)) for it, q in zip(streams, queues)]
    try:
        for k, q in enumerate(queues):
            first = True
            while (item := await q.get()) is not END:
                if isinstance(item, BaseException):
                    raise item
                if first and k > 0:
                    yield sep
                first = False
                yield item
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def answer(req: dict, complete, stream, max_parts: int = 3, stats: dict | None = None):
    """Yield the answer as text pieces: plan, then parallel parts in order; a plan of ONE streams the plain request.
    `stats` (optional) gets {"parts": [...], "plan_s": ...}."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    parts = parse_plan(await complete(plan_body(req)), max_parts)
    if stats is not None:
        stats.update(parts=parts, plan_s=round(loop.time() - t0, 3))
    if not parts:
        async for piece in stream({**req, "stream": True}):
            yield piece
        return
    total = req.get("max_tokens") or 600
    each = max(160, int(total * 0.75))
    async for piece in ordered([stream(part_body(req, parts, i, each)) for i in range(len(parts))]):
        yield piece
