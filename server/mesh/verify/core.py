"""Verify the code blocks of an answer, and the fix loop (failing blocks repaired by the fast tier, re-verified).

    report = Verifier(api, analyzer).verify(text, language=None)
    result = Verifier(...).fix(text, call_model, language=None, rounds=2)

A problem is {kind, severity (error | warning | info), name, message, suggestion, line}. A block is `ok` when it has
no error; it `needs_fix` when it has an error or a warning (deprecated API). Info never triggers a fix.
"""
from __future__ import annotations

import re
import time

from . import csharp, minecraft
from .apidump import ApiIndex
from .luau import LuauChecker

FENCE = re.compile(r"^(?P<ind>[ \t]{0,3})(?P<f>`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n(?P<code>.*?)^(?P=ind)(?P=f)[ \t]*$",
                   re.M | re.S)
OPEN_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n", re.M)
LANGS = {"lua": "luau", "luau": "luau", "rbxlua": "luau", "roblox": "luau",
         "cs": "csharp", "csharp": "csharp", "c#": "csharp", "unity": "csharp",
         "mcfunction": "mcfunction", "minecraft": "minecraft", "mcf": "mcfunction", "mc": "minecraft",
         "json": "json", "java": "java", "kotlin": "java"}
LUAU_HINT = re.compile(r"game:GetService|Instance\.new|\bworkspace\b|\blocal\s+\w+\s*=|:Connect\(|\bend\b")
CS_HINT = re.compile(r"using\s+UnityEngine|:\s*MonoBehaviour|\bvoid\s+Update\s*\(")


def _detect(code: str, info: str) -> str:
    lang = LANGS.get(info.strip().split(" ")[0].lower(), "") if info.strip() else ""
    if lang:
        return lang
    if CS_HINT.search(code):
        return "csharp"
    lines = [ln.strip() for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if lines and all(ln.startswith("/") and ln[1:].split(" ")[0] in minecraft.COMMANDS for ln in lines):
        return "minecraft"
    if LUAU_HINT.search(code):
        return "luau"
    return ""


def extract_blocks(text: str, language: str | None = None) -> list[dict]:
    """Fenced code blocks with their spans. Text without fences is one block only when `language` is given
    ("auto" = detect it)."""
    blocks = []
    for m in FENCE.finditer(text):
        blocks.append({"start": m.start("code"), "end": m.end("code"), "code": m.group("code"),
                       "info": m.group("info").strip(), "line": text.count("\n", 0, m.start("code")) + 1})
    tail = OPEN_FENCE.search(text, blocks[-1]["end"] + 1 if blocks else 0)
    if tail:                                   # a last fence that is never closed runs to the end of the text
        blocks.append({"start": tail.end(), "end": len(text), "code": text[tail.end():],
                       "info": tail.group("info").strip(), "line": text.count("\n", 0, tail.end()) + 1})
    if not blocks and text.strip() and language:     # unfenced text is code only when the caller says so
        lang = LANGS.get(language.lower(), language) if language != "auto" else _detect(text, "")
        blocks.append({"start": 0, "end": len(text), "code": text, "info": lang, "line": 1})
    for b in blocks:
        b["language"] = _detect(b["code"], b["info"]) or (LANGS.get((language or "").lower(), "") if
                                                           len(blocks) == 1 else "")
    return blocks


class Verifier:
    def __init__(self, api: ApiIndex, analyzer: str | None = None):
        self.api = api
        self.luau = LuauChecker(api, analyzer)

    def check_block(self, code: str, lang: str, prose: str = "") -> tuple[list[dict], bool]:
        if lang == "luau":
            return self.luau.check(code), True
        if lang == "csharp":
            return csharp.check_csharp(code), True
        if lang in ("minecraft", "mcfunction"):
            return minecraft.check_commands(code, in_function=lang == "mcfunction"), True
        if lang == "json" and ("pack_format" in code or "pack.mcmeta" in prose):
            return minecraft.check_pack_mcmeta(code), True
        return [], False

    def verify(self, text: str, language: str | None = None) -> dict:
        t0 = time.perf_counter()
        blocks = extract_blocks(text, language)
        out = []
        for k, b in enumerate(blocks):
            problems, checked = self.check_block(b["code"], b["language"], text)
            for p in problems:
                if p.get("line"):
                    p["answer_line"] = b["line"] + p["line"] - 1
            out.append({"index": k, "language": b["language"] or None, "checked": checked, "line": b["line"],
                        "ok": not any(p["severity"] == "error" for p in problems),
                        "needs_fix": any(p["severity"] in ("error", "warning") for p in problems),
                        "problems": problems})
        prose_problems = minecraft.check_datapack_paths(text) if "data/" in text else []
        return {"ok": all(b["ok"] for b in out) and not prose_problems,
                "needs_fix": any(b["needs_fix"] for b in out),
                "blocks": out, "problems": prose_problems,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "dump": {k: self.api.meta.get(k) for k in ("version", "fetched")}}

    def fix(self, text: str, call_model, language: str | None = None, rounds: int = 2) -> dict:
        """Repair the blocks that need it with `call_model(messages) -> str`, re-verify, at most `rounds` times."""
        t0 = time.perf_counter()
        first = report = self.verify(text, language)
        changes, done, model_ms = [], 0, 0.0
        if report["problems"]:                 # prose: renamed datapack folders have one exact replacement
            for p in report["problems"]:
                text = text.replace(p["name"], p["suggestion"])
            changes.append({"round": 0, "block": None, "fixed": [p["message"] for p in report["problems"]]})
            report = self.verify(text, language)
        for rnd in range(1, rounds + 1):
            todo = [b for b in report["blocks"] if b["needs_fix"]]
            if not todo:
                break
            done = rnd
            spans = extract_blocks(text, language)
            edits = []
            for b in todo:
                span = spans[b["index"]]
                t1 = time.perf_counter()
                try:
                    reply = call_model(fix_messages(span["code"], b["language"], b["problems"]))
                except Exception as e:     # model unreachable: keep the answer, report it
                    changes.append({"round": rnd, "block": b["index"], "error": f"fix call failed: {e}"})
                    continue
                finally:
                    model_ms += (time.perf_counter() - t1) * 1000
                new = code_from_reply(reply, span["code"])
                if new and new.strip() != span["code"].strip():
                    edits.append((span, new, b))
            for span, new, b in sorted(edits, key=lambda e: -e[0]["start"]):
                text = text[:span["start"]] + new + text[span["end"]:]
            report = self.verify(text, language)
            for span, new, b in edits:
                after = report["blocks"][b["index"]] if b["index"] < len(report["blocks"]) else None
                changes.append({"round": rnd, "block": b["index"], "fixed": [p["message"] for p in b["problems"]
                                                                             if p["severity"] != "info"],
                                "remaining": [p["message"] for p in (after or {}).get("problems", [])
                                              if p["severity"] != "info"]})
            if not edits:
                break
        return {"answer": text, "ok": report["ok"], "rounds": done, "changes": changes,
                "before": _summary(first), "after": _summary(report), "verify": report,
                "model_ms": round(model_ms), "ms": round((time.perf_counter() - t0) * 1000)}


def _summary(report: dict) -> dict:
    probs = [p for b in report["blocks"] for p in b["problems"]] + report["problems"]
    return {"errors": sum(p["severity"] == "error" for p in probs),
            "warnings": sum(p["severity"] == "warning" for p in probs),
            "blocks_failing": sum(not b["ok"] for b in report["blocks"])}


FIX_SYSTEM = ("You repair code. You get one code block and a list of problems found by a verifier that checks every "
              "API name against the official API list. Fix exactly those problems and keep everything else "
              "unchanged (same structure, names, comments). When a problem gives a suggestion, use it. Never invent "
              "an API: if a call does not exist and there is no suggestion, rewrite that part with APIs you are sure "
              "exist. Reply with only the corrected code in one fenced code block, nothing else.")
FENCE_TAG = {"luau": "lua", "csharp": "csharp", "minecraft": "mcfunction", "mcfunction": "mcfunction"}


def fix_messages(code: str, language: str, problems: list[dict]) -> list[dict]:
    lines = []
    for p in problems:
        if p["severity"] == "info":
            continue
        s = f"- line {p['line']}: {p['message']}" if p.get("line") else f"- {p['message']}"
        if p.get("suggestion"):
            s += f" (use: {p['suggestion']})"
        lines.append(s)
    tag = FENCE_TAG.get(language, language or "")
    return [{"role": "system", "content": FIX_SYSTEM},
            {"role": "user", "content": f"Language: {language}\n\nCode:\n```{tag}\n{code.rstrip()}\n```\n\n"
                                        "Problems:\n" + "\n".join(lines)}]


def code_from_reply(reply: str, old: str) -> str:
    reply = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).strip()
    m = FENCE.search(reply + ("\n" if not reply.endswith("\n") else ""))
    code = m.group("code") if m else reply
    if old.endswith("\n") and not code.endswith("\n"):
        code += "\n"
    return code
