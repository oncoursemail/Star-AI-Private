"""The agent loop: write -> real checks -> read the real errors -> fix -> repeat, bounded by rounds and time.

    agent = Agent(call, checks, max_rounds=4, budget_s=240)
    out = agent.run(messages)      # {"answer", "content" (answer + verified line), "verified", "ok", "rounds", "trace"}

`call(messages, temperature, max_tokens) -> (text, finish_reason)` is a model call (the router's `litha`).
Repairs: rank-3 verifier problems first go through the verifier's own measured block fix (?fix=1, one round); run/load
failures, rule hits, incomplete answers, or a block fix that did not help get a whole-answer revision with the real
error output. A new answer is kept only when its check score is strictly better (never worse than the first try).
"""
from __future__ import annotations

import re
import time

from ..verify import core
from .checks import Checks, clean
from .route import last_user

TYPE_DECL = re.compile(r"^[ \t]*(?:(?:public|private|protected|abstract|final|static|sealed|export|default)\s+)*"
                       r"(?:class|interface|enum|record)\s+[A-Za-z_]\w*", re.M)

AGENT_NOTE = ("\n\n(Build mode: reply with complete, working code - every file in full, nothing left out, no questions "
              "back. The code will be compiled, run and loaded for real.)")
REVISE_SYSTEM = ("You are Litha, a game and code builder. Your previous answer was checked for real (compiler, sandbox "
                 "runs, real game servers). Fix it so every reported problem goes away. Keep what already works and the "
                 "same files and names. Use only APIs that really exist in the version asked for. Reply with the "
                 "complete corrected answer: a short line on what you changed, then every file in full in fenced code "
                 "blocks (label each with its file name). Never write 'rest stays the same'.")


def _with_note(messages: list[dict]) -> list[dict]:
    out = [dict(m) for m in messages]
    for m in reversed(out):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            m["content"] = m["content"] + AGENT_NOTE
            break
    return out


def feedback(problems: list[dict], limit: int = 8) -> str:
    lines = ["The real checks of your answer failed:"]
    for p in sorted(problems, key=lambda p: -p["rank"])[:limit]:
        lines.append(f"- [{p['stage']}] {p['message']}")
    if len(problems) > limit:
        lines.append(f"- ... and {len(problems) - limit} more")
    if any(p["stage"] == "run" for p in problems):
        lines.append("First trace the failing example through your code step by step (silently) to find the line that "
                     "goes wrong; the same code again will fail again.")
    lines.append("Fix these problems and reply with the complete corrected answer (every file in full).")
    return "\n".join(lines)


def code_size(text: str) -> tuple[int, int]:
    """(characters of code, Java/C#/TS type declarations) over all fenced blocks."""
    blocks = core.extract_blocks(text)
    return (sum(len(b["code"].strip()) for b in blocks),
            sum(len(TYPE_DECL.findall(b["code"])) for b in blocks))


def lost_code(old: str, new: str) -> bool:
    """A repair that throws code away (a Java block replaced by YAML, a file dropped) is not a fix, even when the
    checkers then report fewer problems."""
    (oc, ot), (nc, nt) = code_size(old), code_size(new)
    return nc < 0.6 * oc or nt < ot


def verified_line(ev: dict, rounds: int, seconds: float) -> str:
    tail = f" ({rounds} fix round{'s' if rounds != 1 else ''}, {seconds:.0f} s)" if rounds else f" ({seconds:.0f} s)"
    if clean(ev["score"]):
        if not ev["passed"]:
            return "> not checked: no real checker covers this code" + tail
        return "> verified: " + " + ".join(ev["passed"]) + tail
    worst = sorted(ev["problems"], key=lambda p: -p["rank"])[0]
    first = worst["message"].strip().splitlines()[0][:160]
    return f"> not verified: {worst['stage']} problem left: {first}" + tail


class Agent:
    def __init__(self, call, checks: Checks, max_rounds: int = 4, budget_s: float = 240.0, verifier_fix: bool = True,
                 clock=time.monotonic, progress=None):
        self.call, self.checks = call, checks
        self.max_rounds, self.budget_s, self.verifier_fix = max_rounds, budget_s, verifier_fix
        self.clock, self.progress = clock, progress or (lambda text: None)

    def run(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 3000, build: bool = True) -> dict:
        t0 = self.clock()
        question = last_user(messages)
        trace: list[dict] = []
        self.progress("Writing the code...")
        t1 = self.clock()
        answer, finish = self.call(_with_note(messages), temperature, max_tokens)
        gen_s = self.clock() - t1
        ev = self.checks.evaluate(answer, question, finish, build)
        trace.append({"round": 0, "how": "write", "score": list(ev["score"]), "gen_s": round(gen_s, 1),
                      "s": round(self.clock() - t0, 1), "problems": [p["message"][:200] for p in ev["problems"]]})
        self.progress(_status(0, ev))
        first, best, best_ev = answer, answer, ev
        rounds, stall_block, stall_rev = 0, False, 0
        last_round_s = self.clock() - t0
        for rnd in range(1, self.max_rounds + 1):
            if clean(best_ev["score"]):
                break
            left = self.budget_s - (self.clock() - t0)
            if left < max(20.0, 0.8 * last_round_s):
                trace.append({"round": rnd, "how": "stop", "why": f"time budget ({left:.0f} s left)"})
                break
            rs = self.clock()
            rank3_verifier = [p for p in best_ev["problems"] if p["rank"] == 3 and p["stage"] in ("static", "compile")
                              and not p["message"].startswith("Roblox rule")]
            new, how, fin = None, "", "stop"
            if self.verifier_fix and self.checks.verifier and rank3_verifier and not stall_block:
                self.progress(f"Round {rnd}: repairing {len(rank3_verifier)} checker error(s)...")
                fx = self.checks.verifier.fix(best, question, timeout_s=max(30.0, left))
                if fx and fx.get("answer") and fx["answer"] != best:
                    new, how = fx["answer"], "verifier-fix"
                else:
                    stall_block = True
            unusable = [p for p in best_ev["problems"] if p["rank"] == 4]
            if new is None and (unusable or stall_rev % 2 == 1):
                # cut off / repeating / no code, or a revision that did not help: write it again (a fresh sample) with
                # the reason on the request instead of patching the same draft once more
                why = unusable or sorted(best_ev["problems"], key=lambda p: -p["rank"])
                self.progress(f"Round {rnd}: writing it again ({why[0]['message'][:80]})...")
                msgs = _with_note(messages)
                msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + "\n(Last try failed the real checks: " +
                            "; ".join(p["message"].splitlines()[0][:160] for p in why[:3]) + ")"}
                new, fin = self.call(msgs, min(0.9, temperature + 0.2 + 0.2 * stall_rev), max_tokens)
                how = "rewrite"
            if new is None:
                self.progress(f"Round {rnd}: fixing from the real errors...")
                msgs = [{"role": "system", "content": REVISE_SYSTEM}, {"role": "user", "content": question},
                        {"role": "assistant", "content": best},
                        {"role": "user", "content": feedback(best_ev["problems"])}]
                new, fin = self.call(msgs, min(0.9, temperature + 0.2 * stall_rev), max_tokens)
                how = "revise"
            rounds = rnd
            ev = self.checks.evaluate(new, question, fin, build)
            lost = not best_ev["score"][0] and lost_code(best, new)
            better = ev["score"] < best_ev["score"] and not lost
            trace.append({"round": rnd, "how": how, "score": list(ev["score"]), "kept": better,
                          **({"rejected": "lost code"} if lost else {}),
                          "s": round(self.clock() - t0, 1), "problems": [p["message"][:200] for p in ev["problems"]]})
            self.progress(_status(rnd, ev) + ("" if better else " (kept the earlier version)"))
            if better:
                best, best_ev = new, ev
                stall_rev = 0
                stall_block = False
            elif how == "verifier-fix":
                stall_block = True
            else:
                stall_rev += 1
                if stall_rev >= 3:
                    break
            last_round_s = self.clock() - rs
        seconds = self.clock() - t0
        line = verified_line(best_ev, rounds, seconds)
        return {"answer": best, "first": first, "content": best.rstrip() + "\n\n" + line, "verified": line,
                "ok": clean(best_ev["score"]) and bool(best_ev["passed"]), "rounds": rounds,
                "score": list(best_ev["score"]), "passed": best_ev["passed"],
                "problems": [p["message"][:300] for p in best_ev["problems"]], "trace": trace,
                "seconds": round(seconds, 1)}


def _status(rnd: int, ev: dict) -> str:
    if clean(ev["score"]):
        return f"Round {rnd}: all checks pass" + (": " + "; ".join(ev["passed"]) if ev["passed"] else "")
    kinds = sorted({p["stage"] for p in ev["problems"]})
    return f"Round {rnd}: {len(ev['problems'])} problem(s) ({', '.join(kinds)})"
