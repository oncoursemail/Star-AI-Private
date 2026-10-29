"""Hidden help for general (non-coding) questions, added to the last user turn so the system prompt stays the cached
prefix (same place as the docs block and the verified-answer grounding):

- every general question: a short general-mode note (Litha's game-building system prompt made the fast path refuse
  38% of general questions as "outside my expertise");
- maths word problems: the node writes a tiny calculation program, calc.py evaluates it exactly, the steps and the
  final number go into the turn (the answer explains them);
- safety-sensitive questions: official safety facts (helplines, poison control, never share passwords);
- factual questions (optional, `general_notes`): encyclopedia passages from the knowledge service.

    hdr = await run(router, req, plan, auth)      # {"X-Mesh-General": "math calc 18 812ms"} or {}
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from . import calc, classify

DEFAULTS = {
    "general": True,                  # the whole feature (litha requests only)
    "general_note": True,
    "general_calc": True,
    "general_calc_timeout_s": 6.0,
    "general_safety_card": True,
    "general_notes": False,           # encyclopedia notes for factual questions (knowledge service)
    "knowledge_url": "",              # e.g. http://<brain>:8091 ; "" = off
    "knowledge_timeout_s": 1.5,
}

GENERAL_NOTE = ("(Note for Litha, not from the kid: this is a general question, not a game-building one. Litha also "
                "helps with school subjects, science, history, maths, everyday how-to, writing and feelings. Answer it "
                "fully and accurately like a kind tutor in about 120-180 words, with the key facts; never say it is "
                "outside your expertise. Keep the kid safe: no dangerous instructions, no personal data.)")
SAFETY_CARD = ("(Safety facts Litha can use, from official sources: in danger right now -> call 911 (US), 999 (UK) or 112 "
               "(Europe). Thinking about not wanting to live -> call or text 988 (US Suicide & Crisis Lifeline, free, "
               "24/7) or Childline 0800 1111 (UK), and tell a trusted adult now. Swallowed something or found pills -> "
               "do not take them, tell an adult, call Poison Control 1-800-222-1222 (US) or emergency services. Never "
               "share passwords, your address or photos; anyone offering free Robux for a login is a scam. Bullying or "
               "a stranger asking for personal things -> do not reply, save proof, block and report, tell a trusted "
               "adult. Dangerous dares -> it is okay to say no.)")
CALC_SYS = ("You solve math word problems by writing a tiny calculation program. Reply with ONLY one ```calc code block: "
            "one step per line, written as `name = expression` using numbers, + - * / ( ) and names defined on earlier "
            "lines (no units, no words, no functions). The last line must be `answer = ...`.")
GENERAL_SOURCES = {"simplewiki", "wikipedia-topics", "openstax-statistics", "openstax-business", "openstax-prealgebra",
                   "openstax-calculus", "openstax-physics"}


def last_user_text(req: dict) -> str | None:
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "user" \
            or not isinstance(msgs[-1].get("content"), str):
        return None
    if any(req.get(k) for k in ("tools", "functions", "response_format", "grammar", "json_schema")):
        return None
    return msgs[-1]["content"]


def calc_note(program_reply: str) -> tuple[str | None, str]:
    """(note for the user turn or None, the exact value or why it failed)."""
    m = re.search(r"```(?:calc|python)?\s*\n(.*?)```", program_reply or "", re.S)
    try:
        value, steps = calc.run(m.group(1) if m else (program_reply or ""))
    except calc.CalcError as e:
        return None, f"calc failed: {e}"
    lines = "\n".join(f"{n} = {e} = {calc.fmt(v)}" for n, e, v in steps)
    return (f"(Exact calculation from a calculator, already checked:\n{lines}\nFinal answer: {calc.fmt(value)})\n"
            "Explain the steps briefly and clearly for a kid and give the final answer. Do not mention the "
            "calculator."), calc.fmt(value)


def notes_block(passages: list[dict]) -> str:
    out = []
    for i, p in enumerate(passages, 1):
        body = re.sub(r"\s+", " ", p.get("text") or "")[:700]
        out.append(f"[{i}] {p.get('title')} ({p.get('source')}): {body}")
    return ("Reference notes (encyclopedia passages found for this question; they may be incomplete or off-topic):\n"
            + "\n".join(out) + "\n\nUse the notes only where they answer the question. Do not invent facts; if you are "
            "not sure of a fact, leave it out. Do not mention the notes.\n---\nQuestion: ")


async def run(router, req: dict, plan: list, auth: str) -> dict:
    cfg = router.cfg
    if not cfg.get("general", True):
        return {}
    text = last_user_text(req)
    if not text or "(Note for Litha" in text:
        return {}
    kind = classify.kind(text)
    if kind in ("code", "chat"):
        return {}
    t0 = time.monotonic()
    add, info = [], [kind]
    head = ""
    if kind == "math" and cfg.get("general_calc", True) and plan:
        reply = await _model(router, plan, auth, {"messages": [{"role": "system", "content": CALC_SYS},
                                                               {"role": "user", "content": text}],
                                                  "max_tokens": 400, "temperature": 0.1, "stream": False,
                                                  "chat_template_kwargs": {"enable_thinking": False}},
                             cfg.get("general_calc_timeout_s", 6.0))
        note, why = calc_note(reply) if reply is not None else (None, "calc late")
        info.append(f"calc {why}")
        router.counters["general_calc" if note else "general_calc_failed"] += 1
        if note:
            add.append(note)
    elif kind != "math" and cfg.get("general_note", True):
        add.append(GENERAL_NOTE)
        if kind == "safety" and cfg.get("general_safety_card", True):
            add.append(SAFETY_CARD)
            info.append("safety")
        if kind == "factual" and cfg.get("general_notes") and cfg.get("knowledge_url"):
            ps = await _search(router, text, cfg["knowledge_url"], cfg.get("knowledge_timeout_s", 1.5))
            if ps:
                head = notes_block(ps)
                info.append(f"notes {len(ps)}")
    if not add and not head:
        return {"X-Mesh-General": " ".join(info)}
    msgs = req["messages"]
    msgs[-1] = {**msgs[-1], "content": head + text + "\n\n" + "\n".join(add)}
    router.counters["general_used"] += 1
    return {"X-Mesh-General": " ".join(info) + f" {round((time.monotonic() - t0) * 1000)}ms"}


async def _model(router, plan: list, auth: str, body: dict, timeout: float) -> str | None:
    """One short non-stream call on the backend that will answer (a node first), bounded by `timeout`."""
    from ..router import open_upstream, UpstreamError
    backend, url, mid = plan[0]
    backend.inflight += 1
    up = None
    try:
        up = await open_upstream(url + "/chat/completions", "POST", json.dumps({**body, "model": mid}).encode(),
                                 router._headers_for(backend, auth), connect_s=timeout, idle_s=timeout)
        raw = await asyncio.wait_for(up.body(), timeout)
        if up.status != 200:
            return None
        ch = (json.loads(raw).get("choices") or [{}])[0]
        return (ch.get("message") or {}).get("content") or ""
    except (UpstreamError, asyncio.TimeoutError, ValueError, OSError):
        return None
    finally:
        backend.inflight -= 1
        if up is not None:
            up.close()


async def _search(router, text: str, base: str, timeout: float) -> list[dict]:
    from ..router import open_upstream, UpstreamError
    try:
        up = await open_upstream(base.rstrip("/") + "/search", "POST",
                                 json.dumps({"query": text[:400], "mode": "vector", "top": 10, "scope": "all"}).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {router.keys.first()}"},
                                 connect_s=timeout, idle_s=timeout)
        try:
            raw = await asyncio.wait_for(up.body(), timeout)
        finally:
            up.close()
        data = json.loads(raw) if up.status == 200 else {}
    except (UpstreamError, asyncio.TimeoutError, ValueError, OSError):
        router.counters["general_notes_failed"] += 1
        return []
    return [p for p in data.get("passages") or [] if p.get("source") in GENERAL_SOURCES][:3]
