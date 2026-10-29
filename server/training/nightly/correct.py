"""Self-correction data: a failed first answer is rewritten by the SAME deployed model, told exactly what our own
checks found (verifier messages + suggestions, the rule's fix instruction + evidence, the base-model judge's reason,
the docs passage when the prompt came from the docs, "cut off" when it ran out of tokens). The rewrite is checked
again by every check; only a rewrite that passes ALL of them becomes training data:
  SFT   : system + question -> corrected answer (the model learns to write the fixed answer first time)
  pairs : chosen = corrected answer, rejected = the failed first answer (preference data)
Provenance: the rewrite is the model's own text; the feedback comes from our verifier, rules and our own judge
model; this module's instruction line is input only and never a training target. No hosted model is involved.
"""
from __future__ import annotations

import re

ASK = ("Please rewrite your WHOLE answer so that every problem below is fixed. Keep the same friendly tone and "
       "format, keep what was already right, keep it about as short, and use only real, current APIs and commands. "
       "Reply with the new answer only; do not mention this request, the checks or that it is a new version.")
OPENER = re.compile(r"^\s*(here('s| is)|sure|of course|okay|ok|great catch|good catch|you('re| are) right|"
                    r"i('ve| have) (fixed|updated|corrected|rewritten))[^\n]*\n+", re.I)
META = re.compile(r"\b(checker|the checks|problems? (below|listed|found)|fixed version|new version|rewritten "
                  r"answer|corrected answer|as requested)\b", re.I)


def feedback_lines(check: dict, finish: str = "", reference: str = "") -> list[str]:
    """Human-readable problems from one full_check() result (only our own tools' findings)."""
    lines: list[str] = []
    if finish == "length":
        lines.append("The answer was too long and got cut off. Make it shorter and complete.")
    v = check.get("verify") or {}
    for d in v.get("details") or []:
        msg = (d.get("message") or f"{d.get('kind')}: {d.get('name')}").strip()
        if d.get("suggestion"):
            msg += f" (use: {d['suggestion']})"
        if d.get("answer_line"):
            msg += f" [line {d['answer_line']}]"
        lines.append(msg)
    if not v.get("details"):
        lines += [f"Invalid: {e}" for e in (v.get("errors") or []) + (v.get("warnings") or [])]
    for h in check.get("rule_hits") or []:
        lines.append(h["message"] + (f" (seen here: {h['evidence']})" if h.get("evidence") else ""))
    if not check.get("rule_hits"):
        lines += [f"Rule broken: {r}" for r in check.get("rules") or []]
    f = check.get("fact") or {}
    for c in f.get("false_claims") or []:
        lines.append("A fact checker says this is false: " + c)
    if f and f.get("answers_question") is False:
        lines.append("A fact checker says the answer does not answer the question.")
    j = check.get("judge") or {}
    if j.get("pass") is False and j.get("reason"):
        lines.append("A reviewer said: " + j["reason"].strip())
    return lines[:10]


def correction_messages(system: str, question: str, answer: str, lines: list[str], reference: str = "") -> list[dict]:
    ref = f"\n\nOfficial documentation (trust it over your answer):\n{reference[:2500]}" if reference else ""
    probs = "\n".join(f"{i}. {x}" for i, x in enumerate(lines, 1))
    return [{"role": "system", "content": system}, {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": f"{ASK}\n\nProblems:\n{probs}{ref}"}]


def clean(text: str) -> str | None:
    """The rewrite without a chatty opener; None when it talks about the correction itself (not a clean answer)."""
    out = OPENER.sub("", (text or "").strip(), count=1).strip()
    if out.lower().startswith("answer:"):
        out = out[7:].strip()
    if not out or META.search(out[:400]):
        return None
    return out


def correct(srv, question: str, row: dict, system: str, reference: str = "", seed: int = 7) -> dict | None:
    """One rewrite of a failed harvest row (needs row['answer'], row['check'], row['finish']). Returns a chat()
    result with the cleaned text, or None when there is nothing to fix or the rewrite is unusable."""
    lines = feedback_lines(row["check"], row.get("finish", ""), reference)
    if not lines:
        return None
    ans = srv.chat(correction_messages(system, question, row["answer"], lines, reference), temperature=0.3,
                   max_tokens=1200, seed=seed)
    text = clean(ans.get("text", ""))
    if text is None or text.strip() == row["answer"].strip():
        return None
    return {**ans, "text": text, "feedback": lines}
