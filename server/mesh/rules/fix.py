"""ONE targeted fix pass for the rule hits of an answer: the model rewrites the whole answer with the rules' exact fix
instructions (+ the official docs entries for the APIs involved, when the docs service answers in time). The rewrite
is kept only when it is better: fewer rule errors, no new rule errors, the verifier not worse, not cut, not much
longer. Otherwise the original stays (never show a worse answer).

    text, info = await run(question, text, call_model, verify=None, docs=None, budget_s=20)
        call_model(body) -> reply text (awaitable);  verify(text) -> /mesh/verify report or None (awaitable)
        docs(names) -> official docs text or "" (awaitable)
    info: {"hits": [...rule ids], "result": "kept original (...)" | "fixed", "notes": [kid-friendly lines], ...}
"""
from __future__ import annotations

import asyncio
import re
import time

from . import rules

FIX_SYSTEM = (
    "You fix an answer that Litha, a friendly game-building helper for kids, wrote. A checker that knows Roblox "
    "found real problems in it. Rewrite the WHOLE answer so every listed problem is fixed. Keep the same friendly tone "
    "and format: one or two plain sentences, then the code (each block labelled with the script type and exactly where "
    "it goes), then one tip. Keep everything that was already right and keep it about as short; never remove "
    "existing safety code (pcall, BindToClose, debounces, server checks). A server Script never uses "
    "Players.LocalPlayer: it gets the player from the event (Triggered, Touched, OnServerEvent, PlayerAdded). Use "
    "only real, current Roblox APIs (task.wait, game:GetService, :Connect). Do not mention the checker, the problems "
    "or that this is a fixed version. Reply with the answer only.")
OPENER = re.compile(r"^\s*(here('s| is)|sure|of course|okay|great catch|good catch|that('s| is) a (great|fantastic|good) "
                    r"catch|i('ve| have) (fixed|updated|corrected|rewritten))[^\n]*(fix|correct|updat|rewr|revis|"
                    r"version|catch)[^\n]*\n+", re.I)
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})", re.M)


def _prose_words(text: str) -> int:
    return len(re.sub(r"```.*?```", " ", text, flags=re.S).split())


def fix_messages(question: str, text: str, hits: list[dict], docs_text: str = "") -> list[dict]:
    lines = []
    for i, h in enumerate(hits, 1):
        ev = f" (seen here: {h['evidence']})" if h.get("evidence") else ""
        lines.append(f"{i}. {h['message']}{ev}")
    ref = f"\n\nOfficial Roblox docs for the APIs involved:\n{docs_text.strip()}" if docs_text.strip() else ""
    return [{"role": "system", "content": FIX_SYSTEM},
            {"role": "user", "content": f"Question:\n{question.strip()}\n\nAnswer to fix:\n{text.strip()}\n\n"
                                        f"Problems found:\n" + "\n".join(lines) + ref}]


def _bad(report: dict | None) -> tuple[int, int] | None:
    if report is None:
        return None
    probs = [p for b in report.get("blocks") or [] for p in b.get("problems") or []] + list(report.get("problems") or [])
    return (sum(p.get("severity") == "error" for p in probs), sum(p.get("severity") == "warning" for p in probs))


def clean_reply(reply: str) -> str:
    out = OPENER.sub("", (reply or "").strip(), count=1).strip()
    if out.startswith("Answer:"):
        out = out[len("Answer:"):].strip()
    return out


def judge_fix(old: str, new: str, old_hits: list[dict], new_hits: list[dict], old_rep: dict | None,
              new_rep: dict | None, finish: str | None = "stop") -> tuple[bool, str]:
    """(keep the rewrite?, why). Strict: anything doubtful keeps the original."""
    if not new.strip():
        return False, "empty rewrite"
    if finish not in (None, "stop") or len(FENCE.findall(new)) % 2 == 1:
        return False, "rewrite cut off"
    if "```" in old and "```" not in new:
        return False, "rewrite dropped the code"
    oe, ne = {h["rule"] for h in rules.errors(old_hits)}, {h["rule"] for h in rules.errors(new_hits)}
    if ne - oe:
        return False, "rewrite adds rule problems: " + ", ".join(sorted(ne - oe))
    if len(ne) >= len(oe):
        return False, "rule problems not reduced"
    ob, nb = _bad(old_rep), _bad(new_rep)
    if ob is not None and nb is not None and (nb[0] > ob[0] or nb[1] > ob[1]):
        return False, f"verifier worse {ob} -> {nb}"
    if ob is not None and nb is None:
        return False, "rewrite not verified"
    ow, nw = _prose_words(old), _prose_words(new)
    if nw > max(1.6 * ow, ow + 120) or nw > 380:
        return False, f"rewrite too long ({ow} -> {nw} words)"
    return True, f"rule errors {len(oe)} -> {len(ne)}"


async def run(question: str, text: str, call_model, verify=None, docs=None, budget_s: float = 20.0,
              max_tokens: int = 1000, hits: list[dict] | None = None, old_report: dict | None = None) -> tuple[str, dict]:
    t0 = time.monotonic()
    hits = rules.check(text, question) if hits is None else hits
    errs = rules.errors(hits)
    info: dict = {"hits": [h["rule"] for h in hits], "check_ms": round((time.monotonic() - t0) * 1000, 2)}
    if not errs:
        info["result"] = "no rule errors"
        return text, info
    todo = errs + [h for h in hits if h["severity"] == "warning"]
    docs_text = ""
    if docs is not None:
        names = list(dict.fromkeys(n for h in todo for n in h.get("docs") or []))[:6]
        if names:
            try:
                docs_text = (await asyncio.wait_for(docs(names), 0.5)) or ""
            except Exception:
                docs_text = ""
        info["docs_chars"] = len(docs_text[:2500])
    body = {"messages": fix_messages(question, text, todo, docs_text[:2500]), "max_tokens": max_tokens,
            "temperature": 0.2, "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
    t1 = time.monotonic()
    try:
        left = budget_s - (t1 - t0)
        reply = await asyncio.wait_for(call_model(body), max(0.5, left))
    except asyncio.TimeoutError:
        info["result"] = "kept original (fix timed out)"
        return text, info
    except Exception as e:
        info["result"] = f"kept original (model error {type(e).__name__})"
        return text, info
    finally:
        info["model_ms"] = round((time.monotonic() - t1) * 1000)
    finish = "stop"
    if isinstance(reply, dict):              # call_model may return {"text", "finish"}
        reply, finish = reply.get("text") or "", reply.get("finish")
    new = clean_reply(reply)
    new_hits = rules.check(new, question)
    old_rep = old_report
    new_rep = None
    if verify is not None:
        old_rep, new_rep = await asyncio.gather(verify(text) if old_rep is None else _same(old_rep), verify(new))
    keep, why = judge_fix(text, new, hits, new_hits, old_rep, new_rep, finish)
    info["after"] = [h["rule"] for h in new_hits]
    info["why"] = why
    info["total_ms"] = round((time.monotonic() - t0) * 1000)
    if not keep:
        info["result"] = f"kept original ({why})"
        return text, info
    info["result"] = "fixed"
    fixed_ids = {h["rule"] for h in errs} - {h["rule"] for h in rules.errors(new_hits)}
    info["notes"] = [h["note"] for h in errs if h["rule"] in fixed_ids and h.get("note")][:3]
    return new, info


async def _same(x):
    return x
