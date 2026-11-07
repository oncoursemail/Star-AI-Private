"""ONE hidden fix pass for what the sandbox saw go wrong when it ran the answer (runtime errors, infinite yields,
failed property checks). The model rewrites the whole answer with the test results; the rewrite is kept only when the
sandbox finds strictly fewer problems, adds none, and the rules/verifier are not worse (else the original stays).

    text, info = await run(question, text, call_model, check, verify=None, budget_s=20)
        check(text, question) -> sandbox report (harness.run), called in a worker thread
"""
from __future__ import annotations

import asyncio
import re
import time

from ..rules import fix as rules_fix, rules

FIX_SYSTEM = (
    "You fix an answer that Litha, a friendly game-building helper for kids, wrote. Its code was run in a Roblox test "
    "and the test found real problems. Rewrite the WHOLE answer so every listed problem is fixed. Keep the same "
    "friendly tone and format: one or two plain sentences, then the code (each block labelled with the script type and "
    "exactly where it goes), then one tip. Keep everything that was already right and keep it about as short; never "
    "remove existing safety code (pcall, BindToClose, debounces, server checks). A server Script never uses "
    "Players.LocalPlayer. Use only real, current Roblox APIs. Do not mention the test, the problems or that this is a "
    "fixed version. Reply with the answer only.")


def _key(f: dict) -> str:
    msg = re.sub(r"\d+(\.\d+)?", "#", f.get("message") or "")
    return f"{f.get('kind')}:{f.get('phase') if f.get('kind') == 'property' else ''}:{msg[:90]}"


def _code_line(text: str, block: int | None, line: int | None) -> str:
    if not block or not line:
        return ""
    blocks = re.findall(r"^[ \t]{0,3}(?:`{3,}|~{3,})[^\n]*\n(.*?)^[ \t]{0,3}(?:`{3,}|~{3,})", text, re.M | re.S)
    if block - 1 >= len(blocks):
        return ""
    lines = blocks[block - 1].split("\n")
    return lines[line - 1].strip() if 0 < line <= len(lines) else ""


def problem_lines(text: str, findings: list[dict]) -> list[str]:
    out = []
    for f in findings:
        where = ""
        if f.get("block"):
            code = _code_line(text, f["block"], f.get("line"))
            where = f"code block {f['block']}" + (f", line {f['line']}" if f.get("line") else "") + \
                (f" (`{code[:100]}`)" if code else "")
        phase = {"join": "when a player joined", "touch": "when a player touched a part", "prompt":
                 "when a prompt or click detector was used", "gui": "when a GUI button was clicked", "input":
                 "when a key was pressed", "tool": "when a tool was used", "leave": "when the player left", "close":
                 "when the server shut down", "start": "when the script started"}.get(f.get("phase") or "", "")
        if f["kind"] == "property":
            out.append(f["message"])
        elif f["kind"] == "hang":
            out.append(f["message"])
        else:
            out.append(f"Error {phase} in {where}: {f['message']}".replace(" in :", ":").strip())
    return list(dict.fromkeys(out))


def fix_messages(question: str, text: str, findings: list[dict]) -> list[dict]:
    lines = "\n".join(f"{i}. {p}" for i, p in enumerate(problem_lines(text, findings), 1))
    return [{"role": "system", "content": FIX_SYSTEM},
            {"role": "user", "content": f"Question:\n{question.strip()}\n\nAnswer to fix:\n{text.strip()}\n\n"
                                        f"What went wrong in the test:\n{lines}"}]


def judge(old: str, new: str, old_rep: dict, new_rep: dict, question: str, finish: str | None,
          old_ver: dict | None = None, new_ver: dict | None = None) -> tuple[bool, str]:
    if not new.strip():
        return False, "empty rewrite"
    if finish not in (None, "stop") or len(rules_fix.FENCE.findall(new)) % 2 == 1:
        return False, "rewrite cut off"
    if "```" in old and "```" not in new:
        return False, "rewrite dropped the code"
    if not new_rep.get("ran"):
        return False, "rewrite did not run"
    ok, nk = {_key(f) for f in old_rep.get("findings") or []}, {_key(f) for f in new_rep.get("findings") or []}
    if nk - ok:
        return False, "rewrite adds test problems: " + "; ".join(sorted(nk - ok))[:200]
    if len(nk) >= len(ok):
        return False, "test problems not reduced"
    oe = {h["rule"] for h in rules.errors(rules.check(old, question))}
    ne = {h["rule"] for h in rules.errors(rules.check(new, question))}
    if ne - oe:
        return False, "rewrite adds rule problems: " + ", ".join(sorted(ne - oe))
    ob, nb = rules_fix._bad(old_ver), rules_fix._bad(new_ver)
    if ob is not None and nb is not None and (nb[0] > ob[0] or nb[1] > ob[1]):
        return False, f"verifier worse {ob} -> {nb}"
    ow, nw = rules_fix._prose_words(old), rules_fix._prose_words(new)
    if nw > max(1.6 * ow, ow + 120) or nw > 380:
        return False, f"rewrite too long ({ow} -> {nw} words)"
    return True, f"test problems {len(ok)} -> {len(nk)}"


async def run(question: str, text: str, call_model, check, verify=None, budget_s: float = 20.0,
              max_tokens: int = 1000, report: dict | None = None) -> tuple[str, dict]:
    t0 = time.monotonic()
    rep = report if report is not None else await asyncio.to_thread(check, text, question)
    info: dict = {"findings": len(rep.get("findings") or []), "check_ms": rep.get("ms")}
    if not rep.get("findings"):
        info["result"] = "no test problems"
        return text, info
    body = {"messages": fix_messages(question, text, rep["findings"]), "max_tokens": max_tokens, "temperature": 0.2,
            "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
    t1 = time.monotonic()
    try:
        reply = await asyncio.wait_for(call_model(body), max(0.5, budget_s - (t1 - t0)))
    except asyncio.TimeoutError:
        info["result"] = "kept original (fix timed out)"
        return text, info
    except Exception as e:
        info["result"] = f"kept original (model error {type(e).__name__})"
        return text, info
    finally:
        info["model_ms"] = round((time.monotonic() - t1) * 1000)
    finish = "stop"
    if isinstance(reply, dict):
        reply, finish = reply.get("text") or "", reply.get("finish")
    new = rules_fix.clean_reply(reply)
    new_rep = await asyncio.to_thread(check, new, question)
    old_ver = new_ver = None
    if verify is not None:
        old_ver, new_ver = await asyncio.gather(verify(text), verify(new))
    keep, why = judge(text, new, rep, new_rep, question, finish, old_ver, new_ver)
    info.update({"why": why, "after": len(new_rep.get("findings") or []), "total_ms": round((time.monotonic() - t0) * 1000)})
    if not keep:
        info["result"] = f"kept original ({why})"
        return text, info
    info["result"] = "fixed"
    return new, info
